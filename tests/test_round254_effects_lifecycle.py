"""round-254：动画系统生命周期回归 —— 「用几次后动画全失效」类问题。

覆盖三条历史根因（2026-11-25 实测复现）：
1. ``effects._ACTIVE_CARDS`` 用强引用 set，且 ``destroy()`` 不是 Qt 生命周期
   钩子 —— deleteLater / 父控件析构都不触发，失效卡片永远留在集合里，主表
   空转、新卡片也不复活 → WeakSet + destroyed 信号 + tick 剔除。
2. ``feedback.apply_feedback_to_button`` 在**构造期**按全局开关决定挂不挂 mixin，
   设置页运行时打开「点击波纹」后，已存在的按钮永远拿不到效果 → 一律挂载、
   事件期实时读开关（波纹覆盖层懒建，默认关零开销）。
3. 按下途中关掉「按下缩放」，按钮会卡在缩小态 → 关开关时补一次 release。
"""
from __future__ import annotations

import gc
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QGraphicsOpacityEffect, QPushButton,
    QStackedWidget, QWidget,
)

app = QApplication.instance() or QApplication([])

from src import effects as fx  # noqa: E402
from src import feedback as fb  # noqa: E402

FAILS: list[str] = []
COUNT = 0


def check(label, ok, extra=""):
    global COUNT
    COUNT += 1
    print("  %s %-62s %s" % ("OK  " if ok else "FAIL", label, extra))
    if not ok:
        FAILS.append(label)


def pump(ms=30):
    QTest.qWait(ms)
    gc.collect()


def press(btn: QPushButton, x=40.0, y=20.0):
    me = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y),
                     QPointF(x, y), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(btn, me)


def release(btn: QPushButton, x=40.0, y=20.0):
    me = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y),
                     QPointF(x, y), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(btn, me)


fx.set_effects_enabled(True)
fx.set_reduce_motion(False)
fx.set_game_running(False)

print("== 1. 流光卡销毁后不再残留在活动集合 / 主表不空转 ==")
card = fx.LightTrailCard()
card.show()
pump()
check("show() 登记到活动集合", card in fx._ACTIVE_CARDS)
check("主表已启动", fx._MASTER is not None and fx._MASTER.isActive())

card.deleteLater()
pump()
check("deleteLater 后自动移出集合", card not in fx._ACTIVE_CARDS)
check("最后一张卡销毁后主表停摆", fx._MASTER is not None and not fx._MASTER.isActive())

parent = QWidget()
child = fx.LightTrailCard(parent)
child.show()
pump()
check("父控件内新卡正常登记", child in fx._ACTIVE_CARDS)
check("新卡让主表重新起来", fx._MASTER is not None and fx._MASTER.isActive())
parent.deleteLater()
child.deleteLater()
pump()
check("父控件+卡片一起销毁后集合干净", len(fx._ACTIVE_CARDS) == 0,
      "size=%d" % len(fx._ACTIVE_CARDS))
check("全部销毁后主表停摆", fx._MASTER is not None and not fx._MASTER.isActive())

print("== 2. 反复重建后开关仍能恢复动画（不是「切几次页就死」） ==")
for i in range(5):
    c = fx.LightTrailCard()
    c.show()
    pump(10)
    check("第 %d 轮新卡登记" % (i + 1), c in fx._ACTIVE_CARDS)
    c.deleteLater()
    pump(10)
check("5 轮重建后集合为空", len(fx._ACTIVE_CARDS) == 0,
      "size=%d" % len(fx._ACTIVE_CARDS))

revived = fx.LightTrailCard()
revived.show()
pump()
check("重建后新卡仍能启动主表", fx._MASTER is not None and fx._MASTER.isActive())
fx.set_effects_enabled(False)
check("关流光停表", fx._MASTER is not None and not fx._MASTER.isActive())
fx.set_effects_enabled(True)
check("重开流光恢复", fx._MASTER is not None and fx._MASTER.isActive())
revived.deleteLater()
pump()
fx.set_reduce_motion(False)

print("== 3. 反馈开关运行期切换立即对既有按钮生效 ==")
btn = QPushButton("按钮")
btn.resize(100, 40)
btn.show()
pump()

fb.FeedbackConfig.enable_ripple = False
fb.apply_feedback_to_button(btn, press_scale=False, ripple=True, focus_ring=False)
overlays_off = [c for c in btn.children() if isinstance(c, fb._RippleOverlay)]
check("默认关时未创建波纹覆盖层（零开销）", not overlays_off)

fb.FeedbackConfig.enable_ripple = True
press(btn)
pump(120)
overlays_on = [c for c in btn.children() if isinstance(c, fb._RippleOverlay)]
check("运行期打开后，既有按钮生成波纹", bool(overlays_on))
check("波纹动画确实推进",
      bool(overlays_on) and overlays_on[0]._anim is not None
      and overlays_on[0]._radius > 0,
      "radius=%.1f" % (overlays_on[0]._radius if overlays_on else -1))
release(btn)
pump(400)  # 等上一轮波纹自己跑完，避免把残留 opacity 当成"又启动了"

fb.FeedbackConfig.enable_ripple = False
press(btn)
check("运行期关掉后波纹不再启动",
      not overlays_on or (
          overlays_on[0]._anim is None
          or overlays_on[0]._anim.state() != overlays_on[0]._anim.State.Running),
      "opacity=%.2f" % (overlays_on[0]._opacity if overlays_on else -1))
release(btn)

print("== 4. 按下途中关掉「按下缩放」，按钮不卡在缩小态 ==")
btn2 = QPushButton("按压")
btn2.resize(100, 40)
btn2.show()
pump()
fb.FeedbackConfig.enable_press_scale = True
fb.apply_feedback_to_button(btn2, press_scale=True, focus_ring=False)
baseline = btn2.geometry()
press(btn2)
pump(30)
check("按下后按钮被缩放", btn2.geometry() != baseline,
      str(btn2.geometry()))
fb.FeedbackConfig.enable_press_scale = False
release(btn2)   # 关闭后事件过滤仍要负责收尾
pump(150)
check("关掉开关后按钮恢复原尺寸", btn2.geometry() == baseline,
      "now=%s baseline=%s" % (btn2.geometry(), baseline))
fb.FeedbackConfig.enable_press_scale = True

print("== 5. 页面淡入连续打断仍能收尾 ==")
stack = QStackedWidget()
for _ in range(3):
    stack.addWidget(QWidget())
stack.show()
pump()
fx.fade_page_transition(stack, 1)
pump(30)
fx.fade_page_transition(stack, 2)
check("中途切页仍有淡入 effect",
      isinstance(stack.graphicsEffect(), QGraphicsOpacityEffect))
check("旧回调不越权清理新 effect",
      isinstance(stack.graphicsEffect(), QGraphicsOpacityEffect))
pump(400)
check("动画结束后 effect 已摘除", stack.graphicsEffect() is None)
check("页面归位（无累积偏移）", stack.currentWidget().pos().y() == 0,
      str(stack.currentWidget().pos()))

print("\nround-254 effects lifecycle: %d checks, %d failed"
      % (COUNT, len(FAILS)))
if FAILS:
    for f in FAILS:
        print("  FAILED:", f)
    sys.stdout.flush()
    sys.exit(1)
print("ALL CHECKS PASSED（流光卡生命周期 / 反馈开关运行期生效）")
sys.stdout.flush()
os._exit(0)
