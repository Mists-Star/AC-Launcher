"""
Frameless window system — removes native OS chrome entirely.

Provides:
  - FramelessHelper: attaches to any top-level widget (QMainWindow / QDialog / QWidget)
    * Sets Qt.FramelessWindowHint + Qt.Window
    * Edge-resize via startSystemResize (Qt 5.15+, all edges, 8 directions)
    * Cursor shape updates on hover near edges
  - TitleBar: custom title bar widget
    * Drag area → startSystemMove (native drag)
    * Double-click → toggle maximize/restore
    * Window control buttons (minimize / maximize / restore / close)
    * Hover effects (close turns red)

Usage on MainWindow:
    helper = FramelessHelper(self)
    helper.set_titlebar(self.my_titlebar_widget)   # existing top bar works too

Usage on Dialog:
    helper = FramelessHelper(self)
    helper.set_titlebar(self.titlebar)              # thin dialog title bar
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QHBoxLayout,
)
from PySide6.QtCore import Qt, QEvent, QPoint, QObject
from PySide6.QtGui import QMouseEvent


class TitleBar(QWidget):
    """Custom draggable title bar with window controls.

    Parameters
    ----------
    parent : QWidget
        Usually the dialog or main window itself.
    title : str
        Initial window title text.
    show_controls : bool
        Show min/max/close buttons. Set False if the host window draws
        its own controls in a different location.
    height : int
        Bar height in pixels (default 40).
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        title: str = "",
        show_controls: bool = True,
        height: int = 44,
    ):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._window = lambda: self.window()

        # Explicit themed background — frameless windows lose native chrome
        # so we must paint our own to keep text readable in both modes.
        self._refresh_bg()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 4, 0)
        lay.setSpacing(0)

        # ---- left: title text ----
        self.title_lbl = QLabel(title)
        self._title_style = (
            "font-size: 13px; font-weight: 600; "
            "background: transparent; border: none;"
        )
        self._refresh_title_style()
        lay.addWidget(self.title_lbl)
        lay.addStretch(1)

        # ---- right: window controls ----
        self._btns: dict[str, QPushButton] = {}
        if show_controls:
            for name, txt, tip, slot in [
                ("min", "─", "Minimize", "_on_min"),
                ("max", "□", "Maximize", "_on_max"),
                ("close", "✕", "Close", "_on_close"),
            ]:
                btn = QPushButton(txt)
                btn.setObjectName(f"tb_{name}")
                btn.setFixedSize(52, 38)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip(tip)
                btn.clicked.connect(getattr(self, slot))
                lay.addWidget(btn)
                self._btns[name] = btn

            # Base style for all titlebar buttons
            self._tb_css_base = (
                "QPushButton { background: transparent; border: none; "
                "font-size: 16px; color: $COLOR_SUB; }"
                "QPushButton:hover { background: $BG_HOVER; color: $COLOR_MAIN; }"
            )
            # Close button overrides
            close_css = (
                "QPushButton#tb_close:hover "
                "{ background: #EF4444; color: #FFFFFF; }"
            )

            for name, b in self._btns.items():
                if name == "close":
                    b.setStyleSheet(self._tb_css() + close_css)
                else:
                    b.setStyleSheet(self._tb_css())

    # ---- public API ----

    def set_title(self, text: str) -> None:
        self.title_lbl.setText(text)

    def _refresh_bg(self) -> None:
        """Paint the title bar background from current theme tokens."""
        try:
            from .theme import COLORS
            bg = COLORS.get("bg_panel", "#F8F9FA")
        except Exception:
            bg = "#F8F9FA"
        self.setStyleSheet(f"background: {bg}; border: none;")

    def _refresh_title_style(self) -> None:
        """Update title label color + bar background from current theme tokens."""
        try:
            from .theme import COLORS
            color = COLORS.get("text_main", "#E5E5E5")
            self.title_lbl.setStyleSheet(
                self._title_style + f"color: {color};"
            )
            self._refresh_bg()
        except Exception:
            self.title_lbl.setStyleSheet(
                self._title_style + "color: #E5E5E5;"
            )

    def _tb_css(self) -> str:
        """Generate titlebar button CSS from current theme."""
        try:
            from .theme import COLORS
            return self._tb_css_base.replace("$COLOR_SUB", COLORS.get("text_sub", "#9CA3B0"))\
                .replace("$COLOR_MAIN", COLORS.get("text_main", "#E5E5E5"))\
                .replace("$BG_HOVER", COLORS.get("bg_hover", "#33333A"))
        except Exception:
            return self._tb_css_base.replace("$COLOR_SUB", "#9CA3B0")\
                .replace("$COLOR_MAIN", "#E5E5E5").replace("$BG_HOVER", "#33333A")

    # ---- window operations ----

    def _on_min(self) -> None:
        w = self._window()
        w.showMinimized()

    def _on_max(self) -> None:
        w = self._window()
        if w.isMaximized():
            w.showNormal()
            self._btns["max"].setText("□")
        else:
            w.showMaximized()
            self._btns["max"].setText("❐")

    def _on_close(self) -> None:
        self._window().close()

    # ---- drag ----

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            try:
                self._window().startSystemMove()
            except AttributeError:
                pass  # Very old Qt; fall through without drag
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and "max" in self._btns:
            self._on_max()


# ─── edge constants ──────────────────────────────────────────────

# Qt6: Qt.Edge only has the 4 cardinal edges. Corners are expressed by
# combining two edges with `|` (e.g. top-left = TopEdge | LeftEdge).
_TL = Qt.Edge.TopEdge | Qt.Edge.LeftEdge
_TR = Qt.Edge.TopEdge | Qt.Edge.RightEdge
_BL = Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
_BR = Qt.Edge.BottomEdge | Qt.Edge.RightEdge

_EDGE_MAP = {
    (True, True, False, False): _TL,
    (True, False, False, True): _TR,
    (False, True, False, False): Qt.Edge.LeftEdge,
    (False, False, False, True): Qt.Edge.RightEdge,
    (False, True, True, False): _BL,
    (False, False, True, True): _BR,
    (False, False, True, False): Qt.Edge.BottomEdge,
    (True, False, False, False): Qt.Edge.TopEdge,
}

_CURSOR_FOR_EDGE = {
    _TL: Qt.SizeFDiagCursor,
    _TR: Qt.SizeBDiagCursor,
    _BL: Qt.SizeBDiagCursor,
    _BR: Qt.SizeFDiagCursor,
    Qt.Edge.TopEdge: Qt.SizeVerCursor,
    Qt.Edge.BottomEdge: Qt.SizeVerCursor,
    Qt.Edge.LeftEdge: Qt.SizeHorCursor,
    Qt.Edge.RightEdge: Qt.SizeHorCursor,
}


class FramelessHelper(QObject):
    """Attach to any top-level widget to make it frameless.

    Call ``setup()`` **after** the window layout is complete (all children
    added).  The helper installs an event filter that handles:

    * **Edge resize** — cursor changes to resize-arrow within MARGIN px of any
      edge; click+drag calls ``startSystemResize(edge)`` for native behaviour.
    * **Title-bar drag** — click+drag within the registered title bar area
      calls ``startSystemMove()``.
    * **Double-click title bar** — toggles maximize / restore.

    Parameters
    ----------
    window : QWidget
        The top-level window (QMainWindow, QDialog, or bare QWidget).
    margin : int
        Pixel width of the edge-detection zone (default 6).
    """

    def __init__(self, window: QWidget, margin: int = 6) -> None:
        super().__init__()
        self.window = window
        self.margin = margin
        self.titlebar: TitleBar | QWidget | None = None
        self._apply_flags()
        self._enable_dwm_shadow()
        window.installEventFilter(self)

    # ── public ────────────────────────────────────────────────────

    def set_titlebar(self, bar: QWidget) -> None:
        """Register the draggable title-bar widget."""
        self.titlebar = bar

    # ── flags ─────────────────────────────────────────────────────

    def _apply_flags(self) -> None:
        flags = self.window.windowFlags()
        self.window.setWindowFlags(flags | Qt.FramelessWindowHint | Qt.Window)
        # Re-show if already visible (setWindowFlags hides the window)
        if self.window.isVisible():
            self.window.show()

    # ── event filter ──────────────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self.window:
            return False

        etype = event.type()

        if etype == QEvent.Type.MouseMove:
            self._on_mouse_move(event)
        elif etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self._on_mouse_press(event)
        elif etype == QEvent.Type.MouseButtonDblClick:
            if event.button() == Qt.LeftButton:
                pos = event.position().toPoint()
                if self._hit_titlebar(pos):
                    self._toggle_max()

        return False  # never eat the event

    # ── internal ──────────────────────────────────────────────────

    def _edge_at(self, pos: QPoint) -> Qt.Edge | None:
        m = self.margin
        w, h = self.window.width(), self.window.height()
        top = pos.y() < m
        bottom = pos.y() > h - m
        left = pos.x() < m
        right = pos.x() > w - m
        return _EDGE_MAP.get((top, right, bottom, left))

    def _hit_titlebar(self, pos: QPoint) -> bool:
        if self.titlebar is None:
            # Fallback: treat top 48 px as title bar
            return pos.y() < 48
        return self.titlebar.geometry().contains(pos)

    def _on_mouse_move(self, event: QEvent) -> None:
        pos = event.position().toPoint()
        edge = self._edge_at(pos)
        cursor = _CURSOR_FOR_EDGE.get(edge, Qt.ArrowCursor)
        self.window.setCursor(cursor)

    def _on_mouse_press(self, event: QEvent) -> None:
        pos = event.position().toPoint()
        edge = self._edge_at(pos)
        if edge is not None:
            try:
                self.window.startSystemResize(edge)
            except AttributeError:
                pass
        elif self._hit_titlebar(pos):
            # Don't start a window move when grabbing an interactive control
            # (account button, window controls) — they handle their own clicks.
            child = self.window.childAt(pos)
            if isinstance(child, QPushButton):
                return
            try:
                self.window.startSystemMove()
            except AttributeError:
                pass

    def _toggle_max(self) -> None:
        w = self.window
        w.showNormal() if w.isMaximized() else w.showMaximized()

    # ── DWM drop shadow (Windows) ─────────────────────────────────
    # Frameless windows lose the native shadow, so re-add one via DWM.
    # Guarded: never raises on non-Windows or if the API is unavailable.

    def _enable_dwm_shadow(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes.wintypes import HWND, c_int

            class _MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", c_int),
                    ("cxRightWidth", c_int),
                    ("cyTopHeight", c_int),
                    ("cyBottomHeight", c_int),
                ]

            dwmapi = ctypes.windll.dwmapi
            hwnd = int(self.window.winId())
            margins = _MARGINS(-1, -1, -1, -1)
            dwmapi.DwmExtendFrameIntoClientArea(HWND(hwnd), ctypes.byref(margins))
        except Exception:
            pass
