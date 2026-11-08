"""round-209：资源中心「FTB 系列搜不到」回归（离线，零真实 HTTP）。

复现主理人 2026-11-08 报的现象：round-208 整页重做后，默认搜索被目标
实例的 MC 版本 / 加载器静默收窄，CF「FTB」从 409 条变 58 条（-86%）、
「FTB Quests」从 140 变 27 条且 can_next=False，FTB 官方 Forge/NeoForge
版本整批消失。本测试用一个**会按请求参数过滤的假服务端**重放该现象，
并证明修复后默认路径不再发送这些参数。

同时覆盖第二个回归：页面级 SWR / 请求去重 key 漏了 ``source``，切
「全部 → 仅 CurseForge」会复用旧快照、不发新请求，筛选看起来是死的。
"""
import ast
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-64s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8") as f:
        return f.read()


page_src = read("src/pages_browse.py")
filter_src = read("src/store_filter.py")
search_src = read("src/store_search.py")

from src import net_api as na          # noqa: E402
from src import store_search as ss     # noqa: E402

print("\n[1] 静态契约：默认搜索不得隐式继承目标实例")
tree = ast.parse(page_src)
cls = next(n for n in tree.body
           if isinstance(n, ast.ClassDef) and n.name == "StorePage")
collect = next(n for n in cls.body
               if isinstance(n, ast.FunctionDef) and n.name == "_collect_filters")
body = ast.get_source_segment(page_src, collect) or ""
check("_collect_filters 不再读 _target()",
      "self._target()" not in body and "getattr(inst" not in body)
check("_collect_filters 只取 filter_panel.get_filter()",
      "self.filter_panel.get_filter()" in body)
# 用 AST 查真实调用，不查说明文字（round-206 教训：docstring 里提到旧实现
# 会让字面量断言假失败）。
ftree = ast.parse(filter_src)
fcls = next(n for n in ftree.body
            if isinstance(n, ast.ClassDef) and n.name == "StoreFilterPanel")
set_target = next(n for n in fcls.body
                  if isinstance(n, ast.FunctionDef) and n.name == "set_target")
attrs = [n.func.attr for n in ast.walk(set_target)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
check("set_target 用 placeholder 提示，不写 currentText",
      "setPlaceholderText" in attrs and "setCurrentText" not in attrs
      and "addItem" not in attrs)
check("_on_target_changed 注释不再宣称隐含筛选",
      "不再随目标实例隐式收窄" in page_src)
check("filters_key 纳入 source",
      ss.filters_key({"source": "all", "sort": "relevance"})
      != ss.filters_key({"source": "curseforge", "sort": "relevance"}))
check("filters_key 仍区分分类 / 排序（旧能力不丢）",
      ss.filters_key({"category_tag": "406/worldgen"})
      != ss.filters_key({"category_tag": "6814/optimization"})
      and ss.filters_key({"sort": "downloads"})
      != ss.filters_key({"sort": "relevance"}))


# ── 会按参数过滤的假服务端 ────────────────────────────────────────────────
class Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


CF_ROWS = [
    {"id": 1, "name": "FTB Quests (NeoForge)", "slug": "ftb-quests-neoforge",
     "game_versions": ["1.21.1"], "loaders": ["neoforge"]},
    {"id": 2, "name": "FTB Library (NeoForge)", "slug": "ftb-library-neoforge",
     "game_versions": ["1.21.1"], "loaders": ["neoforge"]},
    {"id": 3, "name": "FTB Teams (Forge)", "slug": "ftb-teams-forge",
     "game_versions": ["1.20.1"], "loaders": ["forge"]},
    {"id": 4, "name": "FTB Quests (Fabric)", "slug": "ftb-quests-fabric",
     "game_versions": ["1.20.1"], "loaders": ["fabric"]},
]
MR_ROWS = [
    {"project_id": "m1", "slug": "ftb-quests-freeze-fix",
     "title": "FTB Quests Freeze Fix", "description": "", "downloads": 10,
     "icon_url": "", "author": "a", "versions": ["1.20.1"],
     "categories": ["fabric"]},
    {"project_id": "m2", "slug": "re-ftbq-localization",
     "title": "Re-FTBQLocalizationKeys", "description": "", "downloads": 9,
     "icon_url": "", "author": "a", "versions": ["1.20.1"],
     "categories": ["fabric"]},
]
CF_LOADER = {1: "forge", 4: "fabric", 5: "quilt", 6: "neoforge"}
calls = []


def fake_get(url, params=None, headers=None, timeout=None, proxies=None, **kw):
    p = dict(params or {})
    calls.append((url, p))
    is_cf = "mods/search" in url
    if is_cf:
        rows = list(CF_ROWS)
        if p.get("gameVersion"):
            rows = [r for r in rows if p["gameVersion"] in r["game_versions"]]
        if p.get("modLoaderType"):
            ld = CF_LOADER.get(int(p["modLoaderType"]))
            rows = [r for r in rows if ld in r["loaders"]]
        return Resp({"data": rows[:int(p.get("pageSize", 20))],
                     "pagination": {"totalCount": len(rows)}})
    facets = json.loads(p.get("facets") or "[]")
    flat = [x for group in facets for x in group]
    rows = list(MR_ROWS)
    if any(x.startswith("versions:") for x in flat):
        v = next(x.split(":", 1)[1] for x in flat if x.startswith("versions:"))
        rows = [r for r in rows if v in r["versions"]]
    if any(x.startswith("categories:") for x in flat):
        ld = next(x.split(":", 1)[1] for x in flat
                  if x.startswith("categories:"))
        rows = [r for r in rows if ld in r["categories"]]
    return Resp({"hits": rows[:int(p.get("limit", 20))],
                 "total_hits": len(rows)})


ss.requests.get = fake_get
na._cached = lambda key, ttl=None: None
na._stale = lambda key, max_age=None: None
na._store = lambda key, val: None
na._curseforge_key = lambda: None
na.curseforge_keyless_enabled = lambda: True

print("\n[2] 默认请求不含版本 / 加载器 / 分类；显式筛选仍下推服务端")
ss.search_store_source("cf", "FTB", 0, 20, "mod", {})
p_cf = calls[-1][1]
check("默认 CF 不带 gameVersion", "gameVersion" not in p_cf)
check("默认 CF 不带 modLoaderType", "modLoaderType" not in p_cf)
check("默认 CF 不带 categoryId", "categoryId" not in p_cf)
check("默认 CF 仍带服务端排序 / 分页 / classId",
      p_cf.get("sortField") == 1 and p_cf.get("sortOrder") == "desc"
      and p_cf.get("index") == 0 and p_cf.get("classId") == 6)

ss.search_store_source("mr", "FTB", 0, 20, "mod", {})
p_mr = calls[-1][1]
check("默认 MR facets 只有 project_type",
      json.loads(p_mr["facets"]) == [["project_type:mod"]])

explicit = {"game_version": "1.20.1", "loader": "fabric",
            "category_tag": "6814/optimization", "sort": "downloads"}
ss.search_store_source("cf", "FTB", 0, 20, "mod", explicit)
p_cf2 = calls[-1][1]
check("显式筛选仍下推 CF 四段",
      p_cf2.get("gameVersion") == "1.20.1"
      and p_cf2.get("modLoaderType") == 4
      and p_cf2.get("categoryId") == "6814"
      and p_cf2.get("sortField") == 6)
ss.search_store_source("mr", "FTB", 0, 20, "mod", explicit)
p_mr2 = calls[-1][1]
flat = [x for g in json.loads(p_mr2["facets"]) for x in g]
check("显式筛选仍下推 MR facets 三段",
      "versions:1.20.1" in flat and "categories:fabric" in flat
      and "categories:optimization" in flat
      and p_mr2.get("index") == "downloads")

print("\n[3] 端到端场景：默认路径能搜到 FTB 官方本体")
def run(filters):
    calls.clear()
    r = ss.search_store_page("FTB", 0, ss.STORE_PAGE_SIZE, "mod", "all",
                             filters, None, None, {})
    titles = [str(m.get("title", "")) for m in r["hits"]]
    return r, titles, [p for _, p in calls]


r_default, t_default, params_default = run({})
check("默认搜索不带任何版本/加载器参数（回归红线）",
      all("gameVersion" not in p and "modLoaderType" not in p
          for p in params_default))
check("默认结果含 FTB Quests (NeoForge) 官方本体",
      any("FTB Quests (NeoForge)" in x for x in t_default))
check("默认结果含 FTB Library (NeoForge) 官方本体",
      any("FTB Library (NeoForge)" in x for x in t_default))
check("默认 result 总数 = 全库条数（CF 4 + MR 2）",
      len(r_default["results"]) == 6,
      "got %d" % len(r_default["results"]))

r_narrow, t_narrow, params_narrow = run(
    {"game_version": "1.20.1", "loader": "fabric"})
check("重放旧隐式过滤确实复现「FTB 官方本体消失」",
      not any("NeoForge" in x for x in t_narrow)
      and len(r_narrow["results"]) < len(r_default["results"]),
      "narrow=%d default=%d" % (len(r_narrow["results"]),
                                len(r_default["results"])))
check("旧隐式过滤会带 gameVersion + modLoaderType",
      any(p.get("gameVersion") == "1.20.1" and p.get("modLoaderType") == 4
          for p in params_narrow))


print("\n[4] 页面级：切来源后 SWR / 请求 key 变化且真的重搜")
from PySide6.QtWidgets import QApplication  # noqa: E402
from src import pages_browse as pb         # noqa: E402

app = QApplication.instance() or QApplication([])
page_calls = []


def fake_page(query="", page=0, page_size=40, category="mod", source="all",
              filters=None, cursors=None, results=None, meta=None,
              on_source=None):
    page_calls.append(dict(source=source, filters=dict(filters or {})))
    return {
        "hits": [{"title": "x", "slug": "x%d" % i, "source": "modrinth",
                  "description": "", "icon_url": "", "author": "a",
                  "downloads": 0, "project_id": "x%d" % i,
                  "game_versions": [], "loaders": []}
                 for i in range(page_size)],
        "cursors": ss.new_store_cursors(), "results": [], "page": page,
        "page_size": page_size, "can_prev": False, "can_next": True,
        "meta": {},
    }


pb.search_store_page = fake_page


class Inst:
    id = "i1"
    name = "Smoke"
    game_version = "1.20.1"
    loader = "fabric"


try:
    p = pb.StorePage(lambda: [Inst()], lambda: Inst())
    check("目标实例 1.20.1/fabric 存在", Inst().game_version == "1.20.1")
    f0 = p._collect_filters()
    check("默认 filters 不带 game_version / loader",
          f0["game_version"] == "" and f0["loader"] == "",
          "got %r / %r" % (f0["game_version"], f0["loader"]))
    check("侧栏 placeholder 仍显示目标版本但不进筛选",
          p.filter_panel.version_combo.placeholderText() == "1.20.1"
          and p.filter_panel.version_combo.currentText() == "")

    key_swr_all = p._swr_key()
    key_req_all = p._request_key()
    idx_cf = p.filter_panel.source_combo.findData("curseforge")
    p.filter_panel.source_combo.setCurrentIndex(idx_cf)
    p._search_timer.stop()
    p._filters = p._collect_filters()
    check("切来源后 _swr_key 变化（不复用旧源快照）",
          p._swr_key() != key_swr_all)
    check("切来源后 _request_key 变化（不被去重跳过）",
          p._request_key() != key_req_all)

    p._last_request_key = ""
    before = len(page_calls)
    p._load(reset=True)
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    check("切来源后确实发出新请求", len(page_calls) > before,
          "calls %d -> %d" % (before, len(page_calls)))
    check("新请求带 source=curseforge 且仍不带版本/加载器",
          page_calls[-1]["source"] == "curseforge"
          and page_calls[-1]["filters"]["game_version"] == ""
          and page_calls[-1]["filters"]["loader"] == "")

    # 玩家显式选版本 / 加载器时，服务端过滤能力必须还在。
    fp = p.filter_panel
    fp.version_combo.blockSignals(True)
    fp.loader_combo.blockSignals(True)
    fp.version_combo.setCurrentText("1.20.1")
    fp.loader_combo.setCurrentIndex(fp.loader_combo.findData("fabric"))
    f2 = p._collect_filters()
    check("显式选版本 / 加载器仍会下推服务端",
          f2["game_version"] == "1.20.1" and f2["loader"] == "fabric")
    fp.version_combo.setCurrentIndex(0)
    fp.loader_combo.setCurrentIndex(0)
    fp.version_combo.blockSignals(False)
    fp.loader_combo.blockSignals(False)
finally:
    pass

print("\nround-209 store regression: %d checks, %d failed" %
      (total, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-209 FTB 搜索回归 + 切来源缓存键）")
