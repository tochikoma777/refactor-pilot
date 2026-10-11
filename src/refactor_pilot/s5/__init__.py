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

CELLS = ("A", "B", "D", "E")
STATE_NAME = "state.json"
FINGERPRINT_LIMIT = 400  # 指纹只存前 N 个文件，避免 state.json 膨胀

def _needs_acceptance_message(stage: Stage) -> str:
    """D 格无命令时的提示。若产物是 YAML，附上**环境里探测到的解析器候选**（让人做选择题）。"""
    base = (
        "扫描里没有可用的 test_cmd，而 D 格不允许静默跳过（14.9 第 3 条）。\n"
        '请用 `--test-cmd "<你的验收命令>"` 把命令给我，我再发 D 格指令。'
    )
    yaml_targets = [w for w in stage.writes if w.endswith((".yml", ".yaml"))]
    if yaml_targets:
        candidates = facts.yaml_validator_candidates(yaml_targets[0])
        if candidates:
            listing = "\n".join(
                f"  候选 {i}（{c['parser']}）：{c['cmd']}" for i, c in enumerate(candidates, 1)
            )
            base += (
                "\n本阶段产物是 YAML；环境里探测到这些解析器，**选一条**（或自己给）：\n" + listing
            )
        else:
            base += "\n本阶段产物是 YAML，但环境里没探到可用解析器 —— 请自己给一条。"
    return base + "\n（state.json 已记 needs_manual_acceptance=true）"

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
    test_cmd: str | None = None,
) -> Result:
    """推进一格；`warnings` 由调用方传入以收集 WARNING 文本供打印。"""
    notes = warnings if warnings is not None else []
    root = Path(target).resolve()
    out_dir = Path(out_dir)

    scan = _load_scan(out_dir)
    state = _load_state(out_dir, root, stage)
    # 切到另一个阶段时清掉上一阶段的格进度，否则 current_cell 会串台
    # （多阶段计划的 per-stage 状态留到阶段 2 的驱动循环再细化）
    if state.get("current_stage") not in (None, stage.id):
        for key in (
            "current_cell",
            "create_targets",
            "a_fingerprint",
            "e_expected",
            "e_rev_count",
            "test_cmd",
        ):
            state.pop(key, None)
        state["forced"] = False
        state["current_stage"] = stage.id
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
            f"强制跳到 {requested} 格（当前 {state.get('current_cell')}）"
            "—— 绕过了前一格的检查点，state.json 已记 forced=true"
        )

    if test_cmd:
        state["test_cmd"] = test_cmd
        state["needs_manual_acceptance"] = False

    # 前置条件：切片开工（或仍在 A 格）时工作树必须干净（14.3）
    if requested == "A" and state.get("current_cell") in (None, "A"):
        dirty = facts.worktree_dirty_paths(root)
        if dirty:
            return _blocked(stage, "A", CLEAN_REQUIRED, {"dirty": dirty}, notes)

    gate = (
        _gate_for(state, root, stage, requested, modules, aliases, out_dir)
        if not forced
        else None
    )
    if gate is not None and not gate["passed"]:
        # "重发 D 格指令"（14.9 ②）：指令块要按**当前**命令重渲染，
        # 否则会停在旧命令上（改了 --test-cmd 之后尤其明显）
        if requested == "D":
            cmd = test_cmd or stage.accept_cmd or state.get("test_cmd")
            if cmd:
                _rerender_d(scan, stage, root, out_dir, cmd, notes)
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
                message=f"{' → '.join(CELLS)} 全部通过，本阶段完成",
                gate=gate,
                warnings=notes,
            )
        requested, gate, advanced = nxt, None, True

    # 前置条件 2：D 格没有可用验收命令 → 不许静默跳过（14.9 第 3 条）
    # 命令优先级：--test-cmd（人显式给）> stage.accept_cmd（plan 带的、作用域=本次改动）> state
    effective_cmd = test_cmd or stage.accept_cmd or state.get("test_cmd")
    if requested == "D" and not effective_cmd:
        state["needs_manual_acceptance"] = True
        _save_state(out_dir, state)
        return _blocked(
            stage, "D", _needs_acceptance_message(stage), {"needs_manual_acceptance": True}, notes
        )

    context = _context(scan, stage, root, out_dir, test_cmd=effective_cmd)
    text = render.instruction(requested, context)
    if requested == "D":
        outdir.ensure(out_dir / "evidence")  # 否则指令里那条 tee 会因目录不存在而失败
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


def _rerender_d(
    scan: dict, stage: Stage, root: Path, out_dir: Path, cmd: str, notes: list[str]
) -> None:
    """重发 D 格指令（fail 时用当前命令重渲染，避免指令停在旧命令上）。"""
    context = _context(scan, stage, root, out_dir, test_cmd=cmd)
    outdir.ensure(out_dir / "evidence")
    written = render.write_instruction(out_dir, stage.id, "D", render.instruction("D", context))
    notes.append(f"已重发 D 格指令：{written}")


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
    out_dir: Path,
) -> dict | None:
    """当前格可验则验；首次渲染（还没记过格）返回 None。"""
    if state.get("current_cell") != requested:
        return None
    if requested == "A":
        return _gate_a(state, root, stage, modules, aliases)
    if requested == "B":
        return _gate_b(state, root, stage)
    if requested == "D":
        return _gate_d(state, root, stage, out_dir)
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


def _gate_b(state: dict, root: Path, stage: Stage) -> dict:
    """B 格：改动范围 + 创建类目标的"已创建且非空"（D-06 门禁模型）。"""
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
    # D-06：创建类目标（生成本阶段前不在 git 跟踪里）必须"已创建且非空"。
    # 空文件会让后续 B/D 检查点形同虚设 —— 建了个空壳不算完成。
    create = [rel for rel in (state.get("create_targets") or []) if rel in writes]
    missing = [rel for rel in create if not (root / rel).is_file()]
    if missing:
        return {
            "passed": False,
            "reason": "创建类目标还不存在（本阶段应当新建）：\n  " + "\n  ".join(missing),
            "out_of_scope": [],
            "forbidden_touched": [],
            "changed": changed,
        }
    empty = [rel for rel in create if (root / rel).stat().st_size == 0]
    if empty:
        return {
            "passed": False,
            "reason": "创建了空文件（D-06：新建的产物不能是空壳）：\n  " + "\n  ".join(empty),
            "out_of_scope": [],
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


def _gate_d(state: dict, root: Path, stage: Stage, out_dir: Path) -> dict:
    """D 格：读证据日志，按**命令类型**判该要的证据（退出码 / 用例数 / 输出行）。"""
    del root
    log = facts.evidence_path(out_dir, stage.id)
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else None
    parsed = facts.parse_evidence(text, cmd=state.get("test_cmd"))
    kind = parsed["kind"]

    if parsed["problems"]:
        return {
            "passed": False,
            "reason": (
                "D 格判未完成（缺证据即未完成，4.2①）：\n  "
                + "\n  ".join(parsed["problems"])
                + f"\n→ 请重新执行 D 格指令，把输出写到 {log}"
            ),
            "evidence": str(log),
            **{key: parsed[key] for key in ("exit_code", "collected")},
        }
    if kind == "cases":
        detail = f"收集 {parsed['collected']} 个用例"
    elif kind == "lint":
        detail = "lint / 类型 / 格式化命令，退出码 0 即通过"
    else:
        detail = f"关键输出 {len(parsed['key_lines'])} 行"
    return {
        "passed": True,
        "reason": f"D 格通过：退出码 0，{detail}",
        "evidence": str(log),
        "exit_code": parsed["exit_code"],
        "collected": parsed["collected"],
        "key_lines": parsed["key_lines"],
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
    pairs = list(zip(wanted, actual_subjects))
    mismatch = [
        {"expected": want, "actual": got} for want, got in pairs if not _subject_ok(want, got)
    ]
    if mismatch:
        return {
            "passed": False,
            "reason": "提交 subject 与工具生成的不一致（R6 要求逐字一致）：\n  "
            + "\n  ".join(f"预期「{m['expected']}」实际「{m['actual']}」" for m in mismatch),
            "dirty": dirty,
            "mismatch": mismatch,
        }
    overrides = [
        {"from": _type_of(want), "to": _type_of(got)} for want, got in pairs if want != got
    ]
    if overrides:
        state["e_type_override"] = overrides  # 留痕：谁把 type 改成了什么
    reason = f"E 格通过：{len(expected)} 条提交与工具生成的一致"
    if overrides:
        reason += f"（{len(overrides)} 条 type 被人工覆盖：{overrides}）"
    return {
        "passed": True,
        "reason": reason,
        "dirty": [],
        "e_type_override": overrides,
    }


# R6 允许人工改 type，但**只能在约定白名单里改**（不许填 wip/update 之类）
ALLOWED_TYPES = ("feat", "fix", "refactor", "chore", "docs", "test", "build", "ci")


def _subject_ok(want: str, got: str) -> bool:
    """R6 的比对口径：**逐字一致**；唯一允许的差异是开头的 **type**（scope 与描述须一致）。

    理由：工具按路径推断 type，判不了语义（14.12）；E 块据此提示"修复类改动可自行改为
    fix"。既然让改，就不能反过来判它不一致 —— 但**改后的 type 必须在白名单内**。
    """
    if want == got:
        return True
    w_head, w_sep, w_tail = want.partition(":")
    g_head, g_sep, g_tail = got.partition(":")
    if not (w_sep and g_sep):
        return False
    if _scope_of(w_head) != _scope_of(g_head) or w_tail != g_tail:
        return False
    return _type_of(got) in ALLOWED_TYPES


def _type_of(subject: str) -> str:
    """取 subject 的 type token（`feat(k02): x` → `feat`）。"""
    head = subject.partition(":")[0]
    return head.split("(", 1)[0].strip()


def _scope_of(head: str) -> str:
    """取 `type(scope)` 里的 `(scope)`；没有则空串。"""
    index = head.find("(")
    return head[index:] if index != -1 else ""


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


def _context(
    scan: dict, stage: Stage, root: Path, out_dir: Path, test_cmd: str | None = None
) -> dict:
    layout = scan.get("layout") or {}
    modules = layout.get("modules") or {}
    aliases = layout.get("module_aliases") or {}
    constraints_file = (scan.get("constraints_file") or {}).get("path")
    # ⚠️ 别把参数 test_cmd 覆盖掉：它是人的显式指定，优先级高于扫描的建议值
    entry = (scan.get("toolchain") or {}).get("test_cmd") or {}
    scanned_cmd = entry.get("suggested") or entry.get("cmd")
    effective_cmd = test_cmd or scanned_cmd

    commit_plan = _commit_plan(
        facts.worktree_dirty_paths(root), stage, facts.tracked_paths(root)
    )
    return {
        "project": {
            "name": root.name,
            "path": str(root),
            "constraints_file": constraints_file,
            "no_constraints": not constraints_file,
            "test_cmd_or_placeholder": effective_cmd or "<test_cmd 未探到，请自行替换>",
        },
        "stage": {
            "id": stage.id,
            "type": stage.type,
            "writes": list(stage.writes),
            "forbidden_paths": list(stage.forbidden_paths),
            "behavior_spec": stage.behavior_spec,
            # 证据文件位置：与 D 格一致，落在**仓库外**（决策 #29 / 9.5）
            "evidence_log": str(facts.evidence_path(out_dir, stage.id)),
        },
        "facts": {
            "dep_table": facts.dep_table(root, stage, modules, aliases),
            "external_deps": facts.external_deps(root, stage, modules, aliases),
            "has_external": bool(facts.external_deps(root, stage, modules, aliases)),
            "test_cmd": effective_cmd or "",
            "test_cmd_is_suggested": _test_cmd_is_suggested(scan, effective_cmd),
            "evidence_requirement": facts.evidence_requirement(effective_cmd),
            "evidence_path": str(facts.evidence_path(out_dir, stage.id)),
            "contract_snapshot": facts.contract_snapshot(root, stage, modules),
            "constraints_expected": facts.constraints_expected(root, constraints_file),
            "commit_plan": commit_plan,
            "no_changes": not commit_plan,
            "expected_rev_count": facts.rev_count(root) + len(commit_plan),
        },
    }


def _commit_plan(changed: list[str], stage: Stage, tracked: set[str]) -> list[dict]:
    """按路径分类 commit_type，逐条生成 `git add <path>`（R5）。

    ⚠️ 简化（如实标注）：分类只看路径，不看改动语义 —— 语义分类是 S4 的活。
    **创建类**（不在 git 跟踪里）走 D-06 的表；**修改类**沿用旧的前缀规则。
    """
    if not changed:
        return []
    groups: dict[str, list[str]] = {}
    for path in sorted(changed):
        groups.setdefault(_commit_type(path, created=path not in tracked), []).append(path)

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


def _test_cmd_is_suggested(scan: dict, test_cmd: str | None) -> bool:
    """这条 test_cmd 是扫描的"建议值"（未经实跑验证）吗？"""
    entry = (scan.get("toolchain") or {}).get("test_cmd") or {}
    if not test_cmd:
        return False
    return test_cmd != entry.get("cmd") and test_cmd == entry.get("suggested")


CONFIG_SUFFIXES = (".toml", ".cfg", ".ini", ".yml", ".yaml")


def _commit_type(path: str, *, created: bool) -> str:
    """路径 → commit_type。**创建类**走 D-06 的表；**修改类**走旧前缀规则。

    创建类（D-06，`design-v2.md` 14.12）：
    | 路径 | type |
    | ---- | ---- |
    | `pyproject.toml` / `requirements*.txt` | `build` |
    | `.github/workflows/*` | `ci` |
    | `.gitignore` / `.pre-commit-config*` | `chore` |
    | `test_*.py` | `test` |
    | 其它 | `chore` |

    修改类（沿用旧前缀规则，目的是"改源码"不该落成 `chore`）：
    `docs/`→`docs`、`tests/` 或 `test_*.py`→`test`、配置文件→`chore`、其它→`feat`。
    """
    if created:
        return _created_type(path)
    return _modified_type(path)


def _created_type(path: str) -> str:
    name = Path(path).name
    if name == "pyproject.toml" or (name.startswith("requirements") and name.endswith(".txt")):
        return "build"
    if path.startswith(".github/workflows/"):
        return "ci"
    if name == ".gitignore" or name.startswith(".pre-commit-config"):
        return "chore"
    if name.startswith("test_"):
        return "test"
    return "chore"


def _modified_type(path: str) -> str:
    name = Path(path).name
    if path.startswith("docs/"):
        return "docs"
    if path.startswith("tests/") or name.startswith("test_"):
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
        # D-06：生成本阶段时**不在 git 跟踪里**的 writes → 创建类目标，
        # B 格据此判"已创建且非空"
        tracked = facts.tracked_paths(root)
        state["create_targets"] = [
            rel for rel in context["stage"]["writes"] if rel not in tracked
        ]
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
