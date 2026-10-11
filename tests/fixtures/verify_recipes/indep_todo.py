#!/usr/bin/env python3
"""第三段 · A05：TODO/FIXME/XXX/HACK 密度。

**独立实现**：正则扫全文，不看任何工具产出。
脚本只给**每条位置 + 累计计数**，是否构成"密度超阈值"交给人判断。
"""

from __future__ import annotations

import re
import sys

from _common import dump, finding, python_files, rel, source_line, target

MARKER = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b", re.IGNORECASE)


def main() -> None:
    root = target(sys.argv)
    items: list[dict] = []
    for path in python_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, UnicodeError):
            continue
        file_rel = rel(path, root)
        hits = 0
        for index, line in enumerate(lines, start=1):
            match = MARKER.search(line)
            if not match:
                continue
            hits += 1
            keyword = match.group(0).upper()
            items.append(
                finding(
                    "A05",
                    file_rel,
                    index,
                    source_line(path, index)[:160],
                    f"{keyword} 标注（该文件累计 {hits} 处）",
                )
            )
    dump(items)


if __name__ == "__main__":
    main()
