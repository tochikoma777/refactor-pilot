# verify_recipes · 基线核查配方

基线用的**窄查询脚本**，对应 `docs/design-v2.md` 10.8 的三段法：

- **第一段**：`first_*.py` —— 允许读 `scan.json` 当**索引**（`unresolved_imports` 列表、
  模块清单），但**判定由脚本自己出**，不把事实直接当候选递给人看（P-08）
- **第三段**：`indep_*.py` —— **不读 scan.json、不 import refactor_pilot**，
  各自独立实现。独立才有意义：共用实现会让两边同错，差集就白做了

## 怎么跑

```bash
cd tests/fixtures/verify_recipes
python run_all.py <target_repo> <scan.json>            # 人读汇总
python run_all.py <target_repo> <scan.json> --out candidates.json
```

单个配方（都是 `<script> <target_repo> [scan.json]`，第一段脚本需要第二个参数）：

```bash
python indep_stubs.py /path/to/target
python first_missing_modules.py /path/to/target /path/to/scan.json
```

## 配方清单

| 脚本                        | 规则                          | 段   |
| --------------------------- | ----------------------------- | ---- |
| `first_missing_modules.py`  | A04 / D06                     | 一   |
| `first_missing_files.py`    | B01 / C01 / C02 / C04 / C06 / G05 | 一 |
| `first_cycles.py`           | D04                           | 一   |
| `indep_stubs.py`            | A01 / A02                     | 三   |
| `indep_except_pass.py`      | E01                           | 三   |
| `indep_missing_modules.py`  | A04                           | 三   |
| `indep_todo.py`             | A05                           | 三   |
| `indep_cycles.py`           | D04（DFS 三色，与第一段的 Tarjan 不同） | 三 |
| `indep_tracked_artifacts.py`| G02 / G07                     | 三   |
| `indep_init_exports.py`     | I01                           | 三   |
| `indep_readme_paths.py`     | H01                           | 三   |
| `indep_repo_hygiene.py`     | G01 / G04 / G06               | 三   |

## 输出格式

每条候选与 `baseline.json` 的 `items[]` 对齐，便于人工确认后直接搬过去：

```json
{"rule": "A01", "file": "src/x.py", "line": 42,
 "evidence": "def f(): pass", "desc": "函数 f 的函数体为空"}
```

## 三条使用约定

1. **脚本只提候选，不做最终判断** —— 真假由人确认（第二段），脚本不替人收口
2. **改了规则就要重跑** —— 否则基线过期，召回率数字失真
3. **G02 的阈值（1MB）不在设计里** —— 7.2 只给了 G01（`.git` ≥20MB）的默认值；
   这里取 1MB 是为了让"已跟踪大文件"这条真的能查得出东西，属本配方的自行取值
