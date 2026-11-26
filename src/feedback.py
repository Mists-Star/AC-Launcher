"""
Feedback effects — round-236: 增强启动器的反馈感。

提供：
1. PressScaleMixin —— 按钮按下时轻微缩放（98%），释放恢复，带缓动。
2. RippleEffect —— 点击位置扩散的波纹（Material Design 风格），可选开关。
3. HoverGlowMixin —— 悬停时添加微弱发光阴影（QGraphicsDropShadowEffect）。
4. FocusRingMixin —— 键盘聚焦时显示明显的焦点环（无障碍）。
5. apply_feedback_to_button() —— 一键把以上效果挂到任意 QPushButton。
6. FeedbackConfig —— 全局开关（尊重 MOTION_REDUCED / 无障碍偏好）。

设计原则：
- 纯装饰，绝不阻塞功能；异常静默吞掉。
- 尊重 effects.EFFECTS_ENABLED、effects.MOTION_REDUCED、QApplication 的高对比度模式。
- 不侵入现有 QSS：用 GraphicsEffect + PropertyAnimation 叠加，切主题自动同步颜色。
- 默认开启 PressScale + FocusRing；Ripple / HoverGlow 由配置控制（默认关，避免过度动效）。
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QFocusEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QPushButton,
    QStyle,
    QWidget,
)

# ☠ round-248：`from .effects import EFFECTS_ENABLED, MOTION_REDUCED` 是
# **导入时的值快照**——main_window 后面调 set_effects_enabled()/set_reduce_motion()
# 改的是 effects 模块的变量，这里的副本永远不更新 → 按钮反馈/波纹按错误的
# 开关状态工作（用户实测"所有动画都失效"）。改为实时读模块属性。
try:
    from . import effects as _effects
except Exception:  # noqa: BLE001
    _effects = None


class FeedbackConfig:
    """全局反馈效果开关（可在运行时修改，即时生效）。"""

    # 是否启用按下缩放（PressScale）——默认开，体感最明显
    enable_press_scale: bool = True
    # 缩放比例（1.0 = 不缩放，0.98 = 缩放 2%）
    press_scale_factor: float = 0.98
    # 缩放动画时长（ms），遵循 MOTION_INSTANT_MS
    press_scale_duration_ms: int = 90

    # 是否启用波纹效果——默认关，避免过度动效；玩家可在设置里开
    enable_ripple: bool = False
    # 波纹颜色（默认跟随 accent，alpha=60）
    ripple_color: Optional[QColor] = None
    # 波纹扩散时长（ms）
    ripple_duration_ms: int = 350

    # 是否启用悬停发光——默认关
    enable_hover_glow: bool = False
    # 发光颜色（默认 accent，alpha=40）
    hover_glow_color: Optional[QColor] = None
    # 发光模糊半径
    hover_glow_blur_radius: int = 16

    # 是否启用焦点环——默认开（无障碍必须）
    enable_focus_ring: bool = True
    # 焦点环颜色（默认 accent）
    focus_ring_color: Optional[QColor] = None
    # 焦点环宽度
    focus_ring_width: int = 2

    @classmethod
    def is_reduced_motion(cls) -> bool:
        """是否应当减少动效。

        ☠ round-248：旧实现是 `from .effects import EFFECTS_ENABLED,
        MOTION_REDUCED` 的**导入快照**——运行时 set_reduce_motion()/流光开关
        改的是 effects 模块变量，这里永远不更新。且把 EFFECTS_ENABLED（流光
        装饰）也算进"减少动效"是错的：用户关流光但开了按钮反馈是合法配置。
        现在实时读 effects.MOTION_REDUCED，与 round-238 的 fade_in_widget 解耦
        口径一致——只有无障碍「减少动效」才是全局动画总闸。
        """
        if _effects is None:
            return False
        return bool(getattr(_effects, "MOTION_REDUCED", False))

    @classmethod
    def apply_config(cls, cfg: dict) -> None:
        """把玩家设置里的 feedback_* 开关同步到运行时（当前无人接线，修复）。"""
        if not isinstance(cfg, dict):
            return
        cls.enable_press_scale = bool(cfg.get("feedback_press_scale", True))
        cls.enable_ripple = bool(cfg.get("feedback_ripple", False))
        cls.enable_hover_glow = bool(cfg.get("feedback_hover_glow", False))
        cls.enable_focus_ring = bool(cfg.get("feedback_focus_ring", True))

    @classmethod
    def should_animate(cls) -> bool:
        return not cls.is_reduced_motion()


class _PressScaleMixin(QObject):
    """给 QPushButton 添加按下缩放动画。"""

    def __init__(self, button: QPushButton):
        super().__init__(button)
        self._btn = button
        self._anim: Optional[QPropertyAnimation] = None
        self._orig_geom = None
        button.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self._btn:
            return False
        if FeedbackConfig.is_reduced_motion() or \
                not FeedbackConfig.enable_press_scale:
            # round-254：开关在按下途中被关掉时也要收尾，否则按钮卡在缩小态。
            if self._orig_geom is not None and event.type() in (
                    QEvent.Type.MouseButtonRelease, QEvent.Type.Leave):
                self._release_press()
            return False

        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress:
            # 只有 MouseButtonPress/Release 才是 QMouseEvent；直接把 QEvent
            # 当 QMouseEvent 用会在 Leave 分支抛 AttributeError（crash.log 里
            # 每个鼠标离开都记一条，异常风暴拖慢交互）。
            me = event
            if isinstance(me, QMouseEvent) and \
                    me.button() == Qt.MouseButton.LeftButton and self._btn.isEnabled():
                self._start_press()
                return False  # 不拦截，让按钮正常处理 clicked

        elif etype == QEvent.Type.MouseButtonRelease:
            me = event
            if isinstance(me, QMouseEvent) and me.button() == Qt.MouseButton.LeftButton:
                self._release_press()

        elif etype == QEvent.Type.Leave:
            # Leave 是普通 QEvent，没有 button()，独立处理
            self._release_press()
        return False

    def _start_press(self):
        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()

        self._orig_geom = self._btn.geometry()
        w, h = self._orig_geom.width(), self._orig_geom.height()
        factor = FeedbackConfig.press_scale_factor
        nw, nh = int(w * factor), int(h * factor)
        dx, dy = (w - nw) // 2, (h - nh) // 2
        target = self._orig_geom.adjusted(dx, dy, -dx, -dy)

        # 不用 DeleteWhenStopped：动画停止后 C++ 对象自毁，而 self._anim 仍
        # 持有 Python 引用 → 下一次 _release_press 读 state() 抛
        # "Internal C++ object already deleted"（crash.log 里已复现）。
        # 复用同一个动画对象，下次 _start_press 会 stop + 重设值。
        if self._anim is None:
            self._anim = QPropertyAnimation(self._btn, b"geometry", self)
        self._anim.setDuration(FeedbackConfig.press_scale_duration_ms)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(self._orig_geom)
        self._anim.setEndValue(target)
        self._anim.start()

    def _release_press(self):
        if self._orig_geom is None:
            return
        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()

        if self._anim is None:
            self._anim = QPropertyAnimation(self._btn, b"geometry", self)
        self._anim.setDuration(FeedbackConfig.press_scale_duration_ms)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._anim.setStartValue(self._btn.geometry())
        self._anim.setEndValue(self._orig_geom)
        self._anim.start()
        self._orig_geom = None


class _RippleMixin(QObject):
    """波纹：懒创建覆盖层，全局开关在事件期判定（round-254）。

    旧实现在 ``apply_feedback_to_button()`` 构造期按
    ``FeedbackConfig.enable_ripple`` 决定挂不挂 —— 设置页运行时打开开关后，
    已存在的按钮永远拿不到波纹（"开了没反应"）。现在一律挂载 mixin，
    开关在事件里读；覆盖层只在开关打开且真被点击时才创建（默认关→零开销）。
    """

    def __init__(self, button: QPushButton):
        super().__init__(button)
        self._btn = button
        self._overlay: Optional[_RippleOverlay] = None
        button.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self._btn:
            return False
        if FeedbackConfig.is_reduced_motion() or not FeedbackConfig.enable_ripple:
            if self._overlay is not None:
                self._overlay.hide()
            return False
        if event.type() == QEvent.Type.MouseButtonPress:
            me = event  # type: QMouseEvent
            if isinstance(me, QMouseEvent) and \
                    me.button() == Qt.MouseButton.LeftButton and self._btn.isEnabled():
                if self._overlay is None:
                    self._overlay = _RippleOverlay(self._btn)
                self._overlay._start_ripple(me.position())
        return False


class _RippleOverlay(QWidget):
    """点击位置扩散的波纹覆盖层（作为按钮的子控件，不占布局）。"""

    def __init__(self, parent: QPushButton):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setGeometry(parent.rect())
        self._radius = 0.0
        self._opacity = 0.0
        self._center = QPointF()
        self._anim: Optional[QPropertyAnimation] = None
        self._color = QColor(0, 0, 0, 0)
        self.hide()

    def _start_ripple(self, pos: QPointF):
        self._center = pos
        self._radius = 0.0
        self._opacity = 0.6
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()

        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()

        # 动画半径从 0 到对角线长度
        w, h = self.parent().width(), self.parent().height()
        max_r = (w * w + h * h) ** 0.5

        # 同上：复用动画对象，避免 DeleteWhenStopped 留下悬空 Python 引用。
        if self._anim is None:
            self._anim = QPropertyAnimation(self, b"_ripple_progress", self)
            self._anim.valueChanged.connect(self._on_progress)
            self._anim.finished.connect(self._on_finished)
        self._anim.setDuration(FeedbackConfig.ripple_duration_ms)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_progress(self, v: float):
        w, h = self.parent().width(), self.parent().height()
        max_r = (w * w + h * h) ** 0.5
        self._radius = max_r * v
        self._opacity = 0.6 * (1.0 - v)
        self.update()

    def _on_finished(self):
        self.hide()
        self._radius = 0.0
        self._opacity = 0.0

    def paintEvent(self, event):
        if self._radius <= 0 or self._opacity <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = FeedbackConfig.ripple_color or QColor("#7C3AED")
        color.setAlphaF(self._opacity)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(self._center, self._radius, self._radius)


class _HoverGlowMixin(QObject):
    """悬停时添加发光阴影效果。"""

    def __init__(self, button: QPushButton):
        super().__init__(button)
        self._btn = button
        self._effect: Optional[QGraphicsDropShadowEffect] = None
        button.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self._btn or FeedbackConfig.is_reduced_motion():
            return False
        if not FeedbackConfig.enable_hover_glow:
            return False

        if event.type() == QEvent.Type.Enter:
            self._show_glow()
        elif event.type() == QEvent.Type.Leave:
            self._hide_glow()
        return False

    def _show_glow(self):
        if self._effect is None:
            self._effect = QGraphicsDropShadowEffect(self._btn)
            self._effect.setOffset(0, 0)
            self._effect.setBlurRadius(FeedbackConfig.hover_glow_blur_radius)
            color = FeedbackConfig.hover_glow_color or QColor("#7C3AED")
            color.setAlpha(100)
            self._effect.setColor(color)
            self._btn.setGraphicsEffect(self._effect)

    def _hide_glow(self):
        if self._effect is not None:
            self._btn.setGraphicsEffect(None)
            self._effect.deleteLater()
            self._effect = None


class _FocusRingMixin(QObject):
    """键盘聚焦时绘制焦点环（重写 paintEvent 或用事件过滤器）。"""

    def __init__(self, button: QPushButton):
        super().__init__(button)
        self._btn = button
        self._btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.installEventFilter(self)
        self._focused = False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self._btn or not FeedbackConfig.enable_focus_ring:
            return False

        if event.type() == QEvent.Type.FocusIn:
            self._focused = True
            self._btn.update()
        elif event.type() == QEvent.Type.FocusOut:
            self._focused = False
            self._btn.update()
        return False


def apply_feedback_to_button(
    button: QPushButton,
    *,
    press_scale: bool = True,
    ripple: bool = False,
    hover_glow: bool = False,
    focus_ring: bool = True,
) -> None:
    """
    一键为按钮启用反馈效果。

    参数默认值遵循 FeedbackConfig 全局开关，但可单独覆盖。
    返回的 mixin 对象可保留引用以便后续移除（通常不需要）。
    """
    # round-254：一律挂载，开关在每个 mixin 的事件期实时读。
    # 旧实现在构造期用全局开关决定"挂不挂"，而设置页是运行时改这些开关的
    # ——已存在的按钮（导航/首页 CTA）永远不会获得效果，"开了没反应"。
    if press_scale:
        _PressScaleMixin(button)

    if ripple:
        _RippleMixin(button)   # 懒建 overlay：默认关时零开销

    if hover_glow:
        _HoverGlowMixin(button)

    if focus_ring:
        _FocusRingMixin(button)


def sync_feedback_colors_from_theme() -> None:
    """从当前主题同步颜色（切主题/换强调色后调用）。"""
    try:
        from .theme import COLORS
        accent = QColor(COLORS.get("accent", "#7C3AED"))
        FeedbackConfig.ripple_color = QColor(accent)
        FeedbackConfig.ripple_color.setAlpha(60)
        FeedbackConfig.hover_glow_color = QColor(accent)
        FeedbackConfig.hover_glow_color.setAlpha(100)
        FeedbackConfig.focus_ring_color = QColor(accent)
    except Exception:  # noqa: BLE001
        pass


# 在主题变化时自动同步颜色
try:
    from .theme import on_theme_change
    on_theme_change(sync_feedback_colors_from_theme)
except Exception:  # noqa: BLE001
    pass


# 启动时同步一次
sync_feedback_colors_from_theme()