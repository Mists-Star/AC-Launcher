"""Network data layer: official version manifest + Modrinth mod search.

All functions are *synchronous* (they do blocking HTTP). Pages MUST call them
from a worker thread (QThread) so the UI never freezes. Results are cached in
memory for the session.
"""
from __future__ import annotations

import os
import time
import random
import hashlib
import requests

from .mod_names import cn_name  # round-45 资源中心 mod 中文名

def _t_err(key, default, **kw):
    from .i18n import t as _t
    return _t(key, default=default, **kw)


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
_CACHE_TTL = 1800  # seconds (round-47: 300→1800，版本清单极少变化，30分钟足够)
_DISK_CACHE_TTL = 86400  # keep disk cache for 24h so startup feels instant


_CACHE_DISK_PATH: str | None = None


def _disk_cache_path() -> str:
    """数据目录缓存文件路径（模块级缓存——AC_DEV_TEMP 下 get_data_dir()
    每次 mkdtemp 返回不同目录，不缓存会导致读/写路径不一致）。"""
    global _CACHE_DISK_PATH
    if _CACHE_DISK_PATH is None:
        from .paths import get_data_dir
        _CACHE_DISK_PATH = os.path.join(get_data_dir(), "cache", "net_api_cache.json")
    os.makedirs(os.path.dirname(_CACHE_DISK_PATH), exist_ok=True)
    return _CACHE_DISK_PATH


def _load_disk_cache():
    """Load persisted cache entries that are still fresh."""
    path = _disk_cache_path()
    if not os.path.exists(path):
        return
    try:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        now = time.time()
        for k, v in data.items():
            if not isinstance(v, (list, tuple)) or len(v) != 2:
                continue
            ts, val = v
            if now - ts < _DISK_CACHE_TTL:
                _cache[k] = (ts, val)
    except Exception:  # noqa: BLE001
        pass


def _save_disk_cache():
    """Persist current in-memory cache to disk."""
    path = _disk_cache_path()
    try:
        import json as _json
        now = time.time()
        # drop expired entries before writing
        with _CACHE_LOCK:
            data = {
                k: (ts, v) for k, (ts, v) in _cache.items()
                if now - ts < _DISK_CACHE_TTL
            }
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        pass


# round-34 加固：模块级缓存加锁——多 Worker 并发（store 页 + 版本页同时
# 拉取）时迭代/写入同一 dict 会 RuntimeError。
import threading as _threading
_CACHE_LOCK = _threading.Lock()


def _cached(key: str, ttl: float = _CACHE_TTL):
    now = time.time()
    with _CACHE_LOCK:
        if key in _cache:
            ts, val = _cache[key]
            if now - ts < ttl:
                return val
    # round-40 P2-8 性能：不再每次 miss 读整个磁盘缓存文件——
    # _load_disk_cache() 在模块 import 时已把 24h 内的磁盘缓存全部读入
    # _cache（ts 不变），_cache 里过期 = 磁盘里同样过期，无需再 revive。
    # round-65：调用方可按 key 放宽 TTL（如版本清单走磁盘 24h 语义）。
    return None


def _store(key: str, val) -> None:
    with _CACHE_LOCK:
        _cache[key] = (time.time(), val)
    _save_disk_cache()


# Load any previously-cached results on module import so the store page / version
# list can render instantly on the first run after an app restart.
_load_disk_cache()


class NetError(Exception):
    pass


# ══════════════════════════════════════════════════════════════════════════
# 通用下载器（round-37 轴心2：断点续传）
# ── HTTP Range 续传：本地存在 <dest>.part 时从断点续传，服务器 206 追加、
#    416 说明已完整。所有下载函数统一走这里（mod/modpack/cf/optifine/java）。
# ══════════════════════════════════════════════════════════════════════════
_CHUNK = 65536

# round-72 借鉴主流实现做分片下载：每文件最多尝试 3 次，网络类失败带
# 抖动退避重试（分段里说明 retry<4 + Sleep(300~500+retry*300)）。
_MAX_DOWNLOAD_RETRIES = 3

# round-110 D：大文件自动改走分片多线程。
# 单条 TCP 连接的实际吞吐 ≈ 窗口 / RTT，跨境/跨运营商链路上常常只有 0.3MB/s
# 量级；整合包主文件、大 mod 正是「少数超大文件」的组合，单连接会直接顶死在
# 这个上限上。超过阈值就交给 parallel_download_file（HTTP Range 分片并行）。
_PARALLEL_MIN_BYTES = 8 * 1024 * 1024


def _active_meter():
    """当前线程所属安装的速度计量器（无安装上下文时为 None）。"""
    try:
        from .core.mirror import active_meter
    except Exception:  # noqa: BLE001 - 计量失败绝不影响下载
        return None
    return active_meter()


def _note_bytes(nbytes: int) -> None:
    """把已落盘字节计入当前安装的速度计量（无安装上下文时静默忽略）。"""
    meter = _active_meter()
    if meter is not None:
        meter.note(nbytes)


def _remote_size(url: str, headers: dict | None, timeout: int) -> int:
    """用一次极小的 ``Range: bytes=0-0`` 请求拿远端文件总长（拿不到返回 0）。

    HEAD 在部分 CDN / 镜像上被拒，而这一发 ``206`` 顺带确认了服务器支持分段，
    正好是分片下载的前提。
    """
    hdrs = dict(_HEADERS)
    if headers:
        hdrs.update(headers)
    hdrs["Range"] = "bytes=0-0"
    try:
        r = requests.get(url, headers=hdrs, timeout=timeout, stream=True,
                         proxies=_proxies())
    except requests.RequestException:
        return 0
    try:
        if r.status_code == 206:
            cr = r.headers.get("Content-Range", "")
            return int(cr.rsplit("/", 1)[-1]) if "/" in cr else 0
        if r.status_code == 200:
            return int(r.headers.get("Content-Length", 0) or 0)
        return 0
    except (ValueError, TypeError):
        return 0
    finally:
        try:
            r.close()
        except Exception:  # noqa: BLE001
            pass


def _try_parallel(url: str, dest: str, *, timeout: int, progress, headers,
                  cancel) -> bool:
    """大文件 → 分片多线程；小文件 / 拿不到长度 / 分片失败 → 返回 False。

    返回 False 时调用方继续走单流 ``download_file`` —— 只做加速，不改变语义
    （分片内部失败也会自己回退到单流）。
    """
    size = _remote_size(url, headers, timeout)
    if size < _PARALLEL_MIN_BYTES:
        return False
    try:
        parallel_download_file(url, dest, progress=progress, headers=headers,
                               timeout=timeout, cancel=cancel)
        return True
    except Exception:  # noqa: BLE001 - 加速路径失败，退回单流
        return False



class _TransientDownloadError(NetError):
    """网络抖动 / 内容不完整：值得清空重试或续传；4xx 等确定性错误不抛它。"""


def _download_once(
    url: str,
    dest: str,
    dest_tmp: str,
    *,
    resume: bool,
    progress=None,
    headers: dict | None = None,
    timeout: int = 60,
    cancel=None,
) -> str:
    """单次下载尝试：写 <dest>.part → 校验 size → os.replace 原子收尾。

    返回 dest。确定性错误（4xx）抛 NetError 并清掉可能被污染的 .part；
    瞬时错误（网络/5xx/超时/内容不完整）抛 ``_TransientDownloadError`` 保留
    .part 供上层续传。
    """
    start = 0
    if resume and os.path.exists(dest_tmp):
        start = os.path.getsize(dest_tmp)
    hdrs = dict(_HEADERS)
    if headers:
        hdrs.update(headers)
    if start:
        hdrs["Range"] = f"bytes={start}-"
    try:
        r = requests.get(
            url, headers=hdrs, timeout=timeout, stream=True, proxies=_proxies())
        if start and r.status_code == 416:
            # Range 不满足 = 本地 .part 已等于完整大小 → 直接收尾
            os.replace(dest_tmp, dest)
            return dest
        r.raise_for_status()
        resume_ok = bool(start and r.status_code == 206)
        total = start + int(r.headers.get("Content-Length", 0) or 0)
        sofar = start
        mode = "ab" if resume_ok else "wb"
        with open(dest_tmp, mode) as f:
            for chunk in r.iter_content(_CHUNK):
                if not chunk:
                    continue
                if cancel is not None and cancel():
                    raise NetError(_t_err("err.download_cancel", default="下载已取消"))  # .part 保留，下次断点续传
                f.write(chunk)
                sofar += len(chunk)
                _note_bytes(len(chunk))
                if progress:
                    try:
                        progress(sofar, total)
                    except Exception:
                        pass
    except requests.RequestException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status is not None and 400 <= status < 500:
            # 服务器明确拒绝（404/403…）：URL 作废，保留 .part 只会毒化后续续传
            try:
                os.remove(dest_tmp)
            except OSError:
                pass
            raise NetError(f"下载失败：{e}") from e
        # 网络抖动 / 5xx / 超时：.part 保留，上层带退避重试续传
        raise _TransientDownloadError(f"下载失败：{e}") from e
    if total and sofar != total:
        # Content-Length 已知但没写满 = 连接被掐断，内容不完整 → 当瞬时错误重试
        raise _TransientDownloadError(f"下载不完整：{sofar}/{total}")
    os.replace(dest_tmp, dest)
    return dest


def download_file(
    url: str,
    dest: str,
    *,
    resume: bool = True,
    progress=None,
    headers: dict | None = None,
    timeout: int = 60,
    cancel=None,
    _allow_parallel: bool = True,
) -> str:
    """下载 ``url`` 到 ``dest``，支持断点续传 + 进度回调 + 有限退避重试。

    Args:
        resume:    True 时若有 <dest>.part 残留则从断点续传（默认）
        progress:  callable(sofar, total)——total 未知时为 0
        cancel:    callable() -> bool；返回 True 时中断（round-40 P2-10：
                   队列 shutdown 用它在 chunk 边界安全中断，.part 留下次续传）

    网络类失败最多重试 ``_MAX_DOWNLOAD_RETRIES`` 次（抖动退避，对齐主流）；
    重试期间 .part 断点续传，最终仍失败抛 NetError（.part 保留可再续传）。
    返回 dest。

    round-110 D：大于 ``_PARALLEL_MIN_BYTES`` 的文件先试分片多线程（单连接在
    跨境链路上只有 ~0.3MB/s，大文件必须并行才吃得满带宽）。``_allow_parallel``
    只由分片下载器的单流回退路径传 False，避免「单流 → 分片 → 单流」递归。
    """
    # 有 .part 残留时优先保住断点续传（分片路径会重建 .part，不继承已有进度）。
    if (_allow_parallel and not (resume and os.path.exists(dest + ".part"))
            and _try_parallel(url, dest, timeout=timeout, progress=progress,
                              headers=headers, cancel=cancel)):
        return dest
    dest_tmp = dest + ".part"
    last: Exception | None = None
    for attempt in range(_MAX_DOWNLOAD_RETRIES):
        if attempt:
            # 主流风格抖动退避：0.8s / 1.6s ± 0.3s，网络抖动让开高峰期
            time.sleep(0.4 * (2 ** attempt) + random.random() * 0.3)
        try:
            return _download_once(
                url, dest, dest_tmp,
                resume=(attempt > 0 or resume),   # 重试一律走续传，启用即可
                progress=progress, headers=headers,
                timeout=timeout, cancel=cancel)
        except _TransientDownloadError as e:
            last = e
    raise last if isinstance(last, NetError) else NetError(f"下载失败，已重试 {_MAX_DOWNLOAD_RETRIES} 次")


_ParallelChunk = tuple[int, int]  # (byte_start, byte_end) inclusive


def parallel_download_file(
    url: str,
    dest: str,
    *,
    threads: int | None = None,
    progress=None,
    headers: dict | None = None,
    timeout: int = 30,
    chunk_mb: int = 16,
    cancel=None,
) -> str:
    """分块多线程下载单文件（HTTP Range），失败自动回退到单流 ``download_file``。

    round-48 落地「下载多线程化」核心部分：跑一次性大文件（安装器 jar、
    Minecraft jar 等）时把文件切成多段，用 ``threads`` 个线程并行拉取，再拼回
    一个预建的 ``.part`` 文件；全部完成才 ``os.replace`` 到目标（原子）。

    - 服务器不支持 Range（返回 200 而非 206）→ 无缝回退单流断点续传。
    - 任一分块重试耗尽仍失败 → 清理 .part 并回退单流（保证能下载完）。
    - ``progress(sofar, total)`` 与 ``download_file`` 同签名；``cancel()`` 为真立即中断。
    返回 dest。
    """
    import time as _time

    # round-110 A：分片的工作线程没有安装上下文（thread-local），所以必须在
    # **本线程**先把速度计量器取出来，再交给下面各分块线程喂数。
    meter = _active_meter()

    hdrs = dict(_HEADERS)
    if headers:
        hdrs.update(headers)

    # 1) 探测：带 Range bytes=0-0 的 GET，206 说明支持分块，0 响应体极小
    probe = dict(hdrs)
    probe["Range"] = "bytes=0-0"
    try:
        r = requests.get(url, headers=probe, timeout=timeout, stream=True, proxies=_proxies())
    except requests.RequestException:
        return download_file(url, dest, resume=True, progress=progress,
                             headers=headers, timeout=timeout, cancel=cancel,
                             _allow_parallel=False)
    if r.status_code != 206:
        r.close()
        return download_file(url, dest, resume=True, progress=progress,
                             headers=headers, timeout=timeout, cancel=cancel,
                             _allow_parallel=False)
    cr = r.headers.get("Content-Range", "")
    r.close()
    try:
        total = int(cr.rsplit("/", 1)[-1]) if "/" in cr else 0
    except ValueError:
        total = 0
    if total <= 0:
        return download_file(url, dest, resume=True, progress=progress,
                             headers=headers, timeout=timeout, cancel=cancel,
                             _allow_parallel=False)

    # 2) 智能容量：分块数不超过「每块至少 chunk_mb」，也不超过整数个并发上限
    ncpu = os.cpu_count() or 4
    cap = threads or min(ncpu, 8)
    n = max(1, min(cap, total // (chunk_mb * 1024 * 1024) + 1, total))
    step = max(total // n, 1)
    ranges: list[_ParallelChunk] = []
    lo = 0
    while lo < total:
        hi = min(lo + step - 1, total - 1)
        ranges.append((lo, hi))
        lo = hi + 1

    # 3) 预建 .part（对齐长度），各线程写自己段
    part = dest + ".part"
    if os.path.exists(dest):
        os.remove(dest)
    with open(part, "wb") as f:
        f.truncate(total)

    lock = _threading.Lock()
    done = [0]

    def _tick(nbytes: int) -> None:
        with lock:
            done[0] += nbytes
            d = done[0]
        if meter is not None:
            meter.note(nbytes)
        if progress:
            try:
                progress(d, total)
            except Exception:
                pass

    def _worker(seg: _ParallelChunk) -> None:
        s, e = seg
        for attempt in range(3):
            try:
                h = dict(hdrs)
                h["Range"] = f"bytes={s}-{e}"
                rr = requests.get(url, headers=h, timeout=timeout, stream=True, proxies=_proxies())
                try:
                    if rr.status_code not in (206, 200):
                        rr.raise_for_status()
                    seg_written = 0
                    with open(part, "r+b") as fh:
                        fh.seek(s)
                        for chunk in rr.iter_content(_CHUNK):
                            if not chunk:
                                continue
                            if cancel is not None and cancel():
                                raise NetError(_t_err("err.download_cancel", default="下载已取消"))
                            fh.write(chunk)
                            seg_written += len(chunk)
                            _tick(len(chunk))
                    # 校验本段实际写满（.part 已 truncate 到全长，未写区域是零填充，
                    # 所以必须以「写入字节数」判定，不能用 read 长度）
                    if seg_written >= e - s + 1:
                        return
                    raise NetError("段长度不足，重试")
                finally:
                    rr.close()
            except NetError:
                raise
            except Exception:
                if attempt == 2:
                    raise
                _time.sleep(0.5 * (attempt + 1))

    # 4) 并行执行；任一失败 → 清残件回退单流（保证完成）
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(n, len(ranges))) as ex:
            list(ex.map(_worker, ranges))
    except Exception:
        os.remove(part) if os.path.exists(part) else None
        return download_file(url, dest, resume=False, progress=progress,
                             headers=headers, timeout=timeout, cancel=cancel,
                             _allow_parallel=False)
    os.replace(part, dest)
    return dest


# round-42 自动选源：进程级缓存测速结果（10 分钟）
_AUTO_MIRROR: str | None = None
_AUTO_MIRROR_AT: float = 0.0


def mirror_latencies(timeout: float = 3.0) -> dict:
    """round-79b：下载源测速（官方 manifest / BMCLAPI HEAD 延迟）。

    供设置页「测速选优」使用；与 _pick_auto_mirror 共用端点，但独立于
    进程级缓存——显式测速永远实时重测。返回 {"official": ms|None,
    "bmclapi": ms|None}，None 表示不可达。
    """
    import time as _time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _test(url):
        try:
            t0 = _time.time()
            r = requests.head(url, headers=_HEADERS, timeout=timeout, proxies=_proxies())
            if r.status_code >= 400:
                return None
            return (_time.time() - t0) * 1000.0
        except Exception:  # noqa: BLE001 - 单项失败返回 None 由 UI 呈现
            return None

    out: dict = {}
    urls = (VERSION_MANIFEST_URL, MANIFEST_BMCLAPI)
    with ThreadPoolExecutor(max_workers=2) as ex:
        fs = {ex.submit(_test, u): u for u in urls}
        for f in as_completed(fs, timeout=timeout + 1.5):
            try:
                ms = f.result()
            except Exception:  # noqa: BLE001
                ms = None
            u = fs[f]
            out["official" if u == VERSION_MANIFEST_URL else "bmclapi"] = ms
    return out


def _pick_auto_mirror() -> str:
    """测速选择官方/Bmclapi manifest 端点（对齐主流做法）。

    round-44 性能：HEAD 测速（之前 GET 拉整个 ~1MB manifest ×2，慢网上
    新建实例的版本列表要等 10s+ 才出来——「版本加载不出来」的根因之一）。
    round-46 优化：HEAD 超时从 5s 降到 3s，两个请求并行（最快 1.5s 出结果）。
    """
    global _AUTO_MIRROR, _AUTO_MIRROR_AT
    import time as _time
    now = _time.time()
    if _AUTO_MIRROR and now - _AUTO_MIRROR_AT < 600:
        return _AUTO_MIRROR

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _test(url):
        try:
            t0 = _time.time()
            r = requests.head(url, headers=_HEADERS, timeout=3, proxies=_proxies())
            if r.status_code >= 400:
                return None
            return url, _time.time() - t0
        except Exception:
            return None

    best, best_t = VERSION_MANIFEST_URL, None
    urls = [VERSION_MANIFEST_URL, MANIFEST_BMCLAPI]
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(_test, url): url for url in urls}
        for fut in as_completed(futures, timeout=4):
            res = fut.result()
            if res:
                url, dt = res
                if best_t is None or dt < best_t:
                    best, best_t = url, dt

    _AUTO_MIRROR = best
    _AUTO_MIRROR_AT = now
    return best


def _manifest_url() -> str:
    """Pick the version-manifest endpoint per the download_mirror setting."""
    try:
        from .settings_dialog import load_config
        mode = load_config().get("download_mirror", "bmclapi")
        if mode == "auto":
            return _pick_auto_mirror()
        if mode == "bmclapi":
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
    cached = _cached("versions", _DISK_CACHE_TTL)
    if cached is not None:
        # round-57 修：磁盘缓存来自历史版本（schema 曾为 list[str]）或损坏时
        # 直接返回会让新代码 v.get("id") 崩溃（新建实例一刷新版本列表必炸）。
        # 仅当是 (latest, [{id,...}...]) 结构才信任；否则走网络重新拉取。
        if isinstance(cached, tuple) and len(cached) == 2:
            latest, versions = cached
            if isinstance(versions, list) and all(
                    isinstance(v, dict) and v.get("id") for v in versions):
                return cached
    try:
        r = requests.get(
            _manifest_url(), headers=_HEADERS, timeout=_REQUEST_TIMEOUT,
            proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise NetError(_t_err("err.fetch_versions", default="无法获取版本列表：{err}", err=e)) from e

    latest = data.get("latest", {}).get("release", "")
    # round-38：脏 manifest 缺 id 的条目跳过（v["id"] 会 KeyError 崩整个列表）
    versions = []
    for v in data.get("versions", []):
        if not isinstance(v, dict) or not v.get("id"):
            continue
        versions.append({
            "id": v["id"],
            "type": v.get("type", "release"),
            "releaseTime": v.get("releaseTime", ""),
            "april": v["id"] in APRIL_FOOLS_IDS,
        })
    # order: releases first (stable), then snapshots, then legacy
    order = {"release": 0, "snapshot": 1, "old_beta": 2, "old_alpha": 3}

    def sort_key(v):
        return (order.get(v["type"], 9), v["releaseTime"])

    versions.sort(key=sort_key, reverse=True)
    result = (latest, versions)
    _store("versions", result)
    return result


def _modrinth_versions(project_id: str, mc_version: str = "", loader: str = "",
                       limit: int | None = None, offset: int = 0) -> list[dict]:
    """Fetch the version list of a Modrinth project, optionally filtered by
    game version + loader (server-side filter params).

    round-40 秒加载：结果缓存（300s 内存 + 磁盘）——依赖解析/下载时重复
    调用同一 project 不再每次网络请求。round-85 新增 ``limit``/``offset``
    分页：详情页按页拉取（默认 50），避免大项目（如 Fabric API 上千版本）
    一次拉全量 JSON 导致卡顿；``limit=None`` 保持旧全量行为（更新检查用）。
    """
    key = f"mv:{project_id}:{mc_version}:{loader}:{limit}:{offset}"
    cached = _cached(key)
    if cached is not None:
        return cached
    base = MODRINTH_SEARCH_URL.replace("/search", "")
    params = {}
    if mc_version:
        params["game_versions"] = f'["{mc_version}"]'
    if loader and loader not in ("vanilla", ""):
        params["loaders"] = f'["{loader}"]'
    if limit:
        params["limit"] = limit
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(
            f"{base}/project/{project_id}/version",
            params=params, headers=_HEADERS, timeout=_REQUEST_TIMEOUT,
            proxies=_proxies(),
        )
        r.raise_for_status()
        versions = r.json()
    except requests.RequestException as e:
        raise NetError(_t_err("err.mod_versions", default="无法获取模组版本：{err}", err=e)) from e
    versions = versions if isinstance(versions, list) else []
    _store(key, versions)
    return versions


def _version_primary_file(version: dict, project_id: str) -> tuple[str, str]:
    """(filename, url) of a version's primary file. Raises NetError if none."""
    files = version.get("files", [])
    if not files:
        raise NetError("该模组版本没有可下载的文件")
    primary = next((f for f in files if f.get("primary")), files[0])
    return primary.get("filename", f"{project_id}.jar"), primary.get("url", "")


# round-41：Modrinth project 信息查询（slug→id/title/最新版本）——缓存。
def get_project_info(slug_or_id: str) -> dict | None:
    """Fetch a Modrinth project by slug or id (cached 300s+disk). None if 404."""
    if not slug_or_id:
        return None
    try:
        from .i18n import get_language
        _lang = get_language()
    except Exception:
        _lang = "zh-CN"
    key = "proj:" + str(slug_or_id) + ":" + _lang
    cached = _cached(key)
    if cached is not None:
        return cached
    base = MODRINTH_SEARCH_URL.replace("/search", "")
    try:
        r = requests.get(
            f"{base}/project/{slug_or_id}",
            headers=_HEADERS, timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        if r.status_code == 404:
            _store(key, None)
            return None
        r.raise_for_status()
        info = r.json()
    except requests.RequestException as e:
        raise NetError(_t_err("err.project_info", default="无法获取项目信息：{err}", err=e)) from e
    # round-45 中文界面：title 用内置映射中文名
    if isinstance(info, dict) and _lang != "en-US":
        info["title"] = cn_name(info.get("slug", slug_or_id), info.get("title", ""))
    _store(key, info)
    return info


def get_mod_download(project_id: str) -> tuple[str, str]:
    """Resolve the latest version's primary file (filename, download url)."""
    versions = _modrinth_versions(project_id)
    if not versions:
        raise NetError("该模组没有可下载的文件")
    return _version_primary_file(versions[0], project_id)


# ── Mod 依赖树解析（round-37 轴心1，对齐主流做法）───────────
# Modrinth version dict 带 `dependencies: [{project_id, dependency_type}]`。
# 下载 mod 时递归拉取 required 依赖（本体 + 所有缺的依赖文件），
# optional 跳过、incompatible 跳过、已下载过的依赖去重。

_MOD_DEP_MAX_DEPTH = 5


def resolve_mod_dependencies(
    project_id: str,
    mc_version: str = "",
    loader: str = "",
    version_id: str = "",
    _seen: set | None = None,
    _depth: int = 0,
) -> list[dict]:
    """递归解析 required 依赖，返回去重后的文件清单。

    每项: {"project_id", "filename", "url", "optional"(bool)}
    本体在第一位；递归深度 >5 或循环依赖由 _seen 截断。

    round-66：新增 ``version_id`` —— 指定某一版本 id 解析本体及该版本的依赖
    树（资源中心"选择所有版本下载"）；为空时仍取最新匹配版本，行为不变。
    """
    if _seen is None:
        _seen = set()
    out: list[dict] = []
    if project_id in _seen or _depth > _MOD_DEP_MAX_DEPTH:
        return out
    _seen.add(project_id)
    try:
        versions = _modrinth_versions(project_id, mc_version, loader)
    except NetError:
        return out  # 网络错误 / 项目不存在：跳过该节点，不中断整棵依赖树
    if not versions:
        return out
    target = versions[0]
    if version_id:
        target = next((v for v in versions if v.get("id") == version_id), None)
        if target is None:
            return out
    try:
        filename, url = _version_primary_file(target, project_id)
    except NetError:
        return out
    out.append({
        "project_id": project_id,
        "filename": filename,
        "url": url,
        "optional": False,
    })
    for dep in target.get("dependencies", []):
        dtype = dep.get("dependency_type", "")
        dpid = dep.get("project_id", "")
        if not dpid or dtype in ("optional", "incompatible"):
            continue
        if dpid in _seen:
            continue
        out.extend(
            resolve_mod_dependencies(dpid, mc_version, loader, "", _seen, _depth + 1))
    return out


def download_mod_to(
    project_id: str,
    dest_dir: str,
    mc_version: str = "",
    loader: str = "",
) -> str:
    """Download a mod + its required dependency tree into dest_dir.

    round-37：依赖树自动拉取（Modrinth required dependencies 递归解析）。
    返回本体文件路径（保持旧签名兼容——UI 只需显示主文件）。
    """
    files = resolve_mod_dependencies(project_id, mc_version, loader)
    if not files:
        raise NetError("没有可下载的文件")
    os.makedirs(dest_dir, exist_ok=True)
    primary_path = ""
    for item in files:
        if not item["url"]:
            continue
        dest = os.path.join(dest_dir, item["filename"])
        # round-37：统一断点续传下载器（中断后 .part 续传）
        try:
            download_file(item["url"], dest)
        except NetError as e:
            raise NetError(f"下载失败（{item['filename']}）：{e}") from e
        if item["project_id"] == project_id:
            primary_path = dest
    return primary_path


def download_mod_version_to(
    project_id: str,
    version_id: str,
    dest_dir: str,
    mc_version: str = "",
    loader: str = "",
) -> str:
    """Download a specific version of a mod + its dependency tree (round-66).

    资源中心详情页"选择版本下载"入口：与 `download_mod_to` 行为一致，
    但解析给定的 Modrinth version id 而非最新匹配版本。
    """
    files = resolve_mod_dependencies(
        project_id, mc_version, loader, version_id=version_id)
    if not files:
        raise NetError("没有可下载的文件（或该版本不存在）")
    os.makedirs(dest_dir, exist_ok=True)
    primary_path = ""
    for item in files:
        if not item["url"]:
            continue
        dest = os.path.join(dest_dir, item["filename"])
        try:
            download_file(item["url"], dest)
        except NetError as e:
            raise NetError(f"下载失败（{item['filename']}）：{e}") from e
        if item["project_id"] == project_id:
            primary_path = dest
    return primary_path


# ── 模组翻译（round-66）───────────────────────────────────────────────
# 资源中心详情页"获取翻译"：免费 Google gtx 接口（无需 API key），
# 把项目简介 / README 翻译成目标语言。结果本地缓存 24h（md5 摘要键）。

_TRANSLATE_API = "https://translate.googleapis.com/translate_a/single"
_TRANSLATE_TTL = 24 * 3600


def translate_text(text: str, target: str = "zh-CN") -> str:
    """Translate a chunk of text to ``target`` (默认中文)。

    免费 gtx 端点无 key 即用；超长截断到 5000 字符；失败抛 NetError。
    """
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) > 5000:
        text = text[:5000]
    key = "tr:" + hashlib.md5((target + text[:200]).encode("utf-8")).hexdigest()
    cached = _cached(key, _TRANSLATE_TTL)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            _TRANSLATE_API,
            params={"client": "gtx", "sl": "auto", "tl": target,
                    "dt": "t", "q": text},
            headers=_HEADERS, timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json()
        out = "".join(seg[0] for seg in data[0] if seg and seg[0])
    except requests.RequestException as e:
        raise NetError(
            _t_err("err.translate", default="翻译失败：{err}", err=e)) from e
    if not out:
        raise NetError(_t_err("err.translate_empty", default="翻译结果为空"))
    _store(key, out)
    return out


# 资源中心支持的 Modrinth project_type（对齐主流下载分类：模组/整合包/光影/资源包/数据包）
# round-100：移除 OptiFine 分类入口（用户拍板）——OptiFine 仍可从"新建实例 →
# 加载器"作为独立安装入口使用（见 core/install.py），资源中心不再单列分类。
STORE_CATEGORIES = [
    ("mod",          "store.category_mod"),
    ("modpack",      "store.category_modpack"),
    ("shader",       "store.category_shader"),
    ("resourcepack", "store.category_resourcepack"),
    ("datapack",     "store.category_datapack"),
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


def curseforge_keyless_enabled() -> bool:
    """Whether the keyless fallback channel (cfwidget + forgecdn direct links) is on.

    Default **off**: the public release must route CurseForge traffic through the
    official API only. The keyless channel resolves a slug straight to
    ``edge.forgecdn.net`` and therefore bypasses the mod author's third-party
    distribution consent the API enforces — shipping it as a default would
    contradict what we declare to CurseForge.
    """
    try:
        from .settings_dialog import load_config
        return bool(load_config().get("curseforge_keyless", False))
    except Exception:  # noqa: BLE001
        return False


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
    return download_file(url, dest, timeout=120)


# ---- CurseForge 免 key 通道（cfwidget 详情 + forgecdn 直链）----
# 搜索被 CF 官网 Cloudflare 全量拦截且无公开代理，但"已知 mod → 下载"完全可用：
#   cfwidget.com 返回 mod 详情与文件列表（文件 id/文件名/大小），
#   edge.forgecdn.net/files/<id//1000>/<id%1000>/<file> 是公开直链（同款做法）。
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
            raise NetError(_t_err("err.curseforge_missing", default="CurseForge 未找到「{slug}」（或链接无效）", slug=slug))
        d = r.json()
    except requests.RequestException as e:
        raise NetError(f"无法获取 CurseForge 信息：{e}") from e

    # 取最新文件（cfwidget files 按上传时间倒序）
    files = d.get("files") or []
    if not files:
        raise NetError(_t_err("err.curseforge_no_file", default="该 mod 没有可下载的文件"))
    f = files[0]
    hits = [{
        "project_id": str(d.get("id", "")),
        "slug": slug,
        "title": cn_name(slug, d.get("title", slug)),
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
    return download_file(url, os.path.join(dest_dir, name), timeout=120)


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
    # round-37：走通用断点续传下载器（session 带 OptiFine cookie/token）
    # round-48：改走分块多线程，单文件大 jar 并行更快；Cookie 头透传
    from urllib.parse import quote as _q
    cookie_hdr = "; ".join(
        f"{_q(str(k), safe='')}={_q(str(v), safe='')}" for k, v in s.cookies.items())
    return parallel_download_file(
        OPTIFINE_DOWNLOADX.format(file=f2, token=token),
        dest,
        timeout=120,
        headers={"Cookie": cookie_hdr},
    )


def search_mods(query: str = "", offset: int = 0, limit: int = 20,
                project_type: str = "mod") -> list[dict]:
    """Search Modrinth for content of a given project_type.

    ``project_type`` ∈ {mod, modpack, shader, resourcepack, datapack}.
    Returns list of hit dicts (same shape for every type).
    """
    # round-45：语言进缓存 key——中文界面 title 已替换为中文名
    try:
        from .i18n import get_language
        _lang = get_language()
    except Exception:
        _lang = "zh-CN"
    key = f"mods:{query}:{offset}:{limit}:{project_type}:{_lang}"
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
        raise NetError(_t_err("err.search_mods", default="无法搜索资源：{err}", err=e)) from e

    hits = [
        {
            "project_id": h.get("project_id", ""),
            "slug": h.get("slug", ""),
            # round-45 中文名：内置映射优先（学主流），英文界面显示原名
            "title": (cn_name(h.get("slug", ""), h.get("title", ""))
                      if _lang != "en-US" else h.get("title", "")),
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
    return download_file(url, os.path.join(dest_dir, filename), timeout=120)



# --------------------------------------------------------------------------
# Extra loaders (direction: mainstream launcher loader coverage, 2026-08-01)
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


def legacy_fabric_games_cached():
    """Cached Legacy Fabric supported MC versions, or None if not yet fetched.

    Read-only cache peek (no network) so the UI can consult the real support
    list without blocking; callers fall back to a heuristic while it is cold.
    """
    return _cached("legacyfab:games")


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
