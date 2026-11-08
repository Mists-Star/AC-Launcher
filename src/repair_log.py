"""Repair log — lightweight, append-only JSON record of auto-repair actions.

Feeds the "修复日志流" on the home page (direction A: 控制中枢叙事). Every
auto-repair the launcher performs (mod dependency download, crash fix, batch
repair…) appends one entry; the home page renders the most recent few as a
scrolling stream, giving players a "this launcher actually fixes things" feel.

Storage: <data_dir>/repair_log.json  →  {"entries": [{...}]}
"""
import json
import os
import time

from .paths import get_data_dir

_MAX_ENTRIES = 200


def _path() -> str:
    return os.path.join(get_data_dir(), "repair_log.json")


def _load() -> list[dict]:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        return entries if isinstance(entries, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(entries: list[dict]) -> None:
    """原子写：先写 .tmp 再 os.replace。

    round-217：原实现直接 open(...,"w") 覆盖。修复日志是**每次自动修复都会写**
    的高频小文件，写到一半被杀（关窗 / 崩溃 / 断电）就留下半截 JSON，下一次
    `_load()` 解析失败返回 []，玩家之前攒的整条修复记录全部消失。
    """
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"entries": entries[-_MAX_ENTRIES:]}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def append(kind: str, summary: str, *, instance: str = "", detail: str = "") -> None:
    """Append one repair-log entry.

    kind: short machine tag ("mod_dep" | "crash" | "batch" | "import"…)
    summary: one-line human-readable message (already localized by caller).
    instance: instance name the action applied to (optional).
    detail: optional extra line shown in the stream tooltip.
    """
    entries = _load()
    entries.append({
        "t": time.time(),
        "kind": kind,
        "summary": summary,
        "instance": instance,
        "detail": detail,
    })
    _save(entries)


def list_recent(limit: int = 10) -> list[dict]:
    """Most-recent-first entries, newest at index 0."""
    entries = _load()
    return list(reversed(entries[-limit:]))


def clear() -> None:
    _save([])
