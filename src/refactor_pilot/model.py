"""scan.json / audit.json 的数据契约（12.9）。

序列化注意：`test_cmd = null` 与「没有这个键」语义不同 ——
前者是「探测过、不可用」，后者读起来像「没探测」。不要做去 null 键的美化。
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import SCHEMA_VERSION

# 退出码（9.2 / 12.10）
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3


def new_scan_payload(
    *,
    path: str,
    ref: str | None,
    snapshot_kind: str,
    resolved_sha: str | None,
) -> dict:
    """scan.json 顶层骨架。字段族（lang/layout/toolchain/...）由 S1 填充（第 2 步）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": {
            "path": path,
            "ref": ref,
            "snapshot": snapshot_kind,
            "resolved_sha": resolved_sha,
        },
        "degraded": [],
        "warnings": [],
    }
