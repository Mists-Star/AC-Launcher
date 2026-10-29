"""round-136 品牌自定义：用户自定义标志 / 标题栏文本 / 启动页背景的统一解析入口。

设计约束：
  * 任何读取都必须容错 —— 文件被删/移动/损坏时静默回落默认，绝不让启动器崩。
  * 统一在这里做「路径归一化 + 有效性校验 + 解码缓存」，三处调用方只管用。
  * 本模块不依赖 settings_dialog（避免循环 import），直接读同一个配置文件。
"""
from __future__ import annotations

import json
import os

from .brand import APP_DISPLAY
from .paths import get_config_path

CUSTOM_LOGO_KEY = "custom_logo_path"
CUSTOM_TITLE_KEY = "custom_title_text"
SPLASH_BG_KEY = "splash_bg_image"

SUPPORTED_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".svg", ".ico")

# 进程内解码缓存： key = (绝对路径, 文件 mtime, 目标边长)
_pixmap_cache: dict = {}


def load_brand_cfg() -> dict:
    """读配置文件里与品牌自定义有关的 3 个键（读失败 → 空 dict）。"""
    try:
        with open(get_config_path("launcher_config.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {k: data.get(k, "") for k in (CUSTOM_LOGO_KEY, CUSTOM_TITLE_KEY, SPLASH_BG_KEY)}
    except Exception:
        return {}


def normalize_path(raw) -> str:
    """归一化用户给的路径；无效/空 → ""。"""
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    return os.path.normpath(os.path.abspath(os.path.expanduser(s)))


def valid_image_path(raw) -> str:
    """归一化 + 校验（存在 / 是文件 / 后缀受支持）→ 合法返回绝对路径，否则 ""。"""
    p = normalize_path(raw)
    if not p:
        return ""
    try:
        if not os.path.isfile(p):
            return ""
    except OSError:
        return ""
    if not p.lower().endswith(SUPPORTED_EXTS):
        return ""
    return p


def custom_logo_path(cfg: dict | None = None) -> str:
    """自定义标志的合法绝对路径；没有则 ""。"""
    cfg = cfg if cfg is not None else load_brand_cfg()
    return valid_image_path(cfg.get(CUSTOM_LOGO_KEY, ""))


def custom_title_text(cfg: dict | None = None) -> str:
    """标题栏左上角文本；空/仅空白 → APP_DISPLAY。"""
    cfg = cfg if cfg is not None else load_brand_cfg()
    raw = cfg.get(CUSTOM_TITLE_KEY, "")
    if not isinstance(raw, str):
        return APP_DISPLAY
    s = raw.strip()
    return s or APP_DISPLAY


def splash_bg_path(cfg: dict | None = None) -> str:
    """启动页背景图的合法绝对路径；没有则 ""。"""
    cfg = cfg if cfg is not None else load_brand_cfg()
    return valid_image_path(cfg.get(SPLASH_BG_KEY, ""))


def load_pixmap(path: str, size: int):
    """按目标边长解码图片并缓存；失败返回 None。

    只做等比缩小（不放大）——放大会糊，用户自己的图通常比 30px 大得多。
    """
    if not path or size <= 0:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (path, mtime, int(size))
    hit = _pixmap_cache.get(key)
    if hit is not None:
        return hit
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap
    except Exception:
        return None
    pm = QPixmap(path)
    if pm.isNull():
        return None
    if max(pm.width(), pm.height()) > size:
        pm = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    _pixmap_cache[key] = pm
    return pm
