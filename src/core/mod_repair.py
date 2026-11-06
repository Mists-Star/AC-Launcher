# -*- coding: utf-8 -*-
"""round-178：模组依赖「扫描 → 匹配 → 补装」的唯一实现。

三处 UI 入口（崩溃弹窗「一键修复」、实例右键、体检对话框）此前各写一套：
``crash_dialog._repair_deps`` 自己调 ``find_missing_dependencies``，
``crash_dialog._repair_all`` 只调前者，``diagnostics.repair_all`` 完全不查模组，
``instance_health.scan_conflicts`` 产出的缺前置 finding 又恒 ``fix=None``。
结果同一个「补装依赖」在三个地方语义不一样、失败也没有可解释的终态。

本模块只负责**模组依赖**这一件事（配置 / 账户 / 游戏文件修复仍归
``diagnostics``），返回结构化结果，任何入口都能显示：
``{downloaded, failed, skipped, jar_count, missing, message}``。
"""
from __future__ import annotations

import os
import re

# 与 crash_analysis.scan_mod_manifests 的深扫上限保持一致
MAX_SCAN_JARS = 60

# 这些 id 由游戏 / 加载器本身提供，不是需要下载的 mod
_BUILTIN_IDS = frozenset({
    "minecraft", "java", "fabricloader", "forge", "neoforge",
    "quilt_loader", "fabric-api-base",
})


def _mods_dir(inst) -> str:
    return (getattr(inst, "mods_dir", None)
            or os.path.join(getattr(inst, "mc_dir", "") or "", "mods"))


def scan_missing(inst) -> dict:
    """只读扫描缺失依赖，并显式区分「没有缺失」与「扫描被跳过」。

    ``crash_analysis.scan_mod_manifests`` 在 jar > 60 时返回 ``[]``；旧代码
    把它当成「一个 mod 都没有」→ 弹「依赖齐全」，是**误报正常**。
    """
    from .. import crash_analysis

    mods_dir = _mods_dir(inst)
    jars = []
    if os.path.isdir(mods_dir):
        jars = [n for n in os.listdir(mods_dir)
                if n.lower().endswith(".jar")]
    jar_count = len(jars)
    if jar_count > MAX_SCAN_JARS:
        return {
            "missing": [], "jar_count": jar_count, "skipped": True,
            "message": ("模组数量 %d 超过深扫上限 %d，已跳过依赖扫描"
                        "（不代表依赖齐全）" % (jar_count, MAX_SCAN_JARS)),
        }
    missing = [d for d in crash_analysis.find_missing_dependencies(inst)
               if d not in _BUILTIN_IDS]
    return {
        "missing": missing, "jar_count": jar_count, "skipped": False,
        "message": ("发现 %d 个缺失依赖" % len(missing)) if missing
                   else "依赖齐全",
    }


def match_project(dep: str, hits: list[dict]) -> dict | None:
    """精确解析 mod id → Modrinth 项目，拒绝模糊命中装进无关模组。

    旧实现用 ``dep in slug`` 模糊匹配并以搜索结果首项兜底，``fabric-api``
    会匹配到 ``fabric-api-base`` 之类；这里只接受 slug / 标题
    **规范化后完全相等**。
    ☠ 刻意不做 ``startswith(dep + "-")`` 的「同项目子模块」宽松命中——
    那正是 ``fabric-api`` → ``fabric-api-base`` 装错项目的来源。匹配不上
    就明确计入 failed，让玩家自己到资源中心装，比静默装错好。
    """
    def norm(value) -> str:
        # Modrinth 标题常写作 "Fabric API"，而 modid 是 "fabric-api"：
        # 空格 / 下划线归一成连字符后仍是**精确等价**，不是模糊包含。
        return re.sub(r"[\s_]+", "-", str(value or "").strip().lower())

    d = norm(dep)
    if not d or not hits:
        return None
    for h in hits:
        if not isinstance(h, dict):
            continue
        if norm(h.get("slug")) == d or norm(h.get("title")) == d:
            return h
    return None


def repair_missing(inst, missing_ids: list[str] | None = None,
                   callback=None) -> dict:
    """联网补装缺失依赖。不抛异常，所有失败以结构化条目返回。

    ``failed`` 每项 ``{id, stage, reason}``，stage ∈ search / match /
    download —— UI 终于能区分「搜不到」「匹配不上」「下载失败」。
    """
    from ..net_api import NetError, download_mod_to, search_mods

    result = {
        "downloaded": [], "failed": [], "skipped": False,
        "jar_count": 0, "missing": [], "message": "",
    }
    scan = scan_missing(inst)
    result["skipped"] = scan["skipped"]
    result["jar_count"] = scan["jar_count"]
    result["missing"] = list(missing_ids if missing_ids is not None
                             else scan["missing"])
    if scan["skipped"]:
        result["message"] = scan["message"]
        return result
    if not result["missing"]:
        result["message"] = scan["message"]
        return result

    mc = getattr(inst, "game_version", "") or ""
    loader = getattr(inst, "loader", "") or ""
    mods_dir = _mods_dir(inst)
    for dep in result["missing"]:
        if callback:
            callback("正在查找依赖：%s …" % dep)
        try:
            hits = search_mods(dep, 0, 5, project_type="mod")
        except Exception as e:  # noqa: BLE001 - 网络失败要能解释
            result["failed"].append(
                {"id": dep, "stage": "search", "reason": str(e)})
            continue
        target = match_project(dep, hits or [])
        if target is None:
            result["failed"].append(
                {"id": dep, "stage": "match",
                 "reason": "未在 Modrinth 找到同名项目（已放弃模糊匹配）"})
            continue
        if callback:
            callback("下载依赖：%s …" % (target.get("title") or dep))
        try:
            path = download_mod_to(target["project_id"], mods_dir, mc, loader)
            result["downloaded"].append(os.path.basename(path))
        except Exception as e:  # noqa: BLE001 - 任何失败都要有终态
            result["failed"].append(
                {"id": dep, "stage": "download", "reason": str(e)})

    n_ok = len(result["downloaded"])
    n_fail = len(result["failed"])
    result["message"] = ("已补装 %d 个依赖" % n_ok if n_ok else "未能补装依赖")
    if n_fail:
        result["message"] += "，%d 项失败（见明细）" % n_fail
    return result


def failed_lines(result: dict) -> list[str]:
    """把结构化失败转成 UI 可直接展示的逐行文本。"""
    label = {"search": "搜索失败", "match": "未找到匹配项目",
             "download": "下载失败"}
    return ["• %s：%s — %s" % (f.get("id", "?"),
                              label.get(f.get("stage"), "失败"),
                              f.get("reason", ""))
            for f in result.get("failed", [])]
