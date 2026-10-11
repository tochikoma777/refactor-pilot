"""S5 最小切片：A（只读核对）/ B（实现）/ E（提交拆分）三格。

定位（design-v2 14 节）：**工具产指令 → AI 改代码 → 工具读事实判检查点**。
工具不执行任何 git 写操作，也不改目标仓库源码；产物只落 `.upgrade/`（默认仓库外）。

三条全局规矩：

- **单步推进**（3.1）：一次运行最多推进一格；检查点不过就停在原格输出诊断
- **渲染铁律**（6.2）：未解析占位符 → 拒绝输出（见 render.py）
- **`--cell` 向前跳必须留痕**（14.5）：打印 WARNING + `state.forced = true`

前置条件（14.3）：**进入 A 格前工作树必须干净**。否则 B 格会把开工前的改动
当成越界，误报阻塞。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import gitutil, outdir
from . import facts, render
from .plan import Stage

CELLS = ("A", "B", "E")
STATE_NAME = "state.json"
FINGERPRINT_LIMIT = 400  # 指纹只存前 N 个文件，避免 state.json 膨胀

CLEAN_REQUIRED = (
    "开工前目标工作树必须干净（决策 8）。\n"
    "B 格的判据是「改动路径全部落在 stage.writes 内」；若开工前就有未提交改动，"
    "那些路径不在 writes 里 → 会被判越界 → 误报阻塞。\n"
    "先 `git commit` 或 `git stash` 再开工。"
)


@dataclass
class Result:
    stage: str
    cell: str
    status: str  # rendered | advanced | blocked | done
    message: str
    gate: dict = field(default_factory=dict)
    instruction: Path | None = None
    warnings: list[str] = field(default_factory=list)


def run(
    *,
    target: Path,
    stage: Stage,
    out_dir: Path,
    cell: str | None = None,
    warnings: list[str] | None = None,
) -> Result:
    """推进一格；`warnings` 由调用方传入以收集 WARNING 文本供打印。"""
    notes = warnings if warnings is not None else []
    root = Path(target).resolve()
    out_dir = Path(out_dir)

    scan = _load_scan(out_dir)
    state = _load_state(out_dir, root, stage)
    layout = scan.get("layout") or {}
    modules = layout.get("modules") or {}
    aliases = layout.get("module_aliases") or {}

    requested = (cell or state.get("current_cell") or "A").upper()
    if requested not in CELLS:
        raise ValueError(f"未知的格：{requested}（可选 {', '.join(CELLS)}）")

    forced = _is_forward_jump(requested, state.get("current_cell"))
    if forced:
        state["forced"] = True
        notes.append(
            f"WARNING 强制跳到 {requested} 格（当前 {state.get('current_cell')}）"
            "—— 绕过了前一格的检查点，state.json 已记 forced=true"
        )

    # 前置条件：切片开工（或仍在 A 格）时工作树必须干净（14.3）
    if requested == "A" and state.get("current_cell") in (None, "A"):
        dirty = facts.worktree_dirty_paths(root)
        if dirty:
            return _blocked(stage, "A", CLEAN_REQUIRED, {"dirty": dirty}, notes)

    gate = _gate_for(state, root, stage, requested, modules, aliases) if not forced else None
    if gate is not None and not gate["passed"]:
        return _blocked(stage, requested, gate["reason"], gate, notes)

    # 检查点通过且是"正常推进"（非 --cell 指定）→ 最多前进一格
    advanced = False
    if gate is not None and gate["passed"] and not cell:
        nxt = _next_cell(requested)
        if nxt == "done":
            state.update(
                {
                    "current_stage": stage.id,
                    "current_cell": "done",
                    "last_run": _now(),
                }
            )
            _save_state(out_dir, state)
            return Result(
                stage=stage.id,
                cell=requested,
                status="done",
                message="A → B → E 三格全部通过，本阶段完成",
                gate=gate,
                warnings=notes,
            )
        requested, gate, advanced = nxt, None, True

    context = _context(scan, stage, root, out_dir)
    text = render.instruction(requested, context)
    written = render.write_instruction(out_dir, stage.id, requested, text)

    _record_baseline(state, requested, root, context)
    state.update(
        {"current_stage": stage.id, "current_cell": requested, "last_run": _now()}
    )
    _save_state(out_dir, state)

    return Result(
        stage=stage.id,
        cell=requested,
        status="advanced" if advanced else "rendered",
        message=f"{'已推进到' if advanced else '已渲染'} {requested} 格：{written}",
        gate=gate or {},
        instruction=written,
        warnings=notes,
    )


def _blocked(stage: Stage, cell: str, reason: str, gate: dict, notes: list[str]) -> Result:
    return Result(
        stage=stage.id, cell=cell, status="blocked", message=reason, gate=gate, warnings=notes
    )


def _next_cell(cell: str) -> str:
    index = CELLS.index(cell)
    return CELLS[index + 1] if index + 1 < len(CELLS) else "done"


def _is_forward_jump(requested: str, current: str | None) -> bool:
    """向前跳才警告。还没开始过（current=None）视作 A 格 —— 跳到 B/E 就是向前跳。"""
    if current == "done":
        return False
    baseline = current or "A"
    return CELLS.index(requested) > CELLS.index(baseline)


# ────────────────────────────── 各格检查点 ──────────────────────────────


def _gate_for(
    state: dict,
    root: Path,
    stage: Stage,
    requested: str,
    modules: dict,
    aliases: dict,
) -> dict | None:
    """当前格可验则验；首次渲染（还没记过格）返回 None。"""
    if state.get("current_cell") != requested:
        return None
    if requested == "A":
        return _gate_a(state, root, stage, modules, aliases)
    if requested == "B":
        return _gate_b(root, stage)
    return _gate_e(state, root)


def _gate_a(state: dict, root: Path, stage: Stage, modules: dict, aliases: dict) -> dict:
    rows = facts.dep_table(root, stage, modules, aliases)
    stubs = [row for row in rows if row["status"] in {"stub", "missing"}]
    changed = _fingerprint_drift(state.get("a_fingerprint"), root)

    if stubs:
        detail = ", ".join(
            f"{row['target']} → {row['depends_on']}({row['status']})" for row in stubs
        )
        return {
            "passed": False,
            "reason": (
                "依赖闭合核对未通过：存在未实现的依赖（R1）。\n"
                f"{detail}\n"
                "→ 不要开始实现；应先插入「补实现」阶段。"
            ),
            "stubs": stubs,
            "changed": changed,
        }
    if changed:
        return {
            "passed": False,
            "reason": "A 格是只读的，但检测到源码改动（指纹与渲染时不符）：\n  "
            + "\n  ".join(changed[:10]),
            "stubs": [],
            "changed": changed,
        }
    return {"passed": True, "reason": "A 格通过：依赖闭合、且零改动", "stubs": [], "changed": []}


def _gate_b(root: Path, stage: Stage) -> dict:
    changed = facts.worktree_dirty_paths(root)
    writes = set(stage.writes)
    out_of_scope = [path for path in changed if path not in writes]
    touched = [
        path for path in changed
        if any(_under(path, item) for item in stage.forbidden_paths)
    ]

    if touched:
        return {
            "passed": False,
            "reason": "触碰了禁改路径：\n  " + "\n  ".join(touched),
            "out_of_scope": out_of_scope,
            "forbidden_touched": touched,
            "changed": changed,
        }
    if out_of_scope:
        return {
            "passed": False,
            "reason": "改动超出了本阶段的 writes：\n  "
            + "\n  ".join(out_of_scope)
            + "\n→ 要么退回这批改动，要么把它写进 plan 的 writes 再来。",
            "out_of_scope": out_of_scope,
            "forbidden_touched": [],
            "changed": changed,
        }
    if stage.writes and not changed:
        return {
            "passed": False,
            "reason": (
                "writes 非空却零改动 —— 判未完成。\n"
                "（「说做完了但没动文件」很常见；没有改动就没有可验收的东西。）"
            ),
            "out_of_scope": [],
            "forbidden_touched": [],
            "changed": [],
        }
    return {
        "passed": True,
        "reason": f"B 格通过：{len(changed)} 个改动全部落在 writes 内",
        "out_of_scope": [],
        "forbidden_touched": [],
        "changed": changed,
    }


def _gate_e(state: dict, root: Path) -> dict:
    dirty = facts.worktree_dirty_paths(root)
    expected = state.get("e_expected") or []
    baseline = state.get("e_rev_count")
    actual = facts.rev_count(root)

    if dirty:
        return {
            "passed": False,
            "reason": "E 格要求提交后工作树干净，但仍有未提交改动：\n  " + "\n  ".join(dirty),
            "dirty": dirty,
        }
    if not expected:
        return {"passed": True, "reason": "E 格通过：无需提交（渲染时工作树即干净）", "dirty": []}
    if baseline is None or actual != baseline + len(expected):
        return {
            "passed": False,
            "reason": (
                f"提交数不符：渲染时 {baseline}，"
                f"预期 {(baseline or 0) + len(expected)}，实际 {actual}"
            ),
            "dirty": dirty,
            "rev_expected": (baseline or 0) + len(expected),
            "rev_actual": actual,
        }

    wanted = [item["subject"] for item in expected]
    actual_subjects = facts.recent_subjects(root, len(expected))
    mismatch = [
        {"expected": want, "actual": got}
        for want, got in zip(wanted, actual_subjects)
        if want != got
    ]
    if mismatch:
        return {
            "passed": False,
            "reason": "提交 subject 与工具生成的不一致（R6 要求逐字一致）：\n  "
            + "\n  ".join(f"预期「{m['expected']}」实际「{m['actual']}」" for m in mismatch),
            "dirty": dirty,
            "mismatch": mismatch,
        }
    return {
        "passed": True,
        "reason": f"E 格通过：{len(expected)} 条提交与工具生成的一致",
        "dirty": [],
    }


def _under(path: str, prefix: str) -> bool:
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def _fingerprint_drift(baseline: dict | None, root: Path) -> list[str]:
    if not baseline:
        return []
    now = facts.fingerprint(root)
    drift = [rel for rel, value in now.items() if baseline.get(rel) != value]
    drift += [rel for rel in baseline if rel not in now]
    return drift


# ────────────────────────────── 上下文与状态 ──────────────────────────────


def _context(scan: dict, stage: Stage, root: Path, out_dir: Path) -> dict:
    modules = (scan.get("layout") or {}).get("modules") or {}
    constraints_file = (scan.get("constraints_file") or {}).get("path")
    test_cmd = ((scan.get("toolchain") or {}).get("test_cmd") or {}).get("suggested") or (
        (scan.get("toolchain") or {}).get("test_cmd") or {}
    ).get("cmd")

    commit_plan = _commit_plan(facts.worktree_dirty_paths(root), stage)
    return {
        "project": {
            "name": root.name,
            "path": str(root),
            "constraints_file": constraints_file,
            "no_constraints": not constraints_file,
            "test_cmd_or_placeholder": test_cmd or "<test_cmd 未探到，请自行替换>",
        },
        "stage": {
            "id": stage.id,
            "type": stage.type,
            "writes": list(stage.writes),
            "forbidden_paths": list(stage.forbidden_paths),
            "behavior_spec": stage.behavior_spec,
            "evidence_log": f".upgrade/evidence/{stage.id}.log",
        },
        "facts": {
            "dep_table": facts.dep_table(root, stage, modules),
            "contract_snapshot": facts.contract_snapshot(root, stage, modules),
            "constraints_expected": facts.constraints_expected(root, constraints_file),
            "commit_plan": commit_plan,
            "no_changes": not commit_plan,
            "expected_rev_count": facts.rev_count(root) + len(commit_plan),
        },
    }


COMMIT_TYPE_PREFIXES = (("docs/", "docs"), ("tests/", "test"))
CONFIG_SUFFIXES = (".toml", ".cfg", ".ini", ".yml", ".yaml")


def _commit_plan(changed: list[str], stage: Stage) -> list[dict]:
    """按路径分类 commit_type，逐条生成 `git add <path>`（R5）。

    ⚠️ 简化（如实标注）：分类只看路径前缀，不看改动语义 —— 语义分类是 S4 的活。
    """
    if not changed:
        return []
    groups: dict[str, list[str]] = {}
    for path in sorted(changed):
        groups.setdefault(_commit_type(path), []).append(path)

    plan: list[dict] = []
    for index, (commit_type, paths) in enumerate(sorted(groups.items()), start=1):
        plan.append(
            {
                "index": index,
                "type": commit_type,
                "paths": paths,
                "adds_block": "".join(f"git add {path}\n" for path in paths),
                # R6：subject 由工具生成，AI 逐字照抄（body 允许自由）
                "subject": f"{commit_type}({stage.id}): 更新 {_summary(paths)}",
            }
        )
    return plan


def _commit_type(path: str) -> str:
    for prefix, commit_type in COMMIT_TYPE_PREFIXES:
        if path.startswith(prefix):
            return commit_type
    if Path(path).name.startswith("test_"):
        return "test"
    if path.endswith(CONFIG_SUFFIXES) or path.startswith("."):
        return "chore"
    return "feat"


def _summary(paths: list[str]) -> str:
    return paths[0] if len(paths) == 1 else f"{len(paths)} 个文件"


def _record_baseline(state: dict, cell: str, root: Path, context: dict) -> None:
    if cell == "A":
        sample = dict(list(facts.fingerprint(root).items())[:FINGERPRINT_LIMIT])
        state["a_fingerprint"] = sample
    if cell == "E":
        state["e_rev_count"] = facts.rev_count(root)
        state["e_expected"] = [
            {"subject": item["subject"], "paths": item["paths"]}
            for item in context["facts"]["commit_plan"]
        ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_scan(out_dir: Path) -> dict:
    path = Path(out_dir) / "scan.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"找不到 {path} —— S5 切片要求先跑一次 `refactor-pilot scan <target>`"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_state(out_dir: Path, root: Path, stage: Stage) -> dict:
    path = Path(out_dir) / STATE_NAME
    state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    state.setdefault("schema_version", 1)
    state.setdefault("project_root", str(root))
    state.setdefault("current_stage", stage.id)
    state.setdefault("current_cell", None)
    state.setdefault("forced", False)
    return state


def _save_state(out_dir: Path, state: dict) -> None:
    outdir.write_json(out_dir, STATE_NAME, state)


def is_git_repo(root: Path) -> bool:
    return gitutil.available() and gitutil.is_repo(root)
