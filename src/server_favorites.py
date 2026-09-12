"""Server favorites — stored list of multiplayer servers for one-click direct connect.

round-83: 收藏服务器一键直连。记录 {id, name, host, port, note} 到
``data/servers.json``（便携，原子写，与 accounts/instances 同策略）。
直连本身不做网络探测——启动时靠 Minecraft 的 ``--server/--port`` 参数，
由 ``launch.launch_instance(server_override=..., port_override=...)`` 注入。
"""
from __future__ import annotations

import json
import os
import time
import uuid

from .paths import get_data_dir
from .i18n import t

_PATH = os.path.join(get_data_dir(), "servers.json")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def load_servers() -> list[dict]:
    """全部收藏（无副作用；文件缺失/损坏返回空表）。"""
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return []
        out = []
        for raw in data.get("servers", []):
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            out.append({
                "id": raw["id"],
                "name": str(raw.get("name", "")),
                "host": str(raw.get("host", "")),
                "port": str(raw.get("port", "")),
                "note": str(raw.get("note", "")),
            })
        return out
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError, OSError):
        return []


def _save(servers: list[dict]) -> None:
    """原子写收藏列表（临时文件 + os.replace，防崩溃损坏）。"""
    tmp = _PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"servers": servers, "updated_at": time.time()},
                      f, ensure_ascii=False, indent=2)
        os.replace(tmp, _PATH)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def add_server(name: str, host: str, port: str = "", note: str = "") -> dict:
    """新增收藏（host 去空格；重名去重则更新）。返回存储条目。"""
    servers = load_servers()
    host = (host or "").strip()
    name = (name or host or t("server_fav.default_name")).strip()
    for s in servers:
        if s["host"] == host and s["port"] == (port or "").strip():
            s["name"] = name
            s["note"] = note or s.get("note", "")
            _save(servers)
            return s
    item = {"id": _new_id(), "name": name, "host": host,
            "port": (port or "").strip(), "note": note}
    servers.append(item)
    _save(servers)
    return item


def remove_server(sid: str) -> bool:
    servers = load_servers()
    nxt = [s for s in servers if s.get("id") != sid]
    if len(nxt) == len(servers):
        return False
    _save(nxt)
    return True


def update_server(sid: str, name: str, host: str, port: str = "", note: str = "") -> bool:
    servers = load_servers()
    for s in servers:
        if s.get("id") == sid:
            s["name"] = (name or s["name"]).strip()
            s["host"] = (host or s["host"]).strip()
            s["port"] = (port or "").strip()
            s["note"] = note
            _save(servers)
            return True
    return False