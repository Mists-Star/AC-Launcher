"""round-218：崩溃分析面板空白 + 一键修复无效 + 搜索/版本过滤的回归。

主理人实机反馈三条：
  1. 崩溃分析「发现 2 个问题」但**列表一片空白**；
  2. 「一键修复」按钮**点了没反应**；
  3. 资源中心**部分 mod 搜不到**、**版本与需要找不到对应的**。

根因（本轮逐条复现）：
  1+2. ``_FindingCard`` 里 ``QFontMetrics.boundingRect(w, 0, flags, text)`` 这个
       重载在 PySide6 里不存在 → 每张带 detail 的卡构造时抛 TypeError →
       异常冒到 ``_on_analyzed`` 的循环 → 后面的卡全没了，而且
       ``repair_all_btn.setEnabled(...)`` 那行**根本没执行** → 按钮永远禁用。
  3.   Modrinth 对非法 facet 直接回 HTTP 400（实测 ``versions:26.`` → 400），
       整个搜索请求挂掉 → 一个都搜不到；同时版本下拉是写死的 12 条静态表
       （最新只到 1.21.11），主理人实例是 26.3 → 压根选不到。

本文件的断言全部是**行为判据**（真的渲染、真的发请求参数），不是源码字面量。
"""
import os
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

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication.instance() or QApplication([])

# ══════════════════════════════════════════════════════════════════════
# 1. 崩溃分析面板：结论卡渲染 + 一键修复按钮可用
# ══════════════════════════════════════════════════════════════════════
print("== 1. 崩溃分析面板 ==")
import src.crash_dialog as cd  # noqa: E402
from src.crash_analysis import CrashFinding  # noqa: E402


class _Inst:
    id = "i1"
    name = "26.3"
    mc_dir = os.getcwd()


def _findings():
    return [
        CrashFinding(kind="java_version", severity="warning",
                     title="crash.java_old_title", reason="crash.java_old_reason",
                     suggestion="crash.java_old_suggestion", repairable=True,
                     detail="java.lang.OutOfMemoryError: Java heap space"),
        CrashFinding(kind="mod_dep_missing", severity="critical",
                     title="crash.deps_title", reason="crash.deps_reason",
                     suggestion="crash.deps_suggestion", repairable=True,
                     detail="Missing mod: jei", culprit="jei-1.0.jar"),
    ]


with mock.patch.object(cd.crash, "analyze_instance", lambda inst: _findings()):
    host = QWidget()
    host.resize(900, 600)
    panel = cd.CrashAnalyzerPanel(_Inst(), parent=host)
    host.show()
    for _ in range(6):
        app.processEvents()

    check("状态行显示问题数", "2" in panel.status.text(), panel.status.text())
    check("两张结论卡都渲染出来", panel._vbox.count() == 3,
          "vbox=%d（2 卡 + stretch）" % panel._vbox.count())
    check("结论卡有实际高度", panel._content.sizeHint().height() > 80,
          "%d px" % panel._content.sizeHint().height())
    check("「一键修复」按钮可用", panel.repair_all_btn.isEnabled())

    # 单张卡渲染失败不许拖垮整页
    bad = _findings()
    bad[0].detail = "x" * 40
    with mock.patch.object(cd.crash, "analyze_instance", lambda inst: bad), \
         mock.patch.object(cd, "_FindingCard", side_effect=RuntimeError("boom")), \
         mock.patch.object(cd, "report", lambda *a, **k: None):
        panel2 = cd.CrashAnalyzerPanel(_Inst(), parent=host)
        for _ in range(4):
            app.processEvents()
        check("全部卡渲染失败时按钮仍禁用（无可修项）",
              not panel2.repair_all_btn.isEnabled())

# 修法本身：boundingRect 用 QRect 重载
import inspect  # noqa: E402

_src = inspect.getsource(cd._FindingCard.__init__)
check("boundingRect 改用 QRect 重载", "QRect(0, 0, _w" in _src,
      "旧的 4 参数重载在 PySide6 不存在")

# ══════════════════════════════════════════════════════════════════════
# 2. 版本值校验（非法值不再让 Modrinth 回 400）
# ══════════════════════════════════════════════════════════════════════
print("== 2. 版本值校验 ==")
from src import net_api as na  # noqa: E402
from src import store_search as ss  # noqa: E402

for good in ("26.3", "1.20.1", "1.21.4", "26.4-snapshot-7"):
    check("合法版本 %-16s 保留" % good, na.normalize_mc_version(good) == good)
for bad in ("26.", "abc", "", "   ", None, "1.20.1 1.21"):
    check("非法版本 %-14r 归零" % bad, na.normalize_mc_version(bad) == "")

facets = ss._mr_facets("mod", {"game_version": "26."})
check("非法版本不进 Modrinth facet", "versions:" not in facets, facets)
facets2 = ss._mr_facets("mod", {"game_version": "26.3", "loader": "fabric"})
check("合法版本进 facet", "versions:26.3" in facets2, facets2)

captured = {}


class _Resp:
    status_code = 200
    headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return {"pagination": {"totalCount": 0}, "data": []}


def _fake_get(url, params=None, **kw):
    captured.update(params or {})
    return _Resp()


with mock.patch.object(ss.requests, "get", _fake_get):
    ss._cf_page_ex("https://x", {}, "q", "mod", 10, 0,
                   {"game_version": "26.", "loader": "fabric"})
check("非法版本不进 CF 的 gameVersion", "gameVersion" not in captured,
      str(captured.get("gameVersion")))
with mock.patch.object(ss.requests, "get", _fake_get):
    ss._cf_page_ex("https://x", {}, "q", "mod", 10, 0,
                   {"game_version": "26.3", "loader": "fabric"})
check("合法版本进 CF 的 gameVersion", captured.get("gameVersion") == "26.3",
      str(captured.get("gameVersion")))

mc_captured = {}


def _mc_get(url, params=None, **kw):
    mc_captured.clear()
    mc_captured.update(params or {})
    return _Resp()


with mock.patch.object(na, "_cached", lambda *a, **k: None), \
     mock.patch.object(na, "_store", lambda *a, **k: None), \
     mock.patch.object(na.requests, "get", _mc_get):
    na._modrinth_versions("P7dR8mSH", "26.", "fabric", 5)
check("详情版本列表不带非法 game_versions",
      "game_versions" not in mc_captured, str(mc_captured))
mc_captured.clear()
with mock.patch.object(na, "_cached", lambda *a, **k: None), \
     mock.patch.object(na, "_store", lambda *a, **k: None), \
     mock.patch.object(na.requests, "get", _mc_get):
    na._modrinth_versions("P7dR8mSH", "26.3", "fabric", 5)
check("详情版本列表带合法 game_versions",
      mc_captured.get("game_versions") == '["26.3"]', str(mc_captured))
check("详情版本列表仍带 loaders", mc_captured.get("loaders") == '["fabric"]',
      str(mc_captured))

# ══════════════════════════════════════════════════════════════════════
# 3. 版本下拉走官方列表（不再是写死的 12 条）
# ══════════════════════════════════════════════════════════════════════
print("== 3. 版本列表动态化 ==")

_tag_payload = [
    {"version": "26.3", "version_type": "release", "date": "2026-10-01"},
    {"version": "26.2", "version_type": "release", "date": "2026-07-01"},
    {"version": "26.4-snapshot-7", "version_type": "snapshot",
     "date": "2026-11-03"},
    {"version": "1.20.1", "version_type": "release", "date": "2023-06-01"},
]


class _TagResp:
    status_code = 200
    headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return _tag_payload


with mock.patch.object(na, "_cached", lambda *a, **k: None), \
     mock.patch.object(na, "_store", lambda *a, **k: None), \
     mock.patch.object(na.requests, "get",
                       lambda *a, **k: _TagResp()):
    versions = na.modrinth_game_versions()
check("官方版本表能取到", versions[:2] == ["26.3", "26.2"], str(versions[:3]))
check("包含 release 与 snapshot", "26.4-snapshot-7" in versions)

with mock.patch.object(na, "_cached", lambda *a, **k: None), \
     mock.patch.object(na.requests, "get",
                       mock.Mock(side_effect=OSError("offline"))):
    check("拉不到时返回空（回退静态表）", na.modrinth_game_versions() == [])

from src.store_filter import StoreFilterPanel  # noqa: E402

panel = StoreFilterPanel()
panel._live_versions = ["26.3", "26.2", "1.21.11"]
panel._fill_versions()
items = [panel.version_combo.itemText(i)
         for i in range(panel.version_combo.count())]
check("下拉里出现实时版本", "26.3" in items, str(items[:5]))
check("下拉里保留静态兜底版本", "1.20.1" in items)


class _TInst:
    game_version = "26.4"
    loader = "fabric"


panel.set_target(_TInst())
items2 = [panel.version_combo.itemText(i)
          for i in range(panel.version_combo.count())]
check("目标实例版本一定在可选项里", "26.4" in items2)
check("目标版本不会被写进过滤值", panel.get_filter()["game_version"] == "",
      panel.get_filter()["game_version"])

print("\nround-218b regression: %d checks, %d failed" % (total, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.stdout.flush()
    os._exit(1)
print("ALL CHECKS PASSED（round-218b 崩溃面板 + 搜索/版本过滤）")
sys.stdout.flush()
os._exit(0)
