"""constraints_file 字段族：约束文件是否存在（3.3 / 12.9）。

S1 **只报事实**：存在与否、落在哪个候选上。是否算「缺约束」由 S2 的 C04 判定（12.2）。
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import fsutil

CANDIDATES = ("CODEBUDDY.md", "AGENTS.md", "CLAUDE.md")


def collect(root: str | os.PathLike[str]) -> dict:
    base = Path(root)
    found = [name for name in CANDIDATES if fsutil.is_file(base / name)]
    return {
        "exists": bool(found),
        "path": found[0] if found else None,
        "candidates": list(CANDIDATES),
    }
