"""代码审查 P0 四项修复的回归（2026-11-05）。

静态判据 + 行为判据，防止修好后又被后续 round 改回去：
  1. 手选 Java 走统一配置入口（旧实现写错路径、裸写、读失败清空配置）；
  2. 条款门禁 fail-closed（旧实现整体 try/except，异常即未同意放行）；
  3. 共享池合并不再静默丢文件（sha1 判重 / 失败保留 / 禁无条件 rmtree）；
  4. 共享池只作用于 AC 自建实例（旧判定只有 `not external`）。
"""
import io
import os
import sys
import shutil
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import shared_libs  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with io.open(os.path.join(HERE, rel), "r", encoding="utf-8") as fh:
        return fh.read()


print("== 审查 P0 修复回归 ==")

# ── 1/2. 静态判据：配置路径与条款门禁 ─────────────────────────────────
mw = read(os.path.join("src", "main_window.py"))
check("手选 Java 不再写 data/launcher_config.json",
      'get_data_dir(), "launcher_config.json"' not in mw)
check("手选 Java 走统一 save_config", "save_config(cfg)" in mw)

mp = read("main.py")
check("条款门禁不再静默 ignored", "terms gate failed (ignored)" not in mp)
check("条款门禁异常走 critical + return",
      "QMessageBox.critical" in mp and "terms gate check failed" in mp)
check("条款写盘失败有回报", "terms save failed" in mp)

sl = read(os.path.join("src", "core", "shared_libs.py"))
check("合并不再按文件大小判重", "os.path.getsize(src)" not in sl)
check("合并失败不再无条件 rmtree 源目录",
      "shutil.rmtree(src_dir, ignore_errors=True)" not in sl)

inst_py = read(os.path.join("src", "instances.py"))
check("外来导入复制不再忽略 libraries",
      "shutil.copytree(mc_dir, dst_mc, dirs_exist_ok=True)" in inst_py)
check("复制实例忽略名单含 assets",
      'ignore_patterns("libraries", "assets")' in inst_py)

# ── 3. 行为判据：合并失败不丢文件 ─────────────────────────────────────
TMP = tempfile.mkdtemp(prefix="_p0review_")
try:
    pool = os.path.join(TMP, "pool")
    pending = os.path.join(TMP, "pending__")
    os.makedirs(os.path.join(pool, "net", "x"))
    os.makedirs(os.path.join(pending, "net", "x"))

    # 大小相同、内容不同 —— 旧实现会 os.remove(src) 直接丢掉这个文件
    with io.open(os.path.join(pool, "net", "x", "same_size.jar"), "wb") as f:
        f.write(b"AAAA")
    with io.open(os.path.join(pending, "net", "x", "same_size.jar"), "wb") as f:
        f.write(b"BBBB")

    failed = shared_libs._merge_real_dir_into_pool(pending, pool)
    check("同尺寸不同内容 → 计入失败", failed == 1, "failed=%s" % failed)
    check("同尺寸不同内容 → 源文件保留",
          os.path.isfile(os.path.join(pending, "net", "x", "same_size.jar")))
    with io.open(os.path.join(pool, "net", "x", "same_size.jar"), "rb") as f:
        check("同尺寸不同内容 → 池文件未被覆盖", f.read() == b"AAAA")
    check("合并失败后源目录仍在（供下次重试）", os.path.isdir(pending))

    # 内容完全相同 → 安全去重，源文件被删
    pending2 = os.path.join(TMP, "pending2")
    os.makedirs(os.path.join(pending2, "net", "x"))
    with io.open(os.path.join(pending2, "net", "x", "dup.jar"), "wb") as f:
        f.write(b"identical")
    with io.open(os.path.join(pool, "net", "x", "dup.jar"), "wb") as f:
        f.write(b"identical")
    failed2 = shared_libs._merge_real_dir_into_pool(pending2, pool)
    check("内容相同 → 安全去重", failed2 == 0 and
          not os.path.isfile(os.path.join(pending2, "net", "x", "dup.jar")))

    # 池里没有 → 正常搬移
    pending3 = os.path.join(TMP, "pending3")
    os.makedirs(pending3)
    with io.open(os.path.join(pending3, "new.jar"), "wb") as f:
        f.write(b"new")
    failed3 = shared_libs._merge_real_dir_into_pool(pending3, pool)
    check("新文件 → 搬进池", failed3 == 0 and
          os.path.isfile(os.path.join(pool, "new.jar")))

    # 残留重试仍搬不动时，目录不能被删掉
    shared_libs._retry_pending_merge(pending, pool)
    check("残留重试不删未合并文件",
          os.path.isfile(os.path.join(pending, "net", "x", "same_size.jar")))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

# ── 4. 行为判据：共享池适用范围 ───────────────────────────────────────
def inst(**kw):
    d = dict(external=False, version_id="", kind="", launcher="AC")
    d.update(kw)
    return SimpleNamespace(**d)


check("AC 自建实例 → 允许共享池", shared_libs.should_use_shared_pool(inst()))
check("原地接管(external) → 禁止",
      not shared_libs.should_use_shared_pool(inst(external=True)))
check("外来完整客户端(version_id) → 禁止",
      not shared_libs.should_use_shared_pool(inst(version_id="1.20.1-forge-47.2.0")))
check("MMC 组件包(kind=mmc) → 禁止",
      not shared_libs.should_use_shared_pool(inst(kind="mmc")))
check("其它启动器来源(launcher=PCL-CE) → 禁止",
      not shared_libs.should_use_shared_pool(inst(launcher="PCL-CE")))
check("老配置缺 launcher 字段 → 仍按自建处理",
      shared_libs.should_use_shared_pool(inst(launcher="")))

print("P0 REVIEW FIXES %s (%d failures)" % ("OK" if not fails else "FAILED", len(fails)))
sys.exit(1 if fails else 0)
