"""ConsolePage — 游戏控制台（实时查看运行日志）。

实时 tail 正在运行的游戏日志文件（``<data_dir>/<instance_id>.log``），以
等宽字体、可过滤的面板展示——即 Ardot "Console" 设计稿的设计语言呈现。

只读 + 安全：纯文件尾部跟随，绝不向游戏进程注入任何输入。
"""
import os

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (QFont, QTextCursor, QDesktopServices,
                           QTextCharFormat, QColor)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit,
    QLineEdit, QApplication, QFileDialog, QLabel, QTextEdit,
)

from .theme import COLORS, F_SM
from .i18n import t
from . import ui_kit
from .win_rounded import toast, warn

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

        # ── 搜索行（round-77，对齐 Zaphyrous 日志面板）：搜索并高亮全部匹配，
        #    Enter 跳下一个；右侧「导出…」把当前（过滤后的）视图存成 .txt ──
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("console.search_placeholder"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._render)
        self._search.returnPressed.connect(self._find_next)
        search_row.addWidget(self._search, stretch=1)
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: {F_SM}px;")
        search_row.addWidget(self._count_lbl)
        search_row.addWidget(ui_kit.make_button(
            t("console.export"), kind="secondary", icon_key="export",
            on_click=self._export, min_h=32))
        root.addLayout(search_row)

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
        text = "\n".join(lines) + ("\n" if lines else "")
        # 内容没变化时不重建文本——否则每次 poll（1s）会重置选区、打断搜索选中
        if self._view.toPlainText() != text:
            self._view.setPlainText(text)
        self._apply_search_highlights()
        if self._autoscroll:
            cur = self._view.textCursor()
            cur.movePosition(QTextCursor.End)
            self._view.setTextCursor(cur)
            self._view.ensureCursorVisible()

    def _apply_search_highlights(self) -> None:
        """搜索词高亮全部匹配片段 + 更新匹配计数（round-77）。"""
        q = self._search.text().strip()
        if not q:
            self._view.setExtraSelections([])
            self._count_lbl.setText("")
            return
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(COLORS.get("accent_soft", "#EDE9FE")))
        cur = QTextCursor(self._view.document())
        hits = []
        while True:
            cur = self._view.document().find(q, cur)
            if cur.isNull():
                break
            e = QTextEdit.ExtraSelection()
            e.cursor = QTextCursor(cur)  # 拷贝；原 cursor 会被 find 复用
            e.format = fmt
            hits.append(e)
        self._view.setExtraSelections(hits)
        self._count_lbl.setText(t("console.search_count", n=len(hits)))

    def _find_next(self) -> None:
        """Enter：跳到下一个匹配；到底后从头再来一轮。"""
        q = self._search.text().strip()
        if not q:
            return
        if not self._view.find(q):
            cur = self._view.textCursor()
            cur.movePosition(QTextCursor.Start)
            self._view.setTextCursor(cur)
            self._view.find(q)

    def _export(self) -> None:
        """把当前视图（过滤后的展示结果）导出为 .txt 文件（round-77）。"""
        text = self._view.toPlainText()
        if not text.strip():
            toast(self, t("console.export"), t("console.export_empty"))
            return
        from datetime import datetime
        base = self._game_name or "console"
        base = "".join(c for c in base if c not in '<>:"/\\|?*').strip() or "console"
        default = f"{base}_{datetime.now():%Y%m%d-%H%M%S}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, t("console.export_title"), default,
            "Text Files (*.txt);;All Files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", errors="replace") as f:
                f.write(text)
        except OSError as e:
            warn(self, t("console.export"), t("console.export_fail", err=str(e)))
            return
        toast(self, t("console.export_done_title"),
              t("console.export_done", path=path))

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