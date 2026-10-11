"""S2 审计器：把 S1 的事实变成判定（12.2）。

**S1 只采集事实，S2 才做判定** —— 这条边界的意义在于：S1 的产出可以被单独测
（"事实采集对不对"），S2 的产出也可以被单独测（"判定对不对"）。

判定完成后按 7.4 施加抑制边，最后套上不覆盖声明（1.5）。
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import fsutil, gitutil
from . import config as config_rules
from . import contracts, deps, hygiene, stubs, suppress, testing
from .findings import FindingFactory
from .rules import Rules

# 已知工具链该忽略的缓存目录 → 对应"用没用这个工具"的证据文件名
OPTIONAL_EVIDENCE = {
    ".mypy_cache/": ("mypy.ini", ".mypy.ini"),
    ".ruff_cache/": ("ruff.toml", ".ruff.toml"),
    ".pytest_cache/": ("pytest.ini",),
    ".tox/": ("tox.ini",),
}


def collect_all(
    *,
    root: str | os.PathLike[str],
    source: str | os.PathLike[str],
    scan: dict,
    rules: Rules | None = None,
) -> dict:
    """产出 audit.json 的内容（不含顶层元信息）。"""
    root_path = Path(root)
    source_path = Path(source)
    rules = rules or Rules.default()
    factory = FindingFactory(rules)

    findings: list[dict] = []

    # A 组
    findings += stubs.check(root_path, scan, factory)
    findings += deps.check(root_path, scan, factory)
    # B 组
    findings += testing.check(root_path, scan, factory)
    # C 组
    findings += config_rules.check(root_path, scan, factory)
    # G 组
    findings += hygiene.check(root_path, source_path, scan, factory, git=gitutil.available())
    # I 组
    findings += contracts.check(root_path, scan, factory)

    findings = suppress.apply(findings, rules)
    findings.sort(key=lambda f: (_severity_rank(f["severity"]), f["rule"], f["file"], f["line"]))

    counts = _counts(findings)
    return {
        "rules": _rule_states(rules),
        "findings": findings,
        "counts": counts,
        "not_covered": _not_covered(scan, rules),
        "warnings": _warnings(scan),
    }


def _severity_rank(severity: str) -> int:
    from .rules import BLOCKER, MAJOR, MINOR, UNVERIFIED

    return {BLOCKER: 0, MAJOR: 1, MINOR: 2, UNVERIFIED: 3}.get(severity, 4)


def _counts(findings: list[dict]) -> dict:
    by_severity: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    by_class: dict[str, int] = {}
    for item in findings:
        by_severity[item["severity"]] = by_severity.get(item["severity"], 0) + 1
        by_rule[item["rule"]] = by_rule.get(item["rule"], 0) + 1
        by_class[item["class"]] = by_class.get(item["class"], 0) + 1
    return {
        "total": len(findings),
        "by_severity": dict(sorted(by_severity.items())),
        "by_rule": dict(sorted(by_rule.items())),
        "by_class": dict(sorted(by_class.items())),
        "blockers": sum(1 for f in findings if f["severity"] == "blocker"),
    }


def _rule_states(rules: Rules) -> dict:
    return {
        rid: {
            "enabled": rules.enabled(rid),
            "severity": rules.severity(rid),
            "confidence": rules.confidence(rid),
            "class": rules.klass(rid),
        }
        for rid in sorted(rules.entries)
    }


def _not_covered(scan: dict, rules: Rules) -> dict:
    """1.5 的不覆盖声明：**无条件输出，永远不消失**（P-15，用户 2026-10-11 裁定）。

    原先写成"Q6 无信号时才输出"，结果自家仓库因为 `tests/fixtures/baseline.json`
    命中了数值基线信号（12.11 的已知误命中），声明就静默消失了 ——
    而"静默跳过"恰恰是 1.5 最怕的毛病。**不覆盖范围不该依赖 Q6 信号的有无**：
    即使 Q6 开启，工具也只做了数值对拍，逻辑 bug / 性能回归 / 语义等价性依然不覆盖。

    信号只决定**措辞**。
    """
    signals = scan.get("q6_signals") or {}
    has_reference = bool(signals.get("any"))
    return {
        "q6_reference_available": has_reference,
        "q6_signals": signals.get("signal_count", 0),
        "statement": _statement(has_reference),
        "categories": [
            "逻辑与数值正确性",
            "语义等价性（重构前后行为是否一致）",
            "性能回归",
            *([c for c in _unimplemented_groups(rules)]),
        ],
    }


def _statement(has_reference: bool) -> str:
    common = (
        "  - 逻辑与数值正确性\n"
        "  - 语义等价性（重构前后行为是否一致）\n"
        "  - 性能回归"
    )
    if has_reference:
        return (
            "已启用对拍（Q6），但以下类别仍不在本工具覆盖范围内：\n"
            f"{common}\n"
            "对拍只覆盖与参考实现的数值一致性。"
        )
    return (
        "本项目未检测到可用的参考实现，语义正确性无法自动验证。\n"
        "以下类别不在本工具覆盖范围内：\n"
        f"{common}\n"
        "需通过人工深度审计或提供参考实现（Q6）后重跑。"
    )


def _unimplemented_groups(rules: Rules) -> list[str]:
    """把"登记了但没实现"的规则组列进不覆盖声明 —— 少报的不等于没有问题。"""
    names = {
        "D": "依赖声明与闭合（D 组不在首版五组内）",
        "E": "代码卫生（E 组不在首版五组内）",
        "F": "构建可复现与配置矛盾（F 组不在首版五组内）",
        "H": "文档一致性（H 组不在首版五组内）",
        "J": "运行入口与脚本（J 组不在首版五组内）",
    }
    seen: list[str] = []
    for rid, entry in sorted(rules.entries.items()):
        group = entry["group"]
        if group in names and rid not in rules.implemented() and names[group] not in seen:
            seen.append(names[group])
    return seen


def _warnings(scan: dict) -> list[str]:
    out: list[str] = []
    for key, entry in (scan.get("toolchain") or {}).items():
        reason = entry.get("degraded_reason")
        if isinstance(reason, str) and reason:
            out.append(f"{key}: {reason}")
    return out


def git_dir_bytes(source: Path) -> int:
    """G01 用：`.git` 目录体积（只读统计，不写任何东西）。"""
    git_path = source / ".git"
    if git_path.is_file():
        try:
            return git_path.stat().st_size
        except OSError:
            return 0
    if not git_path.is_dir():
        return 0
    total = 0
    for path in fsutil.iter_files(git_path):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total
