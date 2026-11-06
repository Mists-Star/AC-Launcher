"""启动后窗口行为回归（2026-11-06 真机诉求）。

事故：`close_after_launch` 默认 True → 游戏起来 5s 后 `_tray_auto_quit=True`
+ `close()` → `QApplication.quit()` 真退出。随主窗口销毁的还有
`_game_poll_timer`（`QTimer(self)`），于是退出码分类 / 崩溃弹窗 /
`last_session` 崩溃记录 / 退出后命令 / 控制台结束标记 / 托盘结束游戏
全部失效；玩家退出游戏后也找不到启动器。

新语义：启动后 hide 到托盘（无托盘则 showMinimized），进程常驻；
游戏退出时先恢复窗口再走崩溃诊断，最后常驻等待玩家操作。

判据分两层：
  1. 行为真相：用轻量 fake 直接调用未绑定方法，断言 hide/restore 被调用、
     close/quit 一次都没发生；
  2. 静态防再犯：源码里不得再出现 `_tray_auto_quit` / `self.close()`，
     恢复窗口必须排在 `_show_crash_dialog` 之前。
"""
import inspect
import io
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with io.open(os.path.join(HERE, rel), "r", encoding="utf-8") as fh:
        return fh.read()


from src.main_window import MainWindow  # noqa: E402
from src import i18n  # noqa: E402
from src.settings_dialog import _DEFAULTS  # noqa: E402


class _FakeWin:
    """够用的 MainWindow 替身：不构建任何 Qt 控件。"""

    def __init__(self, tray=True, auto_hidden=False):
        self._game_procs = {"demo": {"proc": object(), "name": "Demo"}}
        self._tray = object() if tray else None
        self._auto_hidden_for_game = auto_hidden
        self._game_poll_timer = _FakeTimer()
        self._game_proc = None
        self.console_page = None
        self.hidden = 0
        self.closed = 0
        self.minimized = 0
        self.notified = 0
        self.restored = 0
        self.showed = 0
        self.crash_dialogs = 0
        self.restore_before_crash = None
        self.msgs = []
        self.ui_running = []

    # Qt-ish surface
    def statusBar(self):
        return self

    def showMessage(self, *args):
        self.msgs.append(args)

    def hide(self):
        self.hidden += 1

    def close(self):
        self.closed += 1

    def showMinimized(self):
        self.minimized += 1

    def showNormal(self):
        self.minimized = 0

    def show(self):
        self.showed += 1

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def _tray_notify_hide(self):
        self.notified += 1

    def _tray_show(self, _page=""):
        self.restored += 1

    def _set_game_running_ui(self, running):
        self.ui_running.append(running)

    def _show_crash_dialog(self, *a, **kw):
        self.crash_dialogs += 1
        self.restore_before_crash = self.restored > 0


class _FakeTimer:
    def __init__(self):
        self.stopped = 0

    def stop(self):
        self.stopped += 1


class _ExitedProc:
    @staticmethod
    def poll():
        return 0


print("== 启动后窗口行为回归 ==")

# ── 1. 行为：启动后隐藏，绝不退出 ──────────────────────────────
w = _FakeWin(tray=True)
MainWindow._auto_close_if_game_running(w, "Demo")
check("有托盘 → hide() 且气泡提示", w.hidden == 1 and w.notified == 1,
      "hide=%d notify=%d" % (w.hidden, w.notified))
check("有托盘 → 绝不 close() / quit", w.closed == 0, "close=%d" % w.closed)
check("有托盘 → 置 _auto_hidden_for_game", w._auto_hidden_for_game is True)
check("状态栏提示用新文案 auto_minimize",
      bool(w.msgs) and "Demo" in str(w.msgs) and "托盘" in str(w.msgs))

w2 = _FakeWin(tray=False)
MainWindow._auto_close_if_game_running(w2, "Demo")
check("无托盘 → 退化为 showMinimized 且仍不 close",
      w2.minimized == 1 and w2.closed == 0,
      "min=%d close=%d" % (w2.minimized, w2.closed))

w3 = _FakeWin(tray=True)
w3._game_procs = {}
MainWindow._auto_close_if_game_running(w3, "Demo")
check("游戏已退出 → 不隐藏窗口（防把窗口藏掉）",
      w3.hidden == 0 and w3.closed == 0)

# ── 2. 行为：游戏退出时恢复窗口 ────────────────────────────────
p = _ExitedProc()
w4 = _FakeWin(tray=True, auto_hidden=True)
w4._game_procs = {"demo": {
    "proc": p, "name": "Demo", "log_path": "", "cwd": "", "exit_cmd": "",
}}
MainWindow._poll_game(w4)
check("游戏退出 → _tray_show() 恢复窗口", w4.restored == 1,
      "restored=%d" % w4.restored)
check("游戏退出 → 标志清零（防重复恢复）",
      w4._auto_hidden_for_game is False)
check("游戏退出 → 轮询停表 + 运行态复位",
      w4._game_poll_timer.stopped == 1 and w4.ui_running == [False],
      "stop=%d ui=%s" % (w4._game_poll_timer.stopped, w4.ui_running))

# ── 3. 静态防再犯 ──────────────────────────────────────────────
auto_src = inspect.getsource(MainWindow._auto_close_if_game_running)
maybe_src = inspect.getsource(MainWindow._maybe_auto_close_launcher)
poll_src = inspect.getsource(MainWindow._poll_game)
mw_src = read("src/main_window.py")
st_src = read("src/settings_dialog.py")

check("_auto_close_if_game_running 不再 self.close()",
      "self.close()" not in auto_src)
check("_auto_close_if_game_running 不再设 _tray_auto_quit",
      "_tray_auto_quit" not in auto_src)
check("隐藏路径含 hide() + 托盘气泡", "self.hide()" in auto_src
      and "_tray_notify_hide()" in auto_src)
check("不再为退出后命令单独跳过（常驻已覆盖）",
      "_game_exit_cmd" not in maybe_src)
check("恢复窗口逻辑写在崩溃弹窗之前",
      "_auto_hidden_for_game" in poll_src
      and "_show_crash_dialog" in poll_src
      and poll_src.index("_auto_hidden_for_game")
      < poll_src.index("self._show_crash_dialog("))
check("默认仍开启启动后自动隐藏（语义保留）",
      _DEFAULTS.get("close_after_launch") is True)
check("tray_minimize 的 UI 缺省与 _DEFAULTS 对齐",
      'self.cfg.get("tray_minimize", False)' in st_src
      and _DEFAULTS.get("tray_minimize") is False)

# ── 4. i18n 中英对齐 ───────────────────────────────────────────
# 语言键是 zh-CN / en-US；切完必须还原，避免污染同进程后续用例。
_prev_lang = i18n.get_language()
i18n.set_language("zh-CN")
zh_txt = i18n.t("status.auto_minimize", name="X")
i18n.set_language("en-US")
en_txt = i18n.t("status.auto_minimize", name="X")
i18n.set_language(_prev_lang)
check("status.auto_minimize 中英均有实文案且不同",
      bool(zh_txt) and bool(en_txt) and zh_txt != en_txt
      and "{" not in zh_txt and "{" not in en_txt,
      "zh=%r en=%r" % (zh_txt[:18], en_txt[:18]))
check("设置项文案不再宣称『自动关闭』",
      "自动关闭" not in read("src/i18n.py").split('"settings.close_after_launch":')[1][:60])

print("== %s ==" % ("PASS" if not fails else "FAIL %d" % len(fails)))
sys.exit(1 if fails else 0)
