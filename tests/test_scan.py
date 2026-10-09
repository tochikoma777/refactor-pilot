"""S1 验收清单测试（13.2）。每条一个用例，且在 docstring 里标出对应条款。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from helpers import make_repo

from refactor_pilot import gitutil, snapshot
from refactor_pilot.cli import main

pytestmark = pytest.mark.skipif(not gitutil.available(), reason="git 不可用")

RULE_ID = __import__("re").compile(r"^[A-J][0-9]{2}$")


def scan(path: Path, *extra: str, out: Path) -> tuple[int, dict]:
    rc = main(["scan", str(path), "--out", str(out), *extra])
    produced = out / "scan.json"
    payload = json.loads(produced.read_text(encoding="utf-8")) if produced.exists() else {}
    return rc, payload


TOOLCHAIN_KEYS = ("test_cmd", "lint_cmd", "fmt_cmd", "type_cmd")


# ───────────────────────────── 13.2 / 12.6 ─────────────────────────────

PLAIN_REPO = {"src/mod.py": "x = 1\n", "README.md": "# demo\n"}


def test_toolchain_all_null_with_reason_when_no_config(tmp_path):
    """工程化配置全缺 → 四条全 null 且**各带** degraded_reason（不编造命令）。"""
    repo = make_repo(tmp_path / "repo", PLAIN_REPO)
    rc, payload = scan(repo, out=tmp_path / "out")
    assert rc == 0

    chain = payload["toolchain"]
    for key in TOOLCHAIN_KEYS:
        entry = chain[key]
        assert entry["cmd"] is None, f"{key} 编造了命令"
        assert entry["suggested"] is None, f"{key} 编造了建议命令"
        assert entry["binary_available"] is None
        assert entry["degraded_reason"], f"{key} 缺 degraded_reason"
        assert key in payload["degraded"]


def test_binary_available_but_probe_off_keeps_verified_false(tmp_path):
    """`binary_available = true` 但 `--exec-probe off` → `verified` 仍为 false（12.6）。"""
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n", "pytest.ini": "[pytest]\n"})
    rc, payload = scan(repo, out=tmp_path / "out")
    assert rc == 0

    entry = payload["toolchain"]["test_cmd"]
    assert entry["suggested"] == "pytest"
    assert entry["source"] == "pytest.ini"
    assert shutil.which("pytest") is not None, "本用例依赖 PATH 上有 pytest"
    assert entry["binary_available"] is True
    assert entry["verified"] is False, "binary 在 PATH 上不等于验证过"


# ───────────────────────────── 13.2 / --exec-probe ─────────────────────────────

PASSING_TESTS = {
    "tests/test_add.py": "def test_add():\n    assert 1 + 1 == 2\n",
    "tests/test_sub.py": (
        "def test_sub():\n    assert 2 - 1 == 1\n\ndef test_skipped():\n    assert True\n"
    ),
    "pyproject.toml": "[project]\nname = 'demo'\n[tool.pytest.ini_options]\n",
}


@pytest.mark.skipif(shutil.which("pytest") is None, reason="PATH 上没有 pytest")
def test_exec_probe_on_verifies_tests(tmp_path):
    """`--exec-probe on` 且实跑通过 → verified/collected/passed_files 都正确。"""
    repo = make_repo(tmp_path / "repo", PASSING_TESTS)
    # 12.5：实跑只在快照目录里做，所以连同 --ref 一起跑
    rc, payload = scan(repo, "--ref", "HEAD", "--exec-probe", "on", out=tmp_path / "out")
    assert rc == 0

    entry = payload["toolchain"]["test_cmd"]
    assert entry["verified"] is True, entry["degraded_reason"]
    assert entry["collected"] == 3
    assert entry["passed_files"] == ["tests/test_add.py", "tests/test_sub.py"]
    assert "test_cmd" not in payload["degraded"]


@pytest.mark.skipif(shutil.which("pytest") is None, reason="PATH 上没有 pytest")
def test_exec_probe_silent_zero_collection(tmp_path):
    """实跑通过但收集 0 个用例 → verified = false 且记录原因（12.6 陷阱）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "tests/test_nothing.py": "CONST = 1\n",
            "pyproject.toml": "[project]\nname = 'demo'\n[tool.pytest.ini_options]\n",
        },
    )
    rc, payload = scan(repo, "--ref", "HEAD", "--exec-probe", "on", out=tmp_path / "out")
    assert rc == 0

    entry = payload["toolchain"]["test_cmd"]
    assert entry["collected"] == 0
    assert entry["verified"] is False, "静默零收集不能算已验证"
    assert "0 个用例" in (entry["degraded_reason"] or "")


@pytest.mark.skipif(shutil.which("pytest") is None, reason="PATH 上没有 pytest")
def test_exec_probe_collection_error_is_not_a_case(tmp_path):
    """收集期错误不是一个用例（12.6 junitxml 坑 2）—— 错误数不能充用例数。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "tests/test_broken.py": "def broken(:\n    pass\n",
            "tests/test_ok.py": "def test_ok():\n    assert True\n",
            "pyproject.toml": "[project]\nname = 'demo'\n[tool.pytest.ini_options]\n",
        },
    )
    rc, payload = scan(repo, "--ref", "HEAD", "--exec-probe", "on", out=tmp_path / "out")
    assert rc == 0

    entry = payload["toolchain"]["test_cmd"]
    assert entry["collected"] == 0
    assert entry["verified"] is False
    assert "收集期错误" in (entry["degraded_reason"] or "")


# ───────────────────────────── 13.2 / 12.3 ─────────────────────────────


def test_unresolved_import_distinguishes_symbol(tmp_path):
    """`from pkg.util import load` 的 load 是符号，不是模块（12.3）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/acme/__init__.py": "",
            "src/acme/schema.py": "def validate(x):\n    return x\n",
            "src/acme/pipeline.py": (
                "import missing_pkg\n"
                "from acme.schema import validate\n"
                "from acme.schema import does_not_exist\n"
            ),
            "pyproject.toml": (
                "[project]\nname = 'demo'\n"
                "[tool.setuptools.packages.find]\nwhere = ['src']\n"
            ),
        },
    )
    rc, payload = scan(repo, out=tmp_path / "out")
    assert rc == 0

    graph = payload["import_graph"]
    records = {(r["target"], r["as_symbol"]): r for r in graph["unresolved_imports"]}
    assert ("missing_pkg", False) in records, "模块 import 应标成 as_symbol=false"
    assert records[("missing_pkg", False)]["kind"] == "third_party"

    symbol = records[("acme.schema.does_not_exist", True)]
    assert symbol["kind"] == "unknown"
    assert symbol["file"] == "src/acme/pipeline.py"

    # 符号 validate 如实解析成内部边，不进 unresolved
    assert "acme.schema" not in {r["target"] for r in payload["import_graph"]["unresolved_imports"]}
    edge = payload["import_graph"]["edges_internal"]["src.acme.pipeline"]
    assert "src.acme.schema" in edge


# ───────────────────────────── 13.2 / 12.4 ─────────────────────────────


def test_test_file_detection_ignores_parent_dir(tmp_path):
    """测试文件判定只看文件名，不看父目录（12.4）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "tests/conftest.py": "import pytest\n",
            "tests/helpers.py": "def helper():\n    return 1\n",
            "tests/fixture_repo.py": "x = 1\n",
            "tests/test_real.py": "def test_real():\n    assert True\n",
            # 反例：父目录叫 src/，文件名不符合 12.4 → 不是测试文件
            "src/helper.py": "def helper():\n    return 2\n",
        },
    )
    rc, payload = scan(repo, out=tmp_path / "out")
    assert rc == 0

    assert payload["layout"]["test_files"] == ["tests/test_real.py"], (
        "tests/ 下的辅助文件不能被当成测试文件"
    )
    paths = [c["path"] for c in payload["q2_candidates"]]
    assert "tests/conftest.py" not in paths, "conftest 被推荐成 Q2 禁改项会让 S4 无解"


# ───────────────────────────── 13.2 / 12.7 ─────────────────────────────


@pytest.mark.parametrize("kind", [snapshot.WORKTREE, snapshot.ARCHIVE])
def test_vcs_facts_complete_for_both_snapshots(tmp_path, kind):
    """worktree / archive 都可用；archive 内无 .git，但 vcs 事实完整（12.7）。"""
    repo = make_repo(tmp_path / "repo", PLAIN_REPO)
    rc, payload = scan(repo, "--ref", "HEAD", "--snapshot", kind, out=tmp_path / "out")
    assert rc == 0

    vcs = payload["vcs"]
    assert vcs["has_git"] is True
    assert vcs["branch"] == "main"
    assert vcs["rev_count"] == 1
    assert vcs["clean"] is True
    assert vcs["head_sha"] == gitutil.rev_parse(repo, "HEAD")


def test_archive_snapshot_has_no_git_dir(tmp_path):
    """archive 快照里没有 .git —— 这是 git 事实必须取自源仓库的原因（12.7）。"""
    repo = make_repo(tmp_path / "repo", PLAIN_REPO)
    with snapshot.create(repo, "HEAD", snapshot.ARCHIVE) as snap:
        assert not (snap.root / ".git").exists()
        from refactor_pilot.scan import vcs as vcs_mod

        facts = vcs_mod.collect(repo)  # 从源仓库采
    assert facts["has_git"] is True


# ───────────────────────────── vcs 仓库根判定（本次修复） ─────────────────────────────


def test_target_is_its_own_repo_root(tmp_path):
    """.git 就在目标目录里、目标自身即仓库根 —— 不能被误判成非 git。"""
    repo = make_repo(tmp_path / "repo", PLAIN_REPO)
    rc, payload = scan(repo, out=tmp_path / "out")
    assert rc == 0

    vcs = payload["vcs"]
    assert vcs["has_git"] is True
    assert Path(vcs["repo_root"]) == repo.resolve()
    assert vcs["branch"] == "main"
    assert vcs["rev_count"] == 1
    assert vcs["clean"] is True
    assert "自身即仓库根" in (vcs["note"] or "")


def test_subdir_of_repo_resolves_to_ancestor_root(tmp_path):
    """目标是仓库子目录时，仓库根落在祖先目录（同一 API 的另一种情形）。"""
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n", "README.md": "# demo\n"})
    rc, payload = scan(repo / "src", out=tmp_path / "out")
    assert rc == 0

    vcs = payload["vcs"]
    assert vcs["has_git"] is True
    assert Path(vcs["repo_root"]) == repo.resolve()
    assert "子目录" in (vcs["note"] or "")


def test_non_repo_reports_false_not_null(tmp_path):
    """非 git 目录：has_git=false 且 note 说明原因，不是静默 null。"""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "src").mkdir()
    (plain / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    rc, payload = scan(plain, out=tmp_path / "out")
    assert rc == 0
    assert payload["vcs"]["has_git"] is False
    assert payload["vcs"]["note"]
    assert "vcs" in payload["degraded"]


# ───────────────────────────── 12.2：S1 产出不含规则 ID ─────────────────────────────


def test_scan_payload_has_no_rule_ids(tmp_path):
    """S1 只采集事实：产出里不应出现任何规则 ID（12.2 推论）。"""
    repo = make_repo(tmp_path / "repo", PLAIN_REPO)
    _, payload = scan(repo, out=tmp_path / "out")
    assert not _rule_ids(payload)


def _rule_ids(node) -> list[str]:
    if isinstance(node, dict):
        hits: list[str] = []
        for key, value in node.items():
            if isinstance(key, str) and RULE_ID.match(key):
                hits.append(key)
            hits.extend(_rule_ids(value))
        return hits
    if isinstance(node, list):
        return [hit for item in node for hit in _rule_ids(item)]
    if isinstance(node, str):
        return [node] if RULE_ID.match(node) else []
    return []


# ───────────────────────────── q6_signals / hooks / q2 ─────────────────────────────


def test_q6_signals_threshold(tmp_path):
    """≥2 个信号才建议 Q6 默认开（5.1 / 12.11）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/mod.py": "x = 1\n",
            "v1-reference/mod.py": "y = 2\n",
            "fixtures/baseline.json": "{}",
        },
    )
    _, payload = scan(repo, out=tmp_path / "out")
    signals = payload["q6_signals"]
    assert signals["ref_dirs"] == ["v1-reference"]
    assert signals["numeric_baselines"] == ["fixtures/baseline.json"]
    assert signals["signal_count"] == 2
    assert signals["suggest_q6_default_on"] is True
    assert signals["threshold"] == 2


def test_reference_dir_not_imported_becomes_q2_candidate(tmp_path):
    """只读参考目录：目录名含参考语义且未被 import → 默认勾选（6.1）。"""
    repo = make_repo(
        tmp_path / "repo",
        {"src/mod.py": "x = 1\n", "v1-reference/ref.py": "y = 2\n"},
    )
    _, payload = scan(repo, out=tmp_path / "out")
    candidate = next(c for c in payload["q2_candidates"] if c["kind"] == "reference_dir")
    assert candidate["path"] == "v1-reference/"
    assert candidate["preselect"] is True
    assert candidate["reason"]


def test_hooks_system_language_is_not_isolated(tmp_path):
    """`language: system` 的 hook 用的是本地工具，不算隔离（hooks 字段族）。"""
    repo = make_repo(
        tmp_path / "repo",
        {
            "src/mod.py": "x = 1\n",
            ".pre-commit-config.yaml": (
                "repos:\n"
                "  - repo: https://github.com/psf/black\n"
                "    rev: 24.2.0\n"
                "    hooks:\n"
                "      - id: black\n"
                "  - repo: local\n"
                "    hooks:\n"
                "      - id: mypy-local\n"
                "        language: system\n"
            ),
        },
    )
    _, payload = scan(repo, out=tmp_path / "out")
    hooks = payload["hooks"]
    assert hooks["precommit_exists"] is True
    assert hooks["isolated"] is False
    assert [e["id"] for e in hooks["entries"]] == ["black", "mypy-local"]
    assert hooks["entries"][0]["rev"] == "24.2.0"
