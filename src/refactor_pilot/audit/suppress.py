"""规则抑制（7.4）：母规则命中时，子规则不逐条产出，合并计一条。

**为什么必须显式实现**：C01 → D01 不会自然发生 —— 不声明的话扫描器会老实地产出
40 条 D01，报告直接不可用。B01 → B02/B03/B04 倒是会自然不产出，但显式声明
能在新增规则时提醒一句"它有没有母规则"。

**抑制不等于丢失信息**：被抑制的子规则以 `{rule, count}` 挂在母规则的 `merged` 上。
"""

from __future__ import annotations

from .rules import Rules


def apply(findings: list[dict], rules: Rules) -> list[dict]:
    """母规则命中 → 子规则整组撤下，计数合并进母规则。"""
    fired = {f["rule"] for f in findings}

    suppressed: dict[str, int] = {}
    kept: list[dict] = []
    for finding in findings:
        rule = finding["rule"]
        mother = _mother_of(rule, rules)
        if mother and mother in fired:
            suppressed[rule] = suppressed.get(rule, 0) + 1
            continue
        kept.append(finding)

    for finding in kept:
        merged = [
            {"rule": child, "count": count}
            for child, count in sorted(suppressed.items())
            if _mother_of(child, rules) == finding["rule"]
        ]
        if merged:
            finding["merged"] = merged
    return kept


def _mother_of(rule: str, rules: Rules) -> str | None:
    for mother, children in rules.edges.items():
        if rule in children:
            return mother
    return None
