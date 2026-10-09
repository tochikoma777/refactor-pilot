"""只读文件访问层 —— 全项目唯一的文件读取入口（12.1）。

本模块只导出读函数：读文本、遍历、判存在、取指纹。
它不提供任何写能力，因此扫描链路上的代码根本拿不到写文件的 API。

全项目唯一的写入口是 ``outdir``。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

# 遍历时跳过的目录（不是源码，且与审计无关）
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "build",
        "dist",
        ".eggs",
    }
)


def exists(path: str | os.PathLike[str]) -> bool:
    return Path(path).exists()


def is_dir(path: str | os.PathLike[str]) -> bool:
    return Path(path).is_dir()


def is_file(path: str | os.PathLike[str]) -> bool:
    return Path(path).is_file()


def read_text(path: str | os.PathLike[str], *, limit: int | None = None) -> str | None:
    """读文本文件。打不开或解不出编码时返回 None（不抛，扫描不应因单文件中止）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as fh:
            return fh.read(limit) if limit is not None else fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def read_bytes(path: str | os.PathLike[str], *, limit: int | None = None) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read(limit) if limit is not None else fh.read()
    except OSError:
        return None


def iter_files(
    root: str | os.PathLike[str],
    *,
    suffixes: frozenset[str] | set[str] | tuple[str, ...] | None = None,
) -> Iterator[Path]:
    """遍历 root 下的文件，返回绝对路径。不跟随符号链接，跳过 SKIP_DIRS。"""
    base = Path(root)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if suffixes is not None and p.suffix not in suffixes:
                continue
            yield p


def relative_to(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> str:
    """相对路径（POSIX 分隔符），供 scan.json 使用。"""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def fingerprint(root: str | os.PathLike[str]) -> dict[str, tuple[int, int]]:
    """{相对路径: (mtime_ns, size)} —— 用于只读专项测试（13.2 最后一条）。"""
    base = Path(root)
    out: dict[str, tuple[int, int]] = {}
    for p in iter_files(base):
        try:
            st = p.stat()
        except OSError:
            continue
        out[p.relative_to(base).as_posix()] = (st.st_mtime_ns, st.st_size)
    return out
