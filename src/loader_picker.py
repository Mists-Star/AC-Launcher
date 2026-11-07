"""加载器卡片 / 选择器（round-189 建，round-196 统一）。

☠ round-196 之前有**两套**加载器选择器：
* 新建实例向导：``pages_instances._LoaderCard``（40px logo + 对勾 + QSS 类）
* 实例编辑「修改」页：``loader_picker.LoaderCard``（30px logo + accent 描边）

同一个功能两套 UI —— 玩家在两个页面看到的加载器卡片长得不一样、选中反馈也不
一样。现在**只有这一套**，两处共用。

视觉沿用新建向导那套（QSS 类 ``loader-card`` / ``loader-card-on`` + 右侧对勾），
因为它更完整；对勾用自绘图形（``ui_kit.state_pix``），Windows 下文本 ✓ 会被
Segoe UI Emoji 渲染成彩色。

logo 复用 ``assets/icons/loader_*.png``（HMCL 已整理好的现成图标集，
见 assets/icons/LOADER_LOGOS.md）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from .icons import icon
from .theme import COLORS

#: 加载器 id → logo 资源名（assets/icons/loader_*.png，_KEEP_COLOR 不染色）
LOGO_NAMES = {
    "vanilla": "loader_vanilla",
    "fabric": "loader_fabric",
    "forge": "loader_forge",
    "neoforge": "loader_neoforge",
    "quilt": "loader_quilt",
    "optifine": "loader_optifine",
    "liteloader": "loader_liteloader",
    "legacyfabric": "loader_legacyfabric",
    "cleanroom": "loader_cleanroom",
    "labymod": "loader_labymod",
}

_logo_cache: dict[tuple, QPixmap] = {}


def loader_logo(loader_id: str, size: int = 28) -> QPixmap:
    """加载器 logo（无 logo 时返回空图，由调用方回落默认图标）。"""
    key = (loader_id, size)
    if key in _logo_cache:
        return _logo_cache[key]
    name = LOGO_NAMES.get((loader_id or "").lower())
    pm = QPixmap()
    if name:
        pm = icon(name).pixmap(size, size)
        if pm.isNull():
            pm = QPixmap()
    _logo_cache[key] = pm
    return pm


class LoaderCard(QFrame):
    """单个加载器卡片：logo + 名称 + 一句说明 + 右侧选中对勾。

    选中态走全局 QSS 类（``loader-card-on``），随明暗主题自动切换。
    """

    picked = Signal(str)

    def __init__(self, parent, loader_id: str, title: str, subtitle: str = "",
                 logo_size: int = 40):
        super().__init__(parent)
        self.loader_id = loader_id
        self.setObjectName("loaderCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("cls", "loader-card")
        self.setFixedHeight(82)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        pm = loader_logo(loader_id, logo_size)
        logo = QLabel()
        if not pm.isNull():
            logo.setPixmap(pm)
        else:
            logo.setPixmap(icon("mods").pixmap(logo_size - 8, logo_size - 8))
            logo.setStyleSheet("background:%s;border-radius:7px;"
                               % COLORS["bg_hover"])
        logo.setFixedSize(logo_size, logo_size)
        logo.setScaledContents(True)
        lay.addWidget(logo, 0, Qt.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(3)
        self.title_lbl = QLabel(title)
        self.title_lbl.setProperty("cls", "title")
        mid.addWidget(self.title_lbl)
        if subtitle:
            self.sub_lbl = QLabel(subtitle)
            self.sub_lbl.setProperty("cls", "sub")
            self.sub_lbl.setWordWrap(True)
            mid.addWidget(self.sub_lbl)
        lay.addLayout(mid, 1)

        # 选中对勾（自绘图形，不用文本 ✓ —— Windows 下会被渲染成彩色 emoji）
        from .ui_kit import state_pix
        self._check = QLabel()
        self._check.setPixmap(state_pix("done", COLORS.get("accent", "#7C3AED"),
                                        15))
        self._check.setFixedSize(16, 16)
        self._check.setVisible(False)
        lay.addWidget(self._check, 0, Qt.AlignTop)

    def set_selected(self, on: bool) -> None:
        self._check.setVisible(on)
        self.setProperty("cls", "loader-card-on" if on else "loader-card")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, ev) -> None:  # noqa: N802 - Qt 命名
        if ev.button() == Qt.LeftButton:
            self.picked.emit(self.loader_id)
        super().mousePressEvent(ev)


class LoaderPicker(QWidget):
    """加载器卡片网格（新建向导与实例编辑共用）。"""

    changed = Signal(str)

    def __init__(self, entries, parent=None, exclude=()):
        """``entries``: ``[(loader_id, 标题, 说明), ...]``。"""
        super().__init__(parent)
        self._cards: dict[str, LoaderCard] = {}
        self._current: str = ""
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(8)
        exclude = set(exclude or ())
        for lid, title, subtitle in entries:
            if lid in exclude:
                continue
            card = LoaderCard(self, lid, title, subtitle)
            card.picked.connect(self._on_pick)
            self._cards[lid] = card
        self._repack()

    def _repack(self) -> None:
        """按 3 列重排（只隐藏会留空洞 —— 最后一行飘着一张卡很难看）。"""
        for card in self._cards.values():
            self._grid.removeWidget(card)
        idx = 0
        for lid, card in self._cards.items():
            if card.isHidden():
                continue
            self._grid.addWidget(card, idx // 3, idx % 3)
            idx += 1
        self._grid.setColumnStretch(3, 1)

    def _on_pick(self, loader_id: str) -> None:
        self.set_current(loader_id)
        self.changed.emit(loader_id)

    def set_current(self, loader_id: str) -> None:
        self._current = loader_id or ""
        for lid, card in self._cards.items():
            card.set_selected(lid == loader_id)

    def current(self) -> str:
        """当前**选中**的加载器 id（不是"第一个可用的卡"）。"""
        return self._current

    def card(self, loader_id: str):
        return self._cards.get(loader_id)

    def set_available(self, allowed) -> None:
        """按可用性过滤（该 MC 版本真有的加载器才留）并重排。"""
        allow = set(allowed or ())
        for lid, card in self._cards.items():
            card.setVisible(lid in allow)
        self._repack()

    def enable(self, on: bool) -> None:
        for card in self._cards.values():
            card.setEnabled(on)
