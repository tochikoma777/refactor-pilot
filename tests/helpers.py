"""合成仓库构造（测试专用辅助模块，不是测试文件 —— 见 12.4）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from refactor_pilot import gitutil

DEFAULT_FILES = {"README.md": "# demo\n"}


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def worktree_count(repo: Path) -> int:
    """源仓库当前登记的工作树数量（正常为 1，多出来即残留）。"""
    out = gitutil.out(["worktree", "list"], cwd=repo) or ""
    return len([ln for ln in out.splitlines() if ln.strip()])


def make_repo(root: Path, files: dict[str, str] | None = None) -> Path:
    """建一个带一次提交的 git 仓库。"""
    root.mkdir(parents=True, exist_ok=True)
    git(["init", "-q", "-b", "main"], root)
    git(["config", "user.email", "dev@example.com"], root)
    git(["config", "user.name", "dev"], root)
    git(["config", "commit.gpgsign", "false"], root)
    for rel, content in (files or DEFAULT_FILES).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "init"], root)
    return root
