#!/usr/bin/env python3
"""把所有核查脚本跑一遍，输出每条规则各捞到多少候选（人读），并把合并结果落到 JSON。

为什么要有这个 runner：10.8 要求定向核查**可重跑、可审计**。规则一改就要重跑，
手工一个个敲会让这件事最终没人做。

用法：
    python run_all.py <target_repo> [scan.json]
    python run_all.py <target_repo> [scan.json] --out candidates.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

# (脚本名, 是否第一段（需要 scan.json）, 覆盖的规则)
RECIPES = [
    ("first_missing_modules.py", True, "A04 / D06"),
    ("first_missing_files.py", True, "B01 / C01 / C02 / C04 / C06 / G05"),
    ("first_cycles.py", True, "D04"),
    ("indep_stubs.py", False, "A01 / A02"),
    ("indep_except_pass.py", False, "E01"),
    ("indep_missing_modules.py", False, "A04"),
    ("indep_todo.py", False, "A05"),
    ("indep_cycles.py", False, "D04"),
    ("indep_tracked_artifacts.py", False, "G02 / G07"),
    ("indep_init_exports.py", False, "I01"),
    ("indep_readme_paths.py", False, "H01"),
    ("indep_repo_hygiene.py", False, "G01 / G04 / G06"),
]


def run(script: str, argv: list[str]) -> tuple[str, list[dict] | None]:
    proc = subprocess.run(
        [sys.executable, str(HERE / script), *argv],
        capture_output=True,
        text=True,
        cwd=str(HERE),
    )
    if proc.returncode != 0:
        return proc.stderr.strip() or "非零退出", None
    try:
        return "", json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        return f"输出不是合法 JSON：{exc}", None


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--out"]
    out_path = None
    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        out_path = Path(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else None
    if not args:
        print("用法：python run_all.py <target_repo> [scan.json] [--out FILE]", file=sys.stderr)
        raise SystemExit(2)

    need_scan = any(needs for _, needs, _ in RECIPES)
    has_scan = len(args) >= 2
    if need_scan and not has_scan:
        print("缺少 scan.json：第一段脚本需要它当索引", file=sys.stderr)

    all_items: list[dict] = []
    print(f"{'脚本':<32}{'规则':<28}{'候选数'}")
    print("-" * 72)
    for script, needs_scan, rules in RECIPES:
        argv = args if not needs_scan else args[:2]
        if needs_scan and not has_scan:
            print(f"{script:<32}{rules:<28}跳过（缺 scan.json）")
            continue
        error, items = run(script, argv)
        if items is None:
            print(f"{script:<32}{rules:<28}失败：{error[:40]}")
            continue
        for item in items:
            item.setdefault("recipe", script)
            all_items.append(item)
        print(f"{script:<32}{rules:<28}{len(items)}")

    print("-" * 72)
    print(f"合计 {len(all_items)} 条候选")
    by_rule: dict[str, int] = {}
    for item in all_items:
        by_rule[item["rule"]] = by_rule.get(item["rule"], 0) + 1
    for rule in sorted(by_rule):
        print(f"  {rule}: {by_rule[rule]}")

    if out_path:
        out_path.write_text(
            json.dumps(all_items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"已写入 {out_path}")


if __name__ == "__main__":
    main()
