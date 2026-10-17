"""
WelcomeWindow — AC Launcher 极简启动页。

设计（用户 2026-08-13 反馈）：
- 只显示 AC 两个字母 → 之后直接进入 onboarding/主窗口流程
- 不要背景（透明画布）
- 不需要"开始"按钮，不需要用户点击

round-103：logo 不再依赖 MC 像素字体（字体不随包、发布环境 100% 走 fallback）。
改用 `brand.py` 的手绘矢量 monogram（填充笔锋路径，零外部资源）；出现动画
也改为「手写显现」——笔画按手绘顺序逐段画出，而不是描边/缩放。

流程：welcome 出现 → 3.5s 后淡出 → close → finished 信号 → main.py 直接走
onboarding 或主窗口（已有逻辑，不改 main.py）。
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor

from . import brand
from .theme import COLORS, get_theme_mode


class WelcomeWindow(QWidget):
    """极简启动页：只画 AC 两个字母，透明背景，自动淡出关闭。

    error_msg 非空表示启动失败。
    """

    finished = Signal(str)

    # QPropertyAnimation 驱动：手写进度 0→1（setter 触发重绘）
    from PySide6.QtCore import Property as _Prop

    @_Prop(float)
    def draw_progress(self):
        return self.__draw_progress

    @draw_progress.setter
    def draw_progress(self, v: float):
        self.__draw_progress = v
        self.update()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen
        )
        # 透明背景：画布完全透出桌面，只画 AC 字母
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(320, 200)
        self._center_on_screen()

        # 主题感知：仅决定文字颜色
        dark = get_theme_mode() == "dark"
        # round-100：颜色全部走主题 token——dark 用 text_accent（随自定义
        # accent 联动提亮，不再硬编码浅紫）；light 下用 accent_text()，
        # 避免用户把主题色设为浅色后在白底上看不清（round-91）。
        if dark:
            self._text_color = QColor(COLORS.get("text_accent", "#8B5CF6"))
        else:
            from .ui_kit import accent_text
            self._text_color = QColor(accent_text())

        # 状态
        self._finished_emitted = False
        self._fatal = ""
        # 手写动画进度（QPropertyAnimation 驱动）
        self.__draw_progress = 0.0

        # round-103：手写显现 = 进度 0→1 驱动笔画逐段画出（1100ms）。
        self._anim = QPropertyAnimation(self, b"draw_progress", self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1100)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.start()

        # 简单淡入（0.4s 到 1.0）
        self.setWindowOpacity(0.0)
        QTimer.singleShot(40, lambda: self._fade_in())

        # 动画完成后停留，再淡出（总时长 ≈ 1100ms 手写 + 停留）
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self._fade_out_and_close)
        self._auto_close_timer.start(3500)

        # 15s 看门狗（防卡住；round-34 从 6s 放宽——慢机 MainWindow 构造
        # 可能 >6s，之前会误报"启动超时"弹错退出）
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_watchdog)
        self._watchdog.start(15000)

    # ---------- 定位 ----------
    def _center_on_screen(self):
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is None:
            return
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + (screen.height() - self.height()) // 2
        self.move(x, y)

    # ---------- 淡入 / 淡出 ----------
    def _fade_in(self):
        for i, v in enumerate([0.4, 0.7, 1.0]):
            QTimer.singleShot(i * 140, lambda v=v: self.setWindowOpacity(v))

    def _fade_out_and_close(self):
        for i, v in enumerate([0.7, 0.4, 0.0]):
            QTimer.singleShot(i * 70, lambda v=v: self.setWindowOpacity(v))
        QTimer.singleShot(240, self._finish_close)

    # ---------- 启动信号 ----------
    def _on_watchdog(self):
        if not self._finished_emitted:
            self._fatal = "启动超时：主窗口初始化超过 15 秒未完成。"
            self._finish_close(self._fatal)

    def _finish_close(self, error_msg: str = "") -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        try:
            self._auto_close_timer.stop()
            self._watchdog.stop()
        except Exception:
            pass
        self.close()
        self.finished.emit(error_msg)

    # ---------- 绘制 ----------
    def paintEvent(self, e):
        # 透明背景——绘制手绘矢量 "AC"：整组以窗口中心居中，"A" 先写出，
        # "C" 随后（两段进度轻微重叠，整体如一笔贯通的手写）。
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        prog = max(0.0, min(1.0, getattr(self, "draw_progress", 1.0)))

        height, _total, cells = brand.monogram_layout(12.0)
        target_h = min(self.height() * 0.52, 130.0)
        scale = target_h / height

        p.translate(self.rect().center())
        p.scale(scale, scale)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._text_color))
        # 浮现 = 透明度 0.45→1.0（与笔画显现同步）
        p.setOpacity(0.45 + 0.55 * prog)

        reveals = (
            ("A", min(1.0, prog / 0.55)),
            ("C", max(0.0, (prog - 0.45) / 0.55)),
        )
        for letter, rv in reveals:
            if rv <= 0.0:
                continue
            ax, ay, bcx, bcy = cells[letter]
            p.save()
            p.translate(ax - bcx, ay - bcy)
            brand.draw_letter(p, letter, rv)
            p.restore()

        p.setOpacity(1.0)
        p.end()

    # ---------- 鼠标（点击任意位置立即跳过）----------
    def mousePressEvent(self, e):
        # round-28 用户反馈：欢迎页停留时间足够看到 AC，但允许点击立即跳过。
        if not self._finished_emitted:
            self._fade_out_and_close()
