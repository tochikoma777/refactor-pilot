"""finding 的构造与编号（3.4）。

每条 finding 的形状：

```json
{"id":"A-013","rule":"A01","class":"engineering","severity":"blocker",
 "file":"src/acme_core/pipeline.py","line":42,"evidence":"def normalize(...): ...",
 "suggestion":"实现或删除存根","confidence":"high"}
```

两条硬性约定：

- **必须带 `file:line`**（7.1 第 2 条）。带不出证据的一律降级 `unverified`，
  不计入 blocker，单列在报告末尾
- **`line = 0` 的语义按规则类型分叉**（用户 2026-10-11 裁定的边界，见 P-12）：

  | 规则类型 | `line = 0` 的含义 | 处置 |
  | -------- | ----------------- | ---- |
  | 缺失型（判"某文件/目录不存在"） | 不适用，不可能有行号 | **不降级**；证据是缺失本身 |
  | 存在型（判代码里的东西） | 找不到行号 | **降级 unverified**，不许假装有证据 |

  若不这样分：缺失型会被全部降级（而它们置信度最高），存在型则会拿 `line=0`
  冒充定位证据。两个方向都是错的。
"""

from __future__ import annotations

from .rules import UNVERIFIED, Rules

# ── 两类"`line = 0` 表示不适用"的**封闭清单**（P-12 / P-16）──────────────
#
# 判据是"**规则判的对象不是某一行**"，不是"实现者懒得找行号"。
# 两个清单都封闭：**新增规则默认不在清单内**，要加入必须在同一 commit 里
# 写明理由（改这里 + 改 tests/test_audit.py 的守卫用例）。
# 其余任何规则 `line = 0` → 一律降级 `unverified`。
#
# 为什么必须封闭：不封闭的话，任何规则实现得偷懒都能自证豁免，
# 7.1 原则 2（"每条 finding 必须带 file:line 证据"）就被架空。

# 判"某文件/目录不存在" —— 根本不可能有行号
MISSING_TYPE_RULES = frozenset({"B01", "C01", "C02", "C04", "C06", "G05"})

# 判"整个文件/目录"（非缺失型，但对象仍不是某一行）
LINE_NA_RULES = frozenset({"G01", "G02", "G07"})

LINE_NOT_APPLICABLE = MISSING_TYPE_RULES | LINE_NA_RULES


class FindingFactory:
    """按规则表统一造 finding，避免各规则自己拼字段拼出分歧。"""

    def __init__(self, rules: Rules) -> None:
        self.rules = rules
        self._seq: dict[str, int] = {}

    def make(
        self,
        rule_id: str,
        *,
        file: str,
        line: int,
        evidence: str,
        severity: str | None = None,
        suggestion: str | None = None,
        merged: list[dict] | None = None,
    ) -> dict | None:
        if not self.rules.enabled(rule_id):
            return None

        # 存在型却拿不到行号 → 不许冒充有定位证据（P-12 的边界）
        no_evidence = line <= 0 and rule_id not in LINE_NOT_APPLICABLE
        if no_evidence:
            severity = UNVERIFIED

        seq = self._seq.get(rule_id, 0) + 1
        self._seq[rule_id] = seq
        return {
            "id": f"{rule_id}-{seq:03d}",
            "rule": rule_id,
            "class": self.rules.klass(rule_id),
            "severity": severity or self.rules.severity(rule_id),
            "confidence": "low" if no_evidence else self.rules.confidence(rule_id),
            "file": file,
            "line": line,
            "evidence": evidence.strip()[:200],
            "suggestion": suggestion or self.rules.suggestion(rule_id),
            "merged": merged or [],
        }

    def unverified(self, rule_id: str, *, file: str, evidence: str) -> dict | None:
        """带不出 `file:line` 的判定：如实降级，不混进 blocker。"""
        return self.make(
            rule_id,
            file=file,
            line=0,
            evidence=evidence,
            severity=UNVERIFIED,
            suggestion="需人工确认：本条没有可定位的 file:line 证据",
        )
