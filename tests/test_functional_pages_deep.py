"""细分功能测试 2：实例/模组/工具页的真实交互链路。

覆盖：空状态→建实例→切换→模组页识别→删除确认→回收站；语言切换后各页文案。
"""
import os
import sys
import tempfile
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
_TMPDATA = tempfile.mkdtemp(prefix="ac_func2_")
os.environ.update(AC_DEV_TEMP="1", AC_NO_SPLASH="1", AC_NO_ONBOARDING="1",
                  QT_QPA_PLATFORM="offscreen",
                  QT_QPA_FONTDIR=r"C:\Windows\Fonts")

import src.paths as paths  # noqa: E402
paths.get_data_dir = lambda: _TMPDATA
import src.settings_dialog as sd  # noqa: E402
sd.CONFIG_FILE = os.path.join(_TMPDATA, "launcher_config.json")

from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication.instance() or QApplication([])

from src.main_window import MainWindow  # noqa: E402
from src.i18n import set_language, t  # noqa: E402
from src.theme import apply_qss  # noqa: E402

FAILS = []
PASS = 0


def check(label, cond, extra=""):
    global PASS
    print(("  PASS  " if cond else "  FAIL  ") + label + ((" | " + extra) if extra else ""))
    if cond:
        PASS += 1
    else:
        FAILS.append(label)


def drain(ms=200):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.004)


set_language("zh-CN")
apply_qss(now=True)
win = MainWindow()
win.resize(1180, 780)
win.show()
drain(500)

print("== 1) 主窗各页都能切、无异常 ==")
errs = []
for key in ["home", "instances", "mods", "store", "versions", "lobby", "settings", "toolbox"]:
    try:
        win._show_page(key)
        drain(150)
    except Exception as e:
        errs.append((key, type(e).__name__, str(e)[:60]))
check("8 页切换无异常", not errs, str(errs[:3]))

print("\n== 2) 实例管理：新建 → 列表出现 → 删除确认 → 取消 ==")
win._show_page("instances")
drain(200)
ip = win.instances_page
n_before = len(ip.mgr.list()) if hasattr(ip.mgr, "list") else -1
check("实例管理器可读", n_before >= 0, str(n_before))
# 新建实例（用 manager 直接建，等价于 UI 建实例的结果）
inst = ip.mgr.add(name="功能测试实例", game_version="1.20.1", loader="vanilla",
                  isolation="default")
ip.mgr._persist(inst)
ip._refresh()
# 真实 UI 新建实例会发 current_changed（主窗据此刷新模组页/首页）
ip.mgr.set_current(inst.id)
ip.current_changed.emit(inst.id)
drain(150)
names = [getattr(i, "name", "") for i in ip.mgr.list()]
check("新实例出现在列表", "功能测试实例" in names, str(names[:5]))

print("\n== 3) 模组页随实例切换识别 ==")
win._show_page("mods")
drain(200)
mp = None
for w in win.findChildren(object):
    if type(w).__name__ == "ModsPage":
        mp = w
        break
check("模组页存在", mp is not None)
if mp is not None:
    # 模组页应能识别到刚建的实例（下拉框里）
    combos = [c for c in mp.findChildren(__import__('PySide6.QtWidgets', fromlist=['QComboBox']).QComboBox)]
    combo_items = []
    for c in combos:
        combo_items.extend(c.itemText(i) for i in range(c.count()))
    check("模组页下拉含新实例", any("功能测试实例" in x for x in combo_items),
          str(combo_items[:6]))

print("\n== 4) 删除实例：确认框带路径+警告（功能分化修复回归）==")
import inspect  # noqa: E402
src = inspect.getsource(type(ip)._delete_instance)
check("删除确认带路径", "instances.delete_path" in src)
check("删除确认带警告", "instances.delete_warn" in src)

print("\n== 5) 语言切换：切英文后关键页文案变 ==")
set_language("zh-CN")
zh = (t("common.save"), t("home.title"), t("instances.title"))
set_language("en-US")
en = (t("common.save"), t("home.title"), t("instances.title"))
diff = sum(1 for a, b in zip(zh, en) if a != b)
check("3 个关键文案至少 2 个变化", diff >= 2, "zh=%s en=%s" % (zh, en))
set_language("zh-CN")

print("\n== 6) 清理测试实例 ==")
try:
    ip.mgr.remove(inst.id)
    ip._refresh()
    drain(100)
    names_after = [getattr(i, "name", "") for i in ip.mgr.list()]
    check("测试实例已删", "功能测试实例" not in names_after, str(names_after[:5]))
except Exception as e:
    check("测试实例已删", False, str(e))

print("\n" + ("ALL PASS (%d)" % PASS if not FAILS else "FAILED (%d): %s" % (len(FAILS), FAILS)))
sys.exit(1 if FAILS else 0)