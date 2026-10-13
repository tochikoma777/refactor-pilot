# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

# refactor-pilot · 会话入口

> 本文件只是**入口指针**。权威设计文档是 [`docs/design-v2.md`](docs/design-v2.md)，
> 那里的条款号（如 12.3、13.2）是唯一口径来源。两者冲突时以设计文档为准。

## 开工前必读

0. `docs/process.md` → **顶部"原始需求 + 三门"**（北极星，**不可由后续讨论覆盖**）
   + **第 0 节摘要**（现在在哪、下一步、有哪些待决）
1. `docs/design-v2.md` → 第 7 节（规则）、第 9 节（范围）、第 12 节（实现口径，踩坑才记）、
   第 13 节（顺序 + 验收清单）、**第 14 节（S5 切片）**
2. `git log --oneline` → 进度走到哪一步
3. 做完先过下面的"冷启动自检"，再开工

## 冷启动自检（init 后逐项确认，**缺一即先补齐再开工**）

- [ ] `git log --oneline -5` 与 `docs/process.md` 第 1 节时间线**对得上**（进度没停在未提交的工作树里）
- [ ] `docs/process.md` 顶部**原始需求 + 三门**已读到，且与本次任务不冲突
- [ ] 第 0 节"下一步"与"待你确认"能对上实际待办
- [ ] `CODEBUDDY.md` 硬约束里的"当前方向"指向 `process.md` 顶部，**不存在**与现状矛盾的旧口径（如"不做 S4/S5"）
- [ ] 记忆（`MEMORY.md` 索引）里没有被推翻的结论（改过方向、已完成却还写"待做"）
- [ ] `ruff check . && mypy && pytest -q` 全绿（**改动前先确认基线是绿的**）

## 常用命令

```bash
source .venv/bin/activate          # 所有命令都在仓库内 .venv 里跑（Python 3.13）

ruff check .                       # lint：line-length 100，规则 E/F/W/I
mypy                               # 类型检查：只看 src/，strict=false
pytest -q                          # 全量测试（当前 123 passed）

pytest tests/test_scan.py                      # 单个测试文件
pytest tests/test_scan.py::test_toolchain_all_null_with_reason_when_no_config  # 单个用例
pytest -k "gate or toolchain"                  # 按名字筛
```

- **测试无需安装包即可跑**：`conftest.py` 把 `src/` 插进 `sys.path`（src 布局，见 12.8）。
  要装则 `pip install -e ".[dev]"`（dev extra 声明了 pytest/ruff/mypy）。
- 改动前先确认基线全绿：`ruff check . && mypy && pytest -q`。
- 跑工具自身：`python -m refactor_pilot <子命令>`，或装好后的 `refactor-pilot <子命令>`。
- `tests/test_readonly.py` 是只读专项测试：扫完断言目标仓库 `git status` 干净 +
  全文件指纹不变 —— 改动文件访问层时它最先炸。

## 硬约束（违反即停手）

- **只读**：全项目唯一的写入口是 `src/refactor_pilot/outdir.py`；文件访问层 `fsutil` 只导出读 API（12.1）
- 产物默认写到**仓库之外**：`./refactor-pilot-out/<项目名>/.upgrade/`（9.5）
- **S1 只采集事实，不做判定**；S1 的产出里不得出现任何规则 ID（12.2）
- **toolchain 不编造命令**：探测不到就置 `null` 并写 `degraded_reason`；
  `verified` **只有真跑过**才为 true，不含 `binary_available` 的推断（12.6）
- **git 仓库根只用 `git rev-parse --show-toplevel` 判定**，禁止遍历父目录找 `.git`（12.12①）
- **工具不执行被测代码、也不执行 git 写操作**（"指挥官模式"）：只**生成**命令与指令块，
  由 AI/人执行，工具下次运行**读证据**判定（14.9）。`--exec-probe` 默认 off
- **S5 链路已实现**：A/B/D/E 四格 + `plan`（finding→阶段）+ `upgrade`（单命令驱动循环）+
  B01 测试骨架交接包（`design-v2.md` 第 14 节，14.11–14.16）。
  **当前方向与验收口径以 `docs/process.md` 顶部"原始需求 + 三门"为准** —— 那里【不可由后续讨论覆盖】

## 代码架构

### 数据流水线（全部从 `cli.py` 出发，串行）

```
argparse → snapshot.create() → scan.collect_all() → audit.collect_all()
        → ├─ recall.run()                     （召回率自检）
          ├─ autoplan.build() → plan.json     （缺失型 finding → 阶段）
          └─ s5.run() / upgrade 驱动循环       （A/B/D/E 逐格推进）
```

`scan` / `audit` / `plan` / `upgrade` 都复用 `cli._build_scan()`（cli.py:193），
**scan.json 只有一个产出源** —— 这样"人读输出"与 `--json`、以及各子命令之间不会各算各的（12.10）。

### 三条"只读"是结构保证，不是约定

- `fsutil.py` **只导出读 API**，扫描链路拿不到写函数（12.1）
- `outdir.py` 是**全项目唯一写入口**；产物默认落仓库外 `./refactor-pilot-out/<项目名>/.upgrade/`（9.5）
- `gitutil.py` 默认**拒绝写子命令**（`WRITE_SUBCOMMANDS` 白名单，gitutil.py:17）；
  唯一例外是 snapshot 建/删 worktree，须显式 `allow_write=True`

所有模块必须守住的两个位置概念（12.7）：
`root` = 快照目录，**文件内容**从这扫；`source` = 源仓库，**git 事实**从这采
（archive 快照里没有 `.git`，混用会得到一片 null）。

### S1 / S2 是硬边界

- `scan/`（S1）**只采集事实**，产出里不得出现规则 ID（12.2）。九个字段族：
  `lang / layout / vcs / constraints / hooks / signals(q6) / q2_candidates / import_graph / toolchain`，
  由 `scan/__init__.py::collect_all` 组装。
- `audit/`（S2）**才做判定**。每个子模块就是一组规则：
  `stubs`=A · `deps`=A · `testing`=B · `config`=C · `hygiene`=G · `contracts`=I；
  再经 `suppress.apply()` 施加 7.4 抑制边，`report.render()` 出 `audit.md`。
  `audit/rules.py` 是规则注册表（`Rules.default()` + `--rules FILE` 覆盖）。
  规则定义**先改设计文档 7.2 那张表，实现排后面**。

### S5：格模型与"指挥官模式"

`s5/plan.py` 定义 `Stage`；`s5/__init__.py::run()` 每次调用**最多推进一格**（A→B→D→E）。

- 检查点 `_gate_a/_gate_b/_gate_d/_gate_e` 各自读**事实**判过不过：
  A=依赖闭合+零改动（指纹）· B=改动全落在 `stage.writes` 内且创建类非空 · D=读 evidence 日志的退出码/用例数 · E=提交数+subject 逐字一致
- `s5/render.py` 渲染指令块（模板里有**未解析占位符就拒绝输出**，6.2）
- **工具不执行被测代码、也不执行 git 写操作**：只生成命令/指令块 → AI/人执行 →
  工具下次运行**读证据**判定（14.9）。`--exec-probe` 默认 off。
- `upgrade`（cli.py:375）是单命令驱动循环：反复运行即逐阶段推进；全 `done` 后还会
  **重规划**一次（跨阶段副作用，封顶 3 轮）；每条 finding 三选一：进 stages / 进 skipped / 不静默。

### 产物与状态文件

`scan.json` · `audit.json` · `plan.json` · `state.json` · `audit.md` · `evidence/`（14.9 的证据日志）。
契约骨架见 `model.py`（scan/audit 顶层）；`state.json` 记当前阶段/格、`forced`、`needs_manual_acceptance` 等。

### 测试与基线

- `tests/helpers.py::make_repo` 合成一次性 git 仓库，是绝大多数用例的夹具底座
- `tests/fixtures/verify_recipes/` 是**基线三段法**的窄查询脚本（`first_*` 用 scan.json 当索引、
  `indep_*` 完全独立实现），`python run_all.py <target> <scan.json>` 跑；
  基线由人确认，**不自己生成基线条目**（见协作口径）

## 规则

规则包的定义在 `docs/design-v2.md` 第 7.2 节。新增或改规则**先改那张表**
（规则 / 严重度 / 置信度 / 检测 / 豁免 / 首版是否 P0），实现排在后面。
规则抑制关系（7.4）必须与规则一同实现，否则报告会被冗余 finding 淹没。

## 工程规矩：任何"修改"都必须验证真的改到了

**这是第五次同类问题** —— A02（`raise NotImplementedError` 无括号时是 `Name` 不是 `Call`）、
B04（`pytestmark = ...` 是 `Assign` 不是 `Expr`）、`dep_table` 缺别名解析、
`--cell` 首次运行判不出"向前跳"、以及 `str.replace` 拿 `"message":` 去匹配代码里的 `message=`
**静默没匹配上**。共同模式：**代码静默地没生效，测试却全过。**

所以：

- `str.replace` 之后**断言替换计数 > 0**；改不到就报错，不许静默放过
- AST / 正则匹配之后**断言命中数 > 0**
- 新增规则 / 检查点之后，**必须配一个"故意让它失败"的用例**（design-v2 14.10）
- 优先用"匹配不到就报错"的编辑方式，而不是静默 replace
- **两条指令不许互相打架**：新增/改一条指令时，检查它是否与既有指令矛盾
  （实例：E 块提示"可自行把 type 改为 fix" vs E 格"subject 逐字一致"校验 —— 照做就卡住）。
  矛盾同属"静默失效"，必须一并改掉，不能只加不改
- **同一事实在文档/代码里多处出现，改一处必须同步全部**：改完要通读并检索同源表述，不能只改最先看到的那处。这是「静默没生效」的文档版 —— 已第二次发生（第一次是 `str.replace` 拿 `"message":` 匹配 `message=`）。实例：README 案例段「`testpaths` 限定在 `tests/` 不会被收集」与「pytest 还乐此不疲地执行它们」前后打架，前半段改了、结尾漏改

不写这条，第六次还会来。

## 当前状态

**见 [`docs/process.md`](docs/process.md) 第 0 节（摘要）+ 第 1 节（时间线）**
（唯一进度来源，本文件不再维护第二张表）。

第 0 节**每完成一个阶段更新一次** —— 先看它就知道现在在哪、下一步是什么、有哪些待决。

## 协作口径

- 分步交付：每步做完停下等人确认，不自动往下走
- 汇报要包含：改了哪些文件 / 验收结果 / 下一步是什么
- 存在型基线由人提供，**不自己生成基线条目**（会让召回率虚高）
