"""Unified, always-visible feedback for one-click repairs (round-209).

Three entry points used to report the same kind of action in three different
ways, which is exactly the "same feature, different page/logic" defect the
owner called out:

* ``CrashAnalyzerPanel`` — one small grey ``status`` label that the async
  worker overwrites, and which ``_on_analyzed`` can leave hidden. No dedicated
  result area at all.
* ``HealthPanel`` — a real in-page feedback bar (round-194).
* ``InstancesPage`` context menu — modal ``info()`` / ``warn()`` only. Those
  are ``QDialog``s; in a frameless window they can appear behind it, which is
  the exact "clicked, nothing happened / no hint" defect round-194 fixed for
  HealthPanel but never applied here.

One implementation: attach a :class:`FeedbackBar` to a panel (or let
:func:`report` fall back to the main window's floating toast), then always
call :func:`report`. Never blocking, never hidden behind a window.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from .i18n import t
from .theme import COLORS

_TONE_COLOR = {
    "info": COLORS.get("text_sub", "#6B7280"),
    "ok": "#16A34A",
    "warn": "#F59E0B",
    "busy": "#2563EB",
}


class FeedbackBar(QLabel):
    """A visible, non-blocking result strip. Hidden only when empty."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.PlainText)
        self.setVisible(False)
        self._apply_tone("info")

    def _apply_tone(self, tone: str) -> None:
        accent = _TONE_COLOR.get(tone, _TONE_COLOR["info"])
        self.setStyleSheet(
            "background:%s;border:1px solid %s;border-left:3px solid %s;"
            "border-radius:8px;padding:8px 10px;font-size:12px;color:%s;"
            % (COLORS.get("bg_frost", "#F3F4F6"),
               COLORS.get("border", "#E5E7EB"), accent,
               COLORS.get("text_main", "#111827")))

    def show_message(self, text: str, tone: str = "info") -> None:
        self.setText(text or "")
        self.setVisible(bool(text))
        self._apply_tone(tone)


def attach(layout, owner) -> FeedbackBar:
    """Create the bar, add it to ``layout`` and register it on ``owner``."""
    bar = FeedbackBar(owner)
    layout.addWidget(bar)
    owner.fix_note = bar
    return bar


def report(owner, text: str, tone: str = "info") -> None:
    """Show a repair result where the player can actually see it.

    Panel with ``fix_note`` -> in-page bar; otherwise -> main window's floating
    toast (``win_rounded._find_toast_host`` walks the whole parent chain, so a
    page inside the main window works); last resort -> the themed info box.
    """
    bar = getattr(owner, "fix_note", None)
    if bar is not None and hasattr(bar, "show_message"):
        bar.show_message(text, tone)
        return
    from .win_rounded import toast
    toast(owner, t("fix.title"), text, duration=4500)


def summarize(ok: int, fail: int, manual: int = 0) -> tuple[str, str]:
    """One structured terminal state -> (text, tone).

    ``t()`` silently leaves ``{placeholders}`` in place when a kwarg is missing,
    which would leak raw source tokens into the player UI, so every argument is
    always supplied here.
    """
    text = t("fix.summary", ok=ok, fail=fail, manual=manual)
    if manual:
        text += " " + t("fix.manual_hint", n=manual)
    tone = "warn" if fail else ("ok" if ok else "info")
    return text, tone
