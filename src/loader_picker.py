"""加载器卡片选择器 + 加载器 logo（round-189）。

为什么不用下拉：修改页里「选哪个加载器」是这页最大的一个决策，而下拉把 logo、
名字、说明全藏起来了 —— 玩家点开才知道选了啥，出了问题更看不出。PCL/HMCL 的
做法都是**带 logo 的卡片列表**，一眼扫过去就知道每个加载器是什么。

本模块提供：

* :func:`loader_logo` —— 加载器 logo（复用 assets/icons/loader_*.png，
  来自 HMCL 已整理好的现成图标集，见 assets/icons/LOADER_LOGOS.md）；
* :class:`LoaderCard` —— 单张卡片（logo + 名称 + 一句说明）；
* :class:`LoaderPicker` —— 卡片网格，负责按可用性过滤 + 选中态。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
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
    """加载器 logo（无 logo 时回落到通用方块）。"""
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
    """单个加载器卡片。"""

    picked = Signal(str)

    def __init__(self, loader_id: str, title: str, subtitle: str = "",
                 parent=None):
        super().__init__(parent)
        self.loader_id = loader_id
        self.setObjectName("loaderCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(62)
        self.setMinimumWidth(168)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        logo = QLabel()
        pm = loader_logo(loader_id, 30)
        if not pm.isNull():
            logo.setPixmap(pm)
        else:
            logo.setPixmap(icon("mods").pixmap(26, 26))
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background:%s;border-radius:8px;"
                           % COLORS["bg_frost"])
        lay.addWidget(logo)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(
            "font-size:13px;font-weight:600;color:%s;" % COLORS["text_main"])
        col.addWidget(self.title_lbl)
        if subtitle:
            self.sub_lbl = QLabel(subtitle)
            self.sub_lbl.setStyleSheet(
                "font-size:10px;color:%s;" % COLORS["text_sub"])
            col.addWidget(self.sub_lbl)
        lay.addLayout(col, 1)
        self._apply_style(False)

    def _apply_style(self, selected: bool) -> None:
        border = COLORS["accent"] if selected else COLORS["border"]
        bg = COLORS["bg_frost"] if selected else "transparent"
        self.setStyleSheet(
            "#loaderCard { background:%s; border:1px solid %s;"
            " border-radius:9px; }"
            "#loaderCard:hover { border-color:%s; }"
            % (bg, border, COLORS["border_light"]))
        self.title_lbl.setStyleSheet(
            "font-size:13px;font-weight:600;color:%s;"
            % (COLORS["accent"] if selected else COLORS["text_main"]))

    def set_selected(self, on: bool) -> None:
        self._apply_style(on)

    def mousePressEvent(self, ev) -> None:  # noqa: N802 - Qt 命名
        if ev.button() == Qt.LeftButton:
            self.picked.emit(self.loader_id)
        super().mousePressEvent(ev)


class LoaderPicker(QWidget):
    """加载器卡片网格。"""

    changed = Signal(str)

    def __init__(self, entries, parent=None):
        """``entries``: ``[(loader_id, 标题, 说明), ...]``。"""
        super().__init__(parent)
        self._cards: dict[str, LoaderCard] = {}
        self._current: str = ""
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(8)
        for i, (lid, title, subtitle) in enumerate(entries):
            card = LoaderCard(lid, title, subtitle)
            card.picked.connect(self._on_pick)
            self._cards[lid] = card
            self._grid.addWidget(card, i // 3, i % 3)
        self._grid.setColumnStretch(3, 1)

    def _on_pick(self, loader_id: str) -> None:
        self.set_current(loader_id)
        self.changed.emit(loader_id)

    def set_current(self, loader_id: str) -> None:
        self._current = loader_id or ""
        for lid, card in self._cards.items():
            card.set_selected(lid == loader_id)

    def current(self) -> str:
        """当前**选中**的加载器 id（不是"第一个可用的"）。"""
        return self._current

    def set_available(self, allowed) -> None:
        """按可用性过滤（该 MC 版本真有的加载器才留）。

        过滤后**重新按 3 列重排**：只 setVisible 会在网格里留下空洞
        （比如 9 个加载器里隐藏 3 个，最后一行只剩一张卡飘在第三列）。
        """
        allow = set(allowed or ())
        for lid, card in self._cards.items():
            card.setVisible(lid in allow)
        # 重排：先把所有卡片从布局里摘掉，再按可见顺序放回去
        for card in self._cards.values():
            self._grid.removeWidget(card)
        idx = 0
        for lid, card in self._cards.items():
            if lid not in allow:
                continue
            self._grid.addWidget(card, idx // 3, idx % 3)
            idx += 1
        self._grid.setRowStretch(idx // 3 + 1, 1)

    def enable(self, on: bool) -> None:
        for card in self._cards.values():
            card.setEnabled(on)
