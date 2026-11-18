"""round-233：百宝箱可达性与存档地图默认落点（离线）。"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.core.world_map as wm  # noqa: E402
import src.main_window as MW  # noqa: E402
from src.map_dialog import MapDialog  # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── [1] 百宝箱页面可达（懒构建索引恰好等于初始栈长度）─────────────────
print("== 百宝箱可达 ==")
win = MW.MainWindow()
win.resize(1280, 800)
ret = win.show_page("toolbox")
app.processEvents()
check("show_page(toolbox) 返回 True", ret)
check("栈切到 toolbox", win.stack.currentIndex() == MW.STACK_INDEX["toolbox"],
      "%s / %s" % (win.stack.currentIndex(), MW.STACK_INDEX["toolbox"]))
check("百宝箱页面已构建", hasattr(win, "toolbox_widget"))

# ── [2] 未打开过实例页时，百宝箱卡片仍能转交 ───────────────────────────
print("== 懒构建兜底 ==")
win2 = MW.MainWindow()
check("初始未构建实例页", not hasattr(win2, "instances_page"))


class FakePage:
    def __init__(self):
        self.calls: list[str] = []

    def _open_map(self, inst):
        self.calls.append("map")

    def _open_preview(self, inst):
        self.calls.append("preview")

    def _export_materials(self, inst):
        self.calls.append("materials")


fake = FakePage()
win2._build_instances = lambda: fake
win2.get_current_instance = lambda: object()
win2._toolbox_action("map")
check("未建实例页时自动构建并转交", fake.calls == ["map"], str(fake.calls))

# ── [3] 地图默认落到有 region 的世界 ───────────────────────────────────
print("== 地图默认落点 ==")
tmp = tempfile.mkdtemp(prefix="ac233_")
saves = os.path.join(tmp, "saves")
empty = os.path.join(saves, "A_empty")
real = os.path.join(saves, "B_real")
os.makedirs(os.path.join(empty, "region"), exist_ok=True)
os.makedirs(os.path.join(real, "region"), exist_ok=True)
with open(os.path.join(empty, "level.dat"), "wb") as fh:
    fh.write(b"\0")
with open(os.path.join(real, "region", "r.0.0.mca"), "wb") as fh:
    fh.write(b"\0" * 32)

dlg = MapDialog(tmp)
items = [dlg.world_box.itemText(i) for i in range(dlg.world_box.count())]
check("两个世界都入列", items == ["A_empty", "B_real"], str(items))
check("默认选中有区块的世界",
      os.path.basename(dlg.world_box.currentData() or "") == "B_real",
      str(dlg.world_box.currentData()))

print("\n%d checks, %d failed" % (total, len(fails)))
if fails:
    print("FAILED:", ", ".join(fails))
    sys.exit(1)
print("ALL CHECKS PASSED（round-233 导航与地图默认落点）")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
