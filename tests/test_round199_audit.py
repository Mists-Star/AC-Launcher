"""round-199：全项目六维审计（弹窗/多套实现 + 截断/反馈）后的补漏。

审计遗留登记项（round-197 之后仍挂着）逐条核对现状并修掉：

1. **商店详情页没有「已安装」标记** —— 列表卡片有，进详情反而看不到。
   判定收进 `core/mod_sources.is_installed`，列表 / 详情 / 前置检查共用一套。
2. **商店列表卡片没有兼容性徽章** —— 详情页有 `_compat_of`，列表没有。
   Modrinth 搜索命中自带 `versions` / `categories`，不额外发请求就能判。
3. **两个诊断面板共用 `diag.title`** —— i18n 同字典里重复键，后写的覆盖
   前一个；启动诊断的「— {name}」被吃掉。拆成 `diag.launch_title`。
4. **实例编辑「内容」页没有来源标记** —— 资源包 / 光影只有文件名，
   看不出是资源中心下的还是手动放的。
5. 顺带：`store_detail._dep_installed` 仍是「标题前 8 字符包含匹配」
   （Sodium 命中 sodium-extra.jar）；详情简介按 240 字符硬切、原文按 1200
   字符硬切；详情下载的来源记录落到旧 `_inst` 而不是实际写入的实例；
   实例页「崩溃分析」菜单仍开 `CrashAnalyzerDialog` 弹窗（同功能已有页内面板）。
"""
import io
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DEV = tempfile.mkdtemp(prefix="ac_r199_")
os.chdir(DEV)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    return io.open(os.path.join(HERE, "src", rel), encoding="utf-8").read()


i18n_src = read("i18n.py")
browse_src = read("pages_browse.py")
detail_src = read("store_detail.py")
editor_src = read("instance_editor.py")
pages_src = read("pages_instances.py")
sources_src = read("core/mod_sources.py")
launch_src = read("launch_diagnostics_dialog.py")
net_src = read("net_api.py")

print("① 「已安装」判定只有一套")
check("mod_sources 有 is_installed", "def is_installed(" in sources_src)
check("列表页调用公共判据",
      "mod_sources.is_installed(" in browse_src)
check("详情页调用公共判据",
      "mod_sources.is_installed(" in detail_src)
check("不再有 title[:8] 包含匹配",
      "title[:8] in fn.lower()" not in detail_src
      and "title[:8] in fn.lower()" not in browse_src)
check("禁用 jar（.jar.disabled）也能判已装",
      "low[:-13]" in sources_src)

print("② 商店详情页「已安装」标记")
check("详情页有 _installed", "def _installed(self)" in detail_src)
check("详情页有刷新方法", "def _refresh_installed_tag" in detail_src)
check("头部有已安装徽章", "self.installed_tag = ui_kit.tag(" in detail_src)
check("切换下载目标时刷新",
      "self.target_combo.currentIndexChanged.connect" in detail_src)

print("③ 商店列表兼容性徽章")
check("列表页有 _compat_of_card", "def _compat_of_card" in browse_src)
check("卡片渲染徽章", "t(\"store.compat_tag\")" in browse_src)
check("搜索命中带支持版本", "\"game_versions\": [str(x) for x in (h.get(\"versions\")" in net_src)
check("搜索命中带加载器", "_STORE_LOADER_TAGS" in net_src)
check("i18n 有兼容/不兼容（中英各一）",
      i18n_src.count('"store.compat_tag"') == 2
      and i18n_src.count('"store.incompat_tag"') == 2)
check("不兼容文案不再歧义",
      "只支持 {loader} 以外的环境" not in i18n_src)

print("④ 两个诊断面板标题分键")
check("启动诊断改用 diag.launch_title",
      't("diag.launch_title"' in launch_src)
check("diag.title 只剩一份（中英各一）",
      i18n_src.count('"diag.title"') == 2)
check("diag.launch_title 中英各一",
      i18n_src.count('"diag.launch_title"') == 2)

print("⑤ 实例编辑「内容」页来源标记")
check("内容页读来源", "mod_sources.source_of(self._inst, n)" in editor_src)
check("资源包/光影才标来源", "\"resourcepacks\"" in editor_src and "shaderpacks" in editor_src)
check("文件名存 UserRole", "item.setData(Qt.UserRole, n)" in editor_src)
check("删除用 UserRole 而不是显示文本",
      "name = item.data(Qt.UserRole) or item.text()" in editor_src)

print("⑥ 崩溃分析统一为页内面板")
check("实例页不再 exec CrashAnalyzerDialog",
      "CrashAnalyzerDialog(inst=inst, parent=self).exec()" not in pages_src)
check("_show_crash 由一级入口调用", 'lambda: self._show_crash(inst)' in pages_src)
check("关闭面板后刷新", "panel.closed.connect(_done)" in pages_src)

print("⑦ 截断与来源记录")
check("详情简介不再按 240 字符硬切",
      "self._short(card.get(\"description\", \"\"), 240)" not in detail_src)
check("详情简介 tooltip 给全文", "self.desc.setToolTip(self._desc_full)" in detail_src)
check("详情原文不再截到 1200", "src[:1200]" not in detail_src)
check("来源记录用实际写入实例", "_dl_inst" in detail_src)

print("⑧ 运行时验证")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.core import mod_sources  # noqa: E402
from src.pages_browse import StorePage  # noqa: E402


class _Inst:
    id = "i199"
    mods_dir = os.path.join(DEV, "mods")
    game_version = "1.20.1"
    loader = "fabric"


inst = _Inst()
os.makedirs(inst.mods_dir, exist_ok=True)
check("空实例 → 未安装", mod_sources.is_installed(inst, title="Sodium") is False)

# 只有 sodium-extra.jar：不是 Sodium 本身
io.open(os.path.join(inst.mods_dir, "sodium-extra-0.6.jar"), "w").close()
check("sodium-extra 不冒充 Sodium",
      mod_sources.is_installed(inst, title="Sodium", slug="sodium") is False)
io.open(os.path.join(inst.mods_dir, "sodium-fabric-0.5.8.jar"), "w").close()
check("sodium-fabric-0.5.8 判已装（加载器后缀）",
      mod_sources.is_installed(inst, title="Sodium", slug="sodium") is True)
io.open(os.path.join(inst.mods_dir, "sodium-0.5.8.jar"), "w").close()
check("sodium-0.5.8 判已装",
      mod_sources.is_installed(inst, title="Sodium", slug="sodium") is True)

mod_sources.record(inst, [{"filename": "renamed-mod.jar",
                           "project_id": "P123", "slug": "jei",
                           "title": "Just Enough Items"}])
check("来源记录按 project_id 命中",
      mod_sources.is_installed(inst, project_id="P123") is True)

dis = _Inst()
dis.id = "i199b"
dis.mods_dir = os.path.join(DEV, "mods_dis")
os.makedirs(dis.mods_dir, exist_ok=True)
io.open(os.path.join(dis.mods_dir, "create-0.5.jar.disabled"), "w").close()
check("禁用模组也算已装",
      mod_sources.is_installed(dis, title="Create") is True)

# 兼容徽章：纯逻辑（不构造整个 StorePage）
fake = types.SimpleNamespace(_current_inst=lambda: inst)
ok, reason = StorePage._compat_of_card(fake, {
    "game_versions": ["1.20.1"], "loaders": ["fabric"]})
check("同版本同加载器 → 兼容", ok is True, reason)
ok, reason = StorePage._compat_of_card(fake, {
    "game_versions": ["1.19.2"], "loaders": ["fabric"]})
check("MC 版本不符 → 不兼容", ok is False, reason)
ok, reason = StorePage._compat_of_card(fake, {
    "game_versions": ["1.20.1"], "loaders": ["forge"]})
check("加载器不符 → 不兼容", ok is False, reason)
check("没有版本数据 → 不画徽章（None）",
      StorePage._compat_of_card(fake, {}) is None)

print("\n%s" % ("ALL PASS" if not fails else "FAILED: %s" % ", ".join(fails)))
sys.exit(1 if fails else 0)
