"""round-229：资源中心本地化的行为回归（离线，零真实网络）。"""
import os
import sys
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.net_api as NA            # noqa: E402
import src.store_detail as SD       # noqa: E402
import src.i18n as I18N            # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


DESC = "A long English description for the mod."
CARD = {"project_id": "p1", "slug": "demo", "title": "Demo",
        "source": "modrinth", "description": DESC}


# ── [1] 译文缓存键覆盖全文，前 200 字相同不撞键 ────────────────────────
keys = []
_o = (NA._cached, NA._store, NA._google_translate, NA._mymemory_translate)
NA._cached = lambda key, *a, **k: (keys.append(key), None)[1]
NA._store = lambda *a, **k: None
NA._google_translate = lambda text, target: "translated"
NA._mymemory_translate = lambda text, target: "translated"
try:
    head = "X" * 200
    NA.translate_text(head + "AAA")
    NA.translate_text(head + "BBB")
finally:
    NA._cached, NA._store, NA._google_translate, NA._mymemory_translate = _o
check("共享前 200 字的两段文本缓存键不同",
      len(keys) == 2 and keys[0] != keys[1], str(len(keys)))


# ── [2] 英文界面不自动机翻，直接显示原文 ───────────────────────────────
_orig_lang = I18N.get_language
I18N.get_language = lambda: "en-US"
try:
    panel_en = SD.StoreDetailPanel(None, dict(CARD), "mod", None, "mods",
                                   instances=[])
finally:
    I18N.get_language = _orig_lang
check("英文界面说明区显示原文",
      panel_en.text.toPlainText() == DESC, panel_en.text.toPlainText()[:40])
check("英文界面没有翻译状态提示", panel_en.tr_status.text() == "")
I18N.get_language = lambda: "zh-CN"
try:
    check("中文界面仍判定为需要自动翻译", SD._is_zh_ui() is True)
    I18N.get_language = lambda: "en-US"
    check("英文界面判定为不自动翻译", SD._is_zh_ui() is False)
finally:
    I18N.get_language = _orig_lang


# ── [3] 自动翻译失败回填原文，不留下空说明区 ───────────────────────────
class Sig:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in list(self.slots):
            fn(*a)


class FailWorker:
    def __init__(self, fn, *a, **k):
        self.finished = Sig()
        self.error = Sig()

    def start(self):
        self.error.emit("boom")


_orig_worker = SD.Worker
SD.Worker = FailWorker
I18N.get_language = lambda: "zh-CN"
try:
    p = SD.StoreDetailPanel(None, dict(CARD, slug="fail-case"), "mod", None,
                            "mods", instances=[])
finally:
    SD.Worker = _orig_worker
    I18N.get_language = _orig_lang
check("自动翻译失败后说明区回填原文",
      p.text.toPlainText() == DESC, p.text.toPlainText()[:40])
check("自动翻译失败不显示报错红字", p.tr_status.text() == "")


# ── [4] 名库命中时不再发机翻请求 ───────────────────────────────────────
tr_calls = []
_o2 = (NA._lookup_cn_slugs, NA._projects_by_slugs, NA.translate_text,
       NA._cached, NA._store)
NA._lookup_cn_slugs = lambda q: ["sodium"]
NA._projects_by_slugs = lambda slugs: [
    {"id": "p1", "slug": "sodium", "title": "Sodium",
     "description": "desc", "project_type": "mod"}]
NA.translate_text = lambda *a, **k: (tr_calls.append(1), "ignored")[1]
NA._cached = lambda *a, **k: None
NA._store = lambda *a, **k: None
try:
    out = NA.search_mods_zh("钠-unique-query-229", 0, 20, "mod")
finally:
    (NA._lookup_cn_slugs, NA._projects_by_slugs, NA.translate_text,
     NA._cached, NA._store) = _o2
check("名库命中时零机翻请求", tr_calls == [], str(len(tr_calls)))
check("名库命中仍能返回结果", len(out) == 1 and out[0]["slug"] == "sodium")

tr_calls.clear()
NA._lookup_cn_slugs = lambda q: []
NA._projects_by_slugs = lambda slugs: []
NA.translate_text = lambda *a, **k: (tr_calls.append(1), "sodium")[1]
NA._cached = lambda *a, **k: None
NA._store = lambda *a, **k: None
_o3 = NA.search_mods
NA.search_mods = lambda *a, **k: [{"project_id": "p2", "slug": "sodium-2",
                                   "title": "Sodium 2", "description": ""}]
try:
    NA.search_mods_zh("完全没收录-zero-229", 0, 20, "mod")
finally:
    (NA._lookup_cn_slugs, NA._projects_by_slugs, NA.translate_text,
     NA._cached, NA._store, NA.search_mods) = _o2 + (_o3,)
check("名库零命中仍保留英文兜底", len(tr_calls) == 1, str(len(tr_calls)))

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-229 本地化回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-229 本地化回归）")
