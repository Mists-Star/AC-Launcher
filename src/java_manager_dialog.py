"""Java Manager — full-spectrum Java runtime manager, living in Settings.

Discovers EVERY Java on the machine — system installs, portable / unzipped
JDKs, other launchers' bundled runtimes, and AC's own downloaded portable
copies — via ``core.java.scan_javas``, lets the user pick any of them as the
launch Java, delete AC's own copies, and download ANY major from Eclipse
Adoptium (Temurin). The version list is no longer a fixed short menu: it is
populated from Adoptium's live "available releases" plus a free-form custom
major field, so the player can grab literally any JDK major.
"""
from __future__ import annotations

import os
import shutil

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QScrollArea, QWidget, QFrame, QComboBox, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer

from .i18n import t
from .theme import COLORS, RoundedCard, with_alpha
from .win_rounded import enable_win11_round_corners, confirm, warn, info
from .frameless import FramelessHelper, TitleBar
from .core import java_install
from .core.java import scan_javas
from .onboarding import _JavaInstallThread
from .worker import Worker


class _JavaDetectedRow(RoundedCard):
    """One detected Java: version + major badge + source + path + actions."""

    def __init__(self, dlg: "JavaManagerDialog", entry: dict):
        super().__init__(radius=8)
        self.dlg = dlg
        self.entry = entry
        self.path = entry.get("path", "")
        self.major = entry.get("major", 0)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(5)

        # top line: version + major badge + source + status
        top = QHBoxLayout()
        ver = entry.get("version") or (f"Java {self.major}" if self.major else "?")
        name_lbl = QLabel(f"<b>{ver}</b>")
        name_lbl.setTextFormat(Qt.RichText)
        top.addWidget(name_lbl)

        if self.major:
            from .ui_kit import accent_text
            badge = QLabel(f"Java {self.major}")
            badge.setStyleSheet(
                f"QLabel {{ background:{with_alpha(COLORS['accent'], 0x22)};"
                f" color:{accent_text()};"
                f" border-radius:4px; padding:1px 6px; font-size:11px; }}")
            top.addWidget(badge)

        tag = QLabel(self._source_tag())
        tag.setStyleSheet(f"QLabel {{ color:{COLORS['text_sub']}; font-size:11px; }}")
        top.addWidget(tag)
        top.addStretch(1)

        self.status = QWidget()
        stl = QHBoxLayout(self.status)
        stl.setContentsMargins(0, 0, 0, 0)
        stl.setSpacing(5)
        self._st_icon = QLabel()
        self._st_icon.setFixedSize(13, 13)
        self._st_text = QLabel()
        self._st_text.setProperty("cls", "sub")
        stl.addWidget(self._st_icon)
        stl.addWidget(self._st_text)
        top.addWidget(self.status)
        lay.addLayout(top)

        # path (selectable)
        path_lbl = QLabel(self.path)
        path_lbl.setProperty("cls", "sub")
        path_lbl.setWordWrap(True)
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_lbl.setToolTip(self.path)
        lay.addWidget(path_lbl)

        # actions
        act = QHBoxLayout()
        is_current = bool(self.dlg.current_path) and \
            os.path.normcase(self.path) == os.path.normcase(self.dlg.current_path)
        if is_current:
            from .ui_kit import accent_text, state_pix
            # 自绘圆点标记「使用中」，不用文本 ●（round-89）
            self._st_icon.setPixmap(state_pix("dot", accent_text(), 8))
            self._st_text.setText(t("javamgr.in_use"))
            self._st_text.setStyleSheet(f"color:{accent_text()};")
            use_btn = QPushButton(t("javamgr.use_this"))
            use_btn.setEnabled(False)
        else:
            from .ui_kit import state_pix
            self._st_icon.setPixmap(state_pix("done", COLORS["success"], 11))
            self._st_text.setText(t("javamgr.installed"))
            self._st_text.setStyleSheet(f"color:{COLORS['text_sub']};")
            use_btn = QPushButton(t("javamgr.use_this"))
            use_btn.clicked.connect(self._use)
        use_btn.setMinimumHeight(28)
        act.addWidget(use_btn)

        if self._is_ours():
            del_btn = QPushButton(t("javamgr.delete_ours"))
            del_btn.setMinimumHeight(28)
            del_btn.clicked.connect(self._delete)
            act.addWidget(del_btn)
        act.addStretch(1)
        lay.addLayout(act)

    # ---------- helpers ----------
    def _is_ours(self) -> bool:
        root = java_install.java_root()
        return os.path.normcase(self.path).startswith(os.path.normcase(root))

    def _source_tag(self) -> str:
        return t("javamgr.source_ac") if self._is_ours() else t("javamgr.source_other")

    def _use(self):
        self.dlg.select_java(self.path)

    def _delete(self):
        root = java_install.java_root()
        target = self.path
        while os.path.dirname(target) != root and len(target) > len(root):
            target = os.path.dirname(target)
        if not (os.path.isdir(target) and target.startswith(root)):
            return
        if confirm(
            self, t("javamgr.title"),
            t("javamgr.del_confirm", major=self.major),
        ) != True:
            return
        shutil.rmtree(target, ignore_errors=True)
        # drop from the cached scan list so it disappears immediately
        if self.dlg._last_javas is not None:
            key = os.path.normcase(self.path)
            self.dlg._last_javas = [
                j for j in self.dlg._last_javas
                if os.path.normcase(j.get("path", "")) != key
            ]
        if self.dlg.current_path and \
                os.path.normcase(self.path) == os.path.normcase(self.dlg.current_path):
            self.dlg.select_java("", quiet=True)
        else:
            self.dlg.refresh_all()


class JavaManagerDialog(QDialog):
    """Scan / pick / delete / download Java runtimes of ANY version.

    ``selected_path`` is set when the user clicks "use this Java" (or after a
    successful download auto-selects it) so the caller (Settings) can write it
    into config.
    """

    def __init__(self, parent=None, current_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle(t("javamgr.title"))
        self.resize(720, 600)
        self.setMinimumSize(620, 460)
        self.current_path = current_path or ""
        self.selected_path: str | None = None
        self._scan_worker = None
        self._dl_thread = None
        self._dl_major = 0
        self._rows: list[_JavaDetectedRow] = []
        self._last_javas: list[dict] | None = []

        # ── AC 无边框窗口：自定义标题栏 + 圆角 ──
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(
            self, title=t("javamgr.title"), height=38, controls="close")
        root.addWidget(self.titlebar)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(10)

        # current launch Java
        self.cur_lbl = QLabel(
            t("javamgr.current", path=self.current_path) if self.current_path
            else t("javamgr.none_system"))
        self.cur_lbl.setProperty("cls", "sub")
        self.cur_lbl.setWordWrap(True)
        self.cur_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.cur_lbl)

        # scan bar
        sbar = QHBoxLayout()
        self.scan_btn = QPushButton(t("javamgr.scan"))
        self.scan_btn.setMinimumHeight(32)
        self.scan_btn.clicked.connect(self._run_scan)
        sbar.addWidget(self.scan_btn)
        self.rescan_btn = QPushButton(t("javamgr.rescan"))
        self.rescan_btn.setMinimumHeight(32)
        self.rescan_btn.clicked.connect(self._run_scan)
        self.rescan_btn.setVisible(False)
        sbar.addWidget(self.rescan_btn)
        self.scan_status = QLabel("")
        self.scan_status.setProperty("cls", "sub")
        self.scan_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sbar.addWidget(self.scan_status, stretch=1)
        lay.addLayout(sbar)

        self.scan_bar = QProgressBar()
        self.scan_bar.setTextVisible(False)
        self.scan_bar.setFixedHeight(6)
        self.scan_bar.setMaximum(0)
        self.scan_bar.setVisible(False)
        lay.addWidget(self.scan_bar)

        # detected list
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.inner = QWidget()
        self.rows_lay = QVBoxLayout(self.inner)
        self.rows_lay.setContentsMargins(0, 0, 0, 0)
        self.rows_lay.setSpacing(8)
        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll, stretch=1)

        # download section
        dl_grp = RoundedCard(radius=8)
        dl = QVBoxLayout(dl_grp)
        dl.setContentsMargins(12, 10, 12, 10)
        dl.setSpacing(8)
        dl_title = QLabel(f"<b>{t('javamgr.download_title')}</b>")
        dl_title.setTextFormat(Qt.RichText)
        dl.addWidget(dl_title)
        dl_hint = QLabel(t("javamgr.hint"))
        dl_hint.setProperty("cls", "sub")
        dl_hint.setWordWrap(True)
        dl.addWidget(dl_hint)

        dl_row = QHBoxLayout()
        dl_row.addWidget(QLabel(t("javamgr.major_label")))
        self.major_combo = QComboBox()
        self.major_combo.setMinimumHeight(30)
        self.major_combo.setInsertPolicy(QComboBox.NoInsert)
        dl_row.addWidget(self.major_combo, stretch=1)
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText(t("javamgr.custom_major"))
        self.custom_input.setMinimumHeight(30)
        self.custom_input.setVisible(False)
        dl_row.addWidget(self.custom_input, stretch=1)
        self.major_combo.currentIndexChanged.connect(self._on_major_picked)
        dl.addLayout(dl_row)

        dl_btn_row = QHBoxLayout()
        self.dl_btn = QPushButton(t("javamgr.download"))
        self.dl_btn.setProperty("cls", "accent")
        self.dl_btn.setMinimumHeight(32)
        self.dl_btn.clicked.connect(self._download)
        dl_btn_row.addWidget(self.dl_btn)
        dl_btn_row.addStretch(1)
        dl.addLayout(dl_btn_row)

        self.dl_bar = QProgressBar()
        self.dl_bar.setTextVisible(False)
        self.dl_bar.setFixedHeight(6)
        self.dl_bar.setVisible(False)
        dl.addWidget(self.dl_bar)
        lay.addWidget(dl_grp)

        # footer
        btns = QHBoxLayout()
        btns.addStretch(1)
        close_btn = QPushButton(t("common.close"))
        close_btn.setMinimumHeight(32)
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

        root.addWidget(body, stretch=1)

        # ── frameless + DWM shadow + win11 rounded corners ──
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        enable_win11_round_corners(self)

        # fill the version combo (network best-effort)
        self._populate_majors()
        # auto-scan on open, like the old instance scanner did
        QTimer.singleShot(50, self._run_scan)

    # ---------- version combo ----------
    def _populate_majors(self):
        self.major_combo.blockSignals(True)
        self.major_combo.clear()
        try:
            majors = java_install.available_majors()
        except Exception:
            majors = [m for m, _ in java_install.JAVA_CHOICES]
        for m in majors:
            self.major_combo.addItem(f"Java {m}", m)
        self.major_combo.addItem(t("javamgr.custom_major"), -1)
        self.major_combo.blockSignals(False)

    def _on_major_picked(self, idx: int):
        is_custom = self.major_combo.itemData(idx) == -1
        self.custom_input.setVisible(is_custom)
        if is_custom:
            self.custom_input.setFocus()

    def _chosen_major(self) -> int:
        idx = self.major_combo.currentIndex()
        data = self.major_combo.itemData(idx)
        if data == -1:
            try:
                return int(self.custom_input.text().strip())
            except ValueError:
                return 0
        return int(data) if data is not None else 0

    # ---------- scan ----------
    def _run_scan(self):
        if self._scan_worker is not None:
            return
        self.scan_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.scan_bar.setVisible(True)
        self.scan_status.setText(t("javamgr.scanning"))
        self._scan_worker = Worker(scan_javas, deep=True)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.error.connect(lambda e: self._on_scan_done([]))
        self._scan_worker.start()

    def _on_scan_done(self, javas):
        self._scan_worker = None
        self.scan_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.rescan_btn.setEnabled(True)
        self.rescan_btn.setVisible(True)
        self._last_javas = javas or []
        self._build_rows(self._last_javas)
        self.scan_status.setText(t("javamgr.scan_summary", n=len(self._last_javas)))

    def _build_rows(self, javas):
        while self.rows_lay.count():
            item = self.rows_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows = []
        if not javas:
            empty = QLabel(t("javamgr.no_java"))
            empty.setProperty("cls", "sub")
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(60)
            self.rows_lay.addWidget(empty)
            return
        for j in sorted(javas, key=lambda x: -(x.get("major", 0) or 0)):
            row = _JavaDetectedRow(self, j)
            self._rows.append(row)
            self.rows_lay.addWidget(row)
        self.rows_lay.addStretch(1)

    # ---------- download ----------
    def _download(self):
        if self._dl_thread is not None:
            return
        major = self._chosen_major()
        if major <= 0:
            warn(self, t("javamgr.title"), t("javamgr.custom_major"))
            return
        self._dl_major = major
        self.dl_btn.setEnabled(False)
        self.dl_btn.setText(t("javamgr.downloading"))
        self.dl_bar.setVisible(True)
        self.dl_bar.setMaximum(0)
        self._dl_thread = _JavaInstallThread(major)
        self._dl_thread.progressed.connect(self._on_dl_progress)
        self._dl_thread.done.connect(self._on_dl_done)
        self._dl_thread.failed.connect(self._on_dl_failed)
        self._dl_thread.start()

    def _on_dl_progress(self, done, total):
        if total and total > 0:
            self.dl_bar.setMaximum(total)
            self.dl_bar.setValue(done)

    def _on_dl_done(self, path):
        self._dl_thread = None
        self.dl_bar.setVisible(False)
        self.dl_btn.setEnabled(True)
        self.dl_btn.setText(t("javamgr.download"))
        # make sure the new runtime shows up without a full re-scan
        if self._last_javas is None:
            self._last_javas = []
        key = os.path.normcase(path)
        if not any(os.path.normcase(j.get("path", "")) == key for j in self._last_javas):
            self._last_javas.append({
                "path": path,
                "version": f"Java {self._dl_major}",
                "major": self._dl_major,
            })
        self.select_java(path, quiet=True)

    def _on_dl_failed(self, err):
        self._dl_thread = None
        self.dl_bar.setVisible(False)
        self.dl_btn.setEnabled(True)
        self.dl_btn.setText(t("javamgr.download"))
        warn(self, t("javamgr.title"),
                            t("javamgr.dl_failed", err=err))

    # ---------- API ----------
    def select_java(self, path, quiet=False):
        self.current_path = path
        self.selected_path = path
        self.cur_lbl.setText(
            t("javamgr.current", path=path) if path else t("javamgr.none_system"))
        self.refresh_all()
        if path and not quiet:
            info(self, t("javamgr.title"),
                                    t("javamgr.selected", path=path))

    def refresh_all(self):
        if self._last_javas is None:
            installed = java_install.installed_majors()
            self._last_javas = [
                {"path": p, "version": f"Java {m}", "major": m}
                for m, p in installed.items()
            ]
        self._build_rows(self._last_javas)

    def closeEvent(self, e):
        busy = self._dl_thread is not None
        if busy and confirm(
            self, t("javamgr.title"), t("javamgr.busy_close"),
        ) != True:
            e.ignore()
            return
        super().closeEvent(e)
