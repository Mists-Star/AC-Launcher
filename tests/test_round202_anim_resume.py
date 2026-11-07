# -*- coding: utf-8 -*-
"""round-202：页面/卡片动画在切页、降载、连续重建后仍能恢复。

用户反馈「切换其他页面后可能导致所有页面动画失效」。根因是两处
一次性 effect 的收尾逻辑：旧动画的 finished 迟到时会清掉「新动画刚装
上的」effect；流光卡在主表停止期间露出时不登记，退出降载后也不复活。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QStackedWidget, QWidget, QGraphicsOpacityEffect,
)
from PySide6.QtTest import QTest  # noqa: E402

from src import effects as fx  # noqa: E402

FAILS: list[str] = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         (" | " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


app = QApplication.instance() or QApplication([])
fx.set_effects_enabled(True)
fx.set_reduce_motion(False)
fx.set_game_running(False)

# ── 1. 列表淡入：连续触发不能用旧回调杀掉新 effect ─────────────────
w = QWidget()
w.resize(200, 120)
w.show()
QTest.qWait(30)
fx.fade_in_widget(w, duration=40)    # 先短后长，模拟快速重建
fx.fade_in_widget(w, duration=400)
QTest.qWait(90)                      # 旧的 40ms 已到，新的还在跑
eff = w.graphicsEffect()
check("连续淡入时新 effect 未被旧回调误清",
      isinstance(eff, QGraphicsOpacityEffect),
      type(eff).__name__ if eff is not None else "None")
check("新淡入仍在进行（未直接跳到 100%）",
      eff is not None and eff.opacity() < 1.0,
      "opacity=%.2f" % (eff.opacity() if eff is not None else -1))
QTest.qWait(420)
check("淡入结束后 effect 已摘除", w.graphicsEffect() is None)
w.hide()

# ── 2. 页面切换：中途打断后再切，动画依旧完整 ───────────────────────
stack = QStackedWidget()
for _ in range(3):
    stack.addWidget(QWidget())
stack.resize(400, 300)
stack.show()
QTest.qWait(30)

fx.fade_page_transition(stack, 1)
QTest.qWait(100)                     # 第一段动画未结束就再切
fx.fade_page_transition(stack, 2)
eff2 = stack.graphicsEffect()
check("打断后新切页仍装上淡入 effect",
      isinstance(eff2, QGraphicsOpacityEffect),
      type(eff2).__name__ if eff2 is not None else "None")
QTest.qWait(90)                      # 第一段的 finished 会在这附近到达
check("旧动画的收尾没有清掉新 effect",
      isinstance(stack.graphicsEffect(), QGraphicsOpacityEffect))
QTest.qWait(400)
check("切页动画结束后 effect 已摘除", stack.graphicsEffect() is None)
check("新页已归位（无累积偏移）",
      stack.currentWidget().pos().y() == 0,
      str(stack.currentWidget().pos()))

# 再切一次，确认不是「只有第一次能动画」
fx.fade_page_transition(stack, 1)
eff3 = stack.graphicsEffect()
check("后续切页仍能开始新的淡入",
      isinstance(eff3, QGraphicsOpacityEffect)
      and eff3.opacity() < 1.0)
QTest.qWait(400)
check("第三次切页也能正常收尾", stack.graphicsEffect() is None)
stack.hide()

# ── 3. 流光卡：降载期间露出 / 开关切回后自动恢复 ───────────────────
card = fx.LightTrailCard()
card.resize(120, 60)
card.show()
QTest.qWait(40)
check("可见卡片会登记到活动集合", card in fx._ACTIVE_CARDS)
check("主表已启动", fx._MASTER is not None and fx._MASTER.isActive())

fx.set_game_running(True)
check("游戏运行 → 主表停摆",
      fx._MASTER is not None and not fx._MASTER.isActive())
check("停摆期间卡片仍保留登记（退出后能复活）", card in fx._ACTIVE_CARDS)
fx.set_game_running(False)
check("游戏退出 → 主表自动恢复",
      fx._MASTER is not None and fx._MASTER.isActive())

fx.set_reduce_motion(True)
check("减少动效 → 主表停摆",
      fx._MASTER is not None and not fx._MASTER.isActive())
check("减少动效期间不清空登记", card in fx._ACTIVE_CARDS)
fx.set_reduce_motion(False)
check("关掉减少动效 → 主表自动恢复",
      fx._MASTER is not None and fx._MASTER.isActive())

fx.set_effects_enabled(False)
check("关闭流光 → 主表停摆",
      fx._MASTER is not None and not fx._MASTER.isActive())
fx.set_effects_enabled(True)
check("重开流光 → 主表自动恢复",
      fx._MASTER is not None and fx._MASTER.isActive())

card.hide()
QTest.qWait(20)
check("卡片隐藏后移出活动集合", card not in fx._ACTIVE_CARDS)
check("无活动卡片后主表停摆",
      fx._MASTER is not None and not fx._MASTER.isActive())

# ── 4. 静态接线：恢复条件收敛在一处，收尾只清自己的 effect ──────────
src = read("src/effects.py")
check("存在统一的恢复入口 _resume_if_possible", "def _resume_if_possible(" in src)
for fn in ("def set_game_running(", "def set_reduce_motion(",
           "def set_effects_enabled("):
    start = src.index(fn)
    body = src[start:start + 900]
    check("%s 调用了 _resume_if_possible" % fn.split()[1].rstrip("("),
          "_resume_if_possible()" in body)
check("减少动效不再清空活动集合",
      "_ACTIVE_CARDS.clear()" not in src[src.index("def set_reduce_motion("):
                                          src.index("def motion_ms(")])
check("切页收尾只清自己装的 effect",
      "if stack.graphicsEffect() is _eff:" in src)
check("列表淡入收尾只清自己装的 effect",
      "if w.graphicsEffect() is _eff:" in src)

print("RESULT:", "PASS" if not FAILS else "FAIL %d: %r" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
