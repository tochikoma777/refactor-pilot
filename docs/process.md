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
| 进度与决策流水   | **本文件**                               |

---

## 1. 进度时间线

| 步    | 内容                              | 状态       | commit    | 日期       |
| ----- | --------------------------------- | ---------- | --------- | ---------- |
| **1** | 骨架 + CLI（三子命令桩）+ `--ref` 快照 | ✅ 已完成  | `4588cf9` | 2026-10-09 |
| —     | 补 `.gitignore` 并把误跟踪的 `.pyc` 移出版本库 | ✅ 已完成  | `0dea45e` | 2026-10-09 |
| **2** | S1 扫描器九个字段族                | ✅ 已完成  | `2709813` | 2026-10-09 |
| **3** | 三段法构建"存在型"基线             | ⬜ 未开始  | —         | —          |
| **4** | S2 审计：A/B/C/G/I 五组 P0 + C06 + 抑制 | ⬜ 未开始  | —         | —          |
| **5** | recall 子命令 + 四层分层统计       | ⬜ 未开始  | —         | —          |
| **6** | 跑出数字，决定 S4/S5 怎么走        | ⬜ 未开始  | —         | —          |

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

---

## 3. 未决问题

| # | 问题 | 提出时间 | 状态 | 影响 |
| - | ---- | -------- | ---- | ---- |
| Q-01 | **G05 → G07 要不要加抑制边**：完全没有 `.gitignore` 时 G05 已命中，G07 再逐文件报一遍属于 C01/D01 式冗余 | 2026-10-09 | ⏳ 待用户定 | 第 4 步实现 S2 前必须定死，否则报告会被冗余 finding 淹没 |
| Q-02 | 本仓库是否补格式化配置（`[tool.black]` 或 `[tool.ruff.format]`） | 2026-10-09 | ⏳ 待用户定 | 不影响工具正确性；目前自扫 `fmt_cmd = null` 是如实输出 |

---

## 4. 验收证据

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

## 5. 怎么维护这份文件

- **有进度** → 改第 1 节时间线 + 落 commit，commit message 写清口头会发生不了的全部背景
- **有决策（尤其是偏离直觉的）** → 第 2 节追加一条：结论 / 理由 / 对应条款
- **有问题没定** → 第 3 节登记，别让它在聊天记录里失忆
- **某步通过验收** → 第 4 节补证据：实际命令 + 结果数字 + 真实目标上的表现

规则与新口径的**权威位置不在这里**：规则去 `design-v2.md` 7.2，实现口径去 `design-v2.md` 12。
本文件只做索引与流水，避免两处同时成为源头。
