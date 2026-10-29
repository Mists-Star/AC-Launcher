"""Network data layer: official version manifest + Modrinth mod search.

All functions are *synchronous* (they do blocking HTTP). Pages MUST call them
from a worker thread (QThread) so the UI never freezes. Results are cached in
memory for the session.
"""
from __future__ import annotations

import html
import json
import os
import re
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
MODRINTH_PROJECTS_URL = "https://api.modrinth.com/v2/projects"
# MC百科（mcmod.cn）：中文资源说明的事实标准站点，主流启动器（PCL2/HMCL）
# 都只把它当外链/中文名来源，不做正文机翻（round-128）。
MCMOD_SEARCH_URL = "https://search.mcmod.cn/s"
MCMOD_CLASS_URL = "https://www.mcmod.cn/class/{id}.html"
# mcmod 搜索页对非浏览器 UA 会返回空壳，必须带浏览器 UA。
_MCMOD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
}

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
# Stale-but-usable window: when the network is down, an expired manifest is
# still far better than an empty version picker (round-126: "删版本后新建里
# 版本显示变少了" was a failed manifest refresh, not an actual deletion).
_DISK_CACHE_MAX_AGE = 7 * 86400


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
            # Keep entries up to a week old in memory: fresh ones are used
            # normally, expired ones only as an offline fallback (_stale).
            if now - ts < _DISK_CACHE_MAX_AGE:
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
                if now - ts < _DISK_CACHE_MAX_AGE
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


def _stale(key: str, max_age: float = _DISK_CACHE_MAX_AGE):
    """Expired but still reasonable cached value (offline fallback)."""
    now = time.time()
    with _CACHE_LOCK:
        if key in _cache:
            ts, val = _cache[key]
            if now - ts < max_age:
                return val
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
        mode = load_config().get("download_mirror", "official")
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
    def _valid_payload(payload):
        # round-57 修：磁盘缓存来自历史版本（schema 曾为 list[str]）或损坏时
        # 直接返回会让新代码 v.get("id") 崩溃（新建实例一刷新版本列表必炸）。
        # 仅当是 (latest, [{id,...}...]) 结构才信任；否则走网络重新拉取。
        if isinstance(payload, tuple) and len(payload) == 2:
            _latest, versions = payload
            if isinstance(versions, list) and all(
                    isinstance(v, dict) and v.get("id") for v in versions):
                return payload
        return None

    cached = _valid_payload(_cached("versions", _DISK_CACHE_TTL))
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
        # Offline / mirror hiccup: an expired manifest still lets the user pick
        # a version. Only surface an error when there is no usable cache at all.
        stale = _valid_payload(_stale("versions"))
        if stale is not None:
            return stale
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
    callback=None,
) -> str:
    """Download a mod + its required dependency tree into dest_dir.

    round-37：依赖树自动拉取（Modrinth required dependencies 递归解析）。
    返回本体文件路径（保持旧签名兼容——UI 只需显示主文件）。

    round-111：``callback`` 收 mll 风格 dict（由 :class:`ProgressWorker`
    注入），桥接成跨文件聚合的字节级进度 + 实时速度。
    """
    files = resolve_mod_dependencies(project_id, mc_version, loader)
    if not files:
        raise NetError("没有可下载的文件")
    os.makedirs(dest_dir, exist_ok=True)
    prog = _cb_progress(callback, len(files))
    primary_path = ""
    for item in files:
        if not item["url"]:
            continue
        dest = os.path.join(dest_dir, item["filename"])
        # round-37：统一断点续传下载器（中断后 .part 续传）
        try:
            download_file(item["url"], dest, progress=prog)
        except NetError as e:
            raise NetError(f"下载失败（{item['filename']}）：{e}") from e
        if prog is not None:
            prog.next_file()
        if item["project_id"] == project_id:
            primary_path = dest
    return primary_path


def download_mod_version_to(
    project_id: str,
    version_id: str,
    dest_dir: str,
    mc_version: str = "",
    loader: str = "",
    callback=None,
) -> str:
    """Download a specific version of a mod + its dependency tree (round-66).

    资源中心详情页"选择版本下载"入口：与 `download_mod_to` 行为一致，
    但解析给定的 Modrinth version id 而非最新匹配版本。

    round-111：新增 ``callback``（mll 风格，ProgressWorker 注入）→ 进度/速度。
    """
    files = resolve_mod_dependencies(
        project_id, mc_version, loader, version_id=version_id)
    if not files:
        raise NetError("没有可下载的文件（或该版本不存在）")
    os.makedirs(dest_dir, exist_ok=True)
    prog = _cb_progress(callback, len(files))
    primary_path = ""
    for item in files:
        if not item["url"]:
            continue
        dest = os.path.join(dest_dir, item["filename"])
        try:
            download_file(item["url"], dest, progress=prog)
        except NetError as e:
            raise NetError(f"下载失败（{item['filename']}）：{e}") from e
        if prog is not None:
            prog.next_file()
        if item["project_id"] == project_id:
            primary_path = dest
    return primary_path


# ── 模组翻译（round-66）───────────────────────────────────────────────
# 资源中心详情页"获取翻译"：免费接口，无需 API key。
# round-125：Google gtx 在国内网络直接超时（用户「资源中心获取翻译失败」），
# 所以改为「Google 优先 + MyMemory 兜底」——MyMemory 无需 key、国内可达。
# round-127: MyMemory 匿名额度只有约 1 万字符/天，超了统一返回 HTTP 429
#   "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY"
#   —— 旧代码把这段英文原文直接甩给用户。现在按 chunk 缓存 7 天（重试只补
#   未翻译的段落），429 时给中文提示；Google 连不上就 30 分钟内不再重试，
#   免得每次点翻译都白等 5 秒。

_TRANSLATE_API = "https://translate.googleapis.com/translate_a/single"
_TRANSLATE_FALLBACK = "https://api.mymemory.translated.net/get"
_TRANSLATE_TTL = 7 * 86400

# Google endpoint is unreachable on mainland networks. Retrying it on every
# click only costs a 4s connect timeout, so remember the failure for a while.
_GOOGLE_SKIP_UNTIL = 0.0
_GOOGLE_SKIP_SECONDS = 1800
_GOOGLE_TIMEOUT = 4


def _google_translate(text: str, target: str) -> str:
    global _GOOGLE_SKIP_UNTIL
    if time.time() < _GOOGLE_SKIP_UNTIL:
        raise NetError("google translate unreachable (skipped)")
    try:
        r = requests.get(
            _TRANSLATE_API,
            params={"client": "gtx", "sl": "auto", "tl": target,
                    "dt": "t", "q": text},
            headers=_HEADERS, timeout=_GOOGLE_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
    except requests.RequestException:
        _GOOGLE_SKIP_UNTIL = time.time() + _GOOGLE_SKIP_SECONDS
        raise
    data = r.json()
    return "".join(seg[0] for seg in data[0] if seg and seg[0])


def _chunk_text(text: str, limit: int = 450) -> list[str]:
    """Split on line boundaries so MyMemory's per-request cap is respected."""
    chunks, buf = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if buf and len(buf) + 1 + len(line) > limit:
            chunks.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf.strip():
        chunks.append(buf)
    return chunks


def _quota_exhausted(detail: str) -> bool:
    """MyMemory answers 429 with a ``MYMEMORY WARNING: ...`` body when the
    anonymous daily quota (~10k chars / IP) is used up."""
    return "ALL AVAILABLE FREE TRANSLATIONS" in (detail or "").upper()


def _mymemory_translate(text: str, target: str) -> str:
    lang = "zh-CN" if target.lower().startswith("zh") else target
    out_parts = []
    for chunk in _chunk_text(text):
        # Per-chunk cache: a failed run still keeps the chunks that made it
        # through, so a retry tomorrow only spends quota on what's missing.
        ck = "trc:" + hashlib.md5((lang + chunk).encode("utf-8")).hexdigest()
        hit = _cached(ck, _TRANSLATE_TTL)
        if hit is not None:
            out_parts.append(hit)
            continue
        r = requests.get(
            _TRANSLATE_FALLBACK,
            params={"q": chunk, "langpair": f"en|{lang}"},
            headers=_HEADERS, timeout=12, proxies=_proxies(),
        )
        try:
            data = r.json()
        except ValueError:
            raise NetError(f"mymemory HTTP {r.status_code}") from None
        if str(data.get("responseStatus")) != "200":
            detail = str(data.get("responseDetails") or "")
            if r.status_code == 429 or _quota_exhausted(detail):
                raise NetError(_t_err(
                    "err.translate_quota",
                    default="免费翻译额度已用完（MyMemory 匿名额度约 1 万字符/天），"
                            "请明天再试，或在设置里配置代理后走 Google 翻译。"))
            raise NetError(detail or f"mymemory error (HTTP {r.status_code})")
        piece = (data.get("responseData") or {}).get("translatedText") or ""
        if not piece:
            raise NetError("mymemory: empty result")
        piece = html.unescape(piece)
        out_parts.append(piece)
        _store(ck, piece)
    return "\n".join(out_parts)


def translate_text(text: str, target: str = "zh-CN") -> str:
    """Translate a chunk of text to ``target`` (默认中文)。

    先试 Google gtx（境外网络最快），失败再走 MyMemory（无 key、国内可用）；
    都失败才抛 NetError。超长截断到 5000 字符。
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
    last_err = None
    for fn in (_google_translate, _mymemory_translate):
        try:
            out = fn(text, target)
        except (requests.RequestException, NetError, ValueError) as e:
            last_err = e
            continue
        if out:
            _store(key, out)
            return out
    if last_err is not None:
        # 详情页自己会加「翻译失败：」前缀，这里只回传后端原因，
        # 否则会出现「翻译失败：翻译失败：…」。
        raise NetError(str(last_err))
    raise NetError(_t_err("err.translate", default="翻译失败"))


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
# round-140：MCIM 公益镜像（HMCL / PCL2-CE 在用）——与官方 API 同契约、
# 免 x-api-key，无 key 时的关键词搜索走这里。仅搜索走镜像；下载仍走
# cfwidget + forgecdn 公开直链。
_CF_MIRROR = "https://mod.mcimirror.top/curseforge/v1"
CURSEFORGE_GAME_ID = 432  # Minecraft
CURSEFORGE_MOD_CLASS = 6  # Mods class
# round-140 修：CF 搜索此前写死 classId=6（模组），资源中心的分类胶囊在
# CF 源下被完全忽略——「整合包」页签搜出来的全是模组（与 PCL 表现不一致）。
# classId 经镜像 + 官网路径实锤：data-packs=6945（4546 是 customization，
# 不是数据包）、resource-packs=12、shaders=6552、modpacks=4471。
CURSEFORGE_CLASS_OF = {
    "mod":          6,
    "modpack":      4471,
    "shader":       6552,
    "resourcepack": 12,
    "datapack":     6945,
}


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
    """Whether the keyless channel (MCIM mirror search + cfwidget/forgecdn links) is on.

    Default **on**（round-140 用户拍板「搜索+下载全默认开」）: without an
    official key, keyword search goes through the MCIM community mirror
    (same contract as the CF API, no ``x-api-key`` — HMCL / PCL2-CE use it)
    and downloads resolve slug → cfwidget → ``edge.forgecdn.net``. Turning
    it off restricts CurseForge to the official keyed API only.
    """
    try:
        from .settings_dialog import load_config
        return bool(load_config().get("curseforge_keyless", True))
    except Exception:  # noqa: BLE001
        return True


_CF_POOL_STEP = 50     # CF 单页上限 50（镜像同）
_CF_POOL_PAGES = 3     # round-141：首屏拉 0/50/100 → 150 条相关性池


def _cf_map_row(m: dict) -> dict:
    """CF API 行 → 统一 hit 形状（与 search_mods 对齐）。"""
    logo = (m.get("logo") or {}).get("url", "")
    return {
        "project_id": str(m.get("id", "")),      # CF mod id
        "slug": m.get("slug", ""),
        "title": m.get("name", ""),
        "description": (m.get("summary") or "")[:160],
        "downloads": m.get("downloadCount", 0),
        "icon_url": logo,
        "author": (m.get("authors") or [{}])[0].get("name", ""),
        "source": "curseforge",
    }


def _cf_relevance(hit: dict, q_norm: str, q_low: str) -> int:
    """本地相关性分级（round-141 搜索质量）。

    实测 CF v1 / MCIM 镜像引擎把「名字精确匹配」的项目埋到 100+ 位
    （搜 sodium，本体排在第 100 页位；sortField 不起作用），我们只取前
    20 永远看不到本体 —— 用户报「搜 sodium 搜不到」的根因。
    分级：0 = 名字/slug 精确 → 1 = 名字包含全部词 → 2 = slug 含关键词
    → 3 = 名字含关键词 → 4 = 其它（保留引擎原始顺序，稳定排序）。
    """
    slug = (hit.get("slug") or "").lower()
    name = (hit.get("title") or "").lower()
    if q_norm and (slug == q_norm or name == q_low):
        return 0
    toks = q_low.split()
    if toks and all(t in name for t in toks):
        return 1
    if q_norm and q_norm in slug:
        return 2
    if q_low and q_low in name:
        return 3
    return 4


def _cf_pool(base: str, headers: dict, query: str, category: str) -> list[dict]:
    """首屏相关性池：3×50 页并行拉取 + slug 精确钉顶 → 去重 → 本地分级重排。

    后续分页从池里切片（0 成本），池整体带缓存。全部失败才 raise，
    部分页失败用已取回的部分兜底。
    """
    key = f"cfpool:{category}:{query}"
    cached = _cached(key)
    if cached is not None:
        return cached
    class_id = CURSEFORGE_CLASS_OF.get(category, CURSEFORGE_MOD_CLASS)

    def _page(idx: int) -> list[dict]:
        params = {"gameId": CURSEFORGE_GAME_ID, "classId": class_id,
                  "searchFilter": query, "pageSize": _CF_POOL_STEP, "index": idx}
        r = requests.get(f"{base}/mods/search", params=params, headers=headers,
                         timeout=_REQUEST_TIMEOUT, proxies=_proxies())
        r.raise_for_status()
        return r.json().get("data", [])

    def _slug_probe() -> list[dict]:
        # slug 精确钉顶：用户输入 ≈ 完整名时，无论引擎把本体埋多深都救回来
        norm = query.strip().lower().replace(" ", "-")
        if not norm or "/" in norm or has_cjk(norm):
            return []
        params = {"gameId": CURSEFORGE_GAME_ID, "slug": norm, "pageSize": 1}
        try:
            r = requests.get(f"{base}/mods/search", params=params, headers=headers,
                             timeout=_REQUEST_TIMEOUT, proxies=_proxies())
            r.raise_for_status()
            return r.json().get("data", [])
        except requests.RequestException:
            return []

    rows: list[dict] = []
    errs: list[Exception] = []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(_slug_probe)] + [
            ex.submit(_page, i * _CF_POOL_STEP) for i in range(_CF_POOL_PAGES)]
        for f in futs:
            try:
                rows.extend(f.result())
            except Exception as e:  # noqa: BLE001 - 单页失败用其余页兜底
                errs.append(e)
    if not rows and errs:
        raise NetError(f"无法搜索 CurseForge：{errs[0]}")
    # 按 slug 去重（钉顶行在最前，先到先得）
    seen: set = set()
    merged: list[dict] = []
    for m in rows:
        s = m.get("slug") or m.get("id")
        if s in seen:
            continue
        seen.add(s)
        merged.append(m)
    hits = [_cf_map_row(m) for m in merged]
    q_low = query.strip().lower()
    q_norm = q_low.replace(" ", "-")
    hits.sort(key=lambda h: _cf_relevance(h, q_norm, q_low))  # 稳定排序
    _store(key, hits)
    return hits


def search_curseforge(query: str = "", offset: int = 0, limit: int = 20,
                      category: str = "mod") -> list[dict]:
    """Search CurseForge mods — official API with a key, MCIM mirror without.

    round-140：无 key 且免 key 通道开启时改走 MCIM 公益镜像（同 API 契约、
    免 x-api-key），关键词 / 中文名库反查 / 分页语义与官方路径一致。
    round-140 修：``category`` → CF classId，分类胶囊在 CF 源下生效
    （此前写死模组类，搜整合包返回的是模组）。
    round-141：offset < 150 走 ``_cf_pool`` 相关性池（3×50 页 + slug 钉顶 +
    本地分级重排），修「搜 sodium 搜不到本体」；更深页走引擎原生顺序。
    Returns the same hit-shaped dicts as :func:`search_mods` so the store page
    renders both sources with identical cards.
    """
    key = _curseforge_key()
    if key:
        base = CURSEFORGE_API
        headers = {**_HEADERS, "x-api-key": key, "Accept": "application/json"}
    elif curseforge_keyless_enabled():
        base = _CF_MIRROR
        headers = {**_HEADERS, "Accept": "application/json"}
    else:
        raise NetError("未配置 CurseForge API Key（设置 → 第三方服务）")
    cache_key = f"cf:{category}:{query}:{offset}:{limit}"
    # round-128：CF 的 searchFilter 同样不认中文，先用本地名库反查 slug，
    # 再走 CF 的 slug 精确查询（单次请求，保持原有分页语义）。
    if has_cjk(query):
        cached = _cached(cache_key)
        if cached is not None:
            return cached
        slugs = _lookup_cn_slugs(query)
        if not slugs:
            return []
        params = {
            "gameId": CURSEFORGE_GAME_ID,
            "classId": CURSEFORGE_CLASS_OF.get(category, CURSEFORGE_MOD_CLASS),
            "slug": slugs[0],
            "pageSize": limit,
            "index": offset,
        }
        try:
            r = requests.get(
                f"{base}/mods/search",
                params=params,
                headers=headers,
                timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
            )
            r.raise_for_status()
            data = r.json().get("data", [])
        except requests.RequestException as e:
            raise NetError(f"无法搜索 CurseForge：{e}") from e
        hits = [_cf_map_row(m) for m in data]
        _store(cache_key, hits)
        return hits
    # 首屏 → 相关性池切片。注意：池是唯一权威 —— 不能先查切片缓存，
    # 否则修复前存下的旧排名数据（sodium 埋 100+ 位那版）会一直短路新池。
    if offset < _CF_POOL_STEP * _CF_POOL_PAGES:
        return _cf_pool(base, headers, query, category)[offset:offset + limit]
    # 深页兜底（>150）：引擎原生顺序
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    params = {
        "gameId": CURSEFORGE_GAME_ID,
        "classId": CURSEFORGE_CLASS_OF.get(category, CURSEFORGE_MOD_CLASS),
        "searchFilter": query,
        "pageSize": limit,
        "index": offset,
    }
    try:
        r = requests.get(
            f"{base}/mods/search",
            params=params,
            headers=headers,
            timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json().get("data", [])
    except requests.RequestException as e:
        raise NetError(f"无法搜索 CurseForge：{e}") from e
    hits = [_cf_map_row(m) for m in data]
    _store(cache_key, hits)
    return hits


def search_all(query: str = "", offset: int = 0, limit: int = 20,
               category: str = "mod") -> list[dict]:
    """「全部」源（round-140 用户要求）：Modrinth + CurseForge 并行搜索合并返回。

    两源各自走自己的缓存/分页；一边失败不拖死另一边（只有两边都失败且
    结果为空才 raise）。命中 dict 自带 ``source`` 字段，卡片/详情/下载
    据此分流。
    """
    from concurrent.futures import ThreadPoolExecutor
    box: dict[str, list[dict] | None] = {"mr": None, "cf": None}
    errs: list[Exception] = []

    def _mr():
        try:
            box["mr"] = search_mods(query, offset, limit, project_type=category)
        except Exception as e:  # noqa: BLE001 - 单源失败不拖死合并视图
            errs.append(e)

    def _cf():
        if not (curseforge_available() or curseforge_keyless_enabled()):
            return
        try:
            box["cf"] = search_curseforge(query, offset, limit, category)
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_mr), ex.submit(_cf)]
        for f in futs:
            f.result()
    hits = (box["mr"] or []) + (box["cf"] or [])
    if not hits and errs:
        raise NetError(str(errs[0]))
    return hits


def download_curseforge_mod(project_id: str, dest_dir: str,
                            file_id: int | str | None = None,
                            callback=None) -> str:
    """Download a CurseForge mod file into dest_dir.

    round-111：新增 ``callback``（mll 风格，ProgressWorker 注入）→ 进度/速度。
    round-142（CF 整合包一键安装）：``file_id`` 支持按 manifest 指定的文件
    版本精确下载；无 key 时不再直接报错，改走 cfwidget→forgecdn 免 key 通道。
    """
    key = _curseforge_key()
    if not key:
        if not curseforge_keyless_enabled():
            raise NetError(_t_err(
                "store.cf_no_key",
                default="CurseForge 暂不可用。请到「设置 → 网络 → 第三方服务」"
                        "开启免密钥选项，或填入自己的 CurseForge API Key。"))
        return _download_cf_keyless(project_id, file_id, dest_dir, callback)
    if file_id:
        # 整合包 manifest 指定版本 → 官方精确文件端点（不再退回最新版，
        # 否则整合包装出来的模组版本和作者声明的不一致）。
        try:
            r = requests.get(
                f"{CURSEFORGE_API}/mods/{project_id}/files/{file_id}",
                headers={**_HEADERS, "x-api-key": key,
                         "Accept": "application/json"},
                timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
            )
            r.raise_for_status()
            f = r.json().get("data") or {}
        except requests.RequestException as e:
            raise NetError(f"无法获取 CurseForge 文件：{e}") from e
        filename = f.get("fileName") or f"{project_id}.zip"
        # 部分文件 downloadUrl 为 null → forgecdn 是同款公开直链，直接拼。
        url = f.get("downloadUrl") or FORGECDN_URL.format(
            a=int(file_id) // 1000, b=int(file_id) % 1000, name=filename)
        os.makedirs(dest_dir, exist_ok=True)
        return download_file(url, os.path.join(dest_dir, filename),
                             timeout=120, progress=_cb_progress(callback))
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
    return download_file(url, dest, timeout=120,
                         progress=_cb_progress(callback))


def _cfwidget_info(proj: str) -> dict:
    """cfwidget 详情（免 key）：``proj`` 可以是 slug 或数字 project_id。带缓存。"""
    key = f"cfwidget:info:{proj}"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(CFWIDGET_URL.format(slug=str(proj)), headers=_HEADERS,
                         timeout=_REQUEST_TIMEOUT, proxies=_proxies())
        if r.status_code != 200:
            raise NetError(_t_err(
                "err.curseforge_missing",
                default="CurseForge 未找到「{slug}」（或链接无效）",
                slug=str(proj)))
        d = r.json()
    except requests.RequestException as e:
        raise NetError(f"无法获取 CurseForge 信息：{e}") from e
    if isinstance(d, dict):
        _store(key, d)
    return d


def _cf_files_mirror(project_id: str) -> list[dict]:
    """镜像文件列表 ``/mods/{id}/files``（同官方 API 契约、免 key）→ 官方形状行。"""
    key = f"cffi:{project_id}"
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(f"{_CF_MIRROR}/mods/{project_id}/files",
                         params={"pageSize": 50},
                         headers=_HEADERS, timeout=_REQUEST_TIMEOUT,
                         proxies=_proxies())
        r.raise_for_status()
        rows = r.json().get("data") or []
    except requests.RequestException as e:
        raise NetError(f"无法获取 CurseForge 文件：{e}") from e
    _store(key, rows)
    return rows


def _cf_direct_url(u: str) -> bool:
    """是否为可直接 GET 的文件直链。

    cfwidget 的 ``file.url`` 是**网页链接**（www.curseforge.com/.../files/N），
    直接 GET 会被 Cloudflare 403（round-142 实测踩坑）；镜像个别条目也可能
    回 null/网页链接。网页链接一律当「没有直链」处理，落到 forgecdn 拼链。
    """
    if not u or not u.startswith(("http://", "https://")):
        return False
    return "curseforge.com/" not in u


def _download_cf_keyless(project_id: str, file_id: int | str | None,
                         dest_dir: str, callback=None) -> str:
    """免 key 下载：镜像拿元数据（1 次）→ forgecdn 直链下载（1 次）。

    round-142 初版每个文件最多要问 4 个地方（精确端点/文件列表/cfwidget/下载），
    用户实测「导入整合包这么久」——现改为：
    * 元数据结果缓存（``cfx:{pid}:{fid}``），重复导入同一包秒回；
    * 精确端点拿到 fileName 即可拼 forgecdn（downloadUrl 为 null 不再往下问）；
    * 文件列表同理：有 id+fileName 直接拼；cfwidget 只在镜像整体故障时才用。
    整合包 manifest 只有 projectID+fileID，必须按文件版本精确下载；
    找不到指定 fileID 时退回最新文件，让安装至少能继续。
    """
    meta_key = f"cfx:{project_id}:{file_id or 'latest'}"
    cached = _cached(meta_key)
    url, filename = ("", "")
    if isinstance(cached, (list, tuple)) and len(cached) == 2:
        url, filename = cached[0] or "", cached[1] or ""

    def _forge(fid, name) -> str:
        return FORGECDN_URL.format(a=int(fid) // 1000, b=int(fid) % 1000,
                                   name=name)

    # 1) 精确文件端点（manifest 指定版本的正路）
    if not url and file_id:
        try:
            r = requests.get(f"{_CF_MIRROR}/mods/{project_id}/files/{file_id}",
                             headers=_HEADERS, timeout=_REQUEST_TIMEOUT,
                             proxies=_proxies())
            if r.status_code == 200:
                f = r.json().get("data") or {}
                fname = f.get("fileName") or ""
                if _cf_direct_url(f.get("downloadUrl") or ""):
                    url, filename = f["downloadUrl"], fname
                elif fname:
                    # downloadUrl 为 null：id+fileName 已足够拼 forgecdn，
                    # 不再往下问文件列表 / cfwidget（省 2 次往返）。
                    url, filename = _forge(file_id, fname), fname
        except requests.RequestException:
            pass
    # 2) 文件列表（精确端点没给 fileName 时按 id 匹配；找不到取最新）
    if not url:
        hit = None
        try:
            rows = _cf_files_mirror(project_id)
            if file_id:
                for cand in rows:
                    if str(cand.get("id")) == str(file_id):
                        hit = cand
                        break
            if hit is None and rows:
                hit = rows[0]
        except NetError:
            hit = None
        if hit:
            fname = hit.get("fileName") or ""
            if _cf_direct_url(hit.get("downloadUrl") or ""):
                url, filename = hit["downloadUrl"], fname
            elif hit.get("id") and fname:
                url, filename = _forge(hit["id"], fname), fname
    # 3) cfwidget 兜底（镜像整体故障才走；注意其 file.url 是网页链接，403，
    #    只能用 id+name 拼 forgecdn）。
    if not url:
        rows: list[dict] = []
        try:
            d = _cfwidget_info(project_id)
            rows = [f for f in (d.get("files") or []) if isinstance(f, dict)]
        except NetError:
            pass
        hit = None
        if file_id:
            for cand in rows:
                if str(cand.get("id")) == str(file_id):
                    hit = cand
                    break
        if hit is None and rows:
            hit = rows[0]
        if hit and hit.get("id"):
            filename = hit.get("name") or f"{project_id}.zip"
            url = _forge(hit["id"], filename)
    if not url:
        raise NetError(_t_err("err.curseforge_no_file",
                              default="该 mod 没有可下载的文件"))
    if not filename:
        filename = os.path.basename(url.split("?")[0]) or f"{project_id}.zip"
    _store(meta_key, [url, filename])
    os.makedirs(dest_dir, exist_ok=True)
    return download_file(url, os.path.join(dest_dir, filename),
                         timeout=300, progress=_cb_progress(callback))


# ---- CurseForge 版本列表 / 指定文件下载（round-120）----
# detail dialog used to be Modrinth-only; these normalise CurseForge files into
# the same version-dict shape so one row renderer serves both sources.
_CF_LOADER_NAMES = {
    "forge", "fabric", "quilt", "neoforge", "liteloader", "rift",
}


def _cf_version_entry(entry_id, display, filename, size, date,
                      game_versions, url="") -> dict:
    """Map one CurseForge file onto the Modrinth version shape."""
    gv = [g for g in (game_versions or []) if isinstance(g, str)]
    return {
        "id": str(entry_id or ""),
        "version_number": display or filename or "—",
        "game_versions": [g for g in gv if g[:1].isdigit()],
        "loaders": [g.lower() for g in gv if g.lower() in _CF_LOADER_NAMES],
        "files": [{
            "id": entry_id,
            "filename": filename or "mod.jar",
            "size": size or 0,
            "url": url,
            "primary": True,
        }],
        "date_published": (date or "")[:19],
        "source": "curseforge",
    }


def _curseforge_versions(project_id: str, limit: int | None = None,
                         offset: int = 0) -> list[dict]:
    """List a CurseForge project's files via the official API (needs a key).

    ``gameVersions`` mixes MC versions and loader names, so they are split
    into ``game_versions`` / ``loaders`` before rendering.
    """
    key = _curseforge_key()
    if not key:
        raise NetError("未配置 CurseForge API Key（设置 → 第三方服务）")
    cache_key = f"cfv:{project_id}:{limit}:{offset}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    params = {"pageSize": limit or 50}
    if offset:
        params["index"] = offset
    try:
        r = requests.get(
            f"{CURSEFORGE_API}/mods/{project_id}/files",
            params=params,
            headers={**_HEADERS, "x-api-key": key, "Accept": "application/json"},
            timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        data = r.json().get("data", [])
    except requests.RequestException as e:
        raise NetError(f"无法获取 CurseForge 版本：{e}") from e
    out = [
        _cf_version_entry(f.get("id"), f.get("displayName"), f.get("fileName"),
                          f.get("fileLength"), f.get("fileDate"),
                          f.get("gameVersions"), f.get("downloadUrl", ""))
        for f in data if isinstance(f, dict)
    ]
    _store(cache_key, out)
    return out


def _curseforge_versions_keyless(proj: str, limit: int | None = None,
                                 offset: int = 0) -> list[dict]:
    """免 key 版本列表：数字 project_id 走镜像文件列表，否则 cfwidget（slug）。

    round-142：cfwidget 对整合包 slug 一律 404，且它的 files 对部分项目为空；
    镜像 ``/mods/{id}/files`` 是官方同契约端点且免 key，数字 id 一律优先走它
    （详情页也改为传 project_id）。
    """
    if not proj:
        raise NetError("缺少 CurseForge 项目标识")
    cache_key = f"cfvw:{proj}:{limit}:{offset}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    out: list[dict] | None = None
    if str(proj).isdigit():
        try:
            rows = _cf_files_mirror(str(proj))
            if limit:
                rows = rows[offset:offset + limit]
            elif offset:
                rows = rows[offset:]
            out = [
                _cf_version_entry(f.get("id"), f.get("displayName"),
                                  f.get("fileName"), f.get("fileLength"),
                                  f.get("fileDate"), f.get("gameVersions"),
                                  f.get("downloadUrl", ""))
                for f in rows if isinstance(f, dict)
            ]
        except NetError:
            out = None  # 镜像挂了 → 落到下方 cfwidget 兜底
    if out is None:
        d = _cfwidget_info(proj)
        files = [f for f in (d.get("files") or []) if isinstance(f, dict)]
        if limit:
            files = files[offset:offset + limit]
        out = [
            _cf_version_entry(f.get("id"), f.get("display"), f.get("name"),
                              f.get("filesize"), f.get("uploaded_at"),
                              f.get("versions"), f.get("url") or "")
            for f in files
        ]
    _store(cache_key, out)
    return out


def download_curseforge_file(project_id: str, file_id, dest_dir: str,
                             filename: str = "", url: str = "",
                             callback=None) -> str:
    """Download one specific CurseForge file into ``dest_dir``.

    Uses the official ``download-url`` endpoint when a key is configured
    (respects author distribution consent); ``url`` from the file listing is a
    fallback for keys whose endpoint is unavailable.
    """
    key = _curseforge_key()
    link = url
    if key and project_id and file_id:
        try:
            r = requests.get(
                f"{CURSEFORGE_API}/mods/{project_id}/files/{file_id}/download-url",
                headers={**_HEADERS, "x-api-key": key, "Accept": "application/json"},
                timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
            )
            r.raise_for_status()
            link = r.json().get("data") or link
        except requests.RequestException:
            if not link:
                raise NetError("该文件没有可用的下载链接（作者可能禁止第三方分发）")
    if not link:
        raise NetError("该文件没有可用的下载链接")
    name = filename or f"{project_id}-{file_id}.jar"
    os.makedirs(dest_dir, exist_ok=True)
    return download_file(link, os.path.join(dest_dir, name), timeout=120,
                         progress=_cb_progress(callback))


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
    # round-128：免 key 通道只认 slug，中文输入先经名库反查（逐个试，
    # 命中即返回），避免直接把「小地图」当 slug 去查必然 404。
    if has_cjk(slug):
        for cand in _lookup_cn_slugs(slug)[:3]:
            try:
                return curseforge_link_search(cand, limit)
            except NetError:
                continue
        raise NetError(_t_err(
            "err.cf_zh_missing",
            default="CurseForge 免 key 通道只支持英文 slug，未能在本地中文名库中找到「{q}」",
            q=query))
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
        "source": "curseforge",
        "_cf_file": {
            "id": f.get("id"),
            "name": f.get("name", f"{slug}.jar"),
        },
    }]
    _store(key, hits)
    return hits


def download_cfwidget_file(cf_file: dict, dest_dir: str, callback=None) -> str:
    """下载 cfwidget 解析出的最新文件（forgecdn 直链，无需 key）。

    round-111：新增 ``callback``（mll 风格，ProgressWorker 注入）→ 进度/速度。
    """
    fid = cf_file.get("id")
    name = cf_file.get("name", "mod.jar")
    if not fid:
        raise NetError("缺少文件 ID")
    url = FORGECDN_URL.format(a=fid // 1000, b=fid % 1000, name=name)
    os.makedirs(dest_dir, exist_ok=True)
    return download_file(url, os.path.join(dest_dir, name), timeout=120,
                         progress=_cb_progress(callback))


def download_cfwidget_slug(slug: str, dest_dir: str, callback=None) -> str:
    """免 key 下载：slug → cfwidget 最新文件 → forgecdn 直链（round-140）。

    供免 key 镜像搜索命中的卡片使用——命中只有 slug / project_id，没有
    官方 download-url 端点可用，走公开直链通道。
    """
    hits = curseforge_link_search(slug)
    cf_file = (hits[0] or {}).get("_cf_file") if hits else None
    if not cf_file:
        raise NetError(_t_err("err.curseforge_no_file",
                              default="该 mod 没有可下载的文件"))
    return download_cfwidget_file(cf_file, dest_dir, callback=callback)


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


# ── 中文关键词搜索（round-128）──────────────────────────────────────────
# Modrinth 的 /search 不认中文（搜「小地图」只会命中几个翻译补丁），facet
# 里的 project_id OR 也不支持零 query。所以中文输入只能先在本地名库里反查
# slug，再用 /projects?ids= 批量取项目。这一层就是「PCL2 搜小地图能出
# Xaero's Minimap」的实现方式。
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def has_cjk(text: str) -> bool:
    """文本里是否含汉字（用于判断该不该走本地反查）。"""
    return bool(_CJK_RE.search(text or ""))


def _lookup_cn_slugs(query: str) -> list[str]:
    """中文关键词 → 名库里命中的 slug（精确 > 前缀 > 包含）。"""
    from .mod_names import cn_slug_map
    q = (query or "").strip()
    if not q:
        return []
    ranked: list[tuple[int, str]] = []
    for short, slugs in cn_slug_map().items():
        if q == short:
            rank = 0
        elif short.startswith(q) or q.startswith(short):
            rank = 1
        elif q in short:
            rank = 2
        else:
            continue
        for s in slugs:
            ranked.append((rank, s))
    ranked.sort()
    seen: set[str] = set()
    out: list[str] = []
    for _, slug in ranked:
        if slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _projects_by_slugs(slugs: list[str]) -> list[dict]:
    """批量取项目（/v2/projects?ids=，上游单次上限 25 个）。"""
    out: list[dict] = []
    for i in range(0, len(slugs), 25):
        chunk = slugs[i:i + 25]
        try:
            r = requests.get(
                MODRINTH_PROJECTS_URL, params={"ids": json.dumps(chunk)},
                headers=_HEADERS, timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            raise NetError(
                _t_err("err.search_mods", default="无法搜索资源：{err}", err=e)
            ) from e
        if isinstance(data, list):
            out.extend(data)
    return out


def search_mods_zh(query: str, offset: int = 0, limit: int = 20,
                   project_type: str = "mod") -> list[dict]:
    """中文关键词搜索：本地名库反查 → 批量取项目 → 过滤类型 → 分页。"""
    try:
        from .i18n import get_language
        _lang = get_language()
    except Exception:
        _lang = "zh-CN"
    key = f"mods_zh:{query}:{project_type}:{_lang}"
    cached = _cached(key)
    if cached is None:
        slugs = _lookup_cn_slugs(query)
        projects = _projects_by_slugs(slugs[:60]) if slugs else []
        cached = [
            {
                "project_id": p.get("id", ""),
                "slug": p.get("slug", ""),
                "title": (cn_name(p.get("slug", ""), p.get("title", ""))
                          if _lang != "en-US" else p.get("title", "")),
                "description": p.get("description", ""),
                "downloads": p.get("downloads", 0),
                "icon_url": p.get("icon_url") or "",
                # /v2/projects 不带作者名（team/organization 只是 id），
                # 名库反查数量少、列表页对作者不敏感，留空即可。
                "author": "",
                "source": "modrinth",
            }
            for p in projects
            if p.get("project_type", "mod") == project_type
        ]
        _store(key, cached)
    return cached[offset:offset + limit]


def mcmod_search_url(name: str) -> str:
    """MC百科搜索页地址（无匹配条目时的兜底入口）。"""
    name = (name or "").strip()
    return (MCMOD_SEARCH_URL + "?key=" + requests.utils.quote(name)) if name \
        else MCMOD_SEARCH_URL


def mcmod_entry_url(name: str) -> str:
    """MC百科条目地址：命中就返回精确 /class/<id>.html，否则返回搜索页。

    走 7 天缓存；网络失败/结构变化都退回搜索页，绝不阻塞用户看说明。
    """
    name = (name or "").strip()
    if not name:
        return MCMOD_SEARCH_URL
    search = mcmod_search_url(name)
    key = "mcmod:" + name
    cached = _cached(key, _DISK_CACHE_TTL)
    if cached is not None:
        return cached
    url = search
    try:
        r = requests.get(search, headers=_MCMOD_HEADERS,
                         timeout=_REQUEST_TIMEOUT, proxies=_proxies())
        if r.ok:
            # 结果页里条目链接是相对路径（/class/2785.html），绝对 URL 只在
            # 少数位置出现——两种都接，取第一条（搜索相关性最高）。
            m = re.search(r"/class/(\d+)\.html", r.text)
            if m:
                url = MCMOD_CLASS_URL.format(id=m.group(1))
                # 只缓存命中：mcmod 对连续请求偶发返回空壳页（实测），
                # 把失败也写进 7 天缓存会让用户这周都拿不到精确条目。
                _store(key, url)
    except requests.RequestException:
        pass
    return url


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
    # round-128：中文关键词走本地名库反查（Modrinth 搜索不认中文）。
    if query and has_cjk(query):
        return search_mods_zh(query, offset, limit, project_type)
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
            "source": "modrinth",
        }
        for h in data.get("hits", [])
    ]
    _store(key, hits)
    return hits


class _CbProgress:
    """把 mll 风格 callback 桥接成 net_api 的 ``progress(sofar, total)``。

    round-111：:class:`ProgressWorker` 会自动往被调用函数注入 mll 风格的
    ``callback`` dict（``setProgress`` / ``setMax``，整数协议）。net_api 的
    下载器只认 ``progress(sofar, total)``，所以需要这层桥接。

    多文件场景（依赖树）用「文件序号 × 100 + 文件内百分比」聚合成总体进度，
    让进度条跨文件平滑前进而不是每完成一个文件跳一格。
    """

    __slots__ = ("_sp", "_sm", "_n", "_i")

    def __init__(self, callback, nfiles: int = 1):
        self._sp = callback.get("setProgress") if isinstance(callback, dict) else None
        self._sm = callback.get("setMax") if isinstance(callback, dict) else None
        self._n = max(1, int(nfiles))
        self._i = 0
        if self._sm is not None:
            try:
                self._sm(self._n * 100)
            except Exception:  # noqa: BLE001 - UI 回调绝不拖垮下载
                pass

    def next_file(self) -> None:
        self._i = min(self._i + 1, self._n)

    def __call__(self, sofar: int, total: int) -> None:
        if self._sp is None:
            return
        try:
            frac = (sofar / total) if total else 0.0
            self._sp(self._i * 100 + int(frac * 100))
        except Exception:  # noqa: BLE001 - UI 回调绝不拖垮下载
            pass


def _cb_progress(callback, nfiles: int = 1):
    """有可用 setProgress 时才返回桥接器，否则返回 None（零开销）。"""
    if isinstance(callback, dict) and callback.get("setProgress") is not None:
        return _CbProgress(callback, nfiles)
    return None


def download_modpack_to(project_id: str, dest_dir: str, callback=None) -> str:
    """Download a Modrinth modpack's primary file (a .mrpack) into dest_dir.

    Returns the local .mrpack path — the caller then installs it as a new
    instance via ``core.install.install_mrpack``.

    round-111：``callback`` 收 mll 风格 dict（``setProgress`` / ``setMax``），
    由 :class:`ProgressWorker` 自动注入。把它桥接到 net_api 的
    ``progress(sofar, total)``，整合包下载从此有字节级进度与实时速度
    （之前走裸 ``Worker``，只有提速没有可观测性）。
    """
    filename, url = get_mod_download(project_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, filename)

    progress_cb = None
    if isinstance(callback, dict):
        set_progress = callback.get("setProgress")
        set_max = callback.get("setMax")
        if set_progress is not None:
            _maxed: list[int] = []

            def _on_progress(sofar, total):  # noqa: A002 - 对齐 net_api 签名
                try:
                    if total and not _maxed and set_max is not None:
                        _maxed.append(1)
                        set_max(total)
                    set_progress(sofar)
                except Exception:  # noqa: BLE001 - UI 回调绝不拖垮下载
                    pass

            progress_cb = _on_progress

    return download_file(url, dest, timeout=120, progress=progress_cb)



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


# Cleanroom ships on its own download site and mirrors every installer to
# repo.cleanroommc.com. GitHub's API is frequently unreachable from CN
# networks (which is exactly the "missing installer URL" failure in round-126),
# so scrape the official page and prefer the Maven mirror it links.
CLEANROOM_DOWNLOAD_PAGE = "https://download.cleanroommc.com/"
CLEANROOM_MAVEN_BASE = (
    "https://repo.cleanroommc.com/releases/com/cleanroommc/cleanroom")
# Last known-good build, used when both the page and the cache are unavailable
# so the loader picker never ends up with a URL-less "latest" entry.
CLEANROOM_LATEST_FALLBACK = "0.7.12-alpha"

_CR_VERSION_RE = re.compile(
    r"cleanroom-(\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)-installer\.jar")


def cleanroom_installer_url(version: str, maven: bool = True) -> str:
    """Direct installer URL for a Cleanroom build.

    ``maven=True`` returns the official Maven mirror (fast in CN); the GitHub
    release URL is the fallback for mirrors that have not synced a build yet.
    """
    ver = (version or "").strip()
    if maven:
        return (f"{CLEANROOM_MAVEN_BASE}/{ver}/"
                f"cleanroom-{ver}-installer.jar")
    return ("https://github.com/CleanroomMC/Cleanroom/releases/download/"
            f"{ver}/cleanroom-{ver}-installer.jar")


def fetch_cleanroom_builds():
    key = "cleanroom:releases"
    cached = _cached(key)
    if cached:  # an empty cached list is a failed fetch — retry, don't reuse
        return cached
    versions: list[str] = []
    try:
        r = requests.get(CLEANROOM_DOWNLOAD_PAGE, headers=_HEADERS,
                         timeout=_REQUEST_TIMEOUT, proxies=_proxies())
        r.raise_for_status()
        for v in _CR_VERSION_RE.findall(r.text):
            if v not in versions:
                versions.append(v)
    except requests.RequestException:
        pass
    if not versions:
        versions = [CLEANROOM_LATEST_FALLBACK]
    out = [{
        "title": v,
        "description": "Cleanroom · 1.12.2 on Java 25",
        "_installer_url": cleanroom_installer_url(v),
        "downloads": 0,
        "author": "CleanroomMC",
    } for v in versions]
    _store(key, out)
    return out


# LabyMod 4 has no standalone Forge jar — the official installer is the only
# distribution (it writes the client jar + a dedicated version JSON). Round-126
# request: no browser detour, fetch it inside the launcher and run it there.
LABYMOD_INSTALLER_URL = (
    "https://releases.r2.labymod.net/launcher/win32/x64/"
    "LabyModLauncherSetup-latest.exe")


def download_labymod_installer(dest_dir: str, progress=None) -> str:
    """Download the official LabyMod installer into ``dest_dir``; return path."""
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "LabyModLauncherSetup-latest.exe")
    return parallel_download_file(LABYMOD_INSTALLER_URL, dest,
                                  progress=progress, timeout=60)
