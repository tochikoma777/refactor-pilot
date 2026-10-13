# refactor-pilot 🛠️

> **工程化补课 + 流程护栏**工具：可靠发现工程化缺失、提示配置矛盾；把缺失型问题拆成可验收的阶段，
> 用检查点护栏驱动「**工具规划 → AI 执行 → 工具验收**」的改造流程。
> 它**不验证语义正确性**——逻辑/数值对不对、重构前后行为是否一致、性能是否回归，这些只有对拍或人工深度审计才能覆盖。

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![tests passing](https://img.shields.io/badge/tests-passing-brightgreen.svg)](tests)
[![Read-only by design](https://img.shields.io/badge/design-read--only-brightgreen.svg)](docs/design-v2.md)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-blue.svg)](https://docs.astral.sh/ruff/)
[![Type: mypy](https://img.shields.io/badge/type-mypy-blue.svg)](https://mypy-lang.org/)

---

## 📑 目录

- [它是什么](#positioning)
- [真实案例：nanogpt-plus 的 6 个「伪装测试」](#case)
- [用法：一条命令跑改造](#usage)
- [已验证的项目](#verified)
- [它不做什么（写死，永不消失）](#scope)
- [只读是结构保证](#readonly)
- [已知局限](#limits)
- [开发](#dev)
- [文档与链接](#docs)

---

<a id="positioning"></a>

## 它是什么

refactor-pilot 是一个**工程化补课 + 流程护栏**工具：

- 可靠发现工程化缺失（缺配置、缺约定、依赖 / 测试 / 文档漏洞），并提示配置矛盾；
- 把缺失型问题拆成可验收的阶段，用检查点护栏驱动「**工具规划 → AI 执行 → 工具验收**」的改造流程；
- **只读分析**：S1 扫描 + S2 审计 + recall 召回率自检；
- **改造切片（实验）**：`A 开工核对 → B 实现 → D 实跑验收 → E 提交拆分`。

> 它**不验证语义正确性**。重构前后行为是否一致、数值对不对、性能是否回归——这些只有开启对拍或人工深度审计才能覆盖。工具的价值是**把工程化缺口暴露出来并驱动补上**，不是替你保证代码逻辑正确。

---

<a id="case"></a>

## 真实案例：nanogpt-plus 的 6 个「伪装测试」

这是项目唯一一次真正的「质量优化」实证——它证明工具能发现**人靠肉眼很难看出**的问题。

### 📍 背景

nanogpt-plus 是一个正常 Python 包，仓库里散落着一批测试文件，表面看测试覆盖齐全。

### 🔍 工具发现

审计后判定：其中 **6 个文件零断言**，顶层直接建数据集、跑前向推理。由于项目 `testpaths` 限定在 `tests/`，它们目前不会被收集；但一旦有人跑全量 pytest 或不带 `testpaths` 配置，导入就会触发建数据集与前向推理（耗算力且什么也没验证）。更根本的问题是：它们让项目看起来有 8 个测试文件，实际只有一个 `tests/unit/test_model.py` 是有效测试。
这些被判定为 **B02（整文件无断言的伪装测试）**：它们不是测试，而是「带副作用的脚本混进了测试目录」。

### 🤝 工具交接，不自己改

工具生成交接包，并给出处理建议：

> 这类文件的正确处置是**移出测试包**（去掉 `test_` 前缀、或挪到 `scripts/`），
> 而不是为了凑覆盖率硬加无害断言——硬加断言会掩盖「这本来就不是测试」的事实。

### ✅ AI 执行后重跑审计

**B02 归零，且无任何新 finding**。

### 🏆 为什么值得放进作品集

其余验证项目都只是「补课」（补缺失的配置文件）；只有这一个案例是「揪出隐藏的质量问题」。
更关键的是，这 6 个问题人很难发现——文件命名规范、能正常 import，看起来和其他测试毫无区别，唯一破绽是「没有断言」。而这类问题一旦项目调整 testpaths、或有人直接跑全量 pytest，就会真的被执行。

---

<a id="usage"></a>

## 用法：一条命令跑改造

```bash
# 1. 准备环境
source .venv/bin/activate        # 复用仓库内 .venv
pip install -e .                 # 装出 refactor-pilot 命令行（上方用法入口）

# 2. 一条命令驱动改造循环：反复运行即逐阶段推进
refactor-pilot upgrade <path>
```

`upgrade` 会先 `scan + audit + plan`，然后逐阶段推进。**工具只生成命令与指令块，不执行被测代码 /
git 写操作**（「指挥官模式」），由 AI/人执行，工具下次运行**读证据**判定。产物默认落在**仓库之外**。

工具是「指挥官」：规划与验收由工具完成，执行交给你 / AI。每一阶段都是 **生成计划 → 执行 → 读证据验收** 的闭环，验收不通过就回头重做，不静默放过任何一条 finding。

```mermaid
flowchart LR
    P[工具 plan：生成命令 / 指令块] --> E[AI 或人：执行指令块]
    E --> V[工具：读证据验收]
    V -->|不通过| P
    V -->|通过| N[推进下一阶段]
```

底层子命令（一般用不到，`upgrade` 已封装）：

```
refactor-pilot scan  <path> [--ref REF] [--out DIR] [--snapshot {worktree,archive}]
                            [--exec-probe {on,off}] [--json] [-v]
refactor-pilot audit <path> [--ref REF] [--out DIR] [--rules FILE] [--json]
refactor-pilot recall --audit FILE --baseline FILE [--json] [--detail]
refactor-pilot plan  <path> [--ref REF] [--out DIR] [--rules FILE] [--json]
refactor-pilot s5    <path> --plan FILE [--out DIR] [--stage-id ID] [--cell {a,b,d,e}] [--test-cmd CMD]
refactor-pilot upgrade <path> [--ref REF] [--out DIR] [--test-cmd CMD] [--cell {a,b,d,e}]
```

退出码：`0` 成功（**发现问题不算错**）／`1` 运行时错误／`2` 用法错误／`3` 目标不支持。

---

<a id="verified"></a>

## 已验证的项目

> 项目来源：nanogpt-plus — https://github.com/tochikoma777/nanogpt-plus；v1、toy2 为本地项目（v1 是 2525 行 / 6 模块的脚本型 GPT 实现仓库）。

| 项目 | 类型 | 结论 |
| ---- | ---- | ---- |
| v1 | 脚本型仓库 | 补齐了 5 项工程化缺失中的 4 项（剩 1 项因脚本导入即产生副作用，设计上不适合机械补齐）；存在型检查的正例已用尽 |
| toy2 | 小项目 | 用真实 pytest 跑通了改造切片 A/B/D/E 四格，全程工具未执行被测代码 |
| nanogpt-plus | 正常包 + 真实测试 + 包内伪装测试 | 见上方「真实案例」：工具交出 6 个 B02 伪装测试，AI 移出包后重跑审计归零、无新 finding |

---

<a id="scope"></a>

## 它不做什么（写死，永不消失）

以下三类**不在本工具覆盖范围内**，无论是否开启对拍都一样（这段声明会被无条件写进每份审计报告）：

- 逻辑与数值正确性
- 语义等价性（重构前后行为是否一致）
- 性能回归

---

<a id="readonly"></a>

## 只读是结构保证

- 文件访问层 `fsutil` **只导出读 API**，扫描链路上的代码拿不到写能力
- 全项目唯一的写入口是 `outdir`
- 产物默认写到**仓库之外**：`./refactor-pilot-out/<项目名>/.upgrade/`
- `--ref` 时在临时目录审计（worktree / archive），进程内绝不执行 git commit / push

---

<a id="limits"></a>

## 已知局限

1. **Q6 信号会误命中**：任何名字含 `baseline/expected/golden/reference` 的数据文件都被算作「数值基线」信号。阈值是 ≥2 个信号才建议 Q6 默认开，单条误命中影响有限，但别把它当强信号。
2. **`--exec-probe on` 且无 `--ref` 时是在目标工作目录里跑被测代码**（会打印警告）。建议始终配合 `--ref`。
3. **模块名只认有证据的 source root**（打包声明 + 入口脚本所在目录）。既没有打包声明、又没有 `__main__` 守卫的脚本目录（如 `archives/`），其兄弟 import 会被标成 `third_party` —— 这是设计上刻意保守的判定：**宁可漏报，也不把仓库里真实存在的模块误判为缺失**。
4. **测试文件只要文件名像测试就算数**——工具只按文件名识别测试，不看文件内容。因此「有断言但 `testpaths` 之外、pytest 永不收集」的死测试当前**报不出来**（已列入后续候选规则：检测这类「死测试」）。

---

<a id="dev"></a>

## 开发

```bash
source .venv/bin/activate
pip install -e .          # 装出 refactor-pilot 命令行（上面用法里的入口）
pytest                    # 含只读专项测试：扫完 git status 干净 + 文件指纹不变
ruff check .
mypy
```

不装也行（`pytest` 靠 `conftest.py` 把 `src/` 加进 `sys.path`，照样跑得起来），但那样
**没有 `refactor-pilot` 命令**。想不装直接用：`PYTHONPATH=src python -m refactor_pilot ...`。

---

<a id="docs"></a>

## 文档与链接

- [`docs/design-v2.md`](docs/design-v2.md) —— 权威设计文档（规则定义、范围、实现口径、验收清单）。改规则先改里面的表。
- [`docs/process.md`](docs/process.md) —— 进展流水 + 原始需求「三门」（方向判定的北极星，**不可由后续讨论覆盖**）。
- [`CODEBUDDY.md`](CODEBUDDY.md) —— 给 AI 协作本的硬约束与入口指针（必读）。
