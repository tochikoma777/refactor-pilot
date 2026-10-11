"""I 组 · I01：`__init__.py` 导出的名字在目标模块中不存在。

只查**包内相对导出**（`from .x import y` / `from . import x`）：
绝对 import 的合法性取决于 sys.path 怎么摆，不该由这把尺子判。

⚠️ `__init__.py` 的**再导出**不算"未使用导入"（5.2 机械阶段的护栏）：
那里的 `import` 常常就是公共契约的组成部分，删了直接破坏 Q3=严格兼容。
所以本规则只报"名字在目标模块里根本找不到"的情况，不报"导入了没用到"。
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..scan.common import parse
from .findings import FindingFactory


def check(root: Path, scan: dict, factory: FindingFactory) -> list[dict]:
    modules = (scan.get("layout") or {}).get("modules") or {}
    rel_by_module = {name: rel for name, rel in modules.items() if rel.endswith("__init__.py")}
    trees = {name: parse(root / rel) for name, rel in rel_by_module.items()}

    findings: list[dict] = []
    for name, rel in sorted(rel_by_module.items()):
        tree = trees.get(name)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            base = _base(node, name, rel)
            base_file = modules.get(base)
            if base_file is None:
                continue  # 目标模块不在仓库里 —— 那是 A04 的事
            defined = _defined_names(trees.get(base) if base in trees else parse(root / base_file))
            for alias in node.names:
                if alias.name == "*":
                    continue
                if alias.name in defined or f"{base}.{alias.name}" in modules:
                    continue
                evidence = _line(root / rel, node.lineno)
                finding = factory.make("I01", file=rel, line=node.lineno, evidence=evidence)
                if finding:
                    findings.append(finding)
    return findings


def _module_of(rel: str) -> str:
    parts = rel[: -len(".py")].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _base(node: ast.ImportFrom, name: str, rel: str) -> str:
    is_package = rel.endswith("__init__.py")
    current = name if is_package else name.rpartition(".")[0]
    parts = [p for p in current.split(".") if p]
    if node.level > 1:
        parts = parts[: len(parts) - (node.level - 1)]
    base = ".".join(parts)
    if node.module:
        base = f"{base}.{node.module}" if base else node.module
    return base


def _defined_names(tree: ast.Module | None) -> set[str]:
    if tree is None:
        return set()
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


def _line(path: Path, lineno: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
