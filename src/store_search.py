"""round-208: resource-center search with server-side filtering and real paging.

Code-level port of the upstream patterns documented in
``docs/specs/round-208-store-alignment/spec.md``:

* ``prism:launcher/modplatform/flame/FlameAPI.cpp:267-296`` — CF query args
  (``gameVersion`` / ``modLoaderTypes`` / ``categoryIds`` / ``sortField`` /
  ``sortOrder`` / ``index`` / ``pageSize``).
* ``prism:launcher/modplatform/modrinth/ModrinthAPI.cpp:105-144,342-356`` —
  Modrinth ``facets`` (loaders / versions / categories / project_type).
* ``hmcl:HMCLCore/.../CurseForgeRemoteAddonRepository.java:102-155`` and
  ``.../ModrinthRemoteAddonRepository.java:144-172`` — ``pageOffset*pageSize``
  and total-derived page count.
* ``pclce:PCL.Launcher.Core/Comp/ProjectStorage.cs:5-22`` and
  ``.../ProjectRequest.cs:77-91,96-194`` — **per-source** ``offset``/``total``
  cursors, ``CanContinue``, target result count and sort mappings.
* ``pclce:PCL.Core/IO/Net/Http/Cache/HttpCacheHandler.cs:23-99`` —
  stale-while-revalidate (fresh -> stale -> miss).

Deliberately a separate module: ``net_api.py`` is ~2900 lines and its
``search_all()`` / ``search_mods()`` / ``search_curseforge()`` contracts are
pinned by the round-206 / round-207 regression suites. Keeping those untouched
means the already-verified "fast source renders first" path cannot regress.

No upstream source text is copied here — only observable API behaviour.
"""

from __future__ import annotations

import copy
import json
import threading
import time

import requests

from . import net_api as na


# ── constants ───────────────────────────────────────────────────────────────
STORE_PAGE_SIZE = 40  # pclce:.../PageComp.xaml.cs:15

STORE_SORTS = ("relevance", "downloads", "follows", "newest", "updated")

# pclce:.../ProjectRequest.cs:137-146 uses Relevance => 4 for the *official*
# api.curseforge.com. We run the MCIM mirror by default; round-207 measured
# ``sortField=1`` puts ``sodium`` first on that mirror, so 1 stays the default.
# See spec §2.4: do not copy the upstream numbers blindly.
_CF_SORT_FIELD = {
    "relevance": 1,
    "downloads": 6,
    "follows": 2,
    "newest": 11,
    "updated": 3,
}

# pclce:.../ProjectRequest.cs:165-173
_MR_SORT_INDEX = {
    "relevance": "relevance",
    "downloads": "downloads",
    "follows": "follows",
    "newest": "newest",
    "updated": "updated",
}

# CurseForge ``modLoaderType`` enum (Forge=1 / Fabric=4 / Quilt=5 / NeoForge=6).
# Only sent when the player explicitly picks a loader; the MCIM mirror may
# ignore it, in which case the client-side compatibility badge still applies.
_CF_LOADER_TYPE = {
    "forge": 1,
    "fabric": 4,
    "quilt": 5,
    "neoforge": 6,
}

_SOURCE_KEYS = {
    "all": ("mr", "cf"),
    "modrinth": ("mr",),
    "curseforge": ("cf",),
}
_SOURCE_LABELS = {"mr": "Modrinth", "cf": "CurseForge"}
_SEARCH_BUDGET = na._SEARCH_BUDGET
_MAX_ROUNDS = 4  # guard: never spin forever on a broken mirror


# ── filter / cache helpers ──────────────────────────────────────────────────
def filters_key(filters: dict | None) -> str:
    """Stable cache-key fragment. Sort and every filter must enter the key,
    otherwise changing sort/filter silently keeps showing the old page."""
    f = filters or {}
    return ":".join(
        "%s=%s" % (k, str(f.get(k) or ""))
        for k in ("game_version", "loader", "category_id", "sort")
    )


def _mr_facets(project_type: str, filters: dict | None) -> str:
    """prism:.../ModrinthAPI.cpp:105-144 — one JSON array of OR-groups."""
    f = filters or {}
    facets: list[list[str]] = [["project_type:%s" % project_type]]
    if f.get("game_version"):
        facets.append(["versions:%s" % f["game_version"]])
    if f.get("loader"):
        facets.append(["categories:%s" % str(f["loader"]).lower()])
    if f.get("category_id"):
        facets.append(["categories:%s" % f["category_id"]])
    return json.dumps(facets, ensure_ascii=False, separators=(",", ":"))


def cache_lookup(key: str, ttl: float | None = None):
    """SWR lookup -> ``(state, value)`` with state in fresh/stale/miss.

    pclce:.../HttpCacheHandler.cs:34-40 returns a hit immediately; :65-76
    reuses the body on 304. We cannot do conditional HTTP requests here, so
    "stale" means "show the old value now, refresh in the background".
    """
    state = na._cached(key, ttl if ttl is not None else na._CACHE_TTL)
    if state is not None:
        return ("fresh", state)
    old = na._stale(key)
    if old is not None:
        return ("stale", old)
    return ("miss", None)


# ── single-source paged search (returns hits AND total) ─────────────────────
def _cf_page_ex(base: str, headers: dict, query: str, category: str,
                limit: int, offset: int, filters: dict | None):
    f = filters or {}
    params = {
        "gameId": na.CURSEFORGE_GAME_ID,
        "classId": na.CURSEFORGE_CLASS_OF.get(category, na.CURSEFORGE_MOD_CLASS),
        "searchFilter": query,
        "pageSize": limit,
        "index": offset,
        "sortField": _CF_SORT_FIELD.get(f.get("sort"), _CF_SORT_FIELD["relevance"]),
        "sortOrder": "desc",
    }
    if f.get("game_version"):
        params["gameVersion"] = f["game_version"]
    if f.get("category_id"):
        params["categoryId"] = f["category_id"]
    if f.get("loader") in _CF_LOADER_TYPE:
        params["modLoaderType"] = _CF_LOADER_TYPE[f["loader"]]
    r = requests.get(
        "%s/mods/search" % base, params=params, headers=headers,
        timeout=na._SEARCH_TIMEOUT, proxies=na._proxies(),
    )
    r.raise_for_status()
    data = r.json()
    total = int((data.get("pagination") or {}).get("totalCount") or 0)
    return [na._cf_map_row(m) for m in data.get("data", [])], total


def _mr_page_ex(query: str, offset: int, limit: int, project_type: str,
                filters: dict | None):
    f = filters or {}
    params = {
        "query": query,
        "facets": _mr_facets(project_type, filters),
        "index": _MR_SORT_INDEX.get(f.get("sort"), "relevance"),
        "limit": limit,
        "offset": offset,
    }
    r = requests.get(
        na.MODRINTH_SEARCH_URL, params=params, headers=na._HEADERS,
        timeout=na._SEARCH_TIMEOUT, proxies=na._proxies(),
    )
    r.raise_for_status()
    data = r.json()
    try:
        from .i18n import get_language
        lang = get_language()
    except Exception:
        lang = "zh-CN"
    hits = [
        {
            "project_id": h.get("project_id", ""),
            "slug": h.get("slug", ""),
            "title": (na.cn_name(h.get("slug", ""), h.get("title", ""))
                      if lang != "en-US" else h.get("title", "")),
            "description": h.get("description", ""),
            "downloads": h.get("downloads", 0),
            "icon_url": h.get("icon_url", ""),
            "author": h.get("author", ""),
            "source": "modrinth",
            "game_versions": [str(x) for x in (h.get("versions") or [])],
            "loaders": [str(x).lower() for x in (h.get("categories") or [])
                        if str(x).lower() in na._STORE_LOADER_TAGS],
        }
        for h in data.get("hits", [])
    ]
    return hits, int(data.get("total_hits") or 0)


def search_store_source(source: str, query: str, offset: int, limit: int,
                        category: str, filters: dict | None = None):
    """One paged request for one source -> ``(hits, total)``.

    ``total`` comes from ``pagination.totalCount`` (CF) / ``total_hits`` (MR),
    exactly like pclce:.../ProjectQuery.cs:649-651,680-681.
    """
    fk = filters_key(filters)
    key = "r208:%s:%s:%s:%s:%s:%s" % (source, category, query, offset, limit, fk)
    cached = na._cached(key)
    if cached is not None:
        return cached

    if source == "cf":
        api_key = na._curseforge_key()
        if api_key:
            base = na.CURSEFORGE_API
            headers = {**na._HEADERS, "x-api-key": api_key,
                       "Accept": "application/json"}
        elif na.curseforge_keyless_enabled():
            base = na._CF_MIRROR
            headers = {**na._HEADERS, "Accept": "application/json"}
        else:
            raise na.NetError("未配置 CurseForge API Key（设置 → 第三方服务）")
        if query and na.has_cjk(query):
            # Name-library reverse lookup (round-128). The mirror's slug probe
            # has no totalCount, so report "unknown" and let CanContinue decide.
            hits = na._cf_search_zh(base, headers, query, category, limit, offset)
            result = (hits, -1)
        else:
            result = _cf_page_ex(base, headers, query, category, limit, offset,
                                 filters)
    else:
        if query and na.has_cjk(query):
            hits = na.search_mods_zh(query, offset, limit, category)
            result = (hits, -1)
        else:
            result = _mr_page_ex(query, offset, limit, category, filters)

    na._store(key, result)
    return result


# ── dual-source cursors / real paging ───────────────────────────────────────
def new_store_cursors() -> dict:
    """pclce:.../ProjectStorage.cs:7-16 — one offset/total pair per source."""
    return {
        "mr": {"offset": 0, "total": -1},
        "cf": {"offset": 0, "total": -1},
    }


def store_can_continue(cursors: dict, source: str = "all") -> bool:
    """pclce:.../ProjectRequest.cs:77-91 ``CanContinue``."""
    for key in _SOURCE_KEYS.get(source, ("mr", "cf")):
        cur = (cursors or {}).get(key) or {"offset": 0, "total": -1}
        if cur["total"] == -1 or cur["offset"] < cur["total"]:
            return True
    return False


def _merge_unique(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Cross-source dedupe by slug / normalised title (net_api round-195)."""
    out = list(existing)
    seen: set[str] = set()
    for m in out:
        for k in (str(m.get("slug", "")).lower(),
                  na._norm_title(str(m.get("title", "")))):
            if k:
                seen.add(k)
    for m in incoming:
        keys = [k for k in (str(m.get("slug", "")).lower(),
                            na._norm_title(str(m.get("title", "")))) if k]
        if keys and any(k in seen for k in keys):
            continue
        for k in keys:
            seen.add(k)
        out.append(m)
    return out


def search_store_page(query: str = "", page: int = 0,
                      page_size: int = STORE_PAGE_SIZE,
                      category: str = "mod", source: str = "all",
                      filters: dict | None = None,
                      cursors: dict | None = None,
                      results: list[dict] | None = None,
                      meta: dict | None = None,
                      on_source=None) -> dict:
    """PCL-CE-style real paging with independent per-source cursors.

    ``target = (page + 1) * page_size`` (pclce:.../PageComp.xaml.cs:295-297).
    Results accumulate in memory, so going back a page costs no HTTP request.
    Each round issues at most one request per source, in parallel daemon
    threads under the round-207 8s budget; a slow source never blocks the fast
    one and late results are still delivered through ``on_source``.

    Returns a dict the page can render directly:
    ``hits / cursors / results / page / can_prev / can_next / meta``.
    """
    cur = copy.deepcopy(cursors) if cursors else new_store_cursors()
    for key in ("mr", "cf"):
        cur.setdefault(key, {"offset": 0, "total": -1})
    all_rows = list(results or [])
    out_meta = {} if meta is None else meta
    out_meta.setdefault("partial", False)
    out_meta.setdefault("timed_out", [])
    out_meta.setdefault("errors", [])
    out_meta.setdefault("cache_state", "miss")
    target = (page + 1) * page_size
    keys = _SOURCE_KEYS.get(source, ("mr", "cf"))
    per = max(10, page_size // max(1, len(keys)))
    rounds = 0

    while (len(all_rows) < target and store_can_continue(cur, source)
           and rounds < _MAX_ROUNDS):
        rounds += 1
        box: dict[str, tuple[list[dict], int]] = {}
        errs: list[Exception] = []

        def _run(k):
            c = cur[k]
            if c["total"] > -1 and c["offset"] >= c["total"]:
                return
            try:
                hits, total = search_store_source(
                    k, query, c["offset"], per, category, filters)
                box[k] = (hits, total)
                if on_source is not None:
                    try:
                        on_source(_SOURCE_LABELS[k], hits or [])
                    except Exception:
                        pass
            except Exception as e:  # noqa: BLE001 - one source must not kill the other
                errs.append(e)

        threads = []
        for k in keys:
            th = threading.Thread(target=_run, args=(k,), daemon=True,
                                  name="ac-store-%s" % k)
            th.start()
            threads.append(th)
        deadline = time.monotonic() + _SEARCH_BUDGET
        for th in threads:
            th.join(max(0.0, deadline - time.monotonic()))
        timed_out = [th.name for th in threads if th.is_alive()]
        if timed_out:
            out_meta["partial"] = True
            out_meta["timed_out"] = timed_out
        if errs:
            out_meta["errors"] = [str(e) for e in errs]

        if not box:
            break
        # pclce:.../ProjectQuery.cs:649-651,680-681 — advance each source by
        # the number of rows it actually returned and record its own total.
        for k, (hits, total) in box.items():
            cur[k]["offset"] += len(hits)
            cur[k]["total"] = total
        merged = na._dedupe_two_sources(box.get("mr", ([], 0))[0],
                                        box.get("cf", ([], 0))[0])
        before = len(all_rows)
        all_rows = _merge_unique(all_rows, merged)
        if len(all_rows) == before:
            # Both sources returned only duplicates (or empty) -> stop.
            break

    start = page * page_size
    page_hits = all_rows[start:start + page_size]
    can_next = len(all_rows) > target or store_can_continue(cur, source)
    out_meta["rounds"] = rounds
    return {
        "hits": page_hits,
        "cursors": cur,
        "results": all_rows,
        "page": page,
        "page_size": page_size,
        "can_prev": page > 0,
        "can_next": can_next,
        "meta": out_meta,
    }
