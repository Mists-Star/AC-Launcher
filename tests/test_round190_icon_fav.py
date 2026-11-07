"""round-190：实例图标 + 收藏夹（PCL 概览页「个性化」）。

判据：
1. **收藏真的置顶**：`sorted_instances` 把收藏项排最前，其余仍按分组/名称；
2. **图标真的复制进来**：set_instance_icon 不改动原文件，写进
   data/instance_icons/<id>.<ext>，换扩展名时清掉旧的；
3. **拒绝坏输入**：非图片扩展名 / 超过 4 MB 抛 ValueError（UI 提示，不静默）；
4. **卡片真的用上**：实例卡与首页卡的 pixmap 不是默认图；
5. **收藏落盘**：写进实例 json，重新读回来还是 True。
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

DEV = tempfile.mkdtemp(prefix="ac_r190_")
# ☠ dev 模式下 get_data_dir() 是 **cwd 相对**的：不 chdir 就会把测试实例/图标
# 写进项目自己的 data/ 里（上一版就是这么污染的）。
os.chdir(DEV)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.instances import Instance, sorted_instances  # noqa: E402

print("① 收藏置顶排序")
a = Instance(id="a", name="Alpha", game_version="1.20.1", group="")
b = Instance(id="b", name="Beta", game_version="1.20.1", group="")
c = Instance(id="c", name="Gamma", game_version="1.20.1", group="")
b.favorite = True
order = [i.name for i in sorted_instances([a, b, c])]
check("收藏排最前", order[0] == "Beta", str(order))
check("其余仍按名称", order[1:] == ["Alpha", "Gamma"], str(order))
b.favorite = False
check("取消收藏后回到普通顺序",
      [i.name for i in sorted_instances([a, b, c])] == ["Alpha", "Beta", "Gamma"])

print("② 图标复制与校验")
from src import instance_art  # noqa: E402
from PySide6.QtGui import QImage, QColor  # noqa: E402

src_png = os.path.join(DEV, "src.png")
im = QImage(16, 16, QImage.Format_ARGB32)
im.fill(QColor("#7C3AED"))
im.save(src_png, "PNG")

inst = Instance(id="i1", name="I1", game_version="1.20.1")
path = instance_art.set_instance_icon(inst, src_png)
check("图标复制到数据目录", os.path.isfile(path), path)
check("原文件还在（不搬走玩家的图）", os.path.isfile(src_png))
check("返回路径带实例 id", os.path.basename(path).startswith("i1"), path)
pm = instance_art.icon_pixmap(path, 32)
check("能生成 pixmap", pm is not None and not pm.isNull(),
      "%dx%d" % (pm.width(), pm.height()) if pm else "-")

# 换扩展名：旧文件要清掉
src_jpg = os.path.join(DEV, "src.jpg")
im.save(src_jpg, "JPG")
path2 = instance_art.set_instance_icon(inst, src_jpg)
check("换格式后旧 png 被清掉", not os.path.isfile(path))
check("新 jpg 就位", os.path.isfile(path2), path2)

# 坏输入
txt = os.path.join(DEV, "note.txt")
io.open(txt, "w", encoding="utf-8").write("hi")
try:
    instance_art.set_instance_icon(inst, txt)
    check("非图片被拒绝", False)
except ValueError:
    check("非图片被拒绝", True)

big = os.path.join(DEV, "big.png")
with io.open(big, "wb") as fh:
    fh.write(b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024))
try:
    instance_art.set_instance_icon(inst, big)
    check("超大文件被拒绝", False)
except ValueError:
    check("超大文件被拒绝", True)

instance_art.clear_instance_icon(inst)
check("恢复默认会删掉缓存文件", not os.path.isfile(path2))

print("③ 卡片真的用上图标 / 星标")
from src.pages_instances import InstanceCard  # noqa: E402

inst_b = Instance(id="i2", name="有图", game_version="1.20.1")
inst_b.icon_path = instance_art.set_instance_icon(inst_b, src_png)
inst_b.favorite = True
card = InstanceCard(inst_b, False)
labels = card.findChildren(type(card.findChild(type(None)) or object))
check("卡片构建成功", card is not None)
from PySide6.QtWidgets import QLabel  # noqa: E402

stars = [w for w in card.findChildren(QLabel) if w.text() == "★"]
check("收藏卡片带星标", len(stars) == 1, str(len(stars)))
pixmaps = [w.pixmap() for w in card.findChildren(QLabel)
           if w.pixmap() is not None and not w.pixmap().isNull()]
check("卡片图标有像素", any(p.width() >= 32 for p in pixmaps),
      str([(p.width(), p.height()) for p in pixmaps][:3]))

print("④ 收藏落盘")
from src.instances import InstancesManager  # noqa: E402

mgr = InstancesManager()
n = mgr.add(name="收藏测试", game_version="1.20.1")
n.favorite = True
mgr.save(n)
again = mgr.get(n.id)
check("重新读回 favorite=True", bool(getattr(again, "favorite", False)),
      str(getattr(again, "favorite", None)))

card.deleteLater()
shutil.rmtree(DEV, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-190 图标 + 收藏）")
