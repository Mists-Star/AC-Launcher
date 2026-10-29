"""
SplashWindow — AC Launcher signature boot animation.

AC-letter intro: the two brand letters "A" and "C" write themselves in
(staggered stroke reveal + scale + fade + soft glow), and a thin progress bar
fills.

Pure-Qt, no external assets and no font dependency — the letters come from
``brand.py`` as hand-drawn tapered vector paths, so they stay crisp at any DPI
and render identically on every machine (the MC pixel font is no longer used:
fonts are not shipped, so that path always fell back anyway, round-103).

Played before MainWindow shows; MainWindow calls mark_ready() when built.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, Signal, QElapsedTimer, QRect
from PySide6.QtGui import QPainter, QColor, QRadialGradient

from . import brand
from .brand import APP_DISPLAY
from .theme import COLORS

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
        # round-96：单实例守卫靠 FindWindowW 按标题识别在跑的旧实例——即使它
        # 仍停留在 splash（主窗口未建）阶段，同样能被命中，避免双开。
        self.setWindowTitle(APP_DISPLAY)
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

        # round-103：手绘矢量 monogram 的布局（本地单位，随窗口缩放）。
        self._mark_height, self._mark_total, self._cells = brand.monogram_layout(12.0)

        # round-136：品牌自定义 —— 自定义标志图替代矢量 AC 字母，可选背景图。
        # 读不到 / 路径失效时静默回落默认（矢量字母 + 透明背景）。
        from . import brand_custom
        # 标志按 512 上限解码（绘制时缩到 112 高，避免小图被放大取自放大糊），
        # 背景按 960 上限解码（启动页 480×320，cover 铺满足够）。
        self._logo_pm = brand_custom.load_pixmap(brand_custom.custom_logo_path(), 512)
        self._bg_pm = brand_custom.load_pixmap(brand_custom.splash_bg_path(), 960)
        # round-137（round-136 遗留）：蒙版强度按背景平均亮度自适应 ——
        # 亮背景压深（前景可读），暗背景少压（保留图片细节）。
        self._bg_veil = self._estimate_veil(self._bg_pm)

        # Wall-clock starts at mark_ready() — NOT at splash.show(). The main
        # window is constructed while the splash plays and would otherwise eat
        # the first ~30% of the animation.
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
        # Logo reveal runs from the very first frame (wall clock) so the splash
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
                "启动超时：主窗口初始化超过 15 秒未完成，"
                "可能被某个页面构造阻塞或抛出了异常。请查看日志后重试。"
            )
            self._finish_close(self._fatal)

    def mark_ready(self):
        """Called by MainWindow once it has finished constructing.

        Records the wall-clock moment so the 1.6 s intro (progress phase)
        runs to completion AFTER construction — while the logo keeps animating
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = self.width(), self.height()
        pad = 18
        # round-65 精简：透明背景上不再绘制深色面板/旋转光晕/标语/状态文字，
        # 只保留干净的 AC 手绘字母交错动画 + 底部进度条。

        # round-136：自定义背景图（cover 铺满）+ 暗色蒙版（保证前景可读）。
        if self._bg_pm is not None and not self._bg_pm.isNull():
            p.drawPixmap(self._cover_rect(self._bg_pm, w, h), self._bg_pm)
            veil = QColor(0, 0, 0, self._bg_veil)
            p.fillRect(0, 0, w, h, veil)

        cx, cy = w // 2, int(h * 0.40)
        accent = QColor(COLORS["accent"])

        # --- AC monogram: the two letters write themselves in, staggered ---
        # A leads, C follows ~0.23s later. Each stroke-reveals, scales 0.6->1.0,
        # fades in, and rises slightly as it appears.
        a_l = _smooth((self._phase - 0.05) / 0.40)
        c_l = _smooth((self._phase - 0.28) / 0.42)

        target_h = 112.0

        if self._logo_pm is not None and not self._logo_pm.isNull():
            # round-136：用户自定义标志图替代矢量笔画（淡入 + 轻微放大）。
            l = a_l
            if l > 0.01:
                pm = self._logo_pm
                k = pm.height() or 1
                dh = int(target_h * (0.86 + 0.14 * l))
                dw = max(1, int(pm.width() * dh / k))
                x = cx - dw // 2
                y = cy - dh // 2
                p.save()
                p.setOpacity(l)
                p.drawPixmap(QRect(x, y, dw, dh), pm)
                p.restore()
        else:
            s = target_h / self._mark_height

            # soft glow behind each letter (px space)
            for letter, l in (("A", a_l), ("C", c_l)):
                if l <= 0.01:
                    continue
                ax, ay, _bcx, _bcy = self._cells[letter]
                gx = cx + s * ax
                gy = cy + s * ay + (1 - l) * 14.0
                self._glow(p, gx, gy, 66 * (0.6 + 0.4 * l), l, accent)

            # letters: reveal + per-letter scale + rise, all in the scaled frame
            p.save()
            p.translate(cx, cy)
            p.scale(s, s)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            for letter, l in (("A", a_l), ("C", c_l)):
                if l <= 0.01:
                    continue
                ax, ay, bcx, bcy = self._cells[letter]
                p.save()
                p.setOpacity(l)
                p.translate(ax, ay + (1 - l) * 14.0 / s)
                k = 0.6 + 0.4 * l
                p.scale(k, k)
                p.translate(-bcx, -bcy)
                brand.draw_letter(p, letter, l)
                p.restore()
            p.restore()

        # progress bar — must reach exactly 100% at phase == 1.0
        prog = _smooth((self._phase - 0.12) / 0.88)
        bar_w = w - 2 * (pad + 26)
        bar_x = pad + 26
        bar_y = h - pad - 34
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#23252F"))
        p.drawRoundedRect(bar_x, bar_y, bar_w, 4, 2, 2)
        p.setBrush(accent)
        p.drawRoundedRect(bar_x, bar_y, int(bar_w * prog), 4, 2, 2)

        p.end()

    # ---------- glow ----------
    @staticmethod
    def _estimate_veil(pm) -> int:
        """按背景图平均亮度估算暗色蒙版 alpha（无背景时用默认 120）。

        缩到 32px 取亮度均值（0.299R+0.587G+0.114B），线性映射：
        全黑 → 40（少压，保留细节），全白 → 170（压深，保证前景可读）。
        """
        if pm is None or pm.isNull():
            return 120
        small = pm.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        img = small.toImage()
        total = 0.0
        n = 0
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                total += 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
                n += 1
        if n == 0:
            return 120
        lum = total / n  # 0..255
        return int(max(40, min(170, 40 + lum * 130.0 / 255.0)))

    @staticmethod
    def _cover_rect(pm, w, h):
        """Target rect that fills w×h with pm, keeping aspect (center crop)."""
        pw, ph = pm.width(), pm.height()
        if pw <= 0 or ph <= 0:
            return QRect(0, 0, w, h)
        scale = max(w / pw, h / ph)
        dw, dh = int(pw * scale + 0.5), int(ph * scale + 0.5)
        return QRect((w - dw) // 2, (h - dh) // 2, dw, dh)

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
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
        p.restore()
