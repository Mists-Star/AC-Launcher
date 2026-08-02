"""Icon loader.

SVGs live in assets/icons/ and are resolved through get_resource_path() so they
work both in dev (cwd-relative) and in the PyInstaller bundle (_MEIPASS).
Icons are cached so repeated lookups are cheap.
"""
import os

from PySide6.QtGui import QIcon

from .paths import get_resource_path

_CACHE: dict[str, QIcon] = {}
_SIZE = 24


def icon(name: str) -> QIcon:
    """Return a QIcon for the named SVG (no extension). Cached."""
    if name in _CACHE:
        return _CACHE[name]
    path = get_resource_path(os.path.join("assets", "icons", f"{name}.svg"))
    ic = QIcon(path)
    if ic.isNull():
        # Fallback to a generic icon so missing-asset SVGs don't render as
        # blank squares in the sidebar (e.g. 'lobby' → 'server').
        fallback = _FALLBACKS.get(name, "settings")
        if fallback != name:
            path = get_resource_path(os.path.join("assets", "icons", f"{fallback}.svg"))
            ic = QIcon(path)
    _CACHE[name] = ic
    return ic


# Fallbacks for icons referenced in nav/key paths that don't have a dedicated
# SVG. Keep this list small — new icons should be added as their own .svg.
_FALLBACKS = {
    "lobby": "server",
}


def pixmap(name: str, size: int = _SIZE):
    """Return a QPixmap of the named icon at the given pixel size."""
    return icon(name).pixmap(size, size)
