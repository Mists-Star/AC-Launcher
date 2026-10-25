"""Instance health check（实例体检）— static, Qt-free instance diagnostics.

Composes ``core.mod_check`` conflict findings with performance-mod, JVM/memory,
Java-runtime and launch-argument checks. Findings reuse the same dataclass shape
as ``mod_check`` (i18n-key based ``title/reason/suggestion``) plus an optional
``fix`` descriptor.

Applying a fix **only mutates the ``Instance`` fields** — no I/O, no network,
no writes to the user's game directory. Missing performance mods are reported
but never auto-installed (the launcher stays offline for this feature).

The module imports no Qt so it can be exercised headless in regression tests.
``settings=None`` means "no global config available": checks that would fall
back to global values then use instance fields only.
"""
from __future__ import annotations

import os
import shlex

from . import mod_check
from .mod_check import Finding

SEV_INFO = mod_check.SEV_INFO
SEV_WARNING = mod_check.SEV_WARNING
SEV_CRITICAL = mod_check.SEV_CRITICAL

# 修复描述符的安全等级。本模块只产出 "safe"（纯本地写实例字段）。
FIX_SAFE = "safe"

# 与 crash_analysis.scan_mod_manifests 的上限一致：模组过多时跳过深扫，
# 避免 UI 线程被上百个 jar 的元数据读取拖死。
_MAX_SCAN_JARS = 60

# 加载器家族归类（对齐 mod_check 的 _FABRIC_FAMILY/_FORGE_FAMILY 语义）
_FABRIC_LOADERS = {"fabric", "legacyfabric", "quilt"}
_FORGE_LOADERS = {"forge", "neoforge", "cleanroom"}

# 公认的性能模组推荐集（按加载器家族）。每组是一个「多选一」候选元组：
# 任一命中即视为已满足。只收录社区一致推荐、低风险、收益明确的模组——
# 光影（iris）、indium、c2me 等属场景化/实验性，推荐它们会造成噪音与误伤，
# 故不列入「缺失」建议（但仍参与冲突检测）。
_PERF_EXPECT_FABRIC = [
    ("sodium", "embeddium"),
    ("lithium",),
    ("ferritecore",),
    ("modernfix",),
    ("entityculling",),
]
_PERF_EXPECT_FORGE = [
    ("embeddium", "rubidium"),
    ("ferritecore",),
    ("modernfix",),
    ("entityculling",),
]

# Java 兼容区间（对齐 core.java.select_java 的 max_ok 表）
_JAVA_MAX_OK = {8: 8, 16: 17, 17: 21, 21: 24, 25: 25}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _mods_dir(inst) -> str:
    return getattr(inst, "mods_dir", None) or os.path.join(
        getattr(inst, "mc_dir", ""), "mods")


def _jar_names(inst) -> list[str]:
    d = _mods_dir(inst)
    try:
        return sorted(n for n in os.listdir(d)
                      if n.lower().endswith(".jar") and not n.startswith("."))
    except OSError:
        return []


def _loader_family(inst) -> str:
    loader = (getattr(inst, "loader", "") or "").lower()
    if loader in _FABRIC_LOADERS:
        return "fabric"
    if loader in _FORGE_LOADERS:
        return "forge"
    if loader == "optifine":
        return "optifine"
    return "vanilla"


def _installed_ids(inst) -> set[str]:
    """实例 mods 目录里所有 jar 声明的 mod id（小写）。解析失败的 jar 忽略。"""
    from ..crash_analysis import scan_mod_manifests
    ids: set[str] = set()
    for m in scan_mod_manifests(inst):
        mid = (m.get("mod_id") or m.get("id") or "").strip().lower()
        if mid:
            ids.add(mid)
    return ids


def _eff_ram(inst, settings) -> int:
    v = int(getattr(inst, "ram_mb", 0) or 0)
    if v > 0:
        return v
    return int((settings or {}).get("ram_mb", 4096) or 4096)


def _eff_preset(inst, settings) -> str:
    v = (getattr(inst, "jvm_preset", "") or "").strip()
    if v:
        return v
    return ((settings or {}).get("jvm_preset") or "default")


def _fix(action: str, label: str, params: dict | None = None,
         label_kwargs: dict | None = None) -> dict:
    d = {"action": action, "params": params or {}, "safety": FIX_SAFE,
         "label": label}
    if label_kwargs:
        d["label_kwargs"] = label_kwargs
    return d


# --------------------------------------------------------------------------- #
# layer 1: performance mods (report-only)
# --------------------------------------------------------------------------- #
def _check_perf_mods(inst, settings) -> list[Finding]:
    findings: list[Finding] = []
    family = _loader_family(inst)
    if family == "vanilla":
        return findings      # 原版实例没有「该装的性能模组」概念

    names = _jar_names(inst)
    if not names:
        return findings      # 零模组：不报，避免给纯原版玩家刷提示
    if len(names) > _MAX_SCAN_JARS:
        return findings      # 模组过多（与 scan_mod_manifests 一致跳过）

    ids = _installed_ids(inst)
    if not ids:
        return findings      # 元数据全解析失败：宁可不报，也不误报

    # ---- 冲突：同装两个渲染优化模组 ----
    if "sodium" in ids and "embeddium" in ids:
        findings.append(Finding(
            kind="renderer_dup", severity=SEV_WARNING,
            title="health.kind.renderer_dup",
            reason="health.reason.renderer_dup",
            suggestion="health.fix.renderer_dup",
            filenames=[], meta={"a": "Sodium", "b": "Embeddium"}))

    # ---- 冲突：OptiFine 与 Sodium/Iris 同装 ----
    if family == "optifine" or "optifine" in ids or "optifabric" in ids:
        clash = sorted(ids & {"sodium", "embeddium", "iris", "oculus", "rubidium"})
        if clash:
            findings.append(Finding(
                kind="optifine_conflict", severity=SEV_WARNING,
                title="health.kind.optifine_conflict",
                reason="health.reason.optifine_conflict",
                suggestion="health.fix.optifine_conflict",
                filenames=[],
                meta={"mods": ", ".join(clash),
                      "loader": "OptiFine"}))

    # ---- 缺失：推荐集里一个都没装的组 ----
    # OptiFine 实例走 OptiFine 自己的路线，不给它推荐 Sodium 系。
    if family in ("fabric", "forge"):
        expect = _PERF_EXPECT_FABRIC if family == "fabric" else _PERF_EXPECT_FORGE
        missing: list[str] = []
        for group in expect:
            if not (ids & set(group)):
                missing.append(group[0])
        if missing:
            findings.append(Finding(
                kind="perf_mod_missing", severity=SEV_INFO,
                title="health.kind.perf_mod_missing",
                reason="health.reason.perf_mod_missing",
                suggestion="health.fix.perf_mod_missing",
                filenames=[],
                meta={"mods": ", ".join(missing),
                      "loader": family.capitalize()}))
    return findings


# --------------------------------------------------------------------------- #
# layer 2: JVM / memory
# --------------------------------------------------------------------------- #
def _check_jvm(inst, settings) -> list[Finding]:
    findings: list[Finding] = []
    ram = _eff_ram(inst, settings)
    preset = _eff_preset(inst, settings)
    extra = (getattr(inst, "jvm_args", "") or "")

    # 默认预设 + 内存充裕 → 建议整组切 Aikar（一次覆盖 GC / Pretouch /
    # DisableExplicitGC，避免再单发重复卡片）。
    aikar_off = (preset == "default" and ram >= 8192)
    if aikar_off:
        findings.append(Finding(
            kind="aikar_off", severity=SEV_INFO,
            title="health.kind.aikar_off",
            reason="health.reason.aikar_off",
            suggestion="health.fix.aikar_off",
            meta={"mb": ram},
            fix=_fix("set_preset_aikar", "health.fixlabel.set_preset_aikar")))

    # 自定义预设（玩家自己填的参数）→ 逐项检查缺失的常用开关
    if preset == "custom":
        if ram >= 8192 and "-XX:+AlwaysPreTouch" not in extra:
            findings.append(Finding(
                kind="pretouch_missing", severity=SEV_INFO,
                title="health.kind.pretouch_missing",
                reason="health.reason.pretouch_missing",
                suggestion="health.fix.pretouch_missing",
                fix=_fix("append_pretouch", "health.fixlabel.append_pretouch")))

    # G1GC 优化参数组（预设为 aikar/auto 时已内含，跳过）
    if (not getattr(inst, "perf_g1gc", True)) and preset not in ("aikar", "auto"):
        findings.append(Finding(
            kind="g1gc_off", severity=SEV_WARNING,
            title="health.kind.g1gc_off",
            reason="health.reason.g1gc_off",
            suggestion="health.fix.g1gc_off",
            fix=_fix("enable_g1gc", "health.fixlabel.enable_g1gc")))

    # 禁止显式 GC（aikar/auto 已内含 DisableExplicitGC，或已建议切 aikar 时跳过）
    if (not getattr(inst, "perf_disable_explicit_gc", False)) \
            and preset not in ("aikar", "auto") and not aikar_off \
            and "-XX:+DisableExplicitGC" not in extra:
        findings.append(Finding(
            kind="disable_explicit_gc_off", severity=SEV_INFO,
            title="health.kind.disable_explicit_gc_off",
            reason="health.reason.disable_explicit_gc_off",
            suggestion="health.fix.disable_explicit_gc_off",
            fix=_fix("enable_degc", "health.fixlabel.enable_degc")))

    # 内存分配区间
    if ram < 2048:
        findings.append(Finding(
            kind="ram_small", severity=SEV_WARNING,
            title="health.kind.ram_small",
            reason="health.reason.ram_small",
            suggestion="health.fix.ram_small",
            meta={"mb": ram},
            fix=_fix("set_ram", "health.fixlabel.set_ram",
                     {"mb": 4096}, {"mb": 4096})))
    elif ram > 16384:
        findings.append(Finding(
            kind="ram_large", severity=SEV_INFO,
            title="health.kind.ram_large",
            reason="health.reason.ram_large",
            suggestion="health.fix.ram_large",
            meta={"mb": ram},
            fix=_fix("set_ram", "health.fixlabel.set_ram",
                     {"mb": 8192}, {"mb": 8192})))
    return findings


# --------------------------------------------------------------------------- #
# layer 3: Java runtime
# --------------------------------------------------------------------------- #
def _java_major_for(javas: list[dict], path: str) -> int:
    """在扫描结果里按路径找该 java 的 major；找不到返回 0（未知，不判定）。"""
    target = os.path.normcase(os.path.normpath(path))
    for j in javas:
        p = (j.get("path") or "")
        if p and os.path.normcase(os.path.normpath(p)) == target:
            return int(j.get("major") or 0)
    return 0


def _check_java(inst, settings) -> list[Finding]:
    from .java import required_java_major_for, select_java, scan_javas

    findings: list[Finding] = []
    gv = (getattr(inst, "game_version", "") or "").strip()
    if not gv:
        return findings
    # Loader-aware: Cleanroom is 1.12.2 on Java 21.
    need = required_java_major_for(gv, getattr(inst, "loader", "") or "")
    max_ok = _JAVA_MAX_OK.get(need, need + 3)

    settings = settings or {}
    inst_path = (getattr(inst, "java_path", "") or "").strip()
    # 生效的 Java：实例指定优先；否则跟随全局——自动模式=扫描选，手动模式=全局路径
    eff_path = inst_path
    if not eff_path and not settings.get("java_auto", True):
        eff_path = (settings.get("java_path") or "").strip()

    if eff_path:
        javas = scan_javas()
        major = _java_major_for(javas, eff_path)
        # 只有能从扫描结果确认版本、且确实不兼容时才报（路径不在扫描表里
        # 说明是玩家手填的 JDK，不运行无法得知版本 → 不误报）。
        if major and not (need <= major <= max_ok):
            fixed = select_java(gv, java_auto=True, need_override=need)
            fix = (_fix("set_java_path", "health.fixlabel.set_java_path",
                        {"path": fixed}) if fixed
                   else _fix("clear_java_path", "health.fixlabel.clear_java_path"))
            findings.append(Finding(
                kind="java_mismatch", severity=SEV_CRITICAL,
                title="health.kind.java_mismatch",
                reason="health.reason.java_mismatch",
                suggestion="health.fix.java_mismatch",
                meta={"need": need, "have": major},
                fix=fix))
    else:
        # 跟随自动：连一个兼容 JDK 都找不到才报（无法自动修 → 只提示装 Java）
        if select_java(gv, java_auto=True, need_override=need) is None:
            findings.append(Finding(
                kind="java_missing", severity=SEV_CRITICAL,
                title="health.kind.java_missing",
                reason="health.reason.java_missing",
                suggestion="health.fix.java_missing",
                meta={"need": need}))
    return findings


# --------------------------------------------------------------------------- #
# layer 4: launch arguments
# --------------------------------------------------------------------------- #
def _check_launch_args(inst) -> list[Finding]:
    findings: list[Finding] = []

    ga = (getattr(inst, "game_args", "") or "").strip()
    if ga:
        from ..launch import parse_game_args
        server, port, extra = parse_game_args(ga)
        if server or port:
            findings.append(Finding(
                kind="residual_server_arg", severity=SEV_WARNING,
                title="health.kind.residual_server_arg",
                reason="health.reason.residual_server_arg",
                suggestion="health.fix.residual_server_arg",
                meta={"server": server or "?", "port": port or "-"},
                # 保留非 server 部分，只剥离残留直连参数
                fix=_fix("clear_game_args", "health.fixlabel.clear_game_args",
                         {"keep": " ".join(extra)})))

    ja = (getattr(inst, "jvm_args", "") or "").strip()
    if ja:
        try:
            shlex.split(ja)
        except ValueError:
            findings.append(Finding(
                kind="malformed_jvm_args", severity=SEV_WARNING,
                title="health.kind.malformed_jvm_args",
                reason="health.reason.malformed_jvm_args",
                suggestion="health.fix.malformed_jvm_args"))
    return findings


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def scan_health(inst, settings: dict | None = None) -> dict:
    """对实例做一次完整体检，返回分区结果 + 计数 + 可修复数。

    Returns {"findings": [Finding, ...], "groups": [{"key", "findings"}],
             "critical": n, "warning": n, "info": n, "scanned": n,
             "fixable": n}
    """
    def _safe(fn, *a):
        try:
            return fn(*a)
        except Exception:  # noqa: BLE001 - 单项检查失败绝不影响整体体检
            return []

    conflict = _safe(mod_check.scan_conflicts, inst)
    conflict_findings = list(conflict.get("findings") or []) if conflict else []

    sections = [
        ("mods", conflict_findings),
        ("perf", _safe(_check_perf_mods, inst, settings)),
        ("jvm", _safe(_check_jvm, inst, settings)),
        ("java", _safe(_check_java, inst, settings)),
        ("args", _safe(_check_launch_args, inst)),
    ]
    groups = [{"key": k, "findings": fs} for k, fs in sections if fs]
    findings = [f for _k, fs in sections for f in fs]

    n_crit = sum(1 for f in findings if f.severity == SEV_CRITICAL)
    n_warn = sum(1 for f in findings if f.severity == SEV_WARNING)
    n_info = len(findings) - n_crit - n_warn
    fixable = sum(1 for f in findings if f.fix)
    return {
        "findings": findings,
        "groups": groups,
        "critical": n_crit,
        "warning": n_warn,
        "info": n_info,
        "scanned": (conflict or {}).get("scanned", 0),
        "fixable": fixable,
    }


def apply_fix(inst, fix: dict) -> bool:
    """按修复描述符改写实例字段。返回是否真的发生了变更（幂等：无变化=False）。"""
    if not isinstance(fix, dict):
        return False
    action = fix.get("action")
    params = fix.get("params") or {}

    if action == "enable_g1gc":
        if not getattr(inst, "perf_g1gc", True):
            inst.perf_g1gc = True
            return True
        return False
    if action == "enable_degc":
        if not getattr(inst, "perf_disable_explicit_gc", False):
            inst.perf_disable_explicit_gc = True
            return True
        return False
    if action == "set_preset_aikar":
        if (getattr(inst, "jvm_preset", "") or "") != "aikar":
            inst.jvm_preset = "aikar"
            return True
        return False
    if action == "set_preset_auto":
        if (getattr(inst, "jvm_preset", "") or "") != "auto":
            inst.jvm_preset = "auto"
            return True
        return False
    if action == "set_ram":
        try:
            mb = int(params.get("mb") or 0)
        except (TypeError, ValueError):
            mb = 0
        if mb > 0 and int(getattr(inst, "ram_mb", 0) or 0) != mb:
            inst.ram_mb = mb
            return True
        return False
    if action == "append_pretouch":
        flag = "-XX:+AlwaysPreTouch"
        args = (getattr(inst, "jvm_args", "") or "").strip()
        if flag in args:
            return False
        inst.jvm_args = (args + " " + flag).strip() if args else flag
        return True
    if action == "set_renderer":
        v = params.get("value") or "auto"
        if (getattr(inst, "renderer", "") or "auto") != v:
            inst.renderer = v
            return True
        return False
    if action == "clear_game_args":
        keep = (params.get("keep") or "").strip()
        if (getattr(inst, "game_args", "") or "").strip() != keep:
            inst.game_args = keep
            return True
        return False
    if action == "set_java_path":
        p = (params.get("path") or "").strip()
        if p and (getattr(inst, "java_path", "") or "") != p:
            inst.java_path = p
            return True
        return False
    if action == "clear_java_path":
        if getattr(inst, "java_path", ""):
            inst.java_path = ""
            return True
        return False
    return False


def apply_all_safe(inst, findings: list) -> int:
    """批量应用所有安全修复。返回实际生效的条数。"""
    n = 0
    for f in findings or []:
        fx = getattr(f, "fix", None)
        if fx and fx.get("safety", FIX_SAFE) == FIX_SAFE:
            if apply_fix(inst, fx):
                n += 1
    return n
