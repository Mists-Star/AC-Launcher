"""round-207 回归：资源中心「秒获取」四项改造。

纯逻辑 + 静态契约，不联网、不拉 Qt 窗口：
1. CF 废弃 3×50 相关性池 → 一次 pageSize=limit 请求 + 服务端 sortField 排序；
2. search_all 增加按源回调，快源一返回就通知 UI，不等另一源 / 不等满预算；
   慢源在预算之后才回来也仍会回调一次，结果不再静默丢弃；
3. 搜索请求超时与 search_all 总预算对齐；
4. 资源中心页用 Qt 信号跨线程渐进渲染，翻页不重复插入、旧 gen 不污染。

对照实验（2026-11-07，同一 MCIM 镜像，联网实测，仅记录在 CHANGELOG）：
    不带排序                   → sodium 不在前 20，top4 全是不相关项目
    sortField=1&sortOrder=desc → sodium 排第 1
本测试不复现联网部分，只锁死代价与接线。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import net_api  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def _read(rel):
    with open(os.path.join(HERE, rel), "r", encoding="utf-8") as f:
        return f.read()


api = _read("src/net_api.py")
ui = _read("src/pages_browse.py")
i18n_src = _read("src/i18n.py")

# ── 1. 相关性池已废弃，排序交回服务端 ──
check("不再有 _cf_pool / _cf_relevance",
      "_cf_pool" not in api.replace("_cf_pool``", "")
      and "def _cf_relevance" not in api)
check("不再有 150 条池常量 / 池缓存键",
      "_CF_POOL_STEP" not in api and "_CF_POOL_PAGES" not in api
      and "cfpool:" not in api)
check("CF 池的非 daemon 线程池已消失",
      "max_workers=4" not in api)

i = api.find("def _cf_page")
cf_page = api[i:api.find("def search_curseforge", i)]
check("_cf_page 存在", bool(cf_page))
check("一次请求带服务端排序",
      '"sortField": 1' in cf_page and '"sortOrder": "desc"' in cf_page)
check("pageSize=limit / index=offset（服务端分页）",
      '"pageSize": limit' in cf_page and '"index": offset' in cf_page)
check("CF 搜索请求数固定为 1", cf_page.count("requests.get(") == 1,
      "%d 次" % cf_page.count("requests.get("))

i = api.find("def search_curseforge")
cf_search = api[i:api.find("def _norm_title", i)]
check("首屏不再走池切片", "_cf_pool(" not in cf_search
      and "offset:offset + limit" not in cf_search)
check("两路都汇到单次请求", "cf_page(" in cf_search
      or "_cf_page(" in cf_search)
check("中文 CF 搜索同样带服务端排序",
      i18n_src is not None and api.count('"sortField": 1') >= 2,
      "%d 处" % api.count('"sortField": 1'))

# ── 2. 超时对齐预算 ──
check("搜索超时独立常量且等于总预算",
      "_SEARCH_TIMEOUT = 8.0" in api
      and "_SEARCH_BUDGET = _SEARCH_TIMEOUT" in api
      and net_api._SEARCH_TIMEOUT == net_api._SEARCH_BUDGET)
i = api.find("def search_mods(")
mr_search = api[i:api.find("def ", i + 20)]
check("Modrinth 搜索用 _SEARCH_TIMEOUT", "timeout=_SEARCH_TIMEOUT" in mr_search)
check("下载链路仍用 15s（不被误改）", "_REQUEST_TIMEOUT = 15" in api)

# ── 3. 按源回调：快源先到 / 慢源迟到不丢 ──
i = api.find("def search_all")
snip = api[i:api.find("def _norm_title", i)]
check("search_all 增加 on_source 出参", "on_source=None" in snip)
check("每个源一返回就回调（写 box 之后立刻）",
      "box[key] = hits" in snip
      and snip.find("on_source(_SEARCH_LABELS[key]") > snip.find("box[key] = hits"))
check("回调失败不影响数据", "回调失败不影响数据" in snip)
check("旧契约未回归：daemon / 严格预算 / partial",
      "daemon=True" in snip and "th.join(" in snip
      and "time.monotonic()" in snip and 'meta["partial"]' in snip
      and "from concurrent.futures" not in snip)

events = []


def _fast(*a, **kw):
    time.sleep(0.02)
    return [{"slug": "alpha", "title": "Alpha", "source": "modrinth",
             "project_id": "a"}]


def _slow(*a, **kw):
    time.sleep(0.35)
    return []


_orig = {
    "search_mods": net_api.search_mods,
    "search_curseforge": net_api.search_curseforge,
    "curseforge_available": net_api.curseforge_available,
    "curseforge_keyless_enabled": net_api.curseforge_keyless_enabled,
    "_SEARCH_BUDGET": net_api._SEARCH_BUDGET,
}
net_api.search_mods = _fast
net_api.search_curseforge = _slow
net_api.curseforge_available = lambda: True
net_api.curseforge_keyless_enabled = lambda: False
net_api._SEARCH_BUDGET = 0.1
try:
    t0 = time.monotonic()
    rows = net_api.search_all(
        "q", meta={}, on_source=lambda label, hits: events.append(
            (label, len(hits), time.monotonic())))
    dt = time.monotonic() - t0
    # 必须等慢源线程真的跑完再恢复 monkeypatch，否则它会在恢复后
    # 解析到真实 search_curseforge 而发起网络请求。
    time.sleep(0.40)
finally:
    for key, value in _orig.items():
        setattr(net_api, key, value)

check("快源结果仍完整返回", len(rows) == 1 and rows[0]["slug"] == "alpha")
check("按源回调至少两次（两源各一次）", len(events) == 2, str(events[:2]))
check("第一次回调来自快源 Modrinth",
      bool(events) and events[0][0] == "Modrinth")
check("回调发生在函数返回之前（不用等满预算）",
      bool(events) and events[0][2] < t0 + dt and dt < 0.25,
      "%.3fs" % dt)
check("慢源在预算之后回来仍回调，结果不丢弃",
      any(e[0] == "CurseForge" and e[2] > t0 + dt for e in events))

# ── 4. CF 真的只发一个请求，且参数正确 ──
calls = []


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [{"id": 1, "name": "Sodium", "slug": "sodium",
                          "summary": "", "downloadCount": 1,
                          "authors": [{"name": "a"}],
                          "logo": {"url": ""}}]}


def _fake_get(url, **kw):
    calls.append((url, kw))
    return _Resp()


_orig2 = {
    "get": net_api.requests.get,
    "_cached": net_api._cached,
    "_store": net_api._store,
    "_curseforge_key": net_api._curseforge_key,
    "curseforge_keyless_enabled": net_api.curseforge_keyless_enabled,
}
net_api.requests.get = _fake_get
net_api._cached = lambda key, ttl=None: None
net_api._store = lambda key, val: None
net_api._curseforge_key = lambda: ""
net_api.curseforge_keyless_enabled = lambda: True
try:
    net_api.search_curseforge("sodium", 0, 20, "mod")
    net_api.search_curseforge("sodium", 40, 20, "mod")
finally:
    net_api.requests.get = _orig2["get"]
    net_api._cached = _orig2["_cached"]
    net_api._store = _orig2["_store"]
    net_api._curseforge_key = _orig2["_curseforge_key"]
    net_api.curseforge_keyless_enabled = _orig2["curseforge_keyless_enabled"]

check("一次搜索 = 一次 HTTP 请求", len(calls) == 2,
      "两次调用共 %d 个请求" % len(calls))
if calls:
    p0 = calls[0][1].get("params", {})
    check("首屏 pageSize=20 / index=0",
          p0.get("pageSize") == 20 and p0.get("index") == 0, str(p0))
    check("请求带 sortField=1&desc",
          p0.get("sortField") == 1 and p0.get("sortOrder") == "desc")
    check("请求超时 == 搜索总预算",
          calls[0][1].get("timeout") == net_api._SEARCH_BUDGET)
if len(calls) == 2:
    p1 = calls[1][1].get("params", {})
    check("翻页走服务端 index=40（不再本地切片）", p1.get("index") == 40,
          str(p1))

# ── 5. UI：跨线程信号 + 渐进渲染 + 守卫 ──
check("StorePage 定义按源信号",
      "sourcePartial = Signal(str, object, int)" in ui)
check("信号连到槽", "sourcePartial.connect(self._on_source_partial)" in ui)
# round-208 整页重做后 _load 改走 search_store_page，但 round-207 的三条
# 行为契约必须继续成立：渐进渲染只在「整页重置 + 首页」启用、按源回调仍
# 传进 Worker、_on_loaded 仍支持 partial 首帧。按新链路写等价判据，
# 不把旧函数名当成行为本身（旧断言固化实现会造「变差了」的假信号）。
check("_load 只在整页重置且首页时启用渐进（翻页不重复插入）",
      "bool(reset and self._source == \"all\"" in ui
      and "self._store_page == 0" in ui)
check("on_source 传进 Worker（按源渐进渲染仍在）",
      "on_source)" in ui
      and "self.sourcePartial.emit(label, hits, g)" in ui)
check("_on_loaded 有 partial 参数（渐进首帧）",
      "def _on_loaded(self, result, reset: bool" in ui
      and "partial: bool = False" in ui)
check("渐进首帧不动到底闸门",
      "if not partial:" in ui and "partial=True" in ui)
check("迟到源走去重增量补卡",
      "def _append_source_rows" in ui and "self._partial_done_gen = gen" in ui)
check("旧 gen 结果被丢弃",
      "gen != self._load_gen" in ui)
check("渐进文案中英齐全",
      '"store.partial_loading"' in i18n_src
      and i18n_src.count('"store.partial_loading"') == 2)

print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ALL CHECKS PASSED（round-207 资源中心秒获取）")
