"""S5 切片需要的**事实**：依赖状态表、契约快照、约束锚点、git 状态。

分工照 4.2③：**机械部分工具做，语义部分交 AI 只读核对**。
所以这里只做能静态确定的判断（存根检测、符号提取、导出清单），
不判"依赖是否真的够用"——那是 A 格里 AI 的活。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .. import fsutil, gitutil
from ..scan.common import is_stdlib, parse
from .plan import Stage

STUB_MARKERS = frozenset({"pass"})
SKIP_SUFFIX = ".py"


# ────────────────────────────── R1 · 依赖状态表 ──────────────────────────────


def dep_table(
    root: Path, stage: Stage, modules: dict[str, str], aliases: dict[str, str] | None = None
) -> list[dict]:
    """对 stage.writes 的每个文件：它依赖的**仓库内**模块是否已实现（R1 的机械部分）。

    状态四种，都机械可判：

    - `implemented`：依赖模块存在且不像存根
    - `stub`       ：依赖模块里存在空函数体 / NotImplementedError
    - `missing`    ：看起来该在仓库里、却找不到（有内部前缀却断链）
    - `external`   ：仓库里找不到、也没有内部前缀 → 大概率是三方依赖，本工具不判

    只有 `stub` / `missing` 会拦住 A 格；`external` 如实列出但不阻塞
    （判不了就说判不了，不拿它当失败）。
    """
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for rel in stage.writes:
        tree = parse(root / rel)
        if tree is None:
            rows.append(
                {
                    "target": rel,
                    "depends_on": "（文件不存在或语法错误）",
                    "status": "missing",
                }
            )
            continue
        for dotted in _dependencies(tree):
            key = (rel, dotted)
            if key in seen:
                continue
            seen.add(key)
            resolved = _resolve(root, rel, dotted, modules, aliases or {})
            if resolved is None:
                head = dotted.split(".")[0]
                if is_stdlib(head):
                    continue
                internal = _has_internal_prefix(root, rel, dotted, modules, aliases or {})
                status = "missing" if internal else "external"
                rows.append({"target": rel, "depends_on": dotted, "status": status})
                continue
            rows.append(
                {
                    "target": rel,
                    "depends_on": dotted,
                    "status": _file_status(root / resolved),
                }
            )
    return rows


def external_deps(root: Path, stage: Stage, modules: dict[str, str],
                   aliases: dict[str, str] | None = None) -> list[str]:
    """依赖表里状态为 `external` 的条目（本工具判不了、按三方依赖处理）。

    **R1 在这里降级** —— 所以 A 格指令块必须把它单列出来给人看，
    不能只躺在表格里（用户 2026-10-11：R1 是最高价值规则，悄悄退化无人知道）。
    """
    return sorted(
        {row["depends_on"] for row in dep_table(root, stage, modules, aliases)
         if row["status"] == "external"}
    )


def _dependencies(tree: ast.Module) -> list[str]:
    """本文件 import 的点分名（含 `from x import y` 里的 x.y）。"""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.append(node.module)
            found.extend(
                f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"
            )
    return sorted(set(found))


def _resolve(
    root: Path, rel: str, dotted: str, modules: dict[str, str], aliases: dict[str, str]
) -> str | None:
    """点分名 → 仓库内文件相对路径。三级：规范名 → 打包声明的别名 → 兄弟目录（script-style）。"""
    canonical = modules.get(dotted) or modules.get(aliases.get(dotted, ""))
    if canonical:
        return canonical
    directory = rel.rsplit("/", 1)[0] if "/" in rel else ""
    for candidate in (dotted, dotted.split(".")[0]):
        path = "/".join(filter(None, [directory, candidate.replace(".", "/")])) + ".py"
        if (root / path).is_file():
            return path
    return None


def _has_internal_prefix(
    root: Path, rel: str, dotted: str, modules: dict[str, str], aliases: dict[str, str]
) -> bool:
    parts = dotted.split(".")[:-1]
    while parts:
        if _resolve(root, rel, ".".join(parts), modules, aliases) is not None:
            return True
        parts.pop()
    return False


def _file_status(path: Path) -> str:
    tree = parse(path)
    if tree is None:
        return "missing"
    return "stub" if _has_stub(tree) else "implemented"


def _has_stub(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = [
            stmt for stmt in node.body
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
        ]
        if not body or (len(body) == 1 and isinstance(body[0], ast.Pass)):
            return True
        for stmt in body:
            if isinstance(stmt, ast.Raise):
                exc = stmt.exc
                target = exc.func if isinstance(exc, ast.Call) else exc
                name = getattr(target, "id", "") or getattr(target, "attr", "")
                if name == "NotImplementedError":
                    return True
    return False


# ────────────────────────────── R2 · 契约快照 ──────────────────────────────


def contract_snapshot(root: Path, stage: Stage, modules: dict[str, str]) -> list[dict]:
    """writes 涉及模块的公共符号 + 签名 + 是否被 `__init__` 导出（R2 数据来源）。"""
    rel_to_module = {rel: name for name, rel in modules.items()}
    exported = _exported_names(root, modules)
    rows: list[dict] = []
    for rel in stage.writes:
        module = rel_to_module.get(rel)
        tree = parse(root / rel)
        if module is None or tree is None:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                rows.append(
                    {
                        "symbol": node.name,
                        "signature": _signature(node),
                        "exported": "是" if node.name in exported else "否",
                    }
                )
    return rows


def _signature(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        return "(class)"
    try:
        return f"({ast.unparse(node.args)})"  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover - py<3.9
        return "(...)"


def _exported_names(root: Path, modules: dict[str, str]) -> set[str]:
    names: set[str] = set()
    for name, rel in modules.items():
        if not rel.endswith("__init__.py"):
            continue
        tree = parse(root / rel)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name != "*"
                )
    return names


# ────────────────────────────── R3b · 约束锚点 ──────────────────────────────


def constraints_expected(root: Path, constraints_file: str | None) -> int:
    """约束文件里 `RP:CONSTRAINT:<ID>` 的**按 ID 计数**（4.2②：不 grep 关键词）。"""
    if not constraints_file:
        return 0
    text = fsutil.read_text(root / constraints_file) or ""
    ids: set[str] = set()
    for line in text.splitlines():
        if "RP:CONSTRAINT:" not in line:
            continue
        rest = line.split("RP:CONSTRAINT:", 1)[1].strip()
        if rest:
            ids.add(rest.split()[0])
    return len(ids)


# ────────────────────────────── git 事实（只读） ──────────────────────────────


def worktree_dirty_paths(source: Path) -> list[str]:
    """`git status --porcelain` 里的改动路径。空列表 = 干净。"""
    text = gitutil.out(["status", "--porcelain"], cwd=source)
    if text is None:
        return []
    paths: list[str] = []
    for line in text.splitlines():
        if not line.strip() or len(line) < 3:
            continue
        # ⚠️ 不能用固定偏移 line[3:]：gitutil.out() 会 strip 整个 stdout，
        # 首行的前导空格会被吃掉（" M src/x.py" → "M src/x.py"），偏移就错位了
        path = line[2:].strip()
        if " -> " in path:  # rename：取新路径
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip('"'))
    return paths


def rev_count(source: Path) -> int:
    value = gitutil.out(["rev-list", "--count", "HEAD"], cwd=source)
    try:
        return int(value or 0)
    except ValueError:  # pragma: no cover
        return 0


def recent_subjects(source: Path, count: int) -> list[str]:
    """最近 count 条提交的 subject（旧 → 新），供 E 格逐字比对。"""
    if count <= 0:
        return []
    text = gitutil.out(["log", f"-{count}", "--format=%s"], cwd=source)
    if not text:
        return []
    return list(reversed(text.splitlines()))


def fingerprint(root: Path) -> dict[str, list[int]]:
    """源码指纹：A 格"运行前后零改动"的基准。"""
    return {rel: list(value) for rel, value in fsutil.fingerprint(root).items()}


# ────────────────────────────── D 格 · 证据日志解析 ──────────────────────────────

EXIT_MARKER = re.compile(r"^RP_EXIT_CODE=(\d+)\s*$", re.MULTILINE)
COLLECTED_MARKER = re.compile(r"collected (\d+) items?")
COUNTED = re.compile(r"(\d+) (passed|failed|error|errors|xfailed|xpassed|skipped)")


def parse_evidence(text: str | None) -> dict:
    """读证据日志 → 判定三要素（design-v2 14.9）。

    - `exit_code`：靠指令里的 `RP_EXIT_CODE=$?` 标记（`tee` 之后的管道退出码不可靠）
    - `collected`：用例数，**0 要判失败**（B03 那条：静默选 0 个）
    - `key_lines`：关键输出行（排除我们自己的标记行后的非空输出）

    缺任何一项 → `problems` 非空 → D 格判未完成并重发指令。
    """
    problems: list[str] = []
    if not text or not text.strip():
        return {
            "exit_code": None,
            "collected": None,
            "key_lines": [],
            "problems": ["没有证据文件（或它是空的）—— 没有证据即判定未完成（4.2①）"],
        }

    exit_match = EXIT_MARKER.search(text)
    exit_code = int(exit_match.group(1)) if exit_match else None
    if exit_code is None:
        problems.append("日志里没有 `RP_EXIT_CODE=` 标记 —— 无法判定退出码")
    elif exit_code != 0:
        problems.append(f"退出码 = {exit_code}（非 0）")

    collected = _collected(text)
    if collected is None:
        problems.append("日志里读不出用例数 —— 无法排除「静默选 0 个用例」")
    elif collected == 0:
        problems.append("收集到 0 个用例（静默零收集，等同没有测试）")

    key_lines = _key_lines(text)
    if not key_lines:
        problems.append("日志里没有任何输出行 —— 只有标记不算证据")

    return {
        "exit_code": exit_code,
        "collected": collected,
        "key_lines": key_lines[:20],
        "problems": problems,
    }


def _collected(text: str) -> int | None:
    if "no tests ran" in text:
        return 0
    match = COLLECTED_MARKER.search(text)
    if match:
        return int(match.group(1))
    counts = [int(value) for value, _ in COUNTED.findall(text)]
    return sum(counts) if counts else None


def _key_lines(text: str) -> list[str]:
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or EXIT_MARKER.match(stripped):
            continue
        kept.append(stripped)
    return kept


def evidence_path(out_dir: Path, stage_id: str) -> Path:
    """证据日志位置。

    ⚠️ 与 4.2① 的字面写法（`.upgrade/evidence/<stage>.log`）不同：按决策 #29 / 9.5，
    产物默认**仓库之外**，所以证据也必须落在仓库外 —— 否则 D 格会把日志写进被审计仓库，
    直接违反只读承诺。指令里给的是**绝对路径**。
    """
    return Path(out_dir) / "evidence" / f"{stage_id}.log"
