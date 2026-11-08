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
round-168: 中止任务改由底部「取消下载 / 取消启动」按钮显式触发
（``cancel_requested`` 信号），主窗口确认后才真正 abort。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
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


def _guard_dead(fn):
    """槽函数保护：对话框的 C++ 对象被销毁后再收到 worker 信号，一律静默。

    round-217：`set_progress` / `set_speed` / `set_step` / `set_status_text` /
    `set_sources` 之前没有这层保护，而其它几个 setter 有 —— 关掉进度框之后
    worker 还在发进度（下载要几秒才收尾）就会在控制台刷 RuntimeError。
    """
    def _inner(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except RuntimeError:      # C++ 对象已删除
            return None
    _inner.__name__ = getattr(fn, "__name__", "guarded")
    _inner.__doc__ = fn.__doc__
    return _inner


class LaunchProgressDialog(QDialog):
    status = Signal(str)
    progress = Signal(int, int)  # value, max
    # round-168：玩家点了「取消下载 / 取消启动」→ 主窗口弹确认后 abort worker。
    cancel_requested = Signal()
    # round-170：下载任务可暂停 / 继续 / 失败后重试（启动准备阶段不提供暂停）。
    pause_requested = Signal()
    resume_requested = Signal()
    retry_requested = Signal()

    _MODE_PENDING, _MODE_RUNNING, _MODE_DONE = "pending", "running", "done"

    def __init__(self, inst, parent=None, *, mode: str = "launch"):
        super().__init__(parent)
        # round-107 T8：mode="download" 复用同一套步骤列表/进度条范式，
        # 只显示「安装 / 补齐」两步（实例创建后即下载时使用）。
        self.mode = mode
        self._fitting = False
        self._cancelling = False
        self._finished = False      # 成功/失败/取消后关闭即销毁（round-217）
        self._paused = False
        self._failed = False
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

        # ── round-155：来源链行（哪个源失败、最后走通哪个）──
        self.sources_lbl = QLabel("")
        self.sources_lbl.setProperty("cls", "sub")
        self.sources_lbl.setWordWrap(True)
        self.sources_lbl.setVisible(False)
        lay.addWidget(self.sources_lbl)

        # ── footer ──
        foot = QHBoxLayout()
        hint = QLabel(t("launch.download_hint") if mode == "download"
                      else t("launch.auto_close_hint"))
        hint.setStyleSheet(f"font-size: 11px; color: {COLORS['text_disabled']};")
        self.hint_lbl = hint
        foot.addWidget(hint, 1)
        # round-168：显式中止入口（确认由主窗口弹，未确认时按钮保持可用）。
        self.cancel_btn = QPushButton(
            t("launch.cancel_download") if mode == "download"
            else t("launch.cancel_launch"))
        self.cancel_btn.setProperty("cls", "secondary")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        foot.addWidget(self.cancel_btn)
        self.hide_btn = QPushButton(t("launch.hide_to_bg"))
        self.hide_btn.setCursor(Qt.PointingHandCursor)
        self.hide_btn.clicked.connect(lambda: self.hide())
        foot.addWidget(self.hide_btn)
        # round-170：暂停 / 继续（只在下载任务显示）+ 失败后的重试。
        self.pause_btn = QPushButton(t("launch.pause_download"))
        self.pause_btn.setProperty("cls", "secondary")
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        self.pause_btn.setVisible(mode == "download")
        foot.insertWidget(1, self.pause_btn)
        self.retry_btn = QPushButton(t("launch.retry_download"))
        self.retry_btn.setCursor(Qt.PointingHandCursor)
        self.retry_btn.clicked.connect(self._on_retry_clicked)
        self.retry_btn.setVisible(False)
        foot.insertWidget(1, self.retry_btn)
        lay.addLayout(foot)

        root.addWidget(body, stretch=1)

        # ── frameless + DWM shadow + win11 rounded corners ──
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        enable_win11_round_corners(self)

        self._set_step(self._steps[0], running=True)
        self._apply_static_heights()

    # ── public API (driven from the UI thread via worker signals) ─────────
    @_guard_dead
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

    @_guard_dead
    def set_status_text(self, text: str):
        """Worker.status slot — show the latest (truncated) status message."""
        self.status_lbl.setText(_wrap(text))
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: 12px;")
        # round-151：文案换行后需要的高度可能变化 → 立即补足，避免下一拍被裁。
        self._fit_text_heights()

    def _apply_static_heights(self) -> None:
        """单行标签一次性定高；换行标签给 2~5 行的硬区间（round-163）。

        像素字体的 ascent/descent 与 QSS 行高不一致，单行标签只拿到
        ``fontMetrics().height()`` 会被裁掉上下半截——这里按字体度量补足。
        换行标签则直接设最大高度：再长的文本也只占 5 行，布局永远无法
        把它反向推动成「窗口向下无限延伸」。
        """
        for lbl in (self.title_lbl, self.sub_lbl, self.speed_lbl,
                    self.hint_lbl, *self._rows.values()):
            fm = lbl.fontMetrics()
            line = max(fm.lineSpacing(), fm.height())
            lbl.setMinimumHeight(line + 6)
        fm = self.status_lbl.fontMetrics()
        line = max(fm.lineSpacing(), fm.height())
        for lbl in (self.status_lbl, self.sources_lbl):
            lbl.setMinimumHeight(line * 2 + 4)
            lbl.setMaximumHeight(line * 5 + 4)

    def _fit_text_heights(self) -> None:
        """按对话框宽度补足换行标签高度（幂等、有界）。

        round-163 修复「窗口无限向下延伸」：旧实现在 ``resizeEvent`` 里用
        ``lbl.width()`` 反复 ``setMinimumHeight``，标签变高 → 布局请求更高
        → 窗口 resize → 标签宽度变化 → 需要更高，形成正反馈。现在：
        - 宽度只取对话框内容宽（与标签当前分配无关，不随 resize 抖动）；
        - 只在高度值真的变化时写入（幂等，断开反馈环）；
        - 高度钳制在 2~5 行，最坏情况也有界。
        """
        if self._fitting:
            return
        self._fitting = True
        try:
            avail = max(240, self.width() - 42)  # body 左右 margin 20 + 余量 2
            for lbl in (self.status_lbl, self.sources_lbl):
                fm = lbl.fontMetrics()
                line = max(fm.lineSpacing(), fm.height())
                need = lbl.heightForWidth(avail)
                lo, hi = line * 2 + 4, line * 5 + 4
                h = min(max(need, lo), hi)
                if h != lbl.minimumHeight():
                    lbl.setMinimumHeight(h)
        except RuntimeError:
            # round-217：本函数既在 resizeEvent 里跑、也被 QTimer.singleShot(0)
            # 排队 —— 对话框已经销毁时那拍仍会到，访问 self.width() 就抛。
            return
        finally:
            self._fitting = False

    def closeEvent(self, event):  # noqa: N802 - Qt 约定
        # round-217：已结束的进度框没有召回价值（任务中心另有记录），关掉就销毁，
        # 别让每个实例的进度框永久挂在主窗口下面。进行中的仍然只 hide()，
        # 以便状态栏点击召回。
        try:
            if self._finished:
                self.setAttribute(Qt.WA_DeleteOnClose, True)
        except RuntimeError:
            pass
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # 等首次布局完成、对话框宽度确定后再算一次（延后一拍避免 0 宽）。
        QTimer.singleShot(0, self._fit_text_heights)

    @_guard_dead
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

    @_guard_dead
    def set_speed(self, text: str):
        """Worker.speed slot — 显示「1.2 MB/s · 已下载 34.5 MB」。"""
        self.speed_lbl.setText(_wrap(text or ""))
        self.speed_lbl.setVisible(bool(text))

    @_guard_dead
    def set_sources(self, text: str):
        """round-155：显示来源链（失败源 + 最后成功源）；空串隐藏。"""
        text = (text or "").strip()
        if text == self.sources_lbl.text() and bool(text) == self.sources_lbl.isVisible():
            return
        self.sources_lbl.setText(_wrap(text, 90))
        self.sources_lbl.setVisible(bool(text))
        self._fit_text_heights()

    def set_cancelling(self, text: str = ""):
        """round-168：已确认取消，进入收尾（禁用按钮，防止重复点击）。"""
        if self._cancelling:
            return
        self._cancelling = True
        try:
            self.cancel_btn.setEnabled(False)
            self.hide_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.retry_btn.setEnabled(False)
        except RuntimeError:  # C++ 对象已删除
            return
        self.status_lbl.setText(text or t("launch.cancelling"))
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: 12px;")

    # round-170：暂停 / 继续 / 重试三态。按钮文案与可用性都在这里收口，
    # 主窗口只负责真正的 worker 控制与任务记录。
    def mark_paused(self, text: str = ""):
        """下载已暂停（对话框保留）→ 按钮变成「继续下载」。"""
        self._paused = True
        self._failed = False
        try:
            self.pause_btn.setText(t("launch.resume_download"))
            self.pause_btn.setEnabled(True)
            self.pause_btn.setVisible(self.mode == "download")
            self.retry_btn.setVisible(False)
            self.cancel_btn.setText(
                t("launch.cancel_download") if self.mode == "download"
                else t("launch.cancel_launch"))
            self.cancel_btn.setEnabled(True)
            self.hide_btn.setEnabled(True)
        except RuntimeError:  # C++ 对象已删除
            return
        self.status_lbl.setText(text or t("launch.dl_paused"))
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: 12px;")
        self._fit_text_heights()

    def mark_resumed(self, text: str = ""):
        """从暂停回到进行中 → 按钮恢复「暂停下载」。"""
        self._paused = False
        self._failed = False
        try:
            self.pause_btn.setText(t("launch.pause_download"))
            self.pause_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setVisible(False)
        except RuntimeError:  # C++ 对象已删除
            return
        self.status_lbl.setText(text or t("launch.resuming"))
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: 12px;")

    def mark_failed(self, err: str = ""):
        """下载失败 → 对话框保留，显示「重试下载」，取消按钮改为「关闭」。"""
        self._failed = True
        self._paused = False
        try:
            self.pause_btn.setVisible(False)
            self.retry_btn.setVisible(self.mode == "download")
            self.retry_btn.setEnabled(True)
            self.cancel_btn.setText(t("common.close"))
            self.cancel_btn.setEnabled(True)
            self.hide_btn.setEnabled(True)
        except RuntimeError:  # C++ 对象已删除
            return
        self.status_lbl.setText(
            t("launch.dl_failed_retry", err=err) if err
            else t("launch.dl_failed_retry", err="—"))
        # round-177：失败必须有醒目终态。此前用灰色小字 + 仍在跑的
        # indeterminate 进度条 + 残留速度数字，用户误以为还在下载而重复点。
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['danger']}; font-size: 12px; font-weight: 600;")
        try:
            self.set_speed("")
            self.bar.setMaximum(1)
            self.bar.setValue(0)
            self.pct_lbl.setText("—")
        except RuntimeError:  # C++ 对象已删除
            return
        self._fit_text_heights()

    def _on_pause_clicked(self):
        """暂停 → 继续；点击后先禁用按钮，防止连点发出两次请求。"""
        try:
            self.pause_btn.setEnabled(False)
        except RuntimeError:
            return
        if self._paused:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit()

    def _on_retry_clicked(self):
        try:
            self.retry_btn.setEnabled(False)
            self.retry_btn.setVisible(False)
        except RuntimeError:
            return
        self.retry_requested.emit()

    def _on_cancel_clicked(self):
        """失败/完成后的取消按钮 = 关闭；其余情况发出取消请求。"""
        if self._failed:
            self.close()
            return
        self.cancel_requested.emit()

    def mark_cancelled(self, text: str = ""):
        """round-168：任务已取消——只改状态文案，不点亮步骤（避免假「完成」）。"""
        self._finished = True
        try:
            self.cancel_btn.setEnabled(False)
            self.pause_btn.setVisible(False)
            self.retry_btn.setVisible(False)
        except RuntimeError:  # C++ 对象已删除
            return
        self.status_lbl.setText(text or t("launch.cancelled"))
        self.status_lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: 12px;")

    def mark_launched(self):
        """Game process spawned — flip every step to done (called by MainWindow)."""
        self.mark_done(t("launch.started"))

    def mark_done(self, subtitle: str = ""):
        """All steps done + optional subtitle (下载任务完成时也走这里）。"""
        self._finished = True
        for k in self._steps:
            self._mark(k, self._MODE_DONE)
        try:
            self.pause_btn.setVisible(False)
            self.retry_btn.setVisible(False)
        except RuntimeError:  # C++ 对象已删除
            pass
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