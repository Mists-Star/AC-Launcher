"""pytest 全局环境：Qt 离屏截图必须有中文字体，否则全 tofu 方框。

☠ 历史事故（2026-11-21 / 11-23 两次）：新写的离屏脚本漏了
   QT_QPA_FONTDIR=C:\\Windows\\Fonts，截图全是 □□□，误判成"UI 显示 bug"，
   被用户当场指出「之前不是修过吗」。这里在 pytest 收集前统一设置，
   测试脚本（含 grab()/save() 截图）不再各自重复。
"""
import os

os.environ["QT_QPA_PLATFORM"] = os.environ.get("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
