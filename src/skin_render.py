"""Skin renderer — turn a Minecraft 64x64 / 64x32 skin PNG into a 2D character.

``render_skin`` draws the classic blocky "Steve pose" front view by copying the
skin's texture regions onto a 16x32 character grid.  ``render_skin_3d`` builds
a real 2.5D showcase instead: every body part is a box with six textured faces
(front / back / both sides / top / bottom), projected in an isometric-style
three-quarter view with a cape plane behind the torso.  The home page uses the
latter — mainstream launchers (PCL2 / HMCL / BakaXL) all anchor their profile
card on a large 3D character, not a 96px flat sticker.

Pure Qt — no external image deps. Used for the login avatar, the account
button, the skin-library thumbnails and the home character showcase.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QPolygonF, QTransform, QColor,
)


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


def _is_slim(img: QImage, model: str | None = None) -> bool:
    """Resolve the skin variant (classic vs slim).

    The variant is metadata, not something encoded in the PNG: Mojang's
    texture property carries ``"slim"`` / ``"classic"`` and the skin library
    stores it per entry (``skins.json``).  When it is unknown (``"auto"``,
    None, local imports) fall back to a one-way layout probe: a slim arm is
    3px wide, so its unwrap only uses columns 32..45 of the left-arm region
    and leaves 46..47 transparent, while every classic skin has pixels there.
    """
    if model in ("slim", "classic"):
        return model == "slim"
    if img.isNull() or img.height() < 64:
        return False
    factor = img.width() / 64.0
    tail = _copy(img, int(round(46 * factor)), int(round(52 * factor)),
                 max(1, int(round(2 * factor))),
                 max(1, int(round(12 * factor))))
    return _empty(tail)


def render_skin(path: str, size: int, model: str | None = None) -> QPixmap:
    """Return a transparent pixmap of the full character, ``size`` wide.

    The character grid is 16×32, so the canvas is 1:2.  This used to return a
    square ``size × size`` pixmap with the grid stretched into it, which drew
    every library card's character twice as wide as tall (用户反馈「皮肤被压扁」).
    Height is always ``size * 2``.
    """
    img = QImage(path)
    out = QPixmap(size, size * 2)
    out.fill(Qt.transparent)
    if img.isNull():
        return out

    slim = _is_slim(img, model)
    legacy = img.height() < 64
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

    # left arm (viewer-right): legacy 64x32 skins mirror the right arm; 1.8+
    # skins have their own slot at (36,52).  The old code sampled (36,20),
    # which is the torso back face, so every modern skin showed a duplicated
    # torso patch instead of the arm.
    if legacy:
        larm = _copy(img, 44, 20, 4, 12)
    else:
        larm = _copy(img, 36, 52, 3 if slim else 4, 12)
        if _empty(larm):
            larm = _copy(img, 44, 20, 4, 12)
    p.drawImage(12, 8, larm)

    # legs (front faces are identical in legacy + 1.8)
    p.drawImage(4, 20, _copy(img, 4, 20, 4, 12))
    lleg = _copy(img, 8, 20, 4, 12)
    p.drawImage(8, 20, lleg)

    p.end()

    qp = QPainter(out)
    # 16×32 grid upscaled to a thumbnail: nearest keeps the skin's pixel-art
    # blocks crisp (smooth scaling turned every 1px texel into a grey smear,
    # which is the "低清" look users reported). Only downsizing gets smoothing,
    # where nearest would drop whole texels.
    qp.setRenderHint(QPainter.SmoothPixmapTransform, size < 16)
    qp.drawPixmap(0, 0, size, size * 2, grid)
    qp.end()
    return out


def render_cape(path: str, width: int, height: int) -> QPixmap:
    """Return the cape's back face scaled to ``width`` x ``height``.

    Cape textures are 64x32 (newer files 64x64 with the classic block in the
    top-left); the back face lives at (1,1) 10x16 in both. Returns a fully
    transparent pixmap when the source cannot be read, so callers can test
    with ``isNull`` / alpha sampling just like ``render_skin``.
    """
    img = QImage(path)
    out = QPixmap(width, height)
    out.fill(Qt.transparent)
    if img.isNull():
        return out

    back = _copy(img, 1, 1, 10, 16)
    qp = QPainter(out)
    qp.setRenderHint(QPainter.SmoothPixmapTransform, True)
    qp.drawPixmap(0, 0, width, height, QPixmap.fromImage(back))
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
    qp.setRenderHint(QPainter.SmoothPixmapTransform, size < 8)
    qp.drawPixmap(0, 0, size, size, head)
    qp.end()
    return out


# ---------------------------------------------------------------- 3D showcase
# UV rectangles on the 64x64 skin template (multiplied by width/64 for HD
# skins).  Legacy 64x32 skins simply have zero alpha in every 1.8-only slot,
# which the fallbacks below detect.
_HEAD_UV = {
    "front": (8, 8, 8, 8), "back": (24, 8, 8, 8),
    "right": (0, 8, 8, 8), "left": (16, 8, 8, 8),
    "top": (8, 0, 8, 8), "bottom": (16, 0, 8, 8),
}
_HAT_UV = {
    "front": (40, 8, 8, 8), "back": (56, 8, 8, 8),
    "right": (32, 8, 8, 8), "left": (48, 8, 8, 8),
    "top": (40, 0, 8, 8), "bottom": (48, 0, 8, 8),
}
_BODY_UV = {
    "front": (20, 20, 8, 12), "back": (32, 20, 8, 12),
    "right": (16, 20, 4, 12), "left": (28, 20, 4, 12),
    "top": (28, 16, 8, 4), "bottom": (32, 16, 8, 4),
}
_RARM_UV = {
    "front": (44, 20, 4, 12), "back": (52, 20, 4, 12),
    "right": (40, 20, 4, 12), "left": (48, 20, 4, 12),
    "top": (44, 16, 4, 4), "bottom": (48, 16, 4, 4),
}
_LARM_UV = {
    "front": (36, 52, 4, 12), "back": (44, 52, 4, 12),
    "right": (32, 52, 4, 12), "left": (40, 52, 4, 12),
    "top": (36, 48, 4, 4), "bottom": (40, 48, 4, 4),
}
# Slim skins are one pixel narrower per side, so their unwrap is packed
# differently: the front/back faces only use 3 columns and every side face
# shifts left by one.  Sampling the classic rectangle here would read column
# 46 — the transparent gap — and paint a stray strip.
_SLIM_LARM_UV = {
    "front": (36, 52, 3, 12), "back": (43, 52, 3, 12),
    "right": (32, 52, 4, 12), "left": (39, 52, 4, 12),
    "top": (36, 48, 3, 4), "bottom": (39, 48, 3, 4),
}
_RLEG_UV = {
    "front": (4, 20, 4, 12), "back": (12, 20, 4, 12),
    "right": (0, 20, 4, 12), "left": (8, 20, 4, 12),
    "top": (4, 16, 4, 4), "bottom": (8, 16, 4, 4),
}
_LLEG_UV = {
    "front": (20, 52, 4, 12), "back": (28, 52, 4, 12),
    "right": (24, 52, 4, 12), "left": (16, 52, 4, 12),
    "top": (20, 48, 4, 4), "bottom": (24, 48, 4, 4),
}


def skin_model(path: str, model: str | None = None) -> str:
    """Return ``"slim"`` for Alex-style skins, else ``"classic"``."""
    try:
        img = QImage(path)
        return "slim" if (not img.isNull() and _is_slim(img, model)) else "classic"
    except Exception:  # noqa: BLE001
        return "classic"


def _uv_crop(img: QImage, uv, factor: float, overlay=None) -> QImage:
    u, v, w, h = uv
    out = _copy(img, int(round(u * factor)), int(round(v * factor)),
                max(1, int(round(w * factor))), max(1, int(round(h * factor))))
    if overlay is not None and not _empty(overlay):
        p = QPainter(out)
        p.drawImage(0, 0, overlay)
        p.end()
    return out


def _face_quad(box, face):
    x0, x1, y0, y1, z0, z1 = box
    if face == "front":
        return [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    if face == "back":
        return [(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)]
    if face == "left":
        return [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)]
    if face == "right":
        return [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)]
    if face == "top":
        return [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]
    return [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)]


# Minecraft's own per-face ambient multipliers (up 1.0 / down 0.5 /
# north-south 0.8 / east-west 0.6).  Shading is fixed to the *model*, not the
# camera: as the turntable spins it reveals differently shaded faces, which is
# what makes the boxes read as solids.  A camera-relative light would instead
# keep the front face at a constant brightness and look flat.
_FACE_SHADE = {
    "top": 1.0, "bottom": 0.5,
    "front": 0.8, "back": 0.8,
    "left": 0.6, "right": 0.6,
}


def render_skin_3d(path: str, width: int, height: int,
                   cape_path: str | None = None, yaw: float = 20.0,
                   pitch: float = 8.0, model: str | None = None,
                   supersample: int = 2, smooth: bool = False) -> QPixmap:
    """Render a large three-quarter character with an optional cape.

    Mainstream launchers anchor the profile card on a big 3D model rather than
    a tiny flat sprite; this is the pure-Qt equivalent.  ``width`` / ``height``
    are in device-independent pixels.

    round-126（用户仍反馈「低清」）：
      * 皮肤是 64×64 的像素画，放大到 ~9 px/texel：双线性会把每颗 texel 抹成
        灰雾，读起来就是「低清」；默认改回最近邻（``smooth=False``），texel
        保持硬块，轮廓交给抗锯齿 + 2× 超采样，观感是像素画而不是糊图。
      * 每个面按 Minecraft 的固有条数（顶 1.0 / 底 0.5 / 前后 0.8 / 侧 0.6）
        压暗，并给面边缘加一条极细接缝——立方体有体积感，手臂/躯干/腿不再
        糊成一整块平板；
      * 取景按整圈旋转的最大轮廓计算，转台过程不缩放、不上下浮动。
    """
    out = QPixmap(width, height)
    out.fill(Qt.transparent)
    img = QImage(path)
    if img.isNull() or img.width() < 64 or img.height() < 32:
        return out

    factor = img.width() / 64.0
    slim = _is_slim(img, model)
    legacy = img.height() < 64
    aw = 3 if slim else 4

    head = {f: _uv_crop(img, uv, factor,
                        _uv_crop(img, _HAT_UV[f], factor) if not legacy else None)
            for f, uv in _HEAD_UV.items()}
    body = {f: _uv_crop(img, uv, factor) for f, uv in _BODY_UV.items()}
    rarm = {f: _uv_crop(img, uv, factor) for f, uv in _RARM_UV.items()}
    larm_uv = _RARM_UV if legacy else (_SLIM_LARM_UV if slim else _LARM_UV)
    larm = {f: _uv_crop(img, uv, factor) for f, uv in larm_uv.items()}
    if not legacy and _empty(larm["front"]):
        larm = rarm
    rleg = {f: _uv_crop(img, uv, factor) for f, uv in _RLEG_UV.items()}
    lleg_uv = _RLEG_UV if legacy else _LLEG_UV
    lleg = {f: _uv_crop(img, uv, factor) for f, uv in lleg_uv.items()}
    if not legacy and _empty(lleg["front"]):
        lleg = rleg

    boxes = [
        ((-4, 4, 0, 8, -4, 4), head),
        ((-4, 4, 8, 20, -2, 2), body),
        ((-4 - aw, -4, 8, 20, -2, 2), rarm),
        ((4, 4 + aw, 8, 20, -2, 2), larm),
        ((-4, 0, 20, 32, -2, 2), rleg),
        ((0, 4, 20, 32, -2, 2), lleg),
    ]

    # Cape as a flared plane behind the torso (visible on the far side in the
    # three-quarter view).  Only drawn when a cape file actually parses.
    cape_quad = None
    cape_img = QImage(cape_path) if cape_path else QImage()
    if not cape_img.isNull():
        cf = cape_img.width() / 64.0
        # Cape hangs from just under the shoulders and flares only slightly;
        # a wide / far-offset plane reads as a flag stuck to the back rather
        # than cloth (first attempt used half-width 8 at z=-5.5).
        cape_quad = ([(-5.2, 8.4, -2.6), (5.2, 8.4, -2.6),
                      (6.9, 27.2, -4.2), (-6.9, 27.2, -4.2)],
                     _copy(cape_img, int(1 * cf), int(1 * cf),
                          max(1, int(10 * cf)), max(1, int(16 * cf))))

    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))

    def project(pt, c_y=cy, s_y=sy):
        x, y, z = pt
        x1 = x * c_y + z * s_y
        z1 = -x * s_y + z * c_y
        return x1, y * cp + z1 * sp, -y * sp + z1 * cp

    # Fit the model using its *widest* silhouette over a full turn instead of
    # this frame's own bbox.  Per-frame fitting made the character zoom in and
    # out while it spun (a side view is 4 units wide, a front view 16) — the
    # "呼吸" that looked wrong next to a real 3D renderer.
    corners = [(x, y, z) for box, _tex in boxes
               for x in (box[0], box[1]) for y in (box[2], box[3])
               for z in (box[4], box[5])]
    if cape_quad:
        corners.extend(cape_quad[0])
    fit_xs, fit_ys = [], []
    for deg in range(0, 360, 15):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        for pt in corners:
            px, py, _pz = project(pt, c, s)
            fit_xs.append(px)
            fit_ys.append(py)
    span_x = max(1e-3, max(fit_xs) - min(fit_xs))
    span_y = max(1e-3, max(fit_ys) - min(fit_ys))
    ss = max(1, int(supersample))
    scale = min((width - 2) / span_x, (height - 2) / span_y) * ss
    ox = (width * ss - span_x * scale) / 2.0 - min(fit_xs) * scale
    oy = (height * ss - span_y * scale) / 2.0 - min(fit_ys) * scale

    faces = []
    for box, tex in boxes:
        for face in ("front", "back", "left", "right", "top", "bottom"):
            proj = [project(v) for v in _face_quad(box, face)]
            depth = sum(p[2] for p in proj) / 4.0
            faces.append((depth, proj, tex[face], face))
    if cape_quad:
        proj = [project(v) for v in cape_quad[0]]
        faces.append((sum(p[2] for p in proj) / 4.0 - 0.01, proj,
                      cape_quad[1], "front"))
    faces.sort(key=lambda it: it[0])  # farthest first (painter's algorithm)

    big = QPixmap(width * ss, height * ss)
    big.fill(Qt.transparent)
    p = QPainter(big)
    p.setRenderHint(QPainter.Antialiasing, True)
    # Skin textures are 64×64 pixel art blown up to ~9 device px per texel.
    # Nearest keeps every texel a hard block (faithful to Minecraft's own GL
    # preview); the antialiased polygon edges + 2× supersampling keep the
    # silhouette smooth. Bilinear here just blurred the whole model.
    p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
    for _, proj, tex, face in faces:
        if tex.isNull():
            continue
        quad = QPolygonF([QPointF(x * scale + ox, y * scale + oy)
                          for x, y, _ in proj])
        src = QPolygonF([QPointF(0, 0), QPointF(tex.width(), 0),
                         QPointF(tex.width(), tex.height()),
                         QPointF(0, tex.height())])
        t = QTransform()
        if not QTransform.quadToQuad(src, quad, t):
            continue
        p.save()
        p.setTransform(t)
        p.drawImage(0, 0, tex)
        p.restore()
        # Minecraft-style per-face ambient (top 1.0, bottom 0.5, front/back
        # 0.8, sides 0.6).  Kept model-relative so spinning reveals the
        # differently shaded faces rather than sliding one flat tint around.
        shade = _FACE_SHADE[face]
        p.setBrush(QColor(0, 0, 0, int((1.0 - shade) * 235)))
        p.setPen(Qt.NoPen)
        p.drawPolygon(quad)
        # A hairline seam keeps coplanar neighbours (arm front vs torso front)
        # from melting into one slab — without it the model reads as a cross.
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(0, 0, 0, 46))
        p.drawPolygon(quad)
    p.end()

    qp = QPainter(out)
    qp.setRenderHint(QPainter.SmoothPixmapTransform, ss > 1)
    qp.drawPixmap(0, 0, width, height, big)
    qp.end()
    return out


def render_skin_frames(path: str, width: int, height: int,
                       cape_path: str | None = None, model: str | None = None,
                       count: int = 30, pitch: float = 8.0) -> list[QPixmap]:
    """Pre-render a full 360° turntable for the home card's idle spin.

    Round-125: the character used to be one frozen frame, which read as a
    statue next to PCL2/HMCL's slowly turning models.  ~30 frames cost well
    under a second to build and ~30 MB peak, so the home page can animate at
    ~18 fps by swapping pixmaps (no per-frame 3D math).
    """
    n = max(1, int(count))
    frames: list[QPixmap] = []
    for i in range(n):
        frames.append(render_skin_3d(path, width, height, cape_path,
                                     yaw=360.0 * i / n, pitch=pitch,
                                     model=model))
    return frames

