"""round-196：全面审计后的补漏。

审计范围 = round-189..195 这几轮的所有整改与统一，逐条复查。发现并修掉：

1. **toast 根因没根治**（round-194 只修了体检那一个调用点）：
   `win_rounded.toast()` 只查 `parent.window()` 的 `show_toast` → 同一个页内面板
   在「页内」能弹浮层、在「弹窗壳」里退化成模态框，**两态行为不一致**。
   现在沿 parent 链向上找最近的浮层宿主。
2. **「全部」源两源不判重**：同一个 mod（JEI…）在 Modrinth 和 CF 都有 → 商店
   连着出两张几乎一样的卡。
3. **导出整合包页内套窗口**：实例编辑面板（页内）里点导出 → `exec()` 弹窗。
   现在发信号，由实例页用**同一个页内栈**打开（栈是真栈，能逐级返回）。
4. **硬截断残留**：崩溃详情 `[:220]`、增强包错误 `[:120]` → 半句话。
5. **「已安装」误报**：按标题前 8 字符包含匹配 → "Sodium" 命中 "sodium-extra.jar"。
6. **加载器选择器两套**：新建向导 `_LoaderCard` vs 修改页 `LoaderPicker` →
   合并成 `src/loader_picker.py` 一套（沿用新建向导那套更完整的视觉）。
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

DEV = tempfile.mkdtemp(prefix="ac_r196_")
os.chdir(DEV)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


win_src = io.open(os.path.join(HERE, "src", "win_rounded.py"),
                  encoding="utf-8").read()
net_src = io.open(os.path.join(HERE, "src", "net_api.py"), encoding="utf-8").read()
pages_src = io.open(os.path.join(HERE, "src", "pages_instances.py"),
                    encoding="utf-8").read()
editor_src = io.open(os.path.join(HERE, "src", "instance_editor.py"),
                     encoding="utf-8").read()
export_src = io.open(os.path.join(HERE, "src", "export_pack_dialog.py"),
                     encoding="utf-8").read()
crash_src = io.open(os.path.join(HERE, "src", "crash_dialog.py"),
                    encoding="utf-8").read()

print("① toast 根因：沿 parent 链找浮层宿主")
check("有 _find_toast_host", "def _find_toast_host" in win_src)
check("不再只看 window()",
      "win = parent.window() if parent is not None else None" not in win_src)
check("toast 用新的查找", "show = _find_toast_host(parent)" in win_src)

print("② 「全部」源两源判重")
check("有 _dedupe_two_sources", "def _dedupe_two_sources" in net_src)
check("search_all 走判重",
      "return _dedupe_two_sources(mr, cf)" in net_src)

print("③ 导出整合包页内化")
check("导出面板是 QWidget", "class ExportPackPanel(QWidget)" in export_src)
check("编辑面板不再 exec 弹窗",
      "ExportPackDialog(self, self._inst).exec()" not in editor_src)
check("编辑面板发信号", "exportRequested" in editor_src)
check("实例页接信号并走页内栈",
      "exportRequested.connect" in pages_src
      and "def _open_export_pack" in pages_src)
check("页内栈是真栈（能逐级返回）",
      "self._feature_stack: list[int]" in pages_src
      and "if stack:" in pages_src)

print("④ 硬截断残留")
check("崩溃详情不再 [:220]", "[:220]" not in crash_src)
check("崩溃详情完整显示 + tooltip",
      "det.setToolTip(finding.detail.strip())" in crash_src)
enh_src = io.open(os.path.join(HERE, "src", "enhance_dialog.py"),
                  encoding="utf-8").read()
check("增强包错误不再 [:120]", "[:120]" not in enh_src)

print("⑤ 「已安装」判定收紧")
check("不再用标题前 8 字符包含匹配",
      "title[:8] in fn.lower()" not in pages_src)
# round-199：前缀判据已从页面收到 core/mod_sources.is_installed（行为不变）
src_src = io.open(os.path.join(HERE, "src", "core", "mod_sources.py"),
                  encoding="utf-8").read()
check("前缀判据收在 mod_sources", "stem.startswith(c + sep)" in src_src)

print("⑥ 加载器选择器只有一套")
check("pages_instances 不再定义 _LoaderCard",
      "class _LoaderCard(QFrame)" not in pages_src)
check("新建向导用统一组件",
      "from .loader_picker import LoaderCard as _LCard" in pages_src)
picker_src = io.open(os.path.join(HERE, "src", "loader_picker.py"),
                     encoding="utf-8").read()
check("统一组件带选中对勾", "state_pix(\"done\"" in picker_src)
check("统一组件走 QSS 类", "loader-card-on" in picker_src)

print("⑦ 运行时验证")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.net_api import _dedupe_two_sources  # noqa: E402

mr = [{"slug": "jei", "title": "Just Enough Items", "source": "modrinth"},
      {"slug": "sodium", "title": "Sodium", "source": "modrinth"}]
cf = [{"slug": "jei", "title": "JEI", "source": "curseforge"},
      {"slug": "fabric-api", "title": "Fabric API", "source": "curseforge"}]
out = _dedupe_two_sources(mr, cf)
check("同名项目只留一张", len(out) == 3, str([h["title"] for h in out]))
check("保留 Modrinth 那张",
      any(h["slug"] == "jei" and h["source"] == "modrinth" for h in out))

from src.win_rounded import _find_toast_host  # noqa: E402
from src.pages_instances import InstancesPage  # noqa: E402
from src.instances import Instance  # noqa: E402

page = InstancesPage()
inst = Instance(id="a1", name="栈测试", game_version="1.20.1", loader="fabric")
page._open_instance_editor(inst)
check("编辑面板进栈", len(page._feature_stack) == 1)
# 模拟「从编辑面板打开导出」→ 栈变两层
from src.export_pack_dialog import ExportPackPanel  # noqa: E402

exp = ExportPackPanel(page, inst)
page._push_feature(exp)
check("导出面板叠在编辑面板之上", len(page._feature_stack) == 2)
page._close_feature()
check("返回后回到编辑面板（不是列表）",
      page._body_stack.currentIndex() == page._feature_stack[-1]
      and len(page._feature_stack) == 1)
page._close_feature()
check("再返回才回到列表",
      page._body_stack.currentIndex() == 1 and not page._feature_stack)
page.deleteLater()

shutil.rmtree(DEV, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-196 全面审计补漏）")
