"""核查脚本共用的小工具：遍历 / 读文件 / 输出。

**刻意不 import refactor_pilot** —— 第三段的价值就在于"另一套实现"。
共用 scan 包的处理逻辑会让两边同错，那样差集就没有意义了。

所有核对脚本统一输出 JSON 数组到 stdout，每条候选的形状与 baseline.json 的
 `items[]` 对齐：`rule / file / line / evidence / desc`。
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)


def target(argv: list[str]) -> Path:
    if len(argv) < 2:
        print("用法：<script> <target_repo> [scan.json]", file=sys.stderr)
        raise SystemExit(2)
    path = Path(argv[1]).resolve()
    if not path.is_dir():
        print(f"目标不是目录：{path}", file=sys.stderr)
        raise SystemExit(2)
    return path


def scan_json(argv: list[str]) -> dict:
    """第一段脚本用它当索引（第三段脚本不该调用）。"""
    if len(argv) < 3:
        print("用法：<script> <target_repo> <scan.json>", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(Path(argv[2]).read_text(encoding="utf-8"))


def python_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".py"):
                found.append(Path(dirpath) / name)
    return found


def rel(path: str | Path, root: Path) -> str:
    return Path(path).relative_to(root).as_posix()


def parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None


def source_line(path: Path, lineno: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""


def finding(rule: str, file: str, line: int, evidence: str, desc: str) -> dict:
    return {"rule": rule, "file": file, "line": line, "evidence": evidence, "desc": desc}


def dump(items: list[dict]) -> None:
    print(json.dumps(items, ensure_ascii=False, indent=2, sort_keys=False))


def git_stdout(args: list[str], cwd: Path) -> list[str]:
    """跑一条只读 git 命令，返回非空行；git 不可用或失败时返回空列表。"""
    import subprocess

    try:
        cp = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if cp.returncode != 0:
        return []
    return [line for line in cp.stdout.splitlines() if line.strip()]
