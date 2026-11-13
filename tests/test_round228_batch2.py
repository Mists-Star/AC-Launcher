"""round-228 第 2 批：数据安全三连的**行为回归**（离线，零真实网络）。

覆盖 P0-1（删运行中实例）、P1-3（备份跳过 junction，但保留外来实例真实
assets）、P2-6（删除残骸不再静默）、P2-7（reparse 判定收敛）、i18n 对称。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.core.backup as B          # noqa: E402
import src.core.shared_libs as SL    # noqa: E402
import src.instances as I            # noqa: E402
import src.pages_instances as PI     # noqa: E402
import src.win_rounded as WR         # noqa: E402
from src.i18n import _STRINGS        # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def make_junction(link, target):
    os.makedirs(target, exist_ok=True)
    # 中文系统 mklink 输出是 GBK，绝不能 capture_output 让 Python 去解码。
    r = subprocess.run('cmd /c mklink /J "%s" "%s"' % (link, target),
                       shell=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    return r.returncode == 0 and SL.is_junction(link)


def fake_inst(mc_dir, root=None, iid="deadbeef"):
    return types.SimpleNamespace(
        id=iid, name="测试实例", mc_dir=mc_dir, root=root or mc_dir,
        game_version="1.20.1", loader="fabric", loader_version="", version_id="",
        kind="", needs_convert=False, java_path="", ram_mb=2048, jvm_args="",
        group="", created_at="2026-11-13", external=False,
        _strip_shared_junctions=lambda d: None,
    )


# ── [1] P0-1 运行中实例不许删 ──────────────────────────────────────────
calls = []
warns = []
_orig_wr_confirm, _orig_pi_confirm, _orig_pi_warn = (
    WR.confirm, PI.confirm, PI.warn)
WR.confirm = lambda *a, **k: True          # 玩家在确认框点了确定
PI.confirm = lambda *a, **k: True
PI.warn = lambda *a, **k: warns.append(a)  # 绝不能让离屏弹 exec() 模态框


def fake_page(remove_result=None):
    p = types.SimpleNamespace(
        mgr=types.SimpleNamespace(
            remove=lambda iid: (calls.append(iid), remove_result)[1],
            get=lambda iid: inst,
            current_id=None),
        _refresh=lambda: None,
        window=lambda: types.SimpleNamespace(
            _game_procs={"deadbeef": {"proc": object()}}),
        _selected_id=None,
        current_changed=types.SimpleNamespace(emit=lambda *a: None),
    )
    p._guard_running = lambda iid: PI.InstancesPage._guard_running(p, iid)
    p._report_delete_leftovers = (
        lambda inst, failed: PI.InstancesPage._report_delete_leftovers(p, inst, failed))
    return p


inst = fake_inst(tempfile.mkdtemp(prefix="ac228b_"))
PI.InstancesPage._delete_instance(fake_page(), inst)
check("P0-1 详情入口：运行中实例不调 mgr.remove", calls == [], str(calls))
check("P0-1 详情入口：弹了明确警告", bool(warns))
calls.clear(); warns.clear()
PI.InstancesPage._remove(fake_page(), "deadbeef")
check("P0-1 列表入口：运行中实例不调 mgr.remove", calls == [], str(calls))

# 非运行实例仍可正常删除
p = fake_page()
p.window = lambda: types.SimpleNamespace(_game_procs={})
PI.InstancesPage._delete_instance(p, inst)
check("P0-1 未运行的实例仍可正常删除", calls == ["deadbeef"], str(calls))

# P2-6：remove 返回失败项时必须提示
calls.clear(); warns.clear()
p = fake_page(remove_result=[os.path.join(inst.root, "locked.txt")])
p.window = lambda: types.SimpleNamespace(_game_procs={})
PI.InstancesPage._delete_instance(p, inst)
check("P2-6 删除残骸会弹提示", bool(warns), "warn 次数=%d" % len(warns))

WR.confirm, PI.confirm, PI.warn = (
    _orig_wr_confirm, _orig_pi_confirm, _orig_pi_warn)


# ── [2] P1-3 备份跳过共享池 junction ───────────────────────────────────
tmp = tempfile.mkdtemp(prefix="ac228b_backup_")
mc = os.path.join(tmp, ".minecraft")
write(os.path.join(mc, "saves", "world1", "level.dat"), b"save")
write(os.path.join(mc, "mods", "jei.jar"), b"mod")
pool = os.path.join(tmp, "pool", "assets")
write(os.path.join(pool, "objects", "aa", "aabbcc"), b"asset")
write(os.path.join(pool, "indexes", "1.20.json"), b"index")
linked = make_junction(os.path.join(mc, "assets"), pool)
check("测试夹具：assets 确实是 junction", linked)

_orig_data_dir = B.get_data_dir
B.get_data_dir = lambda: tmp
try:
    snap = B.create_backup(fake_inst(mc))
finally:
    B.get_data_dir = _orig_data_dir

mc_snap = os.path.join(snap, "minecraft")
check("P1-3 快照保留用户存档",
      os.path.isfile(os.path.join(mc_snap, "saves", "world1", "level.dat")))
check("P1-3 快照保留 mods",
      os.path.isfile(os.path.join(mc_snap, "mods", "jei.jar")))
check("P1-3 快照不再复制 assets 联接内容",
      not os.path.exists(os.path.join(mc_snap, "assets", "objects", "aa", "aabbcc")))
snap_files = [os.path.relpath(os.path.join(d, f), mc_snap)
              for d, _, fs in os.walk(mc_snap) for f in fs]
check("P1-3 快照里没有任何 pool 里的对象文件",
      not any("aabbcc" in p for p in snap_files), str(snap_files))

# 外来实例：assets 是真实目录，仍必须进快照（不能按名字一刀切）
tmp2 = tempfile.mkdtemp(prefix="ac228b_external_")
mc2 = os.path.join(tmp2, ".minecraft")
write(os.path.join(mc2, "assets", "objects", "bb", "ddeeff"), b"real")
write(os.path.join(mc2, "saves", "w", "level.dat"), b"save")
B.get_data_dir = lambda: tmp2
try:
    snap2 = B.create_backup(fake_inst(mc2))
finally:
    B.get_data_dir = _orig_data_dir
check("P1-3 外来实例真实 assets 仍被备份",
      os.path.isfile(os.path.join(snap2, "minecraft", "assets",
                                  "objects", "bb", "ddeeff")))


# ── [3] P2-6 InstancesManager.remove 返回失败项 ────────────────────────
root = tempfile.mkdtemp(prefix="ac228b_remove_")
write(os.path.join(root, "a.txt"))
rm_inst = fake_inst(root, root=root)
fake_mgr = types.SimpleNamespace(
    _instances={"deadbeef": rm_inst}, _current="deadbeef",
    _persist=lambda **kw: None)

_orig_rmtree = shutil.rmtree


def _partial_rmtree(path, **kw):
    cb = kw.get("onexc") or kw.get("onerror")
    if cb:
        cb(os.remove, os.path.join(path, "locked.txt"), OSError("busy"))


shutil.rmtree = _partial_rmtree
try:
    failed = I.InstancesManager.remove(fake_mgr, "deadbeef")
finally:
    shutil.rmtree = _orig_rmtree
check("P2-6 remove 返回删不掉的路径", len(failed) == 1 and "locked.txt" in failed[0],
      str(failed))
check("P2-6 元数据仍按原语义移除", "deadbeef" not in fake_mgr._instances)

# 删干净时返回空列表
root2 = tempfile.mkdtemp(prefix="ac228b_remove2_")
write(os.path.join(root2, "a.txt"))
fake_mgr2 = types.SimpleNamespace(
    _instances={"x": fake_inst(root2, root=root2, iid="x")},
    _current="x", _persist=lambda **kw: None)
failed2 = I.InstancesManager.remove(fake_mgr2, "x")
check("P2-6 删干净时返回空列表", failed2 == [], str(failed2))
check("P2-6 正常删除真的清了目录", not os.path.exists(root2))


# ── [4] P2-7 判定收敛 + i18n 对称 ─────────────────────────────────────
with open(os.path.join(HERE, "src", "core", "backup.py"), encoding="utf-8") as f:
    backup_src = f.read()
check("P2-7 backup 不再自带重复 _is_link 包装", "def _is_link" not in backup_src)
check("P2-7 备份与清理共用 shared_libs.is_junction",
      "from .shared_libs import is_junction" in backup_src)
check("P2-7 is_junction 对真联接返回 True", SL.is_junction(os.path.join(mc, "assets")))
check("P2-7 is_junction 对普通目录返回 False", not SL.is_junction(os.path.join(mc, "saves")))
for key in ("instances.delete_while_running", "instances.delete_partial"):
    check("i18n 中英对称 " + key,
          key in _STRINGS["zh-CN"] and key in _STRINGS["en-US"])


print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-228 第 2 批回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-228 第 2 批回归）")
