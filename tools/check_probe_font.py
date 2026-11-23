"""扫所有会 Qt 截图/渲染的脚本是否设了 QT_QPA_FONTDIR。

☠ 离屏平台不加载系统字体 → 中文全 tofu 方框。这个坑踩过两次
（2026-11-21、2026-11-23），每次都是新写探针漏了那一行，还误判成
"offscreen 不支持中文"。跑一次本工具，缺的立刻列出来。

用法: venv/Scripts/python.exe tools/check_probe_font.py
"""
from __future__ import annotations

import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 会创建 QApplication 并截图/渲染的脚本特征
MARKERS = (".grab(", ".save(", "QApplication(", "QWidget")


def scan() -> list[str]:
    missing: list[str] = []
    for sub in ("tests", "."):
        dp = os.path.join(ROOT, sub)
        for name in os.listdir(dp):
            if not name.endswith(".py"):
                continue
            p = os.path.join(dp, name)
            if sub == "." and not (name.startswith("_probe") or name.startswith("test_")):
                continue
            try:
                text = io.open(p, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            # 只关心真的会 Qt 渲染的
            if "from PySide6" not in text and "import PySide6" not in text:
                continue
            if "QApplication" not in text:
                continue
            # 只有真正 grab()/save() 截图的才需要字体；纯逻辑探针不截图，
            # 中文 tofu 不影响断言（它们不读像素）。
            if any(m in text for m in (".grab(", ".save(")):
                if "QT_QPA_FONTDIR" not in text and not name.startswith("conftest"):
                    missing.append(os.path.relpath(p, ROOT))
    return sorted(set(missing))


if __name__ == "__main__":
    miss = scan()
    if miss:
        print("漏设 QT_QPA_FONTDIR 的渲染/截图脚本 (%d):" % len(miss))
        for p in miss:
            print("  " + p)
        print("\n修法：在创建 QApplication 之前加一行")
        print('  os.environ["QT_QPA_FONTDIR"] = r"C:\\Windows\\Fonts"')
    else:
        print("OK：所有渲染/截图脚本都设了 FONTDIR")
