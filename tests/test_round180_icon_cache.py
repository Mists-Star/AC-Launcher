# -*- coding: utf-8 -*-
"""round-180：资源中心图标缓存的行为判据（离线，不发网络）。"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from PySide6.QtGui import QPixmap, QPainter, QColor  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.async_image as ai  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         (" | " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)


ORIG = ai.get_data_dir


def make_png(path, color="#22C55E", w=64, h=64):
    pm = QPixmap(w, h)
    pm.fill(QColor(color))
    p = QPainter(pm)
    p.fillRect(10, 10, w - 20, h - 20, QColor("#FFFFFF"))
    p.end()
    pm.save(path, "PNG")


with tempfile.TemporaryDirectory() as td:
    ai.get_data_dir = lambda: td
    try:
        url = "https://cdn.modrinth.com/test/icon.png"
        loader = ai.ImageLoader()

        # ── 1. 原图缓存路径与尺寸无关 ──────────────────────────────
        p1 = loader._orig_path(url)
        check("原图缓存按 URL 一份（不含尺寸/DPR）",
              p1.endswith(hashlib.md5(url.encode()).hexdigest() + ".img")
              and "_48@" not in p1 and "_72@" not in p1,
              os.path.basename(p1))

        # ── 2. 磁盘有原图 → 两个尺寸都直接出图、不发请求 ────────────
        make_png(p1)
        lab48, lab72 = QLabel(), QLabel()
        loader.load(url, 48, lab48)
        loader.load(url, 72, lab72)
        check("48px 从同一份原图派生且立即出图",
              not lab48.pixmap().isNull() and lab48.pixmap().width() == 48)
        check("72px 从同一份原图派生且立即出图",
              not lab72.pixmap().isNull() and lab72.pixmap().width() == 72)
        check("磁盘命中不产生任何网络请求",
              loader._inflight == 0 and not loader._queue)

        # ── 3. 坏缓存文件被删除并重下 ───────────────────────────────
        loader._raw.clear()  # 排除内存有效图的干扰，强制走磁盘读取
        with open(p1, "wb") as f:
            f.write(b"not-an-image")
        check("损坏原图读取返回 None", loader._read_orig(url) is None)
        check("损坏缓存文件被清掉", not os.path.exists(p1))

        # ── 4. 同 URL 在途请求去重（挂等待表，不重复发） ────────────
        loader2 = ai.ImageLoader()
        loader2._inflight_urls.add(url)
        lab_a, lab_b = QLabel(), QLabel()
        loader2.load(url, 48, lab_a)
        loader2.load(url, 72, lab_b)
        waiting = loader2._waiting.get(url, [])
        check("同 URL 并发 load 只挂等待表不重发",
              len(waiting) == 2 and loader2._inflight == 0
              and not loader2._queue, "waiting=%d" % len(waiting))

        # ── 5. 失败退避：负缓存未过期时不入队 ───────────────────────
        import time as _t
        loader3 = ai.ImageLoader()
        loader3._failed[url] = (_t.monotonic(), 1)
        lab_c = QLabel()
        loader3.load(url, 48, lab_c)
        check("失败 URL 在退避期内不再打网络",
              not loader3._queue and loader3._inflight == 0)
        check("退避期判定随次数增长",
              not loader3._cooled_down(url))
        loader3._failed[url] = (_t.monotonic() - 3600, 1)
        check("退避过期后允许重试", loader3._cooled_down(url))

        # ── 6. bump 不清 pending（旧回复仍可喂新卡片） ──────────────
        loader4 = ai.ImageLoader()
        loader4._pending[1] = (url, 48, 1.0, QLabel(), 0)
        loader4.bump()
        check("bump 只递增 token，不清 in-flight 登记表",
              1 in loader4._pending and loader4._token == 1)

        # ── 7. prefetch 不再按尺寸单独存盘 ──────────────────────────
        make_png(p1, "#3B82F6")
        loader5 = ai.ImageLoader()
        loader5.prefetch(url, 72)
        check("prefetch 命中原图时不产生请求",
              loader5._inflight == 0 and not loader5._queue)
        check("缓存目录只多一份 .img",
              len([n for n in os.listdir(loader5._cache_dir)
                   if n.endswith(".img")]) == 1)
    finally:
        ai.get_data_dir = ORIG

# ── 8. 静态防再犯 ──────────────────────────────────────────────────
src = open(os.path.join(ROOT, "src", "async_image.py"), encoding="utf-8").read()
check("检查 HTTP 状态码（403/429 不再当成功）",
      "HttpStatusCodeAttribute" in src)
check("限并发 + 负缓存都在",
      "_MAX_INFLIGHT" in src and "_FAIL_TTL" in src
      and "_inflight_urls" in src)
check("旧的两份尺寸缓存命名已移除",
      'f"{key}_{size}@{tag}.png"' not in src)

print("RESULT:", "PASS" if not FAILS else "FAIL %d: %r" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
