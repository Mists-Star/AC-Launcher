"""Diagnostics & repair center — a frameless dialog.

On open it runs ``run_diagnostics()`` on a worker thread and renders one card
per check (status dot + title + detail + optional Repair button). "Re-check"
re-runs the scan; "Repair All" heals every repairable, non-OK check in one pass.
Repairs that download game files / the authlib jar run on a worker so the UI
never freezes.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QStatusBar, QFileDialog,
)
from PySide6.QtCore import QSize

from .theme import COLORS, RoundedCard
from .icons import icon
from .i18n import t
from .frameless import FramelessHelper, TitleBar
from .paths import get_data_dir
from .win_rounded import info
from .worker import Worker
from . import diagnostics as diag
from .core import support_bundle as sb

_STATUS_COLOR = {
    diag.STATUS_OK: COLORS["success"],
    diag.STATUS_WARN: COLORS["warn"],
    diag.STATUS_ERROR: COLORS["danger"],
    diag.STATUS_SKIP: COLORS["text_disabled"],
}
_STATUS_LABEL_KEY = {
    diag.STATUS_OK: "diag.st.ok",
    diag.STATUS_WARN: "diag.st.warn",
    diag.STATUS_ERROR: "diag.st.error",
    diag.STATUS_SKIP: "diag.st.skip",
}


class _Row(RoundedCard):
    def __init__(self, result: diag.CheckResult, on_repair):
        super().__init__(radius=10)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        dot = QLabel()
        dot.setFixedSize(12, 12)
        dot.setStyleSheet(
            f"background:{_STATUS_COLOR[result.status]}; border-radius:6px;"
        )
        lay.addWidget(dot)

        info = QVBoxLayout()
        info.setSpacing(3)
        title = QLabel(t(result.title_key))
        title.setStyleSheet(f"font-weight:600; color:{COLORS['text_main']};")
        detail = QLabel(result.detail)
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color:{COLORS['text_sub']}; font-size:12px;")
        info.addWidget(title)
        info.addWidget(detail)
        lay.addLayout(info, stretch=1)

        if result.repairable and result.status != diag.STATUS_OK:
            btn = QPushButton(t("diag.repair"))
            btn.setMinimumHeight(30)
            btn.setMinimumWidth(72)
            btn.clicked.connect(lambda _=False, b=btn: on_repair(result.id, b))
            lay.addWidget(btn)

        status = QLabel(t(_STATUS_LABEL_KEY[result.status]))
        status.setStyleSheet(f"color:{_STATUS_COLOR[result.status]}; font-size:12px;")
        lay.addWidget(status)


class DiagnosticsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("diag.title"))
        self.resize(660, 580)
        self._running = False
        self._worker = None
        self._last_results: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self, title=t("diag.title"), height=38)
        root.addWidget(self.titlebar)

        # ---- header: action buttons ----
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 14, 20, 8)
        hl.setSpacing(10)
        self.recheck = QPushButton(t("diag.recheck"))
        self.recheck.setIcon(icon("refresh"))
        self.recheck.setIconSize(QSize(16, 16))
        self.recheck.setMinimumHeight(34)
        self.recheck.clicked.connect(self.run)
        self.repair_all_btn = QPushButton(t("diag.repair_all"))
        self.repair_all_btn.setProperty("cls", "accent")
        self.repair_all_btn.setIcon(icon("repair"))
        self.repair_all_btn.setIconSize(QSize(16, 16))
        self.repair_all_btn.setMinimumHeight(34)
        self.repair_all_btn.clicked.connect(self.repair_all)
        self.bundle_btn = QPushButton(t("diag.bundle"))
        self.bundle_btn.setIcon(icon("export"))
        self.bundle_btn.setIconSize(QSize(16, 16))
        self.bundle_btn.setMinimumHeight(34)
        self.bundle_btn.clicked.connect(self.export_bundle)
        hl.addStretch(1)
        hl.addWidget(self.bundle_btn)
        hl.addWidget(self.recheck)
        hl.addWidget(self.repair_all_btn)
        root.addWidget(head)

        # ---- scrollable results list ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_w = QWidget()
        self.list_lay = QVBoxLayout(self.list_w)
        self.list_lay.setContentsMargins(20, 8, 20, 8)
        self.list_lay.setSpacing(10)
        scroll.setWidget(self.list_w)
        root.addWidget(scroll, stretch=1)

        # ---- footer status bar ----
        self._status = QStatusBar()
        self._status.setStyleSheet(f"color:{COLORS['text_sub']};")
        self.summary = QLabel("")
        self._status.addPermanentWidget(self.summary)
        root.addWidget(self._status)

        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

        self.run()

    # ---- state ----
    def _set_running(self, running: bool) -> None:
        self._running = running
        self.recheck.setEnabled(not running)
        self.repair_all_btn.setEnabled(not running)
        self.bundle_btn.setEnabled(not running)

    def run(self) -> None:
        if self._running:
            return
        self._set_running(True)
        self._status.showMessage(t("diag.run"))
        self._clear_list()
        self._worker = Worker(diag.run_diagnostics)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(lambda e: self._on_error(str(e)))
        self._worker.start()

    def _on_done(self, results: list[diag.CheckResult]) -> None:
        # UI-state check touches live widgets → must run on the GUI thread.
        try:
            ui_r = diag.check_ui_state_now()
            if ui_r.status != diag.STATUS_SKIP:
                results = results + [ui_r]
        except Exception:
            pass
        self._render(results)
        self._set_running(False)

    def _on_error(self, err: str) -> None:
        self._status.showMessage("Diagnostics error: " + err)
        self._set_running(False)

    def _render(self, results: list[diag.CheckResult]) -> None:
        self._last_results = list(results)
        self._clear_list()
        ok = warn = err = skip = 0
        for r in results:
            if r.status == diag.STATUS_OK:
                ok += 1
            elif r.status == diag.STATUS_WARN:
                warn += 1
            elif r.status == diag.STATUS_ERROR:
                err += 1
            else:
                skip += 1
            self.list_lay.addWidget(_Row(r, self._repair_one))
        self.list_lay.addStretch(1)
        self.summary.setText(
            t("diag.summary", total=len(results), ok=ok, warn=warn, err=err)
        )
        self._status.showMessage(t("diag.empty") if (err == 0 and warn == 0) else "")

    def _clear_list(self) -> None:
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    # ---- support bundle ----
    def export_bundle(self) -> None:
        if self._running:
            return
        default = os.path.join(get_data_dir(), sb.default_bundle_name())
        path, _ = QFileDialog.getSaveFileName(
            self, t("diag.bundle"), default, "Zip (*.zip)"
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        self._set_running(True)
        self._status.showMessage(t("diag.bundle.working"))
        self._worker = Worker(sb.build_support_bundle, path, self._last_results)

        def _done(saved: str) -> None:
            self._set_running(False)
            self._status.showMessage("")
            info(self, t("diag.bundle"), t("diag.bundle.ok", path=saved))

        def _fail(e) -> None:
            self._set_running(False)
            self._status.showMessage(t("diag.bundle.fail", e=str(e)))

        self._worker.finished.connect(_done)
        self._worker.error.connect(_fail)
        self._worker.start()

    # ---- repair actions ----
    def _repair_one(self, cid: str, btn: QPushButton) -> None:
        if self._running:
            return
        self._set_running(True)
        self._status.showMessage(t("diag.repairing"))
        btn.setEnabled(False)
        self._worker = Worker(diag.repair, cid)

        def _done(msg: str) -> None:
            self._set_running(False)
            info(self, t("diag.title"), msg)
            self.run()

        self._worker.finished.connect(_done)
        self._worker.error.connect(
            lambda e: (self._set_running(False),
                       self._status.showMessage(t("diag.repair.fail", e=str(e))))
        )
        self._worker.start()

    def repair_all(self) -> None:
        if self._running:
            return
        self._set_running(True)
        self._status.showMessage(t("diag.repairing"))
        self._worker = Worker(diag.repair_all)

        def _done(msgs: list[str]) -> None:
            self._set_running(False)
            if msgs:
                info(self, t("diag.title"), "\n".join(msgs))
            self.run()

        self._worker.finished.connect(_done)
        self._worker.error.connect(
            lambda e: (self._set_running(False),
                       self._status.showMessage(t("diag.repair.fail", e=str(e))))
        )
        self._worker.start()
