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
    "bg_btn":       "#FFFFFF",   # round-44 按钮背景（light 同 bg_card）
    "bg_frost":     "#A8FFFFFF",   # frosted-glass translucent card (alpha 168)
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

    # slider knob: white heart both themes (contrast against accent ring);
    # kept tokenized so theme packs can override it.
    "slider_knob": "#FFFFFF",
}

THEME_DARK = {
    # surfaces (dark → violet-tinted neutrals)
    "bg_app":       "#1E1E1E",
    "bg_panel":     "#2A2A2E",
    "bg_card":      "#2A2A2E",
    # round-44 按钮背景：dark 下区分面板（#33333A），与 bg_card 同色导致按钮
    # 边框融背景，文字看不清。light 主题保持白底。
    "bg_btn":       "#33333A",
    "bg_frost":     "#942A2C38",   # frosted-glass translucent card (alpha 148)
    "bg_hover":     "#3F3F47",
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

    # slider knob: white heart both themes (contrast against accent ring)
    "slider_knob": "#FFFFFF",
}

# Active token table (default: LIGHT — matches user's Ardot white-bg design)
COLORS = dict(THEME_LIGHT)
_theme_mode = "light"
# round-49 修复「改选项把强调色拉回紫色」：记录用户自定义的 accent。set_theme_mode /
# apply_theme_pack 重置基础色表后必须重新套用自定义 accent，否则 accent 恒被
# THEME_LIGHT/THEME_DARK 里的 #7C3AED 覆盖。None = 未自定义（用内置紫）。
_custom_accent: str | None = None

# ── 玻璃拟态（round-52 恢复；round-32 曾拍板删除）─────────────────────
# 曾经做过：半透明卡片+渐变底（round-23~28）、系统 Acrylic 透桌面
# （round-30~31，常用方案）。round-32 暂时移除；round-51 先恢复
# 系统 Acrylic（transparent_window 透底），round-52 恢复应用层半透明
# 卡片（$glassy token）。开启时容器走 bg_frost 半透明、按钮仍实色。
_frosted = False


def set_frosted(on: bool) -> None:
    """玻璃拟态开关（round-52 恢复，round-32~49 为 no-op）。

    开启：卡片/分组框走半透明 ``bg_frost``（透出 Acrylic 桌面模糊），
    按钮与导航仍实色（round-44 对比度不回退）。关闭：全部实色。
    需要配合系统 Acrylic（transparent_window）才有效果；无 Acrylic 时
    半透明卡片叠实色底仍可读（alpha 高），不做强制降级。
    """
    global _frosted
    on = bool(on)
    if on == _frosted:
        return
    _frosted = on
    _QSS_CACHE.clear()
    _notify_theme_change()


# ── 透底效果（round-51）：系统级 Acrylic 真毛玻璃时，应用层背景变半透明，
# ── 让 DWM 的桌面模糊透出来。关闭时恢复实色（round-32 的默认行为）。
_app_bg_translucent = False

# ── 壁纸透底（round-119）：壁纸是整窗背景，不是某一页的私有图层。页面容器
# ── 与窗口容器都必须让壁纸透出来，否则只有首页看得到。这里只把
# ── ``bg_app_frost``（QWidget/QMainWindow 的底色）调成半透明；卡片仍走
# ── 实色 ``$glassy``，文字依旧落在不透明底上，可读性不受影响。
# ── 对话框必须保持实色（独立顶层窗口，没有壁纸垫底），走 ``$bg_app_solid``。
_wallpaper_surface = False


def set_wallpaper_surface(on: bool) -> None:
    """Toggle the translucent app surface used while a wallpaper is active."""
    global _wallpaper_surface
    on = bool(on)
    if on == _wallpaper_surface:
        return
    _wallpaper_surface = on
    _QSS_CACHE.clear()
    _notify_theme_change()


def set_app_background_translucent(on: bool) -> None:
    """透底模式：应用层 QSS 背景改为半透明（否则 Acrylic 被实色盖住）。

    只影响 ``bg_app_frost``（QWidget/QMainWindow/QDialog 的底色），卡片等
    表面仍走 ``bg_frost``（实色），保证文字可读。
    """
    global _app_bg_translucent
    on = bool(on)
    if on == _app_bg_translucent:
        return
    _app_bg_translucent = on
    _QSS_CACHE.clear()
    _notify_theme_change()


def _to_translucent(hex_color: str, alpha: int) -> str:
    """把 #RRGGBB 转成 #AARRGGBB（alpha 0..255）。"""
    try:
        c = hex_color.lstrip("#")
        if len(c) != 6:
            return hex_color
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        return f"#{alpha:02X}{r:02X}{g:02X}{b:02X}"
    except Exception:
        return hex_color


def with_alpha(hex_color: str, alpha: int) -> str:
    """公开助手：#RRGGBB → #AARRGGBB（alpha 在前）。

    ⚠️ Qt 的 8 位 hex 是 **#AARRGGBB**（round-99 排查确认）：把 alpha 拼在
    末尾（`f"{accent}22"` = #RRGGBBAA）会被 Qt 当 AARRGGBB 解析成完全无关的
    颜色——紫 #7C3AED + "22" 会解析出 (58,237,20) 亮绿。页面里一切"淡色/
    半透明 accent"都必须走本函数，不要再手工拼末尾 alpha。
    """
    return _to_translucent(hex_color, alpha)


# Active design tokens (override-able via theme packs)
RADII = {"card": 12, "big": 16, "btn": 10, "small": 6, "icon": 8}
FONTS = {"xs": 11, "sm": 12, "md": 14, "lg": 16, "xl": 20}
FONT_FAMILY_BASE = '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'
FONT_FAMILY = FONT_FAMILY_BASE
# Currently applied theme pack id ("" = none)
_theme_pack_id = ""

# Theme-change listeners (e.g. title-bar icons that need re-rendering)
_theme_change_listeners: list = []


def on_theme_change(callback):
    """Register a callback invoked whenever the theme mode or pack changes."""
    if callback not in _theme_change_listeners:
        _theme_change_listeners.append(callback)


def _notify_theme_change():
    """Broadcast theme change to all registered listeners."""
    for cb in list(_theme_change_listeners):
        try:
            cb()
        except Exception:
            pass


def set_theme_mode(mode: str) -> None:
    """Switch between 'light' and 'dark'. Regenerates COLORS in-place."""
    global _theme_mode
    _theme_mode = mode
    COLORS.update(THEME_DARK if mode == "dark" else THEME_LIGHT)
    # round-49 修复「改选项把强调色拉回紫色」：重置基础色表后重新套用用户
    # 自定义 accent，避免 accent 被 THEME_LIGHT/DARK 的 #7C3AED 覆盖。
    if _custom_accent:
        _apply_accent(_custom_accent)
    # round-45 兜底：text_on_accent 只在 set_accent_color 里设置，若启动时
    # config 无 accent_color（旧版/被清）会缺失 → QSS 出现字面 $text_on_accent
    if "text_on_accent" not in COLORS:
        COLORS["text_on_accent"] = "#FFFFFF"
    _notify_theme_change()


def get_theme_mode() -> str:
    return _theme_mode


def set_accent_color(hex_color: str) -> None:
    """Update accent color tokens in-place. Does NOT regenerate QSS (caller must)."""
    global _custom_accent
    _custom_accent = hex_color
    _apply_accent(hex_color)


def _apply_accent(hex_color: str) -> None:
    """Derive all accent-family tokens from a single base hex and write them
    into COLORS. Used by set_accent_color and re-applied after any base-table
    reset (set_theme_mode / apply_theme_pack) so the user's custom accent
    survives option changes."""
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
    # round-99 修「改主题色后大片颜色变绿」：旧写法把 alpha 拼在末尾
    # （f"{_darken(0.95)}22" = #RRGGBBAA），Qt 按 #AARRGGBB 解析 → 紫 accent
    # 的"淡色"变成 (58,237,20) 亮绿，凡是引用 accent_soft / f"{accent}XX"
    # 的地方（卡片底、chip 选中、横幅渐变…）全是荧光绿/黄。必须 alpha 在前。
    COLORS["accent_soft"] = _to_translucent(hex_color, 0x22)  # faint accent film
    COLORS["text_accent"] = _lighten(0.15)
    COLORS["border_focus"] = hex_color
    # round-44 按钮文字自适应：accent 亮度低（深紫等）用白字，亮度高（浅色
    # 自定义主题）用深字——之前固定 #FFFFFF，用户把 accent 设成浅色时白字
    # 看不清（「新建实例」按钮在白色主题下看不清的根因）。
    _luma = (r * 299 + g * 587 + b * 114) / 1000
    COLORS["text_on_accent"] = "#1F2937" if _luma > 150 else "#FFFFFF"

R_CARD = 12
R_BIG = 16
R_BTN = 10
R_SMALL = 6
R_ICON = 8

FONT_FAMILY = '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'
F_XS, F_SM, F_MD, F_LG, F_XL = 11, 12, 14, 16, 20


def _sync_radii() -> None:
    """Recompute module-level R_* constants from the RADII dict."""
    global R_CARD, R_BIG, R_BTN, R_SMALL, R_ICON
    R_CARD = RADII.get("card", 12)
    R_BIG = RADII.get("big", 16)
    R_BTN = RADII.get("btn", 10)
    R_SMALL = RADII.get("small", 6)
    R_ICON = RADII.get("icon", 8)


def _sync_fonts() -> None:
    """Recompute module-level F_* / FONT_FAMILY from the FONTS dict."""
    global F_XS, F_SM, F_MD, F_LG, F_XL, FONT_FAMILY
    F_XS = FONTS.get("xs", 11)
    F_SM = FONTS.get("sm", 12)
    F_MD = FONTS.get("md", 14)
    F_LG = FONTS.get("lg", 16)
    F_XL = FONTS.get("xl", 20)
    FONT_FAMILY = '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'


def set_font_family(family: str) -> None:
    """全局界面字体（round-87 玩家可改字体）。empty = 恢复默认优先列表
    （Segoe UI → 微软雅黑 → 苹方）。改字体后必须失效 QSS 缓存（build_qss
    的缓存 key 不含字体），并同步 QApplication 默认字体兜底原生控件。
    """
    global FONT_FAMILY, _QSS_CACHE
    _QSS_CACHE = {}
    if family:
        FONT_FAMILY = f'"{family}", "Microsoft YaHei", "PingFang SC", sans-serif'
    else:
        FONT_FAMILY = FONT_FAMILY_BASE
    app = QApplication.instance()
    if app is not None:
        from PySide6.QtGui import QFont
        base = family or FONT_FAMILY_BASE.split('"')[1]  # 默认为 "Segoe UI"
        app.setFont(QFont(base))

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
    elif _custom_accent:
        # round-49：无主题包时，重置基础表后重新套用用户自定义 accent，
        # 否则 accent 又变回内置紫。
        _apply_accent(_custom_accent)
    _sync_radii()
    _sync_fonts()
    _QSS_CACHE = {}  # invalidate so next apply_qss() rebuilds
    _notify_theme_change()


def get_active_theme_pack_id() -> str:
    return _theme_pack_id

# ---- QSS template ($token substitution) ------------------------------------
QSS_TEMPLATE = Template("""
/* ---- global reset ---- */
QWidget {
    background: $bg_app_frost;
    color: $text_main;
    font-family: $font_family;
    font-size: ${f_md}px;
}
QMainWindow {
    background: $bg_app_frost;
    /* no border — frameless windows must be edge-to-edge */
}

/* ---- CRITICAL: dialogs must NOT be white ---- */
QDialog {
    background: $bg_app_solid;
    color: $text_main;
    /* no border — FramelessHelper handles chrome */
}

/* ---- generic surfaces ---- */
/* 用 QFrame[cls="card"] 明确限定：光 [cls="card"] 会被下面更具体的
   `QFrame { background: transparent; }` 规则覆盖 → 卡片失去背景/圆角，
   变成黑框直角（用户反馈"数值统计黑框没圆角"）。
   保留无类型前缀的 [cls="card"] 作为非 QFrame 容器（QWidget 等）的兜底。 */
QFrame[cls="card"] {
    background: $glassy;
    border: 1px solid $border;
    border-radius: ${r_card}px;
}
QFrame[cls="card"]:hover {
    background: $glassy;
    border: 1px solid $border_light;
}
[cls="card"] {
    background: $glassy;
    border: 1px solid $border;
    border-radius: ${r_card}px;
}
[cls="card"]:hover {
    background: $glassy;
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
    /* round-111 修：padding 不计入 QLabel.sizeHint（Qt 已知行为），
       布局只给字高 → 渲染溢出被下一个控件盖住（成就页分组标题被卡片压住）。
       间距已改由 ui_kit.group_label() 的 contentsMargins 承担，这里不再设。 */
}

/* ---- push buttons ---- */
QPushButton {
    background: $bg_frost;
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
    color: $text_on_accent;   /* round-44：随 accent 亮度自适应黑/白字 */
    font-weight: 600;
}
QPushButton[cls="accent"]:hover { background: $accent_hover; }
QPushButton[cls="accent"]:pressed { background: $accent_press; }
/* round-105 hero "play" button — same accent as the sidebar so it re-skins on
   every theme/accent change (must NOT be an inline stylesheet, which freezes
   the old accent at construction time). */
QPushButton[cls="play"] {
    background: $accent;
    color: $text_on_accent;
    border: 2px solid $accent_press;
    border-radius: 12px;
    padding: 8px 24px;
    font-weight: 600;
}
QPushButton[cls="play"]:hover { background: $accent_hover; border-color: $accent_press; }
QPushButton[cls="play"]:pressed { background: $accent_press; border-color: $accent; }
/* round-119: with no instance selected the play button is disabled — without
   this rule the accent/disabled cascade left it near-white on white (an
   invisible button). Keep it visible but clearly muted. */
QPushButton[cls="play"]:disabled {
    background: $bg_input;
    color: $text_disabled;
    border-color: $border;
}
/* danger outline */
QPushButton[cls="danger"] {
    background: transparent;
    border: 1px solid $danger;
    color: $danger;
}
QPushButton[cls="danger"]:hover { background: $danger_hover; }
/* secondary outline button (visible on both light and dark themes).
   round-121: $border (#E5E7EB on white) made the outline invisible — the
   home character action looked like bare text. Use the stronger outline tier. */
QPushButton[cls="secondary"] {
    background: $bg_btn;
    border: 1px solid $border_light;
    color: $text_main;
}
QPushButton[cls="secondary"]:hover {
    background: $accent_soft;
    border-color: $accent;
    color: $accent;
}
QPushButton[cls="secondary"]:pressed {
    background: $accent;
    color: $text_on_accent;
}
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
    color: $text_on_accent;
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
    /* round-48 修复：QSS 不支持 # 注释！原 # 注释让 Qt 解析器进入错误
     * 恢复，吞掉其后所有 radio/checkbox 规则，选中圆点因此消失。
     * 现已改为合法的斜杠星注释。 */
    width: 10px;
    height: 10px;
    margin: -2px 0;
    background: $slider_knob;
    border: 2px solid $accent;
    border-radius: 7px;
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
    /* round-46 用户反馈：白主题下选中态 accent_soft 太浅看不清。
     * 改为 accent 实色底 + text_on_accent 白字（类似主按钮）——
     * 强对比，深浅主题都清晰。 */
    background: $accent;
    color: $text_on_accent;
    font-weight: 600;
    border-left: 3px solid $accent_press;
}

/* 左侧导航分组标题（不可选灰字，功能区分化） */
[cls="nav-group"] {
    color: $text_sub;
    font-size: ${f_xs}px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
    border: none;
    /* round-124：分组行高 26px、字号 11px，原 padding 上下合计 18px 只剩
     * 8px 内容区，文字被压成 2–3px 的灰条。改为 5px/4px，内容区 17px。 */
    padding: 5px 0 4px 18px;
}

/* ---- AC left sidebar (scoped by object name) ---- */
#ac-nav {
    background: $bg_panel;
    border: none;
    border-right: 1px solid $border;
    outline: 0;
}
#ac-nav::item {
    color: $text_sub;
    background: transparent;
    padding: 10px 14px;
    margin: 3px 10px;
    border-radius: ${r_btn}px;
    font-size: ${f_md}px;
}
#ac-nav::item:hover {
    background: $bg_hover;
    color: $text_main;
}
#ac-nav::item:selected {
    /* round-46（TRAE 视觉反馈）：AC 导航选中态之前用 accent_soft 浅紫底，
     * 白主题下和未选中几乎无法区分（用户多次反馈"选中看不清"）。
     * 与通用 QListWidget 选中态统一为 accent 实色 + 白字。 */
    background: $accent;
    color: $text_on_accent;
    font-weight: 700;
    border-left: 3px solid $accent_press;
    padding-left: 11px;
}
#ac-nav::item:selected:!active {
    background: $accent;
    color: $text_on_accent;
}
#ac-nav::item:!selected:pressed {
    background: $border;
}
/* round-107 图标模式：条目只有图标（无文字），内边距收紧；选中态去掉左侧竖条
   以保持图标水平居中。 */
#ac-nav[compact="true"]::item {
    padding: 10px 0;
    margin: 3px 8px;
}
#ac-nav[compact="true"]::item:selected {
    border-left: none;
    padding-left: 0;
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
/* round-44 横向滚动条（之前只定义 vertical，底部横条走系统默认灰条
   与主题割裂——实例页/设置页底部会显形难看）。height:8 配合 horizontal 关键字。 */
QScrollBar:horizontal {
    background: $bg_app;
    height: 8px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: $border_light;
    border-radius: 4px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover { background: $text_disabled; }
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal { width: 0; }

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
/* round-107 slim bar（启动对话框 / 状态栏）：去掉「黑框 + 方块」的塑料感，
   改为柔和半透明轨道 + 圆角 accent 填充。百分比用旁侧标签单独显示。 */
QProgressBar[cls="slim"] {
    background: $bg_hover;
    border: none;
    border-radius: 3px;
    height: 6px;
}
QProgressBar[cls="slim"]::chunk {
    background: $accent;
    border-radius: 3px;
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
    padding: 4px 6px;
    border-radius: 6px;
}
QRadioButton::indicator {
    width: 18px; height: 18px;
    /* round-46 用户反馈"白色块看不见"：$border 在白主题下太浅（#E5E7EB），
     * radio 圆圈在白背景几乎透明。改用 $text_sub（深灰）作为未选边框，可见。
     * 未选圆心随主题（light 白 / dark 深色），选中后换 accent。 */
    border: 2px solid $text_sub;
    border-radius: 9px;
    background: $bg_frost;
}
QRadioButton::indicator:checked {
    background: $accent;
    border-color: $accent;
}
QRadioButton::indicator:hover { border-color: $accent; }
QRadioButton:checked {
    /* round-46：选中态——浅紫底 + 加粗文字 + 深紫 accent indicator 三重确认。 */
    background: $accent_soft;
    font-weight: 600;
    color: $accent;
}

/* ---- group box (settings sections) ---- */
QGroupBox {
    background: $glassy;
    border: 1px solid $border;
    border-radius: ${r_card}px;
    padding: 24px 18px 18px 18px;
    margin-top: 14px;
    font-size: ${f_lg}px;
    font-weight: 700;
    color: $text_main;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: $accent;
}
/* round-79e 折叠分组：隐藏 checkable 勾选框（折叠箭头用标题前缀 ▸/▾） */
QGroupBox::indicator {
    width: 0px;
    height: 0px;
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
    color: $bg_card;   /* opaque — bg_panel may be translucent in frosted mode */
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
    /* round-124：原先用 $bg_panel，浅色主题下与页面内容的白底差半档，
     * 底栏看起来像一条独立的灰白条。改为与内容同色，只留分隔线。 */
    background: $bg_card;
    border-top: 1px solid $border;
}
[cls="surface"] {
    background: $glassy;
    border: 1px solid $border;
    border-radius: ${r_card}px;
}
QPushButton[cls="surface"] {
    text-align: left;
    padding: 0;
}
QPushButton[cls="surface"]:hover {
    border: 2px solid $accent;
}
[cls="row"] {
    background: $glassy;
    border: 1px solid $border;
    border-radius: ${r_btn}px;
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
    border-radius: ${r_icon}px;
}
QPushButton[cls="icon-btn"]:hover {
    background: $bg_hover;
}
[cls="tile"] {
    background: $accent_soft;
    border-radius: ${r_card}px;
}
[cls="pill"] {
    background: $bg_input;
    color: $text_sub;
    border: 1px solid $border;
    border-radius: ${r_small}px;
    padding: 2px 10px;
    font-size: ${f_xs}px;
}
[cls="loader-card"] {
    background: $glassy;
    border: 1px solid $border;
    border-radius: ${r_small}px;
}
[cls="loader-card"]:hover {
    border: 1px solid $accent;
}
[cls="loader-card-on"] {
    background: $accent_soft;
    border: 2px solid $accent;
    border-radius: ${r_small}px;
}
[cls="pcl2-top"] {
    background: $bg_panel;
    border-bottom: 1px solid $border;
}
QPushButton[cls="pcl2-pill"] {
    background: transparent;
    color: $text_sub;
    border: none;
    border-radius: ${r_icon}px;
    padding: 6px 18px;
    font-size: ${f_md}px;
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
QPushButton[cls="chip"] {
    background: $bg_card;
    color: $text_sub;
    border: 1px solid $border;
    border-radius: ${r_btn}px;
    padding: 4px 15px;
    font-size: ${f_md}px;
}
QPushButton[cls="chip"]:hover {
    background: $bg_hover;
    color: $text_main;
}
QPushButton[cls="chip"]:pressed {
    background: $accent_soft;
    color: $accent;
}
QPushButton[cls="chip"]:checked {
    background: $accent_soft;   /* round-99：选中态=accent 描边+淡底（点缀），不再整块实色 */
    color: $accent;
    border-color: $accent;
    font-weight: 600;
}

/* ---- round-99 极简基座：详情页中性容器（无渐变 / 无 accent 底纹）--------
   强调色使用规约（新页面照办）：accent 只允许出现在主按钮、选中态、focus
   描边、进度条，以及 ≤16px 的小图标点缀上；禁止作为文字背景或大面积底色
   ——「色块压住文字」的根源。 */
QFrame[cls="hero"] {
    background: $bg_panel;
    border: 1px solid $border;
    border-radius: ${r_big}px;
}
QFrame[cls="latest"] {
    background: $glassy;
    border: 1px solid $border;
    border-left: 3px solid $accent;   /* 唯一强调：3px 左条（点缀级） */
    border-radius: ${r_card}px;
}
[cls="badge"] {
    background: $bg_hover;
    color: $text_sub;
    border: 1px solid $border;
    border-radius: ${r_small}px;
    padding: 1px 9px;
    font-size: ${f_xs}px;
    font-weight: 600;
}
/* round-99：裸容器（无底色、无描边）。plain QWidget 会被全局 QWidget 规则
   画上 bg_app 底色——亮色主题下不可见（贴卡片色），暗色主题下在卡片上变成
   一块「深色补丁压住文字」。纯排布用的 QWidget 包装层挂本类即透明。 */
[cls="bare"] {
    background: transparent;
    border: none;
}
QFrame[cls="vrow"] {
    background: $glassy;
    border: 1px solid $border;
    border-radius: ${r_btn}px;
}
QFrame[cls="vrow"]:hover {
    border: 1px solid $border_light;
}
""")


def build_qss() -> str:
    # Cache per (theme mode, accent, frosted) so repeated toggles don't
    # re-substitute.
    key = (_theme_mode, COLORS.get("accent"), _frosted)
    cached = _QSS_CACHE.get(key)
    if cached is not None:
        return cached
    subst = dict(COLORS)
    # 兜底：text_on_accent 只在 set_accent_color/set_theme_mode 里写入，默认
    # 冷启动（未自定义 accent）时 COLORS 可能缺失 → QSS 出现字面 $text_on_accent。
    subst.setdefault("text_on_accent", "#FFFFFF")
    subst["font_family"] = FONT_FAMILY
    subst["f_xs"] = F_XS
    subst["f_sm"] = F_SM
    subst["f_md"] = F_MD
    subst["f_lg"] = F_LG
    subst["f_xl"] = F_XL
    subst["r_card"] = R_CARD
    subst["r_big"] = R_BIG
    subst["r_btn"] = R_BTN
    subst["r_small"] = R_SMALL
    subst["r_icon"] = R_ICON
    # round-xx 主题一致性：danger 按钮 hover 底 = danger 色 8% 透明度
    # （原 QSS 硬编码 rgba(239,68,68,0.08)，换成 danger token 派生，
    #  自定义主题包改 danger 时 hover 底随之联动）。
    subst["danger_hover"] = _to_translucent(COLORS.get("danger", "#EF4444"), 20)
    # 透底模式（round-51）：应用层底色转半透明，让系统 Acrylic 的桌面模糊
    # 透出来；关闭时保持实色（round-32 默认）。
    if _app_bg_translucent:
        subst["bg_app_frost"] = _to_translucent(COLORS["bg_app"], 205)
    elif _wallpaper_surface:
        # Wallpaper behind every page: keep the surface translucent enough for
        # the artwork to read through while cards stay solid ($glassy).
        subst["bg_app_frost"] = _to_translucent(COLORS["bg_app"], 185)
    else:
        subst["bg_app_frost"] = COLORS["bg_app"]
    # Dialogs are separate top-level windows with no wallpaper behind them —
    # they must stay fully opaque or they would show the desktop through.
    subst["bg_app_solid"] = COLORS["bg_app"]
    # round-44 dark 主题按钮对比度：$bg_frost 走新 bg_btn（dark=#33333A，
    # light=#FFFFFF），避免按钮底色与面板同色导致边框融背景看不清。
    subst["bg_frost"] = COLORS.get("bg_btn", COLORS["bg_card"])
    # round-52 玻璃拟态：容器/卡片/分组框走 $glassy —— 开启时用半透明
    # bg_frost（透出 Acrylic 桌面模糊），关闭时实色 bg_card。注意此处必须
    # 直接读 COLORS["bg_frost"]（上方 subst["bg_frost"] 已被映射成 bg_btn，
    # 那是给按钮的对比度颜色，不是卡片玻璃色）。
    subst["glassy"] = COLORS["bg_frost"] if _frosted else COLORS["bg_card"]
    qss = QSS_TEMPLATE.safe_substitute(**subst)
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
    global _QSS_TIMER
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

    def set_fill(self, fill) -> None:
        # 允许传入 hex 字符串（如 COLORS["bg_card"]），统一归一为 QColor，
        # 否则 paintEvent 里 QPainter.fillPath 收到裸字符串会抛 TypeError。
        if isinstance(fill, str):
            fill = QColor(fill)
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
        fill = self._fill
        if fill is None:
            # frosted → translucent card; otherwise solid (same token logic
            # as the QSS $bg_frost substitution in build_qss()).
            brush = QColor(COLORS["bg_frost"] if _frosted else COLORS["bg_card"])
        elif isinstance(fill, str):
            brush = QColor(fill)
        else:
            brush = fill
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


# ═══════════════════════════════════════════════════════════════════════
# round-46 结构性修复：QSlider 自绘样式
# Qt QSS 对 QSlider::sub-page 的 border-radius **不支持**（只渲染 background）
# → 之前几轮改 QSS 数值（handle margin/border-radius）全部无效，滑条满格时
# 右端永远是直边。改用 QProxyStyle 自绘 groove/sub-page/handle：
#   groove 圆角条（$border）→ sub-page 圆角条（$accent）→ 圆形 handle。
# 挂载：app.setStyle(AcSliderStyle())（main.py 在 apply_qss 后调用）。
# ═══════════════════════════════════════════════════════════════════════
from PySide6.QtWidgets import QProxyStyle, QStyle
from PySide6.QtCore import QPointF


class AcSliderStyle(QProxyStyle):
    """App-wide style tweaks: rounded QSlider + a sane default button icon size.

    1) 自绘横向 QSlider：圆角 groove + 圆角 sub-page + 圆形 handle。
       解决 QSS 无法给 sub-page 圆角的问题（Qt 样式表对 sub-page 只认
       background，border-radius 静默忽略 → 满格右端是直边）。

    2) PM_ButtonIconSize = 18。Qt 的 QPushButton 在没有显式 setIconSize()
       时会用样式的 PM_ButtonIconSize（Windows 默认 16×16），把图标静默压成
       16px —— 44×44 的按钮里只画一个小三角。逐个按钮补 setIconSize 容易漏，
       改成在这里统一给出默认值：没设过的按钮自动得到 18px，显式设过的
       （15/16/20/24 等）依然以显式值为准（实测 setIconSize 优先级高于本指标）。
    """

    #: Default icon size (px) for buttons that never call setIconSize().
    BUTTON_ICON_SIZE = 18

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_ButtonIconSize:
            return self.BUTTON_ICON_SIZE
        return super().pixelMetric(metric, option, widget)

    def drawComplexControl(self, cc, opt, p, widget=None):
        if cc == QStyle.ComplexControl.CC_Slider and widget is not None:
            qs = widget
            if qs.orientation() == Qt.Horizontal:
                try:
                    self._paint_slider(opt, p, qs)
                    return
                except Exception:
                    pass  # 自绘失败退回 base（不崩）
        return super().drawComplexControl(cc, opt, p, widget)

    def _paint_slider(self, opt, p, widget):
        from .theme import COLORS
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.NoPen)
        r = opt.rect
        # groove：左右留 4px，垂直居中 6px 高
        g = QRectF(r.left() + 4, r.center().y() - 3, r.width() - 8, 6)
        p.setBrush(QColor(COLORS.get("border", "#E5E7EB")))
        p.drawRoundedRect(g, 3, 3)
        # handle 中心 x（按 slider 值比例）
        span = max(0, (opt.maximum - opt.minimum))
        frac = (opt.sliderValue - opt.minimum) / span if span else 0.0
        hx = g.left() + g.width() * max(0.0, min(1.0, frac))
        # sub-page：从左到 handle 中心，圆角（左右都圆，handle 处自然衔接）
        sp = QRectF(g.left(), g.top(), max(6.0, hx - g.left()), g.height())
        p.setBrush(QColor(COLORS.get("accent", "#7C3AED")))
        p.drawRoundedRect(sp, 3, 3)
        # handle：圆形 12px（accent 边 + 白心，白心走 slider_knob token）
        hr = 6.0
        p.setBrush(QColor(COLORS.get("slider_knob", "#FFFFFF")))
        pen = p.pen()
        from PySide6.QtGui import QPen
        p.setPen(QPen(QColor(COLORS.get("accent", "#7C3AED")), 2))
        p.drawEllipse(QPointF(hx, g.center().y()), hr, hr)
        p.setPen(pen)

    def sizeFromContents(self, ct, opt, contents, w):
        # 滑条控件自身高度保持 QSS groove 的 6px 视觉 —— 默认高度足够
        return super().sizeFromContents(ct, opt, contents, w)
