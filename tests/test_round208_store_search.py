"""round-208 回归（数据层）：服务端过滤 / 排序 / 双源游标 / 真分页 / SWR。

纯离线：mock 掉 HTTP 与磁盘缓存，不发一个真实请求。
对照规格 docs/specs/round-208-store-alignment/spec.md §2.3-2.9、§6。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import net_api as na  # noqa: E402
from src import store_search as ss  # noqa: E402

fails = []
total_checks = 0


def check(label, cond, extra=""):
    global total_checks
    total_checks += 1
    print("  %s %-60s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def _read(rel):
    with open(os.path.join(HERE, rel), "r", encoding="utf-8") as f:
        return f.read()


src = _read("src/store_search.py")


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


# ── 1. 可追溯性与纪律 ──
check("源码标注 Prism / HMCL / PCL-CE 上游行号",
      "FlameAPI.cpp:267-296" in src
      and "ModrinthAPI.cpp:105-144" in src
      and "ProjectStorage.cs:5-22" in src
      and "HttpCacheHandler.cs:23-99" in src)
# round-211：原来这条只查 docstring 里有没有一句话（删注释即假失败、
# 留注释却改坏逻辑照样通过）。换成可证伪的分页行为判据。
check("未知总数但上一轮空页 -> 不能再翻（无限空页回归）",
      not ss.store_can_continue(
          {"mr": {"offset": 20, "total": -1, "last_count": 0},
           "cf": {"offset": 20, "total": -1, "last_count": 0}}, "all"))
check("未知总数且上一轮有结果 -> 仍可继续（中文名库不误伤）",
      ss.store_can_continue(
          {"mr": {"offset": 20, "total": -1, "last_count": 5},
           "cf": {"offset": 0, "total": 0}}, "all"))
check("没有复活 _cf_pool 本地重排池",
      "_cf_pool" not in src and "_cf_relevance" not in src)
check("真分页 PageSize=40（PCL-CE 口径）", ss.STORE_PAGE_SIZE == 40)
check("默认排序仍是 round-207 实测值 sortField=1",
      ss._CF_SORT_FIELD["relevance"] == 1)
check("排序五档齐全且都有 CF/MR 映射",
      set(ss.STORE_SORTS) == set(ss._CF_SORT_FIELD) == set(ss._MR_SORT_INDEX))


# ── 2. 筛选条件必须进缓存 key（否则换排序/筛选不生效） ──
f1 = {"game_version": "1.20.1", "loader": "fabric", "sort": "relevance"}
f2 = {**f1, "sort": "downloads"}
check("排序变化会改变缓存 key",
      ss.filters_key(f1) != ss.filters_key(f2))
check("版本/加载器/分类都进缓存 key",
      all(k in ss._mr_facets("mod", f1) for k in ("versions:1.20.1", "categories:fabric")))

facets = ss._mr_facets("mod", {"game_version": "1.20.1", "loader": "fabric",
                               "category_id": "optimization"})
check("MR facets 含 project_type / versions / categories",
      "project_type:mod" in facets and "versions:1.20.1" in facets
      and "categories:fabric" in facets and "categories:optimization" in facets)
check("MR facets 是合法 JSON 二维数组",
      isinstance(__import__("json").loads(facets), list)
      and all(isinstance(g, list) for g in __import__("json").loads(facets)))


# ── 3. CF 服务端参数（mock HTTP） ──
captured = {}


def _fake_get(url, params=None, headers=None, timeout=None, proxies=None):
    captured["url"] = url
    captured["params"] = params
    return _Resp({
        "data": [{"id": 1, "slug": "sodium", "name": "Sodium",
                  "summary": "fast", "downloadCount": 100,
                  "logo": {"thumbnailUrl": "https://x/s.png"}}],
        "pagination": {"totalCount": 137},
    })


_orig_get = ss.requests.get
_orig_cached, _orig_store = na._cached, na._store
ss.requests.get = _fake_get
na._cached = lambda key, ttl=None: None
na._store = lambda key, val: None
try:
    hits, total = ss._cf_page_ex(
        "https://mock/v1", {}, "sodium", "mod", 20, 40,
        {"game_version": "1.20.1", "loader": "fabric",
         "category_id": "6814", "sort": "downloads"})
    p = captured.get("params", {})
    check("CF 请求带 gameVersion（服务端版本过滤）", p.get("gameVersion") == "1.20.1")
    check("CF 请求带 modLoaderType（服务端加载器过滤）", p.get("modLoaderType") == 4)
    check("CF 请求带 categoryId（服务端分类过滤）", p.get("categoryId") == "6814")
    check("CF 请求带 sortField/sortOrder/index/pageSize",
          p.get("sortField") == 6 and p.get("sortOrder") == "desc"
          and p.get("index") == 40 and p.get("pageSize") == 20)
    check("CF total 来自 pagination.totalCount", total == 137)
    check("CF 命中映射成统一 hit 形状",
          bool(hits) and hits[0]["slug"] == "sodium"
          and hits[0]["source"] == "curseforge")
finally:
    ss.requests.get = _orig_get

# ── 4. MR 服务端参数 ──
def _fake_mr_get(url, params=None, headers=None, timeout=None, proxies=None):
    captured["mr_params"] = params
    return _Resp({"hits": [{"project_id": "p1", "slug": "sodium",
                            "title": "Sodium", "description": "fast",
                            "downloads": 100, "versions": ["1.20.1"],
                            "categories": ["fabric"]}],
                  "total_hits": 88})


ss.requests.get = _fake_mr_get
try:
    hits, total = ss._mr_page_ex("sodium", 40, 20, "mod",
                                 {"game_version": "1.20.1", "loader": "fabric",
                                  "sort": "downloads"})
    p = captured.get("mr_params", {})
    check("MR 请求带 facets / index / offset / limit",
          "project_type:mod" in p.get("facets", "")
          and p.get("index") == "downloads"
          and p.get("offset") == 40 and p.get("limit") == 20)
    check("MR total 来自 total_hits", total == 88)
    check("MR 命中带 source / game_versions / loaders",
          hits[0]["source"] == "modrinth"
          and hits[0]["game_versions"] == ["1.20.1"]
          and hits[0]["loaders"] == ["fabric"])
finally:
    ss.requests.get = _orig_get


# ── 5. SWR 三态 ──
_orig_stale = na._stale
try:
    na._cached = lambda key, ttl=None: ("FRESH",)
    check("cache_lookup 命中新鲜值 -> fresh", ss.cache_lookup("k")[0] == "fresh")
    na._cached = lambda key, ttl=None: None
    na._stale = lambda key, max_age=None: ("OLD",)
    check("cache_lookup 过期值 -> stale（先画旧数据）",
          ss.cache_lookup("k") == ("stale", ("OLD",)))
    na._stale = lambda key, max_age=None: None
    check("cache_lookup 无缓存 -> miss", ss.cache_lookup("k")[0] == "miss")
finally:
    na._cached, na._store = _orig_cached, _orig_store
    na._stale = _orig_stale


# ── 6. 双源游标 / 真分页（mock 单源函数，不发 HTTP） ──
calls = []
_orig_source = ss.search_store_source


def _fake_source(source, query, offset, limit, category, filters=None):
    calls.append((source, offset, limit))
    n = 10
    base = "m" if source == "mr" else "c"
    hits = [{"project_id": "%s%d_%d" % (base, offset, i),
             "slug": "%s%d_%d" % (base, offset, i),
             "title": "%s %d %d" % (base, offset, i),
             "source": "modrinth" if source == "mr" else "curseforge"}
            for i in range(n)]
    return hits, 100


ss.search_store_source = _fake_source
try:
    r0 = ss.search_store_page("q", page=0, page_size=40, source="all")
    check("双源各自推进 offset，互不覆盖",
          r0["cursors"]["mr"]["offset"] == r0["cursors"]["cf"]["offset"]
          and r0["cursors"]["mr"]["offset"] > 0,
          str(r0["cursors"]))
    check("双源各自记录 total",
          r0["cursors"]["mr"]["total"] == 100
          and r0["cursors"]["cf"]["total"] == 100)
    check("首页返回整页 40 条 / 累积结果 >= 40",
          len(r0["hits"]) == 40 and len(r0["results"]) >= 40,
          "hits=%d results=%d" % (len(r0["hits"]), len(r0["results"])))
    check("首页 can_prev=False / can_next=True",
          r0["can_prev"] is False and r0["can_next"] is True)

    # 翻到第 2 页：把累积结果与游标传回去，验证切片与游标连续性
    calls.clear()
    r1 = ss.search_store_page("q", page=1, page_size=40, source="all",
                              cursors=r0["cursors"], results=r0["results"])
    check("第 2 页从第 40 条开始切片（不重复首页）",
          len(r1["hits"]) == 40 and r1["hits"][0] in r1["results"][40:80])
    check("第 2 页 can_prev=True", r1["can_prev"] is True)
    check("结果不足 80 条时按 targetResultCount 继续拉取",
          len(calls) > 0, "calls=%d" % len(calls))

    # 缓存里已经攒够 80 条 → 翻到第 2 页不应再发任何请求（PCL-CE
    # ProjectQuery.cs:186-191 的「已有多于所需结果，结束处理」）。
    calls.clear()
    big = list(r1["results"]) + [
        {"project_id": "z%d" % i, "slug": "z%d" % i,
         "title": "Z %d" % i, "source": "modrinth"}
        for i in range(max(0, 80 - len(r1["results"])))
    ]
    r1b = ss.search_store_page("q", page=1, page_size=40, source="all",
                               cursors=r1["cursors"], results=big)
    check("累积结果已够一页时不重复请求", len(calls) == 0,
          "calls=%d" % len(calls))
    check("第 2 页切片直接取缓存", r1b["hits"] == big[40:80])

    # 单源失败不拖死另一源
    def _one_fails(source, query, offset, limit, category, filters=None):
        if source == "cf":
            raise RuntimeError("mirror down")
        return _fake_source(source, query, offset, limit, category, filters)

    ss.search_store_source = _one_fails
    r2 = ss.search_store_page("q", page=0, page_size=40, source="all")
    check("单源失败仍返回另一源结果", len(r2["hits"]) > 0)
    check("单源失败被结构化记入 meta.errors",
          any("mirror down" in e for e in r2["meta"]["errors"]))

    # 跨源去重：两源返回同一 slug，只应出现一次
    def _same(source, query, offset, limit, category, filters=None):
        return ([{"project_id": "X", "slug": "same-mod", "title": "Same Mod",
                  "source": source}], 1)

    ss.search_store_source = _same
    r3 = ss.search_store_page("q", page=0, page_size=40, source="all")
    check("跨源同名去重后不出现两张卡",
          len([m for m in r3["results"] if m["slug"] == "same-mod"]) == 1)
finally:
    ss.search_store_source = _orig_source


# ── 7. CanContinue 闸门 ──
check("total=-1 且从未请求过 -> 首轮必须放行",
      ss.store_can_continue({"mr": {"offset": 0, "total": -1},
                             "cf": {"offset": 0, "total": 0}}, "all"))
check("total=-1 且上轮空页 -> 到底（两态语义）",
      not ss.store_can_continue(
          {"mr": {"offset": 0, "total": -1, "last_count": 0},
           "cf": {"offset": 0, "total": 0}}, "all"))
check("两源都到顶则停止",
      not ss.store_can_continue({"mr": {"offset": 20, "total": 20},
                                 "cf": {"offset": 20, "total": 20}}, "all"))
check("单源模式只看该源",
      not ss.store_can_continue({"mr": {"offset": 0, "total": -1},
                                 "cf": {"offset": 20, "total": 20}},
                                "curseforge"))

print("\nround-208 store_search: %d checks, %d failed" %
      (total_checks, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
