"""round-208 资源中心整套对齐回归（UI / IA / 运行时）。

对照 docs/specs/round-208-store-alignment/spec.md §6 的 16 条断言。
纯离线：mock 掉数据层与磁盘缓存，不发一个真实 HTTP 请求；Qt 走 offscreen。
"""
import ast
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-62s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8") as f:
        return f.read()


page_src = read("src/pages_browse.py")
filter_src = read("src/store_filter.py")
search_src = read("src/store_search.py")
i18n_src = read("src/i18n.py")

from src.i18n import _STRINGS, t  # noqa: E402
from src import net_api as na  # noqa: E402
from src import store_search as ss  # noqa: E402
from src.store_filter import (  # noqa: E402
    UPSTREAM_TAGS, UPSTREAM_VERSIONS, UPSTREAM_LOADERS,
)

print("\n[1] 两栏骨架 / 详情仍走整页栈（§2.1 / §6-1）")
tree = ast.parse(page_src)
cls = next(n for n in tree.body
           if isinstance(n, ast.ClassDef) and n.name == "StorePage")
methods = [n.name for n in cls.body if isinstance(n, ast.FunctionDef)]
check("QSplitter 已导入且构造为水平两栏",
      "QSplitter" in page_src
      and "self.splitter = QSplitter(Qt.Horizontal)" in page_src
      and "setChildrenCollapsible(False)" in page_src
      and "self.splitter.addWidget(self.filter_panel)" in page_src
      and "self.splitter.addWidget(results_host)" in page_src)
check("详情继续用 _stack 整页切换（不新开窗口）",
      "self._stack.addWidget(self._list_view)" in page_src
      and "self._stack.setCurrentWidget(panel)" in page_src
      and "self._stack.addWidget(panel)" in page_src)
check("StorePage 不构造 QDialog 作为详情",
      "StoreDetailPanel(" in page_src and "QDialog(" not in page_src)
check("旧无限滚动方法已移除",
      "_more" not in methods and "_has_more" not in page_src
      and "_load_curseforge" not in methods)
check("相邻下载/详情方法未被整段替换吞掉",
      all(m in methods for m in ("_download", "_install_modpack",
                                 "_on_mod_downloaded", "_on_cf_pack_downloaded",
                                 "_on_pack_error", "_compat_of_card")))

print("\n[2] 服务端过滤 / 排序 / 真分页（§2.3-2.6 / §6-3~8）")
check("_load 调用 search_store_page 而非 search_all",
      "search_store_page, self._query, self._store_page" in page_src
      and "Worker(search_all" not in page_src)
check("PageSize=40 由 STORE_PAGE_SIZE 驱动",
      "STORE_PAGE_SIZE" in page_src and ss.STORE_PAGE_SIZE == 40)
check("双源游标 / 累积结果传入数据层",
      "self._store_cursors, self._store_results, meta, on_source" in page_src)
# 只检查 _collect_filters 自身：_download / _open_detail 合法调用 _target()，
# 不能因为别处有 inst = self._target() 就判失败。
collect_src = ast.get_source_segment(
    page_src, next(n for n in cls.body
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "_collect_filters")) or ""
check("目标实例版本/加载器由玩家显式选择，不隐式下推（round-209）",
      "self._target()" not in collect_src
      and "getattr(inst" not in collect_src
      and "setPlaceholderText(v)" in filter_src)
check("CF 服务端参数四段齐备",
      all(k in search_src for k in ("gameVersion", "modLoaderType",
                                    "categoryId", "sortField", "pageSize")))
check("MR facets 含 versions / categories / project_type",
      "versions:%s" in search_src and "categories:%s" in search_src
      and "project_type:%s" in search_src)
check("双段 tag 拆分（一套控件喂两个源）",
      ss._category_pair({"category_tag": "6814/optimization"})
      == ("6814", "optimization")
      and ss._category_pair({"category_tag": "/game-mechanics"})
      == ("", "game-mechanics")
      and ss._category_pair({"category_tag": "407/"}) == ("407", ""))
check("category_tag 进入缓存 key（换分类不串旧页）",
      "category_tag" in search_src
      and ss.filters_key({"category_tag": "406/worldgen"})
      != ss.filters_key({"category_tag": "6814/optimization"}))
check("无 _cf_pool 本地重排回退",
      "_cf_pool" not in search_src and "_cf_relevance" not in search_src)
check("排序五档均有 CF / MR 映射且默认仍是实测值 1",
      set(ss.STORE_SORTS) == set(ss._CF_SORT_FIELD) == set(ss._MR_SORT_INDEX)
      and ss._CF_SORT_FIELD["relevance"] == 1)
check("页码器四态由 can_prev / can_next 推导",
      "_update_pager" in methods and "data[\"can_prev\"]" in page_src
      and "data[\"can_next\"]" in page_src
      and "_goto_first" in methods and "_goto_page" in methods)

print("\n[3] 筛选侧栏字段与上游真实取值（§2.2 / §6-2）")
check("筛选字段 6 组：来源/排序/版本/加载器/分类/隐藏已装",
      all(k in filter_src for k in ("filterChanged = Signal()", "source_combo",
                                    "sort_combo", "version_combo",
                                    "loader_combo", "tag_combo",
                                    "hide_installed")))
check("上游 27 条双段分类 tag 原样保留",
      len(UPSTREAM_TAGS) == 27
      and ("406/worldgen", "store.tag_worldgen") in UPSTREAM_TAGS
      and ("6814/optimization", "store.tag_optimization") in UPSTREAM_TAGS)
check("上游 12 个 MC 版本原样保留",
      len(UPSTREAM_VERSIONS) == 12 and "1.20.1" in UPSTREAM_VERSIONS)
check("加载器取值与 CF modLoaderType 枚举一致",
      {x[0] for x in UPSTREAM_LOADERS if x[0]} == set(ss._CF_LOADER_TYPE))
check("reset() 只 emit 一次 filterChanged",
      "self._guard = True" in filter_src
      and "self.filterChanged.emit()" in filter_src
      and filter_src.count("self.filterChanged.emit()") == 2)

print("\n[4] 防抖 / 去重 / 图标 / SWR（§2.7-2.9 / §6-9~11）")
check("防抖 350ms（Prism 口径）", "setInterval(350)" in page_src)
check("请求 key 含关键词/分类/页码/全部筛选/隐藏已装",
      "_request_key" in methods
      and "filters_key(f)" in page_src
      and "hide_installed" in page_src)
check("相同条件不重复发请求", "key == self._last_request_key" in page_src)
check("旧 gen 迟到结果被丢弃",
      "if gen == self._load_gen:" in page_src)
check("占位图立即上屏（断网不空白）",
      "thumb.setPixmap(fallback)" in page_src)
check("视口内才 load，且图标回来不重建卡片",
      "_pump_icons" in methods and "vh + 240" in page_src
      and "self._icon_pending = rest" in page_src
      and "self._img.load(url, size, target, fallback)" in page_src)
check("SWR 三态：先画旧数据 / 刷新中 / 失败保留",
      "cache_lookup(self._swr_key())" in page_src
      and "swr=True" in page_src
      and "store.swr_refreshing" in page_src
      and "store.swr_keep_old" in page_src)
check("徽章复用列表既有判定，不另写一套",
      "self._is_installed(m)" in page_src
      and "self._compat_of_card(m)" in page_src)
check("中文/部分结果文案仍在（round-206/207 不回归）",
      "store.zh_no_hit" in page_src and "store.partial" in page_src
      and "store.partial_loading" in page_src)

print("\n[5] i18n / IA 护栏（§6-14）")
zh, en = _STRINGS["zh-CN"], _STRINGS["en-US"]
check("中英键集合完全对称", set(zh) == set(en),
      "%d = %d" % (len(zh), len(en)))
new_keys = ("store.filter_title", "store.sort_downloads",
            "store.tag_optimization", "store.page_label",
            "store.swr_refreshing", "store.no_results")
check("round-208 新文案键齐备且非英文裸键回退",
      all(k in zh and k in en and zh[k] and en[k] for k in new_keys))
check("store.fetching 双源文案已修正（不再只说 Modrinth）",
      "Modrinth" not in zh["store.fetching"])
import tools.gen_paths as gp  # noqa: E402
pages, errs = gp.collect()
check("IA 路径表覆盖 4 个关键页 / 0 错误",
      all(p in pages for p in gp.REQUIRED_PAGES) and not errs,
      "%d 页 / %d 条" % (len(pages), sum(len(v) for v in pages.values())))
check("资源中心路径 >= 8 条", len(pages.get("store", [])) >= 8)
_saved = gp.REQUIRED_PAGES
gp.REQUIRED_PAGES = _saved + ("ghost_page",)
_, probe_errs = gp.collect()
gp.REQUIRED_PAGES = _saved
check("覆盖率护栏真会失败（不是摆设）",
      any("ghost_page" in e for e in probe_errs))

print("\n[6] 离屏运行时（构造 / 翻页 / 筛选 / 详情 / SWR）")
app = QApplication.instance() or QApplication([])
import src.pages_browse as pb  # noqa: E402

calls = []


def fake_search_store_page(query="", page=0, page_size=40, category="mod",
                           source="all", filters=None, cursors=None,
                           results=None, meta=None, on_source=None):
    calls.append((query, page, filters))
    hits = [{"project_id": "x%d" % i, "slug": "x%d" % i,
             "title": "Mod %d" % i, "description": "desc", "downloads": i,
             "icon_url": "", "author": "a", "source": "modrinth",
             "game_versions": ["1.20.1"], "loaders": ["fabric"]}
            for i in range(page_size)]
    return {"hits": hits,
            "cursors": {"mr": {"offset": page_size, "total": 200},
                        "cf": {"offset": page_size, "total": 200}},
            "results": hits, "page": page, "page_size": page_size,
            "can_prev": page > 0, "can_next": True, "meta": {}}


pb.search_store_page = fake_search_store_page
na._cached = lambda key, ttl=None: None
na._stale = lambda key, max_age=None: None
na._store = lambda key, val: None


class Inst:
    id = "i1"
    name = "Smoke"
    game_version = "1.20.1"
    loader = "fabric"


try:
    p = pb.StorePage(lambda: [Inst()], lambda: Inst())
    check("StorePage 可离屏构造且无异常", True)
    check("运行时 QSplitter.count() == 2", p.splitter.count() == 2)
    check("左侧是筛选面板 / 右侧是结果区",
          p.splitter.widget(0) is p.filter_panel
          and isinstance(p.splitter.widget(1), type(p._list_view)))
    f = p._collect_filters()
    check("默认来源仍是 all（round-140 决策不被偷改）", f["source"] == "all")
    check("默认不隐式带出目标实例版本与加载器（round-209）",
          f["game_version"] == "" and f["loader"] == "",
          "got %r / %r" % (f["game_version"], f["loader"]))
    check("目标实例版本仍作为侧栏 placeholder 提示可见",
          p.filter_panel.version_combo.placeholderText() == "1.20.1")
    check("页码器首屏：第 1 页 / 上一页禁用 / 下一页可用",
          not p.page_prev_btn.isEnabled() and not p.page_first_btn.isEnabled())

    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    check("Worker 回来渲染 40 张卡", p._vbox.count() == 40,
          "count=%d" % p._vbox.count())
    check("下一页按钮按 can_next 启用", p.page_next_btn.isEnabled())

    before = len(calls)
    p._load(reset=True)
    check("相同筛选重复 _load 不重复发请求", len(calls) == before)

    p.page_next_btn.click()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    check("点下一页 -> 第 2 页且上一页可用",
          p._store_page == 1 and p.page_prev_btn.isEnabled()
          and t("store.page_label", page=2) == p.page_label.text())
    p._goto_first()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    check("点回到首页 -> 页码归零", p._store_page == 0)

    emitted = []
    p.filter_panel.filterChanged.connect(lambda: emitted.append(1))
    p.filter_panel.tag_combo.setCurrentIndex(24)
    check("一次筛选操作恰好 emit 一次", len(emitted) == 1)
    for _ in range(40):
        app.processEvents()
        time.sleep(0.02)
    check("筛选变化后回到第 1 页并带上双段 tag",
          p._store_page == 0 and "/" in p._filters.get("category_tag", ""),
          str(p._filters.get("category_tag")))

    m = {"project_id": "x1", "slug": "x1", "title": "Mod 1",
         "description": "desc", "downloads": 1, "icon_url": "",
         "author": "a", "source": "modrinth"}
    p._open_detail(m)
    check("详情在栈内打开（count 2）", p._stack.count() == 2)
    p._close_detail()
    check("详情关闭回列表（count 1）", p._stack.count() == 1)

    card = p._make_card(m)
    thumbs = [w for w in card.findChildren(QLabel)
              if w.width() == 48 and w.height() == 48]
    check("无网络时首屏卡片仍有占位图",
          bool(thumbs) and not thumbs[0].pixmap().isNull())

    # SWR：过期缓存存在时首帧先画旧数据，不等网络
    snap = fake_search_store_page(page=0)
    p._swr_cache[p._swr_key()] = snap
    na._stale = lambda key, max_age=None: {"n": 40}
    p._last_request_key = ""
    p._load(reset=True)
    check("SWR stale 首帧先画旧数据且标记 stale",
          p._swr == "stale" and p._vbox.count() == 40)
    check("SWR stale 显示「正在更新」",
          t("store.swr_refreshing") == p.status.text())
    na._stale = lambda key, max_age=None: None
finally:
    pass

print("\nround-208 store alignment: %d checks, %d failed" % (total, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
# regress.py 用这个标记兜住「离屏 Qt 在解释器 teardown 阶段崩溃」的已知噪音
# （0xC0000409：测试已跑完但进程退出码非 0）。
print("ALL CHECKS PASSED（round-208 资源中心整页对齐 + IA 护栏）")
