"""Skin renderer — turn a Minecraft 64x64 / 64x32 skin PNG into a 2D character.

We draw the classic blocky "Steve pose" front view by copying the skin's
texture regions onto a 16x32 character grid, then scaling to the requested
size. Works for both the legacy (64x32) and modern (64x64, 1.8+) templates:
the front faces live at the same coordinates in both; for the left arm we try
the legacy slot first and fall back to the 1.8 slot, and we detect the slim
(Alex) model by inspecting the 1.8 left-arm region.

Pure Qt — no external image deps. Used for the login avatar, the account
button and the skin-library thumbnails.
"""
from PySide6.QtGui import QImage, QPixmap, QPainter
from PySide6.QtCore import Qt


def _copy(img: QImage, x: int, y: int, w: int, h: int) -> QImage:
    x = max(0, min(x, img.width() - 1))
    y = max(0, min(y, img.height() - 1))
    w = max(1, min(w, img.width() - x))
    h = max(1, min(h, img.height() - y))
    return img.copy(x, y, w, h)


def _empty(region: QImage) -> bool:
    for yy in range(region.height()):
        for xx in range(region.width()):
            if region.pixelColor(xx, yy).alpha() > 0:
                return False
    return True


def _is_slim(img: QImage) -> bool:
    """Slim (Alex) model => left arm is 3px wide at x=40 in the 1.8 template."""
    if img.height() < 64:
        return False
    cand = _copy(img, 40, 20, 3, 12)
    if _empty(cand):
        return False
    # classic left arm would be 4px at x=36; slim is 3px at x=40..42
    return not _empty(_copy(img, 40, 20, 3, 1))


def render_skin(path: str, size: int) -> QPixmap:
    """Return a transparent pixmap of the full character, scaled to `size`."""
    img = QImage(path)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    if img.isNull():
        return out

    slim = _is_slim(img)
    grid = QPixmap(16, 32)
    grid.fill(Qt.transparent)
    p = QPainter(grid)
    p.setRenderHint(QPainter.Antialiasing, False)

    # head + hat overlay
    p.drawImage(4, 0, _copy(img, 8, 8, 8, 8))
    hat = _copy(img, 40, 8, 8, 8)
    if not _empty(hat):
        p.drawImage(4, 0, hat)

    # torso
    p.drawImage(4, 8, _copy(img, 20, 20, 8, 12))

    # right arm (viewer-left)
    p.drawImage(0, 8, _copy(img, 44, 20, 4, 12))

    # left arm (viewer-right): legacy slot, fall back to 1.8 slot
    larm = _copy(img, 36, 20, 4, 12)
    if _empty(larm):
        larm = _copy(img, 40, 20, 3 if slim else 4, 12)
    elif slim:
        larm = _copy(img, 40, 20, 3, 12)
    p.drawImage(12, 8, larm)

    # legs (front faces are identical in legacy + 1.8)
    p.drawImage(4, 20, _copy(img, 4, 20, 4, 12))
    lleg = _copy(img, 8, 20, 4, 12)
    p.drawImage(8, 20, lleg)

    p.end()

    qp = QPainter(out)
    qp.setRenderHint(QPainter.SmoothPixmapTransform, True)
    qp.drawPixmap(0, 0, size, size, grid)
    qp.end()
    return out


def render_head(path: str, size: int) -> QPixmap:
    """Return a transparent pixmap of just the head (avatar)."""
    img = QImage(path)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    if img.isNull():
        return out

    head = QPixmap(8, 8)
    head.fill(Qt.transparent)
    p = QPainter(head)
    p.drawImage(0, 0, _copy(img, 8, 8, 8, 8))
    hat = _copy(img, 40, 8, 8, 8)
    if not _empty(hat):
        p.drawImage(0, 0, hat)
    p.end()

    qp = QPainter(out)
    qp.setRenderHint(QPainter.SmoothPixmapTransform, True)
    qp.drawPixmap(0, 0, size, size, head)
    qp.end()
    return out
