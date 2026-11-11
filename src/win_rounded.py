"""Windows 11 OS-level rounded window corners + dark title bar + themed dialogs.

Calls DwmSetWindowAttribute for:
  - DWMWA_WINDOW_CORNER_PREFERENCE (33) → round corners
  - DWMWA_USE_IMMERSIVE_DARK_MODE (20) → dark/light native title bar
  - DWMWA_CAPTION_COLOR (35) / DWMWA_TEXT_COLOR (36) → 标题栏配色跟随主题

Also provides confirm() / warn() / info() helpers that build QDialog-based
message boxes with theme-matched title bars (replacing raw QMessageBox, whose
native chrome does not follow the launcher theme).
"""
import sys

try:
    import ctypes
except ImportError:  # non-Windows builds won't have ctypes.windll, but the
                     # import itself is fine
    ctypes = None  # type: ignore

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QFileDialog, QLineEdit,
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


# DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win10 20H1+ / Win11), 19 on older builds.
# Tells DWM to paint the native title bar + 1px window border in dark mode, so a
# standard QDialog blends with the launcher theme instead of showing un-themed
# chrome. round-224：以前这个开关是**写死 1** 的，浅色主题下顶部就是一条黑栏
# （用户报的就是这个）——现在跟随 theme.get_theme_mode() 双向切换。
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19
# Win11 22000+：标题栏底色 / 文字色（让白栏与白窗身不再是两段白）
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36

def _theme_is_dark() -> bool:
    """当前启动器主题是不是深色（取不到主题模块时按浅色处理）。"""
    try:
        from .theme import get_theme_mode

        return get_theme_mode() == "dark"
    except Exception:  # noqa: BLE001 - 主题模块坏了不该拖垮窗口创建
        return False


def _colorref(hex_color: str) -> int | None:
    """``#RRGGBB`` → Win32 COLORREF（0x00BBGGRR）。"""
    try:
        h = hex_color.strip().lstrip("#")
        if len(h) == 8:  # #AARRGGBB
            h = h[2:]
        if len(h) != 6:
            return None
        return (int(h[4:6], 16) << 16) | (int(h[2:4], 16) << 8) | int(h[0:2], 16)
    except (TypeError, ValueError):
        return None


def apply_titlebar_theme(widget, dark: bool | None = None) -> bool:
    """让**原生**标题栏跟随启动器主题（浅色主题给浅色栏）。成功返回 True。

    ``dark=None`` 时读当前主题；显式传 ``True/False`` 可强制。非 Windows /
    无 DWM 时静默跳过。必须在拿到原生句柄之后调用（``winId()`` 会创建它），
    放在 ``__init__`` 末尾或 ``showEvent`` 里都可以。
    """
    if sys.platform != "win32" or ctypes is None:
        return False
    if dark is None:
        dark = _theme_is_dark()
    try:
        hwnd = int(widget.winId())
        if hwnd == 0:
            return False
        value = ctypes.c_int(1 if dark else 0)
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            _DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if hr != 0:  # Win10 20H1 之前的属性号
            hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                _DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        # Win11：把栏底色/文字色也对到主题。失败（旧系统）就不管 —— 系统会按
        # dark 标志自己给一套合适的配色。
        try:
            from .theme import COLORS

            bg = COLORS.get("bg_app") or ("#1E1E1E" if dark else "#FFFFFF")
            fg = COLORS.get("text_main") or ("#E8E8EC" if dark else "#1A1A2E")
            for attr, hexv in ((_DWMWA_CAPTION_COLOR, bg), (_DWMWA_TEXT_COLOR, fg)):
                ref = _colorref(hexv)
                if ref is None:
                    continue
                c = ctypes.c_int(ref)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(c), ctypes.sizeof(c)
                )
        except Exception:  # noqa: BLE001 - 配色是锦上添花，失败不影响可用性
            pass
        return hr == 0
    except Exception:
        return False


def enable_dark_titlebar(widget, dark: bool | None = None) -> bool:
    """兼容旧名 —— 实际行为已是「跟随主题」。新代码请用 ``apply_titlebar_theme``。"""
    return apply_titlebar_theme(widget, dark)


# ── Themed message-box helpers (replace raw QMessageBox) ──────────────────
# QMessageBox uses the OS-native title bar which is white on dark theme.
# These helpers build lightweight QDialogs with theme-matched title bars so all
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

    apply_titlebar_theme(dlg)
    result = dlg.exec()
    picked = clicked[0]
    # round-217：QDialog 以 parent 为父，exec() 之后 C++ 对象仍然挂在父窗口
    # 下面（只是隐藏）。原来没有回收，确认框点得越多、父窗口底下累积的隐藏
    # 对话框就越多（每个还带图标/按钮/布局）。这里用完即删。
    dlg.deleteLater()
    if result and picked:
        return picked
    return None


def confirm(parent, title: str, text: str, detail: str = "", **kw) -> bool:
    """Themed Yes/No confirmation dialog. Returns True if user clicked 'Yes'."""
    return _msgbox(parent, title, text, detail, icon="warning",
                   buttons=("No", "Yes")) == "Yes"


def ask(parent, title: str, text: str, buttons: tuple[str, ...],
        detail: str = "", icon: str = "warning") -> str | None:
    """round-168：带自定义按钮文案的主题确认框（取消任务 / 退出确认用）。

    最后一个按钮是默认（accent）。返回被点击按钮的文案；直接关闭返回 None。
    """
    return _msgbox(parent, title, text, detail, icon=icon, buttons=buttons)


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
    apply_titlebar_theme(dlg)
    ok = bool(dlg.exec())
    files = dlg.selectedFiles() if ok else []
    dlg.deleteLater()      # round-217：同 _msgbox，别把文件对话框留在父窗口下
    if ok:
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
    ok = bool(d.exec())
    sel = d.selectedFiles() if ok else []
    d.deleteLater()        # round-217
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

    apply_titlebar_theme(dlg)
    ok = dlg.exec() == 1
    value = edit.text()
    dlg.deleteLater()      # round-217
    return value, ok


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
    apply_titlebar_theme(dlg)
    ok = bool(dlg.exec())
    picked = dlg.selectedColor().name() if ok else ""
    dlg.deleteLater()      # round-217
    return picked


def warn(parent, title: str, text: str, detail: str = "", **kw) -> None:
    """Themed warning dialog (OK only)."""
    _msgbox(parent, title, text, detail, icon="warning", buttons=("OK",))


def info(parent, title: str, text: str, detail: str = "", **kw) -> None:
    """Themed modal info dialog (data loss / step-by-step guidance)."""
    _msgbox(parent, title, text, detail, icon="info", buttons=("OK",))


def _find_toast_host(parent):
    """向上找**最近**的带 ``show_toast`` 的祖先（round-195）。

    原来只看 ``parent.window()`` —— 弹窗里没有浮层能力时会退化成模态框。
    round-195 起实例编辑 / 体检 / 增强包都改成了**页内面板**：页内面板的
    ``window()`` 是主窗口（有浮层 ✓），但同一个面板被塞进弹窗壳时
    ``window()`` 又是对话框 → 同样的代码在"页内"能弹浮层、在"弹窗"弹模态框，
    **两态行为不一致**。

    现在从 parent 沿 parent 链往上找第一个有 ``show_toast`` 的对象：
    页内面板 → 主窗口 ✓；弹窗壳 → 壳 → 主窗口 ✓（都能用浮层）。
    """
    seen = 0
    obj = parent
    while obj is not None and seen < 40:
        show = getattr(obj, "show_toast", None)
        if callable(show):
            return show
        obj = obj.parent()
        seen += 1
    return None


def toast(parent, title: str, text: str = "", duration: int = 3200) -> None:
    """Non-blocking light toast (round-75 弹窗收敛).

    Delegates to the main window's floating toast when available; falls back
    to a modal info box for windowless/standalone contexts.
    """
    show = _find_toast_host(parent)
    if show is not None:
        show(title, text, duration=duration)
    else:
        info(parent, title, text)