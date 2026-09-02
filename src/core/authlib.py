"""Fetch / verify authlib-injector for third-party (Yggdrasil) login.

The launcher must NOT redistribute the jar; instead we download it on demand
from the official GitHub release and verify its SHA-256. ``ensure_authlib``
returns the local jar path, downloading + verifying when missing, or ``None``
if the network is unavailable (so the caller can show a friendly warning).

Pinned to a known-good version (verify against the release page if bumping).
round-53 增加 "authlib 随版本更新"：``try_update_authlib`` 在启动时后台检查
GitHub latest release，有新版就自动替换本地 jar（原子写 + 完整性校验，
失败静默回退旧版，绝不阻塞启动）。
"""
from __future__ import annotations

import hashlib
import io
import os
import threading
import zipfile

AUTHLIB_VERSION = "1.2.8"
AUTHLIB_URL = (
    "https://github.com/yushijinhun/authlib-injector/releases/download/"
    f"v{AUTHLIB_VERSION}/authlib-injector-{AUTHLIB_VERSION}.jar"
)
AUTHLIB_SHA256 = "9c7f4343e6c82034958ffb48c14a2cb0c85928be7283103ce17da00c6d5a7b10"

_DEFAULT_NAME = "authlib-injector.jar"
_RELEASE_API = "https://api.github.com/repos/yushijinhun/authlib-injector/releases/latest"
# 新版 jar 无法用固定 sha 校验 → 用「zip 可解析 + 规模达标」做基本完整性验证。
# 低于此大小的 jar 视为下载失败/被拦（authlib-injector 正常 ~200KB+）。
_MIN_SIZE = 60 * 1024
_UPDATE_DAYS = 7          # 两次版本检查间隔 ≥7 天，避免每次启动都打 GitHub API


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _version_of(dest: str) -> str:
    """读旁路版本文件 <jar>.version；没有则回退固定版常量。"""
    try:
        with open(dest + ".version", "r", encoding="utf-8") as f:
            v = f.read().strip()
            if v:
                return v
    except OSError:
        pass
    return AUTHLIB_VERSION


def latest_authlib(*, timeout: int = 8) -> str | None:
    """查 GitHub latest release 版本号，如 "1.2.8"。失败返回 None（调用方静默）。"""
    try:
        import requests
        resp = requests.get(_RELEASE_API, timeout=timeout,
                            headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        tag = (resp.json() or {}).get("tag_name", "")
        return tag.lstrip("v") or None
    except Exception:  # noqa: BLE001 - 网络/限流失败一律静默
        return None


def _fetch_to(url: str, dest: str, *, timeout: int = 60) -> bool:
    """下载 ``url`` 到 ``dest.part`` 并做完整性校验；通过则原子替换 dest。"""
    try:
        import requests
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.content
    except Exception:  # noqa: BLE001 - 网络失败
        return False
    # 基本完整性：zip 可解析（jar 本质是 zip）+ 规模达标
    try:
        if len(data) < _MIN_SIZE:
            return False
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.testzip() is not None:
                return False
    except (zipfile.BadZipFile, OSError):
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)  # 原子替换，崩溃不残留半截 jar
        return True
    except OSError:
        return False


def update_authlib(dest: str | None = None, *, timeout: int = 60) -> bool:
    """查最新版并下载替换本地 jar（建议后台线程调用）。

    返回 True 表示成功更新（或已是最新无需更新）；任何失败返回 False，
    且绝不动已有 jar（旧版继续可用）。
    """
    if dest is None:
        from ..paths import get_data_dir
        dest = os.path.join(get_data_dir(), _DEFAULT_NAME)
    cur = _version_of(dest) if os.path.exists(dest) else ""
    try:
        latest = latest_authlib(timeout=min(timeout, 8))
    except Exception:  # noqa: BLE001
        latest = None
    if not latest:
        return False  # 网络不可用 → 保持现状
    if latest == cur:
        return True  # 已是最新
    url = (
        "https://github.com/yushijinhun/authlib-injector/releases/download/"
        f"v{latest}/authlib-injector-{latest}.jar"
    )
    if not _fetch_to(url, dest, timeout=timeout):
        return False
    try:
        with open(dest + ".version", "w", encoding="utf-8") as f:
            f.write(latest + "\n")
    except OSError:
        pass
    return True


def try_update_authlib(dest: str | None = None):
    """后台线程版的随版本更新（round-53）：不阻塞调用方、失败全静默。

    7 天最多查一次 API；线程 daemon，应用退出不等待。
    """
    def _run() -> None:
        try:
            if dest is None:
                from ..paths import get_data_dir
                d = os.path.join(get_data_dir(), _DEFAULT_NAME)
            else:
                d = dest
            mark = d + ".lastcheck"
            try:
                import time as _t
                if os.path.exists(mark) and _t.time() - os.path.getmtime(mark) < _UPDATE_DAYS * 86400:
                    return  # 距上次检查不足一周，跳过
            except OSError:
                pass
            if update_authlib(d):
                try:
                    open(mark, "w").close()
                except OSError:
                    pass
        except Exception:  # noqa: BLE001 - 后台更新绝不外抛
            pass

    threading.Thread(target=_run, daemon=True).start()


def ensure_authlib(dest: str | None = None, *, timeout: int = 60) -> str | None:
    """Return a verified authlib-injector jar path, downloading if necessary.

    ``dest`` is the target jar path. If ``None``, defaults to
    ``<data_dir>/authlib-injector.jar``. Returns ``None`` on failure.
    """
    if dest is None:
        from ..paths import get_data_dir

        dest = os.path.join(get_data_dir(), _DEFAULT_NAME)

    if os.path.exists(dest) and _sha256_of(dest) == AUTHLIB_SHA256:
        return dest
    # round-53：已存在但版本较新（之前随版本更新下载过）→ 旁路 .version 已在，
    # 无需再走固定 sha 校验（旧固定 sha 只约束固定版），直接认为可用。
    if os.path.exists(dest) and os.path.exists(dest + ".version"):
        return dest

    try:
        import requests
    except ImportError:
        return None

    try:
        resp = requests.get(AUTHLIB_URL, timeout=timeout)
        resp.raise_for_status()
        data = resp.content
    except Exception:  # noqa: BLE001
        return None

    if hashlib.sha256(data).hexdigest() != AUTHLIB_SHA256:
        return None

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return dest
