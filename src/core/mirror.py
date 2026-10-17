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
"""
from __future__ import annotations

import contextlib
import importlib
import threading

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
    """

    __slots__ = ("_ev",)

    def __init__(self) -> None:
        self._ev = threading.Event()

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
        if isinstance(url, str) and request.method == "GET":
            rewritten = _rewrite(url)
            if rewritten != url:
                # 游戏文件：主源 = BMCLAPI；失败再试官方源，仍失败则显式抛错。
                request.url = rewritten
                got = self._try_source(request, **kwargs)
                if got is not None:
                    return got
                request.url = url
                return self._try_source(request, last=True, strict=True, **kwargs)
        # 非 Mojang 主机（Modrinth / maven / 自有 API）：原样透传，只加超时/重试。
        return self._try_source(request, last=True, strict=False, **kwargs)

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
                if last:
                    raise
                return None
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
    for host, repl in _MOJANG_HOSTS:
        prefix = "https://" + host
        if url == prefix or url.startswith(prefix + "/"):
            return repl + url[len(prefix):]
    return url


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
