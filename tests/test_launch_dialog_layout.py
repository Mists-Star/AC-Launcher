"""round-163 回归测试：启动进度对话框在长文本下高度有界（不向下无限延伸）。

背景：旧实现在 resizeEvent 里按标签当前宽度反复抬高 minimumHeight，形成
「标签变高 → 布局请求更高 → 窗口 resize → 宽度变化 → 需要更高」的正反馈。
修复后换行标签高度钳制在 2~5 行，连续刷新状态/来源文本时窗口高度应收敛。

覆盖：
  1. 连续 20 次超长状态 + 来源文本后，第 3 次之后相邻高度差 ≤ 1px
  2. 相对初始高度总增高 ≤ 60px
  3. 对话框高度有限（< 900），绝不随文本长度增长
"""
import os
import sys

# 必须在 import PySide6 之前设置离屏后端
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# tests/ 下运行：仓库根 = tests 的上一级
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ["AC_DEV_TEMP"] = "1"  # 不污染真实 data 目录

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.instances import Instance  # noqa: E402
from src.launch_dialog import LaunchProgressDialog  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


dlg = LaunchProgressDialog(
    Instance(id="dlg_layout", name="Test Instance", game_version="1.20.1"))
dlg.show()
app.processEvents()

base_h = dlg.height()
heights = []
for i in range(20):
    dlg.set_status_text(("长文本状态信息。" * 40) + str(i))
    dlg.set_sources("下载来源（逐个尝试）：" * 30)
    app.processEvents()
    heights.append(dlg.height())

check("高度记录完整（20 次）", len(heights) == 20, str(len(heights)))
check("高度始终有限（< 900）", all(h < 900 for h in heights),
      "max=%d" % max(heights))
check("第 3 次后相邻高度差 ≤ 1px",
      all(abs(heights[i] - heights[i - 1]) <= 1 for i in range(3, len(heights))),
      "heights=%s" % heights)
check("总增高 ≤ 60px", max(heights) - base_h <= 60,
      "base=%d max=%d" % (base_h, max(heights)))

dlg.close()
app.processEvents()

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("ALL CHECKS PASSED")
