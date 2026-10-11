"""A 组 · A04：import 的模块在仓库中不存在且非三方包。

两条过滤（12.3 / 12.13），少一条就全变噪音：

- **过滤 `as_symbol = true`** —— `from pkg.util import load` 里的 load 是函数不是模块，
  不过滤则每个跨模块函数调用都被报成"模块不存在"
- **只发生在 `unknown` / `relative` 上** —— `third_party` 那些是外部依赖，
  D01（三方 import 未声明）的事，而 D 组不在首版五组内
"""

from __future__ import annotations

from pathlib import Path

from .findings import FindingFactory

A04_KINDS = frozenset({"unknown", "relative"})


def check(root: Path, scan: dict, factory: FindingFactory) -> list[dict]:
    findings: list[dict] = []
    for record in (scan.get("import_graph") or {}).get("unresolved_imports", []):
        if record.get("as_symbol"):
            continue
        if record.get("kind") not in A04_KINDS:
            continue
        path = root / record["file"]
        line = _locate(path, record["target"])
        finding = factory.make(
            "A04",
            file=record["file"],
            line=line,
            evidence=_evidence(path, line) or f"from {record['target']} import ...",
        )
        if finding:
            findings.append(finding)
    return findings


def _locate(path: Path, dotted: str) -> int:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    head = dotted.split(".")[0]
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("import ") and _matches(stripped[len("import "):], dotted, head):
            return index
        if stripped.startswith("from ") and _matches(stripped[len("from "):].split(" import")[0],
                                                     dotted, head):
            return index
    return 0


def _matches(fragment: str, dotted: str, head: str) -> bool:
    return fragment.split()[0].split(".")[0] in {dotted, head} if fragment.strip() else False


def _evidence(path: Path, line: int) -> str:
    if not line:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[line - 1].strip()
    except (OSError, IndexError):
        return ""
