"""
LobbyDialog — out-of-game lobby UI (join / create / members / copy code).

Matches the PCL/HMCL lobby pattern:
  · Join: paste/enter a U/NNNN-AAAA-SSSS-EEEE code → join
  · Create: pick an instance → generate a lobby with invite code
  · Active lobby: member list, copy code, leave
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QListWidget, QListWidgetItem,
    QWidget, QProgressBar,
)
from PySide6.QtCore import Qt
from .theme import COLORS
from .i18n import t
from .frameless import FramelessHelper, TitleBar
from .win_rounded import warn, info, confirm
from .lobby import (
    create_lobby, join_lobby, leave_lobby,
)
from .instances import manager as instances_manager
from .core import easytier


class LobbyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("lobby.title"))
        self.resize(620, 560)
        self._current_lobby = None
        self._player_name = "Player"

        # try to get player name from account
        try:
            from .accounts import manager as accounts_manager
            acc = accounts_manager().current()
            if acc:
                self._player_name = acc.get("name", "Player")
        except Exception:
            pass

        # frameless shell
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self, title=t("lobby.title"), height=38)
        root.addWidget(self.titlebar)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(16)

        # ── JOIN section ──
        join_grp = QGroupBox(t("lobby.join"))
        jl = QVBoxLayout(join_grp)
        jl.setSpacing(8)
        jl.addWidget(QLabel(t("lobby.join_help")))
        code_row = QHBoxLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText(t("lobby.join_code_ph"))
        self.code_input.setMinimumHeight(36)
        code_row.addWidget(self.code_input, stretch=1)
        for txt, slot in [
            (t("lobby.clear"), lambda: self.code_input.clear()),
            (t("lobby.paste"), self._paste_code),
            (t("lobby.join_btn"), self._do_join),
        ]:
            btn = QPushButton(txt)
            btn.setMinimumHeight(36)
            if txt == t("lobby.join_btn"):
                btn.setProperty("cls", "accent")
            btn.clicked.connect(slot)
            code_row.addWidget(btn)
        jl.addLayout(code_row)
        lay.addWidget(join_grp)

        # ── CREATE section ──
        create_grp = QGroupBox(t("lobby.create"))
        cl = QVBoxLayout(create_grp)
        cl.setSpacing(8)
        cl.addWidget(QLabel(t("lobby.create_help")))
        inst_row = QHBoxLayout()
        self.inst_combo = QComboBox()
        inst_mgr = instances_manager()
        for inst in inst_mgr.list():
            self.inst_combo.addItem(f"{inst.name} ({inst.game_version})", inst.id)
        inst_row.addWidget(QLabel(t("lobby.create_instance")))
        inst_row.addWidget(self.inst_combo, stretch=1)
        cl.addLayout(inst_row)

        create_btn_row = QHBoxLayout()
        self.create_btn = QPushButton(t("lobby.create_btn"))
        self.create_btn.setProperty("cls", "accent")
        self.create_btn.setMinimumHeight(38)
        self.create_btn.clicked.connect(self._do_create)
        create_btn_row.addWidget(self.create_btn)
        create_btn_row.addStretch(1)
        cl.addLayout(create_btn_row)
        lay.addWidget(create_grp)

        # ── Current lobby panel (hidden until joined/created) ──
        self.lobby_panel = QGroupBox(t("lobby.members"))
        self.lobby_panel.setVisible(False)
        pl = QVBoxLayout(self.lobby_panel)
        pl.setSpacing(8)

        # EasyTier 虚拟局域网状态行
        self.et_status = QLabel("")
        self.et_status.setProperty("cls", "sub")
        self.et_status.setWordWrap(True)
        pl.addWidget(self.et_status)

        # Code display + copy
        code_display_row = QHBoxLayout()
        code_display_row.addWidget(QLabel(t("lobby.code_label")))
        self.lobby_code_lbl = QLabel()
        self.lobby_code_lbl.setStyleSheet(
            f"font-family: 'Consolas', 'Courier New', monospace; "
            f"font-size: 14px; color: {COLORS['accent']}; font-weight: bold;"
        )
        code_display_row.addWidget(self.lobby_code_lbl, stretch=1)
        copy_btn = QPushButton(t("lobby.copy_code"))
        copy_btn.clicked.connect(self._copy_code)
        code_display_row.addWidget(copy_btn)
        pl.addLayout(code_display_row)

        # Member list
        self.member_list = QListWidget()
        self.member_list.setMinimumHeight(120)
        pl.addWidget(self.member_list)

        # Leave button
        leave_row = QHBoxLayout()
        leave_row.addStretch(1)
        self.leave_btn = QPushButton(t("common.close"))
        self.leave_btn.setMinimumHeight(34)
        self.leave_btn.clicked.connect(self._do_leave)
        leave_row.addWidget(self.leave_btn)
        pl.addLayout(leave_row)

        lay.addWidget(self.lobby_panel)

        # ── Status line (replaces missing QDialog.statusBar) ──
        self._status_lbl = QLabel("")
        self._status_lbl.setProperty("cls", "sub")
        self._status_lbl.setWordWrap(True)
        lay.addWidget(self._status_lbl)

        # ── EasyTier install progress (hidden unless downloading) ──
        self.et_progress = QProgressBar()
        self.et_progress.setVisible(False)
        lay.addWidget(self.et_progress)

        lay.addStretch(1)

        root.addWidget(body, stretch=1)
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

    def _paste_code(self):
        from PySide6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        text = cb.text()
        if text:
            self.code_input.setText(text.strip())

    def _do_join(self):
        code = self.code_input.text().strip()
        if not code:
            return
        lob = join_lobby(code, self._player_name)
        if lob:
            self._current_lobby = lob
            self._show_lobby(lob)
            self._status(t("lobby.joined", name=lob.name))
            from .achievements import achievements as _ach
            _ach.unlock("first_join")
            self._start_easytier(lob)
        else:
            warn(
                self, t("lobby.title"),
                t("lobby.join_error", e="未找到该编号的大厅"),
            )

    def _do_create(self):
        name = f"{self._player_name} 的大厅"
        inst_id = ""
        if self.inst_combo.count() > 0:
            idx = self.inst_combo.currentIndex()
            inst_id = self.inst_combo.itemData(idx) or ""
        lob = create_lobby(name, inst_id, self._player_name)
        self._current_lobby = lob
        self._show_lobby(lob)
        self._status(t("lobby.created"))
        from .achievements import achievements as _ach
        _ach.unlock("first_join")
        self._start_easytier(lob)

    # ---------------------------------------------------------- EasyTier
    def _start_easytier(self, lob):
        """Launch a virtual-LAN node for this lobby (best effort)."""
        if not easytier.easytier_installed():
            self._status("")
            self.et_status.setText(t("lobby.et_missing"))
            dl = QPushButton(t("lobby.et_download"))
            dl.setMinimumHeight(34)
            dl.clicked.connect(self._download_easytier)
            # Reuse et_status area: append a download button under it.
            # Simplest: show a confirm dialog instead.
            from .win_rounded import confirm as _confirm
            if _confirm(
                self, t("lobby.et_download_title"),
                t("lobby.et_download_body"),
            ):
                self._download_easytier()
            return
        self.et_status.setText(t("lobby.et_starting"))
        from .worker import Worker
        net_name = lob.code
        secret = lob.secret or lob.code
        self._et_worker = Worker(
            easytier.start_node, net_name, secret,
            hostname=self._player_name,
        )
        self._et_worker.finished.connect(self._on_et_started)
        self._et_worker.error.connect(
            lambda e: self.et_status.setText(t("lobby.et_error", e=str(e)))
        )
        self._et_worker.start()

    def _on_et_started(self, result: dict):
        if not result or not result.get("ok"):
            self.et_status.setText(
                t("lobby.et_error", e=result.get("error", "unknown"))
            )
            return
        ip = result.get("ip", "")
        if ip:
            self.et_status.setText(t("lobby.et_ready", ip=ip))
        else:
            self.et_status.setText(t("lobby.et_ready_noip"))

    def _download_easytier(self):
        """Download + unzip easytier-core into the data dir."""
        self.et_progress.setVisible(True)
        self.et_progress.setRange(0, 100)
        self.et_status.setText(t("lobby.et_downloading"))
        from .worker import Worker
        dest = easytier.bundled_dir()

        def _dl():
            return easytier.download_easytier(
                dest, progress=lambda f: self.et_progress.setValue(int(f * 100))
            )

        w = Worker(_dl)
        w.finished.connect(self._on_et_downloaded)
        w.error.connect(
            lambda e: self.et_status.setText(t("lobby.et_dl_error", e=str(e)))
        )
        self._dl_worker = w
        w.start()

    def _on_et_downloaded(self, exe_path: str):
        self.et_progress.setVisible(False)
        self.et_status.setText(t("lobby.et_installed"))
        if self._current_lobby:
            self._start_easytier(self._current_lobby)

    def _status(self, msg: str):
        self._status_lbl.setText(msg)

    def _show_lobby(self, lob):
        """Display the active lobby panel."""
        self.lobby_panel.setVisible(True)
        self.lobby_code_lbl.setText(lob.code)
        self.member_list.clear()
        for m in lob.members:
            name = m.get("name", "?")
            item = QListWidgetItem(f"{name}")
            if name == self._player_name or name == lob.host:
                item.setText(f"{name}（你）" if name == self._player_name else f"{name}（主机）")
            self.member_list.addItem(item)

    def _copy_code(self):
        if self._current_lobby:
            from PySide6.QtWidgets import QApplication
            cb = QApplication.clipboard()
            cb.setText(self._current_lobby.code)
            self._status(t("lobby.copied"))

    def _do_leave(self):
        if self._current_lobby:
            leave_lobby(self._current_lobby.id, self._player_name)
            easytier.stop_node()
            self._current_lobby = None
            self.lobby_panel.setVisible(False)
            self._status("")

    def closeEvent(self, event):
        # Stop the virtual-LAN node when the lobby window closes.
        easytier.stop_node()
        super().closeEvent(event)
