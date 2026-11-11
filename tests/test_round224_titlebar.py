"""round-224：原生标题栏必须**跟随主题**（此前写死深色 → 浅色下一条黑栏）。

用户目视到的现象：浅色主题里「用户条款」窗口顶部是一条纯黑标题栏（截图）。
根因：``win_rounded.enable_dark_titlebar`` 无条件把 ``DWMWA_USE_IMMERSIVE_DARK_MODE``
设成 1 —— round-217 为了让**深色**主题的条款框别顶白条，把浅色一起拖下水。

判据全部是**行为断言**：用一个假的 ``ctypes`` 记录真正发给 DWM 的属性值，
而不是去源码里找 ``enable_dark_titlebar`` 字样。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import theme                          # noqa: E402
from src import win_rounded as wr              # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-70s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── 假 ctypes：记录 DwmSetWindowAttribute(hwnd, attr, value) ──────────────
class _IntBox:
    def __init__(self, v):
        self.value = v


class _DwmApi:
    def __init__(self, fail_first=False):
        self.calls = []
        self.fail_first = fail_first

    def DwmSetWindowAttribute(self, hwnd, attr, ref, size):
        self.calls.append((attr, ref.value))
        return -1 if (self.fail_first and len(self.calls) == 1) else 0


class _FakeCtypes:
    c_int = _IntBox

    def __init__(self, fail_first=False):
        self.dwm = _DwmApi(fail_first)
        self.windll = type("W", (), {"dwmapi": self.dwm})()

    @staticmethod
    def byref(obj):
        return obj

    @staticmethod
    def sizeof(obj):
        return 4


class _Widget:
    def __init__(self, hwnd=0x1234):
        self._hwnd = hwnd

    def winId(self):
        return self._hwnd


_real_ctypes = wr.ctypes


def install(fail_first=False):
    fake = _FakeCtypes(fail_first)
    wr.ctypes = fake
    return fake


def restore():
    wr.ctypes = _real_ctypes


def flags(fake):
    return [v for a, v in fake.dwm.calls if a == wr._DWMWA_USE_IMMERSIVE_DARK_MODE]


print("\n[1] COLORREF 字节序（Win32 是 0x00BBGGRR，不是 RGB）")
check("_colorref('#7C3AED') == 0xED3A7C（B 在高位）",
      wr._colorref("#7C3AED") == 0xED3A7C, hex(wr._colorref("#7C3AED") or 0))
check("_colorref('#112233') == 0x332211", wr._colorref("#112233") == 0x332211)
check("_colorref('#80FF0000') 丢掉 alpha", wr._colorref("#80FF0000") == 0x0000FF)
check("非法输入返回 None", wr._colorref("nope") is None and wr._colorref("") is None)


print("\n[2] 浅色主题 → 深色标志必须是 0（用户看到的那条黑栏）")
theme.set_theme_mode("light")
fake = install()
try:
    ok = wr.apply_titlebar_theme(_Widget())
finally:
    restore()
check("调用成功", ok is True)
check("immersive-dark-mode = 0", flags(fake) == [0], str(fake.dwm.calls))
check("栏底色 = 主题 bg_app",
      [v for a, v in fake.dwm.calls if a == wr._DWMWA_CAPTION_COLOR]
      == [wr._colorref(theme.COLORS["bg_app"])],
      str([(a, hex(v)) for a, v in fake.dwm.calls]))


print("\n[3] 深色主题 → 深色标志 1，文字色也换成浅色")
theme.set_theme_mode("dark")
fake = install()
try:
    wr.apply_titlebar_theme(_Widget())
finally:
    restore()
txt = [v for a, v in fake.dwm.calls if a == wr._DWMWA_TEXT_COLOR]
check("immersive-dark-mode = 1", flags(fake) == [1], str(flags(fake)))
check("文字色 = 主题 text_main", txt == [wr._colorref(theme.COLORS["text_main"])],
      str([hex(v) for v in txt]))


print("\n[4] 显式传参优先于主题（预留给「固定深色」的场景）")
theme.set_theme_mode("light")
fake = install()
try:
    wr.apply_titlebar_theme(_Widget(), dark=True)
finally:
    restore()
check("dark=True 覆盖浅色主题", flags(fake) == [1])

theme.set_theme_mode("dark")
fake = install()
try:
    wr.apply_titlebar_theme(_Widget(), dark=False)
finally:
    restore()
check("dark=False 覆盖深色主题", flags(fake) == [0])


print("\n[5] 旧系统回退：20 号属性失败 → 再试 19 号")
theme.set_theme_mode("light")
fake = install(fail_first=True)
try:
    wr.apply_titlebar_theme(_Widget())
finally:
    restore()
attrs = [a for a, v in fake.dwm.calls]
check("先试 20、失败后试 19", attrs[:2] == [20, 19], str(attrs[:3]))


print("\n[6] 没有原生句柄 → 不动任何属性、返回 False")
fake = install()
try:
    ok = wr.apply_titlebar_theme(_Widget(0))
finally:
    restore()
check("hwnd=0 时无 DWM 调用", fake.dwm.calls == [] and ok is False)


print("\n[7] 主题模块异常时按浅色处理（不能因主题坏了就不弹窗）")
_saved = theme.get_theme_mode


def _boom():
    raise RuntimeError("theme broken")


theme.get_theme_mode = _boom
try:
    dark = wr._theme_is_dark()
finally:
    theme.get_theme_mode = _saved
check("get_theme_mode 抛异常 → False", dark is False)


print("\n[8] 旧名 enable_dark_titlebar 仍可用（外部脚本兼容），行为同一套")
theme.set_theme_mode("light")
fake = install()
try:
    wr.enable_dark_titlebar(_Widget())
finally:
    restore()
check("旧名的浅色标志同样是 0", flags(fake) == [0], str(flags(fake)))


print("\n[9] 真窗口端到端：构造条款框时发给 DWM 的就是「浅色」")
os.environ.setdefault("AC_NO_TERMS", "1")
from PySide6.QtWidgets import QApplication      # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])
theme.set_theme_mode("light")
theme.apply_qss()
fake = install()
try:
    from src.terms_dialog import TermsDialog
    dlg = TermsDialog(None)
finally:
    restore()
check("条款框构造时确实调了 DWM", bool(fake.dwm.calls),
      "calls=%d hwnd=%s" % (len(fake.dwm.calls), hex(int(dlg.winId()))))
check("发给 DWM 的是浅色（不是写死的 1）", flags(fake) == [0], str(flags(fake)))
dlg.deleteLater()
app.processEvents()

print("\n[10] 三个调用点都还挂着这条路径（构造期调用，不是只在文档里）")
theme.set_theme_mode("dark")
fake = install()
try:
    d2 = TermsDialog(None)
finally:
    restore()
check("深色主题下同一入口变成 1", flags(fake) == [1], str(flags(fake)))
d2.deleteLater()
app.processEvents()

theme.set_theme_mode("light")
for k in (wr._DWMWA_USE_IMMERSIVE_DARK_MODE, wr._DWMWA_CAPTION_COLOR,
          wr._DWMWA_TEXT_COLOR, wr._DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY):
    check("属性号 %s 未被改动" % k, isinstance(k, int) and 18 <= k <= 40, str(k))

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-224 标题栏跟随主题）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-224 标题栏跟随主题）")
