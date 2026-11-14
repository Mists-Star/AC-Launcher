"""round-228 第 3 批：路径口径专项的**行为回归**（离线，零真实网络）。

覆盖 P2-11（两份 resolve 实现收敛、结果一致）、P1-4（外来布局免疫全局版本隔离、
整合包 mods/overrides 写游戏读取点而版本文件仍装 mc_dir）。
"""
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.instances as I              # noqa: E402
import src.launch as L                 # noqa: E402
import src.settings_dialog as SD       # noqa: E402
import src.core.install as CI          # noqa: E402
import src.core.mirror as M            # noqa: E402
import minecraft_launcher_lib.mrpack as MRPACK  # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


TMP = tempfile.mkdtemp(prefix="ac228c_")
MC = os.path.join(TMP, ".minecraft")
os.makedirs(MC, exist_ok=True)

_orig_load = SD.load_config


def global_iso(value):
    SD.load_config = lambda: {"version_isolation": value}


def mk(**kw):
    base = dict(id="x", name="probe", game_version="1.20.1", _base=MC)
    base.update(kw)
    return I.Instance(**base)


# ── [1] P2-11：两份入口必须永远一致 ─────────────────────────────────────
cases = [
    ("全局 default / AC 自建", {}, "default"),
    ("全局 isolated / AC 自建", {}, "isolated"),
    ("实例级 default / 全局 isolated", {"isolation": "default"}, "isolated"),
    ("实例级 isolated", {"isolation": "isolated"}, "default"),
    ("实例级 custom（相对路径）",
     {"isolation": "custom", "game_dir_override": "mygame"}, "isolated"),
    ("外来 external", {"external": True}, "isolated"),
    ("外来 kind", {"kind": "standard"}, "isolated"),
    ("外来 launcher", {"launcher": "PCL-CE"}, "isolated"),
    ("外来 + 显式 isolated",
     {"external": True, "isolation": "isolated"}, "isolated"),
]
for label, kw, glob in cases:
    global_iso(glob)
    inst = mk(**kw)
    a = inst.game_dir
    b = L.resolve_game_dir(inst, {"version_isolation": glob})
    check("P2-11 口径一致：" + label, a == b, "%s" % b)

# 收敛本身：launch.resolve_game_dir 里不应再有一份规则实现
with open(os.path.join(HERE, "src", "launch.py"), encoding="utf-8") as f:
    launch_src = f.read()
body = launch_src.split("def resolve_game_dir(", 1)[1].split("\ndef ", 1)[0]
check("P2-11 launch 侧只剩薄封装（无 iso 分支）",
      'iso == "isolated"' not in body and "resolve_game_dir_for" in body)


# ── [2] P1-4：外来布局免疫全局版本隔离 ──────────────────────────────────
global_iso("isolated")
isolated_target = os.path.join(MC, "versions", "1.20.1")
check("P1-4 AC 自建实例仍跟随全局隔离",
      mk().game_dir == isolated_target, mk().game_dir)
for label, kw in (("external", {"external": True}),
                  ("kind", {"kind": "standard"}),
                  ("launcher", {"launcher": "HMCL"})):
    check("P1-4 存量外来实例(%s)不被重定向" % label,
          mk(**kw).game_dir == MC, mk(**kw).game_dir)
check("P1-4 用户显式选隔离时不被覆盖",
      mk(external=True, isolation="isolated").game_dir == isolated_target)
check("P1-4 显式 custom 仍生效",
      mk(isolation="custom", game_dir_override=os.path.join(TMP, "custom")).game_dir
      == os.path.normpath(os.path.join(TMP, "custom")))


# ── [3] P1-4：新建外来实例显式写 default ────────────────────────────────
def fake_mgr():
    return types.SimpleNamespace(
        _instances={}, _current=None, _persist=lambda *a, **k: None,
        get=lambda iid: None)


m = fake_mgr()
inst = I.InstancesManager.add(m, "包", "1.20.1", base=MC)
check("P1-4 mgr.add(base=) 自动 isolation=default",
      inst.isolation == "default", repr(inst.isolation))
m2 = fake_mgr()
inst2 = I.InstancesManager.add(m2, "自建", "1.20.1")
check("P1-4 AC 自建仍跟随全局（isolation 空）",
      inst2.isolation == "", repr(inst2.isolation))

m3 = fake_mgr()
link = I.InstancesManager.import_external(
    m3, mc_dir=MC, name="接管", game_version="1.20.1", mode="link")
check("P1-4 原地接管显式 default", link.isolation == "default",
      repr(link.isolation))

copy_root = os.path.join(TMP, "copy_src")
os.makedirs(os.path.join(copy_root, "saves"), exist_ok=True)
m4 = fake_mgr()
copied = I.InstancesManager.import_external(
    m4, mc_dir=copy_root, name="复制", game_version="1.20.1", mode="copy")
check("P1-4 复制导入(标准布局)显式 default",
      copied.isolation == "default", repr(copied.isolation))


# ── [4] P1-4：整合包写入点分流（modpack_directory） ──────────────────────
GD = os.path.join(MC, "versions", "pack-1")
captured: dict = {}
_orig_mrp = MRPACK.install_mrpack
_orig_lv = MRPACK.get_mrpack_launch_version
_orig_patch = M.patch_install_session


def fake_mrp_install(path, minecraft_directory, modpack_directory=None,
                     callback=None, **kw):
    captured["mc"] = minecraft_directory
    captured["pack"] = modpack_directory


MRPACK.install_mrpack = fake_mrp_install
MRPACK.get_mrpack_launch_version = lambda p: "pack-1"
M.patch_install_session = lambda: None
try:
    CI.install_mrpack("dummy.mrpack", MC, game_dir=GD)
finally:
    MRPACK.install_mrpack = _orig_mrp
    MRPACK.get_mrpack_launch_version = _orig_lv
    M.patch_install_session = _orig_patch
check("P1-4 版本/loader 仍装 mc_dir", captured.get("mc") == MC,
      str(captured.get("mc")))
check("P1-4 mods/overrides 写 game_dir",
      captured.get("pack") == os.path.abspath(GD), str(captured.get("pack")))

captured.clear()
MRPACK.install_mrpack = fake_mrp_install
MRPACK.get_mrpack_launch_version = lambda p: "pack-1"
M.patch_install_session = lambda: None
try:
    CI.install_mrpack("dummy.mrpack", MC)   # 不传 game_dir = 旧行为
finally:
    MRPACK.install_mrpack = _orig_mrp
    MRPACK.get_mrpack_launch_version = _orig_lv
    M.patch_install_session = _orig_patch
check("P1-4 不传 game_dir 时保持 mll 默认", captured.get("pack") is None)

# 静态落点：所有整合包新建/调用点都带上了新口径
with open(os.path.join(HERE, "src", "modpack_import.py"), encoding="utf-8") as f:
    mp_src = f.read()
with open(os.path.join(HERE, "src", "pages_instances.py"), encoding="utf-8") as f:
    pi_src = f.read()
check("P1-4 modpack_import 4 处新建实例都声明 default",
      mp_src.count('isolation="default"') == 4,
      str(mp_src.count('isolation="default"')))
check("P1-4 mrpack 导入传了 game_dir",
      "game_dir=inst.game_dir" in mp_src)
check("P1-4 实例页 mrpack Worker 传了 game_dir",
      "game_dir=inst.game_dir" in pi_src)
check("P1-4 应用到已有实例时备份改读 game_dir",
      "gd = getattr(inst, \"game_dir\", \"\") or inst.mc_dir"
      in open(os.path.join(HERE, "src", "core", "install.py"),
              encoding="utf-8").read())

SD.load_config = _orig_load

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-228 第 3 批回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-228 第 3 批回归）")
