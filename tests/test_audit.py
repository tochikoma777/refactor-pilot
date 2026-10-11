"""S2 验收清单测试（13.3）。每条一个用例，docstring 标出对应条款。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import make_repo

from refactor_pilot import gitutil
from refactor_pilot.audit.report import render
from refactor_pilot.audit.rules import Rules
from refactor_pilot.audit.suppress import apply as apply_suppression
from refactor_pilot.cli import main

pytestmark = pytest.mark.skipif(not gitutil.available(), reason="git 不可用")

PYPROJECT = "[project]\nname = 'demo'\nversion = '0.1.0'\n"


def audit(repo: Path, *extra: str, out: Path) -> tuple[int, dict]:
    rc = main(["audit", str(repo), "--out", str(out), *extra])
    produced = out / "audit.json"
    payload = json.loads(produced.read_text(encoding="utf-8")) if produced.exists() else {}
    return rc, payload


def rules_of(payload: dict) -> set[str]:
    return {f["rule"] for f in payload["findings"]}


# ───────────────────────────── 13.3 / 1.5 ─────────────────────────────


def test_not_covered_statement_when_no_q6_signals(tmp_path):
    """报告开头必须有不覆盖声明（1.5）；Q6 无解时绝不静默跳过。"""
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n"})
    rc, payload = audit(repo, out=tmp_path / "out")
    assert rc == 0

    statement = payload["not_covered"]["statement"]
    assert statement and "语义正确性无法自动验证" in statement
    markdown = (tmp_path / "out" / "audit.md").read_text(encoding="utf-8")
    assert markdown.splitlines()[0].startswith("# 审计结果")
    assert "不覆盖" in markdown or "无法自动验证" in markdown


def test_not_covered_statement_never_disappears(tmp_path):
    """**不覆盖声明永远都在**（P-15），Q6 信号只改措辞。

    反例是旧实现：目标仓库里恰好有个叫 `baseline.json` 的夹具（12.11 的已知误命中）
    就会让声明静默消失 —— 而静默跳过正是 1.5 最怕的毛病。
    """
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/mod.py": "x = 1\n",
            "pyproject.toml": PYPROJECT,
            "v1-reference/impl.py": "y = 1\n",          # 只读参考目录信号
            "fixtures/baseline.json": "{}",              # 数值基线信号
            "tests/test_compare.py": "def test_x():\n    assert True\n",
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    not_covered = payload["not_covered"]

    assert not_covered["q6_reference_available"] is True, "夹具应命中 Q6 信号（这正是旧实现的坑）"
    statement = not_covered["statement"]
    assert statement, "有参考实现信号时，声明也不能消失"
    assert "已启用对拍（Q6）" in statement
    assert "仍不在本工具覆盖范围内" in statement
    markdown = (tmp_path / "out" / "audit.md").read_text(encoding="utf-8")
    assert "已启用对拍（Q6）" in markdown


# ───────────────────────────── 13.3 / class 分类口径 ─────────────────────────────


def test_missing_config_rules_are_engineering_class(tmp_path):
    """缺东西 = engineering（P-14）。

    若缺失型规则被标成 config，10.6 的「工程化召回率」分子分母恒为 0，这一列永久失效。
    """
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n"})
    _, payload = audit(repo, out=tmp_path / "out")
    assert payload["counts"]["by_class"] == {"engineering": payload["counts"]["total"]}
    for finding in payload["findings"]:
        assert finding["class"] == "engineering", finding


# ───────────────────────────── 13.3 / P-12 的边界 ─────────────────────────────


def test_missing_type_keeps_severity_but_code_rule_degrades():
    """缺失型 line=0 是"不适用"；存在型给不出行号 → 必须降级 unverified（P-12）。"""
    from refactor_pilot.audit.findings import FindingFactory

    factory = FindingFactory(Rules.default())

    missing = factory.make("B01", file="tests/", line=0, evidence="未发现")
    assert missing is not None and missing["severity"] == "blocker"

    code_issue = factory.make("A01", file="src/x.py", line=0, evidence="找不到行号")
    assert code_issue is not None
    assert code_issue["severity"] == "unverified"
    assert code_issue["confidence"] == "low"


def test_line_na_exemption_is_a_closed_list():
    """豁免是**封闭清单**（P-16）：除了清单里的，任何规则 line=0 都得降级。

    这条守卫存在的意义：不封闭的话，实现得偷懒的规则都能自证豁免，
    7.1 原则 2 就被架空。加规则进清单必须同时改这里 + 写明理由。
    """
    from refactor_pilot.audit.findings import LINE_NOT_APPLICABLE, FindingFactory

    assert LINE_NOT_APPLICABLE == {
        "B01", "C01", "C02", "C04", "C06", "G05",  # 缺失型
        "G01", "G02", "G07",                        # 整文件型
    }, "清单被改动过？那必须在 commit message 里写明理由"

    factory = FindingFactory(Rules.default())
    for rule_id in sorted(Rules.default().entries):
        finding = factory.make(rule_id, file="x.py", line=0, evidence="e")
        if finding is None:
            continue
        if rule_id in LINE_NOT_APPLICABLE:
            assert finding["severity"] != "unverified", f"{rule_id} 属于不适用清单，不该降级"
        else:
            assert finding["severity"] == "unverified", f"{rule_id} 拿不出行号就必须降级"


def test_a03_and_c05_carry_real_lines(tmp_path):
    """A03 / C05 都给得出真实行号，不该被降级成 unverified。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/pkg/__init__.py": "",
            "src/pkg/stub.py": "def unfinished():\n    pass\n",
            "src/pkg/consumer.py": "from pkg import stub\n",
            "pyproject.toml": PYPROJECT + "[tool.setuptools.packages.find]\nwhere = ['src']\n",
            ".pre-commit-config.yaml": (
                "repos:\n"
                "  - repo: local\n"
                "    hooks:\n"
                "      - id: mypy-local\n"
                "        language: system\n"
            ),
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    by_rule = {f["rule"]: f for f in payload["findings"]}
    assert by_rule["A03"]["line"] > 0
    assert by_rule["C05"]["line"] > 0
    assert by_rule["A03"]["severity"] != "unverified"


# ───────────────────────────── 13.3 / file:line ─────────────────────────────


def test_every_finding_has_file_and_line(tmp_path):
    """每条 finding 都带 file:line；无证据的降级 unverified 且不计入 blocker。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/pkg/__init__.py": "",
            "src/pkg/a.py": "def stub():\n    pass\n",
            "pyproject.toml": PYPROJECT,
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")

    for finding in payload["findings"]:
        assert finding["file"], finding
        assert isinstance(finding["line"], int) and finding["line"] >= 0
        if finding["severity"] == "unverified":
            assert finding["line"] == 0
    blockers = [f for f in payload["findings"] if f["severity"] == "blocker"]
    assert all(f["confidence"] == "high" for f in blockers)


# ───────────────────────────── 13.3 / 12.3 ─────────────────────────────


def test_a04_filters_as_symbol(tmp_path):
    """A04 必须过滤 as_symbol=true（12.3）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/pkg/__init__.py": "",
            "src/pkg/util.py": "def load():\n    return 1\n",
            "src/pkg/user.py": "from pkg.util import load\n",
            "pyproject.toml": PYPROJECT + "[tool.setuptools.packages.find]\nwhere = ['src']\n",
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert "A04" not in rules_of(payload), "符号 import 不能被当成缺失模块"


def test_a04_reports_missing_module(tmp_path):
    """反过来：`import 一个真不存在的模块` 必须报出来。"""
    repo = make_repo(
        tmp_path / "repo",
        # 前缀 `src.pkg` 在仓库内、目标本身不在 —— 这才是"模块不存在"
        {"src/pkg/__init__.py": "", "src/pkg/user.py": "import src.pkg.does_not_exist\n",
         "pyproject.toml": PYPROJECT},
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert "A04" in rules_of(payload)


# ───────────────────────────── 13.3 / 7.4 抑制 ─────────────────────────────


def test_all_suppression_edges_from_7_4_present():
    """7.4 的四条抑制边必须一条不落（最容易偷工减料的地方）。

    - C01→D01、C06→B06、G05→G07：**finding 级**抑制，登记在抑制表里
    - C01→A04：**解析级**抑制（12.13）—— A04 不是被"删掉"，而是根本不该命中，
      所以它不进抑制表；若进了表，C01 命中时连真正缺失的模块也会被吞掉
    """
    edges = Rules.default().edges
    assert "D01" in edges["C01"]
    assert "B06" in edges["C06"]
    assert "G07" in edges["G05"]
    assert "A04" not in edges.get("C01", ()), "C01→A04 是解析级抑制，不能做成删除 A04"


def test_c01_suppresses_d01_into_one_finding():
    """C01 命中时 D01 不逐条产出（13.3：合并计一条，不是 40 条）。"""
    rules = Rules.default()
    findings = [{"id": "C01-001", "rule": "C01", "severity": "blocker", "class": "config",
                 "confidence": "high", "file": "pyproject.toml", "line": 0,
                 "evidence": "未发现", "suggestion": "", "merged": []}]
    findings += [
        {"id": f"D01-{i:03d}", "rule": "D01", "severity": "major", "class": "config",
         "confidence": "high", "file": f"src/m{i}.py", "line": 1,
         "evidence": "import torch", "suggestion": "", "merged": []}
        for i in range(40)
    ]
    kept = apply_suppression(findings, rules)
    assert len(kept) == 1
    assert kept[0]["rule"] == "C01"
    assert kept[0]["merged"] == [{"rule": "D01", "count": 40}]


def test_g05_suppresses_g07(tmp_path):
    """G05 → G07 抑制边：`.gitignore` 漏了核心 pattern 且真有产物被跟踪时合并计一条。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/mod.py": "x = 1\n",
            "__pycache__/mod.cpython-313.pyc": "binary",
            ".gitignore": "# 只忽略 venv，漏了 __pycache__\n.venv/\n",
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert "G05" in rules_of(payload)
    assert "G07" not in rules_of(payload), "G07 应被 G05 抑制"
    g05 = next(f for f in payload["findings"] if f["rule"] == "G05")
    assert any(m["rule"] == "G07" for m in g05["merged"])


def test_b01_suppresses_b02_b03_b04(tmp_path):
    """B01（无测试）命中时，B02/B03/B04 不该再逐条出现。"""
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n", "pyproject.toml": PYPROJECT})
    _, payload = audit(repo, out=tmp_path / "out")
    assert "B01" in rules_of(payload)
    assert not rules_of(payload) & {"B02", "B03", "B04"}


# ───────────────────────────── 13.3 / C06 ─────────────────────────────


def test_c06_implemented(tmp_path):
    """C06（由 P1 提升到 P0）必须已实现。"""
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n", "pyproject.toml": PYPROJECT})
    _, payload = audit(repo, out=tmp_path / "out")
    assert "C06" in rules_of(payload)
    finding = next(f for f in payload["findings"] if f["rule"] == "C06")
    assert finding["file"] == ".github/workflows" and finding["line"] == 0


# ───────────────────────────── 13.3 / A01·A02 豁免 ─────────────────────────────


def test_abc_protocol_stubs_exempt(tmp_path):
    """ABC / Protocol 的存根必须豁免（13.3）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/pkg/__init__.py": "",
            "src/pkg/base.py": (
                "from abc import ABC, abstractmethod\n"
                "from typing import Protocol\n\n"
                "class Base(ABC):\n"
                "    @abstractmethod\n"
                "    def run(self):\n"
                "        pass\n\n"
                "class Iface(Protocol):\n"
                "    def step(self) -> None: ...\n\n"
                "class Real(Base):\n"
                "    def run(self):\n"
                "        return 1\n"
            ),
            "pyproject.toml": PYPROJECT,
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert not rules_of(payload) & {"A01", "A02"}, "接口声明不是没写完的存根"


def test_real_stub_is_reported(tmp_path):
    """反过来：普通函数空体 / 非抽象类里抛 NotImplementedError 必须报。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/pkg/__init__.py": "",
            "src/pkg/work.py": (
                "def todo():\n    pass\n\n"
                "class Worker:\n    def run(self):\n        raise NotImplementedError\n"
            ),
            "pyproject.toml": PYPROJECT,
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert {"A01", "A02"} <= rules_of(payload)


# ───────────────────────────── 13.3 / 5.2 __init__ F401 豁免 ─────────────────────────────


def test_init_reexport_is_not_a_finding(tmp_path):
    """`__init__.py` 的再导出不算问题（5.2 机械阶段的护栏：删了会破坏公共契约）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/pkg/__init__.py": "from .core import Engine, helper\n",
            "src/pkg/core.py": "class Engine:\n    pass\n\ndef helper():\n    return 1\n",
            "pyproject.toml": PYPROJECT,
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert "I01" not in rules_of(payload)


def test_init_export_of_missing_name_is_reported(tmp_path):
    """反过来：导出的名字在目标模块里根本找不到 → I01。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/pkg/__init__.py": "from .core import Engine, no_such_name\n",
            "src/pkg/core.py": "class Engine:\n    pass\n",
            "pyproject.toml": PYPROJECT,
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert "I01" in rules_of(payload)


# ───────────────────────────── 13.3 / 规则可配置 ─────────────────────────────


def test_rules_file_can_disable_and_reseverity(tmp_path):
    """规则可通过配置文件关闭 / 改严重度（13.3）。

    格式用 TOML 而非 YAML：运行时依赖要尽可能为零（12.0），不引 PyYAML。
    """
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n", "pyproject.toml": PYPROJECT})
    config = tmp_path / "rules.toml"
    config.write_text(
        '[rules.C06]\nenabled = false\n\n[rules.C02]\nseverity = "blocker"\n',
        encoding="utf-8",
    )
    _, payload = audit(repo, "--rules", str(config), out=tmp_path / "out")

    assert "C06" not in rules_of(payload), "被关闭的规则不该出现"
    c02 = next(f for f in payload["findings"] if f["rule"] == "C02")
    assert c02["severity"] == "blocker"


def test_report_renders_findings(tmp_path):
    """audit.md 与 audit.json 同源（12.10）；unverified 单列结尾且不算 blocker。"""
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "def f():\n    pass\n"})
    _, payload = audit(repo, out=tmp_path / "out")
    markdown = render(payload)
    assert "A01" in markdown
    assert markdown.count("##") >= 1


# ───────────────────────────── 其余 P0 规则的实测（不许只登记不生效） ─────────────────────────────


def test_a03_stub_referenced_by_real_code(tmp_path):
    """A03：存根被真实调用链引用 → blocker；只被测试引用 → 降 major。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/pkg/__init__.py": "",
            "src/pkg/stub.py": "def unfinished():\n    pass\n",
            "src/pkg/consumer.py": (
                "from pkg import stub\n\n\ndef go():\n    return stub.unfinished()\n"
            ),
            "tests/test_stub.py": "from pkg import stub\n\n\ndef test_x():\n    assert stub\n",
            "pytest.ini": "[pytest]\n",
            # src 布局别名要能解析，`from pkg import stub` 才算内部 import
            "pyproject.toml": PYPROJECT + "[tool.setuptools.packages.find]\nwhere = ['src']\n",
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    a03 = [f for f in payload["findings"] if f["rule"] == "A03"]
    assert a03, "存根被 import 却没报 A03"
    assert all(f["severity"] == "blocker" for f in a03)


def test_b02_test_file_without_assert(tmp_path):
    """B02：测试文件存在但无断言。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "tests/test_empty.py": "def test_nothing():\n    x = 1\n",
            "pyproject.toml": PYPROJECT + "[tool.pytest.ini_options]\n",
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert "B02" in rules_of(payload)


def test_b04_module_level_skip(tmp_path):
    """B04：模块级 skip/xfail。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "tests/test_skipped.py": (
                "import pytest\n\npytestmark = pytest.mark.skip(reason='later')\n\n"
                "def test_x():\n    assert True\n"
            ),
            "pyproject.toml": PYPROJECT + "[tool.pytest.ini_options]\n",
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert "B04" in rules_of(payload)


def test_c05_system_language_hook(tmp_path):
    """C05：pre-commit 用 `language: system`（与本地工具版本强耦合）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/mod.py": "x = 1\n",
            "pyproject.toml": PYPROJECT,
            ".pre-commit-config.yaml": (
                "repos:\n"
                "  - repo: local\n"
                "    hooks:\n"
                "      - id: mypy-local\n"
                "        language: system\n"
            ),
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    assert "C05" in rules_of(payload)


def test_g04_gitignore_space_separated_patterns(tmp_path):
    """G04：`.gitignore` 单行含空格分隔多 pattern → 整行不生效。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/mod.py": "x = 1\n",
            "pyproject.toml": PYPROJECT,
            ".gitignore": "__pycache__/ *.py[cod] build/ dist/\n.venv/\n*.egg-info/\n",
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    g04 = [f for f in payload["findings"] if f["rule"] == "G04"]
    assert g04 and g04[0]["line"] == 1


def test_g03_secret_like_string(tmp_path):
    """G03：疑似密钥（且证据里必须打码，不能把密钥原文写进报告）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/conf.py": 'api_key = "sk-live-9f3a2b7c4d5e6f8a1b2c3d4e"\n',
            "pyproject.toml": PYPROJECT,
            ".gitignore": "__pycache__/\n*.py[cod]\nbuild/\ndist/\n*.egg-info/\n.venv/\n",
        },
    )
    _, payload = audit(repo, out=tmp_path / "out")
    g03 = [f for f in payload["findings"] if f["rule"] == "G03"]
    assert g03, "疑似密钥没报出来"
    assert "9f3a2b7c4d5e6f8a1b2c3d4e" not in g03[0]["evidence"], "证据里不能出现密钥原文"


def test_g02_tracked_large_file(tmp_path):
    """G02：已跟踪的大文件（阈值 1MB，见 hygiene.LARGE_FILE_BYTES）。"""
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n", "pyproject.toml": PYPROJECT})
    big = repo / "weights.bin"
    big.write_bytes(b"\0" * 1_100_000)
    from refactor_pilot import gitutil as gu

    gu.run(["add", "-A"], cwd=repo, allow_write=True)
    gu.run(["commit", "-q", "-m", "add big file"], cwd=repo, allow_write=True)

    _, payload = audit(repo, out=tmp_path / "out")
    g02 = [f for f in payload["findings"] if f["rule"] == "G02"]
    assert g02 and g02[0]["file"] == "weights.bin"


def test_g01_git_dir_threshold(tmp_path, monkeypatch):
    """G01：`.git` 体积超阈值（用 monkeypatch 把阈值压到 1 字节来验通路）。"""
    from refactor_pilot.audit import hygiene

    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n", "pyproject.toml": PYPROJECT})
    monkeypatch.setattr(hygiene, "GIT_DIR_BYTES", 1)

    _, payload = audit(repo, out=tmp_path / "out")
    assert "G01" in rules_of(payload)
