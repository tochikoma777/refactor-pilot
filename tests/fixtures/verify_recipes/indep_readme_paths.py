#!/usr/bin/env python3
"""第三段 · H01：文档里提到的文件路径在仓库中不存在。

护栏（误报修正后补齐 —— v1 的 README:154 命中在 ```python 围栏里，是使用示例，
不是文档声称仓库里有 `data.txt`）：

1. **先剥离代码**：围栏代码块（``` / ~~~）整段去掉，行内代码（`...`）抹掉，
   只看散文 / 列表 / 表格里的路径引用
2. **排除通用占位名**：`data.txt`、`example.py`、`foo.txt` 是示例里的泛指，
   不代表仓库该有这个文件
3. 扫之前先抹掉 URL，否则 `https://…/download.py` 会被当成仓库内路径
4. **只扫面向使用者的 README 类文档** —— 设计/过程文档里必然提到"将来才生成的产物"
   （`scan.json`、`audit.json`、`.upgrade/plan.json` …），那是正常叙述，
   不是文档声称仓库里有它（自审计实测：9 条命中全在设计文档里）

仍保持"只提候选"：剩下的命中交人判断，脚本不替人收口。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from _common import dump, finding, target

TOKEN = re.compile(r"[A-Za-z0-9_./\-]+\.(?:py|md|txt|json|toml|yaml|yml|png|csv|npz|npy)\b")
URL = re.compile(r"^(?:https?://|www\.|[A-Za-z]:\\\\)")
URL_IN_TEXT = re.compile(r"https?://\S+|www\.\S+")
FENCE = re.compile(r"^\s*(?:```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")

KNOWN_SUFFIXES = (".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".png", ".csv")

# 示例里的泛指文件名（词干）——出现在文档里不代表仓库该有它
PLACEHOLDER_STEMS = frozenset(
    {
        "data",
        "example",
        "examples",
        "sample",
        "samples",
        "test",
        "tests",
        "temp",
        "tmp",
        "foo",
        "bar",
        "baz",
        "demo",
        "input",
        "output",
        "file",
        "config",
    }
)


def strip_prose(lines: list[str]) -> list[tuple[int, str]]:
    """去掉围栏代码块，剩下的行再抹掉行内代码，保留原始行号。"""
    kept: list[tuple[int, str]] = []
    inside = False
    for index, line in enumerate(lines, start=1):
        if FENCE.match(line):
            inside = not inside
            continue
        if inside:
            continue
        kept.append((index, INLINE_CODE.sub(" ", line)))
    return kept


def is_placeholder(candidate: str) -> bool:
    return Path(candidate).stem.lower() in PLACEHOLDER_STEMS


def user_facing_docs(root: Path) -> list[Path]:
    """只扫 README 类（面向使用者）；设计/过程文档不扫，见护栏第 4 条。"""
    docs = [p for p in root.glob("README*.md") if ".git" not in p.parts]
    docs += [p for p in root.glob("docs/README*.md")]
    return sorted(docs)


def main() -> None:
    root = target(sys.argv)
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for md in user_facing_docs(root):
        try:
            rel_doc = md.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel_doc.startswith(".git/"):
            continue
        try:
            lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, UnicodeError):
            continue

        for index, line in strip_prose(lines):
            scrubbed = URL_IN_TEXT.sub(" ", line)
            for token in TOKEN.findall(scrubbed):
                candidate = token.strip("`\"'()[]{}<>")
                if URL.match(candidate) or is_placeholder(candidate):
                    continue
                if candidate.endswith(KNOWN_SUFFIXES) is False:
                    continue
                exists = (root / candidate).exists() or any(root.glob(f"**/{candidate}"))
                if exists:
                    continue
                key = (rel_doc, candidate)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    finding(
                        "H01",
                        rel_doc,
                        index,
                        line.strip()[:160],
                        f"文档提到的 `{candidate}` 在仓库中不存在",
                    )
                )
    dump(items)


if __name__ == "__main__":
    main()
