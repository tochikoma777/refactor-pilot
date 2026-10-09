"""layout 字段族：包根、模块树、入口脚本、配置文件（3.3 / 12.9）。

`modules` 的值是**相对 POSIX 路径**，键是相对仓库根的点分模块名
（把仓库根当作 sys.path 的第一项 —— 这是「在项目根跑 python」的事实）。

`test_files` 用 12.4 的口径：只看文件名。放在这里是因为 toolchain /
q6_signals / q2_candidates 三处都要用，各处自己判定就会不一致。
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from .. import fsutil
from .common import all_files, is_test_file, module_name, parse, python_files

try:  # 12.0 环境实测：py3.10 无 stdlib tomllib  # 12.0 环境实测：py3.10 无 stdlib tomllib
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 由 py<3.11 走到
    import tomli as tomllib  # type: ignore[no-redef]

CONFIG_FILE_NAMES = frozenset(
    {
        ".flake8",
        ".mypy.ini",
        ".pre-commit-config.yaml",
        ".pre-commit-config.yml",
        ".ruff.toml",
        "Dockerfile",
        "Makefile",
        "Pipfile",
        "environment.yml",
        "mypy.ini",
        "noxfile.py",
        "poetry.lock",
        "pyproject.toml",
        "pytest.ini",
        "requirements-dev.txt",
        "requirements.txt",
        "ruff.toml",
        "setup.cfg",
        "setup.py",
        "tox.ini",
        "uv.lock",
    }
)

# 常见入口脚本名（配合 AST 的 `__main__` 守卫一起判定）
ENTRY_POINT_NAMES = frozenset({"__main__.py", "app.py", "cli.py", "main.py", "manage.py", "run.py"})


def collect(root: str | os.PathLike[str]) -> dict:
    rels = python_files(root)
    base = Path(root)

    modules: dict[str, str] = {}
    entry_points: list[str] = []
    test_files: list[str] = []
    package_roots: set[str] = set()

    for rel in rels:
        name = module_name(rel)
        if name is not None:
            modules.setdefault(name, rel)
        if is_test_file(rel):
            test_files.append(rel)
        if _is_entry_point(base, rel):
            entry_points.append(rel)
        top = rel.split("/", 1)[0]
        package_roots.add("." if "/" not in rel else top)

    _aliases, source_roots = _module_aliases(base, rels, modules, entry_points)
    return {
        "package_roots": sorted(package_roots),
        "module_count": len(modules),
        "modules": dict(sorted(modules.items())),
        "source_roots": source_roots,
        "module_aliases": dict(sorted(_aliases.items())),
        "entry_points": sorted(entry_points),
        "config_files": _config_files(base),
        "test_files": sorted(test_files),
    }


def _module_aliases(
    base: Path, rels: list[str], modules: dict[str, str], entry_points: list[str]
) -> tuple[dict[str, str], list[str]]:
    """模块名的**别名**：同一个文件在另一个 sys.path 根下会有另一个点分名。

    只有两种情形能确定「真实的 source root」：

    1. 打包声明写了 source root（setuptools `where = ["src"]`、poetry `from = "src"`）
       —— 那时 `import acme.core` 是对的
    2. **入口脚本所在的目录**：`python src/modules/run.py` 会把 `src/modules/` 放进
       `sys.path[0]`，脚本于是能裸名字 import 同目录的兄弟模块。没有打包声明的
       脚本型仓库全靠这一条，否则每个兄弟 import 都会被误判成不存在的模块
       —— 而那正是 A04 最典型的误报来源

    **重名即不解析**：两个根目录出现同名模块时不猜是哪一个（猜错比不说更糟），
    该别名直接丢弃，目标留在 unresolved 里等人工确认。
    """
    source_roots = _source_roots(base, entry_points)
    name_of_rel = {rel: name for name, rel in modules.items()}
    candidates: dict[str, set[str]] = {}

    for root_dir in source_roots:
        prefix = f"{root_dir}/"
        for rel in rels:
            if not rel.startswith(prefix) or rel == prefix:
                continue
            alt = _dotted(rel[len(prefix) :])
            canonical = name_of_rel.get(rel)
            if alt and canonical and alt != canonical:
                candidates.setdefault(alt, set()).add(canonical)

    aliases = {alt: only.pop() for alt, only in candidates.items() if len(only) == 1}
    return aliases, source_roots


def _source_roots(base: Path, entry_points: list[str]) -> list[str]:
    """可能的 sys.path 根：打包声明 > 入口脚本目录（都是仓库里的证据，不是猜）。"""
    script_dirs = {rel.rsplit("/", 1)[0] for rel in entry_points if "/" in rel}
    found = script_dirs | set(_declared_source_roots(base))

    seen: list[str] = []
    for candidate in sorted(found):
        value = candidate.strip("/")
        if value and value != "." and (base / value).is_dir() and value not in seen:
            seen.append(value)
    return seen


def _declared_source_roots(base: Path) -> list[str]:
    """从打包声明里读 source root（有证据才认；没证据就不猜）。"""
    text = fsutil.read_text(base / "pyproject.toml")
    if not text:
        return []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []

    found: list[str] = []
    where = _dig(data, ("tool", "setuptools", "packages", "find", "where"))
    if isinstance(where, str):
        found.append(where)
    elif isinstance(where, list):
        found.extend(str(item) for item in where)

    package_dir = _dig(data, ("tool", "setuptools", "package-dir"))
    if isinstance(package_dir, dict):
        found.extend(str(value).split("/")[0] for value in package_dir.values() if value)

    poetry_packages = _dig(data, ("tool", "poetry", "packages"))
    if isinstance(poetry_packages, list):
        found.extend(
            item["from"] for item in poetry_packages
            if isinstance(item, dict) and isinstance(item.get("from"), str)
        )
    return [_clean_root(value) for value in found]


def _clean_root(value: object) -> str:
    return str(value).strip("/")


def _dig(data: object, path: tuple[str, ...]) -> object | None:
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _dotted(rel: str) -> str:
    parts = rel[: -len(".py")].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(p for p in parts if p)


def _config_files(base: Path) -> list[str]:
    return sorted(rel for rel in all_files(base) if rel.rsplit("/", 1)[-1] in CONFIG_FILE_NAMES)


def _is_entry_point(base: Path, rel: str) -> bool:
    """入口脚本：`if __name__ == "__main__"` 守卫，或常见入口文件名。"""
    if rel.rsplit("/", 1)[-1] in ENTRY_POINT_NAMES:
        return True
    tree = parse(base / rel)
    return tree is not None and any(_is_main_guard(node) for node in ast.walk(tree))


def _is_main_guard(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    return _is_name_equals_main((test.left, test.comparators[0]))


def _is_name_equals_main(sides: tuple[ast.expr, ast.expr]) -> bool:
    def const_main(node: ast.expr) -> bool:
        return isinstance(node, ast.Constant) and node.value == "__main__"

    def dunder_name(node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id == "__name__"

    left, right = sides
    return (dunder_name(left) and const_main(right)) or (const_main(left) and dunder_name(right))
