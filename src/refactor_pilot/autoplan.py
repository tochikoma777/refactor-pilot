"""阶段 1（S4-lite）：把 audit 的**缺失型** finding 自动转成 plan。

范围：**工程化补课** —— 缺失型 finding（finding 已点名期望路径，映射是机械的）。
语义类（A/I 组）与"需要项目知识"的**不自动规划**，如实列进 `skipped`，交人工决定。
这份"不做"清单与做掉的清单同等重要。

覆盖的两类：
- 单文件缺失型（C01/G05/C02/C04/C06）→ 直接给 writes + accept_cmd
- **B01（零测试）→ 生成测试骨架**（机械部分：tests/ 结构 / conftest / 函数签名 / TODO）；
  **断言由 AI 填**（工具不编造断言）

**铁律：每条 finding 三选一 —— 进 stages / 进 skipped（带原因）/ 不可能静默。**
"""

from __future__ import annotations

import ast
from pathlib import Path

from .scan.common import parse

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
MANUAL_RULES: dict[str, str] = {}

DEFAULT_SKIP_REASON = "未自动规划：不在工程化补课映射表内，需 AI/人工判断"

# 按规则给的**交接提示**（不下手改代码，但把"正确做法"讲清楚，别让 AI 只会硬加断言）
SKIP_HINTS: dict[str, str] = {
    "B02": (
        "这些文件顶层有副作用（导入即执行），正确处理通常是**移出包**或**改名为非 test_ 前缀**，"
        "而不是只加断言。"
    ),
}

B01_ACCEPT = "python -m pytest -q tests"


def _skip_entry(rule: str, reason: str, items: list[dict]) -> dict:
    """跳过项：按**规则**去重显示，但带 `count` 与**全部** `files` —— 记账到 finding 粒度。"""
    files: list[str] = []
    for item in items:
        path = item.get("file")
        if path and path not in files:
            files.append(path)
    entry = {"rule": rule, "reason": reason, "count": len(items), "files": files}
    hint = SKIP_HINTS.get(rule)
    if hint:
        entry["hint"] = hint
    return entry


def build(audit: dict, scan: dict | None = None, root: str | Path | None = None) -> dict:
    """audit payload（+ scan / root）→ plan payload（多阶段）。

    **铁律：每条 finding 三选一 —— 进 stages / 进 skipped（带原因）/ 不可能静默。**
    skipped 按**规则**去重显示，但每条带 `count` + 全部 `files`，使
    `sum(skipped.count) + stages 覆盖的 finding 数 == finding 总数` 恒成立。
    """
    findings = audit.get("findings") or []

    by_rule: dict[str, list[dict]] = {}
    order: list[str] = []
    for finding in findings:
        rule = finding.get("rule")
        if not rule:
            continue
        if rule not in by_rule:
            by_rule[rule] = []
            order.append(rule)
        by_rule[rule].append(finding)

    stages: list[dict] = []
    skipped: list[dict] = []

    for rule in order:
        items = by_rule[rule]
        if rule == "B01":
            stage, reason = _b01_stage(scan, root)
            if stage:
                stages.append(stage)
            else:
                skipped.append(_skip_entry(rule, reason, items))
        elif rule in BLUEPRINTS:
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
            skipped.append(
                _skip_entry(rule, MANUAL_RULES.get(rule, DEFAULT_SKIP_REASON), items)
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "autoplan/1",
        "source": "audit.json",
        "stages": stages,
        "skipped": skipped,
    }


# ────────────────────────── B01：测试骨架（机械部分） ──────────────────────────

# 顶层只允许这些语句 —— 否则视为"导入即执行副作用"，不生成测试（会真跑被测代码）
_SAFE_TOPLEVEL = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _import_safe(tree: ast.Module) -> bool:
    for stmt in tree.body:
        if isinstance(stmt, _SAFE_TOPLEVEL):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # 模块 docstring / 常量字符串
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
            continue  # 常量赋值
        if isinstance(stmt, ast.If) and _is_main_guard(stmt):
            continue  # `if __name__ == "__main__":` 不算副作用
        return False
    return True


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left, right = test.left, test.comparators[0]
    if isinstance(left, ast.Name) and left.id == "__name__" and isinstance(right, ast.Constant):
        return right.value == "__main__"
    return False


def _public_symbols(tree: ast.Module) -> list[str]:
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                out.append(node.name)
    return out


def _import_name(module: str, modules: dict[str, str]) -> str:
    """在"仓库根 + 各源码根"都在 sys.path 上的前提下，可用的导入名。

    真包（顶层名在 modules 里）→ 点分名；脚本目录 → 裸模块名。
    """
    top = module.split(".", 1)[0]
    return module if top in modules else module.rsplit(".", 1)[-1]


def _b01_stage(scan: dict | None, root: str | Path | None) -> tuple[dict | None, str]:
    if not scan or root is None:
        return None, "零测试：缺少 scan/root，无法推导测试骨架"
    layout = scan.get("layout") or {}
    modules: dict[str, str] = layout.get("modules") or {}
    graph = scan.get("import_graph") or {}
    base = Path(root)

    external: dict[str, set[str]] = {}
    for row in graph.get("unresolved_imports", []) or []:
        external.setdefault(row["from"], set()).add(row["target"])
    edges: dict[str, list[str]] = graph.get("edges_internal") or {}

    def has_external(module: str, seen: set[str]) -> bool:
        if module in seen:
            return False
        seen.add(module)
        if external.get(module):
            return True
        return any(has_external(target, seen) for target in edges.get(module, []))

    candidates: list[tuple[str, str, list[str]]] = []
    for module, rel in sorted(modules.items()):
        if rel.startswith("tests/") or Path(rel).name == "__init__.py":
            continue
        if has_external(module, set()):
            continue  # 有第三方依赖 → 环境跑不起来
        tree = parse(base / rel)
        if tree is None or not _import_safe(tree):
            continue  # 导入即执行副作用 → 会真跑被测代码，不生成
        symbols = _public_symbols(tree)
        if symbols:
            candidates.append((module, rel, symbols))

    if not candidates:
        return None, (
            "零测试：**无满足条件的可测模块**（模块导入即执行副作用，或没有可导出的函数/类）；"
            "测试设计需 AI/人工判断"
        )

    writes: list[str] = ["tests/conftest.py"]
    scaffold_blocks: list[str] = [
        "# 测试骨架（工具生成；**断言由 AI 填，工具不编造断言**）",
        "",
        "### tests/conftest.py",
        "```python",
        '"""把仓库根与源码根加入 sys.path（工具生成，可改）。"""',
        "import sys",
        "from pathlib import Path",
        "",
        "ROOT = Path(__file__).resolve().parent.parent",
        "for _p in (ROOT,):",
        "    if str(_p) not in sys.path:",
        "        sys.path.insert(0, str(_p))",
        "```",
        "",
    ]
    for module, _rel, symbols in candidates:
        safe = module.replace(".", "_")
        test_rel = f"tests/test_{safe}.py"
        writes.append(test_rel)
        import_name = _import_name(module, modules)
        scaffold_blocks += [
            f"### {test_rel}",
            "```python",
            f'"""{module} 的测试骨架（工具生成；断言由 AI 填）。"""',
            f"from {import_name} import " + ", ".join(symbols),  # noqa: F541
            "",
            "",
        ]
        for symbol in symbols:
            scaffold_blocks += [
                f"def test_{symbol}():",
                f"    # TODO(AI): 断言 {symbol} 的行为（工具只给结构，不编造断言）",
                "    ...",
                "",
                "",
            ]
        scaffold_blocks.append("```")
        scaffold_blocks.append("")

    stage = {
        "id": "b01",
        "type": "ai",
        "writes": writes,
        "forbidden_paths": [],
        "behavior_spec": (
            "按骨架创建测试文件；**断言由你填**（工具不编造断言）。"
            "只测骨架列出的模块与符号，不要改动源码。"
        ),
        "accept_cmd": B01_ACCEPT,
        "scaffold": "\n".join(scaffold_blocks).rstrip() + "\n",
    }
    return stage, ""
