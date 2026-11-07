"""round-190：实例图标与收藏（PCL 概览页的「图标 / 收藏夹」）。

* 图标：玩家可选一张本地图片当实例图标（复制进 data/instance_icons/，
  不改动原文件），卡片与首页网格都用它；空 = 默认图标。
* 收藏：收藏的实例在列表与首页网格里**置顶**，卡片上带星标。

为什么放在 ui_kit 而不是 icons：icons 只管「名 → 图标」，不该认识 Instance。
"""
from __future__ import annotations

import os
import shutil

from .paths import get_data_dir

_ICON_MAX_BYTES = 4 * 1024 * 1024
_ICON_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def icons_dir() -> str:
    d = os.path.join(get_data_dir(), "instance_icons")
    os.makedirs(d, exist_ok=True)
    return d


def set_instance_icon(inst, src_path: str) -> str:
    """把 *src_path* 复制成该实例的图标，返回存进 ``icon_path`` 的路径。

    原文件**不动**（玩家可能就放在下载目录里，删了图标就没了）。
    非图片 / 过大 → 抛 ``ValueError``（由 UI 提示，不静默失败）。
    """
    ext = os.path.splitext(src_path)[1].lower()
    if ext not in _ICON_EXTS:
        raise ValueError("unsupported image type")
    try:
        size = os.path.getsize(src_path)
    except OSError as exc:
        raise ValueError(str(exc)) from exc
    if size > _ICON_MAX_BYTES:
        raise ValueError("image too large")
    dst = os.path.join(icons_dir(), "%s%s" % (getattr(inst, "id", "inst"), ext))
    # 换扩展名时清理旧文件，免得留一堆孤儿
    for e in _ICON_EXTS:
        old = os.path.join(icons_dir(), "%s%s" % (getattr(inst, "id", "inst"), e))
        if old != dst and os.path.isfile(old):
            try:
                os.remove(old)
            except OSError:
                pass
    shutil.copyfile(src_path, dst)
    return dst


def clear_instance_icon(inst) -> None:
    """恢复默认图标（删掉缓存的那张）。"""
    for e in _ICON_EXTS:
        p = os.path.join(icons_dir(), "%s%s" % (getattr(inst, "id", "inst"), e))
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def icon_pixmap(icon_path: str, size: int, *, radius: int = 8):
    """实例图标（圆角）；路径无效/读不出来返回 ``None``，由调用方回落默认图。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPainterPath, QPixmap

    path = (icon_path or "").strip()
    if not path or not os.path.isfile(path):
        return None
    src = QPixmap(path)
    if src.isNull():
        return None
    scaled = src.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, size, size, radius, radius)
    p.setClipPath(clip)
    p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2,
                 scaled)
    p.end()
    return out
