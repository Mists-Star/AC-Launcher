"""LoginDialog — Microsoft device-code OAuth + external (Yggdrasil) login + offline.

Flows:
  - Microsoft: request a device code (main thread, fast) -> show code + URL ->
    poll for completion in a worker -> store the profile.
  - External / third-party: Yggdrasil auth against a user-supplied server URL.
  - Offline: no network, just a username (single-player / cracked servers).

On success the chosen account is persisted via the AccountsManager and handed
back through ``self.account`` for the main window.
"""
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QStackedWidget, QScrollArea,
)
from PySide6.QtCore import Qt, QSize, QUrl, Signal, QTimer
import os
import webbrowser
import secrets

from PySide6.QtGui import QDesktopServices, QPixmap, QColor, QLinearGradient

from .theme import COLORS, RoundedCard
from .icons import icon
from .i18n import t
from .worker import Worker
from .core import auth
from .brand import MS_CLIENT_ID as BRAND_MS_CLIENT_ID
from .win_rounded import enable_dark_titlebar, info
from .accounts import manager as accounts_manager, type_label
from .settings_dialog import load_config
from .skins import manager as skin_manager
from .skin_render import render_head


class LoginDialog(QDialog):
    # Microsoft device-code ready: emitted from the worker thread; queued
    # connection auto-delivers on the UI thread so we can update the dialog
    # safely without race conditions.
    ms_user_code_ready = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("login.title"))
        # Standard modal dialog: keeps the native title bar + Win11's own
        # rounded corners, so we drop FramelessHelper entirely. The old
        # frameless + DwmExtendFrameIntoClientArea hack fought with the round
        # corner attribute and shifted hit-testing, which read as "UI 错位"
        # (misaligned clicks / clipped content). Fixed size keeps the layout
        # predictable across DPI/theme changes.
        self.setFixedSize(460, 580)
        self.account = None
        # Guard against worker callbacks firing on a closed/destroyed dialog
        # (e.g. user pressed × while the loopback was still waiting).
        self._closed = False
        self._cfg = load_config()
        _cfg_cid = (self._cfg.get("ms_client_id") or "").strip().lower()
        # ms_client_id is hardcoded in brand.py — never user-configurable in
        # settings (the old QLineEdit was removed). brand.MS_CLIENT_ID is the
        # authoritative default. The old auth.MICROSOFT_CLIENT_ID fallback
        # (00000000402b12d1) has an incompatible redirect_uri, so it's no
        # longer used.
        self._client_id = (
            _cfg_cid if _cfg_cid and _cfg_cid not in auth._BAD_CLIENT_IDS
            else BRAND_MS_CLIENT_ID
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # QStackedWidget holds the choice / device-code views, each wrapped in
        # a scroll area so the (tall) choice page never gets clipped at the
        # bottom on small screens / different DPI.
        self.stack = QStackedWidget()
        self.stack.addWidget(self._wrap_scroll(self._build_choice()))
        self.stack.addWidget(self._wrap_scroll(self._build_code()))
        root.addWidget(self.stack, stretch=1)

        # 初始显隐：已登录 → 显示"登录其他账号"开关；未登录 → 直接显示登录方式
        self._refresh_account()
        if accounts_manager().current():
            self.switch_btn.setVisible(True)
            self._login_box.setVisible(False)
        else:
            self.switch_btn.setVisible(False)
            self._login_box.setVisible(True)

        # Standard QDialog keeps the native title bar; paint it dark so it
        # doesn't show a white bar against the launcher's dark theme. (The
        # frameless route was dropped because its DWM shadow hack fought the
        # round-corner attribute and mis-aligned clicks in a modal dialog.)
        enable_dark_titlebar(self)

    # ----------------------------------------------------------- choice view
    def _build_choice(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        # ---- hero gradient banner（对齐 Account 设计语言：紫→洋红渐变）----
        lay.addWidget(self._build_hero())

        # ---- current account card (avatar + name + skin manager) ----
        self._acard = QWidget()
        self._acard_lay = QVBoxLayout(self._acard)
        self._acard_lay.setContentsMargins(0, 0, 0, 0)
        self._acard_lay.setSpacing(0)
        lay.addWidget(self._acard)

        # ---- "登录其他账号"开关（已登录时显示，点击展开全部登录方式）----
        self.switch_btn = QPushButton(t("login.switch_account"))
        self.switch_btn.setMinimumHeight(36)
        self.switch_btn.setCursor(Qt.PointingHandCursor)
        self.switch_btn.clicked.connect(self._show_login_options)
        lay.addWidget(self.switch_btn)

        # ---- 全部登录方式（无账号时默认显示；有账号时点击"登录其他账号"展开）----
        self._login_box = QWidget()
        lb = QVBoxLayout(self._login_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.setSpacing(14)

        # 微软登录——主入口（无账号时最优先、最醒目）
        # 2026-08 现状：Microsoft 已撤回所有免注册的公共 client_id，
        # 老 XBL 端点 login.live.com 报 "client does not exist"，
        # 新 Microsoft Identity Platform 端点需 Azure 应用注册 + admin consent。
        # 因此这个按钮默认隐藏；想登录正版服需先在 Settings 配置 Azure client_id。
        from .core.auth import microsoft_login_available
        if microsoft_login_available(self._cfg):
            ms = QPushButton(t("login.microsoft"))
            ms.setProperty("cls", "accent")
            ms.setMinimumHeight(44)
            ms.setIcon(icon("microsoft"))
            ms.setIconSize(QSize(18, 18))
            ms.clicked.connect(self._start_microsoft)
            lb.addWidget(ms)

            sep1 = QLabel(t("login.or"))
            sep1.setProperty("cls", "sub")
            sep1.setAlignment(Qt.AlignCenter)
            lb.addWidget(sep1)
        else:
            # 没有配置有效 Azure 应用时不显示任何微软登录提示——
            # 玩家没配置就别提，没意义反而碍眼。
            pass

        # 离线模式（零配置，无需账号）
        off = QHBoxLayout()
        self.off_name = QLineEdit()
        self.off_name.setPlaceholderText(t("login.offline_placeholder"))
        off_btn = QPushButton(t("login.offline_btn"))
        off_btn.setMinimumHeight(36)
        off_btn.clicked.connect(self._start_offline)
        off.addWidget(self.off_name)
        off.addWidget(off_btn)
        lb.addLayout(off)

        # 外置登录 / 第三方（Yggdrasil / Authlib-Injector）
        ext = RoundedCard(radius=12)
        el = QVBoxLayout(ext)
        el.setContentsMargins(16, 16, 16, 16)
        el.setSpacing(8)
        ext_head = QHBoxLayout()
        ext_icon = QLabel()
        ext_icon.setPixmap(icon("external").pixmap(18, 18))
        ext_head.addWidget(ext_icon)
        ext_head.addWidget(QLabel(t("login.third_title")))
        ext_head.addStretch(1)
        el.addLayout(ext_head)
        hint = QLabel(t("login.third_hint"))
        hint.setProperty("cls", "sub")
        hint.setWordWrap(True)
        el.addWidget(hint)
        self.ext_server = QLineEdit()
        self.ext_server.setPlaceholderText(t("login.third_server_ph"))
        self.ext_user = QLineEdit()
        self.ext_user.setPlaceholderText(t("login.offline_name"))
        self.ext_pass = QLineEdit()
        self.ext_pass.setPlaceholderText("••••••")
        self.ext_pass.setEchoMode(QLineEdit.Password)
        el.addWidget(self.ext_server)
        el.addWidget(self.ext_user)
        el.addWidget(self.ext_pass)
        ext_btn = QPushButton(t("login.third_login"))
        ext_btn.setMinimumHeight(36)
        ext_btn.clicked.connect(self._start_external)
        el.addWidget(ext_btn)
        lb.addWidget(ext)
        lay.addWidget(self._login_box)

        self.error_lbl = QLabel("")
        self.error_lbl.setProperty("cls", "sub")
        self.error_lbl.setStyleSheet(f"color: {COLORS['danger']};")
        self.error_lbl.setWordWrap(True)
        lay.addWidget(self.error_lbl)
        lay.addStretch(1)
        return w

    def _show_login_options(self):
        """已登录账号 → 点击"登录其他账号"展开全部登录方式。"""
        self.switch_btn.setVisible(False)
        self._login_box.setVisible(True)

    def _build_hero(self) -> QWidget:
        """紫色→洋红渐变的顶部横幅：图标 + 标题 + 副标题（白字）。

        对齐 Account 设计稿的高光 banner，作为登录弹窗的第一视觉焦点。
        """
        g = QLinearGradient(0, 0, 460, 0)
        g.setColorAt(0.0, QColor(COLORS["accent"]))
        g.setColorAt(0.55, QColor("#9333EA"))
        g.setColorAt(1.0, QColor("#DB2777"))
        hero = RoundedCard(radius=16, fill=g)
        hero.setMinimumHeight(120)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(22, 18, 22, 18)
        hl.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(icon("account").pixmap(34, 34))
        hl.addWidget(ic)
        ttl = QLabel(t("login.heading"))
        ttl.setStyleSheet("color:#FFFFFF; font-size:22px; font-weight:800;")
        hl.addWidget(ttl)
        sub = QLabel(t("login.subtitle"))
        sub.setStyleSheet("color:rgba(255,255,255,0.92); font-size:12px;")
        sub.setWordWrap(True)
        hl.addWidget(sub)
        return hero

    # ------------------------------------------------------------- code view
    def _build_code(self) -> QWidget:
        """Device-code waiting page: shows 8-char user_code + verification URL."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        head = QLabel(t("login.code_title"))
        head.setProperty("cls", "big")
        lay.addWidget(head)
        sub = QLabel(t("login.code_desc"))
        sub.setProperty("cls", "sub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # User code display (huge, monospace, accent-coloured) — must be obvious
        self.code_value_lbl = QLabel("--------")
        self.code_value_lbl.setProperty("cls", "code")
        self.code_value_lbl.setAlignment(Qt.AlignCenter)
        self.code_value_lbl.setMinimumHeight(64)
        lay.addWidget(self.code_value_lbl)

        self.url_lbl = QLabel("")
        self.url_lbl.setProperty("cls", "sub")
        self.url_lbl.setAlignment(Qt.AlignCenter)
        self.url_lbl.setWordWrap(True)
        self.url_lbl.setOpenExternalLinks(False)
        lay.addWidget(self.url_lbl)

        btn_row = QHBoxLayout()
        open_btn = QPushButton(t("login.open_browser"))
        open_btn.setProperty("cls", "accent")
        open_btn.setMinimumHeight(38)
        open_btn.clicked.connect(self._open_browser)
        btn_row.addWidget(open_btn)
        copy_btn = QPushButton(t("login.copy_code"))
        copy_btn.setMinimumHeight(38)
        copy_btn.clicked.connect(self._copy_code)
        btn_row.addWidget(copy_btn)
        lay.addLayout(btn_row)

        self.code_status = QLabel("")
        self.code_status.setProperty("cls", "sub")
        self.code_status.setAlignment(Qt.AlignCenter)
        self.code_status.setWordWrap(True)
        lay.addWidget(self.code_status)

        back = QPushButton(t("settings.cancel"))
        back.setMinimumHeight(34)
        back.clicked.connect(self._cancel_ms)
        lay.addWidget(back)

        lay.addStretch(1)
        return w

    # ----------------------------------------------------------- scroll wrap
    def _wrap_scroll(self, content: QWidget) -> QScrollArea:
        """Wrap a stacked view in a scroll area so tall pages (e.g. the choice
        view on small screens) never get clipped at the bottom."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(content)
        sa.setFrameShape(QScrollArea.NoFrame)
        return sa

    # --------------------------------------------------------------- actions
    def _show_error(self, msg: str):
        if self._closed:
            return
        self.error_lbl.setText(msg)
        self.stack.setCurrentIndex(0)

    # ----------------------------------------------------- current account
    def _refresh_account(self):
        while self._acard_lay.count():
            w = self._acard_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        acc = accounts_manager().current()
        if not acc:
            hint = QLabel(t("login.no_account"))
            hint.setProperty("cls", "sub")
            self._acard_lay.addWidget(hint)
            return
        card = RoundedCard(radius=12)
        hl = QHBoxLayout(card)
        hl.setContentsMargins(14, 14, 14, 14)
        hl.setSpacing(14)
        av = QLabel()
        av.setFixedSize(56, 56)
        av.setPixmap(self._avatar(acc))
        hl.addWidget(av)
        info = QVBoxLayout()
        info.setSpacing(2)
        nm = QLabel(acc.get("name", "Player"))
        nm.setProperty("cls", "big")
        info.addWidget(nm)
        tp = QLabel(type_label(acc.get("type", "")))
        tp.setProperty("cls", "sub")
        info.addWidget(tp)
        hl.addLayout(info, stretch=1)
        btn = QPushButton(t("skin.manage"))
        btn.setMinimumHeight(34)
        btn.setIcon(icon("skin"))
        btn.setIconSize(QSize(16, 16))
        btn.clicked.connect(self._open_skins)
        hl.addWidget(btn)
        self._acard_lay.addWidget(card)

    def _avatar(self, acc: dict) -> QPixmap:
        path = skin_manager().active_path(acc.get("id"))
        if path and os.path.exists(path):
            return render_head(path, 56)
        return icon("account").pixmap(56, 56)

    def _open_skins(self):
        acc = accounts_manager().current()
        if not acc:
            info(self, t("skin.title"), t("login.no_account_skin"))
            return
        from .skin_dialog import SkinDialog

        SkinDialog(self, account_id=acc["id"]).exec()
        self._refresh_account()

    def _start_microsoft(self):
        """Device-code flow start: request code, display in UI, then poll."""
        if self._closed:
            return
        self.error_lbl.setText("")
        # Pick active client_id (built-in or player-configured override)
        cid = auth.get_active_client_id(self._cfg) or BRAND_MS_CLIENT_ID
        self._client_id = cid

        # Reset UI
        self.code_value_lbl.setText("--------")
        self.url_lbl.setText(t("login.code_fetching"))
        self.code_status.setText("")
        self.stack.setCurrentIndex(1)

        # Cancel token for the worker poll loop
        import threading as _th
        self._ms_cancel = _th.Event()

        # Signal connection: worker → UI thread, queued connection handles
        # cross-thread delivery automatically (worker thread has no event loop).
        self.ms_user_code_ready.connect(self._on_ms_user_code)

        # Worker runs the entire device-code flow but emits the user_code via
        # the signal as soon as it's issued — UI updates + browser open happen
        # BEFORE the token polling starts (matches the feel of mainstream launchers).
        cid_outer = cid
        cancel_outer = self._ms_cancel

        def _do_login():
            code = auth.request_device_code(cid_outer)
            # Emit signal — Qt routes to UI thread via queued connection.
            self.ms_user_code_ready.emit(
                code["user_code"], code.get("verification_uri", "")
            )
            token = auth.poll_for_token(
                cid_outer,
                code["device_code"],
                interval=code.get("interval", 5),
                expires_in=code.get("expires_in", 900),
                cancel=cancel_outer,
            )
            if token is None:
                raise auth.MicrosoftAuthError("登录已取消")
            return auth.complete_login_with_token(cid_outer, token)

        self._ms_worker = Worker(_do_login)
        self._ms_worker.finished.connect(self._on_ms_done)
        self._ms_worker.error.connect(
            lambda e: self._show_error(t("login.error", e=str(e)))
        )
        self._ms_worker.start()

    def _on_ms_user_code(self, user_code: str, verification_uri: str):
        """Slot for the ms_user_code_ready signal — runs on the UI thread."""
        from PySide6.QtWidgets import QApplication
        # Auto-copy the code to clipboard so the player only has to paste it
        # in the browser (matches mainstream launcher behaviour).
        QApplication.clipboard().setText(user_code)
        self._pending_user_code = (user_code, verification_uri)
        self._consume_user_code()

    def _consume_user_code(self):
        uc = getattr(self, "_pending_user_code", None)
        if not uc:
            return
        user_code, verification_uri = uc
        self.code_value_lbl.setText(user_code)
        self._pending_verification_uri = verification_uri
        self.url_lbl.setText(t("login.code_url_label", url=verification_uri))
        self.code_status.setText(t("login.code_waiting"))
        # auto-open browser once
        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass

    def _open_browser(self):
        url = getattr(self, "_pending_verification_uri", None)
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def _copy_code(self):
        from PySide6.QtWidgets import QApplication
        code = self.code_value_lbl.text().strip()
        if not code or code == "--------":
            return
        QApplication.clipboard().setText(code)
        self.code_status.setText(t("login.code_copied"))

    def _cancel_ms(self):
        # Signal the worker to stop polling, then wait for it to exit BEFORE
        # the dialog can be destroyed.  Without the wait, the worker thread
        # keeps running (up to 15 min) while the QDialog is gone; when it
        # finally emits finished/error, Qt hits a destroyed C++ object and
        # fast-fails the process (exit code 3221226505 / 0xC0000409).
        if hasattr(self, "_ms_cancel"):
            self._ms_cancel.set()
        w = getattr(self, "_ms_worker", None)
        if w is not None and w.isRunning():
            w.wait(6000)  # give the poll loop a moment to unwind (interval 5s)
        self.code_status.setText(t("login.code_cancelled"))
        self.stack.setCurrentIndex(0)

    def closeEvent(self, event):
        """Dialog closed mid-login: cancel + join the worker thread so Qt never
        emits into a destroyed QDialog (the 0xC0000409 crash)."""
        if hasattr(self, "_ms_cancel"):
            self._ms_cancel.set()
        w = getattr(self, "_ms_worker", None)
        if w is not None and w.isRunning():
            w.wait(6000)
        self._closed = True
        super().closeEvent(event)

    def _on_ms_done(self, profile: dict):
        # Worker may finish after the user closed the dialog (X-button mid-
        # login). Silently drop the result so we don't disturb the main window.
        if self._closed:
            return
        self.code_status.setText("")
        profile.setdefault("type", "microsoft")
        acc = accounts_manager().add(profile)
        self.account = acc
        if acc.get("id"):
            # pull the player's real skin in the background and set it active.
            # Minecraft's profile "id" field IS the player UUID.
            # Keep a reference (self._skin_worker) so QThread is not destroyed
            # mid-run when this dialog closes (the "Destroyed while running"
            # warning) and so the account card can refresh once done.
            self._skin_worker = Worker(
                self._fetch_skin, acc["id"], acc["id"], acc.get("name", "")
            )
            self._skin_worker.finished.connect(self._on_skin_fetched)
            self._skin_worker.start()
        self.accept()

    def _on_skin_fetched(self, _result=None):
        # After the skin lands, refresh the account card (avatar) once more.
        if self._closed:
            return
        try:
            self._refresh_account()
        except Exception:
            pass

    def _fetch_skin(self, acc_id: str, uuid: str, name: str):
        try:
            skin_manager().download_by_uuid(uuid, name)
            for s in reversed(skin_manager().list()):
                if s.get("player") == name:
                    skin_manager().set_active(acc_id, s["id"])
                    break
        except Exception:
            pass

    def _open_browser(self):
        if getattr(self, "_url", ""):
            QDesktopServices.openUrl(QUrl(self._url))

    def _start_external(self):
        self.error_lbl.setText("")
        server = self.ext_server.text().strip()
        user = self.ext_user.text().strip()
        pw = self.ext_pass.text()
        if not server or not user or not pw:
            self._show_error(t("login.error", e="请填写服务器地址、用户名和密码"))
            return
        self._ext_worker = Worker(auth.yggdrasil_login, server, user, pw)
        self._ext_worker.finished.connect(self._on_ext_done)
        self._ext_worker.error.connect(lambda e: self._show_error(t("login.error", e=str(e))))
        self._ext_worker.start()

    def _on_ext_done(self, profile: dict):
        if self._closed:
            return
        self.account = accounts_manager().add(profile)
        self.accept()

    # ── close lifecycle ────────────────────────────────────────────────
    def reject(self):
        # X-button / Esc / dialog.close(). Worker may still be running.
        self._closed = True
        self._teardown_workers()
        super().reject()

    def closeEvent(self, event):
        # Same safety as reject(): if the dialog is being torn down, mark it
        # so worker callbacks bail out, then stop the worker cleanly.
        self._closed = True
        self._teardown_workers()
        super().closeEvent(event)

    def _teardown_workers(self):
        for attr in ("_ms_worker", "_ext_worker"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if w.isRunning():
                    w.quit()
                    w.wait(500)
            except RuntimeError:
                pass  # C++ object already gone
            setattr(self, attr, None)

    def _start_offline(self):
        name = self.off_name.text().strip() or "Player"
        self.account = accounts_manager().add({
            "name": name, "uuid": "", "access_token": "", "type": "offline",
        })
        self.accept()
