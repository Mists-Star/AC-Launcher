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
"""
from __future__ import annotations

import contextlib
import importlib
import os
import threading
import time
from collections import deque

import requests

_BMCL_BASE = "https://bmclapi2.bangbang93.com"

# (host, replacement-prefix) — only exact https://<host>/... URLs are rewritten.
_MOJANG_HOSTS: list[tuple[str, str]] = [
    ("launchermeta.mojang.com", _BMCL_BASE),
    ("launcher.mojang.com", _BMCL_BASE),
    ("piston-data.mojang.com", _BMCL_BASE),
    ("libraries.minecraft.net", _BMCL_BASE + "/libraries"),
    ("resources.download.minecraft.net", _BMCL_BASE + "/assets"),
]

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
_MIRROR_ON = False


# ── round-110 A：字节记账 + 滑动时间窗测速 ──────────────────────────────────
class SpeedMeter:
    """线程安全的字节记账 + 滑动时间窗速度估算。

    mll 用 ThreadPoolExecutor 并发下载，多个线程同时写盘，所以累加与快照都必须
    持锁。速度按窗口内的「字节数 / 实际跨度」计算：窗口外样本丢弃，因此一次挂死
    （长时间没有新字节）会让速度自然归零，而不是靠一个假的时间戳假装在动。
    """

    __slots__ = ("_lock", "_pending", "_pending_since", "_samples", "_total",
                 "_window")

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


def note_bytes(nbytes: int) -> None:
    """把字节计入**当前线程所属安装**的速度计量（无安装上下文则忽略）。

    net_api 自家的下载循环用它在每个 chunk 落盘时喂数，这样「自建下载」与
    「mll 下载」共用同一个速度口径。
    """
    meter = active_meter()
    if meter is not None:
        meter.note(nbytes)


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
    """Enable/disable the BMCLAPI host rewrite for subsequently sent requests."""
    global _MIRROR_ON
    _MIRROR_ON = bool(enabled)


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
    """

    __slots__ = ("_ev", "meter", "mirror_dead")

    def __init__(self) -> None:
        self._ev = threading.Event()
        self.meter = SpeedMeter()
        self.mirror_dead: set = set()

    def abort(self) -> None:
        self._ev.set()

    @property
    def aborted(self) -> bool:
        return self._ev.is_set()


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
        _apply_proxy(self, _PROXY)

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        # 原样构建 PreparedRequest（保留原始 URL 供 send() 做回退判断）
        return super().request(method, url, *args, **kwargs)

    def send(self, request, **kwargs):  # type: ignore[override]
        # mll 从不传 timeout，而 requests 的 Session.request() 总会把 timeout
        # 显式塞进 kwargs（默认值是 None）——所以这里必须判断「是 None」而不是
        # setdefault，否则超时永远补不上。
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = _SEND_TIMEOUT
        url = getattr(request, "url", None)
        started = time.monotonic()
        if isinstance(url, str) and request.method == "GET":
            rewritten = _rewrite(url)
            if rewritten != url:
                # 游戏文件：主源 = BMCLAPI；失败再试官方源，仍失败则显式抛错。
                request.url = rewritten
                got = self._try_source(request, **kwargs)
                if got is not None:
                    _diag(url, rewritten, got, started)
                    return _wrap_raw(got, self._ctx)
                # 镜像对本主机不可用：记为失效，后续同主机请求直接走官方源，
                # 不再每个文件都白试一次（round-110 B）。
                self._mark_mirror_dead(url)
                request.url = url
                resp = self._try_source(request, last=True, strict=True, **kwargs)
                _diag(url, url, resp, started)
                return _wrap_raw(resp, self._ctx)
        # 非 Mojang 主机（Modrinth / maven / 自有 API）：原样透传，只加超时/重试。
        resp = self._try_source(request, last=True, strict=False, **kwargs)
        _diag(url, url, resp, started)
        return _wrap_raw(resp, self._ctx)

    def _mark_mirror_dead(self, original_url: str) -> None:
        """镜像对 ``original_url`` 所属主机返回「被拦」状态 → 本次安装内不再走它。

        只在 401/403/406 这类「明确拒绝」上生效：404 可能只是该文件镜像没同步，
        逐个回退即可，不足以判定整台主机失效。
        """
        if self._last_status not in (401, 403, 406):
            return
        ctx = self._ctx
        if ctx is None:
            return
        for host, _repl in _MOJANG_HOSTS:
            prefix = "https://" + host
            if original_url == prefix or original_url.startswith(prefix + "/"):
                ctx.mirror_dead.add(host)
                return

    def _try_source(self, request, *, last=False, strict=False, **kwargs):
        """在**单一源**上发请求，最多重试 ``_RETRIES`` 次。

        返回 2xx 响应即成功。``last=False`` 且本源不可用时返回 None，表示「本源
        不可用，请上层换源」；``last=True`` 时连接失败会向上抛异常，且 ``strict``
        时 HTTP ≥400 也抛错（游戏文件两源皆失败 = 安装已损坏，必须显式失败）。
        """
        for attempt in range(_RETRIES + 1):
            ctx = self._ctx
            if ctx is not None and ctx.aborted:
                raise requests.RequestException("download aborted by user")
            try:
                resp = super().send(request, **kwargs)
            except requests.RequestException:
                if attempt < _RETRIES:
                    continue  # 超时 / 连接错误 → 同一源再试一次
                self._last_status = None
                if last:
                    raise
                return None
            self._last_status = resp.status_code
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
    """给响应的 ``raw`` 装上计数代理（无速度计量器时原样返回）。"""
    meter = getattr(ctx, "meter", None) if ctx is not None else None
    if meter is None or resp is None:
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


def _rewrite(url):
    if not _MIRROR_ON or not isinstance(url, str):
        return url
    ctx = active_context()
    dead = ctx.mirror_dead if ctx is not None else None
    for host, repl in _MOJANG_HOSTS:
        if dead and host in dead:
            continue  # round-110 B：该主机已被镜像拒绝，本次安装直接走官方源
        prefix = "https://" + host
        if url == prefix or url.startswith(prefix + "/"):
            return repl + url[len(prefix):]
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
                      overwrite) -> bool:
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
        ctx = active_context()
        return ctx is not None and ctx.aborted()

    try:
        # chunk_mb=4：阈值已是 8MB，按默认 16MB 切只会得到 1~2 块，并行度太弱；
        # 4MB 让 8MB 文件也至少 3 块，客户端 jar（20~25MB）能到 5~6 块。
        net_api.parallel_download_file(real_url, path, timeout=120,
                                       chunk_mb=4, cancel=_cancel)
    except Exception:  # noqa: BLE001 - 分片失败一律回退 mll 原实现
        ctx = active_context()
        if ctx is not None and ctx.aborted():
            raise  # 取消是协作式指令，不能被回退掩盖
        return False

    if sha1 is not None:
        from minecraft_launcher_lib.exceptions import InvalidChecksum
        checksum = get_sha1_hash(path)
        if checksum != sha1:
            raise InvalidChecksum(url, path, sha1, checksum)
    return True


def _wrap_download_file(orig):
    """把 mll 的 ``download_file`` 包一层：大文件走分片并行，其余原样转发。"""

    def download_file(url, path, callback={}, sha1=None, lzma_compressed=False,
                      session=None, minecraft_directory=None, overwrite=False):
        # lzma 内容是变换过的，不能分片；只对「确定是大文件」的目标探测一次。
        if (not lzma_compressed and _is_big_target(path)
                and _try_parallel_mll(url, path, sha1, callback,
                                      minecraft_directory, overwrite)):
            return True
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
    """Set the proxy mode used by subsequently created MirrorSessions."""
    global _PROXY
    _PROXY = proxy


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
    _PATCHED = True


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
