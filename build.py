"""AC Launcher build wrapper.

封装 PyInstaller 调用，把构建产物直接输出到 ``dist_beta/AC_Launcher/`` 作为
唯一交付目录（替代之前 ``dist/`` + robocopy 同步到 ``dist_beta/`` 的双目录方案）。

Usage:
    venv/Scripts/python.exe build.py                # 主包（默认，≈135MB，无 Chromium）
    venv/Scripts/python.exe build.py --full         # 完整包（349MB，仅供组件采集/自测）
    venv/Scripts/python.exe build.py --components   # release 一键：完整包→暂存→主包→组件包
    venv/Scripts/python.exe build.py --lite         # 已并入默认行为（保留兼容旧文档）

round-137 打包瘦身（已落地）：
1. spec 的 excludes 挡未用 PySide6 模块（构建期，见 AC_PiTest_noupx.spec）；
2. 构建后裁剪死资源 —— ``*.debug.pak``/``*.debug.bin``、devtools pak、
   多余翻译（只留 zh_CN / en）、WebEngine 多余 locales（只留 zh-CN/en-*）。
构建结束打印裁剪前后体积对比。

round-139 组件化下载（PCL 式按需安装）：
* 主包 = lite 形态（AC_LITE=1，excludes 去掉 Chromium 整栈），扩展宿主按需装；
* ``--components``：先构建完整包 → 暂存 ``dist_beta/_full_stage`` → 构建主包 →
  **diff 两者的文件差集**（即 Chromium 栈全集，PE 静态分析易漏的动态加载件
  也一并兜住）→ 打 ``dist_components/ac_webengine_runtime_<版本>.zip``
  + ``.zip.sha256`` + ``.manifest.json``（逐文件 sha256，安装时校验用）。

PyInstaller spec 不接受 ``COLLECT(distpath=...)`` 参数（仅 EXE 接受，且
COLLECT 默认仍然在 ``./dist/``），所以必须用 ``--distpath`` 命令行参数。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile


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


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _app_version() -> str:
    """从 src/brand.py 正则取 APP_VERSION（不 import，避免拉起 PySide6）。"""
    brand = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "src", "brand.py")
    with open(brand, encoding="utf-8") as f:
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', f.read())
    return m.group(1) if m else "0.0.0"


def _trim_dist(root: str, lite: bool) -> None:
    """构建后裁剪死资源（只删确定不加载的文件，不碰任何插件目录）。"""
    ps = os.path.join(root, "_internal", "PySide6")
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

    # 1) WebEngine 调试资源：Chromium release 构建只加载 *.pak / *.bin，
    #    *.debug.pak / *.debug.bin 是 debug 构建专用（77 MB 死重）；
    #    devtools_resources.pak（11 MB）仅在打开开发者工具面板时才加载，
    #    正常浏览扩展页不读它。
    res_dir = os.path.join(ps, "resources")
    if os.path.isdir(res_dir):
        for name in os.listdir(res_dir):
            if name.endswith((".debug.pak", ".debug.bin")) or \
                    name.startswith("qtwebengine_devtools_resources"):
                _rm(os.path.join(res_dir, name))

    # 2) Qt 翻译：本项目 QTranslator 只加载 qt_zh_CN（main.py），其余语言
    #    .qm 全是死重 —— 只留 zh_CN / en（en 兜底部分第三方库）。
    tr_dir = os.path.join(ps, "translations")
    if os.path.isdir(tr_dir):
        for name in os.listdir(tr_dir):
            if not name.endswith(".qm"):
                continue
            if "_zh_CN" in name or "_en" in name:
                continue
            _rm(os.path.join(tr_dir, name))

    # 3) WebEngine locales：界面只有中/英，53 个语言包只留 zh-CN / en-*。
    loc_dir = os.path.join(tr_dir, "qtwebengine_locales")
    if os.path.isdir(loc_dir):
        keep = {"zh-CN.pak", "zh-TW.pak", "en-US.pak", "en-GB.pak"}
        for name in os.listdir(loc_dir):
            if name not in keep:
                _rm(os.path.join(loc_dir, name))

    # 4) lite/主包：spec 已排除 WebEngine 模块，这里兜底清掉可能残留的整栈
    #    （resources/、qml/、QtWebEngineProcess.exe、Chromium DLL/locales）。
    if lite:
        shutil.rmtree(os.path.join(ps, "qml"), ignore_errors=True)
        shutil.rmtree(res_dir, ignore_errors=True)
        shutil.rmtree(os.path.join(tr_dir, "qtwebengine_locales"), ignore_errors=True)
        for name in os.listdir(ps) if os.path.isdir(ps) else []:
            low = name.lower()
            if low.startswith("qt6webengine") or low.startswith("qtwebengine"):
                p = os.path.join(ps, name)
                if os.path.isfile(p):
                    _rm(p)
        # 5) round-139：幽灵链定点清除（全量 PE 扫描确认的封闭集合，约 17MB）——
        #    虚拟键盘输入法插件没人用，却拖着 Qt6VirtualKeyboard → Qt6Quick →
        #    Qt6Qml* 整条链；qpdf 图片格式插件拖着 Qt6Pdf。二者与 Chromium 无关
        #    但只在完整包里被真正需要（WebEngineCore 依赖该链）——diff 法会自动
        #    把它们收进组件包，装回组件即恢复完整能力。
        #    保留其余 imageformats（qjpeg/qwebp/qsvg…）与 platforminputcontexts 目录本身。
        ghost = [
            os.path.join(ps, "plugins", "platforminputcontexts",
                         "qtvirtualkeyboardplugin.dll"),
            os.path.join(ps, "plugins", "imageformats", "qpdf.dll"),
            os.path.join(ps, "Qt6VirtualKeyboard.dll"),
            os.path.join(ps, "Qt6Quick.dll"),
            os.path.join(ps, "Qt6Qml.dll"),
            os.path.join(ps, "Qt6QmlMeta.dll"),
            os.path.join(ps, "Qt6QmlModels.dll"),
            os.path.join(ps, "Qt6QmlWorkerScript.dll"),
            os.path.join(ps, "Qt6Pdf.dll"),
        ]
        for p in ghost:
            if os.path.isfile(p):
                _rm(p)

    print(f"[trim] removed {removed} files, saved {saved / 1024 / 1024:.1f} MB")


def _build(here: str, lite: bool) -> int:
    """跑一次 PyInstaller。lite=True → 主包形态（AC_LITE=1 排除 Chromium）。"""
    venv_py = os.path.join(here, "venv", "Scripts", "python.exe")
    py = venv_py if os.path.isfile(venv_py) else sys.executable

    # 清掉构建缓存（避免旧 .pyc 干扰）。Windows 上 cmd 没有 rm，
    # 此前 os.system('rm -rf ...') 一直静默失败，改用 shutil 跨平台可靠。
    for rel in ("build", "__pycache__", os.path.join("src", "__pycache__"),
                os.path.join("dist_beta", "_work")):
        shutil.rmtree(os.path.join(here, rel), ignore_errors=True)

    env = dict(os.environ)
    if lite:
        env["AC_LITE"] = "1"  # spec 读它追加 QtWebEngine excludes
    else:
        env.pop("AC_LITE", None)

    cmd = [
        py, "-m", "PyInstaller",
        "AC_PiTest_noupx.spec",
        "--noconfirm",
        "--distpath", os.path.join(here, "dist_beta"),
        # COLLECT 内部 workpath 同样直接落到 dist_beta/work（避免和 dist 重叠）
        "--workpath", os.path.join(here, "dist_beta", "_work"),
    ]
    kind = "main(lite)" if lite else "full"
    print(f"$ {' '.join(cmd)}   [{kind}]")
    rc = subprocess.call(cmd, env=env)
    if rc != 0:
        return rc

    dist = os.path.join(here, "dist_beta", "AC_Launcher")
    _print_size("before trim", dist)
    _trim_dist(dist, lite=lite)
    _print_size("after trim ", dist)
    return 0


def _make_component(stage: str, main_dist: str, out_dir: str) -> int:
    """完整包 vs 主包做文件 diff → 打组件 zip + sha256 + manifest。

    zip 内路径 = 相对发行根（``_internal/...``），安装端解压到安装目录即落位。
    """
    os.makedirs(out_dir, exist_ok=True)
    ver = _app_version()
    only_full: list[str] = []
    for dirpath, _dirs, names in os.walk(stage):
        for n in names:
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, stage)
            if not os.path.exists(os.path.join(main_dist, rel)):
                only_full.append(rel)
    only_full.sort()
    if not only_full:
        print("[component] ERROR: diff 为空 —— stage 与主包无差异，检查是否先跑了 --full")
        return 1

    base = os.path.join(out_dir, f"ac_webengine_runtime_{ver}")
    zip_path = base + ".zip"
    man_path = base + ".manifest.json"
    files_meta = []

    print(f"[component] packing {len(only_full)} files ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in only_full:
            src = os.path.join(stage, rel)
            arc = rel.replace(os.sep, "/")
            zf.write(src, arc)
            files_meta.append({
                "path": arc,
                "size": os.path.getsize(src),
                "sha256": _sha256(src),
            })

    # manifest 先入 zip（运行端解压前即可读逐文件 sha256，不依赖 sidecar 网络请求）；
    # zip 级 sha256 在**追加 manifest 之后**算（sidecar 校验的是最终 zip）。
    total = sum(m["size"] for m in files_meta)
    manifest = {
        "component": "webengine",
        "launcher_version": ver,
        "component_version": ver,  # 与启动器绑定：不一致即视为需重装
        "file_count": len(files_meta),
        "uncompressed_bytes": total,
        "zip": os.path.basename(zip_path),
        "files": files_meta,
    }
    man_text = json.dumps(manifest, ensure_ascii=False, indent=1)
    with zipfile.ZipFile(zip_path, "a") as zf:
        zf.writestr("component.manifest.json", man_text)

    zip_sha = _sha256(zip_path)
    with open(zip_path + ".sha256", "w", encoding="utf-8") as f:
        f.write(f"{zip_sha}  {os.path.basename(zip_path)}\n")
    with open(man_path, "w", encoding="utf-8") as f:
        f.write(man_text)

    zsize = os.path.getsize(zip_path)
    print(f"[component] {zip_path}")
    print(f"[component] zip {zsize / 1024 / 1024:.1f} MB / "
          f"uncompressed {total / 1024 / 1024:.1f} MB / {len(files_meta)} files")
    print(f"[component] manifest {man_path}")
    return 0


def run_components(here: str) -> int:
    """release 一键：完整包 → 暂存 → 主包 → diff → 组件包。"""
    dist = os.path.join(here, "dist_beta", "AC_Launcher")
    stage = os.path.join(here, "dist_beta", "_full_stage")
    out = os.path.join(here, "dist_components")

    # 1) 完整包（组件素材必须来自未排除 Chromium 的构建）
    rc = _build(here, lite=False)
    if rc != 0:
        return rc
    # 2) 暂存（主包构建会覆盖 dist_beta/AC_Launcher）
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(dist, stage)
    print(f"[stage] {stage}")
    # 3) 主包（默认交付形态）
    rc = _build(here, lite=True)
    if rc != 0:
        return rc
    # 4) diff → zip
    return _make_component(stage, dist, out)


def main() -> int:
    parser = argparse.ArgumentParser(description="AC Launcher build wrapper")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true",
                   help="完整包（含 Chromium 扩展宿主，~349MB，仅供采集/自测）")
    g.add_argument("--components", action="store_true",
                   help="release 一键：完整包→暂存→主包→组件包 zip+sha256+manifest")
    parser.add_argument("--lite", action="store_true",
                        help="(兼容旧文档) lite 已是默认主包行为，此开关无额外效果")
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    if args.components:
        return run_components(here)

    return _build(here, lite=not args.full)


if __name__ == "__main__":
    sys.exit(main())
