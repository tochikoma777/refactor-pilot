"""阶段 1（S4-lite）：把 audit 的**缺失型** finding 自动转成 plan。

范围：**工程化补课** —— 缺失型 finding（finding 已点名期望路径，映射是机械的）。
语义类（A/I 组）与"需要项目知识"的（如 B01 无测试）**不自动规划**，如实列进 `skipped`，
交人工决定。这份"不做"清单与做掉的清单同等重要。

→ audit.json 的 finding 里 `rule` 命中 BLUEPRINTS 的，各生成一个 stage：
   `writes` 是期望路径，`forbidden_paths` 留空（writes 范围本身已约束 B 格）。
"""

from __future__ import annotations

SCHEMA_VERSION = 1

# rule -> (writes, behavior_spec)
BLUEPRINTS: dict[str, tuple[list[str], str]] = {
    "C01": (
        ["pyproject.toml"],
        "补一份 pyproject.toml：声明项目元数据（name / version / description / requires-python）"
        "与构建后端；不改动任何源码。",
    ),
    "G05": (
        [".gitignore"],
        "补一份 .gitignore：忽略常见 Python 产物"
        "（__pycache__/、*.py[cod]、build/、dist/、*.egg-info/、.venv/ 等）；不改动任何源码。",
    ),
    "C02": (
        ["ruff.toml"],
        "补一份 ruff.toml：给出基础 lint 规则；不改动任何源码。",
    ),
    "C04": (
        ["CODEBUDDY.md"],
        "写一份约束文件（CODEBUDDY.md）：记录项目硬约束与开工须知；不改动任何源码。",
    ),
    "C06": (
        [".github/workflows/ci.yml"],
        "补一条 CI 工作流：在 push / PR 时跑 lint、类型检查与测试；不改动任何源码。",
    ),
}

# 明确**不**自动规划（需要项目知识或属语义类），如实登记
MANUAL_RULES: dict[str, str] = {
    "B01": "无测试：生成有意义的测试需要项目知识，交人工",
}


def build(audit: dict) -> dict:
    """audit payload → plan payload（多阶段）。"""
    findings = audit.get("findings") or []
    stages: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()

    for finding in findings:
        rule = finding.get("rule")
        if rule in BLUEPRINTS and rule not in seen:
            seen.add(rule)
            writes, spec = BLUEPRINTS[rule]
            stages.append(
                {
                    "id": rule.lower(),
                    "type": "ai",
                    "writes": list(writes),
                    "forbidden_paths": [],
                    "behavior_spec": spec,
                }
            )
        elif rule in MANUAL_RULES and rule not in {item["rule"] for item in skipped}:
            skipped.append({"rule": rule, "reason": MANUAL_RULES[rule]})

    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "autoplan/1",
        "source": "audit.json",
        "stages": stages,
        "skipped": skipped,
    }
