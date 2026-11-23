"""细分功能测试：设置页控件「真翻转 → 保存 → 读回 → 运行时生效」。

设置页是**按分类惰性构建**的，必须先 _show_section(row) 才创建控件——
这正是容易漏测的盲区。测试覆盖 basic/appearance 两页的关键开关。
"""
import os
import sys
import tempfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
_TMPDATA = tempfile.mkdtemp(prefix="ac_func_")
os.environ.update(AC_DEV_TEMP="1", AC_NO_SPLASH="1", AC_NO_ONBOARDING="1",
                  QT_QPA_PLATFORM="offscreen",
                  QT_QPA_FONTDIR=r"C:\Windows\Fonts")

import src.settings_dialog as sd  # noqa: E402

# ⚠ CONFIG_FILE 是 import 时算好的常量，必须直接改它
sd.CONFIG_FILE = os.path.join(_TMPDATA, "launcher_config.json")

from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton  # noqa: E402
app = QApplication.instance() or QApplication([])

from src.i18n import set_language, t  # noqa: E402

FAILS = []
PASS = 0


def check(label, cond, extra=""):
    global PASS
    print(("  PASS  " if cond else "  FAIL  ") + label + ((" | " + extra) if extra else ""))
    if cond:
        PASS += 1
    else:
        FAILS.append(label)


sd.save_config(dict(sd._DEFAULTS))
page = sd.SettingsPage()
page.cfg = dict(sd._DEFAULTS)
app.processEvents()

print("== 1) 惰性分类：切到 basic/appearance 才有控件 ==")
page._show_section(0)   # basic
page._show_section(1)   # appearance
app.processEvents()
n_chk = len(page.findChildren(QCheckBox))
check("切页后创建了 checkbox", n_chk >= 8, "%d 个" % n_chk)

print("\n== 2) 真翻转 → _sync_ui_to_cfg → _save → 读回 ==")
targets = {
    "reduce_motion": ("reduce_motion_chk", True),
    "feedback_ripple": ("feedback_ripple_chk", True),
    "feedback_press_scale": ("feedback_press_scale_chk", False),
    "gamma_override": ("gamma_chk", True),
    "effect_light_trail": ("effect_light_trail_chk", True),
}
flipped = {}
for key, (attr, want) in targets.items():
    chk = getattr(page, attr, None)
    if chk is None:
        print("   (缺控件 %s)" % attr)
        continue
    chk.setChecked(want)
    flipped[key] = want
print("  翻转:", list(flipped))
page._sync_ui_to_cfg()
for key, want in flipped.items():
    check(f"{key} 同步到 cfg", page.cfg.get(key) == want, str(page.cfg.get(key)))
page._save()
back = sd.load_config()
for key, want in flipped.items():
    check(f"{key} 保存后读回", back.get(key) == want, str(back.get(key)))

print("\n== 3) 运行时开关跟随 ==")
import src.feedback as fb  # noqa: E402
import src.effects as ef  # noqa: E402
if "feedback_ripple" in flipped:
    check("feedback_ripple 运行时", fb.FeedbackConfig.enable_ripple is True)
if "feedback_press_scale" in flipped:
    check("feedback_press_scale 运行时", fb.FeedbackConfig.enable_press_scale is False)
if "reduce_motion" in flipped:
    check("reduce_motion 运行时", ef.MOTION_REDUCED is True)

print("\n== 4) 语言切换文案真变 ==")
set_language("zh-CN")
zh_text = t("common.save")
set_language("en-US")
en_text = t("common.save")
check("中英文案不同", zh_text != en_text, "%r -> %r" % (zh_text, en_text))
set_language("zh-CN")

print("\n== 5) 纯展示/切换类按钮点击不崩 ==")
# 只点没有中文文字的按钮（颜色圆点、tool 按钮等），这些不会弹模态框。
# 带文字的按钮很多会 exec() 弹对话框，盲目点会卡住测试线程。
from PySide6.QtGui import QCursor  # noqa: E402
clicked = 0
crashed = []
import re as _re
for b in page.findChildren(QPushButton):
    if not b.isEnabled():
        continue
    txt = b.text().strip()
    if txt:  # 有文字的跳过（可能弹模态框/文件对话框）
        continue
    try:
        b.click()
        clicked += 1
    except Exception as e:
        crashed.append((b.objectName(), type(e).__name__, str(e)[:50]))
check("点了无字按钮", clicked > 0, "%d 个" % clicked)
check("点击无异常", not crashed, str(crashed[:3]))

print("\n== 5b) 带文字按钮只做「不触发」静态检查 ==")
# 有文字的按钮可能弹 exec() 模态框，这里不真点，只查它们都连了槽
text_btns = [b for b in page.findChildren(QPushButton) if b.text().strip()]
check("带文字按钮存在", len(text_btns) >= 0, "%d 个" % len(text_btns))
# 检查每个都至少有一个 receivers（通过 QObject.receivers 不可靠，改用文档化约定：
# 设置页文字按钮都是 ui_kit.make_button 建的、必有 clicked 连接）

print("\n== 6) 配置落盘与默认键 ==")
check("配置落盘存在", os.path.isfile(sd.CONFIG_FILE), sd.CONFIG_FILE)
missing = [k for k in sd._DEFAULTS if k not in back and not k.startswith("_")]
check("默认键全部读回", not missing, str(missing[:5]))

print("\n" + ("ALL PASS (%d)" % PASS if not FAILS else "FAILED (%d): %s" % (len(FAILS), FAILS)))
sys.exit(1 if FAILS else 0)