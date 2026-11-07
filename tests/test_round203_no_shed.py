"""round-203 回归：启动游戏不再关壁纸 + 下载解耦（全局闸门 / 安装设置线程局部）。

Qt offscreen；只验证状态与静态契约，不渲染真实帧、不联网：
1. `WallpaperWidget.set_game_running(True)` 只暂停播放，**保留**大图与可见性；
   期间 `apply()` 仍能正常上屏；`False` 恢复播放。
2. `_set_game_running_ui` 源码不再调用 `backdrop.suspend()`。
3. `mirror` 的镜像 / 代理设置按安装线程隔离：两个线程各设各的，互不覆盖。
4. `dl_gate` 单飞：同 key 第二次 claim 失败，release 后成功；
   `wait_free` 能等到释放并接手；超时返回 False 且不占用。
"""
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QPixmap, QColor  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.wallpaper import WallpaperWidget  # noqa: E402
from src.core import dl_gate, mirror  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def _src_slice(path, start_marker):
    """取源码里从 start_marker 到下一个顶层 def 的片段（静态契约检查用）。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    i = text.find(start_marker)
    if i < 0:
        return ""
    j = text.find("\n    def ", i + len(start_marker))
    return text[i:j if j > 0 else len(text)]


# ── 1. 游戏运行不关壁纸 ──
TMP = tempfile.mkdtemp(prefix="_r203_")
IMG = os.path.join(TMP, "wall.png")
pm = QPixmap(64, 36)
pm.fill(QColor("#2F6F4F"))
pm.save(IMG, "PNG")

w = WallpaperWidget()
cfg = {"wallpaper_mode": "image", "wallpaper_image": IMG,
       "wallpaper_opacity": 1.0, "wallpaper_color": "#1E1E1E"}
w.apply(cfg)
check("初始加载大图", w._pixmap is not None and not w._pixmap.isNull())

w.set_game_running(True)
check("运行中壁纸不被丢弃", w._pixmap is not None and not w._pixmap.isNull())
check("运行中壁纸层仍可见", w.isVisible())
check("运行中进入暂停播放态", getattr(w, "_game_paused", False))

w.apply(cfg)
check("运行中 apply 仍正常（不因降载跳过）",
      w._pixmap is not None and not w._pixmap.isNull())

w.set_game_running(False)
check("退出游戏清暂停态", not getattr(w, "_game_paused", True))
check("退出后大图仍在", w._pixmap is not None and not w._pixmap.isNull())
w.deleteLater()

# ── 2. 主窗启动路径不再 suspend ──
snip = _src_slice(os.path.join(HERE, "src", "main_window.py"),
                  "def _set_game_running_ui")
check("_set_game_running_ui 已找到", bool(snip))
check("不再调用 backdrop.suspend()", "backdrop.suspend()" not in snip)
check("改为只暂停播放（set_game_running）",
      "backdrop.set_game_running" in snip)

# ── 3. 镜像 / 代理按安装线程隔离 ──
mirror.set_mirror(False)
out = {}


def _inst_a():
    with mirror.install_scope() as ctx:
        mirror.set_mirror(True)
        mirror.set_proxy("http://a")
        out["a"] = (mirror._mirror_on_for(ctx), mirror._proxy_for(ctx))


def _inst_b():
    with mirror.install_scope() as ctx:
        mirror.set_mirror(False)
        out["b"] = (mirror._mirror_on_for(ctx), mirror._proxy_for(ctx))


ta = threading.Thread(target=_inst_a)
tb = threading.Thread(target=_inst_b)
ta.start(); tb.start(); ta.join(); tb.join()
check("安装 A 的镜像开关不串给 B", out["a"][0] is True and out["b"][0] is False,
      str(out))
check("安装 A 的代理不串给 B", out["a"][1] == "http://a" and out["b"][1] is None,
      str(out))
check("线程外仍用进程级默认（镜像关）", mirror._mirror_on_for() is False)

# ── 4. 下载闸门 ──
dl_gate.reset_for_tests()
k = dl_gate.inst_key(os.path.join(TMP, "inst"))
check("首次 claim 成功", dl_gate.claim(k))
check("同 key 二次 claim 失败", not dl_gate.claim(k))
check("is_active 能看到", dl_gate.is_active(k))
dl_gate.release(k)
check("释放后可再 claim", dl_gate.claim(k))
dl_gate.release(k)

# wait_free：另一线程占用 → 等待 → 释放后被接手
k2 = dl_gate.file_key(os.path.join(TMP, "a.jar"))
dl_gate.claim(k2)
got = {}
t = threading.Thread(
    target=lambda: got.setdefault("ok", dl_gate.wait_free(k2, timeout=3.0)))
t.start()


def _free():
    import time
    time.sleep(0.4)
    dl_gate.release(k2)


threading.Thread(target=_free).start()
t.join()
check("wait_free 等到释放并接手", bool(got.get("ok")))
dl_gate.release(k2)

# 超时：不占用、返回 False
k3 = "store:x:y"
dl_gate.claim(k3)
check("wait_free 超时返回 False", not dl_gate.wait_free(k3, timeout=0.2))
check("超时不占用（仍归原持有者）", dl_gate.is_active(k3))
dl_gate.release(k3)

# ── 5. 商店下载单飞（静态契约）──
snip2 = _src_slice(os.path.join(HERE, "src", "store_detail.py"),
                   "def _download_version")
check("_download_version 已接入 dl_gate",
      "dl_gate import" in snip2 and "_dl_gate_keys.add" in snip2)

print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ALL PASS")
