"""round-166：按磁盘现状重构实例定义（只读扫描，不删/不改游戏文件）。

用途：实例记录（版本 / 加载器 / 加载器版本 / 启动版本 id / 布局格式）与磁盘
真实结构漂移时（手工搬目录、整合包覆盖、来源启动器升级），用磁盘上的版本
json 重新推导这些字段，而不是让玩家删除重建整个实例。

只读保证：本模块只读 ``versions/**/*.json``，写回由调用方 ``mgr.save``。
"""
from __future__ import annotations

import json
import os

# 来源启动器的元数据 json（不是 Minecraft 版本文件，扫描时排除）
_META_JSON = {"mmc-pack", "minecraftinstance", "profile", "instance",
              "modrinth.index", "pack"}

# 顺序很重要：*forge* 会命中 neoforge、*fabric* 会命中 legacyfabric
_LOADER_TOKENS = (
    ("legacyfabric", "legacyfabric"),
    ("fabric", "fabric"),
    ("quilt", "quilt"),
    ("neoforge", "neoforge"),
    ("cleanroom", "cleanroom"),
    ("liteloader", "liteloader"),
    ("optifine", "optifine"),
    ("forge", "forge"),
)


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def infer_loader(version_id: str, libraries=()) -> str:
    """从启动版本 id / 依赖库判定加载器；判不出返回 ""（视为原版）。"""
    low = (version_id or "").lower()
    for token, name in _LOADER_TOKENS:
        if token in low:
            return name
    names = []
    for lib in libraries or ():
        if isinstance(lib, dict):
            names.append(str(lib.get("name") or "").lower())
    joined = " ".join(names)
    if "net.fabricmc:fabric-loader" in joined:
        return "fabric"
    if "net.legacyfabric" in joined:
        return "legacyfabric"
    if "org.quiltmc:quilt-loader" in joined:
        return "quilt"
    if "net.neoforged" in joined:
        return "neoforge"
    if "net.minecraftforge" in joined:
        return "forge"
    if "com.mumfrey:liteloader" in joined:
        return "liteloader"
    if "optifine" in joined:
        return "optifine"
    return ""


def loader_version_of(loader: str, version_id: str, libraries=(),
                      base_version: str = "") -> str:
    """从启动版本 id / 依赖库提取加载器版本号；提取不到返回 ""。"""
    raw = (version_id or "").strip()
    low = raw.lower()
    # fabric / legacyfabric / quilt：<loader>-loader-<ver>-<mc>
    for tag in ("legacyfabric-loader-", "fabric-loader-", "quilt-loader-"):
        i = low.find(tag)
        if i >= 0:
            rest = raw[i + len(tag):]
            if base_version and rest.lower().endswith("-" + base_version.lower()):
                rest = rest[:-(len(base_version) + 1)]
            return rest.strip("-")
    # neoforge：neoforge-<ver> 或 <mc>-neoforge-<ver>
    if low.startswith("neoforge-"):
        return raw[len("neoforge-"):].strip("-")
    if "-neoforge-" in low:
        return raw.split("-neoforge-", 1)[1].strip("-")
    # cleanroom：Cleanroom-<ver>
    if low.startswith("cleanroom-"):
        return raw[len("cleanroom-"):].strip("-")
    # forge：<mc>-forge-<ver> 或 forge-<ver>
    if "-forge-" in low:
        return raw.split("-forge-", 1)[1].strip("-")
    if low.startswith("forge-"):
        return raw[len("forge-"):].strip("-")
    # 依赖库兜底（老版本 json 的 id 可能不带版本号）
    for lib in libraries or ():
        if not isinstance(lib, dict):
            continue
        name = str(lib.get("name") or "")
        for prefix in ("net.minecraftforge:forge:", "net.neoforged:neoforge:",
                       "net.fabricmc:fabric-loader:",
                       "org.quiltmc:quilt-loader:",
                       "com.mumfrey:liteloader:"):
            if name.startswith(prefix):
                ver = name[len(prefix):]
                if base_version and ver.startswith(base_version + "-"):
                    ver = ver[len(base_version) + 1:]
                return ver.strip("-")
    return ""


def _collect_candidates(inst) -> list[tuple[str, str, dict]]:
    """收集该实例可能的版本 json：[(name, path, data)]。"""
    from ..instances import layout_of
    out: list[tuple[str, str, dict]] = []
    seen = set()

    def _add(name: str, path: str) -> None:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen or not os.path.isfile(path):
            return
        seen.add(key)
        out.append((name, path, _read_json(path)))

    # 1) 标准布局：<install_root>/versions/<id>/<id>.json
    root = layout_of(inst).get("install_dir") or inst.mc_dir
    vdir = os.path.join(root, "versions")
    if os.path.isdir(vdir):
        try:
            names = sorted(os.listdir(vdir))
        except OSError:
            names = []
        for name in names:
            _add(name, os.path.join(vdir, name, f"{name}.json"))

    # 2) 版本隔离布局：mc_dir 本身就是 versions/<id>，json 扁平躺在 mc_dir
    mc = inst.mc_dir
    if os.path.isdir(mc):
        try:
            files = sorted(os.listdir(mc))
        except OSError:
            files = []
        for fn in files:
            # round-179：点开头的隐藏 json 一律不是版本文件（AC 专属布局
            # 标识 .ac-layout.json 就落在 mc_dir 里，混进来会让「无版本
            # 文件」误判成有，重构出完全错误的实例定义）。
            if not fn.lower().endswith(".json") or fn.startswith("."):
                continue
            name = fn[:-5]
            if name.lower() in _META_JSON:
                continue
            _add(name, os.path.join(mc, fn))
    return out


def _score(inst, name: str, data: dict) -> int:
    s = 0
    cur_id = (getattr(inst, "version_id", "") or "").strip().lower()
    cur_ver = (getattr(inst, "game_version", "") or "").strip().lower()
    cur_loader = (getattr(inst, "loader", "") or "").strip().lower()
    low = name.lower()
    inherit = str(data.get("inheritsFrom") or data.get("jar") or "").lower()
    vid = str(data.get("id") or name).lower()
    if cur_id and low == cur_id:
        s += 100
    if cur_ver and low == cur_ver:
        s += 80
    elif cur_ver and cur_ver in low:
        # 仅在非精确命中时给「包含版本号」加分，避免原版 json 双重计分
        s += 15
    if inherit and cur_ver and inherit == cur_ver:
        s += 40
    if inherit and cur_loader not in ("", "auto", "vanilla"):
        s += 25
    if cur_loader and cur_loader in vid:
        s += 10
    return s


def reconstruct(inst) -> dict:
    """按磁盘现状重建实例定义（就地修改 ``inst``，不落盘）。

    返回 ``{"ok": bool, "reason": str, "changed": [字段名], "version": str}``。
    """
    cands = _collect_candidates(inst)
    if not cands:
        return {"ok": False, "reason": "instances.rebuild_no_files",
                "changed": [], "version": ""}
    best = max(cands, key=lambda c: _score(inst, c[0], c[2]))

    name, path, data = best
    vid = str(data.get("id") or name).strip() or name
    base = str(data.get("inheritsFrom") or data.get("jar") or "").strip()
    libs = data.get("libraries") or ()

    if base:
        # 加载器版本 json：本体继承原版
        game_version = base
        loader = infer_loader(vid, libs) or (inst.loader or "vanilla")
        loader_version = loader_version_of(loader, vid, libs, base)
        version_id = vid
    else:
        # 原版 / 无继承的独立版本 json
        game_version = vid
        loader = "vanilla"
        loader_version = ""
        version_id = ""

    changed = []
    for attr, val in (("game_version", game_version), ("loader", loader),
                      ("loader_version", loader_version),
                      ("version_id", version_id)):
        if getattr(inst, attr, "") != val:
            setattr(inst, attr, val)
            changed.append(attr)
    # 布局格式回到自适应：按磁盘真实结构重新判定（round-164 的 layout_of 口径）
    if (getattr(inst, "format", "") or "").strip() not in ("", "auto"):
        inst.format = ""
        changed.append("format")
    if getattr(inst, "needs_convert", False):
        inst.needs_convert = False
        changed.append("needs_convert")
    return {"ok": True, "reason": "", "changed": changed,
            "version": version_id or game_version, "path": path}
