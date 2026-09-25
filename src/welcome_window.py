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
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QImage

from .fonts import load_mc_font_family
from .theme import COLORS, get_theme_mode

_FONT_CANDIDATES = ("Segoe UI Light", "Segoe UI", "Helvetica Neue", "Arial")

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
        # 半透明 accent（dark 模式下偏白）；light 下用 accent_text()，
        # 避免用户把主题色设为浅色后在白底上看不清描边字（round-91）。
        if dark:
            self._text_color = QColor("#A78BFA")  # 浅紫
        else:
            from .ui_kit import accent_text
            self._text_color = QColor(accent_text())

        # 状态
        self._finished_emitted = False
        self._fatal = ""
        # 描边动画进度（QPropertyAnimation 驱动）
        self.__draw_progress = 0.0

        # 找字体：MC 像素字体优先（round-94 起走共享查找：data/fonts → 随包
        # assets/fonts → 系统已装 "minecraft" family），失败回退系统字体。
        self._mc_font_family = load_mc_font_family()
        try:
            from PySide6.QtGui import QFontDatabase
        except Exception:
            QFontDatabase = None
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

    def _ink_bbox(img: QImage):
        """返回 img 中非透明像素的包围盒 QRect；全透明返回空矩形。"""
        w, h = img.width(), img.height()
        min_x, min_y, max_x, max_y = w, h, -1, -1
        for y in range(h):
            row_has = False
            for x in range(w):
                if img.pixel(x, y) & 0xFF000000:
                    row_has = True
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x
            if row_has:
                if y < min_y:
                    min_y = y
                max_y = y
        if max_x < 0:
            from PySide6.QtCore import QRect
            return QRect()
        from PySide6.QtCore import QRect
        return QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)

    def _render_ac_pixmap(self):
        """预渲染 "AC" 为透明 pixmap，返回裁到墨迹的图。

        round-93 修复「logo 字母粘连/偏移」：Minecraft AE 是**位图字体**，
        `setPixelSize(96)` 后 QFontMetrics 与实际渲染严重脱节——实测 metrics
        报 `horizontalAdvance("AC") == 18`，而字形实际渲染约 90px 宽。
        `drawText` 按 advance 逐字符排布 → A、C 完全重叠粘连，且按 metrics
        宽度居中整体错位。负字距（round-78 的 -14）在失真度量上更是雪上加霜。

        修法：把 A、C 各自渲染到离屏图 → 逐像素测**实际墨迹**包围盒 →
        按墨迹宽度手动排布拼接，彻底绕开失真的字体度量。
        """
        family = self._mc_font_family or self._font_family
        # 防 tofu：family 可能是空串（offscreen / 极简系统下 defaultFamily() 返回 ""），
        # QFont("") 会渲染出缺字形方框；空串时用 QFont() 默认构造。
        font = QFont(family) if family else QFont()
        font.setPixelSize(max(24, int(_MC_FONT_PIXEL)))

        CELL_W, CELL_H = 320, 240
        GAP = 14  # 字符间视觉间距（墨迹到墨迹）
        pieces = []
        for ch in "AC":
            cell = QPixmap(CELL_W, CELL_H)
            cell.fill(Qt.GlobalColor.transparent)
            cp = QPainter(cell)
            cp.setFont(font)
            cp.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)  # 像素字保持硬边
            cp.drawText(40, 180, ch)
            cp.end()
            bbox = WelcomeWindow._ink_bbox(cell.toImage())
            if not bbox.isEmpty():
                pieces.append(cell.copy(bbox))

        total_w = sum(p.width() for p in pieces) + GAP * (len(pieces) - 1)
        total_h = max(p.height() for p in pieces) if pieces else 1
        out = QPixmap(total_w, total_h)
        out.fill(Qt.GlobalColor.transparent)
        op = QPainter(out)
        x = 0
        for p in pieces:
            op.drawPixmap(x, total_h - p.height(), p)  # 底边对齐
            x += p.width() + GAP
        op.end()
        return out

    def paintEvent(self, e):
        # 透明背景——绘制预渲染好的 "AC" 墨迹图（居中），透明度/缩放随进度浮现
        p = QPainter(self)
        prog = max(0.0, min(1.0, getattr(self, "draw_progress", 1.0)))

        pm = getattr(self, "_ac_pm", None)
        if pm is None or pm.isNull():
            try:
                self._ac_pm = self._render_ac_pixmap()
                pm = self._ac_pm
            except Exception:  # noqa: BLE001 - 预渲染失败兜底为纯文本
                pm = None
        if pm is None or pm.isNull():
            family = self._mc_font_family or self._font_family
            font = QFont(family) if family else QFont()
            font.setPixelSize(max(24, int(_MC_FONT_PIXEL)))
            p.setFont(font)
            p.setPen(QColor(self._text_color))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "AC")
            p.end()
            return

        # 按墨迹图实际尺寸居中；浮现 = 透明度 0.51→1.0 + 轻微放大 0.94→1.0
        scale = 0.94 + 0.06 * prog
        col = QColor(self._text_color)
        col.setAlpha(int(130 + 125 * prog))
        p.save()
        p.translate(self.rect().center())
        p.scale(scale, scale)
        p.setOpacity(col.alphaF())
        # 用 tint 上色：预渲染是白色墨迹，这里乘主题色（SourceIn 语义）
        tinted = QPixmap(pm)
        tp = QPainter(tinted)
        tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        tp.fillRect(tinted.rect(), col)
        tp.end()
        p.drawPixmap(int(-pm.width() / 2), int(-pm.height() / 2), tinted)
        p.restore()
        p.end()

    # ---------- 鼠标（点击任意位置立即跳过）----------
    def mousePressEvent(self, e):
        # round-28 用户反馈：欢迎页停留时间足够看到 AC，但允许点击立即跳过。
        if not self._finished_emitted:
            self._fade_out_and_close()