"""存档世界地图：``.mca`` → 顶视图 RGBA（round-171，P2）。

只读、只解表层：用区块的 ``Heightmaps.WORLD_SURFACE`` 定位每列最高的
非空气方块，查该 Y 所在 section 的调色板，得到方块 id；再按自建色表
（``block_palette``）着色，叠加「越高越亮」的明暗曲线。**不做光照/AO**。

版本分叉是最大的坑：1.16+ 的 long 数组不跨边界、1.18 起字段改为
``sections[].block_states``。这里按 ``DataVersion`` 分派，并在高度图解码
结果异常（> 255）时自动回退到旧的「跨 long」打包规则。

缓存：``<data>/map_cache/<world_hash>/<dim>/<rx>.<rz>.<mtime>.<size>.png``，
以 mca 的 mtime + size 作为失效键；第二次打开同一 region 直接读 PNG。
"""
from __future__ import annotations

import hashlib
import os

from ..paths import get_data_dir
from . import nbt
from .nbt import NbtError, unpack_long_array
from .block_palette import color_for, is_air, known, normalize

REGION_BLOCKS = 512
CHUNKS_PER_SIDE = 32
CHUNK_BLOCKS = 16

# 维度 → world_dir 下的子目录（主世界直接在 world_dir/region）
DIMENSIONS = {
    "overworld": "",
    "nether": "DIM-1",
    "end": "DIM1",
}

# 1.16（20w17a）起 long 数组不再跨边界
_DV_NON_CROSSING = 2529


class MapError(ValueError):
    """存档地图读取 / 解析失败。"""


def region_dir(world_dir: str, dim: str) -> str:
    sub = DIMENSIONS.get(dim, "")
    return os.path.join(world_dir, sub, "region") if sub else os.path.join(
        world_dir, "region")


def region_path(world_dir: str, dim: str, rx: int, rz: int) -> str:
    return os.path.join(region_dir(world_dir, dim), "r.%d.%d.mca" % (rx, rz))


def region_grid(world_dir: str, dim: str) -> list[tuple[int, int]]:
    """该维度已存在的 region 坐标（按文件名解析）。"""
    d = region_dir(world_dir, dim)
    out: list[tuple[int, int]] = []
    try:
        for name in os.listdir(d):
            if not name.startswith("r.") or not name.endswith(".mca"):
                continue
            parts = name[2:-4].split(".")
            if len(parts) != 2:
                continue
            try:
                out.append((int(parts[0]), int(parts[1])))
            except ValueError:
                continue
    except OSError:
        return []
    return sorted(out)


def list_worlds(game_dir: str) -> list[str]:
    """实例 ``saves/`` 下的世界目录（含 level.dat 的才算）。"""
    root = os.path.join(game_dir, "saves")
    try:
        names = os.listdir(root)
    except OSError:
        return []
    out = []
    for name in sorted(names, key=str.lower):
        p = os.path.join(root, name)
        if os.path.isfile(os.path.join(p, "level.dat")):
            out.append(p)
    return out


def world_info(world_dir: str) -> dict:
    """读取 level.dat：世界名 / 出生点 / 玩家坐标（未玩过则为 None）。"""
    info = {"name": os.path.basename(world_dir), "spawn": None, "player": None}
    path = os.path.join(world_dir, "level.dat")
    try:
        root = nbt.load_file(path)
    except NbtError:
        return info
    data = root.get("Data") if isinstance(root.get("Data"), dict) else root
    if not isinstance(data, dict):
        return info
    try:
        info["spawn"] = (int(data["SpawnX"]), int(data["SpawnY"]),
                         int(data["SpawnZ"]))
    except (KeyError, TypeError, ValueError):
        pass
    player = data.get("Player")
    if isinstance(player, dict):
        pos = player.get("Pos")
        try:
            if isinstance(pos, (list, tuple)) and len(pos) >= 3:
                info["player"] = (float(pos[0]), float(pos[1]), float(pos[2]))
        except (TypeError, ValueError):
            pass
    return info


# ── mca 读取 ────────────────────────────────────────────────────────────
def _chunk_locations(fh) -> list[tuple[int, int]]:
    """前 8 KiB：1024 个「3 字节扇区偏移 + 1 字节扇区数」。"""
    fh.seek(0)
    head = fh.read(4096)
    if len(head) < 4096:
        raise MapError("region 文件头不完整")
    out = []
    for i in range(1024):
        raw = int.from_bytes(head[i * 4:i * 4 + 4], "big")
        out.append((raw >> 8, raw & 0xFF))
    return out


def _chunk_nbt(fh, sector: int, count: int) -> dict | None:
    fh.seek(sector * 4096)
    head = fh.read(5)
    if len(head) < 5:
        return None
    length = int.from_bytes(head[:4], "big")
    ctype = head[4]
    if length <= 1 or length > 2 * 1024 * 1024:
        return None
    payload = fh.read(length - 1)
    if len(payload) < length - 1:
        return None
    if ctype == 4:  # LZ4（部分整合包/模组存档），不支持
        return None
    if ctype == 3:  # 未压缩
        try:
            return _parse_nbt_plain(payload)
        except NbtError:
            return None
    try:
        return nbt.load_bytes(payload)
    except NbtError:
        return None


def _parse_nbt_plain(payload: bytes) -> dict:
    """未压缩区块（压缩类型 3）：跳过解压直接解析。"""
    r = nbt._Reader(payload)               # noqa: SLF001 - 同包内部工具
    tag = r._u8()                          # noqa: SLF001
    if tag != nbt.TAG_COMPOUND:
        raise NbtError("根标签不是 Compound")
    r._str()                               # noqa: SLF001
    return r.named(0)                      # noqa: SLF001


def _chunk_coords(root: dict, dv: int) -> tuple[int, int] | None:
    lvl = root.get("Level") if isinstance(root.get("Level"), dict) else None
    src = root if root.get("xPos") is not None else (lvl or {})
    try:
        return int(src["xPos"]), int(src["zPos"])
    except (KeyError, TypeError, ValueError):
        return None


def _sections(root: dict) -> list[dict]:
    if isinstance(root.get("sections"), list):
        return [s for s in root["sections"] if isinstance(s, dict)]
    lvl = root.get("Level")
    if isinstance(lvl, dict) and isinstance(lvl.get("Sections"), list):
        return [s for s in lvl["Sections"] if isinstance(s, dict)]
    return []


def _heightmap(root: dict) -> list[int]:
    """WORLD_SURFACE 高度（每列最高非空气方块 +1），解不出返回空列表。"""
    hm = root.get("Heightmaps")
    if not isinstance(hm, dict):
        lvl = root.get("Level")
        hm = lvl.get("Heightmaps") if isinstance(lvl, dict) else None
    if not isinstance(hm, dict):
        return []
    for key in ("WORLD_SURFACE", "MOTION_BLOCKING", "OCEAN_FLOOR"):
        raw = hm.get(key)
        if raw is None:
            continue
        dv = int(root.get("DataVersion") or 0)
        for crossing in (dv < _DV_NON_CROSSING, dv >= _DV_NON_CROSSING):
            try:
                vals = unpack_long_array(raw, 9, 256, crossing=crossing)
            except NbtError:
                return []
            if len(vals) == 256 and max(vals) <= 255:
                return vals
    return []


def _section_palette(sec: dict, dv: int) -> tuple[list[str], object, int] | None:
    """→ (方块名列表, BlockStates 原始长数组, 位宽)；单一调色板时数组为 None。"""
    if isinstance(sec.get("block_states"), dict):
        pal = sec["block_states"].get("palette")
        raw = sec["block_states"].get("data")
    else:
        pal = sec.get("Palette")
        raw = sec.get("BlockStates")
    if not isinstance(pal, list) or not pal:
        return None
    names: list[str] = []
    for entry in pal:
        if isinstance(entry, dict):
            names.append(str(entry.get("Name") or "minecraft:air"))
        else:
            names.append(str(entry))
    if len(names) == 1 and raw is None:
        return names, None, 0
    if raw is None:
        return names, None, 0
    bits = max(4, (len(names) - 1).bit_length())
    return names, raw, bits


def _section_indices(sec: dict, dv: int, cache: dict,
                     sy: int) -> tuple[list[str], list[int] | None]:
    """解码一个 section 的 4096 个方块索引（结果按 Y 缓存）。"""
    if sy in cache:
        return cache[sy]
    got = _section_palette(sec, dv)
    if got is None:
        cache[sy] = (["minecraft:air"], None)
        return cache[sy]
    names, raw, bits = got
    if raw is None:
        idx: list[int] | None = None
    else:
        try:
            idx = unpack_long_array(raw, bits, 4096,
                                    crossing=dv < _DV_NON_CROSSING)
        except NbtError:
            idx = None
    cache[sy] = (names, idx)
    return cache[sy]


def _top_blocks(root: dict, dv: int) -> tuple[list[str], list[int]]:
    """256 列（z*16+x）的（表面方块 id, 表面 Y）；无方块时 Y 为 -1。"""
    sections = {}
    for sec in _sections(root):
        try:
            sections[int(sec.get("Y", 0))] = sec
        except (TypeError, ValueError):
            continue
    cache: dict[int, tuple[list[str], list[int] | None]] = {}
    out = ["minecraft:air"] * 256
    top_y = [-1] * 256

    def block_at(x: int, y: int, z: int) -> str:
        sy = y // 16
        sec = sections.get(sy)
        if sec is None:
            return "minecraft:air"
        names, idx = _section_indices(sec, dv, cache, sy)
        if idx is None:
            return names[0] if names else "minecraft:air"
        i = ((y - sy * 16) * 16 + z) * 16 + x
        if not (0 <= i < len(idx)) or idx[i] >= len(names):
            return "minecraft:air"
        return names[idx[i]]

    heights = _heightmap(root)
    if heights:
        for i, h in enumerate(heights):
            y = h - 1
            if y < 0:
                continue
            sid = block_at(i % 16, y, i // 16)
            if is_air(sid):
                continue
            out[i] = sid
            top_y[i] = y
        return out, top_y

    # 老版本没有 Heightmaps：从最高的 section 往下扫，每列只认第一个非空气。
    pending = set(range(256))
    for sy in sorted(sections, reverse=True):
        names, idx = _section_indices(sections[sy], dv, cache, sy)
        for ly in range(15, -1, -1):
            if not pending:
                break
            for z in range(16):
                for x in range(16):
                    col = z * 16 + x
                    if col not in pending:
                        continue
                    i = (ly * 16 + z) * 16 + x
                    if idx is None:
                        name = names[0] if names else "minecraft:air"
                    elif i < len(idx) and idx[i] < len(names):
                        name = names[idx[i]]
                    else:
                        name = "minecraft:air"
                    if not is_air(name):
                        out[col] = name
                        top_y[col] = sy * 16 + ly
                        pending.discard(col)
        if not pending:
            break
    return out, top_y


def render_region(path: str) -> tuple[bytes, int, int, int] | None:
    """渲染一个 region → ``(RGBA bytes, 未知方块种类数, 区块数, 损坏槽位数)``。

    RGBA 为 512×512；没有区块的像素 alpha=0（由 UI 填底色）。

    round-214：**一个区块都没解析成功**（文件存在但内容损坏 / LZ4 压缩 /
    被杀软截断）时返回 ``None``，不再返回一张全透明 RGBA —— 旧实现会让
    ``load_region_image`` 把这张「看似正常的空白图」写进缓存，玩家看到的
    就是一张永久空白地图且没有任何错误提示。空 region（本来就没有区块）
    仍然返回全透明图，因为那是正确结果。
    """
    try:
        fh = open(path, "rb")
    except OSError:
        return None
    rgba = bytearray(REGION_BLOCKS * REGION_BLOCKS * 4)
    unknown: set[str] = set()
    chunks = 0
    failed = 0
    try:
        with fh:
            locs = _chunk_locations(fh)
            for slot, (sector, count) in enumerate(locs):
                if sector == 0 or count == 0:
                    continue
                root = _chunk_nbt(fh, sector, count)
                if not isinstance(root, dict):
                    failed += 1
                    continue
                dv = int(root.get("DataVersion") or 0)
                if dv <= 0:
                    lvl = root.get("Level")
                    dv = int(lvl.get("DataVersion") or 0) if isinstance(lvl, dict) else 0
                pos = _chunk_coords(root, dv)
                if pos is None:
                    continue
                # region 内区块槽位由文件名决定；xPos/zPos 缺失时退回槽位。
                cx = pos[0] % CHUNKS_PER_SIDE
                cz = pos[1] % CHUNKS_PER_SIDE
                tops, top_y = _top_blocks(root, dv)
                chunks += 1
                bx0 = cx * CHUNK_BLOCKS
                bz0 = cz * CHUNK_BLOCKS
                for z in range(CHUNK_BLOCKS):
                    row = (bz0 + z) * REGION_BLOCKS
                    for x in range(CHUNK_BLOCKS):
                        k = z * CHUNK_BLOCKS + x
                        bid = tops[k]
                        if is_air(bid):
                            continue
                        if not known(bid):
                            unknown.add(normalize(bid))
                        r, g, b = color_for(bid)
                        # 越高越亮：-64 层约 0.55，接近建筑限高约 1.0 封顶
                        shade = 0.55 + min(max(top_y[k], -64), 320) / 384.0 * 0.45
                        i = (row + bx0 + x) * 4
                        rgba[i] = min(255, int(r * shade))
                        rgba[i + 1] = min(255, int(g * shade))
                        rgba[i + 2] = min(255, int(b * shade))
                        rgba[i + 3] = 255
    except (OSError, ValueError):
        return None
    if chunks == 0 and failed > 0:
        # 全是坏块 / 不支持的压缩 → 这不是一张「空地图」，是解析失败。
        return None
    return bytes(rgba), len(unknown), chunks, failed


def image_cache_path(world_dir: str, dim: str, rx: int, rz: int,
                     src: str) -> str:
    """缓存文件按 mtime+size 命名：源文件一变，旧缓存自然不再命中。"""
    st = os.stat(src)
    key = hashlib.sha1(os.path.abspath(world_dir).encode("utf-8")).hexdigest()[:12]
    d = os.path.join(get_data_dir(), "map_cache", key,
                     dim or "overworld")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%d.%d.%d.%d.png" % (rx, rz, st.st_mtime_ns, st.st_size))


def load_region_image(world_dir: str, dim: str, rx: int, rz: int,
                      *, with_stats: bool = False):
    """取 region 顶视图（带磁盘缓存）。返回 QImage 或 None。

    ``with_stats=True`` 时返回 ``(QImage, 未知方块种类数, 区块数)``，供地图
    对话框统计图例；缓存命中时统计值随缓存文件旁的 ``.meta`` 一起复用。
    """
    from PySide6.QtGui import QImage
    src = region_path(world_dir, dim, rx, rz)
    if not os.path.isfile(src):
        return None
    try:
        cache = image_cache_path(world_dir, dim, rx, rz, src)
    except OSError:
        cache = ""
    if cache and os.path.isfile(cache):
        img = QImage(cache)
        if not img.isNull():
            # round-214：缓存必须带「区块数 / 损坏数」才可信。旧版本只有
            # 两个值，而且会把「整片解析失败」存成全透明 PNG —— 这里把
            # 旧格式和 broken 标记都判为无效，落到下面重渲染并覆盖。
            meta_ok = False
            unknown = chunks = 0
            try:
                with open(cache + ".meta", "r", encoding="utf-8") as fh:
                    parts = [int(x) for x in fh.read().strip().split(",")]
                if len(parts) >= 3:
                    unknown, chunks, failed = parts[0], parts[1], parts[2]
                    if not (chunks == 0 and failed > 0):
                        meta_ok = True
            except (OSError, ValueError):
                meta_ok = False
            if meta_ok:
                if not with_stats:
                    return img
                return img, unknown, chunks
    got = render_region(src)
    if got is None:
        return None
    data, unknown, chunks, failed = got
    img = QImage(data, REGION_BLOCKS, REGION_BLOCKS,
                 REGION_BLOCKS * 4, QImage.Format.Format_RGBA8888)
    if cache:
        try:
            img.save(cache, "PNG")
            with open(cache + ".meta", "w", encoding="utf-8") as fh:
                fh.write("%d,%d,%d" % (unknown, chunks, failed))
        except Exception:  # noqa: BLE001 - 缓存失败不影响显示
            pass
    if with_stats:
        return img, unknown, chunks
    return img
