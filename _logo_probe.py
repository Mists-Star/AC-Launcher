"""_ logo 居中实测（诊断脚本，不入库）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QPainter, QFont  # noqa: E402

app = QApplication(sys.argv)

from src.welcome_window import WelcomeWindow, _MC_FONT_PIXEL  # noqa: E402

w = WelcomeWindow()
w.resize(320, 200)
w.show()
app.processEvents()

# 测量：把 bbox 与窗口矩形对比
QTimer.singleShot(1600, app.quit)
app.exec()


def measure():
    from PySide6.QtGui import QFontMetrics
    p = QPainter(w)
    family = w._mc_font_family or w._font_family
    font = QFont(family)
    font.setPixelSize(max(24, int(_MC_FONT_PIXEL)))
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -14)
    p.setFont(font)
    fm = p.fontMetrics()
    adv = fm.horizontalAdvance("AC")
    br = fm.boundingRect("AC")
    tb = fm.tightBoundingRect("AC")
    print(f"font={family[:24]!r} pixelSize={_MC_FONT_PIXEL}")
    print(f"horizontalAdvance('AC') = {adv}")
    print(f"fontMetrics.boundingRect = {br}")
    print(f"tightBoundingRect       = {tb}")
    print(f"ascent={fm.ascent()} descent={fm.descent()} height={fm.height()}")
    r = w.rect()
    print(f"window rect = {r}")
    pm2 = w._render_ac_pixmap()
    print(f"墨迹 pixmap 尺寸 = {pm2.width()}x{pm2.height()}")
    cx = r.center().x()
    print(f"按墨迹居中: 文本范围 [{cx - pm2.width()/2}, {cx + pm2.width()/2}] 中心={cx} == 窗口中心 {cx} => 偏 0px")
    p.end()
    pm = w.grab()
    os.makedirs("_shots", exist_ok=True)
    pm.save("_shots/logo.png")
    print("SHOT _shots/logo.png", pm.width(), "x", pm.height())


measure()
