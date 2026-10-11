"""S5 切片的输入：手写单阶段计划（替代 S4 规划器）。

两条硬约束（design-v2 14.2）：

1. `schema_version` 必填（首版 = 1）；缺字段**报错并指明缺哪个** —— 不猜、不默认
2. `writes[]` 是**相对 target 根**的路径，**不支持 glob** —— glob 会让 B 格的
   越界判定变模糊（`src/**/*.py` 到底算不算越界？判定一含糊，检查点就失去意义）
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
REQUIRED_STAGE_FIELDS = ("id", "type", "writes", "forbidden_paths", "behavior_spec")
GLOB_CHARS = ("*", "?", "[")


class PlanError(ValueError):
    """计划文件不合法。消息里必须指明**缺哪个字段/哪一条不合规**。"""


@dataclass(frozen=True)
class Stage:
    id: str
    type: str
    writes: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    behavior_spec: str


def load(path: str | os.PathLike[str]) -> Stage:
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanError(f"计划文件不存在：{file}") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"计划文件不是合法 JSON：{exc}") from exc

    if not isinstance(raw, dict):
        raise PlanError("计划文件的顶层必须是对象")
    if "schema_version" not in raw:
        raise PlanError("计划缺少字段 `schema_version`（首版 = 1）")
    if raw["schema_version"] != SCHEMA_VERSION:
        raise PlanError(
            f"计划 schema_version = {raw['schema_version']}，本工具只认 {SCHEMA_VERSION}"
        )

    stage = raw.get("stage")
    if not isinstance(stage, dict):
        raise PlanError("计划缺少字段 `stage`（对象）")

    missing = [name for name in REQUIRED_STAGE_FIELDS if name not in stage]
    if missing:
        raise PlanError("stage 缺少字段：" + ", ".join(f"`{name}`" for name in missing))

    writes = _as_str_tuple(stage["writes"], "stage.writes")
    forbidden = _as_str_tuple(stage["forbidden_paths"], "stage.forbidden_paths")
    behavior = stage["behavior_spec"]
    if not isinstance(behavior, str) or not behavior.strip():
        raise PlanError("stage.behavior_spec 必须是非空字符串")

    for group, values in (("stage.writes", writes), ("stage.forbidden_paths", forbidden)):
        for value in values:
            _validate_relative(group, value)

    return Stage(
        id=str(stage["id"]),
        type=str(stage["type"]),
        writes=writes,
        forbidden_paths=forbidden,
        behavior_spec=behavior,
    )


def _as_str_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise PlanError(f"{field} 必须是非空数组")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PlanError(f"{field} 的元素必须是非空字符串")
    return tuple(value)


def _validate_relative(field: str, value: str) -> None:
    if any(char in value for char in GLOB_CHARS):
        raise PlanError(
            f"{field} 不支持 glob：`{value}`（glob 会让 B 格的越界判定变模糊，见 14.2）"
        )
    if Path(value).is_absolute() or value.startswith("~"):
        raise PlanError(f"{field} 必须是相对 target 根的路径：`{value}`")
