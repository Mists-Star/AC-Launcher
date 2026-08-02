"""CrashAnalyzerDialog — read an instance's logs / crash reports, explain the
crash in plain language, and offer one-click auto-repair for fixable causes
(mod dependency download, Java switch, memory bump).

Opened from the instance card / home page "崩溃分析" button. Pure Qt, reuses
the worker-thread pattern for anything network-ish.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QProgressBar,
)
from PySide6.QtCore import Qt, QSize

from .theme import COLORS, RoundedCard
from .icons import icon
from .i18n import t
from .win_rounded import _msgbox, info, warn
from .worker import Worker
from . import crash_analysis as crash
from .instances import manager


_SEV_COLOR = {
    "critical": "#EF4444",
    "warning":  "#F59E0B",
    "info":     "#6B7280",
}


class _FindingCard(RoundedCard):
    """One crash finding: severity dot + title + reason + suggestion + actions."""

    def __init__(self, finding: crash.CrashFinding, on_repair, on_fix_java, on_fix_ram,
                 parent=None):
        super().__init__(radius=12, parent=parent)
        self.finding = finding
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # ── header: severity dot + title ──
        head = QHBoxLayout()
        dot = QLabel()
        dot.setFixedSize(10, 10)
        color = _SEV_COLOR.get(finding.severity, COLORS["text_sub"])
        dot.setStyleSheet(f"background:{color}; border-radius:5px;")
        head.addWidget(dot)
        title = QLabel(t(finding.title))
        title.setProperty("cls", "big")
        title.setStyleSheet(f"color:{color};")
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        # ── reason + suggestion ──
        reason = QLabel(t(finding.reason))
        reason.setProperty("cls", "sub")
        reason.setWordWrap(True)
        lay.addWidget(reason)
        sug = QLabel("💡 " + t(finding.suggestion))
        sug.setProperty("cls", "sub")
        sug.setWordWrap(True)
        lay.addWidget(sug)

        # ── raw detail (collapsible-ish: show excerpt) ──
        if finding.detail:
            det = QLabel(finding.detail.strip()[:220])
            det.setProperty("cls", "sub")
            det.setStyleSheet(
                f"font-size:11px; color:{COLORS['text_sub']};"
                f"background:{COLORS['bg_panel']}; border-radius:6px;"
                f"padding:8px; font-family:'Consolas','Menlo',monospace;"
            )
            det.setWordWrap(True)
            det.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(det)

        # ── actions ──
        acts = QHBoxLayout()
        acts.addStretch(1)
        if finding.kind == "mod_dep_missing":
            btn = QPushButton(icon("repair"), t("crash.btn_repair_deps"))
            btn.setProperty("cls", "accent")
            btn.setMinimumHeight(32)
            btn.clicked.connect(lambda: on_repair(finding))
            acts.addWidget(btn)
        elif finding.kind == "java_version":
            btn = QPushButton(icon("java"), t("crash.btn_fix_java"))
            btn.setProperty("cls", "accent")
            btn.setMinimumHeight(32)
            btn.clicked.connect(on_fix_java)
            acts.addWidget(btn)
        elif finding.kind == "out_of_memory":
            btn = QPushButton(icon("settings"), t("crash.btn_fix_ram"))
            btn.setProperty("cls", "accent")
            btn.setMinimumHeight(32)
            btn.clicked.connect(on_fix_ram)
            acts.addWidget(btn)
        lay.addLayout(acts)


class CrashAnalyzerDialog(QDialog):
    """Analyze + repair UI for a single instance's crash."""

    def __init__(self, inst=None, parent=None):
        super().__init__(parent)
        self.inst = inst or manager().current()
        self._inst_name = getattr(self.inst, "name", "")
        self._findings: list[crash.CrashFinding] = []
        self.setWindowTitle(t("crash.title"))
        self.resize(720, 620)
        self.setMinimumSize(640, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # frameless shell (same pattern as ScanDialog)
        from .frameless import FramelessHelper, TitleBar
        self.titlebar = TitleBar(self, title=t("crash.title"), height=38)
        root.addWidget(self.titlebar)

        # ── head: instance label + analyze button ──
        head = QHBoxLayout()
        head.setContentsMargins(20, 14, 20, 8)
        self.inst_lbl = QLabel()
        self.inst_lbl.setProperty("cls", "big")
        head.addWidget(self.inst_lbl)
        head.addStretch(1)
        self.analyze_btn = QPushButton(icon("refresh"), t("crash.analyze"))
        self.analyze_btn.setMinimumHeight(36)
        self.analyze_btn.clicked.connect(self._run_analyze)
        head.addWidget(self.analyze_btn)
        root.addLayout(head)

        # ── progress / status ──
        self.status = QLabel("")
        self.status.setProperty("cls", "sub")
        self.status.setContentsMargins(20, 0, 20, 4)
        root.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        self.bar.setFixedHeight(4)
        root.addWidget(self.bar)

        # ── scrollable findings ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self._content = QWidget()
        self._vbox = QVBoxLayout(self._content)
        self._vbox.setContentsMargins(20, 8, 20, 8)
        self._vbox.setSpacing(12)
        self.scroll.setWidget(self._content)
        root.addWidget(self.scroll, stretch=1)

        # ── footer ──
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 8, 20, 12)
        self.repair_all_btn = QPushButton(icon("repair"), t("crash.repair_all"))
        self.repair_all_btn.setProperty("cls", "accent")
        self.repair_all_btn.setMinimumHeight(36)
        self.repair_all_btn.clicked.connect(self._repair_all)
        self.repair_all_btn.setEnabled(False)
        foot.addWidget(self.repair_all_btn)
        foot.addStretch(1)
        close_btn = QPushButton(t("common.close"))
        close_btn.setMinimumHeight(34)
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        root.addLayout(foot)

        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

        self._update_header()
        self._run_analyze()

    # ------------------------------------------------------------- analyze
    def _update_header(self):
        name = getattr(self.inst, "name", "?") if self.inst else t("crash.no_instance")
        self.inst_lbl.setText(f"{t('crash.title')} — {name}")

    def _run_analyze(self):
        self.analyze_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setText(t("crash.analyzing"))
        # analysis is file-I/O only, but keep it off the UI thread anyway
        self._worker = Worker(self._analyze)
        self._worker.finished.connect(self._on_analyzed)
        self._worker.error.connect(lambda e: self.status.setText(str(e)))
        self._worker.start()

    def _analyze(self):
        if self.inst is None:
            return []
        return crash.analyze_instance(self.inst)

    def _on_analyzed(self, findings: list[crash.CrashFinding]):
        self._findings = findings
        self.bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        # clear — takeAt removes every item (widgets AND spacers) so repeated
        # analysis cannot pile up stale rows inside the scroll layout.
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not findings:
            ok = QLabel(t("crash.no_crash"))
            ok.setProperty("cls", "sub")
            ok.setAlignment(Qt.AlignCenter)
            ok.setStyleSheet(f"color:{COLORS['success']}; font-size:14px;")
            self._vbox.addWidget(ok)
            self.status.setText(t("crash.no_crash"))
            self.repair_all_btn.setEnabled(False)
            return
        self.status.setText(t("crash.found", n=len(findings)))
        repairable = 0
        for f in findings:
            if f.kind == "mod_dep_missing":
                card = _FindingCard(
                    f, self._repair_deps, self._fix_java, self._fix_ram)
                repairable += 1
            elif f.kind in ("java_version", "out_of_memory"):
                card = _FindingCard(
                    f, self._repair_deps, self._fix_java, self._fix_ram)
                repairable += 1
            else:
                card = _FindingCard(
                    f, self._repair_deps, self._fix_java, self._fix_ram)
            self._vbox.addWidget(card)
        self.repair_all_btn.setEnabled(repairable > 0)
        self._vbox.addStretch(1)

    # ------------------------------------------------------------- repairs
    def _repair_deps(self, _finding=None):
        """Scan mods dir for missing deps, then download them (Modrinth)."""
        if self.inst is None:
            warn(self, t("crash.title"), t("crash.no_instance"))
            return
        missing = crash.find_missing_dependencies(self.inst)
        if not missing:
            info(self, t("crash.title"), t("crash.deps_ok"))
            return
        if not _msgbox(
            self, t("crash.deps_found_title"),
            t("crash.deps_found_body", n=len(missing)),
            detail="\n".join(f"• {m}" for m in missing),
            icon="question",
            buttons=(t("crash.btn_download"), t("common.cancel")),
        ) == t("crash.btn_download"):
            return
        self.bar.setVisible(True)
        self.status.setText(t("crash.deps_fixing"))
        self._worker = Worker(self._fix_deps_worker, missing)
        self._worker.finished.connect(self._on_deps_done)
        self._worker.error.connect(lambda e: self.status.setText(str(e)))
        self._worker.start()

    def _fix_deps_worker(self, missing: list[str]):
        return crash.search_and_download_missing(self.inst, missing)

    def _on_deps_done(self, result):
        downloaded, failed = result
        self.bar.setVisible(False)
        self.status.setText(
            t("crash.deps_done", n=len(downloaded)) if downloaded else
            t("crash.deps_failed"))
        if downloaded:
            from .repair_log import append
            from .achievements import achievements as _ach
            inst_name = getattr(self, "_inst_name", "")
            append("mod_dep", t("crash.log_fixed_deps", n=len(downloaded)),
                   instance=inst_name)
            _ach.unlock("first_repair")
        if failed:
            warn(self, t("crash.title"),
                 t("crash.deps_failed_detail", n=len(failed)),
                 detail="\n".join(f"• {d}" for d in failed))

    def _fix_java(self):
        from .java_manager_dialog import JavaManagerDialog
        dlg = JavaManagerDialog(self)
        dlg.exec()

    def _fix_ram(self):
        info(self, t("crash.title"), t("crash.ram_hint"))

    def _repair_all(self):
        self._repair_deps()
