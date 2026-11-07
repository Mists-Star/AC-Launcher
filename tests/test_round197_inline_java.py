"""round-197：崩溃分析页内化 / Java 管理三入口合一 / 整合包来源记录。

承接 round-196 登记的 7 条未修，本轮做其中 3 条：

1. **崩溃分析页内化**（最后一个还在弹窗的实例功能）；
2. **Java 管理三入口合一**：设置页内嵌唯一的管理 UI；新建向导改成文件选择器；
   崩溃分析改成跳设置页 Java 分区；
3. **整合包 / 导入的模组来源记录**：这些 jar 没有可靠 project_id，但来源要
   标出来（「整合包」/「导入」），不能和手动放入的混在一起。

顺带修了两个「壳包面板」的结构性坑：
* `__setattr__` 也要转发（只转发读取 → `dlg._dl_phase = x` 设在壳上，面板读
  自己的 → 状态行永远停在旧状态）；
* QDialog 自带 `done()` 会**遮蔽**面板同名方法 → 必须显式转发；且转发会
  形成递归（面板 done → closed → 壳 accept → 壳 done → 面板 done）→ 要守卫。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

DEV = tempfile.mkdtemp(prefix="ac_r197_")
os.chdir(DEV)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


crash_src = io.open(os.path.join(HERE, "src", "crash_dialog.py"),
                    encoding="utf-8").read()
java_src = io.open(os.path.join(HERE, "src", "java_manager_dialog.py"),
                   encoding="utf-8").read()
settings_src = io.open(os.path.join(HERE, "src", "settings_dialog.py"),
                       encoding="utf-8").read()
pages_src = io.open(os.path.join(HERE, "src", "pages_instances.py"),
                    encoding="utf-8").read()
pack_src = io.open(os.path.join(HERE, "src", "modpack_import.py"),
                   encoding="utf-8").read()
sources_src = io.open(os.path.join(HERE, "src", "core", "mod_sources.py"),
                      encoding="utf-8").read()
modlist_src = io.open(os.path.join(HERE, "src", "mod_list.py"),
                      encoding="utf-8").read()

print("① 崩溃分析页内化")
check("面板是 QWidget", "class CrashAnalyzerPanel(QWidget)" in crash_src)
check("窗口壳保留", "class CrashAnalyzerDialog(QDialog)" in crash_src)
check("实例页走页内栈",
      "CrashAnalyzerPanel(inst, parent=self)" in pages_src
      and "CrashDialog(inst, parent=self).exec()" not in pages_src)
check("frameless 只在窗口模式",
      "def enable_window_chrome" in crash_src)

print("② Java 管理三入口合一")
check("面板是 QWidget", "class JavaManagerPanel(QWidget)" in java_src)
check("设置页内嵌面板",
      "JavaManagerPanel(self" in settings_src
      and "_java_host" in settings_src)
check("向导改用文件选择器（不再弹管理器）",
      "pick_files(self, t(\"new_instance.java_pick_title\")" in pages_src
      and "JavaManagerDialog(self, current_path=self._java_path)" not in pages_src)
check("崩溃分析跳设置页 Java 分区",
      "_select_settings_section" in crash_src)
check("三处不再各开一个管理器",
      pages_src.count("JavaManagerDialog(") == 0
      or "JavaManagerDialog(" not in pages_src)

print("③ 壳包面板的结构性坑")
for name, src in (("java", java_src), ("crash", crash_src)):
    check("%s 壳有 __setattr__ 转发" % name,
          "def __setattr__(self, name, value)" in src)
    check("%s 壳有 closeEvent 转发" % name, "def closeEvent(self, ev)" in src)
check("Java 壳显式转发 done()（QDialog 自带同名会遮蔽）",
      "def done(self, r):" in java_src)
check("done 转发有递归守卫",
      "_in_done" in java_src)

print("④ 来源记录：整合包 / 导入")
check("record 不再强制要求 project_id",
      "if not pid and not slug and not title:" in sources_src)
check("有 source_of 查询", "def source_of(" in sources_src)
check("mrpack 导入登记来源", "_record_pack_sources(inst, source=\"modpack\"" in pack_src)
check("导入实例登记来源", "source=\"imported\"" in pack_src)
check("列表按来源分标",
      "mods.from_pack" in modlist_src and "mods.from_import" in modlist_src)

print("⑤ 运行时验证")
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.instances import Instance  # noqa: E402
from src.core import mod_sources  # noqa: E402
from src.mod_list import ModListPanel  # noqa: E402

inst = Instance(id="pk", name="整合包实例", game_version="1.20.1",
                loader="fabric")
mc = os.path.join(DEV, "mc")
os.makedirs(os.path.join(mc, "mods"), exist_ok=True)
for jar in ("sodium.jar", "pack.jar"):
    with zipfile.ZipFile(os.path.join(mc, "mods", jar), "w") as z:
        z.writestr("fabric.mod.json", json.dumps(
            {"id": jar[:-4], "name": jar[:-4], "version": "1.0",
             "description": "test mod"}))
n = mod_sources.record(inst, [
    {"filename": "sodium.jar", "project_id": "AANobbMI", "slug": "sodium",
     "source": "modrinth"},
    {"filename": "pack.jar", "project_id": "", "title": "整合包实例",
     "source": "modpack"},
])
check("没有 project_id 也能登记", n == 2, str(n))
check("source_of 读出 modpack",
      mod_sources.source_of(inst, "pack.jar") == "modpack",
      mod_sources.source_of(inst, "pack.jar"))

inst2 = Instance(id="pk2", name="P", game_version="1.20.1", _base=mc)
mod_sources.record(inst2, [
    {"filename": "sodium.jar", "project_id": "AANobbMI", "slug": "sodium",
     "source": "modrinth"},
    {"filename": "pack.jar", "project_id": "", "title": "整合包实例",
     "source": "modpack"},
])
panel = ModListPanel(None, inst2)
rows = {os.path.basename(r.path): r for r in panel._all}
pills = [w.text() for w in rows["pack.jar"].findChildren(QLabel)]
check("整合包的 jar 带「整合包」标", "整合包" in pills, str(pills))
pills2 = [w.text() for w in rows["sodium.jar"].findChildren(QLabel)]
check("资源中心的 jar 带「资源中心」标", "资源中心" in pills2, str(pills2))
panel.deleteLater()

from src.pages_instances import InstancesPage  # noqa: E402

page = InstancesPage()
i2 = Instance(id="cr1", name="崩溃实例", game_version="1.20.1", loader="fabric")
page._show_crash(i2)
check("崩溃分析进了页内栈", len(page._feature_stack) == 1)
page._close_feature()
from src.crash_dialog import CrashAnalyzerPanel  # noqa: E402

cp = CrashAnalyzerPanel(i2)
check("崩溃分析面板能构造", cp is not None)
check("面板有 closed 信号", hasattr(cp, "closed"))
cp.deleteLater()
page.deleteLater()

shutil.rmtree(DEV, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-197 崩溃分析页内 / Java 合一 / 来源记录）")
