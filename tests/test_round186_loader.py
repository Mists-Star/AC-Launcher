"""round-186：加载器 × MC 版本可用性 + 装加载器顺手装 Fabric API。

用户原话：
* 「下加载器不下配套 fabric api」
* 「修改的选项中会出现不存在的加载器与版本」

判据分三层：
1. **静态规则**：哪些加载器在哪些 MC 版本上存在（core.loader_catalog）；
2. **版本号裁剪**：NeoForge 版本号带 MC 前缀（20.1.x ↔ 1.20.1），按前缀裁；
3. **界面**：面板的加载器下拉里不该出现该版本没有的加载器；当前加载器永远
   在（不然打开面板自己的加载器就"消失"了）；Fabric API 勾选项只在
   fabric / quilt 时出现。
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ["AC_DEV_TEMP"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


from src.core.loader_catalog import (  # noqa: E402
    filter_neoforge, loaders_for, neoforge_prefix, parse_mc, supports,
)

print("① 静态可用性规则")
check("1.12.2 没有 NeoForge", not supports("neoforge", "1.12.2"))
check("1.20.1 有 NeoForge", supports("neoforge", "1.20.1"))
check("1.12.2 没有 Fabric", not supports("fabric", "1.12.2"))
check("1.12.2 没有 Quilt", not supports("quilt", "1.12.2"))
check("1.14 有 Fabric", supports("fabric", "1.14"))
check("1.20.1 没有 LiteLoader", not supports("liteloader", "1.20.1"))
check("1.12.2 有 LiteLoader", supports("liteloader", "1.12.2"))
check("1.12.9 也有 LiteLoader（别把 1.12.x 误杀）",
      supports("liteloader", "1.12.9"))
check("1.13.1 没有 LiteLoader", not supports("liteloader", "1.13.1"))
check("1.12.2 有 Legacy Fabric", supports("legacyfabric", "1.12.2"))
check("1.14 没有 Legacy Fabric", not supports("legacyfabric", "1.14"))
check("Cleanroom 只在 1.12.2", supports("cleanroom", "1.12.2") and
      not supports("cleanroom", "1.20.1"))
check("原版任何版本都有", supports("vanilla", "1.7.10"))
check("Forge 1.7.10 有", supports("forge", "1.7.10"))
check("快照版不做静态拦截", supports("neoforge", "24w14a"))
check("版本号解析", parse_mc("1.20.1") == (1, 20, 1) and
      parse_mc("1.21") == (1, 21) and parse_mc("abc") is None)

print("② 按版本筛加载器表")
from src.instances import LOADERS  # noqa: E402

old = loaders_for("1.12.2", LOADERS)
check("1.12.2 表里没有 neoforge", "neoforge" not in old, str(old))
check("1.12.2 表里没有 fabric", "fabric" not in old, str(old))
check("1.12.2 表里没有 quilt", "quilt" not in old, str(old))
check("1.12.2 表里有 cleanroom", "cleanroom" in old, str(old))
check("1.12.2 表里有 legacyfabric", "legacyfabric" in old, str(old))
new = loaders_for("1.20.1", LOADERS)
check("1.20.1 表里有 fabric", "fabric" in new, str(new))
check("1.20.1 表里有 neoforge", "neoforge" in new, str(new))
check("1.20.1 表里没有 liteloader", "liteloader" not in new, str(new))
check("1.20.1 表里没有 cleanroom", "cleanroom" not in new, str(new))

print("③ NeoForge 版本号按 MC 前缀裁剪")
check("1.20.1 前缀", neoforge_prefix("1.20.1") == "20.1.", neoforge_prefix("1.20.1"))
check("1.21 前缀", neoforge_prefix("1.21") == "21.0.", neoforge_prefix("1.21"))
check("1.21.4 前缀", neoforge_prefix("1.21.4") == "21.4.", neoforge_prefix("1.21.4"))
raw = ["20.1.237", "20.4.190", "21.1.77", "21.4.1", "19.2.1"]
cut = filter_neoforge(raw, "1.20.1")
check("1.20.1 只留 20.1.x", cut == ["20.1.237"], str(cut))
check("1.21.4 只留 21.4.x", filter_neoforge(raw, "1.21.4") == ["21.4.1"],
      str(filter_neoforge(raw, "1.21.4")))
check("1.19 没有 NeoForge 前缀", filter_neoforge(raw, "1.19.2") == [],
      str(filter_neoforge(raw, "1.19.2")))

print("④ Fabric API 只对 fabric / quilt")
from src.core.loader_swap import wants_fabric_api  # noqa: E402

check("fabric 需要", wants_fabric_api("fabric"))
check("quilt 需要", wants_fabric_api("quilt"))
check("forge 不需要", not wants_fabric_api("forge"))
check("neoforge 不需要", not wants_fabric_api("neoforge"))
check("原版不需要", not wants_fabric_api("vanilla"))

print("⑤ 非 fabric 加载器不触发 Fabric API 安装（不联网）")
from src.core.loader_swap import install_fabric_api  # noqa: E402
from src.instances import Instance  # noqa: E402

tmp = tempfile.mkdtemp(prefix="ac_loader_")
inst = Instance(id="t", name="T", game_version="1.20.1", loader="forge",
                _base=os.path.join(tmp, "mc"))
try:
    install_fabric_api(inst)
    check("forge 装 Fabric API 被拒绝", False)
except RuntimeError as exc:
    check("forge 装 Fabric API 被拒绝", str(exc) == "not_fabric_like", str(exc))

print("⑥ 面板：加载器下拉按版本过滤")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.instance_editor import InstanceEditorDialog  # noqa: E402

old_inst = Instance(id="o", name="老实例", game_version="1.12.2",
                     loader="forge", _base=os.path.join(tmp, "mc"))
dlg = InstanceEditorDialog(None, old_inst)
choices = [dlg.loader_combo.itemData(i)
            for i in range(dlg.loader_combo.count())]
check("1.12.2 下拉里没有 neoforge", "neoforge" not in choices, str(choices))
check("1.12.2 下拉里没有 fabric", "fabric" not in choices, str(choices))
check("当前加载器仍在下拉里", "forge" in choices, str(choices))
check("当前加载器被选中",
      dlg.loader_combo.currentData() == "forge",
      str(dlg.loader_combo.currentData()))

# 改版本 → 下拉跟着变
dlg.ver_edit.setText("1.20.1")
dlg._on_version_edited()
choices2 = [dlg.loader_combo.itemData(i)
            for i in range(dlg.loader_combo.count())]
check("改成 1.20.1 后出现 neoforge", "neoforge" in choices2, str(choices2))
check("改成 1.20.1 后出现 fabric", "fabric" in choices2, str(choices2))
check("改成 1.20.1 后没有 liteloader", "liteloader" not in choices2, str(choices2))
dlg.deleteLater()

print("⑦ Fabric API 勾选项只在 fabric / quilt 时出现")
fab_inst = Instance(id="f", name="F", game_version="1.20.1", loader="fabric",
                    _base=os.path.join(tmp, "mc"))
dlg2 = InstanceEditorDialog(None, fab_inst)
check("Fabric 实例显示 Fabric API 勾选项",
      not dlg2.fabapi_chk.isHidden(), "")
check("默认勾选", dlg2.fabapi_chk.isChecked())
dlg2.loader_combo.setCurrentIndex(dlg2.loader_combo.findData("forge"))
dlg2._on_loader_picked(0)
check("切到 Forge 后隐藏", dlg2.fabapi_chk.isHidden(), "")
dlg2.loader_combo.setCurrentIndex(dlg2.loader_combo.findData("quilt"))
dlg2._on_loader_picked(0)
check("切回 Quilt 后显示", not dlg2.fabapi_chk.isHidden(), "")
dlg2.deleteLater()

shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-186 加载器可用性 + Fabric API）")
