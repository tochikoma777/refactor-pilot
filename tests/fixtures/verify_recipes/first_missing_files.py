#!/usr/bin/env python3
"""第一段 · 存在型缺失：B01（无测试）/ C01（无依赖声明）/ C02（无 lint）/
 C04（无约束文件）/ C06（无 CI）/ G05（.gitignore 未覆盖常见产物）。

这六条是"某文件不存在"型。它们已经在基线里（K-01~K-05），这里仍产出一遍，
是为了让两段的清单能对得上、也让第 4 步实现时知道要往哪几条规则上验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

from _common import dump, finding, scan_json, target

# (rule, 相对路径候选, 说明)
EXISTENCE_PROBES = [
    ("B01", ["tests", "test"], "测试目录/文件"),
    ("C01", ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"], "依赖/打包声明"),
    ("C02", [".flake8", "ruff.toml", ".ruff.toml"], "lint 配置"),  # 另见下面的 pyproject 判定
    ("C04", ["CODEBUDDY.md", "AGENTS.md", "CLAUDE.md"], "AI 约束文件"),
    ("C06", [".github/workflows", ".gitlab-ci.yml", "azure-pipelines.yml"], "CI 配置"),
    ("G05", [".gitignore"], "gitignore"),
]

# G05 的 pattern 分级（误报修正：v1 用的是标准 GitHub Python 模板，
# 报它"缺 .mypy_cache/ .ruff_cache/ .pytest_cache/ .tox/"是误报 —— 它根本没用这些工具）
#   核心层：缺失即报（major）
#   可选层：仅当仓库里有对应工具的配置/痕迹时才报（minor），否则不报
GITIGNORE_CORE = (
    "__pycache__/",
    "*.py[cod]",
    "build/",
    "dist/",
    "*.egg-info/",
    ".venv/",
)

# pattern → 需要哪些"用过这个工具"的证据
GITIGNORE_OPTIONAL = {
    ".mypy_cache/": ("mypy.ini", ".mypy.ini"),
    ".ruff_cache/": ("ruff.toml", ".ruff.toml"),
    ".pytest_cache/": ("pytest.ini",),
    ".tox/": ("tox.ini",),
}

GITIGNORE_OPTIONAL_TOML = {
    ".mypy_cache/": ("tool", "mypy"),
    ".ruff_cache/": ("tool", "ruff"),
    ".pytest_cache/": ("tool", "pytest", "ini_options"),
}


def missing(root: Path, names: list[str]) -> bool:
    return not any((root / name).exists() for name in names)


def _pyproject(root: Path) -> dict:
    import tomllib

    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _toml_has(data: object, path: tuple[str, ...]) -> bool:
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return True


def _tool_in_use(root: Path, payload: dict) -> dict[str, bool]:
    """可选层 pattern 的前置条件：仓库里到底有没有用过这个工具。"""
    data = _pyproject(root)

    in_use: dict[str, bool] = {}
    for pattern, files in GITIGNORE_OPTIONAL.items():
        present = any((root / name).is_file() for name in files)
        toml_path = GITIGNORE_OPTIONAL_TOML.get(pattern)
        if not present and toml_path:
            present = _toml_has(data, toml_path)
        # pytest 的痕迹也可以是"确实存在测试文件"
        if not present and pattern == ".pytest_cache/":
            present = bool((payload.get("layout") or {}).get("test_files"))
        in_use[pattern] = present
    return in_use


def main() -> None:
    root = target(sys.argv)
    payload = scan_json(sys.argv)

    items: list[dict] = []
    for rule, names, desc in EXISTENCE_PROBES:
        hit = missing(root, names)
        # C02 / C03 的常见写法是写在 pyproject 里（`[tool.ruff]`、`[tool.mypy]`），
        # 只看独立配置文件会误报（自审计就报了自家"无 lint 配置"，而我们有 [tool.ruff]）
        if rule == "C02" and hit and _toml_has(_pyproject(root), ("tool", "ruff")):
            hit = False
        if hit:
            items.append(
                finding(rule, ".", 0, f"未发现：{', '.join(names)}", f"缺失型：无{desc}")
            )

    gitignore = root / ".gitignore"
    text = gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.exists() else ""
    lines = {line.strip() for line in text.splitlines() if line.strip()}
    in_use = _tool_in_use(root, payload)

    absent_core = [p for p in GITIGNORE_CORE if p not in lines]
    absent_optional = [
        p for p, evidence in GITIGNORE_OPTIONAL.items() if p not in lines and in_use.get(p)
    ]

    if absent_core:
        items.append(
            finding(
                "G05",
                ".gitignore" if gitignore.exists() else ".",
                0,
                "核心 pattern 未忽略：" + ", ".join(absent_core),
                f".gitignore 缺少 {len(absent_core)} 个**核心**产物 pattern（major）",
            )
        )
    if absent_optional:
        items.append(
            finding(
                "G05",
                ".gitignore" if gitignore.exists() else ".",
                0,
                "可选 pattern 未忽略：" + ", ".join(absent_optional),
                f"这些工具在用，但 .gitignore 未覆盖其缓存目录：{len(absent_optional)} 个（minor）",
            )
        )

    # B01 的强化：有测试文件但没有任何一个 ../.. 环境能跑（此处只看是否有测试文件）
    if not (payload.get("layout") or {}).get("test_files"):
        items.append(
            finding(
                "B01",
                ".",
                0,
                "layout.test_files 为空",
                "无任何 `test_*.py` / `*_test.py`（12.4 口径：只看文件名）",
            )
        )
    dump(items)


if __name__ == "__main__":
    main()
