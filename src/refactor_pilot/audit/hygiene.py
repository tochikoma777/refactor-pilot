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
from .rules import MAJOR, MINOR

GIT_DIR_BYTES = 20 * 1024 * 1024
LARGE_FILE_BYTES = 1_000_000

GITIGNORE_CORE = ("__pycache__/", "*.py[cod]", "build/", "dist/", "*.egg-info/", ".venv/")
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

    findings += _gitignore(root, scan, factory)
    findings += _secrets(root, tracked_files, factory)
    return findings


def _gitignore(root: Path, scan: dict, factory: FindingFactory) -> list[dict]:
    path = root / ".gitignore"
    if not path.is_file():
        finding = factory.make(
            "G05", file=".gitignore", line=0, evidence=".gitignore 不存在", severity=MAJOR
        )
        return [finding] if finding else []

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    patterns = {line.strip() for line in lines}
    findings: list[dict] = []

    missing_core = [p for p in GITIGNORE_CORE if p not in patterns]
    if missing_core:
        finding = factory.make(
            "G05", file=".gitignore", line=0,
            evidence="核心 pattern 未忽略：" + ", ".join(missing_core), severity=MAJOR,
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


def _secrets(root: Path, tracked_files: list[str], factory: FindingFactory) -> list[dict]:
    findings: list[dict] = []
    for rel in tracked_files:
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
