# refactor-pilot

refactor-pilot 是一个**工程化补课工具**。它能可靠发现工程化缺失；它能提示配置矛盾；它**不能**验证语义正确性——后者只有开启对拍（Q6）或人工深度审计才能覆盖。

## 首版范围

只做 **S1 扫描 + S2 审计 + recall 召回率自检**，全部**只读**。

```
refactor-pilot scan  <path> [--ref REF] [--out DIR] [--snapshot {worktree,archive}]
                            [--exec-probe {on,off}] [--json] [-v]
refactor-pilot audit <path> [--ref REF] [--out DIR] [--rules FILE] [--json]
refactor-pilot recall --audit FILE --baseline FILE [--json] [--detail]
```

退出码：`0` 成功（**发现问题不算错**）／`1` 运行时错误／`2` 用法错误／`3` 目标不支持。

## 只读是结构保证，不是承诺

- 文件访问层 `fsutil` **只导出读 API**，扫描链路上的代码拿不到写能力
- 全项目唯一的写入口是 `outdir`
- 产物默认写到**仓库之外**：`./refactor-pilot-out/<项目名>/.upgrade/`
- `--ref` 时在临时目录审计（worktree / archive），进程内绝不执行 git commit / push

## 已知局限

1. **Q6 信号会误命中**：任何名字含 `baseline/expected/golden/reference` 的数据文件都被算作"数值基线"信号。阈值是 ≥2 个信号才建议 Q6 默认开，单条误命中影响有限，但别把它当强信号。
2. **`--exec-probe on` 且无 `--ref` 时是在目标工作目录里跑被测代码**（会打印警告）。建议始终配合 `--ref`。

## 开发

```bash
source .venv/bin/activate
pytest            # 含只读专项测试：扫完 git status 干净 + 文件指纹不变
ruff check .
mypy
```
