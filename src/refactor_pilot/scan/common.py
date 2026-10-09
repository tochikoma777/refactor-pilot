"""S1 各字段族共用的推导函数。

集中在这里的理由：

- 模块名推导 / 测试文件判定 / 顶层符号提取若在 layout、importer、toolchain
  各写一遍，三处不一致会产出**互相矛盾的事实**。
- 12.4（测试文件只看文件名）与 12.3（模块 vs 符号）是最容易写错的两个判定，
  写成单点，才能保证全链路一致。

本模块只读：所有文件访问经 ``fsutil``（12.1）。绝不 import 目标项目的代码，
只用 ``ast`` 静态解析。
"""

from __future__ import annotations

import ast
import os
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from .. import fsutil

PY_SUFFIXES = frozenset({".py"})

# 标准库模块名：用于区分「外部三方依赖」与「仓库内模块」，避免 numpy/torch 被当成 missing module
STDLIB_MODULES: frozenset[str] = frozenset(getattr(sys, "stdlib_module_names", ()) or ())

# 见 12.4：`tests/` 下的 conftest.py / helpers.py 不是测试文件，只看文件名。
TEST_FILE_SUFFIX = ".py"


def python_files(root: str | os.PathLike[str]) -> list[str]:
    """仓库内所有 .py 文件的相对 POSIX 路径（已排序，稳定可复现）。"""
    rels: list[str] = []
    for p in fsutil.iter_files(root, suffixes=PY_SUFFIXES):
        try:
            rels.append(p.relative_to(root).as_posix())
        except ValueError:  # pragma: no cover - iter_files 保证在 root 下
            continue
    return sorted(rels)


def all_files(root: str | os.PathLike[str]) -> Iterator[str]:
    """仓库内所有文件的相对 POSIX 路径（不跳过任何后缀；忽略 SKIP_DIRS）。"""
    for p in fsutil.iter_files(root):
        try:
            yield p.relative_to(root).as_posix()
        except ValueError:
            continue


def is_test_file(rel_or_path: str | os.PathLike[str]) -> bool:
    """是否测试文件：**只按文件名**，不看父目录名（12.4）。

    `tests/conftest.py`、`tests/helpers.py` 一律不是测试文件 ——
    否则它们会被当成「已通过的测试」推荐进 Q2 禁改清单，S4 直接无解。
    """
    name = Path(rel_or_path).name
    if not name.endswith(TEST_FILE_SUFFIX):
        return False
    stem = name[: -len(TEST_FILE_SUFFIX)]
    return stem.startswith("test_") or stem.endswith("_test")


def module_name(rel: str) -> str | None:
    """相对路径 → 点分模块名。目录按包处理（`__init__.py` 归到目录名本身）。

    命名空间包（无 `__init__.py`）也按包处理（PEP 420），否则扁平目录下的
    一堆脚本会被错报成顶层模块丢失。
    """
    parts = rel[: -len(TEST_FILE_SUFFIX)].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)


def package_of(module: str) -> str:
    """模块所在包的点分名；顶层模块返回 ''。"""
    return module.rpartition(".")[0]


def is_stdlib(top: str) -> bool:
    return top in STDLIB_MODULES


def parse(path: str | os.PathLike[str]) -> ast.Module | None:
    """解析成 AST；读不到或语法错误返回 None（单个坏文件不应中止扫描）。"""
    text = fsutil.read_text(path)
    if text is None:
        return None
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def toplevel_names(tree: ast.Module) -> set[str]:
    """模块的顶层符号名（用于 12.3 判定 `from m import y` 的 y 是不是符号）。

    只覆盖常规的绑定形式 + `try: import x` 兜底写法；更深层的嵌套不展开 ——
    宁可少判一个符号（多留一条 as_symbol=true 记录），也不要把符号错判成模块。
    """
    names: set[str] = set()
    for stmt in _flatten_toplevel(tree.body):
        names.update(_stmt_names(stmt))
    return names


def symbols_by_module(
    root: str | os.PathLike[str], modules: dict[str, str]
) -> dict[str, set[str]]:
    """{模块名: 顶层符号集合}。"""
    empty = ast.Module(body=[], type_ignores=[])
    return {name: toplevel_names(parse(Path(root) / rel) or empty) for name, rel in modules.items()}


def _flatten_toplevel(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """展开顶层语句；把 try/except 的分支也摊到顶层（`try: import tomllib`）。"""
    for stmt in body:
        yield stmt
        if isinstance(stmt, ast.Try):
            branches = [stmt.body, stmt.orelse, stmt.finalbody]
            branches.extend(handler.body for handler in stmt.handlers)
            for nested_body in branches:
                yield from _flatten_toplevel(nested_body)


def _stmt_names(stmt: ast.stmt) -> Iterator[str]:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        yield stmt.name
    elif isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            yield from _binding_names(target)
    elif isinstance(stmt, ast.AnnAssign) and stmt.target is not None:
        yield from _binding_names(stmt.target)
    elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
        for alias in stmt.names:
            if alias.name != "*":
                yield alias.asname or alias.name.split(".")[0]


def _binding_names(node: ast.expr) -> Iterator[str]:
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _binding_names(elt)
