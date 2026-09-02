"""Launch progress dialog — HMCL/PCL2-style step list visible during pre-launch.

Shows the stages of ``launch_instance`` as a list of checkpoints:

    · 检查启动环境（目录 / Java）
    · 安装 / 修复游戏版本
    · 补齐缺失库与原生文件
    · 启动前模组冲突预检
    · 启动游戏

Each row lights up as the corresponding stage starts (driven by launch.py's
``callback["setStep"]``), the mll download progress (`setProgress`/`setMax`)
drives a determinate bar during install, and raw status text (`setStatus`)
shows in the footer. The window only covers the *preparation* phase — as soon
as the game process spawns, MainWindow closes it.

Closing / hiding the dialog does NOT abort the launch: the ProgressWorker keeps
running and the status bar (indeterminate progress) is the fallback surface.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QFrame, QWidget,
)

from .theme import COLORS
from .i18n import t
from .icons import icon

# Step ordering (must match the keys emitted by src/launch.py `_emit_step`).
# The label is resolved lazily so retranslate_ui() keeps working.
STEPS = ["check", "install", "prepare", "precheck", "start"]

_STEP_KEYS = {
    "check": "launch.step.check",
    "install": "launch.step.install",
    "prepare": "launch.step.prepare",
    "precheck": "launch.step.precheck",
    "start": "launch.step.start",
}

_GLYPH = {"pending": "○", "running": "▶", "done": "✔"}
_COLOR = {"pending": "text_disabled", "running": "accent", "done": "success"}


def _wrap(text: str, width: int = 60) -> str:
    """Ellipsis-truncate long status lines (mll emits file paths sometimes)."""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


class LaunchProgressDialog(QDialog):
    status = Signal(str)
    progress = Signal(int, int)  # value, max

    _MODE_PENDING, _MODE_RUNNING, _MODE_DONE = "pending", "running", "done"

    def __init__(self, inst, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("launch.title"))
        self.setModal(False)
        self.setMinimumWidth(460)
        self.setMaximumWidth(560)
        # 毛玻璃友好的对话框底色（QDialog 走 $bg_app_frost，透底时半透明）
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("cls", "card")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        # ── header ──
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icon("play").pixmap(26, 26))
        head.addWidget(ic, 0, Qt.AlignLeft)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_lbl = QLabel(t("launch.launching", name=inst.name))
        self.title_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {COLORS['text_main']};")
        titles.addWidget(self.title_lbl)
        self.sub_lbl = QLabel(t("launch.preparing"))
        self.sub_lbl.setProperty("cls", "sub")
        titles.addWidget(self.sub_lbl)
        head.addLayout(titles, 1)
        root.addLayout(head)

        # ── step list ──
        self._glyphs: dict[str, QLabel] = {}
        self._rows: dict[str, QLabel] = {}
        self._modes: dict[str, str] = {}
        steps_box = QFrame()
        steps_box.setProperty("cls", "surface")
        sl = QVBoxLayout(steps_box)
        sl.setContentsMargins(14, 10, 14, 10)
        sl.setSpacing(6)
        for key in STEPS:
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.setSpacing(10)
            glyph = QLabel("○")
            glyph.setFixedWidth(18)
            glyph.setStyleSheet(
                f"font-size: 14px; color: {COLORS['text_disabled']}; font-weight: 700;")
            name = QLabel(t(_STEP_KEYS[key]))
            name.setStyleSheet(f"font-size: 13px; color: {COLORS['text_sub']};")
            self._glyphs[key] = glyph
            self._rows[key] = name
            self._modes[key] = self._MODE_PENDING
            rh.addWidget(glyph)
            rh.addWidget(name, 1)
            sl.addWidget(row)
        root.addWidget(steps_box)

        # ── determinate download progress (only visible during install) ──
        self.bar = QProgressBar()
        # round-53 下载进度可见化：显示百分比数字（对齐 PCL2/HMCL 下载面板）
        self.bar.setTextVisible(True)
        self.bar.setFormat("%p%")
        self.bar.setFixedHeight(14)
        self.bar.setVisible(False)
        root.addWidget(self.bar)

        # ── status line ──
        self.status_lbl = QLabel(t("launch.status_unknown"))
        self.status_lbl.setProperty("cls", "sub")
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        # ── footer ──
        foot = QHBoxLayout()
        hint = QLabel(t("launch.auto_close_hint"))
        hint.setStyleSheet(f"font-size: 11px; color: {COLORS['text_disabled']};")
        foot.addWidget(hint, 1)
        hide_btn = QPushButton(t("launch.hide_to_bg"))
        hide_btn.setCursor(Qt.PointingHandCursor)
        hide_btn.clicked.connect(lambda: self.hide())
        foot.addWidget(hide_btn)
        root.addLayout(foot)

        self._set_step("check", running=True)

    # ── public API (driven from the UI thread via worker signals) ─────────
    def set_step(self, key: str):
        """Worker.step slot — light up the given stage, done-ify the previous."""
        key = key if key in self._modes else STEPS[0]
        prev_running = None
        for k in STEPS:
            if self._modes[k] == self._MODE_RUNNING:
                prev_running = k
        self._set_step(key, running=True)
        if prev_running and prev_running != key:
            self._mark(prev_running, self._MODE_DONE)

    def set_status_text(self, text: str):
        """Worker.status slot — show the latest (truncated) status message."""
        self.status_lbl.setText(_wrap(text))
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: 12px;")

    def set_progress(self, value: int, maximum: int):
        """Worker.progress slot — determinate bar while installing."""
        if maximum and maximum > 0:
            self.bar.setVisible(True)
            self.bar.setMaximum(maximum)
            self.bar.setValue(max(0, min(value, maximum)))
        else:
            self.bar.setVisible(True)
            self.bar.setMaximum(0)  # indeterminate
        self.bar.setStyleSheet(
            f"QProgressBar {{ background: {COLORS['bg_input']}; border: none; "
            f"border-radius: 7px; color: {COLORS['text_sub']}; font-size: 9px; "
            f"text-align: center; }}"
            f"QProgressBar::chunk {{ background: {COLORS['accent']}; "
            f"border-radius: 7px; }}")

    def mark_launched(self):
        """Game process spawned — flip every step to done (called by MainWindow)."""
        for k in STEPS:
            self._mark(k, self._MODE_DONE)
        self.sub_lbl.setText(t("launch.started"))

    # ── internals ───────────────────────────────────────────────────────────
    def _mark(self, key: str, mode: str):
        self._modes[key] = mode
        c = COLORS[_COLOR[mode]]
        self._glyphs[key].setText(_GLYPH[mode])
        self._glyphs[key].setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {c};")
        if mode == self._MODE_RUNNING:
            self._rows[key].setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {COLORS['accent']};")
        elif mode == self._MODE_DONE:
            self._rows[key].setStyleSheet(
                f"font-size: 13px; color: {COLORS['text_main']};")
        else:
            self._rows[key].setStyleSheet(
                f"font-size: 13px; color: {COLORS['text_disabled']};")

    def _set_step(self, key: str, running: bool):
        self._mark(key, self._MODE_RUNNING if running else self._MODE_PENDING)