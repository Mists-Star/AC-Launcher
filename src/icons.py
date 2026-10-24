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

_CACHE: dict = {}
_PLAIN_CACHE: dict = {}
_SIZE = 24

# Fallbacks for icons referenced in nav/key paths that don't have a dedicated
# SVG. Keep this list small — new icons should be added as their own .svg.
_FALLBACKS = {
    "lobby": "server",
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
    """Resolve ``<name>.svg`` on disk (bundled assets or project tree)."""
    rel = os.path.join("assets", "icons", f"{name}.svg")
    p = get_resource_path(rel)
    if p and os.path.isfile(p):
        return p
    # Dev fallback: walk up from this file to the project root.
    here = os.path.dirname(os.path.abspath(__file__))
    proj = os.path.dirname(here)  # src/ -> project root
    cand = os.path.join(proj, "assets", "icons", f"{name}.svg")
    if os.path.isfile(cand):
        return cand
    return ""


def _svg_bytes(name: str) -> bytes | None:
    """Raw SVG document for ``name`` — QRC first, then the filesystem."""
    if icons_rc is not None:
        f = QFile(f":/icons/{name}.svg")
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
        q = QIcon(f":/icons/{name}.svg")
        if not q.isNull():
            ic = q
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


def pixmap(name: str, size: int = _SIZE, color: str | None = None) -> QPixmap:
    """Return a QPixmap of the named icon at the given pixel size."""
    return icon(name, color).pixmap(size, size)
