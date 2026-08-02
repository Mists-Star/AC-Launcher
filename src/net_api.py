"""Network data layer: official version manifest + Modrinth mod search.

All functions are *synchronous* (they do blocking HTTP). Pages MUST call them
from a worker thread (QThread) so the UI never freezes. Results are cached in
memory for the session.
"""
from __future__ import annotations

import os
import time
import requests

VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
MODRINTH_SEARCH_URL = "https://api.modrinth.com/v2/search"

# BMCLAPI manifest mirror (used when download_mirror == "bmclapi").
try:
    from .core.mirror import MANIFEST_BMCLAPI
except Exception:  # noqa: BLE001 - mirror is optional infra
    MANIFEST_BMCLAPI = "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json"

_REQUEST_TIMEOUT = 15
_HEADERS = {"User-Agent": "MC-Launcher/0.1 (local dev)"}

# Known Mojang April Fools (joke) versions. Their manifest "type" is unreliable
# (some are "release", some "snapshot"), so we match by a curated id set and
# surface them as their own selectable category.
APRIL_FOOLS_IDS = {
    "3D Shareware v1.34",
    "1.RV-Pre1",
    "2.0",
    "15w14a",
    "20w14inf",
    "23w13a_or_b",
    "24w14potato",
    "25w14craftmine",
}

_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # seconds


def _cached(key: str):
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return val
    return None


def _store(key: str, val) -> None:
    _cache[key] = (time.time(), val)


class NetError(Exception):
    pass


def _manifest_url() -> str:
    """Pick the version-manifest endpoint per the download_mirror setting."""
    try:
        from .settings_dialog import load_config
        if load_config().get("download_mirror", "bmclapi") == "bmclapi":
            return MANIFEST_BMCLAPI
    except Exception:  # noqa: BLE001 - config may be unavailable in some contexts
        pass
    return VERSION_MANIFEST_URL


def _proxies() -> dict | None:
    """Proxy dict for requests, derived from the download_proxy setting.

    Returns None when the default (system proxy) behaviour is wanted.
    """
    try:
        from .settings_dialog import load_config
        from .core.mirror import proxy_dict
        return proxy_dict(load_config().get("download_proxy", ""))
    except Exception:  # noqa: BLE001 - config/proxy infra may be unavailable
        return None


def fetch_versions() -> tuple[str, list[dict]]:
    """Return (latest_release_id, [ {id, type, releaseTime} ... ]).

    Ordered: latest release first, then other releases, then snapshots/old.
    """
    cached = _cached("versions")
    if cached is not None:
        return cached
    try:
        r = requests.get(
            _manifest_url(), headers=_HEADERS, timeout=_REQUEST_TIMEOUT,
            proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise NetError(f"无法获取版本列表：{e}") from e

    latest = data.get("latest", {}).get("release", "")
    versions = [
        {
            "id": v["id"],
            "type": v.get("type", "release"),
            "releaseTime": v.get("releaseTime", ""),
            "april": v["id"] in APRIL_FOOLS_IDS,
        }
        for v in data.get("versions", [])
    ]
    # order: releases first (stable), then snapshots, then legacy
    order = {"release": 0, "snapshot": 1, "old_beta": 2, "old_alpha": 3}

    def sort_key(v):
        return (order.get(v["type"], 9), v["releaseTime"])

    versions.sort(key=sort_key, reverse=True)
    result = (latest, versions)
    _store("versions", result)
    return result


def get_mod_download(project_id: str) -> tuple[str, str]:
    """Resolve the latest version's primary file (filename, download url)."""
    try:
        r = requests.get(
            f"{MODRINTH_SEARCH_URL.replace('/search', '')}/project/{project_id}/version",
            headers=_HEADERS, timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        versions = r.json()
    except requests.RequestException as e:
        raise NetError(f"无法获取模组版本：{e}") from e
    if not versions:
        raise NetError("该模组没有可下载的文件")
    # versions are newest-first on Modrinth
    files = versions[0].get("files", [])
    primary = next((f for f in files if f.get("primary")), files[0])
    return primary.get("filename", f"{project_id}.jar"), primary.get("url", "")


def download_mod_to(project_id: str, dest_dir: str) -> str:
    """Download the latest primary file of a mod into dest_dir. Returns path."""
    filename, url = get_mod_download(project_id)
    if not url:
        raise NetError("没有可用的下载链接")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=60, stream=True, proxies=_proxies())
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
    except requests.RequestException as e:
        raise NetError(f"下载失败：{e}") from e
    return dest


# 资源中心支持的 Modrinth project_type（对齐 PCL2 下载分类：模组/整合包/光影/资源包/数据包）
STORE_CATEGORIES = [
    ("mod",          "store.category_mod"),
    ("modpack",      "store.category_modpack"),
    ("shader",       "store.category_shader"),
    ("resourcepack", "store.category_resourcepack"),
    ("datapack",     "store.category_datapack"),
    ("optifine",     "store.category_optifine"),
]

# BMCLAPI OptiFine 元数据端点（按 MC 版本列出所有 OptiFine 版本）。
BMCLAPI_OPTIFINE_LIST = "https://bmclapi2.bangbang93.com/optifine/{mc}"
OPTIFINE_ADLOADX = "https://optifine.net/adloadx?f={file}&x=5b84"
OPTIFINE_DOWNLOADX = "https://optifine.net/downloadx?f={file}&x={token}"
LITELOADER_VERSIONS_URL = "https://dl.liteloader.com/versions/versions.json"
LITELOADER_SNAPSHOTS_INDEX = (
    "https://repo.mumfrey.com/content/repositories/snapshots/com/mumfrey/liteloader/"
)
CURSEFORGE_API = "https://api.curseforge.com/v1"
CURSEFORGE_GAME_ID = 432  # Minecraft
CURSEFORGE_MOD_CLASS = 6  # Mods class


def _curseforge_key() -> str:
    try:
        from .settings_dialog import load_config
        return (load_config().get("curseforge_api_key") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def curseforge_available() -> bool:
    """True when a CurseForge API key is configured."""
    return bool(_curseforge_key())


def search_curseforge(query: str = "", offset: int = 0, limit: int = 20) -> list[dict]:
    """Search CurseForge mods via the official API (needs an API key).

    Returns the same hit-shaped dicts as :func:`search_mods` so the store page
    renders both sources with identical cards.
    """
    key = _curseforge_key()
    if not key:
        raise NetError("未配置 CurseForge API Key（设置 → 第三方服务）")
    cache_key = f"cf:{query}:{offset}:{limit}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            f"{CURSEFORGE_API}/mods/search",
            params={
                "gameId": CURSEFORGE_GAME_ID,
                "classId": CURSEFORGE_MOD_CLASS,
                "searchFilter": query,
                "pageSize": limit,
                "index": offset,
            },
            headers={**_HEADERS, "x-api-key": key, "Accept": "application/json"},
            timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json().get("data", [])
    except requests.RequestException as e:
        raise NetError(f"无法搜索 CurseForge：{e}") from e

    hits = []
    for m in data:
        logo = (m.get("logo") or {}).get("url", "")
        hits.append({
            "project_id": str(m.get("id", "")),      # CF mod id
            "slug": m.get("slug", ""),
            "title": m.get("name", ""),
            "description": (m.get("summary") or "")[:160],
            "downloads": m.get("downloadCount", 0),
            "icon_url": logo,
            "author": (m.get("authors") or [{}])[0].get("name", ""),
        })
    _store(cache_key, hits)
    return hits


def download_curseforge_mod(project_id: str, dest_dir: str) -> str:
    """Download a CurseForge mod's latest file into dest_dir."""
    key = _curseforge_key()
    if not key:
        raise NetError("未配置 CurseForge API Key")
    try:
        r = requests.get(
            f"{CURSEFORGE_API}/mods/{project_id}/files",
            params={"pageSize": 1, "sortField": 2, "sortOrder": "desc"},
            headers={**_HEADERS, "x-api-key": key, "Accept": "application/json"},
            timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        files = r.json().get("data", [])
    except requests.RequestException as e:
        raise NetError(f"无法获取 CurseForge 文件：{e}") from e
    if not files:
        raise NetError("该模组没有可下载的文件")
    f = files[0]
    url = f.get("downloadUrl", "")
    filename = f.get("fileName", f"{project_id}.jar")
    if not url:
        raise NetError("该模组没有直接下载链接")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=120, stream=True, proxies=_proxies())
        r.raise_for_status()
        with open(dest, "wb") as out:
            for chunk in r.iter_content(8192):
                if chunk:
                    out.write(chunk)
    except requests.RequestException as e:
        raise NetError(f"下载失败：{e}") from e
    return dest


# ---- CurseForge 免 key 通道（cfwidget 详情 + forgecdn 直链）----
# 搜索被 CF 官网 Cloudflare 全量拦截且无公开代理，但"已知 mod → 下载"完全可用：
#   cfwidget.com 返回 mod 详情与文件列表（文件 id/文件名/大小），
#   edge.forgecdn.net/files/<id//1000>/<id%1000>/<file> 是公开直链（PCL2 同款）。
CFWIDGET_URL = "https://api.cfwidget.com/minecraft/mc-mods/{slug}"
FORGECDN_URL = "https://edge.forgecdn.net/files/{a}/{b}/{name}"


def curseforge_link_search(query: str, limit: int = 8) -> list[dict]:
    """免 key 的 CurseForge 解析：输入链接或 slug，返回 mod 卡片数据。

    ``query`` 形如 https://www.curseforge.com/minecraft/mc-mods/sodium、
    ``https://www.curseforge.com/minecraft/mc-mods/sodium/files/8550900`` 或裸 slug
    ``sodium``。返回 hit 形状 dict（含 ``_cf_file`` 供下载）。
    """
    import re
    slug = query.strip()
    m = re.search(r"mc-mods/([a-zA-Z0-9\-]+)", slug)
    if m:
        slug = m.group(1)
    slug = slug.split("/")[0].strip().lower()
    if not slug:
        raise NetError("无法识别 CurseForge 链接")
    key = f"cfwidget:{slug}"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(CFWIDGET_URL.format(slug=slug), headers=_HEADERS,
                         timeout=_REQUEST_TIMEOUT, proxies=_proxies())
        if r.status_code != 200:
            raise NetError(f"CurseForge 未找到「{slug}」（或链接无效）")
        d = r.json()
    except requests.RequestException as e:
        raise NetError(f"无法获取 CurseForge 信息：{e}") from e

    # 取最新文件（cfwidget files 按上传时间倒序）
    files = d.get("files") or []
    if not files:
        raise NetError("该 mod 没有可下载的文件")
    f = files[0]
    hits = [{
        "project_id": str(d.get("id", "")),
        "slug": slug,
        "title": d.get("title", slug),
        "description": (d.get("summary") or "")[:160],
        "downloads": d.get("downloads", 0),
        "icon_url": d.get("thumbnail", ""),
        "author": "CurseForge",
        "_cf_file": {
            "id": f.get("id"),
            "name": f.get("name", f"{slug}.jar"),
        },
    }]
    _store(key, hits)
    return hits


def download_cfwidget_file(cf_file: dict, dest_dir: str) -> str:
    """下载 cfwidget 解析出的最新文件（forgecdn 直链，无需 key）。"""
    fid = cf_file.get("id")
    name = cf_file.get("name", "mod.jar")
    if not fid:
        raise NetError("缺少文件 ID")
    url = FORGECDN_URL.format(a=fid // 1000, b=fid % 1000, name=name)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=120, stream=True, proxies=_proxies())
        r.raise_for_status()
        with open(dest, "wb") as out:
            for chunk in r.iter_content(8192):
                if chunk:
                    out.write(chunk)
    except requests.RequestException as e:
        raise NetError(f"下载失败：{e}") from e
    return dest


def fetch_liteloader_builds(mc_version: str) -> list[dict]:
    """List LiteLoader builds for an old Minecraft version (≤1.12.2).

    Reads the official versions.json (dl.liteloader.com) and resolves the
    snapshots stream's ``com.mumfrey:liteloader`` builds. Returns hit-shaped
    dicts: {title, description, _file, _version, _tweak_class, _libraries}.
    """
    key = f"liteloader:{mc_version}"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(LITELOADER_VERSIONS_URL, headers=_HEADERS,
                         timeout=_REQUEST_TIMEOUT, proxies=_proxies())
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise NetError(f"无法获取 LiteLoader 列表：{e}") from e

    entry = (data.get("versions", {}) or {}).get(mc_version)
    if not entry:
        return []
    # 新版本用 snapshots；老版本（≤1.7.x）用 artefacts，结构略有差异
    stream = entry.get("snapshots") or entry.get("artefacts") or {}
    ll = stream.get("com.mumfrey:liteloader") or {}
    builds = []
    for k, it in ll.items():
        if not isinstance(it, dict) or not it.get("file"):
            continue
        label = it.get("build") or it.get("version") or k
        desc = f"MC {mc_version}"
        if it.get("stream"):
            desc += f"  ·  {it['stream']}"
        if it.get("timestamp"):
            desc += f"  ·  {it['timestamp'][:8]}"
        builds.append({
            "title": label,
            "description": desc,
            "_file": it["file"],
            "_version": it.get("version", ""),
            "_tweak_class": it.get("tweakClass",
                                   "com.mumfrey.liteloader.launch.LiteLoaderTweaker"),
            "_libraries": it.get("libraries", []),
            "downloads": 0,
            "author": "LiteLoader",
        })
    _store(key, builds)
    return builds


def liteloader_jar_url(mc_version: str, build_version: str) -> str:
    """Best-effort URL for a LiteLoader build's jar via the maven snapshots repo."""
    # build_version looks like "1.12.2-SNAPSHOT" (maven metadata style) or
    # "1.12.2-20171128.144431-4" (timestamped). We try the timestamped layout
    # first, then the plain SNAPSHOT directory.
    base = (LITELOADER_SNAPSHOTS_INDEX.rstrip("/") + "/" + mc_version + "-SNAPSHOT/")
    return base + f"liteloader-{build_version}.jar"
OPTIFINE_DOWNLOADX = "https://optifine.net/downloadx?f={file}&x={token}"


def fetch_optifine_versions(mc_version: str) -> list[dict]:
    """List OptiFine builds for a Minecraft version via BMCLAPI.

    Returns hit-shaped dicts so the store page can render them in the same
    cards as Modrinth results: {title, description, _filename, ...}.
    """
    key = f"optifine:{mc_version}"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            BMCLAPI_OPTIFINE_LIST.format(mc=mc_version), headers=_HEADERS,
            timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        raw = r.json()
    except requests.RequestException as e:
        raise NetError(f"无法获取 OptiFine 列表：{e}") from e

    hits = []
    for it in raw or []:
        filename = it.get("filename", "")
        if not filename:
            continue
        label = filename.replace("OptiFine_", "").replace(".jar", "")
        desc = f"MC {it.get('mcversion', mc_version)}"
        if it.get("type"):
            desc += f"  ·  {it['type']}"
        if it.get("forge"):
            desc += f"  ·  {it['forge']}"
        hits.append({
            "project_id": filename,
            "slug": label,
            "title": label,
            "description": desc,
            "_filename": filename,
            "_optifine": True,
            "downloads": 0,
            "author": "OptiFine",
        })
    _store(key, hits)
    return hits


def download_optifine_to(filename: str, dest_dir: str) -> str:
    """Download an OptiFine jar into dest_dir.

    OptiFine has no open API: BMCLAPI lists builds, then we walk the official
    adloadx → downloadx redirect (extracting the page-generated token) to reach
    the real jar. Returns the saved path.
    """
    import re
    s = requests.Session()
    s.headers.update(_HEADERS)
    # 1) adloadx page embeds a fresh downloadx token
    try:
        r = s.get(OPTIFINE_ADLOADX.format(file=filename), timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        raise NetError(f"无法获取 OptiFine 下载信息：{e}") from e
    m = re.search(r"downloadx\?f=([^\"&]+)&x=([0-9a-f]+)", r.text)
    if not m:
        raise NetError("OptiFine 下载链接解析失败")
    f2, token = m.group(1), m.group(2)

    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f2)
    try:
        dl = s.get(
            OPTIFINE_DOWNLOADX.format(file=f2, token=token),
            timeout=120, stream=True,
        )
        dl.raise_for_status()
        with open(dest, "wb") as out:
            for chunk in dl.iter_content(8192):
                if chunk:
                    out.write(chunk)
    except requests.RequestException as e:
        raise NetError(f"下载 OptiFine 失败：{e}") from e
    return dest


def search_mods(query: str = "", offset: int = 0, limit: int = 20,
                project_type: str = "mod") -> list[dict]:
    """Search Modrinth for content of a given project_type.

    ``project_type`` ∈ {mod, modpack, shader, resourcepack, datapack}.
    Returns list of hit dicts (same shape for every type).
    """
    key = f"mods:{query}:{offset}:{limit}:{project_type}"
    cached = _cached(key)
    if cached is not None:
        return cached
    facets = f'[["project_type:{project_type}"]]'
    params = {
        "query": query,
        "facets": facets,
        "index": "relevance",
        "limit": limit,
        "offset": offset,
    }
    try:
        r = requests.get(
            MODRINTH_SEARCH_URL, params=params, headers=_HEADERS,
            timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise NetError(f"无法搜索资源：{e}") from e

    hits = [
        {
            "project_id": h.get("project_id", ""),
            "slug": h.get("slug", ""),
            "title": h.get("title", ""),
            "description": h.get("description", ""),
            "downloads": h.get("downloads", 0),
            "icon_url": h.get("icon_url", ""),
            "author": h.get("author", ""),
        }
        for h in data.get("hits", [])
    ]
    _store(key, hits)
    return hits


def download_modpack_to(project_id: str, dest_dir: str) -> str:
    """Download a Modrinth modpack's primary file (a .mrpack) into dest_dir.

    Returns the local .mrpack path — the caller then installs it as a new
    instance via ``core.install.install_mrpack``.
    """
    filename, url = get_mod_download(project_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=120, stream=True, proxies=_proxies())
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
    except requests.RequestException as e:
        raise NetError(f"下载整合包失败：{e}") from e
    return dest



# --------------------------------------------------------------------------
# Extra loaders (direction: PCL CE loader coverage, 2026-08-01)
#   Legacy Fabric  - meta.legacyfabric.net (official meta API)
#   Cleanroom      - Forge continuation fork (1.12.2 on Java 21 + LWJGL3),
#                    official GitHub Releases provide an installer jar
# --------------------------------------------------------------------------
LEGACY_FABRIC_LOADER_API = "https://meta.legacyfabric.net/v2/versions/loader"
LEGACY_FABRIC_GAME_API = "https://meta.legacyfabric.net/v2/versions/game"


def fetch_legacy_fabric_loaders(mc_version):
    key = "legacyfab:" + str(mc_version)
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            LEGACY_FABRIC_LOADER_API + "/" + str(mc_version),
            headers=_HEADERS, timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise NetError("Cannot fetch Legacy Fabric builds: " + str(e)) from e
    out = []
    for item in data:
        loader = item.get("loader", {})
        version = loader.get("version", "")
        if not version:
            continue
        out.append({
            "title": version,
            "description": "Legacy Fabric · MC " + str(mc_version),
            "_loader_version": version,
            "downloads": 0,
            "author": "Legacy Fabric",
        })
    _store(key, out)
    return out


def fetch_legacy_fabric_games():
    key = "legacyfab:games"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            LEGACY_FABRIC_GAME_API,
            headers=_HEADERS, timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        versions = [v["version"] for v in r.json()]
    except requests.RequestException as e:
        raise NetError("Cannot fetch Legacy Fabric game versions: " + str(e)) from e
    _store(key, versions)
    return versions


CLEANROOM_RELEASES_API = "https://api.github.com/repos/CleanroomMC/Cleanroom/releases"


def fetch_cleanroom_builds():
    key = "cleanroom:releases"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            CLEANROOM_RELEASES_API,
            params={"per_page": 20},
            headers={**_HEADERS, "Accept": "application/vnd.github+json"},
            timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise NetError("Cannot fetch Cleanroom builds: " + str(e)) from e
    out = []
    for rel in data:
        tag = rel.get("tag_name", "")
        installer = ""
        for a in rel.get("assets", []):
            if a.get("name", "").endswith("-installer.jar"):
                installer = a.get("browser_download_url", "")
                break
        if not installer:
            continue
        out.append({
            "title": tag,
            "description": "Cleanroom · 1.12.2 on Java 21",
            "_installer_url": installer,
            "downloads": 0,
            "author": "CleanroomMC",
        })
    _store(key, out)
    return out



# --------------------------------------------------------------------------
# Extra loaders (direction: PCL CE loader coverage, 2026-08-01)
#   Legacy Fabric  - meta.legacyfabric.net (official meta API)
#   Cleanroom      - Forge continuation fork (1.12.2 on Java 21 + LWJGL3),
#                    official GitHub Releases provide an installer jar
# --------------------------------------------------------------------------
LEGACY_FABRIC_LOADER_API = "https://meta.legacyfabric.net/v2/versions/loader"
LEGACY_FABRIC_GAME_API = "https://meta.legacyfabric.net/v2/versions/game"


def fetch_legacy_fabric_loaders(mc_version):
    key = "legacyfab:" + str(mc_version)
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            LEGACY_FABRIC_LOADER_API + "/" + str(mc_version),
            headers=_HEADERS, timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise NetError("Cannot fetch Legacy Fabric builds: " + str(e)) from e
    out = []
    for item in data:
        loader = item.get("loader", {})
        version = loader.get("version", "")
        if not version:
            continue
        out.append({
            "title": version,
            "description": "Legacy Fabric · MC " + str(mc_version),
            "_loader_version": version,
            "downloads": 0,
            "author": "Legacy Fabric",
        })
    _store(key, out)
    return out


def fetch_legacy_fabric_games():
    key = "legacyfab:games"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            LEGACY_FABRIC_GAME_API,
            headers=_HEADERS, timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        versions = [v["version"] for v in r.json()]
    except requests.RequestException as e:
        raise NetError("Cannot fetch Legacy Fabric game versions: " + str(e)) from e
    _store(key, versions)
    return versions


CLEANROOM_RELEASES_API = "https://api.github.com/repos/CleanroomMC/Cleanroom/releases"


def fetch_cleanroom_builds():
    key = "cleanroom:releases"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            CLEANROOM_RELEASES_API,
            params={"per_page": 20},
            headers={**_HEADERS, "Accept": "application/vnd.github+json"},
            timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise NetError("Cannot fetch Cleanroom builds: " + str(e)) from e
    out = []
    for rel in data:
        tag = rel.get("tag_name", "")
        installer = ""
        for a in rel.get("assets", []):
            if a.get("name", "").endswith("-installer.jar"):
                installer = a.get("browser_download_url", "")
                break
        if not installer:
            continue
        out.append({
            "title": tag,
            "description": "Cleanroom · 1.12.2 on Java 21",
            "_installer_url": installer,
            "downloads": 0,
            "author": "CleanroomMC",
        })
    _store(key, out)
    return out
