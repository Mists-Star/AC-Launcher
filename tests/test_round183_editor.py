"""round-183：PCL 式编辑面板 + 加载器真装真卸 + 新建向导 pcl 格式。

用户拍板范围：「新建整页编辑面板，左侧分组导航，加载器真装真卸，模组增删
启停内嵌不跳页；新建向导补启动格式下拉与 pcl 枚举」。

判据分四层：

1. **结构**：面板存在、七个页齐、旧长条被替换、右键有入口；
2. **文案**：面板里所有 `t("…")` 用到的键都在 zh/en 两份表里（漏键是真机
   空白文案的根因，静态就能抓）；
3. **安全**：`loader_swap` 只删本实例 versions 下的目录，外来实例拒绝卸，
   装失败必须回滚字段；
4. **运行时**：真开一次面板（offscreen）、保存真的写回实例。
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
# 数据目录隔离：manager 单例在 import 时就定型，必须先设环境变量
os.environ["AC_DEV_TEMP"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with io.open(os.path.join(HERE, rel), "r", encoding="utf-8") as fh:
        return fh.read()


# ──────────────────────────────────────────────────────────────
print("① 结构：面板 / 页 / 入口")

editor_src = read("src/instance_editor.py")
pages_src = read("src/pages_instances.py")
swap_src = read("src/core/loader_swap.py")

check("instance_editor.py 定义 InstanceEditorDialog",
      "class InstanceEditorDialog(QDialog)" in editor_src)
for key in ("basic", "launch", "modify", "java", "dir", "mods", "content",
            "adv"):
    check("有 %-8s 页构建函数" % key, "def _page_%s(" % key in editor_src)

nav_keys = re.findall(r'\("(\w+)", "inst\.tab_(\w+)", "(\w+)"\)', editor_src)
check("导航项 8 个", len(nav_keys) == 8, str(len(nav_keys)))
check("导航项与页函数一一对应",
      {k for k, _t, _i in nav_keys} == {"basic", "launch", "modify", "java",
                                        "dir", "mods", "content", "adv"})
# PCL 的「修改」页是**换加载器**的操作页，不是字段表单：
# 加载器下拉与装卸按钮必须落在这个页里，不能再混在「启动」页。
_mod_body = editor_src.split("def _page_modify(", 1)[-1].split(
    "def _page_java(", 1)[0]
check("修改页含加载器下拉", "self.loader_combo" in _mod_body)
check("修改页含安装按钮", "self.install_btn" in _mod_body)
check("修改页含卸载按钮", "self.uninstall_btn" in _mod_body)
_launch_body = editor_src.split("def _page_launch(", 1)[-1].split(
    "def _page_modify(", 1)[0]
check("启动页不再放加载器下拉", "loader_combo" not in _launch_body)

check("旧 480x620 长条已退役（不再 resize(480, 620)）",
      "resize(480, 620)" not in pages_src)
check("_edit_instance_settings 改开新面板",
      "from .instance_editor import InstanceEditorDialog" in pages_src)
check("右键菜单有「编辑实例」",
      't("instances.edit_instance")' in pages_src)
# round-185：模组页改用 ModListPanel（不再是 ModCard 大卡片列表）
check("面板内嵌模组列表（ModListPanel）",
      "from .mod_list import ModListPanel" in editor_src)
check("面板内嵌加载器真装/真卸",
      "swap_loader" in editor_src and "uninstall_loader" in editor_src)

print("② 文案：面板用到的键必须在两份表里")
import src.i18n as I  # noqa: E402

zh, en = I._STRINGS["zh-CN"], I._STRINGS["en-US"]
used = set(re.findall(r'\bt\(\s*"([^"{}]+)"', editor_src))
used |= set(re.findall(r'_t\(\s*"([^"{}]+)"', editor_src))
# 动态拼接的键（如 t("instances.fmt_" + fmt)）正则只能抓到前缀，
# 这里剔除前缀项，改由下面两组完整键逐项校验。
used = {k for k in used if not k.endswith(("_", "."))}
# 动态拼接的格式键单独校验
used |= {"instances.fmt_" + k for k in
         ("ac", "vanilla", "iso", "multimc", "curseforge", "modrinth",
          "pcl", "custom", "auto")}
used |= {"new_instance.dir_" + k for k in
         ("ac", "vanilla", "iso", "pcl", "custom")}
missing_zh = sorted(k for k in used if k not in zh)
missing_en = sorted(k for k in used if k not in en)
check("面板文案无漏键（zh）", not missing_zh, str(missing_zh[:6]))
check("面板文案无漏键（en）", not missing_en, str(missing_en[:6]))
check("zh / en 键数一致", len(zh) == len(en), "%d / %d" % (len(zh), len(en)))

print("③ 格式枚举：pcl 已接入三处")
from src.instances import INSTANCE_FORMATS, detect_format  # noqa: E402

check("INSTANCE_FORMATS 含 pcl", "pcl" in INSTANCE_FORMATS,
      str(INSTANCE_FORMATS))
check("i18n 有 instances.fmt_pcl（zh）", "instances.fmt_pcl" in zh)
check("i18n 有 instances.fmt_pcl（en）", "instances.fmt_pcl" in en)
check("新建向导 dir 下拉含 pcl",
      '("ac", "vanilla", "iso", "pcl", "custom")' in pages_src)
for k in ("new_instance.dir_pcl", "new_instance.dir_hint_pcl",
          "new_instance.dir_pick_title_pcl", "new_instance.fmt_preview"):
    check("i18n 有 %s" % k, k in zh and k in en)

# ──────────────────────────────────────────────────────────────
print("④ 安全：loader_swap 边界")
from src.core import loader_swap as LS  # noqa: E402
from src.instances import Instance  # noqa: E402

tmp = tempfile.mkdtemp(prefix="ac_r183_")
mc = os.path.join(tmp, ".minecraft")
vroot = os.path.join(mc, "versions")
os.makedirs(os.path.join(mc, "mods"), exist_ok=True)
os.makedirs(os.path.join(mc, "saves", "world1"), exist_ok=True)


def write_version(vid, inherits=""):
    d = os.path.join(vroot, vid)
    os.makedirs(d, exist_ok=True)
    data = {"id": vid}
    if inherits:
        data["inheritsFrom"] = inherits
    with io.open(os.path.join(d, vid + ".json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


write_version("1.20.1")                                   # 原版目录（无 inheritsFrom）
write_version("fabric-loader-0.15.11-1.20.1", "1.20.1")   # 加载器目录
write_version("1.20.1-forge-47.2.0", "1.20.1")            # 另一个加载器

inst = Instance(id="t1", name="T", game_version="1.20.1",
                loader="fabric", loader_version="0.15.11", _base=mc)
check("Instance.mc_dir 指向临时 .minecraft", inst.mc_dir == mc, inst.mc_dir)

ids = LS.loader_version_ids(inst)
check("认得出两个加载器目录", set(ids) == {"fabric-loader-0.15.11-1.20.1",
                                          "1.20.1-forge-47.2.0"}, str(ids))
check("原版目录不在加载器列表里", "1.20.1" not in ids)

cur = LS.current_loader_version_id(inst)
check("current_loader_version_id 命中 fabric",
      cur == "fabric-loader-0.15.11-1.20.1", str(cur))

res = LS.uninstall_loader(inst)
check("卸载成功", bool(res.get("ok")), str(res))
check("删掉的正是 fabric 目录",
      res.get("removed") == ["fabric-loader-0.15.11-1.20.1"], str(res.get("removed")))
check("forge 目录没被误删",
      os.path.isdir(os.path.join(vroot, "1.20.1-forge-47.2.0")))
check("原版目录没被误删", os.path.isdir(os.path.join(vroot, "1.20.1")))
check("mods / saves 保留",
      os.path.isdir(os.path.join(mc, "mods"))
      and os.path.isdir(os.path.join(mc, "saves", "world1")))
check("字段退回 vanilla",
      inst.loader == "vanilla" and inst.loader_version == "")

res2 = LS.uninstall_loader(inst)
check("已是原版时返回 no_loader", res2.get("reason") == "no_loader", str(res2))

ext = Instance(id="t2", name="E", game_version="1.20.1", loader="forge",
               loader_version="47.2.0", _base=mc, external=True)
res3 = LS.uninstall_loader(ext)
check("外来实例拒绝卸载", res3.get("reason") == "external", str(res3))
check("外来实例的文件确实没动",
      os.path.isdir(os.path.join(vroot, "1.20.1-forge-47.2.0")))

# 越界防护：把 vid 伪造成 ../ 跳出 versions
guard_ok = False
try:
    guarded = LS._remove_version_dir(inst, os.path.join("..", "mods"))
    guard_ok = (guarded[0] is False) and os.path.isdir(os.path.join(mc, "mods"))
except Exception:  # noqa: BLE001
    guard_ok = False
check("路径越界被拒（mods 还在）", guard_ok)

print("⑤ 装失败必须回滚字段")
from src.core import install as INST  # noqa: E402

orig_install = INST.install_instance


def boom(*_a, **_kw):
    raise RuntimeError("network down")


INST.install_instance = boom
rolled = Instance(id="t3", name="R", game_version="1.20.1",
                  loader="vanilla", loader_version="", _base=mc)
try:
    LS.swap_loader(rolled, "forge", "47.2.0")
    raised = False
except RuntimeError:
    raised = True
finally:
    INST.install_instance = orig_install

check("装失败向上抛", raised)
check("字段回滚到原值",
      rolled.loader == "vanilla" and rolled.loader_version == "", 
      "%s / %s" % (rolled.loader, rolled.loader_version))

print("⑥ PCL2 特征识别")
pcl_mc = os.path.join(tmp, "pcl", ".minecraft")
os.makedirs(os.path.join(pcl_mc, "versions", "1.20.1"), exist_ok=True)
os.makedirs(os.path.join(pcl_mc, "PCL"), exist_ok=True)
with io.open(os.path.join(pcl_mc, "versions", "1.20.1", "1.20.1.json"),
             "w", encoding="utf-8") as fh:
    json.dump({"id": "1.20.1"}, fh)
with io.open(os.path.join(pcl_mc, "PCL", "Setup.ini"), "w", encoding="utf-8") as fh:
    fh.write("[Setup]\n")

pcl_inst = Instance(id="t4", name="P", game_version="1.20.1",
                    format="auto", _base=pcl_mc, external=True)
check("PCL2 目录识别为 pcl", detect_format(pcl_inst) == "pcl",
      detect_format(pcl_inst))

print("⑦ 运行时：真开一次面板并保存")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.instance_editor import InstanceEditorDialog  # noqa: E402

live = Instance(id="t5", name="原名称", game_version="1.20.1",
                loader="fabric", loader_version="0.15.11",
                ram_mb=2048, jvm_args="-Xmx2G", _base=mc)
dlg = InstanceEditorDialog(None, live)
check("面板能实例化", dlg is not None)
check("八个页都建出来了", dlg.stack.count() == 8, str(dlg.stack.count()))
check("导航行数 = 8", dlg.nav.count() == 8, str(dlg.nav.count()))
check("标题带实例名", "原名称" in dlg.windowTitle(), dlg.windowTitle())

# 改字段 → 保存
dlg.name_edit.setText("改了名")
dlg.mem_spin.setValue(4096)
dlg.jvm_edit.setText("-Xmx4G -XX:+UseG1GC")
dlg.group_edit.setText("测试组")
changed = dlg._collect(trigger=True)
check("版本未变时 version_changed=False", changed is False)
check("名称写回", live.name == "改了名", live.name)
check("内存写回", live.ram_mb == 4096, str(live.ram_mb))
check("JVM 参数写回", live.jvm_args == "-Xmx4G -XX:+UseG1GC", live.jvm_args)
check("分组写回", live.group == "测试组", live.group)

# 改版本 → 应该报告 changed 并清掉 version_id
live.version_id = "stale-id"
dlg.ver_edit.setText("1.21.1")
changed2 = dlg._collect(trigger=True)
check("改版本报告 changed", changed2 is True)
check("version_id 被清空", live.version_id == "", live.version_id)
check("game_version 写回", live.game_version == "1.21.1", live.game_version)

# 模组页：列出现有 jar
mods_d = live.mods_dir
os.makedirs(mods_d, exist_ok=True)
with io.open(os.path.join(mods_d, "a.jar"), "wb") as fh:
    fh.write(b"PK\x03\x04")
with io.open(os.path.join(mods_d, "b.jar.disabled"), "wb") as fh:
    fh.write(b"PK\x03\x04")
dlg._reload_mods()
# round-185：模组页换成 ModListPanel（搜索/筛选/多选），行对象在 _all 里
check("模组页列出 2 个文件", len(dlg.mod_panel._all) == 2,
      str(len(dlg.mod_panel._all)))
check("已禁用项被识别",
      sum(1 for r in dlg.mod_panel._all if not r.enabled) == 1,
      str([r.enabled for r in dlg.mod_panel._all]))
check("模组面板有搜索框", dlg.mod_panel.search.placeholderText() != "")
check("模组面板有四个筛选", len(dlg.mod_panel.chips.buttons) == 4,
      str(len(dlg.mod_panel.chips.buttons)))

# 内容页：资源包 / 光影 / 存档
try:
    gd = live.game_dir
except Exception:  # noqa: BLE001
    gd = live.mc_dir
os.makedirs(os.path.join(gd, "resourcepacks"), exist_ok=True)
with io.open(os.path.join(gd, "resourcepacks", "pack.zip"), "wb") as fh:
    fh.write(b"PK\x03\x04")
dlg._reload_content()
check("资源包列表读到 1 项",
      dlg._content_lists["resourcepacks"].count() == 1,
      str(dlg._content_lists["resourcepacks"].count()))

dlg.deleteLater()

print("⑧ UI 标签不得污染字段（Beta 后缀 / 手选 Java 路径）")
live2 = Instance(id="t6", name="L", game_version="1.20.1", loader="fabric",
                 loader_version="0.15.11", java_path=r"C:\MyJava\bin\java.exe",
                 _base=mc)
dlg2 = InstanceEditorDialog(None, live2)
dlg2.ldver_combo.clear()
dlg2.ldver_combo.addItem("0.16.0-beta.1 · 测试版", "0.16.0-beta.1")
dlg2.ldver_combo.setCurrentIndex(0)
check("Beta 后缀不进字段", dlg2._current_ldver() == "0.16.0-beta.1",
      dlg2._current_ldver())
dlg2.ldver_combo.setEditText("0.17.0")
check("手输版本号原样可用", dlg2._current_ldver() == "0.17.0",
      dlg2._current_ldver())
# 扫描结果里没有玩家手选的路径时，不能在下拉里丢项
dlg2._fill_java_combo([{"major": 21, "path": r"C:\Other\java.exe"}])
check("手选 Java 保留在下拉里",
      dlg2.java_combo.findData(r"C:\MyJava\bin\java.exe") >= 0)
check("手选 Java 仍是当前项",
      dlg2.java_combo.currentData() == r"C:\MyJava\bin\java.exe",
      str(dlg2.java_combo.currentData()))
dlg2.deleteLater()

print("⑨ 端到端：点保存必须真的落盘（manager 是函数不是单例）")
from src.instances import manager as manager_fn  # noqa: E402

mgr = manager_fn()
real = mgr.add("落盘测试", "1.20.1", loader="vanilla")
dlg3 = InstanceEditorDialog(None, real)
dlg3.name_edit.setText("落盘后")
dlg3.mem_spin.setValue(3072)
dlg3.group_edit.setText("G1")
dlg3._on_save()

# ☠ 不能再用 get_data_dir()：AC_DEV_TEMP=1 下它每次调用都 mkdtemp 一个新目录，
# 照它找文件会永远找不到（假失败）。以 manager 自己记录的目录为准。
inst_file = os.path.join(mgr._dir, real.id + ".json")
check("实例文件已写出", os.path.isfile(inst_file), inst_file)
disk = {}
if os.path.isfile(inst_file):
    with io.open(inst_file, "r", encoding="utf-8") as fh:
        disk = json.load(fh)
check("名称落盘", disk.get("name") == "落盘后", str(disk.get("name")))
check("内存落盘", disk.get("ram_mb") == 3072, str(disk.get("ram_mb")))
check("分组落盘", disk.get("group") == "G1", str(disk.get("group")))
dlg3.deleteLater()

print("⑩ 大尺寸字形描边必须收细（否则四宫格粘成一块）")
# 判据不是「有没有画出来」，而是**描边与间隙的比例**：24px 设计的字形
# 直接放大到 56px 时描边涨到 ~4.7px、间隙只剩 4px，四宫格会粘成一团，
# 看起来像「被相邻方块遮挡」（用户实拍指出）。这里量 56px 渲染的中缝。
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])
from src.icons import pixmap as _pm, pixmap_large as _pml  # noqa: E402


def _runs(pix, y):
    img = pix.toImage()
    out, cur, n = [], None, 0
    for x in range(img.width()):
        v = img.pixelColor(x, y).alpha() > 60
        if v == cur:
            n += 1
        else:
            if cur is not None:
                out.append((cur, n))
            cur, n = v, 1
    out.append((cur, n))
    return out


def _gap_vs_stroke(pix):
    """中缝宽度 / 描边宽度。>1.2 才分得开；旧实现约 0.67。"""
    r = _runs(pix, pix.height() // 4)
    # 期望形状：透明(边距) 实(左描边) 透明(孔) 实(右描边) 透明(中缝) 实(左描边)...
    strokes = [n for v, n in r if v]
    gaps = [n for v, n in r if not v]
    if len(strokes) < 2 or len(gaps) < 3:
        return 0.0, r
    mid_gap = gaps[len(gaps) // 2]
    stroke = max(strokes[:2]) if len(strokes) >= 2 else 0
    return (mid_gap / float(stroke) if stroke else 0.0), r


big_old = _pm("mods", 56)
big_new = _pml("mods", 56)
ratio_old, _ = _gap_vs_stroke(big_old)
ratio_new, _runs_new = _gap_vs_stroke(big_new)
check("旧渲染确实是挤的（判据自身有效）", ratio_old < 1.0, "gap/stroke=%.2f" % ratio_old)
check("大尺寸渲染中缝/描边 >= 1.2", ratio_new >= 1.2, "gap/stroke=%.2f" % ratio_new)
check("收细后描边不超过 4.2px",
      max(n for v, n in _runs_new if v) <= 4,
      "max stroke=%d" % max(n for v, n in _runs_new if v))
# 小图标不能被这条路径改动（24px 是设计尺寸，原样最准）
check("24px 仍走原渲染", _pm("mods", 24).width() == 24)
# 品牌/状态图必须原样：收细逻辑不能把加载器 logo 也重着色
from src.icons import _KEEP_COLOR  # noqa: E402
check("keep-color 图标未参与收细", "check" in _KEEP_COLOR)
check("keep-color 渲染仍有内容", not _pml("check", 56).toImage().isNull())

shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-183 编辑面板 / 加载器装卸 / pcl 格式）")
