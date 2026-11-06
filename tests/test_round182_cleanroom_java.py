"""round-182 回归测试：Cleanroom 拿错 Java / 控制台黑窗 / 亮度覆盖。

覆盖：
  1. scan_javas 必须包含「启动器自己下载的运行时」（<data>/java/jre-25）
     —— round-177 只把它接进了 Java 管理页下拉，自动选择仍看不见。
  2. cleanroom_installer_java：玩家显式选的 Java（>=17）优先，其次 Java 25，
     最后才是「最高的现代 JVM」（绝不能无声无息拿系统 Java 26）。
  3. run_cancellable 在 Windows 上必须带 CREATE_NO_WINDOW
     （否则安装器会弹一个全黑的 cmd 窗口）。
  4. _console_java：javaw.exe → 同目录 java.exe（安装器要读 stdout）。
  5. _apply_game_gamma：按设置写 options.txt，其它键保留；关闭时不动；
     越界值夹到 0–10；退出不还原（只写一次）。
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AC_DEV_TEMP"] = "1"

import src.core.java as java_mod  # noqa: E402
import src.core.install as install_mod  # noqa: E402
import src.core.java_install as java_install_mod  # noqa: E402
import src.launch as launch_mod  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── 1. scan_javas 合并启动器自己的 JRE ──────────────────────────────
print("\n[1] scan_javas 合并 <data>/java")
tmp = tempfile.mkdtemp(prefix="ac_r182_")
home = os.path.join(tmp, "jre-25", "jdk-25.0.5+8-jre", "bin")
os.makedirs(home, exist_ok=True)
fake_exe = os.path.join(home, "javaw.exe")
with open(fake_exe, "wb") as f:
    f.write(b"MZ")

_orig_installed = java_install_mod.installed_majors
_orig_scan = java_mod.scan_javas


def _fake_installed():
    return {25: fake_exe}


java_install_mod.installed_majors = _fake_installed
# 其余来源清空，只验证「合并自有 JRE」这一条
java_mod._SCAN_CACHE_DEEP = None
java_mod._SCAN_CACHE_FAST = None
import minecraft_launcher_lib  # noqa: E402

_orig_mll = minecraft_launcher_lib.java_utils.find_system_java_versions_information
minecraft_launcher_lib.java_utils.find_system_java_versions_information = \
    lambda **_kw: []
import src.scan as scan_mod  # noqa: E402

_orig_discover = scan_mod.discover_javas
scan_mod.discover_javas = lambda deep=False, progress=None: []

res = java_mod.scan_javas(deep=False)
paths = [os.path.normcase(os.path.normpath(j["path"])) for j in res]
check("scan_javas 含启动器下载的 Java 25",
      os.path.normcase(os.path.normpath(fake_exe)) in paths)
check("扫描结果里 major=25 可识别",
      any(j["major"] == 25 for j in res), str([(j["major"], j["path"]) for j in res]))
check("java25_path() 能拿到它", java_mod.java25_path() == fake_exe)

# ── 2. cleanroom_installer_java 优先级 ─────────────────────────────
print("\n[2] cleanroom_installer_java 优先级")
user25 = os.path.join(tmp, "java25", "bin", "javaw.exe")
java26 = os.path.join(tmp, "java26", "bin", "javaw.exe")
java8 = os.path.join(tmp, "java8", "bin", "java.exe")
for p in (user25, java26, java8):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"MZ")

check("玩家选 Java 25 → 原样用",
      install_mod.cleanroom_installer_java(user25) == user25)
check("玩家选 Java 8 → 不采用（<17 跑不了安装器）",
      install_mod.cleanroom_installer_java(java8) != java8)
check("空 user_path → 仍取到 Java 25",
      install_mod.cleanroom_installer_java("") == fake_exe)

# 没有 25 时：退回「最高的现代 JVM」，而不是随便一个
_orig_j25 = java_mod.java25_path
java_mod.java25_path = lambda: None
install_mod.java25_path = lambda: None
scan_stub = [{"path": java26, "major": 26, "is_64bit": True},
             {"path": java8, "major": 8, "is_64bit": True}]
java_mod.scan_javas = lambda deep=True: scan_stub
check("无 25 → 取最高现代 JVM（26），不选 8",
      install_mod.cleanroom_installer_java("") == java26)

# ── 3. run_cancellable 隐藏控制台 ──────────────────────────────────
print("\n[3] run_cancellable 不弹控制台")
import src.core.mirror as mirror_mod  # noqa: E402

captured = {}


class _FakeProc:
    pid = 4321
    returncode = 0

    def communicate(self, input=None, timeout=None):
        return ("", "")

    def poll(self):
        return 0


def _fake_popen(cmd, **kwargs):
    captured.update(kwargs)
    captured["cmd"] = cmd
    return _FakeProc()


_orig_popen = subprocess.Popen
subprocess.Popen = _fake_popen
try:
    mirror_mod.run_cancellable(["java", "-version"], capture_output=True, text=True)
finally:
    subprocess.Popen = _orig_popen
if os.name == "nt":
    check("Windows 下带 CREATE_NO_WINDOW",
          bool(captured.get("creationflags", 0) & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)),
          str(captured.get("creationflags")))
else:
    check("非 Windows 不设 creationflags", "creationflags" not in captured)

# ── 4. _console_java 归一 ──────────────────────────────────────────
print("\n[4] _console_java")
java_exe = os.path.join(os.path.dirname(user25), "java.exe")
with open(java_exe, "wb") as f:
    f.write(b"MZ")
check("javaw.exe → java.exe", install_mod._console_java(user25) == java_exe)
check("本来就是 java.exe → 原样", install_mod._console_java(java_exe) == java_exe)
check("目录里没有 java.exe → 原样返回", install_mod._console_java(java8) == java8)

# ── 5. 亮度（gamma）覆盖 ───────────────────────────────────────────
print("\n[5] _apply_game_gamma")
gdir = os.path.join(tmp, "game")
os.makedirs(gdir, exist_ok=True)
opts = os.path.join(gdir, "options.txt")
with open(opts, "w", encoding="utf-8") as f:
    f.write("version:3465\nfov:0.0\ngamma:0.5\nrenderDistance:12\n")


def _opts():
    out = {}
    with open(opts, encoding="utf-8") as f:
        for line in f:
            if ":" in line:
                k, _, v = line.rstrip("\n").partition(":")
                out[k] = v
    return out


launch_mod._apply_game_gamma(gdir, {"gamma_override": True, "gamma_value": 10.0})
o = _opts()
check("写入 gamma=10", o.get("gamma") == "10", str(o.get("gamma")))
check("其它键保留", o.get("fov") == "0.0" and o.get("renderDistance") == "12")
check("fullscreen 不被写入 options.txt（只由窗口模式负责）",
      "fullscreen" not in o)

launch_mod._apply_game_gamma(gdir, {"gamma_override": True, "gamma_value": 25})
check("越界值夹到 10", _opts().get("gamma") == "10")

launch_mod._apply_game_gamma(gdir, {"gamma_override": True, "gamma_value": -3})
check("负数夹到 0", _opts().get("gamma") == "0")

launch_mod._apply_game_gamma(gdir, {"gamma_override": False, "gamma_value": 5})
check("关闭时不写", _opts().get("gamma") == "0")

launch_mod._apply_game_gamma(gdir, {"gamma_override": True, "gamma_value": "abc"})
check("非法值不炸也不写", _opts().get("gamma") == "0")

launch_mod._apply_game_gamma(gdir, {"gamma_override": True, "gamma_value": 1.5})
check("小数正常写（1.5）", _opts().get("gamma") == "1.5")

# 游戏退出后不得回写：再次读文件应与玩家/游戏自己留的值一致（这里等价于未被改动）
before = _opts()
launch_mod._apply_game_gamma(gdir, {"gamma_override": False, "gamma_value": 9})
check("关闭状态下退出不改动", _opts() == before)

# 恢复
java_install_mod.installed_majors = _orig_installed
java_mod.java25_path = _orig_j25
install_mod.java25_path = _orig_j25
java_mod.scan_javas = _orig_scan
minecraft_launcher_lib.java_utils.find_system_java_versions_information = _orig_mll
scan_mod.discover_javas = _orig_discover
shutil.rmtree(tmp, ignore_errors=True)

print("\n%d 项失败" % len(fails))
if fails:
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
