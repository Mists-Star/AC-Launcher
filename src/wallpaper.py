"""Wallpaper backdrop for the home page.

Supports four modes, all user-supplied:

  none   — inherit the theme background
  solid  — a flat colour
  image  — any still image (png/jpg/webp/bmp), scaled to cover
  gif    — an animated GIF / animated WebP, played on loop
  video  — an mp4/webm/mkv played on loop, muted (true "dynamic wallpaper")
  version — the *real* Minecraft panorama of the current instance, rendered
            as a slowly rotating cubemap (see ``panorama.py``)

The widget is meant to sit *behind* page content: it paints itself and never
steals mouse events, so buttons on top keep working.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import QWidget, QLabel, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QUrl, QSize, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import (
    QPixmap, QMovie, QPainter, QColor,
    QRadialGradient, QLinearGradient, QBrush, QPen,
)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".jfif")
GIF_EXTS = (".gif", ".webp", ".apng")
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".avi", ".mov", ".wmv")

IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)"
GIF_FILTER = "动图 (*.gif *.webp *.apng);;所有文件 (*.*)"
VIDEO_FILTER = "视频 (*.mp4 *.webm *.mkv *.avi *.mov);;所有文件 (*.*)"
ANY_FILTER = (
    "所有支持的壁纸 (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.apng "
    "*.mp4 *.webm *.mkv *.avi *.mov);;"
    "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;"
    "动图 (*.gif *.webp *.apng);;"
    "视频 (*.mp4 *.webm *.mkv *.avi *.mov);;所有文件 (*.*)"
)

# ── panorama backdrop tuning ────────────────────────────────────────────
# The cubemap is a full-bleed media backdrop, so the few labels that sit
# directly on it (brand line, repair-log line) must stay readable.  A scrim
# keeps the backdrop in the theme's own polarity: the light theme stays
# light (white scrim), the dark theme stays dark (black scrim).
#
# How strong the scrim has to be depends on the artwork -- a bright sunrise
# panorama needs a heavy scrim, the dark cave panorama needs almost none --
# so it is derived from the cubemap's mean luminance instead of being fixed.
PANO_TARGET_LUMA = {"light": 0.55, "dark": 0.44}
# Scrim strength at the bottom of the page, where no text sits: the artwork
# is most visible there.
PANO_SCRIM_FLOOR = {"light": 0.30, "dark": 0.15}
# Fraction of the page height over which the scrim fades to its lower value.
PANO_SCRIM_SPAN = 0.70
# Animation: Minecraft's title panorama turns very slowly; 0.2 deg per tick
# at 20 fps is ~4 deg/s, fast enough to be noticed, slow enough to stay calm.
PANO_FRAME_MS = 50
PANO_YAW_STEP = 0.2
# The cubemap is rendered into a half-resolution buffer and scaled up: the
# art is soft anyway and it halves the per-frame cost.
PANO_BUFFER_DIV = 2


def _mean_luma(images) -> float:
    """Mean perceptual luminance (0..1) of the cubemap faces.

    Sampled at 8x8 per face -- enough to tell "dark cave" from "bright
    sunrise" without touching every pixel of six 1024x1024 textures.
    """
    total = 0.0
    count = 0
    for img in images:
        small = img.scaled(8, 8, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        for y in range(small.height()):
            for x in range(small.width()):
                c = small.pixelColor(x, y)
                total += (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
                count += 1
    return (total / count / 255.0) if count else 0.0


def guess_mode(path: str) -> str:
    """Pick the right wallpaper mode for a file the user just chose."""
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext == ".gif" or ext == ".apng":
        return "gif"
    if ext in IMAGE_EXTS:
        return "image"
    return "image"


# ── built-in version-themed wallpapers (procedural) ──────────────────────
# These are drawn on the fly by draw_version_wallpaper().  They are free of
# watermarks, scale to any resolution, and stay dark enough not to compete
# with foreground UI text.  A future update can swap them for real Duck.ai
# generated art by returning a QPixmap loaded from resources/wallpapers/.
# Wallpaper themes: the base surface is ALWAYS a quiet neutral — only the soft
# accent glow hue varies per Minecraft version. Kept dark/light-theme aware and
# far calmer than the old colorful blocks+particles scene so it never competes
# with the foreground UI (the "Absolute Controller" / 掌控感 aesthetic).
VERSION_THEMES = {
    "trial":     {"glow": "#B87333"},
    "cherry":    {"glow": "#F472B6"},
    "wild":      {"glow": "#34D399"},
    "caves":     {"glow": "#60A5FA"},
    "nether":    {"glow": "#F87171"},
    "end":       {"glow": "#C084FC"},
    "overworld": {"glow": "#4ADE80"},
}


def _theme_for_version(version_id: str | None) -> str:
    """Map a concrete version id (e.g. '1.21.4-fabric') to a theme key."""
    if not version_id:
        return "overworld"
    v = version_id.lower()
    # Strip mod-loader suffixes so that 1.21.4-fabric resolves to trial.
    for loader in ("fabric", "forge", "quilt", "neoforge"):
        if loader in v:
            v = v.split("-")[0]
            break
    if "1.21" in v or "trial" in v:
        return "trial"
    if "1.20" in v or "cherry" in v:
        return "cherry"
    if "1.19" in v or "wild" in v:
        return "wild"
    if "1.18" in v or "1.17" in v or "cave" in v or "cliff" in v:
        return "caves"
    if "1.16" in v or "nether" in v:
        return "nether"
    if "end" in v:
        return "end"
    return "overworld"


def draw_version_wallpaper(version_id: str | None, size: QSize) -> QPixmap | None:
    """Render a deterministic, resolution-independent themed wallpaper.

    The same ``version_id`` always produces the same scene, so the background
    feels stable while still shifting hue between major versions.

    Design (AC "Absolute Controller" / 掌控感):
      - quiet near-black (dark) or lavender-grey (light) base
      - a single soft accent glow whose HUE follows the version
      - a faint grid overlay (control-console feel) instead of noisy blocks
    """
    if not size.isValid() or size.width() < 2 or size.height() < 2:
        return None
    pm = QPixmap(size)
    w, h = size.width(), size.height()
    theme = VERSION_THEMES.get(_theme_for_version(version_id), VERSION_THEMES["overworld"])
    # round-91 光晕主色跟随自定义 accent（内置紫主题下与原先 #7C3AED 一致）
    try:
        from .theme import COLORS
        accent = QColor(COLORS.get("accent", "#7C3AED"))
    except Exception:
        accent = QColor("#7C3AED")

    # Theme-aware surface: dark builds stay near-black, light builds go airy.
    try:
        from .theme import get_theme_mode
        dark = get_theme_mode() == "dark"
    except Exception:
        dark = True
    base_top = QColor("#101018" if dark else "#F7F6FB")
    base_bot = QColor("#060609" if dark else "#ECEAF7")

    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.Antialiasing)

        # 1. base vertical gradient (neutral, quiet)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, base_top)
        bg.setColorAt(1.0, base_bot)
        p.fillRect(pm.rect(), QBrush(bg))

        # 2. single accent glow, top-left → centre; hue from the version
        # With no instance there is no version to follow, so use the brand
        # accent — falling back to "overworld" painted the home page green
        # for no reason.
        glow_hex = theme["glow"] if version_id else accent.name()
        glow = QRadialGradient(QPointF(w * 0.28, h * 0.18), max(w, h) * 0.75)
        glow_color = QColor(glow_hex)
        glow_color.setAlpha(46 if dark else 26)
        # The 0.55 stop used to be the opaque glow colour, which put a solid
        # green/purple band across the wallpaper. Keep it translucent.
        glow_mid = QColor(glow_hex)
        glow_mid.setAlpha(16 if dark else 10)
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(0.55, glow_mid)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawRect(pm.rect())

        # 2b. faint AC accent echo from the bottom-right corner (brand tie-in)
        if dark:
            acc = QColor(accent)
            acc.setAlpha(22)
            echo = QRadialGradient(QPointF(w * 0.88, h * 0.95), max(w, h) * 0.55)
            echo.setColorAt(0.0, acc)
            echo.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(echo))
            p.drawRect(pm.rect())

        # 3. faint control-console grid (keep alpha very low)
        p.setPen(QColor(255, 255, 255, 14) if dark else QColor(90, 70, 160, 16))
        step = 72
        for gx in range(0, w + step, step):
            p.drawLine(gx, 0, gx, h)
        for gy in range(0, h + step, step):
            p.drawLine(0, gy, w, gy)

        # 4. vignette to keep edges dark-ish for UI text readability
        vig = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.72)
        vig.setColorAt(0.0, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 150 if dark else 90))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(vig))
        p.fillRect(pm.rect(), QBrush(vig))
    finally:
        p.end()
    return pm


class WallpaperWidget(QWidget):
    """Backdrop that renders a colour / image / GIF / video / panorama."""

    # Emitted once the real cubemap is on screen, so the page can adapt the
    # labels that sit directly on the backdrop.
    panorama_ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.lower()
        self._mode = "none"
        self._color = QColor("#1E1E1E")
        self._version_id: str | None = None
        self._pixmap: QPixmap | None = None
        self._scaled: QPixmap | None = None  # cache of the size-fit pixmap
        self._scaled_size = QSize(0, 0)
        self._movie: QMovie | None = None
        self._movie_label: QLabel | None = None
        self._video: object | None = None   # QVideoWidget
        self._player: object | None = None  # QMediaPlayer
        self._audio: object | None = None
        self._opacity = 1.0
        self._blur = 0
        # ── panorama state ──
        self._panorama = None          # PanoramaRenderer once the cubemap is in
        self._pano_buffer: QPixmap | None = None
        self._pano_yaw = 0.0
        self._pano_luma = 0.0           # mean luminance of the artwork
        self._pano_timer: QTimer | None = None
        self._pano_key: tuple | None = None

    # ------------------------------------------------------------- config
    def apply(self, cfg: dict, version_id: str | None = None,
              mc_dir: str = "", game_dir: str = "", version: str = "") -> None:
        """Reconfigure from the settings dict.

        ``version_id`` is used by the ``version`` mode to pick a default
        themed wallpaper.  ``mc_dir`` / ``game_dir`` / ``version`` point at
        the current instance so the real Minecraft panorama of that version
        can be loaded.  A player-supplied custom image always wins.
        """
        mode = cfg.get("wallpaper_mode", "none")
        self._opacity = float(cfg.get("wallpaper_opacity", 1.0))
        self._color = QColor(cfg.get("wallpaper_color", "#1E1E1E"))
        path = cfg.get("wallpaper_image", "")
        self._version_id = version_id

        self._teardown_dynamic()
        self._mode = mode
        self._pixmap = None
        self._scaled = None
        # A "version" wallpaper needs something to show. With no instance (and
        # no custom image) there is no version to draw, and the procedural
        # fallback tinted the whole home page with a version hue the player
        # never picked — keep the backdrop hidden instead.
        visible = mode != "none"

        if mode == "image" and path and os.path.exists(path):
            self._stop_panorama()
            pm = QPixmap(path)
            self._pixmap = pm if not pm.isNull() else None
            self._scaled = None  # invalidate scaled cache
        elif mode == "gif" and path and os.path.exists(path):
            self._stop_panorama()
            self._start_gif(path)
        elif mode == "video" and path and os.path.exists(path):
            self._stop_panorama()
            self._start_video(path, float(cfg.get("wallpaper_video_vol", 0.0)))
        elif mode == "version":
            # Player custom wallpaper takes priority over the version theme.
            if path and os.path.exists(path):
                self._stop_panorama()
                pm = QPixmap(path)
                self._pixmap = pm if not pm.isNull() else None
                self._scaled = None
            elif not mc_dir:
                # No instance yet → nothing to draw (see `visible` above).
                self._stop_panorama()
            else:
                # Real cubemap of the instance's own version; the procedural
                # gradient below only fills the gap until the textures are in.
                self._start_panorama(mc_dir, game_dir, version)
                size = self.size()
                if not size.isValid() or size.width() < 2 or size.height() < 2:
                    size = QSize(1920, 1080)
                self._pixmap = draw_version_wallpaper(version_id, size)
                self._scaled = None
        else:
            self._stop_panorama()

        if mode == "version" and not mc_dir and not (
                path and os.path.exists(path)):
            visible = False
        self.setVisible(visible)
        self.update()

    # ------------------------------------------------------------ panorama
    @property
    def panorama_active(self) -> bool:
        """True while the real Minecraft panorama is on screen."""
        return self._panorama is not None

    def _start_panorama(self, mc_dir: str, game_dir: str, version: str) -> None:
        """Load the cubemap of an instance in the background.

        Scanning the asset store and decoding six 1024x1024 textures takes
        long enough to stall the UI thread, so the work happens in a
        ``PanoramaLoader`` thread and the result arrives via a signal.
        """
        if not mc_dir:
            self._stop_panorama()
            return
        key = (mc_dir, game_dir, version)
        if key == self._pano_key:
            return  # already loading or loaded for this instance
        self._stop_panorama()
        self._pano_key = key
        try:
            from .panorama import PanoramaLoader
        except Exception:  # noqa: BLE001 - no panorama support, keep the gradient
            self._pano_key = None
            return
        loader = PanoramaLoader(key, mc_dir, game_dir, version)
        loader.ready.connect(self._on_panorama_ready)
        loader.start()

    def _stop_panorama(self) -> None:
        """Drop the current cubemap and stop the animation.

        A loader that is still running is *not* cancelled -- it cannot be
        cancelled safely -- but its result is ignored, because the key it
        reports no longer matches the current request.
        """
        self._pano_key = None
        self._panorama = None
        self._pano_buffer = None
        if self._pano_timer is not None:
            self._pano_timer.stop()

    def _on_panorama_ready(self, key, images, source) -> None:
        """Slot for ``PanoramaLoader.ready`` (runs on the UI thread)."""
        if key != self._pano_key:
            return  # a newer request superseded this one
        if not images or len(images) != 6:
            return  # nothing found -> keep the procedural gradient
        try:
            from .panorama import PanoramaRenderer
            self._panorama = PanoramaRenderer(images)
        except Exception:  # noqa: BLE001 - a broken cubemap must not kill the page
            self._panorama = None
            return
        self._pano_luma = _mean_luma(images)
        self._pano_buffer = None
        self._pano_yaw = 0.0
        self._start_pano_timer()
        self.panorama_ready.emit()
        self.update()

    def _start_pano_timer(self) -> None:
        if self._pano_timer is None:
            self._pano_timer = QTimer(self)
            self._pano_timer.setInterval(PANO_FRAME_MS)
            self._pano_timer.timeout.connect(self._pano_tick)
        if self.isVisible():
            self._pano_timer.start()

    def _pano_tick(self) -> None:
        self._pano_yaw = (self._pano_yaw + PANO_YAW_STEP) % 360.0
        self.update()

    def _teardown_dynamic(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        if self._movie_label is not None:
            self._movie_label.deleteLater()
            self._movie_label = None
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:  # noqa: BLE001
                pass
            self._player = None
            self._audio = None
        if self._video is not None:
            self._video.deleteLater()
            self._video = None

    # --------------------------------------------------------------- gif
    def _start_gif(self, path: str) -> None:
        lbl = QLabel(self)
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lbl.setScaledContents(True)
        lbl.setGeometry(self.rect())
        movie = QMovie(path)
        if not movie.isValid():
            lbl.deleteLater()
            return
        movie.setCacheMode(QMovie.CacheAll)
        lbl.setMovie(movie)
        movie.start()
        if self._opacity < 1.0:
            eff = QGraphicsOpacityEffect(lbl)
            eff.setOpacity(self._opacity)
            lbl.setGraphicsEffect(eff)
        lbl.show()
        self._movie, self._movie_label = movie, lbl

    # ------------------------------------------------------------- video
    def _start_video(self, path: str, volume: float = 0.0) -> None:
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtMultimediaWidgets import QVideoWidget
        except ImportError:
            return  # multimedia backend unavailable → silently skip
        vw = QVideoWidget(self)
        vw.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        vw.setGeometry(self.rect())
        vw.setAspectRatioMode(Qt.KeepAspectRatioByExpanding)
        player = QMediaPlayer(self)
        audio = QAudioOutput(self)
        audio.setVolume(max(0.0, min(1.0, volume)))
        player.setAudioOutput(audio)
        player.setVideoOutput(vw)
        player.setLoops(QMediaPlayer.Loops.Infinite)
        player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        if self._opacity < 1.0:
            eff = QGraphicsOpacityEffect(vw)
            eff.setOpacity(self._opacity)
            vw.setGraphicsEffect(eff)
        vw.show()
        player.play()
        self._video, self._player, self._audio = vw, player, audio

    # ------------------------------------------------------------ painting
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._movie_label is not None:
            self._movie_label.setGeometry(self.rect())
        if self._video is not None:
            self._video.setGeometry(self.rect())
        if self._mode == "version" and self._panorama is None:
            size = self.size()
            if size.isValid() and size.width() >= 2 and size.height() >= 2:
                self._pixmap = draw_version_wallpaper(self._version_id, size)
                self._scaled = None
                self.update()

    def paintEvent(self, e):
        if self._mode == "none":
            # Fill with the theme app background so the home page is never
            # see-through. Without this the backdrop is transparent until the
            # image/solid layer is applied, producing a brief transparent
            # flash when the window first paints (e.g. after onboarding).
            try:
                from .theme import COLORS
                p = QPainter(self)
                p.fillRect(self.rect(), QColor(COLORS["bg_app"]))
                p.end()
            except Exception:
                pass
            return
        p = QPainter(self)
        p.setOpacity(self._opacity)
        if self._mode == "solid":
            p.fillRect(self.rect(), self._color)
        elif self._panorama is not None:
            self._paint_panorama(p)
        elif self._mode in ("image", "version") and self._pixmap is not None:
            # Cache the size-fit pixmap — re-scaling a full-res image on every
            # repaint (especially during a resize drag) is very expensive.
            if self._scaled is None or self._scaled.size() != self.size():
                self._scaled = self._pixmap.scaled(
                    self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                )
                self._scaled_size = self.size()
            x = (self.width() - self._scaled.width()) // 2
            y = (self.height() - self._scaled.height()) // 2
            p.drawPixmap(x, y, self._scaled)
        p.end()

    def _paint_panorama(self, p: QPainter) -> None:
        """Draw the cubemap as a rotating 3D view, then the readability scrim."""
        w, h = self.width(), self.height()
        if w < 2 or h < 2 or self._panorama is None:
            return
        bw = max(2, w // PANO_BUFFER_DIV)
        bh = max(2, h // PANO_BUFFER_DIV)
        if self._pano_buffer is None or self._pano_buffer.size() != QSize(bw, bh):
            self._pano_buffer = QPixmap(bw, bh)
        bp = QPainter(self._pano_buffer)
        try:
            bp.fillRect(self._pano_buffer.rect(), QColor(0, 0, 0))
            self._panorama.render(bp, QRectF(0, 0, bw, bh), yaw=self._pano_yaw)
        finally:
            bp.end()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(QRectF(0, 0, w, h), self._pano_buffer,
                     QRectF(self._pano_buffer.rect()))
        self._paint_scrim(p)

    def _paint_scrim(self, p: QPainter) -> None:
        """Vertical scrim that keeps the labels over the artwork readable.

        Light theme -> white scrim (page stays light), dark theme -> black
        scrim (page stays dark).  The strength at the top is derived from the
        artwork's mean luminance so that only as much scrim as needed is
        applied; it fades out towards the bottom where the artwork shows.
        """
        try:
            from .theme import get_theme_mode
            dark = get_theme_mode() == "dark"
        except Exception:  # noqa: BLE001
            dark = True
        key = "dark" if dark else "light"
        luma = self._pano_luma
        target = PANO_TARGET_LUMA[key]
        if dark:
            # Darken until the backdrop is dark enough for light labels.
            top = (luma - target) / luma if luma > target else 0.0
        else:
            # Brighten until the backdrop is light enough for dark labels.
            top = (target - luma) / (1.0 - luma) if luma < target else 0.0
        top = min(1.0, max(0.0, top))
        bottom = min(top, PANO_SCRIM_FLOOR[key])
        base = QColor(0, 0, 0) if dark else QColor(255, 255, 255)
        c_top = QColor(base)
        c_top.setAlpha(int(round(top * 255)))
        c_bottom = QColor(base)
        c_bottom.setAlpha(int(round(bottom * 255)))
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, c_top)
        grad.setColorAt(PANO_SCRIM_SPAN, c_bottom)
        grad.setColorAt(1.0, c_bottom)
        p.setPen(Qt.NoPen)
        p.fillRect(self.rect(), QBrush(grad))

    # ------------------------------------------------------------ lifecycle
    def showEvent(self, e):
        super().showEvent(e)
        self._set_playing(True)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._set_playing(False)

    def _set_playing(self, on: bool) -> None:
        """壁纸不可见（切页/最小化）时暂停动图/视频，省解码 CPU。

        round-61 性能：页面在 QStackedWidget 里切走或窗口最小化时，QMovie /
        QMediaPlayer 仍会继续逐帧解码；这里随可见性暂停与恢复。放行与暂停
        都带 try/except —— 状态错乱最坏只是动图停一下，绝不抛错。
        """
        m = self._movie
        if m is not None:
            try:
                if on:
                    if m.state() == QMovie.MovieState.Paused:
                        m.setPaused(False)
                elif m.state() == QMovie.MovieState.Running:
                    m.setPaused(True)
            except Exception:  # noqa: BLE001
                pass
        p = self._player
        if p is not None:
            try:
                from PySide6.QtMultimedia import QMediaPlayer
                st = p.playbackState()
                if on:
                    if st == QMediaPlayer.PlaybackState.PausedState:
                        p.play()
                elif st == QMediaPlayer.PlaybackState.PlayingState:
                    p.pause()
            except Exception:  # noqa: BLE001
                pass
        # The panorama is rendered by this widget, so it burns CPU just like
        # a video would -- stop the animation while the page is off-screen.
        if self._pano_timer is not None:
            try:
                if on:
                    if self._panorama is not None:
                        self._pano_timer.start()
                else:
                    self._pano_timer.stop()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        self._teardown_dynamic()
        self._stop_panorama()
