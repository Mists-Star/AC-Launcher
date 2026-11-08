"""round-218：资源中心「超长 mod 名把右侧挤到窗口外」行为回归。

主理人实机反馈：资源中心搜索 Mod，部分名称过长时右侧内容被挤出窗口，
且底部出现横向滑块（明确要求**不要**用底部滑块）。

根因：卡片标题是普通 ``QLabel``，它的 ``minimumSizeHint`` 等于整段文本宽度
（实测 400 字 → 4356 px），QScrollArea 的内容最小宽度随之变大，两栏 splitter
只能把右栏推出可视区、并弹出横向滚动条。

本文件断言的是**几何结果**而不是源码字面量：
  1. ``ElidedLabel`` 按宽度省略、``minimumSizeHint().width() == 0``；
  2. 三种窗口宽度（1400 / 1100 / 900）下，结果区 **没有横向滚动条**、
     内容最小宽度不超过视口、右栏右边界不越过页面；
  3. 详情页超长无空格标题同样不把面板撑宽（面板最小宽度 <= 宿主宽度）。

⚠ 几何测量在**子进程**里做：整页 StorePage + 详情面板在离屏环境下偶尔会在
解释器收尾阶段 SIGSEGV（同批 round-208/216 的已知噪音）。放子进程里崩也只
崩子进程，父进程照常拿到测量结果，不会把整条回归拖成假失败。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-62s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


from unittest import mock  # noqa: E402

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt  # noqa: E402

app = QApplication.instance() or QApplication([])

LONG = ("SuperUltraMegaHyperComprehensiveAllInOneIndustrialAutomationAnd"
        "TechnologicalProgressionOverhaulModForMinecraftJavaEdition" * 3)


def _probe(body: str) -> dict:
    """在子进程里跑一段测量代码，返回最后一行 JSON。"""
    code = (
        "import os, sys, json\n"
        "sys.path.insert(0, %r)\n"
        "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n" % HERE
    ) + body
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    out = (p.stdout or "").strip().splitlines()
    for line in reversed(out):
        try:
            return json.loads(line)
        except Exception:  # noqa: BLE001
            continue
    return {"error": (p.stdout or "")[-200:] + (p.stderr or "")[-200:],
            "rc": p.returncode}


# ══════════════════════════════════════════════════════════════════════
# 1. ElidedLabel 本身
# ══════════════════════════════════════════════════════════════════════
print("== 1. ElidedLabel 不参与宽度计算 ==")
from src import ui_kit  # noqa: E402

host = QWidget()
host.resize(300, 80)
lay = QVBoxLayout(host)
lay.setContentsMargins(0, 0, 0, 0)
lbl = ui_kit.ElidedLabel(LONG)
lbl.setProperty("cls", "title")
lay.addWidget(lbl)
host.show()
app.processEvents()

check("最小宽度为 0（不再按全文宽度报）",
      lbl.minimumSizeHint().width() == 0, str(lbl.minimumSizeHint().width()))
check("实际显示已被省略",
      0 < len(lbl.text()) < len(LONG), "%d / %d" % (len(lbl.text()), len(LONG)))
check("full_text() 保留原文", lbl.full_text() == LONG)
check("label 宽度不超过宿主",
      lbl.width() <= host.width(), "%d <= %d" % (lbl.width(), host.width()))

plain = QLabel(LONG)
# 对照：旧实现用的就是普通 QLabel，它的最小宽度 = 全文宽度（不同环境/字体下
# 绝对值不同，这里只断言「远超视口」这个关键性质）。
check("对照：普通 QLabel 的最小宽度远超视口（旧行为）",
      plain.minimumSizeHint().width() > 5 * host.width(),
      "%d px vs 视口 %d" % (plain.minimumSizeHint().width(), host.width()))

lbl.setText("短标题")
app.processEvents()
check("setText 后恢复正常显示", lbl.text() == "短标题")

# ══════════════════════════════════════════════════════════════════════
# 2. 资源中心列表：三种窗口宽度都不溢出、都不出横向滑块
# ══════════════════════════════════════════════════════════════════════
print("== 2. 资源中心列表几何 ==")

_STORE_PROBE = r'''
from unittest import mock
from PySide6.QtWidgets import QApplication
app = QApplication([])
import src.pages_browse as pb


class _NoIcons:
    def load(self, *a, **k):
        return None

    def prefetch(self, *a, **k):
        return None

    def bump(self):
        return None


LONG = ("SuperUltraMegaHyperComprehensiveAllInOneIndustrialAutomationAnd"
        "TechnologicalProgressionOverhaulModForMinecraftJavaEdition" * 3)
rows = [{"title": LONG, "description": LONG, "project_id": "p%d" % i,
         "slug": "s%d" % i, "source": "modrinth", "downloads": 1234567,
         "author": LONG, "icon_url": "", "game_versions": [],
         "loaders": []} for i in range(3)]
data = {"hits": rows, "total": 3, "cursors": {}, "results": rows,
        "can_next": False, "can_prev": False, "meta": {}, "page": 0}
out = []
with mock.patch.object(pb, "get_image_loader", lambda: _NoIcons()):
    for win_w in (1400, 1100, 900):
        page = pb.StorePage(lambda: [], lambda: None)
        page.resize(win_w, 700)
        page.show()
        app.processEvents()
        with mock.patch.object(pb, "search_store_page", lambda *a, **k: data):
            page._on_loaded(data, reset=True)
        app.processEvents()
        right = page.splitter.widget(1)
        rx = right.mapTo(page, right.rect().topLeft()).x()
        titles = [x for x in page._content.findChildren(
            __import__("src.ui_kit", fromlist=["x"]).ElidedLabel)
            if x.full_text() == LONG]
        out.append({
            "win": win_w,
            "hbar": page.scroll.horizontalScrollBar().maximum(),
            "policy": page.scroll.horizontalScrollBarPolicy()
                      == __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ScrollBarAlwaysOff,
            "content_min": page._content.minimumSizeHint().width(),
            "viewport": page.scroll.viewport().width(),
            "right_edge": rx + right.width(),
            "page_w": page.width(),
            "elided": all(0 < len(x.text()) < len(LONG) for x in titles) and bool(titles),
        })
        page._icon_pending = []
print(json.dumps(out))
'''

res = _probe(_STORE_PROBE)
rows_out = res if isinstance(res, list) else []
for row in rows_out:
    w = row.get("win")
    check("w=%s 没有横向滚动条" % w, row.get("hbar") == 0,
          "max=%s" % row.get("hbar"))
    check("w=%s 内容最小宽度不超过视口" % w,
          row.get("content_min", 1e9) <= row.get("viewport", 0),
          "%s <= %s" % (row.get("content_min"), row.get("viewport")))
    check("w=%s 右栏没有越过页面" % w,
          row.get("right_edge", 1e9) <= row.get("page_w", 0),
          "右边界 %s / 页面 %s" % (row.get("right_edge"), row.get("page_w")))
    check("w=%s 横向滚动条策略为 AlwaysOff" % w, row.get("policy") is True)
    check("w=%s 卡片标题都已省略" % w, row.get("elided") is True)
if not rows_out:
    check("资源中心几何探针可运行", False, str(res)[:120])

# ══════════════════════════════════════════════════════════════════════
# 3. 详情页超长无空格标题
# ══════════════════════════════════════════════════════════════════════
print("== 3. 详情页标题不撑宽 ==")

_DETAIL_PROBE = r'''
from unittest import mock
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QSizePolicy
app = QApplication([])
import src.store_detail as sdet
LONG = ("SupercalifragilisticexpialidociousModNameWithoutAnySpaces" * 6)
card = {"title": LONG, "description": "d", "project_id": "p1", "slug": "s1",
        "source": "modrinth", "downloads": 1, "author": "a", "icon_url": ""}
with mock.patch.object(sdet, "_fetch_and_translate", lambda c: ("", None)):
    host = QWidget()
    host.resize(686, 600)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    panel = sdet.StoreDetailPanel(host, card, "mod", None, "mods")
    lay.addWidget(panel)
    host.show()
    app.processEvents()
    app.processEvents()
    print(json.dumps({
        "host_min": host.minimumSizeHint().width(),
        "policy_ignored": panel.title.sizePolicy().horizontalPolicy()
                           == QSizePolicy.Policy.Ignored,
        "tooltip_ok": panel.title.toolTip() == LONG,
    }))
'''

d = _probe(_DETAIL_PROBE)
check("详情面板最小宽度不超过宿主",
      isinstance(d, dict) and d.get("host_min", 1e9) <= 686,
      str(d.get("host_min") if isinstance(d, dict) else d)[:60])
check("标题水平策略为 Ignored（不参与最小宽度）",
      isinstance(d, dict) and d.get("policy_ignored") is True)
check("标题 tooltip 保留全文",
      isinstance(d, dict) and d.get("tooltip_ok") is True)

print("\nround-218 regression: %d checks, %d failed" % (total, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.stdout.flush()
    os._exit(1)
print("ALL CHECKS PASSED（round-218 长标题不再撑破右栏）")
sys.stdout.flush()
os._exit(0)
