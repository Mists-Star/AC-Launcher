"""Icon loader.

SVGs live in ``assets/icons/`` and are shipped next to the binary (or, in dev,
resolved from the project tree). They are loaded from disk with an in-memory
cache so repeated lookups are instant.

An embedded QRC resource (``src/icons_rc.py``, registered under
``:/icons/<name>.svg``) is used when present. Its absence must NEVER crash
startup — frozen builds that fail to collect the generated module simply fall
back to the on-disk SVGs, which are bundled too (``_internal/assets/icons``).

Theme awareness
---------------
Most icons are *flat monochrome glyphs*. Their colour must follow the theme,
otherwise a hard-coded slate grey (``#475569``) sits at only 1.89:1 against
the dark card background — invisible in practice. The glyphs are therefore
rendered through :class:`_TintedIconEngine`, which draws the SVG vector at
the exact requested size and then replaces every opaque pixel with the theme
colour (``text_sub`` for neutral glyphs, ``text_accent`` for accent glyphs).

Brand marks and status colours keep their original artwork (see
``_KEEP_COLOR``) — recolouring a Minecraft loader logo or a green "ready"
check would destroy their meaning.
"""
import os
import re

from PySide6.QtCore import (
    QByteArray, QFile, QIODevice, QPointF, QRectF, QSize, QSizeF, Qt,
)
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap

from .paths import get_resource_path

# Register the embedded icon resource if it was bundled. Failure (e.g. the
# generated src/icons_rc.py wasn't collected by the freezer) is non-fatal — we
# fall back to the on-disk SVGs below. Never let this raise into MainWindow's
# construction (that previously hard-crashed the frozen build on import).
icons_rc = None
try:
    from . import icons_rc  # noqa: F401  (registers :/icons/*)
except Exception:
    icons_rc = None

# round-180：官方加载器 logo 的原始格式（顺序即优先级），一律原样复用
_ICON_EXTS = (".svg", ".png", ".ico")

_CACHE: dict = {}
_PLAIN_CACHE: dict = {}
_SIZE = 24

# Fallbacks for icons referenced in nav/key paths that don't have a dedicated
# SVG. Keep this list small — new icons should be added as their own .svg.
_FALLBACKS = {
    "lobby": "server",
    "toolbox": "tools",   # round-124：AC 侧栏「其他」分组新增百宝箱入口
}

# Icons whose artwork carries meaning and must NOT be recoloured: brand marks
# (loader logos, Microsoft, AC logo) and status colours (green check, amber
# warning, the sun/moon pair).
_KEEP_COLOR = {
    "ac_launcher_icon", "ac_launcher_icon_white", "logo", "microsoft",
    "check", "sun",
    "dialog_info", "dialog_question", "dialog_success", "dialog_warning",
    "loader_cleanroom", "loader_fabric", "loader_forge", "loader_labymod",
    "loader_legacyfabric", "loader_liteloader", "loader_neoforge",
    "loader_optifine", "loader_quilt", "loader_vanilla",
}

# Glyphs that represent an action/brand accent rather than a neutral tool.
_ACCENT_GLYPHS = {"play", "pause", "moon"}

# Bounded cache: keys are (name, tint) and the theme can change at runtime,
# so old entries would otherwise pile up forever.
_MAX_CACHE = 512


def _icon_path(name: str) -> str:
    """Resolve an icon on disk (bundled assets or project tree).

    round-180：官方加载器 logo 有 SVG / PNG / ICO 三种**原始格式**，
    原样复用、不再手绘。按扩展名优先级找第一个存在的文件。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    proj = os.path.dirname(here)  # src/ -> project root
    for ext in _ICON_EXTS:
        rel = os.path.join("assets", "icons", f"{name}{ext}")
        p = get_resource_path(rel)
        if p and os.path.isfile(p):
            return p
        cand = os.path.join(proj, "assets", "icons", f"{name}{ext}")
        if os.path.isfile(cand):
            return cand
    return ""


def _svg_bytes(name: str) -> bytes | None:
    """Raw SVG document for ``name`` — QRC first, then the filesystem."""
    if icons_rc is not None:
        for ext in _ICON_EXTS:
            f = QFile(f":/icons/{name}{ext}")
            # 先判存在：直接 open 会让 QtSvg 对不存在的 .svg 打
            # "Cannot open file" 警告，污染日志（资源本身能正常回退）。
            if not f.exists():
                continue
            if f.open(QIODevice.OpenModeFlag.ReadOnly):
                data = bytes(f.readAll())
                f.close()
                if data:
                    return data
    p = _icon_path(name)
    if p:
        try:
            with open(p, "rb") as fh:
                return fh.read()
        except OSError:
            return None
    return None


class _TintedIconEngine(QIconEngine):
    """Renders an SVG document in one flat colour.

    The vector is drawn at the exact size the widget asks for (so it stays
    crisp), then every opaque pixel is replaced by ``color`` via
    ``CompositionMode_SourceIn``. Anti-aliased edges are preserved because
    the fill is masked by the rendered alpha.
    """

    def __init__(self, svg: bytes, color: str):
        super().__init__()
        self._svg = svg
        self._color = QColor(color)

    def clone(self):
        return _TintedIconEngine(self._svg, self._color.name())

    def _render(self, size: QSize) -> QPixmap:
        from PySide6.QtSvg import QSvgRenderer  # local import: keeps startup lean

        w = max(1, int(size.width()))
        h = max(1, int(size.height()))
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        r = QSvgRenderer(QByteArray(self._svg))
        if r.isValid():
            p = QPainter(pm)
            r.render(p, QRectF(QPointF(0, 0), QSizeF(w, h)))
            p.end()
        if self._color.isValid():
            p2 = QPainter(pm)
            p2.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            p2.fillRect(pm.rect(), self._color)
            p2.end()
        return pm

    def pixmap(self, size, mode, state):
        return self._render(QSize(size))

    def paint(self, painter, rect, mode, state):
        painter.drawPixmap(rect.topLeft(), self._render(rect.size()))


def _default_tint(name: str) -> str:
    """Theme colour for a monochrome glyph."""
    from .theme import COLORS
    if name in _ACCENT_GLYPHS:
        return COLORS.get("text_accent") or COLORS.get("accent") or "#7C3AED"
    return COLORS.get("text_sub") or "#6B7280"


def _plain_icon(name: str) -> QIcon:
    """Un-recoloured icon (brand / status artwork)."""
    if name in _PLAIN_CACHE:
        return _PLAIN_CACHE[name]
    ic = QIcon()
    if icons_rc is not None:
        for ext in _ICON_EXTS:
            _res = f":/icons/{name}{ext}"
            if not QFile(_res).exists():
                continue
            q = QIcon(_res)
            if not q.isNull():
                ic = q
                break
    if ic.isNull():
        p = _icon_path(name)
        if p:
            ic = QIcon(p)
    if ic.isNull() and name in _FALLBACKS and _FALLBACKS[name] != name:
        ic = _plain_icon(_FALLBACKS[name])
    _PLAIN_CACHE[name] = ic
    return ic


def icon(name: str, color: str | None = None) -> QIcon:
    """Return a theme-aware QIcon for the named SVG (no extension).

    Resolution order:
      1. Embedded QRC resource ``:/icons/<name>.svg`` (fastest, if registered).
      2. Filesystem ``assets/icons/<name>.svg`` (bundled or project tree).
      3. Generic fallback so a missing SVG doesn't render as a blank square.

    ``color`` overrides the theme tint (hex string). Use :func:`on_accent`
    for icons that sit on top of an accent-filled surface.
    """
    if name in _KEEP_COLOR:
        return _plain_icon(name)

    tint = color or _default_tint(name)
    key = (name, tint)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    data = _svg_bytes(name)
    if data:
        ic = QIcon(_TintedIconEngine(data, tint))
    else:
        ic = _plain_icon(name)

    if len(_CACHE) >= _MAX_CACHE:
        _CACHE.clear()
    _CACHE[key] = ic
    return ic


def on_accent(name: str) -> QIcon:
    """Icon coloured for a surface filled with the accent colour.

    ``text_on_accent`` is black or white depending on the accent's luminance,
    so the glyph stays readable on every accent (violet, cyan, amber, …).
    """
    from .theme import COLORS
    return icon(name, COLORS.get("text_on_accent") or "#FFFFFF")


def screen_dpr(widget=None) -> float:
    """Device pixel ratio of the screen where rendering is happening (>= 1.0).

    round-217：原来只取 `primaryScreen()` —— 主屏 100% + 副屏 150% 的多屏
    环境下，副屏上的头像/侧栏图标会按 1.0 渲染再被放大 1.5 倍，边缘发虚。
    现在优先用「发起渲染的窗口所在屏幕」，其次用鼠标所在屏幕（新建图标的
    位置基本等于用户正在看的屏幕），最后才回退主屏。
    """
    try:
        if widget is not None:
            try:
                fn = getattr(widget, "devicePixelRatioF", None)
                v = float(fn()) if callable(fn) else float(widget.devicePixelRatio())
                if v > 0:
                    return max(1.0, v)
            except Exception:  # noqa: BLE001 - 窗口还没上屏
                pass
        from PySide6.QtGui import QGuiApplication

        scr = None
        try:
            from PySide6.QtGui import QCursor
            scr = QGuiApplication.screenAt(QCursor.pos())
        except Exception:  # noqa: BLE001 - offscreen 平台没有光标
            scr = None
        scr = scr or QGuiApplication.primaryScreen()
        return max(1.0, float(scr.devicePixelRatio()) if scr else 1.0)
    except Exception:  # noqa: BLE001 - no screen yet
        return 1.0


def pixmap(name: str, size: int = _SIZE, color: str | None = None,
           dpr: float | None = None) -> QPixmap:
    """Return a QPixmap of the named icon at the given *logical* pixel size.

    round-148：HiDPI（125%/150%）屏上，按逻辑尺寸渲染的位图会被 Qt 的设备
    变换再放大一次 → 边缘发虚。这里按 ``size × dpr`` 的**物理**像素渲染，
    并打上 devicePixelRatio 标记，QLabel / QIcon 都会 1:1 显示。

    注意：``size`` 的语义仍是「逻辑边长」——返回的位图物理尺寸是
    ``size × dpr``，但显示出来还是 ``size`` 逻辑像素，布局不受影响。
    """
    dpr = screen_dpr() if dpr is None else max(1.0, float(dpr or 1.0))
    # ``QIcon.pixmap(size, dpr)`` 会让引擎按 ``size × dpr`` 的**物理**像素
    # 渲染，并打上 dpr 标记（``pixmap(size)`` 也会自动套用屏幕 DPR）。
    pm = icon(name, color).pixmap(QSize(size, size), dpr)
    pm.setDevicePixelRatio(dpr)
    return pm


# 大尺寸渲染时描边该有多粗。用**比例**而不是固定值：56px 时 3.36px、
# 80px 时 4.8px，视觉配重才跟得上字号；固定 3.4 在 80px 上会显得单薄。
# 上下夹住 [2.6, 5.0]：小图不至于太细，超大图不至于又糊成块。
_LARGE_GLYPH_RATIO = 0.06
_LARGE_GLYPH_MIN = 2.6
_LARGE_GLYPH_MAX = 5.0

_STROKE_RE = re.compile(rb'(stroke-width\s*=\s*")([\d.]+)(")')


def pixmap_large(name: str, size: int = 56, color: str | None = None,
                 stroke_px: float | None = None,
                 dpr: float | None = None) -> QPixmap:
    """大尺寸字形（空态图标等）：**把描边按绝对像素收细**再渲染。

    ☠ 24px 设计的字形（lucide 系，``stroke-width="2"``）直接放大到 56px 时，
    描边同比涨到 4.7px，而字形内部间隙只有 4 个单位 → 「四宫格」这类多块
    拼接的字形会粘连成一团深色块，看起来像**被相邻方块遮挡**（round-183
    实测：用户在编辑面板模组页一眼看出来，我先前只检查了有没有裁切、
    没看描边配重，所以漏了）。

    做法：按目标物理像素反推 SVG 单位描边 ``stroke_px / scale``，且**只减不增**
    （原本就细的字形保持原样）。颜色/缓存不走 ``icon()``，避免污染小图标缓存。
    """
    from PySide6.QtSvg import QSvgRenderer  # 局部导入：保持启动轻量

    # 品牌/状态图（加载器 logo、绿色勾、警告三角…）自带配色，重着色会把
    # 含义弄丢 —— 交回普通渲染，别在这里也套一层 tint。
    if name in _KEEP_COLOR:
        return pixmap(name, size, color=color, dpr=dpr)

    dpr = screen_dpr() if dpr is None else max(1.0, float(dpr or 1.0))
    if stroke_px is None:
        stroke_px = min(_LARGE_GLYPH_MAX,
                        max(_LARGE_GLYPH_MIN, size * _LARGE_GLYPH_RATIO))
    data = _svg_bytes(name)
    tint = QColor(color or _default_tint(name))
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)

    if data:
        r = QSvgRenderer(QByteArray(data))
        vb = r.viewBox()
        scale = px / max(1.0, vb.width() or float(_SIZE))
        want = stroke_px * dpr / max(1e-6, scale)
        if want > 0:
            data = _STROKE_RE.sub(
                lambda m: m.group(1) + (b"%.3f" % min(float(m.group(2)), want)) + m.group(3),
                data)
            r = QSvgRenderer(QByteArray(data))
        if r.isValid():
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            r.render(p, QRectF(QPointF(0, 0), QSizeF(px, px)))
            p.end()
    if tint.isValid():
        p2 = QPainter(pm)
        p2.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p2.fillRect(pm.rect(), tint)
        p2.end()
    pm.setDevicePixelRatio(dpr)
    return pm
