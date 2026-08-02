"""
SplashWindow — AC Launcher signature boot animation.

Geometric glow style: an AC wordmark scales + fades in over a slowly
rotating diamond halo, the tagline types itself in, and a thin progress bar
fills.

Pure-Qt, no external assets (the logo lives in assets/icons/logo.svg).
Played before MainWindow shows; MainWindow calls mark_ready() when built.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QElapsedTimer
from PySide6.QtGui import (
    QPainter, QColor, QPen, QRadialGradient, QFont,
    QPainterPath, QLinearGradient,
)

from .brand import APP_DISPLAY
from .icons import icon
from .theme import COLORS

_TAGLINE = f"Welcome to {APP_DISPLAY}!"

_TOTAL = 1.6  # seconds for the full intro sequence


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

        self._logo = icon("logo").pixmap(132, 132)
        self._angle = 0.0
        self._phase = 0.0
        self._ready = False
        self._ready_elapsed = 0.0
        self._closing = False

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
        self._watchdog.start(12000)

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
        self._angle = (elapsed * 68.0) % 360.0
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

    # ---------- painting ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        pad = 18
        # base dark panel
        base = QPainterPath()
        base.addRoundedRect(pad, pad, w - 2 * pad, h - 2 * pad, 22, 22)
        pg = QLinearGradient(0, pad, 0, h - pad)
        pg.setColorAt(0, QColor("#12131C"))
        pg.setColorAt(1, QColor("#0B0C14"))
        p.fillPath(base, pg)
        # subtle accent edge
        p.setPen(QPen(QColor(COLORS["accent"]).darker(120), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(base)

        cx, cy = w // 2, int(h * 0.40)

        # rotating diamond halo behind the logo
        self._draw_halo(p, cx, cy, 86)

        # logo wordmark
        ls = _smooth(min(1.0, self._phase / 0.42))
        scale = 0.62 + 0.38 * ls
        op = _smooth(min(1.0, self._phase / 0.45))
        if not self._logo.isNull():
            size = int(self._logo.width() * scale)
            p.save()
            p.setOpacity(op)
            p.drawPixmap(cx - size // 2, cy - size // 2, size, size, self._logo)
            p.restore()

        # tagline (typewriter) — well below the halo
        tline = _smooth((self._phase - 0.32) / 0.5)
        n = int(tline * len(_TAGLINE))
        if n > 0:
            p.save()
            p.setOpacity(min(1.0, tline * 1.4))
            p.setPen(QColor("#C7CBD6"))
            f = QFont("Segoe UI", 13)
            f.setWeight(QFont.Weight.Medium)
            p.setFont(f)
            # centered horizontally; baseline below the logo+halo area
            p.drawText(QRectF(cx - 160, cy + 96, 320, 30),
                       Qt.AlignCenter, _TAGLINE[:n])
            p.restore()

        # progress bar + status — must reach exactly 100% at phase == 1.0
        # (old divisor 1.15 capped the bar at ~80% and looked like a bail-out)
        prog = _smooth((self._phase - 0.12) / 0.88)
        bar_w = w - 2 * (pad + 26)
        bar_x = pad + 26
        bar_y = h - pad - 34
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#23252F"))
        p.drawRoundedRect(bar_x, bar_y, bar_w, 4, 2, 2)
        acc = QColor(COLORS["accent"])
        p.setBrush(acc)
        p.drawRoundedRect(bar_x, bar_y, int(bar_w * prog), 4, 2, 2)

        # status text
        p.setPen(QColor("#7C8290"))
        sf = QFont("Microsoft YaHei", 11)
        sf.setWeight(QFont.Weight.Normal)
        p.setFont(sf)
        p.drawText(bar_x, bar_y + 22, "Loading…")

        p.end()

    def _draw_halo(self, p, cx, cy, r):
        p.save()
        p.translate(cx, cy)
        p.rotate(self._angle)
        # soft radial glow
        glow = QRadialGradient(0, 0, r * 1.5)
        ga = QColor(COLORS["accent"])
        glow.setColorAt(0, ga)
        mid = QColor(COLORS["accent"]); mid.setAlpha(110)
        glow.setColorAt(0.45, mid)
        edge = QColor(COLORS["accent"]); edge.setAlpha(0)
        glow.setColorAt(1, edge)
        p.setBrush(glow)
        p.setPen(Qt.NoPen)
        p.drawEllipse(-r * 1.5, -r * 1.5, r * 3, r * 3)
        # rotating diamond
        pen = QPen(QColor(COLORS["accent"]).lighter(130), 2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        d = r * 0.78
        p.drawPolygon([
            QPointF(0, -d), QPointF(d * 0.7, 0),
            QPointF(0, d), QPointF(-d * 0.7, 0),
        ])
        p.rotate(45)
        faint = QColor(COLORS["accent"]); faint.setAlpha(90)
        p.setPen(QPen(faint, 1))
        p.drawPolygon([
            QPointF(0, -d * 0.6), QPointF(d * 0.42, 0),
            QPointF(0, d * 0.6), QPointF(-d * 0.42, 0),
        ])
        p.restore()
