"""Microsoft account login — Authorization Code flow with a local loopback.

A working default client_id is shipped (Microsoft's first-party Xbox app ID,
which supports personal Microsoft accounts and the desktop browser flow), so
login works out of the box with NO Azure app registration required. For a
production build, register your own Azure AD app and keep the value in
Settings → Advanced → 微软应用 ID (it overrides this).

Flow: the launcher opens the Microsoft sign-in page in the user's browser;
after login, Microsoft redirects back to http://127.0.0.1:7890/ (a tiny local
HTTP server we spin up), we grab the `code`, exchange it for tokens, then do
the XBL → XSTS → Minecraft → profile exchange.

The returned profile dict is what the rest of the launcher consumes:
    {"id": uuid, "name": username, "access_token": ..., "refresh_token": ...,
     "skins": [...], "capes": [...]}
"""
from __future__ import annotations

import time
import re
import secrets
import threading
import http.server
import urllib.parse

import requests

# Default: Microsoft's first-party Xbox app client ID. Supports personal
# Microsoft accounts via the browser/authorization-code flow. Overridable via
# Settings. We use the tenant-agnostic `/common/` endpoint because this app is
# a first-party Microsoft app whose grants live in Microsoft's own tenant, not
# the `consumers` tenant (using `/consumers/` yields AADSTS7000012).
MICROSOFT_CLIENT_ID = "00000000402b12d1"
# Xbox 第一方应用专用 scope（00000000402b12d1 是 MC Java 版 Xbox 客户端 ID）。
# 2026-08-01 实测修正：普通 Azure 注册应用（含 AC launcher 自建应用）登录
# Minecraft 必须用标准 XboxLive.signin scope，而不是 Minecraft 第一方专用的
# `service::user.auth.xboxlive.com::MBI_SSL`（那只认 MC 官方客户端
# 00000000402b12d1，自建应用用它会被拒为 invalid_scope / 127）。
# 各主流启动器用自建 Azure 应用时均为：XboxLive.signin offline_access。
MICROSOFT_SCOPE = "XboxLive.signin offline_access"

# 2026-08 微软登录可用性：
# Microsoft 已撤回所有免注册的公共 client_id。
# 老的 login.live.com/oauth20_authorize.srf 报 "client does not exist"。
# 新的 Microsoft Identity Platform (login.microsoftonline.com) 需要玩家在 Azure
# 注册应用 + admin consent 后才能登录正版服（主流启动器均已要求玩家这么做）。
# 因此微软登录按钮在 settings 里配置了有效 Azure client_id 后才会显示。
# 离线模式和外置登录（LittleSkin 等）始终可用。
def get_active_client_id(cfg: dict | None = None) -> str | None:
    """Return the client_id AC should use for Microsoft login.

    Priority:
      1. cfg["ms_client_id"] — player's own Azure app registration (settings).
      2. Built-in brand MS_CLIENT_ID — the AC launcher Azure app (registered by
         the project; always valid).  This makes Microsoft login available out
         of the box without any configuration.
    Returns None only if both sources are missing/invalid.
    """
    try:
        if cfg:
            cid = (cfg.get("ms_client_id") or "").strip()
            import re
            if cid and re.match(
                r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", cid
            ):
                return cid
    except Exception:
        pass
    try:
        from ..brand import MS_CLIENT_ID as _builtin
        if _builtin:
            return _builtin
    except Exception:
        pass
    return None


def microsoft_login_available(cfg: dict | None = None) -> bool:
    """True iff Microsoft login can be offered (built-in ID always valid)."""
    return get_active_client_id(cfg) is not None

_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
_XBL_URL = "https://user.auth.xboxlive.com/user/authenticate"
_XSTS_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
_MC_AUTH_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
_MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"

_UA = {"user-agent": "MC-Launcher/0.1"}

# ---- Known-invalid client IDs ----
# Obvious placeholders + Microsoft's own Azure Portal app (c44b4083...) which
# only works for tenant members — never user-specific IDs.
_BAD_CLIENT_IDS = {
    # Placeholder / all-zero GUID (the module default)
    "00000000-0000-0000-0000-000000000000",
    # Azure Portal's own app – only works for its tenant members
    "c44b4083-3bb0-49c1-b47d-974e53cbdf3c",
}

# ---- AADSTS error code → human-readable Chinese message ----
_AADSTS_MESSAGES = {
    "AADSTS16000": (
        "你的微软账号在当前应用的租户中不存在。\n"
        "原因：当前使用的 client_id 被限制（例如 Azure Portal 自带的应用 ID、或你手动填入的 ID 不属于个人账号类型）。\n"
        "解决：清空设置里的「微软应用 ID」（留空会用内置可用的默认值），或直接填入你自己注册的 Azure 应用 ID。"
    ),
    "AADSTS700016": (
        "client_id 无效或未授权此操作。\n"
        "请检查设置中的「微软应用 ID」是否正确。"
    ),
    "AADSTS50020": (
        "登录的账户类型与不匹配（例如用了组织账户登录个人应用）。\n"
        "请确保使用个人 Microsoft 账户（非工作/学校账户）登录。"
    ),
    "AADSTS65001": (
        "用户未同意所需的权限。\n"
        "请在浏览器授权页面点击「同意」后再试。"
    ),
}


class MicrosoftAuthError(Exception):
    pass


def validate_client_id(client_id: str) -> str | None:
    """Return a warning message if *client_id* looks invalid, else None.

    An empty value is OK — it means "use the built-in working default".
    The built-in first-party Xbox ID is a 16-hex-digit legacy identifier (not a
    GUID), so it must be whitelisted explicitly or the GUID regex below would
    reject our own default and block every login with a red error.
    """
    cid = (client_id or "").strip().lower()
    if not cid:
        return None  # empty → use built-in default (already valid)
    if cid == MICROSOFT_CLIENT_ID.lower():
        return None  # our built-in default: always fine
    if re.fullmatch(r"[0-9a-f]{16}", cid):
        return None  # other Microsoft legacy first-party IDs
    if cid in _BAD_CLIENT_IDS:
        return (
            "当前微软应用 ID 是占位符，无法登录。\n\n"
            "两个选择：\n"
            "  · 清空该字段 → 使用启动器内置的可用默认值（推荐，立即可用）\n"
            "  · 或注册自己的 Azure AD 应用并填入其「应用程序(客户端) ID」"
        )
    # Be lenient: any string of hex digits + dashes is plausible.
    # Microsoft itself does the strict GUID check on the OAuth side and
    # returns a clear error — better that our local validator not block
    # a near-correct value the user copy-pasted.
    if not re.match(r"^[0-9a-f][0-9a-f-]+[0-9a-f]$", cid):
        return f"微软应用 ID 格式不对（应仅含 0-9 a-f 与短横线），当前值：{client_id}"
    return None


# --------------------------------------------------------------------------
# Microsoft login — Device Code flow (OAuth 2.0 RFC 8628)，主流同款。
#
# 关键：端点必须用 /consumers/（个人 Microsoft 账户租户），不能用 /common/！
# ba522940（Xbox 第一方应用）是 consumers 租户的应用，用 /common/ 会报
# AADSTS700011 "scope not configured for this tenant"。
# 参考主流实现：deviceCodeURL/tokenURL 均为
# https://login.microsoftonline.com/consumers/oauth2/v2.0/{devicecode,token}
# --------------------------------------------------------------------------
_DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"


# (build_auth_url removed — replaced by device-code flow)


# (exchange_code_for_tokens removed — replaced by device-code flow)


# (loopback HTTP server removed — device-code flow doesn't need it)


def _xbl(access_token: str) -> dict:
    r = requests.post(
        _XBL_URL,
        json={
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": f"d={access_token}",
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        },
        headers={**_UA, "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _xsts(xbl_token: str) -> dict:
    r = requests.post(
        _XSTS_URL,
        json={
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        },
        headers={**_UA, "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _mc_login(xsts_token: str, uhs: str) -> dict:
    """Exchange an XSTS token for a Minecraft access token.

    Uses ``login_with_xbox`` (the XSTS-token endpoint), NOT ``login_with_mc_profile``
    (which expects a username+password Mojang account). Adding
    ``ensureLegacyEnabled: true`` keeps the Mojang-session-server path working
    for old launchers / chat reporting — same payload mainstream launchers send.
    """
    r = requests.post(
        _MC_AUTH_URL,
        json={
            "identityToken": f"XBL3.0 x={uhs};{xsts_token}",
            "ensureLegacyEnabled": True,
        },
        headers={**_UA, "Content-Type": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _mc_profile(mc_token: str) -> dict:
    r = requests.get(
        _MC_PROFILE_URL,
        headers={**_UA, "Authorization": f"Bearer {mc_token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def request_device_code(client_id: str) -> dict:
    """POST /devicecode → returns dict with device_code/user_code/verification_uri/interval/expires_in.

    The caller should display user_code + open verification_uri in a browser
    then call :func:`poll_for_token` until the player finishes auth.
    """
    r = requests.post(
        _DEVICE_CODE_URL,
        data={"client_id": client_id, "scope": MICROSOFT_SCOPE},
        headers=_UA,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def poll_for_token(client_id: str, device_code: str, interval: int = 5,
                   expires_in: int = 900, cancel=None) -> dict:
    """Poll the token endpoint until the user completes authorization.

    Returns the full token dict (``access_token``, ``refresh_token``, etc.).
    Raises :class:`MicrosoftAuthError` on denial/timeout.  Honors *cancel*
    (returns ``None`` if set).
    """
    deadline = time.time() + expires_in
    while time.time() < deadline:
        # Sleep the poll interval, but wake immediately on cancel
        # (Event.wait is interruptible, time.sleep is not — a long sleep would
        # keep the worker alive after the user pressed Cancel and let Qt emit
        # into a destroyed dialog → 0xC0000409).
        if cancel is not None:
            if cancel.wait(timeout=interval):
                return None
        else:
            time.sleep(interval)
        r = requests.post(
            _TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            },
            headers=_UA,
            timeout=10,  # short: poll interval is 5s, so a hung request must
                         # not pile up or keep the worker alive forever
        )
        data = r.json()
        if "access_token" in data:
            return data
        err = data.get("error", "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5  # RFC 8628 §3.5: client MUST back off
            continue
        desc = data.get("error_description", err)
        m = re.search(r"AADSTS\d+", desc)
        if m and m.group() in _AADSTS_MESSAGES:
            raise MicrosoftAuthError(_AADSTS_MESSAGES[m.group()])
        raise MicrosoftAuthError(desc or err or "登录失败")
    raise MicrosoftAuthError("登录超时（未在限定时间内完成浏览器授权，请重试）")


def complete_login_with_token(client_id: str, token: dict) -> dict:
    """Take a token dict (from device-code flow) and complete the XBL→XSTS→MC chain."""
    access_token = token["access_token"]
    xbl = _xbl(access_token)
    xbl_token = xbl["Token"]
    uhs = xbl["DisplayClaims"]["xui"][0]["uhs"]
    xsts = _xsts(xbl_token)
    xsts_token = xsts["Token"]
    mc = _mc_login(xsts_token, uhs)
    mc_token = mc["access_token"]
    try:
        profile = _mc_profile(mc_token)
    except requests.HTTPError:
        raise MicrosoftAuthError("该微软账户未拥有 Minecraft（或区域不可用）")
    profile["access_token"] = mc_token
    profile["refresh_token"] = token.get("refresh_token", "")
    profile["ms_access_token"] = access_token
    return profile


def login_with_microsoft(client_id: str, cancel=None) -> dict:
    """Device-code flow end-to-end. Blocking — run inside a Worker thread."""
    code = request_device_code(client_id)
    token = poll_for_token(
        client_id,
        code["device_code"],
        interval=code.get("interval", 5),
        expires_in=code.get("expires_in", 900),
        cancel=cancel,
    )
    if token is None:
        raise MicrosoftAuthError("登录已取消")
    return complete_login_with_token(client_id, token)


def login_with_microsoft_code_display(
    client_id: str, on_user_code, cancel=None
) -> dict:
    """Device-code flow that also reports the 8-char user_code + verification URL.

    ``on_user_code(user_code, verification_uri)`` is called as soon as the
    device code is issued, so the UI can show the code + open the browser
    *before* polling starts.
    """
    code = request_device_code(client_id)
    try:
        on_user_code(code["user_code"], code.get("verification_uri", ""))
    except Exception:
        pass  # UI callback must never break the login flow
    token = poll_for_token(
        client_id,
        code["device_code"],
        interval=code.get("interval", 5),
        expires_in=code.get("expires_in", 900),
        cancel=cancel,
    )
    if token is None:
        raise MicrosoftAuthError("登录已取消")
    return complete_login_with_token(client_id, token)


# --------------------------------------------------------------------------
# Third-party / external auth (Yggdrasil / Authlib-Injector)
#
# Many private servers and "外置登录" providers expose a Yggdrasil-compatible
# auth server (wiki.vg Authentication). We POST to its /authserver/authenticate
# to get an accessToken + selected profile, then launch the game with the
# authlib-injector javaagent (see launch.build_options) so Minecraft talks to
# that server instead of Mojang's.
# --------------------------------------------------------------------------
import uuid as _uuid


# ══════════════════════════════════════════════════════════════════════════
# 微软 token 静默续期（round-34 修复 P1-5）
# ── 之前 refresh_token 存了但从未使用：微软 access_token 约 2h 过期，
#    过期后只能重新完整走设备码登录。现在用 refresh_token 静默换新 token，
#    再重走 XBL→XSTS→MC 链路，无用户交互。
# ══════════════════════════════════════════════════════════════════════════
# round-40 P1 修复：与登录端点（_TOKEN_URL/devicecode 均 /consumers/）一致，
# 内置 Xbox client（consumers 租户）用 /common/ 会 AADSTS700011 导致静默续期失效。
_TOKEN_REFRESH_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"


def refresh_microsoft(profile: dict) -> dict | None:
    """Silently refresh an expired Microsoft session via ``refresh_token``.

    Returns an updated profile dict (same shape as ``complete_login_with_token``
    的输出 + 保留原 id)，或 None（refresh_token 缺失 / 刷新被拒 / 网络异常）——
    调用方回退到完整交互登录即可，绝不让刷新失败抛异常。
    """
    refresh_token = (profile.get("refresh_token") or "").strip()
    if not refresh_token:
        return None
    try:
        r = requests.post(
            _TOKEN_REFRESH_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": MICROSOFT_CLIENT_ID,
                "refresh_token": refresh_token,
                "scope": MICROSOFT_SCOPE,
            },
            headers=_UA,
            timeout=30,
        )
        data = r.json()
        if "access_token" not in data:
            return None  # 刷新被拒（token 失效/撤销）→ 需重新登录
        new_profile = complete_login_with_token(MICROSOFT_CLIENT_ID, data)
        # 保留原账号 id，避免刷新后账号身份漂移
        new_profile["id"] = profile.get("id", new_profile.get("id", ""))
        return new_profile
    except Exception:  # noqa: BLE001 - 静默刷新失败绝不能崩
        return None


def _client_token() -> str:
    return str(_uuid.uuid4())


def yggdrasil_login(server: str, username: str, password: str) -> dict:
    """Authenticate against an external Yggdrasil auth server.

    ``server`` is the base URL (e.g. https://auth.example.com). Returns a
    profile dict compatible with the rest of the launcher:
        {"id": uuid, "name": username, "access_token": ..., "type": "yggdrasil",
         "server": "https://auth.example.com"}
    Raises MicrosoftAuthError on failure (bad server, wrong creds, HTTP error).
    """
    base = server.rstrip("/")
    url = f"{base}/authserver/authenticate"
    payload = {
        "agent": {"name": "Minecraft", "version": 1},
        "username": username,
        "password": password,
        "requestUser": True,
        "clientToken": _client_token(),
    }
    try:
        r = requests.post(
            url,
            json=payload,
            headers={**_UA, "Content-Type": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise MicrosoftAuthError(f"外置登录请求失败：{e}") from e
    except ValueError:
        raise MicrosoftAuthError("外置登录服务器返回了无效响应")

    token = data.get("accessToken")
    prof = data.get("selectedProfile") or (data.get("availableProfiles") or [None])[0]
    if not token or not prof:
        raise MicrosoftAuthError("外置登录失败：服务器未返回有效账户")
    return {
        "id": prof.get("id", ""),
        "name": prof.get("name", username),
        "access_token": token,
        "type": "yggdrasil",
        "server": base,
    }
