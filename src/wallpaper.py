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
from PySide6.QtCore import (Qt, QUrl, QSize, QPointF, QRectF, QTimer, Signal,
                            QElapsedTimer)
from PySide6.QtGui import (
    QPixmap, QMovie, QPainter, QColor, QImage,
    QRadialGradient, QLinearGradient, QBrush,
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
# round-146b：light 目标亮度 0.68 → 0.76、底部遮罩下限 0.46 → 0.56 —— 用户
# 反馈「文字可阅读性低」：#4B5563 次文本压在亮全景上仍不够，把整体压得更亮、
# 底部也不完全放开，保证牌面/说明文字在各角度都能读。
PANO_TARGET_LUMA = {"light": 0.76, "dark": 0.40}
# Scrim strength at the bottom of the page, where no text sits: the artwork
# is most visible there.
PANO_SCRIM_FLOOR = {"light": 0.56, "dark": 0.18}
# Fraction of the page height over which the scrim fades to its lower value.
PANO_SCRIM_SPAN = 0.70
# Animation: the vanilla title panorama advances with the game's tick clock —
# 20 ticks per second, 0.15 deg of yaw per tick — NOT with the render frame
# rate.  So a 144 Hz screen must not spin the cube faster than a 60 Hz one.
#
# Two things follow:
#   * the repaint interval is one tick (50 ms), matching the original rhythm;
#   * the yaw is advanced by the *measured* elapsed time, not by a fixed step,
#     so a timer that fires late (or a machine that stalls) cannot make the
#     rotation drift away from the original speed.
PANO_TICK_HZ = 20
PANO_FRAME_MS = int(1000 / PANO_TICK_HZ)
PANO_YAW_PER_TICK = 0.15
# Degrees per second implied by the original tick rhythm (0.15 * 20 = 3 deg/s).
PANO_YAW_PER_SEC = PANO_YAW_PER_TICK * PANO_TICK_HZ
# round-146：原先 2 = 半分辨率缓冲再放大——用户看到「版本动态背景模糊」。
# 全景贴图本身是 1024×1024，半分辨率重投影等于先丢掉一半细节再插值放大。
# 改为 1（按窗口原生分辨率重投影），配合 SmoothPixmapTransform 直接清晰。
PANO_BUFFER_DIV = 1

# ── loop-seam fade ──────────────────────────────────────────────────────
# GIFs and videos restart abruptly at the loop point; the jump from the last
# frame back to the first reads as a hard cut. Dip the backdrop to the theme
# background and fade back in so the seam is covered. This only paints *inside*
# the backdrop widget, which sits below every page, so it can never hide UI.
LOOP_FADE_MS = 380          # full cover → clear (and clear → full cover)
LOOP_FADE_TICK_MS = 24
LOOP_FADE_LEAD_MS = 420     # video: start covering this long before the end
LOOP_FADE_GIF_FRAMES = 3    # gif: start covering this many frames before the end


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


def _device_dpr(widget) -> float:
    """Device pixel ratio of the surface a widget paints on (>= 1.0).

    round-148：壁纸此前完全没有处理 DPR。显示器 125% 缩放（DPR=1.25）时，
    按**逻辑**尺寸渲染的图会被 Qt 放大 1.25 倍铺到物理像素上 → 一次多余的
    重采样 → 整屏发糊。这与 async_image 在 round-126 修过的「卡片封面低清」
    是同一个坑，只是壁纸漏了。
    """
    try:
        return max(1.0, float(widget.devicePixelRatioF() or 1.0))
    except Exception:  # noqa: BLE001 - no screen yet
        return 1.0


def _flat_raster(pm: QPixmap) -> QPixmap:
    """The pixmap's pixels as a plain DPR-1.0 raster (no resampling).

    ``QPixmap.scaled()`` interprets its target size in the *source* raster's
    own coordinate system, so a source that already carries a device pixel
    ratio has to be normalised first -- otherwise the picture ends up scaled
    by the ratio twice.
    """
    if pm.devicePixelRatio() == 1.0:
        return pm
    img = pm.toImage().copy()
    img.setDevicePixelRatio(1.0)
    return QPixmap.fromImage(img)



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


def draw_version_wallpaper(version_id: str | None, size: QSize,
                           dpr: float = 1.0) -> QPixmap | None:
    """Render a deterministic, resolution-independent themed wallpaper.

    The same ``version_id`` always produces the same scene, so the background
    feels stable while still shifting hue between major versions.

    Design (AC "Absolute Controller" / 掌控感):
      - quiet near-black (dark) or lavender-grey (light) base
      - a single soft accent glow whose HUE follows the version
      - a faint grid overlay (control-console feel) instead of noisy blocks

    round-148：``size`` 是**逻辑**尺寸，``dpr`` 是目标表面的设备像素比。
    图形按物理像素绘制后再打上 DPR 标记，这样贴到屏幕上时是 1:1 的物理
    像素映射，不会被二次插值放大。
    """
    if not size.isValid() or size.width() < 2 or size.height() < 2:
        return None
    dpr = max(1.0, float(dpr or 1.0))
    # 物理像素尺寸的画布
    pw = max(2, int(round(size.width() * dpr)))
    ph = max(2, int(round(size.height() * dpr)))
    pm = QPixmap(pw, ph)
    # 绘制坐标统一用逻辑单位（= 物理像素 / dpr）
    w, h = float(pw) / dpr, float(ph) / dpr
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
        # 画布是物理像素，绘制坐标用逻辑单位 → 缩放 dpr 倍即可 1:1 落位
        p.scale(dpr, dpr)

        # 1. base vertical gradient (neutral, quiet)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, base_top)
        bg.setColorAt(1.0, base_bot)
        p.fillRect(QRectF(0, 0, w, h), QBrush(bg))

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
        p.drawRect(QRectF(0, 0, w, h))

        # 2b. faint AC accent echo from the bottom-right corner (brand tie-in)
        if dark:
            acc = QColor(accent)
            acc.setAlpha(22)
            echo = QRadialGradient(QPointF(w * 0.88, h * 0.95), max(w, h) * 0.55)
            echo.setColorAt(0.0, acc)
            echo.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(echo))
            p.drawRect(QRectF(0, 0, w, h))

        # 3. faint control-console grid (keep alpha very low)
        p.setPen(QColor(255, 255, 255, 14) if dark else QColor(90, 70, 160, 16))
        step = 72
        for gx in range(0, int(w) + step, step):
            p.drawLine(gx, 0, gx, h)
        for gy in range(0, int(h) + step, step):
            p.drawLine(0, gy, w, gy)

        # 4. vignette to keep edges dark-ish for UI text readability
        vig = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.72)
        vig.setColorAt(0.0, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 150 if dark else 90))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(vig))
        p.fillRect(QRectF(0, 0, w, h), QBrush(vig))
    finally:
        p.end()
    # 标记 DPR：贴到屏幕上时按逻辑尺寸 1:1 落位，不再被二次放大
    pm.setDevicePixelRatio(dpr)
    return pm


# ── readability veil for still / animated media ─────────────────────────
# The veil keeps text that sits directly on the artwork legible.  Like the
# panorama scrim it is luminance-adaptive: art whose brightness is far from
# the theme's own polarity (a pale sky in the light theme, a bright photo in
# the dark theme) needs a heavier scrim, otherwise grey hint labels wash out
# (round-120).  ``VEIL_ALPHA`` is the fallback for media whose luma cannot be
# sampled (video) and the floor for everything else.
MEDIA_TARGET_LUMA = {"light": 0.86, "dark": 0.18}
MEDIA_VEIL_MIN = 0.46       # == _Veil.VEIL_ALPHA / 255
MEDIA_VEIL_MAX = 0.92       # never fully hide the artwork


class _Veil(QWidget):
    """Theme-coloured scrim between the artwork and the UI (round-119).

    Pages are plain widgets with a transparent background, so without a scrim
    the artwork would sit *directly* behind page titles and hint labels and
    murder their contrast. The veil keeps the wallpaper clearly visible while
    guaranteeing a legible surface for text; cards stay fully opaque on top.
    """

    VEIL_ALPHA = 118

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._alpha = self.VEIL_ALPHA

    def set_alpha(self, alpha: int) -> None:
        alpha = max(0, min(255, int(alpha)))
        if alpha == self._alpha:
            return
        self._alpha = alpha
        self.update()

    def paintEvent(self, e):
        try:
            from .theme import COLORS
            color = QColor(COLORS["bg_app"])
        except Exception:  # noqa: BLE001
            color = QColor("#1E1E1E")
        color.setAlpha(self._alpha)
        p = QPainter(self)
        p.fillRect(self.rect(), color)
        p.end()


class _LoopFade(QWidget):
    """Theme-coloured cover that animates across a media loop seam.

    Lives inside ``WallpaperWidget`` (below every page), so it dims only the
    artwork — never the UI on top of it.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._value = 0.0

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._value) < 0.004:
            return
        self._value = value
        self.update()

    def paintEvent(self, e):
        if self._value <= 0.004:
            return
        try:
            from .theme import COLORS
            color = QColor(COLORS["bg_app"])
        except Exception:  # noqa: BLE001
            color = QColor("#1E1E1E")
        color.setAlpha(int(round(self._value * 255)))
        p = QPainter(self)
        p.fillRect(self.rect(), color)
        p.end()


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
        self._media_luma: float | None = None  # mean luminance of still art
        self._pano_timer: QTimer | None = None
        self._pano_key: tuple | None = None
        # round-147：真实时钟，用于按原版 tick 节奏推进 yaw（消除定时器漂移）
        self._pano_clock = QElapsedTimer()
        # ── loop-seam fade state ──
        self._veil: _Veil | None = None
        self._fade: _LoopFade | None = None
        self._fade_value = 0.0
        self._fade_target = 0.0
        self._fade_timer: QTimer | None = None
        self._last_gif_frame = -1
        self._last_video_pos = -1

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
        self._media_luma = None
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
            if self._pixmap is not None:
                self._media_luma = _mean_luma([pm.toImage()])
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
                if self._pixmap is not None:
                    self._media_luma = _mean_luma([pm.toImage()])
            elif not mc_dir:
                # No instance yet → nothing to draw (see `visible` above).
                self._stop_panorama()
            else:
                # Real cubemap of the instance's own version. Do NOT paint the
                # procedural fallback while the textures load: on light themes
                # it is a flat lavender wash that reads as a broken background
                # (round-126: "点击启动后出现淡紫色底色"). Stay hidden until the
                # actual panorama arrives; a version without usable assets now
                # simply keeps the normal page background.
                self._start_panorama(mc_dir, game_dir, version)
                # A cubemap that is already loaded (same instance) stays visible;
                # otherwise wait for the loader's ready signal.
                visible = self._panorama is not None
        else:
            self._stop_panorama()

        if mode == "version" and not mc_dir and not (
                path and os.path.exists(path)):
            visible = False
        self.setVisible(visible)
        self._sync_veil()
        # A fresh wallpaper starts clear; the loop seam handles its own fades.
        self._reset_fade()
        self.update()

    # -------------------------------------------------------- readability veil
    def _sync_veil(self) -> None:
        """Keep the theme scrim aligned with the current artwork (round-119)."""
        media = (self._mode in ("image", "gif", "video", "version")
                 and self._panorama is None)
        if not media:
            if self._veil is not None:
                self._veil.hide()
            return
        if self._veil is None:
            self._veil = _Veil(self)
        self._veil.set_alpha(self._veil_alpha())
        self._veil.setGeometry(self.rect())
        self._veil.show()
        self._veil.raise_()
        if self._fade is not None and self._fade.isVisible():
            self._fade.raise_()

    def _veil_alpha(self) -> int:
        """Luminance-adaptive scrim strength for still / animated art.

        Panorama mode has its own vertical scrim; video has no cheap way to
        sample a frame, so both keep the historical constant.  For images and
        GIFs push the scrim only as far as the theme's polarity needs, clamped
        so the artwork always stays visible.
        """
        luma = self._media_luma
        if luma is None:
            return _Veil.VEIL_ALPHA
        try:
            from .theme import get_theme_mode
            dark = get_theme_mode() == "dark"
        except Exception:  # noqa: BLE001
            dark = True
        target = MEDIA_TARGET_LUMA["dark" if dark else "light"]
        if dark:
            need = 1.0 - target / luma if luma > 0 else 0.0
        else:
            need = (target - luma) / (1.0 - luma) if luma < 1.0 else 0.0
        need = max(MEDIA_VEIL_MIN, min(MEDIA_VEIL_MAX, need))
        return int(round(need * 255))

    # -------------------------------------------------------- loop-seam fade
    def _reset_fade(self) -> None:
        self._fade_value = 0.0
        self._fade_target = 0.0
        if self._fade_timer is not None:
            self._fade_timer.stop()
        if self._fade is not None:
            self._fade.set_value(0.0)
            self._fade.hide()

    def _ensure_fade(self) -> "_LoopFade":
        if self._fade is None:
            self._fade = _LoopFade(self)
            self._fade.setGeometry(self.rect())
        self._fade.setGeometry(self.rect())
        self._fade.show()
        self._fade.raise_()
        return self._fade

    def _fade_to(self, target: float) -> None:
        """Animate the seam cover towards ``target`` (0 = clear, 1 = covered)."""
        target = max(0.0, min(1.0, float(target)))
        if abs(target - self._fade_target) < 0.02:
            return
        self._fade_target = target
        self._ensure_fade()
        if self._fade_timer is None:
            self._fade_timer = QTimer(self)
            self._fade_timer.setInterval(LOOP_FADE_TICK_MS)
            self._fade_timer.timeout.connect(self._fade_tick)
        self._fade_timer.start()

    def _fade_tick(self) -> None:
        step = LOOP_FADE_TICK_MS / float(LOOP_FADE_MS)
        if self._fade_value < self._fade_target:
            self._fade_value = min(self._fade_target, self._fade_value + step)
        else:
            self._fade_value = max(self._fade_target, self._fade_value - step)
        if self._fade is not None:
            self._fade.set_value(self._fade_value)
        if abs(self._fade_value - self._fade_target) < 1e-6:
            if self._fade_timer is not None:
                self._fade_timer.stop()
            if self._fade_value <= 0.004 and self._fade is not None:
                self._fade.hide()

    def _on_gif_frame(self, frame: int) -> None:
        """Cover the GIF loop seam (QMovie wraps back to frame 0)."""
        movie = self._movie
        if movie is None:
            return
        try:
            count = movie.frameCount()
        except Exception:  # noqa: BLE001
            return
        if self._media_luma is None and frame == 0:
            # First frame is enough to pick the veil strength (round-120).
            try:
                img = movie.currentImage()
                if not img.isNull():
                    self._media_luma = _mean_luma([img])
                    self._sync_veil()
            except Exception:  # noqa: BLE001
                pass
        if count > LOOP_FADE_GIF_FRAMES * 2:
            if frame >= count - LOOP_FADE_GIF_FRAMES:
                self._fade_to(1.0)
        if 0 <= frame < self._last_gif_frame:
            self._fade_to(0.0)      # wrapped → fade the new loop back in
        self._last_gif_frame = frame

    def _on_video_pos(self, pos: int) -> None:
        """Cover the video loop seam (QMediaPlayer rewinds to 0)."""
        player = self._player
        if player is None:
            return
        try:
            dur = player.duration()
        except Exception:  # noqa: BLE001
            return
        if dur > 3000:
            if pos >= 0 and dur - pos <= LOOP_FADE_LEAD_MS:
                self._fade_to(1.0)
            if 0 <= pos < self._last_video_pos and self._last_video_pos > dur * 0.5:
                self._fade_to(0.0)
        self._last_video_pos = pos

    # ------------------------------------------------------------ panorama
    @property
    def panorama_active(self) -> bool:
        """True while the real Minecraft panorama is on screen."""
        return self._panorama is not None

    @property
    def has_backdrop(self) -> bool:
        """True while any wallpaper (colour / image / GIF / video / panorama) is up."""
        return self._mode != "none" and self.isVisible()

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
            # round-145 修「部分版本获取不到背景」：贴图缺失（资源未下载 /
            # 旧版本无 panorama）时此前直接 return，backdrop 永远隐身 →
            # 整个背景消失。回退到程序化的版本主题背景，至少有底色。
            self._fallback_procedural()
            return  # nothing found -> procedural fallback is on screen
        try:
            from .panorama import PanoramaRenderer
            self._panorama = PanoramaRenderer(images)
        except Exception:  # noqa: BLE001 - a broken cubemap must not kill the page
            self._panorama = None
            self._fallback_procedural()
            return
        self._pano_luma = _mean_luma(images)
        self._pano_buffer = None
        self._pano_yaw = 0.0
        # The backdrop was held hidden while the cubemap loaded; now there is
        # real artwork to show.
        if self._mode == "version" and not self.isVisible():
            self.setVisible(True)
        self._start_pano_timer()
        self._sync_veil()      # the panorama brings its own luminance-adaptive scrim
        self.panorama_ready.emit()
        self.update()

    def _fallback_procedural(self) -> None:
        """Paint the deterministic version-themed wallpaper (round-145).

        Used when the real panorama cannot be loaded — a version without
        usable panorama assets must still get a background. Uses the current
        widget size; a later resize re-scales via the shared ``_scaled`` path.
        """
        if self._mode != "version":
            return
        try:
            pm = draw_version_wallpaper(self._version_id, self.size(),
                                        _device_dpr(self))
        except Exception:  # noqa: BLE001 - a fallback bug must never hurt
            pm = None
        if pm is None or pm.isNull():
            return
        self._pixmap = pm
        self._scaled = None
        try:
            self._media_luma = _mean_luma([pm.toImage()])
        except Exception:  # noqa: BLE001
            self._media_luma = None
        if not self.isVisible():
            self.setVisible(True)
        self._sync_veil()
        self.update()

    def _start_pano_timer(self) -> None:
        if self._pano_timer is None:
            self._pano_timer = QTimer(self)
            self._pano_timer.setInterval(PANO_FRAME_MS)
            self._pano_timer.timeout.connect(self._pano_tick)
        if self.isVisible():
            self._pano_timer.start()
            # round-147：重新计时基准，避免暂停期间积压的时间在恢复瞬间
            # 让全景「跳」一大段。
            self._pano_clock.restart()

    def _pano_tick(self) -> None:
        """Advance the panorama by one tick of the original game's clock.

        round-147：原版主菜单的全景是跟着**游戏 tick** 走的（20 tick/s、
        每 tick 0.15° ≈ 3°/s），跟显示器刷新率无关——144 Hz 屏上不会比
        60 Hz 屏转得更快（这是 Bedrock 版的已知 bug，Java 版没有）。

        所以这里不再用「每次定时器固定 +0.2°」，而是量出**真实经过时间**
        再换算成角度：定时器抖动、系统卡顿都不会让转速偏离原版。
        """
        if not self._pano_clock.isValid():
            self._pano_clock.start()
            elapsed = PANO_FRAME_MS
        else:
            elapsed = self._pano_clock.restart()
        self._pano_yaw = (self._pano_yaw
                          + elapsed * PANO_YAW_PER_SEC / 1000.0) % 360.0
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
        self._last_gif_frame = -1
        movie.frameChanged.connect(self._on_gif_frame)
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
        self._last_video_pos = -1
        player.positionChanged.connect(self._on_video_pos)
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
        if self._fade is not None:
            self._fade.setGeometry(self.rect())
        if self._veil is not None:
            self._veil.setGeometry(self.rect())

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
            #
            # round-148：缩放到**物理**像素并打上 DPR 标记。缩到逻辑尺寸再让
            # 设备变换放大 1.25 倍 = 多一次插值重采样 → 整屏发糊。
            dpr = _device_dpr(self)
            phys = QSize(max(1, int(round(self.width() * dpr))),
                         max(1, int(round(self.height() * dpr))))
            if (self._scaled is None
                    or self._scaled_size != phys
                    or self._scaled.devicePixelRatio() != dpr):
                # ``_flat_raster`` 先把源图归一化成 DPR-1.0 的像素栅格，
                # 否则 ``scaled()`` 会按比例缩放两次。
                self._scaled = _flat_raster(self._pixmap).scaled(
                    phys, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                )
                self._scaled.setDevicePixelRatio(dpr)
                self._scaled_size = phys
            lw = self._scaled.width() / dpr
            lh = self._scaled.height() / dpr
            x = (self.width() - lw) / 2.0
            y = (self.height() - lh) / 2.0
            p.drawPixmap(x, y, self._scaled)
        p.end()

    def _paint_panorama(self, p: QPainter) -> None:
        """Draw the cubemap as a rotating 3D view, then the readability scrim."""
        w, h = self.width(), self.height()
        if w < 2 or h < 2 or self._panorama is None:
            return
        # round-148：缓冲按**物理**像素建。之前缓冲只有逻辑分辨率，再被设备
        # 变换放大 1.25 倍 —— 多一次重采样（糊），面缝也被拉宽成可见黑线。
        dpr = _device_dpr(self)
        bw = max(2, int(round(w * dpr)) // PANO_BUFFER_DIV)
        bh = max(2, int(round(h * dpr)) // PANO_BUFFER_DIV)
        if self._pano_buffer is None or self._pano_buffer.size() != QSize(bw, bh):
            self._pano_buffer = QPixmap(bw, bh)
        bp = QPainter(self._pano_buffer)
        try:
            # round-146：底色从纯黑改为全景平均色 —— 缓冲填黑时，相邻面之间
            # 的亚像素缝会透出黑点/黑线并随 yaw 抖动闪烁（「黑色噪点」）。
            avg = getattr(self._panorama, "avg_color", None)
            bp.fillRect(self._pano_buffer.rect(), avg or QColor(32, 34, 38))
            self._panorama.render(bp, QRectF(0, 0, bw, bh), yaw=self._pano_yaw)
        finally:
            bp.end()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # 缓冲是 DPR-1.0 的物理像素栅格，源矩形用像素坐标；目标矩形用逻辑
        # 坐标（设备变换负责 1:1 落到物理像素）。
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
                        # round-147：恢复播放时重置时钟基准，暂停期间
                        # 的时间不计入 yaw（否则会瞬间跳一大段）。
                        self._pano_clock.restart()
                else:
                    self._pano_timer.stop()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        self._teardown_dynamic()
        self._stop_panorama()
