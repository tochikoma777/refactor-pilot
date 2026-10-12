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


def test_build_dedupes_and_skips_b01_without_scan():
    payload = autoplan.build(_audit(["C01", "C01", "B01"]))
    assert [s["id"] for s in payload["stages"]] == ["c01"]
    assert [i["rule"] for i in payload["skipped"]] == ["B01"]
    assert payload["skipped"][0]["reason"]  # 带原因


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

    # 记账到 finding 粒度：skipped 的 count 之和 + stages 覆盖数 == 总数
    staged_count = sum(1 for r in rules if r in staged)
    skipped_count = sum(item["count"] for item in payload["skipped"])
    assert staged_count + skipped_count == len(rules)


def test_finding_granularity_accounting():
    """skipped 按规则去重显示，但带 count + 全部 files + hint（finding 粒度记账）。"""
    rules = ["B02"] * 6 + ["G05", "G05", "C04", "C06"]
    findings = [{"rule": r, "file": f"f{i}.txt"} for i, r in enumerate(rules)]
    payload = autoplan.build({"findings": findings})

    staged_rules = {s["id"].upper() for s in payload["stages"]}
    staged_count = sum(1 for f in findings if f["rule"] in staged_rules)
    skipped_count = sum(item["count"] for item in payload["skipped"])
    assert staged_count + skipped_count == len(findings), "有 finding 没记账（被静默吞掉）"

    b02 = next(i for i in payload["skipped"] if i["rule"] == "B02")
    assert b02["count"] == 6
    assert len(b02["files"]) == 6
    assert "副作用" in b02["hint"]


def test_yaml_validator_candidates_shape():
    """③ 候选清单：探测到的解析器命令要带文件路径（让人做选择题）。"""
    from refactor_pilot.s5 import facts

    target = ".github/workflows/ci.yml"
    for candidate in facts.yaml_validator_candidates(target):
        assert candidate["parser"]
        assert target in candidate["cmd"]


# ────────────── B01 测试骨架（机械部分） ──────────────


def _scan(mods: dict[str, str]) -> dict:
    return {
        "layout": {"modules": mods},
        "import_graph": {"unresolved_imports": [], "edges_internal": {}},
    }


def test_b01_generates_skeleton_for_safe_modules(tmp_path):
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(
        "def add(a, b):\n    return a + b\n\n\nclass Thing:\n    pass\n", encoding="utf-8"
    )
    scan = _scan({"pkg": "pkg/__init__.py", "pkg.core": "pkg/core.py"})

    payload = autoplan.build(_audit(["B01"]), scan, root)
    stages = payload["stages"]
    assert [s["id"] for s in stages] == ["b01"]
    stage = stages[0]
    assert stage["writes"] == ["tests/conftest.py", "tests/test_pkg_core.py"]
    assert "from pkg.core import add, Thing" in stage["scaffold"]
    assert "TODO(AI)" in stage["scaffold"]
    assert stage["accept_cmd"] == autoplan.B01_ACCEPT


def test_b01_skips_side_effecting_modules(tmp_path):
    """导入即执行副作用的模块（脚本）不生成测试 —— 否则测试会真跑被测代码。"""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "script.py").write_text("print('hi')\n", encoding="utf-8")
    scan = _scan({"script": "script.py"})

    payload = autoplan.build(_audit(["B01"]), scan, root)
    assert payload["stages"] == []
    assert payload["skipped"][0]["rule"] == "B01"
    assert "副作用" in payload["skipped"][0]["reason"]
