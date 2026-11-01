"""方块 id → 近似颜色（自建色表，绝不打包 Mojang 原版纹理）。round-171。

色表在 ``assets/block_colors.json``（键为 ``namespace:block``，值为
``#RRGGBB`` 或 ``{"color": "#RRGGBB", "shade": 0.0–1.0}``）。未知方块（模组 /
新版本）按 id 的稳定 hash 生成灰阶色：同一方块在任何存档里始终同色，避免
「同一栋建筑两块石头颜色不同」的花屏感。

顶视图明暗（Y 越高越亮）由 ``world_map`` 自行叠加，这里只给基色。
"""
from __future__ import annotations

import hashlib
import json
import os

from ..paths import get_resource_path

AIR_IDS = {
    "minecraft:air", "air",
    "minecraft:cave_air", "cave_air",
    "minecraft:void_air", "void_air",
    "minecraft:structure_void", "structure_void",
}

_table: dict[str, tuple[int, int, int]] | None = None
_loaded_path = ""


def normalize(block_id: str) -> str:
    """``minecraft:oak_planks[axis=y]`` → ``minecraft:oak_planks``。"""
    s = (block_id or "").strip().lower()
    if "[" in s:
        s = s.split("[", 1)[0]
    if ":" not in s:
        s = "minecraft:" + s
    return s


def _parse_color(value) -> tuple[int, int, int]:
    if isinstance(value, dict):
        color = str(value.get("color", ""))
        shade = float(value.get("shade", 1.0) or 1.0)
    else:
        color = str(value or "")
        shade = 1.0
    h = color.lstrip("#")
    if len(h) != 6:
        return 0, 0, 0
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 0, 0, 0
    shade = max(0.0, min(1.5, shade))
    return (int(r * shade), int(g * shade), int(b * shade))


def _load() -> dict[str, tuple[int, int, int]]:
    """惰性加载色表（文件缺失/损坏时退化为空表，全部走 hash 灰阶）。"""
    global _table, _loaded_path
    path = get_resource_path(os.path.join("assets", "block_colors.json"))
    if _table is not None and _loaded_path == path:
        return _table
    table: dict[str, tuple[int, int, int]] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            for k, v in raw.items():
                rgb = _parse_color(v)
                if rgb != (0, 0, 0):
                    table[normalize(k)] = rgb
    except (OSError, ValueError):
        table = {}
    _table = table
    _loaded_path = path
    return table


def reload() -> None:
    """丢弃缓存（测试 / 主题资源热更新用）。"""
    global _table
    _table = None


def is_air(block_id: str) -> bool:
    return (block_id or "").strip().lower() in AIR_IDS


def known(block_id: str) -> bool:
    return normalize(block_id) in _load()


def color_for(block_id: str) -> tuple[int, int, int]:
    """基色 (r, g, b)；未知方块给稳定灰阶。"""
    nid = normalize(block_id)
    hit = _load().get(nid)
    if hit is not None:
        return hit
    digest = hashlib.sha1(nid.encode("utf-8")).digest()
    # 110–170 的灰阶：彼此可辨、又不会把未知方块抢成视觉焦点。
    g = 110 + digest[0] % 61
    return g, g, g


def color_hex(block_id: str) -> str:
    r, g, b = color_for(block_id)
    return "#%02x%02x%02x" % (r, g, b)


def display_name(block_id: str) -> str:
    """展示用短名（去 ``minecraft:`` 前缀，保留模组命名空间）。"""
    nid = normalize(block_id)
    if nid.startswith("minecraft:"):
        return nid[len("minecraft:"):]
    return nid
