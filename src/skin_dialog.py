"""Skin & cape library dialog — browse / import / download / manage cosmetics.

Two tabs share one dialog: "Skins" (full-body previews) and "Capes" (back-face
previews). Each tab lists the locally-stored items as cards with actions
(set active for the current account / rename / delete) and a toolbar to import
a PNG or download by player name (resolved through Mojang with third-party
fallbacks). Everything is stored by ``skins.SkinManager``.
"""
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QGridLayout, QStackedWidget, QButtonGroup,
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
from .accounts import manager as accounts_manager
from .skin_render import render_skin, render_cape, skin_model


class SkinDialog(QDialog):
    def __init__(self, parent=None, account_id: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("skin.title"))
        self.resize(680, 620)
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
        bl.setSpacing(10)

        # ---- skins / capes switch ----
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.tab_skin = QPushButton(t("skin.tab_skin"))
        self.tab_cape = QPushButton(t("skin.tab_cape"))
        self._modes = QButtonGroup(self)
        self._modes.setExclusive(True)
        for idx, btn in enumerate((self.tab_skin, self.tab_cape)):
            btn.setCheckable(True)
            btn.setProperty("cls", "chip")
            btn.setMinimumHeight(30)
            btn.setCursor(Qt.PointingHandCursor)
            self._modes.addButton(btn, idx)
            mode_row.addWidget(btn)
        mode_row.addStretch(1)
        self.tab_skin.setChecked(True)
        self._modes.idClicked.connect(self._on_mode)
        bl.addLayout(mode_row)

        # Changing the active skin/cape only means something once an account
        # owns it — say so instead of letting the buttons silently do nothing.
        if not self._account_id:
            hint = QLabel(t("login.no_account_skin"))
            hint.setProperty("cls", "sub")
            hint.setWordWrap(True)
            bl.addWidget(hint)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_skin_page())
        self.pages.addWidget(self._build_cape_page())
        bl.addWidget(self.pages, stretch=1)

        root.addWidget(body, stretch=1)

        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

        self._rebuild()
        self._rebuild_capes()

    def _on_mode(self, index: int):
        self.pages.setCurrentIndex(index)

    # ----------------------------------------------------------- pages
    def _build_skin_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # ---- toolbar ----
        bar = QHBoxLayout()
        bar.setSpacing(10)
        imp = QPushButton(t("skin.import"))
        imp.setMinimumHeight(36)
        imp.setIcon(icon("import"))
        imp.setIconSize(QSize(16, 16))
        imp.clicked.connect(self._import)
        bar.addWidget(imp)

        # round-123: premium accounts can pull their current Mojang skin (and
        # push a local one back) without leaving the launcher.
        self.refresh_btn = QPushButton(t("skin.refresh"))
        self.refresh_btn.setMinimumHeight(36)
        self.refresh_btn.setIcon(icon("refresh"))
        self.refresh_btn.setIconSize(QSize(16, 16))
        self.refresh_btn.setToolTip(t("skin.refresh_tip"))
        self.refresh_btn.clicked.connect(self._refresh_account_skin)
        self.refresh_btn.setVisible(self._account_is_premium())
        bar.addWidget(self.refresh_btn)

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
        lay.addLayout(bar)

        self.status = QLabel("")
        self.status.setProperty("cls", "sub")
        lay.addWidget(self.status)

        # ---- grid ----
        self.grid = QGridLayout()
        self.grid.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        holder.setLayout(self.grid)
        scroll.setWidget(holder)
        lay.addWidget(scroll, stretch=1)
        return page

    def _build_cape_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        imp = QPushButton(t("skin.cape_import"))
        imp.setMinimumHeight(36)
        imp.setIcon(icon("import"))
        imp.setIconSize(QSize(16, 16))
        imp.clicked.connect(self._import_cape)
        bar.addWidget(imp)

        self.cape_unequip_btn = QPushButton(t("skin.cape_unequip"))
        self.cape_unequip_btn.setMinimumHeight(36)
        self.cape_unequip_btn.clicked.connect(self._cape_unequip)
        bar.addWidget(self.cape_unequip_btn)

        bar.addStretch(1)
        self.cape_name_edit = QLineEdit()
        self.cape_name_edit.setPlaceholderText(t("skin.cape_download_ph"))
        self.cape_name_edit.setMinimumWidth(180)
        self.cape_name_edit.returnPressed.connect(self._download_cape)
        bar.addWidget(self.cape_name_edit)
        dl = QPushButton(t("skin.cape_download"))
        dl.setMinimumHeight(36)
        dl.setIcon(icon("download"))
        dl.setIconSize(QSize(16, 16))
        dl.clicked.connect(self._download_cape)
        bar.addWidget(dl)
        lay.addLayout(bar)

        self.cape_status = QLabel("")
        self.cape_status.setProperty("cls", "sub")
        lay.addWidget(self.cape_status)

        self.cape_grid = QGridLayout()
        self.cape_grid.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        holder.setLayout(self.cape_grid)
        scroll.setWidget(holder)
        lay.addWidget(scroll, stretch=1)
        return page

    # ----------------------------------------------------------- skins
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
            # Render at the widget's device pixel ratio and tag the pixmap, so
            # Qt does not upscale a 120×240 image on a HiDPI screen (1.25 here)
            # — that upscale was half of the "低清" skin thumbnails.
            dpr = max(1.0, float(prev.devicePixelRatioF() or 1.0))
            pm = render_skin(path, int(round(120 * dpr)),
                             model=skin.get("model"))
            pm.setDevicePixelRatio(dpr)
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
            use.setEnabled(bool(self._account_id))
            use.clicked.connect(lambda _=False, sid=skin["id"]: self._set_active(sid))
        row.addWidget(use)
        ren = QPushButton(t("skin.rename"))
        ren.setMinimumHeight(30)
        ren.clicked.connect(lambda _=False, sid=skin["id"], nm=skin["name"]: self._rename(sid, nm))
        row.addWidget(ren)
        cl.addLayout(row)

        if self._account_is_premium() and path and os.path.isfile(path):
            up = QPushButton(t("skin.upload"))
            up.setMinimumHeight(30)
            up.setToolTip(t("skin.upload_tip"))
            up.clicked.connect(lambda _=False, sid=skin["id"]: self._upload_skin(sid))
            cl.addWidget(up)

        delb = QPushButton(t("skin.delete"))
        delb.setMinimumHeight(30)
        delb.setProperty("cls", "danger")
        delb.clicked.connect(lambda _=False, sid=skin["id"]: self._delete(sid))
        cl.addWidget(delb)
        return card

    # ----------------------------------------------------------- capes
    def _rebuild_capes(self):
        while self.cape_grid.count():
            w = self.cape_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        active = (self._skins.active_cape_of(self._account_id)
                  if self._account_id else None)
        capes = self._skins.list_capes()
        if not capes:
            empty = QLabel(t("skin.cape_empty"))
            empty.setProperty("cls", "sub")
            empty.setAlignment(Qt.AlignCenter)
            self.cape_grid.addWidget(empty, 0, 0)
        else:
            cols = 3
            for i, c in enumerate(capes):
                self.cape_grid.addWidget(
                    self._cape_card(c, c is active), i // cols, i % cols)
        self.cape_unequip_btn.setEnabled(bool(self._account_id and active))
        self.cape_unequip_btn.setToolTip(
            t("skin.cape_unequip") if active else t("skin.cape_none_active"))

    def _cape_card(self, cape: dict, is_active: bool) -> QWidget:
        card = RoundedCard(radius=12)
        card.setFixedWidth(180)
        if is_active:
            card.set_border(COLORS["accent"], 2)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        path = self._skins.cape_path_of(cape["id"])
        prev = QLabel()
        prev.setFixedSize(120, 192)
        prev.setAlignment(Qt.AlignCenter)
        if path and os.path.isfile(path):
            dpr = max(1.0, float(prev.devicePixelRatioF() or 1.0))
            pm = render_cape(path, int(round(120 * dpr)),
                             int(round(192 * dpr)))
            pm.setDevicePixelRatio(dpr)
            prev.setPixmap(pm)
        else:
            prev.setProperty("cls", "sub")
            prev.setText(t("skin.no_preview"))
            prev.setWordWrap(True)
        cl.addWidget(prev, alignment=Qt.AlignCenter)

        name = QLabel(cape["name"])
        name.setProperty("cls", "big")
        name.setAlignment(Qt.AlignCenter)
        cl.addWidget(name)

        tag = QLabel(
            t("skin.cape_tag_active") if is_active else
            (t("skin.tag_download") if cape.get("source") == "download"
             else t("skin.tag_local"))
        )
        tag.setProperty("cls", "sub")
        tag.setAlignment(Qt.AlignCenter)
        cl.addWidget(tag)

        if is_active:
            use = QPushButton(t("skin.cape_active_btn"))
            use.setEnabled(False)
        else:
            use = QPushButton(t("skin.cape_set_active"))
            use.setMinimumHeight(30)
            use.setEnabled(bool(self._account_id))
            use.clicked.connect(
                lambda _=False, cid=cape["id"]: self._cape_set_active(cid))
        cl.addWidget(use)

        delb = QPushButton(t("skin.delete"))
        delb.setMinimumHeight(30)
        delb.setProperty("cls", "danger")
        delb.clicked.connect(
            lambda _=False, cid=cape["id"], nm=cape["name"]: self._cape_delete(cid, nm))
        cl.addWidget(delb)
        return card

    # ----------------------------------------------------------- actions
    def _account(self) -> dict | None:
        return accounts_manager().get(self._account_id) if self._account_id else None

    def _account_is_premium(self) -> bool:
        acc = self._account()
        return bool(acc and acc.get("type") == "microsoft"
                    and (acc.get("access_token") or "").strip())

    def _notify_parent(self):
        """Ask the main window to re-render avatar + home character card."""
        fn = getattr(self.parent(), "_refresh_account_avatar", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass

    def _refresh_account_skin(self):
        acc = self._account()
        if not acc:
            return
        self.status.setStyleSheet(f"color: {COLORS['text_sub']};")
        self.status.setText(t("skin.refreshing", name=acc.get("name", "")))
        w = Worker(self._skins.fetch_account_skin,
                   acc.get("name", ""), acc.get("id", ""))
        self._refresh_worker = w
        w.finished.connect(lambda entry, a=acc: self._on_refreshed(entry, a))
        w.error.connect(lambda e: self._on_refresh_error(str(e)))
        w.start()

    def _on_refreshed(self, entry, acc: dict):
        if not entry:
            self._on_refresh_error(t("skin.not_found"))
            return
        self._skins.set_active(acc["id"], entry["id"])
        self.status.setText(t("skin.refreshed", name=entry.get("name", "")))
        self._rebuild()
        self._notify_parent()

    def _on_refresh_error(self, msg: str):
        self.status.setStyleSheet(f"color: {COLORS['danger']};")
        self.status.setText(t("skin.refresh_failed", e=msg))

    def _upload_skin(self, skin_id: str):
        acc = self._account()
        path = self._skins.path_of(skin_id)
        if not acc or not path or not os.path.isfile(path):
            return
        if confirm(self, t("skin.upload"), t("skin.upload_confirm")) != True:
            return
        variant = skin_model(path, (self._skins.get(skin_id) or {}).get("model"))
        self.status.setStyleSheet(f"color: {COLORS['text_sub']};")
        self.status.setText(t("skin.uploading"))
        w = Worker(self._upload_job, acc.get("id", ""), path, variant)
        self._upload_worker = w
        w.finished.connect(
            lambda _r=None, sid=skin_id, aid=acc["id"]: self._on_uploaded(sid, aid))
        w.error.connect(self._on_upload_error)
        w.start()

    def _upload_job(self, account_id: str, path: str, variant: str) -> dict:
        """Runs on a worker thread: upload, refreshing the token once on 401."""
        from .skins import SkinUploadError

        def token() -> str:
            acct = accounts_manager().get(account_id) or {}
            return (acct.get("access_token") or "").strip()

        tok = token()
        try:
            return self._skins.upload(tok, path, variant)
        except SkinUploadError as e:
            if e.status != 401:
                raise
            if not accounts_manager().refresh_current_silently():
                raise
            return self._skins.upload(token(), path, variant)

    def _on_uploaded(self, skin_id: str, account_id: str):
        # The uploaded skin is now the account's real one — mirror that locally
        # so the home card and top-bar avatar switch immediately.
        try:
            self._skins.set_active(account_id, skin_id)
        except Exception:
            pass
        self.status.setText(t("skin.uploaded"))
        self._rebuild()
        self._notify_parent()

    def _on_upload_error(self, msg: str):
        self.status.setStyleSheet(f"color: {COLORS['danger']};")
        self.status.setText(t("skin.upload_failed", e=msg))

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

    # ---- cape actions ----
    def _import_cape(self):
        path = pick_files(
            self, t("skin.cape_import_title"), "",
            "PNG Images (*.png);;All Files (*.*)",
        )
        if not path:
            return
        try:
            self._skins.add_cape_file(path)
            self.cape_status.setText("")
            self._rebuild_capes()
        except Exception as e:
            self.cape_status.setStyleSheet(f"color: {COLORS['danger']};")
            self.cape_status.setText(t("skin.error", e=str(e)))

    def _download_cape(self):
        text = self.cape_name_edit.text().strip()
        if not text:
            return
        self.cape_status.setStyleSheet(f"color: {COLORS['text_sub']};")
        self.cape_status.setText(t("skin.cape_downloading", name=text))
        w = Worker(self._skins.download_cape, text)
        w.finished.connect(lambda c: self._on_cape_dl_done(c))
        w.error.connect(lambda e: self._on_cape_dl_error(str(e)))
        w.start()

    def _on_cape_dl_done(self, cape: dict):
        self.cape_status.setText(t("skin.cape_downloaded", name=cape["name"]))
        self._rebuild_capes()

    def _on_cape_dl_error(self, msg: str):
        self.cape_status.setStyleSheet(f"color: {COLORS['danger']};")
        self.cape_status.setText(t("skin.error", e=msg))

    def _cape_set_active(self, cape_id: str):
        if self._account_id:
            self._skins.set_active_cape(self._account_id, cape_id)
        self._rebuild_capes()

    def _cape_unequip(self):
        if self._account_id:
            self._skins.set_active_cape(self._account_id, None)
        self._rebuild_capes()

    def _cape_delete(self, cape_id: str, name: str):
        if confirm(self, t("skin.delete"),
                   t("skin.cape_delete_confirm", name=name)) != True:
            return
        self._skins.remove_cape(cape_id)
        self._rebuild_capes()
