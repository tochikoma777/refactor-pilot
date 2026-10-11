#!/usr/bin/env python3
"""第三段 · G02 / G07：已跟踪的本该被忽略的产物文件，以及已跟踪的大文件。

- **G07**：`git ls-files` 的结果 × 常见产物 pattern（`__pycache__/`、`*.pyc`、`.venv/` …）
  （加 `--rev <ref>` 改查历史版本的跟踪清单 —— 产物被清理后当前树里查不到，
   但历史里确实跟踪过，那正是 G07 最该演示的场景）
- **G02**：已跟踪文件的体积 > 阈值（默认 1MB；7.2 未给 G02 定阈值，此处如实标注）

注意 G05 → G07 的抑制关系（P-07）：`.gitignore` 没写这些 pattern 时，二者合并计一条。
本脚本**照旧分别列出**，是为了让基线能分别知道"有几条真模式" —— 合并是第 4 步报告层的事。
"""

from __future__ import annotations

import fnmatch
import sys

from _common import dump, finding, git_stdout, target

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

LARGE_FILE_BYTES = 1_000_000


def tracked_files(root) -> list[str]:
    """当前工作树用 `git ls-files`；给了 --rev 就用 `git ls-tree -r` 看历史那一版。

    `--rev` 的用途：产物文件被"事后补 .gitignore + git rm --cached"清掉之后，
    当前树里查不到，但**历史里确实跟踪过** —— 那正是 G07 要演示的场景。
    """
    if "--rev" in sys.argv:
        index = sys.argv.index("--rev")
        rev = sys.argv[index + 1] if index + 1 < len(sys.argv) else "HEAD"
        return git_stdout(["ls-tree", "-r", "--name-only", rev], root)
    return git_stdout(["ls-files"], root)


def size_of(root, rel_path: str, historic: bool) -> int | None:
    if historic:  # 历史版本不在工作树里，用 git 的 blob 大小
        rows = git_stdout(["cat-file", "-s", f"HEAD:{rel_path}"], root)
        return int(rows[0]) if rows and rows[0].isdigit() else None
    try:
        return (root / rel_path).stat().st_size
    except OSError:
        return None


def matches_artifact(rel_path: str) -> bool:
    parts = rel_path.split("/")
    for pattern in ARTIFACT_PATTERNS:
        if pattern.endswith("/"):
            if pattern[:-1] in parts:
                return True
        elif fnmatch.fnmatch(parts[-1], pattern):
            return True
    return False


def main() -> None:
    root = target(sys.argv)
    items: list[dict] = []

    historic = "--rev" in sys.argv
    for rel_path in tracked_files(root):
        if matches_artifact(rel_path):
            items.append(
                finding("G07", rel_path, 0, rel_path,
                        "已被版本库跟踪的产物文件（本应由 .gitignore 拦下）")
            )
        size = size_of(root, rel_path, historic)
        if size is not None and size >= LARGE_FILE_BYTES:
            items.append(
                finding("G02", rel_path, 0, f"{size} bytes",
                        f"已跟踪文件体积 {size} bytes ≥ {LARGE_FILE_BYTES}")
            )
    dump(items)


if __name__ == "__main__":
    main()
