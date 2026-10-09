"""toolchain 字段族：test / lint / fmt / type 四条命令的探测与实跑（3.3 / 12.5 / 12.6）。

三个状态严格分离（12.6），**最常见的错是把 `binary_available` 当成 `verified`**：

| 字段                | 含义                                        |
| ------------------- | ------------------------------------------- |
| `cmd = null`        | 仓库里没有可用证据，**绝不编造命令**         |
| `binary_available`  | 二进制在 PATH 上（安全，不涉及仓库代码）      |
| `verified`          | **只有真跑过才为 true**（12.5：默认 `--exec-probe off`） |
| `suggested`         | 由配置推断、建议但未验证，供 S4 参考          |

`source` 记录命令/建议来自哪个文件，没有证据时为 null。
"""

from __future__ import annotations

import configparser
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import fsutil

try:  # 12.0 环境实测：py3.10 无 stdlib tomllib
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 由 py<3.11 走到
    import tomli as tomllib  # type: ignore[no-redef]

KEYS = ("test_cmd", "lint_cmd", "fmt_cmd", "type_cmd")

PROBE_TIMEOUT = 120

# `--exec-probe off` 时命令只是没被验证，不要说成"不可用"
PROBE_OFF_HINT = "未实跑（--exec-probe off），未经证实"


def collect(root: str | os.PathLike[str], layout: dict, *, exec_probe: bool) -> dict:
    ctx = _Context(Path(root), layout)
    out = {
        "test_cmd": ctx.test(),
        "lint_cmd": ctx.lint(),
        "fmt_cmd": ctx.fmt(),
        "type_cmd": ctx.type_check(),
    }
    if exec_probe:
        for key in KEYS:
            _execute(ctx.base, key, out[key])
    return out


# ────────────────────────────── 探测：只找证据 ──────────────────────────────


class _Context:
    """把「配置里有没有这类证据」集中到一处，避免四条命令各写一套文件遍历。"""

    def __init__(self, base: Path, layout: dict) -> None:
        self.base = base
        self.layout = layout
        self._toml: dict | None = None
        self._ini: dict[str, configparser.ConfigParser | None] = {}
        self._make: dict[str, list[str]] | None = None

    # 配置读取（一律经 fsutil，保证只读）

    def toml(self) -> dict:
        if self._toml is None:
            text = fsutil.read_text(self.base / "pyproject.toml")
            try:
                self._toml = tomllib.loads(text) if text else {}
            except tomllib.TOMLDecodeError:
                self._toml = {}
        return self._toml

    def has_toml(self, *path: str) -> bool:
        return _dig(self.toml(), path) is not None

    def has_ini(self, rel: str, section: str) -> bool:
        if rel not in self._ini:
            self._ini[rel] = self._read_ini(rel)
        parser = self._ini[rel]
        return parser is not None and parser.has_section(section)

    def _read_ini(self, rel: str) -> configparser.ConfigParser | None:
        text = fsutil.read_text(self.base / rel)
        if text is None:
            return None
        parser = configparser.ConfigParser()
        try:
            parser.read_string(text)
        except configparser.Error:  # 配置文件坏掉：当作没有这个证据
            return None
        return parser

    def has_file(self, rel: str) -> bool:
        return fsutil.is_file(self.base / rel)

    def make_target(self, name: str) -> str | None:
        """Makefile 里显式声明的命令 —— 这是最强的证据，胜过任何推断。"""
        if self._make is None:
            text = fsutil.read_text(self.base / "Makefile") or ""
            self._make = _parse_make_targets(text)
        recipe = self._make.get(name) or []
        return recipe[0] if recipe else None

    # 四条命令

    def test(self) -> dict:
        explicit = self.make_target("test")
        if explicit:
            return _entry(cmd=explicit, source="Makefile:test")

        source = None
        if self.has_toml("tool", "pytest", "ini_options"):
            source = "pyproject.toml"
        elif self.has_file("pytest.ini"):
            source = "pytest.ini"
        elif self.has_ini("setup.cfg", "tool:pytest"):
            source = "setup.cfg"
        elif self.has_ini("tox.ini", "pytest") or self.has_ini("tox.ini", "testenv"):
            source = "tox.ini"

        if source:
            return _entry(suggested="pytest", source=source)
        test_files = self.layout.get("test_files") or []
        if test_files:
            return _entry(
                suggested="pytest",
                degraded_reason=(
                    f"未发现测试配置；存在 {len(test_files)} 个测试文件，"
                    "建议命令没有仓库证据支撑"
                ),
            )
        return _entry(degraded_reason="未发现测试文件与测试配置，无法推测测试命令")

    def lint(self) -> dict:
        explicit = self.make_target("lint")
        if explicit:
            return _entry(cmd=explicit, source="Makefile:lint")
        if self.has_toml("tool", "ruff"):
            return _entry(suggested="ruff check .", source="pyproject.toml")
        for name in ("ruff.toml", ".ruff.toml"):
            if self.has_file(name):
                return _entry(suggested="ruff check .", source=name)
        if self.has_ini("setup.cfg", "flake8"):
            return _entry(suggested="flake8 .", source="setup.cfg")
        if self.has_file(".flake8"):
            return _entry(suggested="flake8 .", source=".flake8")
        return _entry(degraded_reason="未发现 lint 配置（ruff/flake8），无法推测 lint 命令")

    def fmt(self) -> dict:
        for target in ("fmt", "format"):
            explicit = self.make_target(target)
            if explicit:
                return _entry(cmd=explicit, source=f"Makefile:{target}")
        if self.has_toml("tool", "black"):
            return _entry(suggested="black .", source="pyproject.toml")
        if self.has_toml("tool", "ruff", "format"):
            return _entry(suggested="ruff format .", source="pyproject.toml")
        return _entry(degraded_reason="未发现格式化配置（black/ruff format），无法推测 fmt 命令")

    def type_check(self) -> dict:
        for target in ("type", "typecheck"):
            explicit = self.make_target(target)
            if explicit:
                return _entry(cmd=explicit, source=f"Makefile:{target}")
        if self.has_toml("tool", "mypy"):
            return _entry(suggested="mypy", source="pyproject.toml")
        for name in ("mypy.ini", ".mypy.ini"):
            if self.has_file(name):
                return _entry(suggested="mypy", source=name)
        if self.has_ini("setup.cfg", "mypy"):
            return _entry(suggested="mypy", source="setup.cfg")
        return _entry(degraded_reason="未发现类型检查配置（mypy），无法推测 type 命令")


def _entry(
    *,
    cmd: str | None = None,
    source: str | None = None,
    suggested: str | None = None,
    degraded_reason: str | None = None,
) -> dict:
    """一条命令的固定九键形状；cmd=null 与「没有这个键」语义不同（12.9）。"""
    effective = cmd or suggested
    return {
        "cmd": cmd,
        "source": source,
        "binary_available": _binary_available(effective),
        "verified": False,
        "exit_code": None,
        "collected": None,
        "passed_files": None,
        "suggested": suggested,
        # 探测不到命令时如实说明原因；探测到了则表明"未验证"，不说成"不可用"
        "degraded_reason": degraded_reason or (PROBE_OFF_HINT if effective else None),
    }


def _binary_available(command: str | None) -> bool | None:
    """二进制在不在 PATH 上。安全操作，不涉及仓库代码，可以在 off 时回答。"""
    if not command:
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv:
        return None
    return shutil.which(argv[0]) is not None


def _dig(data: object, path: tuple[str, ...]) -> object | None:
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _parse_make_targets(text: str) -> dict[str, list[str]]:
    targets: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("\t"):
            if current is not None and line.strip():
                targets[current].append(line.strip())
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*:", line)
        if match:
            current = match.group(1)
            targets.setdefault(current, [])
        elif not line.strip():
            current = None
    return targets


# ────────────────────────────── 实跑（仅 --exec-probe on） ──────────────────────────────


def _execute(base: Path, key: str, entry: dict) -> None:
    """只在快照目录里跑（12.5）。目的是把 `verified` 从 false 变成真 True，不是美化。"""
    command = entry["cmd"] or entry["suggested"]
    if not command:
        entry["verified"] = False
        entry["degraded_reason"] = entry["degraded_reason"] or "无命令可跑"
        return
    try:
        argv = shlex.split(command)
    except ValueError:
        entry["verified"] = False
        entry["degraded_reason"] = f"命令无法切分 to argv：{command}"
        return

    if _binary_available(command) is not True:
        entry["verified"] = False
        entry["degraded_reason"] = f"二进制不可用：{argv[0]}"
        return

    if key == "test_cmd" and _is_pytest(argv):
        _run_pytest(base, entry, argv)
        return
    _run_generic(base, entry, argv)


def _is_pytest(argv: list[str]) -> bool:
    return any(Path(token).name == "pytest" for token in argv) or "-m" in argv and "pytest" in argv


def _run_generic(base: Path, entry: dict, argv: list[str]) -> None:
    try:
        cp = _subprocess(base, argv)
    except subprocess.TimeoutExpired:
        entry["verified"] = False
        entry["degraded_reason"] = f"实跑超时（>{PROBE_TIMEOUT}s）"
        return
    entry["verified"] = True
    entry["exit_code"] = cp.returncode
    entry["degraded_reason"] = None


def _run_pytest(base: Path, entry: dict, argv: list[str]) -> None:
    """跑 pytest 并解析 junitxml。

    12.6 的两个坑都对这里生效：
    1. pytest ≥8 的 junitxml **不带 `file` 属性**，要从 classname 反推文件路径
    2. **收集期错误不是一个用例** —— 它也会以 `<testcase>` 形式出现，直接计入
       会让「收集到 1 个用例」这种假象出现
    """
    with tempfile.TemporaryDirectory(prefix="refactor-pilot-probe-") as tmp:
        xml_path = Path(tmp) / "junit.xml"
        try:
            cp = _subprocess(base, [*argv, f"--junitxml={xml_path}"])
        except subprocess.TimeoutExpired:
            entry["verified"] = False
            entry["degraded_reason"] = f"实跑超时（>{PROBE_TIMEOUT}s）"
            return
        entry["exit_code"] = cp.returncode
        text = fsutil.read_text(xml_path)

    if text is None:
        entry["verified"] = False
        entry["degraded_reason"] = "pytest 未产出 junitxml，无法确认收集结果"
        return

    collected, collection_errors, passed, unresolved = _parse_junit(base, text)
    entry["collected"] = collected
    entry["passed_files"] = sorted(set(passed)) if collected else None

    if collected == 0:
        entry["verified"] = False
        detail = f"存在 {collection_errors} 处收集期错误" if collection_errors else "静默零收集"
        entry["degraded_reason"] = f"实跑收集到 0 个用例（{detail}），判定为未验证（12.6）"
        return

    entry["verified"] = True
    entry["degraded_reason"] = (
        f"{unresolved} 个通过用例无法从 classname 反推文件，passed_files 不完整"
        if unresolved
        else None
    )


def _parse_junit(base: Path, text: str) -> tuple[int, int, list[str], int]:
    """→ (收集到的用例数, 收集期错误数, 通过用例的文件列表, 反推失败数)"""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return 0, 0, [], 0

    collected = 0
    collection_errors = 0
    passed: list[str] = []
    unresolved = 0

    for case in root.iter("testcase"):
        classname = case.get("classname") or ""
        tags = {child.tag for child in case}
        if "error" in tags and classname == "":
            collection_errors += 1  # 收集期错误不是用例（12.6 坑 2）
            continue
        collected += 1
        if tags & {"error", "failure", "skipped"}:
            continue
        rel = _file_from_classname(base, classname)
        if rel is None:
            unresolved += 1
        else:
            passed.append(rel)
    return collected, collection_errors, passed, unresolved


def _file_from_classname(base: Path, classname: str) -> str | None:
    """`tests.test_core` → `tests/test_core.py`。

    12.6 坑 1：pytest ≥8 不带 file 属性，逐个前缀试探，**命中最长的那个**。
    反推不出来返回 None —— 不猜，猜出来的路径会污染 Q2 候选。
    """
    parts = [p for p in classname.split(".") if p]
    for size in range(len(parts), 0, -1):
        rel = "/".join(parts[:size]) + ".py"
        if fsutil.is_file(base / rel):
            return rel
    return None


def _subprocess(base: Path, argv: list[str]):
    return subprocess.run(
        argv,
        cwd=str(base),
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT,
        check=False,
    )
