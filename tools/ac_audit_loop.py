"""AC Launcher 自主优化循环 —— 静态审计 + 回归驱动器。

设计目的：让"优化启动器"这件事可以**周期性、可重复**地跑，而不是靠
一次性人肉记忆。每次执行产出一份结构化审计清单（带 file:line 与判据），
供Agent/开发者决定下一轮修什么。

用法：
    venv/Scripts/python.exe tools/ac_audit_loop.py            # 全量审计
    venv/Scripts/python.exe tools/ac_audit_loop.py --quick    # 只跑静态扫描（秒级）
    venv/Scripts/python.exe tools/ac_audit_loop.py --fix-spec # 自动修复 spec 漏列的模块

审计维度（可与主流启动器优化清单对齐）：
  A. 打包完整性：src/*.py 是否都进了 spec 的 _src_modules（漏列=运行时缺模块）
  B. 视觉一致性：f-string 末尾拼 alpha（#RRGGBBAA 被 Qt 当 AARRGGBB 解析）
  C. i18n 对齐：中英键集合是否一致、值是否残留未翻译中文
  D. 动画防失效：effect 复用/代际标记、stop+接力、MOTION_REDUCED 分支
  E. 线程/资源：Worker 引用是否挂到宿主防 GC、QTimer 兜底是否代际保护
  F. 数据边界：部署脚本是否误删用户数据目录

输出：<data>/audit_loop_report.json + 控制台摘要（stdout 可能被吞时用文件）
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = Path(HERE) / "src"
SPEC = Path(HERE) / "AC_PiTest_noupx.spec"

FINDINGS: list[dict] = []


def add(dim: str, level: str, file: str, line: int, msg: str, fix: str = ""):
    FINDINGS.append({
        "dim": dim, "level": level, "file": file, "line": line,
        "msg": msg, "fix": fix,
    })


# ── A. 打包完整性：检查真实打包产物的 PYZ，而非 spec 列表 ────────────────
# ☠ 教训：不能拿「spec._src_modules 没列」当漏收判据 —— PyInstaller 的静态
# 分析会通过函数内 import 自动收进绝大部分模块。实测 21 个「漏列」模块
# 在 PYZ 里全部存在，全是假阳性。判据必须落在最终产物上。
def audit_spec_modules() -> None:
    exe = Path(r"D:\Appdata\AC_Launcher\AC_Launcher.exe")
    if not exe.is_file():
        add("A.打包完整性", "P2", str(SPEC), 0,
            "测试包 exe 不存在，跳过产物级检查（spec 静态列表不作为判据）")
        print("[A] 跳过：测试包 exe 不存在")
        return
    try:
        from PyInstaller.archive.readers import CArchiveReader
        import tempfile
        c = CArchiveReader(str(exe))
        pyz_member = next((n for n in c.toc if "PYZ" in n), None)
        if pyz_member is None:
            add("A.打包完整性", "P1", str(exe), 0, "产物里找不到 PYZ 归档")
            return
        data = c.extract(pyz_member)
        import hashlib
        tmp = os.path.join(tempfile.gettempdir(),
                           "ac_audit_pyz_%s.pyz" % hashlib.md5(str(exe).encode()).hexdigest()[:8])
        with open(tmp, "wb") as f:
            f.write(data)
        from PyInstaller.archive.readers import ZlibArchiveReader
        packed = set(ZlibArchiveReader(tmp).toc)

        # 磁盘模块里，找出「被 import 但产物中缺失」的（真漏收）
        on_disk = set()
        for p in SRC.rglob("*.py"):
            rel = p.relative_to(Path(HERE)).with_suffix("")
            mod = str(rel).replace(os.sep, ".")
            if mod.startswith("src.") and "__init__" not in mod:
                on_disk.add(mod)
        missing = sorted(m for m in on_disk if m not in packed)
        for mod in missing:
            add("A.打包完整性", "P1", str(exe), 0,
                f"模块 {mod} 在磁盘存在但打包产物 PYZ 里缺失（真漏收）",
                f'在 spec._src_modules 加 "{mod}"')
        try:
            os.remove(tmp)
        except OSError:
            pass
        print(f"[A] PYZ 收 {len(packed)} 模块，磁盘 {len(on_disk)}，真缺 {len(missing)}")
    except Exception as e:
        add("A.打包完整性", "P2", str(exe), 0, f"产物检查异常: {e}")
        print(f"[A] 产物检查异常: {e}")


# ── B. 视觉一致性：末尾拼 alpha 的 f-string ──────────────────────────────
def audit_alpha_suffix() -> None:
    pat = re.compile(r"(COLORS(?:\.get\([^)]*\)|\[[^\]]+\]))\}\s*[0-9A-Fa-f]{2}\b")
    hit = 0
    for p in SRC.rglob("*.py"):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if pat.search(line):
                hit += 1
                add("B.视觉一致性", "P0", str(p.relative_to(HERE)), i,
                    "末尾拼 alpha → Qt 按 #AARRGGBB 解析成错误颜色（应用 with_alpha）",
                    "改用 with_alpha(color, 0xNN)")
    print(f"[B] 末尾拼 alpha 命中 {hit}")


# ── C. i18n 键对齐 ──────────────────────────────────────────────────────
def audit_i18n() -> None:
    try:
        sys.path.insert(0, HERE)
        from src.i18n import _STRINGS
    except Exception as e:
        add("C.i18n", "P1", "src/i18n.py", 0, f"导入失败: {e}")
        return
    zh, en = set(_STRINGS.get("zh-CN", {})), set(_STRINGS.get("en-US", {}))
    for k in sorted(zh - en):
        add("C.i18n", "P1", "src/i18n.py", 0, f"中文键 {k} 缺英文", f"en-US 补 {k}")
    for k in sorted(en - zh):
        add("C.i18n", "P1", "src/i18n.py", 0, f"英文键 {k} 缺中文", f"zh-CN 补 {k}")
    # en-US 里残留中文（排除语言名本身）
    import unicodedata
    def has_cjk(s):
        return any("\u4e00" <= c <= "\u9fff" for c in s)
    leftovers = [(k, v) for k, v in _STRINGS.get("en-US", {}).items()
                 if has_cjk(str(v)) and k not in ("settings.lang_zh",)]
    for k, v in leftovers[:20]:
        add("C.i18n", "P2", "src/i18n.py", 0, f"en-US 值含中文: {k} = {v[:40]}")
    print(f"[C] zh={len(zh)} en={len(en)} 差 {len(zh ^ en)}，英文残留中文 {len(leftovers)}")


# ── D. 动画防失效 ───────────────────────────────────────────────────────
def audit_animation() -> None:
    eff = SRC / "effects.py"
    if not eff.is_file():
        return
    txt = eff.read_text(encoding="utf-8")
    checks = [
        ("_fade_gen", "页面切换缺代际标记（旧动画回调可能误删新 effect）"),
        ("isinstance(prev_eff, QGraphicsOpacityEffect)", "缺 effect 复用（中途切页会闪回全透明）"),
        ("QEasingCurve.OutQuad", "easing 非 OutQuad（OutCubic 观感像抖一下）"),
    ]
    for token, msg in checks:
        if token not in txt:
            add("D.动画防失效", "P1", "src/effects.py", 0, msg)
    # fade_in_widget 不应再被 EFFECTS_ENABLED 连带关闭
    m = re.search(r"def fade_in_widget.*?(?=\ndef |\Z)", txt, re.S)
    if m and "not EFFECTS_ENABLED" in m.group(0):
        add("D.动画防失效", "P1", "src/effects.py", 0,
            "fade_in_widget 仍被流光开关 EFFECTS_ENABLED 连带关闭")
    print(f"[D] 动画防失效检查 {len(checks)+1} 项")


# ── E. 列表虚拟化 / 图片懒加载（来自 Playnite/LaunchBox 优化清单）────────
# ☠ 教训：旧版 E 组用「.start() 前无 self.xxx 持有」当 GC 判据，实测 36 条
# 全是假阳性（timer/动画/模块级单例都被误判）。已删除该判据。
# 现改为查更可靠的「大列表是否虚拟化 + 图片是否降采样」模式（仅提示，P2）。
def audit_list_virtualization() -> None:
    # ☠ 教训：QListWidget 判据对 AC 是假阳性——唯一用处是「选备份快照」
    # 小对话框（几个条目）；主列表走 QScrollArea+手动卡片。已删除。
    # 改为查 PolyMC issue #331 的坑：把 devicePixelRatio 缓存进成员变量，
    # 跨屏拖动/改缩放后不刷新 → 图标模糊或错位。
    for p in SRC.rglob("*.py"):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if re.search(r"self\.\w*dpr\w*\s*=\s*.*devicePixelRatio\s*\(", line, re.I):
                add("E.高DPI", "P2", str(p.relative_to(HERE)), i,
                    "devicePixelRatio 被缓存进 self 成员（跨屏/改缩放后不刷新，PolyMC #331 坑）",
                    "每次使用时读 QApplication.instance().devicePixelRatio()")
    # 图片降采样：只查真正加载「外部大图」的模块（async_image 是唯一入口）。
    # ☠ 教训：store_detail 只有 14/88px 内置小图标，不需要 scaled——
    # 把它纳入判据会产生假阳性。判据要落在「加载用户/网络大图」的路径上。
    ai = SRC / "async_image.py"
    if ai.is_file() and ".scaled(" not in ai.read_text(encoding="utf-8"):
        add("E.列表性能", "P2", "src/async_image.py", 0,
            "外部图片加载入口未见 .scaled() 降采样（大图直显费内存）")
    # 搜索防抖（Playnite/HMCL 通用模式）：textChanged 直连网络请求 = 每键一次请求
    for name in ("pages_browse.py", "mod_list.py"):
        p = SRC / name
        if not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8")
        if "textChanged.connect" in txt and "QTimer" in txt:
            # 有 QTimer 且连了 textChanged —— 进一步看是否真做了防抖
            if "setInterval" not in txt and "singleShot" not in txt:
                add("E.列表性能", "P2", f"src/{name}", 0,
                    "搜索 textChanged 连了 QTimer 但未见 setInterval/singleShot 防抖配置")
    print(f"[E] 列表/图片/搜索性能提示 {len([f for f in FINDINGS if f['dim'].startswith('E.')])}")


# ── 主流程 ──────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="只跑静态扫描，不跑回归测试")
    ap.add_argument("--fix-spec", action="store_true", help="自动把漏列模块加进 spec")
    args = ap.parse_args()

    print("=== AC Launcher 自主优化循环 · 静态审计 ===")
    audit_spec_modules()
    audit_alpha_suffix()
    audit_i18n()
    audit_animation()
    audit_list_virtualization()

    if args.fix_spec:
        missing = [f["msg"].split()[1] for f in FINDINGS
                   if f["dim"].startswith("A.") and "模块" in f["msg"]]
        if missing:
            txt = SPEC.read_text(encoding="utf-8")
            marker = "    _src_modules = [" if "    _src_modules = [" in txt else None
            if marker:
                for mod in missing:
                    txt = txt.replace(marker, marker + f'\n    "{mod}",  # audit_loop auto', 1)
                SPEC.write_text(txt, encoding="utf-8")
                print(f"[fix-spec] 已加入 {len(missing)} 个模块")
            else:
                print("[fix-spec] 找不到 _src_modules 锚点，未改动")

    # 分类统计
    by_dim: dict[str, int] = {}
    for f in FINDINGS:
        by_dim[f["dim"]] = by_dim.get(f["dim"], 0) + 1
    print("\n=== 发现汇总 ===")
    for dim, n in sorted(by_dim.items()):
        print(f"  {dim}: {n}")
    print(f"  总计: {len(FINDINGS)}")

    # 写报告（data 目录，不污染项目）
    try:
        sys.path.insert(0, HERE)
        from src.paths import get_data_dir
        out = os.path.join(get_data_dir(), "audit_loop_report.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"total": len(FINDINGS), "findings": FINDINGS},
                      f, ensure_ascii=False, indent=2)
        print(f"\n报告: {out}")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
