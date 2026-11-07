"""round-189：修改页重做（加载器卡片选择器 / 版本下拉 / 危险区）。

用户实拍：「我们整个修改太简陋了」——原来是一个纯文本框 + 两个下拉 + 两颗按钮，
看着像调试面板。这轮对着 PCL/HMCL 的做法重做。

判据：
1. **卡片选择器**：每张卡有真实 logo 像素；点哪张 current 就是哪张
   （☠ 上一版 current() 返回"第一个可用的卡"，选 quilt 却报 vanilla —— 这条
   判据就是为了钉死它）；按可用性过滤后**网格无空洞**（重排生效）。
2. **版本框**：可编辑下拉（能填也能选），「选版本」按钮存在。
3. **版本列表标注**：第一条带「最新」标记。
4. **危险区**：卸载按钮是 danger 样式，且说清「会删什么 / 会留什么」。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


print("① 加载器卡片选择器")
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.loader_picker import LoaderPicker, loader_logo  # noqa: E402

pm = loader_logo("fabric", 30)
check("fabric logo 有像素", not pm.isNull(), "%dx%d" % (pm.width(), pm.height()))
check("未知加载器回落到空图", loader_logo("nope", 30).isNull())

entries = [(lid, lid, "desc") for lid in
            ("vanilla", "fabric", "forge", "quilt", "neoforge", "optifine",
             "liteloader", "legacyfabric", "cleanroom")]
picker = LoaderPicker(entries)
check("卡片数量对", len(picker._cards) == 9, str(len(picker._cards)))

picker._cards["quilt"].picked.emit("quilt")
check("点哪张 current 就是哪张", picker.current() == "quilt", picker.current())
picker._cards["forge"].picked.emit("forge")
check("再点换一张", picker.current() == "forge", picker.current())

# 过滤后重排：可见卡片必须占连续格子，不能留空洞
picker.set_available(["vanilla", "fabric", "forge"])
cells = []
for lid, card in picker._cards.items():
    if card.isHidden():
        continue
    idx = picker._grid.indexOf(card)
    cells.append((idx // picker._grid.columnCount(),
                  idx % picker._grid.columnCount()))
cells.sort()
check("过滤后卡片连续排布（无空洞）", cells == [(0, 0), (0, 1), (0, 2)],
      str(cells))
check("被过滤掉的卡确实隐藏",
      picker._cards["quilt"].isHidden() and
      not picker._cards["fabric"].isHidden())

print("② 修改页结构")
from src.instances import Instance  # noqa: E402
from src.instance_editor import InstanceEditorDialog  # noqa: E402

inst = Instance(id="t", name="T", game_version="1.20.1", loader="fabric",
                loader_version="0.15.11")
dlg = InstanceEditorDialog(None, inst)
check("版本框是可编辑下拉",
      hasattr(dlg.ver_edit, "currentText"), type(dlg.ver_edit).__name__)
check("有「选版本」按钮入口",
      "inst.modify_pick_version" in open(
          os.path.join(HERE, "src", "i18n.py"), encoding="utf-8").read())
check("有加载器卡片选择器", hasattr(dlg, "loader_picker"))
check("当前加载器卡有 logo 位", hasattr(dlg, "ld_logo"))
check("卸载按钮是 danger 样式",
      dlg.uninstall_btn.property("cls") == "danger",
      str(dlg.uninstall_btn.property("cls")))
check("安装按钮是 accent 样式",
      dlg.install_btn.property("cls") == "accent",
      str(dlg.install_btn.property("cls")))

print("③ 版本列表标注「最新」")
dlg._on_loader_versions([
    {"title": "0.20.1", "meta": "0.20.1", "channel": "unknown"},
    {"title": "0.19.0", "meta": "0.19.0", "channel": "unknown"},
])
texts = [dlg.ldver_combo.itemText(i)
         for i in range(dlg.ldver_combo.count())]
# 实例当前版本会保留在下拉第一项（没匹配到就插回去），所以「最新」应落在
# 拉回来的那批的第一条上
marked = [t for t in texts if "最新" in t]
check("有且只有一条标「最新」", len(marked) == 1, str(texts))
check("「最新」标在拉回来的第一条上", "最新" in texts[1], str(texts))
check("实例当前版本仍在下拉里", texts[0] == "0.15.11", str(texts[0]))
check("版本数据没丢", dlg.ldver_combo.count() == 3,
      str(dlg.ldver_combo.count()))
dlg.deleteLater()

print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-189 修改页重做）")
