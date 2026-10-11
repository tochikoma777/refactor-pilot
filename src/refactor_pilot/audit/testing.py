"""B 组 · 测试与验收（B01 / B02 / B03 / B04）。

B01 是**缺失型**：`file` 填期望路径、line 0，证据即"未发现"（见 findings 的说明）。
B03 需要实跑（`--exec-probe on`），没实跑就不该声称"零收集"——
没验证的事不能说成"已验证没问题"（12.6）。
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..scan.common import parse
from .findings import FindingFactory
from .rules import UNVERIFIED

TEST_FILE_CANDIDATES = ("tests", "test")
SKIP_MARKERS = frozenset({"skip", "skipif", "xfail"})


def check(root: Path, scan: dict, factory: FindingFactory) -> list[dict]:
    layout = scan.get("layout") or {}
    test_files = list(layout.get("test_files") or [])
    chain = scan.get("toolchain") or {}
    test_cmd = chain.get("test_cmd") or {}

    findings: list[dict] = []

    if not test_files:
        finding = factory.make(
            "B01",
            file="tests/",
            line=0,
            evidence="未发现：tests/ 目录、test_*.py、*_test.py（12.4 口径：只看文件名）",
        )
        if finding:
            findings.append(finding)

    for rel in test_files:
        tree = parse(root / rel)
        if tree is None:
            continue
        if not _has_assert(tree):
            finding = factory.make(
                "B02",
                file=rel,
                line=0,
                evidence=f"{rel} 中未发现任何 assert / pytest.raises",
            )
            if finding:
                findings.append(finding)
        for lineno, marker in _module_level_skips(tree):
            finding = factory.make(
                "B04", file=rel, line=lineno, evidence=f"模块级 skip 标记：{marker}"
            )
            if finding:
                findings.append(finding)

    findings += _silent_zero(root, scan, test_cmd, factory)
    return findings


def _silent_zero(root: Path, scan: dict, test_cmd: dict, factory: FindingFactory) -> list[dict]:
    """B03：静默零收集。只在**实跑过**且确实收集到 0 个时才判（12.6）。"""
    if not test_cmd.get("verified"):
        return []
    if test_cmd.get("collected"):
        return []
    detail = test_cmd.get("degraded_reason") or "实跑收集到 0 个用例"
    finding = factory.make("B03", file=".", line=0, evidence=detail)
    return [finding] if finding else []


def _has_assert(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call):
            name = _name(node.func)
            if name.endswith("raises") or name.startswith("assert_"):
                return True
    return False


def _module_level_skips(tree: ast.Module) -> list[tuple[int, str]]:
    """模块级 skip/xfail —— **只报无条件的**。

    B04 的规则是"模块级 skip/xfail 或全量 skip"。`pytest.mark.skipif(cond, ...)`
    是**条件**跳过（例：`skipif(not git_available())`，没有 git 时才跳），
    把它当"全量 skip"报，会在任何健康项目上刷一片误报 —— 自审计实测 7 条，全是这类。

    口径：
    - `pytestmark = pytest.mark.skip(...)` / `xfail(...)`（无条件）→ 报
    - `pytestmark = pytest.mark.skipif(<常量真值>, ...)` → 报（这才是全量）
    - `skipif(<表达式>)` → 不报
    - 类装饰器同理；**函数装饰器不算模块级**
    """
    out: list[tuple[int, str]] = []
    for stmt in tree.body:
        call = _assigned_call(stmt)
        if call is not None and _is_blanket(call):
            marker = _marker_name(call) or "skip"
            out.append((stmt.lineno, f"pytestmark = {marker}"))
        if isinstance(stmt, ast.ClassDef):
            for decorator in stmt.decorator_list:
                if _is_blanket(decorator):
                    marker = _marker_name(decorator) or "skip"
                    out.append((stmt.lineno, f"@{marker}（类级）"))
    return out


def _is_blanket(call: ast.expr) -> bool:
    """这个标记会不会把整组测试无条件跳过。"""
    if not isinstance(call, ast.Call):
        call = ast.Call(func=call, args=[], keywords=[])  # 允许 `@pytest.mark.skip`
    marker = _marker_name(call)
    if marker in {"skip", "xfail"}:
        return True
    if marker == "skipif":
        first = call.args[0] if call.args else None
        return isinstance(first, ast.Constant) and bool(first.value)
    return False


def _assigned_call(stmt: ast.stmt) -> ast.Call | None:
    """`pytestmark = <call>` 或 `pytestmark = [<call>, ...]` 里的那个 call。"""
    if not isinstance(stmt, ast.Assign):
        return None
    targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    if "pytestmark" not in targets:
        return None
    value = stmt.value
    if isinstance(value, ast.Call):
        return value
    if isinstance(value, ast.List):
        for elt in value.elts:
            if isinstance(elt, ast.Call):
                return elt
    return None


def _marker_name(node: ast.expr) -> str | None:
    """`pytest.mark.skip(...)` / `pytest.mark.skipif` / `skip` → 标记名；否则 None。"""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute) and target.attr in SKIP_MARKERS:
        return target.attr
    name = _name(target)
    return name if name in SKIP_MARKERS else None


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def unverified_note(factory: FindingFactory, rule_id: str, detail: str) -> dict | None:
    """没实跑时的如实标注：不判 B03，只留一条 unverified 给人看。"""
    return factory.make(rule_id, file=".", line=0, evidence=detail, severity=UNVERIFIED)
