"""
SplashWindow — AC Launcher signature boot animation.

AC-letter intro: the two brand letters "A" and "C" draw themselves in
(staggered scale + fade + glow) over a slowly rotating diamond halo, the
tagline types itself in, and a thin progress bar fills.

Pure-Qt, no external assets — the letters are vector paths, so they stay
crisp at any DPI and never depend on a logo file existing.

Played before MainWindow shows; MainWindow calls mark_ready() when built.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QElapsedTimer
from PySide6.QtGui import (
    QPainter, QColor, QPen, QRadialGradient, QFont,
)

from .brand import APP_DISPLAY, APP_TAGLINE
from .theme import COLORS

_TAGLINE = APP_TAGLINE or f"Welcome to {APP_DISPLAY}!"

_TOTAL = 1.6  # seconds for the full intro sequence

# MC 像素字体（用户字体目录，round-62/63）：优先加载，真正打出 MC 风味的 "AC"。
# 全部缺失时回退矢量描边字母（_draw_letter_A/_draw_letter_C），保证 logo 永不消失。
_MC_FONT_PATHS = (
    r"<本地字体目录>\[苦力怕论坛]Minecraft(同时支持中英文).ttf",
)
# AC 字母渲染字号（MC 像素字为等宽方块字，给足大号）
_MC_FONT_PIXEL = 96


def _load_mc_font_family() -> str | None:
    """加载 MC 像素字体，返回 family 名；失败返回 None（调用方回退矢量）。"""
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:  # noqa: BLE001 - 字体加载失败绝不阻塞启动
        return None
    for path in _MC_FONT_PATHS:
        try:
            fid = QFontDatabase.addApplicationFont(path)
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    return fams[0]
        except Exception:  # noqa: BLE001
            continue
    return None


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


class SplashWindow(QWidget):
    # Emitted the instant the intro is done (or a fatal error occurs) and just
    # before the window hides, so the caller can reveal the main window exactly
    # when the splash leaves. Carries an error message — "" means success, a
    # non-empty string means startup failed (construction exception / timeout).
    finished = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(480, 320)
        self._center_on_screen()

        self._phase = 0.0
        self._ready = False
        self._ready_elapsed = 0.0
        self._closing = False

        # round-63：MC 像素字体（用户指定），失败回退矢量描边字母。
        self._mc_font_family = _load_mc_font_family()

        # Wall-clock starts at mark_ready() — NOT at splash.show(). The main
        # window is constructed while the splash plays and would otherwise eat
        # the first ~30% of the animation (Phase was up to ~1.0 before the
        # logo even fully appeared).
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30fps — enough for smooth animation, less CPU
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        # Watchdog: if the main window never signals ready (e.g. an exception or
        # a hang inside MainWindow.__init__), do NOT leave the user stuck on the
        # splash forever with no feedback. Emit a failure so the app can show a
        # message and quit instead of freezing on the boot screen.
        self._finished_emitted = False
        self._fatal = ""
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_watchdog)
        # round-63 对齐 WelcomeWindow 的 15s：慢机首次启动 MainWindow 构造
        # 可能 >12s，之前会误报"启动超时"（round-34 曾从 6s 放宽到 15s）。
        self._watchdog.start(15000)

    # ---------- positioning ----------
    def _center_on_screen(self):
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is None:
            return
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + (screen.height() - self.height()) // 2
        self.move(x, y)

    # ---------- animation driver ----------
    def _tick(self):
        # Logo spin runs from the very first frame (wall clock) so the splash
        # never looks frozen while MainWindow constructs. The progress bar /
        # phase only advances AFTER mark_ready() — otherwise the 1-2 s of
        # construction eats the animation and it "jumps" from 0 to 100%.
        elapsed = self._clock.elapsed() / 1000.0
        if self._ready:
            self._phase = min(1.0, max(0.0, elapsed - self._ready_elapsed) / _TOTAL)
        else:
            self._phase = 0.0
        self.update()
        # Only close once the intro has FULLY played (phase == 1.0).
        if self._ready and self._phase >= 1.0 and not self._closing:
            self._closing = True
            self.repaint()
            QTimer.singleShot(180, self._finish_close)

    def _on_watchdog(self):
        """Fired if the main window never became ready in time."""
        if not self._ready and not self._finished_emitted:
            self._fatal = (
                "启动超时：主窗口初始化超过 12 秒未完成，"
                "可能被某个页面构造阻塞或抛出了异常。请查看日志后重试。"
            )
            self._finish_close(self._fatal)

    def mark_ready(self):
        """Called by MainWindow once it has finished constructing.

        Records the wall-clock moment so the 1.6 s intro (progress phase)
        runs to completion AFTER construction — while the logo keeps spinning
        the whole time, never a frozen frame.
        """
        self._ready = True
        self._ready_elapsed = self._clock.elapsed() / 1000.0

    def _finish_close(self, error_msg: str = "") -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self._timer.stop()
        self._watchdog.stop()
        # Drop the splash FIRST, then reveal the next screen. This guarantees
        # the (now transparent) splash window is fully gone before the
        # onboarding dialog appears, so it can never sit on top and swallow
        # the dialog's input. Using a plain close() (no opacity animation)
        # avoids the Windows bug where the SplashScreen opacity-animation
        # finished signal never fires and leaves the splash stuck forever.
        self.setWindowOpacity(0.0)
        self.close()
        self.finished.emit(error_msg)

    def mousePressEvent(self, e):
        # round-63：点击立即跳过剩余动画（仅在主窗口就绪后生效，避免与
        # boot() 的窗口构造争用；欢迎页历史设计即支持点击跳过）。
        if self._ready and not self._closing and not self._finished_emitted:
            self._closing = True
            self.repaint()
            QTimer.singleShot(120, self._finish_close)

    # ---------- painting ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        pad = 18
        # round-65 精简：透明背景上不再绘制深色面板/旋转光晕/标语/状态文字，
        # 只保留干净的 AC 字母交错动画 + 底部进度条（用户要求去掉 logo 页背景和文字）。

        cx, cy = w // 2, int(h * 0.40)
        accent = QColor(COLORS["accent"])

        # --- AC monogram: two letters draw themselves in, staggered ---
        # A leads, C follows ~0.23s later. Each scales 0.6 -> 1.0, fades in,
        # and rises slightly as it appears.
        a_l = _smooth((self._phase - 0.05) / 0.40)
        c_l = _smooth((self._phase - 0.28) / 0.42)

        if self._mc_font_family:
            # round-63：MC 像素字体真实打出 "AC"（用户指定），保留交错动画。
            # round-79b：MC 像素字是等宽方块——A/C 字形各 60px，原 A 起点 cx-80 /
            # C 起点 cx+70 让中间空了 90px（"隔太远"）。改为 A 起点 cx-62、C 从
            # A 右缘后 4px 接上，整组以 cx 居中，凑成贴合 logo 的 "AC"。
            self._draw_text_letter(
                p, "A", cx - 62, cy + (1 - a_l) * 14, 0.6 + 0.4 * a_l, a_l, accent)
            self._draw_text_letter(
                p, "C", cx + 2, cy + (1 - c_l) * 14, 0.6 + 0.4 * c_l, c_l, accent)
        else:
            # 字体缺失回退矢量描边字母——logo 永远看得见。
            self._draw_letter_A(p, cx - 58, cy + (1 - a_l) * 14, 0.6 + 0.4 * a_l, a_l, accent)
            self._draw_letter_C(p, cx + 58, cy + (1 - c_l) * 14, 0.6 + 0.4 * c_l, c_l, accent)

        # progress bar — must reach exactly 100% at phase == 1.0
        prog = _smooth((self._phase - 0.12) / 0.88)
        bar_w = w - 2 * (pad + 26)
        bar_x = pad + 26
        bar_y = h - pad - 34
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#23252F"))
        p.drawRoundedRect(bar_x, bar_y, bar_w, 4, 2, 2)
        p.setBrush(accent)
        p.drawRoundedRect(bar_x, bar_y, int(bar_w * prog), 4, 2, 2)

        p.end()

    # ---------- letter glyphs (vector, no assets) ----------
    def _draw_text_letter(self, p, ch, cx, cy, s, op, accent):
        """用 MC 像素字体画单个字母（round-63），保持与矢量版一致的交错动画。"""
        if op <= 0.01:
            return
        self._glow(p, cx, cy, 70 * s, op, accent)
        p.save()
        p.translate(cx, cy)
        p.scale(s, s)
        p.setOpacity(op)
        f = QFont(self._mc_font_family)
        f.setPixelSize(max(24, int(_MC_FONT_PIXEL)))
        p.setFont(f)
        fm = p.fontMetrics()
        # 垂直居中：基线 y = (ascent - descent) / 2
        x = int(-fm.horizontalAdvance(ch) / 2.0)
        y = int((fm.ascent() - fm.descent()) / 2.0)
        p.setPen(accent)
        p.drawText(x, y, ch)
        p.restore()

    def _glow(self, p, cx, cy, r, op, accent):
        """Soft radial glow behind a letter, scaled by the letter's opacity."""
        if op <= 0.01:
            return
        g = QRadialGradient(cx, cy, r)
        a = QColor(accent)
        a.setAlpha(int(120 * op))
        g.setColorAt(0, a)
        edge = QColor(accent)
        edge.setAlpha(0)
        g.setColorAt(1, edge)
        p.save()
        p.setOpacity(1.0)
        p.setBrush(g)
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
        p.restore()

    def _draw_letter_A(self, p, cx, cy, s, op, accent):
        if op <= 0.01:
            return
        self._glow(p, cx, cy, 70 * s, op, accent)
        p.save()
        p.translate(cx, cy)
        p.scale(s, s)
        p.setOpacity(op)
        pen = QPen(accent, 12, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        H, W = 120.0, 96.0
        # outline: left foot -> apex -> right foot
        p.drawLine(QPointF(-W / 2, H / 2), QPointF(0, -H / 2))
        p.drawLine(QPointF(0, -H / 2), QPointF(W / 2, H / 2))
        # crossbar
        p.drawLine(QPointF(-W * 0.26, H * 0.14), QPointF(W * 0.26, H * 0.14))
        p.restore()

    def _draw_letter_C(self, p, cx, cy, s, op, accent):
        if op <= 0.01:
            return
        self._glow(p, cx, cy, 70 * s, op, accent)
        p.save()
        p.translate(cx, cy)
        p.scale(s, s)
        p.setOpacity(op)
        pen = QPen(accent, 12, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        R = 58.0
        rect = QRectF(-R, -R, 2 * R, 2 * R)
        # Qt arc angles: 0deg at 3 o'clock, positive = counterclockwise.
        # 50deg -> 310deg CCW covers the left side, leaving a gap on the right
        # (a "C" opening to the right).
        p.drawArc(rect, int(50 * 16), int(260 * 16))
        p.restore()
