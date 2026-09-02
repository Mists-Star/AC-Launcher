"""
WelcomeWindow — AC Launcher 极简启动页（round-28 第三次重做）。

设计（用户 2026-08-13 反馈）：
- 只显示 AC 两个字母（用好看的细体字）→ 之后直接进入 onboarding/主窗口流程
- 不要背景（透明画布）
- 不需要"开始"按钮，不需要用户点击

字体：round-62 用户指定使用 MC 像素字体（<本地字体目录> 下的
[苦力怕论坛]Minecraft(同时支持中英文).ttf），真正打出 MC 风味的"AC"。
字体文件缺失时回退系统字体（Segoe UI Light → Segoe UI → Arial）。
流程：welcome 出现 → 1.6s 淡出 → close → finished 信号 → main.py 直接
走 onboarding 或主窗口（已有逻辑，不改 main.py）。
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QFont

from .theme import COLORS, get_theme_mode

_FONT_CANDIDATES = ("Segoe UI Light", "Segoe UI", "Helvetica Neue", "Arial")

# MC 像素字体（用户字体目录），优先加载；全部缺失才回退 _FONT_CANDIDATES。
_MC_FONT_PATHS = (
    r"<本地字体目录>\[苦力怕论坛]Minecraft(同时支持中英文).ttf",
)
# AC 字母渲染字号（MC 像素字为等宽方块字，给足大号）
_MC_FONT_PIXEL = 96


class WelcomeWindow(QWidget):
    """极简启动页：只画 AC 两个字母，透明背景，自动淡出关闭。

    error_msg 非空表示启动失败。
    """

    finished = Signal(str)

    # QPropertyAnimation 驱动：描边进度 0→1（setter 触发重绘）
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
        # 半透明紫色 accent（dark 模式下偏白）
        if dark:
            self._text_color = QColor("#A78BFA")  # 浅紫
        else:
            self._text_color = QColor(COLORS["accent"])  # #7C3AED

        # 状态
        self._finished_emitted = False
        self._fatal = ""
        # 描边动画进度（QPropertyAnimation 驱动）
        self.__draw_progress = 0.0

        # 找字体：MC 像素字体优先（用户指定，round-62），失败回退系统字体。
        try:
            from PySide6.QtGui import QFontDatabase
        except Exception:
            QFontDatabase = None
        self._mc_font_family = None
        if QFontDatabase is not None:
            for _path in _MC_FONT_PATHS:
                try:
                    _fid = QFontDatabase.addApplicationFont(_path)
                    if _fid >= 0:
                        _fams = QFontDatabase.applicationFontFamilies(_fid)
                        if _fams:
                            self._mc_font_family = _fams[0]
                            break
                except Exception:
                    continue
        avail = set(QFontDatabase.families()) if QFontDatabase is not None else set()
        self._font_family = next((f for f in _FONT_CANDIDATES if f in avail),
                                 QFont().defaultFamily())

        # round-46: QPropertyAnimation(0→1) 驱动出现动画——round-62 改为
        # MC 像素字体的"AC"浮现（透明度 + 轻微放大），不再手工描边路径。
        self._draw_progress = 0.0
        self._anim = QPropertyAnimation(self, b"draw_progress", self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1100)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.finished.connect(self._on_stroke_done)
        self._anim.start()

        # 简单淡入（0.4s 到 1.0）
        self.setWindowOpacity(0.0)
        QTimer.singleShot(40, lambda: self._fade_in())

        # 动画完成后 1.6s 淡出（总时长 ≈ 1100ms 描边 + 停留）
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
    def mark_ready(self):
        """兼容旧调用；新方案中欢迎页不再依赖 mark_ready 决定关闭时机。"""
        pass

    def _on_watchdog(self):
        if not self._finished_emitted:
            self._fatal = "启动超时：主窗口初始化超过 6 秒未完成。"
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
    def _on_stroke_done(self):
        """出现动画完成：刷新一次（保持旧接口兼容）。"""
        self.update()

    def _center_ac_rect(self, p):
        """计算 "AC" 在窗口中居中的绘制信息（(基线点 x, y, 宽, 高)）。"""
        fm = p.fontMetrics()
        w = fm.horizontalAdvance("AC")
        h = fm.ascent() + fm.descent()
        r = self.rect()
        bx = r.center().x() - w // 2
        by = r.center().y() - h // 2 + fm.ascent()
        return bx, by, w, h

    def paintEvent(self, e):
        # 透明背景——用 MC 像素字体画出居中的 "AC"，透明度/缩放随进度浮现
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        prog = max(0.0, min(1.0, getattr(self, "draw_progress", 1.0)))

        family = self._mc_font_family or self._font_family
        font = QFont(family)
        font.setPixelSize(max(24, int(_MC_FONT_PIXEL)))
        p.setFont(font)

        col = QColor(self._text_color)
        col.setAlpha(int(130 + 125 * prog))  # 边现边亮（0.51 → 1.0 alpha）
        p.setPen(col)

        bx, by, w, h = self._center_ac_rect(p)
        # 轻微放大浮现：0.94 → 1.0，围绕文字中心
        scale = 0.94 + 0.06 * prog
        cx, cy = bx + w / 2.0, by - (p.fontMetrics().ascent() - h / 2.0)
        p.save()
        p.translate(cx, cy)
        p.scale(scale, scale)
        p.translate(-cx, -cy)
        p.drawText(bx, by, "AC")
        p.restore()

    # ---------- 鼠标（点击任意位置立即跳过）----------
    def mousePressEvent(self, e):
        # round-28 用户反馈：欢迎页停留时间足够看到 AC，但允许点击立即跳过。
        if not self._finished_emitted:
            self._fade_out_and_close()