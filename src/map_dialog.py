"""存档地图对话框（round-171，P2）：region 顶视图 + 缩放 / 平移 + 玩家与出生点标记。

数据源：`core.world_map`（`.mca` → RGBA）。真实坐标：1 像素 = 1 方块。
只读——绝不写存档；缓存写在 `<data>/map_cache/`（按 mca 的 mtime + size 失效）。

加载策略：一次最多铺 ``MAX_TILES`` 个 region（默认取玩家 / 出生点附近，
按切比雪夫距离排序），避免大存档一次性把内存吃满。加载在后台线程完成，
UI 只负责合成 QPixmap 与绘制。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from .core import world_map as wm
from .frameless import FramelessHelper, TitleBar
from .i18n import t
from .theme import COLORS
from .worker import Worker

MAX_TILES = 16                 # 一次最多铺的 region 数（4×4）
MAX_TILES_SIDE = 4             # 连续窗口边长：4×4 = 16 个 region
_MAX_CANVAS_BYTES = 256 * 1024 * 1024   # 画布硬上限（4×4 正常只有 16 MB）
ZOOMS = (1, 2, 4, 8)
REGION_PX = wm.REGION_BLOCKS   # 512

_DIM_LABEL = {
    "overworld": "map.dim_overworld",
    "nether": "map.dim_nether",
    "end": "map.dim_end",
}


def build_tiles(world_dir: str, dim: str, center) -> dict | None:
    """后台线程：把若干 region 拼成一张大图（透明处 = 无区块）。

    ``center`` 是世界坐标 ``(x, y, z)``；用来挑「离玩家最近」的 region。
    """
    grid = wm.region_grid(world_dir, dim)
    if not grid:
        return None
    if center:
        rx0 = int(center[0] // REGION_PX)
        rz0 = int(center[2] // REGION_PX)
    else:
        rx0 = rz0 = 0
    # round-214 P1：只铺「以锚点为中心的连续 4×4 窗口」，不能按距离取散点。
    # 旧实现取 16 个**最近**的 region 再按极值算包围盒 —— 存档里只要有两张
    # 相距 8000 方块的 region（玩家坐鞘翅/传送就会留下），包围盒就是
    # 26112×26112 ≈ 2.7 GB 的 QImage：分配失败 → 一块无提示的全白画布，
    # 分配成功 → 直接顶满内存。
    half = MAX_TILES_SIDE // 2
    window = {(x, z)
              for x in range(rx0 - half, rx0 + MAX_TILES_SIDE - half)
              for z in range(rz0 - half, rz0 + MAX_TILES_SIDE - half)}
    chosen = [tuple(g) for g in grid if tuple(g) in window]
    if not chosen:
        # 锚点周围没有 region（玩家站在未生成区域）→ 只画最近的一个，
        # 绝不为了「凑 16 张」把包围盒拉到几百个 region 宽。
        chosen = [min(grid, key=lambda g: max(abs(g[0] - rx0),
                                              abs(g[1] - rz0)))]
    minx = min(c[0] for c in chosen)
    maxx = max(c[0] for c in chosen)
    minz = min(c[1] for c in chosen)
    maxz = max(c[1] for c in chosen)
    w = (maxx - minx + 1) * REGION_PX
    h = (maxz - minz + 1) * REGION_PX
    if w * h * 4 > _MAX_CANVAS_BYTES:
        # 护栏：即使上面的窗口逻辑被改坏，也不允许分配超过 256 MB 的画布。
        return None
    canvas = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(0)
    painter = QPainter(canvas)
    tiles = 0
    unknown = 0
    try:
        for rx, rz in chosen:
            got = wm.load_region_image(world_dir, dim, rx, rz, with_stats=True)
            if got is None:
                continue
            img, n_unknown, _chunks = got
            if img.isNull():
                continue
            tiles += 1
            unknown += n_unknown
            dx = (rx - minx) * REGION_PX
            dz = (rz - minz) * REGION_PX
            painter.drawImage(QPoint(dx, dz), img)
    finally:
        painter.end()
    if not tiles:
        return None
    return {
        "image": canvas,
        "origin": (minx * REGION_PX, minz * REGION_PX),
        "tiles": tiles,
        "unknown": unknown,
        "center": center,
    }


class _Canvas(QWidget):
    """1 像素 = 1 方块的地图画布（滚轮缩放，左键拖动平移）。"""

    zoomed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._pix = QPixmap()
        self._zoom = 1
        self._off = QPointF(0.0, 0.0)
        self._origin = (0, 0)
        self._marks: list[tuple[float, float, str]] = []
        self._empty = ""
        self._pending = None
        self._drag_from = None
        self._drag_off = QPointF(0.0, 0.0)

    # ── 对外 ──────────────────────────────────────────────────────────
    def set_empty(self, text: str) -> None:
        self._pix = QPixmap()
        self._marks = []
        self._pending = None
        self._empty = text
        self.update()

    def set_map(self, image: QImage, origin, marks, center) -> None:
        self._pix = QPixmap.fromImage(image)
        self._origin = origin
        self._marks = marks
        self._empty = ""
        self._zoom = 1
        # 首次布局完成前 width/height 不可靠 → 留到 resizeEvent 再居中
        self._pending = center or (origin[0] + self._pix.width() / 2, 0,
                                   origin[1] + self._pix.height() / 2)
        if self.width() > 1 and self.height() > 1:
            self._center_on(self._pending)
            self._pending = None
        self.zoomed.emit(self._zoom)
        self.update()

    def zoom(self) -> int:
        return self._zoom

    # ── 坐标 ──────────────────────────────────────────────────────────
    def _map_px(self, block_x: float, block_z: float) -> tuple[float, float]:
        return ((block_x - self._origin[0]) * self._zoom,
                (block_z - self._origin[1]) * self._zoom)

    def _center_on(self, center) -> None:
        cx, cz = self._map_px(center[0], center[2])
        self._off = QPointF(self.width() / 2.0 - cx, self.height() / 2.0 - cz)
        self._clamp()

    def _clamp(self) -> None:
        """把图拽回来：至少留 80px 在可视区内，避免拖丢了找不到。"""
        w = self._pix.width() * self._zoom
        h = self._pix.height() * self._zoom
        margin = 80.0
        self._off.setX(min(self.width() - margin, max(margin - w, self._off.x())))
        self._off.setY(min(self.height() - margin, max(margin - h, self._off.y())))

    def _set_zoom(self, new_zoom: int) -> None:
        if new_zoom == self._zoom:
            return
        # 以视口中心为锚点缩放，画面不会乱跳
        mx = (self.width() / 2.0 - self._off.x()) / self._zoom
        mz = (self.height() / 2.0 - self._off.y()) / self._zoom
        self._zoom = new_zoom
        self._off = QPointF(self.width() / 2.0 - mx * new_zoom,
                            self.height() / 2.0 - mz * new_zoom)
        self._clamp()
        self.zoomed.emit(self._zoom)
        self.update()

    # ── 事件 ──────────────────────────────────────────────────────────
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._pending is not None and not self._pix.isNull():
            self._center_on(self._pending)
            self._pending = None

    def wheelEvent(self, ev):
        if self._pix.isNull():
            return
        step = 1 if ev.angleDelta().y() > 0 else -1
        idx = ZOOMS.index(self._zoom) + step
        idx = max(0, min(len(ZOOMS) - 1, idx))
        self._set_zoom(ZOOMS[idx])

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton or self._pix.isNull():
            return
        self._drag_from = ev.position()
        self._drag_off = QPointF(self._off)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._drag_from is None:
            return
        d = ev.position() - self._drag_from
        self._off = QPointF(self._drag_off.x() + d.x(), self._drag_off.y() + d.y())
        self._clamp()
        self.update()

    def mouseReleaseEvent(self, ev):
        self._drag_from = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # ── 绘制 ──────────────────────────────────────────────────────────
    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(COLORS["bg_panel"]))
        if self._pix.isNull():
            p.setPen(QColor(COLORS["text_sub"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._zoom < 1)
        target = QRectF(self._off.x(), self._off.y(),
                        self._pix.width() * self._zoom,
                        self._pix.height() * self._zoom)
        p.drawPixmap(target, self._pix, QRectF(self._pix.rect()))
        for bx, bz, kind in self._marks:
            px = self._off.x() + (bx - self._origin[0]) * self._zoom
            pz = self._off.y() + (bz - self._origin[1]) * self._zoom
            if kind == "player":
                p.setPen(QPen(QColor("#FFFFFF"), 2))
                p.setBrush(QColor(COLORS["accent"]))
                p.drawEllipse(QPointF(px, pz), 5.0, 5.0)
            else:
                p.setPen(QPen(QColor(COLORS["warn"]), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(px - 4, pz - 4, 8, 8))
        p.end()


class MapDialog(QDialog):
    """存档地图窗口：世界 / 维度切换 + 缩放 + 标记。"""

    def __init__(self, game_dir: str, parent=None):
        super().__init__(parent)
        self._game_dir = game_dir
        self._worker = None
        # round-214：每次 _reload 递增；旧 worker 的结果按代号丢弃。
        self._load_gen = 0
        self._marks: list[tuple[float, float, str]] = []
        self.setWindowTitle(t("map.title"))
        self.resize(920, 700)
        self.setMinimumSize(720, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self, title=t("map.title"), height=38)
        root.addWidget(self.titlebar)

        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(20, 12, 20, 8)
        bl.setSpacing(10)
        self.world_box = QComboBox()
        self.world_box.setMinimumWidth(200)
        self.dim_box = QComboBox()
        self.dim_box.setMinimumWidth(110)
        bl.addWidget(QLabel(t("map.world")))
        bl.addWidget(self.world_box)
        bl.addSpacing(6)
        bl.addWidget(QLabel(t("map.dim")))
        bl.addWidget(self.dim_box)
        bl.addStretch(1)
        self.zoom_lbl = QLabel(t("map.zoom", x=self._zoom_value()))
        self.zoom_lbl.setStyleSheet(f"color:{COLORS['text_sub']};")
        bl.addWidget(self.zoom_lbl)
        hint = QLabel(t("map.hint_drag"))
        hint.setStyleSheet(f"color:{COLORS['text_sub']}; font-size:11px;")
        bl.addWidget(hint)
        root.addWidget(bar)

        self.canvas = _Canvas()
        self.canvas.zoomed.connect(
            lambda z: self.zoom_lbl.setText(t("map.zoom", x=z)))
        root.addWidget(self.canvas, stretch=1)

        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 6, 20, 10)
        self.stats = QLabel("")
        self.stats.setStyleSheet(f"color:{COLORS['text_sub']}; font-size:11px;")
        fl.addWidget(self.stats)
        fl.addStretch(1)
        root.addWidget(foot)

        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

        for dim in wm.DIMENSIONS:
            self.dim_box.addItem(t(_DIM_LABEL[dim]), dim)
        self._fill_worlds()
        self.world_box.currentIndexChanged.connect(self._reload)
        self.dim_box.currentIndexChanged.connect(self._reload)
        self._reload()

    # ── 数据 ──────────────────────────────────────────────────────────
    def _zoom_value(self) -> int:
        canvas = getattr(self, "canvas", None)
        return canvas.zoom() if canvas is not None else 1

    def _fill_worlds(self) -> None:
        worlds = wm.list_worlds(self._game_dir)
        self.world_box.blockSignals(True)
        self.world_box.clear()
        for w in worlds:
            self.world_box.addItem(os.path.basename(w), w)
        self.world_box.blockSignals(False)
        if not worlds:
            self.canvas.set_empty(t("map.no_saves"))

    def _reload(self) -> None:
        world = self.world_box.currentData()
        dim = self.dim_box.currentData() or "overworld"
        self._marks = []
        if not world:
            self.canvas.set_empty(t("map.no_saves"))
            self.stats.setText("")
            return
        info = wm.world_info(world)
        player = info.get("player")
        spawn = info.get("spawn")
        if player:
            self._marks.append((player[0], player[2], "player"))
        if spawn:
            self._marks.append((float(spawn[0]), float(spawn[2]), "spawn"))
        center = player or spawn
        if not wm.region_grid(world, dim):
            self.canvas.set_empty(t("map.no_region"))
            self.stats.setText("")
            return
        self.canvas.set_empty(t("map.loading"))
        self.stats.setText("")
        self._load_gen += 1
        gen = self._load_gen
        worker = Worker(build_tiles, world, dim, center)
        # round-214 P1：切世界/维度后旧 worker 不会被取消（build_tiles 没有
        # 中断点），旧实现把 finished 直连 _on_tiles → 旧图覆盖新画布，
        # 而 _marks 已经是新世界的玩家/出生点，画面与坐标互相矛盾。
        worker.finished.connect(lambda res, g=gen: self._on_tiles(res, g))
        worker.error.connect(lambda err, g=gen: self._on_error(err, g))
        self._worker = worker
        worker.start()

    def _on_tiles(self, result, gen: int = 0) -> None:
        if gen and gen != self._load_gen:
            return  # 旧世界/旧维度的迟到结果，丢弃
        if not result:
            self.canvas.set_empty(t("map.no_region"))
            return
        self.canvas.set_map(result["image"], result["origin"], self._marks,
                            result.get("center"))
        n = result.get("unknown") or 0
        self.stats.setText(t("map.legend_unknown", n=n) if n else "")

    def _on_error(self, err: str, gen: int = 0) -> None:
        if gen and gen != self._load_gen:
            return
        self.canvas.set_empty(t("map.err_open_world", err=err))
