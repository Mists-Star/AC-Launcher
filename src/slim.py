"""round-167 低配模式（slim_mode）— 运行时压制高开销效果。

玩家原偏好（壁纸 / 动效 / 音效 / 透底…）原样保存在配置里，低配模式只在
**消费端**返回压制后的值，关闭低配后立即恢复，不需要二次设置。

用法：
    from . import slim
    if slim.eff(cfg, "page_transition"): ...
    home._apply_wallpaper(slim.effective(cfg))
"""
from __future__ import annotations

# 低配模式下强制关闭/替换的配置键与取值
SLIM_OVERRIDES = {
    "effect_light_trail": False,
    "page_transition": False,
    "achievement_toasts": False,
    "transparent_window": False,
    "frosted_theme": False,
    "wallpaper_mode": "none",
    "window_opacity": 1.0,
    "splash_enabled": False,
    "launch_sound": False,
    "bgm_enabled": False,
    "sfx_enabled": False,
    "reduce_motion": True,
}

IMAGE_MEM_LIMIT_NORMAL = 256
IMAGE_MEM_LIMIT_SLIM = 64


def is_slim(cfg: dict | None) -> bool:
    return bool((cfg or {}).get("slim_mode", False))


def eff(cfg: dict | None, key: str):
    """返回某配置键在低配模式下的有效值（不修改 cfg）。"""
    if is_slim(cfg) and key in SLIM_OVERRIDES:
        return SLIM_OVERRIDES[key]
    return (cfg or {}).get(key)


def effective(cfg: dict | None) -> dict:
    """返回压制后的配置副本，供壁纸 / 音效 / 启动画面等消费端使用。"""
    out = dict(cfg or {})
    if is_slim(out):
        out.update(SLIM_OVERRIDES)
    return out
