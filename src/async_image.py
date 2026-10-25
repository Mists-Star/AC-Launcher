"""Async image loading + generated version thumbnails.

- ``ImageLoader`` downloads remote icons (Modrinth mod icons) with
  ``QNetworkAccessManager`` so the UI never blocks, caches them on disk under
  ``data/cache/icons`` and renders rounded pixmaps into a target QLabel.
- ``make_version_pixmap`` draws a colorful per-version tile locally (no network),
  giving the versions library a real "cover art" look.

Both are Qt-aware; keep them out of the Qt-free ``core`` layer.
"""
from __future__ import annotations

import os
import math
import hashlib
from collections import OrderedDict

from PySide6.QtCore import QObject, QUrl, Qt, QPointF, QRectF
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkRequest, QNetworkReply,
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QPainterPath, QPolygonF, QTransform,
)

from shiboken6 import isValid

from .paths import get_data_dir, get_resource_path


# ----------------------------------------------------------------------- loader
def _dpr_tag(dpr: float) -> int:
    """Stable integer key for a device pixel ratio (125% → 125)."""
    return int(round(max(1.0, float(dpr or 1.0)) * 100))


class ImageLoader(QObject):
    """Download + cache remote images, render them rounded into a QLabel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mgr = QNetworkAccessManager(self)
        self._mgr.finished.connect(self._on_finished)
        self._cache_dir = os.path.join(get_data_dir(), "cache", "icons")
        os.makedirs(self._cache_dir, exist_ok=True)
        # Bumped on every UI teardown (e.g. store category switch / new search)
        # so in-flight replies know their target widget may already be dead.
        self._token = 0
        # In-memory cache: (url, size, dpr) -> rounded QPixmap. Makes revisiting a
        # page or rebuilding a list with the same icons effectively instant.
        # round-40 P2-7：LRU 上限 256——OrderedDict 访问即置顶，超限丢最老。
        self._mem: "OrderedDict[tuple[str, int, int], QPixmap]" = OrderedDict()
        self._mem_max = 256
        # Pending request registry: request-id -> (target QLabel, size).
        # CRITICAL: never store the target widget pointer as a QNetworkReply
        # dynamic property — PySide6 round-trips it through QVariant as a raw
        # void*, and reading it back in _on_finished can dereference a dangling
        # pointer → hard segfault (access violation), no crash.log. Keep the
        # Python wrapper in a plain dict instead; isValid() then safely detects
        # widgets deleted between request and reply.
        self._rid = 0
        self._pending: dict[int, tuple] = {}

    def _mem_get(self, key):
        """LRU get：命中即置顶。"""
        pm = self._mem.get(key)
        if pm is not None:
            self._mem.move_to_end(key)
        return pm

    def _mem_put(self, key, pm) -> None:
        self._mem[key] = pm
        self._mem.move_to_end(key)
        while len(self._mem) > self._mem_max:
            self._mem.popitem(last=False)  # 丢最老

    def bump(self) -> None:
        """Invalidate all in-flight image loads. Call before tearing down any
        widgets that currently hold pending image targets."""
        self._token += 1

    def load(self, url: str, size: int, target, fallback: QPixmap | None = None) -> None:
        """Fetch ``url`` and drop a rounded ``size×size`` pixmap into ``target``
        (a QLabel). On empty url or failure, show ``fallback`` if provided.

        Lookup order: memory cache → disk cache (pre-rounded) → network.
        """
        dpr = self._dpr_for(target)
        tag = _dpr_tag(dpr)
        if not url:
            if fallback is not None and isValid(target):
                target.setPixmap(self._round(fallback, size, dpr))
            return

        cache_key = (url, size, tag)
        # 1) Memory cache: instant, no disk I/O / no rounding.
        if cache_key in self._mem:
            pm = self._mem_get(cache_key)
            if not pm.isNull() and isValid(target):
                target.setPixmap(pm)
                return

        # Show fallback immediately while we read disk or fetch network.
        if fallback is not None and isValid(target):
            target.setPixmap(self._round(fallback, size, dpr))

        key = hashlib.md5(url.encode("utf-8")).hexdigest()
        # 缓存文件按「逻辑尺寸 @ DPR」保存已经 round 好的 PNG，下次加载直接
        # setPixmap，不需要再缩放/裁圆角，比存原图快得多。
        path = os.path.join(self._cache_dir, f"{key}_{size}@{tag}.png")
        if os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                pm.setDevicePixelRatio(dpr)
                self._mem_put(cache_key, pm)
                if isValid(target):
                    target.setPixmap(pm)
                return

        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.UserAgentHeader, "MC-Launcher/0.1")
        # Register the target in the Python-side dict; only plain int/str go
        # into QVariant properties (safe to read back). See __init__ note.
        self._rid += 1
        rid = self._rid
        self._pending[rid] = (target, size, dpr)
        reply = self._mgr.get(req)
        reply.setProperty("rid", rid)
        reply.setProperty("url", url)
        reply.setProperty("path", path)
        reply.setProperty("token", self._token)

    def prefetch(self, url: str, size: int) -> None:
        """Warm disk + memory caches for ``url`` without a target widget.

        Used by the store list: the moment results arrive, every card's cover
        is also fetched for the detail-dialog size — opening a detail view then
        hits memory/disk instead of starting a fresh network fetch (the old
        behaviour was "cache only after the user clicks in"). Replies reuse
        ``_on_finished``: the rounded PNG is saved to disk and put into the
        memory LRU; pixmap delivery is skipped because the target is None.
        Failures stay silent — the regular ``load()`` path retries on demand.
        """
        if not url:
            return
        dpr = self._screen_dpr()
        tag = _dpr_tag(dpr)
        cache_key = (url, size, tag)
        if cache_key in self._mem:
            self._mem_get(cache_key)  # touch for LRU freshness
            return
        key = hashlib.md5(url.encode("utf-8")).hexdigest()
        path = os.path.join(self._cache_dir, f"{key}_{size}@{tag}.png")
        if os.path.exists(path):
            return  # already on disk — the later load() reads it straight in
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.UserAgentHeader, "MC-Launcher/0.1")
        self._rid += 1
        rid = self._rid
        self._pending[rid] = (None, size, dpr)
        reply = self._mgr.get(req)
        reply.setProperty("rid", rid)
        reply.setProperty("url", url)
        reply.setProperty("path", path)
        reply.setProperty("token", self._token)

    def _on_finished(self, reply: QNetworkReply) -> None:
        # Cache the result regardless of whether the original target widget is
        # still alive; stale replies still warm the disk+memory cache. Only set
        # the pixmap when the token matches and the widget is valid.
        try:
            rid = reply.property("rid")
            url = reply.property("url")
            path = reply.property("path")
            token = reply.property("token")
            # Look up the target wrapper in the Python dict (never via a
            # QVariant property — that path segfaults on dangling pointers).
            target, size, dpr = self._pending.pop(rid, (None, None, 1.0))
            if reply.error() == QNetworkReply.NoError:
                data = reply.readAll()
                pm = QPixmap()
                if pm.loadFromData(data):
                    rounded = self._round(pm, size, dpr)
                    try:
                        rounded.save(path, "PNG")
                    except OSError:
                        pass
                    if url:
                        self._mem_put((url, size, _dpr_tag(dpr)), rounded)
                    if token == self._token and target is not None and isValid(target):
                        try:
                            target.setPixmap(rounded)
                        except RuntimeError:
                            # Widget was deleted between the isValid check and here.
                            pass
            reply.deleteLater()
        except Exception:
            # Swallow and log: this Qt slot must never take the whole app down.
            try:
                import traceback as _tb
                from .paths import get_data_dir
                _p = os.path.join(get_data_dir(), "crash.log")
                with open(_p, "a", encoding="utf-8") as f:
                    f.write("\n--- ImageLoader._on_finished exception ---\n")
                    _tb.print_exc(file=f)
            except Exception:
                pass
            try:
                reply.deleteLater()
            except Exception:
                pass

    @staticmethod
    def _screen_dpr() -> float:
        try:
            from PySide6.QtGui import QGuiApplication
            scr = QGuiApplication.primaryScreen()
            return max(1.0, float(scr.devicePixelRatio()) if scr else 1.0)
        except Exception:  # noqa: BLE001
            return 1.0

    @classmethod
    def _dpr_for(cls, target) -> float:
        """Device pixel ratio of the widget that will show the pixmap.

        A QPixmap carrying DPR 1.0 gets upscaled by Qt on a 1.25×/1.5× display,
        which is exactly what made card covers look low-res (round-126).
        """
        try:
            if target is not None and isValid(target):
                return max(1.0, float(target.devicePixelRatioF() or 1.0))
        except Exception:  # noqa: BLE001 - widget may be gone
            pass
        return cls._screen_dpr()

    @staticmethod
    def _round(pm: QPixmap, size: int, dpr: float = 1.0) -> QPixmap:
        # Render at physical pixels and tag the DPR so a fractional-scaling
        # display draws it 1:1 instead of blurring a Qt upscale.
        px = max(4, int(round(size * max(1.0, dpr))))
        scaled = pm.scaled(px, px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        out = QPixmap(px, px)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        r = px * 0.18
        path.addRoundedRect(0, 0, px, px, r, r)
        p.setClipPath(path)
        p.drawPixmap(0, 0, scaled)
        p.end()
        out.setDevicePixelRatio(max(1.0, dpr))
        return out


# --------------------------------------------------------- version thumbnails
# Per-update "cover art" for the version library. Each major.minor gets a
# signature gradient + an official update name + a vector *motif* (bottom band)
# + a few *eco deco* chips around the rim (the creatures / blocks / items that
# update introduced — e.g. Nether Update paints piglin / lava / netherite).
# This is the differentiator: no other launcher themes per-version covers.

_TYPE_THEME: dict[str, tuple[str, str]] = {
    "release": ("#4ADE80", "#16A34A"),   # grass green
    "snapshot": ("#A78BFA", "#7C3AED"),  # experimental purple
    "april": ("#F472B6", "#DB2777"),       # joke-version pink
    "old_beta": ("#FBBF24", "#D97706"),   # amber
    "old_alpha": ("#94A3B8", "#64748B"),  # slate
}

# round-53：版本图标改为 MC 风格 3D 等距方块（对齐官方启动器/主流启动器的方块
# 图标）。每种版本类型配一组「顶面/左面/右面」的经典 MC 贴图配色：
#   release → 草方块；snapshot → 紫珀块；april → 工作台；old_beta → 砖块；
#   old_alpha / 未知 → 圆石。这些只是贴图缺失时的纯色回退。
_ISO_BLOCK: dict[str, tuple[str, str, str]] = {
    "release": ("#7EC850", "#5B3A1E", "#8B5A2B"),   # grass block
    "snapshot": ("#C084FC", "#6D28D9", "#A78BFA"),  # purpur
    "april": ("#C9A06B", "#6B4423", "#8B5E34"),     # crafting table
    "old_beta": ("#B45309", "#7C2D12", "#92400E"),  # brick block
    "old_alpha": ("#9CA3AF", "#374151", "#6B7280"), # cobblestone
}


# ---------------------------------------------------- real MC texture overlay
# Optional layer: each eco-deco key can be backed by a real Minecraft texture
# (extracted from the user's owned 26.2 client, shipped under assets/mc_textures,
# bundled via the PyInstaller "assets" datas rule). When a texture resolves we
# draw it on the card; otherwise the vector motif/deco below stays as the
# fallback, so a missing/renamed texture never breaks a card. Loading is
# memoised per texture path.
_TEXTURE_ROOT = "assets/mc_textures"
_DECO_TO_TEXTURE: dict[str, str | None] = {
    "acacia": "block/acacia_log", "armor": "item/iron_chestplate",
    "banner": "entity/banner/banner_base", "bat": "entity/bat/bat",
    "bee": "entity/bee/bee", "breeze": "entity/breeze/breeze",
    "bubble": "particle/bubble", "color": None,  # multicolour concept → keep vector
    "copper": "item/copper_ingot", "crate": "item/trial_key",
    "elytra": "item/elytra", "fish": "item/cod", "flower": "block/dandelion",
    "frog": "entity/frog/frog_temperate", "glazed": "block/white_glazed_terracotta",
    "hay": "block/hay_block_side", "honey": "item/honey_bottle", "ice": "block/ice",
    "iron": "item/iron_ingot", "kelp": "block/kelp", "lava": "block/lava_still",
    "llama": "entity/llama/llama_brown", "mangrove": "block/mangrove_log",
    "map": "item/map", "nether": "block/netherrack",
    "netherite": "item/netherite_ingot", "parrot": "entity/parrot/parrot_blue",
    "petal": "block/cherry_leaves", "pillage": "entity/illager/pillager",
    "piglin": "entity/piglin/piglin", "polar": "entity/bear/polarbear",
    "pumpkin": "block/carved_pumpkin", "rabbit": "entity/rabbit/rabbit_brown",
    "redstone": "item/redstone", "repeater": "item/repeater", "hopper": "item/hopper",
    "shulker": "entity/shulker/shulker", "shield": "entity/shield/base",
    "sniffer": "entity/sniffer/sniffer", "spike": "block/amethyst_cluster",
    "stray": "entity/skeleton/stray", "sword": "item/iron_sword",
    "village": "item/emerald", "warden": "entity/warden/warden",
    "wheat": "item/wheat", "branch": "block/cherry_sapling",
}
_tex_cache: dict[str, QPixmap] = {}
_tex_miss: set[str] = set()


# round-107 版本图标回归「MC 3D 等距方块」：正式版草方块 / 快照命令方块 /
# 愚人节工作台 / 旧版砖块·圆石，对齐主流启动器。此前 round-92 压成「纯色方块 +
# 版本号文字」，长版本号被省略号截断且毫无辨识度。这里改用随包的真实 MC 贴图
# （assets/mc_textures/block）渲染 3D 方块，缺贴图时回退纯色向量块。
_BLOCK_FACES: dict[str, tuple[str, str, str | None]] = {
    # vtype -> (top texture, side texture, right face texture or None)
    "release":   ("grass_block_top", "grass_block_side", None),
    "snapshot":  ("command_block_side", "command_block_side", "command_block_front"),
    # April Fools versions are joke updates; a cake reads as "birthday" noise and
    # its side texture is mostly white, so swap it for the crafting table —
    # the theme of the most recent April Fools update ("Craftmine").
    "april":     ("crafting_table_top", "crafting_table_side", "crafting_table_front"),
    # Anvil textures are largely transparent (the sprite only covers the anvil
    # shape), which punched holes in the cube — use an opaque old-school block.
    "old_beta":  ("bricks", "bricks", None),
    "old_alpha": ("cobblestone", "cobblestone", None),
}
_BLOCK_FALLBACK = ("bedrock", "bedrock", None)


def _load_block_tex(name: str) -> "QPixmap | None":
    """Load a block texture from the bundled assets; crop the first frame for
    animated strips (e.g. command_block is 16×64 = 4 frames)."""
    if not name:
        return None
    if name in _tex_cache:
        return _tex_cache[name]
    if name in _tex_miss:
        return None
    path = get_resource_path(os.path.join(_TEXTURE_ROOT, "block", f"{name}.png"))
    pm = QPixmap(path) if (path and os.path.exists(path)) else QPixmap()
    if pm.isNull():
        _tex_miss.add(name)
        return None
    if pm.height() > pm.width():
        frames = max(1, pm.height() // pm.width())
        pm = pm.copy(0, 0, pm.width(), pm.height() // frames)
    _tex_cache[name] = pm
    return pm


# Some vanilla textures are grayscale masks that Minecraft tints at runtime.
# Drawing them raw makes the grass block read as a stone block with a green
# stripe, so tint the top face with the plains grass colour before mapping it.
_FACE_TINTS = {
    "grass_block_top": "#91BD59",
}
_tint_cache: dict[tuple[str, str], "QPixmap"] = {}


def _tinted_block_tex(name: str, tint: str) -> "QPixmap | None":
    pm = _load_block_tex(name)
    if pm is None or not tint:
        return pm
    key = (name, tint)
    if key in _tint_cache:
        return _tint_cache[key]
    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    try:
        p.drawPixmap(0, 0, pm)
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        p.fillRect(out.rect(), QColor(tint))
    finally:
        p.end()
    _tint_cache[key] = out
    return out


def _paint_face(p: QPainter, quad: list, tf: QTransform,
                pm: "QPixmap | None", col: QColor, shade: int) -> None:
    """Paint one isometric face: textured (mapped via ``tf``) or flat fill,
    then a translucent black overlay for 3D shading."""
    path = QPainterPath()
    path.addPolygon(QPolygonF(quad))
    p.save()
    p.setClipPath(path)
    if pm is not None and not pm.isNull():
        old = p.transform()
        p.setTransform(tf, True)
        p.drawPixmap(QRectF(0.0, 0.0, 1.0, 1.0), pm, QRectF(pm.rect()))
        p.setTransform(old)
    else:
        p.fillPath(path, col)
    if shade:
        p.fillPath(path, QColor(0, 0, 0, shade))
    p.restore()


def _draw_iso_block(p: QPainter, s: float, top_pm, side_pm, right_pm,
                    top_col: QColor, side_col: QColor, right_col: QColor) -> None:
    """Draw an isometric cube of width ``s`` (top vertex at the origin).

    ``hh`` is the half-height of the top diamond (2:1, the MC pixel-art
    standard). The vertical side edges must be as long as the slanted top
    edges — ``hypot(cx, hh)`` ≈ 0.559·s — otherwise the same 16×16 texture is
    stretched horizontally on the sides and the whole cube reads as squashed.
    Total silhouette height = 2·hh + vh ≈ 1.059·s.
    """
    cx = s / 2.0
    hh = s * 0.25
    vh = math.hypot(cx, hh)
    A = QPointF(cx, 0.0)
    C = QPointF(cx, hh * 2.0)
    D = QPointF(0.0, hh)

    def quad(o: QPointF, e1: QPointF, e2: QPointF) -> list:
        return [o, o + e1, o + e1 + e2, o + e2]

    # Top face (brightest), left face, right face (darkest)
    _paint_face(p, quad(A, QPointF(cx, hh), QPointF(-cx, hh)),
                QTransform(cx, hh, -cx, hh, cx, 0.0), top_pm, top_col, 0)
    _paint_face(p, quad(D, QPointF(cx, hh), QPointF(0.0, vh)),
                QTransform(cx, hh, 0.0, vh, 0.0, hh), side_pm, side_col, 44)
    _paint_face(p, quad(C, QPointF(cx, -hh), QPointF(0.0, vh)),
                QTransform(cx, -hh, 0.0, vh, cx, hh * 2.0),
                right_pm or side_pm, right_col, 82)


def make_version_pixmap(version_id: str, vtype: str, size: int = 56) -> QPixmap:
    """Draw a 3D isometric MC block icon for a version (HMCL / PCL2 style).

    round-107：正式版草方块、快照命令方块、愚人节工作台、旧版砖块 / 圆石。用
    随包真实 MC 贴图渲染；任何贴图缺失都会回退到纯色向量块，绝不画出坏图标。
    ``version_id`` 保留在签名里以兼容旧调用点（图标由 ``vtype`` 决定）。
    """
    names = _BLOCK_FACES.get(vtype) or _BLOCK_FALLBACK
    top_pm = _tinted_block_tex(names[0], _FACE_TINTS.get(names[0], ""))
    side_pm = _load_block_tex(names[1])
    right_pm = _load_block_tex(names[2]) if names[2] else None
    cols = _ISO_BLOCK.get(vtype) or _ISO_BLOCK["old_alpha"]

    # Render at the physical pixel size and carry the DPR on the pixmap, so a
    # 1.25×/1.5× display gets a crisp icon instead of a Qt-upscaled blur.
    try:
        from PySide6.QtGui import QGuiApplication
        _scr = QGuiApplication.primaryScreen()
        dpr = float(_scr.devicePixelRatio()) if _scr is not None else 1.0
    except Exception:
        dpr = 1.0
    dpr = max(1.0, dpr)
    px = max(8, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # 2px padding so the AA edges of the top vertex aren't clipped. The cube is
    # taller than wide (height = s·(2+√5)/4 ≈ 1.059·s), so derive the width from
    # the available height instead of stuffing it into a square — that was the
    # "grass block looks squashed" bug.
    box = float(px - 4 * dpr)
    s = box * 4.0 / (2.0 + math.sqrt(5.0))
    p.translate((px - s) / 2.0, 2.0 * dpr)
    _draw_iso_block(p, s, top_pm, side_pm, right_pm,
                    QColor(cols[0]), QColor(cols[1]), QColor(cols[2]))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm

