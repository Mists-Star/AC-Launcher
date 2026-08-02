"""
Design system for the AC Launcher UI — Light / Dark dual theme.

Default: Light theme (matches Ardot white-background design).
Toggle via set_theme_mode("light" | "dark") or config key "theme_mode".

The QSS template is token-driven — switching COLORS dict re-generates all styles.

Radii: card 12 | big 16 | btn 10 | small 6  (matched to Ardot: radius/radiusSm/radiusLg)
"""
from string import Template
import os as _os_module

# PySide6 is already initialised by the time any UI module imports this file.
from PySide6.QtWidgets import QApplication, QFrame
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen

# ---- Theme presets -------------------------------------------------------

THEME_LIGHT = {
    # surfaces (white / warm gray canvas)
    "bg_app":       "#FFFFFF",
    "bg_panel":     "#F8F9FA",
    "bg_card":      "#FFFFFF",
    "bg_hover":     "#F0F1F3",
    "bg_input":     "#F8F9FA",

    # brand (violet accent, same in both themes)
    "accent":       "#7C3AED",
    "accent_hover": "#8B5CF6",
    "accent_press": "#6D28D9",
    "accent_soft":  "#EDE9FE",   # light violet tint

    # text hierarchy (dark-on-light)
    "text_main":    "#1A1A2E",
    "text_sub":     "#6B7280",
    "text_disabled":"#9CA3AF",
    "text_accent":  "#7C3AED",

    # borders
    "border":       "#E5E7EB",
    "border_light": "#D1D5DB",
    "border_focus": "#7C3AED",

    # functional
    "danger":       "#EF4444",
    "success":      "#22C55E",
    "info":         "#3B82F6",
    "warn":         "#F59E0B",

    # shadow
    "shadow_card":  "0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.05)",
}

THEME_DARK = {
    # surfaces (dark → violet-tinted neutrals)
    "bg_app":       "#1E1E1E",
    "bg_panel":     "#2A2A2E",
    "bg_card":      "#2A2A2E",
    "bg_hover":     "#33333A",
    "bg_input":     "#232327",

    # brand
    "accent":       "#7C3AED",
    "accent_hover": "#8B5CF6",
    "accent_press": "#6D28D9",
    "accent_soft":  "#2A2140",

    # text hierarchy (light-on-dark)
    "text_main":    "#E5E5E5",
    "text_sub":     "#9CA3B0",
    "text_disabled":"#6B7280",
    "text_accent":  "#8B5CF6",

    # borders
    "border":       "#3A3A40",
    "border_light": "#4B4B52",
    "border_focus": "#8B5CF6",

    # functional
    "danger":       "#EF4444",
    "success":      "#22C55E",
    "info":         "#3B82F6",
    "warn":         "#F59E0B",

    # shadow
    "shadow_card":  "0 1px 3px rgba(0,0,0,0.45), 0 1px 2px rgba(0,0,0,0.35)",
}

# Active token table (default: LIGHT — matches user's Ardot white-bg design)
COLORS = dict(THEME_LIGHT)
_theme_mode = "light"

# Active design tokens (override-able via theme packs)
RADII = {"card": 12, "big": 16, "btn": 10, "small": 6}
FONTS = {"sm": 12, "md": 14, "lg": 16, "xl": 20}
FONT_FAMILY_BASE = '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'
FONT_FAMILY = FONT_FAMILY_BASE
# Currently applied theme pack id ("" = none)
_theme_pack_id = ""


def set_theme_mode(mode: str) -> None:
    """Switch between 'light' and 'dark'. Regenerates COLORS in-place."""
    global _theme_mode
    _theme_mode = mode
    COLORS.copy()  # no-op placeholder for future signal
    if mode == "dark":
        COLORS.update(THEME_DARK)
    else:
        COLORS.update(THEME_LIGHT)


def get_theme_mode() -> str:
    return _theme_mode


def set_accent_color(hex_color: str) -> None:
    """Update accent color tokens in-place. Does NOT regenerate QSS (caller must)."""
    COLORS["accent"] = hex_color
    # Derive hover/press/soft variants from the base accent
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    def _lighten(factor: float) -> str:
        return f"#{min(255, int(r + (255 - r) * factor)):02x}" \
               f"{min(255, int(g + (255 - g) * factor)):02x}" \
               f"{min(255, int(b + (255 - b) * factor)):02x}"
    def _darken(factor: float) -> str:
        return f"{max(0, int(r * factor)):02x}{max(0, int(g * factor)):02x}{max(0, int(b * factor)):02x}"
    COLORS["accent_hover"] = _lighten(0.2)
    COLORS["accent_press"] = _darken(0.85)
    COLORS["accent_soft"] = f"{_darken(0.95)}22"  # very faint tint with alpha
    COLORS["text_accent"] = _lighten(0.15)
    COLORS["border_focus"] = hex_color

R_CARD = 12
R_BIG = 16
R_BTN = 10
R_SMALL = 6

FONT_FAMILY = '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'
F_SM, F_MD, F_LG, F_XL = 12, 14, 16, 20


def _sync_radii() -> None:
    """Recompute module-level R_* constants from the RADII dict."""
    global R_CARD, R_BIG, R_BTN, R_SMALL
    R_CARD = RADII.get("card", 12)
    R_BIG = RADII.get("big", 16)
    R_BTN = RADII.get("btn", 10)
    R_SMALL = RADII.get("small", 6)


def _sync_fonts() -> None:
    """Recompute module-level F_* / FONT_FAMILY from the FONTS dict."""
    global F_SM, F_MD, F_LG, F_XL, FONT_FAMILY
    F_SM = FONTS.get("sm", 12)
    F_MD = FONTS.get("md", 14)
    F_LG = FONTS.get("lg", 16)
    F_XL = FONTS.get("xl", 20)
    FONT_FAMILY = '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'

# --------------------------------------------------------------------------
# Theme packs — player-customizable token overrides (direction C, 2026-08-01)
#
# A theme pack is a JSON file like:
#   {
#     "id": "control",
#     "name": "控制中枢",
#     "mode": "dark",                 # base mode: "light" | "dark"
#     "colors": { "accent": "#00E5FF", ... },   # any COLORS token
#     "radii":  { "card": 14, ... },
#     "fonts":  { "md": 15, ... }
#   }
# Packs live in <data_dir>/themes/*.json. apply_theme_pack() merges the
# overrides on top of the built-in light/dark token table, then the QSS
# cache is invalidated so the next apply_qss() rebuilds everything.
# --------------------------------------------------------------------------
import json as _json

THEME_PACK_DIR_NAME = "themes"

# Built-in "控制中枢" (Control Center) pack — the flagship dark/neon theme
# that anchors AC's "Absolute Controller" narrative (direction A).
BUILTIN_THEME_PACKS = {
    "control": {
        "id": "control",
        "name": "控制中枢",
        "name_en": "Control Center",
        "mode": "dark",
        "colors": {
            "bg_app":        "#0B0E14",
            "bg_panel":      "#111722",
            "bg_card":       "#141B28",
            "bg_hover":      "#1A2332",
            "bg_input":      "#0F141E",
            "accent":        "#00E5FF",
            "accent_hover":  "#33EAFF",
            "accent_press":  "#00B8CC",
            "accent_soft":   "#0E2A33",
            "text_main":     "#E6F0F5",
            "text_sub":      "#8FA6B5",
            "text_disabled": "#5A6B77",
            "text_accent":   "#00E5FF",
            "border":        "#1E2938",
            "border_light":  "#2B3B4D",
            "border_focus":  "#00E5FF",
            "danger":        "#FF5370",
            "success":       "#2ED47A",
            "info":          "#4DA3FF",
            "warn":          "#FFB020",
            "shadow_card":   "0 2px 8px rgba(0,0,0,0.5), 0 1px 2px rgba(0,0,0,0.4)",
        },
        "radii": {"card": 14, "big": 18, "btn": 10, "small": 6},
    },
    # "晨光" light pack — demonstrates the pack system also works on light.
    "morning": {
        "id": "morning",
        "name": "晨光",
        "name_en": "Morning",
        "mode": "light",
        "colors": {
            "accent":       "#0EA5E9",
            "accent_hover": "#38BDF8",
            "accent_press": "#0284C7",
            "accent_soft":  "#E0F2FE",
            "text_main":    "#0F172A",
            "text_sub":     "#64748B",
            "border":       "#E2E8F0",
            "border_focus": "#0EA5E9",
            "text_accent":  "#0284C7",
        },
        "radii": {"card": 16, "big": 20, "btn": 12, "small": 8},
    },
}


def get_theme_pack_dir() -> str:
    from .paths import get_data_dir
    d = _os_module.path.join(get_data_dir(), THEME_PACK_DIR_NAME)
    _os_module.makedirs(d, exist_ok=True)
    return d


def list_theme_packs() -> list[dict]:
    """Built-in packs + packs from <data>/themes/*.json (user order wins)."""
    packs = [dict(p) for p in BUILTIN_THEME_PACKS.values()]
    d = get_theme_pack_dir()
    try:
        for fn in sorted(_os_module.listdir(d)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(_os_module.path.join(d, fn), "r", encoding="utf-8") as f:
                    p = _json.load(f)
                if isinstance(p, dict) and p.get("id"):
                    packs.append(p)
            except Exception:
                continue
    except OSError:
        pass
    return packs


def find_theme_pack(pack_id: str) -> dict | None:
    for p in list_theme_packs():
        if p.get("id") == pack_id:
            return p
    return None


def import_theme_pack_file(path: str) -> dict:
    """Copy a .json theme pack into <data>/themes/ and return it."""
    import shutil as _shutil
    with open(path, "r", encoding="utf-8") as f:
        pack = _json.load(f)
    if not isinstance(pack, dict) or not pack.get("id"):
        raise ValueError("主题包格式无效：缺少 id")
    safe_id = "".join(c for c in str(pack["id"]) if c.isalnum() or c in "-_")
    dest = _os_module.path.join(get_theme_pack_dir(), f"{safe_id}.json")
    _shutil.copyfile(path, dest)
    return pack


def export_theme_pack(pack: dict, dest_path: str) -> None:
    """Write a pack (built-in or user) to a single .json file for sharing."""
    with open(dest_path, "w", encoding="utf-8") as f:
        _json.dump(pack, f, ensure_ascii=False, indent=2)


def apply_theme_pack(pack: dict | None) -> None:
    """Apply a theme pack's token overrides on top of the base light/dark
    table. Passing None clears the pack override (back to built-in theme)."""
    global _theme_pack_id, _QSS_CACHE
    _theme_pack_id = pack.get("id", "") if pack else ""
    # Reset to base table, then merge pack overrides.
    if _theme_mode == "dark":
        COLORS.update(THEME_DARK)
    else:
        COLORS.update(THEME_LIGHT)
    if pack:
        mode = pack.get("mode")
        if mode == "dark":
            COLORS.update(THEME_DARK)
        elif mode == "light":
            COLORS.update(THEME_LIGHT)
        COLORS.update(pack.get("colors", {}))
        RADII.update(pack.get("radii", {}))
        FONTS.update(pack.get("fonts", {}))
    _sync_radii()
    _sync_fonts()
    _QSS_CACHE = {}  # invalidate so next apply_qss() rebuilds


def get_active_theme_pack_id() -> str:
    return _theme_pack_id

# ---- QSS template ($token substitution) ------------------------------------
QSS_TEMPLATE = Template("""
/* ---- global reset ---- */
QWidget {
    background: $bg_app;
    color: $text_main;
    font-family: $font_family;
    font-size: ${f_md}px;
}
QMainWindow {
    background: $bg_app;
    /* no border — frameless windows must be edge-to-edge */
}

/* ---- CRITICAL: dialogs must NOT be white ---- */
QDialog {
    background: $bg_app;
    color: $text_main;
    /* no border — FramelessHelper handles chrome */
}

/* ---- generic surfaces ---- */
/* 用 QFrame[cls="card"] 明确限定：光 [cls="card"] 会被下面更具体的
   `QFrame { background: transparent; }` 规则覆盖 → 卡片失去背景/圆角，
   变成黑框直角（用户反馈"数值统计黑框没圆角"）。
   保留无类型前缀的 [cls="card"] 作为非 QFrame 容器（QWidget 等）的兜底。 */
QFrame[cls="card"] {
    background: $bg_card;
    border: 1px solid $border;
    border-radius: ${r_card}px;
}
QFrame[cls="card"]:hover {
    background: $bg_hover;
    border: 1px solid $border_light;
}
[cls="card"] {
    background: $bg_card;
    border: 1px solid $border;
    border-radius: ${r_card}px;
}
[cls="card"]:hover {
    background: $bg_hover;
    border: 1px solid $border_light;
}

/* 大字授权码（登录对话框显示 user_code） */
[cls="code"] {
    color: $accent;
    background: $accent_soft;
    border: 2px dashed $accent;
    border-radius: ${r_card}px;
    padding: 12px 16px;
    font-size: 36px;
    font-weight: 800;
    font-family: 'Consolas', 'Cascadia Mono', 'Courier New', monospace;
    letter-spacing: 4px;
}
QFrame {
    background: transparent;
    border: none;
}

/* ---- labels ---- */
QLabel {
    background: transparent;
    color: $text_main;
}
QLabel[cls="sub"] {
    color: $text_sub;
    font-size: ${f_sm}px;
}
QLabel[cls="title"] {
    font-size: ${f_xl}px;
    font-weight: 700;
    color: $text_main;
}
QLabel[cls="big"] {
    font-size: ${f_lg}px;
    font-weight: 600;
    color: $text_main;
}
QLabel[cls="group"] {
    font-size: ${f_lg}px;
    font-weight: 700;
    color: $text_main;
    padding: 4px 2px;
    border-bottom: 2px solid $accent_soft;
    margin-bottom: 2px;
}

/* ---- push buttons ---- */
QPushButton {
    background: $bg_card;
    color: $text_main;
    border: 1px solid $border;
    border-radius: ${r_btn}px;
    padding: 8px 16px;
    font-size: ${f_md}px;
}
QPushButton:hover {
    background: $bg_hover;
    border-color: $border_light;
}
QPushButton:pressed {
    background: $border;
}
QPushButton:disabled {
    color: $text_disabled;
    background: $bg_input;
    border-color: $border;
}
/* primary accent button */
QPushButton[cls="accent"] {
    background: $accent;
    border: none;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton[cls="accent"]:hover { background: $accent_hover; }
QPushButton[cls="accent"]:pressed { background: $accent_press; }
/* danger outline */
QPushButton[cls="danger"] {
    background: transparent;
    border: 1px solid $danger;
    color: $danger;
}
QPushButton[cls="danger"]:hover { background: rgba(239,68,68,0.08); }
/* segmented control button (新手 / 进阶) */
QPushButton[cls="seg"] {
    background: $bg_input;
    border: 1px solid $border;
    color: $text_sub;
    border-radius: 0;
}
QPushButton[cls="seg"]:first { border-top-left-radius: ${r_small}px; border-bottom-left-radius: ${r_small}px; }
QPushButton[cls="seg"]:last { border-top-right-radius: ${r_small}px; border-bottom-right-radius: ${r_small}px; }
QPushButton[cls="seg"]:checked {
    background: $accent;
    color: #FFFFFF;
    border-color: $accent;
    font-weight: 600;
}
QPushButton[cls="seg"]:hover:!checked { background: $bg_hover; }

/* ---- line edit / combo / spin ---- */
QLineEdit, QComboBox, QSpinBox {
    background: $bg_input;
    border: 1px solid $border;
    border-radius: ${r_small}px;
    padding: 6px 10px;
    color: $text_main;
    font-size: ${f_md}px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 2px solid $border_focus;
    padding: 5px 9px;  /* compensate for thicker border */
}
QLineEdit:disabled { color: $text_disabled; background: $bg_app; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border: none;
}
QComboBox::dropdown {
    background: $bg_card;
    border: 1px solid $border;
}
QComboBox QAbstractItemView {
    background: $bg_card;
    color: $text_main;
    selection-background-color: $accent_soft;
    selection-color: $accent;
    border: 1px solid $border;
    outline: none;
    padding: 4px 0;
}
QComboBox QAbstractItemView::item {
    min-height: 28px;
    padding: 4px 12px;
    color: $text_main;
    background: $bg_card;
}
QComboBox QAbstractItemView::item:hover {
    background: $bg_hover;
    color: $text_main;
}
QComboBox QAbstractItemView::item:selected {
    background: $accent_soft;
    color: $accent;
}
QComboBox:on { border: 2px solid $border_focus; }

/* ---- slider (RAM) ---- */
QSlider::groove:horizontal {
    height: 6px;
    background: $border;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: $accent;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -6px 0;
    background: #FFFFFF;
    border: 2px solid $accent;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    background: $accent_hover;
    border-color: $accent_press;
}

/* ---- list / navigation ---- */
QListWidget {
    background: $bg_panel;
    border: none;
    outline: 0;
    border-right: 1px solid $border;
}
QListWidget::item {
    color: $text_sub;
    padding: 10px 16px;
    border-radius: ${r_small}px;
}
QListWidget::item:hover { background: $bg_hover; color: $text_main; }
QListWidget::item:selected {
    background: $accent_soft;
    color: $accent;
    font-weight: 600;
    border-left: 3px solid $accent;
}

/* 左侧导航分组标题（不可选灰字，功能区分化） */
[cls="nav-group"] {
    color: $text_sub;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 2px;
    background: transparent;
    border: none;
    padding: 8px 0 4px 8px;
}

/* ---- scroll area ---- */
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical {
    background: $bg_app;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: $border_light;
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: $text_disabled; }
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }

/* ---- progress bar ---- */
QProgressBar {
    background: $border;
    border-radius: ${r_small}px;
    height: 8px;
    text-align: center;
    color: $text_sub;
    font-size: ${f_sm}px;
    border: none;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: ${r_small}px;
}

/* ---- check box ---- */
QCheckBox { background: transparent; color: $text_main; spacing: 8px; }
QCheckBox::indicator {
    width: 18px; height: 18px;
    border: 2px solid $border;
    border-radius: 4px;
    background: $bg_card;
}
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QCheckBox::indicator:hover { border-color: $border_light; }

/* ---- radio button ---- */
QRadioButton {
    background: transparent;
    color: $text_main;
    spacing: 8px;
}
QRadioButton::indicator {
    width: 18px; height: 18px;
    border: 2px solid $border;
    border-radius: 9px;
    background: $bg_card;
}
QRadioButton::indicator:checked {
    background: $accent;
    border-color: $accent;
}
QRadioButton::indicator:hover { border-color: $border_light; }

/* ---- group box (settings sections) ---- */
QGroupBox {
    background: $bg_card;
    border: 1px solid $border;
    border-radius: ${r_card}px;
    padding: 20px 16px 16px 16px;
    margin-top: 12px;
    font-size: ${f_lg}px;
    font-weight: 600;
    color: $text_main;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: $text_main;
}

/* ---- text edit (JVM args) ---- */
QTextEdit {
    background: $bg_input;
    border: 1px solid $border;
    border-radius: ${r_small}px;
    padding: 8px 10px;
    color: $text_main;
    font-family: "Consolas", "Cascadia Code", monospace;
    font-size: ${f_sm}px;
}
QTextEdit:focus { border: 2px solid $border_focus; }

/* ---- tooltip ---- */
QToolTip {
    background: $text_main;
    color: $bg_panel;
    border: none;
    border-radius: ${r_small}px;
    padding: 4px 10px;
    font-size: ${f_sm}px;
}

/* ---- status bar ---- */
QStatusBar {
    background: $bg_panel;
    color: $text_sub;
    border-top: 1px solid $border;
    font-size: ${f_sm}px;
}

/* ---- separator line helper ---- */
[cls="separator"] {
    background: $border;
    max-height: 1px;
    min-height: 1px;
}

/* ---- themed container surfaces (auto-refresh on theme switch via cls) ----
   These use the `cls` property instead of baked per-widget stylesheets so
   that re-applying the global QSS (app.setStyleSheet(build_qss())) re-skins
   every persistent widget when the light/dark mode changes. */
[cls="titlebar"] {
    background: $bg_panel;
    border-bottom: 1px solid $border;
}
[cls="page-header"] {
    background: $bg_panel;
    border-bottom: 1px solid $border;
    color: $text_main;
    font-size: ${f_xl}px;
    font-weight: 700;
    padding: 0 20px;
}
[cls="page-footer"] {
    background: $bg_panel;
    border-top: 1px solid $border;
}
[cls="surface"] {
    background: $bg_panel;
    border: 1px solid $border;
    border-radius: 12px;
}
QPushButton[cls="surface"] {
    text-align: left;
    padding: 0;
}
QPushButton[cls="surface"]:hover {
    border: 2px solid $accent;
}
[cls="row"] {
    background: $bg_panel;
    border: 1px solid $border;
    border-radius: 10px;
}
QPushButton[cls="row"] {
    text-align: left;
    padding: 0;
}
QPushButton[cls="row"]:hover {
    border: 2px solid $accent;
}
QPushButton[cls="icon-btn"] {
    background: transparent;
    border: none;
    border-radius: 8px;
}
QPushButton[cls="icon-btn"]:hover {
    background: $bg_hover;
}
[cls="tile"] {
    background: $accent_soft;
    border-radius: 12px;
}
[cls="pill"] {
    background: $bg_input;
    color: $text_sub;
    border: 1px solid $border;
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 11px;
}
[cls="loader-card"] {
    background: $bg_card;
    border: 1px solid $border;
    border-radius: 10px;
}
[cls="loader-card-on"] {
    background: $accent_soft;
    border: 2px solid $accent;
    border-radius: 10px;
}
[cls="pcl2-top"] {
    background: $bg_panel;
    border-bottom: 1px solid $border;
}
QPushButton[cls="pcl2-pill"] {
    background: transparent;
    color: $text_sub;
    border: none;
    border-radius: 8px;
    padding: 6px 18px;
    font-size: 13px;
}
QPushButton[cls="pcl2-pill"]:hover {
    background: $bg_hover;
    color: $text_main;
}
QPushButton[cls="pcl2-pill"]:checked {
    background: $accent_soft;
    color: $accent;
    font-weight: 600;
}
""")


def build_qss() -> str:
    # Cache per (theme mode, accent) so repeated toggles don't re-substitute.
    key = (_theme_mode, COLORS.get("accent"))
    cached = _QSS_CACHE.get(key)
    if cached is not None:
        return cached
    qss = QSS_TEMPLATE.safe_substitute(
        **COLORS,
        font_family=FONT_FAMILY,
        f_sm=F_SM, f_md=F_MD, f_lg=F_LG, f_xl=F_XL,
        r_card=R_CARD, r_big=R_BIG, r_btn=R_BTN, r_small=R_SMALL,
    )
    _QSS_CACHE[key] = qss
    return qss


# ---- Coalesced global-style applier ---------------------------------------
# app.setStyleSheet() forces a full repolish of the WHOLE widget tree (every
# stacked page + every dialog). On a launcher with hundreds of widgets that is
# ~300 ms. We (a) cache the QSS string, (b) skip when nothing changed, and
# (c) debounce so several calls inside one event-loop tick collapse into a
# single setStyleSheet() — e.g. theme toggle + dialog "OK" used to restyle 3x.
_QSS_CACHE: dict = {}
_QSS_APPLIED: str | None = None
_QSS_TIMER: "QTimer | None" = None


def apply_qss() -> None:
    """Re-apply the global theme stylesheet (cached + change-guarded + debounced)."""
    global _QSS_APPLIED, _QSS_TIMER
    app = QApplication.instance()
    if app is None:
        return
    qss = build_qss()
    # Nothing changed since last applied → no work needed.
    if qss == _QSS_APPLIED and (_QSS_TIMER is None or not _QSS_TIMER.isActive()):
        return
    # A coalesced apply is already pending; it will pick up the latest qss.
    if _QSS_TIMER is not None and _QSS_TIMER.isActive():
        return
    _QSS_TIMER = QTimer(app)
    _QSS_TIMER.setSingleShot(True)

    def _do() -> None:
        global _QSS_APPLIED, _QSS_TIMER
        _QSS_TIMER = None
        latest = build_qss()
        if latest == _QSS_APPLIED:
            return
        _QSS_APPLIED = latest
        QApplication.instance().setStyleSheet(latest)

    _QSS_TIMER.timeout.connect(_do)
    _QSS_TIMER.start(0)


class RoundedCard(QFrame):
    """QFrame whose background is painted with a rounded rect in paintEvent.

    Qt's stylesheet ``border-radius`` does NOT clip the *background* of plain
    QFrame/QWidget containers (only the border) — cards render as sharp
    rectangles. Drawing the card ourselves guarantees the rounded corners.
    Uses the same token colors as ``[cls="card"]`` so it blends with the theme.

    ``fill`` may be None (theme bg_card + border), a QColor, or a QLinearGradient
    (gradient cards skip the border — they have their own visual edge).
    """

    def __init__(self, radius: int | None = None, parent=None, fill=None,
                 border_color=None, border_width: int = 1,
                 accent_border: int = 0):
        super().__init__(parent)
        self._radius = radius if radius is not None else 12
        self._fill = fill
        self._border_color = border_color
        self._border_width = border_width
        self._accent_border = accent_border  # px accent stripe on the left
        # 容器透明 + 自绘背景（不再依赖 QSS background）
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_radius(self, r: int) -> None:
        self._radius = r
        self.update()

    def set_fill(self, fill) -> None:
        self._fill = fill
        self.update()

    def set_border(self, color, width: int = 1) -> None:
        self._border_color = color
        self._border_width = width
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        brush = self._fill if self._fill is not None else QColor(COLORS["bg_card"])
        p.fillPath(path, brush)
        # 左侧 accent 条（toast / 通知卡用）
        if self._accent_border > 0:
            stripe = QPainterPath()
            stripe.addRoundedRect(
                QRectF(self.rect().left(), self.rect().top(),
                       self._accent_border, self.rect().height()),
                2, 2)
            stripe = stripe.intersected(path)
            p.fillPath(stripe, QColor(COLORS["accent"]))
        bc = self._border_color if self._border_color is not None else COLORS["border"]
        bw = self._border_width
        if self._fill is None or bw > 1 or self._border_color is not None:
            # 渐变卡默认不画边框（自带视觉边界）；纯色卡画 1px；
            # 选中态（bw>1 或自定义色）始终画
            p.setPen(QPen(QColor(bc), bw))
            p.drawPath(path)
        p.end()


if __name__ == "__main__":
    qss = build_qss()
    print("QSS generated, length:", len(qss))
    print("sample:", qss[:120])
