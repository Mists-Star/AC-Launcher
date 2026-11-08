"""round-171 回归测试：NBT 读取 / 材料清单 CSV / 存档顶视图。

测试内自造 NBT 字节（不依赖外部样本文件），覆盖：
  1. nbt：gzip / zlib / 未压缩、数组上限、递归深度上限；
  2. unpack_long_array：1.16+ 不跨 long 与 1.15- 跨 long 两种规则；
  3. schematic：材料统计（空气过滤）、负尺寸区域、CSV（BOM/表头/降序/百分比）、
     元数据不一致、体积超限、旧版 .schematic 明确报错、分层网格；
  4. world_map：合成 .mca → 顶视图 RGBA、未知方块计数、磁盘缓存、世界信息。
"""
import gzip
import os
import sys
import tempfile
import zlib
from array import array

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AC_DEV_TEMP"] = "1"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)          # get_resource_path 在开发态按 cwd 解析 assets/

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.core import nbt  # noqa: E402
from src.core.nbt import NbtError, unpack_long_array  # noqa: E402
from src.core import schematic as sc  # noqa: E402
from src.core.schematic import Schematic, SchematicError  # noqa: E402
from src.core import block_palette as bp  # noqa: E402
from src.core import world_map as wm  # noqa: E402
from src.i18n import t  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── 极简 NBT 写入器（仅测试用）──────────────────────────────────────────
MASK64 = (1 << 64) - 1


def _txt(s: str) -> bytes:
    b = s.encode("utf-8")
    return len(b).to_bytes(2, "big") + b


def _int(v: int) -> bytes:
    return int(v).to_bytes(4, "big", signed=True)


def _byte(v: int) -> bytes:
    return int(v).to_bytes(1, "big", signed=True)


def _named(tid: int, name: str, payload: bytes) -> bytes:
    return bytes([tid]) + _txt(name) + payload


def _compound(entries: list[bytes]) -> bytes:
    return b"".join(entries) + b"\x00"


def _list(elem_tid: int, payloads: list[bytes]) -> bytes:
    return bytes([elem_tid]) + _int(len(payloads)) + b"".join(payloads)


def _long_array(vals) -> bytes:
    return _int(len(vals)) + b"".join((int(v) & MASK64).to_bytes(8, "big")
                                      for v in vals)


def _double_list(vals) -> bytes:
    import struct
    return _list(6, [struct.pack(">d", v) for v in vals])


def pack_non_crossing(vals, bits: int) -> list[int]:
    """1.16+ 规则：每个 long 内放 64//bits 个值，余位补零。"""
    per = 64 // bits
    out = []
    for i in range(0, len(vals), per):
        chunk = vals[i:i + per]
        v = 0
        for k, x in enumerate(chunk):
            v |= (x & ((1 << bits) - 1)) << (bits * k)
        out.append(v)
    return out


def pack_crossing(vals, bits: int) -> list[int]:
    """1.15- 规则：值在 long 之间连续排列。"""
    acc = 0
    n = 0
    out = []
    for x in vals:
        acc |= (x & ((1 << bits) - 1)) << n
        n += bits
        while n >= 64:
            out.append(acc & MASK64)
            acc >>= 64
            n -= 64
    if n:
        out.append(acc & MASK64)
    return out


def root_nbt(entries: list[bytes]) -> bytes:
    """带空根名的 Compound。"""
    return _named(10, "", _compound(entries))


def write_gzip(path: str, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(gzip.compress(data, 6))


def _litematic(path: str, regions: list[tuple], *, name="Test", author="AC",
               total_blocks=None, legacy=False) -> None:
    """构造 .litematic：regions 为 (rname, pos, size, palette, indices)。"""
    if legacy:
        write_gzip(path, root_nbt([
            _named(7, "Blocks", _int(4) + b"\x00\x00\x00\x00"),
        ]))
        return
    reg_entries = []
    for rname, pos, size, palette, indices in regions:
        n_pal = len(palette)
        bits = max(2, (n_pal - 1).bit_length())
        packed = pack_non_crossing(indices, bits)
        reg_entries.append(_named(10, rname, _compound([
            _named(10, "Position", _compound([
                _named(3, "x", _int(pos[0])),
                _named(3, "y", _int(pos[1])),
                _named(3, "z", _int(pos[2])),
            ])),
            _named(10, "Size", _compound([
                _named(3, "x", _int(size[0])),
                _named(3, "y", _int(size[1])),
                _named(3, "z", _int(size[2])),
            ])),
            _named(10, "Palette", _compound([
                _named(3, bn, _int(i)) for bn, i in palette.items()
            ])),
            _named(12, "BlockStates", _long_array(packed)),
        ])))
    meta_entries = [_named(8, "Name", _txt(name)),
                    _named(8, "Author", _txt(author))]
    if total_blocks is not None:
        meta_entries.append(_named(3, "TotalBlocks", _int(total_blocks)))
    write_gzip(path, root_nbt([
        _named(10, "Metadata", _compound(meta_entries)),
        _named(10, "Regions", _compound(reg_entries)),
    ]))


# ── 1. nbt 读取 ─────────────────────────────────────────────────────────
print("== nbt 读取 ==")
payload = root_nbt([
    _named(3, "DataVersion", _int(3465)),
    _named(8, "Name", _txt("石头")),
    _named(12, "L", _long_array([1, 2])),
])

got = nbt.load_bytes(payload)
check("未压缩数据原样解析", got.get("DataVersion") == 3465, str(got.get("DataVersion")))
check("字符串 UTF-8 解码", got.get("Name") == "石头", repr(got.get("Name")))
check("LongArray 转 array('q')",
      isinstance(got.get("L"), array) and got["L"].tolist() == [1, 2])

zipped = zlib.compress(payload)
check("zlib 自动识别", nbt.load_bytes(zipped).get("DataVersion") == 3465)
check("gzip 自动识别",
      nbt.load_bytes(gzip.compress(payload)).get("DataVersion") == 3465)

try:
    nbt.load_bytes(root_nbt([_named(12, "Bad", _int(-1))]))
    check("负数数组长度被拒", False)
except NbtError as e:
    check("负数数组长度被拒", "数组长度" in str(e), str(e))

try:
    nbt.load_bytes(root_nbt([_named(12, "Big", _int(nbt.MAX_ARRAY + 1))]))
    check("超上限数组长度被拒", False)
except NbtError as e:
    check("超上限数组长度被拒", "上限" in str(e), str(e))

deep = b""
for _ in range(nbt.MAX_DEPTH + 5):
    deep = _named(10, "k", _compound([deep]) if deep else _compound([]))
try:
    nbt.load_bytes(root_nbt([deep]))
    check("递归深度上限生效", False)
except NbtError as e:
    check("递归深度上限生效", "深度" in str(e), str(e))


# ── 2. 位解包两种规则 ──────────────────────────────────────────────────
print("== long 数组位解包 ==")
vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
bits = 5
got_nc = unpack_long_array(pack_non_crossing(vals, bits), bits, len(vals))
check("不跨 long（1.16+）解码正确", got_nc == vals, str(got_nc))
got_c = unpack_long_array(pack_crossing(vals, bits), bits, len(vals),
                          crossing=True)
check("跨 long（1.15-）解码正确", got_c == vals, str(got_c))
check("两种规则确不等价（互解错）",
      unpack_long_array(pack_crossing(vals, bits), bits, len(vals)) != vals)

try:
    unpack_long_array([0], 0, 1)
    check("位宽 0 被拒", False)
except NbtError:
    check("位宽 0 被拒", True)

try:
    unpack_long_array([0], 5, nbt.MAX_ARRAY + 1)
    check("解包数量超上限被拒", False)
except NbtError:
    check("解包数量超限被拒", True)


# ── 3. schematic ────────────────────────────────────────────────────────
print("== 材料清单 ==")
tmp = tempfile.mkdtemp(prefix="ac_sch_")
sx, sy, sz = 4, 3, 5
n = sx * sy * sz
palette = {"minecraft:stone": 0, "minecraft:air": 1, "minecraft:oak_planks": 2}
indices = []
for i in range(n):
    if i % 10 == 0:
        indices.append(2)
    elif i % 3 == 0:
        indices.append(1)
    else:
        indices.append(0)
expect = {"minecraft:stone": 0, "minecraft:air": 0, "minecraft:oak_planks": 0}
for idx in indices:
    bid = [k for k, v in palette.items() if v == idx][0]
    expect[bid] += 1
non_air = expect["minecraft:stone"] + expect["minecraft:oak_planks"]

path = os.path.join(tmp, "house.litematic")
_litematic(path, [("main", (0, 0, 0), (sx, sy, sz), palette, indices)],
           name="小木屋", author="AC", total_blocks=non_air)

sch = Schematic.load(path)
check("加载成功：名称取自 Metadata", sch.name == "小木屋", sch.name)
check("体积 = 4×3×5", sch.volume == n, sch.volume)
check("区域包围盒", sch.bounds() == (0, 0, 0, 3, 2, 4), str(sch.bounds()))

mats = sch.materials()
check("材料统计忽略空气",
      mats == {"minecraft:stone": expect["minecraft:stone"],
               "minecraft:oak_planks": expect["minecraft:oak_planks"]}, str(mats))
check("total_blocks 不计空气", sch.total_blocks() == non_air, sch.total_blocks())
check("total_blocks(include_air) 计空气",
      sch.total_blocks(include_air=True) == n)
check("TotalBlocks 匹配 → 不报不一致", sch.mismatched() is False)
sch.meta_blocks = 999
check("TotalBlocks 不符 → 报不一致", sch.mismatched() is True)
sch.meta_blocks = non_air
check("既知方块无未知项", sch.unknown_blocks() == 0, sch.unknown_blocks())

csv_path = os.path.join(tmp, "out.csv")
rows = sc.export_materials_csv(sch, csv_path)
check("CSV 行数 = 方块种类数", rows == 2, rows)
with open(csv_path, "rb") as fh:
    head = fh.read(3)
check("CSV 带 UTF-8 BOM", head == b"\xef\xbb\xbf", repr(head))
with open(csv_path, encoding="utf-8-sig") as fh:
    lines = fh.read().strip().splitlines()
check("CSV 表头", lines[0] == "block_id,count,percentage", lines[0])
first_count = int(lines[1].split(",")[1])
check("按数量降序", first_count == max(expect["minecraft:stone"],
                                      expect["minecraft:oak_planks"]),
      lines[1])
pct = float(lines[1].split(",")[2])
check("百分比与总数一致",
      abs(pct - first_count * 100.0 / non_air) < 0.01, str(pct))
check("默认文件名去非法字符",
      sc.default_csv_name(Schematic(tmp, 'a/b:c', '', [], 0, 0)) == "a_b_c.csv",
      sc.default_csv_name(Schematic(tmp, 'a/b:c', '', [], 0, 0)))

w, d, cells = sch.layer_grid(1)
check("分层网格尺寸 4×5", (w, d) == (4, 5), "%s×%s" % (w, d))
check("分层网格全格有值（含空气）", all(c is not None for c in cells),
      str(len([c for c in cells if c is None])))
check("分层网格取到第 0 行首格", cells[0] == "minecraft:oak_planks", cells[0])
check("范围外 Y 层为空网格",
      all(c is None for c in sch.layer_grid(99)[2]))

# 负尺寸区域：Position 是「最大角」，起点要回退 |Size|+1
neg_path = os.path.join(tmp, "neg.litematic")
_litematic(neg_path, [("r", (10, 5, 10), (-3, 2, -2),
                      {"minecraft:stone": 0}, [0] * 12)])
neg = Schematic.load(neg_path)
check("负尺寸起点回退", neg.regions[0].start == (8, 5, 9), str(neg.regions[0].start))
check("负尺寸包围盒", neg.bounds() == (8, 5, 9, 10, 6, 10), str(neg.bounds()))
check("负尺寸取块", neg.regions[0].block_at(0, 0, 0) == "minecraft:stone")
check("越界取块返回 None", neg.regions[0].block_at(3, 0, 0) is None)

# 旧版 MCEdit .schematic：有 Blocks 无 Regions → 明确指出不支持
legacy_path = os.path.join(tmp, "old.schematic")
_litematic(legacy_path, [], legacy=True)
try:
    Schematic.load(legacy_path)
    check("旧版 .schematic 明确报错", False)
except SchematicError as e:
    check("旧版 .schematic 明确报错", t("map.err_legacy_schematic") in str(e), str(e))

# 体积超限
big_path = os.path.join(tmp, "big.litematic")
_litematic(big_path, [("big", (0, 0, 0), (2000, 2000, 3),
                       {"minecraft:stone": 0}, [0] * 4)])
try:
    Schematic.load(big_path)
    check("体积超限被拒", False)
except SchematicError as e:
    check("体积超限被拒", "上限" in str(e) or "too" in str(e).lower(), str(e))

# 没有 Regions 的 .nbt（结构方块导出）
noreg_path = os.path.join(tmp, "noreg.nbt")
write_gzip(noreg_path, root_nbt([_named(3, "version", _int(1))]))
try:
    Schematic.load(noreg_path)
    check("无 Regions 明确报错", False)
except SchematicError as e:
    check("无 Regions 明确报错", t("map.err_no_regions") in str(e), str(e))


# ── 4. 区块顶视图 ───────────────────────────────────────────────────────
print("== 存档顶视图 ==")


def chunk_nbt(cx: int, cz: int, top_y: int, surface: str = "minecraft:stone") -> bytes:
    """1.18+ 结构的单个区块：一个 section + WORLD_SURFACE 高度图。"""
    sy = top_y // 16
    heights = [top_y + 1] * 256
    hm = pack_non_crossing(heights, 9)
    # List 元素是「匿名」的：只有负载，没有类型字节与名称
    sec = _compound([
        _named(1, "Y", _byte(sy)),
        _named(10, "block_states", _compound([
            _named(9, "palette", _list(10, [
                _compound([_named(8, "Name", _txt(surface))]),
                _compound([_named(8, "Name", _txt("minecraft:air"))]),
            ])),
            _named(12, "data", _long_array([0] * 256)),
        ])),
    ])
    return root_nbt([
        _named(3, "DataVersion", _int(3465)),
        _named(3, "xPos", _int(cx)),
        _named(3, "zPos", _int(cz)),
        _named(9, "sections", _list(10, [sec])),
        _named(10, "Heightmaps", _compound([
            _named(12, "WORLD_SURFACE", _long_array(hm)),
        ])),
    ])


def write_region(path: str, chunks: list[tuple[int, int, bytes]]) -> None:
    header = bytearray(8192)
    body = bytearray()
    sector = 2
    for cx, cz, raw in chunks:
        comp = zlib.compress(raw, 6)
        rec = _int(len(comp) + 1) + b"\x02" + comp
        padded = rec + b"\x00" * ((4096 - len(rec) % 4096) % 4096)
        count = len(padded) // 4096
        slot = ((cz % 32) * 32 + (cx % 32)) * 4
        header[slot:slot + 4] = ((sector << 8) | count).to_bytes(4, "big")
        body += padded
        sector += count
    with open(path, "wb") as fh:
        fh.write(bytes(header) + bytes(body))


world = os.path.join(tmp, "world")
os.makedirs(os.path.join(world, "region"), exist_ok=True)
mca = wm.region_path(world, "overworld", 0, 0)
write_region(mca, [(0, 0, chunk_nbt(0, 0, 64))])

got = wm.render_region(mca)
check("region 渲染返回结果", got is not None)
if got:
    rgba, unknown, chunks = got[:3]
    check("RGBA 长度 = 512×512×4", len(rgba) == 512 * 512 * 4, len(rgba))
    check("解析到 1 个区块", chunks == 1, chunks)
    check("已配色方块无未知项", unknown == 0, unknown)
    px = rgba[0:4]
    check("区块 (0,0) 不透明", px[3] == 255, str(px))
    base = bp.color_for("minecraft:stone")
    ratio = px[0] / float(base[0]) if base[0] else 0
    check("亮度按 Y=64 落在合理区间", 0.5 <= ratio <= 0.8, "%.3f" % ratio)
    px2 = rgba[(16 * 512 + 16) * 4:(16 * 512 + 16) * 4 + 4]
    check("未生成区块处透明", px2[3] == 0, str(px2))

img = wm.load_region_image(world, "overworld", 0, 0)
check("load_region_image 返回 512×512", img is not None and not img.isNull()
      and img.width() == 512 and img.height() == 512,
      "" if img is None else "%dx%d" % (img.width(), img.height()))
check("第二次读取命中磁盘缓存",
      wm.load_region_image(world, "overworld", 0, 0) is not None)
check("不存在的 region 返回 None",
      wm.load_region_image(world, "overworld", 5, 5) is None)

# round-214：region 结构在、但区块内容全坏 → 必须返回 None，不能伪装成
# 一张「全透明但合法」的地图写进缓存（玩家会看到永久空白且无任何提示）。
bad = wm.region_path(world, "overworld", 1, 1)
_bad_hdr = bytearray(4096)
_bad_hdr[0:4] = ((2 << 8) | 1).to_bytes(4, "big")   # slot0 → sector 2, 1 sector
_bad_body = b"\x00\x00\x00\x10" + b"\x02" + b"\xff" * 24
with open(bad, "wb") as fh:
    fh.write(bytes(_bad_hdr) + b"\x00" * 4088 + _bad_body)
check("整片损坏的 region 渲染返回 None（不产假空白图）",
      wm.render_region(bad) is None)
check("整片损坏的 region 不进地图缓存",
      wm.load_region_image(world, "overworld", 1, 1) is None)

# 未知方块（模组方块）→ 计入未知种类
mod_chunk = chunk_nbt(0, 0, 64, "mymod:machine")
write_region(mca, [(0, 0, mod_chunk)])
got2 = wm.render_region(mca)
check("模组方块计入未知种类", got2 is not None and got2[1] == 1,
      "" if got2 is None else str(got2[1]))

# round-214：存档里只要有一张远处的 region，旧实现就按极值把画布拉到
# 26112×26112（2.7 GB）。现在只铺锚点周围的连续 4×4 窗口。
far = wm.region_path(world, "overworld", 50, 50)
with open(far, "wb") as fh:
    fh.write(b"\x00" * 4096)
import src.map_dialog as md  # noqa: E402
_tiles = md.build_tiles(world, "overworld", (0, 64, 0))
check("地图画布限制在 4×4 窗口内（不再按极值铺满）",
      _tiles is not None and _tiles["image"].width() <= 2048
      and _tiles["image"].height() <= 2048,
      "" if _tiles is None else "%dx%d" % (
          _tiles["image"].width(), _tiles["image"].height()))

# region 网格 / 世界列表 / 出生点
_grid = wm.region_grid(world, "overworld")
check("region_grid 解析文件名", (0, 0) in _grid and (50, 50) in _grid,
      str(_grid))
check("无 region 的维度返回空", wm.region_grid(world, "nether") == [])

saves = os.path.join(tmp, "game", "saves")
os.makedirs(os.path.join(saves, "MyWorld"), exist_ok=True)
level = root_nbt([
    _named(10, "Data", _compound([
        _named(3, "SpawnX", _int(12)),
        _named(3, "SpawnY", _int(70)),
        _named(3, "SpawnZ", _int(-30)),
        _named(10, "Player", _compound([
            _named(9, "Pos", _double_list([1.5, 80.0, 2.5])),
        ])),
    ])),
])
write_gzip(os.path.join(saves, "MyWorld", "level.dat"), level)
os.makedirs(os.path.join(saves, "NotAWorld"), exist_ok=True)

game = os.path.join(tmp, "game")
check("list_worlds 只认有 level.dat 的目录",
      wm.list_worlds(game) == [os.path.join(saves, "MyWorld")],
      str(wm.list_worlds(game)))
info = wm.world_info(os.path.join(saves, "MyWorld"))
check("出生点解析", info["spawn"] == (12, 70, -30), str(info["spawn"]))
check("玩家坐标解析", info["player"] == (1.5, 80.0, 2.5), str(info["player"]))
check("世界名回退目录名", info["name"] == "MyWorld", info["name"])

# ── 5. 地图对话框（P2 接入层）────────────────────────────────────────────
print("== 地图对话框 ==")
# round-214：上面为了验证「损坏 region / 远处 region」临时加了两个文件，
# 拼图断言假设只有一个 region，这里先清掉。
for _p in (bad, far):
    try:
        os.remove(_p)
    except OSError:
        pass
from src.map_dialog import MapDialog, build_tiles  # noqa: E402

tiles = build_tiles(world, "overworld", None)
check("build_tiles 拼图成功", tiles is not None)
if tiles:
    img = tiles["image"]
    check("拼图尺寸 = 1 个 region", (img.width(), img.height()) == (512, 512),
          "%dx%d" % (img.width(), img.height()))
    check("拼图原点", tiles["origin"] == (0, 0), str(tiles["origin"]))
check("空维度 build_tiles 返回 None", build_tiles(world, "nether", None) is None)

empty_game = os.path.join(tmp, "empty_game")
os.makedirs(os.path.join(empty_game, "saves"), exist_ok=True)
dlg = MapDialog(empty_game)
check("无存档 → 画布显示空态提示", dlg.canvas._empty == t("map.no_saves"),
      dlg.canvas._empty)

map_game = os.path.join(tmp, "map_game")
os.makedirs(os.path.join(map_game, "saves", "W2"), exist_ok=True)
write_gzip(os.path.join(map_game, "saves", "W2", "level.dat"), level)
os.makedirs(os.path.join(map_game, "saves", "W2", "region"), exist_ok=True)
import shutil  # noqa: E402
shutil.copyfile(mca, wm.region_path(os.path.join(map_game, "saves", "W2"),
                                    "overworld", 0, 0))
dlg2 = MapDialog(map_game)
check("有存档 → 世界下拉已填充", dlg2.world_box.count() == 1,
      dlg2.world_box.count())
dlg2._on_tiles(tiles)
check("地图铺进画布（512 缩放 1×时有图）",
      not dlg2.canvas._pix.isNull() and dlg2.canvas._pix.width() == 512,
      0 if dlg2.canvas._pix.isNull() else dlg2.canvas._pix.width())
check("玩家与出生点各一个标记", len(dlg2._marks) == 2, len(dlg2._marks))

# round-214：切世界/维度后旧 worker 的迟到结果不得覆盖画布
from PySide6.QtGui import QImage as _QImage  # noqa: E402
_stale = {"image": _QImage(32, 32, _QImage.Format.Format_ARGB32),
          "origin": (0, 0), "unknown": 0}
dlg2.canvas.set_empty("KEEP")
dlg2._load_gen = 7
dlg2._on_tiles(_stale, 6)
check("旧 gen 的地图结果被丢弃", dlg2.canvas._pix.isNull())
dlg2._on_tiles(_stale, 7)
check("当前 gen 的结果正常上屏", not dlg2.canvas._pix.isNull())
dlg2.close()
dlg.close()

# ── 6. 投影分层预览（P3 接入层）──────────────────────────────────────────
print("== 投影分层预览 ==")
from src.schematic_dialog import SchematicDialog  # noqa: E402

pv = SchematicDialog(sch)
check("层滑杆范围 = 投影 Y 范围", (pv.slider.minimum(), pv.slider.maximum())
      == sch.y_range(), "%d..%d" % (pv.slider.minimum(), pv.slider.maximum()))
check("默认停在最高层", pv.slider.value() == sch.y_range()[1], pv.slider.value())
pv.slider.setValue(1)
check("层标签随层更新", pv.layer_lbl.text() == t("preview.layer", y=1),
      pv.layer_lbl.text())
check("切层后有图", not pv.canvas._pix.isNull()
      and (pv.canvas._pix.width(), pv.canvas._pix.height()) == (4, 5),
      0 if pv.canvas._pix.isNull() else
      "%dx%d" % (pv.canvas._pix.width(), pv.canvas._pix.height()))
pv._on_hover("minecraft:oak_planks")
check("悬停显示方块短名", pv.hover_lbl.text() == "oak_planks", pv.hover_lbl.text())
pv._on_hover(None)
check("移出后清空悬停名", pv.hover_lbl.text() == "", pv.hover_lbl.text())
pv.close()

air_path = os.path.join(tmp, "airtop.litematic")
_litematic(air_path, [("r", (0, 0, 0), (2, 2, 2),
                       {"minecraft:stone": 0, "minecraft:air": 1},
                       [0, 0, 0, 0, 1, 1, 1, 1])])
pv2 = SchematicDialog(Schematic.load(air_path))
pv2.slider.setValue(1)
check("空层显示占位文案", pv2.canvas._empty == t("preview.empty"), pv2.canvas._empty)
pv2.close()

print()
if fails:
    print("失败 %d 项：%s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL CHECKS PASSED（round-171 投影 / 地图）")
