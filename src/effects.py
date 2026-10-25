"""液态流光 (Liquid Light-flow) effects — round-49.

Self-contained, fault-tolerant animated surfaces for the launcher:

  * ``LightTrailCard`` — a ``RoundedCard`` subclass that paints a **流体曳光**
    (bright gradient segment traveling clockwise around the border) plus a
    **反射** (soft diagonal highlight sweep across the surface). Subtle by
    default, uses the active theme accent so it blends with light/dark.
  * ``set_window_opacity`` — 全局透明 / 透底 (whole-window alpha).
  * ``fade_page_transition`` — 启动器动画：页面切换淡入。

Every painter is wrapped in try/except and falls back to a plain rounded card,
so an effect bug can never break the UI. A module-level ``EFFECTS_ENABLED``
(gated by config ``effect_light_trail``) lets the whole system turn off at once.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QLinearGradient, QConicalGradient,
)
from PySide6.QtWidgets import QApplication

from .theme import COLORS, RoundedCard

# ── global switch (config-driven, refreshed at startup) ─────────────────────
EFFECTS_ENABLED = True


def set_effects_enabled(on: bool) -> None:
    global EFFECTS_ENABLED
    EFFECTS_ENABLED = bool(on)
    if not EFFECTS_ENABLED:
        _stop_master()


# ── shared master ticker (round-50 性能：多卡片共用一只表) ────────────────
# 之前每张流光卡都私有一个 33ms QTimer，卡片一多 CPU 直接起飞。这里用一个
# 模块级主定时器统一 tick 所有"可见"的流光卡，切后台自动停表——卡片混合
# 视觉不变，CPU 却只花一份。
_ACTIVE_CARDS: set = set()
_MASTER: QTimer | None = None


def _ensure_master() -> None:
    global _MASTER
    if _MASTER is None:
        _MASTER = QTimer()
        _MASTER.setInterval(33)  # ~30 fps
        _MASTER.timeout.connect(_tick_all)
    try:
        if not _MASTER.isActive():
            _MASTER.start()
    except RuntimeError:
        pass  # 见 _stop_master：退出期 C++ 定时器可能已被销毁


def _stop_master() -> None:
    try:
        if _MASTER is not None and _MASTER.isActive():
            _MASTER.stop()
    except RuntimeError:
        # round-61 收尾：进程退出时卡片析构会触发 hideEvent → 本函数，
        # 此时 C++ 侧的 QTimer 可能已被销毁（Python 包装还活着），
        # isActive()/stop() 抛 RuntimeError —— 直接放过，不再重试。
        pass


def _has_focus() -> bool:
    """本应用任意窗口处于激活状态吗？

    round-60 性能：主窗口失焦（切到别的程序）时停掉流光卡的重绘。
    ``activeWindow()`` 为 None 说明当前焦点不在本应用（含最小化），返回
    False → 主表空转（每 33ms 一次纯 Python 检查，几乎零开销），焦点回来
    自动恢复重绘，无需状态机。
    无 QApplication（离线纯逻辑/测试）时一律放行，避免误停。
    """
    try:
        app = QApplication.instance()
        if app is None:
            return True
        return app.activeWindow() is not None
    except Exception:  # noqa: BLE001
        return True


def _in_viewport(c) -> bool:
    """卡片当前是否真的有一小块可被看到？

    round-61 性能：Qt 的 ``isVisible()`` 不会因滚动出视口而变 False ——
    QScrollArea 里滚出屏幕的卡片依旧算"可见"，每帧都会触发一次被裁剪掉的
    光栅化。``visibleRegion()`` 只会计入真实可见的像素（滚动区、被裁剪的
    祖先都会参与剪裁），用它判断最准；滚回来动画自动续上。判错最坏只是
    某帧不重绘，无副作用。
    """
    try:
        return not c.visibleRegion().isEmpty()
    except Exception:  # noqa: BLE001 - 判定失败放行，最多多画一帧
        return True


def _tick_all() -> None:
    # 失焦 → 暂停所有流光卡（大卡片 30fps 光栅化比空循环贵几个数量级）；
    # 焦点恢复后下一次 tick 自动继续，动画无感知。
    if not _has_focus():
        return
    for c in list(_ACTIVE_CARDS):
        try:
            # 视口裁剪：滚出滚动区视口的卡片跳过（见 _in_viewport）。
            if c is not None and c.isVisible() and _in_viewport(c):
                c._advance()
        except Exception:  # noqa: BLE001 - 单卡异常不影响其它
            pass
    if not _ACTIVE_CARDS:
        _stop_master()


def _accent() -> QColor:
    try:
        return QColor(COLORS.get("accent", "#7C3AED"))
    except Exception:  # noqa: BLE001
        return QColor("#7C3AED")


def _card_fill() -> QColor:
    try:
        return QColor(COLORS.get("bg_card", "#FFFFFF"))
    except Exception:  # noqa: BLE001
        return QColor("#FFFFFF")


def _border() -> QColor:
    try:
        return QColor(COLORS.get("border", "#E5E7EB"))
    except Exception:  # noqa: BLE001
        return QColor("#E5E7EB")


class LightTrailCard(RoundedCard):
    """``RoundedCard`` + 流体曳光描边 + 反射扫光。

    用法与 ``RoundedCard`` 完全一致（radius / fill / border 等），只是在
    paintEvent 里追加可关闭的流光动画。动画只在卡片可见时跑（show/hide
    驱动 QTimer），切到后台自动停表，省 CPU。
    """

    def __init__(self, radius: int = 12, parent=None, fill=None,
                 border_color=None, border_width: int = 1,
                 accent_border: int = 0, *, trail: bool = True,
                 reflect: bool = True, strength: float = 1.0,
                 speed: float = 1.0):
        super().__init__(radius=radius, parent=parent, fill=fill,
                         border_color=border_color, border_width=border_width,
                         accent_border=accent_border)
        self._trail = bool(trail)
        self._reflect = bool(reflect)
        # round-50 视觉整洁：列表/商店卡用低强度+慢速流光，避免满屏奔跑高亮
        self._strength = max(0.0, min(1.0, float(strength)))
        self._speed = max(0.1, float(speed))
        self._angle = 0.0      # 曳光位置（度）
        self._sweep = -0.6     # 反射光带偏移

    # -- lifecycle -----------------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        if EFFECTS_ENABLED and (self._trail or self._reflect):
            _ACTIVE_CARDS.add(self)
            _ensure_master()

    def hideEvent(self, e):
        super().hideEvent(e)
        _ACTIVE_CARDS.discard(self)
        if not _ACTIVE_CARDS:
            _stop_master()

    def destroy(self, *a, **k):
        _ACTIVE_CARDS.discard(self)
        super().destroy(*a, **k)

    def _advance(self):
        self._angle = (self._angle + 2.4 * self._speed) % 360
        self._sweep += 0.014 * self._speed
        if self._sweep > 1.6:
            self._sweep = -0.6
        self.update()

    # -- painting ------------------------------------------------------
    def paintEvent(self, e):
        # 效果关闭 → 走普通 RoundedCard 绘制。
        if not EFFECTS_ENABLED or not (self._trail or self._reflect):
            return super().paintEvent(e)
        try:
            self._paint_liquid(e)
        except Exception:  # noqa: BLE001 - 效果绘制失败绝不崩 UI
            try:
                super().paintEvent(e)
            except Exception:  # noqa: BLE001
                pass

    def _paint_liquid(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)

        # 1) 表面填充（与 RoundedCard 一致）
        fill = self._fill
        if fill is None:
            brush = _card_fill()
        elif isinstance(fill, str):
            brush = QColor(fill)
        else:
            brush = fill
        p.fillPath(path, brush)

        # 2) 反射扫光（软光带横扫表面）
        if self._reflect:
            w, h = self.width(), self.height()
            lg = QLinearGradient(0, 0, w, h)
            base = QColor(255, 255, 255, 0)
            hi = QColor(255, 255, 255, int(46 * self._strength))
            pos = max(0.0, min(1.0, self._sweep))
            lg.setColorAt(max(0.0, pos - 0.18), base)
            lg.setColorAt(pos, hi)
            lg.setColorAt(min(1.0, pos + 0.18), base)
            p.fillPath(path, lg)

        # 3) 流体曳光描边（亮段沿边框顺时针流动）
        accent = _accent()
        if self._trail:
            cg = QConicalGradient()
            center = QPointF(self.width() / 2.0, self.height() / 2.0)
            cg.setCenter(center)
            cg.setAngle(0)
            pseg = (self._angle / 360.0) % 1.0
            seg_half = 0.10
            steps = 32
            for i in range(steps + 1):
                t = i / steps
                d = abs(t - pseg)
                d = min(d, 1.0 - d)  # 圆环距离
                if d < seg_half:
                    a = 1.0 - d / seg_half
                else:
                    a = 0.0
                c = QColor(accent)
                c.setAlphaF((0.18 + 0.82 * a) * self._strength)
                cg.setColorAt(t, c)
            stripe = QColor(accent)
            stripe.setAlphaF(0.10 * self._strength)
            cg.setColorAt(0, stripe)
            cg.setColorAt(1, stripe)
            p.setPen(QPen(cg, 2.0))
            p.drawPath(path)

        # 4) 左侧 accent 条（RoundedCard 原有能力）
        if getattr(self, "_accent_border", 0) > 0:
            stripe_path = QPainterPath()
            stripe_path.addRoundedRect(
                QRectF(self.rect().left(), self.rect().top(),
                       self._accent_border, self.rect().height()), 2, 2)
            stripe_path = stripe_path.intersected(path)
            p.fillPath(stripe_path, accent)

        # 5) 边框（选中/自定义色时）
        bc = self._border_color if self._border_color is not None else _border()
        bw = self._border_width
        if self._fill is None or bw > 1 or self._border_color is not None:
            p.setPen(QPen(QColor(bc), bw))
            p.drawPath(path)
        p.end()


def set_window_opacity(win, opacity: float) -> bool:
    """全局透明 / 透底：设置顶级窗口整体透明度（0.5..1.0）。

    返回是否成功应用。1.0 = 不透。透明窗口在无桌面合成器（老系统）上无
    效果，这里静默返回 False，不抛错。"""
    try:
        if win is None:
            return False
        opacity = float(opacity)
        opacity = max(0.5, min(1.0, opacity))
        win.setWindowOpacity(opacity)
        return True
    except Exception:  # noqa: BLE001
        return False


def fade_page_transition(stack, index: int) -> None:
    """页面切换淡入（启动器动画）。一次性 QGraphicsOpacityEffect，动画结束
    必清 effect → 不会残留"双页"重影（round-49 修复旧版：持久 effect 在
    modal 弹窗打断时被孤立，页面停在半透明叠加在自身之上）。

    round-100 动画打磨：新页同时轻量上浮 8px 汇入（克制——只动子页局部，
    与淡入同拍）；上浮前强制同步布局拿到真实落点，动画结束再归位一次，
    连续切换/中途打断都不会累积偏移。

    调用方（main_window._switch_stack）按配置 ``page_transition`` 决定是否
    调用本函数；动画失败 → 直接瞬时切换（不崩、不卡）。

    round-103：不再受 ``EFFECTS_ENABLED``（流光装饰总开关）牵连——页面切换
    动画有自己的配置 ``page_transition``（默认开）。此前本函数在流光关闭时
    直接跳转，导致「页面切换动画」开关形同虚设。"""
    if stack is None:
        return
    from PySide6.QtCore import QPropertyAnimation, QEasingCurve
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    try:
        # 清掉上一次被打断可能残留的 effect
        stack.setGraphicsEffect(None)
        eff = QGraphicsOpacityEffect(stack)
        eff.setOpacity(0.0)
        stack.setGraphicsEffect(eff)
        stack.setCurrentIndex(index)
        anim = QPropertyAnimation(eff, b"opacity", stack)
        anim.setDuration(160)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _done():
            # 无论正常结束还是被打断后恢复，都移除 effect，杜绝重影
            try:
                stack.setGraphicsEffect(None)
                eff.deleteLater()
            except Exception:  # noqa: BLE001
                pass

        anim.finished.connect(_done)
        anim.start()
        # 持有引用防 GC；下次切换会重新 setGraphicsEffect，旧的 finished 仍
        # 会触发 _done 清掉自身，不会互相干扰。
        stack._fade_anim = anim

        # 新页上浮（round-100）：先同步布局取真实落点，再从 +8px 滑回。
        page = stack.widget(index)
        if page is not None:
            try:
                stack.layout().activate()
            except Exception:  # noqa: BLE001
                pass
            end_pos = page.pos()
            page.move(end_pos.x(), end_pos.y() + 8)
            rise = QPropertyAnimation(page, b"pos", stack)
            rise.setDuration(180)
            rise.setStartValue(page.pos())
            rise.setEndValue(end_pos)
            rise.setEasingCurve(QEasingCurve.OutCubic)

            def _rise_done(_p=page, _pos=end_pos):
                try:
                    _p.move(_pos)  # 归位：抵消动画被中途打断的残留偏移
                except Exception:  # noqa: BLE001
                    pass

            rise.finished.connect(_rise_done)
            rise.start()
            stack._rise_anim = rise
    except Exception:  # noqa: BLE001
        try:
            stack.setGraphicsEffect(None)
            stack.setCurrentIndex(index)
        except Exception:  # noqa: BLE001
            pass


def fade_in_widget(w, duration: int = 170) -> None:
    """列表/容器重建后的轻量淡入（round-100 动画打磨，克制）。

    一次性 QGraphicsOpacityEffect——动画结束必清 effect（同
    fade_page_transition 的防重影策略）；重复触发先清旧 effect。
    失败或效果总开关关闭 → 静默跳过（纯装饰，不参与功能）。"""
    if w is None or not EFFECTS_ENABLED:
        return
    from PySide6.QtCore import QPropertyAnimation, QEasingCurve
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    try:
        w.setGraphicsEffect(None)
        eff = QGraphicsOpacityEffect(w)
        eff.setOpacity(0.0)
        w.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", w)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _done():
            try:
                w.setGraphicsEffect(None)
                eff.deleteLater()
            except Exception:  # noqa: BLE001
                pass

        anim.finished.connect(_done)
        anim.start()
        w._fade_in_anim = anim  # 持有引用防 GC
    except Exception:  # noqa: BLE001
        try:
            w.setGraphicsEffect(None)
        except Exception:  # noqa: BLE001
            pass