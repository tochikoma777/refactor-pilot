"""阶段 1（S4-lite）：把 audit 的**缺失型** finding 自动转成 plan。

范围：**工程化补课** —— 缺失型 finding（finding 已点名期望路径，映射是机械的）。
语义类（A/I 组）与"需要项目知识"的（如 B01 无测试）**不自动规划**，如实列进 `skipped`，
交人工决定。这份"不做"清单与做掉的清单同等重要。

每个阶段可带一条 `accept_cmd`（D 格的验收命令）。**作用域【必须遵守】**：
验收"**本次改动可用**"，**不是"全仓库达标"** ——
`ruff.toml` 只需"能加载"，不要求 `ruff check .` 全仓库 0 错误（存量 lint 债务是另一类阶段）。
"""

from __future__ import annotations

SCHEMA_VERSION = 1

# 3.10 无 stdlib tomllib → 用 tomli 兜底（同 D 格的既有约定）
_TOML_OPEN = (
    "python -c \"import sys; "
    "m=__import__('tomllib') if sys.version_info>=(3,11) else __import__('tomli'); "
)

# rule -> (writes, behavior_spec, accept_cmd)
BLUEPRINTS: dict[str, tuple[list[str], str, str | None]] = {
    "C01": (
        ["pyproject.toml"],
        "补一份 pyproject.toml：声明项目元数据（name / version / description / requires-python）"
        "与构建后端；不改动任何源码。",
        _TOML_OPEN
        + "d=m.load(open('pyproject.toml','rb')); "
        "assert d['project']['name'] and d['project']['version']; "
        "print('OK pyproject.toml：可解析且含 name/version（本次改动可用）')\"",
    ),
    "G05": (
        [".gitignore"],
        "补一份 .gitignore：忽略常见 Python 产物"
        "（__pycache__/、*.py[cod]、build/、dist/、*.egg-info/、.venv/ 等）；不改动任何源码。",
        "python -c \"ls=[l for l in open('.gitignore',encoding='utf-8') "
        "if l.strip() and not l.lstrip().startswith('#')]; "
        "assert len(ls)>0; print('OK .gitignore：含规则行（本次改动可用）')\"",
    ),
    "C02": (
        ["ruff.toml"],
        "补一份 ruff.toml：给出基础 lint 规则；不改动任何源码。",
        _TOML_OPEN
        + "m.load(open('ruff.toml','rb')); "
        "print('OK ruff.toml：可加载（本次改动可用，非全仓库 lint 达标）')\"",
    ),
    "C04": (
        ["CODEBUDDY.md"],
        "写一份约束文件（CODEBUDDY.md）：记录项目硬约束与开工须知；不改动任何源码。",
        "python -c \"t=open('CODEBUDDY.md',encoding='utf-8').read(); "
        "assert t.strip() and '#' in t; print('OK CODEBUDDY.md：非空且含标题')\"",
    ),
    "C06": (
        [".github/workflows/ci.yml"],
        "补一条 CI 工作流：在 push / PR 时跑 lint、类型检查与测试；不改动任何源码。",
        None,  # 无 stdlib YAML 校验器；**不编造**命令 —— 交人工给（演示 D 格守卫）
    ),
}

# 明确**不**自动规划（需要项目知识或属语义类），如实登记
MANUAL_RULES: dict[str, str] = {
    "B01": "无测试：生成有意义的测试需要项目知识，交人工",
}


# 不自动规划的**通用**原因（除 MANUAL_RULES 里的专门说明外）
DEFAULT_SKIP_REASON = "未自动规划：不在工程化补课映射表内，需 AI/人工判断"


def build(audit: dict) -> dict:
    """audit payload → plan payload（多阶段）。

    **铁律：每条 finding 三选一 —— 进 stages / 进 skipped（带原因）/ 不可能静默。**
    （找不到映射就登记为 skipped，绝不静默丢弃。）
    """
    findings = audit.get("findings") or []
    stages: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()

    for finding in findings:
        rule = finding.get("rule")
        if not rule or rule in seen:
            continue
        seen.add(rule)
        if rule in BLUEPRINTS:
            writes, spec, accept = BLUEPRINTS[rule]
            stage = {
                "id": rule.lower(),
                "type": "ai",
                "writes": list(writes),
                "forbidden_paths": [],
                "behavior_spec": spec,
            }
            if accept:
                stage["accept_cmd"] = accept
            stages.append(stage)
        else:
            skipped.append({"rule": rule, "reason": MANUAL_RULES.get(rule, DEFAULT_SKIP_REASON)})

    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "autoplan/1",
        "source": "audit.json",
        "stages": stages,
        "skipped": skipped,
    }
