"""
LobbyDialog — out-of-game lobby UI (join / create / members / copy code).

  · Join: paste/enter a U/NNNN-AAAA-SSSS-EEEE code → join
  · Create: pick an instance → generate a lobby with invite code
  · Active lobby: member list, copy code, leave
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QGroupBox, QListWidget, QListWidgetItem,
    QWidget, QProgressBar, QPushButton, QCheckBox,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from .theme import COLORS
from .i18n import t
from . import ui_kit
from .frameless import FramelessHelper, TitleBar
from .win_rounded import warn, enable_win11_round_corners
from .lobby import (
    create_lobby, join_lobby, leave_lobby,
)
from .instances import manager as instances_manager
from .core import easytier

# 第三方虚拟局域网联机工具官网（round-64 多工具选择：玩家未安装时自行挑选）
# · EasyTier   —— 开源虚拟局域网内核，启动器内置下载（easytier.py）
# · 陶瓦 Terracotta —— 基于 EasyTier 的 P2P 联机工具（Burning_TNT 开源）
# · MCTier    —— 免安装联机工具，内置语音/聊天/文件传输/屏幕共享（官网 mctier.pmhs.top）
TERRACOTTA_URL = "https://github.com/burningtnt/Terracotta/releases"
MCTIER_URL = "https://mctier.pmhs.top"


class _ToolPicker(QDialog):
    """联机工具选择器（round-78 完善）：EasyTier 推荐位——accent 整行大按钮 +
    「推荐」徽标 + 说明自动下载并接回联机；陶瓦 / MCTier 降为官网备选。
    可勾选「记住选择」：下次未安装时直接自动下载 EasyTier，不再弹窗。

    exec() 返回码：1=EasyTier，2=Terracotta，3=MCTier，0=取消。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("lobby.tool_title"))
        self.setModal(True)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(
            self, title=t("lobby.tool_title"), height=38, controls="close")
        root.addWidget(self.titlebar)

        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 10, 20, 16)
        lay.setSpacing(8)

        ti = QLabel(t("lobby.tool_title"))
        ti.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {COLORS['text_main']};")
        lay.addWidget(ti)

        body = QLabel(t("lobby.tool_body"))
        body.setStyleSheet(f"color: {COLORS['text_sub']}; font-size: 12px;")
        body.setWordWrap(True)
        lay.addWidget(body)
        lay.addSpacing(4)

        # ── EasyTier：推荐位 ──
        et_row = QHBoxLayout()
        et_row.setSpacing(8)
        et_btn = ui_kit.make_button(
            t("lobby.tool_easytier"), kind="accent",
            on_click=lambda: self.done(1), min_h=44)
        et_row.addWidget(et_btn, stretch=1)
        badge = QLabel(t("lobby.tool_recommend"))
        badge.setStyleSheet(
            f"background: {COLORS.get('accent_soft', '#EDE9FE')}; "
            f"color: {COLORS.get('accent', '#7C3AED')}; "
            f"border-radius: 10px; font-size: 11px; font-weight: 600; "
            f"padding: 3px 9px;")
        badge.setAlignment(Qt.AlignCenter)
        et_row.addWidget(badge)
        lay.addLayout(et_row)
        ed_lbl = QLabel(t("lobby.tool_easytier_desc"))
        ed_lbl.setStyleSheet(f"color: {COLORS['text_sub']}; font-size: 11px;")
        ed_lbl.setWordWrap(True)
        lay.addWidget(ed_lbl)

        # ── 备选：陶瓦 / MCTier（官网跳转，需自行安装、不接回启动器托管）──
        for code, name, desc in [
            (2, t("lobby.tool_terracotta"), t("lobby.tool_terracotta_desc")),
            (3, t("lobby.tool_mctier"), t("lobby.tool_mctier_desc")),
        ]:
            btn = ui_kit.make_button(
                name, kind="secondary",
                on_click=lambda c=code: self.done(c), min_h=40)
            lay.addWidget(btn)
            dl = QLabel(desc)
            dl.setStyleSheet(f"color: {COLORS['text_sub']}; font-size: 11px;")
            dl.setWordWrap(True)
            lay.addWidget(dl)

        lay.addSpacing(6)
        self._remember = QCheckBox(t("lobby.tool_remember"))
        self._remember.setStyleSheet(f"color: {COLORS['text_main']};")
        lay.addWidget(self._remember)

        lay.addSpacing(8)
        cancel = ui_kit.make_button(
            t("lobby.tool_cancel"), kind="secondary",
            on_click=lambda: self.done(0), min_h=36)
        lay.addWidget(cancel)

        root.addWidget(panel, stretch=1)

        # ── frameless + DWM shadow + win11 rounded corners ──
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        enable_win11_round_corners(self)

    def remember_checked(self) -> bool:
        """「记住选择」是否被勾选（勾选 → 下次自动下载 EasyTier）。"""
        return bool(self._remember.isChecked())


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
            code_row.addWidget(ui_kit.make_button(
                txt, kind="accent" if txt == t("lobby.join_btn") else None,
                on_click=slot, min_h=36))
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
        self.create_btn = ui_kit.make_button(
            t("lobby.create_btn"), kind="accent", on_click=self._do_create,
            min_h=38, min_w=120)
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
        copy_btn = ui_kit.make_button(
            t("lobby.copy_code"), on_click=self._copy_code, min_h=34)
        code_display_row.addWidget(copy_btn)
        pl.addLayout(code_display_row)

        # Member list
        self.member_list = QListWidget()
        self.member_list.setMinimumHeight(120)
        pl.addWidget(self.member_list)

        # Leave button
        leave_row = QHBoxLayout()
        leave_row.addStretch(1)
        self.leave_btn = ui_kit.make_button(
            t("common.close"), kind="secondary", on_click=self._do_leave, min_h=34)
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
            warn(self, t("lobby.title"), t("lobby.not_found"))

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
            self.et_status.setText(t("lobby.tool_missing"))
            # 未安装联机工具：弹出选择器，EasyTier 内置下载 / 陶瓦 / MCTier 打开官网
            self._choose_tool_prompt(lob)
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

    def _choose_tool_prompt(self, lob):
        """未安装联机工具时的引导（round-78 完善）：

        设置里选了「自动 EasyTier」→ 不再弹窗，直接自动下载；
        否则弹选择器：EasyTier 推荐位，勾选「记住选择」后写入偏好。
        无论选择哪个，大厅簿记仍可继续使用；只有 EasyTier 会由启动器
        自动下载并接回虚拟局域网启动流程。
        """
        try:
            from .settings_dialog import load_config
            pref = load_config().get("lobby_tool", "ask")
        except Exception:  # noqa: BLE001 - 配置读取失败按默认每次询问
            pref = "ask"
        if pref == "easytier":
            self._download_easytier()
            return
        pick = _ToolPicker(self)
        code = pick.exec()
        if code == 1:
            if pick.remember_checked():
                try:
                    from .settings_dialog import save_config, load_config as _lc
                    cfg = _lc()
                    cfg["lobby_tool"] = "easytier"
                    save_config(cfg)
                except Exception:  # noqa: BLE001 - 记不住也不阻塞联机
                    pass
            self._download_easytier()
        elif code in (2, 3):
            url = TERRACOTTA_URL if code == 2 else MCTIER_URL
            self._open_url(url)
            self._status(t("lobby.tool_browser"))

    def _open_url(self, url: str):
        """用系统默认浏览器打开外部链接。"""
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception:  # noqa: BLE001
            pass

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
