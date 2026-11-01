"""round-165 回归：下载（新建）实例允许玩家自选布局 / 启动格式。

覆盖：
  1. 默认 = AC 独立目录（external=False，格式识别 ac）
  2. 选「原版共享 .minecraft」→ external，mc_dir/补全根 = 所选目录
  3. 选「版本隔离」→ external，实例定位到 versions/<版本>，补全根上溯
  4. 选「自定义游戏目录」→ external，补全根 = 所选目录
  5. 落盘重载后 external / _base / format 全部保留
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AC_DEV_TEMP"] = "1"  # 不污染真实 data 目录

import src.instances as _inst_mod  # noqa: E402

# AC_DEV_TEMP=1 下 get_data_dir() 每次调用都新建临时目录 → 路径漂移。
_FIXED_DATA = os.path.join(tempfile.gettempdir(), "ac_create_fmt_data")
shutil.rmtree(_FIXED_DATA, ignore_errors=True)
os.makedirs(_FIXED_DATA, exist_ok=True)
_inst_mod.get_data_dir = lambda: _FIXED_DATA

# 不建共享 libraries 联接（本测试只关心布局写盘根）
import src.core.shared_libs as _shared  # noqa: E402
_shared.ensure_shared_libraries = lambda _d: False

from src.instances import InstancesManager, detect_format, layout_of  # noqa: E402
from src.launch import versions_root  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


TMP = tempfile.mkdtemp(prefix="ac_create_")
try:
    def mk(name):
        p = os.path.join(TMP, name)
        os.makedirs(p, exist_ok=True)
        return p

    mgr = InstancesManager()

    # ── 1. 默认：AC 独立目录 ──
    ac = mgr.add("ac1", "1.20.1", "vanilla")
    check("默认创建 external=False", ac.external is False and ac._base == "")
    check("默认格式识别为 ac", detect_format(ac) == "ac", detect_format(ac))
    check("默认补全根 = mc_dir", layout_of(ac)["install_dir"] == ac.mc_dir,
          layout_of(ac)["install_dir"])

    # ── 2. 原版共享 .minecraft ──
    mc = mk("vanilla_mc")
    van = mgr.add("van", "1.20.1", "vanilla", format="vanilla", base=mc)
    check("vanilla 记为 external", van.external is True and van._base == mc)
    check("vanilla mc_dir = 所选目录", van.mc_dir == mc, van.mc_dir)
    check("vanilla 格式识别", detect_format(van) == "vanilla",
          detect_format(van))
    check("vanilla 补全根 = 所选目录",
          layout_of(van)["install_dir"] == mc, layout_of(van)["install_dir"])
    check("vanilla 启动根 = 补全根", versions_root(van) == mc)

    # ── 3. 版本隔离：选 .minecraft，实例落在 versions/<版本> ──
    mc2 = mk("iso_mc")
    iso_base = os.path.join(mc2, "versions", "1.20.1")
    iso = mgr.add("iso", "1.20.1", "vanilla", format="iso", base=iso_base)
    check("iso 格式识别", detect_format(iso) == "iso", detect_format(iso))
    lo = layout_of(iso)
    check("iso 补全根上溯到 .minecraft", lo["install_dir"] == mc2,
          lo["install_dir"])
    check("iso 标记 flat", lo["flat"] is True)
    check("iso 版本 id 用 game_version", lo["version"] == "1.20.1",
          lo["version"])
    check("iso 启动根 = 补全根", versions_root(iso) == mc2)

    # ── 4. 自定义游戏目录 ──
    custom = mk("custom_dir")
    cus = mgr.add("cus", "1.20.1", "vanilla", format="custom", base=custom)
    check("custom 格式识别", detect_format(cus) == "custom", detect_format(cus))
    check("custom 补全根 = 所选目录",
          layout_of(cus)["install_dir"] == custom, layout_of(cus)["install_dir"])
    check("custom 启动根 = 补全根", versions_root(cus) == custom)

    # ── 5. 落盘重载后布局保留 ──
    mgr2 = InstancesManager()
    rv = mgr2.get(van.id)
    check("重载后 external 保留", rv is not None and rv.external)
    check("重载后 _base 保留", rv is not None and rv._base == mc,
          getattr(rv, "_base", ""))
    check("重载后 format 保留",
          rv is not None and detect_format(rv) == "vanilla",
          detect_format(rv) if rv else "None")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
    shutil.rmtree(_FIXED_DATA, ignore_errors=True)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("ALL CHECKS PASSED")
