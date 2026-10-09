"""lang 字段族：语言、是否被支持、证据（3.3 / 12.9）。

首版只支持 Python。判据是**文件事实**：有多少 `.py` 文件，不是「看起来像 Python 项目」。
"""

from __future__ import annotations

import os

from .common import PY_SUFFIXES, python_files


def collect(root: str | os.PathLike[str]) -> dict:
    files = python_files(root)
    file_count = len(files)
    supported = file_count > 0

    if supported:
        evidence = [f"发现 {file_count} 个 {'/'.join(sorted(PY_SUFFIXES))} 文件"]
    else:
        evidence = [f"未发现 {'/'.join(sorted(PY_SUFFIXES))} 文件，无法判定语言"]

    return {
        "primary": "python" if supported else None,
        "supported": supported,
        "file_count": file_count,
        "evidence": evidence,
    }
