"""Application brand: single source of truth for name / identity / definition.

Everything user-facing that names the launcher reads from here, so renaming
later is a one-file edit.

Name: AC Launcher / Absolute Controller
  - English full name : Absolute Controller
  - Short brand / abbreviation : AC   (like "AC" -> "AC Launcher")
  - Chinese full name : 绝对控制器
  - Window title / about : AC Launcher

定位：跨启动器的 Minecraft Java 版统一控制器。聚合、管理并修复本机所有
其它启动器的实例——一切尽在本地、私密、由你掌控。
"""

# Core identity
APP_NAME = "AC"                 # short ASCII brand (logs, Minecraft launcherName)
APP_NAME_EN = "Absolute Controller"
APP_NAME_ZH = "绝对控制器"
APP_DISPLAY = "AC Launcher"     # window title / about / titlebar logo text
APP_ABBR = "AC"

# Microsoft identity platform — this launcher's own Azure AD app (public client).
# Registered by Mists-Star. The launcher uses the Authorization Code flow with a
# local loopback redirect (http://127.0.0.1:7890/), so the Azure app MUST list
# that exact URI under "公共客户端/本机" redirect URIs. Overridable at runtime via
# Settings -> 登录 -> 微软应用 ID (leave blank to fall back to the built-in default).
# NOTE: Xbox Live scope (XboxLive.signin) for this app requires Mojang review
# (https://aka.ms/mce-reviewappid) before real Minecraft login works end-to-end.
MS_CLIENT_ID = "ba522940-6118-4c81-82f1-7e5dd304d5e0"
APP_DESCRIPTION = (
    "现代、轻量的跨启动器 Minecraft Java 版启动器。"
    "统一管理本机与各主流启动器的实例，支持微软 / 离线 / 外置登录，"
    "并能自动检测、导入与修复其它启动器的实例，让你的每一次启动都尽在掌握。"
)

# Versioning
APP_VERSION = "1.0.0-beta"
APP_AUTHOR = "雾星 / Mists Star"

# Brand accent (mirrors theme.py accent so the logo + UI stay in sync)
BRAND_ACCENT = "#7C3AED"


# ---------------------------------------------------------------------------
# Vector "AC" monogram (hand-drawn logotype, zero font dependency).
#
# The splash and the welcome screen both render this mark. Keeping the geometry
# here gives the brand letterforms a single source of truth. Strokes are filled
# tapered "brush" shapes (thicker along the body, thin at the tips) so the mark
# reads as hand-drawn rather than as a typed font.
# ---------------------------------------------------------------------------
import math as _math


def _sample_cubic(p0, p1, p2, p3, n=48):
    """Sample a cubic Bezier into n points (control points are plain tuples)."""
    from PySide6.QtCore import QPointF
    pts = []
    for i in range(n):
        u = i / (n - 1)
        v = 1.0 - u
        x = v**3 * p0[0] + 3 * v**2 * u * p1[0] + 3 * v * u**2 * p2[0] + u**3 * p3[0]
        y = v**3 * p0[1] + 3 * v**2 * u * p1[1] + 3 * v * u**2 * p2[1] + u**3 * p3[1]
        pts.append(QPointF(x, y))
    return pts


def _sample_quad(p0, p1, p2, n=16):
    """Sample a quadratic Bezier into n points."""
    from PySide6.QtCore import QPointF
    pts = []
    for i in range(n):
        u = i / (n - 1)
        v = 1.0 - u
        x = v**2 * p0[0] + 2 * v * u * p1[0] + u**2 * p2[0]
        y = v**2 * p0[1] + 2 * v * u * p1[1] + u**2 * p2[1]
        pts.append(QPointF(x, y))
    return pts


def _sample_arc(deg0, deg1, radius=50.0, wobble=1.6, n=64):
    """Sample a gentle organic arc (radius wobbles slightly for a drawn feel)."""
    from PySide6.QtCore import QPointF
    pts = []
    for i in range(n):
        u = i / (n - 1)
        a = _math.radians(deg0 + (deg1 - deg0) * u)
        r = radius + wobble * _math.sin(3.0 * _math.pi * u)
        pts.append(QPointF(r * _math.cos(a), r * _math.sin(a)))
    return pts


def letter_a_strokes():
    """Strokes of the "A": (points, w_start, w_end, w_mid).

    The two legs are ONE continuous centreline with a rounded apex (avoids the
    notch two separate legs leave), drawn very first; the crossbar follows.
    Width swells to a brush belly at the apex and tapers to pointed tips.
    """
    left = _sample_cubic((-36, 54), (-26, 10), (-11, -30), (-4, -46), 40)
    apex = _sample_quad((-4, -46), (0, -56), (4, -46), 16)
    right = _sample_cubic((4, -46), (11, -30), (26, 10), (36, 54), 40)
    outline = left + apex[1:] + right[1:]
    return [
        (outline, 6.0, 6.0, 11.0),
        (_sample_cubic((-20, 17), (-7, 11), (8, 11), (26, 15), 24), 5.5, 5.5, 6.5),
    ]


def letter_c_strokes():
    """Strokes of the "C": a single open crescent, thick in the middle and
    tapering to pointed brush tips."""
    return [
        (_sample_arc(308.0, 52.0, 50.0, 1.6, 64), 4.5, 4.5, 14.0),
    ]


def _strokes_for(letter):
    return letter_a_strokes() if letter.upper() == "A" else letter_c_strokes()


def brush_path(points, w_start, w_end, w_mid=None):
    """Build a filled, tapered brush polygon along a centreline.

    Width eases from ``w_start`` to ``w_end``; when ``w_mid`` is given the width
    bulges through it at the midpoint (calligraphic belly). Round caps are added
    at both tips. Fill rule is Winding so overlapping sub-paths still fill.
    """
    from PySide6.QtGui import QPainterPath
    from PySide6.QtCore import Qt, QPointF
    n = len(points)
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    if n < 2:
        return path
    left, right = [], []
    for i, pt in enumerate(points):
        if i == 0:
            tx, ty = points[1].x() - pt.x(), points[1].y() - pt.y()
        elif i == n - 1:
            tx, ty = pt.x() - points[i - 1].x(), pt.y() - points[i - 1].y()
        else:
            tx, ty = points[i + 1].x() - points[i - 1].x(), points[i + 1].y() - points[i - 1].y()
        ln = _math.hypot(tx, ty) or 1.0
        nx, ny = -ty / ln, tx / ln
        u = i / (n - 1)
        base = w_start + (w_end - w_start) * u
        if w_mid is None:
            w = base
        else:
            w = base + (w_mid - (w_start + w_end) / 2.0) * _math.sin(_math.pi * u)
        left.append(QPointF(pt.x() + nx * w / 2.0, pt.y() + ny * w / 2.0))
        right.append(QPointF(pt.x() - nx * w / 2.0, pt.y() - ny * w / 2.0))
    path.moveTo(left[0])
    for p in left[1:]:
        path.lineTo(p)
    for p in reversed(right):
        path.lineTo(p)
    path.closeSubpath()
    return path


def letter_path(letter):
    """Full merged path of one letter in its canonical local box (centred near
    the origin, ~104px tall) — used for bounds and static rendering."""
    from PySide6.QtGui import QPainterPath
    from PySide6.QtCore import Qt
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for pts, w0, w1, wmid in _strokes_for(letter):
        path.addPath(brush_path(pts, w0, w1, wmid))
    return path


def letter_bounds(letter):
    """Natural bounding box of one letter (local canonical units)."""
    return letter_path(letter).boundingRect()


def draw_letter(painter, letter, reveal=1.0):
    """Draw one letter at the painter's current origin.

    ``reveal`` 0..1 progressively draws the strokes in hand order: the mark
    literally writes itself. The painter's brush supplies the colour; set
    ``NoPen`` before calling (fills only).
    """
    strokes = _strokes_for(letter)
    total = sum(len(s[0]) for s in strokes) or 1
    budget = max(0.0, min(1.0, reveal)) * total
    walked = 0
    for pts, w0, w1, wmid in strokes:
        seg = len(pts)
        local = max(0.0, min(1.0, (budget - walked) / seg))
        walked += seg
        if local <= 0.0:
            continue
        k = max(2, int(round(local * seg)))
        painter.fillPath(brush_path(pts[:k], w0, w1, wmid), painter.brush())


def monogram_layout(gap=12.0):
    """Layout for the paired "AC" mark in local units.

    Returns ``(height, total_width, cells)`` where ``cells`` maps "A"/"C" to
    ``(anchor_x, anchor_y, bbox_cx, bbox_cy)``: translate by
    ``(anchor_x - bbox_cx, anchor_y - bbox_cy)`` then :func:`draw_letter`.
    """
    ab, cb = letter_bounds("A"), letter_bounds("C")
    height = max(ab.height(), cb.height())
    w_a, w_c = ab.width(), cb.width()
    total = w_a + w_c + gap
    cells = {
        "A": (-total / 2.0 + w_a / 2.0, 0.0, ab.center().x(), ab.center().y()),
        "C": (total / 2.0 - w_c / 2.0, 0.0, cb.center().x(), cb.center().y()),
    }
    return height, total, cells
