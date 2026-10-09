"""S1 扫描器：按字段族组装 scan.json（3.3 / 12.9）。

**S1 只采集事实，不做判定**（12.2）：产出里不会出现任何规则 ID ——
`constraints_file.exists = false` 是事实，"缺约束"是 C04 的判定。

两个位置概念不要混（12.7）：

- `root`：快照目录，**文件内容**从这里扫（worktree / archive / 工作目录）
- `source`：源仓库，**git 事实**从这里采（archive 快照里没有 `.git`）
"""

from __future__ import annotations

import os
from pathlib import Path

from . import constraints, forbidden, hooks, importer, lang, layout, signals, toolchain, vcs

# 未经证实可用的命令要进 degraded（12.6：未验证不能说成已验证）
_TOOLCHAIN_KEYS = tuple(toolchain.KEYS)


def collect_all(*, root: str | os.PathLike[str], source: str | os.PathLike[str],
                exec_probe: bool = False) -> dict:
    """产出 scan.json 的字段族部分（不含 top-level 元信息）。"""
    root_path = Path(root)
    lang_family = lang.collect(root_path)
    layout_family = layout.collect(root_path)
    vcs_family = vcs.collect(source)
    constraints_family = constraints.collect(root_path)
    hooks_family = hooks.collect(root_path)
    signals_family = signals.collect(root_path)
    toolchain_family = toolchain.collect(root_path, layout_family, exec_probe=exec_probe)
    graph = importer.build(root_path, layout_family)
    q2 = forbidden.collect(root_path, layout_family, graph, toolchain_family, signals_family)

    families = {
        "lang": lang_family,
        "layout": layout_family,
        "toolchain": toolchain_family,
        "vcs": vcs_family,
        "constraints_file": constraints_family,
        "hooks": hooks_family,
        "q6_signals": signals_family,
        "q2_candidates": q2,
        "import_graph": graph,
    }
    families["degraded"] = _degraded(families)
    families["warnings"] = _warnings(families, exec_probe=exec_probe)
    return families


def _degraded(families: dict) -> list[str]:
    out: list[str] = []
    if not families["lang"]["supported"]:
        out.append("lang")
    out.extend(key for key in _TOOLCHAIN_KEYS if not families["toolchain"][key]["verified"])
    if not families["vcs"]["has_git"]:
        out.append("vcs")
    return out


def _warnings(families: dict, *, exec_probe: bool) -> list[str]:
    """只放**非显然**的提示：四条"未实跑"这种通用降级看 degraded 就够了。"""
    out: list[str] = []
    for key, entry in families["toolchain"].items():
        reason = entry.get("degraded_reason")
        if isinstance(reason, str) and reason and reason != toolchain.PROBE_OFF_HINT:
            out.append(f"{key}: {reason}")
    if not exec_probe:
        out.append(f"{'/'.join(_TOOLCHAIN_KEYS)} 均未实跑（--exec-probe off），"
                   "verified 全部为 false（12.5）")
    if families["vcs"]["has_git"] and families["vcs"]["clean"] is False:
        out.append("目标工作树有未提交改动；建议配合 --ref 以获得可复现的快照")
    return out
