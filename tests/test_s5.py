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


def run_s5(repo: Path, plan: Path, tmp_path: Path, *extra: str) -> tuple[int, str]:
    out = tmp_path / "out"
    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out), *extra])
    return rc, out.as_posix()


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

    # 实现（改 writes 内的文件）
    (repo / "src/acme/core.py").write_text("VALUE = 2\n\n\ndef configure(x):\n    return x\n")

    rc = main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])
    assert rc == 0
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
    main(["s5", str(repo), "--plan", str(plan), "--out", str(out)])  # 到 E

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
    assert "WARNING" in captured.err
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
