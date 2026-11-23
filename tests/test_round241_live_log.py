"""round-241：游戏启动后进度框切换成实时日志窗（PCL2 式）。

用户反馈：游戏启动后进度框 900ms 就关了，看不到 mod 加载进度。
本测试验证行为判据（不是源码字面量）：
  1. mark_launched(log_path) 后：日志视图可见、步骤区隐藏、标题变化
  2. 定时器增量读取 latest.log：关键行（Loading/ERROR）进文本框，噪音行过滤
  3. 日志增长后再次 poll 能追加（增量偏移正确，不重复不漏）
  4. stop_log_tail 后定时器停止
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

app = QApplication(sys.argv)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def pump(ms=100):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


from src.launch_dialog import LaunchProgressDialog  # noqa: E402

td = tempfile.mkdtemp()
logp = os.path.join(td, "latest.log")


class _Inst:
    name = "测试实例"


print("== 0. 默认模式（无 log_path）不切日志 ==")
dlg0 = LaunchProgressDialog(_Inst(), mode="launch")
dlg0.show()
app.processEvents()
dlg0.mark_launched()   # 普通启动：不传 log_path
app.processEvents()
check("默认模式不切日志视图", not dlg0.log_view.isVisible())
check("默认模式不启定时器", dlg0._log_timer is None)
check("默认模式步骤已点亮", all(m == dlg0._MODE_DONE for m in dlg0._modes.values()))
dlg0.close()

print("== 1. 调试模式（传 log_path）切日志视图 ==")
dlg = LaunchProgressDialog(_Inst(), mode="launch")
dlg.show()
app.processEvents()
check("初始日志视图隐藏", not dlg.log_view.isVisible())
with open(logp, "w", encoding="utf-8") as f:
    f.write("[04:12:01] [main/INFO]: Loading mod: sodium\n")
    f.write("[04:12:01] [main/INFO]: Setting user: Steve\n")  # 噪音行
    f.write("[04:12:02] [main/ERROR]: Missing dependency JEI\n")
dlg.mark_launched(logp)
app.processEvents()
check("切后日志视图可见", dlg.log_view.isVisible())
check("切后 live_log_mode=True", dlg._live_log_mode)
check("标题变运行中", "运行中" in dlg.title_lbl.text() or "running" in dlg.title_lbl.text().lower(),
      dlg.title_lbl.text())

print("== 2. 关键行过滤 + 增量读 ==")
txt = dlg.log_text.toPlainText()
check("Loading 行进日志", "Loading mod: sodium" in txt, txt[:120].replace("\n", " | "))
check("ERROR 行进日志", "Missing dependency JEI" in txt)
check("噪音行被过滤", "Setting user" not in txt)

n_before = len(dlg.log_text.toPlainText())
with open(logp, "a", encoding="utf-8") as f:
    f.write("[04:12:05] [main/INFO]: Loaded 150 mods\n")
dlg._poll_log()   # 增量
app.processEvents()
txt2 = dlg.log_text.toPlainText()
check("新增行被追加", "Loaded 150 mods" in txt2)
check("旧行不重复", txt2.count("Loading mod: sodium") == 1)

print("== 3. 停 tail ==")
dlg.stop_log_tail()
check("定时器已停", dlg._log_timer is None)

print("\nround-241 live log: 13 checks, %d failed" % len(fails))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED（启动进度实时日志窗）")
sys.stdout.flush()
os._exit(0)
