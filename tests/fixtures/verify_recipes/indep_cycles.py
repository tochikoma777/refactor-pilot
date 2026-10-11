#!/usr/bin/env python3
"""第三段 · D04：模块级循环 import —— **另一套实现**（DFS 三色标记）。

刻意与第一段的 Tarjan 不同：算法不同，才有"漏报交叉验证"的意义。
"""

from __future__ import annotations

import ast
import sys

from _common import dump, finding, parse, python_files, rel, target


def module_name(file_rel: str) -> str:
    parts = file_rel[: -len(".py")].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def build_graph(root):
    """文件 → 它 import 的本仓库模块（相对仓库根的点分名）。"""
    files = {rel(p, root): p for p in python_files(root)}
    names = {rel_path: module_name(rel_path) for rel_path in files}
    known = set(names.values())

    edges: dict[str, set[str]] = {name: set() for name in known}
    for rel_path, path in files.items():
        tree = parse(path)
        if tree is None:
            continue
        source_name = names[rel_path]
        package = source_name.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target_name = _pick_known(alias.name, known)
                    if target_name and target_name != source_name:
                        edges[source_name].add(target_name)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = package.split(".") if package else []
                    if node.level > 1:
                        parts = parts[: len(parts) - (node.level - 1)]
                    base = ".".join([*parts, base]) if parts else base
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    candidate = f"{base}.{alias.name}" if base else alias.name
                    target_name = _pick_known(candidate, known) or _pick_known(base, known)
                    if target_name and target_name != source_name:
                        edges[source_name].add(target_name)
    return edges


def _pick_known(dotted: str, known: set[str]) -> str | None:
    parts = dotted.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in known:
            return candidate
        parts.pop()
    return None


def find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    """三色 DFS：回到灰色节点即成环，记录灰色栈上的那一段。"""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in edges}
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def visit(node: str, stack: list[str]) -> None:
        color[node] = GRAY
        stack.append(node)
        for nxt in sorted(edges.get(node, ())):
            if color.get(nxt) == GRAY:
                start = stack.index(nxt)
                cycle = stack[start:] + [nxt]
                key = tuple(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
            elif color.get(nxt) == WHITE:
                visit(nxt, stack)
        stack.pop()
        color[node] = BLACK

    sys.setrecursionlimit(10000)
    for node in sorted(edges):
        if color[node] == WHITE:
            visit(node, [])
    return cycles


def main() -> None:
    root = target(sys.argv)
    edges = build_graph(root)
    # 反查 模块名 → 文件
    files = {module_name(rel(p, root)): rel(p, root) for p in python_files(root)}

    items: list[dict] = []
    for cycle in find_cycles(edges):
        head = cycle[0]
        file_rel = files.get(head, "")
        path = root / file_rel if file_rel else None
        line = line_of(path, cycle[1]) if path else 0
        items.append(
            finding("D04", file_rel or ".", line, " → ".join(cycle),
                    f"模块级循环 import：{' → '.join(cycle)}")
        )
    dump(items)


def line_of(path, next_module: str) -> int:
    if not path or not path.is_file():
        return 0
    tail = next_module.split(".")[-1]
    for index, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if tail in line and "import" in line:
            return index
    return 0


if __name__ == "__main__":
    main()
