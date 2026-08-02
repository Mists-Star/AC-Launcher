"""Async image loading + generated version thumbnails.

- ``ImageLoader`` downloads remote icons (Modrinth mod icons) with
  ``QNetworkAccessManager`` so the UI never blocks, caches them on disk under
  ``data/cache/icons`` and renders rounded pixmaps into a target QLabel.
- ``make_version_pixmap`` draws a colorful per-version tile locally (no network),
  giving the versions library a real "cover art" look.

Both are Qt-aware; keep them out of the Qt-free ``core`` layer.
"""
from __future__ import annotations

import os
import hashlib

from PySide6.QtCore import QObject, QUrl, Qt
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkRequest, QNetworkReply,
)
from PySide6.QtGui import QPixmap, QPainter, QColor, QLinearGradient, QBrush, QFont, QPainterPath

from .paths import get_data_dir


# ----------------------------------------------------------------------- loader
class ImageLoader(QObject):
    """Download + cache remote images, render them rounded into a QLabel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mgr = QNetworkAccessManager(self)
        self._mgr.finished.connect(self._on_finished)
        self._cache_dir = os.path.join(get_data_dir(), "cache", "icons")
        os.makedirs(self._cache_dir, exist_ok=True)

    def load(self, url: str, size: int, target, fallback: QPixmap | None = None) -> None:
        """Fetch ``url`` and drop a rounded ``size×size`` pixmap into ``target``
        (a QLabel). On empty url or failure, show ``fallback`` if provided."""
        if fallback is not None:
            target.setPixmap(self._round(fallback, size))
        if not url:
            return
        key = hashlib.md5(url.encode("utf-8")).hexdigest()
        path = os.path.join(self._cache_dir, key + ".img")
        if os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                target.setPixmap(self._round(pm, size))
                return
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.UserAgentHeader, "MC-Launcher/0.1")
        reply = self._mgr.get(req)
        reply.setProperty("target", target)
        reply.setProperty("size", size)
        reply.setProperty("path", path)

    def _on_finished(self, reply: QNetworkReply) -> None:
        target = reply.property("target")
        size = reply.property("size")
        path = reply.property("path")
        if reply.error() == QNetworkReply.NoError:
            data = reply.readAll()
            pm = QPixmap()
            if pm.loadFromData(data):
                try:
                    pm.save(path)
                except OSError:
                    pass
                if target is not None:
                    target.setPixmap(self._round(pm, size))
        reply.deleteLater()

    @staticmethod
    def _round(pm: QPixmap, size: int) -> QPixmap:
        scaled = pm.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        out = QPixmap(size, size)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, size, size, size * 0.18, size * 0.18)
        p.setClipPath(path)
        p.drawPixmap(0, 0, scaled)
        p.end()
        return out


# --------------------------------------------------------- version thumbnails
_TYPE_THEME: dict[str, tuple[str, str]] = {
    "release": ("#4ADE80", "#16A34A"),   # grass green
    "snapshot": ("#A78BFA", "#7C3AED"),   # experimental purple
    "april": ("#F472B6", "#DB2777"),       # joke-version pink
    "old_beta": ("#FBBF24", "#D97706"),   # amber
    "old_alpha": ("#94A3B8", "#64748B"),  # slate
}


def make_version_pixmap(version_id: str, vtype: str, size: int = 56) -> QPixmap:
    """Draw a colorful cover tile for a game version (gradient + id text)."""
    c1, c2 = _TYPE_THEME.get(vtype, ("#94A3B8", "#64748B"))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor(c1))
    grad.setColorAt(1, QColor(c2))
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, size * 0.16, size * 0.16)
    p.fillPath(path, QBrush(grad))

    label = version_id
    if len(label) <= 6:
        fs = size * 0.26
    elif len(label) <= 9:
        fs = size * 0.2
    else:
        fs = size * 0.15
    f = QFont("Microsoft YaHei", int(fs), QFont.Bold)
    p.setFont(f)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(pm.rect(), Qt.AlignCenter, label)
    p.end()
    return pm
