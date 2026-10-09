"""只读 git 命令封装（subprocess）。

用 git CLI 而不是 GitPython：git CLI 的输出就是事实本身，抽象层只会引入偏差（12.8）。

默认拒绝写子命令 —— 9.4 的「绝不执行 git commit / push / 任何写操作」在这里是结构保证，
不是口头承诺。唯一的例外是 ``snapshot`` 创建/销毁 worktree，需显式传 allow_write=True。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

WRITE_SUBCOMMANDS = frozenset(
    {
        "add",
        "am",
        "apply",
        "branch",
        "checkout",
        "clean",
        "clone",
        "commit",
        "fetch",
        "init",
        "merge",
        "mv",
        "pull",
        "push",
        "rebase",
        "reset",
        "restore",
        "rm",
        "stash",
        "switch",
        "tag",
        "update-index",
        "update-ref",
        "worktree",
    }
)

# 写子命令里的只读例外：`git worktree list` 不改动任何东西
READONLY_EXCEPTIONS = frozenset({("worktree", "list")})

TIMEOUT = 60


class GitError(RuntimeError):
    """git 不可用或调用失败。"""


def available() -> bool:
    return shutil.which("git") is not None


def run(
    args: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    allow_write: bool = False,
    text: bool = True,
    timeout: int = TIMEOUT,
) -> subprocess.CompletedProcess:
    """执行 git <args>。默认禁止写子命令。"""
    if not args:
        raise GitError("空的 git 参数")
    if (
        not allow_write
        and args[0] in WRITE_SUBCOMMANDS
        and tuple(args[:2]) not in READONLY_EXCEPTIONS
    ):
        raise GitError(f"只读层拒绝写子命令：git {' '.join(args)}")
    if not available():
        raise GitError("git 不可用（PATH 上找不到 git）")
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=text,
            errors="replace" if text else None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} 超时") from exc
    except OSError as exc:
        raise GitError(f"git {' '.join(args)} 调用失败：{exc}") from exc


def out(
    args: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    default: str | None = None,
) -> str | None:
    """rc == 0 时返回去空白的 stdout，否则返回 default。"""
    cp = run(args, cwd=cwd)
    if cp.returncode != 0:
        return default
    return (cp.stdout or "").strip()


def ok(args: Sequence[str], *, cwd: str | os.PathLike[str] | None = None) -> bool:
    return run(args, cwd=cwd).returncode == 0


def is_repo(path: str | os.PathLike[str]) -> bool:
    return out(["rev-parse", "--is-inside-work-tree"], cwd=path) == "true"


def repo_root(path: str | os.PathLike[str]) -> Path | None:
    top = out(["rev-parse", "--show-toplevel"], cwd=path)
    return Path(top) if top else None


def rev_parse(path: str | os.PathLike[str], ref: str) -> str | None:
    """解析 ref 到 commit sha；解析不出返回 None（绝不编造）。"""
    return out(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=path)


def status_porcelain(path: str | os.PathLike[str] | None = None) -> str | None:
    """`git status --porcelain` 输出；空串表示工作树干净。"""
    return out(["status", "--porcelain"], cwd=path, default=None)
