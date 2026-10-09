"""vcs 字段族：分支、干净与否、remote、提交数（3.3 / 12.9）。

**仓库根的判定只用 ``git rev-parse --show-toplevel``**（12.7：git 事实一律从源仓库采集，
archive 快照里没有 ``.git``，从快照目录采会得到一片 null）。

⚠️ 不要改成「逐级往上找哪个父目录有 ``.git``」：

- 那种写法对「目标目录**自身**就是仓库根」的情况必然漏判 —— `.git` 就在目标目录里，
  往上找反而什么也找不到。历史上误判 `v1-reference` 不在 git 仓库里，根源就在这里。
- `git rev-parse --show-toplevel` 自己会向上查找并**报告真实仓库根**：
  自身即根时返回自身，是子目录时返回祖先，一个 API 覆盖两种情形。
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import gitutil

FIELDS = ("has_git", "repo_root", "branch", "clean", "remotes", "rev_count", "head_sha", "note")


def collect(source: str | os.PathLike[str]) -> dict:
    """从**源仓库**采集 git 事实（不是从快照目录）。"""
    if not gitutil.available():
        return _empty("git 不可用：PATH 上找不到 git")

    root = gitutil.repo_root(source)  # ← git rev-parse --show-toplevel
    if root is None:
        return _empty("git rev-parse --show-toplevel 未报告仓库根（目标不在 git 仓库内）")

    notes: list[str] = []
    root_note = _root_note(Path(source), root)
    if root_note:
        notes.append(root_note)

    branch = _branch(source, notes)
    clean = _clean(source, notes)
    rev_count = _rev_count(source, notes)

    return {
        "has_git": True,
        "repo_root": str(root),
        "branch": branch,
        "clean": clean,
        "remotes": _remotes(source),
        "rev_count": rev_count,
        "head_sha": gitutil.out(["rev-parse", "HEAD"], cwd=source),
        "note": "；".join(notes) if notes else None,
    }


def _empty(note: str) -> dict:
    return {
        "has_git": False,
        "repo_root": None,
        "branch": None,
        "clean": None,
        "remotes": [],
        "rev_count": None,
        "head_sha": None,
        "note": note,
    }


def _root_note(source: Path, root: Path) -> str | None:
    try:
        same = source.resolve() == root.resolve()
    except OSError:  # pragma: no cover
        return None
    if same:
        return "目标目录自身即仓库根（git rev-parse --show-toplevel 与 target.path 一致）"
    return f"仓库根位于 {root}（目标是其子目录）"


def _branch(source, notes: list[str]) -> str | None:
    """当前分支名。detached HEAD 返回 null —— "HEAD" 不是分支名。"""
    value = gitutil.out(["rev-parse", "--abbrev-ref", "HEAD"], cwd=source)
    if value is None:
        notes.append("git rev-parse --abbrev-ref HEAD 失败")
        return None
    if value == "HEAD":
        notes.append("HEAD 处于分离状态（detached），无分支名")
        return None
    return value


def _clean(source, notes: list[str]) -> bool | None:
    status = gitutil.out(["status", "--porcelain"], cwd=source)
    if status is None:
        notes.append("git status --porcelain 失败")
        return None
    return status == ""


def _remotes(source) -> list[str]:
    value = gitutil.out(["remote"], cwd=source)
    return [line for line in (value or "").splitlines() if line.strip()]


def _rev_count(source, notes: list[str]) -> int | None:
    value = gitutil.out(["rev-list", "--count", "HEAD"], cwd=source)
    if value is None:
        notes.append("git rev-list --count HEAD 失败（可能尚无提交）")
        return None
    try:
        return int(value)
    except ValueError:  # pragma: no cover - git 只输出整数或失败
        notes.append("git rev-list --count HEAD 输出非整数")
        return None
