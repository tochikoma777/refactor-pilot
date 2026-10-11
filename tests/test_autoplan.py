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


def test_every_finding_is_stage_or_skipped():
    """② 铁律：每条 finding 三选一 —— stages / skipped（带原因）/ 不可能静默。"""
    rules = ["C01", "C01", "B01", "G03", "A01", "I02"]
    payload = autoplan.build({"findings": [{"rule": r} for r in rules]})

    staged = {s["id"].upper() for s in payload["stages"]}
    skipped = {s["rule"] for s in payload["skipped"]}
    assert staged | skipped == set(rules)      # 全覆盖，无静默丢弃
    assert not (staged & skipped)              # 不重复归属
    assert all(item["reason"] for item in payload["skipped"])  # 跳过必须带原因


def test_yaml_validator_candidates_shape():
    """③ 候选清单：探测到的解析器命令要带文件路径（让人做选择题）。"""
    from refactor_pilot.s5 import facts

    target = ".github/workflows/ci.yml"
    for candidate in facts.yaml_validator_candidates(target):
        assert candidate["parser"]
        assert target in candidate["cmd"]
