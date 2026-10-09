"""q6_signals 字段族：要不要启用 Q6 对拍，先看有没有信号（3.3 / 12.9 / 5.1-Q6）。

三类信号：只读参考目录、对拍类测试、数值基线文件。**采集的都是存在性事实**；
`suggest_q6_default_on` 只是建议，不是决定（真正的交互在 S3）。

⚠️ 已知局限（12.11）：名字里含 baseline/expected/golden/reference 的数据文件会被算作
数值基线信号 —— 工具自己的 `tests/fixtures/baseline.json` 就会命中。所以阈值定在
**≥2 个信号**：单条误命中不足以翻转建议，别把它当强信号。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .. import fsutil
from .common import all_files, is_test_file

THRESHOLD = 2

REFERENCE_TOKENS = ("reference", "vendor", "frozen", "golden", "oracle")

# 数值基线文件的名字线索（比目录名宽松：baseline/expected 也算）
BASELINE_TOKENS = ("baseline", "expected", "golden", "reference")

BASELINE_SUFFIXES = frozenset({".json", ".csv", ".npy", ".npz"})

COMPARE_MARKERS = re.compile(
    r"allclose|array_equal|assert_close|expected_output|golden|reference|baseline|compare|diff",
    re.IGNORECASE,
)


def collect(root: str | os.PathLike[str]) -> dict:
    base = Path(root)
    ref_dirs = _reference_dirs(base)
    baselines = _numeric_baselines(base)
    compare_tests = _compare_tests(base, ref_dirs)

    count = len(ref_dirs) + len(compare_tests) + len(baselines)
    return {
        "ref_dirs": ref_dirs,
        "compare_tests": compare_tests,
        "numeric_baselines": baselines,
        "signal_count": count,
        "any": count > 0,
        "suggest_q6_default_on": count >= THRESHOLD,
        "threshold": THRESHOLD,
    }


def _reference_dirs(base: Path) -> list[str]:
    """目录名含参考语义（reference/vendor/frozen/golden/oracle）的相对目录路径。"""
    dirs: set[str] = set()
    for rel in all_files(base):
        for parent in _ancestors(rel):
            if _matches(parent.rsplit("/", 1)[-1], REFERENCE_TOKENS):
                dirs.add(parent)
    return sorted(dirs)


def _numeric_baselines(base: Path) -> list[str]:
    """名字含 baseline/expected/golden/reference 的数据文件。"""
    return [
        rel
        for rel in sorted(all_files(base))
        if Path(rel).suffix in BASELINE_SUFFIXES and _matches(Path(rel).name, BASELINE_TOKENS)
    ]


def _compare_tests(base: Path, ref_dirs: list[str]) -> list[str]:
    """疑似对拍类测试：测试文件引用参考目录，或正文出现比对/容差标记。

    测试文件判定沿用 12.4（只看文件名，不看父目录）。
    """
    ref_names = [Path(d).name for d in ref_dirs]
    hits: list[str] = []
    for rel in sorted(all_files(base)):
        if not is_test_file(rel):
            continue
        text = fsutil.read_text(base / rel) or ""
        mentions_ref = any(name in text for name in ref_names)
        if mentions_ref or COMPARE_MARKERS.search(text):
            hits.append(rel)
    return hits


def _ancestors(rel: str) -> list[str]:
    parts = rel.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _matches(name: str, tokens: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in tokens)
