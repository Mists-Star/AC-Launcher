"""Fetch / verify authlib-injector for third-party (Yggdrasil) login.

The launcher must NOT redistribute the jar; instead we download it on demand
from the official GitHub release and verify its SHA-256. ``ensure_authlib``
returns the local jar path, downloading + verifying when missing, or ``None``
if the network is unavailable (so the caller can show a friendly warning).

Pinned to a known-good version (verify against the release page if bumping).
"""
from __future__ import annotations

import hashlib
import os

AUTHLIB_VERSION = "1.2.8"
AUTHLIB_URL = (
    "https://github.com/yushijinhun/authlib-injector/releases/download/"
    f"v{AUTHLIB_VERSION}/authlib-injector-{AUTHLIB_VERSION}.jar"
)
AUTHLIB_SHA256 = "9c7f4343e6c82034958ffb48c14a2cb0c85928be7283103ce17da00c6d5a7b10"

_DEFAULT_NAME = "authlib-injector.jar"


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


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
