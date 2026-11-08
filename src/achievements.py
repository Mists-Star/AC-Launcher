"""Achievements system (direction B 彩蛋, FMCL-style).

Lightweight, self-contained: achievement definitions, unlocked-state
persistence (data/achievements.json), a toast signal for the UI, and a
simple API for the rest of the launcher to fire events:

    from .achievements import achievements
    achievements.unlock("first_launch")

The achievements page lives in the ``achievements`` feature pack
(``assets/features/achievements/entry.py``) after the round-167 module split;
the toast overlay is owned by MainWindow (it connects to `achievements.toast`).
"""
import json
import os
import time

from PySide6.QtCore import QObject, Signal

from .paths import get_data_dir

# ── definitions ────────────────────────────────────────────────────────────
# id: (label_key, desc_key, category)
ACHIEVEMENTS: dict[str, tuple[str, str, str]] = {
    "first_launch":   ("ach.first_launch",   "ach.first_launch_desc",   "start"),
    "first_login":    ("ach.first_login",    "ach.first_login_desc",    "account"),
    "first_instance": ("ach.first_instance", "ach.first_instance_desc", "instance"),
    "first_mod":      ("ach.first_mod",      "ach.first_mod_desc",      "content"),
    "first_join":     ("ach.first_join",     "ach.first_join_desc",     "multiplayer"),
    "first_repair":   ("ach.first_repair",   "ach.first_repair_desc",   "repair"),
    "first_theme":    ("ach.first_theme",    "ach.first_theme_desc",    "custom"),
    "takeover_3":     ("ach.takeover_3",     "ach.takeover_3_desc",     "repair"),
    "playlist_5":     ("ach.playlist_5",     "ach.playlist_5_desc",     "custom"),
    "five_instances": ("ach.five_instances", "ach.five_instances_desc", "instance"),
}

CATEGORY_KEYS = ["start", "account", "instance", "content", "multiplayer", "repair", "custom"]


def _path() -> str:
    return os.path.join(get_data_dir(), "achievements.json")


class Achievements(QObject):
    """Singleton manager: unlock state + toast emission."""

    toast = Signal(str)  # achievement id — UI listens to show a notification

    def __init__(self):
        super().__init__()
        self._unlocked: dict[str, float] = {}
        self._load()

    # ---- persistence ----
    def _load(self) -> None:
        try:
            with open(_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("unlocked", {}) if isinstance(data, dict) else {}
            self._unlocked = {k: float(v) for k, v in raw.items()}
        except (OSError, json.JSONDecodeError, ValueError, TypeError,
                AttributeError):
            self._unlocked = {}

    def _save(self) -> None:
        """原子写 + 永不抛。

        round-217：原实现直接覆盖且不接异常——成就解锁发生在事件回调里，
        磁盘满 / 文件被占用会把异常抛进 UI 槽函数（Qt 里就是一条控制台
        traceback + 该回调后续逻辑全断）。成就丢了只是少个徽章，不该影响主流程。
        """
        p = _path()
        tmp = p + ".tmp"
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"unlocked": self._unlocked}, f,
                          ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ---- queries ----
    def is_unlocked(self, aid: str) -> bool:
        return aid in self._unlocked

    def progress(self) -> tuple[int, int]:
        return len(self._unlocked), len(ACHIEVEMENTS)

    # ---- trigger ----
    def unlock(self, aid: str) -> bool:
        """Mark an achievement unlocked. Returns True if newly unlocked
        (and emits the toast signal)."""
        if aid not in ACHIEVEMENTS or aid in self._unlocked:
            return False
        self._unlocked[aid] = time.time()
        self._save()
        self.toast.emit(aid)
        return True

    def reset(self) -> None:
        self._unlocked.clear()
        self._save()


achievements = Achievements()
