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
# round-207：搜索请求单独收紧到与 search_all 总预算一致。下载 / 文件清单仍用
# 15s（大文件、慢网需要），但搜索挂满 15s 会让慢源在后台多跑近一倍预算。
_SEARCH_TIMEOUT = 8.0
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
                  cancel, expected_sha1: str = "") -> bool:
    """大文件 → 分片多线程；小文件 / 拿不到长度 / 分片失败 → 返回 False。

    返回 False 时调用方继续走单流 ``download_file`` —— 只做加速，不改变语义
    （分片内部失败也会自己回退到单流）。
    """
    size = _remote_size(url, headers, timeout)
    if size < _PARALLEL_MIN_BYTES:
        return False
    try:
        parallel_download_file(url, dest, progress=progress, headers=headers,
                               timeout=timeout, cancel=cancel,
                               expected_sha1=expected_sha1)
        return True
    except Exception:  # noqa: BLE001 - 加速路径失败，退回单流
        return False



class _TransientDownloadError(NetError):
    """网络抖动 / 内容不完整：值得清空重试或续传；4xx 等确定性错误不抛它。"""


def _parse_content_range(value: str) -> tuple[int | None, int | None]:
    """``bytes 100-999/1000`` → ``(100, 1000)``；``bytes */1000`` → ``(None, 1000)``。

    round-217：单流续传原来看见 206 就 append，完全不核对服务器实际返回的
    区间起点。带 Range 的请求经代理/CDN（或服务端 Range 归一化）回来一个
    「从 0 开始」的 206 时，就会把文件头接到 .part 尾部 —— 一个字节数看起来
    合理、内容彻底错位的坏文件，而且还会被 os.replace 转正。
    """
    if not value:
        return None, None
    m = re.match(r"bytes\s+(?:(\d+)-(\d+)|\*)/(\d+|\*)", value.strip())
    if not m:
        return None, None
    start = int(m.group(1)) if m.group(1) is not None else None
    total = int(m.group(3)) if m.group(3) not in (None, "*") else None
    return start, total


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
    expected_sha1: str = "",
) -> str:
    """单次下载尝试：写 <dest>.part → 校验 size/hash → os.replace 原子收尾。

    round-178：`expected_sha1` 非空时在 **.part 阶段**校验，坏字节永远不
    会 `os.replace` 成正式文件；不匹配就丢掉 .part 抛瞬时错误让上层重下。

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
            # Range 不满足：可能是「本地 .part 已经是完整文件」，也可能是
            # 「本地 .part 比远端还大」（旧版本残留 / 远端换了个更小的文件）。
            # round-217：原实现一律当成品直接 os.replace，后一种情况会把一个
            # 尺寸错误的文件转正，而后续「大小相同 → 认为已安装」的判据再也
            # 修不了它。这里先用 Content-Range 的总长核对，对不上就清掉重下。
            _s, total_remote = _parse_content_range(
                r.headers.get("Content-Range", ""))
            size_local = os.path.getsize(dest_tmp)
            r.close()
            if total_remote is None or size_local != total_remote:
                try:
                    os.remove(dest_tmp)
                except OSError:
                    pass
                return _download_once(
                    url, dest, dest_tmp, resume=False, progress=progress,
                    headers=headers, timeout=timeout, cancel=cancel,
                    expected_sha1=expected_sha1)
            if expected_sha1:
                _verify_sha1(dest_tmp, expected_sha1)
            os.replace(dest_tmp, dest)
            return dest
        r.raise_for_status()
        # 只有「确实是 206，且服务器声明的区间起点 == 本地已有长度」才允许 append
        resume_ok = False
        if start and r.status_code == 206:
            seg_start, _seg_total = _parse_content_range(
                r.headers.get("Content-Range", ""))
            resume_ok = seg_start == start
            if not resume_ok:
                # 起点对不上 → 丢弃本地 .part 从头写，绝不允许拼接错位内容
                start = 0
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
    if expected_sha1:
        try:
            _verify_sha1(dest_tmp, expected_sha1)
        except NetError:
            # hash 不符 = 内容已损坏；留着 .part 续传只会把坏字节拼进去，
            # 必须丢掉从头重下（_verify_sha1 已删文件，这里再兜一次）。
            try:
                os.remove(dest_tmp)
            except OSError:
                pass
            raise _TransientDownloadError(
                "文件校验失败（sha1 不匹配），已丢弃重下") from None
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
    expected_sha1: str = "",
) -> str:
    """下载 ``url`` 到 ``dest``，支持断点续传 + 进度回调 + 有限退避重试。

    Args:
        expected_sha1: 可选；非空时落盘前校验 sha1，不符则丢弃重下（round-178）
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
                              headers=headers, cancel=cancel,
                              expected_sha1=expected_sha1)):
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
                timeout=timeout, cancel=cancel,
                expected_sha1=expected_sha1)
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
    expected_sha1: str = "",
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
    # round-177：绝不预删 dest。旧实现先把已存在的 mod / 核心 jar 删掉，
    # 万一分片失败且单流兜底也失败，玩家原本能用的文件就没了。全程写
    # .part、最后 os.replace(part, dest) 原子覆盖，本来就不需要先删。
    with open(part, "wb") as f:
        f.truncate(total)

    lock = _threading.Lock()
    done = [0]
    seg_done = {seg: 0 for seg in ranges}

    def _tick(seg, nbytes: int) -> None:
        with lock:
            seg_done[seg] += nbytes
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
        # 重跑该段前把它的进度退回，避免重试时进度条越过 100%。
        with lock:
            done[0] -= seg_done[seg]
            seg_done[seg] = 0
        for attempt in range(3):
            try:
                h = dict(hdrs)
                h["Range"] = f"bytes={s}-{e}"
                rr = requests.get(url, headers=h, timeout=timeout, stream=True, proxies=_proxies())
                try:
                    # round-210 P0：probe 阶段已确认服务端支持 Range，但部分 CDN /
                    # 镜像只对首个请求返回 206，后续分片静默降级成 200 + 整文件。
                    # 旧实现把 200 也当成分片成功 → 各段把整文件从自己的 offset
                    # 写进去互相覆盖，.part 拼出一个坏 jar，还会 sha1 蒙混过关或
                    # 被 os.replace 成正式文件，下次 isfile 判已装跳过修复。
                    # 现在严格要求 206 且 Content-Range 起点与本段一致。
                    if rr.status_code != 206:
                        rr.raise_for_status()
                        raise NetError("服务端未返回 206，Range 被忽略")
                    cr = (rr.headers.get("Content-Range") or "").strip()
                    m = re.match(r"bytes\s+(\d+)-(\d+)/(\d+)", cr)
                    if not m or int(m.group(1)) != s:
                        raise NetError(f"分片范围不匹配：期望 {s}-，收到 {cr!r}")
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
                            _tick(seg, len(chunk))
                    # .part 已 truncate 到全长，未写区域是零填充，必须以「写入
                    # 字节数」判定；且不能多于本段长度（多写会污染相邻段）。
                    if seg_written == e - s + 1:
                        return
                    raise NetError(
                        f"段长度不符：期望 {e - s + 1}，实际 {seg_written}")
                finally:
                    rr.close()
            except NetError:
                raise
            except Exception:
                if attempt == 2:
                    raise
                _time.sleep(0.5 * (attempt + 1))

    # 4) 并行执行；round-176：只补跑失败段（每段内部已重试 3 次），
    #    仍失败才清残件回退单流（保证完成）。
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        failed = []
        with ThreadPoolExecutor(max_workers=min(n, len(ranges))) as ex:
            futs = {ex.submit(_worker, seg): seg for seg in ranges}
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception:
                    failed.append(futs[fut])
        if failed:
            with ThreadPoolExecutor(max_workers=min(n, len(failed))) as ex:
                list(ex.map(_worker, failed))
            failed = []
    except Exception:
        failed = list(ranges)
    if failed:
        try:
            os.remove(part)
        except OSError:
            pass
        return download_file(url, dest, resume=False, progress=progress,
                             headers=headers, timeout=timeout, cancel=cancel,
                             _allow_parallel=False,
                             expected_sha1=expected_sha1)
    if expected_sha1:
        try:
            _verify_sha1(part, expected_sha1)
        except NetError:
            try:
                os.remove(part)
            except OSError:
                pass
            # 分片拼出来的内容坏了 → 回退单流从头下，别把坏文件交出去
            return download_file(url, dest, resume=False, progress=progress,
                                 headers=headers, timeout=timeout,
                                 cancel=cancel, _allow_parallel=False,
                                 expected_sha1=expected_sha1)
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
    # round-218：这两个是**服务端过滤参数**，形态不合法时 Modrinth 直接回
    # HTTP 400（实测 "versions:26." → 400）→ 详情页一条版本都拿不到，
    # 玩家看到的就是「版本找不到对应的」。校验不过就不传这个参数。
    _mc = normalize_mc_version(mc_version)
    if _mc:
        params["game_versions"] = f'["{_mc}"]'
    if loader and loader not in ("vanilla", ""):
        _ld = str(loader).strip().lower()
        if _ld and re.match(r"^[a-z0-9_-]{1,24}$", _ld):
            params["loaders"] = f'["{_ld}"]'
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


def _safe_filename(name: str, fallback: str = "download.jar") -> str:
    """round-177：只取 basename，挡住服务端返回 ``../`` 写穿目标目录。"""
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    if not base or base in (".", ".."):
        return fallback
    return base


def _cf_sha1(f: dict) -> str:
    """round-178：从 CurseForge / 镜像 / cfwidget 的文件元数据取 sha1。

    CF 官方 ``hashes`` 是 ``[{"algo": 1, "value": "..."}]``（1=SHA1、2=MD5）；
    镜像同契约；cfwidget 偶尔给 ``{"sha1": "..."}`` 或直接 ``sha1`` 字段。
    取不到返回空串 → 退化为只校验长度（绝不拿 MD5 / fingerprint 冒充 sha1）。
    """
    if not isinstance(f, dict):
        return ""
    h = f.get("hashes")
    if isinstance(h, list):
        for item in h:
            if not isinstance(item, dict):
                continue
            algo = item.get("algo", item.get("algorithm", ""))
            if algo in (1, "1", "sha1", "SHA1") and item.get("value"):
                return str(item["value"])
    elif isinstance(h, dict) and h.get("sha1"):
        return str(h["sha1"])
    return str(f.get("sha1") or "")


_CF_LOADER_TAGS = {"forge", "fabric", "quilt", "neoforge",
                   "liteloader", "rift", "bukkit", "spigot", "paper"}


def _cf_filter_files(rows: list[dict], mc_version: str = "",
                     loader: str = "") -> list[dict]:
    """round-178：按实例 MC 版本 / 加载器筛 CurseForge 候选文件。

    CF 官方 ``gameVersions`` 形如 ``["1.20.1", "Forge", "Java 17"]``；
    cfwidget 用 ``versions``。规则保守：字段缺失时**不因未知而误杀**
    （资源包 / 光影常不标加载器），只有明确声明了不兼容值时才排除。
    """
    out = []
    mc = str(mc_version or "").strip().lower()
    ld = str(loader or "").strip().lower()
    for f in rows or []:
        if not isinstance(f, dict):
            continue
        raw = f.get("gameVersions") or f.get("versions") or []
        gv = [str(x).strip().lower() for x in raw if x]
        if mc and gv and mc not in gv:
            continue
        if ld and gv:
            declared = [g for g in gv if g in _CF_LOADER_TAGS]
            if declared and ld not in declared:
                continue
        out.append(f)
    return out


def _primary_hashes(version: dict) -> dict:
    """Modrinth version.primary file 的 hashes（sha1/sha512），供下载后校验。"""
    files = version.get("files", []) or []
    primary = next((f for f in files if f.get("primary")),
                   files[0] if files else {})
    h = primary.get("hashes") or {}
    return h if isinstance(h, dict) else {}


def _verify_sha1(path: str, expected: str) -> None:
    """下载完成后校验 sha1；不匹配就删掉坏文件并抛 NetError。"""
    if not expected:
        return
    import hashlib
    digest = hashlib.sha1()  # noqa: S324 - 校验用，非安全用途
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != expected.lower():
        try:
            os.remove(path)
        except OSError:
            pass
        raise NetError("文件校验失败（sha1 不匹配），已删除损坏文件")


def _version_primary_file(version: dict, project_id: str) -> tuple[str, str]:
    """(filename, url) of a version's primary file. Raises NetError if none."""
    files = version.get("files", [])
    if not files:
        raise NetError("该模组版本没有可下载的文件")
    primary = next((f for f in files if f.get("primary")), files[0])
    return primary.get("filename", f"{project_id}.jar"), primary.get("url", "")


# round-41：Modrinth project 信息查询（slug→id/title/最新版本）——缓存。
# round-218：Modrinth 的版本 facet 对**非法** id 直接回 HTTP 400
# （实测 "versions:26." → 400），整个搜索请求就挂了 → 玩家看到「搜不到任何
# 东西」。所以凡是拼进 facet / gameVersion 的版本号，都要先过形态校验。
_MC_VERSION_RE = re.compile(r"^\d+(\.\d+){0,2}(-[0-9A-Za-z._-]+)?$")


def normalize_mc_version(raw) -> str:
    """规整 MC 版本号；形态不合法一律返回 ""（调用方按「不过滤」处理）。"""
    v = str(raw or "").strip()
    if not v or not _MC_VERSION_RE.match(v):
        return ""
    return v


def modrinth_game_versions(*, timeout: int = 20) -> list[str]:
    """Modrinth 官方版本标签列表（release 优先 + 最近几个 snapshot，按日期倒序）。

    round-218：版本下拉原来是一张**写死的 12 条**静态表（抄自 Prism，最新只到
    1.21.11）。主理人的实例是 MC **26.3**，压根不在表里 → 「我想要的版本找不到
    对应的」。这里改成从 Modrinth 的 ``/tag/game_version`` 拉真实列表
    （实测 922 条，含 26.3），离线时回退静态表。
    """
    key = "mr:tag:game_version"
    cached = _cached(key, 1800)
    if cached is not None:
        return cached
    base = MODRINTH_SEARCH_URL.replace("/search", "")
    try:
        r = requests.get("%s/tag/game_version" % base, headers=_HEADERS,
                         timeout=timeout, proxies=_proxies())
        r.raise_for_status()
        data = r.json()
    except Exception:  # noqa: BLE001 - 离线 / 限流：回退静态表，不打断搜索
        return []
    rel: list[tuple[str, str]] = []
    snap: list[tuple[str, str]] = []
    for x in data if isinstance(data, list) else []:
        if not isinstance(x, dict):
            continue
        vid = str(x.get("version") or "").strip()
        if not vid:
            continue
        item = (str(x.get("date") or ""), vid)
        if x.get("version_type") == "release":
            rel.append(item)
        elif x.get("version_type") == "snapshot":
            snap.append(item)
    rel.sort(reverse=True)
    snap.sort(reverse=True)
    out = [v for _d, v in rel[:80]] + [v for _d, v in snap[:8]]
    if out:
        _store(key, out)
    return out


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


def get_mod_download(project_id: str,
                     version_id: str = "") -> tuple[str, str]:
    """Resolve a version's primary file (filename, download url).

    round-178：允许指定 version_id —— 资源中心「选版本装整合包」与
    「一键装最新版」原先走两条口径，前者没法复用本函数。
    """
    versions = _modrinth_versions(project_id)
    if not versions:
        raise NetError("该模组没有可下载的文件")
    target = versions[0]
    if version_id:
        target = next((v for v in versions if v.get("id") == version_id), None)
        if target is None:
            raise NetError("指定的整合包版本不存在或已下架")
    return _version_primary_file(target, project_id)


def project_supports(project_id: str, mc_version: str = "",
                     loader: str = "") -> dict:
    """查 Modrinth 项目声明能否用于「该 MC 版本 + 该加载器」（round-182）。

    返回 ``{"exists": bool, "loaders": [...], "game_versions": [...],
    "version_ok": bool|None, "loader_ok": bool|None}``。``None`` 表示
    项目没声明该字段（或列表为空）→ 未知，调用方不应据此判死。

    客户端增强包用它给出「这个 mod 在你这实例上装不了，因为它只支持
    Forge」这种**有据可依**的拒绝，而不是装了启动即崩。
    """
    info = get_project_info(project_id)
    if not info:
        return {"exists": False, "loaders": [], "game_versions": [],
                "version_ok": None, "loader_ok": None}
    loaders = [str(x).lower() for x in (info.get("loaders") or [])]
    gv = [str(x) for x in (info.get("game_versions") or [])]
    mc = str(mc_version or "").strip()
    ld = str(loader or "").strip().lower()
    return {
        "exists": True,
        "loaders": loaders,
        "game_versions": gv,
        "version_ok": (mc in gv) if (mc and gv) else None,
        "loader_ok": (ld in loaders) if (ld and loaders) else None,
    }


def find_mod_version(project_id: str, mc_version: str = "",
                     loader: str = "") -> dict | None:
    """挑一个「该 MC 版本 + 该加载器」下真能用的构建（round-182）。

    ``_modrinth_versions`` 的 game_versions / loaders 是服务端过滤参数，
    正常情况下第一个就够用；这里再在本地复核一遍——服务端偶尔会忽略
    过滤（尤其是很老的版本号），拿到的构建装上去就是启动即崩。
    找不到可用构建返回 ``None``（而不是抛错），由调用方给出人话。
    """
    versions = _modrinth_versions(project_id, mc_version, loader, limit=20)
    mc = str(mc_version or "").strip()
    ld = str(loader or "").strip().lower()
    for v in versions or []:
        if not isinstance(v, dict):
            continue
        gv = [str(x) for x in (v.get("game_versions") or [])]
        lds = [str(x).lower() for x in (v.get("loaders") or [])]
        if mc and gv and mc not in gv:
            continue
        if ld and lds and ld not in lds:
            continue
        try:
            _name, url = _version_primary_file(v, project_id)
        except NetError:
            continue
        if url:
            return v
    return None


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
    only_self: bool = False,
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
        if _depth == 0:
            raise  # round-177：本体的网络错误不能吞，否则 UI 显示「已下载」却啥也没装
        return out  # 子依赖失败可降级，主文件照常安装
    if not versions:
        if _depth == 0:
            raise NetError("该模组没有匹配当前游戏版本 / 加载器的文件")
        return out
    target = versions[0]
    if version_id:
        target = next((v for v in versions if v.get("id") == version_id), None)
        if target is None:
            if _depth == 0:
                raise NetError(
                    "指定的版本不存在，或不在当前游戏版本 / 加载器的匹配结果中")
            return out  # 子依赖的精确版本取不到 → 宁可不装，也不装错版本
    try:
        filename, url = _version_primary_file(target, project_id)
    except NetError:
        return out
    out.append({
        "project_id": project_id,
        "filename": filename,
        "url": url,
        "sha1": _primary_hashes(target).get("sha1", ""),
        "optional": False,
    })
    if only_self:
        # round-193：玩家明确选择「不装前置」时只取本体
        return out
    for dep in target.get("dependencies", []):
        dtype = dep.get("dependency_type", "")
        dpid = dep.get("project_id", "")
        # round-178：embedded 是已打包进本体的库，再单独下 jar 会造成
        # duplicate modid；incompatible/optional 同理不装。
        if not dpid or dtype in ("optional", "incompatible", "embedded"):
            continue
        if dpid in _seen:
            continue
        # 依赖声明带 version_id 时必须精确解析，否则会拉到与本体要求不符
        # 的最新版（Modrinth dependencies 支持指定 version）。
        out.extend(
            resolve_mod_dependencies(dpid, mc_version, loader,
                                     dep.get("version_id", "") or "",
                                     _seen, _depth + 1))
    return out


def mod_version_dependencies(project_id: str, version_id: str = "",
                             mc_version: str = "", loader: str = "") -> list[dict]:
    """某个版本的**前置模组**清单（round-193）。

    返回 ``[{"project_id", "title", "slug", "version_id", "optional"}]``：
    * ``title`` 优先用本地中文名库，其次 Modrinth 原名；
    * 只列 ``required``（optional / incompatible / embedded 都不装）。

    用途：详情页把前置**摆出来**给玩家看，下载前再问一句「是否一并安装」——
    玩家不该在进游戏报「缺前置」之后才知道这事。
    """
    if not project_id:
        return []
    versions = _modrinth_versions(project_id, mc_version, loader)
    target = None
    for v in versions:
        if str(v.get("id")) == str(version_id):
            target = v
            break
    if target is None and versions:
        target = versions[0]
    if target is None:
        return []
    deps = []
    for dep in target.get("dependencies", []) or []:
        dtype = str(dep.get("dependency_type", "") or "")
        dpid = str(dep.get("project_id", "") or "")
        if not dpid or dtype != "required":
            continue
        title, slug = _dep_title(dpid)
        deps.append({
            "project_id": dpid,
            "title": title,
            "slug": slug,
            "version_id": str(dep.get("version_id", "") or ""),
            "optional": False,
        })
    return deps


def _dep_title(project_id: str) -> tuple[str, str]:
    """取依赖项目的名字（中文名库优先），失败就退回 id。"""
    slug = ""
    title = ""
    try:
        info = get_project_info(project_id)
        if isinstance(info, dict):
            slug = str(info.get("slug", "") or "")
            title = str(info.get("title", "") or "")
    except Exception:  # noqa: BLE001 - 网络失败就退回 id
        pass
    if not title:
        title = project_id
    try:
        from .i18n import get_language
        if get_language() != "en-US":
            title = cn_name(slug, title) if slug else title
    except Exception:  # noqa: BLE001
        pass
    return title, slug


def download_mod_to(
    project_id: str,
    dest_dir: str,
    mc_version: str = "",
    loader: str = "",
    callback=None,
    manifest_out: list | None = None,
    with_deps: bool = True,
) -> str:
    """Download a mod + its required dependency tree into dest_dir.

    round-37：依赖树自动拉取（Modrinth required dependencies 递归解析）。
    返回本体文件路径（保持旧签名兼容——UI 只需显示主文件）。

    round-111：``callback`` 收 mll 风格 dict（由 :class:`ProgressWorker`
    注入），桥接成跨文件聚合的字节级进度 + 实时速度。
    """
    files = resolve_mod_dependencies(project_id, mc_version, loader,
                                     only_self=not with_deps)
    if with_deps:
        # round-220：跨源「必需伴随」覆盖（Ultimine Unchained → FTB Ultimine 等）
        files.extend(_override_companions(project_id, mc_version, loader))
    if not files:
        raise NetError("没有可下载的文件")
    os.makedirs(dest_dir, exist_ok=True)
    prog = _cb_progress(callback, len(files))
    primary_path = ""
    for item in files:
        if not item["url"]:
            continue
        dest = os.path.join(dest_dir, _safe_filename(item["filename"]))
        # round-37：统一断点续传下载器（中断后 .part 续传）
        try:
            download_file(item["url"], dest, progress=prog,
                          expected_sha1=item.get("sha1", ""))
        except NetError as e:
            raise NetError(f"下载失败（{item['filename']}）：{e}") from e
        if prog is not None:
            prog.next_file()
        if manifest_out is not None:
            # round-191：把「这次下了哪些文件、各属于哪个项目」回报给调用方，
            # 供它登记模组来源（区分资源中心下载 vs 手动放入）。依赖也在内 ——
            # 否则依赖在模组列表里会被当成"本地安装"。
            manifest_out.append({
                "filename": item["filename"],
                "project_id": item["project_id"],
            })
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
    manifest_out: list | None = None,
    with_deps: bool = True,
) -> str:
    """Download a specific version of a mod + its dependency tree (round-66).

    资源中心详情页"选择版本下载"入口：与 `download_mod_to` 行为一致，
    但解析给定的 Modrinth version id 而非最新匹配版本。

    round-111：新增 ``callback``（mll 风格，ProgressWorker 注入）→ 进度/速度。
    """
    files = resolve_mod_dependencies(
        project_id, mc_version, loader, version_id=version_id,
        only_self=not with_deps)
    if with_deps:
        # round-220：跨源「必需伴随」覆盖（Ultimine Unchained → FTB Ultimine 等）
        files.extend(_override_companions(project_id, mc_version, loader))
    if not files:
        raise NetError("没有可下载的文件（或该版本不存在）")
    os.makedirs(dest_dir, exist_ok=True)
    prog = _cb_progress(callback, len(files))
    primary_path = ""
    for item in files:
        if not item["url"]:
            continue
        dest = os.path.join(dest_dir, _safe_filename(item["filename"]))
        try:
            download_file(item["url"], dest, progress=prog,
                          expected_sha1=item.get("sha1", ""))
        except NetError as e:
            raise NetError(f"下载失败（{item['filename']}）：{e}") from e
        if prog is not None:
            prog.next_file()
        if manifest_out is not None:
            manifest_out.append({
                "filename": item["filename"],
                "project_id": item["project_id"],
            })
        if item["project_id"] == project_id:
            primary_path = dest
    return primary_path


# ── CurseForge 依赖树解析（round-220）────────────────────────────────
# 资源中心的依赖递归解析一直只有 Modrinth 通道；CurseForge 通道直接下单，
# 导致 FTB Ultimine（CF 独占，project 448231）这种「本体 + 前置分开发布」的
# 模组，装完缺 FTB Library / Architectury，版本不对就崩退出码 1。
# 这里补齐 CF 依赖解析：CF 文件元数据自带 dependencies（relationType），
# 官方 API 与免 key 镜像（mod.mcimirror.top）契约一致，无需 API key。
#
# 实测事实（2026-11-08，来自 CurseForge 镜像）：
#   * FTB Ultimine(448231) 文件 dependencies：FTB Library(438495) relType=3(required)
#     + Fabric API(306612) relType=3；1.21.1 线额外 required Architectury(419699)。
#   * FTB Library(438495) 自身又 required Fabric API(306612)（26.1.x 线）。
#   * Fabric API(306612) 是加载器级依赖（实例已由加载器提供），**不**当作普通
#     mod jar 重下，否则会和实例已有的 Fabric API 撞出两个 jar。
#   * 递归用 _seen 去重 + 深度上限，FTB 家族依赖树干净、不会爆 / 成环。

_CF_REL_REQUIRED = 3
# 加载器级 API：实例已由加载器提供，不当普通 mod 重下（避免双 jar）。
_CF_LOADER_API_IDS = frozenset({"306612"})  # Fabric API (CurseForge)

# 跨源「必需伴随」覆盖：某些上游在一个源发布、却依赖只在另一源存在的模组。
# Modrinth 的 Ultimine Unchained(rGNPldmX) 是 FTB Ultimine 的 mixin 修复补丁，
# 自身只声明 Fabric API + Cloth Config，但**必须有** FTB Ultimine（CF 独占、
# 无 Modrinth 条目）+ FTB Library 才能真正工作；FTB Ultimine 自己的 CF 依赖会
# 顺带把 FTB Library 拉进来，所以这里只桥到 FTB Ultimine 即可。
_KNOWN_DEP_OVERRIDES: dict[str, list[tuple[str, str]]] = {
    "rGNPldmX": [("curseforge", "448231")],  # Ultimine Unchained → FTB Ultimine
}


def _cf_file_required_deps(project_id: str, file_id) -> list[str]:
    """某 CF 文件的 required(relationType==3) 依赖 mod id 列表。

    优先官方 keyed API，失败回退免 key 镜像；都拿不到返回空（子依赖降级、
    主文件照常下）。
    """
    pid, fid = str(project_id), str(file_id or "")
    if not fid:
        return []
    key = _curseforge_key()
    if key:
        try:
            r = requests.get(
                f"{CURSEFORGE_API}/mods/{pid}/files/{fid}",
                headers={**_HEADERS, "x-api-key": key, "Accept": "application/json"},
                timeout=_REQUEST_TIMEOUT, proxies=_proxies())
            if r.status_code == 200:
                f = r.json().get("data") or {}
                return [str(d["modId"]) for d in (f.get("dependencies") or [])
                        if d.get("relationType") == _CF_REL_REQUIRED]
        except requests.RequestException:
            pass
    try:
        r = requests.get(f"{_CF_MIRROR}/mods/{pid}/files/{fid}",
                         headers=_HEADERS, timeout=_REQUEST_TIMEOUT,
                         proxies=_proxies())
        if r.status_code == 200:
            f = r.json().get("data") or r.json()
            return [str(d["modId"]) for d in (f.get("dependencies") or [])
                    if d.get("relationType") == _CF_REL_REQUIRED]
    except requests.RequestException:
        pass
    return []


# round-221：CF 文件列表必须**分页拉全**。
# 老项目动辄上百个文件（FTB Library / NeoForge 404465 实测 183 个），此前
# 只取第一页 50 条，按日期倒序会把旧 MC 版本线整条截掉（1.21 / 1.20.6 /
# 1.19 / 1.18.1 / 1.16.2~4 / 1.15.2 全都落在 index>50），表现为：
#   * 详情页版本列表看不到该 MC 版本的任何文件、offset 翻页越界即空；
#   * 依赖解析 _cf_resolve_dep_file 挑不到匹配前置 → 装完缺库崩游戏。
# 镜像实测支持 pageSize=200 一次拿全；官方 API pageSize 上限 50，需按 index 翻页。
_CF_FILES_PAGE_MIRROR = 200
_CF_FILES_PAGE_OFFICIAL = 50
_CF_FILES_MAX_PAGES = 12


def _cf_files_all(base: str, project_id: str, headers: dict,
                  page_size: int) -> list[dict]:
    """按 ``index`` 分页拉全某 CF 项目的文件列表（官方形状行）。

    直到某页不满 ``page_size`` / 无新增 / 达 ``_CF_FILES_MAX_PAGES`` 上限为止。
    中途失败把已拿到的页照常返回——宁可少几条，也不要整个列表失败；
    按 id 去重同时兜住「服务端忽略 index 反复返回同一页」的死循环。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(_CF_FILES_MAX_PAGES):
        params = {"pageSize": page_size, "index": page * page_size}
        if base == CURSEFORGE_API:
            params.update({"sortField": 2, "sortOrder": "desc"})
        try:
            r = requests.get(f"{base}/mods/{project_id}/files",
                             params=params, headers=headers,
                             timeout=_REQUEST_TIMEOUT, proxies=_proxies())
            r.raise_for_status()
            rows = r.json().get("data") or []
        except requests.RequestException:
            break
        if not isinstance(rows, list):
            break
        fresh = 0
        for f in rows:
            if not isinstance(f, dict):
                continue
            raw_id = f.get("id")
            # 不能用 `or ""`：id 为 0 时会被吞成空串，绕过去重，
            # 让「服务端忽略 index 反复返回同一页」的收敛判断失效。
            fid = "" if raw_id is None else str(raw_id)
            if fid and fid in seen:
                continue
            if fid:
                seen.add(fid)
            out.append(f)
            fresh += 1
        if len(rows) < page_size or fresh == 0:
            break
    return out


def _cf_raw_files(project_id: str) -> list[dict]:
    """某 CF 项目的文件列表（原始形状、分页拉全），官方 API 优先、镜像兜底。"""
    pid = str(project_id)
    key = _curseforge_key()
    if key:
        try:
            rows = _cf_files_all(
                CURSEFORGE_API, pid,
                {**_HEADERS, "x-api-key": key, "Accept": "application/json"},
                _CF_FILES_PAGE_OFFICIAL)
            if rows:
                return rows
        except requests.RequestException:
            pass
    try:
        return _cf_files_mirror(pid)
    except NetError:
        return []


def _cf_resolve_dep_file(project_id: str, mc_version: str, loader: str) -> dict | None:
    """为依赖 mod 选一个匹配实例版本的最新文件，返回可下载元数据。

    返回 {"project_id","file_id","filename","url","sha1"}，挑不到返回 None。
    """
    pid = str(project_id)
    files = _cf_filter_files(_cf_raw_files(pid), mc_version, loader)
    if not files:
        return None
    f = files[0]
    fid = f.get("id")
    fname = f.get("fileName") or ""
    if not (fid and fname):
        return None
    url = f.get("downloadUrl") or ""
    if not _cf_direct_url(url):
        try:
            url = FORGECDN_URL.format(a=int(fid) // 1000, b=int(fid) % 1000,
                                      name=fname)
        except (TypeError, ValueError):
            return None
    return {"project_id": pid, "file_id": str(fid), "filename": fname,
            "url": url, "sha1": _cf_sha1(f)}


def resolve_cf_dependencies(project_id: str, file_id: str,
                            mc_version: str = "", loader: str = "",
                            _seen: set | None = None, _depth: int = 0) -> list[dict]:
    """递归解析 CF required 依赖，返回去重文件清单（**不含本体**）。

    每项 {"project_id","file_id","filename","url","sha1"}，与 MR 解析器同形状，
    下载循环直接复用。跳过 Fabric API 等加载器级依赖；循环 / 超限由 _seen 截断。
    """
    if _seen is None:
        _seen = set()
    out: list[dict] = []
    if project_id in _seen or _depth > _MOD_DEP_MAX_DEPTH:
        return out
    _seen.add(project_id)
    for dpid in _cf_file_required_deps(project_id, file_id):
        if dpid in _seen or dpid in _CF_LOADER_API_IDS:
            continue
        df = _cf_resolve_dep_file(dpid, mc_version, loader)
        if not df:
            continue
        out.append(df)
        out.extend(resolve_cf_dependencies(dpid, df["file_id"], mc_version,
                                           loader, _seen, _depth + 1))
    return out


def cf_project_title(project_id: str) -> str:
    """CF 项目的显示名（中文名库优先），拿不到退回 id。"""
    pid = str(project_id)
    slug, name = "", ""
    try:
        r = requests.get(f"{_CF_MIRROR}/mods/{pid}",
                         headers=_HEADERS, timeout=_REQUEST_TIMEOUT,
                         proxies=_proxies())
        if r.status_code == 200:
            p = r.json().get("data") or r.json()
            slug = str(p.get("slug") or "")
            name = str(p.get("name") or p.get("title") or "")
    except requests.RequestException:
        pass
    if not name:
        return pid
    try:
        from .i18n import get_language
        if get_language() != "en-US" and slug:
            name = cn_name(slug, name)
    except Exception:  # noqa: BLE001
        pass
    return name


def cf_version_dependencies(project_id: str, file_id: str,
                            mc_version: str = "", loader: str = "") -> list[dict]:
    """CF 某文件的 required 前置清单，给详情页「前置」展示用。

    返回 [{"project_id","title","slug","optional":False}]；跳过加载器级 API。
    """
    out = []
    for dpid in _cf_file_required_deps(project_id, file_id):
        if dpid in _CF_LOADER_API_IDS:
            continue
        out.append({"project_id": dpid, "title": cf_project_title(dpid),
                    "slug": "", "optional": False})
    return out


def _override_companions(project_id: str, mc_version: str,
                        loader: str) -> list[dict]:
    """跨源「必需伴随」覆盖：返回附加的 CF 依赖文件清单（已递归解析）。

    仅 Ultimine Unchained(rGNPldmX) 触发，桥到 FTB Ultimine(CF) → FTB Library。
    """
    out: list[dict] = []
    for csrc, cpid in _KNOWN_DEP_OVERRIDES.get(str(project_id), []):
        if csrc != "curseforge":
            continue
        cf = _cf_resolve_dep_file(cpid, mc_version, loader)
        if not cf:
            continue
        out.append(cf)
        out.extend(resolve_cf_dependencies(cpid, cf["file_id"], mc_version, loader))
    return out


def _cf_existing_pid_map(inst, dest_dir: str) -> dict[str, list[str]]:
    """{project_id: [已装在 dest_dir 的文件名]}，供依赖重下时删旧版。"""
    mapping: dict[str, list[str]] = {}
    if inst is None:
        return mapping
    try:
        from .core import mod_sources
        reg = mod_sources.load(inst)
        present = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
        for fn, meta in reg.items():
            if fn in present:
                mapping.setdefault(str(meta.get("project_id") or ""), []).append(fn)
    except Exception:  # noqa: BLE001 - 判定失败按无旧版处理
        pass
    return mapping


def _cf_download_one(pid: str, fid, dest_dir: str, callback, manifest_out,
                     existing_by_pid: dict, sha1: str = "") -> str:
    """下载一个 CF 文件；下载前删掉同 mod 的旧版本 jar，避免双 jar 共存崩游戏。"""
    for fn in existing_by_pid.get(str(pid), []):
        p = os.path.join(dest_dir, fn)
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    key = _curseforge_key()
    if key and fid:
        path = download_curseforge_file(str(pid), fid, dest_dir,
                                       callback=callback, sha1=sha1)
        if manifest_out is not None and path:
            manifest_out.append({"filename": os.path.basename(path),
                                "project_id": str(pid)})
    else:
        path = _download_cf_keyless(str(pid), fid, dest_dir, callback=callback,
                                   manifest_out=manifest_out)
    return path


def download_cf_with_deps(project_id, file_id, dest_dir, mc_version: str = "",
                          loader: str = "", callback=None, manifest_out=None,
                          with_deps: bool = True, inst=None,
                          primary_sha1: str = "") -> str:
    """下载 CF 模组本体 + 其 required 依赖树（含跨源覆盖）。

    round-220：CF 通道终于和 MR 一样会自动拉前置；依赖重下时删掉同 mod 旧版本
    jar，防止「新旧 FTB Library 共存」继续崩游戏。返回本体文件路径。
    round-221：``primary_sha1`` 把详情页版本条目里的 sha1 透传给本体下载，
    修复 round-220 重构后「官方 keyed 通道本体不再校验 sha1」的回归。
    """
    os.makedirs(dest_dir, exist_ok=True)
    existing_by_pid = _cf_existing_pid_map(inst, dest_dir) if inst else {}
    primary = _cf_download_one(str(project_id), file_id, dest_dir, callback,
                               manifest_out, existing_by_pid,
                               sha1=primary_sha1)
    if not with_deps:
        return primary
    for d in resolve_cf_dependencies(str(project_id), str(file_id),
                                     mc_version, loader):
        _cf_download_one(d["project_id"], d["file_id"], dest_dir, callback,
                         manifest_out, existing_by_pid, sha1=d.get("sha1", ""))
    return primary


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
        # ☠ round-191：这里原本把源语言**写死成 en**（只考虑「译成中文」）。
        # 一旦要中译英（搜索关键词兜底），langpair 就变成 en|en，MyMemory 直接
        # 回 "PLEASE SELECT TWO DISTINCT LANGUAGES"。
        _src = "zh-CN" if has_cjk(chunk) else "en"
        _dst = lang
        if _src == _dst:
            _src = "en" if _dst != "en" else "zh-CN"
        r = requests.get(
            _TRANSLATE_FALLBACK,
            params={"q": chunk, "langpair": f"{_src}|{_dst}"},
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

# round-199：Modrinth 搜索命中里 `categories` 混着加载器与主题标签，只认这些。
_STORE_LOADER_TAGS = {
    "fabric", "forge", "quilt", "neoforge", "liteloader", "rift",
}

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


# round-207：相关性池已废弃。CF 服务端排序可用（同一镜像对照实验：
# 不带排序 sodium 不在前 20，sortField=1&desc 直接排第 1），
# 首屏改成一次 pageSize=20 请求，不再拉 3×50 条回本地重排。


def _cf_search_zh(base: str, headers: dict, query: str, category: str,
                  limit: int, offset: int) -> list[dict]:
    """CF 源的中文搜索（round-192）。

    CF 的 ``searchFilter`` 只认英文/拼音 slug，中文必须转换：

    1. **本地名库**反查 slug（精确 > 前缀 > 包含），逐个试（原来只试第一个，
       名库命中多个时白白丢掉后面的）；
    2. 名库没有 → **翻成英文**再按关键词搜（与 Modrinth 源同一套兜底，
       见 :func:`search_mods_zh`）。
    """
    slugs = _lookup_cn_slugs(query)
    hits: list[dict] = []
    seen: set[str] = set()
    for slug in slugs[:6]:
        params = {
            "gameId": CURSEFORGE_GAME_ID,
            "classId": CURSEFORGE_CLASS_OF.get(category, CURSEFORGE_MOD_CLASS),
            "slug": slug,
            "pageSize": limit,
            "index": offset,
            "sortField": 1,
            "sortOrder": "desc",
        }
        try:
            r = requests.get(
                f"{base}/mods/search", params=params, headers=headers,
                timeout=_SEARCH_TIMEOUT, proxies=_proxies())
            r.raise_for_status()
            data = r.json().get("data", [])
        except requests.RequestException:
            continue
        for m in data:
            row = _cf_map_row(m)
            pid = row.get("project_id", "")
            if pid and pid not in seen:
                seen.add(pid)
                hits.append(row)
        if hits:
            break
    if hits:
        return hits
    # 名库没命中 → 翻译兜底
    try:
        en = translate_text(query, "en")
    except Exception:  # noqa: BLE001 - 翻译挂了就当没有
        en = ""
    if not en or has_cjk(en):
        return []
    params = {
        "gameId": CURSEFORGE_GAME_ID,
        "classId": CURSEFORGE_CLASS_OF.get(category, CURSEFORGE_MOD_CLASS),
        "searchFilter": en,
        "pageSize": limit,
        "index": offset,
        "sortField": 1,
        "sortOrder": "desc",
    }
    try:
        r = requests.get(
            f"{base}/mods/search", params=params, headers=headers,
            timeout=_REQUEST_TIMEOUT, proxies=_proxies())
        r.raise_for_status()
        data = r.json().get("data", [])
    except requests.RequestException as e:
        raise NetError(f"无法搜索 CurseForge：{e}") from e
    return [_cf_map_row(m) for m in data]


def _cf_map_row(m: dict) -> dict:
    """CF API 行 → 统一 hit 形状（与 search_mods 对齐）。"""
    _logo = m.get("logo") or {}
    # ☠ round-191 修：原规则是「URL 里带 /avatars/ 就当无图标」，本意是滤掉
    # 作者头像 GIF 动图（实测 18.8 MB / 4.2 MB）—— 但 **CF 的项目 logo 本身就在**
    # media.forgecdn.net/avatars/<modId>/<fileId>/xxx.png ！一刀切的结果是
    # **CF 源一个图标都出不来**，全部退回首字母占位（用户报「好多图标加载不出来」）。
    # 正确的区分：作者头像是 authors[].avatarUrl（jtvnw / googleusercontent），
    # 与 logo 无关；logo 里只有动图（.gif）需要丢。
    # 并且优先用 thumbnailUrl（256×256 小图）：卡片只显示 48px，原图动辄
    # 300+ KB（实测 grassier-grass 364 KB），小图更快也不占下载槽。
    logo = _logo.get("thumbnailUrl") or _logo.get("url", "")
    _low = str(logo).lower().split("?", 1)[0]
    if _low.endswith(".gif"):
        # 动图：退到 thumbnailUrl（静态小图），没有就当无图标
        thumb = str(_logo.get("thumbnailUrl") or "")
        logo = "" if thumb.lower().endswith(".gif") else thumb
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


def _cf_page(base: str, headers: dict, query: str, category: str,
             limit: int, offset: int) -> list[dict]:
    """CF 关键词搜索：一次请求，排序交给服务端（round-207）。

    round-141 曾判定「sortField 不起作用」，于是拉 3×50 页共 150 条回本地
    分级重排（4 个并发请求 + 一个非 daemon 线程池）。2026-11-07 对同一
    MCIM 镜像做对照实验，结论已过期：

        不带排序                  → sodium 不在前 20，top4 全是不相关项目
        sortField=1&sortOrder=desc → sodium 排第 1

    CurseForge 官方 API 文档同样原生支持 ``sortField`` / ``sortOrder`` /
    ``pageSize`` / ``index``。与主流启动器一致：一次 pageSize=limit 请求，
    服务端排好直接用；深翻页也走服务端 index，不再本地切片。
    """
    params = {
        "gameId": CURSEFORGE_GAME_ID,
        "classId": CURSEFORGE_CLASS_OF.get(category, CURSEFORGE_MOD_CLASS),
        "searchFilter": query,
        "pageSize": limit,
        "index": offset,
        "sortField": 1,
        "sortOrder": "desc",
    }
    r = requests.get(
        f"{base}/mods/search", params=params, headers=headers,
        timeout=_SEARCH_TIMEOUT, proxies=_proxies())
    r.raise_for_status()
    return [_cf_map_row(m) for m in r.json().get("data", [])]


def search_curseforge(query: str = "", offset: int = 0, limit: int = 20,
                      category: str = "mod") -> list[dict]:
    """Search CurseForge mods — official API with a key, MCIM mirror without.

    round-140：无 key 且免 key 通道开启时改走 MCIM 公益镜像（同 API 契约、
    免 x-api-key），关键词 / 中文名库反查 / 分页语义与官方路径一致。
    round-140 修：``category`` → CF classId，分类胶囊在 CF 源下生效
    （此前写死模组类，搜整合包返回的是模组）。
    round-207：废弃 ``_cf_pool`` 相关性池，统一走 ``_cf_page`` 一次请求 +
    服务端 ``sortField=1`` 排序分页（实测该参数有效，round-141 记下的
    「sortField 不起作用」结论已过期）。
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
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    # round-128：CF 的 searchFilter 不认中文 → 名库反查 slug 精确查询；
    # 其余关键词一律单次服务端排序分页（round-207 废弃相关性池）。
    try:
        if has_cjk(query):
            hits = _cf_search_zh(base, headers, query, category, limit, offset)
        else:
            hits = _cf_page(base, headers, query, category, limit, offset)
    except requests.RequestException as e:
        raise NetError(f"无法搜索 CurseForge：{e}") from e
    _store(cache_key, hits)
    return hits


_SEARCH_BUDGET = _SEARCH_TIMEOUT
_SEARCH_LABELS = {"mr": "Modrinth", "cf": "CurseForge"}


def search_all(query: str = "", offset: int = 0, limit: int = 20,
               category: str = "mod", meta: dict | None = None,
               on_source=None) -> list[dict]:
    """「全部」源（round-140 用户要求）：Modrinth + CurseForge 并行搜索合并返回。

    两源各自走自己的缓存/分页；一边失败不拖死另一边（只有两边都失败且
    结果为空才 raise）。命中 dict 自带 ``source`` 字段，卡片/详情/下载
    据此分流。

    round-206：改用 **daemon 线程** + 严格总预算。旧 round-205 实现用
    ``ThreadPoolExecutor``，它的 worker 是**非 daemon** 线程，Python 退出时
    ``threading._shutdown()`` 会无条件 join —— 慢源最坏把「关启动器」拖住
    15s，与「搜索 8s 预算」自相矛盾。daemon 线程不参与退出 join。
    逐个 ``join`` 时用单调时钟扣剩余预算，保证两个源合计不超过 8s。

    ``meta`` 是可选出参，写入 ``partial`` / ``timed_out`` / ``errors`` /
    ``budget``，UI 据此提示「某源超时，只显示部分结果」，避免玩家误判
    「这个源没有这个资源」。

    round-207：``on_source(label, hits)`` 是可选的**按源回调**。每个源一
    返回就立刻调用（不等另一源、也不等 8s 预算），UI 用 Qt 信号把它排队
    到主线程做首屏渲染 —— 快源约 1.2s 就能出结果。回调在 daemon 线程里
    执行；即使本函数已因预算超时返回，迟到的慢源仍会回调一次，UI 增量
    补卡，不再把慢源结果静默丢弃。
    """
    import threading
    import time

    box: dict[str, list[dict] | None] = {"mr": None, "cf": None}
    errs: list[Exception] = []

    def _run(key, fn):
        try:
            hits = fn()
            box[key] = hits
            if on_source is not None:
                try:
                    on_source(_SEARCH_LABELS[key], hits or [])
                except Exception:  # noqa: BLE001 - 回调失败不影响数据
                    pass
        except Exception as e:  # noqa: BLE001 - 单源失败不拖死合并视图
            errs.append(e)

    def _cf():
        if not (curseforge_available() or curseforge_keyless_enabled()):
            return None
        return search_curseforge(query, offset, limit, category)

    jobs = (
        ("mr", lambda: search_mods(query, offset, limit, project_type=category)),
        ("cf", _cf),
    )
    threads = []
    for key, fn in jobs:
        th = threading.Thread(target=_run, args=(key, fn), daemon=True,
                              name="ac-search-%s" % key)
        th.start()
        threads.append((key, th))
    deadline = time.monotonic() + _SEARCH_BUDGET
    for _, th in threads:
        th.join(max(0.0, deadline - time.monotonic()))
    timed_out = [_SEARCH_LABELS[key] for key, th in threads if th.is_alive()]
    if meta is not None:
        meta["partial"] = bool(timed_out)
        meta["timed_out"] = timed_out
        meta["errors"] = [str(e) for e in errs]
        meta["budget"] = _SEARCH_BUDGET
    mr = box["mr"] or []
    cf = box["cf"] or []
    if not mr and not cf and errs:
        raise NetError(str(errs[0]))
    return _dedupe_two_sources(mr, cf)


def _norm_title(s: str) -> str:
    """标题归一化（用于跨源判重）：小写 + 去非字母数字。"""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _dedupe_two_sources(mr: list[dict], cf: list[dict]) -> list[dict]:
    """合并两源并去重（round-195）。

    原来直接把两边相加 → 同一个 mod（JEI、Sodium…）在 Modrinth 和 CF 都有，
    「全部」源会连着出现**两张几乎一样的卡**，玩家会以为出 bug。

    规则：按 slug 相同、标题归一化相同判为同一个项目 → 保留 **Modrinth** 那张
    （CF 的 project_id 与 Modrinth 的不是同一套 id，下载分流按 source 走，
    保留哪边都不会串）；被吞掉的那张在卡上标「另一源也有」。
    """
    out = list(mr)
    seen_keys: set[str] = set()
    for h in out:
        for key in (str(h.get("slug", "")).lower(),
                    _norm_title(h.get("title", ""))):
            if key:
                seen_keys.add(key)
    for h in cf:
        keys = [str(h.get("slug", "")).lower(), _norm_title(h.get("title", ""))]
        keys = [k for k in keys if k]
        if keys and any(k in seen_keys for k in keys):
            continue
        for k in keys:
            seen_keys.add(k)
        out.append(h)
    return out


def download_curseforge_mod(project_id: str, dest_dir: str,
                            file_id: int | str | None = None,
                            callback=None, mc_version: str = "",
                            loader: str = "",
                            manifest_out: list | None = None) -> str:
    """Download a CurseForge mod file into dest_dir.

    round-111：新增 ``callback``（mll 风格，ProgressWorker 注入）→ 进度/速度。
    round-142（CF 整合包一键安装）：``file_id`` 支持按 manifest 指定的文件
    版本精确下载；无 key 时不再直接报错，改走 cfwidget→forgecdn 免 key 通道。

    round-178：``file_id`` 为空（资源中心卡片直接下载）时必须带实例
    ``mc_version`` / ``loader`` 过滤候选文件，**不能取最新一条**——那会给
    1.20.1 的实例装上只支持 1.21 的 jar。整合包 manifest 指定 file_id 时
    是精确版本，不做过滤。
    """
    key = _curseforge_key()
    if not key:
        if not curseforge_keyless_enabled():
            raise NetError(_t_err(
                "store.cf_no_key",
                default="CurseForge 暂不可用。请到「设置 → 网络 → 第三方服务」"
                        "开启免密钥选项，或填入自己的 CurseForge API Key。"))
        return _download_cf_keyless(project_id, file_id, dest_dir, callback,
                                    mc_version, loader, manifest_out)
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
        dest = os.path.join(dest_dir, _safe_filename(filename))
        path = download_file(url, dest, timeout=120,
                             progress=_cb_progress(callback),
                             expected_sha1=_cf_sha1(f))
        if manifest_out is not None:
            manifest_out.append({"filename": os.path.basename(path),
                                  "project_id": str(project_id)})
        return path
    try:
        r = requests.get(
            f"{CURSEFORGE_API}/mods/{project_id}/files",
            params={"pageSize": 50, "sortField": 2, "sortOrder": "desc"},
            headers={**_HEADERS, "x-api-key": key, "Accept": "application/json"},
            timeout=_REQUEST_TIMEOUT, proxies=_proxies(),
        )
        r.raise_for_status()
        files = r.json().get("data", [])
    except requests.RequestException as e:
        raise NetError(f"无法获取 CurseForge 文件：{e}") from e
    if not files:
        raise NetError("该模组没有可下载的文件")
    files = _cf_filter_files(files, mc_version, loader)
    if not files:
        raise NetError(
            "该模组没有匹配当前游戏版本 / 加载器的文件（已放弃取最新版，"
            "避免装进不兼容的模组）")
    f = files[0]
    url = f.get("downloadUrl", "")
    filename = f.get("fileName", f"{project_id}.jar")
    if not url:
        raise NetError("该模组没有直接下载链接")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, _safe_filename(filename))
    path = download_file(url, dest, timeout=120,
                         progress=_cb_progress(callback),
                         expected_sha1=_cf_sha1(f))
    if manifest_out is not None:
        manifest_out.append({"filename": os.path.basename(path),
                              "project_id": str(project_id)})
    return path


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
    """镜像文件列表（同官方 API 契约、免 key）→ 官方形状行，**分页拉全**。

    round-221：pageSize 从 50 提到 200（镜像实测一次返回全部 183 个文件），
    并由 ``_cf_files_all`` 兜住 >200 文件的项目按 index 继续翻页。缓存 key
    同步升到 ``cffi2:``——否则磁盘里那份旧的 50 条缓存会继续生效，改了白改。
    """
    key = f"cffi2:{project_id}"
    cached = _cached(key)
    if cached is not None:
        return cached
    rows = _cf_files_all(_CF_MIRROR, project_id, _HEADERS,
                         _CF_FILES_PAGE_MIRROR)
    if not rows:
        raise NetError(f"无法获取 CurseForge 文件：{project_id}")
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
                         dest_dir: str, callback=None, mc_version: str = "",
                         loader: str = "",
                         manifest_out: list | None = None) -> str:
    """免 key 下载：镜像拿元数据（1 次）→ forgecdn 直链下载（1 次）。

    round-142 初版每个文件最多要问 4 个地方（精确端点/文件列表/cfwidget/下载），
    用户实测「导入整合包这么久」——现改为：
    * 元数据结果缓存（``cfx:{pid}:{fid}``），重复导入同一包秒回；
    * 精确端点拿到 fileName 即可拼 forgecdn（downloadUrl 为 null 不再往下问）；
    * 文件列表同理：有 id+fileName 直接拼；cfwidget 只在镜像整体故障时才用。
    整合包 manifest 只有 projectID+fileID，必须按文件版本精确下载。
    round-178：指定 fileID 找不到时**不再静默退回最新文件**——整合包装出
    来的模组版本会与作者声明不一致且玩家无感知；改为明确报错。
    """
    meta_key = f"cfx:{project_id}:{file_id or 'latest'}"
    cached = _cached(meta_key)
    url, filename, sha1 = ("", "", "")
    if isinstance(cached, (list, tuple)) and len(cached) >= 2:
        url, filename = cached[0] or "", cached[1] or ""
        if len(cached) >= 3:
            sha1 = cached[2] or ""

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
                    sha1 = _cf_sha1(f)
                elif fname:
                    # downloadUrl 为 null：id+fileName 已足够拼 forgecdn，
                    # 不再往下问文件列表 / cfwidget（省 2 次往返）。
                    url, filename = _forge(file_id, fname), fname
                    sha1 = _cf_sha1(f)
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
            if hit is None and rows and not file_id:
                # 卡片下载（无精确 fileID）→ 按实例版本 / 加载器过滤
                rows = _cf_filter_files(rows, mc_version, loader)
                hit = rows[0] if rows else None
        except NetError:
            hit = None
        if hit:
            fname = hit.get("fileName") or ""
            if _cf_direct_url(hit.get("downloadUrl") or ""):
                url, filename = hit["downloadUrl"], fname
            elif hit.get("id") and fname:
                url, filename = _forge(hit["id"], fname), fname
            sha1 = _cf_sha1(hit)
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
        if hit is None and rows and not file_id:
            rows = _cf_filter_files(rows, mc_version, loader)
            hit = rows[0] if rows else None
        if hit and hit.get("id"):
            filename = hit.get("name") or f"{project_id}.zip"
            url = _forge(hit["id"], filename)
            sha1 = _cf_sha1(hit)
    if not url:
        if file_id:
            raise NetError(
                f"找不到整合包指定的文件 {file_id}（不会退回最新版，"
                f"避免装进与作者声明不一致的模组）")
        raise NetError(_t_err("err.curseforge_no_file",
                              default="该 mod 没有匹配当前版本的可下载文件"))
    if not filename:
        filename = os.path.basename(url.split("?")[0]) or f"{project_id}.zip"
    _store(meta_key, [url, filename, sha1])
    os.makedirs(dest_dir, exist_ok=True)
    path = download_file(
        url, os.path.join(dest_dir, _safe_filename(filename)),
        timeout=300, progress=_cb_progress(callback), expected_sha1=sha1)
    if manifest_out is not None:
        manifest_out.append({"filename": os.path.basename(path),
                              "project_id": str(project_id)})
    return path


# ---- CurseForge 版本列表 / 指定文件下载（round-120）----
# detail dialog used to be Modrinth-only; these normalise CurseForge files into
# the same version-dict shape so one row renderer serves both sources.
_CF_LOADER_NAMES = {
    "forge", "fabric", "quilt", "neoforge", "liteloader", "rift",
}


def _cf_version_entry(entry_id, display, filename, size, date,
                      game_versions, url="", sha1="") -> dict:
    """Map one CurseForge file onto the Modrinth version shape.

    round-221：带上 ``sha1``（从文件元数据的 hashes 取），详情页下载本体时
    要用它做完整性校验。round-220 改走 ``download_cf_with_deps`` 后，详情页
    那个 ``f0.get("sha1")`` 一直是死值——版本结构里从没写过这个字段。
    """
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
            "sha1": sha1 or "",
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
    # round-221：key 升级到 cfv2: ——旧缓存的版本条目没有 sha1 字段，
    # 且是「只取第一页 50 条」时切片的结果（offset 越界即空），磁盘缓存
    # 是持久化的，不换 key 会让分页拉全 + sha1 透传的改动白做一半。
    cache_key = f"cfv2:{project_id}:{limit}:{offset}"
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
                          f.get("gameVersions"), f.get("downloadUrl", ""),
                          _cf_sha1(f))
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
    # round-221：同 cfv2:，旧 cfvw: 缓存是旧的 50 条切片且条目无 sha1。
    cache_key = f"cfvw2:{proj}:{limit}:{offset}"
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
                                  f.get("downloadUrl", ""), _cf_sha1(f))
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
                              f.get("versions"), f.get("url") or "",
                              _cf_sha1(f))
            for f in files
        ]
    _store(cache_key, out)
    return out


def download_curseforge_file(project_id: str, file_id, dest_dir: str,
                             filename: str = "", url: str = "",
                             callback=None, sha1: str = "") -> str:
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
    return download_file(link, os.path.join(dest_dir, _safe_filename(name)),
                         timeout=120, progress=_cb_progress(callback),
                         expected_sha1=sha1)


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


def download_cfwidget_file(cf_file: dict, dest_dir: str, callback=None,
                            mc_version: str = "", loader: str = "",
                            manifest_out: list | None = None,
                            project_id: str = "") -> str:
    """下载 cfwidget 解析出的文件（forgecdn 直链，无需 key）。

    round-111：新增 ``callback``（mll 风格，ProgressWorker 注入）→ 进度/速度。
    round-178：带实例版本 / 加载器时先校验候选文件，明确声明不兼容就拒绝，
    不再把「只支持 1.21 的最新 jar」静默装进 1.20.1 实例。
    """
    if (mc_version or loader) and not _cf_filter_files(
            [cf_file], mc_version, loader):
        raise NetError(
            "该文件声明的游戏版本 / 加载器与当前实例不匹配（已放弃下载）")
    fid = cf_file.get("id")
    name = cf_file.get("name", "mod.jar")
    if not fid:
        raise NetError("缺少文件 ID")
    try:
        fid = int(fid)  # cfwidget 有时给字符串，直接 // 会 TypeError
    except (TypeError, ValueError):
        raise NetError(f"无效的文件 ID：{fid!r}") from None
    url = FORGECDN_URL.format(a=fid // 1000, b=fid % 1000, name=name)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, _safe_filename(name))
    path = download_file(url, dest, timeout=120,
                         progress=_cb_progress(callback),
                         expected_sha1=_cf_sha1(cf_file))
    if manifest_out is not None:
        manifest_out.append({"filename": os.path.basename(path),
                              "project_id": str(project_id or "")})
    return path


def download_cfwidget_slug(slug: str, dest_dir: str, callback=None,
                            mc_version: str = "", loader: str = "",
                            manifest_out: list | None = None) -> str:
    """免 key 下载：slug → cfwidget 最新文件 → forgecdn 直链（round-140）。

    供免 key 镜像搜索命中的卡片使用——命中只有 slug / project_id，没有
    官方 download-url 端点可用，走公开直链通道。
    """
    hits = curseforge_link_search(slug)
    candidates = [h.get("_cf_file") for h in (hits or [])
                  if isinstance(h, dict) and h.get("_cf_file")]
    if mc_version or loader:
        candidates = [c for c in candidates
                      if _cf_filter_files([c], mc_version, loader)]
    cf_file = candidates[0] if candidates else None
    if not cf_file:
        raise NetError(_t_err("err.curseforge_no_file",
                              default="该 mod 没有匹配当前版本的可下载文件"))
    return download_cfwidget_file(cf_file, dest_dir, callback=callback,
                                  mc_version="", loader="",
                                  manifest_out=manifest_out,
                                  project_id=str(slug))


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
        # round-191：名库只有一百多条，绝大多数中文词查不到 —— 那就把中文
        # 查询翻成英文再搜一次 Modrinth（它不认中文）。名库命中优先保留，
        # 英文结果按 project_id 去重后接在后面。
        if len(projects) < 3:
            try:
                en = translate_text(query, "en")
            except Exception:  # noqa: BLE001 - 翻译挂了就当没有
                en = ""
            if en and not has_cjk(en):
                try:
                    extra = search_mods(en, 0, limit, project_type)
                except Exception:  # noqa: BLE001
                    extra = []
                seen_ids = {str(p.get("id") or "") for p in projects}
                # 英文结果只有摘要字段，转成和 projects 相同的形状再合并
                for hit in extra:
                    pid = str(hit.get("project_id") or "")
                    if not pid or pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    projects.append({
                        "id": pid,
                        "slug": hit.get("slug", ""),
                        "title": hit.get("title", ""),
                        "description": hit.get("description", ""),
                        "downloads": hit.get("downloads", 0),
                        "icon_url": hit.get("icon_url") or "",
                        "project_type": project_type,
                    })
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


def mcmod_best_entry(names) -> str:
    """按候选词依次找 MC百科精确条目；全不中时返回第一个候选的搜索页。

    round-205：`_open_mcmod` 原来只用 ``cn_short(slug)``（本地名库只有百余条，
    绝大多数 mod 没有中文短名）→ 直接拿英文 slug 去中文站搜，命中率极低，
    玩家体验就是「MC百科基本查不到」。现在调用方按「中文短名 → 中文全名 →
    标题 → slug」给候选，逐个尝试，命中即返回。
    """
    clean: list[str] = []
    for n in (names or []):
        s = str(n or "").strip()
        if s and s not in clean:
            clean.append(s)
    for name in clean:
        url = mcmod_entry_url(name)
        if "/class/" in url:
            return url
    return mcmod_search_url(clean[0] if clean else "")


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
            timeout=_SEARCH_TIMEOUT, proxies=_proxies(),
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
            # round-199：搜索命中自带全部支持版本与加载器（Modrinth 的
            # `versions` 是完整列表），列表页据此画兼容徽章，不用逐卡再查。
            "game_versions": [str(x) for x in (h.get("versions") or [])],
            "loaders": [str(x).lower() for x in (h.get("categories") or [])
                        if str(x).lower() in _STORE_LOADER_TAGS],
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


def download_modpack_to(project_id: str, dest_dir: str, callback=None,
                        version_id: str = "") -> str:
    """Download a Modrinth modpack's primary file (a .mrpack) into dest_dir.

    Returns the local .mrpack path — the caller then installs it as a new
    instance via ``core.install.install_mrpack``.

    round-111：``callback`` 收 mll 风格 dict（``setProgress`` / ``setMax``），
    由 :class:`ProgressWorker` 自动注入。把它桥接到 net_api 的
    ``progress(sofar, total)``，整合包下载从此有字节级进度与实时速度
    （之前走裸 ``Worker``，只有提速没有可观测性）。
    """
    # round-178：默认路径保持「单参调用」不变（老调用点 / mock 都兼容），
    # 只有显式指定版本时才传 version_id。
    filename, url = (get_mod_download(project_id, version_id) if version_id
                     else get_mod_download(project_id))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, _safe_filename(filename))

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

#: Fabric 官方 meta：按 MC 版本列加载器构建（round-186）。
#: 与 ``mll.fabric.get_all_loader_versions()`` 的区别是**带 MC 版本**——
#: 后者返回全历史版本，填进下拉就是「这个版本装不上却列着」。
FABRIC_LOADER_API = "https://meta.fabricmc.net/v2/versions/loader"
QUILT_LOADER_API = "https://meta.quiltmc.org/v3/versions/loader"


def fetch_loader_builds(mc_version: str, loader: str = "fabric") -> list[dict]:
    """拉「该 MC 版本」可用的 Fabric / Quilt 加载器构建。

    返回 ``[{"title", "meta", "stable"}]``；网络失败抛 :class:`NetError`
    （由调用方决定是提示还是退回空列表）。
    """
    base = QUILT_LOADER_API if str(loader).lower() == "quilt" else FABRIC_LOADER_API
    key = "%s_loader:%s" % (str(loader).lower(), mc_version)
    cached = _cached(key)
    if cached is not None:
        return cached
    url = base + "/" + str(mc_version)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT,
                         proxies=_proxies())
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise NetError("Cannot fetch %s loader builds: %s" % (loader, e)) from e
    out = []
    for item in data if isinstance(data, list) else []:
        ld = item.get("loader") or {}
        ver = str(ld.get("version") or "")
        if not ver:
            continue
        out.append({"title": ver, "meta": ver,
                    "stable": bool(ld.get("stable", True))})
    _store(key, out)
    return out
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
