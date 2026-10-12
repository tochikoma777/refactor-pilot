"""G 组 · 仓库卫生（G01 / G02 / G03 / G04 / G05 / G07）。

G03 用 `git ls-files` + 正则，不用 `git grep`：两者事实等价，而前者能直接拿到
相对路径，也能顺手复用 G02 的体积统计。

G05 的 pattern **分级**（核心 / 可选），G07 **受 G05 抑制**（7.4）。
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from .. import fsutil, gitutil
from .findings import FindingFactory
from .rules import HIGH, MAJOR, MEDIUM, MINOR

GIT_DIR_BYTES = 20 * 1024 * 1024
LARGE_FILE_BYTES = 1_000_000

GITIGNORE_CORE = ("__pycache__/", "*.py[cod]", "build/", "dist/", "*.egg-info/", ".venv/")

# G05 核心 pattern → **代表路径**，交给 `git check-ignore` 实测是否真被忽略。
# 两条硬要求：
#  1. 目录 pattern 用"目录内的文件"当代表：`git check-ignore -q .venv` 对 `.venv/`
#     这类目录 pattern 会误判"未忽略"（它按文件判），只有 `.venv/x` 才判得对
#  2. 代表路径**不能被别的核心 pattern 顺带匹配**，否则会张冠李戴 ——
#     例如 `__pycache__/x.pyc` 会被 `*.py[cod]` 匹配，从而把"漏了 __pycache__/"
#     误判成"已忽略"。故 `__pycache__/` 用无扩展名的 `__pycache__/x`。
# 这样 `.gitignore` 写 `*.py[codz]`（超集）或 `.venv`（无斜杠，语义等价）也不再误报。
GITIGNORE_PROBE = {
    "__pycache__/": "__pycache__/x",
    "*.py[cod]": "x.pyc",
    "build/": "build/x",
    "dist/": "dist/x",
    "*.egg-info/": "x.egg-info/PKG-INFO",
    ".venv/": ".venv/x",
}
GITIGNORE_OPTIONAL = {
    ".mypy_cache/": ("mypy.ini", ".mypy.ini"),
    ".ruff_cache/": ("ruff.toml", ".ruff.toml"),
    ".pytest_cache/": ("pytest.ini",),
    ".tox/": ("tox.ini",),
}
OPTIONAL_TOML = {
    ".mypy_cache/": ("tool", "mypy"),
    ".ruff_cache/": ("tool", "ruff"),
    ".pytest_cache/": ("tool", "pytest", "ini_options"),
}

ARTIFACT_PATTERNS = (
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".venv/",
    "venv/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".pytest_cache/",
    ".tox/",
    "*.egg-info/",
    "build/",
    "dist/",
)

SECRET_PATTERN = re.compile(
    r"(?:api[_-]?key|secret|token|password|passwd|private[_-]?key|access[_-]?key)"
    r"\s*[:=]\s*['\"]([^'\"]{8,})['\"]",
    re.IGNORECASE,
)
PLACEHOLDER = re.compile(
    r"example|placeholder|dummy|changeme|xxxx|your[_-]?key|<[^>]+>|fixture|test[_-]?key|TODO",
    re.IGNORECASE,
)


def check(
    root: Path,
    source: Path,
    scan: dict,
    factory: FindingFactory,
    *,
    git: bool = True,
) -> list[dict]:
    findings: list[dict] = []
    if not git:
        return findings

    git_dir = _git_dir_bytes(source)
    if git_dir >= GIT_DIR_BYTES:
        finding = factory.make(
            "G01", file=".git", line=0, evidence=f".git 体积 {git_dir} bytes ≥ {GIT_DIR_BYTES}"
        )
        if finding:
            findings.append(finding)

    tracked = gitutil.out(["ls-files"], cwd=source)
    tracked_files = [line for line in (tracked or "").splitlines() if line.strip()]

    for rel in tracked_files:
        path = root / rel
        size = _size(path)
        if size is not None and size >= LARGE_FILE_BYTES:
            finding = factory.make("G02", file=rel, line=0, evidence=f"{size} bytes")
            if finding:
                findings.append(finding)
        if _is_artifact(rel):
            finding = factory.make("G07", file=rel, line=0, evidence=rel)
            if finding:
                findings.append(finding)

    findings += _gitignore(root, source, scan, factory)
    findings += _secrets(root, tracked_files, factory)
    return findings


def _gitignore(root: Path, source: Path, scan: dict, factory: FindingFactory) -> list[dict]:
    path = root / ".gitignore"
    if not path.is_file():
        finding = factory.make(
            "G05", file=".gitignore", line=0, evidence=".gitignore 不存在", severity=MAJOR
        )
        return [finding] if finding else []

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    patterns = {line.strip() for line in lines}
    findings: list[dict] = []

    missing_core, used_git = _missing_core(source, patterns)
    if missing_core:
        detail = ", ".join(f"{p}（代表路径 `{rep}`）" for p, rep in missing_core)
        note = "" if used_git else "；**非 git 目标**，按字符串匹配（未经 check-ignore 实测）"
        finding = factory.make(
            "G05", file=".gitignore", line=0,
            evidence="核心 pattern 未忽略：" + detail + note,
            severity=MAJOR,
            # 实测过的用规则默认（high）；只能串匹配时如实降为 medium（12.6 精神）
            confidence=HIGH if used_git else MEDIUM,
        )
        if finding:
            findings.append(finding)

    missing_optional = [
        p for p in GITIGNORE_OPTIONAL if p not in patterns and _in_use(root, scan, p)
    ]
    if missing_optional:
        finding = factory.make(
            "G05", file=".gitignore", line=0,
            evidence="这些工具在用、但未忽略其缓存目录：" + ", ".join(missing_optional),
            severity=MINOR,
        )
        if finding:
            findings.append(finding)

    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(stripped.split()) >= 2:
            finding = factory.make(
                "G04", file=".gitignore", line=index,
                evidence=stripped,
            )
            if finding:
                findings.append(finding)
    return findings


def _missing_core(source: Path, patterns: set[str]) -> tuple[list[tuple[str, str]], bool]:
    """哪些核心 pattern 没被忽略：优先用 `git check-ignore` 实测代表路径。

    返回 (缺失的 [(pattern, 代表路径)], 是否用了 git 实测)。
    git 不可用 / 非仓库 / 调用异常 → 该 pattern 退回字符串匹配（used_git 保持 False）。
    """
    missing: list[tuple[str, str]] = []
    used_git = False
    for pattern in GITIGNORE_CORE:
        rep = GITIGNORE_PROBE[pattern]
        ignored = _ignored_by_git(source, rep)
        if ignored is None:
            if pattern not in patterns:
                missing.append((pattern, rep))
        else:
            used_git = True
            if not ignored:
                missing.append((pattern, rep))
    return missing, used_git


def _ignored_by_git(source: Path, rel: str) -> bool | None:
    """`git check-ignore -q <rel>`：0=已忽略 / 1=未忽略 / 其它或非仓库=None（走 fallback）。"""
    if not gitutil.available() or not gitutil.is_repo(source):
        return None
    try:
        cp = gitutil.run(["check-ignore", "-q", "--", rel], cwd=source)
    except gitutil.GitError:
        return None
    if cp.returncode == 0:
        return True
    if cp.returncode == 1:
        return False
    return None


def _secrets(root: Path, tracked_files: list[str], factory: FindingFactory) -> list[dict]:
    findings: list[dict] = []
    for rel in tracked_files:
        if _g03_exempt(rel):
            continue
        path = root / rel
        text = fsutil.read_text(path)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines()[:4000], start=1):
            match = SECRET_PATTERN.search(line)
            if not match or PLACEHOLDER.search(match.group(1)):
                continue
            finding = factory.make("G03", file=rel, line=lineno, evidence=_mask(line.strip()))
            if finding:
                findings.append(finding)
    return findings


# G03 豁免：测试夹具 / 示例里出现 `api_key = "..."` 是**常态**，不是泄露。
# （2026-10-11 自审计抓到：本仓库 tests/test_audit.py 的假 key 被误报）
G03_EXEMPT_DIRS = ("tests/", "test/", "examples/", "example/", "fixtures/", "docs/")
G03_EXEMPT_TOKENS = ("fixture", "example", "sample", "dummy", "fake")


def _g03_exempt(rel: str) -> bool:
    lowered = rel.lower()
    if lowered.startswith(G03_EXEMPT_DIRS):
        return True
    name = Path(rel).name.lower()
    if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
        return True
    return any(token in name for token in G03_EXEMPT_TOKENS)


def _mask(text: str) -> str:
    """证据里不要把密钥原文落盘 —— 报告是会给人传阅的。"""
    return SECRET_PATTERN.sub(lambda m: m.group(0)[: m.group(0).index(m.group(1))] + "***", text)


def _in_use(root: Path, scan: dict, pattern: str) -> bool:
    if any((root / name).is_file() for name in GITIGNORE_OPTIONAL.get(pattern, ())):
        return True
    path = GITIGNORE_OPTIONAL_TOML_SECTION.get(pattern)
    if path and _toml_has(root, path):
        return True
    if pattern == ".pytest_cache/":
        return bool((scan.get("layout") or {}).get("test_files"))
    return False


GITIGNORE_OPTIONAL_TOML_SECTION = OPTIONAL_TOML


def _toml_has(root: Path, path: tuple[str, ...]) -> bool:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]

    file = root / "pyproject.toml"
    if not file.is_file():
        return False
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeError):
        return False
    node: object = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return True


def _is_artifact(rel: str) -> bool:
    parts = rel.split("/")
    for pattern in ARTIFACT_PATTERNS:
        if pattern.endswith("/"):
            if pattern[:-1] in parts:
                return True
        elif fnmatch.fnmatch(parts[-1], pattern):
            return True
    return False


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _git_dir_bytes(source: Path) -> int:
    from ..audit import git_dir_bytes

    return git_dir_bytes(source)
