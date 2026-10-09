"""全项目唯一的写入口（12.1 / 9.5）。

默认写到仓库之外：./refactor-pilot-out/<项目名>/.upgrade/
理由：往被审计仓库里写 .upgrade/ 会违反工具自己的只读硬约束，
顺带也不需要改 .gitignore。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR_NAME = "refactor-pilot-out"
STAGE_DIR_NAME = ".upgrade"


def project_name(project: str | os.PathLike[str]) -> str:
    p = Path(project).resolve()
    name = p.name
    return name if name else p.as_posix().replace("/", "_")


def default_root(project: str | os.PathLike[str]) -> Path:
    """默认产物目录：CWD/refactor-pilot-out/<项目名>/.upgrade/"""
    return Path.cwd() / BASE_DIR_NAME / project_name(project) / STAGE_DIR_NAME


def resolve(project: str | os.PathLike[str], out: str | None = None) -> tuple[Path, bool]:
    """返回 (产物目录, 是否落在目标仓库内)。落在仓库内时调用方应打印 WARN（9.5）。"""
    target = Path(out).expanduser() if out else default_root(project)
    if not target.is_absolute():
        target = Path.cwd() / target
    inside = _is_inside(target, Path(project))
    return target, inside


def ensure(directory: str | os.PathLike[str]) -> Path:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(directory: str | os.PathLike[str], name: str, payload: object) -> Path:
    d = ensure(directory)
    path = d / name
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def write_text(directory: str | os.PathLike[str], name: str, text: str) -> Path:
    d = ensure(directory)
    path = d / name
    path.write_text(text, encoding="utf-8")
    return path


def _is_inside(candidate: Path, project: Path) -> bool:
    try:
        candidate.resolve().relative_to(project.resolve())
    except ValueError:
        return False
    return True
