#!/usr/bin/env python3
"""第三段 · I01：`__init__.py` 导出的名字在目标模块中不存在。

口径：只查**包内相对导出**（`from .x import y` / `from . import x`）——
绝对 import 的导出是否合法取决于 sys.path 怎么摆，不该由这把窄尺子判。
"""

from __future__ import annotations

import ast
import sys

from _common import dump, finding, parse, python_files, rel, source_line, target


def module_of(file_rel: str) -> str:
    parts = file_rel[: -len(".py")].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def file_of(rel_map: dict[str, str], dotted: str) -> str | None:
    return rel_map.get(dotted)


def defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name.split(".")[0])
    return names


def main() -> None:
    root = target(sys.argv)
    files = {rel(p, root): p for p in python_files(root)}
    rel_map = {module_of(file_rel): file_rel for file_rel in files}

    trees = {file_rel: parse(path) for file_rel, path in files.items()}
    defined = {file_rel: defined_names(tree) for file_rel, tree in trees.items() if tree}

    items: list[dict] = []
    for file_rel, path in sorted(files.items()):
        if not file_rel.endswith("__init__.py"):
            continue
        tree = trees.get(file_rel)
        if tree is None:
            continue
        package = module_of(file_rel)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            base_parts = package.split(".") if package else []
            if node.level > 1:
                base_parts = base_parts[: len(base_parts) - (node.level - 1)]
            base = ".".join([*base_parts, node.module] if node.module else base_parts)
            base_file = rel_map.get(base)
            if base_file is None:
                continue  # 目标模块不在仓库里 —— 那是 A04 的事，不是 I01
            for alias in node.names:
                if alias.name == "*":
                    continue
                in_target = alias.name in defined.get(base_file, set())
                in_submodule = file_of(rel_map, f"{base}.{alias.name}") is not None
                if in_target or in_submodule:
                    continue
                items.append(
                    finding(
                        "I01",
                        file_rel,
                        node.lineno,
                        source_line(path, node.lineno),
                        f"`{package}` 导出的 `{alias.name}` 在 `{base}` 里找不到定义或子模块",
                    )
                )
    dump(items)


if __name__ == "__main__":
    main()
