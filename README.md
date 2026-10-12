# refactor-pilot

refactor-pilot 是一个**工程化补课 + 流程护栏**工具。它能可靠发现工程化缺失；它能提示配置矛盾；
它把缺失型问题拆成可验收的阶段，用检查点护栏驱动「**工具规划 → AI 执行 → 工具验收**」的改造流程。
它**不能**验证语义正确性 —— 后者只有开启对拍（Q6）或人工深度审计才能覆盖。

## 不覆盖（写死，永不消失）

以下三类**不在本工具覆盖范围内**，无论是否开启对拍都一样（审计报告里也**无条件**输出这段声明，见 design-v2 1.5）：

- 逻辑与数值正确性
- 语义等价性（重构前后行为是否一致）
- 性能回归

## 用法：一条命令跑改造

```bash
refactor-pilot upgrade <path>      # 单命令驱动循环：反复运行即逐阶段推进
```

`upgrade` 反复运行时：先 `scan + audit + plan`，然后逐阶段推进 ——
**工具只生成命令与指令块，不执行被测代码 / git 写操作**（"指挥官模式"），
由 AI/人执行，工具下次运行**读证据**判定。产物默认落在**仓库之外**。

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

## 当前能力

- **只读分析**：**S1 扫描 + S2 审计 + recall 召回率自检**
- **改造切片（S5，实验）**：`A 开工核对 → B 实现 → D 实跑验收 → E 提交拆分`

**当前方向与验收口径**见 [`docs/process.md`](docs/process.md) 顶部的"原始需求 + 三门"。

## 已验证的项目（三个）

| 项目 | 类型 | 结论 |
| ---- | ---- | ---- |
| v1（`/tmp/rp-toy-v1`） | 脚本型仓库 | **缺失型补课** 4/5 关（B01 设计性跳过，脚本导入即副作用）；**存在型**正例已耗尽 |
| toy2 | 小项目 | **S5 四格 A/B/D/E 用真实 pytest 走通**，工具全程未执行被测代码 |
| nanogpt-plus（`/tmp/rp-toy-nanogpt`） | 正常包 + 真测试 + 包内假测试 | **首轮真正的"质量优化"**：`upgrade` 三阶段跑通；工具交接的 B02（6 个导入即执行副作用的假测试）由 AI 判断**移出包**（而非硬加断言）后，重跑 audit **B02 归零且无新 finding** |

## 只读是结构保证，不是承诺

- 文件访问层 `fsutil` **只导出读 API**，扫描链路上的代码拿不到写能力
- 全项目唯一的写入口是 `outdir`
- 产物默认写到**仓库之外**：`./refactor-pilot-out/<项目名>/.upgrade/`
- `--ref` 时在临时目录审计（worktree / archive），进程内绝不执行 git commit / push

## 已知局限

1. **Q6 信号会误命中**：任何名字含 `baseline/expected/golden/reference` 的数据文件都被算作"数值基线"信号。阈值是 ≥2 个信号才建议 Q6 默认开，单条误命中影响有限，但别把它当强信号。
2. **`--exec-probe on` 且无 `--ref` 时是在目标工作目录里跑被测代码**（会打印警告）。建议始终配合 `--ref`。
3. **模块名只认有证据的 source root**（打包声明 + 入口脚本所在目录）。既没有打包声明、又没有 `__main__` 守卫的脚本目录（如 `archives/`），其兄弟 import 会被标成 `third_party` —— 宁可漏判，也不把"仓库里有的模块"说成不存在（见 12.12）。
4. **测试文件只要文件名像测试就算数**（12.4 只看文件名）。因此"有断言但 `testpaths` 之外、pytest 永不收集"的死测试当前**报不出来**（候选规则 B08，见 `docs/process.md` 技术债 D-07）。

## 开发

```bash
source .venv/bin/activate
pytest            # 含只读专项测试：扫完 git status 干净 + 文件指纹不变
ruff check .
mypy
```
