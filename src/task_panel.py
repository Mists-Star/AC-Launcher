"""任务列表页内分区：把 TaskCenter 的进行中记录与历史可视化。

不做成弹窗——和 StoreDetailPanel 一样挂进资源中心的页内栈，点「返回」回列表。
TaskCenter 保持 Qt-free（纯 Python + 锁，可被后台线程直接写），因此这里用
定时轮询而不是给数据层加 Qt 信号；面板不可见时不轮询。
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QScrollArea, QVBoxLayout, QWidget)

from . import ui_kit
from .core import task_center as tc
from .i18n import t
from .theme import COLORS

_STATE_KEY = {
    tc.STATE_QUEUED: "tasks.state_queued",
    tc.STATE_RUNNING: "tasks.state_running",
    tc.STATE_PAUSED: "tasks.state_paused",
    tc.STATE_DONE: "tasks.state_done",
    tc.STATE_FAILED: "tasks.state_failed",
    tc.STATE_CANCELLED: "tasks.state_cancelled",
}
_KIND_KEY = {
    "download": "tasks.kind_download",
    "launch": "tasks.kind_launch",
    "import": "tasks.kind_import",
    "install": "tasks.kind_install",
    "repair": "tasks.kind_repair",
    "update": "tasks.kind_update",
}


def _state_color(state: str) -> str:
    if state == tc.STATE_FAILED:
        return COLORS["danger"]
    if state == tc.STATE_DONE:
        return COLORS["success"]
    if state in (tc.STATE_PAUSED, tc.STATE_CANCELLED):
        return COLORS["warn"]
    return COLORS["accent"]


def _stamp(rec) -> str:
    ts = rec.updated_at or rec.created_at
    if not ts:
        return ""
    try:
        return time.strftime("%H:%M", time.localtime(ts))
    except (OSError, OverflowError, ValueError):
        return ""


class _TaskRow(QFrame):
    """一条任务：状态 / 标题 / 阶段或失败原因 / 进度 / 就地操作。"""

    def __init__(self, rec, panel: "TaskListPanel"):
        super().__init__()
        self.setProperty("cls", "card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        state_text = t(_STATE_KEY.get(rec.state, "tasks.state_running"))
        top.addWidget(ui_kit.tag(state_text, _state_color(rec.state),
                                 COLORS["text_main"], font_size=10,
                                 pad="2px 8px"))
        title = QLabel(rec.label or t("tasks.kind_other"))
        title.setProperty("cls", "th")
        top.addWidget(title, 1)
        kind = QLabel(t(_KIND_KEY.get(rec.kind, "tasks.kind_other")))
        kind.setProperty("cls", "sub")
        top.addWidget(kind)
        stamp = _stamp(rec)
        if stamp:
            s = QLabel(stamp)
            s.setProperty("cls", "sub")
            top.addWidget(s)
        lay.addLayout(top)

        if rec.state in (tc.STATE_FAILED, tc.STATE_CANCELLED, tc.STATE_DONE):
            detail = (rec.detail or "").strip()
        else:
            detail = (rec.stage or "").strip()
        if detail:
            d = QLabel(detail)
            d.setProperty("cls", "sub")
            d.setWordWrap(True)
            if rec.state == tc.STATE_FAILED:
                d.setStyleSheet("color:%s;" % COLORS["danger"])
            lay.addWidget(d)
        if rec.sources:
            self.setToolTip(t("tasks.sources") + "：" + " → ".join(rec.sources))

        if rec.state in tc._OPEN_STATES:
            bar = QProgressBar()
            bar.setFixedHeight(6)
            bar.setTextVisible(False)
            if rec.total > 0:
                bar.setRange(0, rec.total)
                bar.setValue(max(0, min(rec.total, rec.completed)))
            else:
                bar.setRange(0, 0)
            lay.addWidget(bar)

        actions = QHBoxLayout()
        actions.addStretch(1)
        if rec.retry_key and rec.state in (tc.STATE_FAILED, tc.STATE_CANCELLED):
            actions.addWidget(ui_kit.make_button(
                t("tasks.retry"), kind="secondary",
                on_click=lambda *_: panel.retry_requested.emit(rec.retry_key),
                min_h=26))
        if rec.target_page:
            actions.addWidget(ui_kit.make_button(
                t("tasks.goto"), kind="secondary",
                on_click=lambda *_: panel.navigate_requested.emit(rec.target_page),
                min_h=26))
        if actions.count() > 1:
            lay.addLayout(actions)


class TaskListPanel(QWidget):
    """进行中 + 历史任务的页内分区（非弹窗、非模态）。"""

    back_requested = Signal()
    retry_requested = Signal(str)      # retry_key（实例 id）
    navigate_requested = Signal(str)   # nav key

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        back = ui_kit.make_button(
            t("common.back"), kind="secondary",
            on_click=lambda *_: self.back_requested.emit(), min_h=32)
        head.addWidget(back)
        title = QLabel(t("tasks.title"))
        title.setProperty("cls", "title")
        head.addWidget(title)
        head.addStretch(1)
        self.summary = QLabel("")
        self.summary.setProperty("cls", "sub")
        head.addWidget(self.summary)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._host = QWidget()
        self._rows = QVBoxLayout(self._host)
        self._rows.setContentsMargins(0, 0, 4, 0)
        self._rows.setSpacing(8)
        self._rows.addStretch(1)
        scroll.setWidget(self._host)
        root.addWidget(scroll, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.clear_btn = ui_kit.make_button(
            t("tasks.clear_history"), kind="secondary",
            on_click=lambda *_: self._clear(), min_h=32)
        foot.addWidget(self.clear_btn)
        root.addLayout(foot)

        self._timer = QTimer(self)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def refresh(self):
        center = tc.get_task_center()
        running = center.running()
        recent = center.recent(20)
        self.summary.setText(t("tasks.summary", n=len(running)))
        self.clear_btn.setEnabled(bool(recent))
        while self._rows.count() > 1:
            item = self._rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not running and not recent:
            empty = QLabel(t("tasks.empty"))
            empty.setProperty("cls", "sub")
            empty.setAlignment(Qt.AlignCenter)
            self._rows.insertWidget(0, empty)
            return
        for heading, rows in ((t("tasks.running"), running),
                              (t("tasks.recent"), recent)):
            if not rows:
                continue
            h = QLabel(heading)
            h.setProperty("cls", "title")
            self._rows.insertWidget(self._rows.count() - 1, h)
            for rec in rows:
                self._rows.insertWidget(self._rows.count() - 1,
                                        _TaskRow(rec, self))

    def _clear(self):
        tc.get_task_center().clear_history()
        self.refresh()
