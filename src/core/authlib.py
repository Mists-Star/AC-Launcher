"""Fetch / verify authlib-injector for third-party (Yggdrasil) login.

The launcher must NOT redistribute the jar; instead we download it on demand
from the official GitHub release and verify its SHA-256. ``ensure_authlib``
returns the local jar path, downloading + verifying when missing, or ``None``
if the network is unavailable (so the caller can show a friendly warning).

Pinned to a known-good version (verify against the release page if bumping).

round-213：**不再自动追 GitHub latest**。历史上 `try_update_authlib` 会把最新
jar 以「zip 可解析 + ≥60KB」为标准覆盖本地，再靠 `.version` 文件让
`ensure_authlib` 直接信任 —— 固定 sha256 对真实运行路径没有任何约束力，
被替换的 jar 会作为 `-javaagent` 注入游戏 JVM。现在唯一信任源是
`AUTHLIB_VERSION` + `AUTHLIB_SHA256`，升级随启动器版本走。
"""
from __future__ import annotations

import hashlib
import os
import threading

AUTHLIB_VERSION = "1.2.8"
AUTHLIB_URL = (
    "https://github.com/yushijinhun/authlib-injector/releases/download/"
    f"v{AUTHLIB_VERSION}/authlib-injector-{AUTHLIB_VERSION}.jar"
)
AUTHLIB_SHA256 = "9c7f4343e6c82034958ffb48c14a2cb0c85928be7283103ce17da00c6d5a7b10"

_DEFAULT_NAME = "authlib-injector.jar"
_UPDATE_DAYS = 7          # 节流：两次确保固定版存在之间至少隔 7 天


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# round-213：`_version_of` / `latest_authlib` / `_fetch_to` 三个函数已删除。
# 它们构成「查 latest → 只校验 zip 可解析 → 覆盖本地 jar → 写 .version →
# ensure_authlib 凭 .version 信任」的完整旁路；留着就等于保留一条能把任意
# jar 注入游戏 JVM 的路径。固定版本 + AUTHLIB_SHA256 是唯一信任源。


def update_authlib(dest: str | None = None, *, timeout: int = 60) -> bool:
    """round-213：改为「确保固定版存在且 sha256 校验通过」，不再自动追 latest。

    旧实现会把 GitHub latest 的 jar 以「zip 可解析 + ≥60KB」为标准覆盖本地，
    随后 `ensure_authlib` 仅凭 `.version` 文件就信任它 —— 固定 sha256 形同虚设，
    而这个 jar 会被 `-javaagent` 注入游戏 JVM（任意代码执行）。
    现在唯一信任源是 `AUTHLIB_VERSION` + `AUTHLIB_SHA256`；升级随启动器版本走。
    保留函数名是因为 `launch.py` 每次启动都会调它（节流后等于一次本地校验）。
    """
    return ensure_authlib(dest, timeout=timeout) is not None


def try_update_authlib(dest: str | None = None):
    """后台线程版「确保固定版存在且校验通过」：不阻塞调用方、失败全静默。

    round-213 起不再查询/下载 GitHub latest（见模块 docstring）；
    节流 7 天，线程 daemon，应用退出不等待。
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
    # round-213 P1：删除「有 .version 就信任」的旁路。旧逻辑配合
    # update_authlib（把 GitHub latest 以「zip 能打开」为标准覆盖固定版），
    # 让 AUTHLIB_SHA256 对真实运行路径完全没有约束力 —— 任何本地进程写一个
    # 文本文件就能让任意 jar 作为 -javaagent 注入游戏 JVM。
    # 现在只认固定版本 + 固定 sha256；不匹配就重下，下不到就返回 None。

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
