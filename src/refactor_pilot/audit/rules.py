"""S2 规则包：注册表 + 抑制边（7.2 / 7.4）。

首版范围（9.3）：**A / B / C / G / I 五组的 P0 规则** + 由 P1 提升的 **C06**。

规则可通过 `--rules FILE`（TOML 或 JSON）关闭 / 改严重度 —— 不支持 YAML，
因为运行时依赖要尽可能为零（12.0），而仓库里并没有装 PyYAML 的义务。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:  # 12.0：py3.10 无 stdlib tomllib
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

BLOCKER = "blocker"
MAJOR = "major"
MINOR = "minor"
UNVERIFIED = "unverified"

SEVERITIES = (BLOCKER, MAJOR, MINOR, UNVERIFIED)

ENGINEERING = "engineering"
CONFIG = "config"
SEMANTIC = "semantic"

HIGH = "high"
MEDIUM = "medium"
LOW = "low"


class Rules:
    """规则表（含运行时可改的 enabled / severity 覆盖）。"""

    def __init__(self, entries: dict[str, dict], edges: dict[str, list[str]]) -> None:
        self.entries = entries
        self.edges = edges

    @classmethod
    def default(cls) -> "Rules":
        return cls(ENTRIES, {k: list(v) for k, v in SUPPRESSION_EDGES.items()})

    def load_overrides(self, path: str | os.PathLike[str] | None) -> None:
        """`--rules FILE`：关规则 / 改严重度。文件格式见 README。"""
        if path is None:
            return
        file = Path(path)
        text = file.read_text(encoding="utf-8")
        if file.suffix == ".json":
            data = json.loads(text)
        else:
            data = tomllib.loads(text)
        for rule_id, override in (data.get("rules") or {}).items():
            if rule_id not in self.entries:
                continue
            if "enabled" in override:
                self.entries[rule_id]["enabled"] = bool(override["enabled"])
            if "severity" in override and override["severity"] in SEVERITIES:
                self.entries[rule_id]["severity"] = override["severity"]

    def enabled(self, rule_id: str) -> bool:
        return bool(self.entries.get(rule_id, {}).get("enabled", False))

    def severity(self, rule_id: str) -> str:
        return str(self.entries.get(rule_id, {}).get("severity", UNVERIFIED))

    def confidence(self, rule_id: str) -> str:
        return str(self.entries.get(rule_id, {}).get("confidence", LOW))

    def klass(self, rule_id: str) -> str:
        return str(self.entries.get(rule_id, {}).get("class", ENGINEERING))

    def suggestion(self, rule_id: str) -> str:
        return str(self.entries.get(rule_id, {}).get("suggestion", ""))

    def implemented(self) -> set[str]:
        """已实现的规则集（有检测函数就登记在 IMPLEMENTED 里）。"""
        return {rid for rid in self.entries if rid in IMPLEMENTED}


def _rule(group, severity, confidence, klass, desc, suggestion, *, enabled=True):
    return {
        "group": group,
        "severity": severity,
        "confidence": confidence,
        "class": klass,
        "desc": desc,
        "suggestion": suggestion,
        "enabled": enabled,
    }


# ────────────────────────── 规则表（7.2 的 P0 子集） ──────────────────────────
#
# `class` 的判据（用户 2026-10-11 裁定，见 process.md P-14）：
#   **缺东西 = engineering，值对不上 = config**
# 一开始把 B01/C01/C02/C04/C05/C06 全标成 config 是错的 —— 那会让 10.6 的
# 「工程化召回率 = L1命中∩engineering / L1总数∩engineering」分子分母恒为 0，
# 这一列永久失效，而且不报错、测试全过、数字看着正常。
# 本表里只有 G04（`.gitignore` 某行写法不对 = 配置值不对）属 config。

ENTRIES: dict[str, dict] = {
    # A 组 · 存根与依赖闭合
    "A01": _rule("A", BLOCKER, HIGH, ENGINEERING, "函数/方法体为空",
                 "实现或删除该存根"),
    "A02": _rule("A", BLOCKER, HIGH, ENGINEERING, "非抽象类中 raise NotImplementedError",
                 "实现该分支，或把类声明为 ABC/Protocol"),
    "A03": _rule("A", BLOCKER, HIGH, ENGINEERING, "存根被真实调用链引用",
                 "补实现后再动它的调用方"),
    "A04": _rule("A", BLOCKER, HIGH, ENGINEERING, "import 的模块在仓库中不存在且非三方包",
                 "确认是缺失模块还是外部依赖；外部依赖应写进依赖声明"),
    # B 组 · 测试与验收
    "B01": _rule("B", BLOCKER, HIGH, ENGINEERING, "无测试目录/测试文件",
                 "为核心路径补测试，或在问卷里显式声明不强制"),
    "B02": _rule("B", MAJOR, HIGH, ENGINEERING, "测试文件存在但无断言",
                 "补断言，或把它标成 fixture"),
    "B03": _rule("B", BLOCKER, HIGH, ENGINEERING, "静默零收集：有测试文件但收集用例数 == 0",
                 "检查收集期错误；没有用例的测试等于没有测试"),
    "B04": _rule("B", MAJOR, HIGH, ENGINEERING, "模块级 skip/xfail 或全量 skip",
                 "去掉全局 skip，或说明为什么必须跳过"),
    # C 组 · 工程化配置
    "C01": _rule("C", BLOCKER, HIGH, ENGINEERING, "无任何依赖/打包声明",
                 "补 pyproject.toml / setup.py / requirements.txt"),
    "C02": _rule("C", MAJOR, HIGH, ENGINEERING, "无 lint 配置",
                 "接入 ruff 或 flake8"),
    "C04": _rule("C", MINOR, HIGH, ENGINEERING, "无约束文件（工具会创建）",
                 "让工具生成约束文件，或自己写 CODEBUDDY.md"),
    "C05": _rule("C", MAJOR, HIGH, ENGINEERING, "pre-commit hook 未用隔离环境",
                 "把 language: system 的 hook 改成 pre-commit 托管的版本"),
    "C06": _rule("C", MINOR, HIGH, ENGINEERING, "无 CI 配置",
                 "补 CI，让 lint/type/test 在提交时真的跑起来"),
    # G 组 · 仓库卫生
    "G01": _rule("G", MAJOR, HIGH, ENGINEERING, ".git 体积超阈值（默认 20MB）",
                 "清理历史里的大文件（git filter-repo / BFG）"),
    "G02": _rule("G", BLOCKER, HIGH, ENGINEERING, "已跟踪大文件",
                 "移出版本库并加入 .gitignore，或用 Git LFS"),
    "G03": _rule("G", BLOCKER, MEDIUM, ENGINEERING, "疑似密钥/凭证",
                 "立刻轮换该凭证，并从历史中清除"),
    "G04": _rule("G", MAJOR, HIGH, CONFIG, ".gitignore 单行含空格分隔多 pattern（不生效）",
                 "一个 pattern 一行"),
    "G05": _rule("G", MAJOR, HIGH, ENGINEERING, ".gitignore 缺失或未忽略常见产物",
                 "补齐忽略规则"),
    "G07": _rule("G", MAJOR, HIGH, ENGINEERING, "仓库中跟踪了本该忽略的产物文件",
                 "git rm --cached 并补 .gitignore（补规则不会自动移除已跟踪文件）"),
    # I 组 · 接口契约一致性
    "I01": _rule("I", BLOCKER, HIGH, ENGINEERING, "__init__.py 导出的名字在目标模块中不存在",
                 "修导出名，或在目标模块里补上定义"),
}

# 有检测函数的规则（其余登记在册但未实现，命中不了也不该假装命中）
IMPLEMENTED = frozenset(ENTRIES)

# ────────────────────────── 抑制边（7.4） ──────────────────────────

SUPPRESSION_EDGES: dict[str, tuple[str, ...]] = {
    "C01": ("D01",),  # D01 不在首版五组，边保留以防将来实现时漏判
    "C06": ("B06",),
    "B01": ("B02", "B03", "B04"),
    "C02": ("E03",),
    "G05": ("G07",),
}
