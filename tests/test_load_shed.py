"""round-156 回归测试：启动即降载（装饰动画暂停 + 壁纸缓存释放）。

Qt offscreen；验证的是状态迁移，不渲染真实帧：
1. `effects.set_game_running` 置位/复位：游戏运行中主表停摆，但可见卡片
   仍保留登记（round-202：退出后无需再切页即可自动恢复动画）；
2. `WallpaperWidget.suspend()` 丢弃大图/缩放缓存并隐藏，游戏运行中
   `apply()` 不重新加载；`resume()` + `apply()` 能恢复原图。
"""
import os
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QPixmap, QColor  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tmp_img(qapp):
    TMP = tempfile.mkdtemp(prefix="_shed_")
    IMG = os.path.join(TMP, "wall.png")
    pm = QPixmap(64, 36)
    pm.fill(QColor("#2F6F4F"))
    pm.save(IMG, "PNG")
    yield IMG
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)


def test_game_running_pause(qapp):
    """1. 装饰动画随游戏运行暂停"""
    from src import effects  # noqa: E402

    effects.set_game_running(True)
    assert effects.GAME_RUNNING
    assert effects._MASTER is None or not effects._MASTER.isActive()

    card = effects.LightTrailCard()
    card.show()
    assert effects._MASTER is None or not effects._MASTER.isActive()
    assert card in effects._ACTIVE_CARDS

    effects.set_game_running(False)
    assert not effects.GAME_RUNNING
    assert effects._MASTER is not None and effects._MASTER.isActive()

    card.hide()
    effects._stop_master()
    card.deleteLater()


def test_wallpaper_suspend_resume(qapp, tmp_img):
    """2. 壁纸降载 / 恢复"""
    from src.wallpaper import WallpaperWidget  # noqa: E402

    w = WallpaperWidget()
    cfg = {"wallpaper_mode": "image", "wallpaper_image": tmp_img,
           "wallpaper_opacity": 1.0, "wallpaper_color": "#1E1E1E"}
    w.apply(cfg)
    assert w._pixmap is not None and not w._pixmap.isNull()

    w.suspend()
    assert w._pixmap is None and w._scaled is None and w._pano_buffer is None
    assert w._suspended and not w.isVisible()
    assert w._pano_timer is None or not w._pano_timer.isActive()

    w.apply(cfg)
    assert w._pixmap is None and w._suspended

    w.resume()
    assert not w._suspended
    w.apply(cfg)
    assert w._pixmap is not None and not w._pixmap.isNull() and w.isVisible()

    # 非图片模式：版本全景被 suspend 丢弃后，恢复走 apply 重新请求
    w.apply({"wallpaper_mode": "none"})
    assert not w.isVisible() and w._pixmap is None
    w.deleteLater()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])