"""Skin library dialog — browse / import / download / manage player skins.

Shows every locally-stored skin as a card (full-body preview + name) with
actions: set as the active skin for the current account, rename, delete. New
skins come from a file picker or by typing a player name (downloaded via the
skin manager, which resolves through Mojang with third-party fallbacks).
"""
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QScrollArea, QGridLayout, QFileDialog,
)
from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QDesktopServices

import os

from .theme import COLORS, RoundedCard
from .icons import icon
from .i18n import t
from .win_rounded import confirm, pick_files, text_input
from .frameless import FramelessHelper, TitleBar
from .worker import Worker
from .skins import manager as skin_manager
from .skin_render import render_skin


class SkinDialog(QDialog):
    def __init__(self, parent=None, account_id: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("skin.title"))
        self.resize(640, 560)
        self._account_id = account_id
        self._skins = skin_manager()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self, title=t("skin.title"), height=38)
        root.addWidget(self.titlebar)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 18, 20, 18)
        bl.setSpacing(14)

        # ---- toolbar ----
        bar = QHBoxLayout()
        bar.setSpacing(10)
        imp = QPushButton(t("skin.import"))
        imp.setMinimumHeight(36)
        imp.setIcon(icon("import"))
        imp.setIconSize(QSize(16, 16))
        imp.clicked.connect(self._import)
        bar.addWidget(imp)

        bar.addStretch(1)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("skin.download_ph"))
        self.name_edit.setMinimumWidth(180)
        self.name_edit.returnPressed.connect(self._download)
        bar.addWidget(self.name_edit)
        dl = QPushButton(t("skin.download"))
        dl.setMinimumHeight(36)
        dl.setIcon(icon("download"))
        dl.setIconSize(QSize(16, 16))
        dl.clicked.connect(self._download)
        bar.addWidget(dl)
        third = QPushButton(t("skin.open_third"))
        third.setMinimumHeight(36)
        third.setIcon(icon("external"))
        third.setIconSize(QSize(16, 16))
        third.clicked.connect(self._open_third)
        bar.addWidget(third)
        bl.addLayout(bar)

        self.status = QLabel("")
        self.status.setProperty("cls", "sub")
        bl.addWidget(self.status)

        # ---- grid ----
        self.grid = QGridLayout()
        self.grid.setSpacing(14)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        holder = QWidget()
        holder.setLayout(self.grid)
        self.scroll.setWidget(holder)
        bl.addWidget(self.scroll, stretch=1)

        root.addWidget(body, stretch=1)

        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

        self._rebuild()

    # ----------------------------------------------------------- build grid
    def _rebuild(self):
        # clear
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        active = self._skins.active_of(self._account_id) if self._account_id else None
        skins = self._skins.list()
        if not skins:
            empty = QLabel(t("skin.empty"))
            empty.setProperty("cls", "sub")
            empty.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(empty, 0, 0)
            return
        cols = 3
        for i, s in enumerate(skins):
            self.grid.addWidget(self._card(s, s is active), i // cols, i % cols)

    def _card(self, skin: dict, is_active: bool) -> QWidget:
        card = RoundedCard(radius=12)
        card.setFixedWidth(180)
        if is_active:
            card.set_border(COLORS["accent"], 2)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        path = self._skins.path_of(skin["id"])
        prev = QLabel()
        prev.setFixedSize(120, 240)
        prev.setAlignment(Qt.AlignCenter)
        if path and os.path.isfile(path):
            pm = render_skin(path, 120)
            # render_skin returns a sized transparent pixmap even when the source
            # image is invalid/corrupt.  Detect this by checking whether the
            # pixmap has any real content (sample center pixel alpha).
            _has_content = (
                not pm.isNull()
                and pm.width() > 1
                and pm.toImage().pixelColor(pm.width() // 2, pm.height() // 2).alpha() > 0
            )
            if _has_content:
                prev.setPixmap(pm)
            else:
                prev.setProperty("cls", "sub")
                prev.setText(t("skin.no_preview"))
                prev.setWordWrap(True)
        else:
            prev.setProperty("cls", "sub")
            prev.setText(t("skin.no_preview"))
            prev.setWordWrap(True)
        cl.addWidget(prev, alignment=Qt.AlignCenter)

        name = QLabel(skin["name"])
        name.setProperty("cls", "big")
        name.setAlignment(Qt.AlignCenter)
        cl.addWidget(name)

        tag = QLabel(
            t("skin.tag_active") if is_active else
            (t("skin.tag_download") if skin.get("source") == "download"
             else t("skin.tag_local"))
        )
        tag.setProperty("cls", "sub")
        tag.setAlignment(Qt.AlignCenter)
        cl.addWidget(tag)

        row = QHBoxLayout()
        row.setSpacing(6)
        if is_active:
            use = QPushButton(t("skin.active_btn"))
            use.setEnabled(False)
        else:
            use = QPushButton(t("skin.set_active"))
            use.setMinimumHeight(30)
            use.clicked.connect(lambda _=False, sid=skin["id"]: self._set_active(sid))
        row.addWidget(use)
        ren = QPushButton(t("skin.rename"))
        ren.setMinimumHeight(30)
        ren.clicked.connect(lambda _=False, sid=skin["id"], nm=skin["name"]: self._rename(sid, nm))
        row.addWidget(ren)
        cl.addLayout(row)

        delb = QPushButton(t("skin.delete"))
        delb.setMinimumHeight(30)
        delb.setProperty("cls", "danger")
        delb.clicked.connect(lambda _=False, sid=skin["id"]: self._delete(sid))
        cl.addWidget(delb)
        return card

    # ----------------------------------------------------------- actions
    def _set_active(self, skin_id: str):
        if self._account_id:
            self._skins.set_active(self._account_id, skin_id)
        self._rebuild()

    def _rename(self, skin_id: str, old: str):
        new, ok = text_input(self, t("skin.rename"), t("skin.rename_ph"),
                             default=old)
        if ok and new.strip():
            self._skins.rename(skin_id, new.strip())
            self._rebuild()

    def _delete(self, skin_id: str):
        s = self._skins.get(skin_id)
        if s and confirm(
            self, t("skin.delete"), t("skin.delete_confirm", name=s["name"])
        ) != True:
            return
        self._skins.remove(skin_id)
        self._rebuild()

    def _import(self):
        path = pick_files(
            self, t("skin.import_title"), "",
            "PNG Images (*.png);;All Files (*.*)",
        )
        if not path:
            return
        try:
            self._skins.add_file(path)
            self.status.setText("")
            self._rebuild()
        except Exception as e:
            self.status.setStyleSheet(f"color: {COLORS['danger']};")
            self.status.setText(t("skin.error", e=str(e)))

    def _download(self):
        text = self.name_edit.text().strip()
        if not text:
            return
        is_url = text.lower().startswith("http://") or text.lower().startswith("https://")
        self.status.setStyleSheet(f"color: {COLORS['text_sub']};")
        self.status.setText(t("skin.downloading", name=text))
        if is_url:
            w = Worker(self._skins.add_url, text)
        else:
            w = Worker(self._skins.download, text)
        w.finished.connect(lambda s: self._on_dl_done(s, text))
        w.error.connect(lambda e: self._on_dl_error(str(e)))
        w.start()

    def _open_third(self):
        """Open the player's skin page on a third-party site (mc-heads)."""
        name = self.name_edit.text().strip()
        if name and not name.lower().startswith("http"):
            QDesktopServices.openUrl(QUrl(f"https://mc-heads.net/skin/{name}"))
        else:
            QDesktopServices.openUrl(QUrl("https://mc-heads.net"))

    def _on_dl_done(self, skin: dict, name: str):
        self.status.setText(t("skin.downloaded", name=skin["name"]))
        self._rebuild()

    def _on_dl_error(self, msg: str):
        self.status.setStyleSheet(f"color: {COLORS['danger']};")
        self.status.setText(t("skin.error", e=msg))
