"""round-232：存档地图 / 投影预览 / 材料清单的百宝箱入口回归（离线）。"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.i18n as I  # noqa: E402
import src.main_window as MW  # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


NEW_KEYS = ("tool.map_tile_desc", "tool.preview_tile_desc",
            "tool.materials_tile_desc", "tool.need_instance")

# ── [1] 新文案双语齐全 ─────────────────────────────────────────────────
print("== i18n ==")
langs = [d for d in I._STRINGS.values() if isinstance(d, dict)]
for key in NEW_KEYS:
    hosted = [d for d in langs if key in d]
    check(key + " 双语齐全", len(hosted) >= 2 and all(d[key] != key for d in hosted),
          str(len(hosted)))

# ── [2] 百宝箱真的出现三个入口 ─────────────────────────────────────────
print("== 百宝箱入口 ==")
win = MW.MainWindow()
widget = win._build_toolbox()
texts = [b.text() for b in widget.findChildren(QPushButton)]
for key in ("map.menu", "preview.title", "tool.materials"):
    label = I.t(key)
    check("百宝箱有入口：" + label, label in texts)
labels = [lab.text() for lab in widget.findChildren(QLabel)]
for key in NEW_KEYS[:3]:
    check("说明文字可见：" + key, I.t(key) in labels)

# ── [3] 动作转交实例页，避免两套逻辑分叉 ───────────────────────────────
print("== 动作分派 ==")


class FakePage:
    def __init__(self):
        self.calls: list[str] = []

    def _open_map(self, inst):
        self.calls.append("map")

    def _open_preview(self, inst):
        self.calls.append("preview")

    def _export_materials(self, inst):
        self.calls.append("materials")


page = FakePage()
win.instances_page = page
inst = object()
win.get_current_instance = lambda: inst
for kind, want in (("map", "map"), ("preview", "preview"),
                   ("materials", "materials")):
    page.calls.clear()
    win._toolbox_action(kind)
    check(kind + " 转交实例页", page.calls == [want], str(page.calls))

# 无当前实例时提示而不是抛异常
win.instances_page = None
win.get_current_instance = lambda: None
try:
    win._toolbox_action("map")
    ok = True
except Exception as exc:  # noqa: BLE001 - 探针要报出真实异常
    ok = False
    print("   exception:", repr(exc))
check("无实例时只提示不崩", ok)

print("\n%d checks, %d failed" % (total, len(fails)))
if fails:
    print("FAILED:", ", ".join(fails))
    sys.exit(1)
print("ALL CHECKS PASSED（round-232 百宝箱三件套入口）")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
