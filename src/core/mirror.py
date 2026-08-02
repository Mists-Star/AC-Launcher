"""BMCLAPI download mirror for Mojang hosts.

When the user selects the BMCLAPI mirror, we transparently rewrite the 4 Mojang
download hosts to their BMCLAPI equivalents. BMCLAPI mirrors these 1:1, so only
the host changes — the path and query string are preserved byte-for-byte.
Non-Mojang hosts (Modrinth, authlib download, etc.) pass through untouched,
which keeps this patch safe to leave active for the whole app session.

The single hook that matters is ``minecraft_launcher_lib.install``: the library
calls ``requests.session()`` internally for *every* download (version jar,
libraries, assets, runtime), so replacing its session factory mirrors all of
them at once.
"""
from __future__ import annotations

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


class MirrorSession(requests.Session):
    """A requests.Session that rewrites Mojang download hosts to BMCLAPI.

    Also honours a process-wide proxy setting (see ``set_proxy``), so a user
    behind a corporate / GFW proxy can route Minecraft downloads through it.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_proxy(self, _PROXY)

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        return super().request(method, _rewrite(url), *args, **kwargs)


def _rewrite(url):
    if not isinstance(url, str):
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
    """Replace minecraft_launcher_lib.install's session factory with MirrorSession.

    Idempotent — safe to call on every install when the mirror is enabled.
    The patched factory always reads the current ``_PROXY`` at creation time,
    so a later ``set_proxy`` call takes effect on the next install.
    """
    global _PATCHED
    if _PATCHED:
        return
    import minecraft_launcher_lib.install as _inst

    _inst.requests.session = lambda: MirrorSession()  # type: ignore[attr-defined]
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
