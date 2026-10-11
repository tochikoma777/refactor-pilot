"""S5 的指令块渲染：三层占位符 + **渲染铁律**（design-v2 6.2）。

三层空间：`project.*`（来自 scan.json）/ `stage.*`（来自 plan）/ `facts.*`（每次实时算）。

**渲染铁律【必须遵守】**：任何未解析的占位符 → **拒绝输出指令块并报错**。
绝不允许把 `{{stage.id}}` 原样交给 AI —— 那是指令质量崩塌的头号原因。

引擎只支持本切片用到的四种写法（够用即可，不引模板库）：
`{{a.b.c}}` / `{{#each x}}…{{/each}}` / `{{#if x}}…{{/if}}` / `{{> partial}}`。
**不支持嵌套**（模板里凡是"块里还要列表"的地方，都由 facts 侧预先拼成字符串字段，
例如 `commit_plan[].adds_block`）。要支持嵌套就先扩引擎，别默默降级。
"""

from __future__ import annotations

import re
from pathlib import Path

EACH = re.compile(r"\{\{#each\s+([\w.]+)\}\}(.*?)\{\{/each\}\}", re.DOTALL)
IF = re.compile(r"\{\{#if\s+([\w.]+)\}\}(.*?)\{\{/if\}\}", re.DOTALL)
PARTIAL = re.compile(r"\{\{>\s*([\w/_.-]+)\s*\}\}")
VAR = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
LEFTOVER = re.compile(r"\{\{.*?\}\}", re.DOTALL)


class RenderError(ValueError):
    """模板里有解析不了的占位符 —— 拒绝输出，绝不原样交给 AI。"""


def render(template: str, context: dict) -> str:
    text = _expand_partials(template)
    text = _expand_each(text, context)
    text = _expand_if(text, context)
    text = _substitute(text, context)
    leftover = LEFTOVER.findall(text)
    if leftover:
        raise RenderError("未解析的占位符：" + ", ".join(sorted(set(leftover))))
    return text


def _expand_partials(template: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in PARTIALS:
            raise RenderError(f"找不到 partial：{name}")
        return PARTIALS[name]

    return PARTIAL.sub(replace, template)


def _expand_each(template: str, context: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        items = _lookup(context, match.group(1))
        if items is None:
            raise RenderError(f"each 的目标不存在：{match.group(1)}")
        if not isinstance(items, list):
            raise RenderError(f"each 的目标不是数组：{match.group(1)}")
        body = match.group(2)
        rendered: list[str] = []
        for item in items:
            scope = dict(context)
            scope["this"] = item
            rendered.append(_substitute(_expand_if(body, scope), scope))
        return "".join(rendered)

    return EACH.sub(replace, template)


def _expand_if(template: str, context: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        return match.group(2) if _lookup(context, match.group(1)) else ""

    return IF.sub(replace, template)


def _substitute(text: str, context: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        value = _lookup(context, match.group(1))
        if value is None:
            raise RenderError(f"占位符取不到值：{match.group(1)}")
        return str(value)

    return VAR.sub(replace, text)


def _lookup(context: dict, dotted: str) -> object | None:
    node: object = context
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


# ────────────────────────────── 内置 partial ──────────────────────────────

PARTIALS = {
    "common/_constraints_block": """## 硬约束（R10）

- 不要改本阶段 `writes` 之外的文件
- 不要碰禁改路径里的任何东西
- 不要顺便重构、不要改公共契约的名字
- 需要偏离时：停下来说明原因，等我决定
""",
    "common/_evidence_protocol": """## 证据协议

命令输出一律重定向到证据文件（**仓库外**；没有证据文件即判定未完成）：

```bash
{ <本阶段的验证命令> 2>&1; echo "RP_EXIT_CODE=$?"; } | tee {{stage.evidence_log}}
```

> 具体的验收命令由 D 格给出；本节只约定证据文件的位置（在仓库之外）。
""",
}


# ────────────────────────────── 三格模板 ──────────────────────────────

A_TEMPLATE = """# [{{project.name}}] 阶段 {{stage.id}} · A 格开工核对（只读，不要改任何代码）

## 0. 先确认约束还在（R3b）

{{#if project.constraints_file}}约束文件：`{{project.constraints_file}}`
预期 `RP:CONSTRAINT:` 锚点：{{facts.constraints_expected}} 条（按 ID 计数）。

```bash
grep -c "RP:CONSTRAINT:" {{project.constraints_file}}
```

少了就停下来补写，不要继续。
{{/if}}{{#if project.no_constraints}}本项目还没有约束文件 —— 本格跳过 R3b，但**不要**自己创建它。
{{/if}}
## 1. 依赖闭合核对（R1）

本阶段要实现/修改：

{{#each stage.writes}}- `{{this}}`
{{/each}}

我扫到的依赖状态（机械部分已做，请只核对语义部分）：

| 目标 | 依赖 | 状态 |
| ---- | ---- | ---- |
{{#each facts.dep_table}}| {{this.target}} | {{this.depends_on}} | {{this.status}} |
{{/each}}
任一行是 `stub` / `missing` → 停下来说明，不要开始实现。

{{#if facts.has_external}}### ⚠️ R1 在本阶段**降级**了，以下依赖我判不了

{{#each facts.external_deps}}- `{{this}}`
{{/each}}
它们在仓库里找不到、也不是标准库，我按「三方依赖」处理，**没有阻塞**。
如果其中其实有本仓库的模块（例如 src 布局却没写打包声明），请**明确指出** ——
这类降级不报出来就等于 R1 悄悄失效。
{{/if}}

## 2. 命名核对（R2）

仓库现有契约（**名字一律沿用**，我只描述行为）：

{{#each facts.contract_snapshot}}- `{{this.symbol}}{{this.signature}}`  [导出: {{this.exported}}]
{{/each}}
【期望行为】（只描述行为，不指定名字）

{{stage.behavior_spec}}

{{> common/_constraints_block}}

---

核对通过后，**再次运行本工具**获取实现指令。
"""

B_TEMPLATE = """# [{{project.name}}] 阶段 {{stage.id}} · B 格实现

## 1. 本阶段只改这些文件

{{#each stage.writes}}- `{{this}}`
{{/each}}

## 2. 禁改路径（碰了就不算完成）

{{#each stage.forbidden_paths}}- `{{this}}`
{{/each}}

## 3. 命名沿用现有契约（R2）

{{#each facts.contract_snapshot}}- `{{this.symbol}}{{this.signature}}`
{{/each}}

{{#if stage.scaffold}}## 4. 骨架（工具生成的**机械部分** —— 断言由你填，工具不编造）

{{stage.scaffold}}
{{/if}}
【期望行为】

{{stage.behavior_spec}}

{{> common/_constraints_block}}

{{> common/_evidence_protocol}}

---

实现完成后，**再次运行本工具**，我会读 git 事实核对改动范围。
"""

E_TEMPLATE = """# [{{project.name}}] 阶段 {{stage.id}} · E 格提交拆分（R5 + R6）

{{#if facts.no_changes}}## 无需提交

工作树是干净的，没有可提交的改动。**不要**执行任何 `git add`。

---
{{/if}}{{#each facts.commit_plan}}## 提交 {{this.index}}：{{this.type}}（**禁止 `git add -A`**）

```bash
{{this.adds_block}}git commit -m "{{this.subject}}"
```

{{/each}}## 逐字照抄 subject（R6）

> subject 必须与上面**完全一致**（逐字比对，多一个空格都算不一致）；body 可自行补充说明。
>
> ⚠️ **type 由路径推断；若本次其实是修复类改动，请自行把 type 改为 `fix`。**
> 只能从 `feat / fix / refactor / chore / docs / test / build / ci` 里选；
> 工具判不了改动语义，故如实标注 —— 别把推断当结论。
> **除 type 外**其余部分必须逐字一致（scope 与描述都不许动）。

## 提交后核对

```bash
git status --short
git rev-list --count HEAD
```

预期提交总数：{{facts.expected_rev_count}}。
"""

D_TEMPLATE = """# [{{project.name}}] 阶段 {{stage.id}} · D 格实跑验收（R4）

## 1. 跑这条命令（**由你执行，本工具不执行被测代码**）

```bash
cd {{project.path}} && { {{facts.test_cmd}} 2>&1; echo "RP_EXIT_CODE=$?"; } \
  | tee {{facts.evidence_path}}
```

> 验收**本次改动可用**即可，不是"全仓库达标"（存量问题另有阶段处理）。

{{#if facts.test_cmd_is_suggested}}
> ⚠️ 这条命令来自扫描的**建议值**（未经实跑验证）。
> 跑不起来就直接把可用的命令告诉我。
{{/if}}
## 2. 这条命令需要什么证据（缺一即判未完成）

- {{facts.evidence_requirement}}
- 日志里必须有 `RP_EXIT_CODE=` 标记（上面的命令会自动带上）

**不要**手写证据文件、**不要**改日志内容 —— 下次运行我会读它并逐项核对。

## 3. 跑完再运行本工具

我会读 `{{facts.evidence_path}}` 判定；没有证据文件 = 未完成，我会重发这条指令。

{{> common/_constraints_block}}
"""

TEMPLATES = {"A": A_TEMPLATE, "B": B_TEMPLATE, "D": D_TEMPLATE, "E": E_TEMPLATE}


def instruction(cell: str, context: dict) -> str:
    """渲染某一格的指令块；模板缺失或不合法一律报错，不降级输出。"""
    template = TEMPLATES.get(cell)
    if template is None:
        raise RenderError(f"没有 {cell} 格的模板")
    return render(template, context)


def write_instruction(directory: Path, stage_id: str, cell: str, text: str) -> Path:
    """写指令块。**仍然只经 outdir**（全项目唯一写入口，12.1）。"""
    from .. import outdir

    steps_dir = outdir.ensure(directory / "steps")
    return outdir.write_text(steps_dir, f"{stage_id}.{cell}.md", text)
