"""Log masking — strip access tokens & Windows usernames from shown logs.

Learned from mainstream practice: keep the first/last 5 chars of a
token, mask the middle, and never print the Windows user-name it might be
leaking. Applied at *display* boundaries (console page, crash evidence) —
the on-disk game log is left untouched so crash analysis keeps raw truth.
"""
from __future__ import annotations

import os

__all__ = ["mask_launch_text", "mask_secret"]

_MASK_CHAR = "*"


def _mask_middle(value: str, keep: int = 5) -> str:
    """Common practice: token[:keep] + '*'*(len-2*keep) + token[-keep:]."""
    if len(value) <= keep * 2:
        return _MASK_CHAR * len(value)
    return value[:keep] + _MASK_CHAR * (len(value) - keep * 2) + value[-keep:]


def _mask_access_token(text: str) -> str:
    """打码 ``accessToken <值>`` 之后的内容（对齐主流对启动命令行参数的过滤）。

    命令行里 token 与关键字间以空格分隔（``--accessToken <uuid>``），这里对
    ``accessToken `` 后续的第一个连续非空白段按「保留首尾 5 位」处理。
    """
    out = []
    i = 0
    while True:
        idx = text.find("accessToken ", i)
        if idx < 0:
            out.append(text[i:])
            break
        out.append(text[i: idx + len("accessToken ")])
        rest = text[idx + len("accessToken "):]
        j = 0
        while j < len(rest) and not rest[j].isspace():
            j += 1
        out.append(_mask_middle(rest[:j]))
        i = idx + len("accessToken ") + j
    return "".join(out)


def _mask_user_name(text: str) -> str:
    """打码当前 Windows 用户名出现的片段（主流同时会处理用户目录路径）。"""
    try:
        profile = os.path.expanduser("~")
        user = os.path.basename(os.path.normpath(profile))
    except Exception:  # noqa: BLE001 - 拿不到用户名就跳过打码
        return text
    if not user or len(user) < 2 or user.lower() in ("users", "home"):
        return text
    # 只替换「完整用户名」出现处，避免把路径里 C:\Users\xxx 误伤成 C:\Users\***
    # （仍会打码用户目录段，但保留分隔符位置，日志依旧可读）。
    return text.replace(user, _MASK_CHAR * len(user))


def mask_secret(text: str, secret: str) -> str:
    """打码一个具体敏感值（登录 token / UUID），保留首尾 5 位。

    与主流一致：长度 < 10 或与 UUID 相同的离线 token 不强制处理——
    但调用方可自行决定传入。空值/过短时原样返回。
    """
    if not secret or len(secret) < 10:
        return text
    if secret in text:
        text = text.replace(secret, _mask_middle(secret))
    return text


def mask_launch_text(text: str, token: str = "") -> str:
    """对要展示给玩家的日志文本统一打码。

    - 形如 ``accessToken xxx`` 的启动参数段（首尾各留 5 位）；
    - 当前登录的 token（若提供）；
    - Windows 用户名。
    """
    if not text:
        return text
    text = _mask_access_token(text)
    if token:
        text = mask_secret(text, token)
    return _mask_user_name(text)