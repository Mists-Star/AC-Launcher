"""Litematica 投影解析 + 材料清单导出（round-171，P1）。

输入：`.litematic`（gzip 压缩的 NBT，根含 ``Regions`` / ``Metadata``）。
输出：方块统计（``dict[block_id, count]``）与 UTF-8 BOM 的 CSV（Excel 友好）。

安全上限：按 ``Size`` 计算的总体积超过 ``MAX_VOLUME`` 直接拒绝（提示改用
2D / 清单模式由调用方决定），解码后的方块数同样受 ``nbt.MAX_ARRAY`` 保护。

旧版 MCEdit ``.schematic``（``Blocks`` 字节数组、无调色板）暂不支持——
按规格属低优先级，遇到时给明确错误而不是静默失败。
"""
from __future__ import annotations

import csv
import os
from array import array

from . import nbt
from .nbt import NbtError, unpack_long_array
from .block_palette import is_air

MAX_VOLUME = 8_000_000        # 单个投影的方块数上限（超过拒绝解析）
MAX_LAYER_CELLS = 1_000_000   # 单层预览的格子数上限（防超大平面卡死）


class SchematicError(ValueError):
    """投影文件损坏 / 超出上限 / 格式不支持。"""


def _t(key: str, **kw) -> str:
    from ..i18n import t
    return t(key, **kw)


def _vec(tag, default=(0, 0, 0)) -> tuple[int, int, int]:
    if isinstance(tag, dict):
        try:
            return (int(tag.get("x", default[0])), int(tag.get("y", default[1])),
                    int(tag.get("z", default[2])))
        except (TypeError, ValueError):
            return default
    return default


class Region:
    """一个投影区域：调色板 + 打包后的 BlockStates。"""

    __slots__ = ("name", "pos", "size", "start", "palette", "indices")

    def __init__(self, name: str, pos, size, palette: list[str],
                 indices: array):
        self.name = name
        self.pos = pos
        self.size = size                  # 原始尺寸（可能为负）
        self.start = (
            pos[0] + (size[0] + 1 if size[0] < 0 else 0),
            pos[1] + (size[1] + 1 if size[1] < 0 else 0),
            pos[2] + (size[2] + 1 if size[2] < 0 else 0),
        )
        self.palette = palette
        self.indices = indices

    @property
    def extent(self) -> tuple[int, int, int]:
        return (abs(self.size[0]), abs(self.size[1]), abs(self.size[2]))

    @property
    def volume(self) -> int:
        sx, sy, sz = self.extent
        return sx * sy * sz

    @property
    def bounds(self) -> tuple[int, int, int, int, int, int]:
        sx, sy, sz = self.extent
        x, y, z = self.start
        return x, y, z, x + sx - 1, y + sy - 1, z + sz - 1

    def block_at(self, lx: int, ly: int, lz: int) -> str | None:
        sx, sy, sz = self.extent
        if not (0 <= lx < sx and 0 <= ly < sy and 0 <= lz < sz):
            return None
        i = (ly * sz + lz) * sx + lx
        if i >= len(self.indices):
            return None
        idx = self.indices[i]
        if idx >= len(self.palette):
            return None
        return self.palette[idx]


class Schematic:
    """解析后的投影（多区域合并为同一个世界坐标包围盒）。"""

    def __init__(self, path: str, name: str, author: str, regions: list[Region],
                 meta_volume: int = 0, meta_blocks: int = 0):
        self.path = path
        self.name = name
        self.author = author
        self.regions = regions
        self.meta_volume = meta_volume
        self.meta_blocks = meta_blocks
        self._materials: dict[str, int] | None = None

    # ── 统计 ──────────────────────────────────────────────────────────
    @property
    def volume(self) -> int:
        return sum(r.volume for r in self.regions)

    def bounds(self) -> tuple[int, int, int, int, int, int]:
        bs = [r.bounds for r in self.regions]
        return (min(b[0] for b in bs), min(b[1] for b in bs),
                min(b[2] for b in bs), max(b[3] for b in bs),
                max(b[4] for b in bs), max(b[5] for b in bs))

    def materials(self, *, include_air: bool = False) -> dict[str, int]:
        """方块 id → 数量（默认忽略各类空气）。"""
        if self._materials is None:
            counts: dict[str, int] = {}
            for reg in self.regions:
                pal = reg.palette
                for idx in reg.indices:
                    if idx >= len(pal):
                        continue
                    bid = pal[idx]
                    counts[bid] = counts.get(bid, 0) + 1
            self._materials = counts
        if include_air:
            return dict(self._materials)
        return {k: v for k, v in self._materials.items() if not is_air(k)}

    def total_blocks(self, *, include_air: bool = False) -> int:
        return sum(self.materials(include_air=include_air).values())

    def unknown_blocks(self) -> int:
        """色表里没有的方块种类数（模组方块统计，用于图例提示）。"""
        from .block_palette import known
        return sum(1 for k in self.materials() if not known(k))

    def mismatched(self) -> bool:
        """``Metadata.TotalBlocks`` 与实际统计不一致（文件可能损坏）。

        Litematica 的 ``TotalBlocks`` 记的是**非空气**方块数，因此与
        ``materials()`` 的非空气总数比较。
        """
        if not self.meta_blocks:
            return False
        return self.total_blocks() != self.meta_blocks

    def y_range(self) -> tuple[int, int]:
        b = self.bounds()
        return b[1], b[4]

    # ── 分层预览（P3 用）─────────────────────────────────────────────
    def layer_grid(self, y: int) -> tuple[int, int, list[str | None]]:
        """某一绝对 Y 层的平面网格（宽 × 深，行序 z 增长）。

        同一格被多个区域覆盖时后解析的区域覆盖前者（与游戏里「后放置覆盖」
        直觉一致）。网格过大时抛错，避免伪造的超大结构拖死 UI。
        """
        minx, _, minz, maxx, _, maxz = self.bounds()
        w = maxx - minx + 1
        d = maxz - minz + 1
        if w * d > MAX_LAYER_CELLS:
            raise SchematicError(_t("map.err_layer_too_large", cells=w * d))
        cells: list[str | None] = [None] * (w * d)
        for reg in self.regions:
            x0, y0, z0, x1, y1, z1 = reg.bounds
            if not (y0 <= y <= y1):
                continue
            sx, _, sz = reg.extent
            ly = y - y0
            gx = x0 - minx
            gz = z0 - minz
            for lz in range(sz):
                row = (ly * sz + lz) * sx
                base = (gz + lz) * w + gx
                for lx in range(sx):
                    i = row + lx
                    if i >= len(reg.indices):
                        break
                    idx = reg.indices[i]
                    if idx < len(reg.palette):
                        cells[base + lx] = reg.palette[idx]
        return w, d, cells

    # ── 加载 ──────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: str) -> "Schematic":
        try:
            root = nbt.load_file(path)
        except NbtError as e:
            raise SchematicError(_t("map.err_schematic_read", err=str(e))) from e
        if not isinstance(root, dict):
            raise SchematicError(_t("map.err_schematic_read", err="root"))
        regions_tag = root.get("Regions")
        if not isinstance(regions_tag, dict):
            if "Blocks" in root:
                raise SchematicError(_t("map.err_legacy_schematic"))
            raise SchematicError(_t("map.err_no_regions"))
        meta = root.get("Metadata") if isinstance(root.get("Metadata"), dict) else {}
        name = str(meta.get("Name") or os.path.splitext(os.path.basename(path))[0])
        author = str(meta.get("Author") or "")
        try:
            meta_blocks = int(meta.get("TotalBlocks") or 0)
        except (TypeError, ValueError):
            meta_blocks = 0

        regions: list[Region] = []
        total_volume = 0
        for rname, rt in regions_tag.items():
            if not isinstance(rt, dict):
                continue
            pos = _vec(rt.get("Position"))
            size = _vec(rt.get("Size"))
            pal_tag = rt.get("Palette")
            raw = rt.get("BlockStates")
            if not isinstance(pal_tag, dict) or raw is None:
                # 结构方块导出的 .nbt 用 palette/blocks，不在这里支持
                raise SchematicError(_t("map.err_bad_region", name=str(rname)))
            extent = tuple(abs(v) for v in size)
            vol = extent[0] * extent[1] * extent[2]
            total_volume += vol
            if total_volume > MAX_VOLUME:
                raise SchematicError(_t("map.err_too_large", volume=total_volume))
            if vol == 0:
                continue
            n_pal = len(pal_tag)
            if n_pal == 0:
                raise SchematicError(_t("map.err_bad_palette"))
            palette: list[str] = [""] * n_pal
            for bname, i in pal_tag.items():
                try:
                    ii = int(i)
                except (TypeError, ValueError):
                    ii = -1
                if 0 <= ii < n_pal:
                    palette[ii] = str(bname)
            bits = max(2, (n_pal - 1).bit_length())
            idx = array("I")
            try:
                unpack_long_array(raw, bits, vol, out=idx)
            except NbtError as e:
                raise SchematicError(
                    _t("map.err_schematic_read", err=str(e))) from e
            if len(idx) < vol:
                raise SchematicError(_t("map.err_bad_indices"))
            if max(idx) >= n_pal:
                raise SchematicError(_t("map.err_bad_indices"))
            regions.append(Region(str(rname), pos, size, palette, idx))
        if not regions:
            raise SchematicError(_t("map.err_no_regions"))
        return cls(path, name, author, regions, total_volume, meta_blocks)


def load(path: str) -> Schematic:
    """模块级快捷入口（``Schematic.load`` 的薄封装）。"""
    return Schematic.load(path)


def export_materials_csv(sch: Schematic, path: str, *,
                         include_air: bool = False) -> int:
    """把材料清单写成 CSV（UTF-8 BOM，Excel 双击不乱码）。返回数据行数。"""
    mats = sch.materials(include_air=include_air)
    total = sum(mats.values())
    rows = sorted(mats.items(), key=lambda kv: (-kv[1], kv[0]))
    # utf-8-sig：带 BOM，Excel 直接识别为 UTF-8（纯 utf-8 会被当 GBK）。
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["block_id", "count", "percentage"])
        for bid, cnt in rows:
            pct = (cnt * 100.0 / total) if total else 0.0
            w.writerow([bid, cnt, "%.2f" % pct])
    return len(rows)


def default_csv_name(sch: Schematic) -> str:
    """给「另存为」对话框用的默认文件名（去掉非法字符）。"""
    base = (sch.name or "schematic").strip() or "schematic"
    for ch in '\\/:*?"<>|':
        base = base.replace(ch, "_")
    return base + ".csv"
