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
from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QPixmap, QMovie, QPainter, QColor

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


class WallpaperWidget(QWidget):
    """Backdrop that renders a colour / image / GIF / video behind content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.lower()
        self._mode = "none"
        self._color = QColor("#1E1E1E")
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
    def apply(self, cfg: dict) -> None:
        """Reconfigure from the settings dict."""
        mode = cfg.get("wallpaper_mode", "none")
        self._opacity = float(cfg.get("wallpaper_opacity", 1.0))
        self._color = QColor(cfg.get("wallpaper_color", "#1E1E1E"))
        path = cfg.get("wallpaper_image", "")

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
        elif self._mode == "image" and self._pixmap is not None:
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
    def stop(self) -> None:
        self._teardown_dynamic()
