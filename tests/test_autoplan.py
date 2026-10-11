"""阶段 1：audit finding → plan（autoplan）+ 多阶段 plan 的校验。"""

from __future__ import annotations

import json

import pytest

from refactor_pilot import autoplan
from refactor_pilot.s5 import plan


def _audit(rules: list[str]) -> dict:
    return {"findings": [{"rule": rule, "file": "x"} for rule in rules]}


def test_build_maps_missing_type_findings_to_stages():
    payload = autoplan.build(_audit(["C01", "C02", "C04", "C06"]))
    assert [s["id"] for s in payload["stages"]] == ["c01", "c02", "c04", "c06"]
    writes = {s["id"]: s["writes"] for s in payload["stages"]}
    assert writes["c01"] == ["pyproject.toml"]
    assert writes["c06"] == [".github/workflows/ci.yml"]


def test_build_dedupes_and_skips_manual_rules():
    payload = autoplan.build(_audit(["C01", "C01", "B01"]))
    assert [s["id"] for s in payload["stages"]] == ["c01"]
    assert payload["skipped"] == [{"rule": "B01", "reason": autoplan.MANUAL_RULES["B01"]}]


def test_build_ignores_unmapped_rules():
    """语义类 / 未映射规则不自动规划（如实留空，不猜）。"""
    assert autoplan.build(_audit(["A01", "G01", "I02"]))["stages"] == []


def test_generated_plan_is_loadable_and_multi_stage(tmp_path):
    payload = autoplan.build(_audit(["C01", "C06"]))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    stages = plan.load_stages(path)
    assert [s.id for s in stages] == ["c01", "c06"]
    assert stages[0].writes == ("pyproject.toml",)
    assert stages[0].forbidden_paths == ()  # 允许为空（writes 范围本身已约束）


def test_single_stage_load_rejects_multi(tmp_path):
    payload = autoplan.build(_audit(["C01", "C06"]))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(plan.PlanError):
        plan.load(path)
