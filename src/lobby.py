"""
Lobby — out-of-game multiplayer lobby system (v1: local, extensible to server).

Provides:
  · create_lobby(name, instance_id) → Lobby with invite code U/NNNN-AAAA-SSSS-EEEE
  · join_lobby(code) → Lobby or None
  · list_lobbies() → active lobbies
  · leave_lobby(lobby_id)

v1 stores state in data/lobbies.json (local only).
A future server backend would replace _store with HTTP calls.
"""
import json, os, random, time
from dataclasses import dataclass, field, asdict

from .paths import get_data_dir

_LOBBY_FILE = os.path.join(get_data_dir(), "lobbies.json")

# Code alphabet: unambiguous chars (no 0/O, 1/l/I)
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass
class Lobby:
    id: str
    name: str
    code: str                    # U/NNNN-AAAA-SSSS-EEEE (also the EasyTier network name)
    host: str = ""               # player name
    instance_id: str = ""
    secret: str = ""             # EasyTier network secret (auto-generated)
    members: list = field(default_factory=list)  # [{"name": ..., "joined_at": ...}]
    created_at: float = 0.0
    max_players: int = 8


def _load() -> dict:
    try:
        with open(_LOBBY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"lobbies": {}, "next_id": 1}


def _save(data: dict):
    os.makedirs(os.path.dirname(_LOBBY_FILE), exist_ok=True)
    with open(_LOBBY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _generate_code() -> str:
    """Generate a lobby code like U/NNNN-AAAA-SSSS-EEEE."""
    parts = [
        "".join(random.choices(_CODE_CHARS, k=4)),
        "".join(random.choices(_CODE_CHARS, k=4)),
        "".join(random.choices(_CODE_CHARS, k=4)),
        "".join(random.choices(_CODE_CHARS, k=4)),
    ]
    return f"U/{'-'.join(parts)}"


def _generate_secret() -> str:
    """Random 12-char network secret (EasyTier --network-secret)."""
    return "".join(random.choices(_CODE_CHARS, k=12))


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
        if raw.get("code", "").upper() == code.upper():
            raw["members"].append({"name": player, "joined_at": time.time()})
            _save(data)
            return Lobby(**raw)
    return None


def list_lobbies() -> list[Lobby]:
    """List all active lobbies."""
    data = _load()
    return [Lobby(**raw) for raw in data["lobbies"].values()]


def leave_lobby(lobby_id: str, player: str = "Player"):
    """Remove a player from a lobby. If empty, delete it."""
    data = _load()
    raw = data["lobbies"].get(lobby_id)
    if not raw:
        return
    raw["members"] = [m for m in raw.get("members", []) if m.get("name") != player]
    if not raw["members"]:
        del data["lobbies"][lobby_id]
    _save(data)


def get_lobby(lobby_id: str) -> Lobby | None:
    """Get a single lobby by ID."""
    data = _load()
    raw = data["lobbies"].get(lobby_id)
    return Lobby(**raw) if raw else None
