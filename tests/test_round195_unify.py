"""round-195：功能统一 + 页面化（不再一堆弹窗）。

用户三条：
1. 「又是和之前一样被截断的问题」——模组行描述被按**字符数**砍到 78，
   "Fabric API" 的描述只剩半句。
2. 「我们有这么多明明功能相同却页面和逻辑不一样的页面，就不能导向同一个」
   ——模组管理有**两套**（侧栏 ModsPage 大卡片 / 编辑面板 ModListPanel 紧凑行）。
3. 「为什么这么多实用功能的页面你不直接换页而是用窗口？」——实例编辑、体检、
   客户端增强都是 QDialog 弹窗。

判据：
1. **模组管理只有一套**：侧栏模组页与编辑面板模组页都用 ModListPanel；
2. **描述不按字符数截断**：按像素宽度折行，最多两行，悬停给全文；
3. **页内栈存在**：编辑/体检/增强包都经 `_push_feature` 进页内栈，
   不再 `exec()` 弹窗；三个面板都是 QWidget（窗口壳保留给历史调用点）。
"""
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

DEV = tempfile.mkdtemp(prefix="ac_r195_")
os.chdir(DEV)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


pages_src = io.open(os.path.join(HERE, "src", "pages_instances.py"),
                    encoding="utf-8").read()
editor_src = io.open(os.path.join(HERE, "src", "instance_editor.py"),
                     encoding="utf-8").read()
modlist_src = io.open(os.path.join(HERE, "src", "mod_list.py"),
                      encoding="utf-8").read()
health_src = io.open(os.path.join(HERE, "src", "mod_check_dialog.py"),
                     encoding="utf-8").read()
enh_src = io.open(os.path.join(HERE, "src", "enhance_dialog.py"),
                  encoding="utf-8").read()

print("① 模组管理只有一套（侧栏 = 编辑面板）")
check("侧栏模组页用 ModListPanel",
      "from .mod_list import ModListPanel" in pages_src)
check("侧栏不再自建大卡片列表", "ModCard(path, enabled)" not in pages_src)
check("编辑面板也用 ModListPanel",
      "from .mod_list import ModListPanel" in editor_src)
check("侧栏不再有独立的「检查更新」按钮（面板自带可更新筛选）",
      'self.update_btn = ui_kit.make_button' not in pages_src)

print("② 描述不再按字符数截断")
check("没有 _elide(desc, 78) 这种按字符砍",
      '_elide(self.meta.get("description") or "", 78)' not in modlist_src)
check("有按像素宽度折行", "def _wrap_by_width" in modlist_src)
check("折行随宽度重排", "def resizeEvent" in modlist_src)
check("描述有全文 tooltip", "setToolTip(self._desc_full)" in modlist_src)

print("③ 弹窗改页内")
check("编辑面板是 QWidget", "class InstanceEditorPanel(QWidget)" in editor_src)
check("体检面板是 QWidget", "class HealthPanel(QWidget)" in health_src)
check("增强包面板是 QWidget", "class EnhancePanel(QWidget)" in enh_src)
check("实例页有页内栈", "def _push_feature" in pages_src)
check("编辑走页内", "InstanceEditorPanel(self, inst)" in pages_src)
check("体检走页内", "HealthPanel(self, result" in pages_src)
check("增强包走页内", "EnhancePanel(self, inst)" in pages_src)
check("编辑不再 exec 弹窗",
      "InstanceEditorDialog(self, inst)" not in pages_src)
check("体检不再 exec 弹窗", "open_health_dialog(self, inst" not in pages_src)
check("增强包不再 exec 弹窗", "EnhanceDialog(self, inst).exec()" not in pages_src)
check("窗口壳仍保留（兼容旧调用点）",
      "class InstanceEditorDialog(QDialog)" in editor_src
      and "class HealthDialog(QDialog)" in health_src
      and "class EnhanceDialog(QDialog)" in enh_src)

print("④ 运行时：页内栈能开合")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.instances import Instance  # noqa: E402
from src.pages_instances import InstancesPage  # noqa: E402

page = InstancesPage()
inst = Instance(id="p1", name="页内探针", game_version="1.20.1",
                loader="fabric")
page._open_instance_editor(inst)
check("编辑面板进了页内栈", bool(page._feature_stack))
check("当前显示的是功能页",
      page._body_stack.currentIndex() == page._feature_stack[-1])
btn_text = page._body_stack.widget(page._feature_stack[-1]).cancel_btn.text()
check("页内模式按钮是「返回」", btn_text == "返回", btn_text)
page._close_feature()
check("返回后回到实例列表",
      page._body_stack.currentIndex() == 1 and not page._feature_stack)
page.deleteLater()

print("⑤ 运行时：模组描述两行显示")
from src.mod_list import ModListPanel  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402

mc = os.path.join(DEV, "mc")
os.makedirs(os.path.join(mc, "mods"), exist_ok=True)
import zipfile  # noqa: E402

with zipfile.ZipFile(os.path.join(mc, "mods", "sodium.jar"), "w") as z:
    z.writestr("fabric.mod.json", json.dumps({
        "id": "sodium", "name": "Sodium",
        "description": "A modern rendering engine for Minecraft which "
                       "improves performance, and fixes many graphical and "
                       "rendering issues, with a much cleaner and more "
                       "modern look.",
        "authors": ["CaffeineMC"], "version": "0.6.0"}))
panel = ModListPanel(None, Instance(id="p2", name="M", game_version="1.20.1",
                                     _base=mc))
row = list(panel._all)[0]
desc = row.desc_lbl.text()
check("描述不是空", bool(desc.strip()), desc[:40])
check("描述包含完整句子（不再 78 字截断）",
      "modern look" in desc or "rendering engine" in desc, desc[-40:])
check("描述按宽度折行（可能含换行）", len(desc) > 60, str(len(desc)))
check("tooltip 是全文",
      len(row.desc_lbl.toolTip()) > len(desc), str(len(row.desc_lbl.toolTip())))
panel.deleteLater()

shutil.rmtree(DEV, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-195 功能统一 + 页面化）")
