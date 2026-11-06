"""round-169 回归：设置页组合选项必须给出行为说明（已按 2026-11-06 语义更新）。

背景：截图里「启动后自动关闭启动器」与「最小化到系统托盘（关窗不退出）」
可以同时勾选，看起来自相矛盾；此外低配模式与外观/音效开关、自动检测 Java
与强制不兼容 Java 也存在「勾了却不生效」的组合。

2026-11-06 语义变更：启动后不再真退出，改为**隐藏到系统托盘、进程常驻**，
游戏退出时自动恢复窗口（修崩溃检测/退出后命令链路失效）。因此：
- 说明只在「开启自动最小化」时出现，与 tray_chk 是否勾选**无关**；
- 说明讲清「恢复窗口 / 想真退出用托盘右键」；
- 「退出后命令」那行改为「常驻托盘以确保命令能执行」，不再说「会被跳过」。

本套只验证 UI 的**说明/禁用联动**，不改任何配置语义：
- 开启自动最小化 → 出现恢复/退出方式说明；关闭 → 隐藏；
- 自动最小化 + 退出后命令 → 出现「常驻托盘」说明；
- 低配模式勾选 → 出现「外观/音效开关暂不生效」说明；
- 自动检测 Java 勾选 → 强制开关禁用并出现说明。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import src.settings_dialog as sd  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-46s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# 配置走内存，绝不碰真实 launcher_config.json
_CFG = dict(sd._DEFAULTS)
sd.load_config = lambda *a, **k: dict(_CFG)
sd.save_config = lambda *a, **k: None

page = sd.SettingsPage()
check("设置页可构造", page is not None)


def section(idx):
    page._show_section(idx)
    app.processEvents()


# ── 1. 外观页：自动最小化说明与托盘开关解耦 ──
section(1)
note = getattr(page, "behavior_note", None)
check("外观页有行为说明控件", note is not None)
page.close_launch_chk.setChecked(True)
page.tray_chk.setChecked(True)
app.processEvents()
check("开启自动最小化时说明可见", not note.isHidden(),
      "hidden=%r" % note.isHidden())
check("说明讲清游戏退出时恢复窗口",
      "游戏退出时恢复" in note.text(), note.text().replace("\n", " / "))
check("说明讲清真退出走托盘右键",
      "托盘右键" in note.text(), note.text().replace("\n", " / "))
page.tray_chk.setChecked(False)
app.processEvents()
check("关掉托盘常驻后说明仍在（不再依赖 tray_chk）",
      not note.isHidden(), "hidden=%r" % note.isHidden())
page.close_launch_chk.setChecked(False)
app.processEvents()
check("关掉自动最小化后说明隐藏", note.isHidden())

# ── 2. 启动页：退出后命令由常驻托盘保证执行 ──
page.close_launch_chk.setChecked(True)
section(2)
edit = getattr(page, "exit_cmd_edit", None)
check("启动页有退出后命令输入框", edit is not None)
edit.setText("echo done")
app.processEvents()
check("配置命令后说明含「常驻托盘」",
      "常驻托盘" in note.text(), note.text().replace("\n", " / "))
edit.setText("")
app.processEvents()
check("清空命令后该行消失", "常驻托盘" not in note.text())

# ── 3. 基础页：低配模式压制提示 ──
section(0)
slim_note = getattr(page, "slim_note", None)
check("基础页有低配提示控件", slim_note is not None)
check("默认关闭时不显示", slim_note.isHidden())
page.slim_chk.setChecked(True)
app.processEvents()
check("打开低配后显示", not slim_note.isHidden())
check("提示含「暂不生效」", "暂不生效" in slim_note.text(), slim_note.text())
page.slim_chk.setChecked(False)
app.processEvents()
check("关闭后隐藏", slim_note.isHidden())

# ── 4. Java 页：自动检测开启时强制开关禁用 ──
section(7)
auto = getattr(page, "java_auto", None)
force = getattr(page, "java_force", None)
jnote = getattr(page, "java_force_note", None)
check("Java 页有自动/强制控件", auto is not None and force is not None)
auto.setChecked(True)
app.processEvents()
check("自动检测开启 → 强制禁用", not force.isEnabled())
check("并显示不生效说明", jnote is not None and not jnote.isHidden())
auto.setChecked(False)
app.processEvents()
check("自动检测关闭 → 强制可用", force.isEnabled())

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("ALL CHECKS PASSED")
