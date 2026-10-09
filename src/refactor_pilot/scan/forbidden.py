"""q2_candidates 字段族：Q2「禁止改动的路径」候选（3.3 / 6.1）。

三条生成规则（6.1），每条都带"为什么推荐它"的理由 —— 没有理由的候选与填空题无异：

| 候选类型     | 门槛                                                    | 默认勾 |
| ------------ | ------------------------------------------------------- | ------ |
| 只读参考目录 | 目录名含参考语义 **且** 未被仓库任何模块 import          | ✓      |
| 已通过的测试 | **实跑**解析出的通过文件（不靠路径猜）                   | ✓      |
| 核心模块     | 被 import 次数最多                                       | ✗      |

`needs_probe` 为 true 表示这条候选**必须先实跑才能决定是否勾选**：
`--exec-probe off` 时我们无权声称某个测试文件是"已通过的测试"。
"""

from __future__ import annotations

import os

from .signals import REFERENCE_TOKENS

CORE_MODULE_LIMIT = 5


def collect(
    root: str | os.PathLike[str],
    layout: dict,
    import_graph: dict,
    toolchain: dict,
    signals: dict,
) -> list[dict]:
    imported = {target for targets in import_graph["edges_internal"].values() for target in targets}
    candidates: list[dict] = [
        *_reference_dirs(signals["ref_dirs"], imported, layout),
        *_tests(layout, toolchain),
        *_core_modules(import_graph, layout),
    ]
    return candidates


def _reference_dirs(ref_dirs: list[str], imported: set[str], layout: dict) -> list[dict]:
    modules_in_dir: dict[str, list[str]] = {}
    for name, rel in layout["modules"].items():
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        modules_in_dir.setdefault(parent, []).append(name)

    out: list[dict] = []
    for directory in ref_dirs:
        if any(module in imported for module in modules_in_dir.get(directory, [])):
            continue  # 被本仓库 import 的目录不是"只读参考"
        out.append(
            {
                "path": f"{directory}/",
                "kind": "reference_dir",
                "reason": f"目录名含参考语义（{'/'.join(REFERENCE_TOKENS)} 之一），"
                f"且未被本仓库任何模块 import，疑似只读参考实现",
                "preselect": True,
                "needs_probe": False,
            }
        )
    return out


def _tests(layout: dict, toolchain: dict) -> list[dict]:
    """已通过的测试需要实跑；没实跑就列为"待探测"，不冒充已通过。"""
    passed = toolchain["test_cmd"].get("passed_files")
    if passed:
        return [
            {
                "path": rel,
                "kind": "passing_test",
                "reason": "实跑 test_cmd 解析出的通过文件（6.1）",
                "preselect": True,
                "needs_probe": False,
            }
            for rel in passed
        ]
    return [
        {
            "path": rel,
            "kind": "passing_test",
            "reason": "测试文件候选：未实跑（--exec-probe off），无法确认是否通过，"
            "需先 `--exec-probe on` 探测",
            "preselect": False,
            "needs_probe": True,
        }
        for rel in layout["test_files"]
    ]


def _core_modules(import_graph: dict, layout: dict) -> list[dict]:
    """被 import 次数最多的模块 —— 默认不勾：误锁会让 S4 无解（6.1）。"""
    counts: dict[str, int] = {}
    for targets in import_graph["edges_internal"].values():
        for target in targets:
            counts[target] = counts.get(target, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:CORE_MODULE_LIMIT]
    out: list[dict] = []
    for name, count in ranked:
        rel = layout["modules"].get(name)
        if rel is None:
            continue
        out.append(
            {
                "path": rel,
                "kind": "core_module",
                "reason": f"被 {count} 个模块 import，疑似核心模块"
                "（置信度低，误锁会让 S4 无解，默认不勾）",
                "preselect": False,
                "needs_probe": False,
            }
        )
    return out
