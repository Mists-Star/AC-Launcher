"""AC Launcher build wrapper.

构建 -> 裁剪 -> 部署到 D:\\Appdata\\AC_Launcher（个人测试包，固定路径）。
不再产出 dist_beta/ 目录，构建中间产物在临时目录，结束自动清理。

Usage:
    venv/Scripts/python.exe build.py                # 构建并部署到测试目录
    venv/Scripts/python.exe build.py --clean        # 仅清理测试部署目录
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile


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


def _trim_dist(root: str) -> tuple[int, int, int]:
    """构建后裁剪死资源：Qt 翻译只留 zh_CN / en（其余语言全是死重）。"""
    ps = os.path.join(root, "_internal", "PySide6")
    tr_dir = os.path.join(ps, "translations")
    saved = 0
    removed = 0
    failed = 0

    def _rm(path: str) -> None:
        nonlocal saved, removed, failed
        try:
            sz = os.path.getsize(path)
            os.remove(path)
            saved += sz
            removed += 1
        except KeyboardInterrupt:
            raise
        except BaseException as e:  # noqa: BLE001
            failed += 1
            if failed <= 3:
                print(f"[trim] WARN 无法删除 {os.path.basename(path)}: "
                      f"{type(e).__name__}: {e}")

    if os.path.isdir(tr_dir):
        for name in os.listdir(tr_dir):
            if not name.endswith(".qm"):
                continue
            if "_zh_CN" in name or "_en" in name:
                continue
            _rm(os.path.join(tr_dir, name))

    print(f"[trim] removed {removed} files, saved {saved / 1024 / 1024:.1f} MB")
    if failed:
        print(f"[trim] WARNING: {failed} 个翻译文件未能删除；"
              f"产物仍完整可用，只是没瘦身（可手工清理 translations/ 下"
              f"非 zh_CN / en 的 .qm）")
    return removed, failed, saved


def _get_test_deploy_dir() -> str:
    """返回个人测试包部署目录：D:\\Appdata\\AC_Launcher（固定路径，按惯例）"""
    return r"D:\Appdata\AC_Launcher"


def _deploy_to_test_dir(src: str, dest: str) -> bool:
    """把裁剪后的程序文件覆盖到测试目录，**保留用户数据**。

    ☠ 目标目录同时是「程序目录 + 用户数据目录」：data/（存档/账号/日志/
    缓存）、launcher_config.json、ac.lock 都是活数据，绝不能 rmtree(整个 dest)。
    只覆盖程序文件：AC_Launcher.exe 与 _internal/。

    round-247：不再做 .old-<时间戳> 留底。程序文件是构建产物、源码在 git，
    出问题重新构建覆盖即可；每轮留一份 117MB 的 _internal.old-* 纯属浪费磁盘
    （用户实测一晚堆了好几份）。失败时也不回滚旧程序——返回 False 让用户
    重跑构建，避免把"旧包能用"的假安全感保留下来。
    """
    if not os.path.isdir(dest):
        # 全新部署：直接整目录复制
        try:
            shutil.copytree(src, dest)
            print(f"[deploy] 全新部署到: {dest}")
            return True
        except Exception as e:
            print(f"[deploy] ERROR 部署失败: {e}")
            return False

    old_exe = os.path.join(dest, "AC_Launcher.exe")
    old_internal = os.path.join(dest, "_internal")

    # 逐文件覆盖，不 rmtree 整个 _internal：
    # ① 外层沙箱对 4000+ 文件的批量删除会拦（SAFE_DELETE_BULK_CONFIRM_REQUIRED）；
    # ② 产物文件集合每轮相同，覆盖即等价，还避免"删完复制失败 → 程序没得跑"。
    # data/、launcher_config.json、ac.lock 一律不碰。
    try:
        shutil.copytree(os.path.join(src, "_internal"), old_internal,
                        dirs_exist_ok=True)
        shutil.copy2(os.path.join(src, "AC_Launcher.exe"), old_exe)
    except Exception as e:
        print(f"[deploy] ERROR 新文件复制失败: {e}")
        print(f"[deploy] 重新跑一次 build.py 即可（源码在 git）")
        return False

    print(f"[deploy] 已覆盖新程序文件到: {dest}")
    print(f"[deploy] 用户数据（data/、launcher_config.json）保持原样未动")
    print(f"[deploy] 未留 .old 备份（程序文件可随时从 git 重建）")
    return True


def _build(here: str, deploy_dir: str | None = None) -> int:
    """跑一次 PyInstaller（主包形态，spec 已排除 Chromium 整栈）。

    ``deploy_dir`` 仅供测试注入临时目录；生产调用一律走固定的
    ``_get_test_deploy_dir()``（D:\\Appdata\\AC_Launcher）。
    """
    venv_py = os.path.join(here, "venv", "Scripts", "python.exe")
    py = venv_py if os.path.isfile(venv_py) else sys.executable

    # 用临时目录构建，避免污染项目目录
    with tempfile.TemporaryDirectory(prefix="ac_build_") as tmpdir:
        dist_tmp = os.path.join(tmpdir, "AC_Launcher")
        work_tmp = os.path.join(tmpdir, "_work")

        # 清掉本地构建缓存
        for rel in ("build", "__pycache__", os.path.join("src", "__pycache__")):
            try:
                shutil.rmtree(os.path.join(here, rel), ignore_errors=True)
            except KeyboardInterrupt:
                raise
            except BaseException as e:  # noqa: BLE001
                print(f"[build] WARN 清理缓存失败（继续构建）: {rel}: {type(e).__name__}: {e}")

        env = dict(os.environ)

        cmd = [
            py, "-m", "PyInstaller",
            "AC_PiTest_noupx.spec",
            "--noconfirm",
            "--distpath", tmpdir,
            "--workpath", work_tmp,
        ]
        print(f"$ {' '.join(cmd)}")
        rc = subprocess.call(cmd, env=env)
        if rc != 0:
            return rc

        # 裁剪
        _print_size("before trim", dist_tmp)
        removed, failed, _saved = _trim_dist(dist_tmp)
        _print_size("after trim ", dist_tmp)

        # 验证产物完整
        if not os.path.isfile(os.path.join(dist_tmp, "AC_Launcher.exe")):
            print("[build] ERROR: 产物缺少 AC_Launcher.exe")
            return 1
        if not os.path.isdir(os.path.join(dist_tmp, "_internal", "PySide6")):
            print("[build] ERROR: 产物缺少 _internal/PySide6")
            return 1

        print(f"[build] OK  产物完整；trim removed={removed} failed={failed}"
              + ("（瘦身未完成，不影响可用性）" if failed else ""))

        # 部署到测试目录（deploy_dir 仅测试可注入，生产用固定路径）
        test_dir = deploy_dir or _get_test_deploy_dir()
        if not _deploy_to_test_dir(dist_tmp, test_dir):
            return 1

    return 0


def _clean_test_deploy() -> int:
    """清理测试部署目录。"""
    test_dir = _get_test_deploy_dir()
    if os.path.isdir(test_dir):
        try:
            shutil.rmtree(test_dir, ignore_errors=True)
            print(f"[clean] 已清理测试部署目录: {test_dir}")
        except Exception as e:
            print(f"[clean] ERROR 清理失败: {e}")
            return 1
    else:
        print(f"[clean] 测试部署目录不存在: {test_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AC Launcher build wrapper")
    parser.add_argument("--clean", action="store_true",
                        help="仅清理测试部署目录（D:\\Appdata\\AC_Launcher）")
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    if args.clean:
        return _clean_test_deploy()
    return _build(here)


if __name__ == "__main__":
    sys.exit(main())
