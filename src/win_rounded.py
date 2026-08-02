"""Windows 11 OS-level rounded window corners + dark title bar + themed dialogs.

Calls DwmSetWindowAttribute for:
  - DWMWA_WINDOW_CORNER_PREFERENCE (33) → round corners
  - DWMWA_USE_IMMERSIVE_DARK_MODE (20) → dark native title bar / border

Also provides confirm() / warn() / info() helpers that build QDialog-based
message boxes with dark title bars (replacing raw QMessageBox which shows a
white Windows-native chrome against the dark launcher theme).
"""
import sys

try:
    import ctypes
except ImportError:  # non-Windows builds won't have ctypes.windll, but the
                     # import itself is fine
    ctypes = None  # type: ignore

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QSizePolicy, QFileDialog, QLineEdit, QFormLayout,
)
from PySide6.QtCore import Qt


_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2


def enable_win11_round_corners(widget) -> bool:
    """Ask DWM to round the widget's window corners. Returns True on success."""
    if sys.platform != "win32" or ctypes is None:
        return False
    try:
        hwnd = int(widget.winId())
        if hwnd == 0:
            return False
        value = ctypes.c_int(_DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        return True
    except Exception:
        return False  # old Windows, missing DLL, or no DWM — just skip


# DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win10 20H1+ / Win11). Tells DWM to paint
# the native title bar + 1px window border in dark mode, so a standard QDialog
# (which we use for the login dialog) blends with the launcher's dark theme
# instead of showing an un-themed white title bar.
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20


def enable_dark_titlebar(widget) -> bool:
    """Paint the native title bar / border dark. No-op off Windows or pre-20H1.

    Must be called after the widget has a native handle (winId() creates one),
    e.g. at the end of __init__ or in showEvent.
    """
    if sys.platform != "win32" or ctypes is None:
        return False
    try:
        hwnd = int(widget.winId())
        if hwnd == 0:
            return False
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        return True
    except Exception:
        return False


# ── Themed message-box helpers (replace raw QMessageBox) ──────────────────
# QMessageBox uses the OS-native title bar which is white on dark theme.
# These helpers build lightweight QDialogs with enable_dark_titlebar so all
# confirmations / warnings / info dialogs blend with the launcher theme.

# Custom SVG icons (no emoji) — assets/icons/<name>.svg, loaded via .icons.icon
_ICON_MAP = {
    "warning": "dialog_warning",
    "question": "dialog_question",
    "info": "dialog_info",
    "success": "dialog_success",
}


def _msgbox(
    parent,
    title: str,
    text: str,
    detail: str = "",
    icon: str = "warning",
    buttons: tuple[str, ...] = ("Yes", "No"),
) -> str | None:
    """Show a themed confirmation/info dialog. Returns button text or None.

    Args:
        parent: parent widget (for modality + centering).
        title:  window title.
        text:   main message (rich text OK).
        detail: optional secondary text below the main message.
        icon:   one of "warning", "question", "info", "success".
        buttons: button labels shown right-to-left (last = default).

    Returns:
        The label of the clicked button, or None if dismissed.
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumSize(420, 160)
    dlg.resize(480, 200)

    root = QVBoxLayout(dlg)
    root.setContentsMargins(24, 20, 24, 16)
    root.setSpacing(12)

    # icon + text row
    row = QHBoxLayout()
    row.setSpacing(16)
    from .icons import icon as _load_icon
    from PySide6.QtGui import QPixmap
    px = _load_icon(_ICON_MAP.get(icon, "dialog_warning")).pixmap(40, 40)
    icon_lbl = QLabel()
    icon_lbl.setPixmap(px)
    icon_lbl.setFixedSize(40, 40)
    icon_lbl.setAlignment(Qt.AlignCenter)
    row.addWidget(icon_lbl)

    col = QVBoxLayout()
    col.setSpacing(6)
    msg = QLabel(text)
    msg.setWordWrap(True)
    msg.setTextFormat(Qt.RichText)
    msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    col.addWidget(msg)
    if detail:
        det = QLabel(detail)
        det.setWordWrap(True)
        det.setProperty("cls", "sub")
        col.addWidget(det)
    col.addStretch()
    row.addLayout(col, stretch=1)
    root.addLayout(row, stretch=1)

    # buttons
    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    clicked = [None]
    def _make_cb(lbl):
        def _cb():
            clicked[0] = lbl
            dlg.accept()
        return _cb
    for label in reversed(buttons):
        btn = QPushButton(label)
        btn.setMinimumHeight(34)
        btn.setMinimumWidth(70)
        if label == buttons[-1]:
            btn.setProperty("cls", "accent")
        btn.clicked.connect(_make_cb(label))
        btn_row.addWidget(btn)
    root.addLayout(btn_row)

    enable_dark_titlebar(dlg)
    result = dlg.exec()
    if result and clicked[0]:
        return clicked[0]
    return None


def confirm(parent, title: str, text: str, detail: str = "", **kw) -> bool:
    """Themed Yes/No confirmation dialog. Returns True if user clicked 'Yes'."""
    return _msgbox(parent, title, text, detail, icon="warning",
                   buttons=("No", "Yes")) == "Yes"


# ── Themed native-style dialogs (replace raw QColorDialog / QFileDialog / ──
# ── QInputDialog which render with the OS's light chrome on a dark theme) ──

def pick_files(parent, title: str, start_dir: str = "", filt: str = "",
               multi: bool = False, dir_only: bool = False):
    """Themed file / directory picker.

    Forces the non-native Qt file dialog (so our dark QSS applies) and paints
    the 1px native window border dark via DWM.

    Returns:
        str            — when single file ("" if cancelled)
        list[str]     — when multi ([]) if cancelled
        str           — when dir_only ("" if cancelled)
    """
    dlg = QFileDialog(parent, title, start_dir, filt)
    dlg.setOption(QFileDialog.DontUseNativeDialog)
    if dir_only:
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly)
    elif multi:
        dlg.setFileMode(QFileDialog.ExistingFiles)
    else:
        dlg.setFileMode(QFileDialog.ExistingFile)
    enable_dark_titlebar(dlg)
    if dlg.exec():
        files = dlg.selectedFiles()
        if multi:
            return files
        return files[0] if files else ""
    return [] if multi else ""


def pick_folder(parent, title: str, start_dir: str = "") -> str:
    """Native folder picker; returns absolute path or empty string."""
    from PySide6.QtWidgets import QFileDialog
    d = QFileDialog(parent, title, start_dir)
    d.setFileMode(QFileDialog.Directory)
    d.setOption(QFileDialog.ShowDirsOnly, True)
    if d.exec():
        sel = d.selectedFiles()
        if sel:
            return sel[0]
    return ""


def text_input(parent, title: str, label: str, default: str = "",
               placeholder: str = "") -> tuple[str, bool]:
    """Themed single-line text input dialog. Returns (text, ok).

    Replaces QInputDialog.getText (which shows a white native dialog on the
    dark theme). The dialog inherits the app's dark QSS; the native border is
    painted dark via DWM.
    """
    from .i18n import t
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(380)
    dlg.setMinimumHeight(150)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(20, 18, 20, 16)
    lay.setSpacing(14)

    lab = QLabel(label)
    lab.setWordWrap(True)
    lay.addWidget(lab)

    edit = QLineEdit(default)
    if placeholder:
        edit.setPlaceholderText(placeholder)
    edit.setMinimumHeight(34)
    lay.addWidget(edit)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = QPushButton(t("common.cancel"))
    cancel_btn.setMinimumHeight(34)
    cancel_btn.setMinimumWidth(80)
    cancel_btn.clicked.connect(lambda: dlg.done(0))
    ok_btn = QPushButton(t("common.ok"))
    ok_btn.setMinimumHeight(34)
    ok_btn.setMinimumWidth(80)
    ok_btn.setProperty("cls", "accent")
    ok_btn.clicked.connect(lambda: dlg.done(1))
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(ok_btn)
    lay.addLayout(btn_row)

    enable_dark_titlebar(dlg)
    ok = dlg.exec() == 1
    return edit.text(), ok


def dark_color(parent, start: str = "#000000") -> str:
    """Themed color picker. Returns chosen hex color, or '' if cancelled.

    Forces the non-native Qt color dialog so our dark QSS applies, and paints
    the native border dark.
    """
    from PySide6.QtWidgets import QColorDialog
    from PySide6.QtGui import QColor
    dlg = QColorDialog(parent)
    dlg.setOption(QColorDialog.DontUseNativeDialog)
    dlg.setCurrentColor(QColor(start))
    enable_dark_titlebar(dlg)
    if dlg.exec():
        return dlg.selectedColor().name()
    return ""


def warn(parent, title: str, text: str, detail: str = "", **kw) -> None:
    """Themed warning dialog (OK only)."""
    _msgbox(parent, title, text, detail, icon="warning", buttons=("OK",))


def info(parent, title: str, text: str, detail: str = "", **kw) -> None:
    """Themed info dialog (OK only)."""
    _msgbox(parent, title, text, detail, icon="info", buttons=("OK",))