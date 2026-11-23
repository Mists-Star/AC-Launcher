"""体检发现项的「忽略」清单（round-248）。

为什么需要：扫描/体检的判据是启发式的，玩家实例"明明能玩却被报问题"
（典型：加载器 id 命名特殊、外来整合包布局）。允许玩家按发现项忽略误报，
避免每次体检都被同一条假阳性淹没。

落盘：``<data>/health_ignored.json``，格式::

    {"<instance_id>": {"<finding签名>": {"at": 时间戳, "title": 文案}}}

签名用 ``kind`` + 关键 meta（文件名/版本）做稳定哈希；升级/翻译改动不会
让忽略失效，但同一类问题在不同实例上互不串扰。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

_LOCK = __import__("threading").RLock()
_CACHE: dict[str, dict] | None = None


def _file() -> str:
    from ..paths import get_data_dir
    return os.path.join(get_data_dir(), "health_ignored.json")


def signature(inst_id: str, finding: Any) -> str:
    """给一条 finding 算稳定签名（kind + 相关 meta，不含 i18n 文案）。"""
    kind = str(getattr(finding, "kind", "") or "")
    meta = getattr(finding, "meta", None)
    if not isinstance(meta, dict):
        meta = {}
    # 只取有辨识度的键，避免时间戳/路径这类易变字段让签名漂移
    keys = ("loader", "version", "base", "dep", "need", "jar", "id",
            "filename", "project_id", "source", "kind")
    parts = [f"{k}={meta[k]}" for k in keys
             if k in meta and meta[k] not in (None, "")]
    raw = "|".join([kind] + sorted(parts))
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{inst_id}:{kind}:{h}"


def load() -> dict[str, dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    with _LOCK:
        data: dict[str, dict] = {}
        try:
            with open(_file(), "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                data = {str(k): v for k, v in obj.items()
                        if isinstance(v, dict)}
        except (OSError, ValueError):
            pass
        _CACHE = data
        return data


def _save(data: dict[str, dict]) -> None:
    import tempfile
    path = _file()
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".health_ignored-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def is_ignored(inst_id: str, finding: Any) -> bool:
    return signature(inst_id, finding) in load().get(inst_id, {})


def add(inst_id: str, finding: Any, title: str = "") -> str:
    with _LOCK:
        data = load()
        bucket = data.setdefault(inst_id, {})
        sig = signature(inst_id, finding)
        bucket[sig] = {"at": int(time.time()), "title": str(title or "")}
        _save(data)
    return sig


def remove(inst_id: str, finding: Any) -> bool:
    with _LOCK:
        data = load()
        bucket = data.get(inst_id, {})
        sig = signature(inst_id, finding)
        if sig not in bucket:
            return False
        del bucket[sig]
        if not bucket:
            data.pop(inst_id, None)
        _save(data)
    return True


def clear_instance(inst_id: str) -> int:
    with _LOCK:
        data = load()
        n = len(data.pop(inst_id, {}))
        if n:
            _save(data)
    return n


def ignored_count(inst_id: str) -> int:
    return len(load().get(inst_id, {}))
