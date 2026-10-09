"""命令行入口：scan / audit / recall（9.2）。

退出码：0 成功（发现问题不算错）／1 运行时错误／2 用法错误／3 目标不支持。
默认人读输出，--json 输出机器可读，两者内容同源（12.10）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, gitutil, model, outdir, snapshot
from .model import EXIT_ERROR, EXIT_OK, EXIT_UNSUPPORTED, EXIT_USAGE


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
        help="是否实跑测试/lint 命令探测（默认 off，见 12.5；第 2 步启用）",
    )
    p_scan.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_scan.add_argument("-v", "--verbose", action="store_true", help="打印细节")
    p_scan.set_defaults(func=_cmd_scan)

    p_audit = sub.add_parser("audit", help="S2 审计：按规则包判定（第 4 步）")
    p_audit.add_argument("path", help="目标项目路径")
    p_audit.add_argument("--ref", default=None, help="审计该 git ref 的快照")
    p_audit.add_argument("--out", default=None, help="产物目录")
    p_audit.add_argument("--rules", default=None, help="规则配置文件（rules.yaml）")
    p_audit.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    p_audit.set_defaults(func=_cmd_audit)

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
    out_dir, inside_repo = outdir.resolve(target, args.out)
    if inside_repo:
        print(f"WARN 产物目录在目标仓库内：{out_dir}（默认应在仓库之外，见 9.5）", file=sys.stderr)

    try:
        with snapshot.create(target, args.ref, kind) as snap:
            snapshot_root = str(snap.root)
            payload = model.new_scan_payload(
                path=str(target.resolve()),
                ref=snap.ref,
                snapshot_kind=snap.kind,
                resolved_sha=snap.resolved_sha,
            )
            # 字段族由 S1 填充（第 2 步）
            written = outdir.write_json(out_dir, "scan.json", payload)
    except RuntimeError as exc:
        print(f"快照失败：{exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_scan(payload, written, verbose=args.verbose, snapshot_root=snapshot_root)
    return EXIT_OK


def _cmd_audit(args: argparse.Namespace) -> int:
    print("audit 尚未实现（实现顺序第 4 步，见 13.1）", file=sys.stderr)
    return EXIT_ERROR


def _cmd_recall(args: argparse.Namespace) -> int:
    print("recall 尚未实现（实现顺序第 5 步，见 13.1）", file=sys.stderr)
    return EXIT_ERROR


def _print_scan(payload: dict, written: Path, *, verbose: bool, snapshot_root: str) -> None:
    tgt = payload["target"]
    ref = f"{tgt['ref']} → {tgt['resolved_sha']}" if tgt["ref"] else "（工作目录）"
    print("refactor-pilot · scan")
    print(f"  目标      : {tgt['path']}")
    print(f"  快照      : {tgt['snapshot']}")
    print(f"  引用      : {ref}")
    print(f"  产物目录  : {written.parent}")
    print(f"  产出      : {written.name}")
    if verbose:
        print(f"  快照根    : {snapshot_root}")
