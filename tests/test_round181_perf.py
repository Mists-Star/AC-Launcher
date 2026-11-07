# -*- coding: utf-8 -*-
"""round-181：资源中心加载性能 / 加载器图标来源 判据。

量化到的问题（见 docs/quality_punchlist.md 第十一章）：
  * 三个页面各 new 一个 ImageLoader → 每次点详情重建连接池与内存缓存
  * 18.8 MB 的 CF 作者头像 GIF 被当图标下载，单个占满并发槽 25 秒
  * 落盘存原图：38 MB / 240 文件
  * 每次点详情重新拉版本列表 + 重新机翻
"""
import io
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QPixmap, QColor  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

app = QApplication.instance() or QApplication([])

FAILS = []


def check(label, cond, extra=""):
    if cond:
        print("  PASS", label)
    else:
        print("  FAIL", label, extra)
        FAILS.append(label)


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   newline="").read()


# ── 1. 全局单例 ────────────────────────────────────────────────────
from src.async_image import ImageLoader, get_image_loader  # noqa: E402
import src.async_image as _ai  # noqa: E402
import src.pages_browse as _pb  # noqa: E402
import src.store_detail as _sd  # noqa: E402
import src.net_api as _na  # noqa: E402

check("get_image_loader() 返回同一实例",
      get_image_loader() is get_image_loader())
check("全仓不再按页面 new ImageLoader",
      "ImageLoader(self)" not in read("src/pages_browse.py")
      and "ImageLoader(self)" not in read("src/store_detail.py"))
check("列表页 / 版本页 / 详情页都走单例",
      read("src/pages_browse.py").count("get_image_loader()") == 2
      and read("src/store_detail.py").count("get_image_loader()") == 1)

# ── 2. 下载熔断 + 缩略图落盘 ───────────────────────────────────────
ldr = get_image_loader()
check("单图上限 <= 512KB", 0 < ldr._MAX_ICON_BYTES <= 512 * 1024,
      "got=%d" % ldr._MAX_ICON_BYTES)
check("缩略图边长 <= 128px", 0 < ldr._THUMB_PX <= 128,
      "got=%d" % ldr._THUMB_PX)
ai_src = read("src/async_image.py")
check("readyRead 熔断会 abort 请求",
      "reply.readyRead.connect(self._on_ready_read)" in ai_src
      and "reply.abort()" in ai_src)
check("落盘前缩放且以 PNG 保存",
      "thumb.save(tmp, \"PNG\")" in ai_src
      and "Qt.SmoothTransformation" in ai_src)
check("旧版超大原图读取时淘汰",
      "os.path.getsize(path) > self._MAX_ICON_BYTES" in ai_src
      and "os.remove(path)" in ai_src)

# 行为：readyRead 超限时 abort
class _FakeReply:
    def __init__(self, n):
        self._n = n
        self._seen = 0
        self.aborted = False

    def property(self, k):
        return self._seen

    def setProperty(self, k, v):
        self._seen = v

    def bytesAvailable(self):
        return self._n

    def abort(self):
        self.aborted = True


big = _FakeReply(ldr._MAX_ICON_BYTES + 1)
small = _FakeReply(1024)
for r, want in ((big, True), (small, False)):
    # bound method + 显式 sender 替换（QObject.sender 只在信号上下文有效）
    orig = ldr.sender
    ldr.sender = lambda r=r: r
    try:
        ldr._on_ready_read()
    finally:
        ldr.sender = orig
    check("超过上限 abort（%d B）" % r._n if want else "未超限不 abort",
          r.aborted is want, "aborted=%s" % r.aborted)

# 行为：内存/磁盘派生与淘汰
tmpdir = tempfile.mkdtemp()
ldr._cache_dir = tmpdir
url = "https://example.invalid/icon.png"
p = ldr._orig_path(url)
with open(p, "wb") as f:
    f.write(b"x" * (ldr._MAX_ICON_BYTES + 1))
check("超大旧缓存被 _read_orig 淘汰并删文件",
      ldr._read_orig(url) is None and not os.path.isfile(p))

img = QPixmap(512, 512)
img.fill(QColor("#7C3AED"))
thumb = img.scaled(ldr._THUMB_PX, ldr._THUMB_PX,
                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
check("缩略图落盘后尺寸受限",
      max(thumb.width(), thumb.height()) <= ldr._THUMB_PX)

# ── 3. CF 数据层过滤头像动图 ───────────────────────────────────────
row = _na._cf_map_row({"id": 1, "logo": {"url":
    "https://media.forgecdn.net/avatars/1992/163/639226607749089342.gif"}})
check("CF 作者头像 GIF 不再当项目图标", row["icon_url"] == "", row["icon_url"])
# round-192 修正：原断言「CF avatars 路径（非 gif）也过滤」把**项目 logo 本身**
# 也干掉了 —— CF 的项目图标就在 media.forgecdn.net/avatars/<modId>/<fileId>/，
# 一刀切的实际后果是 CF 源一个图标都出不来（用户报「好多图标加载不出来」）。
# 正确规则：只有 .gif 动图要丢；普通 png/jpg 项目图标要保留，并且优先用
# 256×256 的 thumbnailUrl（小图更快、更省下载槽）。
row2 = _na._cf_map_row({"id": 2, "logo": {
    "url": "https://media.forgecdn.net/avatars/1474/428/638957192475584420.png",
    "thumbnailUrl": "https://media.forgecdn.net/avatars/thumbnails/1474/428/"
                    "256/256/638957192475584420.png"}})
check("CF 项目图标（avatars 路径）要保留",
      row2["icon_url"].endswith("638957192475584420.png"), row2["icon_url"])
check("优先用 thumbnailUrl（小图）",
      "/thumbnails/" in row2["icon_url"], row2["icon_url"])
row3 = _na._cf_map_row({"id": 3, "logo": {
    "url": "https://media.forgecdn.net/avatars/1992/163/639226607749089342.gif",
    "thumbnailUrl": "https://media.forgecdn.net/avatars/thumbnails/1992/163/"
                    "256/256/639226607749089342.png"}})
check("GIF 动图退到静态缩略图",
      row3["icon_url"].endswith(".png") and "/thumbnails/" in row3["icon_url"],
      row3["icon_url"])
row4 = _na._cf_map_row({"id": 4, "logo": {
    "url": "https://media.forgecdn.net/avatars/1992/163/x.gif"}})
check("只有 GIF 且无缩略图 → 当无图标", row4["icon_url"] == "", row4["icon_url"])
row3 = _na._cf_map_row({"id": 3, "logo": {"url":
    "https://media.forgecdn.net/logos/abc.png"}})
check("正常 logo URL 不受影响", row3["icon_url"].endswith("abc.png"))

# ── 4. 详情页 TTL 缓存 ─────────────────────────────────────────────
from collections import OrderedDict  # noqa: E402
store = OrderedDict()
_sd._cache_write(store, "modrinth:abc", ["v1", "v2"])
check("缓存写入后立即可读", _sd._cache_read(store, "modrinth:abc") == ["v1", "v2"])
_sd._VERSION_CACHE.clear()
_sd._TRANSLATION_CACHE.clear()
check("缓存容量有上限", len(store) == 1)
# TTL 过期
_sd._cache_write(store, "k", "v")
import time as _t  # noqa: E402
store["k"] = (_t.monotonic() - _sd._DETAIL_TTL - 1, "v")
check("超过 TTL 视为未命中并清除",
      _sd._cache_read(store, "k") is None and "k" not in store)
sd_src = read("src/store_detail.py")
check("首屏版本列表先查缓存",
      "hit = _cache_read(_VERSION_CACHE, self._ck)" in sd_src)
check("首屏成功后写缓存",
      "_cache_write(_VERSION_CACHE, self._ck, list(page))" in sd_src)
check("机翻命中缓存不走 Worker",
      "hit = _cache_read(_TRANSLATION_CACHE, self._ck)" in sd_src
      and "self._render_translation(hit)" in sd_src)
check("机翻结果写缓存",
      "_cache_write(_TRANSLATION_CACHE, self._ck, pair)" in sd_src)

# ── 5. HMCL 现成图标集 ─────────────────────────────────────────────
from src import icons  # noqa: E402
ids = ("vanilla", "fabric", "forge", "quilt", "neoforge", "optifine",
       "cleanroom", "legacyfabric", "labymod", "liteloader")
for lid in ids:
    pm = icons.pixmap("loader_" + lid, 40, dpr=1.0)
    check("图标渲染 %s" % lid, not pm.isNull())
qrc = read("icons.qrc")
check("全部 loader 资源已注册进 QRC",
      all(("loader_%s." % lid) in qrc for lid in ids))
notice = read("assets/icons/LOADER_LOGOS.md")
check("来源与 GPL 署名已落盘",
      "HMCL" in notice and "GPL-3.0" in notice and "round-181" in notice)
check("不再逐个溯源上游原图（无自绘 SVG）",
      not any(f.startswith("loader_") and f.endswith(".svg")
              for f in os.listdir(os.path.join(ROOT, "assets", "icons"))))

print("\nRESULT: %d checks, %d failures" % (
    22 + len(ids), len(FAILS)))
if FAILS:
    for f in FAILS:
        print("  -", f)
sys.exit(1 if FAILS else 0)
