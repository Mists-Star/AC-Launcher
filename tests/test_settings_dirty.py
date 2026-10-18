"""round-111 回归测试：设置页不得「没改也报未保存」（诊断脚本，不入库）。

背景（真 bug）：_DEFAULTS 缺 4 个 _sync_ui_to_cfg 会写入的键，且派生键
jvm_aikars 与 jvm_preset 自相矛盾 → is_dirty() 恒为真 → 玩家每次进设置页
再离开都被弹「有未保存的更改」，离屏自动化则直接挂死在模态框上。
"""
import ast
import os
import sys

# tests/ 下运行：仓库根 = tests 的上一级
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import src.settings_dialog as sd  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-48s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── 1. _sync_ui_to_cfg 写入的每个键都必须在 _DEFAULTS 里 ──
src = open(sd.__file__, encoding="utf-8").read()
tree = ast.parse(src)
sync_keys = set()
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "_sync_ui_to_cfg":
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for tgt in sub.targets:
                    if (isinstance(tgt, ast.Subscript)
                            and isinstance(tgt.value, ast.Name)
                            and tgt.value.id == "target"
                            and isinstance(tgt.slice, ast.Constant)):
                        sync_keys.add(tgt.slice.value)

missing = sorted(sync_keys - set(sd._DEFAULTS))
check("_sync_ui_to_cfg 的键全部有默认值", not missing,
      "缺 %s" % missing if missing else "共 %d 键" % len(sync_keys))

# ── 2. 派生键 jvm_aikars 必须与 jvm_preset 一致 ──
cfg = sd.load_config()
check("jvm_aikars 与 jvm_preset 自洽",
      cfg.get("jvm_aikars") == (cfg.get("jvm_preset") == "aikar"),
      "jvm_preset=%r jvm_aikars=%r" % (cfg.get("jvm_preset"),
                                       cfg.get("jvm_aikars")))

# ── 3. 新建设置页立刻 is_dirty() 必须为 False ──
page = sd.SettingsPage()
check("新建设置页 is_dirty() == False", page.is_dirty() is False,
      "is_dirty=%r" % page.is_dirty())

# ── 4. 改了 UI 之后确实要报 dirty（不能为了不弹窗而把检测整个废掉）──
try:
    if hasattr(page, "ram") and hasattr(page.ram, "setValue"):
        page.ram.setValue(page.ram.value() + 512)
        check("改内存滑块后 is_dirty() == True",
              page.is_dirty() is True)
    else:
        check("改内存滑块后 is_dirty() == True", True, "(无 ram 控件，跳过)")
except Exception as e:  # noqa: BLE001
    check("改内存滑块后 is_dirty() == True", False, str(e)[:80])

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("ALL CHECKS PASSED")
