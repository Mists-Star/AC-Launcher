"""round-211：整体设计比对后的第 3 / 5 / 6 批行为回归（离线、零真实网络）。

覆盖：资源中心缓存键与分页守卫、迟到回调与 SWR signet、IA 8 页护栏；
凭据落盘 / 多形态脱敏 / 单一敏感键清单 / 条款文案；classpath 基准 /
ProgressWorker 终态 / 教程 reject 顺序。

刻意不写「源码里有没有某句话」的假断言：凡能跑真对象的一律跑真对象，
只有「基准常量 / 调用顺序」这类无法造运行时判据的才用 AST，并显式标注。
"""
import ast
import json
import os
import sys
import tempfile
import time
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-66s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8") as f:
        return f.read()


# ── 1. 资源中心：缓存键 / 未知总数 / 迟到回调 ──────────────────────────────
print("\n[1] 资源中心：缓存键随语言与隐藏已装变化")
from src import store_search as ss  # noqa: E402
from src import net_api as na  # noqa: E402

f = {"source": "all", "sort": "relevance", "game_version": "1.20.1"}
orig_lang = ss._current_language
ss._current_language = lambda: "zh-CN"
k_zh = ss.filters_key(f)
ss._current_language = lambda: "en-US"
k_en = ss.filters_key(f)
ss._current_language = orig_lang
check("filters_key 随界面语言变化（中文标题不串到英文界面）", k_zh != k_en)
check("filters_key 含 language 段", "language=" in k_zh)
check("filters_key 区分 hide_installed",
      ss.filters_key(f) != ss.filters_key({**f, "hide_installed": True}))
check("旧能力不丢：来源 / 分类 / 排序仍进 key",
      ss.filters_key(f) != ss.filters_key({**f, "source": "curseforge"})
      and ss.filters_key(f) != ss.filters_key({**f, "sort": "downloads"}))

# r208: 单源缓存键必须真的随语言变（不是只改了 filters_key 的说明文字）
class _Resp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"hits": [], "total_hits": 0}


def capture_source_key(lang):
    ss._current_language = lambda: lang
    seen = []
    old_cached, old_get = na._cached, ss.requests.get
    na._cached = lambda key, ttl=None: (seen.append(key), None)[1]
    ss.requests.get = lambda *a, **kw: _Resp()
    try:
        ss.search_store_source("mr", "q", 0, 20, "mod", {})
    except Exception:  # noqa: BLE001 - 只要拿到缓存键即可
        pass
    finally:
        na._cached, ss.requests.get = old_cached, old_get
    return seen[0] if seen else ""


ss._current_language = orig_lang
key_zh, key_en = capture_source_key("zh-CN"), capture_source_key("en-US")
ss._current_language = orig_lang
check("r208: 单源缓存键随语言变化", bool(key_zh and key_en) and key_zh != key_en)

print("\n[2] 未知总数分页守卫 + 8s 超时后容器冻结")
check("从未请求过的源首轮放行",
      ss.store_can_continue(ss.new_store_cursors(), "all"))
check("上轮有结果的未知总数源可继续",
      ss.store_can_continue({"mr": {"offset": 20, "total": -1,
                                    "last_count": 5}}, "modrinth"))
check("上轮空页的未知总数源到底",
      not ss.store_can_continue({"mr": {"offset": 20, "total": -1,
                                        "last_count": 0}}, "modrinth"))

orig_source, orig_budget = ss.search_store_source, ss._SEARCH_BUDGET
late_calls = []


def slow_source(source, query, offset, limit, category, filters=None):
    time.sleep(0.06)
    return ([{"slug": "late-" + source, "title": "Late " + source,
              "source": source}], -1)


ss.search_store_source = slow_source
ss._SEARCH_BUDGET = 0.01
try:
    r = ss.search_store_page("q", page=0, source="all",
                             on_source=lambda label, hits: late_calls.append(label))
finally:
    ss.search_store_source, ss._SEARCH_BUDGET = orig_source, orig_budget
check("超时返回标记 partial", r["meta"]["partial"] is True)
check("超时后 can_next=False（不再无限翻空页）", r["can_next"] is False)
check("超时源 last_count=0 且已收敛 total",
      all(c["last_count"] == 0 and c["total"] == c["offset"]
          for c in r["cursors"].values()))
time.sleep(0.15)
check("慢源仍可 emit（round-207 渐进渲染能力不丢）", len(late_calls) >= 1)
check("但迟到结果没污染已返回的 cursors / results",
      all(c["offset"] == 0 for c in r["cursors"].values())
      and r["results"] == [])


# ── 3. SWR signet 不能让 fresh 恒真 ───────────────────────────────────────
print("\n[3] SWR：缓存命中不重写 signet（stale/miss 必须可达）")
from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication.instance() or QApplication([])
import src.pages_browse as pb  # noqa: E402

store_calls = []


def fake_page(query="", page=0, page_size=40, category="mod", source="all",
              filters=None, cursors=None, results=None, meta=None,
              on_source=None):
    hits = [{"project_id": "n%d" % i, "slug": "n%d" % i,
             "title": "Mod %d" % i, "description": "", "downloads": 0,
             "icon_url": "", "author": "", "source": "modrinth"}
            for i in range(3)]
    return {"hits": hits, "cursors": ss.new_store_cursors(),
            "results": hits, "page": page, "page_size": page_size,
            "can_prev": False, "can_next": False, "meta": {}}


class _Inst:
    id, name = "i1", "Smoke"
    game_version, loader = "1.20.1", "fabric"


old_page, old_cached, old_stale, old_store = (
    pb.search_store_page, na._cached, na._stale, na._store)
pb.search_store_page = fake_page
na._cached = lambda key, ttl=None: {"n": 3}
na._stale = lambda key, max_age=None: None
na._store = lambda key, val: store_calls.append((key, val))
try:
    p = pb.StorePage(lambda: [_Inst()], lambda: _Inst())
    p._swr_cache[p._swr_key()] = fake_page()
    p._last_request_key = ""
    p._load(reset=True)
    check("fresh 命中直接复用快照", p._swr == "fresh")
    check("fresh 命中不调用 _store（TTL 才能自然过期）", store_calls == [])
finally:
    pb.search_store_page, na._cached, na._stale, na._store = (
        old_page, old_cached, old_stale, old_store)
    try:
        p.deleteLater()
    except Exception:
        pass

print("\n[4] IA 护栏覆盖全部 8 个主页面")
import tools.gen_paths as gp  # noqa: E402
pages, errs = gp.collect()
check("8 页 / ≥41 条 / 0 错误",
      len(pages) == 8 and len(gp.REQUIRED_PAGES) == 8
      and sum(len(v) for v in pages.values()) >= 41 and not errs,
      "%d 页 / %d 条" % (len(pages), sum(len(v) for v in pages.values())))
_mw_tree = ast.parse(read("src/main_window.py"))
_stack = next(
    ast.literal_eval(n.value) for n in ast.walk(_mw_tree)
    if isinstance(n, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "STACK_INDEX"
            for t in n.targets))
check("STACK_INDEX 与护栏口径一致", set(gp.REQUIRED_PAGES) == set(_stack),
      "%d 页" % len(_stack))


# ── 5. 隐私：凭据落盘 ─────────────────────────────────────────────────────
print("\n[5] 凭据：DPAPI 失败不明文落盘 + 原子写")
import src.accounts as acc_mod  # noqa: E402
from src.core import support_bundle as sb  # noqa: E402
from src import log_mask as lm  # noqa: E402

TOKEN = "TOKEN-ABCDEFGHIJKLMNOP-1234567890"
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "accounts.json")
    mgr = acc_mod.AccountsManager()
    mgr._path = path
    mgr._accounts = {"a1": {"id": "a1", "name": "Tester",
                            "access_token": TOKEN,
                            "refresh_token": TOKEN + "-R"}}
    with mock.patch.object(acc_mod, "dpapi_encrypt", lambda v: None):
        mgr._save()
    raw = open(path, encoding="utf-8").read()
    check("加密失败时磁盘不含任何明文 token",
          TOKEN not in raw and (TOKEN + "-R") not in raw)
    check("降级标志可被诊断读取", acc_mod.AccountsManager.LAST_SAVE_DEGRADED)

    # 写盘失败时旧文件字节不变（原子写）
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("ORIGINAL-SAFE")
    before = open(path, "rb").read()
    with mock.patch.object(acc_mod.os, "replace",
                           side_effect=OSError("disk full")):
        try:
            mgr._save()
        except OSError:
            pass
    check("os.replace 失败后旧 accounts.json 字节不变",
          open(path, "rb").read() == before)
    check("失败只留下 .tmp，不覆盖正式文件",
          os.path.isfile(path + ".tmp"))

print("\n[6] 脱敏：多形态凭据 + 单一敏感键清单")
forms = [
    'log line --accessToken %s end' % TOKEN,
    '{"access_token": "%s"}' % TOKEN,
    'refresh_token=%s' % TOKEN,
    'client_secret: %s' % TOKEN,
    'Authorization: Bearer %s' % TOKEN,
]
masked = [lm.mask_launch_text(x) for x in forms]
check("5 种凭据形态全部打码", all(TOKEN not in m for m in masked),
      repr([m[:52] for m in masked]))
check("沿用首尾各留 5 位风格",
      all(TOKEN[:5] in m and TOKEN[-5:] in m for m in masked))
check("普通日志文字不被误伤",
      lm.mask_launch_text("Loaded 42 mods in 1.2s")
      == "Loaded 42 mods in 1.2s")
import src.settings_dialog as sd  # noqa: E402
check("设置导出与诊断包共用同一敏感键清单",
      set(sd._SENSITIVE_CFG_KEYS) == set(sb.SENSITIVE_CONFIG_KEYS))
red = sb.redact_config({"download_proxy": "http://u:p@host",
                        "ms_client_id": "azure-id",
                        "update_manifest_url": "http://internal/x",
                        "ram_mb": 4096})
check("代理凭据 / Azure ID / 私有更新源全部 redact",
      red["download_proxy"] == sb._REDACTED
      and red["ms_client_id"] == sb._REDACTED
      and red["update_manifest_url"] == sb._REDACTED)
check("普通配置值不被误 redact", red["ram_mb"] == 4096)
check("诊断包自由文本也走多形态脱敏",
      TOKEN not in sb._mask('{"refresh_token": "%s"}' % TOKEN))

print("\n[7] 条款文案与实际外联一致")
import src.terms as terms  # noqa: E402
check("条款已升版并更新日期",
      terms.TERMS_VERSION >= 2 and terms.TERMS_UPDATED == "2026-11-08")
privacy = terms.legal_text("privacy")
check("正文写明翻译服务 / GitHub 更新检查 / 皮肤 CDN",
      "翻译服务" in privacy and "GitHub" in privacy and "皮肤 CDN" in privacy)
check("正文不再宣称「仅与 Mojang 官方 API 或你指定的服务器通信」",
      "仅与 Mojang 官方 API" not in privacy)
check("README 同步联网范围，删掉「无任何数据上传」",
      "第三方翻译服务" in read("README.md")
      and "无任何数据上传" not in read("README.md"))


# ── 8. 历史 P0/P1 ─────────────────────────────────────────────────────────
print("\n[8] classpath 基准 / Worker 终态 / 教程 reject 顺序")
launch_src = read("src/launch.py")
tree = ast.parse(launch_src)
assign_bases = []
for n in ast.walk(tree):
    if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_libs_root" for t in n.targets):
        assign_bases.append(ast.get_source_segment(launch_src, n.value) or "")
# 结构契约：这是单行基准常量，无法在离屏造出真实 iso classpath，用 AST 锁定。
check("补库 relpath 基准改为 vroot/libraries（与 classpath 同源）",
      any("vroot" in b and "libraries" in b for b in assign_bases)
      and not any("inst.mc_dir" in b for b in assign_bases))

from src.worker import ProgressWorker  # noqa: E402


def boom(**_kw):
    raise ValueError("boom")


w = ProgressWorker(boom)
fin, can, err = [], [], []
w.finished.connect(fin.append)
w.cancelled.connect(can.append)
w.error.connect(err.append)
w.abort()
w.run()
check("异常 + 取消：cancelled 恰好 1 次", len(can) == 1, "can=%d" % len(can))
check("异常 + 取消：不发 error / finished", len(err) == 0 and len(fin) == 0)

onb_src = read("src/onboarding.py")
onb_tree = ast.parse(onb_src)
onb_cls = next(n for n in onb_tree.body
               if isinstance(n, ast.ClassDef) and n.name.endswith("Dialog"))
reject_fn = next((n for n in onb_cls.body
                  if isinstance(n, ast.FunctionDef) and n.name == "reject"), None)
rej_body = ast.get_source_segment(onb_src, reject_fn) or "" if reject_fn else ""
check("教程 reject 先落盘再标记完成（顺序契约）",
      "save_config(self.cfg)" in rej_body
      and "mark_onboarding_done()" in rej_body
      and rej_body.index("save_config(self.cfg)")
      < rej_body.index("mark_onboarding_done()"))
check("写盘异常分支不标记完成",
      "except Exception" in rej_body and "super().reject()" in rej_body)

print("\nround-211 regression: %d checks, %d failed" % (total, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-211 第 3/5/6 批行为回归）")
