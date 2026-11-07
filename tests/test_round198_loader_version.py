"""round-198：修改页加载器版本的「继承 / 看不到」问题。

用户：「在所有修改选项加载器版本会随着第一个你所选择的版本而切换，而且就算根本
不存在也会继承，而且看不到版本」。

三个症状，一个根因（外加两个放大器）：

1. **继承**：`_on_loader_versions` 里 `keep`（上一个 MC 版本的加载器版本）
   在新列表里找不到时，**硬插回下拉第一项**（`insertItem(0, keep, keep)`）——
   那个版本在新 MC 版本下根本不存在，玩家看到它还在就以为能用。
2. **看不到版本**：列表为空时，下拉里只剩那个继承来的值（或完全空白），
   玩家看不到"到底有哪些版本"，也不知道是空的。
3. **保存会清字段**：列表为空时 `_collect` 把 `loader_version` 写成空 ——
   「这个 MC 版本装不了这个加载器」不等于「把这个加载器版本删掉」。

修法：
* 空列表 → 下拉里写明「（该 MC 版本没有可用版本）」+ 禁用 + 不插旧值；
* 旧值不在新列表 → 选**最新的**，并在提示里说明换了（原值不适用于该 MC）；
* 保存时列表为空 → **保留**实例原有的 loader_version。
* 新建实例向导同样问题：空列表时它会显示「最新稳定版（推荐）」→ 装了才知道
  没版本。现在写明并禁用。
"""
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

DEV = tempfile.mkdtemp(prefix="ac_r198_")
os.chdir(DEV)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


editor_src = io.open(os.path.join(HERE, "src", "instance_editor.py"),
                     encoding="utf-8").read()
pages_src = io.open(os.path.join(HERE, "src", "pages_instances.py"),
                    encoding="utf-8").read()

print("① 不再把不存在的旧版本硬插回下拉")
check("没有 insertItem(0, keep, keep)",
      "insertItem(0, keep, keep)" not in editor_src)
check("空列表走独立分支", "if n == 0:" in editor_src)
check("空列表时写明原因", "inst.loader_ver_empty_item" in editor_src)
check("空列表时禁用下拉", "self.ldver_combo.setEnabled(False)" in editor_src)
check("旧值不在列表 → 选最新并说明",
      "inst.loader_ver_switched" in editor_src)

print("② 保存时不覆盖实例已有的加载器版本")
check("_collect 有空列表保护",
      'getattr(self, "_ldver_available", True)' in editor_src)
check("有 _ldver_available 标记", "self._ldver_available" in editor_src)

print("③ 新建向导同样修")
check("向导空列表不再假装有版本",
      "if not rows:" in pages_src
      and 'inst.loader_ver_empty_item' in pages_src)

print("④ 运行时验证")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.instances import Instance  # noqa: E402
from src.instance_editor import InstanceEditorPanel  # noqa: E402

inst = Instance(id="ld", name="加载器版本测试", game_version="1.20.1",
                loader="fabric", loader_version="0.15.11")
panel = InstanceEditorPanel(None, inst)

# 场景 A：新列表为空（该 MC 版本没有这个加载器）
panel._on_loader_versions([])
check("空列表 → 下拉禁用", not panel.ldver_combo.isEnabled())
check("空列表 → 下拉里写明没有版本",
      "没有可用版本" in panel.ldver_combo.currentText(),
      panel.ldver_combo.currentText())
check("空列表 → 不插回旧版本",
      panel.ldver_combo.findData("0.15.11") < 0,
      str([panel.ldver_combo.itemData(i)
           for i in range(panel.ldver_combo.count())]))
check("空列表 → 提示说明不是网络问题",
      "没有这个加载器的可用版本" in panel.ldver_hint.text(),
      panel.ldver_hint.text())
check("空列表 → 安装按钮禁用", not panel.install_btn.isEnabled())
check("空列表 → 标记不可用", panel._ldver_available is False)

# 保存时不能把实例的 loader_version 清空
before = inst.loader_version
panel._collect(trigger=False)
check("保存后原加载器版本没被清空",
      inst.loader_version == before == "0.15.11", str(inst.loader_version))

# 场景 B：新列表有值但不含旧值
panel._on_loader_versions([
    {"title": "0.20.1", "meta": "0.20.1", "channel": "unknown"},
    {"title": "0.19.0", "meta": "0.19.0", "channel": "unknown"},
])
check("有列表 → 下拉恢复可用", panel.ldver_combo.isEnabled())
check("有列表 → 选最新",
      panel.ldver_combo.currentData() == "0.20.1",
      str(panel.ldver_combo.currentData()))
check("有列表 → 提示说明换了版本",
      "不适用于" in panel.ldver_hint.text(), panel.ldver_hint.text())
check("有列表 → 标记可用", panel._ldver_available is True)

# 场景 C：新列表含旧值 → 保留旧值
panel._on_loader_versions([
    {"title": "0.15.11", "meta": "0.15.11", "channel": "unknown"},
    {"title": "0.14.0", "meta": "0.14.0", "channel": "unknown"},
])
check("旧值仍在列表 → 保留旧值",
      panel.ldver_combo.currentData() == "0.15.11",
      str(panel.ldver_combo.currentData()))
panel.deleteLater()

shutil.rmtree(DEV, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-198 加载器版本继承/空列表）")
