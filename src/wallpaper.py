"""Wallpaper backdrop for the home page.

Supports four modes, all user-supplied:

  none   — inherit the theme background
  solid  — a flat colour
  image  — any still image (png/jpg/webp/bmp), scaled to cover
  gif    — an animated GIF / animated WebP, played on loop
  video  — an mp4/webm/mkv played on loop, muted (true "dynamic wallpaper")

The widget is meant to sit *behind* page content: it paints itself and never
steals mouse events, so buttons on top keep working.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import QWidget, QLabel, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QUrl, QSize, QPointF
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
        glow = QRadialGradient(QPointF(w * 0.28, h * 0.18), max(w, h) * 0.75)
        glow_color = QColor(theme["glow"])
        if dark:
            glow_color.setAlpha(46)
        else:
            glow_color.setAlpha(26)
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(0.55, QColor(theme["glow"]))
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
    """Backdrop that renders a colour / image / GIF / video behind content."""

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

    # ------------------------------------------------------------- config
    def apply(self, cfg: dict, version_id: str | None = None) -> None:
        """Reconfigure from the settings dict.

        ``version_id`` is used by the ``version`` mode to pick a default
        themed wallpaper.  A player-supplied custom image always wins.
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

        if mode == "image" and path and os.path.exists(path):
            pm = QPixmap(path)
            self._pixmap = pm if not pm.isNull() else None
            self._scaled = None  # invalidate scaled cache
        elif mode == "gif" and path and os.path.exists(path):
            self._start_gif(path)
        elif mode == "video" and path and os.path.exists(path):
            self._start_video(path, float(cfg.get("wallpaper_video_vol", 0.0)))
        elif mode == "version":
            # Player custom wallpaper takes priority over the version theme.
            if path and os.path.exists(path):
                pm = QPixmap(path)
                self._pixmap = pm if not pm.isNull() else None
                self._scaled = None
            else:
                size = self.size()
                if not size.isValid() or size.width() < 2 or size.height() < 2:
                    size = QSize(1920, 1080)
                self._pixmap = draw_version_wallpaper(version_id, size)
                self._scaled = None

        self.setVisible(mode != "none")
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
        if self._mode == "version":
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

    def stop(self) -> None:
        self._teardown_dynamic()
