# -*- coding: utf-8 -*-
"""round-180：官方图标 / 交互不跳 / 版本渠道 / 列表详情排版判据。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication.instance() or QApplication([])

FAILS = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         (" | " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ── 1. 加载器图标：round-181 起复用 HMCL 现成集，不再逐个溯源上游原图 ──
ICONS = os.path.join(ROOT, "assets", "icons")
from src import icons  # noqa: E402

check("图标管道支持 SVG/PNG/ICO 三种格式",
      icons._ICON_EXTS == (".svg", ".png", ".ico"))
check("来源与许可 NOTICE 已落盘",
      os.path.isfile(os.path.join(ICONS, "LOADER_LOGOS.md")))
# 主理人 round-181 纠正：「加载器基本上是一样的，可以复用他们的，
# 不要自己乱找」→ 8 张统一取 HMCL assets/img/*@2x.png；
# HMCL 未收录的 LabyMod / LiteLoader 保留官网 favicon.ico。
official = {
    "fabric": ".png", "forge": ".png", "quilt": ".png", "neoforge": ".png",
    "optifine": ".png", "labymod": ".ico", "legacyfabric": ".png",
    "liteloader": ".ico", "vanilla": ".png", "cleanroom": ".png",
}
for lid, ext in official.items():
    p = os.path.join(ICONS, "loader_%s%s" % (lid, ext))
    pm = icons.pixmap("loader_" + lid, 40, dpr=1.0)
    check("HMCL/官网图标 %-10s 可渲染" % lid,
          os.path.isfile(p) and not pm.isNull())
check("Cleanroom 用 HMCL 现成图标（不再留空占位）",
      os.path.isfile(os.path.join(ICONS, "loader_cleanroom.png")))
check("QRC 收录了 PNG/ICO 资源",
      ".png" in read("icons.qrc") and ".ico" in read("icons.qrc"))

# ── 2. 版本渠道识别：识别不了不假造 ────────────────────────────────
from src.pages_instances import version_channel  # noqa: E402
check("beta 标题识别为测试版", version_channel("1.20.1-beta.3") == "beta")
check("preview / snapshot / 中文测试 识别",
      all(version_channel(x) == "beta"
          for x in ("OptiFine HD U I5 preview", "26.1-snapshot-4", "1.12 测试版")))
check("recommended 识别为稳定版",
      version_channel("forge-47.2.0-recommended") == "stable")
check("纯版本号 → unknown（不假造稳定）",
      version_channel("0.16.10") == "unknown")

# ── 3. 加载器版本下拉：默认项显示具体版本号 + 渠道角标 ─────────────
from PySide6.QtWidgets import QComboBox  # noqa: E402
from src.pages_instances import NewInstanceDialog  # noqa: E402
try:
    dlg = NewInstanceDialog.__new__(NewInstanceDialog)
    dlg.ldver_combo = QComboBox()
    NewInstanceDialog._on_loader_versions(dlg, [
        {"title": "0.16.10", "meta": "0.16.10", "channel": "stable"},
        {"title": "0.16.0-beta.1", "meta": "b1", "channel": "beta"},
        {"title": "0.15.9", "meta": "0.15.9", "channel": "unknown"},
    ])
    check("默认项把具体版本号写给玩家",
          "0.16.10" in dlg.ldver_combo.itemText(0),
          dlg.ldver_combo.itemText(0))
    check("稳定版 / 测试版有角标",
          "稳定版" in dlg.ldver_combo.itemText(1)
          and "测试版" in dlg.ldver_combo.itemText(2))
    check("unknown 不加角标",
          "·" not in dlg.ldver_combo.itemText(3),
          dlg.ldver_combo.itemText(3))
    check("默认项 data 仍为空（安装取最新）",
          dlg.ldver_combo.itemData(0) == "")
except Exception as e:  # noqa: BLE001
    check("下拉行为判据可执行", False, repr(e))

# ── 4. 交互不跳：重复点守卫 / 高度占位 / 缓存 ──────────────────────
pi = read("src/pages_instances.py")
check("重复点同一加载器不再重发请求",
      'getattr(self, "_ldver_loaded_for", "") == loader_id' in pi)
check("切换用高度占位而非 setVisible",
      "setMaximumHeight(0 if not show_ldver" in pi)
check("加载器版本结果有缓存",
      'self._ldver_cache' in pi and "cache[key] = versions" in pi)
check("selected_loader_version 用显式标志",
      'getattr(self, "_ldver_visible", False)' in pi)
check("选中态不再依赖 card.isVisible()",
      "card.set_selected(lid == loader_id and card.isVisible())" not in pi)

# ── 5. 排版：结构改动而非堆装饰 ────────────────────────────────────
from src.ui_kit import format_count  # noqa: E402
check("下载量人读格式",
      format_count(1234567) == "123.5万" and format_count(999) == "999"
      and format_count(None) == "—")
pb = read("src/pages_browse.py")
sd = read("src/store_detail.py")
check("列表描述单行省略（列表节奏统一）",
      "ElideRight" in pb and "setToolTip(raw_desc[:400])" in pb)
check("列表有来源标签 + 次信息降权",
      'ui_kit.tag(' in pb and "COLORS['text_disabled']" in pb)
check("详情页封面 88px / 标题用 big 类",
      "setFixedSize(88, 88)" in sd
      and 'self.title.setProperty("cls", "big")' in sd)
check("详情页 meta 也用格式化下载量",
      "ui_kit.format_count(card.get" in sd)

print("RESULT:", "PASS" if not FAILS else "FAIL %d: %r" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
