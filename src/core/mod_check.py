"""Mod pre-flight conflict scan（N5，导入/启动前的模组冲突预检）。

纯静态、无网络：读实例 ``mods/`` 下每个 .jar 的依赖元数据（Fabric/Quilt
``*.mod.json``、Forge/NeoForge ``META-INF/mods.toml``），交叉比对已装模组，
在**启动前**就说出哪些组合会「装了也白装 / 直接打不开」，而不是等到崩溃后
才由 ``crash_analysis`` 事后分析。

支持的发现：
  · loader_mismatch — 实例是 Forge 却放了 Fabric/Quilt 模组（反之亦然）：
                      模组不会加载（Warning，非崩溃——只是白装）。
  · missing_dep     — 一个能加载的模组依赖另一个未安装的模组（Critical，
                      常见的真正崩溃源，如缺 Fabric API / 前置库）。
  · duplicate_id    — 两个 .jar 声明了同一个 mod id（不稳定/冲突，Warning）。

本模块不依赖 Qt、不外发网络，返回纯数据结构，便于无头回归测试。
"""
from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass, field

# 内部运行时 id：模组声明依赖它们不属于「缺少另一个模组」，跳过。
_INTERNAL_IDS = {
    "minecraft", "minecraft:java", "java", "fabricloader", "fabric-loader",
    "quilt_loader", "fabric", "mixin", "forge", "neoforge", "fml",
    # Quilt 标准库 / 游戏本身依赖
    "minecraft:nether", "minecraft:end", "minecraft:overworld",
}

# 加载器「家族」→ 可互通运行的加载器集合。
# fabric 家族（fabric / legacyfabric / quilt）都能跑 fabric.mod.json；
# forge 家族（forge / neoforge / cleanroom）都跑 mods.toml。
_FABRIC_FAMILY = {"fabric", "legacyfabric", "quilt"}
_FORGE_FAMILY = {"forge", "neoforge", "cleanroom"}

# id-key 勿拼错：既是 dataclass 字段名，也直接喂给 UI。
SEV_WARNING = "warning"
SEV_CRITICAL = "critical"
# info：提示级（如"可以装但没装的性能模组"）。core.instance_health 复用本
# dataclass 时用到；纯增量，不影响 scan_conflicts 既有消费方。
SEV_INFO = "info"


@dataclass
class Finding:
    kind: str                     # loader_mismatch / missing_dep / duplicate_id
    severity: str                 # critical / warning / info
    title: str                    # i18n key（对话框翻译）
    reason: str                   # i18n key（发生了什么）
    suggestion: str               # i18n key（怎么修）
    filenames: list[str] = field(default_factory=list)   # 涉及的 .jar
    meta: dict = field(default_factory=dict)             # 如 {"dep": "fabric-api", "need": "1.20.x"}
    # fix：可选的一键修复描述符（仅 core.instance_health 产出，None = 只报告）。
    # 结构见 instance_health.apply_fix；scan_conflicts 恒为 None，保持既有语义。
    fix: dict | None = None


@dataclass
class _ModMeta:
    id: str
    version: str
    filename: str
    family: str            # fabric / quilt / forge / unknown
    deps: dict             # mod id → version range


def _mods_dir(inst) -> str:
    return getattr(inst, "mods_dir", None) or os.path.join(
        getattr(inst, "mc_dir", ""), "mods")


def _list_jars(inst) -> list[str]:
    d = _mods_dir(inst)
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d)
                  if n.lower().endswith(".jar") and not n.startswith("."))


# ---- per-jar metadata parsing -------------------------------------------------
def _parse_jar(jar_path: str, filename: str) -> _ModMeta | None:
    """从 jar 内部分析 id / family / deps。解析不了返回 None。"""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())
            # Fabric / Quilt: 根下 *.mod.json
            meta_name = None
            if "fabric.mod.json" in names:
                meta_name, family = "fabric.mod.json", "fabric"
            elif "quilt.mod.json" in names:
                meta_name, family = "quilt.mod.json", "quilt"
            elif "META-INF/mods.toml" in names:
                meta_name, family = "META-INF/mods.toml", "forge"

            if meta_name:
                if family in ("fabric", "quilt"):
                    data = json.loads(zf.read(meta_name).decode("utf-8"))
                    mod_id = data.get("id") or ""
                    mod_ver = data.get("version") or ""
                    deps = dict(data.get("depends") or {})
                else:  # forge / neoforge
                    import tomllib
                    data = tomllib.loads(zf.read(meta_name).decode("utf-8"))
                    mods = data.get("mods") or []
                    mod_id = (mods[0].get("modId") if mods else None) or ""
                    mod_ver = (mods[0].get("version") if mods else None) or ""
                    deps = {}
                    # [[dependencies.<modid>]] 里 type=required 的依赖
                    for sec in data.get("dependencies", {}).values():
                        for entry in sec:
                            dep = entry.get("modId")
                            if not dep:
                                continue
                            # 跳过对自己/游戏/加载器的引用
                            if dep in (mod_id, "minecraft", "forge", "fml", "java"):
                                continue
                            if entry.get("type", "").lower() in ("required", "depends", "optional"):
                                deps.setdefault(dep, entry.get("versionRange", ""))
                if mod_id:
                    return _ModMeta(id=mod_id, version=mod_ver,
                                    filename=filename, family=family, deps=deps)
    except (OSError, zipfile.BadZipFile, KeyError, ValueError,
            json.JSONDecodeError):
        return None
    except Exception:  # noqa: BLE001 - 单个 jar 异常不影响整体扫描
        return None
    return None


def _family_loadable(family: str, inst_loader: str) -> bool:
    """该 family 的模组在目标实例加载器下能否被加载。unknown=都能。"""
    if family == "unknown":
        return True
    if family in ("fabric", "quilt"):
        return inst_loader in _FABRIC_FAMILY
    if family == "forge":
        return inst_loader in _FORGE_FAMILY
    return True


def scan_conflicts(inst) -> dict:
    """扫描实例 mods 目录并返回冲突发现。

    Returns {"findings": [Finding, ...], "critical": int, "warning": int,
             "scanned": int, "unknown": [filename, ...]}
    """
    inst_loader = (getattr(inst, "loader", "") or "").lower()
    files = _list_jars(inst)

    metas: list[_ModMeta] = []
    unknown: list[str] = []
    for fn in files:
        m = _parse_jar(os.path.join(_mods_dir(inst), fn), fn)
        if m and m.id:
            metas.append(m)
        else:
            unknown.append(fn)

    # 提供 map：mod id → 文件（只统计能在该实例加载的模组，避免误报）
    provided: dict[str, list[str]] = {}
    for m in metas:
        if _family_loadable(m.family, inst_loader):
            provided.setdefault(m.id, []).append(m.filename)

    findings: list[Finding] = []

    # 1) 加载器不匹配（装了也不给用）
    for m in metas:
        if not _family_loadable(m.family, inst_loader):
            findings.append(Finding(
                kind="loader_mismatch", severity=SEV_WARNING,
                title="modcheck.kind.loader_mismatch",
                reason="modcheck.reason.loader_mismatch",
                suggestion="modcheck.fix.loader_mismatch",
                filenames=[m.filename],
                meta={"mod_id": m.id, "family": m.family,
                      "inst_loader": inst_loader}))
            continue
        # 2) 缺少硬依赖（仅在「该模组确实会被加载」时报，避免噪音）
        for dep, dep_range in m.deps.items():
            if dep in _INTERNAL_IDS:
                continue
            if dep not in provided:
                findings.append(Finding(
                    kind="missing_dep", severity=SEV_CRITICAL,
                    title="modcheck.kind.missing_dep",
                    reason="modcheck.reason.missing_dep",
                    suggestion="modcheck.fix.missing_dep",
                    filenames=[m.filename],
                    meta={"mod_id": m.id, "dep": dep, "range": dep_range,
                          "inst_loader": inst_loader}))

    # 3) 重复 id（两个 jar 声明同一 mod id）
    for mid, fns in provided.items():
        if len(fns) > 1:
            findings.append(Finding(
                kind="duplicate_id", severity=SEV_WARNING,
                title="modcheck.kind.duplicate_id",
                reason="modcheck.reason.duplicate_id",
                suggestion="modcheck.fix.duplicate_id",
                filenames=list(fns),
                meta={"mod_id": mid}))

    n_crit = sum(1 for f in findings if f.severity == SEV_CRITICAL)
    n_warn = len(findings) - n_crit
    return {
        "findings": findings,
        "critical": n_crit,
        "warning": n_warn,
        "scanned": len(files),
        "unknown": unknown,
    }