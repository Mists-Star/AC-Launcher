"""Skin library — local store of player skins + download from Mojang / third-party.

A "skin" is a 64x64 (or legacy 64x32) PNG. They live in data/skins/ with a
side-car metadata file (skins.json) describing each one and which skin is
active for which account. Skins can be imported from disk, downloaded by a
player name (resolved through Mojang, with mc-heads / crafatar fallbacks),
renamed, deleted, and assigned as the active skin of an account.

Nothing here touches the running game — the launcher only *displays* skins
(avatar + full-body preview) and remembers the player's choice. Actually
applying a custom skin in-game for online accounts is handled by Mojang
automatically; for offline accounts it requires a skin mod / server-side
plugin, which is out of scope for the library itself.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import uuid

from .paths import get_data_dir

_HEADERS = {"User-Agent": "AC-Launcher/0.2 (+https://github.com/)"}


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _http_bytes(url: str, timeout: int = 20) -> bytes:
    import urllib.request

    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _http_json(url: str, timeout: int = 20):
    import urllib.request

    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class SkinManager:
    def __init__(self):
        self._dir = os.path.join(get_data_dir(), "skins")
        os.makedirs(self._dir, exist_ok=True)
        self._meta = os.path.join(get_data_dir(), "skins.json")
        self._skins: dict[str, dict] = {}
        self._active: dict[str, str] = {}   # account_id -> skin_id
        self._load()

    # ---- persistence ----
    def _load(self) -> None:
        if not os.path.exists(self._meta):
            return
        try:
            with open(self._meta, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        for raw in data.get("skins", []):
            # drop skins whose file vanished
            if os.path.exists(os.path.join(self._dir, raw.get("file", ""))):
                self._skins[raw["id"]] = raw
        self._active = data.get("active", {})

    def _save(self) -> None:
        with open(self._meta, "w", encoding="utf-8") as f:
            json.dump(
                {"skins": list(self._skins.values()), "active": self._active},
                f, ensure_ascii=False, indent=2,
            )

    # ---- queries ----
    def list(self) -> list[dict]:
        return list(self._skins.values())

    def get(self, skin_id: str) -> dict | None:
        return self._skins.get(skin_id)

    def path_of(self, skin_id: str) -> str | None:
        s = self._skins.get(skin_id)
        return os.path.join(self._dir, s["file"]) if s else None

    def active_of(self, account_id: str) -> dict | None:
        sid = self._active.get(account_id)
        return self._skins.get(sid) if sid else None

    def active_path(self, account_id: str) -> str | None:
        s = self.active_of(account_id)
        return os.path.join(self._dir, s["file"]) if s else None

    # ---- mutations ----
    def add_file(self, src_path: str, name: str | None = None) -> dict:
        ext = os.path.splitext(src_path)[1].lower() or ".png"
        sid = _new_id()
        fname = sid + ext
        shutil.copyfile(src_path, os.path.join(self._dir, fname))
        skin = {
            "id": sid,
            "name": name or os.path.splitext(os.path.basename(src_path))[0],
            "source": "local",
            "player": "",
            "model": "auto",
            "file": fname,
        }
        self._skins[sid] = skin
        self._save()
        return skin

    def add_bytes(self, data: bytes, name: str, source: str,
                  player: str = "", model: str = "auto") -> dict:
        sid = _new_id()
        fname = sid + ".png"
        with open(os.path.join(self._dir, fname), "wb") as f:
            f.write(data)
        skin = {
            "id": sid, "name": name, "source": source,
            "player": player, "model": model, "file": fname,
        }
        self._skins[sid] = skin
        self._save()
        return skin

    def add_url(self, url: str, name: str | None = None) -> dict:
        """Download a skin PNG directly from a URL and store it locally.

        Lets the player paste a direct skin-image link (e.g. from a third-party
        skin site) instead of only searching by player name.
        """
        data = _http_bytes(url)
        if not data or len(data) < 64 or data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"链接不是有效的 PNG 皮肤：{url}")
        base = os.path.basename(url.split("?")[0]) or "skin"
        if name is None:
            name = os.path.splitext(base)[0] or "skin"
        return self.add_bytes(data, name, "download", player="", model="auto")

    def remove(self, skin_id: str) -> None:
        s = self._skins.pop(skin_id, None)
        if s:
            try:
                os.remove(os.path.join(self._dir, s["file"]))
            except OSError:
                pass
        for acc, sid in list(self._active.items()):
            if sid == skin_id:
                self._active.pop(acc, None)
        self._save()

    def rename(self, skin_id: str, name: str) -> None:
        s = self._skins.get(skin_id)
        if s:
            s["name"] = name
            self._save()

    def set_active(self, account_id: str, skin_id: str | None) -> None:
        if skin_id is None:
            self._active.pop(account_id, None)
        else:
            self._active[account_id] = skin_id
        self._save()

    # ---- download by player name ----
    def download(self, name: str) -> dict:
        """Resolve a player name to a skin and store it. Raises on failure."""
        name = name.strip()
        if not name:
            raise ValueError("玩家名为空")
        model = "auto"
        data = None
        # 1) Mojang: name -> uuid -> skin url
        try:
            prof = _http_json(
                f"https://api.mojang.com/users/profiles/minecraft/{name}"
            )
            uid = prof.get("id")
            if uid:
                pj = _http_json(
                    f"https://sessionserver.mojang.com/session/minecraft/"
                    f"profile/{uid}?unsigned=false"
                )
                tex = self._decode_texture(pj)
                if tex:
                    data = _http_bytes(tex["url"])
                    model = tex.get("model", "auto") or "auto"
                    player = name
        except Exception:
            data = None
        # 2) Fallback: mc-heads direct PNG
        if data is None:
            data = _http_bytes(f"https://mc-heads.net/skin/{name}")
            player = name
        if not data or len(data) < 64:
            raise ValueError(f"无法下载皮肤：{name}")
        return self.add_bytes(data, name, "download", player=player, model=model)

    def download_by_uuid(self, uuid: str, name: str) -> dict:
        """Download a skin directly from a Minecraft UUID (crafatar)."""
        uuid = uuid.replace("-", "")
        if not uuid:
            raise ValueError("UUID 为空")
        data = _http_bytes(f"https://crafatar.com/skins/{uuid}")
        if not data or len(data) < 64:
            raise ValueError(f"无法下载皮肤：{name}")
        return self.add_bytes(data, name or uuid, "download", player=name, model="auto")

    @staticmethod
    def _decode_texture(profile_json: dict) -> dict | None:
        for prop in profile_json.get("properties", []):
            if prop.get("name") != "textures":
                continue
            try:
                raw = base64.b64decode(prop["value"])
                tex = json.loads(raw.decode("utf-8"))
                skin = tex.get("textures", {}).get("SKIN")
                if skin and skin.get("url"):
                    return {
                        "url": skin["url"],
                        "model": skin.get("metadata", {}).get("model", "auto"),
                    }
            except Exception:
                return None
        return None


_manager = SkinManager()


def manager() -> SkinManager:
    return _manager
