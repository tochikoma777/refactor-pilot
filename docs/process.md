# refactor-pilot · 进展流水

## ⚑ 原始需求（用户 2026-10-11，**不可由后续讨论覆盖**）

> 输入项目路径 → 自动全流程完成优化升级。
> 开头输入必要信息，中间决策尽量少，优化质量高。
> 目标：能端到端优化升级我其他的 toy 项目。

**每次做方向/去留判断前，先逐条对照：**

- □ 这个动作是否推进"全流程"？
- □ 这个动作是否减少"中间决策"？
- □ 截止目前，能否端到端跑一个真实项目？

**任何一项为否，就不能以"完成"为由收尾。**

---

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

- **更新于**：2026-10-11 · **提交**：见 `git log`（摘要不写死 SHA，否则它自己先过期）
- **已完成**：第 1 步骨架/CLI/快照 · 第 2 步 S1 九字段族 · 第 3 步三段法基线（结论：v1 存在型正例耗尽，L1 维持 5 条缺失型）· 第 4 步 S2 审计器 + recall 核心
- **已完成**：**S5 最小切片 + D 格**（A/B/D/E 四格）—— toy2 上用**真实 pytest** 走通全流程
- **已完成**：**首次真实试验**（`/tmp/rp-toy-v1` 跑 K-02 补 pyproject.toml）暴露"创建类任务"边界 → 五处修复（P-21~P-23），结论入 `design-v2.md` 14.11
- **已冻结的方向**：不再扩张 S2 规则（无验证材料，边际收益趋近零）；不做 S4 规划算法、问卷、完整七格状态机
- **质量门**：`ruff` / `mypy` 全绿 · `pytest 94 passed`
- **规则库现状**：v1 召回 5/5（**全是缺失型送分题**，10.7 早已预警）· 自审计误报 1 条（C06 真问题）
- **待你确认**：无（五处修复已批准并落地）
- **下一步**：**等用户判断"创建类任务边界"意味着什么** —— 这是 S4/S5 完整版动工前必须先想清的问题（`design-v2.md` 14.11）
- **技术债**：D-02（D 格 R4）**已还清**；余下 D-03（C 格）、D-04（F 格）、D-05（R2 反向查）、**D-06（创建类任务的门禁模型待定，S4/S5 前必须还）**

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
| **S5 切片** | A 只读核对 / B 实现 / **D 实跑验收** / E 提交拆分 | ✅ 已完成（toy2 真实 pytest 走通） | 本轮 | 2026-10-11 |

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

### P-17 · S5 最小切片的设计与六处补充

- **结论**（用户批准并补充）：只做 A / B / E 三格，规格落在 `design-v2.md` 第 14 节。六处补充：
  1. `--plan` 加 `schema_version`（首版=1），缺字段**报错并指明缺哪个**
  2. `writes[]` 明确"相对 target 根、**不支持 glob**"（glob 会让 B 格越界判定变模糊）
  3. `--cell` 强制向前跳 → **打印 WARNING + `state.json.forced = true`**（绕过门禁不该静默，
     同 `--exec-probe` 的道理）；重跑当前格/回退不警告
  4. **【必须修】开工前工作树必须干净** —— B 格判据是"改动路径全在 `writes` 内"，
     开工前就有未提交改动会被判越界而误报阻塞（决策 8 早有此规矩，切片漏了）；
     这也是 A 格"运行前后零改动"有基准的前提
  5. E 格边界：无改动 → 输出"无需提交"，不输出空 `git add`；**subject 逐字一致、body 允许自由**
  6. toy 测试再加一个分支：**`writes` 非空却零改动 → B 格判未完成**
     （"AI 说做完了但没动文件"，很常见）
- **理由**：三格是 v2 项目里被反复验证有效的部分（依赖闭合检查、命名核对、提交拆分），
  能立刻看出工具有没有用；而 v1 的存在型正例已耗尽，继续加审计规则没有验证材料
- **条款**：`design-v2.md` 第 14 节（含 14.6 切片验收清单、14.7 已知缺口）

### P-19 · D 格（实跑验收 R4）落地：五条约束

- **结论**（用户裁定，规格见 `design-v2.md` 14.9）：
  ① **只生成命令不执行** —— `{ <test_cmd> 2>&1; echo "RP_EXIT_CODE=$?"; } | tee <log>`，
  人/AI 执行、工具下次读日志判定。理由：`scan --exec-probe` 默认 off 就是"工具不执行被测代码"，
  D 格自己跑测试就自相矛盾。**人执行 + 工具读证据 = 指挥官模式**
  ② **判定三要素**：退出码 / 用例数（0 个算失败）/ 关键输出行；缺一即未完成、无证据文件即重发指令
  ③ **无可用 test_cmd 不许静默跳过**：标 `needs_manual_acceptance` 并阻塞，提示人用 `--test-cmd` 给命令
  ④ **每个检查点必须配"故意让它失败"的用例**（见 P-20）
  ⑤ **`external` 降级必须显式列在指令块里**（A 块单列一节），不能只躺在日志里 ——
  R1 是最高价值规则，悄悄退化无人知道
- **两处对 4.2① 字面写法的必要偏离**（已在代码注明）：
  证据日志放**仓库外**（决策 #29/9.5 要求产物在仓库外，按字面写会污染被审计仓库）；
  命令里加 `RP_EXIT_CODE=$?` 标记（`tee` 之后的管道退出码不可靠）
- **条款**：`design-v2.md` 14.3 D 行 / 14.9 / 14.10

### P-20 · 规矩：每个检查点必须配"故意让它失败"的用例

- **结论**：新增任何检查点，必须同时交一条**故意失败**的用例；`design-v2.md` 14.10 列了清单
- **理由**（用户，第四次踩到同类问题）：**只测通过路径测不出失效**。
  A 格 `dep_table`、`--cell` 向前跳、B 格越界都出现过"看起来在工作、其实永远通过"的风险
- **执行**：现有检查点的反向用例已补齐（A 格存根 / A 格零改动 / B 格越界 / B 格禁改 / B 格零改动 /
  D 格四种 / E 格三种 / 向前跳要警告且回退不警告 / 渲染铁律）

### P-18 · 技术债登记：D 格必须补（D-02）

- **结论**：S5 切片不做 D 格（实跑验收 R4）可以，但**真实使用前必须补**
- **理由**（用户）：**D 格是 R1–R10 里漏检代价最大的一条** ——
  "AI 说做完了但测试挂了"这种失败，只有 D 格能抓住
- **执行顺序**：**本切片过关后第一个要加的模块就是它**
- **条款**：`design-v2.md` 14.7

### P-21 · A 格区分"新建文件"与"依赖缺失"（git 事实推断，**不加** `creates`）

- **结论**：目标文件**不在 `git ls-files` 里、磁盘也不存在** → 判为新建，**不产 `missing` 行**。
  判据来自 git 事实自动推断，**不加 `creates` 字段**
- **理由**（用户）：加字段等于让 plan 作者多一个要填对的东西，写错的后果和现在一样严重
  （写成 `writes` 就又卡死）；**能从事实推断的就不该让人声明** —— 决策 6 的直接应用
- **问题来源**：真实试验（v1 clone 跑 K-02 补 pyproject.toml）A 格把"待创建的目标"当成缺失依赖，
  门禁卡死；强跳 `--cell b` 才能走，但强跳绕过 R1，等于门白设
- **条款**：`design-v2.md` 14.11 第 1 条
- **防回归**：`test_a_cell_allows_creating_a_new_file`（正）、
  `test_a_cell_still_blocks_when_target_has_syntax_error`（反，别把真问题也放过）

### P-22 · D 格按**命令类型**决定证据要求（**不加** `--expect`）

- **结论**：`pytest`/`unittest` → 要用例数（0 个算失败）；`ruff`/`mypy`/`flake8` 等 →
  只要退出码 0；其它命令 → 退出码 0 + 至少一行非空输出。判据来自**命令本身**
- **理由**（用户）：人只给命令，不额外声明期望 —— 这才是傻瓜式；`--expect` 等于又让人声明
- **问题来源**：真实试验里 D 格的"用例数"是 pytest 形状的，任何非测试命令（lint / TOML 校验 /
  import smoke）都凑不出用例数 → D 格永远判未完成，哪怕命令成功
- **条款**：`design-v2.md` 14.11 第 2 条
- **防回归**：`test_d_lint_command_only_needs_exit_zero`（+非 0 反向）、
  `test_d_generic_command_needs_an_output_line`（+有输出则通过）、
  `test_d_instruction_renders_command_specific_requirement`

### P-23 · 三处文案/一致性修复

- **结论**：① 收尾消息改 `A → B → D → E`（旧实现写死"A → B → E"，漏了 D）；
  ② B 格证据协议统一到**仓库外绝对路径**（旧写 `.upgrade/evidence/<id>.log`，与 D 格自相矛盾），
  去掉不可执行的占位命令；③ 去掉重复 `WARN WARNING`（CLI 已加 `WARN ` 前缀，文案不再自带）
- **理由**：都是"工具判了但人看不懂"的实例，真实试验中逐条发现
- **条款**：`design-v2.md` 14.11（现象小节）

### P-24 · 工程规矩：任何"修改"必须验证真的改到了 **【必须遵守】**

- **结论**：写进 `CODEBUDDY.md` —— `str.replace` 之后**断言替换计数 > 0**；
  AST / 正则匹配后**断言命中数 > 0**；新增规则/检查点后**配一个"故意失败"的用例**
- **理由**（用户）：**这是第五次同类问题** —— A02（`Name` vs `Call`）、B04（`Assign` vs `Expr`）、
  `dep_table` 缺解析、`--cell` 向前跳、以及本轮 `str.replace` 用 `"message":` 去匹配 `message=`
  **静默没匹配上**。共同模式：**代码静默地没生效，测试却全过**
- **条款**：`CODEBUDDY.md` 工程规矩一节

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

### 技术债（不是缺陷，但真实使用前必须还）

| # | 债 | 影响 | 触发条件 |
| - | -- | ---- | -------- |
| ~~D-02~~ | ~~D 格（实跑验收 R4）未实现~~ | ✅ **已还清**（2026-10-11）：R4 的漏检代价最大，已实现并 toy2 实测 | — |
| D-03 | C 格（R7 阈值实测）未实现 | 数值类改动没有实测阈值与余量 | 需要 Q6/阈值场景时 |
| D-04 | F 格（R8/R9 push 与网络失败）未实现 | 推送到远端失败时无重试指引 | 需要发布流程时 |
| D-05 | R2 的 D 格反向查（4.1，warn 不 block）未实现 | 新增顶层符号超出契约快照时无提示 | 随 D 格一起补 |
| **D-06** | **创建类任务的门禁模型未定** | 对"新建文件"任务，R1/R2 无从发力，门禁目前只做了"放行 + 记录"；**边界含义未想清** | **S4/S5 完整版动工前必须定**（见 `design-v2.md` 14.11） |

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

### D 格（R4）验收 + toy2 端到端实测（2026-10-11）

**D 格判定三要素的用例**（`tests/test_s5.py`）

| 条款 | 用例 | 结论 |
| ---- | ---- | ---- |
| 无 test_cmd → 不许静默跳过 | `test_d_cell_blocks_without_test_cmd` | ✅ 标 `needs_manual_acceptance` 且**不渲染 D 块** |
| 无证据文件 → 未完成 + 重发指令 | `test_d_cell_blocks_when_evidence_missing` | ✅ |
| 退出码非 0 | `test_d_cell_blocks_on_nonzero_exit` | ✅ |
| 零用例（静默零收集） | `test_d_cell_blocks_on_zero_collected` | ✅ |
| 只有标记没有输出 | `test_d_cell_blocks_when_log_has_no_output` | ✅ |
| 三要素齐 → 通过 | `test_d_cell_passes_with_complete_evidence` | ✅ |

**反向用例补齐**（14.10 规矩，故意失败路径）

`test_a_cell_blocks_when_sources_drift`（A 格零改动）、`test_b_cell_blocks_on_forbidden_path`、
`test_e_cell_blocks_on_wrong_commit_count`、`test_e_cell_blocks_when_worktree_dirty`、
`test_rerun_current_cell_does_not_warn`（重跑不警告）、
`test_a_instruction_lists_external_deps_explicitly`（external 降级必须显式）

**toy2 端到端（真实 pytest，工具全程未执行被测代码）**

```
① scan → ② s5 渲染 A → ③ s5 推进到 B → ④ 改 acme/core.py
   （中途故意改了 tests/ → 被 B 格**禁改路径**拦下，回退后继续）
⑤ s5 --test-cmd "<venv>/bin/python -m pytest -q" → 渲染 D 格
⑥ 我扮演 AI 执行 D 指令 → 证据日志：1 passed / RP_EXIT_CODE=0
⑦ s5 → D 通过，推进到 E（逐条 git add + 工具生成的 subject）
⑧ 照抄 subject 提交 → s5 → done「A → B → D → E 全部通过，本阶段完成」
```

**过程中修掉的 3 个真 bug**

1. **`--test-cmd` 永远不生效**：`_context` 里参数被扫描的建议值覆盖（`test_cmd = ...suggested...`），
   指令块里永远是 `pytest` 而不是人指定的命令。参数改名 + 显式优先级（人 > 扫描建议）
2. **`tee` 因目录不存在失败**：渲染 D 格时没建 `<out>/evidence/`，AI 照抄命令必然写不进日志
3. **拦下时不重发指令**：D 格 fail 时指令块停在旧命令上；现在 fail 会用当前命令重渲染

### 真实试验（v1 clone）+ 五处修复验收（2026-10-11）

**试验**：`/tmp/rp-toy-v1`（v1 的 clone 副本）跑 **K-02 补 pyproject.toml**
（`writes = ["pyproject.toml"]`）。

结论引用（`design-v2.md` 14.11，**原样保留**）：

> 工具在改已有 Python 时最亮（R1 依赖闭合 + R2 契约快照都满血）。但新建非 Python 文件时，
> 两个核心价值同时归零，偏偏门禁在这情形下是错的。

**修复前的卡点**（原始输出）：

```
A 格 → blocked：依赖闭合核对未通过：存在未实现的依赖（R1）。
        pyproject.toml → （文件不存在或语法错误）(missing)
```

必须 `--cell b` 强跳（WARNING + `forced=true`）才能继续。

**修复后同一任务**（无需任何强跳）：

```
① s5             → rendered  A
② s5             → advanced  A 通过（依赖闭合、零改动）→ B
③ 建 pyproject    → advanced  B 通过（untracked 文件判定正确）→ D
④ 执行 D 命令      → advanced  D 通过（1 passed / RP_EXIT_CODE=0）→ E
⑤ 逐字照抄提交     → done      A → B → D → E 全部通过，本阶段完成
```

| 修复 | 验收 |
| ---- | ---- |
| ① A 格 create-file（git 事实推断） | 正反用例 + 真实 v1 上 A 格首次即通过 |
| ② D 格按命令类型 | 测试 / lint / 普通三类正反用例；D 块按命令渲染要求 |
| ③ done 消息含 D | `test_done_message_lists_all_four_cells` + 实测 |
| ④ B 格证据协议统一仓库外绝对路径 | 与 D 格一致，去掉了不可执行的占位命令 |
| ⑤ 去重复 WARN | 实测输出 `WARN 强制跳到…` |
| ⑥ CODEBUDDY 工程规矩 | 已写入 `CODEBUDDY.md` |
| ⑦ 结论入档 | 本条 + `design-v2.md` 14.11 |

**顺带确认**：untracked 文件解析（`?? pyproject.toml` → `pyproject.toml`）在删除 / 修改 /
未跟踪 / 嵌套四类混合下均正确 —— 与 `line[3:]` 那个 bug 属同类风险，**未复发**。

`ruff` / `mypy` 全绿 · `pytest 94 passed`

### S5 最小切片 · 第 14 节验收（2026-10-11）

新文件：`src/refactor_pilot/s5/`（`plan` / `facts` / `render` / `__init__`）+ `tests/test_s5.py`（13 个用例）

**14.6 清单逐条对照**

| 条款 | 用例 | 结论 |
| ---- | ---- | ---- |
| A→B→E 连续推进，每步最多进一格 | `test_three_cells_advance_one_step_at_a_time` | ✅ |
| 三份指令块零未渲染占位符（渲染铁律） | `test_instructions_have_no_unrendered_placeholders` + `test_render_refuses_leftover_placeholder` | ✅ 渲染器遇到残留 `{{}}` 直接报错 |
| 分支① A 格 `stub` → 拦下 | `test_a_cell_blocks_on_stub_dependency` | ✅ 且 A 块里如实列出 stub 行 |
| 分支② B 格越界 → 拦下 | `test_b_cell_blocks_out_of_scope_change` | ✅ |
| 分支③ **B 格 write 非空却零改动** | `test_b_cell_blocks_when_writes_nonempty_but_nothing_changed` | ✅ |
| 分支④ E 格 subject 不一致 → 拦下 | `test_e_cell_blocks_on_subject_mismatch` | ✅ |
| 工作树不干净 → 停在 A 之前 | `test_dirty_worktree_blocks_at_start` | ✅ |
| E 格无改动 → "无需提交" | `test_e_cell_says_no_changes_needed` | ✅ 模板走 `no_changes` 分支，不输出空 `git add` |
| `--cell` 向前跳 → WARNING + `forced=true` | `test_forced_cell_jump_warns_and_records` | ✅ |
| plan 缺字段指明缺哪个 / 不支持 glob | `test_plan_errors_point_at_the_missing_field` | ✅ |
| 只读：目标源码指纹不变 | `test_s5_does_not_touch_target_sources` | ✅ |

**toy 项目实测（`/tmp/toy`，扁平包布局）**

```
① 首次运行      → rendered  A 格；A 块里含真实路径与依赖表
② 再跑一次      → advanced   A 通过（依赖闭合、零改动）→ 渲染 B 格
③ 改 writes 内文件 → advanced  B 通过 → 渲染 E 格（含 git add 逐条 + subject）
④ 用自写 subject 提交 → blocked（退出码 1）「预期 feat(s1): 更新 acme/core.py 实际 feat: 我自己写的消息」
⑤ 逐字照抄 subject  → done    「A → B → E 三格全部通过，本阶段完成」
```

**过程中修掉的 3 个真 bug**（都是"不留神就会静默错"的那类）

1. `git status --porcelain` 的路径解析用了固定偏移 `line[3:]`，但 `gitutil.out()` 会 strip
   整个 stdout，首行前导空格被吃掉 → 路径变成 `rc/acme/core.py` → B 格误判越界。
   改用 `line[2:].strip()`
2. `dep_table` 不做别名/兄弟解析，`from acme.schema import ...` 解析不到 → A 格漏检存根。
   现在三级解析（规范名 → 打包声明别名 → 兄弟目录），并区分 `missing` 与 `external`
   （判不了的三方依赖如实列 `external`，**不阻塞**）
3. 首次运行时 `state.current_cell` 是 `None`，"向前跳"判不出来 → `--cell e` 不打 WARNING。
   现在把 `None` 视作 A 格

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
