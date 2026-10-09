import pytest
from helpers import make_repo, worktree_count

from refactor_pilot import gitutil, snapshot
from refactor_pilot.cli import main

pytestmark = pytest.mark.skipif(not gitutil.available(), reason="git 不可用")


def test_worktree_snapshot(tmp_path):
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n"})
    sha = gitutil.rev_parse(repo, "HEAD")

    with snapshot.create(repo, "HEAD", snapshot.WORKTREE) as snap:
        assert snap.kind == snapshot.WORKTREE
        assert snap.resolved_sha == sha
        assert (snap.root / "src" / "mod.py").read_text(encoding="utf-8") == "x = 1\n"
        assert (snap.root / ".git").exists()  # G 组需要 git 上下文
        tmp_parent = snap.root.parent

    assert not tmp_parent.exists(), "临时目录应被清理"
    assert worktree_count(repo) == 1, "worktree 残留"


def test_archive_snapshot_has_no_git(tmp_path):
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n"})
    sha = gitutil.rev_parse(repo, "HEAD")

    with snapshot.create(repo, "HEAD", snapshot.ARCHIVE) as snap:
        assert snap.kind == snapshot.ARCHIVE
        assert snap.resolved_sha == sha
        assert (snap.root / "src" / "mod.py").read_text(encoding="utf-8") == "x = 1\n"
        assert not (snap.root / ".git").exists()  # archive 内无 .git（12.7）

    assert worktree_count(repo) == 1, "archive 不应在源仓库留 worktree"


def test_ref_on_non_repo_exits_3(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert main(["scan", str(plain), "--ref", "HEAD", "--out", str(tmp_path / "out")]) == 3


def test_scan_on_workdir_needs_no_ref(tmp_path):
    repo = make_repo(tmp_path / "repo", {"src/mod.py": "x = 1\n"})
    out = tmp_path / "out"
    assert main(["scan", str(repo), "--out", str(out)]) == 0
    assert (out / "scan.json").exists()
