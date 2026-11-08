"""
Lobby — out-of-game multiplayer lobby system (v1: local, extensible to server).

Provides:
  · create_lobby(name, instance_id) → Lobby with invite code U/NNNN-AAAA-SSSS-EEEE
  · join_lobby(code) → Lobby or None
  · list_lobbies() → active lobbies
  · leave_lobby(lobby_id)

v1 stores state in data/lobbies.json (local only).
A future server backend would replace _store with HTTP calls.

round-215：
  · ``secret`` 是 EasyTier 的**网络口令**，不再明文落盘 —— 与账户 token 一样走
    DPAPI；加密失败就不写该字段（宁可让旧大厅失效，也不把口令写在 json 里）。
  · 邀请码 / 口令改用 ``secrets``（原来是 ``random.choices``，Mersenne Twister）。
  · 写盘改 tmp + ``os.replace``（原来直接 ``open(...,"w")``，断电会截断）。
  · ``Lobby(**raw)`` 过滤未知字段，旧版本/脏数据不会再 TypeError。
"""
import dataclasses
import json
import os
import secrets
import time
from dataclasses import dataclass, field, asdict

from .paths import get_data_dir

# Code alphabet: unambiguous chars (no 0/O, 1/l/I)
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_SECRET_PREFIX = "dpapi:"


def _lobby_file() -> str:
    # 函数内取路径：AC_DEV_TEMP=1 时 get_data_dir() 每次是新临时目录，
    # 模块级快照会让「创建」与「读取」落在不同目录（features.py / net_api.py
    # 已经踩过并缓存过这个坑）。
    return os.path.join(get_data_dir(), "lobbies.json")


@dataclass
class Lobby:
    id: str
    name: str
    code: str                    # U/NNNN-AAAA-SSSS-EEEE (also the EasyTier network name)
    host: str = ""               # player name
    instance_id: str = ""
    secret: str = ""             # EasyTier network secret (encrypted at rest)
    members: list = field(default_factory=list)  # [{"name": ..., "joined_at": ...}]
    created_at: float = 0.0
    max_players: int = 8


_FIELDS = {f.name for f in dataclasses.fields(Lobby)}


def _lobby_from(raw) -> "Lobby | None":
    """脏数据容错：非 dict / 缺必填 / 多了未知字段都跳过，不让 UI 崩。"""
    if not isinstance(raw, dict):
        return None
    data = {k: v for k, v in raw.items() if k in _FIELDS}
    try:
        return Lobby(**data)
    except TypeError:
        return None


def _seal(secret: str) -> str:
    """落盘前加密网络口令；DPAPI 不可用则返回空（绝不写明文）。"""
    if not secret:
        return ""
    try:
        from .win_dpapi import dpapi_encrypt
        enc = dpapi_encrypt(secret)
        return _SECRET_PREFIX + enc if enc else ""
    except Exception:  # noqa: BLE001 - 加密能力缺失 → 不落盘
        return ""


def _unseal(value) -> str:
    if not isinstance(value, str) or not value:
        return ""
    if value.startswith(_SECRET_PREFIX):
        try:
            from .win_dpapi import dpapi_decrypt
            return dpapi_decrypt(value[len(_SECRET_PREFIX):]) or ""
        except Exception:  # noqa: BLE001
            return ""
    return value  # 旧明文记录：兼容读取，下次 _save 会加密


def _load() -> dict:
    path = _lobby_file()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"lobbies": {}, "next_id": 1}
    if not isinstance(data, dict):
        return {"lobbies": {}, "next_id": 1}
    if not isinstance(data.get("lobbies"), dict):
        data["lobbies"] = {}
    try:
        data["next_id"] = max(1, int(data.get("next_id") or 1))
    except (TypeError, ValueError):
        data["next_id"] = 1
    for raw in data["lobbies"].values():
        if isinstance(raw, dict):
            raw["secret"] = _unseal(raw.get("secret"))
    return data


def _save(data: dict):
    path = _lobby_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 逐条加密 secret 后再写；深拷贝避免修改调用方内存里的明文
    out = {"next_id": data.get("next_id", 1), "lobbies": {}}
    for lid, raw in (data.get("lobbies") or {}).items():
        if not isinstance(raw, dict):
            continue
        copy = dict(raw)
        plain = copy.get("secret") or ""
        if plain and not str(plain).startswith(_SECRET_PREFIX):
            sealed = _seal(plain)
            if sealed:
                copy["secret"] = sealed
            else:
                copy.pop("secret", None)
        out["lobbies"][lid] = copy
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _generate_code() -> str:
    """Generate a lobby code like U/NNNN-AAAA-SSSS-EEEE."""
    parts = [
        "".join(secrets.choice(_CODE_CHARS) for _ in range(4))
        for _ in range(4)
    ]
    return f"U/{'-'.join(parts)}"


def _generate_secret() -> str:
    """Random 12-char network secret (EasyTier --network-secret)."""
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(12))


def create_lobby(name: str, instance_id: str = "", host: str = "Player") -> Lobby:
    """Create a new lobby and return it."""
    data = _load()
    lid = str(data["next_id"])
    data["next_id"] += 1
    code = _generate_code()
    now = time.time()
    lob = Lobby(
        id=lid,
        name=name,
        code=code,
        host=host,
        instance_id=instance_id,
        secret=_generate_secret(),
        members=[{"name": host, "joined_at": now}],
        created_at=now,
    )
    data["lobbies"][lid] = asdict(lob)
    _save(data)
    return lob


def join_lobby(code: str, player: str = "Player") -> Lobby | None:
    """Join an existing lobby by code. Returns Lobby or None if not found."""
    data = _load()
    for lid, raw in data["lobbies"].items():
        if not isinstance(raw, dict):
            continue
        if str(raw.get("code", "")).upper() == code.upper():
            members = raw.get("members")
            if not isinstance(members, list):
                members = []
            if not any(isinstance(m, dict) and m.get("name") == player
                       for m in members):
                members.append({"name": player, "joined_at": time.time()})
            raw["members"] = members
            _save(data)
            return _lobby_from(raw)
    return None


def list_lobbies() -> list[Lobby]:
    """List all active lobbies."""
    data = _load()
    out = []
    for raw in data["lobbies"].values():
        lob = _lobby_from(raw)
        if lob is not None:
            out.append(lob)
    return out


def leave_lobby(lobby_id: str, player: str = "Player"):
    """Remove a player from a lobby. If empty, delete it."""
    data = _load()
    raw = data["lobbies"].get(lobby_id)
    if not isinstance(raw, dict):
        return
    members = raw.get("members")
    if not isinstance(members, list):
        members = []
    raw["members"] = [m for m in members
                      if not (isinstance(m, dict) and m.get("name") == player)]
    if not raw["members"]:
        del data["lobbies"][lobby_id]
    _save(data)
