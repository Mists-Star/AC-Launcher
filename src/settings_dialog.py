"""
SettingsPage — dual-panel settings, embedded in the main window's content
stack (no more popup dialog). Two tabs:
  · Quick  — RAM presets, resolution, window mode, language, color picker,
             wallpaper, home style, about/legal links
  · Advanced — raw sliders, JVM args, Java path, client_id, sound details,
              splash toggle, diagnostics entry

The page is a plain QWidget added to MainWindow.stack; "保存" persists the
config and emits `saved` (MainWindow refreshes UI + navigates home).
"""
import json, os, sys

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QTextEdit, QGroupBox, QCheckBox, QComboBox,
    QWidget, QTabWidget, QRadioButton, QButtonGroup,
    QSlider,
    QScrollArea, QListWidget, QFrame,
)
from PySide6.QtCore import Qt, Signal

from .theme import COLORS, RoundedCard
from .icons import icon
from .paths import get_config_path, get_data_dir
from .launch import find_java
from .i18n import t, set_language
from .worker import Worker
from .core import authlib as authlib_dl
from .core.java import scan_javas, java_major
from .win_rounded import info, warn, pick_files, dark_color, enable_dark_titlebar

CONFIG_FILE = get_config_path("launcher_config.json")
_DEFAULTS = {
    # ---- quick ----
    "ram_mb": 4096,
    "launcher_ram_mb": 1024,
    "jvm_aikars": True,
    "window_mode": "windowed",       # windowed / borderless / fullscreen
    "res_w": 1280,
    "res_h": 720,
    "language": "zh-CN",
    "accent_color": "#7C3AED",        # hex
    "wallpaper_mode": "none",         # none / solid / image / gif / video
    "wallpaper_color": "#1E1E1E",
    "wallpaper_image": "",
    "wallpaper_opacity": 1.0,          # 0..1
    "wallpaper_video_vol": 0.0,        # 0..1, video wallpaper volume
    "home_style": "ac_default",        # AC 自有默认模板；pcl_card/hmcl_list/modrinth_modern 为可选模板
    # ---- advanced ----
    "java_auto": True,
    "java_path": "",
    "jvm_args": "",
    "ms_client_id": "",
    "authlib_path": "",
    "launch_sound": True,
    "launch_sound_trigger": "game",
    "launch_sound_file": "",
    "launch_sound_vol": 0.8,
    # ---- background music (loop) ----
    "bgm_enabled": False,
    "bgm_file": "",
    "bgm_vol": 0.4,
    # ---- UI sound effects ----
    "sfx_enabled": False,
    "sfx_click": "",
    "sfx_hover": "",
    "sfx_success": "",
    "sfx_error": "",
    "sfx_vol": 0.6,
    "splash_enabled": True,
    # ---- launcher window geometry (persisted across sessions) ----
    "win_geometry": None,            # [x, y, w, h] or None → use default size
    "win_maximized": False,
    # ---- theme ----
    "theme_mode": "dark",            # light / dark
    "theme_pack": "",                # ""=none (built-in) / "control" / user pack id
    # ---- download mirror ----
    "download_mirror": "official",   # official (官方 Mojang, 默认) / bmclapi (国内镜像)
    # ---- network proxy for downloads ----
    "download_proxy": "",            # ""=system proxy, "none"=direct, or "http://host:port"
}


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**_DEFAULTS, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULTS)


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── preset color palette ──────────────────────────────────────────────────
ACCENT_PRESETS = [
    ("#7C3AED", "紫罗兰"),
    ("#6366F1", "靛蓝"),
    ("#3B82F6", "天蓝"),
    ("#22C55E", "翠绿"),
    ("#EAB308", "琥珀"),
    ("#EF4444", "赤红"),
    ("#EC4899", "玫粉"),
    ("#14B8A6", "青碧"),
]


class SettingsPage(QWidget):
    """Embedded settings page (main window stack), replacing the old dialog."""

    # Emitted after a successful save so MainWindow can refresh + navigate.
    saved = Signal()
    # Emitted by "取消" so MainWindow can leave the settings page.
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rebuilding = False
        # Back-reference to the MainWindow; set after construction. Used for
        # live-refreshing home/wallpaper when a setting changes.
        self._window = None
        self._build_ui()

    # ═══════════════════════════════════════════════════════════════════════
    # UI BUILD
    # ═══════════════════════════════════════════════════════════════════════
    def _wrap_scroll(self, content: QWidget) -> QScrollArea:
        """Wrap a tab page in a QScrollArea so overflowing content stays reachable."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        # 水平滚动条：需要时出现（AsNeeded）。之前 ScrollBarAlwaysOff 会隐藏
        # 被超宽内容（长文本 QComboBox / 未换行 hint）撑出屏幕的选项。
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sa.setWidget(content)
        sa.setFrameShape(QScrollArea.NoFrame)
        return sa

    def _build_ui(self):
        self.cfg = load_config()
        self._custom_color = ""

        # Reuse the existing layout if reload() already cleared it; otherwise
        # attach a new one. Creating `QVBoxLayout(self)` when the widget
        # already has a layout makes the new layout orphan — every widget
        # added to it disappears from the rendered tree (the bug that left
        # the settings page blank after navigation).
        existing = self.layout()
        root = existing if existing is not None else QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._root_layout = root

        # ── page header (text only — main window owns the title bar) ──
        header = QLabel(t("settings.title"))
        header.setProperty("cls", "page-header")
        header.setFixedHeight(48)
        header.setAlignment(Qt.AlignCenter)
        root.addWidget(header)

        # ── 单一设置滚动页（快速 + 高级合并）──
        # 两个 QTabWidget tab 会让"同一项"在两处维护、改一处不同步。
        # 合并成一个 QScrollArea：快速区在上，分隔线，高级区在下。
        merged = QWidget()
        ml = QVBoxLayout(merged)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        ml.addWidget(self._build_quick())
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")
        ml.addWidget(sep)
        ml.addWidget(self._build_advanced())
        ml.addStretch(1)
        root.addWidget(self._wrap_scroll(merged), stretch=1)

        # ── footer ──
        footer = QWidget()
        footer.setFixedHeight(60)
        footer.setProperty("cls", "page-footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 0, 20, 0)
        save = QPushButton(t("settings.save"))
        save.setProperty("cls", "accent")
        save.setMinimumHeight(38)
        save.clicked.connect(self._save)
        cancel = QPushButton(t("settings.cancel"))
        cancel.setMinimumHeight(38)
        cancel.clicked.connect(self.close_requested)
        fl.addStretch(1)
        fl.addWidget(cancel)
        fl.addWidget(save)

        root.addWidget(footer)

    def reload(self):
        """Tear down and rebuild all controls from the current config.

        Called by MainWindow when re-entering the settings page (e.g. after a
        language switch) so the UI reflects the latest cfg and translations.
        """
        self._rebuilding = True
        try:
            # Delete old widgets first, then rebuild in place.
            while self._root_layout.count():
                item = self._root_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
                elif item.layout() is not None:
                    self._clear_layout(item.layout())
            # Clear every self.<widget> reference so any signal/slot still in
            # the dispatch queue cannot deref a C++-deleted wrapper between
            # this point and the moment _build_ui() finishes reassigning them.
            # Without this, ``self.java_auto`` (etc.) would briefly point at
            # the old, about-to-be-destroyed widget and a click on the new save
            # button (or any other in-flight signal) could raise
            # ``RuntimeError: Internal C++ object already deleted``.
            for _name in list(self.__dict__.keys()):
                obj = self.__dict__[_name]
                if isinstance(obj, QWidget):
                    self.__dict__[_name] = None
            self._build_ui()
        finally:
            self._rebuilding = False

    # ═══════════════════════════════════════════════════════════════════════
    # QUICK PANEL
    # ═══════════════════════════════════════════════════════════════════════
    def _build_quick(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(18)

        # ── RAM presets ──
        ram_grp = QGroupBox(t("settings.ram_preset"))
        rl = QVBoxLayout(ram_grp)
        rl.setSpacing(8)
        self.ram_btns = QButtonGroup()
        ram_row = QHBoxLayout()
        for val, label in [
            (2048, t("settings.ram_2g")),
            (4096, t("settings.ram_4g")),
            (8192, t("settings.ram_8g")),
            (16384, t("settings.ram_16g")),
        ]:
            btn = QRadioButton(label)
            btn.setProperty("cls", "ram-preset")
            btn.setChecked(int(self.cfg.get("ram_mb", 4096)) == val)
            btn.val = val
            self.ram_btns.addButton(btn, val)
            ram_row.addWidget(btn)
        rl.addLayout(ram_row)
        lay.addWidget(ram_grp)

        # ── Window mode + resolution ──
        mode_grp = QGroupBox(t("settings.window_mode"))
        ml = QVBoxLayout(mode_grp)
        self.mode_btns = QButtonGroup()
        mode_row = QHBoxLayout()
        for key, label in [
            ("windowed", t("settings.win_windowed")),
            ("borderless", t("settings.win_borderless")),
            ("fullscreen", t("settings.win_fullscreen")),
        ]:
            btn = QRadioButton(label)
            btn.setChecked(self.cfg.get("window_mode", "windowed") == key)
            btn.mode_key = key
            self.mode_btns.addButton(btn)
            mode_row.addWidget(btn)
        ml.addLayout(mode_row)
        lay.addWidget(mode_grp)

        res_grp = QGroupBox(t("settings.resolution_preset"))
        resl = QVBoxLayout(res_grp)
        self.res_btns = QButtonGroup()
        res_row = QHBoxLayout()
        for rw, rh, label in [
            (1280, 720, t("settings.res_hd")),
            (1920, 1080, t("settings.res_fhd")),
            (2560, 1440, t("settings.res_2k")),
        ]:
            btn = QRadioButton(label)
            btn.setChecked(
                int(self.cfg.get("res_w", 1280)) == rw
                and int(self.cfg.get("res_h", 720)) == rh
            )
            btn.res_val = (rw, rh)
            self.res_btns.addButton(btn)
            res_row.addWidget(btn)
        resl.addLayout(res_row)
        lay.addWidget(res_grp)

        # ── Language ──
        lang_grp = QGroupBox(t("settings.language"))
        langl = QVBoxLayout(lang_grp)
        self.lang_btns = QButtonGroup()
        lang_row = QHBoxLayout()
        for code, label in [
            ("zh-CN", t("settings.lang_zh")),
            ("en-US", t("settings.lang_en")),
        ]:
            btn = QRadioButton(label)
            btn.setChecked(self.cfg.get("language", "zh-CN") == code)
            btn.lang_code = code
            self.lang_btns.addButton(btn)
            lang_row.addWidget(btn)
        langl.addLayout(lang_row)
        for b in self.lang_btns.buttons():
            b.toggled.connect(self._on_lang_toggle)
        lay.addWidget(lang_grp)

        # ── Appearance: color picker + wallpaper + home style ──
        app_grp = QGroupBox(t("settings.appearance"))
        apl = QVBoxLayout(app_grp)
        apl.setSpacing(12)

        # Accent color dots
        cl = QHBoxLayout()
        cl.addWidget(QLabel(t("settings.color_label")))
        self.color_btns = []
        current_accent = self.cfg.get("accent_color", "#7C3AED")
        for hex_c, name in ACCENT_PRESETS:
            dot = QPushButton()
            dot.setFixedSize(28, 28)
            dot.setCursor(Qt.PointingHandCursor)
            dot.setToolTip(name)
            dot.setStyleSheet(
                f"QPushButton {{ background: {hex_c}; border-radius: 14px; "
                f"border: 2px solid {'white' if hex_c == current_accent else 'transparent'}; }}"
                f"QPushButton:hover {{ border: 2px solid #E5E5E5; }}"
            )
            dot.color_hex = hex_c
            dot.clicked.connect(lambda checked, h=hex_c: self._pick_color(h))
            self.color_btns.append(dot)
            cl.addWidget(dot)
        # custom color button
        custom_dot = QPushButton("…")
        custom_dot.setFixedSize(28, 28)
        custom_dot.setCursor(Qt.PointingHandCursor)
        custom_dot.setToolTip(t("settings.color_custom"))
        custom_dot.setStyleSheet(
            "QPushButton { background: #33333A; border-radius: 14px; border: 1px dashed #555; "
            "font-size: 14px; color: #9CA3B0; }"
            "QPushButton:hover { border-color: #9CA3B0; }"
        )
        custom_dot.clicked.connect(self._pick_color_custom)
        cl.addWidget(custom_dot)
        cl.addStretch(1)
        apl.addLayout(cl)

        # Light / Dark theme toggle
        th_row = QHBoxLayout()
        th_row.addWidget(QLabel(t("settings.theme_mode")))
        self.theme_btns = QButtonGroup()
        for mode, label, icon_name in [
            ("light", t("settings.theme_light"), "sun"),
            ("dark", t("settings.theme_dark"), "moon"),
        ]:
            rb = QRadioButton(label)
            rb.setIcon(icon(icon_name).pixmap(18, 18))
            rb.setChecked(self.cfg.get("theme_mode", "light") == mode)
            rb.theme_mode_val = mode
            self.theme_btns.addButton(rb)
            th_row.addWidget(rb)
        th_row.addStretch(1)
        apl.addLayout(th_row)

        # Live preview: apply theme immediately on toggle (no need to save first)
        self.theme_btns.buttonClicked.connect(self._on_theme_toggle)

        # Theme pack selector (player-customizable token overrides)
        pk_row = QHBoxLayout()
        pk_row.addWidget(QLabel(t("settings.theme_pack")))
        self.pack_combo = QComboBox()
        self.pack_combo.setMinimumHeight(30)
        # 限制下拉框宽度防溢出：用 AdjustToContents 按当前文本收缩——
        # 之前误用 AdjustToMinimumContentsLengthWithIcon（minContentsLength=0）
        # 会把 combo 收缩到 ~29px，名称被挤成空白（"主题包没显示名称"）。
        self.pack_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.pack_combo.setMaximumWidth(320)
        pk_row.addWidget(self.pack_combo)
        import_btn = QPushButton(t("settings.theme_pack_import"))
        import_btn.setMinimumHeight(28)
        import_btn.clicked.connect(self._import_theme_pack)
        pk_row.addWidget(import_btn)
        export_btn = QPushButton(t("settings.theme_pack_export"))
        export_btn.setMinimumHeight(28)
        export_btn.clicked.connect(self._export_theme_pack)
        pk_row.addWidget(export_btn)
        pk_row.addStretch(1)
        apl.addLayout(pk_row)
        self._reload_pack_combo()
        self.pack_combo.currentIndexChanged.connect(self._on_pack_changed)
        pk_hint = QLabel(t("settings.theme_pack_hint"))
        pk_hint.setProperty("cls", "sub")
        pk_hint.setWordWrap(True)
        apl.addWidget(pk_hint)

        # Wallpaper mode + browse button
        wp_row = QHBoxLayout()
        wp_row.addWidget(QLabel(t("settings.wallpaper_label")))
        self.wp_modes = QButtonGroup()
        for mode, label in [
            ("none", t("settings.wp_none")),
            ("solid", t("settings.wp_solid")),
            ("image", t("settings.wp_image")),
            ("gif", t("settings.wp_gif")),
            ("video", t("settings.wp_video")),
        ]:
            rb = QRadioButton(label)
            rb.setChecked(self.cfg.get("wallpaper_mode", "none") == mode)
            rb.wp_mode = mode
            self.wp_modes.addButton(rb)
            wp_row.addWidget(rb)
        # Browse button — filters by currently selected mode
        self.wp_browse = QPushButton(t("settings.wp_browse_btn"))
        self.wp_browse.setCursor(Qt.PointingHandCursor)
        self.wp_browse.setMinimumHeight(28)
        self.wp_browse.setProperty("cls", "accent")
        self.wp_browse.clicked.connect(self._browse_wallpaper)
        wp_row.addWidget(self.wp_browse)
        wp_row.addStretch(1)
        apl.addLayout(wp_row)

        # Wallpaper opacity + video volume
        wp_more = QHBoxLayout()
        self.wp_opacity = QSlider(Qt.Horizontal)
        self.wp_opacity.setRange(0, 100)
        self.wp_opacity.setValue(int(float(self.cfg.get("wallpaper_opacity", 1.0)) * 100))
        wp_more.addWidget(QLabel(t("settings.wp_opacity")))
        wp_more.addWidget(self.wp_opacity, stretch=1)
        self.wp_vol = QSlider(Qt.Horizontal)
        self.wp_vol.setRange(0, 100)
        self.wp_vol.setValue(int(float(self.cfg.get("wallpaper_video_vol", 0.0)) * 100))
        wp_more.addWidget(QLabel(t("settings.wp_volume")))
        wp_more.addWidget(self.wp_vol, stretch=1)
        apl.addLayout(wp_more)
        apl.addWidget(QLabel(t("settings.wp_hint")))

        # Home style
        hs_row = QHBoxLayout()
        hs_row.addWidget(QLabel(t("settings.home_style")))
        self.style_combo = QComboBox()
        self.style_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.style_combo.setMaximumWidth(280)
        self.style_combo.addItems([
            t("style.ac_default"),
            t("style.pcl_card"),
            t("style.hmcl_list"),
            t("style.modrinth_modern"),
        ])
        styles_idx = {
            "ac_default": 0, "pcl_card": 1, "hmcl_list": 2, "modrinth_modern": 3,
        }
        # 模板开放策略：只开放 AC 默认（已做完）；PCL2 主页卡 / HMCL /
        # Modrinth 仍在制作中 → 灰掉不可选（保留入口，后续启用）。
        cur_style = self.cfg.get("home_style", "ac_default")
        # 若历史配置指向未开放模板，强制回 AC 默认
        if cur_style not in styles_idx or cur_style != "ac_default":
            cur_style = "ac_default"
        self.style_combo.setCurrentIndex(styles_idx[cur_style])
        # 灰掉其余项（QComboBox item 级禁用）
        for i in range(1, self.style_combo.count()):
            item = self.style_combo.model().item(i)
            if item is not None:
                item.setEnabled(False)
        hs_row.addWidget(self.style_combo, stretch=1)
        self.style_combo.currentIndexChanged.connect(self._on_style_combo_changed)
        apl.addLayout(hs_row)
        _hs_hint = QLabel(t("settings.home_style_hint"))
        _hs_hint.setProperty("cls", "text-sub")
        apl.addWidget(_hs_hint)

        # ── 导航布局（独立于主页模板；PCL2 为实验态，切换需重启）──
        nl_row = QHBoxLayout()
        nl_row.addWidget(QLabel(t("settings.nav_layout")))
        self.nav_combo = QComboBox()
        self.nav_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.nav_combo.setMaximumWidth(280)
        self.nav_combo.addItems([
            t("style.ac_default"),     # AC 左侧导航（默认）
            t("style.pcl_card"),       # PCL2 顶栏导航（实验）
        ])
        _nav_idx = {
            "ac": 0, "pcl2": 1,
        }
        self.nav_combo.setCurrentIndex(
            _nav_idx.get(self.cfg.get("nav_layout", "ac"), 0)
        )
        nl_row.addWidget(self.nav_combo, stretch=1)
        apl.addLayout(nl_row)
        _nl_hint = QLabel(t("settings.nav_layout_hint"))
        _nl_hint.setProperty("cls", "text-sub")
        apl.addWidget(_nl_hint)

        lay.addWidget(app_grp)

        # ── About + Legal ──
        about_grp = QGroupBox(t("settings.about"))
        al = QVBoxLayout(about_grp)
        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel(t("settings.version")))
        from .brand import APP_VERSION
        ver_row.addWidget(QLabel(APP_VERSION))
        ver_row.addStretch(1)
        al.addLayout(ver_row)

        legal_row = QHBoxLayout()
        legal_row.setSpacing(10)
        for key in ["privacy", "tos", "disclaimer"]:
            btn = QPushButton(t(f"settings.{key}"))
            btn.setProperty("cls", "link")
            btn.setMinimumHeight(30)
            btn.setMinimumWidth(80)
            btn.clicked.connect(lambda checked, k=key: self._open_legal(k))
            legal_row.addWidget(btn)
        legal_row.addStretch(1)
        al.addLayout(legal_row)

        # Reset tutorial
        reset_btn = QPushButton(t("settings.reset_tutorial"))
        reset_btn.setMinimumHeight(32)
        reset_btn.clicked.connect(self._reset_tutorial)
        al.addWidget(reset_btn)

        lay.addWidget(about_grp)
        lay.addStretch(1)
        return w

    # ═══════════════════════════════════════════════════════════════════════
    # ADVANCED PANEL (original numeric controls)
    # ═══════════════════════════════════════════════════════════════════════
    @staticmethod
    def _physical_memory_mb() -> int:
        """Physical RAM in MB via ctypes — no third-party deps (psutil etc).

        Windows: GlobalMemoryStatusEx.  Other OS / failure: conservative 16 GB.
        """
        try:
            if sys.platform == "win32":
                import ctypes
                from ctypes import wintypes
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", wintypes.DWORD),
                        ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                m = MEMORYSTATUSEX()
                m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                    return int(m.ullTotalPhys // (1024 * 1024))
            return 16 * 1024
        except Exception:
            return 16 * 1024

    def _build_advanced(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(14)

        # ── 游戏内存（分配给 Minecraft）滑条 + 精确到 512MB ──
        ram_grp = QGroupBox(t("settings.ram_preset") + " (MB)")
        rl = QVBoxLayout(ram_grp)
        self.ram = QSlider(Qt.Horizontal)
        # 最小 1024MB（MC 1.6+ 硬性下限）；最大取物理内存一半 + 2GB，最高 32GB。
        total_mb = self._physical_memory_mb()
        ram_max = min(32768, max(4096, total_mb // 2 + 2048))
        self.ram.setRange(1024, ram_max)
        self.ram.setSingleStep(512)
        self.ram.setValue(int(self.cfg["ram_mb"]))
        self.ram_label = QLabel()
        self.ram.valueChanged.connect(
            lambda v: self.ram_label.setText(f"{v} MB  ({v // 1024} GB)")
        )
        self.ram.valueChanged.emit(self.ram.value())
        rl.addWidget(self.ram)
        rl.addWidget(self.ram_label)
        lay.addWidget(ram_grp)

        # ── 启动器自身内存分配（独立于游戏；用于加速模组加载/解压等）──
        lr_grp = QGroupBox(t("settings.launcher_ram"))
        ll = QVBoxLayout(lr_grp)
        ll.setSpacing(6)
        self.launcher_ram = QSlider(Qt.Horizontal)
        self.launcher_ram.setRange(256, 4096)
        self.launcher_ram.setSingleStep(128)
        self.launcher_ram.setValue(int(self.cfg.get("launcher_ram_mb", 1024)))
        self.launcher_ram_label = QLabel()
        self.launcher_ram.valueChanged.connect(
            lambda v: self.launcher_ram_label.setText(f"{v} MB  ({v // 1024} GB)")
        )
        self.launcher_ram.valueChanged.emit(self.launcher_ram.value())
        ll.addWidget(self.launcher_ram)
        ll.addWidget(self.launcher_ram_label)
        hint = QLabel(t("settings.launcher_ram_hint"))
        hint.setProperty("cls", "sub")
        hint.setWordWrap(True)
        ll.addWidget(hint)
        lay.addWidget(lr_grp)

        # ── JVM 启动优化（GC 调优，对应 PCL2 的优化参数）──
        opt_grp = QGroupBox(t("settings.jvm_opts"))
        ol = QVBoxLayout(opt_grp)
        opt_hint = QLabel(t("settings.jvm_opts_hint"))
        opt_hint.setProperty("cls", "sub")
        opt_hint.setWordWrap(True)
        ol.addWidget(opt_hint)
        self.aikars = QCheckBox(t("settings.aikars"))
        self.aikars.setChecked(bool(self.cfg.get("jvm_aikars", True)))
        ol.addWidget(self.aikars)
        lay.addWidget(opt_grp)

        # Resolution spinboxes
        res_grp = QGroupBox(t("settings.resolution_preset") + " (px)")
        rrow = QHBoxLayout(res_grp)
        self.rw = QSpinBox(); self.rw.setRange(640, 7680)
        self.rw.setValue(int(self.cfg["res_w"]))
        self.rh = QSpinBox(); self.rh.setRange(480, 4320)
        self.rh.setValue(int(self.cfg["res_h"]))
        rrow.addWidget(QLabel(t("settings.width")))
        rrow.addWidget(self.rw)
        rrow.addWidget(QLabel(t("settings.height")))
        rrow.addWidget(self.rh)
        rrow.addStretch(1)
        lay.addWidget(res_grp)

        # Java
        java_grp = QGroupBox(t("settings.java"))
        jl = QVBoxLayout(java_grp)
        self.java_auto = QCheckBox(t("settings.java_auto"))
        self.java_auto.setChecked(bool(self.cfg["java_auto"]))
        jl.addWidget(self.java_auto)
        jrow = QHBoxLayout()
        self.java_path = QLineEdit(self.cfg["java_path"])
        self.java_path.setPlaceholderText(t("settings.java_path"))
        browse = QPushButton(t("settings.browse"))
        browse.clicked.connect(self._browse_java)
        detect = QPushButton(t("settings.detect"))
        detect.clicked.connect(self._detect_java)
        jrow.addWidget(self.java_path)
        jrow.addWidget(browse)
        jrow.addWidget(detect)
        jl.addLayout(jrow)

        # ---- 快速选择：已识别的 Java 列表（每行一键"使用"）----
        quick_lbl = QLabel(t("settings.java_quick_label"))
        quick_lbl.setProperty("cls", "sub")
        jl.addWidget(quick_lbl)
        self.java_quick_list = QWidget()
        qlay = QVBoxLayout(self.java_quick_list)
        qlay.setContentsMargins(0, 0, 0, 0)
        qlay.setSpacing(4)
        jl.addWidget(self.java_quick_list)
        self._refresh_java_quick_list()

        manage_btn = QPushButton(t("settings.java_manage"))
        manage_btn.setProperty("cls", "accent")
        manage_btn.setMinimumHeight(30)
        manage_btn.clicked.connect(self._open_java_manager)
        jl.addWidget(manage_btn)
        lay.addWidget(java_grp)

        # Download mirror (BMCLAPI)
        mirror_grp = QGroupBox(t("settings.mirror"))
        ml = QVBoxLayout(mirror_grp)
        self.mirror_btns = QButtonGroup()
        self.mirror_btns.setExclusive(True)
        mrow = QHBoxLayout()
        for key, label in [
            ("official", t("settings.mirror_official")),
            ("bmclapi", t("settings.mirror_bmclapi")),
        ]:
            rb = QRadioButton(label)
            rb.setChecked(self.cfg.get("download_mirror", "bmclapi") == key)
            rb.mirror_key = key
            self.mirror_btns.addButton(rb)
            mrow.addWidget(rb)
        mrow.addStretch(1)
        ml.addLayout(mrow)
        ml.addWidget(QLabel(t("settings.mirror_hint")))
        lay.addWidget(mirror_grp)

        # Network proxy (for downloads behind a corporate / GFW proxy)
        proxy_grp = QGroupBox(t("settings.proxy"))
        pl = QVBoxLayout(proxy_grp)
        pl.setSpacing(8)
        self.proxy_btns = QButtonGroup()
        proxy_row = QHBoxLayout()
        for key, label in [
            ("none", t("settings.proxy_none")),
            ("system", t("settings.proxy_system")),
            ("custom", t("settings.proxy_custom")),
        ]:
            rb = QRadioButton(label)
            rb.proxy_key = key
            rb.setChecked(self._proxy_is(key))
            self.proxy_btns.addButton(rb)
            proxy_row.addWidget(rb)
        proxy_row.addStretch(1)
        pl.addLayout(proxy_row)
        self.proxy_btns.buttonClicked.connect(self._on_proxy_toggle)
        self.proxy_edit = QLineEdit(
            self.cfg.get("download_proxy", "") if "://" in str(self.cfg.get("download_proxy", "")) else ""
        )
        self.proxy_edit.setPlaceholderText(t("settings.proxy_ph"))
        self.proxy_edit.textChanged.connect(lambda _: self._on_proxy_toggle())
        pl.addWidget(self.proxy_edit)
        pl.addWidget(QLabel(t("settings.proxy_hint")))
        lay.addWidget(proxy_grp)
        self._on_proxy_toggle()  # sync proxy_edit enabled state to the radio

        # JVM args
        jvm_grp = QGroupBox(t("settings.jvm"))
        vl = QVBoxLayout(jvm_grp)
        self.jvm = QTextEdit(self.cfg["jvm_args"])
        self.jvm.setPlaceholderText(t("settings.jvm_placeholder"))
        self.jvm.setMaximumHeight(80)
        vl.addWidget(self.jvm)
        lay.addWidget(jvm_grp)

        # Sound details
        sound_grp = QGroupBox(t("settings.sound"))
        sl = QVBoxLayout(sound_grp)
        sl.setSpacing(8)
        self.sound_on = QCheckBox(t("settings.sound_enable"))
        self.sound_on.setChecked(bool(self.cfg.get("launch_sound", True)))
        sl.addWidget(self.sound_on)
        trig_row = QHBoxLayout()
        self.sound_trig = QComboBox()
        self.sound_trig.addItems([
            t("settings.sound_trigger_game"),
            t("settings.sound_trigger_app"),
            t("settings.sound_trigger_both"),
            t("settings.sound_trigger_off"),
        ])
        _trig_map = {
            "game": t("settings.sound_trigger_game"),
            "app": t("settings.sound_trigger_app"),
            "both": t("settings.sound_trigger_both"),
            "off": t("settings.sound_trigger_off"),
        }
        self.sound_trig.setCurrentText(_trig_map.get(self.cfg.get("launch_sound_trigger", "game"), t("settings.sound_trigger_game")))
        trig_row.addWidget(QLabel(t("settings.sound_trigger")))
        trig_row.addWidget(self.sound_trig, stretch=1)
        sl.addLayout(trig_row)
        file_row = QHBoxLayout()
        self.sound_file = QLineEdit(self.cfg.get("launch_sound_file", ""))
        self.sound_file.setPlaceholderText(t("settings.sound_ph"))
        browse_s = QPushButton(t("settings.sound_browse"))
        browse_s.clicked.connect(self._browse_sound)
        file_row.addWidget(self.sound_file, stretch=1)
        file_row.addWidget(browse_s)
        sl.addWidget(QLabel(t("settings.sound_file")))
        sl.addLayout(file_row)
        vol_row = QHBoxLayout()
        self.sound_vol = QSlider(Qt.Horizontal)
        self.sound_vol.setRange(0, 100)
        self.sound_vol.setValue(int(float(self.cfg.get("launch_sound_vol", 0.8)) * 100))
        vol_row.addWidget(QLabel(t("settings.sound_volume")))
        vol_row.addWidget(self.sound_vol, stretch=1)
        sl.addLayout(vol_row)
        preview_row = QHBoxLayout()
        preview = QPushButton(t("settings.sound_preview"))
        preview.clicked.connect(self._preview_sound)
        reset = QPushButton(t("settings.sound_reset"))
        reset.clicked.connect(self._reset_sound)
        preview_row.addWidget(preview)
        preview_row.addWidget(reset)
        preview_row.addStretch(1)
        sl.addLayout(preview_row)
        lay.addWidget(sound_grp)

        # Background music (loop / sequential / shuffle, multi-file or folder)
        bgm_grp = QGroupBox(t("settings.bgm"))
        bl = QVBoxLayout(bgm_grp)
        bl.setSpacing(8)
        self.bgm_on = QCheckBox(t("settings.bgm_enable"))
        self.bgm_on.setChecked(bool(self.cfg.get("bgm_enabled", False)))
        bl.addWidget(self.bgm_on)
        # 播放模式（顺序/循环/随机）
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(t("settings.bgm_mode")))
        self.bgm_mode = QComboBox()
        self.bgm_mode.addItems([
            t("settings.bgm_mode_loop"),      # 单曲循环
            t("settings.bgm_mode_sequential"),# 顺序播放
            t("settings.bgm_mode_shuffle"),   # 随机播放
        ])
        _mode_map = {
            "loop": t("settings.bgm_mode_loop"),
            "sequential": t("settings.bgm_mode_sequential"),
            "shuffle": t("settings.bgm_mode_shuffle"),
        }
        cur_mode = self.cfg.get("bgm_mode", "loop")
        self.bgm_mode.setCurrentText(_mode_map.get(cur_mode, t("settings.bgm_mode_loop")))
        mode_row.addWidget(self.bgm_mode, stretch=1)
        bl.addLayout(mode_row)
        # 文件列表（多文件）+ 快速添加文件夹
        list_lbl = QLabel(t("settings.bgm_files"))
        bl.addWidget(list_lbl)
        self.bgm_list = QListWidget()
        self.bgm_list.setMaximumHeight(110)
        for f in self.cfg.get("bgm_files", []) or ([]):
            self.bgm_list.addItem(f)
        bl.addWidget(self.bgm_list)
        bf_row = QHBoxLayout()
        add_file = QPushButton(t("settings.bgm_add_files"))
        add_file.clicked.connect(self._browse_bgm)
        add_dir = QPushButton(t("settings.bgm_add_folder"))
        add_dir.clicked.connect(self._browse_bgm_folder)
        clear = QPushButton(t("settings.bgm_clear"))
        clear.clicked.connect(self._clear_bgm_files)
        bf_row.addWidget(add_file)
        bf_row.addWidget(add_dir)
        bf_row.addWidget(clear)
        bf_row.addStretch(1)
        bl.addLayout(bf_row)
        # 兼容：单文件字段（老配置）
        self.bgm_file = QLineEdit(self.cfg.get("bgm_file", ""))
        self.bgm_file.setVisible(False)
        bv_row = QHBoxLayout()
        self.bgm_vol = QSlider(Qt.Horizontal)
        self.bgm_vol.setRange(0, 100)
        self.bgm_vol.setValue(int(float(self.cfg.get("bgm_vol", 0.4)) * 100))
        bv_row.addWidget(QLabel(t("settings.bgm_volume")))
        bv_row.addWidget(self.bgm_vol, stretch=1)
        bl.addLayout(bv_row)
        bprev_row = QHBoxLayout()
        bgm_preview = QPushButton(t("settings.bgm_preview"))
        bgm_preview.clicked.connect(self._preview_bgm)
        bgm_reset = QPushButton(t("settings.bgm_reset"))
        bgm_reset.clicked.connect(self._reset_bgm)
        bprev_row.addWidget(bgm_preview)
        bprev_row.addWidget(bgm_reset)
        bprev_row.addStretch(1)
        bl.addLayout(bprev_row)
        bl.addWidget(QLabel(t("settings.bgm_hint")))
        lay.addWidget(bgm_grp)

        # 添加 _browse_bgm_folder / _clear_bgm_files 方法 + 保存多文件逻辑
        # （紧跟已有 _browse_bgm 之后）

        # UI sound effects
        sfx_grp = QGroupBox(t("settings.sfx"))
        xl = QVBoxLayout(sfx_grp)
        xl.setSpacing(8)
        self.sfx_on = QCheckBox(t("settings.sfx_enable"))
        self.sfx_on.setChecked(bool(self.cfg.get("sfx_enabled", False)))
        xl.addWidget(self.sfx_on)
        self.sfx_files: dict[str, QLineEdit] = {}
        for key in ("click", "hover", "success", "error"):
            row = QHBoxLayout()
            row.addWidget(QLabel(t(f"settings.sfx_{key}")))
            le = QLineEdit(self.cfg.get(f"sfx_{key}", ""))
            le.setPlaceholderText("—")
            browse = QPushButton(t("settings.browse"))
            browse.setFixedWidth(64)
            browse.clicked.connect(lambda checked, k=key, le=le: self._browse_sfx(k, le))
            row.addWidget(le, stretch=1)
            row.addWidget(browse)
            xl.addLayout(row)
            self.sfx_files[key] = le
        sv_row = QHBoxLayout()
        self.sfx_vol = QSlider(Qt.Horizontal)
        self.sfx_vol.setRange(0, 100)
        self.sfx_vol.setValue(int(float(self.cfg.get("sfx_vol", 0.6)) * 100))
        sv_row.addWidget(QLabel(t("settings.sfx_volume")))
        sv_row.addWidget(self.sfx_vol, stretch=1)
        xl.addLayout(sv_row)
        xl.addWidget(QLabel(t("settings.sfx_hint")))
        lay.addWidget(sfx_grp)

        # Boot animation
        boot_grp = QGroupBox(t("settings.boot"))
        bl = QVBoxLayout(boot_grp)
        bl.setSpacing(8)
        self.splash_on = QCheckBox(t("settings.splash_enable"))
        self.splash_on.setChecked(bool(self.cfg.get("splash_enabled", True)))
        bl.addWidget(self.splash_on)
        bl.addWidget(QLabel(t("settings.splash_hint")))
        lay.addWidget(boot_grp)

        # Login / auth — 仅保留 Authlib-Injector 外置登录服务器代理。
        # 微软 client_id 已在 brand.py 内置 (MS_CLIENT_ID) —— 不暴露手动配置。
        login_grp = QGroupBox(t("settings.title") + " · 登录")
        ll = QVBoxLayout(login_grp)
        ll.setSpacing(8)
        al_row = QHBoxLayout()
        self.authlib = QLineEdit(self.cfg.get("authlib_path", ""))
        self.authlib.setPlaceholderText(t("settings.authlib_ph"))
        al_row.addWidget(self.authlib, stretch=1)
        self.authlib_dl = QPushButton(t("settings.authlib_download"))
        self.authlib_dl.setMinimumHeight(30)
        self.authlib_dl.clicked.connect(self._download_authlib)
        al_row.addWidget(self.authlib_dl)
        ll.addWidget(QLabel(t("settings.authlib")))
        ll.addLayout(al_row)
        ll.addWidget(QLabel(t("settings.authlib_hint")))
        lay.addWidget(login_grp)

        # Diagnostics
        diag_grp = QGroupBox(t("diag.title"))
        dgl = QVBoxLayout(diag_grp)
        dgl.addWidget(QLabel(t("diag.desc")))
        open_diag = QPushButton(t("diag.open"))
        open_diag.setProperty("cls", "accent")
        open_diag.setMinimumHeight(34)
        open_diag.clicked.connect(self._open_diagnostics)
        dgl.addWidget(open_diag)
        lay.addWidget(diag_grp)

        lay.addStretch(1)
        return w

    # ── helpers ────────────────────────────────────────────────────────────

    def _browse_bgm_folder(self):
        from .win_rounded import pick_folder
        folder = pick_folder(self, t("settings.bgm_pick_folder"))
        if not folder:
            return
        added = 0
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".mp3", ".ogg", ".wav", ".flac", ".m4a")):
                self.bgm_list.addItem(os.path.join(folder, name))
                added += 1
        if added:
            from .win_rounded import info
            info(self, t("settings.bgm"), t("settings.bgm_folder_added", n=added))

    def _clear_bgm_files(self):
        self.bgm_list.clear()

    def _pick_color(self, hex_color: str):
        """Preset color dot clicked — apply immediately."""
        from .theme import set_accent_color, apply_qss
        from .achievements import achievements as _ach
        _ach.unlock("first_theme")
        for dot in self.color_btns:
            active = dot.color_hex == hex_color
            dot.setStyleSheet(
                f"QPushButton {{ background: {dot.color_hex}; border-radius: 14px; "
                f"border: 2px solid {'white' if active else 'transparent'}; }}"
                f"QPushButton:hover {{ border: 2px solid {'white' if active else '#E5E5E5'}; }}"
            )
        # Apply accent color globally so user sees the change instantly
        set_accent_color(hex_color)
        app = QApplication.instance()
        if app:
            apply_qss()

    def _pick_color_custom(self):
        from .theme import set_accent_color, apply_qss
        c = dark_color(self, self._custom_color or "#3B82F6")
        if c:
            # Update UI state (mark custom as active)
            for dot in self.color_btns:
                dot.setStyleSheet(
                    f"QPushButton {{ background: {dot.color_hex}; border-radius: 14px; "
                    f"border: 2px solid transparent; }}"
                    f"QPushButton:hover {{ border: 2px solid #E5E5E5; }}"
                )
            # Apply globally + remember it's a custom color (not in presets)
            self._custom_color = c
            set_accent_color(c)
            app = QApplication.instance()
            if app:
                apply_qss()

    def _browse_wallpaper(self):
        """Open file picker filtered by the currently selected wallpaper mode."""
        from .wallpaper import guess_mode

        # Determine which mode is selected → choose appropriate filter
        checked = self.wp_modes.checkedButton()
        mode = checked.wp_mode if checked else "image"

        filters = {
            "image": "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
            "gif":   "Animated (*.gif *.webp);;All Files (*)",
            "video": "Video (*.mp4 *.webm *.mkv);;All Files (*)",
        }
        title_map = {
            "image": t("settings.wp_browse_image"),
            "gif":   t("settings.wp_browse_gif"),
            "video": t("settings.wp_browse_video"),
        }

        filt = filters.get(mode, filters["image"])
        title = title_map.get(mode, t("settings.wp_browse_image"))

        # If user has "none" or "solid" selected, default to image picker
        if mode in ("none", "solid"):
            mode = "image"
            filt = filters["image"]
            title = title_map["image"]

        path = pick_files(self, title, "", filt)
        if path:
            self.cfg["wallpaper_image"] = path
            # Auto-detect mode from file extension (in case user picked wrong mode)
            self.cfg["wallpaper_mode"] = guess_mode(path)
            for rb in self.wp_modes.buttons():
                if rb.wp_mode == self.cfg["wallpaper_mode"]:
                    rb.setChecked(True)
            # Preview immediately on home page
            try:
                from .main_window import MainWindow
                parent = self.parent()
                if isinstance(parent, MainWindow) and hasattr(parent, 'home'):
                    parent.home._apply_wallpaper()
            except Exception:
                pass

    def _browse_bgm(self):
        from .core.sound import AUDIO_FILTER
        path = pick_files(
            self, t("settings.bgm_browse_title"), "",
            AUDIO_FILTER,
        )
        if path:
            self.bgm_file.setText(path)

    def _preview_bgm(self):
        from .core.sound import music
        p = self.bgm_file.text().strip()
        if p:
            music().play(p, self.bgm_vol.value() / 100.0)
        else:
            info(self, t("settings.bgm"), t("settings.bgm_file"))

    def _reset_bgm(self):
        self.bgm_file.clear()
        self.bgm_on.setChecked(False)

    def _browse_sfx(self, key: str, le: QLineEdit):
        from .core.sound import AUDIO_FILTER
        path = pick_files(
            self, t("settings.bgm_browse_title"), "",
            AUDIO_FILTER,
        )
        if path:
            le.setText(path)

    def _open_legal(self, key: str):
        """Open privacy / TOS / disclaimer — show a simple text dialog."""
        texts = {
            "privacy": (
                "AC Launcher 隐私协议\n\n"
                "1. AC Launcher 是一款本地运行的 Minecraft Java 版启动器，\n"
                "   所有数据存储在你的设备上。\n"
                "2. 我们不收集、上传或共享任何个人信息。\n"
                "3. 你的游戏实例、账户凭据、皮肤文件均保留在本地。\n"
                "4. 联网功能（版本下载、皮肤获取）仅在你主动操作时触发，\n"
                "   且仅与 Mojang 官方 API 或你指定的服务器通信。\n"
                "5. 本启动器开源透明，你可以随时审查源码。\n\n"
                "最后更新：2026-07-30"
            ),
            "tos": (
                "AC Launcher 用户守则\n\n"
                "1. 本启动器仅供合法使用 Minecraft 的用户。\n"
                "2. 你需要自行拥有 Minecraft 正版授权。\n"
                "3. 禁止利用本启动器进行任何违法活动。\n"
                "4. Mod / 资源包 / 光影的版权归属其原作者。\n"
                "5. 使用联机大厅功能时请遵守社区规范。\n\n"
                "最后更新：2026-07-30"
            ),
            "disclaimer": (
                "AC Launcher 免责声明\n\n"
                "1. AC Launcher 由雾星（Mists Star）开发维护。\n"
                "2. 本软件按「现状」提供，不作任何明示或暗示的保证。\n"
                "3. 开发者不对因使用本软件造成的任何直接或间接损失负责。\n"
                "4. Minecraft 是 Mojang Studios 的商标，本启动器与其无关。\n"
                "5. 第三方 Mod / 资源 / 皮肤由其原作者负责，与本启动器无关。\n\n"
                "最后更新：2026-07-30"
            ),
        }
        info(self, t(f"settings.{key}"), texts.get(key, ""))

    def _reset_tutorial(self):
        cnt_path = os.path.join(get_data_dir(), "launch_count.txt")
        if os.path.exists(cnt_path):
            os.remove(cnt_path)
            info(self, t("settings.reset_tutorial"),
                "新手教程已重置。下次启动时将重新显示。")

    def _browse_java(self):
        path = pick_files(
            self, t("settings.java_browse_title"), "", "Java (*.exe)"
        )
        if path:
            self.java_path.setText(path)
            self.java_auto.setChecked(False)
            self._refresh_java_quick_list()

    def _refresh_java_quick_list(self):
        """Rebuild the "快速选择" Java list from scan_javas().

        Each row: Java major + version + path + "使用" button. One click
        sets the path + disables auto-select. Mirrors PCL2's quick-pick UX.
        """
        from PySide6.QtWidgets import QFrame
        # Tear down previous rows
        qlay = self.java_quick_list.layout()
        while qlay.count():
            item = qlay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        try:
            entries = scan_javas()
        except Exception:  # noqa: BLE001 - never let a scan break the settings page
            entries = []
        if not entries:
            empty = QLabel(t("settings.java_quick_empty"))
            empty.setProperty("cls", "sub")
            qlay.addWidget(empty)
            return
        # Prefer major ≥ 8, then sort by major desc (newest first) then path
        entries.sort(key=lambda e: (-(e.get("major") or 0), e.get("path", "")))
        cur_norm = os.path.normcase(self.java_path.text().strip()) if self.java_path.text().strip() else ""
        for entry in entries:
            row = RoundedCard(radius=6)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 6, 10, 6)
            rl.setSpacing(10)
            major = entry.get("major", 0) or 0
            known = major > 0
            ver = entry.get("version") or (f"Java {major}" if known else t("javamgr.version_unknown"))
            major_badge = QLabel(f"Java {major}" if known else t("javamgr.version_unknown"))
            major_badge.setStyleSheet(
                f"QLabel {{ background:{COLORS['accent'] if known else COLORS['danger']}22;"
                f" color:{COLORS['accent'] if known else COLORS['danger']};"
                f" border-radius:4px; padding:1px 7px; font-size:11px; font-weight:600; }}"
            )
            rl.addWidget(major_badge)
            info = QVBoxLayout()
            info.setSpacing(0)
            v_lbl = QLabel(ver)
            v_lbl.setProperty("cls", "sub")
            v_lbl.setStyleSheet("font-size:12px;")
            p_lbl = QLabel(entry.get("path", ""))
            p_lbl.setProperty("cls", "sub")
            p_lbl.setStyleSheet("font-size:11px; opacity:0.7;")
            p_lbl.setWordWrap(True)
            p_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            info.addWidget(v_lbl)
            info.addWidget(p_lbl)
            # 未知版本的 Java：提示玩家不建议使用（可能是精简 JDK/破损/AI 生成）
            if not known:
                warn_lbl = QLabel(t("javamgr.not_recommended"))
                warn_lbl.setStyleSheet(
                    f"font-size:11px; color:{COLORS['danger']};"
                )
                warn_lbl.setWordWrap(True)
                info.addWidget(warn_lbl)
            rl.addLayout(info, stretch=1)
            use_btn = QPushButton(t("javamgr.use_this"))
            use_btn.setMinimumHeight(28)
            path = entry.get("path", "")
            is_current = bool(cur_norm) and os.path.normcase(path) == cur_norm
            if is_current:
                use_btn.setEnabled(False)
                use_btn.setText(t("javamgr.in_use"))
            else:
                use_btn.clicked.connect(lambda _c=False, p=path: self._use_java_row(p))
            rl.addWidget(use_btn)
            qlay.addWidget(row)

    def _use_java_row(self, path: str):
        """Quick-pick: set the chosen path + disable auto-select + refresh."""
        self.java_path.setText(path)
        self.java_auto.setChecked(False)
        self._refresh_java_quick_list()

    # ── proxy helpers ──
    def _proxy_is(self, key: str) -> bool:
        v = self.cfg.get("download_proxy", "")
        if key == "none":
            return v == "none"
        if key == "system":
            return v == "" or v == "system"
        if key == "custom":
            return isinstance(v, str) and "://" in v
        return False

    def _on_proxy_toggle(self, *_):
        checked = self.proxy_btns.checkedButton()
        if checked is None:
            return
        key = checked.proxy_key
        if key == "custom":
            self.proxy_edit.setEnabled(True)
            if not self.proxy_edit.text().strip():
                self.proxy_edit.setFocus()
        else:
            self.proxy_edit.setEnabled(False)
            if key == "none":
                self.proxy_edit.clear()

    def _on_theme_toggle(self, rb):
        """Live-preview theme change when user clicks light/dark radio."""
        if rb is None or not hasattr(rb, "theme_mode_val"):
            return
        mode = rb.theme_mode_val
        from .theme import set_theme_mode, apply_qss
        set_theme_mode(mode)
        apply_qss()

    # ── theme packs (direction C: player-customizable token overrides) ──
    def _reload_pack_combo(self):
        from .theme import list_theme_packs, get_active_theme_pack_id
        self._packs = list_theme_packs()
        self.pack_combo.blockSignals(True)
        self.pack_combo.clear()
        self.pack_combo.addItem(t("settings.theme_pack_none"), "")
        for p in self._packs:
            label = p.get("name") or p.get("id", "?")
            self.pack_combo.addItem(label, p.get("id", ""))
        active = get_active_theme_pack_id()
        idx = 0
        for i, p in enumerate(self._packs, start=1):
            if p.get("id") == active:
                idx = i
                break
        self.pack_combo.setCurrentIndex(idx)
        self.pack_combo.blockSignals(False)

    def _on_pack_changed(self, _idx: int):
        """Live-apply the selected theme pack (none = built-in theme)."""
        pack_id = self.pack_combo.currentData() or ""
        from .theme import find_theme_pack, apply_theme_pack, apply_qss
        apply_theme_pack(find_theme_pack(pack_id) if pack_id else None)
        apply_qss()
        from .achievements import achievements as _ach
        _ach.unlock("first_theme")

    def _import_theme_pack(self):
        from .theme import import_theme_pack_file, apply_theme_pack, apply_qss
        from .win_rounded import pick_files, warn
        path = pick_files(self, t("settings.theme_pack_import_title"), "", "主题包 (*.json)")
        if not path:
            return
        try:
            pack = import_theme_pack_file(path)
        except Exception as e:
            warn(self, t("settings.theme_pack_import_fail"), str(e))
            return
        apply_theme_pack(pack)
        apply_qss()
        self._reload_pack_combo()
        # select the imported pack
        for i, p in enumerate(self._packs, start=1):
            if p.get("id") == pack.get("id"):
                self.pack_combo.setCurrentIndex(i)
                break

    def _export_theme_pack(self):
        from .theme import find_theme_pack, export_theme_pack
        from .win_rounded import pick_folder, warn
        pack_id = self.pack_combo.currentData() or ""
        if not pack_id:
            return
        pack = find_theme_pack(pack_id)
        if not pack:
            return
        d = pick_folder(self, t("settings.theme_pack_export_title"))
        if not d:
            return
        import os
        dest = os.path.join(d, f"{pack['id']}.json")
        try:
            export_theme_pack(pack, dest)
        except OSError as e:
            warn(self, t("settings.theme_pack_export_fail"), str(e))

    def _detect_java(self):
        # The single-Java find_java() is replaced by the full manager, which
        # auto-scans the entire machine on open (system / portable / other
        # launchers / AC's own copies). So "detect" now reveals every Java.
        self._open_java_manager()

    def _open_java_manager(self):
        from .java_manager_dialog import JavaManagerDialog
        dlg = JavaManagerDialog(self, current_path=self.java_path.text().strip())
        dlg.exec()
        # If the user picked a runtime, adopt it as the explicit java path.
        if dlg.selected_path is not None:
            self.java_path.setText(dlg.selected_path)
            self.java_auto.setChecked(not dlg.selected_path)

    def _download_authlib(self):
        self.authlib_dl.setEnabled(False)
        self.authlib_dl.setText(t("settings.authlib_downloading"))
        path = self.authlib.text().strip() or None
        # 必须存 self 引用！Worker 是 QThread，如果只用局部变量 w，
        # 函数返回后 Python GC 销毁 QThread（线程仍在跑）→ 闪退。
        # （用户反馈：设置页第三方皮肤站 jar 下载按钮点了就闪退）
        self._authlib_worker = Worker(authlib_dl.ensure_authlib, path)

        def _done(p):
            self.authlib_dl.setEnabled(True)
            self.authlib_dl.setText(t("settings.authlib_download"))
            if p:
                self.authlib.setText(p)
                info(self, t("settings.authlib"), t("settings.authlib_ok", p=p))
            else:
                warn(self, t("settings.authlib"), t("settings.authlib_fail"))

        self._authlib_worker.finished.connect(_done)
        self._authlib_worker.error.connect(lambda _e: _done(None))
        self._authlib_worker.start()

    def _browse_sound(self):
        path = pick_files(
            self, t("settings.sound_browse_title"),
            "", t("settings.sound_filter"),
        )
        if path:
            self.sound_file.setText(path)

    def _preview_sound(self):
        from .core.sound import SoundPlayer, ensure_default_exists
        f = self.sound_file.text().strip() or ensure_default_exists()
        p = SoundPlayer(self)
        p.play(f, self.sound_vol.value() / 100.0)

    def _reset_sound(self):
        self.sound_file.clear()
        info(self, t("settings.sound"), t("settings.sound_reset_ok"))

    def _open_diagnostics(self):
        from .diagnostics_dialog import DiagnosticsDialog
        DiagnosticsDialog(self).exec()

    # ── save ───────────────────────────────────────────────────────────────
    # ── language live switch ──
    def _on_lang_toggle(self, checked: bool):
        if not checked or self._rebuilding:
            return
        rb = self.sender()
        if rb and hasattr(rb, "lang_code"):
            set_language(rb.lang_code)
            self.cfg["language"] = rb.lang_code
            self._rebuild()

    def _rebuild(self):
        """Tear down and rebuild the whole dialog so every string reflects
        the newly selected language. Current input is preserved via cfg."""
        self._rebuilding = True
        try:
            self._sync_ui_to_cfg()
            self._clear_layout(self.layout())
            # Same teardown-between-builds guard as ``reload()`` — wipe
            # self.<widget> refs so an in-flight signal doesn't deref a dead
            # wrapper while the new UI is being assembled.
            for _name in list(self.__dict__.keys()):
                obj = self.__dict__[_name]
                if isinstance(obj, QWidget):
                    self.__dict__[_name] = None
            self._build_ui()
        finally:
            self._rebuilding = False

    @staticmethod
    def _clear_layout(layout):
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                SettingsPage._clear_layout(item.layout())

    @staticmethod
    def _safe(fn, default):
        """Read a Qt widget's state without crashing if its underlying C++
        object has already been deleted (typical during ``reload()`` /
        ``retranslate_ui()`` rebuilds). Returns *default* when the access
        raises ``RuntimeError`` — usually
        ``libshiboken: Internal C++ object ... already deleted``."""
        try:
            return fn()
        except RuntimeError:
            return default

    def _sync_ui_to_cfg(self):
        """Read all current control values back into self.cfg (no save).

        Every widget read is funneled through ``self._safe`` so a C++-deleted
        reference (which can occur during a teardown/rebuild race when the
        user opens the page while ``reload()`` / ``retranslate_ui()`` is in
        flight) cannot crash the whole save. The previous value in ``cfg``
        is kept as the fallback for any field whose control has gone away.
        """
        checked_ram = self._safe(self.ram_btns.checkedButton, None)
        if checked_ram:
            self.cfg["ram_mb"] = getattr(checked_ram, "val", self.cfg["ram_mb"])
        else:
            self.cfg["ram_mb"] = self._safe(self.ram.value, self.cfg["ram_mb"])
            self.cfg["launcher_ram_mb"] = self._safe(
                self.launcher_ram.value, self.cfg["launcher_ram_mb"])
            self.cfg["jvm_aikars"] = self._safe(
                self.aikars.isChecked, bool(self.cfg["jvm_aikars"]))
        checked_mode = self._safe(self.mode_btns.checkedButton, None)
        if checked_mode:
            self.cfg["window_mode"] = getattr(checked_mode, "mode_key", self.cfg["window_mode"])
        checked_res = self._safe(self.res_btns.checkedButton, None)
        if checked_res:
            self.cfg["res_w"], self.cfg["res_h"] = getattr(
                checked_res, "res_val", (self.cfg["res_w"], self.cfg["res_h"]))
        else:
            self.cfg["res_w"] = self._safe(self.rw.value, self.cfg["res_w"])
            self.cfg["res_h"] = self._safe(self.rh.value, self.cfg["res_h"])
        checked_lang = self._safe(self.lang_btns.checkedButton, None)
        if checked_lang:
            self.cfg["language"] = getattr(checked_lang, "lang_code", self.cfg["language"])
        checked_wp = self._safe(self.wp_modes.checkedButton, None)
        if checked_wp:
            self.cfg["wallpaper_mode"] = getattr(checked_wp, "wp_mode", self.cfg["wallpaper_mode"])
        self.cfg["wallpaper_opacity"] = self._safe(
            lambda: self.wp_opacity.value() / 100.0, self.cfg["wallpaper_opacity"])
        self.cfg["wallpaper_video_vol"] = self._safe(
            lambda: self.wp_vol.value() / 100.0, self.cfg["wallpaper_video_vol"])
        # 只开放 AC 默认模板；其余仍在制作中，强制写回 ac_default
        self.cfg["home_style"] = "ac_default"
        _nav_keys = ["ac", "pcl2"]
        idx = self._safe(self.nav_combo.currentIndex, 0)
        idx = max(0, min(idx, len(_nav_keys) - 1))
        self.cfg["nav_layout"] = _nav_keys[idx]
        checked_theme = self._safe(self.theme_btns.checkedButton, None)
        if checked_theme:
            self.cfg["theme_mode"] = getattr(checked_theme, "theme_mode_val", self.cfg["theme_mode"])
        self.cfg["theme_pack"] = self._safe(
            lambda: self.pack_combo.currentData() or "", self.cfg["theme_pack"])
        self.cfg["java_auto"] = self._safe(
            self.java_auto.isChecked, bool(self.cfg["java_auto"]))
        self.cfg["java_path"] = self._safe(self.java_path.text, self.cfg["java_path"])
        self.cfg["jvm_args"] = self._safe(self.jvm.toPlainText, self.cfg["jvm_args"])
        checked_mirror = self._safe(self.mirror_btns.checkedButton, None)
        if checked_mirror:
            self.cfg["download_mirror"] = getattr(checked_mirror, "mirror_key", self.cfg["download_mirror"])
        checked_proxy = self._safe(self.proxy_btns.checkedButton, None)
        if checked_proxy:
            key = getattr(checked_proxy, "proxy_key", "custom")
            self.cfg["download_proxy"] = self._safe(
                lambda: self.proxy_edit.text().strip() if key == "custom" else key,
                self.cfg["download_proxy"],
            )
        self.cfg["authlib_path"] = self._safe(
            lambda: self.authlib.text().strip(), self.cfg["authlib_path"])
        self.cfg["launch_sound"] = self._safe(
            self.sound_on.isChecked, bool(self.cfg["launch_sound"]))
        _rev = {
            t("settings.sound_trigger_game"): "game",
            t("settings.sound_trigger_app"): "app",
            t("settings.sound_trigger_both"): "both",
            t("settings.sound_trigger_off"): "off",
        }
        self.cfg["launch_sound_trigger"] = _rev.get(
            self._safe(self.sound_trig.currentText, t("settings.sound_trigger_game")),
            "game",
        )
        self.cfg["launch_sound_file"] = self._safe(
            lambda: self.sound_file.text().strip(), self.cfg["launch_sound_file"])
        self.cfg["launch_sound_vol"] = self._safe(
            lambda: self.sound_vol.value() / 100.0, self.cfg["launch_sound_vol"])
        self.cfg["bgm_enabled"] = self._safe(
            self.bgm_on.isChecked, bool(self.cfg["bgm_enabled"]))
        _mode_rev = {v: k for k, v in {
            "loop": t("settings.bgm_mode_loop"),
            "sequential": t("settings.bgm_mode_sequential"),
            "shuffle": t("settings.bgm_mode_shuffle"),
        }.items()}
        self.cfg["bgm_mode"] = _mode_rev.get(
            self._safe(self.bgm_mode.currentText, t("settings.bgm_mode_loop")),
            "loop",
        )
        # 多文件列表（替代单文件字段）
        try:
            self.cfg["bgm_files"] = [
                self.bgm_list.item(i).text() for i in range(self.bgm_list.count())
            ]
        except RuntimeError:
            pass  # bgm_list torn down — keep previous cfg["bgm_files"]
        if self.cfg.get("bgm_files"):
            self.cfg["bgm_file"] = self.cfg["bgm_files"][0]
        else:
            self.cfg["bgm_file"] = ""
        self.cfg["bgm_vol"] = self._safe(
            lambda: self.bgm_vol.value() / 100.0, self.cfg["bgm_vol"])
        self.cfg["sfx_enabled"] = self._safe(
            self.sfx_on.isChecked, bool(self.cfg["sfx_enabled"]))
        if hasattr(self, "sfx_files"):
            for _key, _le in self.sfx_files.items():
                self.cfg[f"sfx_{_key}"] = self._safe(
                    lambda le=_le: le.text().strip(), self.cfg.get(f"sfx_{_key}", ""))
        self.cfg["sfx_vol"] = self._safe(
            lambda: self.sfx_vol.value() / 100.0, self.cfg["sfx_vol"])
        self.cfg["splash_enabled"] = self._safe(
            self.splash_on.isChecked, bool(self.cfg["splash_enabled"]))
        if hasattr(self, '_custom_color') and self._custom_color:
            self.cfg["accent_color"] = self._custom_color
        else:
            for dot in self.color_btns:
                try:
                    style = dot.styleSheet()
                except RuntimeError:
                    continue
                if "border: 2px solid white" in style or "border: 2px solid #FFFFFF" in style:
                    self.cfg["accent_color"] = dot.color_hex
                    break

    # ── save ──
    def _save(self):
        self._sync_ui_to_cfg()
        save_config(self.cfg)

        # Background music — start/stop to match the new setting
        try:
            from .core.sound import apply_bgm
            apply_bgm(self.cfg)
        except Exception:  # noqa: BLE001 - audio must never block the save
            pass

        # ── Apply changes immediately ──
        from .theme import set_accent_color, apply_qss, set_theme_mode

        # Accent color
        set_accent_color(self.cfg.get("accent_color", "#7C3AED"))
        apply_qss()

        # Theme mode (light/dark)
        set_theme_mode(self.cfg.get("theme_mode", "light"))
        apply_qss()

        # Wallpaper — refresh home page background
        try:
            win = self._window
            if win is not None and hasattr(win, 'home'):
                win.home._apply_wallpaper()
                # Re-render home page with the (possibly) new style
                win.apply_home_style(self.cfg.get("home_style", "ac_default"))
                # NOTE: window_mode / resolution are GAME settings — applied at
                # launch time inside launch.py (resolutionWidth/Height +
                # options.txt `fullscreen`), NOT to the launcher window. Do not
                # resize/flag the launcher here: it conflicts with the frameless
                # helper and would break the custom title bar. The launcher's own
                # window size is persisted separately (see MainWindow geometry).
        except Exception:
            pass

        self.saved.emit()

    def _on_style_combo_changed(self, idx: int):
        """Live-apply the home style while the settings page is open.

        Only the AC default template is currently open — other entries are
        disabled in the combo, so a non-zero idx should never arrive; guard
        anyway so a stray signal can't force an unfinished template.
        """
        if idx != 0:
            # 未开放模板：强制回到 AC 默认（不应发生，纯防御）
            self.style_combo.blockSignals(True)
            self.style_combo.setCurrentIndex(0)
            self.style_combo.blockSignals(False)
            return
        self.cfg["home_style"] = "ac_default"
        win = self._window
        if win is not None and hasattr(win, "apply_home_style"):
            win.apply_home_style("ac_default")
