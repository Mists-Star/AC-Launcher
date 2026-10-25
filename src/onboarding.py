"""
OnboardingDialog — first-launch wizard.

Shows when launch_count < 3 (or after reset). Steps:
  1. Welcome + launcher mode recommendation
  2. Language selection
  3. Accent color pick
  4. RAM preset
  5. Java detection
  6. Done → writes settings + bumps launch count

Home style pick was removed (2026-08-01): template switching is Settings-only
to avoid re-render crashes on a not-yet-revealed main window.

Pure Qt, no external assets.
"""
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QWidget, QComboBox, QProgressBar,
    QCheckBox, QGridLayout,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from .theme import COLORS, RoundedCard, set_accent_color
from .icons import icon
from .i18n import t, set_language
from .frameless import FramelessHelper, TitleBar
from .settings_dialog import load_config, save_config, ACCENT_PRESETS
from .paths import get_data_dir
from .worker import TrackedThread


# Hardcoded defaults for the onboarding wizard. We deliberately do NOT read
# from the saved config here: every time the wizard opens (e.g. during
# DEV_FORCE_ONBOARDING testing) it must start from a clean default state and
# must NOT pollute the user's real saved settings.
ONBOARDING_DEFAULTS = {
    "language": "zh-CN",
    "accent_color": "#7C3AED",
    "ram_mb": 4096,
}

# ── appearance profiles ─────────────────────────────────────────────────────
# Each profile is exactly the switch set the bundled effect modules write, so
# the tutorial and the Modules page agree (picking a profile installs the
# matching bundles; uninstalling them later turns the effect off again).
#
# (config key, label key, est. RAM MB, est. single-core CPU %)
# The two numbers are rough per-effect weights for the relative meter only —
# they come from each effect's paint/compositing path, not from benchmarks:
#   * light trail owns a shared 30 fps repaint ticker (the only steady cost),
#   * acrylic hands blur to DWM (GPU-heavy, little CPU),
#   * frosted/transition are QSS/paint-time only, toasts are idle until shown.
_APPEARANCE_EFFECTS = [
    ("page_transition", "settings.page_transition", 2, 0.3),
    ("achievement_toasts", "settings.achievement_toasts", 2, 0.0),
    ("frosted_theme", "settings.frosted_theme", 4, 0.2),
    ("transparent_window", "settings.transparent_window", 5, 1.0),
    ("effect_light_trail", "settings.effect_light_trail", 8, 3.0),
]
_STYLE_ORDER = ("minimal", "normal", "fancy", "custom")
_STYLE_TIERS = {
    "minimal": set(),
    "normal": {"page_transition", "achievement_toasts"},
    "fancy": {key for key, _, _, _ in _APPEARANCE_EFFECTS},
    "custom": set(),      # resolved from the checkboxes instead
}
_EFFECT_MODULES = {
    "page_transition": "effect-page-transition",
    "achievement_toasts": "effect-achievement-toast",
    "frosted_theme": "effect-frosted-glass",
    "transparent_window": "effect-acrylic-window",
    "effect_light_trail": "effect-liquid-trail",
}


def _derive_style_tier(cfg: dict) -> str:
    """Name the profile a config currently matches (custom when it matches none)."""
    on = {key for key, _, _, _ in _APPEARANCE_EFFECTS if cfg.get(key, False)}
    if not on:
        return "minimal"
    for tier in ("normal", "fancy"):
        if on == _STYLE_TIERS[tier]:
            return tier
    return "custom"



def mark_onboarding_done() -> None:
    """round-45 恢复 flag 文件方案（用户明确说别乱改 onboarding）：
    写显式「已完成」flag，不依赖 launch_count。"""
    p = os.path.join(get_data_dir(), "onboarding_done.flag")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
    except OSError:
        pass


def reset_onboarding() -> None:
    """清 flag——让教程重新显示。设置页「重置新手教程」用。"""
    p = os.path.join(get_data_dir(), "onboarding_done.flag")
    try:
        os.remove(p)
    except OSError:
        pass


def should_show_onboarding() -> bool:
    # round-45 恢复（用户说别乱改 onboarding）：回到 round-44 flag 文件方案
    return not os.path.exists(
        os.path.join(get_data_dir(), "onboarding_done.flag"))


class OnboardingDialog(QDialog):
    """Multi-step wizard that runs before the main window on first launches."""

    STEPS = [
        ("welcome", [
            ("title", "onboard.title"),
            ("body", "onboard.welcome"),
            ("body", "onboard.mode_hint"),
        ]),
        ("lang", [
            ("title", "onboard.step_lang"),
        ]),
        ("color", [
            ("title", "onboard.step_color"),
        ]),
        ("style", [
            ("title", "onboard.step_style"),
            ("body", "onboard.style_text"),
        ]),
        ("ram", [
            ("title", "onboard.step_ram"),
        ]),
        ("java", [
            ("title", "onboard.step_java"),
            ("body", "onboard.java_text"),
        ]),
        ("done", [
            ("title", "onboard.step_done"),
            ("body", "onboard.done_text"),
        ]),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("onboard.title"))
        self.resize(640, 600)
        self.cfg = load_config()
        self._step = 0
        self._selected_color: str = ONBOARDING_DEFAULTS["accent_color"]
        self._style_tier: str = "minimal"

        # Round window corners on Win11 — same as MainWindow does. Without
        # this the wizard renders as a sharp rectangle (用户反馈"新手教程没圆角").
        try:
            from .win_rounded import enable_win11_round_corners
            enable_win11_round_corners(self)
        except Exception:
            pass

        # frameless shell
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # round-46 用户反馈：教程不该有 min/max/close（正常只有跳过/下一步）→ controls="none"
        self.titlebar = TitleBar(self, title=t("onboard.title"), height=38, controls="none")
        root.addWidget(self.titlebar)

        # content area — card style
        # 容器圆角一律自绘（QSS border-radius 对 QFrame 背景不裁剪，详见 theme.RoundedCard）
        self.body = RoundedCard(radius=12,
                                fill=QColor(COLORS["bg_panel"]))
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(36, 28, 36, 24)
        bl.setSpacing(16)

        self.title_lbl = QLabel()
        self.title_lbl.setProperty("cls", "title")
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {COLORS['text_main']}; background: transparent; border: none;")
        bl.addWidget(self.title_lbl)

        self.body_lbl = QLabel()
        self.body_lbl.setWordWrap(True)
        self.body_lbl.setStyleSheet(f"color: {COLORS['text_sub']}; font-size: 13px; background: transparent; border: none;")
        bl.addWidget(self.body_lbl)

        # step-specific widget area — recreated on each step change to prevent leaks
        self.step_widget = None  # created lazily in _show_step
        self._step_container = RoundedCard(radius=8, fill=QColor(COLORS["bg_panel"]))
        self._step_container_layout = QVBoxLayout(self._step_container)
        self._step_container_layout.setContentsMargins(20, 16, 20, 16)
        bl.addWidget(self._step_container)

        bl.addStretch(1)

        # navigation buttons
        nav = QHBoxLayout()
        self.prev_btn = QPushButton(t("onboard.prev"))
        self.prev_btn.setMinimumHeight(36)
        self.prev_btn.clicked.connect(self._prev)
        self.next_btn = QPushButton(t("onboard.next"))
        self.next_btn.setProperty("cls", "accent")
        self.next_btn.setMinimumHeight(36)
        self.next_btn.clicked.connect(self._next)
        self.skip_btn = QPushButton(t("onboard.skip"))
        self.skip_btn.setMinimumHeight(36)
        self.skip_btn.clicked.connect(self.reject)  # skip = close without saving
        nav.addWidget(self.prev_btn)
        nav.addStretch(1)
        nav.addWidget(self.skip_btn)
        nav.addWidget(self.next_btn)
        bl.addLayout(nav)

        root.addWidget(self.body, stretch=1)
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)

        self._show_step(0)

    def showEvent(self, e):
        super().showEvent(e)
        # 首启时主窗口尚未 show（教程走完才 _show_main），本对话框是一个
        # 「owner 不可见的 owned window」——Windows 默认不给这类窗口发任务栏
        # 按钮（用户反馈：教程窗口在、任务栏却找不到图标，容易以为程序没开）。
        # 加 WS_EX_APPWINDOW 强制它在任务栏占一个条目（图标继承 app windowIcon）。
        if getattr(self, "_appwindow_forced", False):
            return
        self._appwindow_forced = True
        try:
            import sys as _sys
            if _sys.platform != "win32":
                return
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_APPWINDOW)
        except Exception:  # noqa: BLE001 - 任务栏图标是增强，失败不阻断教程
            pass

    def _show_step(self, idx: int):
        self._step = idx
        step_def = self.STEPS[idx]
        step_key = step_def[0]

        # ── Nuke old step widget and create a fresh one ──
        # takeAt() removes the item from the layout (including any stretch /
        # spacer), then deleteLater() destroys the C++ object asynchronously.
        # Previous code only called deleteLater() and never removed the layout
        # item → every step switch (and language re-render) piled old widgets
        # into _step_container_layout, eventually freezing the wizard.
        while self._step_container_layout.count():
            item = self._step_container_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.step_widget = QWidget()
        self.step_widget.setStyleSheet("background: transparent;")
        self.step_layout = QVBoxLayout(self.step_widget)
        self.step_layout.setContentsMargins(0, 0, 0, 0)
        self.step_layout.setSpacing(12)
        self._step_container_layout.addWidget(self.step_widget)

        title_key = "onboard.title" if idx == 0 else f"onboard.step_{step_key}"
        self.title_lbl.setText(t(title_key))

        body_texts = []
        # step_def is (key, [items]); iterate the item list itself. The earlier
        # `step_def[1:]` iterated the one-element tuple wrapping that list, so
        # `key_type` was itself a tuple and **no body text ever rendered**.
        for item in step_def[1]:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                key_type, key = item
                if key_type == "body":
                    body_texts.append(t(key))
        body_text = "\n\n".join(body_texts)
        self.body_lbl.setVisible(bool(body_text))
        if body_text:
            self.body_lbl.setText(body_text)

        # build step-specific controls
        if step_key == "welcome":
            pass  # just text

        elif step_key == "lang":
            # round-79: checked 必须跟随 cfg 里已保存的语言（之前写死
            # ONBOARDING_DEFAULTS 导致重渲染后选中点永远回到中文，界面已变
            # 英文、radio 却显示中文被选）；English 未全面中文化，标“实验性”。
            self.lang_grp, lang_w = _radio_group(
                [("zh-CN", t("settings.lang_zh")),
                 ("en-US", t("settings.lang_en_lab"))],
                self.cfg.get("language", ONBOARDING_DEFAULTS["language"]),
            )
            # Connect each radio button: switch language immediately + re-render
            for rb in self.lang_grp.buttons():
                rb.toggled.connect(self._on_lang_picked)
            self.step_layout.addWidget(lang_w)

        elif step_key == "theme":
            from PySide6.QtWidgets import QRadioButton, QButtonGroup
            self.ob_theme_grp = QButtonGroup()
            theme_row = QHBoxLayout()
            theme_row.setSpacing(20)

            for mode, label, icon_name in [
                ("light", t("settings.theme_light"), "sun"),
                ("dark", t("settings.theme_dark"), "moon"),
            ]:
                # Card-style radio: icon + label in a framed card
                card = RoundedCard(radius=12, fill=QColor(COLORS["bg_input"]),
                                   border_color=COLORS["border"], border_width=2)
                card.setCursor(Qt.PointingHandCursor)
                card.setMinimumWidth(180)
                # hover：边框变 accent（自绘卡片不支持 QSS :hover，
                # 用 enter/leave 事件换边框色）
                def _hover_enter(e, c=card):
                    c.set_border(COLORS["accent"], 2)
                def _hover_leave(e, c=card):
                    c.set_border(COLORS["border"], 2)
                card.enterEvent = _hover_enter
                card.leaveEvent = _hover_leave
                card_lay = QHBoxLayout(card)
                card_lay.setContentsMargins(18, 14, 18, 14)
                card_lay.setSpacing(12)

                icon_lbl = QLabel()
                icon_lbl.setPixmap(icon(icon_name).pixmap(28, 28))
                icon_lbl.setStyleSheet("background: transparent; border: none;")
                card_lay.addWidget(icon_lbl)

                rb = QRadioButton(label)
                rb.setMinimumHeight(36)
                rb.setMinimumWidth(60)
                rb.setStyleSheet("background: transparent; border: none;")
                rb.theme_mode_val = mode
                rb.setChecked(mode == (self.cfg.get("theme_mode", "dark")))
                self.ob_theme_grp.addButton(rb)
                card_lay.addWidget(rb)

                # Click anywhere on card toggles the radio AND triggers theme apply
                card.mousePressEvent = lambda e, r=rb: (
                    r.setChecked(True) or self._on_ob_theme_picked(r)
                )
                theme_row.addWidget(card)

            theme_row.addStretch(1)
            self.step_layout.addLayout(theme_row)

            # Live preview: apply theme immediately on selection
            self.ob_theme_grp.buttonClicked.connect(self._on_ob_theme_picked)

            hint = QLabel(t("onboard.theme_hint"))
            hint.setProperty("cls", "sub")
            hint.setWordWrap(True)
            self.step_layout.addWidget(hint)

        elif step_key == "color":
            row = QHBoxLayout()
            row.setSpacing(12)
            self.ob_color_btns = []
            for hex_c, name in ACCENT_PRESETS:
                dot = QPushButton()
                dot.setFixedSize(44, 44)
                dot.setCursor(Qt.PointingHandCursor)
                dot.setToolTip(name)
                is_current = hex_c == self._selected_color
                # Use dark border for selection — visible on both light & dark bg
                border_color = COLORS["accent"] if is_current else "transparent"
                border_width = "3px" if is_current else "2px"
                dot.setStyleSheet(
                    f"QPushButton {{ background: {hex_c}; border-radius: 22px; "
                    f"border: {border_width} solid {border_color}; }}"
                    f"QPushButton:hover {{ border: 2px solid {COLORS['text_sub']}; }}"
                )
                dot.color_hex = hex_c
                dot.clicked.connect(lambda checked, h=hex_c: self._ob_pick(h))
                self.ob_color_btns.append(dot)
                row.addWidget(dot)
            row.addStretch(1)
            self.step_layout.addLayout(row)

        elif step_key == "style":
            self._build_style_step()

        elif step_key == "ram":
            self.ram_grp, ram_w = _radio_group(
                [(2048, t("settings.ram_2g")), (4096, t("settings.ram_4g")),
                 (8192, t("settings.ram_8g")), (16384, t("settings.ram_16g"))],
                ONBOARDING_DEFAULTS["ram_mb"],
            )
            self.step_layout.addWidget(ram_w)

        elif step_key == "java":
            # Detection status
            self.java_status = QLabel()
            self.java_status.setWordWrap(True)
            self.java_status.setProperty("cls", "sub")
            # ── 异步检测 ──
            # find_java() 走 os.walk 扫多个安装根目录、installed_majors()
            # 也扫磁盘 —— 同步执行会让欢迎页卡住数秒。先显示"检测中"，
            # 结果出来后由 Worker 回调填充 UI（快速实现：单次线程）。
            self.java_status.setText(t("onboard.java_checking"))
            self.step_layout.addWidget(self.java_status)
            self._java_scan_worker = _JavaScanThread()
            self._java_scan_worker.done.connect(self._on_java_scan_done)
            self._java_scan_worker.start()

            self.java_progress = QProgressBar()
            self.java_progress.setMaximum(0)  # indeterminate until size known
            self.java_progress.setTextVisible(False)
            self.java_progress.setVisible(False)
            self.step_layout.addWidget(self.java_progress)

        elif step_key == "done":
            self.next_btn.setText(t("onboard.finish"))

        # button state + always refresh nav labels for i18n
        self.prev_btn.setEnabled(idx > 0)
        self.skip_btn.setVisible(idx < len(self.STEPS) - 1)
        # Re-apply translated text to nav buttons & window/titlebar (i18n)
        self.prev_btn.setText(t("onboard.prev"))
        self.skip_btn.setText(t("onboard.skip"))
        if idx < len(self.STEPS) - 1:
            self.next_btn.setText(t("onboard.next"))
        else:
            self.next_btn.setText(t("onboard.finish"))
        title_text = t("onboard.title")
        self.setWindowTitle(title_text)
        self.titlebar.set_title(title_text)

    def _ob_pick(self, hex_color: str):
        self._selected_color = hex_color
        for dot in self.ob_color_btns:
            active = dot.color_hex == hex_color
            border_color = COLORS["accent"] if active else "transparent"
            border_width = "3px" if active else "2px"
            dot.setStyleSheet(
                f"QPushButton {{ background: {dot.color_hex}; border-radius: 22px; "
                f"border: {border_width} solid {border_color}; }}"
                f"QPushButton:hover {{ border: 2px solid {COLORS['text_sub']}; }}"
            )
        # Apply accent color immediately so user sees the effect everywhere
        set_accent_color(hex_color)
        self._refresh_qss()

    def _on_lang_picked(self, checked: bool):
        """Called when a language radio button is toggled."""
        if not checked:
            return
        rb = self.sender()
        if rb and hasattr(rb, 'val'):
            lang_code = rb.val
            set_language(lang_code)
            self.cfg["language"] = lang_code
            # Re-render current step so all text updates to new language
            self._show_step(self._step)

    def _on_ob_theme_picked(self, rb):
        """Live-preview theme when user picks light/dark in onboarding."""
        if rb is None or not hasattr(rb, "theme_mode_val"):
            return
        mode = rb.theme_mode_val
        from .theme import set_theme_mode
        set_theme_mode(mode)
        self.cfg["theme_mode"] = mode
        self._refresh_qss()

    def _refresh_qss(self):
        """Re-generate and re-apply QSS so token changes take effect visually."""
        from .theme import apply_qss
        apply_qss()

    # ── appearance style step ─────────────────────────────────────────────
    def _build_style_step(self):
        """Tier picker + live cost meter (+ per-effect switches for custom).

        The profile is stored as the five config switches the effect modules
        write, so there is no extra "tier" key to keep in sync later.
        """
        self._style_tier = _derive_style_tier(self.cfg)
        self._style_cards = {}
        self._style_checks = {}
        self._style_syncing = False

        row = QHBoxLayout()
        row.setSpacing(8)
        self._style_group = QButtonGroup(self)
        self._style_group.buttonClicked.connect(
            lambda rb: self._on_style_tier(rb.tier_val))
        for tier in _STYLE_ORDER:
            card = RoundedCard(radius=10, fill=QColor(COLORS["bg_input"]),
                               border_color=COLORS["border"], border_width=2)
            card.setCursor(Qt.PointingHandCursor)
            card.setFixedWidth(126)
            card.setFixedHeight(64)
            card.mousePressEvent = (
                lambda e, tier=tier: self._pick_style_tier(tier))
            card.enterEvent = lambda e, c=card: c.set_border(COLORS["accent"], 2)
            card.leaveEvent = lambda e: self._refresh_style_borders()
            lay = QVBoxLayout(card)
            lay.setContentsMargins(10, 8, 10, 8)
            lay.setSpacing(2)
            rb = QRadioButton(t("onboard.style_" + tier))
            rb.setStyleSheet("background: transparent; border: none;")
            rb.tier_val = tier
            rb.setChecked(tier == self._style_tier)
            self._style_group.addButton(rb)
            hint = QLabel(t("onboard.style_%s_hint" % tier))
            hint.setProperty("cls", "sub")
            hint.setWordWrap(False)
            hint.setStyleSheet("background: transparent; border: none;")
            lay.addWidget(rb)
            lay.addWidget(hint)
            row.addWidget(card)
            self._style_cards[tier] = card
        row.addStretch(1)
        self.step_layout.addLayout(row)

        # ── cost meter: two slim bars (RAM / single-core CPU) ──
        meter = RoundedCard(radius=8, fill=QColor(COLORS["bg_panel"]))
        ml = QVBoxLayout(meter)
        ml.setContentsMargins(12, 8, 12, 8)
        ml.setSpacing(4)
        cap = QLabel(t("onboard.style_estimate"))
        cap.setStyleSheet(
            "color: %s; font-size: 12px; font-weight: 600;"
            " background: transparent; border: none;" % COLORS["text_sub"])
        ml.addWidget(cap)
        self._style_mem_bar, self._style_mem_lbl = self._meter_row(
            ml, t("onboard.style_mem_cap"))
        self._style_cpu_bar, self._style_cpu_lbl = self._meter_row(
            ml, t("onboard.style_cpu_cap"))
        note = QLabel(t("onboard.style_note"))
        note.setProperty("cls", "sub")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 11px; background: transparent;"
                           " border: none;")
        # A word-wrapped QLabel reports one text line through sizeHint, so a
        # content-sized card used to clip the note to a single line. Reserve
        # three lines instead — enough for both zh and en at this width.
        note.setMinimumHeight(note.fontMetrics().lineSpacing() * 3)
        ml.addWidget(note)
        self.step_layout.addWidget(meter)

        # ── per-effect switches (only visible for "custom") ──
        self._style_custom_box = QWidget()
        self._style_custom_box.setStyleSheet("background: transparent;")
        gl = QGridLayout(self._style_custom_box)
        gl.setContentsMargins(2, 0, 2, 0)
        gl.setHorizontalSpacing(16)
        gl.setVerticalSpacing(4)
        for i, (key, name_key, mem_mb, cpu_pct) in enumerate(_APPEARANCE_EFFECTS):
            cb = QCheckBox(t(name_key))
            cb.effect_key = key
            cb.setChecked(bool(self.cfg.get(key, False)))
            cb.setToolTip("+%d MB / +%.1f%%" % (mem_mb, cpu_pct))
            cb.stateChanged.connect(self._on_style_check)
            self._style_checks[key] = cb
            gl.addWidget(cb, i // 2, i % 2)
        self.step_layout.addWidget(self._style_custom_box)

        self._style_custom_box.setVisible(self._style_tier == "custom")
        self._refresh_style_borders()
        self._update_style_meter()

    def _meter_row(self, layout, caption: str):
        """One slim bar row: caption | bar | value. Returns (bar, value label)."""
        row = QHBoxLayout()
        row.setSpacing(8)
        cap = QLabel(caption)
        cap.setFixedWidth(34)
        cap.setStyleSheet(
            "color: %s; font-size: 11px; background: transparent; border: none;"
            % COLORS["text_sub"])
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        bar.setStyleSheet(
            "QProgressBar { background: %s; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: %s; border-radius: 3px; }"
            # Track uses the border token, not bg_input: in the light theme
            # bg_input and bg_panel are the same #F8F9FA, so an empty bar was
            # invisible (only the numbers showed).
            % (COLORS["border"], COLORS["accent"]))
        val = QLabel("+0")
        val.setFixedWidth(64)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val.setStyleSheet(
            "color: %s; font-size: 11px; background: transparent; border: none;"
            % COLORS["text_main"])
        row.addWidget(cap)
        row.addWidget(bar, 1)
        row.addWidget(val)
        layout.addLayout(row)
        return bar, val

    def _selected_effect_keys(self) -> set:
        """Switches implied by the current tier / checkbox state."""
        if self._style_tier == "custom":
            return {key for key, cb in self._style_checks.items()
                    if cb.isChecked()}
        return set(_STYLE_TIERS.get(self._style_tier, ()))

    def _pick_style_tier(self, tier: str):
        for rb in self._style_group.buttons():
            if rb.tier_val == tier:
                rb.setChecked(True)
                break
        self._on_style_tier(tier)

    def _on_style_tier(self, tier: str):
        self._style_tier = tier
        if tier != "custom":
            self._style_syncing = True
            wanted = set(_STYLE_TIERS[tier])
            for key, cb in self._style_checks.items():
                cb.setChecked(key in wanted)
            self._style_syncing = False
        self._style_custom_box.setVisible(tier == "custom")
        self._refresh_style_borders()
        self._update_style_meter()

    def _on_style_check(self, _state: int = 0):
        """A single switch was toggled → the profile is custom by definition."""
        if self._style_syncing:
            return
        self._style_tier = "custom"
        for rb in self._style_group.buttons():
            if rb.tier_val == "custom":
                rb.setChecked(True)
                break
        self._refresh_style_borders()
        self._update_style_meter()

    def _refresh_style_borders(self):
        for tier, card in getattr(self, "_style_cards", {}).items():
            try:
                card.set_border(
                    COLORS["accent"] if tier == self._style_tier
                    else COLORS["border"], 2)
            except Exception:  # noqa: BLE001 - mid-teardown widget
                pass

    def _update_style_meter(self):
        if not hasattr(self, "_style_mem_bar"):
            return
        keys = self._selected_effect_keys()
        mem = sum(c[2] for c in _APPEARANCE_EFFECTS if c[0] in keys)
        cpu = sum(c[3] for c in _APPEARANCE_EFFECTS if c[0] in keys)
        max_mem = sum(c[2] for c in _APPEARANCE_EFFECTS)
        max_cpu = sum(c[3] for c in _APPEARANCE_EFFECTS)
        self._style_mem_bar.setValue(
            int(round(mem * 100.0 / max_mem)) if max_mem else 0)
        self._style_cpu_bar.setValue(
            int(round(cpu * 100.0 / max_cpu)) if max_cpu else 0)
        self._style_mem_lbl.setText(t("onboard.style_mem_val", mb=mem))
        self._style_cpu_lbl.setText(
            t("onboard.style_cpu_val", cpu=("%.1f" % cpu)))

    def _sync_effect_modules(self, wanted: set) -> None:
        """Install the bundles the player picked so the Modules page keeps a
        real switch for them (installed → uninstall turns the effect off).

        Failures are tolerated: ``_commit_appearance`` writes the same switches
        straight into the config, so the chosen look still applies even when a
        bundle cannot be copied (read-only / portable layouts).
        """
        try:
            from . import modules as M
        except Exception:  # noqa: BLE001 - modules are optional bookkeeping
            return
        try:
            entries = {e.get("id"): e for e in M.load_catalog()
                       if e.get("type") == "effect"}
        except Exception:  # noqa: BLE001
            entries = {}
        for key, mid in _EFFECT_MODULES.items():
            if key not in wanted:
                continue
            try:
                mod = M.find_module(mid)
                if mod is None:
                    entry = entries.get(mid)
                    if entry is None:
                        continue
                    mod = M.install_bundle(entry)
                M.apply_effect_module(mod, reapply=False)
            except Exception:  # noqa: BLE001 - keep the rest of the profile
                continue

    def _commit_appearance(self) -> None:
        """Persist the wizard's picks and hand them to the (hidden) main window.

        Until now the wizard never wrote the config: language / accent / RAM
        lived only in this process, and the main window's exit-time save
        re-wrote its pre-wizard copy over anything that did land on disk. The
        appearance profile needs the same treatment — the window was built
        before this dialog opened.
        """
        keys = {key for key, _, _, _ in _APPEARANCE_EFFECTS
                if self.cfg.get(key, False)}
        for key, _, _, _ in _APPEARANCE_EFFECTS:
            self.cfg[key] = key in keys
        try:
            save_config(self.cfg)
        except Exception:  # noqa: BLE001 - read-only install → session-only
            pass
        self._sync_effect_modules(keys)
        # Module payloads write their own switch on apply; re-read so the final
        # state is exactly the chosen profile (an installed but deselected
        # effect stays off) and drop stale ownership claims, otherwise the
        # Modules page would keep showing "applied" for a switch that is off.
        try:
            cfg = load_config()
            for key, _, _, _ in _APPEARANCE_EFFECTS:
                cfg[key] = key in keys
            owners = dict(cfg.get("_effect_owners") or {})
            for key, mid in _EFFECT_MODULES.items():
                if key not in keys:
                    owners.pop(key, None)
            cfg["_effect_owners"] = owners
            save_config(cfg)
        except Exception:  # noqa: BLE001
            cfg = self.cfg
        win = self.parent()
        try:
            if win is not None and hasattr(win, "apply_appearance_config"):
                win.apply_appearance_config(cfg)
        except Exception:  # noqa: BLE001 - appearance must not block finishing
            pass

    def _prev(self):
        if self._step > 0:
            # Commit the current step before rebuilding it: without this, a
            # choice survives only if it was applied globally (colour/theme),
            # and stepping back then forward silently reset radios to the
            # values that were already in cfg.
            self._save_step()
            self._show_step(self._step - 1)

    def _next(self):
        if self._step < len(self.STEPS) - 1:
            # save current step's choice before advancing
            self._save_step()
            self._show_step(self._step + 1)
        else:
            self._save_step()
            # Persist the picks and push them into the main window, which was
            # constructed before the wizard opened.
            self._commit_appearance()
            # User finished the wizard — mark it done so the next launch
            # skips past ``should_show_onboarding()``.
            mark_onboarding_done()
            self.accept()

    def reject(self):
        # User skipped — same effect as finishing: don't show it again.
        mark_onboarding_done()
        super().reject()

    def _save_step(self):
        key = self.STEPS[self._step][0]
        if key == "lang" and hasattr(self, 'lang_grp'):
            chk = self.lang_grp.checkedButton()
            if chk:
                self.cfg["language"] = chk.val
        elif key == "color":
            self.cfg["accent_color"] = self._selected_color
        elif key == "ram" and hasattr(self, 'ram_grp'):
            chk = self.ram_grp.checkedButton()
            if chk:
                self.cfg["ram_mb"] = chk.val
        elif key == "theme" and hasattr(self, 'ob_theme_grp'):
            chk = self.ob_theme_grp.checkedButton()
            if chk and hasattr(chk, "theme_mode_val"):
                self.cfg["theme_mode"] = chk.theme_mode_val
        elif key == "style" and hasattr(self, "_style_checks"):
            keys = self._selected_effect_keys()
            for effect_key, _, _, _ in _APPEARANCE_EFFECTS:
                self.cfg[effect_key] = effect_key in keys

    # ── Java install (step) ──
    def _on_java_scan_done(self, result: tuple):
        """Async Java detection finished → build the ready/install UI."""
        try:
            if self._step >= len(self.STEPS) or self.STEPS[self._step][0] != "java":
                return  # user already moved on
            sys_java, ours = result
            self._java_detected = bool(sys_java or ours)
            if self._java_detected:
                # ── Java already available: show "ready" UI ──
                detected_path = sys_java or ours[max(ours)]
                self.title_lbl.setText(t("onboard.step_java_ok"))
                self.body_lbl.setText(t("onboard.java_ok_text"))
                self.body_lbl.setVisible(True)
                self.java_status.setText(t("onboard.java_have", path=detected_path))
                self.java_combo = None
                self.java_install_btn = None
                mgr_hint = QLabel(t("onboard.java_mgr_hint"))
                mgr_hint.setWordWrap(True)
                mgr_hint.setProperty("cls", "sub")
                self.step_layout.addWidget(mgr_hint)
            else:
                # ── No Java: show full install UI ──
                from .core import java_install
                self.java_status.setText(t("onboard.java_text"))
                self.java_combo = QComboBox()
                for major, desc in java_install.JAVA_CHOICES:
                    self.java_combo.addItem(f"Java {major} — {desc}", major)
                idx21 = self.java_combo.findData(21)
                if idx21 >= 0:
                    self.java_combo.setCurrentIndex(idx21)
                self.java_combo.setStyleSheet(
                    f"QComboBox {{ background: {COLORS['bg_input']}; color: {COLORS['text_main']}; "
                    f"border: 1px solid {COLORS['border']}; border-radius: 6px; padding: 6px 10px; }}"
                    f"QComboBox::dropdown {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; }}"
                    f"QComboBox QAbstractItemView {{ background: {COLORS['bg_card']}; color: {COLORS['text_main']}; "
                    f"border: 1px solid {COLORS['border']}; outline: none; padding: 4px 0; }}"
                    f"QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 4px 12px; "
                    f"color: {COLORS['text_main']}; background: {COLORS['bg_card']}; }}"
                    f"QComboBox QAbstractItemView::item:hover {{ background: {COLORS['bg_hover']}; }}"
                    f"QComboBox QAbstractItemView::item:selected {{ background: {COLORS['accent_soft']}; color: {COLORS['text_accent']}; }}"
                )
                self.step_layout.addWidget(self.java_combo)
                self.java_install_btn = QPushButton(t("onboard.java_install"))
                self.java_install_btn.setProperty("cls", "accent")
                self.java_install_btn.setMinimumHeight(36)
                self.java_install_btn.clicked.connect(self._on_java_install)
                self.step_layout.addWidget(self.java_install_btn)
        except Exception:  # noqa: BLE001 - never let detection break the wizard
            pass

    def _on_java_install(self):
        if getattr(self, "_java_thread", None) and self._java_thread.isRunning():
            return
        major = self.java_combo.currentData()
        self.java_install_btn.setEnabled(False)
        self.java_progress.setVisible(True)
        self.java_status.setText(t("onboard.java_installing", major=major))
        self._java_thread = _JavaInstallThread(major)
        self._java_thread.progressed.connect(self._on_java_progress)
        self._java_thread.done.connect(self._on_java_done)
        self._java_thread.failed.connect(self._on_java_failed)
        self._java_thread.start()

    def _on_java_progress(self, done: int, mx: int):
        try:
            if mx and mx > 0:
                self.java_progress.setMaximum(mx)
                self.java_progress.setValue(done)
                self.java_progress.setTextVisible(True)
            else:
                self.java_progress.setMaximum(0)
        except Exception:  # noqa: BLE001 - widget may be mid-teardown
            pass

    def _on_java_done(self, path: str):
        try:
            self.java_progress.setVisible(False)
            self.java_progress.setMaximum(100)
            self.java_progress.setValue(0)
            self.java_install_btn.setEnabled(True)
            self.java_status.setText(t("onboard.java_done", path=path))
        except Exception:  # noqa: BLE001
            pass
        # Persist the Java choice (an install action, not a preview) so it
        # survives the wizard and is used at launch time.
        self.cfg["java_path"] = path
        self.cfg["java_auto"] = False
        self._persist_java()

    def _on_java_failed(self, err: str):
        try:
            self.java_progress.setVisible(False)
            self.java_install_btn.setEnabled(True)
            self.java_status.setText(t("onboard.java_failed", e=err))
        except Exception:  # noqa: BLE001
            pass

    def _persist_java(self):
        """Merge the Java choice into the saved config without touching the
        wizard's preview-only settings (accent / ram / lang)."""
        cfg = load_config()
        cfg["java_path"] = self.cfg.get("java_path", "")
        cfg["java_auto"] = self.cfg.get("java_auto", True)
        save_config(cfg)


def _radio_group(options, default_val) -> tuple:
    """Build a horizontal radio button group. Returns (QButtonGroup, QWidget)."""
    grp = QButtonGroup()
    row = QHBoxLayout()
    for val, label in options:
        rb = QRadioButton(label)
        rb.setChecked(val == default_val)
        rb.val = val
        grp.addButton(rb)
        row.addWidget(rb)
    row.addStretch(1)
    container = QWidget()
    container.setLayout(row)
    return grp, container


class _JavaScanThread(TrackedThread):
    """Async Java detection (PATH + os.walk over install roots).

    Running this off the GUI thread keeps the onboarding wizard responsive —
    the scan touches multiple Program Files roots and can take a second or two
    on a slow disk.
    """

    done = Signal(object)  # (sys_java, ours_dict)

    def run(self) -> None:
        try:
            from .core.java import find_java
            from .core import java_install
            sys_java = find_java()
            ours = java_install.installed_majors()
            self.done.emit((sys_java, ours))
        except Exception:  # noqa: BLE001 - treat as "no java detected"
            self.done.emit((None, {}))


class _JavaInstallThread(TrackedThread):
    """Download + unpack a portable Java runtime off the GUI thread.

    Bridges ``java_install.install_java``'s (done, total, phase) callback to Qt
    signals so the wizard can show a live progress bar without blocking.
    """

    progressed = Signal(int, int)   # value, max (-1 = unknown)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, major: int):
        super().__init__()
        self._major = major

    def run(self) -> None:
        try:
            from .core import java_install

            def _cb(done: int, total: int, phase: str) -> None:
                self.progressed.emit(done, total if total else -1)

            path = java_install.install_java(self._major, progress=_cb)
            self.done.emit(path)
        except Exception as e:  # noqa: BLE001 - surface to the UI
            self.failed.emit(str(e))
