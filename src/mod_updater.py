"""Mod 一键更新（round-41，对齐 Prism / CurseForge App 的高频功能）。

流程：
1. 扫描实例 mods 目录的 .jar
2. 从文件名启发式解析 Modrinth slug（去版本段/loader 后缀，逐个试 /v2/project/{slug}）
3. 对比在线最新版本号，列出可更新
4. 批量下载新版（断点续传）→ 替换旧文件（旧文件移入 mods/.updates_backup/）

文件名→slug 启发式（Modrinth 下载文件名形如 ``<slug>-<loader>-<version>+mc<mc>.jar``
或 ``<slug>-<version>.jar``）：去 .jar → 去 ``+mc`` / ``-mc`` 版本段 → 逐段
剥末尾版本号/已知 loader 名 → 得到候选 slug 列表，逐个请求 project 信息，
命中即用。识别不了的 mod 跳过（返回 unknown 列表）。
"""
from __future__ import annotations

import os
import re

from .net_api import get_project_info, _modrinth_versions, _version_primary_file, NetError

_LOADER_HINTS = ("fabric", "forge", "quilt", "neoforge", "optifine", "liteloader")
_MC_SUFFIX_RE = re.compile(r"[+-]mc[\d.]+$")


def parse_mod_slug(filename: str) -> list[str]:
    """文件名 → 候选 Modrinth slug 列表（从精确到宽松）。"""
    name = filename[:-4] if filename.lower().endswith(".jar") else filename
    # 去 MC 版本后缀：sodium-fabric-0.5.13+mc1.20.1 → sodium-fabric-0.5.13
    m = _MC_SUFFIX_RE.search(name)
    if m:
        name = name[:m.start()]
    cands = [name]
    parts = name.split("-")
    # 剥末尾版本号段（以数字开头或含 + . 的段）
    while parts and (re.match(r"^\d", parts[-1]) or "+" in parts[-1] or "." in parts[-1]):
        parts.pop()
        cands.append("-".join(parts))
    # 剥末尾 loader 名（fabric/forge/...）
    while parts and parts[-1].lower() in _LOADER_HINTS:
        parts.pop()
        cands.append("-".join(parts))
    # 去重保序
    seen = set()
    out = []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def scan_installed_mods(inst) -> list[str]:
    """实例 mods 目录所有 .jar 文件名（排序）。"""
    mods_dir = getattr(inst, "mods_dir", None) or os.path.join(
        getattr(inst, "mc_dir", ""), "mods")
    if not os.path.isdir(mods_dir):
        return []
    return sorted(n for n in os.listdir(mods_dir) if n.lower().endswith(".jar"))


def _resolve_slug(filename: str) -> str | None:
    """尝试解析出可用的 Modrinth slug（None=识别不了）。"""
    for slug in parse_mod_slug(filename):
        try:
            info = get_project_info(slug)
            if info and isinstance(info, dict) and info.get("id"):
                return slug
        except NetError:
            return None  # 网络错误：整个检查中止（不是 404，404 已被 get_project_info 缓存 None）
    return None


def check_updates(inst, *, mc_version: str = "", loader: str = "",
                  on_progress=None) -> dict:
    """扫描并检查所有已装 mod 的更新。

    Returns {"updates": [{filename, slug, title, local_version, latest_version,
                          url, project_id}], "unknown": [filename, ...], "count": n}
    网络错误/识别不了的 mod 进 unknown 不中断。
    """
    updates: list[dict] = []
    unknown: list[str] = []
    files = scan_installed_mods(inst)
    mc = mc_version or getattr(inst, "game_version", "") or ""
    ld = loader or getattr(inst, "loader", "") or ""
    for i, filename in enumerate(files):
        if on_progress:
            try:
                on_progress(i + 1, len(files), filename)
            except Exception:
                pass
        slug = _resolve_slug(filename)
        if not slug:
            unknown.append(filename)
            continue
        try:
            info = get_project_info(slug)
            if not info or not isinstance(info, dict) or not info.get("id"):
                unknown.append(filename)
                continue
            pid = info["id"]
            title = info.get("title") or slug
            versions = _modrinth_versions(pid, mc, ld)
            if not versions:
                unknown.append(filename)
                continue
            new_filename, url = _version_primary_file(versions[0], pid)
            # 本地版本号：文件名去 slug 前缀后的部分（仅用于展示）
            local_ver = filename[:-4]
            for c in parse_mod_slug(filename):
                if filename.startswith(c):
                    local_ver = filename[len(c) + 1:-4] if len(filename) > len(c) + 1 else ""
                    break
            if new_filename != filename and url:
                updates.append({
                    "filename": filename,
                    "slug": slug,
                    "title": title,
                    "local_version": local_ver or "?",
                    "latest_version": new_filename[:-4],
                    "url": url,
                    "project_id": pid,
                })
        except NetError:
            unknown.append(filename)
    return {"updates": updates, "unknown": unknown, "count": len(updates)}


def update_mods(inst, updates: list[dict], *, on_progress=None) -> int:
    """批量下载新版并替换旧文件。返回成功数。旧文件移入 mods/.updates_backup/。"""
    from .net_api import download_file

    mods_dir = getattr(inst, "mods_dir", None) or os.path.join(
        getattr(inst, "mc_dir", ""), "mods")
    os.makedirs(mods_dir, exist_ok=True)
    ok = 0
    for i, u in enumerate(updates, start=1):
        if on_progress:
            try:
                on_progress(i, len(updates), u["slug"])
            except Exception:
                pass
        try:
            new_path = download_file(u["url"], os.path.join(mods_dir, u["latest_version"] + ".jar"))
            old = os.path.join(mods_dir, u["filename"])
            if new_path != old and os.path.isfile(old):
                backup_dir = os.path.join(mods_dir, ".updates_backup")
                os.makedirs(backup_dir, exist_ok=True)
                try:
                    os.replace(old, os.path.join(backup_dir, u["filename"]))
                except OSError:
                    try:
                        os.remove(old)
                    except OSError:
                        pass
            ok += 1
        except Exception:  # noqa: BLE001 - 单个失败不中断批量
            continue
    return ok
