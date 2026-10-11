"""S5 切片的输入：计划（手写单阶段，或 `plan` 子命令自动生成的多阶段）。

三条硬约束（design-v2 14.2）：

1. `schema_version` 必填（首版 = 1）；缺字段**报错并指明缺哪个** —— 不猜、不默认
2. `writes[]` 是**相对 target 根**的路径，**不支持 glob** —— glob 会让 B 格的
   越界判定变模糊（`src/**/*.py` 到底算不算越界？判定一含糊，检查点就失去意义）
3. 形状有两种：`{"stage": {...}}`（单阶段，手写）或 `{"stages": [{...}, ...]}`
   （多阶段，`plan` 子命令生成）；`forbidden_paths` 允许为空（writes 范围本身已约束）
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
    """读**单个**阶段（手写 plan 的常规入口）。多阶段计划请用 `load_stages`。"""
    stages = load_stages(path)
    if len(stages) != 1:
        raise PlanError(
            f"计划里有 {len(stages)} 个阶段 —— 单阶段入口只接受 1 个，请用 load_stages()"
        )
    return stages[0]


def load_stages(path: str | os.PathLike[str]) -> list[Stage]:
    """读计划里的**全部**阶段（`stage` 或 `stages` 两种形状都支持）。"""
    raw = _read(path)
    if "schema_version" not in raw:
        raise PlanError("计划缺少字段 `schema_version`（首版 = 1）")
    if raw["schema_version"] != SCHEMA_VERSION:
        raise PlanError(
            f"计划 schema_version = {raw['schema_version']}，本工具只认 {SCHEMA_VERSION}"
        )

    items = raw.get("stages")
    if items is None:
        single = raw.get("stage")
        items = [single] if isinstance(single, dict) else None
    if not isinstance(items, list) or not items:
        raise PlanError("计划缺少 `stage`（对象）或 `stages`（非空数组）")

    return [_to_stage(item, index) for index, item in enumerate(items)]


def _read(path: str | os.PathLike[str]) -> dict:
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanError(f"计划文件不存在：{file}") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"计划文件不是合法 JSON：{exc}") from exc
    if not isinstance(raw, dict):
        raise PlanError("计划文件的顶层必须是对象")
    return raw


def _to_stage(stage: object, index: int) -> Stage:
    where = f"stages[{index}]"
    if not isinstance(stage, dict):
        raise PlanError(f"{where} 必须是对象")

    missing = [name for name in REQUIRED_STAGE_FIELDS if name not in stage]
    if missing:
        raise PlanError(f"{where} 缺少字段：" + ", ".join(f"`{name}`" for name in missing))

    writes = _as_str_tuple(stage["writes"], f"{where}.writes", allow_empty=False)
    forbidden = _as_str_tuple(
        stage["forbidden_paths"], f"{where}.forbidden_paths", allow_empty=True
    )
    behavior = stage["behavior_spec"]
    if not isinstance(behavior, str) or not behavior.strip():
        raise PlanError(f"{where}.behavior_spec 必须是非空字符串")

    for group, values in ((f"{where}.writes", writes), (f"{where}.forbidden_paths", forbidden)):
        for value in values:
            _validate_relative(group, value)

    return Stage(
        id=str(stage["id"]),
        type=str(stage["type"]),
        writes=writes,
        forbidden_paths=forbidden,
        behavior_spec=behavior,
    )


def _as_str_tuple(value: object, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise PlanError(f"{field} 必须是{'可空' if allow_empty else '非空'}数组")
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
