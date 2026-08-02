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
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump({"entries": entries[-_MAX_ENTRIES:]}, f, ensure_ascii=False, indent=2)


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
