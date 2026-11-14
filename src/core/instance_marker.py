# -*- coding: utf-8 -*-
"""AC 专属实例布局标识（round-179）。

方案：新建/下载时本来就能选格式（AC 自有 / 原版共享 / 版本隔离 / 其它
启动器实例），给这些格式一个**只有 AC 识别**的标识；启动时先找标识，命中就
按记录的路径映射查漏补缺，没标识才看一遍磁盘特征并把结果写下来。目的：
省掉「每次都重新猜格式 → 猜错 → 按错的根补全 → 再查验完整性」的循环。

文件放在
``.minecraft``）。点开头的未知 JSON，Minecraft 与 PCL2 / HMCL / Prism 都
不读、不索引；它们最多忽略它，**不影响正常启动、不影响迁移、不影响识别**。

☠ 三条铁律：
1. 标识是「探测结果的缓存」，**不是真理源**。指纹不匹配 / 置信度低 / 结构
   被外部改动时一律降级到实时探测，绝不拿一张旧表硬补。
2. 标识内容不是格式枚举，而是**逐项路径映射**——格式枚举表达不了
   「游戏目录被拆成多层、各资源分散在不同层」的极端布局。
3. 只在探测置信度高时落盘。低置信度写死一张错表，比没有标识更糟。
"""
from __future__ import annotations

import hashlib
import json
import os
import time

MARKER_NAME = ".ac-layout.json"
SCHEMA = 1

# 与 instances.INSTANCE_FORMATS 对齐（这里不 import，避免循环依赖）
KNOWN_FORMATS = frozenset({
    "auto", "ac", "vanilla", "iso", "multimc", "curseforge", "modrinth",
    "custom",
})

# 路径映射表的键；全部是**相对于 mc_dir** 的路径
PATH_KEYS = ("install_dir", "versions_root", "mods_dir", "saves_dir",
             "assets_dir", "libraries_dir")

_MAX_PARENT_HOPS = 3  # flat / iso 布局最多允许回溯到 mc 的第 3 级父目录


def marker_path(inst) -> str:
    return os.path.join(inst.mc_dir, MARKER_NAME)


def fingerprint(mc_dir: str) -> str:
    """目录结构摘要：标识是否还适用于当前磁盘状态。

    只取顶层条目名 + 少量关键存在性，避免对上万个文件做哈希。目录被搬走、
    被别的启动器重建、或补齐了 versions/ 后，指纹都会变 → 标识自动失效。
    """
    h = hashlib.sha1()  # noqa: S324 - 变化检测，非安全用途
    try:
        names = sorted(os.listdir(mc_dir))
    except OSError:
        names = []
    ignore = (MARKER_NAME, MARKER_NAME + ".tmp")
    for n in names:
        if n in ignore:
            continue  # 自己与原子写临时文件都不能进指纹，否则写完就失效
        h.update(n.encode("utf-8", "replace"))
        h.update(b"\0")
    for rel in ("versions", "mods", "libraries", "assets", "saves",
                "mmc-pack.json", "minecraftinstance.json", "profile.json",
                "instance.cfg"):
        try:
            h.update(b"1" if os.path.exists(os.path.join(mc_dir, rel)) else b"0")
        except OSError:
            h.update(b"0")
    return h.hexdigest()


def _safe_rel(rel) -> bool:
    """相对路径校验：挡绝对路径、盘符、过度上跳。"""
    if not isinstance(rel, str) or not rel.strip():
        return False
    p = rel.replace("\\", "/")
    if os.path.isabs(rel) or p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        return False
    parts = [x for x in p.split("/") if x and x != "."]
    if not parts:
        return True  # "." = mc_dir 本身
    hops = sum(1 for x in parts if x == "..")
    return hops <= _MAX_PARENT_HOPS


def absolute_paths(mc_dir: str, paths: dict) -> dict:
    """相对路径表 → 绝对路径表；不合法的路径退化成 mc_dir 本身。"""
    out = {}
    for key in PATH_KEYS:
        rel = (paths or {}).get(key, ".")
        if not _safe_rel(rel):
            rel = "."
        out[key] = os.path.normpath(os.path.join(mc_dir, rel))
    return out


def relative_paths(mc_dir: str, paths_abs: dict) -> dict:
    out = {}
    for key in PATH_KEYS:
        p = (paths_abs or {}).get(key) or mc_dir
        try:
            rel = os.path.relpath(p, mc_dir)
        except ValueError:  # 不同盘符
            rel = "."
        out[key] = rel.replace("\\", "/")
    return out


def read(inst) -> dict | None:
    """读标识；任何异常/过期/低置信度都返回 None 让调用方降级。"""
    mc = inst.mc_dir
    path = os.path.join(mc, MARKER_NAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    if data.get("confidence") != "high":
        return None
    if data.get("fmt") not in KNOWN_FORMATS:
        return None
    # 标识绑定实例身份：同一游戏目录被另一个实例接管、来源判定变了、
    # 游戏版本换了、或玩家在设置里改了手选格式 → 旧标识一律作废重探。
    for key, attr in (("owner", "id"), ("kind", "kind"),
                      ("launcher", "launcher"),
                      ("game_version", "game_version"),
                      ("declared_format", "format")):
        if str(data.get(key, "")) != str(getattr(inst, attr, "") or ""):
            return None
    if data.get("fingerprint") != fingerprint(mc):
        return None
    paths = data.get("paths")
    if not isinstance(paths, dict) or any(
            not _safe_rel(paths.get(k, ".")) for k in PATH_KEYS):
        return None
    out = dict(data)
    out["abs_paths"] = absolute_paths(mc, paths)
    return out


def write(inst, fmt: str, paths_abs: dict, confidence: str = "high",
          flat: bool = False) -> bool:
    """原子写标识。低置信度不落盘；只读目录 / 外部实例写失败静默返回 False。"""
    if confidence != "high" or fmt not in KNOWN_FORMATS or fmt == "auto":
        return False
    mc = inst.mc_dir
    try:
        os.makedirs(mc, exist_ok=True)
        data = {
            "schema": SCHEMA,
            "fmt": fmt,
            "confidence": "high",
            "flat": bool(flat),
            "created_at": int(time.time()),
            "fingerprint": fingerprint(mc),
            "owner": str(getattr(inst, "id", "") or ""),
            "kind": str(getattr(inst, "kind", "") or ""),
            "launcher": str(getattr(inst, "launcher", "") or ""),
            "game_version": str(getattr(inst, "game_version", "") or ""),
            "declared_format": str(getattr(inst, "format", "") or ""),
            "paths": relative_paths(mc, paths_abs),
        }
        tmp = os.path.join(mc, MARKER_NAME + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, os.path.join(mc, MARKER_NAME))
        return True
    except (OSError, ValueError, TypeError):
        try:
            os.remove(os.path.join(mc, MARKER_NAME + ".tmp"))
        except OSError:
            pass
        return False


def verify(paths_abs: dict) -> dict:
    """「查漏补缺」：按标识的路径映射逐项验证目录存在性（**只读，不创建**）。

    真正的下载/补全仍由 ``core.install.install_instance`` 负责；这里只回答
    「该有的目录齐不齐」，避免标识系统擅自往外部实例里建目录。
    """
    checked, missing = [], []
    for key in PATH_KEYS:
        p = (paths_abs or {}).get(key)
        if not p:
            continue
        checked.append(key)
        if not os.path.isdir(p):
            missing.append(key)
    return {"ok": not missing, "checked": checked, "missing": missing}
