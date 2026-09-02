"""Windows 系统级毛玻璃（Acrylic / Mica）—— 真毛玻璃，透出用户桌面。

实现参考：BlockHelm Launcher `NativeBackdrop.cs`（GPL-3.0，2026-08-13 研究）。
关键点（决定成败）：
1. ``DwmExtendFrameIntoClientArea(hwnd, margins=-1)`` —— 把 DWM 玻璃帧扩展到
   整个客户区。**没有这步，Acrylic 只作用于标题栏区域**。
2. ``DwmSetWindowAttribute(hwnd, 38, SystemBackdropType)`` —— Win11 22H2+：
   None=1 / Mica=2 / Acrylic(TransientWindow)=3 / Tabbed=4
3. Win10 1809+ 回退：``SetWindowCompositionAttribute ACCENT_ENABLE_ACRYLICBLURBEHIND(4)``
4. 窗口背景必须透明（Qt 侧 setAttribute(WA_TranslucentBackground)）

用法（Qt 侧）：
    from .win_acrylic import enable_acrylic, disable_acrylic
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    enable_acrylic(int(widget.winId()))          # 开
    disable_acrylic(int(widget.winId()), dark)   # 关（恢复实色）
"""
import sys

try:
    import ctypes
    from ctypes import wintypes
except ImportError:  # 非 Windows 无 ctypes.windll
    ctypes = None
    wintypes = None

if sys.platform == "win32" and ctypes is not None:
    _dwmapi = ctypes.windll.dwmapi
    _user32 = ctypes.windll.user32
else:
    _dwmapi = None
    _user32 = None


# DwmWindowAttribute（与 BlockHelm NativeBackdrop.cs 一致）
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWA_SYSTEMBACKDROP_TYPE = 38

# DwmSystemBackdropType
_DWMSBT_NONE = 1
_DWMSBT_MAINWINDOW = 2   # Mica
_DWMSBT_TRANSIENTWINDOW = 3  # Acrylic

# DwmWindowCornerPreference
_DWMWCP_ROUND = 2

# 无边框色标记（Win11 23H2+）
_BORDER_COLOR_NONE = 0xFFFFFFFE

# ACCENT (Win10 SetWindowCompositionAttribute)
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


class _MARGINS(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_int), ("Right", ctypes.c_int),
                ("Top", ctypes.c_int), ("Bottom", ctypes.c_int)]


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),  # ABGR
        ("AnimationId", ctypes.c_int),
    ]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    if _dwmapi is None:
        return False
    try:
        v = ctypes.c_int(value)
        return _dwmapi.DwmSetWindowAttribute(
            hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0
    except Exception:
        return False


def _extend_frame(hwnd: int) -> bool:
    """把 DWM 玻璃帧扩展到整个客户区（margins=-1）—— Acrylic 铺满的关键。"""
    if _dwmapi is None:
        return False
    try:
        m = _MARGINS(-1, -1, -1, -1)
        return _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m)) == 0
    except Exception:
        return False


def _acrylic_win10(hwnd: int) -> bool:
    """Win10 1809+ 回退：SetWindowCompositionAttribute ACCENT_ENABLE_ACRYLICBLURBEHIND。"""
    if _user32 is None:
        return False
    try:
        # GradientColor = ABGR: alpha 0xCC (204) + white → 白 tint
        accent = _ACCENT_POLICY(_ACCENT_ENABLE_ACRYLICBLURBEHIND, 2, 0xCCFFFFFF, 0)
        data = _WINCOMPATTRDATA(19, ctypes.byref(accent), ctypes.sizeof(accent))
        return bool(_user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)))
    except Exception:
        return False


def enable_acrylic(widget, dark: bool = False) -> bool:
    """把 QWidget 变成系统级 Acrylic（透桌面模糊）。

    widget 需已 setAttribute(Qt.WA_TranslucentBackground, True)。
    完整调用链（按 BlockHelm NativeBackdrop.cs）：
      ExtendFrameIntoClientArea(-1) → 深色标题栏 → 圆角 → 边框透明 → SystemBackdrop
    """
    if sys.platform != "win32" or ctypes is None:
        return False
    try:
        hwnd = int(widget.winId())
        if hwnd == 0:
            return False
        _extend_frame(hwnd)
        _set_attr(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
        _set_attr(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
        _set_attr(hwnd, _DWMWA_BORDER_COLOR, _BORDER_COLOR_NONE)
        if _set_attr(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_TRANSIENTWINDOW):
            return True
        return _acrylic_win10(hwnd)
    except Exception:
        return False


def disable_acrylic(widget, dark: bool = False) -> None:
    """关闭 Acrylic：SystemBackdrop=None + 恢复实色背景（light=白, dark=#151515）。

    与 BlockHelm 的 ApplyCore 对称：关闭时 DWM 不模糊，窗口背景改回实色。
    """
    if sys.platform != "win32" or ctypes is None:
        return
    try:
        hwnd = int(widget.winId())
        if hwnd == 0:
            return
        _set_attr(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_NONE)
        # 深色主题关 Acrylic 时的实色 = #151515（BlockHelm GetOpaqueWindowBackgroundColor）
        from PySide6.QtGui import QColor
        from PySide6.QtCore import Qt
        widget.setAttribute(Qt.WA_TranslucentBackground, False)
        # 恢复不透明背景需要重新设置 palette / repolish
        widget.update()
    except Exception:
        pass
