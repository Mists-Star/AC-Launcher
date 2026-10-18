"""round-112 视觉自验收 v2：覆盖全部 11 个 stack 页面（审计用，不入库）。

侧栏只有 6 项（round-107 精简），music/achievements/console/mods/versions/
toolbox 这些页面从 STACK_INDEX 直接切（_ensure_page 负责懒构建）。
"""
import os
import sys

# tests/ 下运行：仓库根 = tests 的上一级
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"

OUT = os.path.join(HERE, "_shots_r112")
os.makedirs(OUT, exist_ok=True)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import src.settings_dialog as sd  # noqa: E402
sd.load_config = lambda *a, **k: dict(sd._DEFAULTS)
sd.save_config = lambda *a, **k: None

from src.main_window import MainWindow, STACK_INDEX  # noqa: E402

win = MainWindow()
win.resize(1280, 800)
win.show()
app.processEvents()


def shot(name):
    app.processEvents()
    pm = win.grab()
    path = os.path.join(OUT, name + ".png")
    pm.save(path)
    print("shot %-16s %dx%d %6.1fKB" % (name, pm.width(), pm.height(),
                                        os.path.getsize(path) / 1024))
    sys.stdout.flush()


# 1) 侧栏真实页面（走正常导航，连带 nav 高亮）
for key in ["home", "instances", "store", "settings"]:
    try:
        win._on_nav(win._nav_row(key))
        app.processEvents()
        shot("nav-" + key)
    except Exception as e:  # noqa: BLE001
        print("nav %s FAIL: %r" % (key, e))
        sys.stdout.flush()

# 2) 隐藏页面（STACK_INDEX 直切 + 懒构建）
for key, idx in STACK_INDEX.items():
    if key in ("home", "instances", "store", "settings"):
        continue
    try:
        win._ensure_page(idx)
        win.stack.setCurrentIndex(idx)
        app.processEvents()
        shot("page-" + key)
    except Exception as e:  # noqa: BLE001
        print("page %s FAIL: %r" % (key, e))
        sys.stdout.flush()

win.close()
print("DONE ->", OUT)
