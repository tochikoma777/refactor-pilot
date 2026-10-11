"""命令行入口：scan / audit / recall（9.2）。

退出码：0 成功（发现问题不算错）／1 运行时错误／2 用法错误／3 目标不支持。
默认人读输出，--json 输出机器可读，两者内容同源（12.10）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, gitutil, model, outdir, recall, s5, snapshot
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
    sub = parser.add_subparsers(dest="command", metavar="{scan,audit,recall}")

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
        "--cell",
        choices=("a", "b", "d", "e"),
        default=None,
        help="强制渲染指定格（向前跳会打 WARNING 并在 state.json 记 forced）",
    )
    p_s5.set_defaults(func=_cmd_s5)

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


def _cmd_s5(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser()
    if not target.is_dir():
        print(f"目标不是目录或不存在：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED
    if not s5.is_git_repo(target):
        print(f"目标不是 git 仓库（E 格无法判定提交）：{target}", file=sys.stderr)
        return EXIT_UNSUPPORTED

    try:
        stage = s5.plan.load(args.plan)
    except s5.plan.PlanError as exc:
        print(f"计划文件不合法：{exc}", file=sys.stderr)
        return EXIT_USAGE

    out_dir, inside_repo = outdir.resolve(target, args.out)
    if inside_repo:
        print(f"WARN 产物目录在目标仓库内：{out_dir}（见 9.5）", file=sys.stderr)

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

    for line in result.warnings:
        print(f"WARN {line}", file=sys.stderr)

    print(f"refactor-pilot · s5 阶段 {result.stage} · {result.cell} 格")
    print(f"  状态      : {result.status}")
    print(f"  {result.message}")
    if result.gate.get("reason"):
        print(f"  检查点    : {result.gate['reason']}")
    print(f"  产物目录  : {out_dir}")
    return EXIT_OK if result.status != "blocked" else EXIT_ERROR


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
