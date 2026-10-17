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
import re
import math
import hashlib
from collections import OrderedDict

from PySide6.QtCore import QObject, QUrl, Qt, QPointF
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkRequest, QNetworkReply,
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QLinearGradient, QBrush, QFont, QFontMetrics,
    QPainterPath, QPen, QPolygonF,
)

from shiboken6 import isValid

from .paths import get_data_dir, get_resource_path


# ----------------------------------------------------------------------- loader
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
        # In-memory cache: (url, size) -> rounded QPixmap. Makes revisiting a
        # page or rebuilding a list with the same icons effectively instant.
        # round-40 P2-7：LRU 上限 256——OrderedDict 访问即置顶，超限丢最老。
        self._mem: "OrderedDict[tuple[str, int], QPixmap]" = OrderedDict()
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
        if not url:
            if fallback is not None and isValid(target):
                target.setPixmap(self._round(fallback, size))
            return

        cache_key = (url, size)
        # 1) Memory cache: instant, no disk I/O / no rounding.
        if cache_key in self._mem:
            pm = self._mem_get(cache_key)
            if not pm.isNull() and isValid(target):
                target.setPixmap(pm)
                return

        # Show fallback immediately while we read disk or fetch network.
        if fallback is not None and isValid(target):
            target.setPixmap(self._round(fallback, size))

        key = hashlib.md5(url.encode("utf-8")).hexdigest()
        # 缓存文件按尺寸保存已经 round 好的 48×48 PNG，下次加载直接 setPixmap，
        # 不需要再缩放/裁圆角，比存原图快得多。
        path = os.path.join(self._cache_dir, f"{key}_{size}.png")
        if os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
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
        self._pending[rid] = (target, size)
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
        cache_key = (url, size)
        if cache_key in self._mem:
            self._mem_get(cache_key)  # touch for LRU freshness
            return
        key = hashlib.md5(url.encode("utf-8")).hexdigest()
        path = os.path.join(self._cache_dir, f"{key}_{size}.png")
        if os.path.exists(path):
            return  # already on disk — the later load() reads it straight in
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.UserAgentHeader, "MC-Launcher/0.1")
        self._rid += 1
        rid = self._rid
        self._pending[rid] = (None, size)
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
            target, size = self._pending.pop(rid, (None, None))
            if reply.error() == QNetworkReply.NoError:
                data = reply.readAll()
                pm = QPixmap()
                if pm.loadFromData(data):
                    rounded = self._round(pm, size)
                    try:
                        rounded.save(path, "PNG")
                    except OSError:
                        pass
                    if url:
                        self._mem_put((url, size), rounded)
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
    def _round(pm: QPixmap, size: int) -> QPixmap:
        scaled = pm.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        out = QPixmap(size, size)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, size, size, size * 0.18, size * 0.18)
        p.setClipPath(path)
        p.drawPixmap(0, 0, scaled)
        p.end()
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
#   release → 草方块；snapshot → 紫珀块；april → 樱花木；old_beta → 铁砧；
#   old_alpha / 未知 → 圆石。
_ISO_BLOCK: dict[str, tuple[str, str, str]] = {
    "release": ("#7EC850", "#5B3A1E", "#8B5A2B"),   # grass block
    "snapshot": ("#C084FC", "#6D28D9", "#A78BFA"),  # purpur
    "april": ("#F9A8D4", "#9D174D", "#DB2777"),     # cherry planks
    "old_beta": ("#CBD5E1", "#4B5563", "#94A3B8"),  # anvil/iron
    "old_alpha": ("#9CA3AF", "#374151", "#6B7280"), # cobblestone
}

# major.minor -> theme. c1/c2 gradient, en/zh update name, motif (bottom band),
# deco (list of eco chips painted around the rim).
VERSION_THEMES: dict[str, dict] = {
    "1.21": {"c1": "#F59E0B", "c2": "#B45309", "motif": "trials",
             "en": "Tricky Trials", "zh": "巧密试炼",
             "deco": ["crate", "copper", "breeze"]},
    "1.20": {"c1": "#FBCFE8", "c2": "#DB2777", "motif": "cherry",
             "en": "Trails & Tales", "zh": "足迹与故事",
             "deco": ["petal", "branch", "sniffer"]},
    "1.19": {"c1": "#34D399", "c2": "#065F46", "motif": "wild",
             "en": "Wild Update", "zh": "荒野更新",
             "deco": ["frog", "mangrove", "warden"]},
    "1.18": {"c1": "#A78BFA", "c2": "#5B21B6", "motif": "caves",
             "en": "Caves & Cliffs", "zh": "洞穴与山崖",
             "deco": ["amethyst", "spike", "copper"]},
    "1.17": {"c1": "#C4B5FD", "c2": "#6D28D9", "motif": "caves",
             "en": "Caves & Cliffs", "zh": "洞穴与山崖",
             "deco": ["amethyst", "spike", "copper"]},
    "1.16": {"c1": "#FB7185", "c2": "#9F1239", "motif": "nether",
             "en": "Nether Update", "zh": "下界更新",
             "deco": ["piglin", "lava", "netherite"]},
    "1.15": {"c1": "#FDE047", "c2": "#CA8A04", "motif": "bees",
             "en": "Buzzy Bees", "zh": "嗡嗡蜂群",
             "deco": ["bee", "honey", "flower"]},
    "1.14": {"c1": "#86EFAC", "c2": "#15803D", "motif": "village",
             "en": "Village & Pillage", "zh": "村庄与掠夺",
             "deco": ["village", "pillage", "iron"]},
    "1.13": {"c1": "#38BDF8", "c2": "#0369A1", "motif": "aquatic",
             "en": "Update Aquatic", "zh": "海洋更新",
             "deco": ["fish", "kelp", "bubble"]},
    "1.12": {"c1": "#F472B6", "c2": "#7C3AED", "motif": "color",
             "en": "World of Color", "zh": "多彩世界更新",
             "deco": ["color", "glazed", "parrot"]},
    "1.11": {"c1": "#D6B98C", "c2": "#92400E", "motif": "exploration",
             "en": "Exploration Update", "zh": "探索更新",
             "deco": ["shulker", "llama", "map"]},
    "1.10": {"c1": "#BAE6FD", "c2": "#0EA5E9", "motif": "frost",
             "en": "Frostburn Update", "zh": "霜燃更新",
             "deco": ["polar", "stray", "ice"]},
    "1.9":  {"c1": "#F87171", "c2": "#B91C1C", "motif": "combat",
             "en": "Combat Update", "zh": "战斗更新",
             "deco": ["sword", "shield", "elytra"]},
    "1.8":  {"c1": "#4ADE80", "c2": "#15803D", "motif": "bountiful",
             "en": "Bountiful Update", "zh": "丰饶更新",
             "deco": ["wheat", "rabbit", "banner"]},
    "1.7":  {"c1": "#34D399", "c2": "#0F766E", "motif": "color",
             "en": "The Update that Changed the World",
             "zh": "改变世界的更新",
             "deco": ["color", "rabbit", "acacia"]},
    "1.6":  {"c1": "#FCD34D", "c2": "#B45309", "motif": "bountiful",
             "en": "Horse Update", "zh": "马匹更新",
             "deco": ["horse", "armor", "hay"]},
    "1.5":  {"c1": "#F87171", "c2": "#DC2626", "motif": "redstone",
             "en": "Redstone Update", "zh": "红石更新",
             "deco": ["redstone", "repeater", "hopper"]},
    "1.4":  {"c1": "#A78BFA", "c2": "#6D28D9", "motif": "nether",
             "en": "Halloween Update", "zh": "万圣节更新",
             "deco": ["pumpkin", "bat", "nether"]},
}


def version_theme(version_id: str) -> dict | None:
    """Return the curated update theme for a version id, or None (e.g. a
    snapshot like ``25w14craftmine`` has no themed release)."""
    m = re.match(r"^(\d+)\.(\d+)", version_id or "")
    if not m:
        return None
    return VERSION_THEMES.get(f"{m.group(1)}.{m.group(2)}")


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


def make_version_pixmap(version_id: str, vtype: str, size: int = 56) -> QPixmap:
    """Draw a flat per-version tile in the style of HMCL / PCL2: solid theme
    color rounded square + centered version id.

    round-92 扁平化：去掉渐变卡片 / 3D 等距方块 / 装饰 chips / 更新名，只剩
    「主题色方块 + 版本号」，观感与主流启动器对齐。release 用其更新主题色
    (c1)，snapshot 等无主题的版本回退到 vtype 语义色。
    """
    th = version_theme(version_id)
    if th is not None:
        c1, c2 = th["c1"], th["c2"]
    else:
        c1, c2 = _TYPE_THEME.get(vtype, ("#94A3B8", "#64748B"))

    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    # 1) 扁平纯色圆角方块 + 细描边（与浅色列表背景拉开层次）
    path = QPainterPath()
    radius = size * 0.16
    path.addRoundedRect(0, 0, size, size, radius, radius)
    fill = QColor(c1)
    p.fillPath(path, fill)
    p.setPen(QPen(QColor(c2), 1.0))
    p.drawPath(path)

    # 2) 版本号居中。文字色按底色亮度自适应：亮底用深色，保证可读。
    label = version_id
    base_fs = size * 0.26 if len(label) <= 9 else size * 0.20
    min_fs = max(6.0, size * 0.15)
    f = QFont("Microsoft YaHei", int(base_fs), QFont.Bold)
    f.setWeight(QFont.Bold)
    lum = 0.299 * fill.red() + 0.587 * fill.green() + 0.114 * fill.blue()
    text_color = QColor("#1F2937") if lum > 150 else QColor("#FFFFFF")
    shade = QColor(0, 0, 0, 60)
    text_rect = pm.rect().adjusted(int(size * 0.06), int(size * 0.08),
                                   int(-size * 0.06), int(-size * 0.08))
    fm = QFontMetrics(f)
    for _ in range(10):
        if fm.horizontalAdvance(label) <= text_rect.width():
            break
        new_fs = max(min_fs, f.pointSizeF() * 0.88)
        if abs(new_fs - f.pointSizeF()) < 0.1:
            break
        f.setPointSizeF(new_fs)
        fm = QFontMetrics(f)
    if fm.horizontalAdvance(label) > text_rect.width():
        label = fm.elidedText(label, Qt.ElideRight, text_rect.width())
    p.setFont(f)
    p.setPen(shade)
    p.drawText(text_rect.adjusted(0, 1, 0, 1), Qt.AlignCenter, label)
    p.setPen(text_color)
    p.drawText(text_rect, Qt.AlignCenter, label)
    p.end()
    return pm
