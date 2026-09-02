"""ConsolePage — 游戏控制台（实时查看运行日志）。

实时 tail 正在运行的游戏日志文件（``<data_dir>/<instance_id>.log``），以
等宽字体、可过滤的面板展示——即 Ardot "Console" 设计稿的设计语言呈现。

只读 + 安全：纯文件尾部跟随，绝不向游戏进程注入任何输入。
"""
import os

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFont, QTextCursor, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit,
    QLineEdit, QApplication,
)

from .theme import COLORS
from .i18n import t
from . import ui_kit

_MONO = "Consolas", "Cascadia Mono", "Courier New"
# 超过该行数后只保留尾部，避免超大日志拖垮 UI 线程。
_MAX_LINES = 4000


class ConsolePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._log_path: str | None = None
        self._offset = 0
        self._game_name: str | None = None
        self._token: str = ""
        self._buffer = ""
        self._autoscroll = True
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ── header：标题 + 当前实例 + 工具按钮 ──
        self._auto_btn = ui_kit.make_button(
            t("console.autoscroll"), kind="secondary", icon_key="refresh",
            on_click=self._toggle_autoscroll, checkable=True, min_h=32)
        self._auto_btn.setChecked(True)
        self._header = ui_kit.page_header(
            t("console.title"), desc="", icon_key="console",
            action=[
                self._auto_btn,
                ui_kit.make_button(t("console.copy"), kind="secondary",
                                   icon_key="export", on_click=self._copy, min_h=32),
                ui_kit.make_button(t("console.open_folder"), kind="secondary",
                                   icon_key="folder", on_click=self._open_folder, min_h=32),
                ui_kit.make_button(t("console.clear"), kind="secondary",
                                   icon_key="delete", on_click=self._clear, min_h=32),
            ])
        self._sub = self._header.desc_lbl
        root.addWidget(self._header)

        # ── 过滤行 ──
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(t("console.filter_placeholder"))
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._render)
        root.addWidget(self._filter)

        # ── 日志面板 ──
        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setUndoRedoEnabled(False)
        self._view.setFont(QFont(list(_MONO), 12))
        self._view.setStyleSheet(
            f"QPlainTextEdit {{ background: {COLORS['bg_panel']}; "
            f"color: {COLORS['text_main']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 12px; padding: 12px; font-size: 12px; }}"
        )
        self._view.setPlaceholderText(t("console.empty"))
        root.addWidget(self._view, stretch=1)

    # ── 对外接口：绑定游戏日志 ──
    def set_game(self, log_path: str | None, game_name: str | None = None,
                 token: str = "") -> None:
        """游戏启动时调用：重置视图并开始 tail 该日志文件。

        ``token`` 为当前登录令牌（可选，round-71 借鉴 PCL-CE McLogFilter 的
        展示层打码）：console 里出现 accessToken / 用户名时打码，避免玩家
        录屏/截图分享日志时泄漏凭证。磁盘日志原样保留，崩溃分析不受影响。
        """
        self._log_path = log_path
        self._game_name = game_name
        self._token = token or ""
        self._offset = 0
        self._buffer = ""
        self._view.clear()
        if self._sub is not None and game_name:
            self._sub.setText(game_name)
        if log_path and os.path.isfile(log_path) and os.path.getsize(log_path):
            self._tick()
        self._poll.start()

    def set_game_finished(self, code: int | None = None) -> None:
        """游戏进程退出时调用：停止 tail 并追加结束标记。"""
        self._poll.stop()
        if code is not None:
            self._append_line(t("console.finished", code=code))
        else:
            self._append_line(t("console.stopped"))

    # ── 内部：尾部跟随 + 渲染 ──
    def _tick(self):
        path = self._log_path
        if not path:
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size < self._offset:          # 文件被截断/重建 → 从头
            self._offset = 0
        try:
            if size > self._offset:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._offset)
                    chunk = f.read()
                self._offset = size
                # round-71 展示层打码：accessToken / 用户名不在 console 露出
                from .log_mask import mask_launch_text
                self._buffer += mask_launch_text(chunk, self._token)
                self._render()
        except Exception:
            return

    def _append_line(self, text: str) -> None:
        self._buffer += text + "\n"
        self._render(force=True)

    def _render(self, force: bool = True):
        lines = self._buffer.splitlines()
        q = self._filter.text().strip().lower()
        if q:
            lines = [ln for ln in lines if q in ln.lower()]
        if len(lines) > _MAX_LINES:
            lines = lines[-_MAX_LINES:]
        self._view.setPlainText("\n".join(lines) + ("\n" if lines else ""))
        if self._autoscroll:
            cur = self._view.textCursor()
            cur.movePosition(QTextCursor.End)
            self._view.setTextCursor(cur)
            self._view.ensureCursorVisible()

    # ── 工具按钮 ──
    def _toggle_autoscroll(self):
        self._autoscroll = self._auto_btn.isChecked()

    def _copy(self):
        QApplication.clipboard().setText(self._view.toPlainText())

    def _clear(self):
        self._buffer = ""
        self._view.clear()

    def _open_folder(self):
        path = self._log_path
        if not path:
            return
        folder = os.path.dirname(path)
        if os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))