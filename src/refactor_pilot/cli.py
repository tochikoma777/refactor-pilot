"""命令行入口：scan / audit / recall / plan / s5（9.2）。

退出码：0 成功（发现问题不算错）／1 运行时错误／2 用法错误／3 目标不支持。
默认人读输出，--json 输出机器可读，两者内容同源（12.10）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, autoplan, gitutil, model, outdir, recall, s5, snapshot
from .audit import collect_all as audit_all
from .audit.report import render as render_audit
from .audit.rules import Rules
from .model import EXIT_ERROR, EXIT_OK, EXIT_UNSUPPORTED, EXIT_USAGE
from .scan import collect_all


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="refactor-pilot",
        description="只读重构审计工具：S1 扫描 + S2 审计 + 召回率自检",
    )
    parser.add_argument("--version", action="version", version=f"refactor-pilot {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="{scan,audit,recall,plan,s5,upgrade}")

    p_scan = sub.add_parser("scan", help="S1 扫描：只采集事实，不做判定")
    p_scan.add_argument("path", help="目标项目路径")
    p_scan.add_argument("--ref", default=None, help="审计该 git ref 的快照（默认审计当前工作目录）")
    p_scan.add_argument("--out", default=None, help="产物目录（默认在仓库之外，见 9.5）")
    p_scan.add_argument(
        "--snapshot",
        choices=snapshot.KINDS,
        default=snapshot.WORKTREE,
        help="快照方式（默认 worktree；archive 对源仓库零写入）",
    )
    p_scan.add_argument(
        "--exec-probe",
        choices=("on", "off"),
        default="off",
        help="是否实跑测试/lint 命令探测（默认 off，见 12.5）",
    )
    p_scan.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_scan.add_argument("-v", "--verbose", action="store_true", help="打印细节")
    p_scan.set_defaults(func=_cmd_scan)

    p_audit = sub.add_parser("audit", help="S2 审计：按规则包判定")
    p_audit.add_argument("path", help="目标项目路径")
    p_audit.add_argument("--ref", default=None, help="审计该 git ref 的快照")
    p_audit.add_argument("--out", default=None, help="产物目录（默认在仓库之外，见 9.5）")
    p_audit.add_argument(
        "--snapshot",
        choices=snapshot.KINDS,
        default=snapshot.WORKTREE,
        help="快照方式（默认 worktree；archive 对源仓库零写入）",
    )
    p_audit.add_argument(
        "--exec-probe",
        choices=("on", "off"),
        default="off",
        help="是否实跑测试命令探测（B03 静默零收集依赖它，默认 off，见 12.5）",
    )
    p_audit.add_argument(
        "--rules",
        default=None,
        help="规则配置文件（.toml / .json）：可关规则或改严重度",
    )
    p_audit.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_audit.set_defaults(func=_cmd_audit)

    p_plan = sub.add_parser(
        "plan",
        help="阶段 1：把 audit 的缺失型 finding 自动转成 plan（S4-lite，见 design-v2 14.13）",
    )
    p_plan.add_argument("path", help="目标项目路径")
    p_plan.add_argument("--ref", default=None, help="审计该 git ref 的快照")
    p_plan.add_argument("--out", default=None, help="产物目录（默认在仓库之外，见 9.5）")
    p_plan.add_argument(
        "--snapshot", choices=("worktree", "archive"), default="worktree", help="快照方式（12.7）"
    )
    p_plan.add_argument("--rules", default=None, help="规则配置文件（.toml / .json）")
    p_plan.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_plan.set_defaults(func=_cmd_plan)

    p_s5 = sub.add_parser(
        "s5", help="S5 最小切片：A 只读核对 / B 实现 / E 提交拆分（见 design-v2 第 14 节）"
    )
    p_s5.add_argument("path", help="目标项目路径（必须是 git 仓库）")
    p_s5.add_argument("--plan", required=True, help="手写单阶段计划（JSON，见 14.2）")
    p_s5.add_argument("--out", default=None, help="产物目录（默认在仓库之外，见 9.5）")
    p_s5.add_argument(
        "--test-cmd",
        default=None,
        help="D 格的验收命令（扫描探不到时必须由人给出，见 14.9）",
    )
    p_s5.add_argument(
        "--stage-id",
        default=None,
        help="多阶段计划里选择要推进的阶段（缺省：接着 state.json 里的阶段，否则第一个）",
    )
    p_s5.add_argument(
        "--cell",
        choices=("a", "b", "d", "e"),
        default=None,
        help="强制渲染指定格（向前跳会打 WARNING 并在 state.json 记 forced）",
    )
    p_s5.set_defaults(func=_cmd_s5)

    p_up = sub.add_parser(
        "upgrade",
        help="阶段 2：单命令驱动循环 —— 反复运行即逐阶段推进到全部完成（AI 执行指令）",
    )
    p_up.add_argument("path", help="目标项目路径（必须是 git 仓库）")
    p_up.add_argument("--ref", default=None, help="首次生成 plan 时用该 ref 快照")
    p_up.add_argument("--out", default=None, help="产物目录（默认在仓库之外，见 9.5）")
    p_up.add_argument(
        "--snapshot", choices=("worktree", "archive"), default="worktree", help="快照方式（12.7）"
    )
    p_up.add_argument("--rules", default=None, help="规则配置文件（.toml / .json）")
    p_up.add_argument(
        "--test-cmd", default=None, help="覆盖当前阶段的验收命令（缺省用 plan 的 accept_cmd）"
    )
    p_up.add_argument(
        "--cell", choices=("a", "b", "d", "e"), default=None, help="调试用：强制推进某一格"
    )
    p_up.set_defaults(func=_cmd_upgrade)

    p_recall = sub.add_parser("recall", help="召回率自检（第 5 步）")
    p_recall.add_argument("--audit", required=True, help="audit.json 路径")
    p_recall.add_argument("--baseline", required=True, help="baseline.json 路径")
    p_recall.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_recall.add_argument("--detail", action="store_true", help="列出命中与漏报明细")
    p_recall.set_defaults(func=_cmd_recall)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"运行时错误：{exc}", file=sys.stderr)
        return EXIT_ERROR


def _cmd_scan(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser()
    if not target.is_dir():
        print(f"目标不是目录或不存在：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED
    if args.ref is not None:
        if not gitutil.available():
            print("git 不可用，无法创建 --ref 快照", file=sys.stderr)
            return EXIT_UNSUPPORTED
        if not gitutil.is_repo(target):
            print(f"目标不是 git 仓库，无法解析 --ref {args.ref}：{target}", file=sys.stderr)
            return EXIT_UNSUPPORTED

    kind = args.snapshot if args.ref is not None else snapshot.WORKDIR
    exec_probe = args.exec_probe == "on"
    if exec_probe and args.ref is None:
        # 12.5：实跑只在快照目录里做；没有 --ref 就是在目标工作目录里跑被测代码
        print("WARN 未指定 --ref：实跑将在目标工作目录中进行（会执行目标代码），"
              "建议配合 --ref（见 12.5）", file=sys.stderr)

    out_dir, inside_repo = outdir.resolve(target, args.out)
    if inside_repo:
        print(f"WARN 产物目录在目标仓库内：{out_dir}（默认应在仓库之外，见 9.5）", file=sys.stderr)

    try:
        with snapshot.create(target, args.ref, kind) as snap:
            payload = _build_scan(target, args, snap)
            written = outdir.write_json(out_dir, "scan.json", payload)
    except RuntimeError as exc:
        print(f"快照失败：{exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_scan(payload, written, verbose=args.verbose)
    return EXIT_OK


def _build_scan(target: Path, args: argparse.Namespace, snap: snapshot.Snapshot) -> dict:
    """在快照上下文里采集 S1 事实（audit 也复用这一段，保证两者同源）。"""
    meta = model.new_scan_payload(
        path=str(target.resolve()),
        ref=snap.ref,
        snapshot_kind=snap.kind,
        resolved_sha=snap.resolved_sha,
    )
    families = collect_all(
        root=snap.root,
        source=target,  # git 事实始终取自源仓库（12.7）
        exec_probe=getattr(args, "exec_probe", "off") == "on",
    )
    # 字段族在前、degraded / warnings 在后，与 12.9 的契约顺序一致
    for name in ("degraded", "warnings"):
        meta.pop(name, None)
    return {**meta, **families}


def _cmd_audit(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser()
    if not target.is_dir():
        print(f"目标不是目录或不存在：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED
    if args.ref is not None and not gitutil.is_repo(target):
        print(f"目标不是 git 仓库，无法解析 --ref {args.ref}：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED

    kind = args.snapshot if args.ref is not None else snapshot.WORKDIR
    if args.exec_probe == "on" and args.ref is None:
        print("WARN 未指定 --ref：实跑将在目标工作目录中进行（12.5）", file=sys.stderr)

    out_dir, inside_repo = outdir.resolve(target, args.out)
    if inside_repo:
        print(f"WARN 产物目录在目标仓库内：{out_dir}（默认应在仓库之外，见 9.5）", file=sys.stderr)

    rules = Rules.default()
    try:
        rules.load_overrides(args.rules)
    except (OSError, ValueError) as exc:
        print(f"规则配置文件读不了：{exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        with snapshot.create(target, args.ref, kind) as snap:
            scan_payload = _build_scan(target, args, snap)
            written_scan = outdir.write_json(out_dir, "scan.json", scan_payload)
            payload = model.new_audit_payload(
                path=str(target.resolve()),
                ref=snap.ref,
                snapshot_kind=snap.kind,
                resolved_sha=snap.resolved_sha,
                scan_path=str(written_scan),
            )
            payload.update(
                audit_all(root=snap.root, source=target, scan=scan_payload, rules=rules)
            )
            written = outdir.write_json(out_dir, "audit.json", payload)
            outdir.write_text(out_dir, "audit.md", render_audit(payload))
    except RuntimeError as exc:
        print(f"快照失败：{exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_audit(payload, written)
    return EXIT_OK


def _cmd_plan(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser()
    if not target.is_dir():
        print(f"目标不是目录或不存在：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED
    if args.ref is not None and not gitutil.is_repo(target):
        print(f"目标不是 git 仓库，无法解析 --ref {args.ref}：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED

    out_dir, inside_repo = outdir.resolve(target, args.out)
    if inside_repo:
        print(f"WARN 产物目录在目标仓库内：{out_dir}（默认应在仓库之外，见 9.5）", file=sys.stderr)

    rc, plan_payload, written = _build_plan_files(target, args, out_dir)
    if rc != EXIT_OK or plan_payload is None or written is None:
        return rc

    if args.json:
        print(json.dumps(plan_payload, ensure_ascii=False, indent=2))
    else:
        _print_plan(plan_payload, written)
    return EXIT_OK


def _print_plan(payload: dict, written: Path) -> None:
    stages = payload["stages"]
    print("refactor-pilot · plan（阶段 1：audit finding → 阶段）")
    print(f"  阶段数    : {len(stages)}")
    for stage in stages:
        print(f"    - {stage['id']} → {', '.join(stage['writes'])}")
    for item in payload.get("skipped", []):
        print(f"    （跳过 {item['rule']}：{item['reason']}）")
    print(f"  产出      : {written}")


def _pick_stage(stages: list[s5.plan.Stage], out_dir: Path, stage_id: str | None) -> s5.plan.Stage:
    """多阶段计划里选要推进的阶段：显式 `--stage-id` > state.json 里的 > 第一个。"""
    if stage_id:
        for stage in stages:
            if stage.id == stage_id:
                return stage
        options = ", ".join(stage.id for stage in stages)
        raise s5.plan.PlanError(f"--stage-id={stage_id} 不在计划里（可选：{options}）")

    state_path = Path(out_dir) / "state.json"
    if state_path.is_file():
        try:
            current = json.loads(state_path.read_text(encoding="utf-8")).get("current_stage")
        except (OSError, json.JSONDecodeError):
            current = None
        for stage in stages:
            if stage.id == current:
                return stage
    return stages[0]


def _cmd_s5(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser()
    if not target.is_dir():
        print(f"目标不是目录或不存在：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED
    if not s5.is_git_repo(target):
        print(f"目标不是 git 仓库（E 格无法判定提交）：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED

    out_dir, inside_repo = outdir.resolve(target, args.out)
    if inside_repo:
        print(f"WARN 产物目录在目标仓库内：{out_dir}（见 9.5）", file=sys.stderr)

    try:
        stage = _pick_stage(s5.plan.load_stages(args.plan), out_dir, args.stage_id)
    except s5.plan.PlanError as exc:
        print(f"计划文件不合法：{exc}", file=sys.stderr)
        return EXIT_USAGE

    notes: list[str] = []
    try:
        result = s5.run(
            target=target,
            stage=stage,
            out_dir=out_dir,
            cell=args.cell,
            warnings=notes,
            test_cmd=args.test_cmd,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except s5.render.RenderError as exc:
        print(f"渲染失败（拒绝输出指令块）：{exc}", file=sys.stderr)
        return EXIT_ERROR

    _emit_s5(result, out_dir)
    return EXIT_OK if result.status != "blocked" else EXIT_ERROR


def _emit_s5(result: s5.Result, out_dir: Path) -> None:
    for line in result.warnings:
        print(f"WARN {line}", file=sys.stderr)
    print(f"refactor-pilot · s5 阶段 {result.stage} · {result.cell} 格")
    print(f"  状态      : {result.status}")
    print(f"  {result.message}")
    if result.gate.get("reason"):
        print(f"  检查点    : {result.gate['reason']}")
    print(f"  产物目录  : {out_dir}")


def _cmd_upgrade(args: argparse.Namespace) -> int:
    """阶段 2：单命令驱动循环 —— 反复运行本命令即逐格推进到全部阶段完成。

    工具仍**不执行**被测代码 / git 写操作；执行者是 AI。人只需给一次路径。
    """
    target = Path(args.path).expanduser()
    if not target.is_dir():
        print(f"目标不是目录或不存在：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED
    if not s5.is_git_repo(target):
        print(f"目标不是 git 仓库（E 格无法判定提交）：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED

    out_dir, inside_repo = outdir.resolve(target, args.out)
    if inside_repo:
        print(f"WARN 产物目录在目标仓库内：{out_dir}（见 9.5）", file=sys.stderr)

    plan_path = Path(out_dir) / "plan.json"
    if not ((Path(out_dir) / "scan.json").is_file() and plan_path.is_file()):
        print("（首次运行：先 scan + audit + 自动生成 plan）")
        rc, _, _ = _build_plan_files(target, args, out_dir)
        if rc != EXIT_OK:
            return rc

    try:
        stages = s5.plan.load_stages(plan_path)
    except s5.plan.PlanError as exc:
        print(f"计划文件不合法：{exc}", file=sys.stderr)
        return EXIT_USAGE

    done = list(_read_state(out_dir).get("done_stages") or [])
    remaining = [stage for stage in stages if stage.id not in done]
    if not remaining:
        print(f"refactor-pilot · upgrade · 全部 {len(stages)} 个阶段已完成 ✅")
        for stage in stages:
            print(f"    ✓ {stage.id} → {', '.join(stage.writes)}")
        return EXIT_OK

    stage = remaining[0]
    print(f"refactor-pilot · upgrade（已完成 {len(done)}/{len(stages)}，当前阶段 {stage.id}）")
    notes: list[str] = []
    try:
        result = s5.run(
            target=target,
            stage=stage,
            out_dir=out_dir,
            cell=args.cell,
            warnings=notes,
            test_cmd=args.test_cmd,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except s5.render.RenderError as exc:
        print(f"渲染失败（拒绝输出指令块）：{exc}", file=sys.stderr)
        return EXIT_ERROR

    _emit_s5(result, out_dir)
    if result.status == "done":
        state = _read_state(out_dir)
        done = list(state.get("done_stages") or [])
        if stage.id not in done:
            done.append(stage.id)
        state["done_stages"] = done
        outdir.write_json(Path(out_dir), "state.json", state)
        print(f"  → 阶段 {stage.id} 完成（{len(done)}/{len(stages)}）；再运行一次进入下一阶段")
    return EXIT_OK if result.status != "blocked" else EXIT_ERROR


def _read_state(out_dir: Path) -> dict:
    path = Path(out_dir) / "state.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _build_plan_files(
    target: Path, args: argparse.Namespace, out_dir: Path
) -> tuple[int, dict | None, Path | None]:
    """scan + audit + autoplan，落 scan.json / audit.json / plan.json。"""
    rules = Rules.default()
    try:
        rules.load_overrides(getattr(args, "rules", None))
    except (OSError, ValueError) as exc:
        print(f"规则配置文件读不了：{exc}", file=sys.stderr)
        return EXIT_USAGE, None, None

    ref = getattr(args, "ref", None)
    kind = getattr(args, "snapshot", "worktree") if ref is not None else snapshot.WORKDIR
    try:
        with snapshot.create(target, ref, kind) as snap:
            scan_payload = _build_scan(target, args, snap)
            written_scan = outdir.write_json(out_dir, "scan.json", scan_payload)
            audit_payload = model.new_audit_payload(
                path=str(target.resolve()),
                ref=snap.ref,
                snapshot_kind=snap.kind,
                resolved_sha=snap.resolved_sha,
                scan_path=str(written_scan),
            )
            audit_payload.update(
                audit_all(root=snap.root, source=target, scan=scan_payload, rules=rules)
            )
            outdir.write_json(out_dir, "audit.json", audit_payload)
            plan_payload = autoplan.build(audit_payload)
            written = outdir.write_json(out_dir, "plan.json", plan_payload)
    except RuntimeError as exc:
        print(f"快照失败：{exc}", file=sys.stderr)
        return EXIT_ERROR, None, None
    return EXIT_OK, plan_payload, written


def _cmd_recall(args: argparse.Namespace) -> int:
    try:
        result = recall.run(args.audit, args.baseline)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"读不了 audit/baseline：{exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(recall.render(result, detail=args.detail))
    return EXIT_OK


def _print_audit(payload: dict, written: Path) -> None:
    counts = payload["counts"]
    print("refactor-pilot · audit")
    print(f"  目标      : {payload['target']['path']}")
    print(f"  产出      : {written.name} / audit.md（产物目录 {written.parent}）")
    print(f"  发现      : {counts['total']} 条，其中 blocker {counts['blockers']} 条")

    statement = payload["not_covered"].get("statement")
    if statement:  # 永远都有（P-15），只是措辞随 Q6 信号变化
        print("")
        for line in statement.splitlines():
            print(f"  {line}")

    print("")
    for item in payload["findings"]:
        location = f"{item['file']}:{item['line']}" if item["line"] else item["file"]
        print(f"  [{item['severity']:<10}] {item['rule']} {location}")
        print(f"               {item['evidence'][:96]}")
        for merged in item.get("merged") or []:
            print(f"               合并计入 {merged['rule']} × {merged['count']}（7.4 抑制）")


def _print_scan(payload: dict, written: Path, *, verbose: bool) -> None:
    """人读输出。与 --json **同源**：都从 payload 出，不做第二套计算（12.10）。"""
    tgt = payload["target"]
    lang = payload["lang"]
    lay = payload["layout"]
    vcs = payload["vcs"]

    print("refactor-pilot · scan")
    print(f"  目标      : {tgt['path']}")
    _print_snapshot_line(tgt)
    print(f"  语言      : {lang['primary'] or '未知'}，{lang['file_count']} 个文件")
    print(f"  包根      : {', '.join(lay['package_roots']) or '（无）'}"
          + (f"，模块 {lay['module_count']} 个" if lay["module_count"] else ""))
    if lay["entry_points"]:
        print(f"  入口      : {', '.join(lay['entry_points'])}")
    if lay["config_files"]:
        print(f"  配置文件  : {', '.join(lay['config_files'])}")

    print("  toolchain :")
    for key, entry in payload["toolchain"].items():
        cmd = entry["cmd"] or entry["suggested"]
        state = "已实跑" if entry["verified"] else "未验证"
        detail = cmd or "探测不到命令"
        extra = ""
        if entry["verified"] and entry["collected"] is not None:
            extra = f"，收集 {entry['collected']} 个用例"
        print(f"    {key:<9}: {detail}  [{state}{extra}]")
        if entry["source"]:
            print(f"              来源 {entry['source']}")
        if entry["passed_files"]:
            print(f"              通过文件 {', '.join(entry['passed_files'])}")
        if entry["degraded_reason"] and (verbose or not entry["verified"]):
            print(f"              {entry['degraded_reason']}")

    print(f"  vcs       : {'git' if vcs['has_git'] else '非 git 仓库'}"
          + (_git_detail(vcs) if vcs["has_git"] else ""))
    if vcs["remotes"]:
        print(f"    remote   : {', '.join(vcs['remotes'])}")

    graph = payload["import_graph"]
    print(f"  import 图 : {graph['node_count']} 节点 / {graph['edge_count']} 内部边"
          f" / {graph['unresolved_count']} 未解析 / {graph['cycle_count']} 个环")

    signals = payload["q6_signals"]
    advice = "建议默认开启 Q6" if signals["suggest_q6_default_on"] else "不建议默认开启"
    print(f"  Q6 信号   : {signals['signal_count']} 个"
          f"（阈值 {signals['threshold']}，{advice}）")

    print(f"  约束文件  : {payload['constraints_file']['path'] or '无'}"
          f"（候选 {', '.join(payload['constraints_file']['candidates'])}）")
    print(f"  pre-commit: {'存在' if payload['hooks']['precommit_exists'] else '无'}")

    candidates = payload["q2_candidates"]
    if candidates:
        print("  Q2 候选   :")
        for cand in candidates:
            mark = "✓" if cand["preselect"] else " "
            probe = "（需先实跑）" if cand["needs_probe"] else ""
            print(f"    [{mark}] {cand['path']}{probe}  理由：{cand['reason']}")

    if payload["degraded"]:
        print(f"  degraded  : {', '.join(payload['degraded'])}")
    for line in payload["warnings"]:
        print(f"  WARN      : {line}")
    print(f"  产物目录  : {written.parent}")
    print(f"  产出      : {written.name}")


def _print_snapshot_line(tgt: dict) -> None:
    if tgt["ref"]:
        sha = (tgt["resolved_sha"] or "")[:8]
        tail = f"（{tgt['ref']} → {sha}）"
    else:
        tail = "（工作目录）"
    print(f"  快照      : {tgt['snapshot']}{tail}")


def _git_detail(vcs: dict) -> str:
    cleanliness = "干净" if vcs["clean"] else "有未提交改动"
    return f"，分支 {vcs['branch']}，{cleanliness}，{vcs['rev_count']} 个提交"
