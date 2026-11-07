"""round-185：读 jar 真实元数据（core.modmeta）+ 模组列表面板。

为什么要有这层判据：模组页以前拿**文件名**当名字。这个 bug 不会抛异常、
不会崩，只是显示得难看 —— 只能靠断言钉住「读出来的名字/版本/描述必须是 jar
里写的那份，不是文件名」。

造的是**真 zip 包**（不是 mock）：fabric / quilt / forge / neoforge / 老版
mcmod.info 各造一个，再放两个坏包验证「读不出来不算失败」。
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

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# 8×8 纯色 PNG（合法 PNG —— 上一版手写 hex 的 IDAT 校验和是坏的，
# Qt 会报 "libpng error: IDAT: incorrect data check"，只是没人解码才发现）。
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000008000000080806000000c40fbe8b"
    "000000097048597300000ec400000ec401952b0e1b"
    "0000001649444154189563acb17afb9f010f60c227397c140000b8c302b2"
    "913458570000000049454e44ae426082")

tmp = tempfile.mkdtemp(prefix="ac_modmeta_")


def jar(name, entries: dict) -> str:
    p = os.path.join(tmp, name)
    with zipfile.ZipFile(p, "w") as z:
        for arc, data in entries.items():
            z.writestr(arc, data)
    return p


from src.core import modmeta  # noqa: E402

print("① Fabric 清单")
p = jar("sodium.jar", {
    "fabric.mod.json": json.dumps({
        "schemaVersion": 1, "id": "sodium", "version": "0.5.13+mc1.20.1",
        "name": "Sodium", "description": "Modern rendering engine  for Minecraft",
        "authors": ["jellysquid3", {"name": "CaffeineMC"}],
        "environment": "client", "icon": "assets/sodium/icon.png",
        "depends": {"minecraft": "~1.20.1"},
    }),
    "assets/sodium/icon.png": PNG,
})
m = modmeta.read_meta(p)
check("fabric 读到 id", m and m["id"] == "sodium", str(m and m["id"]))
check("fabric 读到真名（不是文件名）", m and m["name"] == "Sodium",
      str(m and m["name"]))
check("fabric 读到版本", m and m["version"] == "0.5.13+mc1.20.1",
      str(m and m["version"]))
check("fabric 描述空白被压平", m and "  " not in m["description"],
      repr(m and m["description"])[:40])
check("fabric 作者混合格式", m and m["authors"] == ["jellysquid3", "CaffeineMC"],
      str(m and m["authors"]))
check("fabric 环境字段", m and m["env"] == "client", str(m and m["env"]))
check("fabric 图标取到字节", m and len(m["icon"]) >= 60, str(m and len(m["icon"])))
from PySide6.QtGui import QImage  # noqa: E402

check("图标字节是能解码的图片",
      bool(m and not QImage.fromData(m["icon"]).isNull()))
check("fabric 加载器标记", m and m["loader"] == "fabric", str(m and m["loader"]))
check("fabric 依赖里的 mc 版本", m and m["mc"] == "~1.20.1", str(m and m["mc"]))

print("② Quilt 清单")
pq = jar("qmod.jar", {
    "quilt.mod.json": json.dumps({
        "schema_version": 1,
        "quilt_loader": {"group": "x", "id": "qsl", "version": "1.0.0",
                         "metadata": {"name": "Quilted Thing",
                                      "description": "desc",
                                      "contributors": {"alice": {"role": "dev"}},
                                      "icon": "icon.png"}},
    }),
    "icon.png": PNG,
})
mq = modmeta.read_meta(pq)
check("quilt 读到 id", mq and mq["id"] == "qsl", str(mq and mq["id"]))
check("quilt 读到名字", mq and mq["name"] == "Quilted Thing",
      str(mq and mq["name"]))
check("quilt 贡献者转作者", mq and mq["authors"] == ["alice"],
      str(mq and mq["authors"]))
check("quilt 图标", mq and len(mq["icon"]) >= 60)

print("③ Forge / NeoForge TOML")
toml_body = '''modLoader = "javafml"
loaderVersion = "[47,)"
license = "MIT"

[[mods]]
modId = "create"
version = "0.5.1"
displayName = "Create"
description = "Aesthetic technology"
authors = "simibubi"
logoFile = "icon.png"
'''
pf = jar("create.jar", {"META-INF/mods.toml": toml_body, "icon.png": PNG})
mf = modmeta.read_meta(pf)
check("forge 读到 modId", mf and mf["id"] == "create", str(mf and mf["id"]))
check("forge 读到 displayName", mf and mf["name"] == "Create",
      str(mf and mf["name"]))
check("forge 读到版本", mf and mf["version"] == "0.5.1", str(mf and mf["version"]))
check("forge 作者", mf and mf["authors"] == ["simibubi"],
      str(mf and mf["authors"]))
check("forge 图标", mf and len(mf["icon"]) >= 60)

pn = jar("neo.jar", {"META-INF/neoforge.mods.toml": toml_body})
mn = modmeta.read_meta(pn)
check("neoforge 识别", mn and mn["loader"] == "neoforge",
      str(mn and mn["loader"]))
check("neoforge 名字", mn and mn["name"] == "Create", str(mn and mn["name"]))

print("④ 老版 mcmod.info")
pl = jar("old.jar", {"mcmod.info": json.dumps([{
    "modid": "thermal", "name": "Thermal Expansion", "version": "5.5.7",
    "description": "Machines", "authorList": ["TeamCoFH"],
    "mcversion": "1.12.2", "logoFile": "logo.png"}]), "logo.png": PNG})
ml = modmeta.read_meta(pl)
check("legacy 读到名字", ml and ml["name"] == "Thermal Expansion",
      str(ml and ml["name"]))
check("legacy 读 mc 版本", ml and ml["mc"] == "1.12.2", str(ml and ml["mc"]))
check("legacy 加载器记为 forge", ml and ml["loader"] == "forge")
mlist = jar("list.jar", {"mcmod.info": json.dumps({"modList": [
    {"modid": "a", "name": "AA"}]})})
check("mcmod.info 是 dict 也能读",
      (modmeta.read_meta(mlist) or {}).get("name") == "AA")

print("⑤ 读不出来不算失败")
pbad = os.path.join(tmp, "broken.jar")
with io.open(pbad, "wb") as fh:
    fh.write(b"not a zip at all")
check("坏包返回 None", modmeta.read_meta(pbad) is None)
pnone = jar("nomod.jar", {"META-INF/MANIFEST.MF": "Manifest-Version: 1.0"})
check("没有清单的 jar 返回 None", modmeta.read_meta(pnone) is None)
check("缺文件返回 None", modmeta.read_meta(os.path.join(tmp, "nope.jar")) is None)

print("⑥ 展示名与搜索文本")
check("读不到元数据时退回文件名",
      modmeta.display_name(pnone) == "nomod", modmeta.display_name(pnone))
check("disables 后缀不显示",
      modmeta.display_name(pnone + ".disabled") == "nomod",
      modmeta.display_name(pnone + ".disabled"))
blob = modmeta.search_blob(p, m)
check("搜索文本含真名", "sodium" in blob)
check("搜索文本含描述", "rendering" in blob)
check("搜索文本含作者", "jellysquid3" in blob)
check("搜索文本含文件名", "sodium.jar" in blob)
check("中文描述也能搜", "渲染" in modmeta.search_blob(
    p, dict(m or {}, description="更好的渲染")))
# 缓存：同一文件第二次读走缓存（返回同一对象）
check("缓存命中返回同一对象", modmeta.read_meta(p) is m)

print("⑦ 模组面板：筛选 / 搜索 / 批量")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.instances import Instance  # noqa: E402
from src.mod_list import ModListPanel  # noqa: E402

mc = os.path.join(tmp, "mc")
mods = os.path.join(mc, "mods")
os.makedirs(mods, exist_ok=True)
for name, data in (("sodium.jar", None), ("create.jar", None),
                   ("old.jar.disabled", None)):
    src = {"sodium.jar": p, "create.jar": pf, "old.jar.disabled": pl}[name]
    shutil.copy2(src, os.path.join(mods, name))

inst = Instance(id="t", name="T", game_version="1.20.1", _base=mc)
panel = ModListPanel(None, inst)
check("列出全部 3 个", len(panel._all) == 3, str(len(panel._all)))
check("禁用项识别正确",
      sum(1 for r in panel._all if not r.enabled) == 1,
      str([r.enabled for r in panel._all]))
check("行显示真实名字",
      "Sodium" in [r.name_lbl.text() for r in panel._all],
      str([r.name_lbl.text() for r in panel._all]))
check("行里带着真实版本号",
      any(r.version.startswith("0.5.13") for r in panel._all),
      str([r.version for r in panel._all]))


def visible():
    return [r for r in panel._all if not r.isHidden()]


panel.search.setText("create")
panel._apply_filter()
check("搜索按真名过滤", len(visible()) == 1 and
      visible()[0].name_lbl.text() == "Create",
      str([r.name_lbl.text() for r in visible()]))
panel.search.setText("thermal")
panel._apply_filter()
check("搜索也命中 legacy 包（按名字）", len(visible()) == 1,
      str(len(visible())))
panel.search.setText("")
panel.chips.set("off")
panel._apply_filter()
check("筛选「已禁用」只剩 1 个", len(visible()) == 1, str(len(visible())))
panel.chips.set("on")
panel._apply_filter()
check("筛选「已启用」剩 2 个", len(visible()) == 2, str(len(visible())))
panel.chips.set("all")
panel._apply_filter()
check("筛选「全部」回到 3", len(visible()) == 3, str(len(visible())))

print("⑧ 批量启停真落盘")
for r in panel._all:
    r.set_checked(True)
panel._on_selection()
check("批量条显示已选 3", "3" in panel.batch_lbl.text(), panel.batch_lbl.text())
check("批量条可见", panel.batch.isVisibleTo(panel), "")
panel._batch_disable()
names = sorted(os.listdir(mods))
check("全部变成 .disabled", all(n.endswith(".disabled") for n in names),
      str(names))
check("面板已重载", len(panel._all) == 3 and
      all(not r.enabled for r in panel._all))
# 批量操作后列表会重建、勾选清空（路径也变了：x.jar → x.jar.disabled），
# 要再勾一次才能继续批量
for r in panel._all:
    r.set_checked(True)
panel._on_selection()
panel._batch_enable(True)
names2 = sorted(os.listdir(mods))
check("全部恢复启用", all(n.endswith(".jar") for n in names2), str(names2))

for r in panel._all:
    r.set_checked(True)
panel._on_selection()
n_before = len(os.listdir(mods))
import src.mod_list as ML  # noqa: E402
ML.confirm = lambda *a, **k: True       # 模态框在 offscreen 会永久阻塞
ML.toast = lambda *a, **k: None
panel._batch_delete()
check("批量删除清空目录", len(os.listdir(mods)) == n_before - 3,
      str(len(os.listdir(mods))))
check("删完显示空态", panel.empty_box.isVisibleTo(panel) or
      len(panel._all) == 0, str(len(panel._all)))

panel.deleteLater()
shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-185 模组元数据 + 模组列表）")
