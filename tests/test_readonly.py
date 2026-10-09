"""只读专项测试（12.1 配套 / 13.2 最后一条）。

扫完仓库后：git status 干净 + 全部文件 mtime/size 指纹不变。
"""

import json

import pytest
from helpers import make_repo

from refactor_pilot import fsutil, gitutil, outdir
from refactor_pilot.cli import main

pytestmark = pytest.mark.skipif(not gitutil.available(), reason="git 不可用")

REPO_FILES = {
    "src/mod.py": "x = 1\n",
    "pyproject.toml": "[project]\nname = 'demo'\n",
    "README.md": "# demo\n",
}


def test_scan_leaves_repo_untouched(tmp_path):
    repo = make_repo(tmp_path / "repo", REPO_FILES)
    out = tmp_path / "out"

    before = fsutil.fingerprint(repo)
    assert main(["scan", str(repo), "--out", str(out)]) == 0
    assert fsutil.fingerprint(repo) == before, "扫描修改了仓库内容"
    assert gitutil.status_porcelain(repo) in ("", None), "扫描弄脏了工作树"

    payload = json.loads((out / "scan.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["target"]["path"] == str(repo.resolve())
    assert payload["target"]["snapshot"] == "workdir"
    assert payload["target"]["ref"] is None
    assert payload["target"]["resolved_sha"] is None


def test_scan_with_ref_leaves_repo_untouched(tmp_path):
    repo = make_repo(tmp_path / "repo", REPO_FILES)
    out = tmp_path / "out"

    before = fsutil.fingerprint(repo)
    assert main(["scan", str(repo), "--ref", "HEAD", "--out", str(out)]) == 0
    assert fsutil.fingerprint(repo) == before, "带 ref 的扫描修改了仓库内容"
    assert gitutil.status_porcelain(repo) in ("", None)

    payload = json.loads((out / "scan.json").read_text(encoding="utf-8"))
    assert payload["target"]["snapshot"] == "worktree"
    assert payload["target"]["resolved_sha"] == gitutil.rev_parse(repo, "HEAD")


def test_default_outdir_is_outside_repo(tmp_path):
    repo = make_repo(tmp_path / "repo", REPO_FILES)
    directory, inside = outdir.resolve(repo)
    assert not inside, "默认产物目录必须在仓库外（9.5）"
    assert directory.name == outdir.STAGE_DIR_NAME
    assert outdir.BASE_DIR_NAME in directory.parts


def test_explicit_outdir_inside_repo_is_flagged(tmp_path):
    repo = make_repo(tmp_path / "repo", REPO_FILES)
    directory, inside = outdir.resolve(repo, str(repo / ".upgrade"))
    assert inside, "指向仓库内时应被标记，供 CLI 打印 WARN"
    assert directory == (repo / ".upgrade").resolve() or directory == repo / ".upgrade"
