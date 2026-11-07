# -*- coding: utf-8 -*-
"""客户端增强包：按实例的 MC 版本 + 加载器一键装 / 卸常用客户端 mod（round-182）。

用户诉求原话：「有没有能力给 AC 配一些可以便利游戏中的功能，比如 mod 中的
鼠标手势功能可以不加 mod 直接在游戏中使用？」

查证结论（2026-11-07）：用户指的「鼠标手势」是 **Mouse Tweaks**（YaLTeR，
BSD-3，Modrinth slug ``mouse-tweaks``）——右键拖动连续放置、左键拖动收同类、
Shift+左键扫过整列快速转移、滚轮逐件推拉。它 hook 的是容器界面的
``mouseClicked / mouseDragged / mouseScrolled``，必须知道「光标下是哪个 slot、
手里拿着什么、对面是什么容器」。启动器在进程外只有像素，硬做等于按坐标盲点，
**轻则没反应，重则把物品丢到地上**。所以这条路只能装 mod——本模块把它做成
「一键」，比让用户自己去资源中心搜、对着几十个构建挑版本要省事得多。

☠ 三条铁律（与实例标识同源的教训）：
1. **支持范围走运行时查询，绝不硬编码**。``project_supports`` 从 Modrinth
   读项目声明的 loaders / game_versions；mod 上游扩了支持范围，这里自动跟上。
   硬编码一份表，半年后就开始骗人。
2. **只在「确认不支持」时禁用**。服务端没声明（``None``）一律放行——
   宁可装失败报错，也不要拿未知当不兼容把可用选项灰掉。
3. **卸载只删本项目自己的文件**。自动带上的前置库（Fabric API 之类）保留：
   别的 mod 可能也在用，顺手删掉就是给人制造崩溃。

记录文件 ``<mc_dir>/.ac-enhance.json``（点开头，Minecraft 与 PCL2 / HMCL /
Prism 都不读、不索引，与 ``.ac-layout.json`` 同一套理由）。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

RECORD_NAME = ".ac-enhance.json"
SCHEMA = 1

# 与 crash_analysis.scan_mod_manifests 同一口径：jar 超过这个数就不逐个
# 解压读清单（上百个 jar 的读盘会让 UI 线程卡死）。
_MAX_SCAN_JARS = 60

# 分组顺序即 UI 展示顺序
GROUP_ORDER = ("input", "perf", "visual", "info", "dep")


@dataclass(frozen=True)
class Item:
    """一个可一键装/卸的客户端 mod。"""

    slug: str                 # Modrinth project slug（已实测存在）
    name: str                 # 展示名（产品名，不翻译）
    group: str                # input / perf / visual / info / dep
    desc_key: str             # i18n 键后缀：enhance.desc.<desc_key>
    # jar 里声明的 mod id（小写）。用于识别「不是我装的、但已经在 mods 里」。
    # 多个值之间是「或」关系——多写不误伤。不确定宁可留空，只靠记录识别。
    mod_ids: tuple[str, ...] = ()
    # 额外提示的 i18n 键后缀（可选）：增强.extra.<x>
    extra_key: str = ""
    # 前置库：不参与「状态为未装就催你装」的提示，只在分组里列出
    is_dep: bool = False


CATALOG: tuple[Item, ...] = (
    # ── 操作手感 ──
    Item("mouse-tweaks", "Mouse Tweaks", "input", "mouse_tweaks",
         ("mousetweaks",)),
    Item("controlling", "Controlling", "input", "controlling",
         ("controlling",)),
    Item("appleskin", "AppleSkin", "input", "appleskin",
         ("appleskin",)),
    # ── 性能 ──
    Item("sodium", "Sodium", "perf", "sodium", ("sodium",)),
    Item("lithium", "Lithium", "perf", "lithium", ("lithium",)),
    Item("ferrite-core", "FerriteCore", "perf", "ferrite_core",
         ("ferritecore",)),
    Item("entityculling", "Entity Culling", "perf", "entityculling",
         ("entityculling",)),
    Item("modernfix", "ModernFix", "perf", "modernfix", ("modernfix",)),
    # ── 光影 ──
    Item("iris", "Iris Shaders", "visual", "iris", ("iris",), "iris"),
    # ── 信息与界面 ──
    Item("jade", "Jade", "info", "jade", ("jade",)),
    Item("modmenu", "Mod Menu", "info", "modmenu", ("modmenu",)),
    # ── 前置库（一般由上面的条目自动带上）──
    Item("fabric-api", "Fabric API", "dep", "fabric_api",
         ("fabric-api", "fabric"), is_dep=True),
    Item("cloth-config", "Cloth Config API", "dep", "cloth_config",
         ("cloth-config", "cloth_config", "cloth-config2",
          "cloth_config2"), is_dep=True),
    Item("architectury-api", "Architectury API", "dep", "architectury",
         ("architectury",), is_dep=True),
)

_BY_SLUG = {it.slug: it for it in CATALOG}

# 加载器家族 → Modrinth 查询候选（按优先级）。
# quilt 能跑 fabric 构建、cleanroom 是 1.12.2 的 forge 分支，都是社区通行做法；
# neoforge 与 forge 在 1.20.2 之后已分家，**不能**互相顶替。
_LOADER_CHAIN = {
    "fabric": ("fabric",),
    "quilt": ("quilt", "fabric"),
    "legacyfabric": ("legacyfabric", "fabric"),
    "forge": ("forge",),
    "neoforge": ("neoforge",),
    "cleanroom": ("forge",),
}


# --------------------------------------------------------------------------- #
# 记录文件
# --------------------------------------------------------------------------- #
def record_path(inst) -> str:
    return os.path.join(inst.mc_dir, RECORD_NAME)


def load_record(inst) -> dict:
    """读记录。缺失 / 损坏 / schema 不符一律当空表——记录是缓存，不是真理源。"""
    path = record_path(inst)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return {}
    items = data.get("items")
    return items if isinstance(items, dict) else {}


def save_record(inst, items: dict) -> None:
    """原子写（tmp + os.replace），半截文件不会被下次读成乱码。"""
    path = record_path(inst)
    payload = {"schema": SCHEMA, "items": items}
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 实例上下文
# --------------------------------------------------------------------------- #
def loader_chain(inst) -> tuple[str, ...]:
    """该实例能接受的 Modrinth 加载器标签（按优先级）；装不了返回空元组。"""
    return _LOADER_CHAIN.get((getattr(inst, "loader", "") or "").lower(), ())


def mods_dir(inst) -> str:
    return getattr(inst, "mods_dir", None) or os.path.join(
        getattr(inst, "mc_dir", ""), "mods")


def _jar_mod_ids(inst) -> dict[str, set[str]]:
    """{jar 文件名: {声明的 mod id}}。解析失败的 jar 跳过（不猜）。

    复用 crash_analysis 的清单解析器；同样受「jar 太多就跳过」的保护——
    上百个 mod 时逐个解压读清单会把 UI 线程卡死。
    """
    try:
        from ..crash_analysis import _manifest_from_zip
    except ImportError:              # pragma: no cover - 结构被改动时降级
        return {}
    import zipfile

    d = mods_dir(inst)
    try:
        names = sorted(n for n in os.listdir(d)
                       if n.lower().endswith(".jar") and not n.startswith("."))
    except OSError:
        return {}
    if len(names) > _MAX_SCAN_JARS:
        return {}
    out: dict[str, set[str]] = {}
    for name in names:
        try:
            with zipfile.ZipFile(os.path.join(d, name)) as z:
                info = _manifest_from_zip(z)
        except (OSError, zipfile.BadZipFile):
            continue
        mid = str((info or {}).get("mod_id") or "").strip().lower()
        if mid:
            out[name] = {mid}
    return out


def installed_files(inst, item: Item, record: dict | None = None,
                    jar_ids: dict[str, set[str]] | None = None) -> list[str]:
    """该条目当前在磁盘上的 jar 文件名（可能为空）。

    识别顺序：① 记录里的**主文件**还在 → 就是它；② 记录没有命中，但 mods 里
    有 jar 声明了同一个 mod id（用户从资源中心 / 别的启动器装的）→ 也算已装，
    免得界面写「未安装」让他重复装一遍变成两份。

    ☠ 记录里的 ``deps``（自动带上的前置库）**不算**这个条目的文件——它们
    卸载时不能被当成本项目的东西删掉。
    """
    rec = record if record is not None else load_record(inst)
    d = mods_dir(inst)
    entry = rec.get(item.slug, {}) or {}

    primary = str(entry.get("primary") or "")
    if primary and os.path.isfile(os.path.join(d, primary)):
        return [primary]
    if not item.mod_ids:
        return []
    ids = jar_ids if jar_ids is not None else _jar_mod_ids(inst)
    wanted = {m.lower() for m in item.mod_ids}
    return sorted(name for name, mids in ids.items() if mids & wanted)


# --------------------------------------------------------------------------- #
# 状态解析（需要联网，调用方放 Worker 里跑）
# --------------------------------------------------------------------------- #
def _human_loaders(tags) -> str:
    """把 Modrinth 的 loader 标签拼成人读字符串（保持原样，不翻译品牌名）。"""
    seen: list[str] = []
    for t in tags or []:
        t = str(t)
        if t and t not in seen:
            seen.append(t)
    return " / ".join(seen)


def resolve_status(inst) -> dict:
    """扫出每个条目的可用性 + 安装状态。

    返回 ``{"mc_version", "loader", "chain", "loader_ok", "items": [...]}``；
    每项含 ``item``（Item 本体）+ ``state``：
    ``installed`` / ``available`` / ``version_unsupported`` /
    ``loader_unsupported`` / ``no_build`` / ``unreachable``。

    网络异常按**单条目**降级（``unreachable`` + 错误串），不让一个 mod 查不到
    就把整页搞崩——用户至少还能操作其余条目。
    """
    from .. import net_api

    mc = str(getattr(inst, "game_version", "") or "")
    loader = str(getattr(inst, "loader", "") or "").lower()
    chain = loader_chain(inst)
    record = load_record(inst)
    jar_ids = _jar_mod_ids(inst)

    items: list[dict] = []
    for it in CATALOG:
        files = installed_files(inst, it, record, jar_ids)
        row = {
            "item": it,
            "files": files,
            "installed": bool(files),
            "state": "installed" if files else "available",
            "version": (record.get(it.slug, {}) or {}).get("version_number", ""),
            "detail": "",
            "supports": [],
        }
        if files:
            items.append(row)
            continue
        if not chain:
            row["state"] = "loader_unsupported"
            row["detail"] = loader or "vanilla"
            items.append(row)
            continue
        try:
            probe = net_api.project_supports(it.slug, mc, chain[0])
            if not probe["exists"]:
                row["state"] = "no_build"
                items.append(row)
                continue
            row["supports"] = probe["loaders"]
            if probe["version_ok"] is False:
                row["state"] = "version_unsupported"
                row["detail"] = mc
                items.append(row)
                continue
            # 加载器：候选链里任一被声明支持即可（quilt → fabric 兜底）
            if probe["loader_ok"] is False and not any(
                    ld in probe["loaders"] for ld in chain):
                row["state"] = "loader_unsupported"
                row["detail"] = _human_loaders(probe["loaders"])
                items.append(row)
                continue
            hit = None
            for ld in chain:
                hit = net_api.find_mod_version(it.slug, mc, ld)
                if hit:
                    row["loader_used"] = ld
                    break
            if not hit:
                row["state"] = "no_build"
                row["detail"] = f"{mc} / {loader}"
            else:
                row["version_id"] = hit.get("id", "")
                row["version_number"] = hit.get("version_number", "")
        except Exception as e:       # noqa: BLE001 - 单条目查询失败不该毁整页
            row["state"] = "unreachable"
            row["detail"] = str(e)[:120]
        items.append(row)
    return {
        "mc_version": mc,
        "loader": loader,
        "chain": list(chain),
        "loader_ok": bool(chain),
        "items": items,
    }


# --------------------------------------------------------------------------- #
# 装 / 卸
# --------------------------------------------------------------------------- #
def _safe_name(name: str) -> str:
    """与服务端下载时同一口径的文件名归一（只取 basename）。"""
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    return base if base not in ("", ".", "..") else ""


def install_item(inst, slug: str, callback=None) -> dict:
    """装一个条目（含 required 依赖树）。返回 ``{"files": [...], ...}``。

    下载失败直接抛异常（由 Worker 转成错误弹窗）；成功才写记录——中途失败
    留下半截记录会让界面谎报「已安装」。
    """
    from .. import net_api

    item = _BY_SLUG.get(slug)
    if item is None:
        raise ValueError(f"unknown enhance item: {slug}")
    chain = loader_chain(inst)
    if not chain:
        raise RuntimeError("no_loader")
    mc = str(getattr(inst, "game_version", "") or "")
    dest = mods_dir(inst)
    os.makedirs(dest, exist_ok=True)

    used_loader = ""
    version = None
    for ld in chain:
        version = net_api.find_mod_version(slug, mc, ld)
        if version:
            used_loader = ld
            break
    if not version:
        raise RuntimeError("no_build")

    primary_path = net_api.download_mod_version_to(
        slug, str(version.get("id", "")), dest, mc, used_loader,
        callback=callback)

    # 下载器只回主文件路径，依赖文件名要另取；依赖树刚解析过，走缓存不打网络。
    files: list[str] = []
    try:
        for f in net_api.resolve_mod_dependencies(
                slug, mc, used_loader, version_id=str(version.get("id", ""))):
            name = _safe_name(f.get("filename", ""))
            if name and os.path.isfile(os.path.join(dest, name)):
                files.append(name)
    except Exception:                   # noqa: BLE001 - 记录不全不影响已装成功
        files = []

    record = load_record(inst)
    primary = _safe_name(primary_path)
    if primary and not os.path.isfile(os.path.join(dest, primary)):
        primary = ""
    if not primary:
        # 下载器没回主文件（极端情况）→ 退回「mtime 最新的那个 jar」
        try:
            jars = [(os.path.getmtime(os.path.join(dest, n)), n)
                    for n in os.listdir(dest)
                    if n.lower().endswith(".jar") and not n.startswith(".")]
            jars.sort()
            primary = jars[-1][1] if jars else ""
        except OSError:
            primary = ""
    deps = [f for f in files if f != primary]

    record[slug] = {
        "primary": primary,
        "deps": sorted(set(deps)),
        "version_id": str(version.get("id", "")),
        "version_number": str(version.get("version_number", "")),
        "loader": used_loader,
        "game_version": mc,
        "at": int(time.time()),
    }
    save_record(inst, record)
    return {"slug": slug, "primary": primary, "deps": deps,
            "loader": used_loader,
            "version": str(version.get("version_number", ""))}


def remove_item(inst, slug: str) -> dict:
    """卸载一个条目：只删它自己的 jar，保留自动带来的前置库。

    返回 ``{"removed": [...], "missing": [...], "kept_deps": bool}``；
    ``missing`` 表示记录里有但磁盘上已经不在（用户手删过）——照样清记录。
    """
    item = _BY_SLUG.get(slug)
    if item is None:
        raise ValueError(f"unknown enhance item: {slug}")
    record = load_record(inst)
    d = mods_dir(inst)
    entry = record.get(slug, {}) or {}
    deps = [f for f in (entry.get("deps") or [])
            if f and os.path.isfile(os.path.join(d, f))]
    targets = installed_files(inst, item, record)
    removed: list[str] = []
    missing: list[str] = []
    for name in targets:
        if name in deps:
            continue          # ☠ 前置库保留：别的 mod 可能也在用
        path = os.path.join(d, name)
        if not os.path.isfile(path):
            missing.append(name)
            continue
        try:
            os.remove(path)
            removed.append(name)
        except OSError:
            missing.append(name)

    record.pop(slug, None)
    save_record(inst, record)
    return {"slug": slug, "removed": removed, "missing": missing,
            "kept_deps": bool(deps)}


def has_record(inst) -> bool:
    return bool(load_record(inst))
