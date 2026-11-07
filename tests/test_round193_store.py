"""round-193：资源中心重做（版本随实例 / 前置可见 / 下载可见）。

用户四问：
① 「模组最高版本推荐不是随着我版本加载器来选的有何作用？」
② 「下载为啥不可见？」
③ 「为什么看不到前置模组？」
④ 「为什么不询问/自动补前置模组？」

判据：
1. **推荐版本跟实例走**：不兼容的版本不能当"推荐"；兼容判定按实例的
   MC 版本 + 加载器；
2. **前置可见**：详情页有前置区；required 依赖能取到（Mod Menu → Fabric API）；
3. **下载前询问**：有前置时弹确认；玩家选「否」→ 只下本体（with_deps=False）；
4. **下载可见**：详情页有进度条 + 速度；完成时列出装了哪些文件。
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

DEV = tempfile.mkdtemp(prefix="ac_r193_")
os.chdir(DEV)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.instances import Instance  # noqa: E402
from src.store_detail import StoreDetailPanel  # noqa: E402

print("① 兼容判定：推荐版本必须跟实例走")
inst = Instance(id="i1", name="1.20.1 实例", game_version="1.20.1",
                loader="fabric")
card = {"source": "modrinth", "project_id": "mOgUt4GM", "slug": "modmenu",
        "title": "Mod Menu", "description": "", "downloads": 1,
        "icon_url": "", "author": ""}
panel = StoreDetailPanel(None, card, "mod", inst, "mods")

# 1.21 的版本对 1.20.1 实例不兼容；1.20.1 的兼容
v_121 = {"id": "a", "version_number": "9.0.0", "game_versions": ["1.21"],
         "loaders": ["fabric"], "files": [], "date_published": "2024-01-01"}
v_1201 = {"id": "b", "version_number": "8.0.0", "game_versions": ["1.20.1"],
          "loaders": ["fabric"], "files": [], "date_published": "2023-01-01"}
v_forge = {"id": "c", "version_number": "7.0.0", "game_versions": ["1.20.1"],
           "loaders": ["forge"], "files": [], "date_published": "2022-01-01"}

ok, why = panel._compat_of(v_121)
check("1.21 版本对 1.20.1 实例不兼容", not ok, why)
check("不兼容给出原因（需要 MC 1.20.1）", "1.20.1" in why, why)
ok2, _ = panel._compat_of(v_1201)
check("1.20.1 版本兼容", ok2)
ok3, why3 = panel._compat_of(v_forge)
check("forge 版本对 fabric 实例不兼容", not ok3, why3)

panel._versions = [v_121, v_1201, v_forge]
rec = panel._recommended()
check("推荐版本是兼容的那个（不是最新）",
      rec is not None and rec.get("id") == "b",
      str(rec.get("version_number") if rec else None))

print("② 前置模组可见（Mod Menu 需要 Fabric API）")
deps = panel._deps
check("前置区有内容或已请求", isinstance(deps, list), str(type(deps)))
src = io.open(os.path.join(HERE, "src", "store_detail.py"),
               encoding="utf-8").read()
check("详情页有前置区组件", "self.deps_box" in src)
check("有前置清单接口", "mod_version_dependencies" in src)
check("前置项带 installed 判定", "_dep_installed" in src)

print("③ 下载前询问 + 可选只装本体")
check("有下载前询问", "def _ask_deps" in src)
check("询问默认是「装」", "QMessageBox.Yes" in src)
net = io.open(os.path.join(HERE, "src", "net_api.py"), encoding="utf-8").read()
check("下载函数支持 with_deps", "with_deps: bool = True" in net)
check("only_self 时不下依赖", "only_self=not with_deps" in net)
check("resolve 支持 only_self", "only_self: bool = False" in net)

print("④ 下载可见")
check("详情页有进度条", "self.dl_bar" in src)
check("进度条接了 progress 信号", "w.progress.connect(self._on_dl_progress)" in src)
check("速度接了 speed 信号", "self.dl_speed.setText(s)" in src)
check("完成时列出装了哪些文件", "store.installed_files" in src)

print("⑤ 列表页标「已安装」")
browse = io.open(os.path.join(HERE, "src", "pages_browse.py"),
                  encoding="utf-8").read()
check("卡片有已安装标记", "store.installed_tag" in browse)
check("已装判定用来源记录", "mod_sources.load(inst)" in browse)

print("⑥ 数据层：依赖清单接口")
net2 = io.open(os.path.join(HERE, "src", "net_api.py"), encoding="utf-8").read()
check("mod_version_dependencies 存在",
      "def mod_version_dependencies" in net2)
check("只列 required 依赖", 'dtype != "required"' in net2)

panel.deleteLater()
shutil.rmtree(DEV, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-193 资源中心：版本随实例 / 前置 / 下载可见）")
