"""A 组 · 存根与依赖闭合（A01 / A02 / A03）。

豁免口径照 7.2：`@abstractmethod`、`Protocol`、`@overload`、`TypedDict`、
`NamedTuple`、仅 `super().__init__()` 的 `__init__`、异常基类钩子。
**ABC/Protocol 的存根一律豁免** —— 那本来就是接口声明，不是没写完。

A03（存根被真实调用链引用）用 import 图的**反向闭包**：
只被测试引用 → 降到 major；被非测试模块引用 → blocker。
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..scan.common import parse
from .findings import FindingFactory
from .rules import MAJOR

EXEMPT_DECORATORS = frozenset({"abstractmethod", "overload"})
EXEMPT_BASES = frozenset({"Protocol", "TypedDict", "NamedTuple", "ABC", "Exception"})
EXEMPT_HOOK_BASES = frozenset({"Exception", "BaseException", "KeyboardInterrupt", "SystemExit"})


def check(root: Path, scan: dict, factory: FindingFactory) -> list[dict]:
    modules = (scan.get("layout") or {}).get("modules") or {}
    test_files = set((scan.get("layout") or {}).get("test_files") or [])
    reverse = _reverse_closure(scan)

    findings: list[dict] = []
    # 模块名 → [(存根符号名, 定义行号)]：A03 要拿它当**真实行号证据**，
    # 否则「存在型却给不出行号」会被按 P-12 降级成 unverified
    stubs: dict[str, list[tuple[str, int]]] = {}

    for name, rel in sorted(modules.items()):
        tree = parse(root / rel)
        if tree is None:
            continue
        owner_bases = _class_bases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if is_exempt(node, owner_bases.get(id(node), frozenset())):
                continue
            rule = _stub_rule(node)
            if rule is None:
                continue
            stubs.setdefault(name, []).append((node.name, node.lineno))
            evidence = _source_line(root / rel, node.lineno)
            finding = factory.make(rule, file=rel, line=node.lineno, evidence=evidence)
            if finding:
                findings.append(finding)

    # A03：存根被真实调用链引用
    for name, entries in sorted(stubs.items()):
        rel = modules.get(name)
        if not rel:
            continue
        importers = reverse.get(name, set())
        real = [m for m in importers if modules.get(m) not in test_files]
        if not importers:
            continue
        symbols = [symbol for symbol, _ in entries]
        _, first_line = entries[0]  # 证据落在存根定义处，不拿 0 冒充
        severity = None if real else MAJOR
        finding = factory.make(
            "A03",
            file=rel,
            line=first_line,
            evidence=f"存根 {', '.join(symbols[:5])} 被 {len(importers)} 个模块 import"
            + ("" if real else "（仅测试引用）"),
            severity=severity,
        )
        if finding:
            findings.append(finding)
    return findings


def _reverse_closure(scan: dict) -> dict[str, set[str]]:
    """模块 → 直接 import 它的模块集合（A03 的反向闭包）。"""
    reverse: dict[str, set[str]] = {}
    for source, targets in (scan.get("import_graph") or {}).get("edges_internal", {}).items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)
    return reverse


def _stub_rule(node: ast.AST) -> str | None:
    if _is_empty_body(node):
        return "A01"
    if _raises_notimplemented(node):
        return "A02"
    return None


def _is_empty_body(node: ast.AST) -> bool:
    body = getattr(node, "body", []) or []
    meaningful = [
        stmt
        for stmt in body
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
    ]
    if not meaningful:
        return True
    return len(meaningful) == 1 and isinstance(meaningful[0], ast.Pass)


def _raises_notimplemented(node: ast.AST) -> bool:
    """`raise NotImplementedError` —— 无括号时 AST 是 Name，带括号时是 Call，两种都要认。"""
    for stmt in getattr(node, "body", []) or []:
        if not isinstance(stmt, ast.Raise):
            continue
        exc = stmt.exc
        if exc is None:  # 裸 raise（无表达式）→ 不是 NotImplementedError
            continue
        target: ast.expr = exc.func if isinstance(exc, ast.Call) else exc
        if _name(target) == "NotImplementedError":
            return True
    return False


def _class_bases(tree: ast.Module) -> dict[int, frozenset[str]]:
    """函数节点 → 所属类的基类集合。

    方法自己没有 `bases`，基类在 `ClassDef` 上 —— 不把这层带上，
    ABC/Protocol 的存根豁免就永远命中不了（方法看着就跟普通空函数一样）。
    """
    owner: dict[int, frozenset[str]] = {}
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        bases = frozenset(_name(base) for base in cls.bases)
        for child in ast.walk(cls):
            owner.setdefault(id(child), bases)
    return owner


def is_exempt(node: ast.FunctionDef | ast.AsyncFunctionDef, bases: frozenset[str]) -> bool:
    decorators = {_name(d) for d in getattr(node, "decorator_list", []) or []}
    if decorators & EXEMPT_DECORATORS:
        return True
    if bases & (EXEMPT_BASES | EXEMPT_HOOK_BASES):
        return True
    return node.name == "__init__" and _only_super_init(node)


def _only_super_init(node: ast.AST) -> bool:
    for stmt in getattr(node, "body", []) or []:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            if isinstance(func, ast.Attribute) and func.attr in {"__init__", "init"}:
                return True
    return False


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _name(node.func)
    return ""


def _source_line(path: Path, lineno: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
