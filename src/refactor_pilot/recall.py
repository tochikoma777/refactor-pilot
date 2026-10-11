"""召回率自检（1.6 / 10.x）。

匹配口径**必须事先定死且可重跑**（10.3），所以做成子命令而不是临时脚本：
手算的数字既不可复现也不可审计，而召回率是这里唯一能证明规则库有效的手段。

- **绝不按 line 匹配**：机械阶段跑完 line 必然位移，按 line 匹配会让召回率假性下降
- **绝不做模糊匹配**：模糊匹配能让数字好看，但那是自己给自己打分
- **缺失型 vs 存在型分叉**（10.3）：缺失型只按 `rule_id` 匹配
- **分层统计，绝不混合**（10.5）：L2 / L3 不进分母
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ENGINEERING = "engineering"
SEMANTIC = "semantic"


def run(audit_path: str, baseline_path: str) -> dict:
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))

    findings = audit.get("findings") or []
    implemented = _implemented_rules(audit)
    repo_files = _repo_files(audit)

    layers: dict[str, list[dict]] = {"L1": [], "L2": [], "L3": [], "L4": []}
    hits: list[dict] = []
    misses: list[dict] = []

    for entry in baseline.get("items") or []:
        rules = list(entry.get("detectable_by") or [])
        layer = _layer(entry, rules, implemented)
        layers[layer].append(entry)

        if layer not in ("L1", "L4"):
            continue
        match = _find_match(entry, rules, findings, repo_files)
        if match is None:
            misses.append({"id": entry.get("id"), "rules": rules, "desc": entry.get("desc")})
        else:
            hits.append({
                "id": entry.get("id"),
                "rule": match["rule"],
                "class": entry.get("class", ENGINEERING),
                "audited_file": f"{match['file']}:{match['line']}",
            })

    unmatched = _unmatched(findings, hits)
    return {
        "l1_total": len([e for e in layers["L1"]]),
        "l1_hit": len(hits),
        "engineering": _ratio(hits, layers, ENGINEERING),
        "semantic": _ratio(hits, layers, SEMANTIC),
        "l2": [{"id": e.get("id"), "rules": e.get("detectable_by"), "desc": e.get("desc")}
               for e in layers["L2"]],
        "l3": [{"id": e.get("id"), "desc": e.get("desc")} for e in layers["L3"]],
        "l4": [{"id": e.get("id"), "desc": e.get("desc")} for e in layers["L4"]],
        "misses": misses,
        "unmatched": unmatched,
        "false_positive_rate": _false_positive_rate(findings, unmatched),
    }


def _implemented_rules(audit: dict) -> set[str]:
    states = audit.get("rules") or {}
    return {rid for rid, state in states.items() if state.get("enabled")}


def _layer(entry: dict, rules: list[str], implemented: set[str]) -> str:
    """10.5 的分层：先分覆盖范围，再决定进不进分母。"""
    if not rules:
        return "L3"
    if str(entry.get("baseline_confidence", "")).lower() == "low":
        return "L4"
    if any(rule in implemented for rule in rules):
        return "L1"
    return "L2"


def _repo_files(audit: dict) -> set[str] | None:
    """借 audit.json 指向的 scan.json 拿到仓库文件清单（判缺失型要用）。"""
    path = (audit.get("target") or {}).get("scan")
    if not path or not Path(path).is_file():
        return None
    try:
        scan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    layout = scan.get("layout") or {}
    files = set(layout.get("modules") or {}.values())
    files.update(layout.get("test_files") or [])
    return files


def _is_missing_type(entry: dict, repo_files: set[str] | None) -> bool:
    """缺失型 = 判的是"某文件/目录不存在"（10.3 的分叉）。"""
    if entry.get("line") is not None:
        return False
    file = entry.get("file") or ""
    if not file or file.endswith("/") or "(" in file or " / " in file:
        return True
    if repo_files is not None:
        return file not in repo_files
    return False


def _find_match(entry: dict, rules: list[str], findings: list[dict],
                repo_files: set[str] | None) -> dict | None:
    missing_type = _is_missing_type(entry, repo_files)
    for finding in findings:
        if finding["rule"] not in rules:
            continue
        if missing_type:
            return finding  # 缺失型：只按 rule_id 匹配
        if _same_file(entry, finding) and _same_evidence(entry, finding):
            return finding
    return None


def _same_file(entry: dict, finding: dict) -> bool:
    wanted = entry.get("file") or ""
    aliases = [wanted, *(entry.get("file_aliases") or [])]
    return finding.get("file") in aliases


def _same_evidence(entry: dict, finding: dict) -> bool:
    expected = entry.get("evidence") or entry.get("desc") or ""
    if not expected:
        return True
    return _normalize(expected) in _normalize(finding.get("evidence") or "")


def _normalize(text: str) -> str:
    """去注释、去空白、统一大小写（10.3 的归一化比对）。"""
    stripped = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", "", stripped).lower()


def _unmatched(findings: list[dict], hits: list[dict]) -> list[dict]:
    """工具报了但基线没有 —— 未必是误报，交人定性（10.2 陷阱 2）。"""
    matched_ids = {hit["rule"] for hit in hits}
    matched_files = {hit["audited_file"] for hit in hits}
    out: list[dict] = []
    for finding in findings:
        key = f"{finding['file']}:{finding['line']}"
        if finding["rule"] in matched_ids and key in matched_files:
            continue
        out.append({
            "rule": finding["rule"],
            "severity": finding["severity"],
            "file": finding["file"],
            "line": finding["line"],
            "evidence": finding["evidence"],
        })
    return out


def _ratio(hits: list[dict], layers: dict, klass: str) -> dict:
    total = sum(1 for e in layers["L1"] if e.get("class", ENGINEERING) == klass)
    hit = sum(1 for h in hits if h["class"] == klass)
    return {"hit": hit, "total": total, "rate": (hit / total) if total else None}


def _false_positive_rate(findings: list[dict], unmatched: list[dict]) -> dict:
    """建议只统计 blocker 级，避免人工量爆炸（10.6）。"""
    blockers = [f for f in findings if f["severity"] == "blocker"]
    unmatched_blockers = [u for u in unmatched if u["severity"] == "blocker"]
    return {
        "scope": "blocker",
        "hit": len(unmatched_blockers),  # 与召回率同一套键，方便统一渲染
        "total": len(blockers),
        "rate": (len(unmatched_blockers) / len(blockers)) if blockers else None,
    }


def render(result: dict, *, detail: bool) -> str:
    lines = [
        "refactor-pilot · recall",
        f"  L1 总数 / 命中 : {result['l1_total']} / {result['l1_hit']}",
        f"  工程化召回率   : {_fmt(result['engineering'])}",
        f"  语义召回率     : {_fmt(result['semantic'])}（预期为 0：本工具不覆盖）",
        f"  L2（规则未实现）: {len(result['l2'])} 条 —— 是待办不是缺陷",
        f"  L3（无规则）   : {len(result['l3'])} 条 —— 不覆盖声明的依据",
        f"  漏报（L1 未命中）: {len(result['misses'])} 条",
        f"  未匹配（工具多报）: {len(result['unmatched'])} 条",
        f"  误报率（blocker）: {_fmt(result['false_positive_rate'])}",
    ]
    if detail:
        for label, key in (("L2", "l2"), ("L3", "l3"), ("漏报", "misses"), ("未匹配", "unmatched")):
            rows = result[key]
            if not rows:
                continue
            lines.append("")
            lines.append(f"  {label}明细：")
            for row in rows:
                lines.append("    - " + json.dumps(row, ensure_ascii=False))
    return "\n".join(lines)


def _fmt(metric: dict) -> str:
    rate = metric.get("rate")
    if rate is None:
        return f"{metric['hit']}/{metric['total']}（无样本，不适用）"
    return f"{metric['hit']}/{metric['total']} = {rate:.0%}"
