"""--ref 快照：worktree（默认，带 .git）与 archive（零写入，无 .git）（12.7）。

关键约束：**git 事实始终从源仓库采集，文件内容从快照目录扫描。**
archive 快照里没有 .git，若从快照目录采 git 事实会得到一片 null。
"""

from __future__ import annotations

import io
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import gitutil

WORKDIR = "workdir"
WORKTREE = "worktree"
ARCHIVE = "archive"

KINDS = (WORKTREE, ARCHIVE)


class SnapshotError(RuntimeError):
    """快照创建失败。"""


@dataclass(frozen=True)
class Snapshot:
    root: Path
    kind: str  # workdir | worktree | archive
    ref: str | None
    resolved_sha: str | None


@contextmanager
def create(
    path: str | Path,
    ref: str | None = None,
    kind: str = WORKTREE,
) -> Iterator[Snapshot]:
    """产出快照目录；退出时清理。

    - 无 ref：直接在原工作目录读（kind=workdir，不做任何拷贝，也不清理）
    - ref + worktree：源仓库 .git/worktrees/ 下有元数据写入，try/finally 保证 remove + prune
    - ref + archive：对源仓库零写入，tmpdir 而已
    """
    src = Path(path)
    if ref is None:
        yield Snapshot(root=src, kind=WORKDIR, ref=None, resolved_sha=None)
        return

    if kind not in KINDS:
        raise SnapshotError(f"未知快照类型：{kind}")
    sha = gitutil.rev_parse(src, ref)
    if sha is None:
        raise SnapshotError(f"无法解析 ref：{ref}")

    tmp_root = Path(tempfile.mkdtemp(prefix="refactor-pilot-"))  # 一律建在仓库之外
    try:
        if kind == WORKTREE:
            dest = tmp_root / "snapshot"
            cp = gitutil.run(
                ["worktree", "add", "--detach", str(dest), sha], cwd=src, allow_write=True
            )
            if cp.returncode != 0:
                raise SnapshotError(f"git worktree add 失败：{(cp.stderr or '').strip()}")
        else:
            dest = tmp_root / "snapshot"
            dest.mkdir(parents=True, exist_ok=True)
            _extract_archive(src, sha, dest)
        yield Snapshot(root=dest, kind=kind, ref=ref, resolved_sha=sha)
    finally:
        if kind == WORKTREE:
            gitutil.run(["worktree", "remove", "--force", str(dest)], cwd=src, allow_write=True)
            gitutil.run(["worktree", "prune"], cwd=src, allow_write=True)
        shutil.rmtree(tmp_root, ignore_errors=True)


def _extract_archive(src: Path, sha: str, dest: Path) -> None:
    cp = gitutil.run(["archive", "--format=tar", sha], cwd=src, text=False)
    if cp.returncode != 0:
        raise SnapshotError(f"git archive 失败：{(cp.stderr or b'').decode('utf-8', 'replace')}")
    with tarfile.open(fileobj=io.BytesIO(cp.stdout or b""), mode="r:") as tf:
        if sys.version_info >= (3, 12):
            tf.extractall(dest, filter="data")
        else:
            tf.extractall(dest)
