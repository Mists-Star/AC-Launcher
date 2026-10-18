"""审计：找出 _sync_ui_to_cfg 会写入、但 _DEFAULTS 里没有的键（诊断脚本，不入库）。

这类缺漏会让 is_dirty() 永远为真 → 每次进设置页再离开都弹「有未保存的更改」。
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

src = open(sd.__file__, encoding="utf-8").read()
tree = ast.parse(src)

# 1) _sync_ui_to_cfg 里所有 target["x"] = ... 的键
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

defaults = set(sd._DEFAULTS)
missing = sorted(sync_keys - defaults)

print("_sync_ui_to_cfg 写入的键: %d" % len(sync_keys))
print("_DEFAULTS 里的键:        %d" % len(defaults))
print()
print("=== 会写入但 _DEFAULTS 缺失（%d 个）===" % len(missing))
for k in missing:
    print("   %s" % k)
print()

cfg = sd.load_config()
print("=== 已知派生键的一致性 ===")
for k in ["jvm_preset", "jvm_aikars"]:
    print("   %-14s = %r" % (k, cfg.get(k, "<<缺失>>")))
print("   推导 jvm_aikars 应为:", cfg.get("jvm_preset") == "aikar")
