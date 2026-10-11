"""hooks 字段族：pre-commit 是否存在、hook 是否用隔离环境（3.3 / 12.9）。

不引第三方 YAML 库（运行时依赖应尽可能为零，12.0），用一个只认这一种文件结构的
行解析器：pre-commit 配置格式固定，够用且比正则套 YAML 可靠。

`isolated = false` 的含义是**使用了本地工具**：`language: system` 的 hook 直接调用
PATH 上的二进制，与本仓库的 lint/type 版本强耦合；其余 language（python/node/...）
由 pre-commit 在自带虚拟环境里装，版本与本地无关。
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import fsutil

CONFIG_NAMES = (".pre-commit-config.yaml", ".pre-commit-config.yml")
SYSTEM_LANGUAGE = "system"


def collect(root: str | os.PathLike[str]) -> dict:
    base = Path(root)
    path = next((name for name in CONFIG_NAMES if fsutil.is_file(base / name)), None)

    if path is None:
        return {
            "precommit_exists": False,
            "isolated": None,
            "entries": [],
            "notes": ["未发现 .pre-commit-config.yaml"],
        }

    text = fsutil.read_text(base / path)
    entries = _parse(text or "")
    notes: list[str] = []
    if not entries:
        notes.append(f"{path} 存在，但未解析出任何 hook（格式可能超出本解析器的覆盖范围）")
    return {
        "precommit_exists": True,
        "isolated": _isolated(entries),
        "entries": entries,
        "notes": notes,
    }


def _isolated(entries: list[dict]) -> bool | None:
    if not entries:
        return None
    languages = [e["language"] for e in entries if e["language"]]
    if not languages:
        return None
    return SYSTEM_LANGUAGE not in languages


def _parse(text: str) -> list[dict]:
    entries: list[dict] = []
    repo: str | None = None
    rev: str | None = None

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        stripped = line.strip()
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip().strip("'\"")

        if stripped.startswith("-"):
            item = stripped.lstrip("- ").strip()
            key, _, value = item.partition(":")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key == "repo":
                repo, rev = value, None
            elif key == "id":
                entries.append(
                    {"repo": repo, "rev": rev, "id": value, "language": None, "line": lineno}
                )
            continue

        if key == "repo":
            repo, rev = value, None
        elif key == "rev":
            rev = value
        elif key == "id" and entries:
            entries[-1]["id"] = value
        elif key == "language" and entries:
            entries[-1]["language"] = value
            # C05 要拿它的行号当证据，不能给 0（P-12：存在型无行号就得降级）
            entries[-1]["line"] = lineno
    return entries
