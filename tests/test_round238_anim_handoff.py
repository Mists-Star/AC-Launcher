"""round-238：页面切换渐入的接力与代际保护回归。

用户反馈「动画只有一点点抖动」「操作几次后淡入失效」。根因两条：
  1. 每次切页先删旧 effect 再建新 effect 从 opacity=0 开始 → 中途切换时
     画面闪回全透明再淡入（观感=抖动）；
  2. 旧动画的兜底 QTimer 迟到时会 deleteLater 掉新动画正在用的 effect →
     后续切换没有 effect 可用（观感=动画失效）。

本测试用真实 QPropertyAnimation + 事件循环验证：
  * 中途切页：effect 对象被复用，opacity 从当前值接力（不闪回 0）
  * 快速连点 N 次后：effect 仍挂载且动画在跑（没被迟到回调误删）
  * 全部动画跑完后：effect 被清掉（不留半透明重影）
  * 减少动效：瞬时切换、无 effect
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPropertyAnimation, QTimer  # noqa: E402
from PySide6.QtWidgets import (QApplication, QGraphicsOpacityEffect,  # noqa: E402
                               QStackedWidget, QWidget)

app = QApplication(sys.argv)

from src import effects as ef  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


print("== 1. 中途切页从当前 opacity 接力（不闪回 0）==")
stack = QStackedWidget()
for _ in range(3):
    w = QWidget()
    stack.addWidget(w)
stack.show()
app.processEvents()

ef.fade_page_transition(stack, 0)
pump(80)  # 让淡入走到中间（190ms 动画的 ~40%）
first_eff = stack.graphicsEffect()
mid_op = first_eff.opacity() if isinstance(first_eff, QGraphicsOpacityEffect) else -1
check("第一次动画在半途 (0<opacity<1)", 0 < mid_op < 1, "opacity=%.2f" % mid_op)

ef.fade_page_transition(stack, 1)  # 中途切页
second_eff = stack.graphicsEffect()
second_start = getattr(stack, "_fade_anim", None)
check("effect 对象被复用（不重建）", second_eff is first_eff,
      "same=%s" % (second_eff is first_eff))
check("第二次动画从当前值起步（非 0）",
      second_start is not None and second_start.startValue() > 0.05,
      "start=%.2f" % (second_start.startValue() if second_start else -1))
pump(300)
check("动画结束后 effect 被清掉", stack.graphicsEffect() is None)

print("== 2. 快速连点 10 次：effect 不被迟到回调误删 ==")
for i in range(10):
    ef.fade_page_transition(stack, i % 3)
    pump(15)  # 每次只走一点点，制造大量中途打断
final_eff = stack.graphicsEffect()
final_anim = getattr(stack, "_fade_anim", None)
check("连点后 effect 仍挂载", isinstance(final_eff, QGraphicsOpacityEffect))
check("连点后动画仍在跑", final_anim is not None and final_anim.state() == QPropertyAnimation.Running)
pump(400)
check("连点全部结束后 effect 清掉", stack.graphicsEffect() is None)

print("== 3. 减少动效：瞬时切换 ==")
ef.set_reduce_motion(True)
ef.fade_page_transition(stack, 0)
check("减少动效时无 effect", stack.graphicsEffect() is None)
check("减少动效时页码正确", stack.currentIndex() == 0)
ef.set_reduce_motion(False)

print("\nround-238 anim handoff: %d checks, %d failed" % (8, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.stdout.flush()
    sys.exit(1)
print("ALL CHECKS PASSED（渐入接力 / 代际保护）")
sys.stdout.flush()
os._exit(0)
