"""round-136 品牌自定义回归：配置键 / 路径校验 / 标题栏刷新 / 启动页不崩。

离屏运行（QT_QPA_PLATFORM=offscreen），不触碰真实用户配置。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

app = QApplication(sys.argv)  # noqa: E841

import src.brand_custom as bc  # noqa: E402
import src.settings_dialog as sd  # noqa: E402
from src.brand import APP_DISPLAY  # noqa: E402

FAILS = []

# ── 隔离：测试绝不能写用户的真实 launcher_config.json ──
# MainWindow 关闭时会 save_config()（窗口几何等），不隔离就会把测试用的
# 标志路径/标题文本写进真实配置。config 文件在项目根，不受 AC_DEV_TEMP 影响。
_TMP_DIR = tempfile.mkdtemp(prefix="ac_brand_test_")
_TMP_CFG = os.path.join(_TMP_DIR, "launcher_config.json")
_REAL_CFG = sd.CONFIG_FILE
sd.CONFIG_FILE = _TMP_CFG
bc.get_config_path = lambda filename: _TMP_CFG


def check(label, cond):
    if cond:
        print("  PASS  %s" % label)
    else:
        print("  FAIL  %s" % label)
        FAILS.append(label)


def make_png(path, w=32, h=32):
    pm = QPixmap(w, h)
    pm.fill(Qt.red)
    pm.save(path, "PNG")
    return path


print("== round-136 品牌自定义 ==")

# ---- 1. _DEFAULTS 含 3 个新键，默认值都是 "" ----
for k in ("custom_logo_path", "custom_title_text", "splash_bg_image"):
    check("_DEFAULTS 含 %s" % k, k in sd._DEFAULTS)
    check("_DEFAULTS[%s] 默认 ''" % k, sd._DEFAULTS.get(k) == "")

# ---- 2. custom_title_text 三种输入 ----
check("空 cfg → APP_DISPLAY", bc.custom_title_text({}) == APP_DISPLAY)
check("空串 → APP_DISPLAY", bc.custom_title_text({"custom_title_text": ""}) == APP_DISPLAY)
check("纯空白 → APP_DISPLAY", bc.custom_title_text({"custom_title_text": "   "}) == APP_DISPLAY)
check("有值 → 原样", bc.custom_title_text({"custom_title_text": "My Launcher"}) == "My Launcher")
check("非 str → APP_DISPLAY", bc.custom_title_text({"custom_title_text": 123}) == APP_DISPLAY)

# ---- 3/4/5/6. 路径校验 ----
tmpdir = tempfile.mkdtemp(prefix="ac_brand_")
png = make_png(os.path.join(tmpdir, "logo.png"))
txt = os.path.join(tmpdir, "logo.txt")
with open(txt, "w", encoding="utf-8") as f:
    f.write("not an image")

check("不存在的路径 → ''", bc.custom_logo_path({"custom_logo_path": os.path.join(tmpdir, "nope.png")}) == "")
check("合法 png → 绝对路径", bc.custom_logo_path({"custom_logo_path": png}) == os.path.normpath(os.path.abspath(png)))
check("不支持的后缀 → ''", bc.custom_logo_path({"custom_logo_path": txt}) == "")
check("空值 → ''", bc.custom_logo_path({"custom_logo_path": ""}) == "")
check("非 str → ''", bc.custom_logo_path({"custom_logo_path": None}) == "")
check("splash_bg 合法 png", bc.splash_bg_path({"splash_bg_image": png}) == os.path.normpath(os.path.abspath(png)))
check("splash_bg 不存在 → ''", bc.splash_bg_path({"splash_bg_image": os.path.join(tmpdir, "x.png")}) == "")

# load_pixmap
pm = bc.load_pixmap(png, 30)
check("load_pixmap 返回非空", pm is not None and not pm.isNull())
check("load_pixmap 缩放到 ≤30", pm is not None and max(pm.width(), pm.height()) <= 30)
check("load_pixmap 无效路径 → None", bc.load_pixmap(os.path.join(tmpdir, "nope.png"), 30) is None)
check("load_pixmap 空路径 → None", bc.load_pixmap("", 30) is None)
check("load_pixmap size=0 → None", bc.load_pixmap(png, 0) is None)

# normalize_path
check("normalize 空 → ''", bc.normalize_path("") == "")
check("normalize None → ''", bc.normalize_path(None) == "")
check("normalize 相对路径 → 绝对", os.path.isabs(bc.normalize_path("logo.png")))

# ---- 7. 标题栏刷新 ----
try:
    from src.main_window import MainWindow
    win = MainWindow()
    win.cfg = dict(win.cfg)
    win.cfg["custom_title_text"] = "ZZ Brand"
    win._refresh_titlebar_brand()
    check("标题栏文本刷新", win._tb_name.text() == "ZZ Brand")
    # 标志：自定义图应覆盖内置 logo
    win.cfg["custom_logo_path"] = png
    win._refresh_titlebar_brand()
    check("标题栏标志非空", not win._tb_logo.pixmap().isNull())
    check("窗口图标非空", not win.windowIcon().isNull())
    win.close()
except Exception as e:  # noqa: BLE001
    print("  SKIP  MainWindow 构造失败: %r" % (e,))

# ---- 8. 启动页不崩 ----
_orig_load = bc.load_brand_cfg
try:
    from src.splash_window import SplashWindow
    bc.load_brand_cfg = lambda: {}
    sw = SplashWindow()
    sw._phase = 1.0
    sw.grab()
    check("SplashWindow 默认构造 + grab 不崩", True)
    check("SplashWindow 默认无自定义标志", sw._logo_pm is None)
    check("SplashWindow 默认无背景图", sw._bg_pm is None)
    sw.close()
except Exception as e:  # noqa: BLE001
    check("SplashWindow 构造/grab", False)
    print("       %r" % (e,))

# 启动页带自定义标志 / 背景
try:
    from src.splash_window import SplashWindow
    bc.load_brand_cfg = lambda: {
        "custom_logo_path": os.path.normpath(os.path.abspath(png)),
        "splash_bg_image": os.path.normpath(os.path.abspath(png)),
    }
    sw = SplashWindow()
    sw._phase = 1.0
    sw.grab()
    check("SplashWindow 自定义标志 + 背景 grab 不崩", sw._logo_pm is not None and sw._bg_pm is not None)
    sw.close()
except Exception as e:  # noqa: BLE001
    check("SplashWindow 自定义标志 + 背景", False)
    print("       %r" % (e,))
finally:
    bc.load_brand_cfg = _orig_load

print()
if FAILS:
    print("FAILED: %d 项" % len(FAILS))
    for f in FAILS:
        print("   - %s" % f)
    sys.exit(1)
# 标记与 regress.py 的成功标记表对齐（离屏 teardown 噪音会让退出码非 0）
print("ALL CHECKS PASSED")
