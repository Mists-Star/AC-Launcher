"""round-156 回归测试：启动即降载（装饰动画暂停 + 壁纸缓存释放）。

Qt offscreen；验证的是状态迁移，不渲染真实帧：
1. `effects.set_game_running` 置位/复位，游戏运行中流光卡不再注册主表；
2. `WallpaperWidget.suspend()` 丢弃大图/缩放缓存并隐藏，游戏运行中
   `apply()` 不重新加载；`resume()` + `apply()` 能恢复原图。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QPixmap, QColor  # noqa: E402

app = QApplication.instance() or QApplication([])

from src import effects  # noqa: E402
from src.wallpaper import WallpaperWidget  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── 1. 装饰动画随游戏运行暂停 ──
effects.set_game_running(True)
check("游戏运行 → GAME_RUNNING=True", effects.GAME_RUNNING)
check("无卡时主表不启动",
      effects._MASTER is None or not effects._MASTER.isActive())

card = effects.LightTrailCard()
card.show()
check("游戏运行中不注册流光卡", card not in effects._ACTIVE_CARDS)
effects.set_game_running(False)
check("游戏退出 → GAME_RUNNING=False", not effects.GAME_RUNNING)
card.hide()
card.show()
check("退出后恢复注册", card in effects._ACTIVE_CARDS)
card.hide()
effects._stop_master()
card.deleteLater()

# ── 2. 壁纸降载 / 恢复 ──
TMP = tempfile.mkdtemp(prefix="_shed_")
IMG = os.path.join(TMP, "wall.png")
pm = QPixmap(64, 36)
pm.fill(QColor("#2F6F4F"))
pm.save(IMG, "PNG")

w = WallpaperWidget()
cfg = {"wallpaper_mode": "image", "wallpaper_image": IMG,
       "wallpaper_opacity": 1.0, "wallpaper_color": "#1E1E1E"}
w.apply(cfg)
check("初始加载大图", w._pixmap is not None and not w._pixmap.isNull())

w.suspend()
check("suspend 丢弃大图/缩放缓存",
      w._pixmap is None and w._scaled is None and w._pano_buffer is None)
check("suspend 隐藏并置位", w._suspended and not w.isVisible())
check("暂停期间 panorama 也停表",
      w._pano_timer is None or not w._pano_timer.isActive())

w.apply(cfg)
check("游戏运行中 apply 不重新加载",
      w._pixmap is None and w._suspended)

w.resume()
check("resume 清除降载标记", not w._suspended)
w.apply(cfg)
check("恢复后重新上屏大图",
      w._pixmap is not None and not w._pixmap.isNull() and w.isVisible())

# 非图片模式：版本全景被 suspend 丢弃后，恢复走 apply 重新请求
w.apply({"wallpaper_mode": "none"})
check("切回无壁纸 → 隐藏", not w.isVisible() and w._pixmap is None)
w.deleteLater()

print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ALL PASS")
