#!/usr/bin/env python3
"""第三段 · E01：`except: pass` / `except Exception: pass`。

**独立实现**：直接走 AST，不依赖任何工具产出。
"""

from __future__ import annotations

import ast
import sys

from _common import dump, finding, parse, python_files, rel, source_line, target


def is_broad_pass(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True  # 裸 except
    name = handler.type.id if isinstance(handler.type, ast.Name) else ""
    return name in {"Exception", "BaseException"}


def only_pass(body: list[ast.stmt]) -> bool:
    meaningful = [
        stmt
        for stmt in body
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Constant)
    ]
    return not meaningful or all(isinstance(stmt, ast.Pass) for stmt in meaningful)


def main() -> None:
    root = target(sys.argv)
    items: list[dict] = []
    for path in python_files(root):
        tree = parse(path)
        if tree is None:
            continue
        file_rel = rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and is_broad_pass(node) and only_pass(node.body):
                items.append(
                    finding(
                        "E01",
                        file_rel,
                        node.lineno,
                        source_line(path, node.lineno),
                        "宽泛 except 后什么也不做（异常被静默吞掉）",
                    )
                )
    dump(items)


if __name__ == "__main__":
    main()
