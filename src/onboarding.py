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
    QRadioButton, QButtonGroup, QWidget, QFrame, QComboBox, QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QColor

from .theme import COLORS, RoundedCard, set_accent_color, build_qss
from .icons import icon
from .i18n import t, set_language
from .frameless import FramelessHelper, TitleBar
from .settings_dialog import load_config, save_config, ACCENT_PRESETS
from .paths import get_data_dir


# Hardcoded defaults for the onboarding wizard. We deliberately do NOT read
# from the saved config here: every time the wizard opens (e.g. during
# DEV_FORCE_ONBOARDING testing) it must start from a clean default state and
# must NOT pollute the user's real saved settings.
ONBOARDING_DEFAULTS = {
    "language": "zh-CN",
    "accent_color": "#7C3AED",
    "ram_mb": 4096,
    "home_style": "ac_default",
}


def get_launch_count() -> int:
    p = os.path.join(get_data_dir(), "launch_count.txt")
    try:
        with open(p, "r") as f:
            return int(f.read().strip() or "0")
    except (FileNotFoundError, ValueError):
        return 0


def increment_launch_count() -> int:
    p = os.path.join(get_data_dir(), "launch_count.txt")
    try:
        c = get_launch_count() + 1
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(str(c))
        return c
    except OSError:
        return 999  # skip onboarding if we can't write


def mark_onboarding_done() -> None:
    """Force the launch_count past the onboarding threshold so the wizard
    never shows again — called both when the user completes it (done step)
    AND when they skip it (reject). Without this, every fresh launch sees
    ``launch_count=0 < 3`` and the wizard reappears forever (every prior
    ship had this bug — the done/skip paths never wrote the counter)."""
    p = os.path.join(get_data_dir(), "launch_count.txt")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("999")
    except OSError:
        pass


def should_show_onboarding() -> bool:
    return get_launch_count() < 3


class OnboardingDialog(QDialog):
    """Multi-step wizard that runs before the main window on first launches."""

    # Emitted whenever the user picks a home style, so the live main window can
    # re-render its home page immediately (without persisting anything to disk).
    style_changed = Signal(str)

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
        ("ram", [
            ("title", "onboard.step_ram"),
        ]),
        # NOTE: "style" step intentionally removed (2026-08-01) — template
        # switching in the wizard caused dangling-C++-widget crashes
        # (libshiboken "already deleted") while the live home page re-renders.
        # Template switching is only available in Settings now. Restore by
        # re-adding ("style", [("title", "onboard.step_style")]) here.
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
        self.resize(620, 520)
        self.cfg = load_config()
        self._step = 0
        self._selected_color: str = ONBOARDING_DEFAULTS["accent_color"]

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

        self.titlebar = TitleBar(self, title=t("onboard.title"), height=38)
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
        for item in step_def[1:]:
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
            self.lang_grp, lang_w = _radio_group(
                [("zh-CN", t("settings.lang_zh")), ("en-US", t("settings.lang_en"))],
                ONBOARDING_DEFAULTS["language"],
            )
            # Connect each radio button: switch language immediately + re-render
            for rb in self.lang_grp.buttons():
                rb.toggled.connect(self._on_lang_picked)
            self.step_layout.addWidget(lang_w)

        elif step_key == "theme":
            from PySide6.QtWidgets import QRadioButton, QButtonGroup, QFrame
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

                from PySide6.QtGui import QPixmap
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

        elif step_key == "ram":
            self.ram_grp, ram_w = _radio_group(
                [(2048, t("settings.ram_2g")), (4096, t("settings.ram_4g")),
                 (8192, t("settings.ram_8g")), (16384, t("settings.ram_16g"))],
                ONBOARDING_DEFAULTS["ram_mb"],
            )
            self.step_layout.addWidget(ram_w)

        elif step_key == "style":
            self.style_grp, style_w = _radio_group(
                [("ac_default", t("style.ac_default")),
                 ("pcl_card", t("style.pcl_card")),
                 ("hmcl_list", t("style.hmcl_list")),
                 ("modrinth_modern", t("style.modrinth_modern"))],
                ONBOARDING_DEFAULTS["home_style"],
            )
            # Connect radio buttons: show preview + save immediately
            for rb in self.style_grp.buttons():
                rb.toggled.connect(self._on_style_picked)
            self.step_layout.addWidget(style_w)

            # Preview card — shows description of selected style
            self.style_preview = QLabel()
            self.style_preview.setWordWrap(True)
            self.style_preview.setObjectName("style_preview")
            self.style_preview.setStyleSheet(
                f"background: {COLORS['bg_panel']}; border-radius: 8px; "
                f"padding: 12px 16px; color: {COLORS['text_sub']}; "
                f"font-size: 12px; border: 1px solid {COLORS['border']};"
            )
            self.step_layout.addWidget(self.style_preview)
            self._update_style_preview(self.cfg.get("home_style", "ac_default"))

        elif step_key == "java":
            from .core.java import find_java
            from .core import java_install
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

    def _on_style_picked(self, checked: bool):
        """Called when a style radio button is toggled."""
        if not checked:
            return
        rb = self.sender()
        if rb and hasattr(rb, 'val'):
            self.cfg["home_style"] = rb.val
            self._update_style_preview(rb.val)
            # Notify the live main window so its home page re-renders immediately.
            # (We do NOT persist this — onboarding must not pollute saved config.)
            self.style_changed.emit(rb.val)

    def _on_ob_theme_picked(self, rb):
        """Live-preview theme when user picks light/dark in onboarding."""
        if rb is None or not hasattr(rb, "theme_mode_val"):
            return
        mode = rb.theme_mode_val
        from .theme import set_theme_mode, apply_qss
        set_theme_mode(mode)
        self.cfg["theme_mode"] = mode
        self._refresh_qss()

    def _update_style_preview(self, style_key: str):
        """Update the style preview card text based on selected style."""
        previews = {
            "ac_default": (
                "AC Default — Clean centered layout with a large Play button, "
                "instance card, and scan entry. Best for new users."
            ),
            "pcl_card": (
                "PCL Card — Grid of instance cards with version badges, "
                "mod count, and quick-action buttons. Visual & information-dense."
            ),
            "hmcl_list": (
                "HMCL List — Traditional list view with instance details "
                "in rows. Compact, familiar to HMCL users."
            ),
            "modrinth_modern": (
                "Modrinth Modern — Sidebar navigation with featured instances, "
                "horizontal scrolling cards, and modern spacing."
            ),
        }
        # Try i18n keys first, fall back to English descriptions
        key = f"style.preview_{style_key}"
        translated = t(key)
        if translated != key:  # translation exists
            text = translated
        else:
            text = previews.get(style_key, "")
        if hasattr(self, 'style_preview'):
            self.style_preview.setText(text)

    def _refresh_qss(self):
        """Re-generate and re-apply QSS so token changes take effect visually."""
        from .theme import apply_qss
        apply_qss()

    def _prev(self):
        if self._step > 0:
            self._show_step(self._step - 1)

    def _next(self):
        if self._step < len(self.STEPS) - 1:
            # save current step's choice before advancing
            self._save_step()
            self._show_step(self._step + 1)
        else:
            self._save_step()
            # User finished the wizard — mark it done so the next launch
            # skips past ``should_show_onboarding()``. The live main window
            # already reflects the picks via signals / global setters.
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
        elif key == "style" and hasattr(self, 'style_grp'):
            chk = self.style_grp.checkedButton()
            if chk:
                self.cfg["home_style"] = chk.val
        elif key == "theme" and hasattr(self, 'ob_theme_grp'):
            chk = self.ob_theme_grp.checkedButton()
            if chk and hasattr(chk, "theme_mode_val"):
                self.cfg["theme_mode"] = chk.theme_mode_val

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
        wizard's preview-only settings (accent / ram / style / lang)."""
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


class _JavaScanThread(QThread):
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


class _JavaInstallThread(QThread):
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
