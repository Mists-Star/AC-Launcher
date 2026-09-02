"""Icon loader.

SVGs live in ``assets/icons/`` and are shipped next to the binary (or, in dev,
resolved from the project tree). They are loaded from disk with an in-memory
cache so repeated lookups are instant.

An embedded QRC resource (``src/icons_rc.py``, registered under
``:/icons/<name>.svg``) is used when present. Its absence must NEVER crash
startup — frozen builds that fail to collect the generated module simply fall
back to the on-disk SVGs, which are bundled too (``_internal/assets/icons``).
"""
import os
import sys

from PySide6.QtGui import QIcon, QPixmap

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
_SIZE = 24

# Fallbacks for icons referenced in nav/key paths that don't have a dedicated
# SVG. Keep this list small — new icons should be added as their own .svg.
_FALLBACKS = {
    "lobby": "server",
}


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


def icon(name: str) -> QIcon:
    """Return a QIcon for the named SVG (no extension). Cached.

    Resolution order:
      1. Embedded QRC resource ``:/icons/<name>.svg`` (fastest, if registered).
      2. Filesystem ``assets/icons/<name>.svg`` (bundled or project tree).
      3. Generic fallback so a missing SVG doesn't render as a blank square.
    """
    if name in _CACHE:
        return _CACHE[name]

    ic = QIcon()

    # 1. QRC embedded — fastest, only if the resource was registered.
    if icons_rc is not None:
        q = QIcon(f":/icons/{name}.svg")
        if not q.isNull():
            ic = q

    # 2. Filesystem SVG (bundled assets / project tree).
    if ic.isNull():
        p = _icon_path(name)
        if p:
            ic = QIcon(p)

    # 3. Fallback to a generic icon so missing-asset SVGs don't render as
    #    blank squares in the sidebar (e.g. 'lobby' -> 'server').
    if ic.isNull() and name in _FALLBACKS and _FALLBACKS[name] != name:
        ic = icon(_FALLBACKS[name])

    _CACHE[name] = ic
    return ic


def pixmap(name: str, size: int = _SIZE) -> QPixmap:
    """Return a QPixmap of the named icon at the given pixel size."""
    return icon(name).pixmap(size, size)
