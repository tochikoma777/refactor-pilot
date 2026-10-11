#!/usr/bin/env python3
"""第三段 · G01 / G04 / G06：仓库卫生里那几条纯 git 事实。

- **G01**：`.git` 体积 ≥ 20MB（7.2 的默认阈值）
- **G04**：`.gitignore` 单行含空格分隔多 pattern —— 那一行会整体失效
- **G06**：无 remote，或本地有未 push 的提交

刻意不读 scan.json：这几条用 git 命令直接问更可靠，也没必要绕一层。
"""

from __future__ import annotations

import sys
from pathlib import Path

from _common import dump, finding, git_stdout, target

GIT_DIR_BYTES_THRESHOLD = 20 * 1024 * 1024


def du_bytes(path: Path) -> int:
    total = 0
    for file in path.rglob("*"):
        try:
            total += file.stat().st_size
        except OSError:
            continue
    return total


def git_size(root: Path) -> tuple[int, str]:
    """返回 (字节数, 目录路径)。`.git` 可能是文件（worktree / submodule）。"""
    git_path = root / ".git"
    if git_path.is_dir():
        return du_bytes(git_path), ".git"
    if git_path.is_file():
        try:
            return git_path.stat().st_size, ".git（文件，指向 gitdir）"
        except OSError:
            return 0, ".git"
    return 0, ".git"


def main() -> None:
    root = target(sys.argv)
    items: list[dict] = []

    size, where = git_size(root)
    if size >= GIT_DIR_BYTES_THRESHOLD:
        items.append(
            finding("G01", where, 0, f"{size} bytes",
                    f"`.git` 体积 {size} bytes ≥ {GIT_DIR_BYTES_THRESHOLD}（默认 20MB）")
        )

    gitignore = root / ".gitignore"
    if gitignore.is_file():
        for index, line in enumerate(
            gitignore.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # 注释后的行内空格不算（git 不支持行内注释，但作者常这么写，先不误伤）
            patterns = stripped.split()
            if len(patterns) >= 2:
                items.append(
                    finding("G04", ".gitignore", index, stripped,
                            "单行含空格分隔的多个 pattern，整行不生效（git 按整行匹配）")
                )

    remotes = git_stdout(["remote"], root)
    if not remotes:
        items.append(finding("G06", ".", 0, "git remote 为空", "仓库没有配置任何 remote"))
    else:
        ahead_behind = git_stdout(["rev-list", "--left-right", "--count", "HEAD...@{u}"], root)
        for row in ahead_behind:
            parts = row.split()
            if len(parts) == 2 and parts[0] not in ("0", ""):
                items.append(
                    finding("G06", ".", 0, row,
                            f"本地有 {parts[0]} 个提交未推送到 {','.join(remotes)}")
                )

    dump(items)


if __name__ == "__main__":
    main()
