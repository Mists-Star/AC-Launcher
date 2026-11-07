"""BMCLAPI download mirror + download hardening for Mojang-hosted files.

When the user selects the BMCLAPI mirror, we transparently rewrite the Mojang
download hosts to their BMCLAPI equivalents. BMCLAPI mirrors these 1:1, so only
the host changes — the path and query string are preserved byte-for-byte.
Non-Mojang hosts (Modrinth, maven, authlib download, etc.) pass through
untouched, which keeps this patch safe to leave active for the whole app
session.

round-109 下载止血：minecraft-launcher-lib 的每一次下载都走
``requests.session()`` / ``requests.get()``，而且从不传 ``timeout``。一个卡住的
socket 就会让它所属的 ThreadPoolExecutor 线程永久阻塞：``future.result()`` 永不
返回、不报错、无法取消 —— 用户看到的是进度条钉死在某个哈希上「下载卡死」。
所以这里把 mll 三个自行 ``import requests`` 的下载子模块（``_helper`` / ``install``
/ ``runtime``；mrpack / fabric / forge / quilt 都经由 ``_helper.download_file``，
已被传递覆盖）的 ``requests`` 属性替换成 :class:`_RequestsShim`，全部引流到
:class:`MirrorSession`，由其统一提供：

* ``(connect, read)`` 超时 —— 挂住的 socket 必在 30 秒内抛错；
* 每源一次重试，之后回退到原始官方 URL（BMCLAPI → Mojang）；
* 游戏文件两源皆失败时显式抛错，不再让「缺文件」被误报为
  "Installation complete"；
* 协作式取消 —— :func:`install_scope` + ``abort()``，供「取消下载并启动」用。

``_MIRROR_ON`` 在**请求时**决定是否重写 Mojang 主机，因此「打补丁」与「走镜像」
解耦：官方源用户同样拿到超时 / 重试 / 取消，只是不做主机重写。

round-110 三件事：

* A 速度可见 —— mll 的回调只有「文件计数」，拿不到字节数，所以速度只能在传输
  层按响应字节记账（:class:`SpeedMeter` + :class:`_CountingRaw`），再按滑动时间窗
  估出 B/s；
* B 镜像健康 —— 某个 Mojang 主机在 BMCLAPI 上返回 403（当前 ``libraries`` 路径
  就是被 Cloudflare 拦的）时，把该主机记进本次安装的失效集合，后续请求直接走官方
  源，不再逐文件白试一遍再回退；
* C 诊断日志 —— 每请求的 status / 耗时 / 声明字节数，默认关闭（:func:`set_diag`）。

round-111 大文件分片并行：把 mll 的 ``download_file`` 包一层，让**客户端 jar**
（``versions/<id>/<id>.jar``，单次安装里最大的单文件）走我们的
:func:`net_api.parallel_download_file`。刻意**不**对所有文件生效 ——
一次完整安装有数百到上千次 ``download_file`` 调用，无差别探测大小会是净回归；
只认这一个确定是大文件的目标，其余零开销原样转发。见
:func:`_is_big_target` / :func:`_try_parallel_mll`。

round-174 源健康与超时策略：把「bmclapi 总是等待响应」按**源级**止血 ——
镜像用更短的超时（5/15s）且失败不重试；连续 2 次连接类失败 / 5xx 即冷却
90 秒，期间所有请求直接走官方；响应明显变慢（EWMA ≥ 4s）时官方优先。
所有状态都在 :class:`SourceHealth` 里，进程内共享、重启归零。
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import os
import socket
import subprocess
import threading
import time
import weakref
from collections import deque

import requests

from .transfer import (MirrorRule, OfficialProvider, PrefixMirrorProvider,
                       SourceChain, SourceTrace, MIRROR_FIRST, OFFICIAL_ONLY)

_BMCL_BASE = "https://bmclapi2.bangbang93.com"

# round-113 路径感知重写表：(完整 URL 前缀, 替换前缀)。
# 前缀匹配后必须紧跟 "/" 或 URL 结束，避免把同前缀的其它主机误伤。
#
# 依据实测（2026-10-22，本机 12 核）：
#   piston-meta/piston-data 的真实路径是 /v1/packages/<sha>/<id>.json 与
#   /v1/objects/<sha>/client.jar（不再是旧的 /mc/game/<id>.json），
#   BMCLAPI 同构路径全部 200/206 —— 之前漏掉 piston-meta，镜像模式下
#   版本 json 与 assetIndex 一直直连官方。
#   libraries.minecraft.net 按 PCL2 的映射走 /maven（实测与 /libraries
#   命中同一批文件，字节数一致）。
#   loader 的 maven/meta 端点 BMCLAPI 只镜像了一部分，逐条探测结论：
#     /fabric-meta      → meta.fabricmc.net     ✓
#     /quilt-meta       → meta.quiltmc.org      ✓
#     /maven            → maven.minecraftforge.net ✓（md + installer）
#     /maven            → maven.fabricmc.net    ✓（loader jar；installer 404 会回退官方）
#     /maven            → maven.quiltmc.org/repository/release ✓（同上游路径）
#     /maven/net/neoforged → maven.neoforged.net/releases/net/neoforged ✓
#   未被镜像的（neoforge 的 /api/maven/versions JSON）保持原样走官方。
_MIRROR_RULES: list[tuple[str, str]] = [
    ("https://launchermeta.mojang.com", _BMCL_BASE),
    ("https://launcher.mojang.com", _BMCL_BASE),
    ("https://piston-meta.mojang.com", _BMCL_BASE),
    ("https://piston-data.mojang.com", _BMCL_BASE),
    ("https://libraries.minecraft.net", _BMCL_BASE + "/maven"),
    ("https://resources.download.minecraft.net", _BMCL_BASE + "/assets"),
    ("https://meta.fabricmc.net", _BMCL_BASE + "/fabric-meta"),
    ("https://meta.quiltmc.org", _BMCL_BASE + "/quilt-meta"),
    ("https://maven.minecraftforge.net", _BMCL_BASE + "/maven"),
    ("https://maven.fabricmc.net", _BMCL_BASE + "/maven"),
    ("https://maven.quiltmc.org/repository/release", _BMCL_BASE + "/maven"),
    ("https://maven.neoforged.net/releases/net/neoforged", _BMCL_BASE + "/maven/net/neoforged"),
]

# 失效闩锁按主机记账（round-110 B）：从重写表派生。
_MIRROR_HOSTS: tuple[str, ...] = tuple(dict.fromkeys(
    p.split("/")[2] for p, _ in _MIRROR_RULES
))

# Manifest URLs consumed by our own net_api.fetch_versions().
MANIFEST_OFFICIAL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
MANIFEST_BMCLAPI = _BMCL_BASE + "/mc/game/version_manifest_v2.json"

# round-109：(connect, read) 超时。read 是「相邻两次读之间的间隔」上限，而不是
# 整个响应的总时长 —— 持续有数据到达的慢速下载不会被误杀，只有真正挂死的
# socket 才会在 30 秒内抛 ReadTimeout。
_SEND_TIMEOUT = (10, 30)
# 每个源最多重试 1 次（仅针对超时 / 连接类异常）。HTTP ≥400 属于本源给出的确定
# 答案，直接换源，不做无谓重试。
_RETRIES = 1

# 是否把 Mojang 主机重写为 BMCLAPI。由 install_instance / install_mrpack 按用户
# 的 download_mirror 设置在每个安装开始前设定。
# round-203：这是**进程级默认值**；每次安装在自己的 InstallContext 里存一份，
# 并行安装不再互相覆盖（详见 InstallContext 的说明）。
_MIRROR_ON = False

# 「未设置」哨兵：InstallContext.proxy 用它区分「没调用过 set_proxy」。
_UNSET = object()

# round-113：mll 库/资源下载的并发上限与 HTTP 连接池大小。
#
# 实测（本机 12 核，官方源，80 个真实资源对象共 41.9MB）：
#   workers=8  → 2.67MB/s     workers=32 → 7.71MB/s
#   workers=16 → 6.03MB/s     workers=48 → 8.35MB/s（最快）
#   workers=64 → 7.27MB/s     workers=96 → 6.76MB/s（开始回落）
# 48 是拐点，再往上延迟（p50 1779ms → 1934ms → 2453ms）反而拖慢整体。
# 16 是 mll 里 ThreadPoolExecutor 的默认值（min(32, cpu+4)），我们一直在吃这个亏。
_MAX_WORKERS = 48
# 连接池要能同时容纳全部并发，否则多余的请求每次都要重新握手。
_POOL_SIZE = 64

# round-155：来源链 —— 把上面的重写表变成可展开的数据规则。
# 镜像开启时保持既有行为：镜像优先（BMCLAPI → 官方）；关闭时只有官方候选。
_TRANSFER_RULES = [MirrorRule(official, mirror)
                   for official, mirror in _MIRROR_RULES]
_CHAIN = SourceChain(
    [OfficialProvider(),
     PrefixMirrorProvider(_TRANSFER_RULES, name="bmclapi",
                          max_concurrency=_MAX_WORKERS)],
    prefer=MIRROR_FIRST,
)

# ── round-174：源健康 + 超时策略 ─────────────────────────────────────────────
# 用户实测「bmclapi 总是等待响应」：镜像挂住时，每个文件都要按官方源的口径等
# 连接 10s + 读 30s，还在同一源上再重试一次（≈80s/文件）；就算最后回退官方，
# 几百个文件累加就是「一直在等」。三项改动：
#
# 1. 镜像用更短的超时（连接 5s / 相邻读 15s）——它是「加速手段」，不值得为它
#    长时间等待；官方源保持 (10, 30)（跨境连接本来就慢）。
# 2. 镜像失败不重试：超时 / 连接错误直接换官方，省掉一次白等。
# 3. 连续 2 次连接类失败（超时 / 连接被重置 / 5xx）判定镜像不健康，冷却 90 秒
#    内所有请求直接走官方；冷却结束后重新探测（再给它 2 次机会）。
#    404 不算：可能只是某个文件镜像没同步，逐文件回退即可。
# 另外镜像响应变慢（EWMA ≥ 4s、样本 ≥ 5）时，把官方排到前面，镜像只作回退。
_MIRROR_TIMEOUT = (5, 15)
_OFFICIAL_TIMEOUT = _SEND_TIMEOUT
_MIRROR_FAIL_LIMIT = 2
_MIRROR_COOLDOWN = 90.0
_SLOW_MS = 4000.0
_SLOW_SAMPLES = 5


class SourceHealth:
    """进程内的来源健康表：连续失败 → 冷却；成功 → 记录响应耗时。

    mll 一次安装会发几百到上千个请求，全部并发 —— 这里所有方法都必须持锁，
    且只在内存里记账（不落盘），重启启动器即重新探测。
    """

    __slots__ = ("_lock", "_fails", "_down_until", "_ewma", "_samples",
                 "_reason", "_fail_limit", "_cooldown", "_slow_ms",
                 "_slow_samples")

    def __init__(self, *, fail_limit: int = _MIRROR_FAIL_LIMIT,
                 cooldown: float = _MIRROR_COOLDOWN,
                 slow_ms: float = _SLOW_MS,
                 slow_samples: int = _SLOW_SAMPLES) -> None:
        self._lock = threading.Lock()
        self._fails: dict[str, int] = {}
        self._down_until: dict[str, float] = {}
        self._ewma: dict[str, float] = {}
        self._samples: dict[str, int] = {}
        self._reason: dict[str, str] = {}
        self._fail_limit = max(1, int(fail_limit))
        self._cooldown = float(cooldown)
        self._slow_ms = float(slow_ms)
        self._slow_samples = max(1, int(slow_samples))

    def is_down(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            until = self._down_until.get(key)
            if until is None:
                return False
            if now >= until:
                self._down_until.pop(key, None)
                self._fails.pop(key, None)
                return False
            return True

    def is_slow(self, key: str) -> bool:
        with self._lock:
            return (self._samples.get(key, 0) >= self._slow_samples
                    and self._ewma.get(key, 0.0) >= self._slow_ms)

    def note_ok(self, key: str, elapsed: float) -> None:
        """一次成功响应：清零连败，并把「到响应头」的耗时并入 EWMA。"""
        ms = max(0.0, elapsed) * 1000.0
        with self._lock:
            self._fails.pop(key, None)
            self._down_until.pop(key, None)
            self._reason.pop(key, None)
            old = self._ewma.get(key)
            self._ewma[key] = ms if old is None else (old * 0.7 + ms * 0.3)
            self._samples[key] = min(10000, self._samples.get(key, 0) + 1)

    def note_fail(self, key: str, reason: str = "") -> None:
        """一次连接类失败（超时 / 连接错误 / 5xx）：累计到阈值即进入冷却。"""
        with self._lock:
            n = self._fails.get(key, 0) + 1
            self._fails[key] = n
            self._reason[key] = reason or "connection error"
            if n >= self._fail_limit:
                self._down_until[key] = time.monotonic() + self._cooldown
                self._fails[key] = 0
                self._samples.pop(key, None)   # 恢复后重新积累速度样本

    def note_rejected(self, key: str, reason: str = "rejected") -> None:
        """被明确拒绝（401/403/406）：立刻进入冷却，不等累计。"""
        with self._lock:
            self._down_until[key] = time.monotonic() + self._cooldown
            self._fails[key] = 0
            self._reason[key] = reason

    def reason(self, key: str) -> str:
        with self._lock:
            return self._reason.get(key, "")

    def snapshot(self) -> dict[str, dict]:
        """诊断用快照：``{source: {down, fails, ewma_ms, samples, reason}}``。"""
        now = time.monotonic()
        with self._lock:
            keys = set(self._fails) | set(self._down_until) | set(self._ewma)
            out: dict[str, dict] = {}
            for k in keys:
                until = self._down_until.get(k)
                out[k] = {
                    "down": bool(until is not None and now < until),
                    "fails": self._fails.get(k, 0),
                    "ewma_ms": round(self._ewma.get(k, 0.0), 1),
                    "samples": self._samples.get(k, 0),
                    "reason": self._reason.get(k, ""),
                }
            return out

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()
            self._down_until.clear()
            self._ewma.clear()
            self._samples.clear()
            self._reason.clear()


_HEALTH = SourceHealth()


def source_health() -> SourceHealth:
    """进程级来源健康表（测试可 :func:`reset_source_health` 清空）。"""
    return _HEALTH


def reset_source_health() -> None:
    _HEALTH.reset()


def _source_key(cand) -> str:
    """健康表的键：镜像按来源名（bmclapi），官方固定 official。"""
    return getattr(cand, "source", "") or (
        "mirror" if getattr(cand, "mirrored", False) else "official")


def _timeout_for(cand) -> tuple[float, float]:
    """每个来源自己的 (connect, read) 超时。"""
    return _MIRROR_TIMEOUT if getattr(cand, "mirrored", False) else _OFFICIAL_TIMEOUT


def _retries_for(cand) -> int:
    """镜像失败不重试（直接换官方）；官方保留一次重试。"""
    return 0 if getattr(cand, "mirrored", False) else _RETRIES


def _rank_candidates(cands):
    """按健康表调整候选顺序：丢不健康镜像；慢镜像让位给官方（保留作回退）。

    官方候选永不丢弃 —— 它既是回退目标，也是「镜像全灭」时唯一能用的源。
    """
    if not cands:
        return cands
    kept = [c for c in cands
            if not (getattr(c, "mirrored", False) and _HEALTH.is_down(_source_key(c)))]
    if not kept:
        kept = list(cands)
    first = kept[0]
    if getattr(first, "mirrored", False) and _HEALTH.is_slow(_source_key(first)):
        official = [c for c in kept if not getattr(c, "mirrored", False)]
        mirror = [c for c in kept if getattr(c, "mirrored", False)]
        if official:
            return official + mirror
    return kept


# ── round-110 A：字节记账 + 滑动时间窗测速 ──────────────────────────────────
class SpeedMeter:
    """线程安全的字节记账 + 滑动时间窗速度估算。

    mll 用 ThreadPoolExecutor 并发下载，多个线程同时写盘，所以累加与快照都必须
    持锁。速度按窗口内的「字节数 / 实际跨度」计算：窗口外样本丢弃，因此一次挂死
    （长时间没有新字节）会让速度自然归零，而不是靠一个假的时间戳假装在动。
    """

    __slots__ = ("_lock", "_pending", "_pending_since", "_samples", "_total",
                 "_window", "__weakref__")

    def __init__(self, window: float = 5.0) -> None:
        self._lock = threading.Lock()
        self._pending = 0
        self._pending_since = 0.0
        self._samples: deque = deque()      # [(monotonic_ts, bytes)]
        self._total = 0
        self._window = window

    def note(self, nbytes: int) -> None:
        """记入刚收到的字节数（可由任意线程调用）。"""
        if nbytes <= 0:
            return
        with self._lock:
            if not self._pending:
                # 采样点的时间戳取「本批字节的起点」而不是 flush 的时刻，否则单批
                # 数据算出来的跨度为 0，速度会永远是 0。
                self._pending_since = time.monotonic()
            self._pending += nbytes
            self._total += nbytes

    def snapshot(self) -> tuple[float, int]:
        """返回 ``(bytes_per_second, total_bytes)``。

        ``bytes_per_second`` 在样本跨度太短（<0.75s）或窗口内无样本时为 0.0 ——
        宁可不显示速度，也不显示一个虚高的数字。
        """
        now = time.monotonic()
        with self._lock:
            if self._pending:
                self._samples.append((self._pending_since, self._pending))
                self._pending = 0
            total = self._total
            cutoff = now - self._window
            while self._samples and self._samples[0][0] < cutoff:
                self._samples.popleft()
            if not self._samples:
                return 0.0, total
            span = now - self._samples[0][0]
            got = sum(n for _, n in self._samples)
        if span < 0.75:
            return 0.0, total
        return got / span, total


def active_meter():
    """当前线程所属安装的速度计量器（无安装上下文时为 None）。

    分片下载把字节统计放在 ThreadPoolExecutor 的工作线程里，那些线程没有安装
    上下文，所以调用方要在**自己线程**先取到计量器再传进去。
    """
    ctx = active_context()
    return getattr(ctx, "meter", None) if ctx is not None else None


# ── round-110 C：每请求诊断日志（默认关，绝不打断下载）────────────────────
_DIAG = False
_DIAG_LOCK = threading.Lock()


def set_diag(enabled: bool) -> None:
    """开关「每请求 status / 耗时 / 声明字节数」诊断日志。"""
    global _DIAG
    _DIAG = bool(enabled)


def _diag_log(line: str) -> None:
    with _DIAG_LOCK:
        try:
            from ..paths import get_data_dir
            log_dir = os.path.join(get_data_dir(), "logs")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "download.log"), "a",
                      encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:  # noqa: BLE001 - 诊断日志任何失败都不影响下载
            pass


def set_mirror(enabled: bool) -> None:
    """Enable/disable the BMCLAPI host rewrite for subsequently sent requests.

    round-203：安装线程内只改本次安装自己的 ``ctx.mirror_on``；该线程外（设置页
    预览、单文件下载等）才落到进程级默认值。这样两个安装并行时，谁也不会把
    对方的镜像开关改掉。
    """
    global _MIRROR_ON
    ctx = active_context()
    if ctx is not None:
        ctx.mirror_on = bool(enabled)
        return
    _MIRROR_ON = bool(enabled)


def _mirror_on_for(ctx=None) -> bool:
    """当前请求该不该走镜像：本次安装的设置优先，否则用进程级默认值。"""
    if ctx is None:
        ctx = active_context()
    val = getattr(ctx, "mirror_on", None) if ctx is not None else None
    return _MIRROR_ON if val is None else bool(val)


class InstallCancelled(Exception):
    """用户主动取消安装。

    和网络失败区分开：取消不该触发换源重试（:func:`install_instance` 的
    ``_retry_with_mirror``），也不该被报成「启动失败」。
    """


class InstallContext:
    """Cooperative cancellation token for one install run.

    Sessions constructed while the token is active keep a reference to it, so
    ``abort()`` makes every in-flight download raise ``RequestException``
    instead of continuing to write into the game directory. Used by the
    "cancel download and launch" escape hatch: mll spawns its worker threads
    from the same thread that builds the session, so one abort flag reaches
    every concurrent download of that install.

    round-110：同时挂载该次安装的 :class:`SpeedMeter`（A）与「镜像失效主机」集合
    （B）—— 某主机在镜像上返回 403 时记入，后续该主机的请求直接走官方源。

    round-172：取消要能**真正**停下正在跑的下载 —— 之前的 ``abort()`` 只在
    「下一个请求发出前」生效，已经在 ``copyfileobj`` 里读流的文件会一直读到
    结束（BMCLAPI 挂住时更久，read timeout 最长 30 秒）。现在每个响应都登记
    在案，``abort()`` 直接 ``shutdown`` 其底层 socket，阻塞中的读立刻抛错；
    由 :func:`run_cancellable` 启动的安装器子进程一并结束。

    round-203：``mirror_on`` / ``proxy`` 从进程级全局搬到这里 —— 两个安装
    （比如「启动前补全」和商店下载）并行时，后启动的那个会把前一个的镜像 /
    代理设置覆盖掉，表现为「下载互相占用、有的走镜像有的走官方」。现在每次
    安装用自己的设置，互不影响；未设置时回落到进程级默认值。
    """

    __slots__ = ("_ev", "meter", "mirror_dead", "trace", "_resps", "_procs",
                 "_lock", "mirror_on", "proxy")

    def __init__(self) -> None:
        self._ev = threading.Event()
        self.meter = SpeedMeter()
        self.mirror_dead: set = set()
        # round-155：本次安装的逐源失败记录（UI / 任务历史可读）。
        self.trace = SourceTrace()
        # 在途响应 / 子进程（弱引用，安装结束自动释放）
        self._resps: list = []
        self._procs: list = []
        self._lock = threading.Lock()
        # round-203：未设置 = None，请求时回落到全局默认值。
        self.mirror_on = None
        self.proxy = _UNSET

    def abort(self) -> None:
        self._ev.set()
        with self._lock:
            resps = list(self._resps)
            self._resps.clear()
            procs = list(self._procs)
            self._procs.clear()
        for ref in resps:
            resp = ref() if callable(ref) else None
            if resp is not None:
                shutdown_response(resp)
        for proc in procs:
            kill_process_tree(proc)

    @property
    def aborted(self) -> bool:
        return self._ev.is_set()

    def track_response(self, resp) -> None:
        """登记一个正在读流的响应，供 ``abort()`` 立刻掐断。"""
        try:
            ref = weakref.ref(resp)
        except TypeError:  # 不支持弱引用（极少见）→ 放弃登记，不影响下载
            return
        with self._lock:
            if len(self._resps) > 2048:  # 超长安装：清掉已死引用
                self._resps = [r for r in self._resps if r() is not None]
            self._resps.append(ref)

    def track_proc(self, proc) -> None:
        with self._lock:
            self._procs.append(proc)

    def untrack_proc(self, proc) -> None:
        with self._lock:
            self._procs = [p for p in self._procs if p is not proc]


def _response_socket(resp):
    """从 requests 响应里挖出底层 socket（urllib3 v1/v2 都覆盖）。"""
    obj = getattr(resp, "raw", None)
    if isinstance(obj, _CountingRaw):
        obj = object.__getattribute__(obj, "_raw")
    for _ in range(6):
        if obj is None:
            return None
        sock = getattr(obj, "_sock", None)
        if isinstance(sock, socket.socket):
            return sock
        conn = getattr(obj, "_connection", None)
        if conn is not None:
            sock = getattr(conn, "sock", None)
            if isinstance(sock, socket.socket):
                return sock
        nxt = getattr(obj, "_fp", None) or getattr(obj, "fp", None)
        if nxt is None or nxt is obj:
            return None
        obj = nxt
    return None


def shutdown_response(resp) -> None:
    """掐断一个响应：shutdown socket + close，让阻塞中的读立刻抛错。"""
    sock = _response_socket(resp)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    try:
        resp.close()
    except Exception:  # noqa: BLE001 - 关不掉也不影响取消
        pass


def kill_process_tree(proc) -> None:
    """结束安装器子进程（Windows 连子进程一起杀）。"""
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
    except Exception:  # noqa: BLE001
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10,
                           creationflags=getattr(subprocess,
                                                  "CREATE_NO_WINDOW", 0))
        else:
            proc.kill()
    except Exception:  # noqa: BLE001 - 杀不掉就让进程自己结束
        pass


def abort_requested() -> bool:
    """当前安装是否已被用户取消（无安装上下文时恒为 False）。"""
    ctx = active_context()
    return ctx is not None and ctx.aborted


def run_cancellable(command, *, cwd=None, timeout=None, check=False, **kwargs):
    """跑一个安装器子进程，取消时立刻结束它（含子进程树）。

    替代 ``subprocess.run``：Forge / NeoForge / Fabric / Quilt 的安装器 jar
    自己会下载几百 MB 的库，取消启动时必须能停下来。返回
    :class:`subprocess.CompletedProcess`，语义与 ``subprocess.run`` 对齐
    （``capture_output`` / ``text`` / ``check`` / ``timeout``）。
    """
    if abort_requested():
        raise InstallCancelled("install cancelled by user")
    capture = kwargs.pop("capture_output", False)
    if capture:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    allowed = ("stdout", "stderr", "stdin", "startupinfo", "env", "text",
               "encoding", "errors", "shell")
    popen_kwargs = {k: v for k, v in kwargs.items() if k in allowed}
    # round-182：安装器（Forge / NeoForge / Cleanroom / OptiFine 的 jar）都是
    # 控制台程序。启动器是窗口应用，Popen 不带 CREATE_NO_WINDOW 就会弹出一个
    # 全黑的 cmd 窗口（用户实测：「拉起 D 盘 java26 的 cmd 空窗口」）。
    # 我们要的是 stdout/stderr 管道，不需要那个窗口。
    if os.name == "nt":
        popen_kwargs.setdefault(
            "creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    data = kwargs.get("input")
    if data is not None:
        # Popen 没有 input（那是 run() 的糖）：转成本进程 stdin 管道
        popen_kwargs["stdin"] = subprocess.PIPE
    proc = subprocess.Popen(command, cwd=cwd, **popen_kwargs)
    ctx = active_context()
    if ctx is not None:
        ctx.track_proc(proc)
    deadline = time.monotonic() + timeout if timeout else None
    out = err = None
    sent = False
    try:
        while True:
            step = 0.2
            if deadline is not None:
                left = deadline - time.monotonic()
                if left <= 0:
                    kill_process_tree(proc)
                    raise subprocess.TimeoutExpired(command, timeout)
                step = min(step, left)
            try:
                # communicate 只允许第一次带 input（之后再传会 ValueError）
                inp, sent = (data if not sent else None), True
                out, err = proc.communicate(input=inp, timeout=step)
                break
            except subprocess.TimeoutExpired:
                if abort_requested():
                    kill_process_tree(proc)
                    proc.communicate()
                    raise InstallCancelled("install cancelled by user")
    finally:
        if ctx is not None:
            ctx.untrack_proc(proc)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, command, output=out, stderr=err)
    return subprocess.CompletedProcess(command, proc.returncode, out, err)


class _SubprocessShim:
    """把 ``subprocess.run`` 换成可取消版本（供 mll 安装器模块使用）。"""

    __slots__ = ("_real",)

    def __init__(self, real):
        self._real = real

    def run(self, *args, **kwargs):
        check = kwargs.pop("check", False)
        timeout = kwargs.pop("timeout", None)
        return run_cancellable(*args, check=check, timeout=timeout, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


_SCOPE = threading.local()


@contextlib.contextmanager
def install_scope():
    """Mark the calling thread as "inside one install" and yield its token.

    ``ProgressWorker.run`` wraps its blocking call in this so that the sessions
    mll creates on that thread capture the token.
    """
    ctx = InstallContext()
    _SCOPE.ctx = ctx
    try:
        yield ctx
    finally:
        _SCOPE.ctx = None


def active_context():
    """Return the token of the install running on this thread (or None)."""
    return getattr(_SCOPE, "ctx", None)


class MirrorSession(requests.Session):
    """A requests.Session with mirror rewrite, timeouts and cancellation.

    Also honours a process-wide proxy setting (see ``set_proxy``), so a user
    behind a corporate / GFW proxy can route Minecraft downloads through it.

    round-48 B 多源回退：重写后走 BMCLAPI（主源），若该文件在 BMCLAPI 上失败
    （HTTP ≥400 如 404/403/502，或连接错误如超时/被墙），自动改用该文件原始的
    官方 URL 重试一次 —— 对齐 prism-bootstrap 的 per-file 多源回退。非 Mojang
    主机原样透传。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ctx = active_context()
        self._last_status = None
        # round-203：代理同样按「本次安装优先」取值，不受并行下载影响。
        _apply_proxy(self, _proxy_for(self._ctx))
        # round-113 P0-c：requests 的默认 HTTPAdapter 连接池只有 10 条
        # （pool_maxsize=10, pool_block=False）。并发 48 时其余 38 条每次都要
        # 重新握手 —— 实测同口径下 pool=10 比 pool=32 慢 15%（6.29s vs 5.30s，
        # 80 个资源对象）。把池放大到 64，让并发数与可复用连接数匹配。
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=_POOL_SIZE, pool_maxsize=_POOL_SIZE, pool_block=False)
        self.mount("https://", adapter)
        self.mount("http://", adapter)

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        # 原样构建 PreparedRequest（保留原始 URL 供 send() 做回退判断）
        return super().request(method, url, *args, **kwargs)

    def send(self, request, **kwargs):  # type: ignore[override]
        # mll 从不传 timeout，而 requests 的 Session.request() 总会把 timeout
        # 显式塞进 kwargs（默认值是 None）——所以这里必须判断「是 None」而不是
        # setdefault，否则超时永远补不上。
        explicit_timeout = kwargs.get("timeout")
        if explicit_timeout is None:
            kwargs["timeout"] = _SEND_TIMEOUT
        url = getattr(request, "url", None)
        started = time.monotonic()
        cands = []
        strict_single = False
        if isinstance(url, str) and request.method == "GET":
            # round-174：先按健康表排序（不健康镜像直接跳过、慢镜像让位官方）。
            raw_cands = _candidates(url, self._ctx)
            cands = _rank_candidates(raw_cands)
            # 原本有镜像候选（= 游戏文件双源）时，官方单源也要保持 strict：
            # 两源皆失败必须显式报错，不能被 mll 的 `download_file` 静默吞掉。
            strict_single = len(raw_cands) > 1 and bool(cands) and not cands[0].mirrored
            if len(cands) > 1:
                # round-155：来源链逐候选尝试；非末位失败记录原因并换源，
                # 末位 strict（游戏文件两源皆失败 = 安装已损坏，必须显式失败）。
                for i, cand in enumerate(cands):
                    last = i == len(cands) - 1
                    request.url = cand.url
                    call_kw = kwargs
                    if explicit_timeout is None:
                        call_kw = dict(kwargs)
                        call_kw["timeout"] = _timeout_for(cand)
                    key = _source_key(cand)
                    t0 = time.monotonic()
                    try:
                        resp = self._try_source(
                            request, last=last, strict=last,
                            retries=_retries_for(cand), **call_kw)
                    except requests.RequestException as exc:
                        # 末位源失败会抛错（strict / 连接不可用）：先记账再放行。
                        status = self._last_status
                        reason = (("HTTP %s" % status) if status
                                  else (str(exc) or "connection error"))
                        self._note_source(cand.source, cand.url, ok=False,
                                          reason=reason, status=status)
                        _HEALTH.note_fail(key, reason)
                        if _DIAG:
                            _diag_log("health %s down (%s)" % (key, reason))
                        raise
                    if resp is not None and resp.status_code < 400:
                        _HEALTH.note_ok(key, time.monotonic() - t0)
                        self._note_source(cand.source, cand.url, ok=True)
                        _diag(url, cand.url, resp, started)
                        return _wrap_raw(resp, self._ctx)
                    status = self._last_status
                    reason = ("HTTP %s" % status) if status else "connection error"
                    self._note_source(cand.source, cand.url, ok=False,
                                      reason=reason, status=status)
                    # 只有连接类失败 / 5xx 才影响「源健康」；404 只是这个文件
                    # 镜像没同步，不代表整台主机不能用。
                    if status is None or status >= 500:
                        _HEALTH.note_fail(key, reason)
                    if cand.mirrored:
                        # 镜像对本主机不可用：记为失效，后续同主机请求直接走
                        # 官方源，不再每个文件都白试一次（round-110 B）。
                        # round-174：不再要求它是第 0 个候选 —— 慢镜像可能被
                        # 健康表排到官方后面。
                        self._mark_mirror_dead(url, cand.source)
                # 理论不可达：末位 strict 失败会抛错。
                request.url = cands[-1].url
                last_kw = kwargs
                if explicit_timeout is None:
                    last_kw = dict(kwargs)
                    last_kw["timeout"] = _timeout_for(cands[-1])
                resp = self._try_source(
                    request, last=True, strict=True,
                    retries=_retries_for(cands[-1]), **last_kw)
                _diag(url, cands[-1].url, resp, started)
                return _wrap_raw(resp, self._ctx)
        # 单候选（非 Mojang 主机 / 镜像关闭 / 镜像已被健康表剔除）：
        # 原样透传，只加超时/重试。
        target = cands[0] if cands else None
        if target is not None:
            request.url = target.url
        call_kw = kwargs
        if target is not None and explicit_timeout is None:
            call_kw = dict(kwargs)
            call_kw["timeout"] = _timeout_for(target)
        t0 = time.monotonic()
        resp = self._try_source(
            request, last=True,
            strict=bool(cands and strict_single),
            retries=_retries_for(target) if target is not None else _RETRIES,
            **call_kw)
        if target is not None:
            key = _source_key(target)
            if resp is not None and resp.status_code < 400:
                _HEALTH.note_ok(key, time.monotonic() - t0)
                if target.mirrored:
                    self._note_source(target.source, target.url, ok=True)
            elif resp is not None and resp.status_code >= 500:
                _HEALTH.note_fail(key, "HTTP %s" % resp.status_code)
        _diag(url, target.url if target is not None else url, resp, started)
        return _wrap_raw(resp, self._ctx)

    def _note_source(self, source: str, url: str, *, ok: bool,
                     reason: str = "", status: int | None = None) -> None:
        """把一次来源尝试写进本次安装的 trace（无上下文时忽略）。"""
        trace = getattr(self._ctx, "trace", None)
        if trace is None:
            return
        try:
            if ok:
                trace.success(source, url)
            else:
                trace.failure(source, url, reason, status)
        except Exception:  # noqa: BLE001 - 记录失败绝不影响下载
            pass

    def _mark_mirror_dead(self, original_url: str, source: str = "bmclapi") -> None:
        """镜像对 ``original_url`` 所属主机返回「被拦」状态 → 本次安装内不再走它。

        只在 401/403/406 这类「明确拒绝」上生效：404 可能只是该文件镜像没同步，
        逐个回退即可，不足以判定整台主机失效。round-174 起同时把该来源记入
        进程级健康表（立刻冷却），即使用户不重开安装也不会再被同一台镜子拖住。
        """
        if self._last_status not in (401, 403, 406):
            return
        _HEALTH.note_rejected(source, "HTTP %s" % self._last_status)
        ctx = self._ctx
        if ctx is None:
            return
        for host in _MIRROR_HOSTS:
            prefix = "https://" + host
            if original_url == prefix or original_url.startswith(prefix + "/"):
                ctx.mirror_dead.add(host)
                return

    def _try_source(self, request, *, last=False, strict=False, retries=None,
                    **kwargs):
        """在**单一源**上发请求，最多重试 ``retries`` 次。

        返回 2xx 响应即成功。``last=False`` 且本源不可用时返回 None，表示「本源
        不可用，请上层换源」；``last=True`` 时连接失败会向上抛异常，且 ``strict``
        时 HTTP ≥400 也抛错（游戏文件两源皆失败 = 安装已损坏，必须显式失败）。

        round-174：``retries`` 按来源区分 —— 镜像 0 次（挂住就立刻换官方），
        官方仍是 1 次。
        """
        tries = _RETRIES if retries is None else max(0, int(retries))
        attempt = 0
        rate_waits = 0
        while True:
            ctx = self._ctx
            if ctx is not None and ctx.aborted:
                raise requests.RequestException("download aborted by user")
            try:
                resp = super().send(request, **kwargs)
            except requests.RequestException:
                if attempt < tries:
                    attempt += 1
                    continue  # 超时 / 连接错误 → 同一源再试一次
                self._last_status = None
                if last:
                    raise
                return None
            self._last_status = resp.status_code
            # round-176：429 限流单独处理 —— 按 Retry-After 等一次再试，且不计入
            # 源健康（限流说明源是活的，不该被冷却）。超过一次后按普通失败处理。
            if resp.status_code == 429 and rate_waits < 1:
                rate_waits += 1
                wait = _retry_after_seconds(resp)
                try:
                    resp.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                if not last:
                    try:
                        resp.close()
                    except Exception:  # noqa: BLE001
                        pass
                    return None
                if strict:
                    # 此前 download_file 只会静默 return False，安装却照报
                    # "Installation complete" —— 这里改为显式抛出 HTTPError。
                    try:
                        resp.raise_for_status()
                    finally:
                        resp.close()
                return resp
            return resp
        return None  # 理论不可达（循环至少跑一次）


class _CountingRaw:
    """包住 urllib3 的 ``HTTPResponse``，只统计 ``read()`` 真正拿到的字节数。

    mll 的 ``_helper.download_file`` 用 ``shutil.copyfileobj(r.raw, f)`` 落盘，
    全程只调 ``raw.read``；包一层即可拿到真实字节吞吐，而不改动任何下载逻辑。
    其余属性原样透传（``decode_content`` 等会被 mll 赋值，走 ``__setattr__``）。
    """

    __slots__ = ("_raw", "_sink")

    def __init__(self, raw, sink) -> None:
        object.__setattr__(self, "_raw", raw)
        object.__setattr__(self, "_sink", sink)

    def read(self, *args, **kwargs):
        data = object.__getattribute__(self, "_raw").read(*args, **kwargs)
        if data:
            try:
                object.__getattribute__(self, "_sink")(len(data))
            except Exception:  # noqa: BLE001
                pass
        return data

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_raw"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_raw"), name, value)


def _wrap_raw(resp, ctx):
    """登记在途响应（供取消掐断），并给 ``raw`` 装上计数代理。"""
    if resp is None:
        return resp
    if ctx is not None:
        try:
            ctx.track_response(resp)
        except Exception:  # noqa: BLE001 - 登记失败不影响下载
            pass
    meter = getattr(ctx, "meter", None) if ctx is not None else None
    if meter is None:
        return resp
    try:
        raw = resp.raw
        if isinstance(raw, _CountingRaw):
            return resp
        resp.raw = _CountingRaw(raw, meter.note)
    except Exception:  # noqa: BLE001 - 包装失败不影响下载
        pass
    return resp


def _diag(orig: str, used: str, resp, started: float) -> None:
    """round-110 C：每请求一行诊断（status / 耗时 / 声明字节 / 是否走镜像）。"""
    if not _DIAG:
        return
    ms = int((time.monotonic() - started) * 1000)
    status = getattr(resp, "status_code", "?")
    size = "-"
    try:
        size = resp.headers.get("Content-Length", "-") or "-"
    except Exception:  # noqa: BLE001
        pass
    src = "mirror" if used != orig else "direct"
    _diag_log(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {status} {ms}ms "
              f"{size}B {src} {orig}")



class _RequestsShim:
    """Stand-in for the ``requests`` module inside mll submodules.

    ``session()`` returns a :class:`MirrorSession`. ``get()`` covers the calls
    that bypass sessions — ``_helper.download_file`` when no session is passed
    (version json / logging config / client jar) plus the runtime & loader
    metadata fetches — routing them through a MirrorSession too so they also
    get the timeout, retry and cancellation. Every other attribute delegates to
    the real module.
    """

    __slots__ = ("_real",)

    def __init__(self, real):
        self._real = real

    def session(self, *args, **kwargs):
        return MirrorSession(*args, **kwargs)

    def get(self, url, **kwargs):
        kwargs.setdefault("timeout", _SEND_TIMEOUT)
        return MirrorSession().get(url, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


# mll submodules that import ``requests`` themselves. mrpack / fabric / forge /
# quilt reach the network only through ``_helper.download_file`` or
# ``install.install_minecraft_version``, so patching the three below covers them.
_PATCH_MODULES = ("_helper", "install", "runtime")

# round-172：这些加载器安装函数用 ``subprocess.run`` 跑安装器 jar，jar 自己还会
# 下载几百 MB —— 取消启动时必须能连带杀掉子进程，否则「取消」看起来毫无反应。
_SPROC_PATCH_MODULES = ("mod_loader._fabric", "mod_loader._forge",
                        "mod_loader._neoforge", "mod_loader._quilt")


def _candidates(url, ctx=None):
    """当前 URL 的候选来源链（镜像关闭 → 只有官方候选）。

    round-203：``ctx`` 存在时用它自己的 mirror_on（并行安装互不串扰）。
    """
    if not _mirror_on_for(ctx) or not isinstance(url, str):
        return _CHAIN.candidates(url, prefer=OFFICIAL_ONLY)
    dead = getattr(ctx, "mirror_dead", None) if ctx is not None else None
    return _CHAIN.candidates(url, dead=dead)


def _rewrite(url):
    """单 URL 重写（分片并行等自有路径用）；等价于候选链里的镜像候选。

    round-174：镜像被健康表判为不健康时不再改写 —— 大文件（客户端 jar）宁可
    走官方，也不要在挂住的镜子上等到超时。
    """
    if not _mirror_on_for() or not isinstance(url, str):
        return url
    for cand in _candidates(url, active_context()):
        if cand.mirrored and not _HEALTH.is_down(_source_key(cand)):
            return cand.url
    return url


# ── round-111：mll 的大文件走分片并行 ─────────────────────────────────────
# mll 的 install / fabric / forge / mrpack / quilt / runtime 都用
# ``from ._helper import download_file`` 拿了**直接引用**，所以只改 ``_helper``
# 本身不够，必须逐个模块替换属性。
#
# ⚠️ 为什么不给所有文件都加分片：一次完整安装会调用 ``download_file`` 数百到
# 上千次（libraries + assets 逐个下载），而无差别加分片就要先探测每个文件的
# 大小 —— 那是几百上千个额外请求，在跨境链路上是几十秒到几分钟的**净回归**。
# 因此只对「确定是大文件」的目标做一次探测：客户端 jar
# （``versions/<id>/<id>.jar``，通常 20~25MB，是单次安装里最大的单文件，
# 且整个安装只出现 1 个）。其余一律零开销原样转发给 mll 原实现。
_DL_PATCH_MODULES = ("_helper", "install", "runtime", "fabric", "forge",
                     "mrpack", "quilt")


def _is_big_target(path) -> bool:
    """零网络成本判断「这个目标值得为它探测一次大小」。

    只认客户端 jar：``<mc>/versions/<version>/<version>.jar``。
    单次安装里最大的单文件，且只有 1 个 —— 探测开销可忽略，
    换来的是把 20~25MB 从单连接（跨境 ~0.3MB/s）拉到多连接。
    """
    if not isinstance(path, str) or not path.endswith(".jar"):
        return False
    parts = os.path.normpath(path).replace("\\", "/").rstrip("/").split("/")
    # .../versions/<id>/<id>.jar → versions 在倒数第 3 位，且文件名 == 目录名.jar
    return (len(parts) >= 3 and parts[-3] == "versions"
            and parts[-1] == parts[-2] + ".jar")


def _try_parallel_mll(url, path, sha1, callback, minecraft_directory,
                      overwrite, ctx=None) -> bool:
    """尝试用分片并行下载 mll 的一个大文件。

    返回 True = 已由本函数完成下载（调用方直接 ``return True``）；
    返回 False = 不适用或失败，调用方应走 mll 原实现（单流，含镜像/重试/取消）。

    与 mll ``_helper.download_file`` 的语义对齐点：
    * 路径安全检查（``minecraft_directory``）；
    * 已存在且（无 sha1 或校验通过）→ 不重复下载；
    * 只发 ``setStatus``，**绝不发 setProgress/setMax** ——
      mll 的 install 用它们做「文件计数」进度，掺入字节数会把进度条搞乱；
    * sha1 不符时抛 mll 自己的 ``InvalidChecksum``；
    * 任何失败都回退原实现，不改变下载结果。
    """
    from minecraft_launcher_lib._helper import (
        check_path_inside_minecraft_directory,
        get_sha1_hash,
    )

    if minecraft_directory is not None:
        check_path_inside_minecraft_directory(minecraft_directory, path)
    if os.path.isfile(path) and not overwrite:
        # 与 mll 同语义：已存在且无需校验 / 校验通过 → 跳过。
        # 返回 False，让 mll 原实现走它自己的跳过分支并返回 False。
        if sha1 is None or get_sha1_hash(path) == sha1:
            return False

    # net_api 不做 Mojang 主机重写（只有这里的 _rewrite 做），所以必须自己先
    # 重写，否则分片路径会丢掉 BMCLAPI 镜像。
    real_url = _rewrite(url)

    from .. import net_api
    try:
        size = net_api._remote_size(real_url, None, 30)
    except Exception:  # noqa: BLE001 - 探测失败一律回退
        return False
    if size < net_api._PARALLEL_MIN_BYTES:
        return False

    callback.get("setStatus", lambda *a, **k: None)(
        "Download " + os.path.basename(path))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:  # noqa: BLE001 - 与 mll 一致：建目录失败不阻断
        pass

    def _cancel():
        if ctx is not None:
            return ctx.aborted
        c = active_context()
        return c is not None and c.aborted

    try:
        # round-113 P1-c：chunk_mb 4 → 2，threads 显式给 16。
        # 实测客户端 jar（40.1MB）单连接 0.39MB/s，4 路 1.62MB/s，
        # 8 路 1.39MB/s（反而慢），16 路 3.19MB/s —— 分片不是越多越好，
        # 跨境链路 RTT 才是瓶颈，8 路起内耗占比就上来了。
        # net_api 的默认 cap 是 min(cpu, 8)，本机 12 核也只给 8 路，
        # 必须显式传 threads=16 才能落到实测最优点。
        # 2MB 切块让 40MB 文件有 21 个候选块，配合 cap=16 正好 16 路；
        # 8MB 阈值文件则自然落到 5 路，不会过切。
        net_api.parallel_download_file(real_url, path, timeout=120,
                                       threads=16, chunk_mb=2, cancel=_cancel)
    except Exception:  # noqa: BLE001 - 分片失败一律回退 mll 原实现
        # round-172：取消是协作式指令，不能被回退掩盖（池线程里没有线程局部
        # 上下文，这里改用会话带来的 ctx）。
        c = ctx if ctx is not None else active_context()
        if c is not None and c.aborted:
            raise
        return False

    if sha1 is not None:
        from minecraft_launcher_lib.exceptions import InvalidChecksum
        checksum = get_sha1_hash(path)
        if checksum != sha1:
            raise InvalidChecksum(url, path, sha1, checksum)
    return True


# ── round-176：mll 安装路径的断点续传 + 低速判据 ────────────────────────────
# 自有下载器（net_api.download_file / parallel_download_file）早就有 Range 续传，
# 但版本安装走的是 mll 的 ``_helper.download_file``：一次中断整文件从 0 重下。
# 这里接管那条路径：
#   * 写入 ``<path>.part``，下次从末尾用 ``Range: bytes=N-`` 续传（206 追加，
#     200 说明服务器不认 Range → 清空重下）；
#   * sha1 边下边算（省掉 mll 下完再整文件读一遍的开销），完成后再原子替换；
#   * 低速判据：已收 ≥256KB、窗口 ≥8s 且平均 <6KB/s → 断开重连续传（最多 1 次），
#     专治「连接活着但只有几 KB/s」的假死链路；
#   * 任何无法接管的异常都退回 mll 原实现，不改变最终结果。
_RESUME_MIN_BYTES = 1 << 20
_SLOW_WINDOW = 8.0
_SLOW_BPS = 6 * 1024
_SLOW_MIN_BYTES = 256 * 1024


class _ResumeFallback(Exception):
    """本路径无法安全接管 → 退回 mll 原实现。"""


class _SlowDownload(Exception):
    """低速判据命中：断开后从 .part 续传。"""


def _retry_after_seconds(resp, default: float = 5.0) -> float:
    """解析 ``Retry-After``（秒数形式；HTTP-date 形式忽略并取默认值）。"""
    raw = resp.headers.get("Retry-After") if resp is not None else None
    try:
        return max(0.0, min(float(raw), 20.0))
    except (TypeError, ValueError):
        return default


def _resume_mll_download(url, path, *, callback, sha1, session,
                         minecraft_directory, overwrite) -> bool:
    """mll ``download_file`` 的等价实现：断点续传 + 低速重连 + 单遍 sha1。

    返回 False 表示「文件已存在且无需下载」（与 mll 一致）；True 表示已就位。
    无法接管时抛 :class:`_ResumeFallback`，由调用方退回原实现。
    """
    from minecraft_launcher_lib._helper import (
        check_path_inside_minecraft_directory,
        get_sha1_hash,
    )
    from minecraft_launcher_lib.exceptions import InvalidChecksum

    if minecraft_directory is not None:
        check_path_inside_minecraft_directory(minecraft_directory, path)

    part = path + ".part"
    if os.path.isfile(path) and not overwrite:
        if sha1 is None or get_sha1_hash(path) == sha1:
            # 目标已就位：顺手清掉上次残留的半截文件。
            if os.path.isfile(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
            return False

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:  # noqa: BLE001 - 与 mll 一致：建目录失败不阻断
        pass

    callback.get("setStatus", lambda *a, **k: None)(
        "Download " + os.path.basename(path))

    sess = session
    if sess is None:
        # mll 各模块的 requests 已被换成 _RequestsShim → 仍走 MirrorSession。
        from minecraft_launcher_lib import _helper as _mll_helper
        sess = getattr(_mll_helper, "requests", requests)

    ctx = active_context()
    for attempt in range(2):
        start = os.path.getsize(part) if os.path.isfile(part) else 0
        hdrs = {"Range": "bytes=%d-" % start} if start else {}
        try:
            resp = sess.get(url, stream=True, headers=hdrs)
        except Exception:  # noqa: BLE001 - 连接层失败交给原实现决定
            raise _ResumeFallback()
        try:
            if ctx is not None and ctx.aborted:
                raise requests.RequestException("download aborted by user")

            if resp.status_code == 416 and start:
                # .part 已不比远端小：校验通过就收尾，否则丢掉重下。
                if sha1 is None or get_sha1_hash(part) == sha1:
                    os.replace(part, path)
                    return True
                os.remove(part)
                raise _ResumeFallback()
            if resp.status_code not in (200, 206):
                raise _ResumeFallback()

            total = 0
            if resp.status_code == 206:
                cr = resp.headers.get("Content-Range", "")
                try:
                    total = int(cr.rsplit("/", 1)[1])
                except (IndexError, ValueError):
                    total = 0
            else:
                try:
                    total = int(resp.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                start = 0            # 服务器不认 Range → 从头写

            hasher = None
            if sha1:
                hasher = hashlib.sha1()
                if start:
                    with open(part, "rb") as fh:
                        for chunk in iter(lambda: fh.read(1 << 20), b""):
                            hasher.update(chunk)

            got = 0
            win_start = time.monotonic()
            win_bytes = 0
            with open(part, "ab" if start else "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    if not chunk:
                        continue
                    if ctx is not None and ctx.aborted:
                        raise requests.RequestException(
                            "download aborted by user")
                    fh.write(chunk)
                    got += len(chunk)
                    if hasher is not None:
                        hasher.update(chunk)
                    win_bytes += len(chunk)
                    now = time.monotonic()
                    if (win_bytes >= _SLOW_MIN_BYTES and total >= _RESUME_MIN_BYTES
                            and now - win_start >= _SLOW_WINDOW
                            and win_bytes / max(1e-6, now - win_start) < _SLOW_BPS):
                        raise _SlowDownload()
        except _SlowDownload:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
            if attempt == 0:
                time.sleep(0.5)
                continue        # 续传再来一轮
            raise _ResumeFallback()
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

        if sha1 is not None:
            checksum = hasher.hexdigest()
            if checksum != sha1:
                try:
                    os.remove(part)
                except OSError:
                    pass
                raise InvalidChecksum(url, path, sha1, checksum)
        os.replace(part, path)
        return True
    raise _ResumeFallback()


def _wrap_download_file(orig):
    """把 mll 的 ``download_file`` 包一层：大文件走分片并行，其余原样转发。"""

    def download_file(url, path, callback={}, sha1=None, lzma_compressed=False,
                      session=None, minecraft_directory=None, overwrite=False):
        # lzma 内容是变换过的，既不能分片也不能续传 → 原样交给 mll。
        if lzma_compressed:
            return orig(url, path, callback, sha1, lzma_compressed, session,
                        minecraft_directory, overwrite)
        # 客户端 jar 仍然优先走分片并行（内部自带 .part 与回退）。
        if _is_big_target(path) and _try_parallel_mll(
                url, path, sha1, callback, minecraft_directory, overwrite,
                ctx=getattr(session, "_ctx", None)):
            return True
        # round-176：其余文件走「.part + Range 续传 + 低速重连 + 单遍 sha1」。
        try:
            return _resume_mll_download(
                url, path, callback=callback, sha1=sha1, session=session,
                minecraft_directory=minecraft_directory, overwrite=overwrite)
        except _ResumeFallback:
            c = active_context()
            if c is not None and c.aborted:
                raise requests.RequestException("download aborted by user")
            return orig(url, path, callback, sha1, lzma_compressed, session,
                        minecraft_directory, overwrite)

    download_file._ac_parallel_wrapped = True  # type: ignore[attr-defined]
    return download_file


def _patch_download_file() -> None:
    """把上述包裹应用到每个持有 ``download_file`` 直接引用的 mll 模块。"""
    for name in _DL_PATCH_MODULES:
        try:
            mod = importlib.import_module("minecraft_launcher_lib." + name)
        except ImportError:
            continue
        cur = getattr(mod, "download_file", None)
        if cur is None or getattr(cur, "_ac_parallel_wrapped", False):
            continue
        setattr(mod, "download_file", _wrap_download_file(cur))


# Process-wide proxy mode, shared by every MirrorSession spawned by the patched
# install session factory. "none" = force direct (disable system proxy),
# "system" = let requests use OS/env proxy (default), or a URL string.
_PROXY = None


def set_proxy(proxy):
    """Set the proxy mode used by subsequently created MirrorSessions.

    round-203：与 :func:`set_mirror` 同一套规则 —— 安装线程内写本次安装的
    ``ctx.proxy``，线程外才改进程级默认值。并行下载不会互相改代理。
    """
    global _PROXY
    ctx = active_context()
    if ctx is not None:
        ctx.proxy = proxy
        return
    _PROXY = proxy


def _proxy_for(ctx=None):
    """当前请求该用哪个代理设置：本次安装优先，否则进程级默认值。"""
    if ctx is None:
        ctx = active_context()
    val = getattr(ctx, "proxy", _UNSET) if ctx is not None else _UNSET
    return _PROXY if val is _UNSET else val


def _apply_proxy(session: requests.Session, proxy) -> None:
    """Apply a proxy setting to a requests.Session.

    proxy:
      None / "system"  -> requests default (trust_env=True, uses OS proxy)
      "none"           -> force direct, ignore any system/env proxy
      "http://host:port" (or https://) -> route through that proxy
    """
    if proxy is None or proxy == "system":
        session.trust_env = True
    elif proxy == "none":
        session.trust_env = False
        session.proxies.clear()
    elif isinstance(proxy, str) and "://" in proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    else:
        session.trust_env = True


_PATCHED = False


def _patch_install_concurrency() -> None:
    """round-113 P0-b：给 mll 的库/资源下载注入更高的并发。

    ``minecraft_launcher_lib.install`` 里的 ``install_libraries`` 与
    ``install_assets`` 都接受 ``max_workers``，但 ``do_version_install``
    调用它们时**不传**，于是落到 ``ThreadPoolExecutor`` 的默认值
    ``min(32, cpu_count + 4)`` —— 本机 12 核只有 16 并发。

    实测（同口径 80 个资源对象）：16 并发 6.03MB/s，48 并发 8.35MB/s。
    48 是拐点，再往上 p50 延迟开始拖慢整体。

    这两个函数在 mll 内部是**模块级全局查找**（``install_libraries(...)``
    而非 ``install.install_libraries(...)``），所以直接替换模块属性即可生效；
    其它模块（forge / fabric / quilt）用的是 ``from .install import
    install_libraries`` 的直接引用，需一并替换。
    """
    try:
        import minecraft_launcher_lib.install as mll_install
    except ImportError:
        return

    def _wrap(fn):
        def wrapper(*args, **kwargs):
            # 显式传入的 max_workers 优先，不覆盖调用方的意图
            if kwargs.get("max_workers") is None:
                kwargs["max_workers"] = _MAX_WORKERS
            return fn(*args, **kwargs)
        wrapper._ac_concurrency_patched = True  # type: ignore[attr-defined]
        return wrapper

    for name in ("install_libraries", "install_assets"):
        fn = getattr(mll_install, name, None)
        if fn is None or getattr(fn, "_ac_concurrency_patched", False):
            continue
        setattr(mll_install, name, _wrap(fn))

    # forge 模块用 `from ..install import install_libraries` 直接引用，
    # 替换 install 模块的属性对它无效，必须单独替换。
    for mod_name, attr in (
        ("minecraft_launcher_lib.mod_loader._forge", "install_libraries"),
    ):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        fn = getattr(mod, attr, None)
        if fn is None or getattr(fn, "_ac_concurrency_patched", False):
            continue
        setattr(mod, attr, _wrap(fn))


def patch_install_session() -> None:
    """Route every mll download through MirrorSession.

    Idempotent — safe to call on every install, and worth calling even when the
    mirror is off: the timeout / retry / cancel hardening applies to the
    official source too. ``_MIRROR_ON`` decides at request time whether Mojang
    hosts are rewritten, so ``set_proxy`` / ``set_mirror`` take effect on the
    next install without re-patching.
    """
    global _PATCHED
    if _PATCHED:
        return
    for name in _PATCH_MODULES:
        try:
            mod = importlib.import_module("minecraft_launcher_lib." + name)
        except ImportError:
            continue
        real = getattr(mod, "requests", None)
        if real is not None and not isinstance(real, _RequestsShim):
            setattr(mod, "requests", _RequestsShim(real))
    # round-111：大文件（客户端 jar）走分片并行。只对确定是大文件的目标探测
    # 一次大小，其余零开销 —— 详见 _is_big_target 的说明。
    _patch_download_file()
    # round-113 P0-b：库/资源下载并发 16 → 48。
    _patch_install_concurrency()
    # round-172：加载器安装器子进程可取消。
    _patch_subprocess()
    _PATCHED = True


def _patch_subprocess() -> None:
    """把 mll 加载器安装函数里的 ``subprocess.run`` 换成可取消版本。"""
    for name in _SPROC_PATCH_MODULES:
        try:
            mod = importlib.import_module("minecraft_launcher_lib." + name)
        except ImportError:
            continue
        real = getattr(mod, "subprocess", None)
        if real is None or isinstance(real, _SubprocessShim):
            continue
        setattr(mod, "subprocess", _SubprocessShim(real))


def proxy_dict(proxy) -> dict | None:
    """Build a requests ``proxies`` dict from a proxy setting (for our own
    net_api calls). Returns None when the default (system) behaviour applies."""
    if proxy is None or proxy == "system":
        return None
    if proxy == "none":
        # requests treats a None per-scheme entry as "no proxy for this scheme",
        # which overrides trust_env — effectively direct.
        return {"http": None, "https": None}
    if isinstance(proxy, str) and "://" in proxy:
        return {"http": proxy, "https": proxy}
    return None
