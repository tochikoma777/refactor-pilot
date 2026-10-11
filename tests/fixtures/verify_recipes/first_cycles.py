#!/usr/bin/env python3
"""第一段 · D04：模块级循环 import（以 scan.json 的 import 图为依据）。

这里不重算图 —— 第一段允许用工具的产出当输入；是否漏报由第三段的独立实现来兜。
"""

from __future__ import annotations

import sys

from _common import dump, finding, scan_json, target


def main() -> None:
    root = target(sys.argv)
    payload = scan_json(sys.argv)
    graph = payload.get("import_graph", {})

    items: list[dict] = []
    for cycle in graph.get("cycles", []):
        head = cycle[0]
        rel_path = graph.get("module_paths", {}).get(head, "")
        path = root / rel_path if rel_path else None
        line = _first_import_line(path, cycle[1]) if cycle[1:] and path else 0
        items.append(
            finding(
                "D04",
                rel_path or ".",
                line,
                " → ".join(cycle),
                f"模块级循环 import：{' → '.join(cycle)}",
            )
        )
    dump(items)


def _first_import_line(path, next_module: str) -> int:
    if not path or not path.is_file():
        return 0
    tail = next_module.split(".")[-1]
    for index, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if tail in line and ("import" in line):
            return index
    return 0


if __name__ == "__main__":
    main()
