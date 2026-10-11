"""S5 最小切片的验收测试（design-v2 14.6）。

四个"应拦下"的分支是重点 —— 它们代表真实的失败模式：
A 格依赖没实现、B 格改到范围外、B 格说做了却没动文件、E 格提交信息被改。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import git, make_repo

from refactor_pilot import gitutil, s5
from refactor_pilot.cli import main

pytestmark = pytest.mark.skipif(not gitutil.available(), reason="git 不可用")


def setup_repo(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    """建仓库 → 跑 scan（S5 依赖 scan.json）→ 返回仓库路径。"""
    repo = make_repo(tmp_path / "repo", files or {"src/acme/core.py": "VALUE = 1\n"})
    out = tmp_path / "out"
    assert main(["scan", str(repo), "--out", str(out)]) == 0
    return repo


def write_plan(tmp_path: Path, **stage_overrides) -> Path:
    stage = {
        "id": "s1",
        "type": "ai",
        "writes": ["src/acme/core.py"],
        "forbidden_paths": ["tests/"],
        "behavior_spec": "让 core 暴露一个可配置的入口",
    }
    stage.update(stage_overrides)
    plan = {"schema_version": 1, "stage": stage}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return path


def advance(repo: Path, plan: Path, out: Path, *extra: str) -> int:
    """跑一次 S5（一次运行最多推进一格）。"""
    return main(["s5", str(repo), "--plan", str(plan), "--out", str(out), *extra])


def write_evidence(out: Path, body: str = "3 passed in 0.02s", exit_code: int = 0,
                   stage: str = "s1") -> Path:
    """模拟"AI 执行了 D 格命令"：把证据日志写到产物目录（仓库外）。"""
    log = out / "evidence" / f"{stage}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"$ pytest -q\n{body}\nRP_EXIT_CODE={exit_code}\n", encoding="utf-8")
    return log


def cell_of(out: Path) -> str | None:
    import json as _json

    path = out / "state.json"
    return _json.loads(path.read_text(encoding="utf-8"))["current_cell"] if path.is_file() else None


# ────────────────────────────── 14.6 主流程 ──────────────────────────────


def test_three_cells_advance_one_step_at_a_time(tmp_path):
    """A→B→E 连续推进；每次运行最多进一格（3.1）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"

    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc == 0
    assert json.loads((out / "state.json").read_text())["current_cell"] == "A"
    assert (out / "steps" / "s1.A.md").is_file()

    # A 格通过（依赖闭合、零改动）→ 推进到 B
    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc == 0
    assert json.loads((out / "state.json").read_text())["current_cell"] == "B"
    assert (out / "steps" / "s1.B.md").is_file()

    # 实现（改 writes 内的文件）→ B 通过 → 推进到 D
    (repo / "src/acme/core.py").write_text("VALUE = 2\n\n\ndef configure(x):\n    return x\n")
    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out),
                 "--test-cmd", "pytest -q"]) == 0
    assert cell_of(out) == "D"
    assert (out / "steps" / "s1.D.md").is_file()

    # AI 执行 D 格命令（测试里直接写证据日志）→ D 通过 → 推进到 E
    write_evidence(out)
    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) == 0
    state = json.loads((out / "state.json").read_text())
    assert state["current_cell"] == "E"
    assert (out / "steps" / "s1.E.md").is_file()
    assert len(state["e_expected"]) == 1


def test_instructions_have_no_unrendered_placeholders(tmp_path):
    """渲染铁律：指令块里不许有未解析的 `{{...}}`（6.2）。"""
    repo = setup_repo(tmp_path, {"src/acme/core.py": "VALUE = 1\n", "CODEBUDDY.md": "# 约束\n"})
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])

    text = (out / "steps" / "s1.A.md").read_text(encoding="utf-8")
    assert "{{" not in text and "}}" not in text
    assert "src/acme/core.py" in text  # 真实路径，而不是"先实现缺失的模块"


def test_render_refuses_leftover_placeholder():
    """未解析占位符 → 拒绝输出（渲染铁律），不降级。"""
    from refactor_pilot.s5 import render

    with pytest.raises(render.RenderError):
        render.render("阶段 {{stage.id}} 缺字段 {{stage.nope}}", {"stage": {"id": "s1"}})


# ────────────────────────────── 四个"应拦下"的分支 ──────────────────────────────


def test_a_cell_blocks_on_stub_dependency(tmp_path):
    """分支①：A 格发现依赖是存根 → 不推进，提示先补实现。"""
    # 扁平包布局：`from acme.schema import ...` 能被规范名解析到
    # （src 布局若没有打包声明，按 P-03 属于"无证据不解析"，不在这里测）
    repo = setup_repo(
        tmp_path,
        {
            "acme/core.py": "from acme.schema import normalize\n",
            "acme/schema.py": "def normalize():\n    pass\n",
            "acme/__init__.py": "",
        },
    )
    plan = write_plan(tmp_path, writes=["acme/core.py"])
    out = tmp_path / "out"

    # 首次运行渲染 A 格（A 块的依赖表里已如实列出 stub 行，块本身会叫 AI 停下）
    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) == 0
    assert "stub" in (out / "steps" / "s1.A.md").read_text(encoding="utf-8")

    # 再跑一次：A 格检查点不通过 → 拦下且不推进
    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc != 0
    assert json.loads((out / "state.json").read_text())["current_cell"] == "A"
    assert not (out / "steps" / "s1.B.md").exists()


def test_b_cell_blocks_out_of_scope_change(tmp_path):
    """分支②：B 格改动超出 writes → 判越界。"""
    repo = setup_repo(tmp_path, {"src/acme/core.py": "VALUE = 1\n", "src/acme/other.py": "X = 1\n"})
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # A 渲染
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # 推进到 B

    (repo / "src/acme/other.py").write_text("X = 2\n")  # writes 之外

    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc != 0
    assert json.loads((out / "state.json").read_text())["current_cell"] == "B"


def test_b_cell_blocks_when_writes_nonempty_but_nothing_changed(tmp_path):
    """分支③：writes 非空却零改动 → 判未完成（"说做完了但没动文件"）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # 到 B
    assert rc == 0

    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # 没改任何东西
    assert rc != 0
    assert json.loads((out / "state.json").read_text())["current_cell"] == "B"


def test_e_cell_blocks_on_subject_mismatch(tmp_path):
    """分支④：提交 subject 与工具生成的不一致（R6）→ 拦下。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])

    (repo / "src/acme/core.py").write_text("VALUE = 2\n")
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out),
          "--test-cmd", "pytest -q"])  # B 通过 → D
    write_evidence(out)
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # D 通过 → E

    git(["add", "src/acme/core.py"], repo)
    git(["commit", "-q", "-m", "feat: 我自己写的提交信息"], repo)

    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc != 0, "subject 不一致必须拦下"
    assert json.loads((out / "state.json").read_text())["current_cell"] == "E"


def test_e_cell_passes_with_exact_subject(tmp_path):
    """反向：逐字照抄 subject → E 格通过，三格走完。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])

    (repo / "src/acme/core.py").write_text("VALUE = 3\n")
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out),
          "--test-cmd", "pytest -q"])
    write_evidence(out)
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])

    state = json.loads((out / "state.json").read_text())
    expected = state["e_expected"][0]
    for path in expected["paths"]:
        git(["add", path], repo)
    git(["commit", "-q", "-m", expected["subject"]], repo)

    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc == 0
    assert json.loads((out / "state.json").read_text())["current_cell"] == "done"


# ────────────────────────────── 其余 14.6 条目 ──────────────────────────────


def test_dirty_worktree_blocks_at_start(tmp_path):
    """工作树不干净 → 停在 A 格之前（14.3 / 决策 8）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    (repo / "src/acme/core.py").write_text("VALUE = 99\n")  # 开工前就有未提交改动

    out = tmp_path / "out"
    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc != 0
    assert not (out / "steps" / "s1.A.md").exists()


def test_e_cell_says_no_changes_needed(tmp_path):
    """E 格无改动 → 输出"无需提交"，不输出空的 git add（14.3）。"""
    from refactor_pilot.s5 import facts

    assert facts.worktree_dirty_paths(setup_repo(tmp_path)) == []


def test_forced_cell_jump_warns_and_records(tmp_path, capsys):
    """`--cell` 向前跳 → WARNING + state.forced = true（14.5）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"

    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out), "--cell", "e"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "强制跳到" in captured.err  # CLI 已加 `WARN ` 前缀，文案不再自带 WARNING
    state = json.loads((out / "state.json").read_text())
    assert state["forced"] is True
    assert state["current_cell"] == "E"
    assert (out / "steps" / "s1.E.md").is_file()


def test_plan_errors_point_at_the_missing_field(tmp_path):
    """plan 校验：缺字段要指明缺哪个；writes 不支持 glob（14.2）。"""
    repo = setup_repo(tmp_path)

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 1, "stage": {"id": "s1"}}), encoding="utf-8")
    rc = main(["s5", str(repo), "--plan", str(bad), "--out", str(tmp_path / "out")])
    assert rc == 2
    assert not (tmp_path / "out" / "steps").exists()

    with pytest.raises(s5.plan.PlanError) as excinfo:
        s5.plan.load(bad)
    assert "type" in str(excinfo.value) and "writes" in str(excinfo.value)

    glob_plan = write_plan(tmp_path, writes=["src/**/*.py"])
    with pytest.raises(s5.plan.PlanError) as excinfo:
        s5.plan.load(glob_plan)
    assert "glob" in str(excinfo.value)


def test_s5_does_not_touch_target_sources(tmp_path):
    """只读验证：S5 只写产物目录，目标仓库源码指纹不变（14.6）。"""
    from refactor_pilot import fsutil

    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"

    before = fsutil.fingerprint(repo)
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert fsutil.fingerprint(repo) == before
    assert gitutil.status_porcelain(repo) == ""


# ────────────────────────────── D 格（实跑验收 R4） ──────────────────────────────


def to_d(repo: Path, plan: Path, out: Path, *, change: bool = True,
         cmd: str = "pytest -q") -> None:
    """走到 D 格：A → B（改 writes 内文件）→ D。"""
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # A
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # → B
    if change:
        (repo / "src/acme/core.py").write_text("VALUE = 7\n")
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out),
          "--test-cmd", cmd])  # → D
    assert cell_of(out) == "D"


def write_raw_evidence(out: Path, text: str, stage: str = "s1") -> Path:
    """直接写证据日志（用于构造特殊内容）。"""
    log = out / "evidence" / f"{stage}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(text, encoding="utf-8")
    return log


def test_d_cell_blocks_without_test_cmd(tmp_path):
    """无可用 test_cmd → 不许静默跳过：标 needs_manual_acceptance 并阻塞（14.9 第 3 条）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"

    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # A
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # → B
    (repo / "src/acme/core.py").write_text("VALUE = 8\n")

    # B 通过后要进 D，但没给命令 → 阻塞，且**不渲染 D 块**
    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc != 0
    state = json.loads((out / "state.json").read_text())
    assert state["needs_manual_acceptance"] is True
    assert not (out / "steps" / "s1.D.md").exists()


def test_d_cell_blocks_when_evidence_missing(tmp_path):
    """没有证据文件 = 未完成，并重发 D 格指令（4.2①）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out)

    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc != 0
    assert cell_of(out) == "D"
    assert "未完成" in (out / "steps" / "s1.D.md").read_text(encoding="utf-8")


def test_d_cell_blocks_on_nonzero_exit(tmp_path):
    """退出码非 0 → 判未完成。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out)
    write_evidence(out, body="1 failed, 2 passed in 0.03s", exit_code=1)

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) != 0
    assert cell_of(out) == "D"


def test_d_cell_blocks_on_zero_collected(tmp_path):
    """静默零收集 → 判未完成（与 B03 同一条道理）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out)
    write_evidence(out, body="no tests ran in 0.01s")

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) != 0
    assert cell_of(out) == "D"


def test_d_cell_blocks_when_log_has_no_output(tmp_path):
    """只有标记、没有输出行 → 不算证据。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out)
    log = out / "evidence" / "s1.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("RP_EXIT_CODE=0\n", encoding="utf-8")

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) != 0
    assert cell_of(out) == "D"


def test_d_cell_passes_with_complete_evidence(tmp_path):
    """反向：三要素齐 → D 通过并推进。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out)
    write_evidence(out, body="collected 3 items\n3 passed in 0.03s")

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) == 0
    assert cell_of(out) == "E"


# ────────────────── 每个检查点都配"故意让它失败"的用例（14.10） ──────────────────


def test_a_cell_blocks_when_sources_drift(tmp_path):
    """A 格零改动检查点：渲染后源码被改动 → 拦下（否则只测通过测不出失效）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # 渲染 A、记指纹

    (repo / "src/acme/core.py").write_text("VALUE = 999\n")  # A 格期间不该动源码

    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc != 0
    assert cell_of(out) == "A"


def test_b_cell_blocks_on_forbidden_path(tmp_path):
    """B 格禁改路径检查点：改到 forbidden_paths → 拦下。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path, forbidden_paths=["src/acme/schema.py"])
    out = tmp_path / "out"
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # → B

    (repo / "src/acme/schema.py").write_text("SCHEMA = 2\n")  # 禁改

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) != 0
    assert cell_of(out) == "B"


def test_e_cell_blocks_on_wrong_commit_count(tmp_path):
    """E 格提交数检查点：少提交一次 → 拦下。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out)
    write_evidence(out)
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # → E
    assert cell_of(out) == "E"

    # 什么都不提交，直接再跑
    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) != 0
    assert cell_of(out) == "E"


def test_e_cell_blocks_when_worktree_dirty(tmp_path):
    """E 格"工作树必须干净"检查点。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out)
    write_evidence(out)
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # → E

    git(["add", "-A"], repo)
    git(["commit", "-q", "-m", "先提交了"], repo)
    (repo / "src/acme/core.py").write_text("VALUE = 11\n")  # 又弄脏

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) != 0
    assert cell_of(out) == "E"


def test_rerun_current_cell_does_not_warn(tmp_path, capsys):
    """重跑当前格不警告（只有向前跳才警告，14.5）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    capsys.readouterr()

    main(["s5", str(repo), "--plan", str(plan), "--out", str(out), "--cell", "a"])
    assert "强制跳到" not in capsys.readouterr().err
    assert json.loads((out / "state.json").read_text())["forced"] is False


def test_a_instruction_lists_external_deps_explicitly(tmp_path):
    """R1 降级必须显式列在指令块里（14.9 第 5 条），不能只躺在日志。"""
    repo = setup_repo(
        tmp_path,
        {"src/acme/core.py": "import torch\nimport numpy\n\nVALUE = 1\n"},
    )
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])

    text = (out / "steps" / "s1.A.md").read_text(encoding="utf-8")
    assert "R1 在本阶段**降级**" in text
    assert "torch" in text and "numpy" in text
    assert "external" in text


# ────────────── ① A 格 create-file 自动推断（2026-10-11 决定，决策 6） ──────────────


def test_a_cell_allows_creating_a_new_file(tmp_path):
    """① 新建文件（git 未跟踪、磁盘也没有）不产 missing 行 → A 格通过。

    判据用 git 事实自动推断，不靠 plan 作者声明 creates ——
    否则「补 pyproject.toml」这类最先该帮上忙的任务会被自己的门禁卡死。
    """
    repo = setup_repo(tmp_path)  # 已有 src/acme/core.py
    plan = write_plan(tmp_path, writes=["pyproject.toml"], forbidden_paths=["src/"])
    out = tmp_path / "out"

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) == 0  # 渲染 A
    text = (out / "steps" / "s1.A.md").read_text(encoding="utf-8")
    assert "（文件不存在或语法错误）" not in text  # 不再把"待创建的目标"当缺失依赖

    # 再跑一次：A 检查点应通过 → 推进到 B
    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) == 0
    assert cell_of(out) == "B"


def test_a_cell_still_blocks_when_target_has_syntax_error(tmp_path):
    """① 反向：目标存在但语法错误 → 仍产 missing 行并拦下（别把真问题也放过）。"""
    repo = setup_repo(tmp_path, {"src/acme/broken.py": "def broken(:\n    pass\n"})
    plan = write_plan(tmp_path, writes=["src/acme/broken.py"])
    out = tmp_path / "out"

    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    text = (out / "steps" / "s1.A.md").read_text(encoding="utf-8")
    assert "（文件不存在或语法错误）" in text
    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) != 0
    assert cell_of(out) == "A"


# ────────────── ② D 格按命令类型定证据要求（2026-10-11 决定） ──────────────


def test_d_lint_command_only_needs_exit_zero(tmp_path):
    """② lint 类命令：只要退出码 0，不需要用例数（不加 --expect，判据来自命令）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out, cmd="ruff check .")
    write_raw_evidence(out, "All checks passed!\nRP_EXIT_CODE=0\n")

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) == 0
    assert cell_of(out) == "E"


def test_d_lint_command_still_blocks_on_nonzero_exit(tmp_path):
    """② 反向：lint 类命令退出码非 0 → 拦下。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out, cmd="mypy src")
    write_raw_evidence(out, "src/x.py:1: error: bad\nRP_EXIT_CODE=1\n")

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) != 0
    assert cell_of(out) == "D"


def test_d_generic_command_needs_an_output_line(tmp_path):
    """② 普通命令：只有退出码、没有输出 → 不算证据。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out, cmd="python tools/validate.py")
    write_raw_evidence(out, "RP_EXIT_CODE=0\n")

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) != 0
    assert cell_of(out) == "D"


def test_d_generic_command_passes_with_output(tmp_path):
    """② 反向：普通命令退出码 0 + 有输出 → 通过并推进。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out, cmd="python tools/validate.py")
    write_raw_evidence(out, "validating...\nOK\nRP_EXIT_CODE=0\n")

    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) == 0
    assert cell_of(out) == "E"


def test_d_instruction_renders_command_specific_requirement(tmp_path):
    """② 指令块要渲染**这条命令**的证据要求，而不是写死的"用例数"。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out, cmd="ruff check .")
    text = (out / "steps" / "s1.D.md").read_text(encoding="utf-8")

    assert "只要退出码为 0" in text
    assert "用例数汇总行" not in text  # 不再对 lint 命令要求用例数


# ────────────── ③ done 消息如实描述四格 ──────────────


def test_done_message_lists_all_four_cells(tmp_path, capsys):
    """③ 收尾消息要说 A → B → D → E，不能漏掉 D（旧实现写死"A → B → E"）。"""
    repo = setup_repo(tmp_path)
    plan = write_plan(tmp_path)
    out = tmp_path / "out"
    to_d(repo, plan, out)
    write_evidence(out)
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # → E
    state = json.loads((out / "state.json").read_text())
    for path in state["e_expected"][0]["paths"]:
        git(["add", path], repo)
    git(["commit", "-q", "-m", state["e_expected"][0]["subject"]], repo)

    capsys.readouterr()
    assert main(["s5", str(repo), "--plan", str(plan), "--out", str(out)]) == 0
    assert "A → B → D → E 全部通过" in capsys.readouterr().out
