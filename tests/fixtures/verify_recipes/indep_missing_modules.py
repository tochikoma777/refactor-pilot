#!/usr/bin/env python3
"""第三段 · A04：import 的模块在仓库中不存在 —— **完全独立**的一版。

与 `first_missing_modules.py` 的区别：

- 不看 scan.json，自己收集所有 import、自己建模块清单
- **不做 src 布局别名**（P-03 的别名逻辑是工具的行为，这里按最朴素的
  "仓库根相对路径"来算 —— 两侧口径不同，差集才有意义）
- 自己区分"外部依赖"与"仓库里应该有但没有"
"""

from __future__ import annotations

import ast
import sys

from _common import (  # noqa: E402
    dump,
    finding,
    parse,
    python_files,
    rel,
    source_line,
    target,
)

STDLIB_MODULES = frozenset(getattr(sys, "stdlib_module_names", ()) or ())

THIRD_PARTY_HINTS = frozenset(
    {
        "matplotlib",
        "numpy",
        "requests",
        "tensorflow",
        "tiktoken",
        "torch",
        "tqdm",
    }
)


def repo_modules(root) -> set[str]:
    """仓库根相对路径 → 点分模块名（朴素版：不做别名）。"""
    names: set[str] = set()
    for path in python_files(root):
        rel_path = rel(path, root)
        parts = rel_path[: -len(".py")].split("/")
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            names.add(".".join(parts))
    return names


def collect_imports(root):
    """→ [(file_rel, dotted, lineno, node)]，含相对 import 的朴素处理。"""
    rows = []
    for path in python_files(root):
        tree = parse(path)
        if tree is None:
            continue
        file_rel = rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    rows.append((file_rel, alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    rows.append((file_rel, f"{node.module}.{alias.name}", node.lineno))
    return rows


def main() -> None:
    root = target(sys.argv)
    known = repo_modules(root)

    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for file_rel, dotted, lineno in collect_imports(root):
        module_part = dotted
        top = module_part.split(".")[0]
        if top in STDLIB_MODULES or top in THIRD_PARTY_HINTS:
            continue
        if any(module_part.startswith(name) for name in known):
            continue
        if module_part in known:
            continue
        key = (file_rel, module_part)
        if key in seen:
            continue
        seen.add(key)
        path = root / file_rel
        items.append(
            finding(
                "A04",
                file_rel,
                lineno,
                source_line(path, lineno),
                f"import 的 `{module_part}` 在仓库中找不到对应模块",
            )
        )
    dump(items)


if __name__ == "__main__":
    main()
