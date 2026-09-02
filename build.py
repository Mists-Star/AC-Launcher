"""AC Launcher build wrapper.

封装 PyInstaller 调用，把构建产物直接输出到 ``dist_beta/AC_Launcher/`` 作为
唯一交付目录（替代之前 ``dist/`` + robocopy 同步到 ``dist_beta/`` 的双目录方案）。

Usage:
    venv/Scripts/python.exe build.py

PyInstaller spec 不接受 ``COLLECT(distpath=...)`` 参数（仅 EXE 接受，且
COLLECT 默认仍然在 ``./dist/``），所以必须用 ``--distpath`` 命令行参数。
"""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    # 优先使用项目 venv 内的 PyInstaller
    venv_py = os.path.join(here, "venv", "Scripts", "python.exe")
    py = venv_py if os.path.isfile(venv_py) else sys.executable

    # 清掉构建缓存（避免旧 .pyc 干扰；用 rm -rf 不触发 Python safe-delete shim）
    os.system('rm -rf build __pycache__ src/__pycache__ dist_beta/_work 2>/dev/null')

    cmd = [
        py, "-m", "PyInstaller",
        "AC_PiTest_noupx.spec",
        "--noconfirm",
        "--distpath", os.path.join(here, "dist_beta"),
        # COLLECT 内部 workpath 同样直接落到 dist_beta/work（避免和 dist 重叠）
        "--workpath", os.path.join(here, "dist_beta", "_work"),
    ]
    print("$", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
