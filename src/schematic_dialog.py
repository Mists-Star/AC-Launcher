"""投影 2D 分层预览（round-171，P3）：层滑杆 + 悬停方块名 + 一键导出材料清单。

只画当前 Y 层的平面（1 格 = 1 方块），空气留空。颜色走自建近似色表；未知
方块由 ``block_palette`` 给稳定灰阶，种类数在底部提示。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider,
    QVBoxLayout, QWidget,
)

from .core import block_palette as bp
from .core import schematic as sch_mod
from .core.schematic import SchematicError
from .frameless import FramelessHelper, TitleBar
from .i18n import t
from .theme import COLORS


class _LayerCanvas(QWidget):
    """一格一方块的层平面图；鼠标悬停回报方块 id。"""

    hovered = Signal(object)          # str | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._pix = QPixmap()
        self._cells: list[str | None] = []
        self._w = 0
        self._d = 0
        self._scale = 1
        self._origin = (0.0, 0.0)
        self._empty = ""

    def set_empty(self, text: str) -> None:
        self._pix = QPixmap()
        self._cells = []
        self._w = self._d = 0
        self._empty = text
        self.update()

    def set_layer(self, w: int, d: int, cells: list[str | None]) -> None:
        img = QImage(w, d, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        for z in range(d):
            base = z * w
            for x in range(w):
                bid = cells[base + x]
                if not bid or bp.is_air(bid):
                    continue
                r, g, b = bp.color_for(bid)
                img.setPixelColor(x, z, QColor(r, g, b))
        self._pix = QPixmap.fromImage(img)
        self._cells = cells
        self._w, self._d = w, d
        self._empty = ""
        self._layout_scale()
        self.update()

    def _layout_scale(self) -> None:
        if self._w <= 0 or self._d <= 0:
            return
        self._scale = max(1, min(12, int(min(self.width() / self._w,
                                              self.height() / self._d))))
        self._origin = ((self.width() - self._w * self._scale) / 2.0,
                        (self.height() - self._d * self._scale) / 2.0)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._layout_scale()

    def mouseMoveEvent(self, ev):
        if self._pix.isNull() or self._w <= 0:
            return
        x = int((ev.position().x() - self._origin[0]) // self._scale)
        z = int((ev.position().y() - self._origin[1]) // self._scale)
        if not (0 <= x < self._w and 0 <= z < self._d):
            self.hovered.emit(None)
            return
        bid = self._cells[z * self._w + x] if self._cells else None
        if bid and bp.is_air(bid):
            bid = None
        self.hovered.emit(bid)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(COLORS["bg_panel"]))
        if self._pix.isNull():
            p.setPen(QColor(COLORS["text_sub"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty)
            return
        target = QRectF(self._origin[0], self._origin[1],
                        self._w * self._scale, self._d * self._scale)
        p.drawPixmap(target, self._pix, QRectF(self._pix.rect()))
        if self._scale >= 6:
            p.setPen(QPen(QColor(0, 0, 0, 30)))
            x1 = int(self._origin[0] + self._w * self._scale)
            z1 = int(self._origin[1] + self._d * self._scale)
            for x in range(1, self._w):
                px = int(self._origin[0] + x * self._scale)
                p.drawLine(px, int(self._origin[1]), px, z1)
            for z in range(1, self._d):
                pz = int(self._origin[1] + z * self._scale)
                p.drawLine(int(self._origin[0]), pz, x1, pz)


class SchematicDialog(QDialog):
    """投影预览 + 材料清单导出的合并窗口。"""

    def __init__(self, sch, parent=None):
        super().__init__(parent)
        self._sch = sch
        self.setWindowTitle(t("preview.title"))
        self.resize(860, 680)
        self.setMinimumSize(640, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self, title=t("preview.title"), height=38)
        root.addWidget(self.titlebar)

        y0, y1 = sch.y_range()
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(20, 12, 20, 8)
        bl.setSpacing(12)
        self.layer_lbl = QLabel()
        self.layer_lbl.setMinimumWidth(96)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(y0, y1)
        self.slider.setValue(y1)
        self.slider.valueChanged.connect(self._show_layer)
        bl.addWidget(self.layer_lbl)
        bl.addWidget(self.slider, stretch=1)
        export_btn = QPushButton(t("tool.materials"))
        export_btn.setMinimumHeight(34)
        export_btn.clicked.connect(self._export_csv)
        bl.addWidget(export_btn)
        root.addWidget(bar)

        self.canvas = _LayerCanvas()
        self.canvas.hovered.connect(self._on_hover)
        root.addWidget(self.canvas, stretch=1)

        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 6, 20, 10)
        self.hover_lbl = QLabel("")
        self.hover_lbl.setStyleSheet(
            f"color:{COLORS['text_sub']}; font-family:Consolas,monospace; font-size:12px;")
        fl.addWidget(self.hover_lbl)
        fl.addStretch(1)
        self.stats = QLabel("")
        self.stats.setStyleSheet(f"color:{COLORS['text_sub']}; font-size:11px;")
        fl.addWidget(self.stats)
        root.addWidget(foot)

        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

        unknown = sch.unknown_blocks()
        self.stats.setText(t("tool.materials_unknown", n=unknown) if unknown else "")
        self._show_layer(y1)

    # ── 层渲染 ────────────────────────────────────────────────────────
    def _show_layer(self, y: int) -> None:
        self.layer_lbl.setText(t("preview.layer", y=y))
        try:
            w, d, cells = self._sch.layer_grid(y)
        except SchematicError as e:
            self.canvas.set_empty(str(e))
            return
        if not any(c and not bp.is_air(c) for c in cells):
            self.canvas.set_empty(t("preview.empty"))
            return
        self.canvas.set_layer(w, d, cells)

    def _on_hover(self, bid) -> None:
        self.hover_lbl.setText(bp.display_name(bid) if bid else "")

    # ── 导出 ─────────────────────────────────────────────────────────
    def _export_csv(self) -> None:
        from .win_rounded import toast, warn
        out = os.path.join(os.path.dirname(self._sch.path),
                           sch_mod.default_csv_name(self._sch))
        try:
            rows = sch_mod.export_materials_csv(self._sch, out)
        except OSError as e:
            warn(self, t("tool.materials_failed"), str(e))
            return
        if not rows:
            toast(self, t("tool.materials_title"), t("tool.materials_empty"))
            return
        msg = t("tool.materials_done", rows=rows, path=out)
        if self._sch.mismatched():
            msg += "\n" + t("tool.materials_meta_warn",
                            meta=self._sch.meta_blocks,
                            real=self._sch.total_blocks())
        toast(self, t("tool.materials_title"), msg, duration=6000)
