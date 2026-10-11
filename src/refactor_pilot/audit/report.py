"""audit.md 渲染（12.10：与 --json 同源，不做第二套计算）。

两条硬要求：

- **不覆盖声明放在开头**（1.5）—— 放末尾没人看，而"静默跳过"正是本工具要治的毛病
- **无证据的 finding 降级 `unverified`，单列在末尾**（7.3 / 13.3）
"""

from __future__ import annotations

from .rules import BLOCKER, MAJOR, MINOR, UNVERIFIED

ORDER = (BLOCKER, MAJOR, MINOR, UNVERIFIED)


def render(payload: dict) -> str:
    lines: list[str] = []
    not_covered = payload.get("not_covered") or {}

    # 1.5：不覆盖声明必须打头，且**永远都在**（P-15）—— 措辞随 Q6 信号变化
    lines.append("# 审计结果")
    lines.append("")
    lines.append("> ⚠️ " + str(not_covered.get("statement", "")).replace("\n", "\n> "))
    lines.append("")

    counts = payload.get("counts") or {}
    findings = payload.get("findings") or []
    lines.append(f"共 {counts.get('total', 0)} 条，其中 blocker {counts.get('blockers', 0)} 条")
    lines.append("")
    _table(lines, "按严重度", counts.get("by_severity") or {})
    _table(lines, "按规则", counts.get("by_rule") or {})
    _table(lines, "按类别", counts.get("by_class") or {})
    lines.append("")

    for severity in ORDER:
        group = [f for f in findings if f["severity"] == severity]
        if not group:
            continue
        title = (
            "需人工确认（无 file:line 证据，不计入 blocker）"
            if severity == UNVERIFIED
            else severity
        )
        lines.append(f"## {title}")
        lines.append("")
        for item in group:
            location = f"{item['file']}:{item['line']}" if item["line"] else item["file"]
            lines.append(f"- **{item['rule']}** `{location}` — {item['evidence']}")
            lines.append(f"  - 建议：{item['suggestion']}（置信度 {item['confidence']}）")
            for merged in item.get("merged") or []:
                lines.append(f"  - 合并计入：{merged['rule']} × {merged['count']}（7.4 抑制）")
        lines.append("")

    categories = not_covered.get("categories") or []
    if categories:
        lines.append("## 本工具不覆盖的范围")
        lines.append("")
        for category in categories:
            lines.append(f"- {category}")
        lines.append("")
    return "\n".join(lines)


def _table(lines: list[str], title: str, data: dict) -> None:
    if not data:
        return
    lines.append(f"{title}：" + "、".join(f"{key} {value}" for key, value in data.items()))
