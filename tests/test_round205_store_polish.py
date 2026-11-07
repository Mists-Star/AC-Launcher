"""round-205 回归：资源中心四件套（搜索预算 / 版本列表 / 翻译 / 版本建议）。

Qt offscreen；纯逻辑 + 静态契约，不联网：
1. `_recommended` 优先正式版（release），且不把 beta/alpha 当推荐；
2. 「推荐版本」按钮下载的就是 `_recommended()`（不再错下列表第一条）；
3. `_rebuild_rows` 分批 + 行缓存、翻页追加不回顶；
4. `search_all` 给慢源 8s 总预算，不再 join 等死；
5. MC百科按「中文短名 → 中文全名 → 标题 → slug」依次尝试；
6. `_translate` 真的启动 Worker（修复缩进错位后不再「半天没动静」）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src import net_api  # noqa: E402
from src.store_detail import StoreDetailPanel  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def _src_slice(path, start_marker):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    i = text.find(start_marker)
    if i < 0:
        return ""
    j = text.find("\n    def ", i + len(start_marker))
    return text[i:j if j > 0 else len(text)]


def _src_slice_mod(path, start_marker):
    """模块级函数切片：截到下一个 0 缩进的 def / class。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    i = text.find(start_marker)
    if i < 0:
        return ""
    js = [text.find(m, i + len(start_marker)) for m in ("\ndef ", "\nclass ")]
    js = [j for j in js if j > 0]
    j = min(js) if js else len(text)
    return text[i:j]


# ── 1. 推荐版本优先正式版 ──
class FakePanel:
    def __init__(self, versions):
        self._versions = versions

    def _compat_of(self, v):
        return (bool(v.get("ok")), "")


beta = {"id": "b", "version_number": "2.0-beta", "ok": True,
        "version_type": "beta", "date_published": "2026-10-01"}
stable_new = {"id": "s1", "version_number": "1.9", "ok": True,
              "version_type": "release", "date_published": "2026-09-01"}
stable_old = {"id": "s2", "version_number": "1.8", "ok": True,
              "version_type": "release", "date_published": "2026-08-01"}
incompat = {"id": "x", "version_number": "3.0", "ok": False,
            "version_type": "release", "date_published": "2026-11-01"}

fp = FakePanel([incompat, beta, stable_new, stable_old])
rec = StoreDetailPanel._recommended(fp)
check("推荐跳过不兼容版本", rec is not None and rec["id"] != "x", str(rec))
check("推荐优先正式版而非 beta", rec["id"] == "s1", str(rec))

fp2 = FakePanel([beta, {"id": "s3", "version_number": "1.7", "ok": True,
                        "version_type": "release"}])
check("没有正式版时才退兼容版",
      StoreDetailPanel._recommended(fp2)["id"] == "s3")

fp3 = FakePanel([beta])
check("只有 beta 时仍给出（不返回 None）",
      StoreDetailPanel._recommended(fp3) is not None)

# ── 2. 推荐按钮下的是推荐版本 ──
class FakeDl(FakePanel):
    _recommended = StoreDetailPanel._recommended

    def __init__(self, versions):
        super().__init__(versions)
        self.downloaded = None

    def _download_version(self, v):
        self.downloaded = v


fd = FakeDl([incompat, beta, stable_new, stable_old])
StoreDetailPanel._download_latest(fd)
check("下载按钮跟随推荐版本", fd.downloaded is not None
      and fd.downloaded["id"] == "s1", str(fd.downloaded))

# ── 3. 版本列表分批 / 缓存 / 不重顶 ──
snip = _src_slice(os.path.join(HERE, "src", "store_detail.py"),
                  "def _rebuild_rows")
snip_flush = _src_slice(os.path.join(HERE, "src", "store_detail.py"),
                        "def _flush_rows")
check("_rebuild_rows 已找到", bool(snip))
check("按缓存复用行（不再每行 new + deleteLater）",
      "_row_cache" in snip_flush and "deleteLater()" not in snip)
check("分批插入（_flush_rows + QTimer）",
      "_flush_rows" in snip and "QTimer" in snip_flush)
check("追加页不重置滚动条",
      "appending" in snip and "setValue(0)" in snip)

# ── 4. 搜索给慢源设预算 ──
snip_s = _src_slice_mod(os.path.join(HERE, "src", "net_api.py"),
                        "def search_all")
check("search_all 已找到", bool(snip_s))
check("不再 join 等慢源", "f.result()" not in snip_s)
# round-206：预算机制从 ThreadPoolExecutor 换成 daemon 线程（非 daemon
# worker 会在解释器退出时被 join，反而把「关启动器」拖住）。
check("退出不 join（daemon 线程）",
      "daemon=True" in snip_s
      and "from concurrent.futures" not in snip_s
      and "ex = ThreadPoolExecutor" not in snip_s
      and "ex.shutdown" not in snip_s)
check("严格总预算（单调时钟扣减）",
      "time.monotonic()" in snip_s and "th.join(" in snip_s)
check("慢源超时写出参", 'meta["partial"]' in snip_s)

# ── 5. MC百科候选顺序 ──
calls = []
_orig_entry = net_api.mcmod_entry_url
_orig_search = net_api.mcmod_search_url


def _fake_entry(name):
    calls.append(name)
    return "https://www.mcmod.cn/class/999.html" if name == "钠" else \
        net_api.mcmod_search_url(name)


net_api.mcmod_entry_url = _fake_entry
try:
    url = net_api.mcmod_best_entry(["钠", "Sodium", "sodium"])
    check("中文短名命中即返回", "/class/999" in url and calls == ["钠"], str(calls))
    calls.clear()
    url2 = net_api.mcmod_best_entry(["多世界", "Multiverse"])
    check("全不中时退回首个候选的搜索页",
          "search" in url2 and calls == ["多世界", "Multiverse"], str(calls))
finally:
    net_api.mcmod_entry_url = _orig_entry

# ── 6. 翻译确实启动 Worker ──
snip_t = _src_slice(os.path.join(HERE, "src", "store_detail.py"),
                    "def _translate")
snip_r = _src_slice(os.path.join(HERE, "src", "store_detail.py"),
                    "def _render_translation")
check("_translate 内有 w.start()", "w.start()" in snip_t)
check("_render_translation 不再偷偷 start Worker", "w.start()" not in snip_r)
check("_translate 连了 error 回调", "w.error.connect" in snip_t)

print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ALL PASS")
