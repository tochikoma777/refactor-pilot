#!/usr/bin/env python3
"""第一段 · A04 / D06：import 的模块在仓库中不存在。

用 scan.json **只当索引**（`unresolved_imports` 列表 + 模块清单），判定全在本脚本：

- 过滤 `as_symbol = true`（12.3：符号不是模块，逐符号 import 不算"模块不存在"）
- 顶层既不在标准库、又不是仓库里的模块 → A04 候选
- `kind = relative` 的单独归到 D06（相对 import 越出包根）
- 逐条在源文件里定位行号，给出那一行的原文当证据
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from _common import dump, finding, scan_json, source_line, target

COMMON_THIRD_PARTY = frozenset(
    {
        "matplotlib",
        "numpy",
        "requests",
        "tensorflow",
        "tiktoken",
        "torch",
        "tqdm",
    }
)


def module_names(payload: dict) -> set[str]:
    layout = payload.get("layout", {})
    names = set(layout.get("modules", {}))
    names.update(layout.get("module_aliases", {}))
    return names


def declared_dependencies(root: Path) -> set[str]:
    """pyproject 里声明的依赖包名（含条件依赖）—— A04 的豁免条款。

    A04 判的是"模块不存在**且非三方包**"。已经在依赖里声明过的（哪怕是
    `tomli>=2.0; python_version < '3.11'` 这种条件依赖）就是三方包，不该报。
    """
    import re

    import tomllib

    path = root / "pyproject.toml"
    if not path.is_file():
        return set()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeError):
        return set()

    specs: list[str] = list(data.get("project", {}).get("dependencies", []) or [])
    for group in (data.get("project", {}).get("optional-dependencies", {}) or {}).values():
        specs.extend(group or [])

    names: set[str] = set()
    for spec in specs:
        head = re.split(r"[\[;=<>!~(\s]", spec.strip().strip("'\""))[0]
        if head:
            names.add(head.lower().replace("-", "_"))
    return names


def locate(path, dotted: str) -> int:
    """找到引入这个 dotted 名字的那一行（取第一次出现）。"""
    head = dotted.split(".")[0]
    patterns = (
        re.compile(rf"^\s*import\s+{re.escape(dotted)}\b"),
        re.compile(rf"^\s*from\s+{re.escape(dotted)}\b"),
        re.compile(rf"from\s+{re.escape(dotted)}\s+import"),
        re.compile(rf"^\s*import\s+{re.escape(head)}\b"),
        re.compile(rf"^\s*from\s+{re.escape(head)}\b"),
    )
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    for pattern in patterns:
        for index, line in enumerate(text, start=1):
            if pattern.search(line):
                return index
    return 0


def main() -> None:
    root = target(sys.argv)
    payload = scan_json(sys.argv)
    known = module_names(payload)
    declared = declared_dependencies(root)

    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for record in payload.get("import_graph", {}).get("unresolved_imports", []):
        if record.get("as_symbol"):
            continue
        dotted = record["target"]
        top = dotted.split(".")[0]
        if top in COMMON_THIRD_PARTY or top in declared:
            continue  # 外部依赖（含已声明的条件依赖）：D01 的事，不是"模块不存在"
        if dotted in known or top in known:
            continue
        key = (record["file"], dotted)
        if key in seen:
            continue
        seen.add(key)

        path = root / record["file"]
        line = locate(path, dotted)
        rule = "D06" if record.get("kind") == "relative" else "A04"
        items.append(
            finding(
                rule,
                record["file"],
                line,
                source_line(path, line) if line else f"from {dotted} import ...",
                f"import 的 `{dotted}` 在仓库中找不到对应模块（kind={record.get('kind')}）",
            )
        )
    dump(items)


if __name__ == "__main__":
    main()
