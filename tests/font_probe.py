"""探测：离屏模式下中文字到底能不能渲染（审计用，不入库）。

如果 QFontDatabase 里能列出中文字体、且截图像素非空白，
说明「离屏必 tofu」是**字体没加载**导致的，可以修好 —— 那我就能自己看截图做视觉验收。
"""
import os
import sys

# tests/ 下运行：仓库根 = tests 的上一级
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout  # noqa: E402
from PySide6.QtGui import QFontDatabase, QFont  # noqa: E402

app = QApplication(sys.argv)

fdb = QFontDatabase()
families = fdb.families()
cn = [f for f in families if any(c in f for c in ("Microsoft", "SimSun", "YaHei",
                                                  "黑体", "宋体", "Noto", "DengXian",
                                                  "KaiTi", "FangSong"))]
print("字体总数:", len(families))
print("中文字体候选:", cn[:12])
print()

w = QWidget()
w.resize(520, 200)
lay = QVBoxLayout(w)
lay.addWidget(QLabel("默认字体：AC Launcher 启动器 中文测试 123"))
l2 = QLabel("微软雅黑：AC Launcher 启动器 中文测试 123")
l2.setFont(QFont("Microsoft YaHei", 14))
lay.addWidget(l2)
l3 = QLabel("SimHei：AC Launcher 启动器 中文测试 123")
l3.setFont(QFont("SimHei", 14))
lay.addWidget(l3)
w.show()
app.processEvents()

out = os.path.join(HERE, "_font_probe.png")
pm = w.grab()
pm.save(out)
print("截图:", out, pm.width(), "x", pm.height())

# 统计非背景像素，判断是否真的画出了东西
img = pm.toImage()
w_, h_ = img.width(), img.height()
dark = 0
for y in range(0, h_, 2):
    for x in range(0, w_, 2):
        c = img.pixelColor(x, y)
        if c.red() < 200 or c.green() < 200 or c.blue() < 200:
            dark += 1
print("非空白像素采样数:", dark, "(0 = 什么都没画出来)")
