"""Last launch outcome per instance（上次会话失败）— Qt-free, persisted.

首页「需要留意」要回答「上次是不是没起来/崩了」，而崩溃弹窗一关这条
信息就没了。这里只存**最近一次**启动结果，供首页聚合读取：

    outcome: "starting" | "ok" | "failed" | "crashed"
    reason:  人读的一行原因（已本地化，截断 120 字）
    t:       记录时间

存储：``<data_dir>/last_session.json`` → ``{instance_id: {...}}``。
非关键数据：读写失败一律静默（首页跳过该条，不误报）。
"""
from __future__ import annotations

import json
import os
import time

from ..paths import get_data_dir

_MAX_REASON = 120


def _path() -> str:
    return os.path.join(get_data_dir(), "last_session.json")


def _load_all() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save_all(data: dict) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def record(instance_id: str, outcome: str, reason: str = "") -> None:
    """记下某实例最近一次启动结果（空 id 直接忽略）。"""
    iid = (instance_id or "").strip()
    if not iid:
        return
    data = _load_all()
    data[iid] = {
        "outcome": (outcome or "ok").strip(),
        "reason": (reason or "").strip()[:_MAX_REASON],
        "t": time.time(),
    }
    _save_all(data)


def load(instance_id: str) -> dict | None:
    """返回该实例最近一次记录；没有则 None。"""
    iid = (instance_id or "").strip()
    if not iid:
        return None
    rec = _load_all().get(iid)
    return rec if isinstance(rec, dict) else None


def clear(instance_id: str) -> None:
    iid = (instance_id or "").strip()
    if not iid:
        return
    data = _load_all()
    if iid in data:
        data.pop(iid, None)
        _save_all(data)
