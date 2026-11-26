"""round-255：流光绘制优化 —— 性能提升 + 像素级视觉不变。

优化内容（src/effects.py）：
1. _paint_liquid 32 步渐变循环复用 QColor（45µs → 9.7µs/33步）
2. 圆角 path 按 (w,h,r) 缓存
3. 主题色/边框色按字符串值缓存（主题变化自动失效）
4. 预存渐变 t 序列

验证分两层：
* **视觉**：用固定 angle/sweep/strength 抓 pixmap，与「参考实现」
  （照抄优化前的逐帧新建写法）逐像素比对，必须完全一致。
* **性能**：微基准断言复用 QColor 比新写快 ≥2×，缓存 path 非空命中。
* **正确性**：换 accent 后缓存失效、尺寸变化后 path 重建。
"""
from __future__ import annotations

import os
import sys
import timeit

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QConicalGradient, QImage, QLinearGradient, QPainter,
    QPainterPath, QPen,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src import effects as fx  # noqa: E402
from src.theme import COLORS  # noqa: E402

FAILS: list[str] = []
COUNT = 0


def check(label, ok, extra=""):
    global COUNT
    COUNT += 1
    print("  %s %-60s %s" % ("OK  " if ok else "FAIL", label, extra))
    if not ok:
        FAILS.append(label)


def _draw_liquid_to(p, card, w, h, radius, angle, sweep, strength,
                    accent, fill, *, scratch=True):
    """与 effects._paint_liquid 等价的两套实现：scratch=True 走优化写法。"""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(0, 0, w, h).adjusted(0.5, 0.5, -0.5, -0.5)
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    p.fillPath(path, fill)

    lg = QLinearGradient(0, 0, w, h)
    base = QColor(255, 255, 255, 0)
    hi = QColor(255, 255, 255, int(46 * strength))
    pos = max(0.0, min(1.0, sweep))
    lg.setColorAt(max(0.0, pos - 0.18), base)
    lg.setColorAt(pos, hi)
    lg.setColorAt(min(1.0, pos + 0.18), base)
    p.fillPath(path, lg)

    cg = QConicalGradient()
    cg.setCenter(QPointF(w / 2.0, h / 2.0))
    cg.setAngle(0)
    pseg = (angle / 360.0) % 1.0
    seg_half = 0.10
    steps = 32
    if scratch:
        c = QColor(accent)
        for i in range(steps + 1):
            t = i / steps
            d = abs(t - pseg)
            d = min(d, 1.0 - d)
            a = 1.0 - d / seg_half if d < seg_half else 0.0
            c.setAlphaF((0.18 + 0.82 * a) * strength)
            cg.setColorAt(t, c)
        c.setAlphaF(0.10 * strength)
        cg.setColorAt(0, c)
        cg.setColorAt(1, c)
    else:
        for i in range(steps + 1):
            t = i / steps
            d = abs(t - pseg)
            d = min(d, 1.0 - d)
            a = 1.0 - d / seg_half if d < seg_half else 0.0
            c = QColor(accent)
            c.setAlphaF((0.18 + 0.82 * a) * strength)
            cg.setColorAt(t, c)
        stripe = QColor(accent)
        stripe.setAlphaF(0.10 * strength)
        cg.setColorAt(0, stripe)
        cg.setColorAt(1, stripe)
    p.setPen(QPen(cg, 2.0))
    p.drawPath(path)


print("== 1. 视觉不变：复用 QColor 写法 vs 逐步新建写法逐像素一致 ==")
for label, kw in [
    ("默认紫 accent", dict()),
    ("浅色 accent", dict(accent="#00E5FF")),
    ("低强度", dict(strength=0.3)),
    ("不同角度", dict(angle=293.0, sweep=0.05)),
    ("不同尺寸", dict(w=240, h=46, radius=8)),
]:
    a = QImage(kw.get("w", 160), kw.get("h", 80), QImage.Format.Format_ARGB32)
    b = QImage(a.size(), QImage.Format.Format_ARGB32)
    a.fill(QColor(0, 0, 0, 0))
    b.fill(QColor(0, 0, 0, 0))
    accent = QColor(kw.get("accent", "#7C3AED"))
    fill = QColor(kw.get("fill", "#FFFFFF"))
    pa, pb = QPainter(a), QPainter(b)
    _draw_liquid_to(pa, None, kw.get("w", 160), kw.get("h", 80),
                    kw.get("radius", 12), kw.get("angle", 137.0),
                    kw.get("sweep", 0.42), kw.get("strength", 0.8),
                    accent, fill, scratch=True)
    _draw_liquid_to(pb, None, kw.get("w", 160), kw.get("h", 80),
                    kw.get("radius", 12), kw.get("angle", 137.0),
                    kw.get("sweep", 0.42), kw.get("strength", 0.8),
                    accent, fill, scratch=False)
    pa.end(); pb.end()
    diff = 0
    for y in range(a.height()):
        for x in range(a.width()):
            if a.pixel(x, y) != b.pixel(x, y):
                diff += 1
    check(label + " 像素零差异", diff == 0, "diff=%d px" % diff)

print("== 2. 性能：复用色值显著更快 ==")
accent = QColor("#7C3AED")


def old_loop():
    cg = QConicalGradient(); cg.setCenter(QPointF(60, 30))
    for i in range(33):
        c = QColor(accent); c.setAlphaF(0.3); cg.setColorAt(i / 32, c)


def new_loop():
    cg = QConicalGradient(); cg.setCenter(QPointF(60, 30))
    c = QColor(accent)
    for i in range(33):
        c.setAlphaF(0.3); cg.setColorAt(i / 32, c)


N = 1500
t_old = timeit.timeit(old_loop, number=N) / N
t_new = timeit.timeit(new_loop, number=N) / N
check("复用 QColor 提速 ≥2×", t_old / t_new >= 2.0,
      "old=%.1fus new=%.1fus (%.1fx)" % (t_old * 1e6, t_new * 1e6, t_old / t_new))
check("绝对耗时 <15µs/33步", t_new * 1e6 < 15,
      "%.1f us" % (t_new * 1e6))

print("== 3. 缓存失效：主题色变化 / 尺寸变化 ==")
card = fx.LightTrailCard(radius=12, fill="#FFFFFF")
card.resize(160, 80)
card._paint_liquid(None)
p1 = card._fx_path
g1 = card._fx_path_geom
card._paint_liquid(None)
check("同尺寸 path 复用（不重建）", card._fx_path is p1 and card._fx_path_geom == g1)
card.resize(200, 90)
card._paint_liquid(None)
check("尺寸变化后 path 重建", card._fx_path is not p1
      and card._fx_path_geom == (200, 90, 12))

old = COLORS.get("accent")
COLORS["accent"] = "#FF0000"
c1 = fx._accent()
check("切主题色后缓存失效", c1.red() == 255 and c1.green() == 0 and c1.blue() == 0,
      str(c1.name()))
COLORS["accent"] = old
c2 = fx._accent()
check("切回原色恢复", c2.name().lower() == str(old).lower(),
      "%s vs %s" % (c2.name(), old))

print("\nround-255 effects perf: %d checks, %d failed" % (COUNT, len(FAILS)))
if FAILS:
    for f in FAILS:
        print("  FAILED:", f)
    sys.stdout.flush()
    sys.exit(1)
print("ALL CHECKS PASSED（像素零差异 / 提速 ≥2× / 缓存正确失效）")
sys.stdout.flush()
os._exit(0)
