#!/usr/bin/env python3
"""第三段 · A01 / A02：空函数体与 NotImplementedError（存根）。

**独立实现**：只看 AST，不看 scan.json，也不复用 scan 包的任何逻辑。
豁免口径照 7.2 的 A01/A02 条目：`@abstractmethod` / `Protocol` / `@overload` /
 `TypedDict` / `NamedTuple` / 仅 `super().__init__()` 的 `__init__` / 异常基类钩子。
"""

from __future__ import annotations

import ast
import sys

from _common import dump, finding, parse, python_files, rel, source_line, target


def is_empty_body(node: ast.AST) -> bool:
    body = getattr(node, "body", [])
    stripped = [stmt for stmt in body if not isinstance(stmt, ast.Expr) or not _is_docstring(stmt)]
    if not stripped:
        return True
    if len(stripped) == 1 and isinstance(stripped[0], ast.Pass):
        return True
    if len(stripped) == 1 and isinstance(stripped[0], ast.Expr) and isinstance(
        stripped[0].value, ast.Constant
    ):
        return True  # 只有 docstring
    return False


def _is_docstring(stmt: ast.Expr) -> bool:
    return isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def is_exempt(node: ast.AST) -> bool:
    decorator_names = {_name(d) for d in getattr(node, "decorator_list", [])}
    if decorator_names & {"abstractmethod", "overload"}:
        return True
    for base in getattr(node, "bases", []):
        if isinstance(base, ast.Name) and base.id in {"Protocol", "TypedDict", "NamedTuple"}:
            return True
        if isinstance(base, ast.Attribute) and base.attr in {"Protocol", "TypedDict", "NamedTuple"}:
            return True
    return node.name == "__init__" and _only_super_init(node)


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _name(node.func)
    return ""


def _only_super_init(node: ast.AST) -> bool:
    for stmt in getattr(node, "body", []):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            if isinstance(func, ast.Attribute) and func.attr in {"__init__", "init"}:
                return True
    return False


def raises_notimplemented(node: ast.AST) -> bool:
    for stmt in getattr(node, "body", []):
        if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
            if _name(stmt.exc.func) == "NotImplementedError":
                return True
    return False


def main() -> None:
    root = target(sys.argv)
    items: list[dict] = []

    for path in python_files(root):
        tree = parse(path)
        if tree is None:
            continue
        file_rel = rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                evidence = source_line(path, node.lineno)
                if is_empty_body(node) and not is_exempt(node):
                    items.append(
                        finding("A01", file_rel, node.lineno, evidence,
                                f"函数 `{node.name}` 的函数体为空")
                    )
                elif raises_notimplemented(node) and not is_exempt(node):
                    items.append(
                        finding("A02", file_rel, node.lineno, evidence,
                                f"非抽象类中的 `{node.name}` 抛 NotImplementedError")
                    )
    dump(items)


if __name__ == "__main__":
    main()
