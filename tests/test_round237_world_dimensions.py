"""round-237：存档地图支持 MC 1.16+ 新维度目录布局。

用户实机反馈「地图主世界看不到/找不出数据」。根因：26.3 存档的主世界
区块在 <world>/dimensions/minecraft/overworld/region/，而 world_map 写死
老布局 <world>/region/ → region_grid 返回空 → 「该维度暂无地图数据」。

本测试用**合成目录结构**（不依赖用户存档）验证：
  * 新版布局（dimensions/minecraft/<dim>/region）能被识别
  * 老布局（region / DIM-1 / DIM1）仍兼容
  * 两者并存时新版优先；list_worlds 的「半个存档」兜底也认新版
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import world_map as wm  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def touch_mca(d, *names):
    os.makedirs(d, exist_ok=True)
    for n in names:
        open(os.path.join(d, n), "wb").close()


print("== 1. 新版维度布局（MC 1.16+）==")
with tempfile.TemporaryDirectory() as t:
    world = os.path.join(t, "NewWorld")
    # 主世界：dimensions/minecraft/overworld/region
    touch_mca(os.path.join(world, "dimensions", "minecraft", "overworld", "region"),
              "r.0.0.mca", "r.1.0.mca", "r.-1.2.mca")
    # 下界 / 末地
    touch_mca(os.path.join(world, "dimensions", "minecraft", "the_nether", "region"),
              "r.0.0.mca")
    touch_mca(os.path.join(world, "dimensions", "minecraft", "the_end", "region"),
              "r.0.0.mca", "r.0.1.mca")

    check("overworld 找到 3 个 region", len(wm.region_grid(world, "overworld")) == 3,
          str(wm.region_grid(world, "overworld")))
    check("nether 找到 1 个", len(wm.region_grid(world, "nether")) == 1)
    check("end 找到 2 个", len(wm.region_grid(world, "end")) == 2)
    rd = wm.region_dir(world, "overworld").replace("\\", "/")
    check("overworld region_dir 指向新版目录",
          rd.endswith("dimensions/minecraft/overworld/region"), rd)

    # list_worlds：无 level.dat 的「半个存档」也该被识别
    # list_worlds 入参是「游戏目录」，内部自己拼 <game_dir>/saves
    saves = os.path.join(t, "saves")
    os.makedirs(saves, exist_ok=True)
    os.rename(world, os.path.join(saves, "NewWorld"))
    found = wm.list_worlds(t)
    check("无 level.dat 的新版存档被 list_worlds 收录", len(found) == 1, str(found))

print("== 2. 老布局兼容 ==")
with tempfile.TemporaryDirectory() as t:
    world = os.path.join(t, "OldWorld")
    touch_mca(os.path.join(world, "region"), "r.0.0.mca")
    touch_mca(os.path.join(world, "DIM-1", "region"), "r.0.0.mca")
    touch_mca(os.path.join(world, "DIM1", "region"), "r.0.0.mca")
    check("老 overworld 找到 1 个", len(wm.region_grid(world, "overworld")) == 1)
    check("老 nether(DIM-1) 找到 1 个", len(wm.region_grid(world, "nether")) == 1)
    check("老 end(DIM1) 找到 1 个", len(wm.region_grid(world, "end")) == 1)

print("== 3. 两布局并存：新版优先 ==")
with tempfile.TemporaryDirectory() as t:
    world = os.path.join(t, "Both")
    touch_mca(os.path.join(world, "region"), "r.9.9.mca")  # 老布局 1 个
    touch_mca(os.path.join(world, "dimensions", "minecraft", "overworld", "region"),
              "r.0.0.mca", "r.1.1.mca")  # 新版 2 个
    check("新版优先（2 个而非老的 1 个）",
          len(wm.region_grid(world, "overworld")) == 2,
          str(wm.region_grid(world, "overworld")))

print("\nround-237 world dimensions: %d checks, %d failed" % (
    sum(1 for _ in range(11)), len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.stdout.flush()
    sys.exit(1)
print("ALL CHECKS PASSED（双布局维度目录）")
sys.stdout.flush()
