"""round-175 回归测试：assets 共享池（去重）。

覆盖：
  1. 新建实例：<mc_dir>/assets 变成指向全局池的目录联接，原内容并入池；
  2. 幂等：重复调用返回 True 且不重复搬移；
  3. libraries 与 assets 各自独立成池，互不干扰；
  4. 删除实例（先摘联接）后，共享池内容仍在；
  5. game_dir 不存在 / 空值时安全返回 False，不抛异常。
"""
import os
import sys
import tempfile

os.environ["AC_DEV_TEMP"] = "1"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import shared_libs  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


print("== round-175 assets 共享池 ==")

TMP = tempfile.mkdtemp(prefix="_shared175_")
data_dir = os.path.join(TMP, "data")
inst_dir = os.path.join(data_dir, "instances", "abc123", ".minecraft")
os.makedirs(inst_dir)

_ORIG_GET_DATA_DIR = shared_libs.get_data_dir
shared_libs.get_data_dir = lambda: data_dir

try:
    # ── 1. 已存在的真实 assets 目录并入池并改为联接 ─────────────────────
    real_assets = os.path.join(inst_dir, "assets")
    obj_dir = os.path.join(real_assets, "objects", "ab")
    os.makedirs(obj_dir)
    obj = os.path.join(obj_dir, "abcdef0123456789")
    with open(obj, "wb") as f:
        f.write(b"asset-bytes")

    ok = shared_libs.ensure_shared_assets(inst_dir)
    check("ensure_shared_assets 返回 True", ok)

    pool = shared_libs.assets_pool_dir()
    check("池目录已创建", os.path.isdir(pool))
    pooled = os.path.join(pool, "objects", "ab", "abcdef0123456789")
    check("原文件已并入池", os.path.isfile(pooled))
    check("实例 assets 是联接", shared_libs.is_junction(
        os.path.join(inst_dir, "assets")))
    check("通过联接可读到池文件", os.path.isfile(
        os.path.join(inst_dir, "assets", "objects", "ab", "abcdef0123456789")))
    check("原真实目录已清走", not os.path.isdir(real_assets + "__pending"))

    # ── 2. 幂等 ────────────────────────────────────────────────────────
    check("重复调用仍返回 True", shared_libs.ensure_shared_assets(inst_dir))
    check("池未被重复搬移", os.path.isfile(pooled))

    # ── 3. libraries 与 assets 独立 ───────────────────────────────────
    lib_dir = os.path.join(inst_dir, "libraries")
    os.makedirs(os.path.join(lib_dir, "org", "lwjgl"))
    lib = os.path.join(lib_dir, "org", "lwjgl", "lwjgl.jar")
    with open(lib, "wb") as f:
        f.write(b"lib-bytes")
    check("ensure_shared_libraries 返回 True",
          shared_libs.ensure_shared_libraries(inst_dir))
    lib_pool = shared_libs.pool_dir()
    check("libraries 池与 assets 池不同",
          os.path.abspath(lib_pool) != os.path.abspath(pool))
    check("库文件进了 libraries 池",
          os.path.isfile(os.path.join(lib_pool, "org", "lwjgl", "lwjgl.jar")))
    check("assets 池未被库文件污染",
          not os.path.exists(os.path.join(pool, "org", "lwjgl", "lwjgl.jar")))

    # ── 4. 删除实例安全：摘联接后池仍完整 ─────────────────────────────
    shared_libs._remove_junction(os.path.join(inst_dir, "assets"))
    shared_libs._remove_junction(os.path.join(inst_dir, "libraries"))
    check("联接已摘除（不再是联接）",
          not shared_libs.is_junction(os.path.join(inst_dir, "assets")))
    check("资产池文件仍在", os.path.isfile(pooled))
    check("库池文件仍在",
          os.path.isfile(os.path.join(lib_pool, "org", "lwjgl", "lwjgl.jar")))

    # ── 5. 边界 ───────────────────────────────────────────────────────
    check("空 game_dir 返回 False", shared_libs.ensure_shared_assets("") is False)
    check("不存在的 game_dir 返回 False",
          shared_libs.ensure_shared_assets(
              os.path.join(TMP, "nope")) is False)

    # 全新实例（assets 尚不存在）也能提前建联接
    fresh = os.path.join(data_dir, "instances", "fresh", ".minecraft")
    os.makedirs(fresh)
    check("全新实例也建联接", shared_libs.ensure_shared_assets(fresh))
    check("全新实例联接可用",
          os.path.isdir(os.path.join(fresh, "assets")))
finally:
    shared_libs.get_data_dir = _ORIG_GET_DATA_DIR
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)

print()
if fails:
    print("FAILED: %d 项 -> %s" % (len(fails), fails))
    sys.exit(1)
print("ALL PASS")
