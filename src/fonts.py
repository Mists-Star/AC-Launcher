"""共享字体查找：MC 像素字体加载（round-94 移除写死的本机路径）。

查找顺序（先到先用，符合「随包资源优先 + 用户可配置」）：
  1. data/fonts/（启动器旁的运行时数据目录）——“用户显式放置即覆盖默认”，
     想换别的像素字体直接放个 .ttf 进去，无需改任何设置。
  2. assets/fonts/ 随包只读资源（dev 走项目根，Nuitka 由
     --include-data-dir=assets=assets 打进制成品）。
  3. 系统已安装字体里 family 名含 "minecraft" 的（用户把像素字体装进
     Windows\\Fonts 的常见命名习惯）。

全部缺失返回 None，调用方回退矢量字母 / 系统字体——启动动画永不崩。
历史：round-62/63 曾写死本机字体路径 <本地字体目录>\\[苦力怕论坛]
Minecraft(同时支持中英文).ttf（换机/目录移动后静默失效），已随包复制为
assets/fonts/minecraft_pixel.ttf 并移除该私有路径。
"""
from __future__ import annotations

import os

_FONT_EXTS = (".ttf", ".otf", ".ttc")


def _font_files(folder: str, seen: set[str]) -> list[str]:
    """返回目录下全部字体文件绝对路径（去重、跳过非字体）。"""
    out: list[str] = []
    if not os.path.isdir(folder):
        return out
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for n in names:
        if not n.lower().endswith(_FONT_EXTS):
            continue
        p = os.path.normpath(os.path.join(folder, n))
        key = os.path.normcase(p)
        if key in seen or not os.path.isfile(p):
            continue
        seen.add(key)
        out.append(p)
    return out


def mc_font_paths() -> list[str]:
    """按优先级返回候选字体文件路径（data 用户位 > assets 随包位）。"""
    from .paths import get_data_dir, get_resource_path

    seen: set[str] = set()
    out: list[str] = []
    # 1) 用户导入位：data/fonts（放字体文件即覆盖默认）
    out += _font_files(os.path.join(get_data_dir(), "fonts"), seen)
    # 2) 随包内置位：assets/fonts
    out += _font_files(os.path.join(get_resource_path("assets"), "fonts"), seen)
    return out


def load_mc_font_family() -> str | None:
    """加载 MC 像素字体，返回 Qt family 名；找不到返回 None（调用方回退）。"""
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:  # noqa: BLE001 - 字体加载失败绝不阻塞启动
        return None
    for p in mc_font_paths():
        try:
            fid = QFontDatabase.addApplicationFont(p)
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    return fams[0]
        except Exception:  # noqa: BLE001
            continue
    # 3) 系统已安装字体的 family 含 "minecraft"（如装入 Windows\Fonts）
    try:
        avail = QFontDatabase.families()
    except Exception:  # noqa: BLE001
        avail = []
    for f in avail:
        if "minecraft" in f.lower():
            return f
    return None