"""Launch progress dialog — AC-style step list visible during pre-launch.

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
from .frameless import FramelessHelper, TitleBar
from .win_rounded import enable_win11_round_corners

# Step ordering (must match the keys emitted by src/launch.py `_emit_step`).
# The label is resolved lazily so retranslate_ui() keeps working.
STEPS = ["check", "install", "prepare", "precheck", "start"]
# round-107 T8 下载任务模式：实例创建后即后台下载，只需「安装 / 补齐」两步。
_DL_STEPS = ["install", "prepare"]

_STEP_KEYS = {
    "check": "launch.step.check",
    "install": "launch.step.install",
    "prepare": "launch.step.prepare",
    "precheck": "launch.step.precheck",
    "start": "launch.step.start",
}

# round-91 删除已迁移到 state_pix 的文本符号表 _GLYPH（未引用，残留）。
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

    def __init__(self, inst, parent=None, *, mode: str = "launch"):
        super().__init__(parent)
        # round-107 T8：mode="download" 复用同一套步骤列表/进度条范式，
        # 只显示「安装 / 补齐」两步（实例创建后即下载时使用）。
        self.mode = mode
        self._steps = list(_DL_STEPS if mode == "download" else STEPS)
        self.setWindowTitle(t("launch.download_title") if mode == "download"
                            else t("launch.title"))
        self.setModal(False)
        self.setMinimumWidth(460)
        self.setMaximumWidth(560)
        # 主题化对话框底色（QDialog 走 $bg_app_frost 主题 token）
        self.setProperty("cls", "card")

        # ── AC 无边框窗口：自定义标题栏 + 圆角 ──
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(
            self, title=(t("launch.download_title") if mode == "download"
                         else t("launch.title")), height=38, controls="close")
        root.addWidget(self.titlebar)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 12, 20, 14)
        lay.setSpacing(12)

        # ── header ──
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icon("play").pixmap(26, 26))
        head.addWidget(ic, 0, Qt.AlignLeft)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_lbl = QLabel(
            t("launch.download_sub", name=inst.name) if mode == "download"
            else t("launch.launching", name=inst.name))
        self.title_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {COLORS['text_main']};")
        titles.addWidget(self.title_lbl)
        self.sub_lbl = QLabel(t("launch.preparing"))
        self.sub_lbl.setProperty("cls", "sub")
        titles.addWidget(self.sub_lbl)
        head.addLayout(titles, 1)
        lay.addLayout(head)

        # ── step list ──
        self._glyphs: dict[str, QLabel] = {}
        self._rows: dict[str, QLabel] = {}
        self._modes: dict[str, str] = {}
        steps_box = QFrame()
        steps_box.setProperty("cls", "surface")
        sl = QVBoxLayout(steps_box)
        sl.setContentsMargins(14, 10, 14, 10)
        sl.setSpacing(6)
        for key in self._steps:
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.setSpacing(10)
            glyph = QLabel()
            glyph.setFixedWidth(18)
            from .ui_kit import state_pix
            glyph.setPixmap(state_pix("pending", COLORS["text_disabled"], 16))
            name = QLabel(t(_STEP_KEYS[key]))
            name.setStyleSheet(f"font-size: 13px; color: {COLORS['text_sub']};")
            self._glyphs[key] = glyph
            self._rows[key] = name
            self._modes[key] = self._MODE_PENDING
            rh.addWidget(glyph)
            rh.addWidget(name, 1)
            sl.addWidget(row)
        lay.addWidget(steps_box)

        # ── determinate download progress (only visible during install) ──
        # round-107：改 slim 主题条（去塑料感），百分比用旁侧标签显示。
        prog_row = QHBoxLayout()
        prog_row.setSpacing(10)
        self.bar = QProgressBar()
        self.bar.setProperty("cls", "slim")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setVisible(False)
        prog_row.addWidget(self.bar, 1)
        self.pct_lbl = QLabel("")
        self.pct_lbl.setProperty("cls", "sub")
        self.pct_lbl.setMinimumWidth(38)
        self.pct_lbl.setVisible(False)
        prog_row.addWidget(self.pct_lbl)
        lay.addLayout(prog_row)

        # ── round-110 A：实时速度行（mll 只给文件计数，拿不到字节数，
        #    所以这里显示的是传输层计量出的真实吞吐与累计字节）──
        self.speed_lbl = QLabel("")
        self.speed_lbl.setProperty("cls", "sub")
        self.speed_lbl.setVisible(False)
        lay.addWidget(self.speed_lbl)

        # ── status line ──
        self.status_lbl = QLabel(t("launch.status_unknown"))
        self.status_lbl.setProperty("cls", "sub")
        self.status_lbl.setWordWrap(True)
        lay.addWidget(self.status_lbl)

        # ── footer ──
        foot = QHBoxLayout()
        hint = QLabel(t("launch.download_hint") if mode == "download"
                      else t("launch.auto_close_hint"))
        hint.setStyleSheet(f"font-size: 11px; color: {COLORS['text_disabled']};")
        foot.addWidget(hint, 1)
        hide_btn = QPushButton(t("launch.hide_to_bg"))
        hide_btn.setCursor(Qt.PointingHandCursor)
        hide_btn.clicked.connect(lambda: self.hide())
        foot.addWidget(hide_btn)
        lay.addLayout(foot)

        root.addWidget(body, stretch=1)

        # ── frameless + DWM shadow + win11 rounded corners ──
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        enable_win11_round_corners(self)

        self._set_step(self._steps[0], running=True)

    # ── public API (driven from the UI thread via worker signals) ─────────
    def set_step(self, key: str):
        """Worker.step slot — light up the given stage, done-ify the previous."""
        key = key if key in self._modes else self._steps[0]
        prev_running = None
        for k in self._steps:
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
        self.bar.setVisible(True)
        self.pct_lbl.setVisible(True)
        if maximum and maximum > 0:
            v = max(0, min(value, maximum))
            self.bar.setMaximum(maximum)
            self.bar.setValue(v)
            self.pct_lbl.setText(f"{int(v * 100 / maximum)}%")
        else:
            self.bar.setMaximum(0)  # indeterminate
            self.pct_lbl.setText(t("launch.status_unknown"))

    def set_speed(self, text: str):
        """Worker.speed slot — 显示「1.2 MB/s · 已下载 34.5 MB」。"""
        self.speed_lbl.setText(_wrap(text or ""))
        self.speed_lbl.setVisible(bool(text))

    def mark_launched(self):
        """Game process spawned — flip every step to done (called by MainWindow)."""
        self.mark_done(t("launch.started"))

    def mark_done(self, subtitle: str = ""):
        """All steps done + optional subtitle (下载任务完成时也走这里）。"""
        for k in self._steps:
            self._mark(k, self._MODE_DONE)
        if subtitle:
            self.sub_lbl.setText(subtitle)

    # ── internals ───────────────────────────────────────────────────────────
    def _mark(self, key: str, mode: str):
        self._modes[key] = mode
        c = COLORS[_COLOR[mode]]
        from .ui_kit import state_pix
        self._glyphs[key].setPixmap(state_pix(mode, c, 16))
        self._glyphs[key].setStyleSheet("")
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