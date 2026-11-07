"""导出整合包（``.mrpack``）对话框。

入口在实例右键菜单「导出整合包」与编辑面板「高级」页。真正的打包逻辑在
:mod:`core.mrpack_export`，本文件只负责：填名字/版本/简介、勾选要带的内容、
选保存位置、后台打包 + 进度、失败提示。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from . import ui_kit
from .frameless import TitleBar
from .i18n import t
from .theme import COLORS
from .win_rounded import info, warn
from .worker import ProgressWorker


class ExportPackPanel(QWidget):
    """把当前实例导出成 Modrinth 整合包（**页内**，round-196）。

    round-195 之后实例编辑面板已经是页内的 —— 编辑面板里再 `exec()` 弹窗
    就是「页内套窗口」，最刺眼的一处。窗口壳 :class:`ExportPackDialog`
    保留给历史调用点。
    """

    closed = Signal()

    def __init__(self, parent, inst):
        super().__init__(parent)
        self._inst = inst
        self._worker = None
        self._done = False

        from .core.mrpack_export import PARTS, default_pack_name

        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # 页内模式不要 frameless 标题栏（页面自己有标题）→ 用普通标题标签
        self._title = self._label(t("export.title"))
        self._title.setStyleSheet(
            "font-size:15px;font-weight:700;color:%s;" % COLORS["text_main"])
        root.addWidget(self._title)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(11)

        # ── 元数据 ──
        lay.addWidget(self._label(t("export.name")))
        self.name_edit = QLineEdit(default_pack_name(inst))
        lay.addWidget(self.name_edit)

        row = QHBoxLayout()
        row.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(self._label(t("export.version")))
        self.ver_edit = QLineEdit("1.0.0")
        col.addWidget(self.ver_edit)
        row.addLayout(col, 1)
        col2 = QVBoxLayout()
        col2.setSpacing(6)
        col2.addWidget(self._label(t("export.game_version")))
        gv = QLabel((inst.game_version or "?") + " · " +
                    (inst.loader or "vanilla") +
                    (" " + inst.loader_version if inst.loader_version else ""))
        gv.setStyleSheet("color:%s;" % COLORS["text_main"])
        col2.addWidget(gv)
        row.addLayout(col2, 1)
        lay.addLayout(row)

        lay.addWidget(self._label(t("export.summary")))
        self.sum_edit = QLineEdit("")
        self.sum_edit.setPlaceholderText(t("export.summary_hint"))
        lay.addWidget(self.sum_edit)

        # ── 内容 ──
        sec = QLabel(t("export.parts"))
        sec.setStyleSheet("color:%s;font-size:12px;font-weight:600;"
                          "margin-top:4px;" % COLORS["text_main"])
        lay.addWidget(sec)
        self._boxes: dict[str, QCheckBox] = {}
        for key, _rel, _is_dir, default_on in PARTS:
            cb = QCheckBox(t("export.part_" + key))
            cb.setChecked(default_on)
            self._boxes[key] = cb
            lay.addWidget(cb)

        self.hint = QLabel(t("export.overrides_hint"))
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:%s;font-size:11px;" % COLORS["text_sub"])
        lay.addWidget(self.hint)

        # ── 目标文件 ──
        lay.addWidget(self._label(t("export.target")))
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.path_edit = QLineEdit(self._default_path(default_pack_name(inst)))
        # 长路径默认把光标放末尾 → 显示成「…\data\exports\x.mrpack」，盘符被吃掉
        self.path_edit.setCursorPosition(0)
        prow.addWidget(self.path_edit, 1)
        prow.addWidget(ui_kit.make_button(
            t("export.browse"), kind="secondary", icon_key="folder",
            on_click=self._pick_path, min_h=32))
        lay.addLayout(prow)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.bar.setTextVisible(True)
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:%s;font-size:11px;" % COLORS["text_sub"])
        lay.addWidget(self.status)

        lay.addStretch(1)

        foot = QHBoxLayout()
        foot.setSpacing(10)
        foot.addStretch(1)
        self.cancel_btn = ui_kit.make_button(
            t("common.cancel"), kind="secondary", on_click=self._on_cancel,
            min_h=36)
        self.ok_btn = ui_kit.make_button(
            t("export.run"), kind="accent", icon_key="export",
            on_click=self._start, min_h=36)
        foot.addWidget(self.cancel_btn)
        foot.addWidget(self.ok_btn)
        lay.addLayout(foot)

        root.addWidget(body, 1)

    # ── 小助手 ──
    @staticmethod
    def _label(text: str) -> QLabel:
        lb = QLabel(text)
        lb.setStyleSheet("color:%s;font-size:11px;" % COLORS["text_sub"])
        return lb

    def _default_path(self, base: str) -> str:
        try:
            from .paths import get_data_dir
            d = os.path.join(get_data_dir(), "exports")
        except Exception:  # noqa: BLE001
            d = os.path.expanduser("~")
        return os.path.join(d, base + ".mrpack")

    def _pick_path(self) -> None:
        p, _f = QFileDialog.getSaveFileName(
            self, t("export.target"), self.path_edit.text(),
            t("export.filter"))
        if p:
            if not p.lower().endswith(".mrpack"):
                p += ".mrpack"
            self.path_edit.setText(p)

    def _selected_parts(self) -> tuple:
        return tuple(k for k, cb in self._boxes.items() if cb.isChecked())

    # ── 执行 ──
    def _start(self) -> None:
        from .core.mrpack_export import export_mrpack

        parts = self._selected_parts()
        if not parts:
            warn(self, t("export.title"), t("export.nothing_checked"))
            return
        out = self.path_edit.text().strip()
        if not out:
            warn(self, t("export.title"), t("export.no_path"))
            return
        if not out.lower().endswith(".mrpack"):
            out += ".mrpack"
            self.path_edit.setText(out)
        if os.path.exists(out):
            from .win_rounded import confirm
            if not confirm(self, t("export.title"),
                           t("export.overwrite", name=os.path.basename(out))):
                return

        self.ok_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.status.setText(t("export.working"))

        self._worker = ProgressWorker(
            export_mrpack, self._inst, out,
            name=self.name_edit.text().strip(),
            version_id=self.ver_edit.text().strip() or "1.0.0",
            summary=self.sum_edit.text().strip(),
            parts=parts)
        self._worker.status.connect(self._on_status)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_status(self, text: str) -> None:
        self.status.setText(t("export.packing", name=str(text)))

    def _on_progress(self, value: int, maximum: int) -> None:
        if maximum and maximum > 1:
            self.bar.setRange(0, maximum)
            self.bar.setValue(value)

    def _on_done(self, result: dict) -> None:
        self._done = True
        self.bar.setVisible(False)
        self.ok_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        mb = (result.get("size") or 0) / (1024.0 * 1024.0)
        msg = t("export.done", n=result.get("files") or 0, mb="%.1f" % mb)
        skipped = result.get("skipped") or []
        if skipped:
            msg += "\n" + t("export.skipped", items=", ".join(skipped[:5]))
        self.status.setText(msg)
        # 页内模式用浮层提示（round-196：toast 已支持页内面板），
        # 路径写进状态行，不再弹模态框打断
        try:
            from .win_rounded import toast
            toast(self, t("export.title"), msg)
        except Exception:  # noqa: BLE001
            pass
        self.closed.emit()

    def _on_error(self, err: str) -> None:
        self.bar.setVisible(False)
        self.ok_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.status.setText("")
        warn(self, t("export.title"), t("export.failed", e=str(err)))

    def _on_cancel(self) -> None:
        """取消：页内模式通知外层返回。"""
        if self._worker is not None and self._worker.isRunning():
            warn(self, t("export.title"), t("export.busy"))
            return
        self.closed.emit()

    def closeEvent(self, ev) -> None:  # noqa: N802 - Qt 命名
        if self._worker is not None and self._worker.isRunning():
            warn(self, t("export.title"), t("export.busy"))
            ev.ignore()
            return
        super().closeEvent(ev)


class ExportPackDialog(QDialog):
    """**兼容壳**：窗口模式（历史调用点）。内部就是 :class:`ExportPackPanel`。"""

    def __init__(self, parent, inst):
        super().__init__(parent)
        self.setWindowTitle(t("export.title"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.panel = ExportPackPanel(self, inst)
        lay.addWidget(self.panel)
        self.panel.closed.connect(self.accept)

    def __getattr__(self, name):
        if name == "panel":
            raise AttributeError(name)
        return getattr(self.panel, name)
