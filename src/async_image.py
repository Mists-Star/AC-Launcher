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
_MEM_MAX = 256          # 默认图片内存缓存条数（round-167 低配模式可降到 64）


def set_mem_limit(n: int) -> None:
    """调整图片内存缓存上限（round-167 低配模式：256 → 64）。"""
    global _MEM_MAX
    try:
        _MEM_MAX = max(8, int(n))
    except (TypeError, ValueError):
        _MEM_MAX = 256


def _dpr_tag(dpr: float) -> int:
    """Stable integer key for a device pixel ratio (125% → 125)."""
    return int(round(max(1.0, float(dpr or 1.0)) * 100))


class ImageLoader(QObject):
    """Download + cache remote images, render them rounded into a QLabel.

    round-180 重构（修「明明有缓存却还是没图」）：

    * **原图只缓存一份**（``<md5(url)>.img``），各显示尺寸在内存里派生 ——
      旧实现按 ``(url, size, dpr)`` 各存一份、各发一次网络请求，一次搜索
      N 个结果就是 2N 个并发（48px 卡片 + 72px 预取），QNAM 同主机默认
      只有 6 条连接，后面全排队超时。
    * **同 URL 请求去重**：在途 URL 的后续 load/prefetch 挂到等待表，
      回来后一次渲染给所有目标，不再重复发请求。
    * **检查 HTTP 状态码**：403/429 返回 HTML 时 Qt 的 ``error()`` 可能是
      NoError，旧实现会静默丢弃且不写缓存 → 那些图永远出不来。
    * **失败负缓存 + 退避**：60s 内不重复打失败 URL，避免每次搜索重试
      一遍无效请求；同时删掉损坏的缓存文件。
    * **限并发**：最多 6 个在途请求，其余排队。
    * **token 过期不再吞图**：``bump()`` 只让旧 widget 失效；同 URL 的新
      卡片挂在等待表里，旧回复成功时照样能拿到图。
    """

    _MAX_INFLIGHT = 6
    _FAIL_TTL = 60.0
    # round-181：单张图标上限。实测 CF 「作者头像 GIF」最大 18.8 MB，
    # 一个就占满 6 个并发槽之一 25 秒，整页图标全排队。48/88px 的展示
    # 根本不需要原图，超过上限直接熔断。
    _MAX_ICON_BYTES = 512 * 1024
    _THUMB_PX = 128

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mgr = QNetworkAccessManager(self)
        self._mgr.finished.connect(self._on_finished)
        self._cache_dir = os.path.join(get_data_dir(), "cache", "icons")
        os.makedirs(self._cache_dir, exist_ok=True)
        self._token = 0
        # (url, size, dpr_tag) -> 已裁圆的 QPixmap
        self._mem: "OrderedDict[tuple[str, int, int], QPixmap]" = OrderedDict()
        self._mem_max = _MEM_MAX
        # url -> 原始图 QPixmap（内存，避免重复读盘）
        self._raw: "OrderedDict[str, QPixmap]" = OrderedDict()
        self._rid = 0
        self._pending: dict[int, tuple] = {}
        self._queue: list = []
        self._inflight = 0
        self._inflight_urls: set = set()
        self._waiting: dict[str, list] = {}
        self._failed: dict[str, tuple] = {}

    # ------------------------------------------------------------ helpers
    def _mem_get(self, key):
        pm = self._mem.get(key)
        if pm is not None:
            self._mem.move_to_end(key)
        return pm

    def _mem_put(self, key, pm) -> None:
        self._mem[key] = pm
        self._mem.move_to_end(key)
        while len(self._mem) > self._mem_max:
            self._mem.popitem(last=False)

    def _raw_put(self, url: str, pm) -> None:
        self._raw[url] = pm
        self._raw.move_to_end(url)
        while len(self._raw) > 128:
            self._raw.popitem(last=False)

    def _orig_path(self, url: str) -> str:
        key = hashlib.md5(url.encode("utf-8")).hexdigest()  # noqa: S324 - 缓存键
        return os.path.join(self._cache_dir, key + ".img")

    def _read_orig(self, url: str):
        """读原始图（内存 → 磁盘）；坏文件直接删掉，返回 None 触发重下。"""
        pm = self._raw.get(url)
        if pm is not None and not pm.isNull():
            self._raw.move_to_end(url)
            return pm
        path = self._orig_path(url)
        if not os.path.isfile(path):
            return None
        try:
            # 旧版本落的是未经压缩的原图（实测单文件 18.8 MB）。读之前先
            # 淘汰：既省磁盘，也避免每次进页面都解码一次巨型 GIF。
            if os.path.getsize(path) > self._MAX_ICON_BYTES:
                os.remove(path)
                return None
            with open(path, "rb") as fh:
                data = fh.read()
            pm = QPixmap()
            if data and pm.loadFromData(data):
                self._raw_put(url, pm)
                return pm
        except OSError:
            pass
        try:
            os.remove(path)
        except OSError:
            pass
        return None

    def _deliver(self, url: str, size: int, dpr: float, target) -> None:
        """把原图渲染成目标尺寸并交给 widget（缓存渲染结果）。"""
        raw = self._read_orig(url)
        if raw is None:
            return
        key = (url, size, _dpr_tag(dpr))
        pm = self._mem_get(key)
        if pm is None:
            pm = self._round(raw, size, dpr)
            self._mem_put(key, pm)
        if target is not None and isValid(target):
            try:
                target.setPixmap(pm)
            except RuntimeError:
                pass

    def _cooled_down(self, url: str) -> bool:
        rec = self._failed.get(url)
        if not rec:
            return True
        import time as _t
        if _t.monotonic() - rec[0] < min(self._FAIL_TTL, 5.0 * (2 ** min(rec[1], 4))):
            return False
        return True

    # -------------------------------------------------------------- public
    def bump(self) -> None:
        """Mark in-flight replies as targeting widgets that may be gone.

        不清 ``_pending``：同 URL 的新卡片已挂进 ``_waiting``，旧回复
        成功时仍会把图交给它们（这正是旧实现「有缓存却没图」的原因之一）。
        """
        self._token += 1

    def load(self, url: str, size: int, target, fallback: QPixmap | None = None) -> None:
        dpr = self._dpr_for(target)
        if not url:
            if fallback is not None and isValid(target):
                target.setPixmap(self._round(fallback, size, dpr))
            return
        key = (url, size, _dpr_tag(dpr))
        hit = self._mem_get(key)
        if hit is not None and not hit.isNull() and isValid(target):
            target.setPixmap(hit)
            return
        if fallback is not None and isValid(target):
            target.setPixmap(self._round(fallback, size, dpr))
        if self._read_orig(url) is not None:
            self._deliver(url, size, dpr, target)
            return
        self._enqueue(url, size, dpr, target)

    def prefetch(self, url: str, size: int) -> None:
        """只把原图拉下来；不负责渲染，也不额外发一次「按尺寸」的请求。"""
        if not url or self._read_orig(url) is not None:
            return
        self._enqueue(url, size, self._screen_dpr(), None)

    def _enqueue(self, url, size, dpr, target) -> None:
        item = (url, size, dpr, target, self._token)
        # 同 URL 已在途 → 挂等待表，回来后统一派发，不重复请求
        if url in self._inflight_urls:
            self._waiting.setdefault(url, []).append(item)
            return
        if not self._cooled_down(url):
            return  # 负缓存：失败 URL 退避期内不再打网络
        self._queue.append(item)
        self._pump()

    def _pump(self) -> None:
        import time as _t
        while self._queue and self._inflight < self._MAX_INFLIGHT:
            url, size, dpr, target, token = self._queue.pop(0)
            if url in self._inflight_urls or not self._cooled_down(url):
                continue
            if self._read_orig(url) is not None:
                self._deliver(url, size, dpr, target)
                continue
            req = QNetworkRequest(QUrl(url))
            req.setHeader(QNetworkRequest.UserAgentHeader, "MC-Launcher/0.1")
            self._rid += 1
            rid = self._rid
            self._pending[rid] = (url, size, dpr, target, token)
            self._inflight_urls.add(url)
            self._inflight += 1
            reply = self._mgr.get(req)
            reply.setProperty("rid", rid)
            reply.setProperty("seen", 0)
            reply.readyRead.connect(self._on_ready_read)

    # ------------------------------------------------------------ replies
    def _on_ready_read(self) -> None:
        """round-181：边下边数，超过上限立刻中止，不让大图占满并发槽。"""
        reply = self.sender()
        if reply is None:
            return
        try:
            seen = int(reply.property("seen") or 0) + reply.bytesAvailable()
            reply.setProperty("seen", seen)
            if seen > self._MAX_ICON_BYTES:
                reply.abort()
        except RuntimeError:
            pass

    def _on_finished(self, reply: QNetworkReply) -> None:
        import time as _t
        try:
            rid = reply.property("rid")
            url, size, dpr, target, token = self._pending.pop(
                rid, (None, 0, 1.0, None, -1))
            if url is None:
                reply.deleteLater()
                return
            self._inflight = max(0, self._inflight - 1)
            self._inflight_urls.discard(url)

            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            ok = (reply.error() == QNetworkReply.NoError
                  and (status is None or 200 <= int(status) < 300))
            data = reply.readAll() if ok else None
            pm = QPixmap()
            if data and pm.loadFromData(bytes(data)):
                # round-181：只落 <=128px 的缩略图，不存原图。列表 48px /
                # 详情 88px 都够用，体积从 MB 级降到 KB 级，二次读盘瞬间完成。
                thumb = pm
                if max(pm.width(), pm.height()) > self._THUMB_PX:
                    thumb = pm.scaled(self._THUMB_PX, self._THUMB_PX,
                                      Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation)
                path = self._orig_path(url)
                tmp = path + ".tmp"
                try:
                    if not thumb.save(tmp, "PNG"):
                        raise OSError("pixmap.save returned False")
                    os.replace(tmp, path)
                except OSError:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                self._raw_put(url, thumb)
                self._failed.pop(url, None)
                self._deliver(url, size, dpr, target)
                for _u, _s, _d, _tgt, _tok in self._waiting.pop(url, []):
                    self._deliver(_u, _s, _d, _tgt)
            else:
                cnt = self._failed.get(url, (0, 0))[1] + 1
                self._failed[url] = (_t.monotonic(), cnt)
                try:
                    os.remove(self._orig_path(url))
                except OSError:
                    pass
            reply.deleteLater()
        except Exception:
            try:
                import traceback as _tb
                with open(os.path.join(get_data_dir(), "crash.log"),
                          "a", encoding="utf-8") as f:
                    f.write("\n--- ImageLoader._on_finished exception ---\n")
                    _tb.print_exc(file=f)
            except Exception:
                pass
            try:
                reply.deleteLater()
            except Exception:
                pass
        finally:
            self._pump()

    # ------------------------------------------------------------ static
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
        try:
            if target is not None and isValid(target):
                return max(1.0, float(target.devicePixelRatioF() or 1.0))
        except Exception:  # noqa: BLE001
            pass
        return cls._screen_dpr()

    @staticmethod
    def _round(pm: QPixmap, size: int, dpr: float = 1.0) -> QPixmap:
        px = max(4, int(round(size * max(1.0, dpr))))
        scaled = pm.scaled(px, px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        out = QPixmap(px, px)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, px, px, px * 0.18, px * 0.18)
        p.setClipPath(path)
        p.drawPixmap(0, 0, scaled)
        p.end()
        out.setDevicePixelRatio(max(1.0, dpr))
        return out


# ------------------------------------------------------------ singleton
_IMAGE_LOADER_SINGLETON = None


def get_image_loader() -> ImageLoader:
    """全局共享的图片加载器（round-181）。

    旧实现在列表页 / 版本页 / **每次新建的详情面板**里各 ``ImageLoader(self)``
    一份：3 个 ``QNetworkAccessManager``、3 套内存缓存、3 个并发队列。点开
    一个项目就重建连接池（TLS 握手重来）、丢掉所有已解码图标 → 这正是用户
    说的「点一个加载一次」。改单例后同一图标全进程只解一次、只下一次。
    """
    global _IMAGE_LOADER_SINGLETON
    if _IMAGE_LOADER_SINGLETON is None:
        _IMAGE_LOADER_SINGLETON = ImageLoader()
    return _IMAGE_LOADER_SINGLETON


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

    round-145：照 MC 官方 GUI 投影（block model gui display: rot [30,225,0]）
    取比例——顶面菱形 2:1（hh = 0.25·s，官方同为 2:1），竖直棱 vh ≈ 0.6124·s，
    即官方「竖边/总宽」比 0.866/1.414。
    此前 vh 取 hypot(cx, hh) ≈ 0.559·s（与斜边等长、贴图零形变），但官方
    渲染里竖边本就比斜边长 9.6%（16×16 贴图被竖向拉伸 1.096×，正是 MC 自
    己的效果），0.559 让侧壁矮了一截、整体 h/w 仅 1.059，视觉上就是用户
    说的「压扁」。现按官方比例：总高 = 2·hh + vh ≈ 1.112·s（官方 1.112）。
    HMCL 等启动器直接渲染 MC 原版模型，即此比例（PCL2 则用 2D 平面图标）。
    """
    cx = s / 2.0
    hh = s * 0.25
    vh = s * 0.6124
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


# round-129：原版方块贴图只有 16×16，直接按目标尺寸做最近邻映射时，每个
# texel 在 56px 图标上只占 ~3.5px，再叠加斜切变换，斜面全是阶梯状硬边、
# 噪点贴图糊成颗粒——观感就是「低清 / 被压缩」。改为 4× 超采样 + 双线性
# 贴图 + 平滑缩回：texel 边界被抗锯齿，斜边平滑，读起来像一张干净的小渲染
# 图，而不是被压坏的小图。图标只与 vtype 有关，按 (vtype, size, dpr) 缓存。
_ICON_SS = 4
_version_icon_cache: dict[tuple[str, int, float], QPixmap] = {}


def make_version_pixmap(version_id: str, vtype: str, size: int = 56,
                        dpr: float | None = None) -> QPixmap:
    """Draw a 3D isometric MC block icon for a version (HMCL / PCL2 style).

    round-107：正式版草方块、快照命令方块、愚人节工作台、旧版砖块 / 圆石。用
    随包真实 MC 贴图渲染；任何贴图缺失都会回退到纯色向量块，绝不画出坏图标。
    ``version_id`` 保留在签名里以兼容旧调用点（图标由 ``vtype`` 决定）。
    """
    if dpr is None:
        try:
            from PySide6.QtGui import QGuiApplication
            _scr = QGuiApplication.primaryScreen()
            dpr = float(_scr.devicePixelRatio()) if _scr is not None else 1.0
        except Exception:
            dpr = 1.0
    dpr = max(1.0, float(dpr))
    px = max(8, int(round(size * dpr)))
    key = (vtype, int(size), round(dpr, 2))
    hit = _version_icon_cache.get(key)
    if hit is not None:
        return hit

    names = _BLOCK_FACES.get(vtype) or _BLOCK_FALLBACK
    top_pm = _tinted_block_tex(names[0], _FACE_TINTS.get(names[0], ""))
    side_pm = _load_block_tex(names[1])
    right_pm = _load_block_tex(names[2]) if names[2] else None
    cols = _ISO_BLOCK.get(vtype) or _ISO_BLOCK["old_alpha"]

    ss = _ICON_SS
    big = px * ss
    pm = QPixmap(big, big)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    # 2 logical px padding so the AA edges of the top vertex aren't clipped. The
    # cube is taller than wide (round-145: height = s·(0.5+0.6124) ≈ 1.1124·s，
    # 照 MC 官方 GUI 投影比例，见 _draw_iso_block docstring)，so derive the
    # width from the available height instead of stuffing it into a square —
    # that was the "grass block looks squashed" bug.
    box = float(big - 4 * ss)
    s = box / 1.1124
    p.translate((big - s) / 2.0, 2.0 * ss)
    _draw_iso_block(p, s, top_pm, side_pm, right_pm,
                    QColor(cols[0]), QColor(cols[1]), QColor(cols[2]))
    p.end()

    pm = pm.scaled(px, px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    pm.setDevicePixelRatio(dpr)
    _version_icon_cache[key] = pm
    return pm

