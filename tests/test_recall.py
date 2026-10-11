"""recall 的匹配口径测试（10.3 / 10.5 / 10.6）。

召回率是唯一能证明规则库有效的手段，匹配器写错会让数字**假性变化**，
且不报错、不易察觉（10.3 明确点过这一点）。所以这里逐条锁口径。
"""

from __future__ import annotations

import json
from pathlib import Path

from refactor_pilot import recall


def _audit(tmp_path: Path, findings: list[dict], rules: dict[str, dict] | None = None) -> str:
    payload = {
        "target": {"scan": None},
        "rules": rules or {"B01": {"enabled": True}, "C01": {"enabled": True}},
        "findings": findings,
    }
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _baseline(tmp_path: Path, items: list[dict]) -> str:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _finding(rule: str, file: str, line: int, evidence: str, severity: str = "blocker") -> dict:
    return {
        "id": f"{rule}-001", "rule": rule, "class": "engineering", "severity": severity,
        "confidence": "high", "file": file, "line": line, "evidence": evidence,
        "suggestion": "", "merged": [],
    }


def test_missing_type_matches_by_rule_id_only(tmp_path):
    """缺失型只按 rule_id 匹配：file 与 evidence 均不参与（10.3）。"""
    audit_path = _audit(
        tmp_path,
        [_finding("B01", "tests/", 0, "未发现：tests/ 目录、test_*.py、*_test.py")],
    )
    baseline_path = _baseline(
        tmp_path,
        [{"id": "K-01", "class": "engineering", "file": "tests/", "line": None,
          "detectable_by": ["B01"], "baseline_confidence": "high"}],
    )
    result = recall.run(audit_path, baseline_path)
    assert (result["l1_total"], result["l1_hit"]) == (1, 1)
    assert result["misses"] == []


def test_line_is_never_used_for_matching(tmp_path):
    """绝不按 line 匹配：机械阶段跑完 line 必然位移（10.3）。"""
    audit_path = _audit(
        tmp_path,
        [_finding("C01", "pyproject.toml", 999, "未发现：pyproject.toml")],
    )
    baseline_path = _baseline(
        tmp_path,
        [{"id": "K-02", "class": "engineering", "file": "pyproject.toml", "line": 3,
          "detectable_by": ["C01"], "baseline_confidence": "high"}],
    )
    result = recall.run(audit_path, baseline_path)
    assert result["l1_hit"] == 1, "行号不一致不该影响命中"


def test_layering_l2_l3_excluded_from_denominator(tmp_path):
    """L2（规则未实现）/ L3（无规则）不进分母（10.5）。"""
    audit_path = _audit(
        tmp_path, [_finding("B01", "tests/", 0, "未发现")]
    )
    baseline_path = _baseline(
        tmp_path,
        [
            {"id": "K-01", "class": "engineering", "file": "tests/", "line": None,
             "detectable_by": ["B01"], "baseline_confidence": "high"},          # L1
            {"id": "K-08", "class": "engineering", "file": "docs/", "line": None,
             "detectable_by": ["C07"], "baseline_confidence": "high"},          # L2（C07 未实现）
            {"id": "K-10", "class": "semantic", "file": "src/a.py", "line": 1,
             "detectable_by": [], "baseline_confidence": "medium"},             # L3
        ],
    )
    result = recall.run(audit_path, baseline_path)
    assert result["l1_total"] == 1
    assert [row["id"] for row in result["l2"]] == ["K-08"]
    assert [row["id"] for row in result["l3"]] == ["K-10"]
    assert len(result["misses"]) == 0


def test_l4_low_confidence_counted_with_note(tmp_path):
    """L4（基线存疑）计入但标注（10.5）。"""
    audit_path = _audit(tmp_path, [_finding("B01", "tests/", 0, "未发现")])
    baseline_path = _baseline(
        tmp_path,
        [{"id": "K-09", "class": "engineering", "file": "x (需核对)", "line": None,
          "detectable_by": ["B01"], "baseline_confidence": "low"}],
    )
    result = recall.run(audit_path, baseline_path)
    assert [row["id"] for row in result["l4"]] == ["K-09"]
    assert result["l1_hit"] == 1, "L4 也计入命中"


def test_miss_and_unmatched_are_reported_separately(tmp_path):
    """漏报（L1 未命中）与未匹配（工具多报）必须分开报（10.2 / 10.6）。"""
    audit_path = _audit(
        tmp_path,
        [_finding("C01", "pyproject.toml", 0, "未发现：pyproject.toml"),
         _finding("C02", "ruff.toml", 0, "未发现：ruff.toml")],
        rules={"C01": {"enabled": True}, "C02": {"enabled": True}, "C06": {"enabled": True}},
    )
    baseline_path = _baseline(
        tmp_path,
        [
            {"id": "K-02", "class": "engineering", "file": "pyproject.toml", "line": None,
             "detectable_by": ["C01"], "baseline_confidence": "high"},
            {"id": "K-99", "class": "engineering", "file": "does-not-exist/", "line": None,
             "detectable_by": ["C06"], "baseline_confidence": "high"},
        ],
    )
    result = recall.run(audit_path, baseline_path)
    assert [m["id"] for m in result["misses"]] == ["K-99"]
    assert [u["rule"] for u in result["unmatched"]] == ["C02"]


def test_engineering_rate_is_per_class(tmp_path):
    """工程化召回率按 class 分开算（10.6）。"""
    audit_path = _audit(tmp_path, [_finding("B01", "tests/", 0, "未发现")])
    baseline_path = _baseline(
        tmp_path,
        [{"id": "K-01", "class": "engineering", "file": "tests/", "line": None,
          "detectable_by": ["B01"], "baseline_confidence": "high"}],
    )
    result = recall.run(audit_path, baseline_path)
    assert result["engineering"] == {"hit": 1, "total": 1, "rate": 1.0}
    assert result["semantic"]["rate"] is None  # 无样本 → 不适用，不硬凑成 0
