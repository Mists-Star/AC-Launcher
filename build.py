"""AC Launcher build wrapper.

封装 PyInstaller 调用，把构建产物直接输出到 ``dist_beta/AC_Launcher/`` 作为
唯一交付目录（替代之前 ``dist/`` + robocopy 同步到 ``dist_beta/`` 的双目录方案）。

Usage:
    venv/Scripts/python.exe build.py                # 主包（唯一形态，无 Chromium）

round-137 打包瘦身（已落地）：
1. spec 的 excludes 挡未用 PySide6 模块（含 QtWebEngine 整栈，见
   AC_PiTest_noupx.spec）；
2. 构建后裁剪死资源：Qt 翻译只留 zh_CN / en。
构建结束打印裁剪前后体积对比。

round-157：JS 扩展宿主（QtWebEngine）已整体移除，不再产出任何组件包。

PyInstaller spec 不接受 ``COLLECT(distpath=...)`` 参数（仅 EXE 接受，且
COLLECT 默认仍然在 ``./dist/``），所以必须用 ``--distpath`` 命令行参数。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys


def _dir_size(path: str) -> tuple[int, int]:
    """返回 (字节数, 文件数)。"""
    total = 0
    count = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
                count += 1
            except OSError:
                pass
    return total, count


def _print_size(label: str, path: str) -> tuple[int, int]:
    total, count = _dir_size(path)
    print(f"[size] {label}: {total / 1024 / 1024:.1f} MB / {count} files  ({path})")
    return total, count


def _trim_dist(root: str) -> None:
    """构建后裁剪死资源：Qt 翻译只留 zh_CN / en（其余语言全是死重）。"""
    ps = os.path.join(root, "_internal", "PySide6")
    tr_dir = os.path.join(ps, "translations")
    saved = 0
    removed = 0

    def _rm(path: str) -> None:
        nonlocal saved, removed
        try:
            sz = os.path.getsize(path)
            os.remove(path)
            saved += sz
            removed += 1
        except OSError:
            pass

    if os.path.isdir(tr_dir):
        for name in os.listdir(tr_dir):
            if not name.endswith(".qm"):
                continue
            if "_zh_CN" in name or "_en" in name:
                continue
            _rm(os.path.join(tr_dir, name))

    print(f"[trim] removed {removed} files, saved {saved / 1024 / 1024:.1f} MB")


def _build(here: str) -> int:
    """跑一次 PyInstaller（主包形态，spec 已排除 Chromium 整栈）。"""
    venv_py = os.path.join(here, "venv", "Scripts", "python.exe")
    py = venv_py if os.path.isfile(venv_py) else sys.executable

    # 清掉构建缓存（避免旧 .pyc 干扰）。Windows 上 cmd 没有 rm，
    # 此前 os.system('rm -rf ...') 一直静默失败，改用 shutil 跨平台可靠。
    for rel in ("build", "__pycache__", os.path.join("src", "__pycache__"),
                os.path.join("dist_beta", "_work")):
        shutil.rmtree(os.path.join(here, rel), ignore_errors=True)

    env = dict(os.environ)

    cmd = [
        py, "-m", "PyInstaller",
        "AC_PiTest_noupx.spec",
        "--noconfirm",
        "--distpath", os.path.join(here, "dist_beta"),
        # COLLECT 内部 workpath 同样直接落到 dist_beta/work（避免和 dist 重叠）
        "--workpath", os.path.join(here, "dist_beta", "_work"),
    ]
    print(f"$ {' '.join(cmd)}")
    rc = subprocess.call(cmd, env=env)
    if rc != 0:
        return rc

    dist = os.path.join(here, "dist_beta", "AC_Launcher")
    _print_size("before trim", dist)
    _trim_dist(dist)
    _print_size("after trim ", dist)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AC Launcher build wrapper")
    parser.add_argument("--lite", action="store_true",
                        help="(兼容旧文档) 主包已是唯一形态，此开关无额外效果")
    parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)
    return _build(here)


if __name__ == "__main__":
    sys.exit(main())
