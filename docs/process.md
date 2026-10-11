# refactor-pilot · 进展流水

> 本文件记录**实现过程中发生了什么**：进度、决策、未决问题、每步验收证据。
> 另一份 `design-v2.md` 记录**应该是什么**（规格、规则、口径）——两者分开是因为
> 变更频率差一个量级：那份半年动一次，这份每步都动。

| 想找什么         | 去哪                                     |
| ---------------- | ---------------------------------------- |
| 规则定义/严重度  | `design-v2.md` 第 7.2 节                 |
| 实现对不对的依据 | `design-v2.md` 第 13.2 / 13.3 节（验收清单） |
| 实现顺序         | `design-v2.md` 第 13.1 节                |
| 硬约束           | `CODEBUDDY.md`                           |
| 进度与决策流水   | **本文件**（第 0 节摘要 / 第 1 节时间线） |

---

## 0. 当前状态摘要

> **每完成一个阶段就在这里更新一次**（用户 2026-10-11 定的规矩）。
> 只写"现在在哪、下一步是什么、有哪些待决"，细节去下面各节。

- **更新于**：2026-10-11 · **HEAD**：`8e7b5d6` · 工作区干净
- **已完成**：第 1 步骨架/CLI/快照 · 第 2 步 S1 九字段族 · 第 3 步三段法基线（结论：v1 存在型正例耗尽，L1 维持 5 条缺失型）· 第 4 步 S2 审计器 + recall 核心
- **进行中**：**S5 最小切片**（A 依赖闭合+命名核对 / B 实现 / E 提交拆分）—— 设计已提交，**待确认 3 条**后开工，未写代码
- **已冻结的方向**：不再扩张 S2 规则（无验证材料，边际收益趋近零）；不做 S4 规划算法、问卷、完整七格状态机
- **质量门**：`ruff` / `mypy` 全绿 · `pytest 61 passed`
- **规则库现状**：v1 召回 5/5（**全是缺失型送分题**，10.7 早已预警）· 自审计误报 1 条（C06 真问题）
- **待你确认**：S5 切片三条 —— ① 手写单阶段 `--plan FILE` ② CLI 一次推进一格 ③ E 格只生成命令不执行

---

## 1. 进度时间线

| 步    | 内容                              | 状态       | commit    | 日期       |
| ----- | --------------------------------- | ---------- | --------- | ---------- |
| **1** | 骨架 + CLI（三子命令桩）+ `--ref` 快照 | ✅ 已完成  | `4588cf9` | 2026-10-09 |
| —     | 补 `.gitignore` 并把误跟踪的 `.pyc` 移出版本库 | ✅ 已完成  | `0dea45e` | 2026-10-09 |
| **2** | S1 扫描器九个字段族                | ✅ 已完成  | `2709813` | 2026-10-09 |
| **3** | 三段法构建"存在型"基线             | ✅ 已完成  | `a8ea4f4`+`c3a7e4c` | 2026-10-09 |
| **4** | S2 审计：A/B/C/G/I 五组 P0 + C06 + 抑制 | ✅ 已完成  | `88f13dd`+`88fa52c`+`1867d8b`+`8e7b5d6` | 2026-10-11 |
| **5** | recall 子命令 + 四层分层统计       | ✅ 已完成  | `88f13dd`+`fb2c525` | 2026-10-11 |
| **6** | 跑出数字，决定 S4/S5 怎么走        | ✅ 已裁定（见 4.7）：**不再加规则，转向最小 S5 切片** | — | 2026-10-11 |
| **S5 切片** | A 依赖闭合+命名核对 / B 实现 / E 提交拆分 | 🟡 设计已提交，待确认 3 条后开工 | — | 2026-10-11 |

> 第 3 步的"存在型基线"结论：v1 上**没有**可建的存在型正例（A01/A02/D04/E01 全零命中），
> 新增候选 G05/H01 经判定均为误报 → **L1 维持 5 条缺失型**，分层加法仍是 5+2+10=17。

> **第 3 步不可跳过，也不可与第 4 步合并**（`design-v2.md` 10.8 / 13.1）—— 否则召回率是虚空。

---

## 2. 决策台账

按发生顺序编号。每条写结论、理由，以及对应的设计条款（以那边为权威）。

### P-01 · vcs 仓库根只用 `git rev-parse --show-toplevel` 判定

- **结论**：禁止"逐级往上找哪个父目录有 `.git`"的写法；产出新增 `repo_root`，
   `note` 显式区分「目标自身即仓库根」/「目标是子目录」
- **理由**：2026-10-09 曾误判 `llm-playground/oss-upgrade/v1-reference` 不是 git 仓库。
   实则是目标自身即根（`.git` 就在目标目录里），往上找父目录对这种情形**必然**漏判，
   且对所有"自己就是仓库根"的目标都成立，不只 v1
- **条款**：`design-v2.md` 12.12①（【必须遵守】）
- **防回归**：`tests/test_scan.py::test_target_is_its_own_repo_root`、
   `test_subdir_of_repo_resolves_to_ancestor_root`、`test_non_repo_reports_false_not_null`；
   已写入会话记忆 `feedback_git_repo_detection.md`

### P-02 · 新增规则 G07：仓库跟踪了本该忽略的产物文件

- **结论**：严重度 major / 置信度 high / P0；检测口径 `git ls-files` × 产物 pattern 比对
- **理由**：用户自身事故 —— 新项目 `git init` 后直接 `git add -A`，把 9 个 `.pyc` 提交了，
   事后补 `.gitignore` 但已跟踪的文件不会自动消失（还得 `git rm --cached`）。
   靠人记住不可靠，该由工具兜住。（本仓库也犯过：见上面 `0dea45e`）
- **条款**：`design-v2.md` 7.2 G 组表
- **状态**：规则定义已入表，**实现随第 4 步 S2**（目前暂无规则代码载体）

### P-03 · 模块别名：只认有证据的 source root，重名即不解析

- **结论**：`layout` 产出 `source_roots` / `module_aliases`。source root 两种来源 ——
   ① 打包声明（`setuptools.packages.find.where`、poetry `from`）② **入口脚本所在目录**
   （`python x.py` 时该目录进 `sys.path[0]`）。别名重名时**直接丢弃**，不猜是哪个
- **理由**：只按"仓库根相对路径"算点分名，会让 src 布局项目把自己、
   `from language_module import ...` 这类兄弟 import 全部误判成「模块不存在」，那是 A04 最典型的误报来源。
   宁可漏判也不猜：猜错会让人以为看到了真相
- **条款**：`design-v2.md` 12.12②、README「已知局限」第 3 条
- **已知覆盖不到的情形**：既无打包声明、又无 `__main__` 守卫的纯脚本目录（如本项目审计对象的
   `archives/`），其兄弟 import 会被标成 `third_party`

### P-04 · `degraded` 口径：未经证实可用即进 degraded

- **结论**：toolchain 四条命令只要 `verified = false`，该 key 就进 `degraded`；
   `--exec-probe off` 时另加一条汇总 warning，不逐条重复刷屏
- **理由**：12.6「未验证时如实标 degraded，不把没验证说成已验证」的直接推论。
   质疑过是否过于宽松，最终取"如实"一侧
- **条款**：`design-v2.md` 12.6

### P-05 · 新增 `CODEBUDDY.md` 作为会话入口指针

- **结论**：入口只做指针（读哪、硬约束、规则归属），权威仍在 `design-v2.md`；状态表缩为一行指针指向本文件
- **理由**：此前三个入口候选文件（`CODEBUDDY.md`/`AGENTS.md`/`CLAUDE.md`）**全部缺失**，
   新会话不会自动去读设计文档；而工具对自己跑 scan 时 `constraints_file.exists = false`，
   正是自家 C04 要报的问题
- **尾随修正**：为避免与本文件的状态表双写漂移，`CODEBUDDY.md` 不再维护第二张状态表

### P-06 · 每次输出末尾标注是否需要决策

- **结论**：正文结束后单独一行 —— `【无需确认】`/ `【待你确认：N 条】`，N 为实数
- **理由**：用户要扫一眼末尾就知道这次输出有没有要拍板的东西
- **条款**：会话记忆 `feedback_stepwise_delivery.md`

### P-07 · G05 → G07 抑制边

- **结论**：加抑制边，与 C01→D01 同类；合并输出为
   `G05 命中：.gitignore 未忽略 N 个常见 pattern，且仓库中已跟踪 M 个此类产物文件`
- **理由**：母规则命中时子规则**必然**命中（`.gitignore` 漏了 pattern，产物就进版本库），
   逐条列只会制造几十条冗余 finding
- **条款**：`design-v2.md` 7.4 抑制表 + 7.2 G07 条目下的说明

### P-08 · 第 3 步第一段的候选来源：不依赖 S2

> ⚠️ **口径更正（用户裁定）**：第一段的脚本**不要**把 scan.json 的事实直接当候选给人看 ——
> 那是"让人肉眼找问题"，退化成开放式审计，正是 10.8 要避免的。scan.json 只可当**索引**，
> 判定在脚本里出。

- **结论**：第一段 = `tests/fixtures/verify_recipes/` 里的提示脚本跑一遍出候选；
   第三段 = 另一组独立窄查询出差集；两者都脚本化。允许第一段脚本**读 scan.json 当索引**
   （`unresolved_imports` 列表、`modules` 清单），但**判定由脚本自己出**，
   不把 scan.json 的事实直接当候选递给人看
- **理由**：用户裁定 —— 直接拿 scan.json 当候选等于让人肉眼找问题，退化成开放式审计，
   正是 10.8 要避免的东西
- **附带发现的文档内部不一致**：见下面「文档不一致登记」

### P-09 · A04 的 script-style 解析（C01 → A04 抑制边）

- **结论**：无打包声明（C01 命中）时，A04 的解析顺序改为
   ① 兄弟解析 `{import 所在目录}/{target}.py` ② 入口目录作 source root ③ 打包声明的别名 ④ 才报
- **理由**：v1 上 33 条 A04 候选**全是误报**（用户已确认）。根因是 `python x.py`
   会把脚本目录放进 `sys.path[0]`，脚本型仓库的兄弟 import 完全合法 ——
   用"包路径解析"去判它必然全军覆没
- **效果**：第一段 A04 候选 9 → 0；内部边 7 → 16；剩余 unresolved 全是真正的三方库
- **条款**：`design-v2.md` 7.4 抑制表 + 12.13；回归测试 `test_script_style_sibling_imports_resolve`
   （有打包声明时不启用，见 `test_packaged_project_keeps_package_path_semantics`）

### P-10 · G05 的 pattern 分级

- **结论**：核心层（`__pycache__/`、`*.py[cod]`、`build/`、`dist/`、`*.egg-info/`、`.venv/`）
   缺失即报 major；可选层（`.mypy_cache/`、`.ruff_cache/`、`.pytest_cache/`、`.tox/`）
   **仅在检测到对应工具在用**时报 minor
- **理由**：v1 用标准 GitHub Python 模板，却因"缺那 4 个缓存目录"被报 ——
   而它根本没用这些工具（用户判为误报）
- **附带定死**：**G07 不分级** —— 缓存目录进了版本库就是错的，不管仓库用不用这个工具
- **条款**：`design-v2.md` 7.2 G05 条目下的分级表

### P-11 · H01 的三条护栏（+ 第四条）

- **结论**：① 剥离围栏代码块与行内代码 ② 排除通用占位名 ③ 先抹掉 URL
   ④ **只扫面向使用者的 README 类文档**
- **理由**：v1 的命中在 ```python 围栏里（`with open("data.txt")` 是使用示例，用户判为误报）；
   自审计又暴露第 4 类噪音 —— 设计文档里必然提到"将来才生成的产物"（`scan.json`、
   `.upgrade/plan.json` …），9 条命中全在这里
- **条款**：`design-v2.md` 7.2 H 组条目下的护栏
- **统计口径提醒**：H 组**不在**首版五组（9.3 是 A/B/C/G/I），H01 命中成立也只能进 L2，
   不进 L1 分母

### P-12 · `line = 0` 的语义按规则类型分叉

- **结论**（用户 2026-10-11 认可并补了边界）：

  | 规则类型 | `line = 0` | 处置 |
  | -------- | ---------- | ---- |
  | **缺失型**（判某文件/目录不存在） | "不适用" | **不降级**，`file` 填期望路径，证据是缺失本身 |
  | **存在型**（判代码里的东西） | "找不到行号" | **必须降级 `unverified`** + `confidence=low` |

- **理由**：缺失型根本不可能有行号；若不豁免，置信度最高的那 5 条 L1 会全被降成 unverified，
  与 7.2 表里 B01=B/H、C01=B/H 直接矛盾。反过来，存在型拿 `line=0` 冒充定位证据同样是错的
- **配套修正**：A03 改用**存根定义行号**、C05 改用 **hook 的 `language:` 行号**
  （`scan/hooks.py` 的解析开始记录行号）—— 它们本来给不出行号，修完就能给，不必降级
- **扩展已批准并改为封闭清单**（P-16）：新增 `LINE_NA_RULES = {"G01", "G02", "G07"}`
  （整文件型：`G01` `.git` 目录、`G02` 已跟踪大文件、`G07` 已跟踪产物）。
  **两个清单都封闭**：新增规则默认不在清单内，要加入必须写明理由；
  其余任何规则 `line = 0` 一律降 unverified。守在用例
  `test_line_na_exemption_is_a_closed_list`（遍历全部规则逐条验），
  不封闭的话"实现偷懒"就能自证豁免，7.1 原则 2 会被架空

### P-16 · `line = 0` 的豁免是封闭清单

- **结论**：豁免只覆盖两个**封闭**集合 —— `MISSING_TYPE_RULES`（判"不存在"，6 条）
  与 `LINE_NA_RULES`（判"整个文件/目录"，3 条：G01/G02/G07）。其余任何规则 `line = 0`
  一律降 `unverified` + `confidence=low`
- **理由**（用户裁定）：**判据是"规则判的对象不是某一行"，不是"懒得找行号"**。
  不封闭的话，任何实现得偷懒的规则都能自证豁免，7.1 原则 2 直接架空
- **强制手段**：`test_line_na_exemption_is_a_closed_list` 遍历规则表逐条验；
  清单本身也被断言字面值，改动必须同时改测试（等于强制写理由）

### P-14 · `class` 的判据：缺东西 = engineering，值对不上 = config

- **结论**：B01 / B03 / C01 / C02 / C04 / C05 / C06 从 `config` 改为 **`engineering`**；
  G01/G02/G03/G05/G07 也归 engineering；**只有 G04**（`.gitignore` 某行写法不对）留 `config`
- **理由**（用户发现）：v1 的 `by_class` 曾是 `{"config": 5}`，而基线 K-01~K-05 标的是
  `engineering` —— 10.6 的「工程化召回率 = L1命中∩engineering / L1总数∩engineering」
  分子分母恒为 0，**这一列永久失效**，且不报错、测试全过、数字看着正常
- **条款**：`design-v2.md` 7.3 新增的 class 判据表
- **实测确认**：修完 v1 `by_class = {"engineering": 5}`、自审计 `{"engineering": 1}`；
  recall 的工程化召回率 5/5 = 100%
- **补充说明**：recall 侧的 class 一取基线条目的值，所以那一列一直算得出真数字；
  真正坏掉的是 `audit.json` 自己的 `by_class`，两侧对不上。现在两侧一致

### P-15 · 不覆盖声明无条件输出，Q6 信号只改措辞

- **结论**：`not_covered.statement` **永远非空**。无参考实现 → "未检测到可用的参考实现…"；
  有参考实现 → "已启用对拍（Q6），但以下类别仍不在覆盖范围内：逻辑 bug、性能回归、语义等价性…"
- **理由**（用户裁定）：旧实现写成"Q6 无信号时才输出"，自家仓库因为
  `tests/fixtures/baseline.json` 命中数值基线信号（12.11 的已知误命中）就让声明**静默消失** ——
  而静默跳过正是 1.5 最怕的毛病。**不覆盖范围不该依赖 Q6 信号的有无**：即使开了对拍，
  工具也只做数值一致性，逻辑 bug / 性能回归 / 语义等价性依然不覆盖
- **为什么不收紧 Q6 启发式**：用户指出那样修错了层面 —— 对拍类测试本来就该在 `tests/` 里，
  一刀切排除会漏掉真信号并引入新误判。修根因（声明无条件）而不是修症状（信号口径）

### P-13 · 规则配置文件格式用 TOML/JSON，不用 YAML

- **结论**：`--rules FILE` 支持 `.toml` / `.json`；YAML **不支持**，
  并把 `design-v2.md` 里两处 `rules.yaml` 一并改成 TOML（7.3 与 13.3），否则文档与实现对不上
- **理由**：12.0 要求运行时依赖尽可能为零 —— 引 PyYAML 就为了读一个开关表，不划算
  （9.2 的 CLI 帮助原文写的是 `rules.yaml`，属文档与依赖约束的冲突，取依赖约束一侧）

---

## 2.5 文档不一致登记

| # | 位置 | 问题 | 现状 |
| - | ---- | ---- | ---- |
| D-01 | `design-v2.md` 10.8 第一段 | 原文写「S1 扫描器跑一遍 v1，输出所有 finding 作为候选条目」，但 12.2 钉死 **S1 不判定、不产 finding**（finding 是 S2 产物）。按字面执行第一段 = 先实现 S2，而 S2 是第 4 步，与 13.1「第 3 步不可跳过、不可与第 4 步合并」冲突 | 实现侧已由 **P-08** 规避；10.8 正文暂未改写（改写会连带 3.2 / 12.2 / 13.1 多处），故不擅自动笔 —— 若将来调整实现顺序，先回来读这条 |

> D-01 是 2026-10-09 规划第 3 步时发现的。记在这里是因为它属于**文档内部的真实不一致**，
> 而不是实现偏差；将来有人改实现顺序、或把 S1/S2 职责再调一次，会直接踩到。

---

## 3. 未决问题

| # | 问题 | 提出时间 | 状态 | 结论/影响 |
| - | ---- | -------- | ---- | --------- |
| Q-01 | G05 → G07 要不要加抑制边（杜绝 C01→D01 式冗余） | 2026-10-09 | ✅ 已定 | **加**，见 P-07；已落 `design-v2.md` 7.4 |
| Q-02 | 本仓库是否补格式化配置（`[tool.black]` 或 `[tool.ruff.format]`） | 2026-10-09 | ✅ 已定 | **补，但排在第 4 步之后**。理由：12.11 自证原则 —— 检查别人有没有 lint 的工具自己没有 fmt 配置很尴尬；不阻塞正确性 |
| Q-03 | 第 3 步第一段的候选来源怎么取（10.8 与 12.2/13.1 冲突，见 D-01） | 2026-10-09 | ✅ 已定 | **不依赖 S2**，见 P-08 |
| Q-04 | 自审计查出本仓库仍跟踪 3 个 `.pyc`（`tests/__pycache__/`），要不要 `git rm --cached` | 2026-10-09 | ✅ 已定已做 | 用户批准 → `b034b70` 清掉（只动索引）；G07 现在对本仓库零命中 |
| Q-05 | 自审计查出 `pytest` 未在 pyproject 声明（dev 依赖缺失） | 2026-10-09 | ✅ 已定已做 | 用户批准 → `b034b70` 补 `[project.optional-dependencies].dev`（pytest/ruff/mypy） |

> ⚠️ **统计口径更正**：v1 的两条新增候选（G05、H01）经用户判定**都是误报，不入基线**。
> 因此 **L1 仍是 5 条**，10.7 的分层加法维持 **5 + 2 + 10 = 17**，不改成 7。

---

## 4. 验收证据

### 第 3 步 · 自审计（误报率测试，2026-10-09）

v1 的存在型正例已耗尽（A01/A02/D04/E01 全零命中），L1 只有 5 条缺失型送分题。
所以补一个**反向测试目标**：拿 refactor-pilot 自己当健康项目（pyproject + ruff + mypy +
pytest + git + .gitignore + 27 个测试），逐条看它报出什么。

```bash
# scan 能跑；audit 尚未实现（第 4 步），所以自审计目前 = scan + verify_recipes
python -m refactor_pilot scan /home/tachikoma/projects/refactor-pilot --out /tmp/rp-self
python run_all.py /home/tachikoma/projects/refactor-pilot /tmp/rp-self/scan.json
```

| 报出的 | 条数 | 判定 |
| ------ | ---- | ---- |
| **G07** 已跟踪的产物文件 | 3 | ✅ **真问题** —— `tests/__pycache__/*.pyc` 仍在版本库里 |
| **G06** 无 remote | 1 | ✅ 真（本地项目，符合预期） |
| **C06** 无 CI 配置 | 1 | ✅ 真（确实没有 `.github/workflows`） |
| **A04** 第一段：`pytest` × 3 | 3 | ✅ **真问题** —— 测试依赖未在 pyproject 声明（B05/D01 素材） |
| A04 第一段：`helpers` × 3 | 3 | ❌ 误报 —— 测试辅助模块，靠 pytest 的 rootdir 插入 |
| A04 第一段：`tomli` × 2 | 2 | ❌ 误报 —— 条件依赖 + pyproject 已声明（配方已加豁免） |
| A04 第三段（朴素版） | 85 | ❌ 误报 —— 不做别名/src 布局解析的后果；与第一段之差即 P-03 消掉的噪音 |
| A05 TODO 标注 | 2 | ❌ 误报 —— 命中在核查脚本自己的正则常量里 |
| C02 无 lint 配置 | 1 → 0 | ❌ 误报 —— 配方没看 pyproject 的 `[tool.ruff]`，已修 |
| H01 文档路径不存在 | 9 → 0 | ❌ 误报 —— 命中在设计文档提到的"将来产物"，已加护栏第 4 条 |

**G07 的历史演示**（这条最能说明规则为什么必要）：

```
4588cf9（第 1 步完成时）  跟踪 12 个 .pyc
0dea45e（补 .gitignore）  清掉 9 个，剩 3 个
当前 HEAD                 仍剩 3 个（tests/__pycache__/）
```

正是"事后补 `.gitignore` 不会让已跟踪文件自动消失"的活证据 —— 也就是 G07 存在的理由。
配方支持 `--rev <ref>`（`git ls-tree -r --name-only`）来查历史版本。

**结论**：自审计既报出了真问题（G07/G06/C06/测试依赖未声明），也暴露了 3 类配方缺陷
（都已修）。**不算"报 0 条"** —— 报 0 条只能证明"不吵"，不能证明有效。

### 第 4 步 · S2 审计器（2026-10-11）

- **范围**：A/B/C/G/I 五组 P0 + C06（由 P1 提升）+ 7.4 抑制边
- **新文件**：`src/refactor_pilot/audit/`（rules / findings / stubs / deps / testing /
  config / hygiene / contracts / suppress / report / `__init__`）+ `src/refactor_pilot/recall.py`
  + `tests/test_audit.py`
- **规则表**：20 条规则登记在 `audit/rules.py`，每条可被 `--rules` 关闭或改严重度

**13.3 逐条自查**（用例见 `tests/test_audit.py`，共 50 passed）

| 条款 | 用例 | 结论 |
| ---- | ---- | ---- |
| 报告开头有不覆盖声明（`q6_signals.any=false`） | `test_not_covered_statement_when_no_q6_signals` | ✅ v1 的报告首段即是声明 |
| 每条 finding 带 `file:line`；无证据降级 `unverified` | `test_every_finding_has_file_and_line` | ✅ 见 P-12 的缺失型口径 |
| **A04 过滤 `as_symbol = true`** | `test_a04_filters_as_symbol` + `test_a04_reports_missing_module` | ✅ 正反两向都测 |
| **C01 命中时 D01 被抑制（合并计一条）** | `test_c01_suppresses_d01_into_one_finding` | ✅ 40 条 → 1 条，`merged` 记 40 |
| **C06 已实现（P0）** | `test_c06_implemented` | ✅ |
| **ABC/Protocol 的存根被豁免** | `test_abc_protocol_stubs_exempt` + `test_real_stub_is_reported` | ✅ 豁免与不豁免都测 |
| **`__init__.py` 的 F401 豁免（5.2）** | `test_init_reexport_is_not_a_finding` + `..._of_missing_name_is_reported` | ✅ |
| 规则可通过配置文件关闭/改严重度 | `test_rules_file_can_disable_and_reseverity` | ✅ 用 TOML（见 P-13） |
| **7.4 四条抑制边一条不落** | `test_all_suppression_edges_from_7_4_present` | ✅ 其中 C01→A04 是解析级抑制（12.13） |
| 其余 P0 规则实测（不许只登记不生效） | A03/B02/B04/C05/G02/G03/G04 各一条用例 | ✅ 过程中揪出 2 个真 bug：`raise NotImplementedError` 的 AST 是 Name、`pytestmark = ...` 是 Assign |

**只读验证**：审计 v1 前后，`fsutil.fingerprint` 与 `git status --porcelain` 均无变化 ✅

**复审发现的 4 处修正**（用户 2026-10-11 复审，全部已改，见 P-12/P-14/P-15 + 下面 4.7）

| # | 问题 | 修正 |
| - | ---- | ---- |
| 1 | `by_class` 全是 `config` → 工程化召回率那列永久失效 | P-14：改判据为"缺东西=engineering" |
| 2 | 不覆盖声明在检出 Q6 信号时**静默消失** | P-15：声明无条件输出，信号只改措辞 |
| 3 | `line=0` 在缺失型/存在型之间没区分 | P-12 边界；A03/C05 补真实行号 |
| 4 | `design-v2.md` 7.3 / 13.3 还写着 `rules.yaml` | P-13：文档同步改成 TOML |

### 4.7 第 6 步 · 两个目标的数字（2026-10-11，修正后复跑）

```
v1 → 召回率（audit + recall）        refactor-pilot → 误报率（自审计）
  L1 总数 / 命中 : 5 / 5               报出 1 条：C06（无 CI）✅ 真问题
  工程化召回率   : 5/5 = 100%          by_class = {"engineering": 1}，blockers 0
  语义召回率     : 0/0（无样本）       不覆盖声明：措辞为"已启用对拍（Q6）…"（不再消失）
  漏报           : 0 条                期间共修掉 2 类误报：B04 条件 skip、不覆盖声明静默
  未匹配         : 0 条
  误报率(blocker): 0/2 = 0%
  by_class       : {"engineering": 5}  ← P-14 修正后
```

**自审计揪出的 B04 误报**（反向测试的又一次实证）：初版把
`pytestmark = pytest.mark.skipif(not gitutil.available(), reason="git 不可用")`
当成"全量 skip"，在自家仓库上报了 **7 条 major**。修正：只报**无条件**的
`skip` / `xfail` / `skipif(<常量真值>)`，函数装饰器不算模块级。
修正后自审计只剩 C06 一条真问题。

### 第 2 步（commit `2709813`）

```bash
ruff check .          # All checks passed!
mypy                  # Success: no issues found in 19 source files
pytest -q             # 25 passed
```

**13.2 清单逐条对照**（用例名见 `tests/test_scan.py`）

| 条款 | 用例 | 结论 |
| ---- | ---- | ---- |
| 配置全缺 → 四条 null + 各带 `degraded_reason` | `test_toolchain_all_null_with_reason_when_no_config` | ✅ cmd 与 suggested 均 null，不编造 |
| `binary_available=true` 但 off → `verified=false` | `test_binary_available_but_probe_off_keeps_verified_false` | ✅ |
| on + 实跑通过 → verified/collected/passed_files | `test_exec_probe_on_verifies_tests` | ✅ 3 用例 / 2 文件 |
| 静默零收集 → `verified=false` 且记原因 | `test_exec_probe_silent_zero_collection` | ✅ |
| 收集期错误不算用例 | `test_exec_probe_collection_error_is_not_a_case` | ✅ junitxml 里它伪装成 `<testcase>` |
| unresolved 区分 `as_symbol` | `test_unresolved_import_distinguishes_symbol` | ✅ 符号能落地就不进 unresolved |
| 测试文件只看文件名 | `test_test_file_detection_ignores_parent_dir` | ✅ `tests/conftest.py`、`tests/helpers.py` 不入选，也不进 Q2 候选 |
| worktree / archive 均可用，archive 无 `.git` 但 vcs 完整 | `test_vcs_facts_complete_for_both_snapshots`（参数化） | ✅ |
| S1 产出不含规则 ID | `test_scan_payload_has_no_rule_ids` | ✅（12.2 推论） |
| 只读：指纹不变 + git status 干净 | `tests/test_readonly.py` | ✅ |
| 产物目录默认在仓库外 | `test_default_outdir_is_outside_repo` | ✅ |

**真实目标 v1-reference 上的实跑验证**

```
工作目录 vs worktree vs archive 三处 vcs 事实一致：
  branch=main  rev_count=26  clean=true  remotes=[origin]  head_sha=c9a94716
两种快照的内容侧一致：py=22、内部边=7
只读验证：扫前后 fsutil.fingerprint 逐文件 diff 一致；
          git -C v1-reference status --porcelain 均为空
```

**自审计（本项目跑自己）**

```
constraints_file = True / CODEBUDDY.md      ← P-05 后 C04 从命中变通过
toolchain: test_cmd=pytest(unverified)  lint_cmd=ruff check .  fmt_cmd=null  type_cmd=mypy
import_graph: unresolved=8  cycles=0
```

### 第 1 步（commit `4588cf9`）

```
pytest -q  # 骨架阶段用例：只读专项 + snapshot 行为，全绿
```

---

## 4.5 方法论结论：反向测试优先（2026-10-09，用户裁定并固化）

> **反向测试（自审计）比正向测试更能暴露规则质量。**
>
> - 正向只能证明"规则能命中"，反向才能证明"规则没想错"
> - 而且**反向目标永远可得** —— 工具自己就是健康项目（pyproject + ruff + mypy +
>   pytest + git + .gitignore + 测试全绿），不需要额外找样本
> - v1 的存在型正例已经挖尽（A01/A02/D04/E01 全部零命中），
>   **不在 v1 上继续找存在型正例了**，L1 维持 5 条缺失型

**固化为策略**：

1. **每加一组规则就跑一次自审计**（`scan` + `verify_recipes` + `audit`）
2. 报出的每条都**逐条看**：是真问题，还是配方/规则自身的缺陷
3. 健康项目上的误报 = 规则质量的直接度量；报 0 条只证明"不吵"，不证明有效
4. 两个目标一起复核：v1 → 召回率（L1 应全中），refactor-pilot → 误报率

## 5. 怎么维护这份文件

- **有进度** → 改第 1 节时间线 + 落 commit，commit message 写清口头会发生不了的全部背景
- **有决策（尤其是偏离直觉的）** → 第 2 节追加一条：结论 / 理由 / 对应条款
- **有问题没定** → 第 3 节登记，别让它在聊天记录里失忆
- **某步通过验收** → 第 4 节补证据：实际命令 + 结果数字 + 真实目标上的表现

规则与新口径的**权威位置不在这里**：规则去 `design-v2.md` 7.2，实现口径去 `design-v2.md` 12。
本文件只做索引与流水，避免两处同时成为源头。
