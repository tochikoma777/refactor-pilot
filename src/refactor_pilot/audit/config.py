"""C 组 · 工程化配置（C01 / C02 / C04 / C05 / C06）。

除 C05 外都是**缺失型**：`file` 填期望存在的路径，`line = 0`。

C01 同时是两条抑制边的母规则：C01 → D01、C01 → A04 切 script-style（后者在 S1 里生效）。
所以 C01 必须**先于**其它判定确定是否命中。
"""

from __future__ import annotations

from pathlib import Path

from .findings import FindingFactory

DEPENDENCY_FILES = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")
LINT_CONFIGS = ("ruff.toml", ".ruff.toml", ".flake8")
CONSTRAINT_FILES = ("CODEBUDDY.md", "AGENTS.md", "CLAUDE.md")
CI_PATHS = (".github/workflows", ".gitlab-ci.yml", "azure-pipelines.yml", ".circleci")


def check(root: Path, scan: dict, factory: FindingFactory) -> list[dict]:
    findings: list[dict] = []

    if not _any_exists(root, DEPENDENCY_FILES):
        finding = factory.make(
            "C01", file="pyproject.toml", line=0,
            evidence="未发现：" + ", ".join(DEPENDENCY_FILES),
        )
        if finding:
            findings.append(finding)

    if not _any_exists(root, LINT_CONFIGS) and not _toml_lint(root):
        finding = factory.make(
            "C02", file="ruff.toml", line=0,
            evidence="未发现：" + ", ".join(LINT_CONFIGS) + "，pyproject 也无 [tool.ruff]",
        )
        if finding:
            findings.append(finding)

    if not _any_exists(root, CONSTRAINT_FILES):
        finding = factory.make(
            "C04", file="CODEBUDDY.md", line=0, evidence="未发现：" + ", ".join(CONSTRAINT_FILES)
        )
        if finding:
            findings.append(finding)

    if not _any_exists(root, CI_PATHS):
        finding = factory.make(
            "C06", file=".github/workflows", line=0, evidence="未发现：" + ", ".join(CI_PATHS)
        )
        if finding:
            findings.append(finding)

    findings += _c05(scan, factory)
    return findings


def _c05(scan: dict, factory: FindingFactory) -> list[dict]:
    """C05：pre-commit hook 用隔离环境与本地版本不一致。

    `language: system` 的 hook 直接调用 PATH 上的二进制 → 与本地版本强耦合，
    换台机器就换版本，CI 与本地可能对不上。
    """
    hooks = scan.get("hooks") or {}
    if not hooks.get("precommit_exists"):
        return []
    if hooks.get("isolated") is not False:
        return []
    system_hooks = [e for e in hooks.get("entries") or [] if e.get("language") == "system"]
    if not system_hooks:
        return []
    names = [str(e.get("id")) for e in system_hooks]
    line = int(system_hooks[0].get("line") or 0)  # hooks 解析带行号，别拿 0 冒充
    finding = factory.make(
        "C05",
        file=".pre-commit-config.yaml",
        line=line,
        evidence="language: system 的 hook：" + ", ".join(names),
    )
    return [finding] if finding else []


def _any_exists(root: Path, names: tuple[str, ...]) -> bool:
    return any((root / name).exists() for name in names)


def _toml_lint(root: Path) -> bool:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]

    path = root / "pyproject.toml"
    if not path.is_file():
        return False
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeError):
        return False
    tool = data.get("tool") if isinstance(data, dict) else None
    return isinstance(tool, dict) and any(
        key in tool for key in ("ruff", "flake8", "pylint", "black")
    )
