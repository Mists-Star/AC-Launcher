"""round-223：第二轮解耦 / 功能查重（离线，零真实 HTTP / 零真窗口）。

本轮四处改动，全部是「同一件事写了好几遍」：

1. ``_loader_vivid`` —— 资源中心列表页与详情页各存一份逐字相同的实现
   （读主题包 ``loader_vivid`` 开关）。改口径只改一边就会「列表彩色、详情
   中性」。收归 ``theme.loader_vivid``，并加按 pack id 的记忆（此前每张徽章
   都要扫一次主题目录 + 解析全部 JSON）。
2. ``_on_close`` —— 4 个对话框壳各写一份 ``self.closed.emit()``。同步收进
   ``panel_shell.PanelShellMixin``（round-222 已把 ``__getattr__`` 等收进去）。
3. ``_center_on_screen`` —— splash / welcome 各一份。抽到
   ``win_geometry.center_on_screen``。
4. 「打开目录」—— 4 套实现、4 种体验：``instance_editor`` 建目录后打开、
   ``pages_instances`` **只在目录已存在时才动**（不存在时点按钮毫无反应）、
   ``mod_list`` 直接 startfile + warn。统一到 ``os_open.open_local_path``，
   目录缺失/系统拒绝都**明确提示**，不再静默吞掉。

判据全部是**行为断言**，不靠源码字面量（round-221 教训）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import theme                        # noqa: E402
from src import pages_instances, store_detail, instance_editor  # noqa: E402
from src import os_open, win_geometry        # noqa: E402
from src.panel_shell import PanelShellMixin  # noqa: E402
from src.i18n import t, set_language, _STRINGS  # noqa: E402

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── 1) theme.loader_vivid 是唯一实现 ──────────────────────────────────────
print("\n[1] loader_vivid single source")

check("列表页不再自带 _loader_vivid", not hasattr(pages_instances, "_loader_vivid"))
check("详情页不再自带 _loader_vivid", not hasattr(store_detail, "_loader_vivid"))
check("两处绑定的是同一个函数对象",
      pages_instances.loader_vivid is theme.loader_vivid
      and store_detail.loader_vivid is theme.loader_vivid)

_orig_find = theme.find_theme_pack
calls = {"n": 0}


def _fake_find(pid):
    calls["n"] += 1
    return {"id": pid, "loader_vivid": True}


theme.find_theme_pack = _fake_find
theme._VIVID_CACHE.clear()
theme._theme_pack_id = "pack-a"
try:
    check("主题包声明 loader_vivid → True", theme.loader_vivid() is True)
    n1 = calls["n"]
    theme.loader_vivid()
    theme.loader_vivid()
    check("同一主题包只解析一次（记忆生效）", calls["n"] == n1,
          "find 调用 %d 次" % calls["n"])
    check("列表页 / 详情页读到的值一致",
          pages_instances.loader_vivid() is True
          and store_detail.loader_vivid() is True)

    # 换主题包（apply_theme_pack）必须让记忆失效，否则开关要重启才生效
    theme.apply_theme_pack(None)
    check("apply_theme_pack 清掉记忆", not theme._VIVID_CACHE
          and theme.get_active_theme_pack_id() == "")

    theme._theme_pack_id = "pack-b"
    theme.find_theme_pack = lambda pid: {"id": pid}
    check("未声明 loader_vivid → False", theme.loader_vivid() is False)
finally:
    theme.find_theme_pack = _orig_find
    theme._VIVID_CACHE.clear()
    theme._theme_pack_id = ""


# ── 2) _on_close 收进 PanelShellMixin ─────────────────────────────────────
print("\n[2] PanelCloseMixin / PanelShellMixin._on_close")

from src.crash_dialog import CrashAnalyzerDialog, CrashAnalyzerPanel  # noqa: E402
from src.enhance_dialog import EnhanceDialog, EnhancePanel            # noqa: E402
from src.java_manager_dialog import JavaManagerDialog, JavaManagerPanel  # noqa: E402
from src.mod_check_dialog import HealthDialog, HealthPanel            # noqa: E402
from src.panel_shell import PanelCloseMixin                          # noqa: E402

_shells = (CrashAnalyzerDialog, EnhanceDialog, JavaManagerDialog, HealthDialog)
_panels = (CrashAnalyzerPanel, EnhancePanel, JavaManagerPanel, HealthPanel)
check("四个壳都继承 PanelShellMixin",
      all(issubclass(c, PanelShellMixin) for c in _shells))
check("四个面板都继承 PanelCloseMixin（_on_close 属于面板，不属于壳）",
      all(issubclass(c, PanelCloseMixin) for c in _panels))
check("四个壳自身都不再写 _on_close",
      all("_on_close" not in c.__dict__ for c in _shells),
      ",".join(c.__name__ for c in _shells if "_on_close" in c.__dict__))
check("四个面板自身也不写 _on_close（只有一份实现）",
      all("_on_close" not in c.__dict__ for c in _panels),
      ",".join(c.__name__ for c in _panels if "_on_close" in c.__dict__))


class _Sig:
    def __init__(self):
        self.n = 0

    def emit(self):
        self.n += 1


class _Panel(PanelCloseMixin):
    def __init__(self):
        self.closed = _Sig()


class _Shell(PanelShellMixin):
    def __init__(self, panel):
        self.panel = panel


_p = _Panel()
_p._on_close()
check("面板自己就能 _on_close（页内模式的调用方是面板）", _p.closed.n == 1,
      "emit=%d" % _p.closed.n)

_p2 = _Panel()


class _Shell2(PanelShellMixin):
    def __init__(self, panel):
        self.panel = panel


_s = _Shell2(_p2)
_s._on_close()
check("壳上 _on_close 经 __getattr__/.closed 落到面板且只发一次",
      _p2.closed.n == 1, "emit=%d" % _p2.closed.n)
_s._on_close()
check("再点一次再发一次（不是幂等哨兵）", _p2.closed.n == 2)


# ── 2b) 窗口模式弹窗不是空白（P1，round-223 目视巡检抓到） ────────────────
print("\n[2b] window-mode dialogs are not blank")

from PySide6.QtWidgets import QApplication          # noqa: E402
from src.frameless import enable_panel_window_chrome  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeInst:
    name = "1.21.4 Fabric"
    version_id = "1.21.4-fabric"
    game_version = "1.21.4"
    loader = "fabric"
    mc_dir = HERE
    game_dir = HERE
    mods_dir = HERE


def _colors(widget):
    img = widget.grab().toImage().scaled(48, 36)
    seen = set()
    for y in range(36):
        for x in range(48):
            c = img.pixelColor(x, y)
            seen.add((c.red(), c.green(), c.blue()))
    return len(seen)


_dlg = HealthDialog(_FakeInst(), {})
_dlg.show()
for _ in range(6):
    _app.processEvents()
check("体检弹窗：面板没被 Qt.Window 顶出父窗口（否则整窗空白）",
      _dlg.panel.isWindow() is False, "isWindow=%s" % _dlg.panel.isWindow())
check("体检弹窗：面板真的在显示", _dlg.panel.isVisible())
check("体检弹窗：抓图里有真实内容（不是一整片纯色）", _colors(_dlg) > 1,
      "%d 种颜色" % _colors(_dlg))
_dlg.close()

# 同一功能挂在独立窗口上时仍作用在自己（页面不外挂壳的那种用法）
from PySide6.QtCore import Qt                        # noqa: E402
from PySide6.QtWidgets import QWidget                 # noqa: E402

_alone = QWidget()
_alone.show()
_app.processEvents()
enable_panel_window_chrome(_alone)
check("独立面板（自己就是窗口）：frameless 挂在自己身上",
      _alone.isWindow() and bool(_alone.windowFlags() & Qt.FramelessWindowHint))
_alone.close()


# ── 3) center_on_screen 共用 ─────────────────────────────────────────────
print("\n[3] center_on_screen shared")

from src.splash_window import SplashWindow            # noqa: E402
from src.welcome_window import WelcomeWindow          # noqa: E402
import src.splash_window as _splash_mod                # noqa: E402
import src.welcome_window as _welcome_mod              # noqa: E402

check("SplashWindow 不再自带 _center_on_screen",
      not hasattr(SplashWindow, "_center_on_screen"))
check("WelcomeWindow 不再自带 _center_on_screen",
      not hasattr(WelcomeWindow, "_center_on_screen"))
check("两个启动窗都用同一个函数",
      _splash_mod.center_on_screen is win_geometry.center_on_screen
      and _welcome_mod.center_on_screen is win_geometry.center_on_screen)


class _Area:
    def x(self):
        return 0

    def y(self):
        return 0

    def width(self):
        return 1920

    def height(self):
        return 1080


class _Screen:
    def availableGeometry(self):
        return _Area()


class _W:
    def __init__(self, w, h, screen=True):
        self._w, self._h = w, h
        self._screen = _Screen() if screen else None
        self.pos = None

    def screen(self):
        return self._screen

    def width(self):
        return self._w

    def height(self):
        return self._h

    def move(self, x, y):
        self.pos = (x, y)


w = _W(480, 320)
win_geometry.center_on_screen(w)
check("按可用区域居中（扣任务栏后的矩形）", w.pos == ((1920 - 480) // 2, (1080 - 320) // 2),
      str(w.pos))

w2 = _W(480, 320, screen=False)
win_geometry.center_on_screen(w2)
check("无屏幕时不移动也不抛", w2.pos is None)


# ── 4) 打开目录统一实现 ────────────────────────────────────────────────────
print("\n[4] open_local_path")

notes = []
_orig_notify = os_open._notify
os_open._notify = lambda parent, msg: notes.append(msg)

_orig_startfile = getattr(os, "startfile", None)
started = []
try:
    if _orig_startfile is None:  # 非 Windows：走 subprocess 分支
        class _Popen:
            def __init__(self, *a, **k):
                started.append(a[0] if a else None)
        _orig_popen = os_open.subprocess.Popen
        os_open.subprocess.Popen = _Popen
    else:
        os.startfile = lambda p: started.append(p)

    check("空路径：直接 False 且不弹框",
          os_open.open_local_path(None, "") is False and not notes)

    notes.clear()
    missing = os.path.join(HERE, "_scratch", "no_such_dir_223")
    check("目录不存在：False + 明确提示（旧实现是静默无反应）",
          os_open.open_local_path(None, missing) is False and len(notes) == 1,
          notes[0] if notes else "")

    notes.clear()
    made = os.path.join(HERE, "_scratch", "round223_made")
    ok = os_open.open_local_path(None, made, create=True)
    check("create=True 会先建目录再打开",
          ok is True and os.path.isdir(made) and started, str(started[-1:] if started else []))

    notes.clear()
    if _orig_startfile is not None:
        os.startfile = lambda p: (_ for _ in ()).throw(OSError("denied"))
    else:
        os_open.subprocess.Popen = lambda *a, **k: (_ for _ in ()).throw(OSError("denied"))
    check("系统拒绝打开：False + 提示带原因",
          os_open.open_local_path(None, HERE) is False
          and len(notes) == 1 and "denied" in notes[0], notes[0] if notes else "")
finally:
    if _orig_startfile is not None:
        os.startfile = _orig_startfile
    else:
        os_open.subprocess.Popen = _orig_popen
    os_open._notify = _orig_notify
    try:
        if os.path.isdir(made):
            os.rmdir(made)
    except OSError:
        pass


# ── 5) 三个调用点都改成走统一实现 ─────────────────────────────────────────
print("\n[5] call sites routed through os_open")

calls = []
_orig_pi = pages_instances.open_local_path
_orig_ml = None
pages_instances.open_local_path = lambda parent, path, **kw: calls.append((path, kw))


class _Inst:
    mc_dir = os.path.join(HERE, "src")
    game_dir = os.path.join(HERE, "src")
    mods_dir = os.path.join(HERE, "src")


try:
    pages_instances.InstancesPage._open_folder(object(), _Inst())
    pages_instances.InstancesPage._open_saves(object(), _Inst())
    check("实例页「打开目录 / 打开存档」都走统一实现",
          len(calls) == 2 and calls[0][1].get("create") is not True
          and calls[1][1].get("create") is True, str(calls))
    check("打开存档指向 <game_dir>/saves",
          calls[1][0] == os.path.join(_Inst.game_dir, "saves"), calls[1][0])
finally:
    pages_instances.open_local_path = _orig_pi

import src.mod_list as _mod_list                       # noqa: E402
_orig_ml = _mod_list.open_local_path
_ml_calls = []
_mod_list.open_local_path = lambda parent, path, **kw: _ml_calls.append((path, kw))


class _ML:
    _on_open_folder = None
    _inst = _Inst()


try:
    _mod_list.ModListPanel._open_folder(_ML())
    check("模组列表「打开目录」走统一实现且 create=True",
          len(_ml_calls) == 1 and _ml_calls[0][1].get("create") is True,
          str(_ml_calls))
finally:
    _mod_list.open_local_path = _orig_ml

check("instance_editor._reveal_path 死代码已删",
      not hasattr(instance_editor, "_reveal_path"))


# ── 6) 新增 i18n 键中英对称 ───────────────────────────────────────────────
print("\n[6] i18n new keys")

for key in ("common.open_missing", "common.open_failed"):
    check("中英文都有 %s" % key,
          key in _STRINGS["zh-CN"] and key in _STRINGS["en-US"])

try:
    set_language("zh-CN")
    zh = t("common.open_missing", path="C:/x")
    set_language("en-US")
    en = t("common.open_missing", path="C:/x")
    check("占位符两边都能填", "C:/x" in zh and "C:/x" in en, "%s | %s" % (zh, en))
finally:
    set_language("zh-CN")

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-223 第二轮解耦 / 查重）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-223 第二轮解耦 / 查重）")
