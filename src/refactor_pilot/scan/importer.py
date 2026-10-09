"""import_graph 字段族：内部边、未解析 import、模块级环（3.3 / 12.3 / 12.9）。

每条 unresolved 记录都带 ``as_symbol``（12.3）：

- ``False``：目标是**模块**（``import x.y``，或 ``from x import y`` 里的模块部分 x）
- ``True`` ：目标是**符号**（``from x import y`` 中模块部分 x 存在、y 既不是 x 的子模块
  也不是 x 的顶层符号 —— y 可能是函数/类/常量，12.3 的例子正是这类）

S2 的 A04 **必须过滤 ``as_symbol = true``** 后再判「模块不存在」，否则每个跨模块函数
调用都会被误报成 import 了不存在的模块。

``kind`` 取值：

- ``third_party``：顶层既非仓库内模块也非标准库 —— 大概率外部依赖
  （本工具不读目标环境，无法证明它在 site-packages 里）
- ``unknown``    ：目标的某个前缀在仓库内，但目标本身不在（疑似缺失子模块或符号）
- ``relative``   ：相对 import 解析不到包内目标（D06 的输入）
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from .common import is_stdlib, package_of, parse, symbols_by_module

THIRD_PARTY = "third_party"
UNKNOWN = "unknown"
RELATIVE = "relative"


def build(root: str | os.PathLike[str], layout: dict) -> dict:
    builder = _Builder(Path(root), layout)
    builder.run()
    unresolved_list = builder.unresolved_records()
    edges = builder.sorted_edges()
    cycles = _cycles(edges)
    return {
        "node_count": len(layout["modules"]),
        "edge_count": sum(len(v) for v in edges.values()),
        "module_paths": dict(sorted(layout["modules"].items())),
        "edges_internal": edges,
        "unresolved_imports": unresolved_list,
        "unresolved_count": len(unresolved_list),
        "cycles": cycles,
        "cycle_count": len(cycles),
    }


class _Builder:
    def __init__(self, root: Path, layout: dict) -> None:
        self.root = root
        self.modules: dict[str, str] = layout["modules"]
        self.aliases: dict[str, str] = layout.get("module_aliases", {})
        self.symbols = symbols_by_module(root, self.modules)
        self.name_of_file: dict[str, str] = {rel: name for name, rel in self.modules.items()}
        self.edges: dict[str, set[str]] = {name: set() for name in self.modules}
        self.unresolved: dict[tuple[str, str, bool], dict] = {}

    def run(self) -> None:
        for rel in sorted(set(self.modules.values())):
            tree = parse(self.root / rel)
            if tree is None:
                continue
            source_name = self.name_of_file.get(rel)
            if source_name is None:  # pragma: no cover - 每个 .py 都有模块名
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.resolve(alias.name, source_name, rel, relative=False)
                elif isinstance(node, ast.ImportFrom):
                    self._handle_from(node, source_name, rel)

    # ---- 内部：把目标落到「内部边 / 忽略 / unresolved」 ------------------------

    def link(self, source_name: str, target: str) -> None:
        if target != source_name and target in self.modules:
            self.edges.setdefault(source_name, set()).add(target)

    def add(self, target: str, kind: str, *, source_name: str, rel: str, as_symbol: bool) -> None:
        self.unresolved.setdefault(
            (source_name, target, as_symbol),
            {
                "from": source_name,
                "target": target,
                "kind": kind,
                "as_symbol": as_symbol,
                "file": rel,
            },
        )

    def canonical(self, dotted: str) -> str | None:
        """点分名 → 仓库内的规范模块名（含 src 布局别名）；不在仓库内返回 None。"""
        if dotted in self.modules:
            return dotted
        return self.aliases.get(dotted)

    def resolve(
        self, dotted: str, source_name: str, rel: str, *, relative: bool, as_symbol: bool = False
    ) -> None:
        """模块目标的解析（``import a.b`` 或 ``from a.b import x`` 的模块部分）。"""
        module = self.canonical(dotted)
        if module:
            self.link(source_name, module)
            return
        if is_stdlib(dotted.split(".", 1)[0]):
            return
        if self._has_internal_prefix(dotted):
            kind = UNKNOWN
        elif relative:
            kind = RELATIVE
        else:
            kind = THIRD_PARTY
        self.add(dotted, kind, source_name=source_name, rel=rel, as_symbol=as_symbol)

    def _has_internal_prefix(self, dotted: str) -> bool:
        parts = dotted.split(".")[:-1]
        while parts:
            if self.canonical(".".join(parts)) is not None:
                return True
            parts.pop()
        return False

    def _handle_from(self, node: ast.ImportFrom, source_name: str, rel: str) -> None:
        relative = node.level > 0
        base = _base_module(node, source_name, self.modules)
        relative = relative or base == ""

        canonical_base = self.canonical(base)
        if canonical_base:
            names = self.symbols.get(canonical_base, set())
            for alias in node.names:
                if alias.name == "*":
                    self.link(source_name, canonical_base)
                    continue
                candidate = f"{base}.{alias.name}"
                submodule = self.canonical(candidate)
                if submodule:
                    self.link(source_name, submodule)
                elif alias.name in names:
                    # y 是 base 里的符号而不是模块 → 12.3 的 as_symbol=true
                    self.link(source_name, canonical_base)
                else:
                    self.add(candidate, UNKNOWN, source_name=source_name, rel=rel, as_symbol=True)
            return

        # 模块部分本身解析不到：逐条落到 unresolved（as_symbol=false，A04 的正当素材）
        if not base:
            for alias in node.names:
                self.add(alias.name, RELATIVE, source_name=source_name, rel=rel, as_symbol=False)
            return
        self.resolve(base, source_name, rel, relative=relative)

    # ---- 输出形态 -------------------------------------------------------------

    def sorted_edges(self) -> dict[str, list[str]]:
        return {name: sorted(targets) for name, targets in sorted(self.edges.items()) if targets}

    def unresolved_records(self) -> list[dict]:
        return sorted(
            self.unresolved.values(),
            key=lambda item: (item["file"], item["target"], item["as_symbol"]),
        )


def _base_module(node: ast.ImportFrom, source_name: str, modules: dict[str, str]) -> str:
    """``from <b> import x`` 里的 <b>；相对 import 按当前包换算。

    注意 `from . import x` 写在**包的 `__init__.py` 里**时，点指的是这个包本身，
    不是它的父包 —— 算到父包去会把包内每个子模块都误报成 unresolved。
    """
    if not node.level:
        return node.module or ""
    is_package = modules.get(source_name, "").endswith("__init__.py")
    current = source_name if is_package else package_of(source_name)
    parts = [p for p in current.split(".") if p]
    if node.level > 1:
        parts = parts[: len(parts) - (node.level - 1)]
    base = ".".join(parts)
    if node.module:
        base = f"{base}.{node.module}" if base else node.module
    return base


def _cycles(edges: dict[str, list[str]]) -> list[list[str]]:
    """模块级 import 环：每个强连通分量给一条代表性闭环。"""
    cycles: list[list[str]] = []
    for component in _strongly_connected(edges):
        if len(component) > 1:
            start = sorted(component)[0]
            cycle = _cycle_through(start, component, edges)
            if cycle:
                cycles.append(cycle)
        else:
            node = next(iter(component))
            if node in edges.get(node, ()):
                cycles.append([node, node])
    return sorted(cycles, key=lambda c: (len(c), c))


def _strongly_connected(edges: dict[str, list[str]]) -> list[set[str]]:
    """Tarjan（迭代版，避免深依赖链递归爆栈）。"""
    nodes = sorted(set(edges) | {t for targets in edges.values() for t in targets})
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    result: list[set[str]] = []
    counter = 0

    for root_node in nodes:
        if root_node in index_of:
            continue
        work: list[tuple[str, int]] = [(root_node, 0)]
        while work:
            node, step = work.pop()
            if step == 0:
                index_of[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack[node] = True
            successors = edges.get(node, ())
            if step < len(successors):
                work.append((node, step + 1))
                nxt = successors[step]
                if nxt not in index_of:
                    work.append((nxt, 0))
                elif on_stack.get(nxt):
                    low[node] = min(low[node], index_of[nxt])
                continue
            if low[node] == index_of[node]:
                component: set[str] = set()
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component.add(member)
                    if member == node:
                        break
                result.append(component)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return result


def _cycle_through(start: str, component: set[str], edges: dict[str, list[str]]) -> list[str]:
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    seen: set[tuple[str, tuple[str, ...]]] = set()
    while stack:
        node, path = stack.pop()
        for nxt in edges.get(node, ()):
            if nxt == start:
                return [*path, start]
            if nxt in component and nxt not in path:
                state = (nxt, tuple(path))
                if state not in seen:
                    seen.add(state)
                    stack.append((nxt, [*path, nxt]))
    return []
