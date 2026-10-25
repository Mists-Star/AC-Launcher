"""Server favorites dialog — manage saved servers & one-click direct connect.

round-83: 收藏服务器列表（增删改）+ 双击直连。直连动作交给调用方
``on_connect(host, port)``（MainWindow 用它以当前实例带 ``--server/--port`` 启动），
本对话框不关心启动细节——只负责收藏数据的浏览/编辑。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QLineEdit, QFormLayout, QDialogButtonBox,
    QMessageBox, QWidget,
)

from .theme import COLORS
from .i18n import t
from . import server_favorites as fav
from .frameless import FramelessHelper, TitleBar
from .win_rounded import enable_win11_round_corners


def _prompt_server(parent, title: str, data: dict | None = None) -> dict | None:
    """收藏编辑小窗：返回合并字段；取消返回 None。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumWidth(430)
    enable_win11_round_corners(dlg)

    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    titlebar = TitleBar(dlg, title=title, height=38, controls="close")
    root.addWidget(titlebar)
    _frameless = FramelessHelper(dlg)
    _frameless.set_titlebar(titlebar)

    body = QWidget()
    form = QFormLayout(body)
    form.setContentsMargins(20, 14, 20, 16)
    form.setSpacing(10)
    name = QLineEdit((data or {}).get("name", ""))
    name.setPlaceholderText(t("server_fav.ph_name"))
    host = QLineEdit((data or {}).get("host", ""))
    host.setPlaceholderText(t("server_fav.ph_host"))
    port = QLineEdit((data or {}).get("port", ""))
    port.setPlaceholderText(t("server_fav.ph_port"))
    note = QLineEdit((data or {}).get("note", ""))
    note.setPlaceholderText(t("server_fav.ph_note"))
    form.addRow(t("server_fav.name"), name)
    form.addRow(t("server_fav.host"), host)
    form.addRow(t("server_fav.port"), port)
    form.addRow(t("server_fav.note"), note)
    root.addWidget(body)

    btns = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    btns.button(QDialogButtonBox.StandardButton.Ok).setText(t("common.ok"))
    btns.button(QDialogButtonBox.StandardButton.Cancel).setText(t("common.cancel"))
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    root.addWidget(btns)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    out = dict(data or {})
    out["name"] = name.text().strip()
    out["host"] = host.text().strip()
    out["port"] = port.text().strip()
    out["note"] = note.text().strip()
    if not out["host"]:
        return None
    return out


class ServerFavDialog(QDialog):
    """收藏服务器浏览 / 增删改 / 双击一键直连。"""

    def __init__(self, parent=None, on_connect=None):
        super().__init__(parent)
        self._on_connect = on_connect
        self.setWindowTitle(t("server_fav.title"))
        self.resize(560, 480)
        self.setMinimumSize(480, 400)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self, title=t("server_fav.title"), height=38,
                                 controls="close")
        root.addWidget(self.titlebar)

        body = QVBoxLayout()
        body.setSpacing(10)
        body.setContentsMargins(16, 12, 16, 16)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.itemDoubleClicked.connect(lambda _it: self._connect_selected())
        self.list.itemSelectionChanged.connect(self._on_selection)
        body.addWidget(self.list, stretch=1)

        hint = QLabel(t("server_fav.hint"))
        sub_color = COLORS.get("text_sub", "#6B7280")
        hint.setStyleSheet(f"color: {sub_color}; font-size: 11px;")
        body.addWidget(hint)

        btns = QHBoxLayout()
        add_b = QPushButton(t("server_fav.add"))
        add_b.setProperty("cls", "accent")
        edt_b = QPushButton(t("server_fav.edit"))
        del_b = QPushButton(t("server_fav.del"))
        conn_b = QPushButton(t("server_fav.connect"))
        add_b.clicked.connect(self._add)
        edt_b.clicked.connect(self._edit)
        del_b.clicked.connect(self._delete)
        conn_b.clicked.connect(self._connect_selected)
        close_b = QPushButton(t("common.close"))
        close_b.clicked.connect(self.reject)
        edt_b.setEnabled(False)
        del_b.setEnabled(False)
        conn_b.setEnabled(False)
        self._edt_b, self._del_b, self._conn_b = edt_b, del_b, conn_b
        btns.addWidget(add_b)
        btns.addWidget(edt_b)
        btns.addWidget(del_b)
        btns.addStretch(1)
        btns.addWidget(conn_b)
        btns.addWidget(close_b)
        body.addLayout(btns)
        root.addLayout(body)

        # ── frameless + DWM shadow + win11 rounded corners ──
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        enable_win11_round_corners(self)

        self._reload()

    # ── 数据 ──
    def _reload(self) -> None:
        self.list.clear()
        self._items: dict[str, dict] = {}
        for s in fav.load_servers():
            self._items[s["id"]] = s
            addr = f"{s['host']}" + (f":{s['port']}" if s.get("port") else "")
            line = QListWidgetItem(f"{s['name']}   —   {addr}")
            if s.get("note"):
                line.setToolTip(s["note"])
            self.list.addItem(line)

    def _on_selection(self) -> None:
        ok = self.list.currentRow() >= 0
        for b in (self._edt_b, self._del_b, self._conn_b):
            b.setEnabled(ok)

    def _selected(self) -> dict | None:
        row = self.list.currentRow()
        if row < 0:
            return None
        key = list(self._items.keys())
        return self._items.get(key[row]) if row < len(key) else None

    def _add(self) -> None:
        data = _prompt_server(self, t("server_fav.add"))
        if not data:
            return
        fav.add_server(data["name"], data["host"], data["port"], data.get("note", ""))
        self._reload()

    def _edit(self) -> None:
        s = self._selected()
        if not s:
            return
        data = _prompt_server(self, t("server_fav.edit"), s)
        if not data:
            return
        fav.update_server(s["id"], data["name"], data["host"], data["port"],
                          data.get("note", ""))
        self._reload()

    def _delete(self) -> None:
        s = self._selected()
        if not s:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(t("server_fav.del"))
        box.setText(t("server_fav.del_ask", name=s.get("name", "")))
        yes = box.addButton(QMessageBox.StandardButton.Yes)
        yes.setText(t("server_fav.del_yes"))
        box.addButton(QMessageBox.StandardButton.No)
        box.exec()
        if box.clickedButton() is yes:
            fav.remove_server(s["id"])
            self._reload()

    def _connect_selected(self) -> None:
        s = self._selected()
        if not s or not s.get("host"):
            return
        if self._on_connect:
            self.accept()
            self._on_connect(s["host"], s.get("port", ""))