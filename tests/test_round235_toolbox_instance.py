"""round-235：百宝箱实例下拉，三件套按所选实例工作（离线）。"""
import os
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.main_window as MW  # noqa: E402
from src.i18n import t  # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


tmp = tempfile.mkdtemp(prefix="ac235_")
a = SimpleNamespace(id="a", name="Alpha", mc_dir=tmp, game_dir=tmp)
b = SimpleNamespace(id="b", name="Beta", mc_dir=tmp, game_dir=tmp)


class FakeMgr:
    def list(self):
        return [a, b]

    def get(self, iid):
        return {"a": a, "b": b}.get(iid)

    def current(self):
        return None


win = MW.MainWindow()
win.inst_mgr = FakeMgr()
win.get_current_instance = lambda: None     # 模拟「未选择当前实例」
win._build_toolbox()
combo = win._toolbox_inst_combo
app.processEvents()

check("百宝箱有实例下拉", isinstance(combo, QComboBox))
check("两个实例都入列",
      [combo.itemText(i) for i in range(combo.count())] == ["Alpha", "Beta"],
      str([combo.itemText(i) for i in range(combo.count())]))
check("无当前实例时默认选第一个", combo.currentData() == "a",
      str(combo.currentData()))
check("下拉标签已本地化", t("toolbox.instance") not in ("toolbox.instance", ""),
      t("toolbox.instance"))


class FakePage:
    def __init__(self):
        self.calls: list[object] = []

    def _open_map(self, inst):
        self.calls.append(inst)

    def _open_preview(self, inst):
        self.calls.append(inst)

    def _export_materials(self, inst):
        self.calls.append(inst)


page = FakePage()
win._build_instances = lambda: page
combo.setCurrentIndex(1)                   # 选 Beta
win._toolbox_action("map")
check("地图使用下拉所选实例", page.calls == [b],
      str([getattr(x, "name", "?") for x in page.calls]))

page.calls.clear()
win._toolbox_action("preview")
check("投影使用下拉所选实例", page.calls == [b])

page.calls.clear()
combo.setCurrentIndex(0)                   # 换回 Alpha
win._toolbox_action("materials")
check("材料清单使用下拉所选实例", page.calls == [a],
      str([getattr(x, "name", "?") for x in page.calls]))

print("\n%d checks, %d failed" % (total, len(fails)))
if fails:
    print("FAILED:", ", ".join(fails))
    sys.exit(1)
print("ALL CHECKS PASSED（round-235 百宝箱实例下拉）")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
