"""Instance management pages: instance list/details + mods page.

Contains:
- InstanceCard      compact instance row used in the old list layout
- _InstRow          compact row for the new left-side instance list
- _LoaderCard       loader picker card in NewInstanceDialog
- NewInstanceDialog create-instance wizard (version + loader + java)
- InstancesPage     Prism-style split view: list | details
- ModCard / ModsPage  per-instance mod toggling
- _parse_mrpack_info / _MrpackDialog  Modrinth pack import
"""
from __future__ import annotations

import os
import shutil
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QDialog, QFormLayout, QLineEdit, QComboBox,
    QSizePolicy, QGridLayout, QCheckBox, QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from .theme import COLORS, RoundedCard
from .icons import icon
from .frameless import FramelessHelper, TitleBar
from .win_rounded import enable_win11_round_corners, confirm, pick_files, info, warn
from .i18n import t, loader_name
from .instances import manager, Instance, LOADERS
from .net_api import fetch_versions
from .worker import Worker, ProgressWorker


# ---------------------------------------------------------------- Instances
# Loader badge colors (brand-ish hues, used for the small pills on cards).
LOADER_BADGE = {
    "vanilla":      "#6B7280",
    "fabric":       "#DBB36C",
    "forge":        "#E04E14",
    "quilt":        "#61C8B8",
    "neoforge":     "#8B5CF6",
    "liteloader":   "#3B82F6",
    "legacyfabric": "#A78BFA",
    "cleanroom":    "#2DD4BF",
    "optifine":     "#F59E0B",
    "labymod":      "#22D3EE",
}

# loader → i18n key for its one-line description (shown under loader cards).
_LOADER_DESC = {
    "vanilla":      "new_instance.ld_vanilla",
    "fabric":       "new_instance.ld_fabric",
    "forge":        "new_instance.ld_forge",
    "quilt":        "new_instance.ld_quilt",
    "neoforge":     "new_instance.ld_neoforge",
    "liteloader":   "new_instance.ld_liteloader",
    "legacyfabric": "new_instance.ld_legacyfabric",
    "cleanroom":    "new_instance.ld_cleanroom",
    "optifine":     "new_instance.ld_optifine",
    "labymod":      "new_instance.ld_labymod",
}


def _badge_style(color: str) -> str:
    """Small rounded pill (loader badges on cards)."""
    return (
        f"color: {color}; background: {color}1F; border-radius: 9px; "
        f"padding: 2px 10px; font-size: 11px; font-weight: 600;"
    )


def _fetch_loader_versions(mc_version: str, loader: str) -> list[dict]:
    """Return [{title, meta}] for the loader, or [] on any error.

    Runs inside a Worker thread. Each branch maps a loader to its version
    source; all return a uniform list of dicts so the UI can render them as
    combo items (``title`` text + ``meta`` data).
    """
    if loader == "legacyfabric":
        from .net_api import fetch_legacy_fabric_loaders
        try:
            return [
                {"title": h["title"], "meta": h.get("_loader_version", "")}
                for h in fetch_legacy_fabric_loaders(mc_version)
            ]
        except Exception:
            return []
    if loader == "cleanroom":
        from .net_api import fetch_cleanroom_builds
        try:
            return [
                {"title": b["title"], "meta": b.get("_build", "")}
                for b in fetch_cleanroom_builds()
            ]
        except Exception:
            return []
    if loader == "optifine":
        from .net_api import fetch_optifine_versions
        try:
            return [
                {"title": v["title"], "meta": v.get("_filename", "")}
                for v in fetch_optifine_versions(mc_version)
            ]
        except Exception:
            return []
    # forge / neoforge via minecraft-launcher-lib
    try:
        from minecraft_launcher_lib.mod_loader import Forge, Neoforge
        if loader == "forge":
            return [
                {"title": v["version"], "meta": v["version"]}
                for v in Forge.forge_versions(mc_version)
            ]
        if loader == "neoforge":
            return [
                {"title": v["version"], "meta": v["version"]}
                for v in Neoforge.get_loader_versions()
            ]
    except Exception:
        pass
    # fabric via minecraft-launcher-lib
    try:
        from minecraft_launcher_lib.fabric import get_all_loader_versions
        if loader == "fabric":
            return [
                {"title": v["version"], "meta": v["version"]}
                for v in get_all_loader_versions()
            ]
    except Exception:
        pass
    return []


class InstanceCard(RoundedCard):
    set_current = Signal(str)
    removed = Signal(str)
    analyze = Signal(object)  # CrashAnalyzerDialog

    def __init__(self, inst: Instance, is_current: bool, parent=None):
        super().__init__(radius=12, parent=parent)
        self.inst = inst
        self.setMinimumHeight(84)
        self.setMaximumHeight(96)  # anti-stretch: cap height so the card stays compact
        # Ignore vertical resize hints from the parent scroll area
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(14)

        # ── rounded icon tile ──
        icon_box = QLabel()
        icon_box.setFixedSize(44, 44)
        icon_box.setAlignment(Qt.AlignCenter)
        icon_box.setProperty("cls", "tile")
        icon_box.setPixmap(icon("instances").pixmap(24, 24))
        lay.addWidget(icon_box)

        # ── info column: name + (version pill · loader badge) ──
        info = QVBoxLayout()
        info.setSpacing(6)
        name = QLabel(inst.name)
        name.setProperty("cls", "title")
        info.addWidget(name)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        ver_pill = QLabel(inst.game_version or "?")
        ver_pill.setProperty("cls", "pill")
        meta.addWidget(ver_pill)
        loader_color = LOADER_BADGE.get(inst.loader, LOADER_BADGE["vanilla"])
        ld_badge = QLabel(loader_name(inst.loader))
        ld_badge.setStyleSheet(_badge_style(loader_color))
        meta.addWidget(ld_badge)
        meta.addStretch(1)
        info.addLayout(meta)
        lay.addLayout(info, stretch=1)

        # ── right: current tag / actions ──
        if is_current:
            tag = QLabel("✓ " + t("instances.current"))
            tag.setStyleSheet(
                f"color: {COLORS['success']}; background: #22C55E1A; "
                f"font-weight: 600; border-radius: 10px; padding: 4px 12px;"
            )
            lay.addWidget(tag)
        else:
            b = QPushButton(t("instances.set_current"))
            b.setMinimumHeight(32)
            b.setIcon(icon("check"))
            b.setIconSize(QSize(16, 16))
            b.clicked.connect(lambda: self.set_current.emit(inst.id))
            lay.addWidget(b)

        crash_btn = QPushButton(t("instances.crash_analyze"))
        crash_btn.setMinimumHeight(32)
        crash_btn.setIcon(icon("repair"))
        crash_btn.setIconSize(QSize(16, 16))
        crash_btn.setToolTip(t("instances.crash_analyze_hint"))
        crash_btn.clicked.connect(lambda: self.analyze.emit(inst))
        lay.addWidget(crash_btn)

        del_btn = QPushButton(t("instances.delete"))
        del_btn.setProperty("cls", "danger")
        del_btn.setMinimumHeight(32)
        del_btn.setIcon(icon("delete"))
        del_btn.setIconSize(QSize(16, 16))
        del_btn.clicked.connect(lambda: self.removed.emit(inst.id))
        lay.addWidget(del_btn)


class _InstRow(RoundedCard):
    """Compact row for the left instance list (Prism style)."""

    clicked = Signal(str)

    def __init__(self, inst: Instance, is_current: bool, parent=None):
        super().__init__(radius=10, parent=parent)
        self.inst = inst
        self._selected = False
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        icon_box = QLabel()
        icon_box.setFixedSize(32, 32)
        icon_box.setAlignment(Qt.AlignCenter)
        icon_box.setProperty("cls", "tile")
        icon_box.setPixmap(icon("instances").pixmap(18, 18))
        lay.addWidget(icon_box)

        col = QVBoxLayout()
        col.setSpacing(2)
        nm = QLabel(inst.name)
        nm.setProperty("cls", "title")
        nm.setStyleSheet(f"color: {COLORS['text_main']}; font-size: 13px;")
        nm.setWordWrap(False)
        col.addWidget(nm)
        sub = QLabel(f"{inst.game_version or '?'}  ·  {loader_name(inst.loader)}")
        sub.setStyleSheet(f"color: {COLORS['text_sub']}; font-size: 11px;")
        col.addWidget(sub)
        lay.addLayout(col, stretch=1)

        self._cur_tag = QLabel("✓")
        self._cur_tag.setStyleSheet(
            f"color: {COLORS['success']}; font-weight: 700; font-size: 14px;")
        self._cur_tag.setVisible(is_current)
        lay.addWidget(self._cur_tag)

    def set_selected(self, on: bool):
        self._selected = on
        self.set_border(COLORS["accent"] if on else COLORS["border"],
                        2 if on else 1)
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit(self.inst.id)
        super().mousePressEvent(e)


class _LoaderCard(QFrame):
    """Clickable loader picker card — card-style selection (UI 大改 Step B)."""

    def __init__(self, dlg: "NewInstanceDialog", loader_id: str, color: str, parent=None):
        super().__init__(parent)
        self.dlg = dlg
        self.loader_id = loader_id
        self._color = color
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(74)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        top = QHBoxLayout()
        dot = QLabel()
        dot.setFixedSize(12, 12)
        dot.setStyleSheet(f"background: {color}; border-radius: 6px;")
        top.addWidget(dot)
        name = QLabel(loader_name(loader_id))
        name.setProperty("cls", "title")
        top.addWidget(name)
        top.addStretch(1)
        self._check = QLabel("✓")
        self._check.setStyleSheet(f"color: {COLORS['accent']}; font-weight: 700;")
        self._check.setVisible(False)
        top.addWidget(self._check)
        lay.addLayout(top)

        desc = QLabel(t(_LOADER_DESC.get(loader_id, "new_instance.ld_vanilla")))
        desc.setProperty("cls", "sub")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        self._apply_style(False)

    def _apply_style(self, selected: bool):
        self.setProperty("cls", "loader-card-on" if selected else "loader-card")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_selected(self, on: bool):
        self._check.setVisible(on)
        self._apply_style(on)

    def mousePressEvent(self, e):
        self.dlg._select_loader(self.loader_id)
        super().mousePressEvent(e)


class NewInstanceDialog(QDialog):
    """Create-instance wizard: name → loader → game version → Java."""

    def __init__(self, parent=None, preset_version: str = ""):
        super().__init__(parent)
        self.setWindowTitle(t("new_instance.title"))
        self.setMinimumWidth(520)
        self._versions = []
        self._loader = "vanilla"
        self._java_path = ""
        self._loader_cards = {}
        self._preset_version = preset_version

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self, title=t("new_instance.title"), height=38)
        root.addWidget(self.titlebar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(18)

        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        # ── name ──
        name_lbl = QLabel(t("new_instance.name"))
        name_lbl.setProperty("cls", "group")
        lay.addWidget(name_lbl)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("new_instance.name_placeholder"))
        self.name_edit.setMinimumHeight(36)
        lay.addWidget(self.name_edit)

        # ── loader picker ──
        ld_title = QLabel(t("new_instance.loader_pick"))
        ld_title.setProperty("cls", "group")
        lay.addWidget(ld_title)

        grid = QGridLayout()
        grid.setSpacing(10)
        cols = 3
        for i, loader_id in enumerate(LOADERS):
            card = _LoaderCard(self, loader_id, LOADER_BADGE.get(loader_id, LOADER_BADGE["vanilla"]))
            self._loader_cards[loader_id] = card
            grid.addWidget(card, i // cols, i % cols)
        # LabyMod card (opens the official site — not installable in-app)
        labymod_card = _LoaderCard(self, "labymod", LOADER_BADGE.get("labymod"))
        grid.addWidget(labymod_card, len(LOADERS) // cols, len(LOADERS) % cols)
        lay.addLayout(grid)

        # ── game version ──
        ver_title = QLabel(t("new_instance.version"))
        ver_title.setProperty("cls", "group")
        lay.addWidget(ver_title)
        self.version_combo = QComboBox()
        self.version_combo.setMinimumHeight(36)
        if preset_version:
            # 从版本页"安装"进入：锁定该版本，避免玩家改错。
            self.version_combo.setEnabled(False)
            self.version_combo.addItem(preset_version, preset_version)
        else:
            self.version_combo.addItem(t("new_instance.loading"))
        # ── 跳到版本库选择 ──
        # 同步体验：NewInstanceDialog 的 QComboBox 是平铺下拉，跟 VersionsPage
        # 的"最新/正式/快照/愚人节"分组卡片视觉差距大。给玩家一个"在版本库选"入口，
        # 跳到 VersionsPage 的卡牌界面（带加载器筛选），选完回调填入当前 combo。
        self.browse_btn = QPushButton(t("new_instance.browse_versions"))
        self.browse_btn.setMinimumHeight(32)
        self.browse_btn.clicked.connect(self._open_versions_picker)
        if preset_version:
            self.browse_btn.setEnabled(False)
        lay.addWidget(self.version_combo)
        lay.addWidget(self.browse_btn)
        self.snap_toggle = QCheckBox(t("new_instance.show_snapshots"))
        self.snap_toggle.setChecked(False)
        self.snap_toggle.toggled.connect(self._on_snap_toggle)
        lay.addWidget(self.snap_toggle)

        # ── loader version (hidden until a loader is chosen) ──
        ldver_box = QWidget()
        ldver_box.setVisible(False)
        lv_lay = QVBoxLayout(ldver_box)
        lv_lay.setContentsMargins(0, 0, 0, 0)
        lv_lay.setSpacing(6)
        ldver_title = QLabel(t("new_instance.loader_version"))
        ldver_title.setProperty("cls", "group")
        lv_lay.addWidget(ldver_title)
        self.ldver_combo = QComboBox()
        self.ldver_combo.setMinimumHeight(36)
        self.ldver_combo.addItem(t("new_instance.ldver_latest"))
        self.ldver_combo.setToolTip(t("new_instance.ldver_hint"))
        lv_lay.addWidget(self.ldver_combo)
        self.ldver_box = ldver_box
        lay.addWidget(ldver_box)
        # 版本变化 → 重新拉该版本的加载器列表
        self.version_combo.currentIndexChanged.connect(self._on_version_changed)

        # ── Java ──
        java_title = QLabel(t("new_instance.java_section"))
        java_title.setProperty("cls", "group")
        lay.addWidget(java_title)
        self.java_default = QCheckBox(t("new_instance.java_use_default"))
        self.java_default.setChecked(True)
        self.java_default.toggled.connect(self._on_java_default)
        lay.addWidget(self.java_default)
        self.java_row = QHBoxLayout()
        self.java_path_lbl = QLabel()
        self.java_path_lbl.setProperty("cls", "sub")
        self.java_path_lbl.setWordWrap(True)
        self.java_path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.java_choose = QPushButton(t("new_instance.java_choose"))
        self.java_choose.setMinimumHeight(32)
        self.java_choose.clicked.connect(self._choose_java)
        self.java_row.addWidget(self.java_path_lbl, 1)
        self.java_row.addWidget(self.java_choose)
        self.java_row_w = QWidget()
        self.java_row_w.setLayout(self.java_row)
        self.java_row_w.setVisible(False)
        lay.addWidget(self.java_row_w)

        # ── save path preview ──
        self.path_lbl = QLabel()
        self.path_lbl.setProperty("cls", "sub")
        self.path_lbl.setWordWrap(True)
        self.path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.path_lbl)

        # ── footer ──
        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton(t("new_instance.cancel"))
        cancel.setMinimumHeight(38)
        cancel.clicked.connect(self.reject)
        ok = QPushButton(t("new_instance.create"))
        ok.setProperty("cls", "accent")
        ok.setMinimumHeight(38)
        ok.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        lay.addLayout(foot)

        # frameless + DWM rounded corners
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

        # default to vanilla, kick off version fetch
        self._select_loader("vanilla")
        self.name_edit.textChanged.connect(self._update_path)
        self._update_path()

        self._worker = Worker(fetch_versions)
        self._worker.finished.connect(self._on_versions)
        self._worker.error.connect(lambda e: None)
        self._worker.start()

    # ------------------------------------------------------------------
    def _mc_too_new_for_liteloader(self) -> bool:
        parts = self._current_version_id().split(".")
        try:
            major, minor = int(parts[0]), int(parts[1])
            return (major, minor) > (1, 12)
        except Exception:
            return True  # unknown version — assume too new

    def _select_loader(self, loader_id: str):
        if loader_id == "labymod":
            self._open_labymod()
            return
        if loader_id == "liteloader":
            if self._mc_too_new_for_liteloader():
                info(self, t("common.hint"),
                     t("new_instance.ld_liteloader_new", ver=self._current_version_id()))
                return
        elif loader_id == "legacyfabric":
            if not self._is_legacy_fabric_ok(self._current_version_id()):
                info(self, t("common.hint"),
                     t("new_instance.ld_legacyfabric_new"))
                loader_id = "vanilla"
        elif loader_id == "cleanroom":
            if not self._is_legacy_fabric_ok("1.12.2"):
                info(self, t("common.hint"),
                     t("new_instance.ld_cleanroom_new"))
                loader_id = "vanilla"

        self._loader = loader_id
        for lid, card in self._loader_cards.items():
            card.set_selected(lid == loader_id)

        show_ldver = loader_id not in ("vanilla", "optifine", "labymod")
        if hasattr(self, "ldver_box"):
            self.ldver_box.setVisible(show_ldver)
            if show_ldver:
                self._load_loader_versions()
        self._update_path()

    def _open_labymod(self):
        QDesktopServices.openUrl(QUrl("https://www.labymod.net"))
        info(self, t("common.hint"), t("new_instance.labymod_visit"))

    def _is_legacy_fabric_ok(self, ver: str) -> bool:
        parts = ver.split(".")
        try:
            major, minor = int(parts[0]), int(parts[1])
            return (major, minor) <= (1, 13)
        except Exception:
            return False

    def _current_version_id(self) -> str:
        return self.version_combo.currentData() or self.version_combo.currentText() or ""

    def _on_version_changed(self, _index: int):
        if self._loader not in ("vanilla", "optifine", "labymod"):
            if hasattr(self, "ldver_box"):
                self._load_loader_versions()
        self._update_path()

    # ---------------- loader versions ----------------
    def _load_loader_versions(self):
        mc = self._current_version_id()
        loader = self._loader
        self.ldver_combo.blockSignals(True)
        self.ldver_combo.clear()
        self.ldver_combo.addItem(t("new_instance.ldver_latest"))
        self.ldver_combo.blockSignals(False)
        # 防竞态：生成器序号，只接受最新一次的返回
        gen = getattr(self, "_ldver_gen", 0) + 1
        self._ldver_gen = gen
        self._ldver_worker = Worker(_fetch_loader_versions, mc, loader)

        def _done(versions: list[dict], g=gen):
            if getattr(self, "_ldver_gen", 0) != g:
                return
            self._on_loader_versions(versions)

        def _err(e, g=gen):
            if getattr(self, "_ldver_gen", 0) != g:
                return

        self._ldver_worker.finished.connect(_done)
        self._ldver_worker.error.connect(_err)
        self._ldver_worker.start()

    def _on_loader_versions(self, versions: list[dict]):
        self.ldver_combo.blockSignals(True)
        self.ldver_combo.clear()
        self.ldver_combo.addItem(t("new_instance.ldver_latest"), "")
        for v in versions or []:
            if isinstance(v, dict):
                title = v.get("title") or ""
                meta = v.get("meta") or ""
                self.ldver_combo.addItem(title, meta)
        self.ldver_combo.blockSignals(False)

    def selected_loader_version(self) -> str:
        if not hasattr(self, "ldver_combo") or not self.ldver_combo.isVisible():
            return ""
        return self.ldver_combo.currentData() or ""

    # ---------------- java ----------------
    def _on_java_default(self, on: bool):
        self.java_row_w.setVisible(not on)
        if on:
            self._java_path = ""
            self.java_path_lbl.setText("")

    def _choose_java(self):
        from .java_manager_dialog import JavaManagerDialog
        dlg = JavaManagerDialog(self, current_path=self._java_path)
        if dlg.exec() == QDialog.Accepted and dlg.selected_path:
            self._java_path = dlg.selected_path
            self.java_path_lbl.setText(
                t("new_instance.java_selected", path=self._java_path))

    # ---------------- version library picker ----------------
    def _open_versions_picker(self):
        """Open a VersionsPage in a dialog; picking a version fills the combo."""
        from .pages_browse import VersionsPage
        dlg = QDialog(self)
        dlg.setWindowTitle(t("new_instance.browse_versions_title"))
        dlg.resize(880, 600)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        v = VersionsPage()
        # Intercept "install this version" → fill our combo instead of installing.
        if hasattr(v, "instance_created"):
            v.instance_created.disconnect()
        orig_create = v._create

        def _on_card_click(ver_id):
            self.version_combo.blockSignals(True)
            self.version_combo.clear()
            self.version_combo.addItem(ver_id, ver_id)
            self.version_combo.blockSignals(False)
            self._on_version_changed(0)
            dlg.accept()

        def _pick_create(ver_id):
            _on_card_click(ver_id)

        v._create = _pick_create
        lay.addWidget(v)
        dlg.exec()

    # ---------------- versions ----------------
    def _on_snap_toggle(self, on: bool):
        self._populate_versions(on)

    def _populate_versions(self, include_snap: bool):
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        if not self._versions:
            self.version_combo.addItem(t("new_instance.loading"))
            self.version_combo.blockSignals(False)
            return
        versions = [v for v in self._versions
                    if v.get("type") == "release"]
        if include_snap:
            versions = self._versions
        for v in versions[:60]:
            self.version_combo.addItem(v["id"], v["id"])
        if self.version_combo.count() == 0:
            self.version_combo.addItem("1.21.4", "1.21.4")
        self.version_combo.blockSignals(False)

    def _on_versions(self, data):
        err, versions = data if isinstance(data, tuple) else (None, data or [])
        self._versions = versions or []
        self._populate_versions(self.snap_toggle.isChecked())

    # ---------------- naming / path ----------------
    def _auto_name(self) -> str:
        ver = self.version_combo.currentData() or self.version_combo.currentText() or ""
        ver = ver.strip()
        if ver == t("new_instance.loading"):
            ver = "1.20.1"
        loader = self._loader
        name = ver
        if loader and loader != "vanilla":
            name = f"{ver}-{loader}"
        return name

    def _update_path(self):
        name = self.name_edit.text().strip()
        auto = self._auto_name()
        if not name:
            self.name_edit.setPlaceholderText(auto)
        else:
            self.name_edit.setPlaceholderText(t("new_instance.name_placeholder"))
        from .paths import get_data_dir
        safe_name = "".join(c for c in (name or auto) if c not in "-_. ")
        preview = os.path.join(get_data_dir(), "instances", f"{safe_name}/")
        self.path_lbl.setText(t("new_instance.save_to", path=preview))

    def result_data(self) -> tuple[str, str, str, str, str]:
        name = self.name_edit.text().strip()
        if not name:
            name = self._auto_name()
        version = self.version_combo.currentData() or self.version_combo.currentText()
        return (name, version, self._loader, self._java_path,
                self.selected_loader_version())


class InstancesPage(QWidget):
    """Instance manager — Prism-style split: compact list on the left, a
    details panel for the selected instance on the right.

    Left  : scrollable list of compact rows (icon + name + version pill).
            Clicking selects; the current (launch) instance gets a ✓ tag.
    Right : overview card for the selection — name, version/loader/Java/path,
            and action buttons (launch is on the home page; here: open folder,
            export mrpack, crash analysis, delete) plus section entries
            (Mods / Resource packs / Shaders / Saves) that jump to the
            corresponding pages with the instance pre-targeted.
    """

    current_changed = Signal(str)
    section_requested = Signal(str, str)  # section key, instance id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mgr = manager()
        self._rows: dict[str, _InstRow] = {}
        self._selected_id: str | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        # ── header ──
        head = QHBoxLayout()
        self.title_lbl = QLabel(t("instances.title"))
        self.title_lbl.setProperty("cls", "big")
        head.addWidget(self.title_lbl)
        head.addStretch(1)
        self.new_btn = QPushButton(t("instances.new"))
        self.new_btn.setProperty("cls", "accent")
        self.new_btn.setMinimumHeight(38)
        self.new_btn.setIcon(icon("add"))
        self.new_btn.setIconSize(QSize(16, 16))
        self.new_btn.clicked.connect(self._new)
        head.addWidget(self.new_btn)

        # 扫描并导入（把已有的 MC 文件夹接管/复制成实例）
        self.scan_btn = QPushButton(t("instances.scan_import"))
        self.scan_btn.setMinimumHeight(38)
        self.scan_btn.setIcon(icon("search"))
        self.scan_btn.setIconSize(QSize(16, 16))
        self.scan_btn.clicked.connect(self._open_scan)
        head.addWidget(self.scan_btn)

        # 导入整合包（.mrpack 文件）—— 次级样式以免和新建立例按钮视觉冲突
        self.mrpack_btn = QPushButton(t("instances.import_mrpack"))
        self.mrpack_btn.setMinimumHeight(38)
        self.mrpack_btn.setIcon(icon("download"))
        self.mrpack_btn.setIconSize(QSize(16, 16))
        self.mrpack_btn.clicked.connect(self._import_mrpack)
        head.addWidget(self.mrpack_btn)
        root.addLayout(head)

        # ── body: left list | right details ──
        body = QHBoxLayout()
        body.setSpacing(16)

        # ══ left column ══
        left = QWidget()
        left.setFixedWidth(280)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(8)

        self.list_lbl = QLabel(t("instances.list_title"))
        self.list_lbl.setProperty("cls", "group")
        left_lay.addWidget(self.list_lbl)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        self._list_content = QWidget()
        self._list_vbox = QVBoxLayout(self._list_content)
        self._list_vbox.setContentsMargins(0, 0, 0, 0)
        self._list_vbox.setSpacing(6)
        self.list_scroll.setWidget(self._list_content)
        left_lay.addWidget(self.list_scroll, stretch=1)
        body.addWidget(left)

        # ══ right details panel ══
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.NoFrame)
        self.detail_content = QWidget()
        self.detail_lay = QVBoxLayout(self.detail_content)
        self.detail_lay.setContentsMargins(0, 0, 0, 0)
        self.detail_lay.setSpacing(16)
        self.detail_scroll.setWidget(self.detail_content)
        body.addWidget(self.detail_scroll, stretch=1)

        # ── empty-state layer (built once, toggled in _refresh) ──
        # Inserting/removing a widget in _refresh repeatedly is what caused
        # "double page" — Qt keeps the old slot in the layout, so the next
        # insert lands *next to* the stale one. Build it once here and just
        # show()/hide() it.
        self._empty_holder = self._empty_state()
        self._empty_holder.setVisible(False)
        root.insertWidget(1, self._empty_holder)  # between head and body

        root.addLayout(body, stretch=1)
        QTimer.singleShot(0, self._refresh)

    # ------------------------------------------------------------------ view
    def _refresh(self):
        """Rebuild the left list + right details from the manager."""
        # teardown rows
        self._rows.clear()
        while self._list_vbox.count():
            item = self._list_vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                try:
                    from shiboken6 import delete as _shibdelete
                    _shibdelete(w)
                except Exception:
                    w.deleteLater()

        cur = self.mgr.current_id
        insts = self.mgr.list()
        if not insts:
            # toggle the pre-built empty-state layer — never insert/remove
            # widgets here (that produced stacked "double page" cards).
            holder = getattr(self, "_empty_holder", None)
            if holder is not None:
                holder.setVisible(True)
                holder.raise_()
            self.list_lbl.setVisible(False)
            self.list_scroll.setVisible(False)
            self.detail_scroll.setVisible(False)
            return

        self.list_lbl.setVisible(True)
        self.list_scroll.setVisible(True)
        self.detail_scroll.setVisible(True)
        holder = getattr(self, "_empty_holder", None)
        if holder is not None:
            holder.setVisible(False)

        for inst in insts:
            row = _InstRow(inst, is_current=(inst.id == cur))
            row.clicked.connect(self._select)
            self._rows[inst.id] = row
            self._list_vbox.addWidget(row)
        self._list_vbox.addStretch(1)

        # restore selection (keep previous if still valid, else current/first)
        if self._selected_id not in self._rows:
            self._selected_id = cur or (insts[0].id if insts else None)
        for rid, row in self._rows.items():
            row.set_selected(rid == self._selected_id)
        self._render_detail()

    def _render_detail(self):
        """Fill the right-hand details panel for the selected instance."""
        # clear previous detail widgets
        while self.detail_lay.count():
            item = self.detail_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                try:
                    from shiboken6 import delete as _shibdelete
                    _shibdelete(w)
                except Exception:
                    w.deleteLater()

        inst = self.mgr.get(self._selected_id) if self._selected_id else None
        if inst is None:
            return
        self._render_detail_card(inst)

    def _render_detail_card(self, inst: Instance):
        card = RoundedCard(radius=16)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        # name + current tag
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        nm = QLabel(inst.name)
        nm.setProperty("cls", "big")
        nm.setStyleSheet(f"font-size: 20px; color: {COLORS['text_main']};")
        name_row.addWidget(nm)
        if inst.id == self.mgr.current_id:
            tag = QLabel("✓ " + t("instances.current"))
            tag.setStyleSheet(
                f"color: {COLORS['success']}; background: #22C55E1A; "
                f"font-weight: 600; border-radius: 10px; padding: 4px 12px;"
            )
            name_row.addWidget(tag)
        name_row.addStretch(1)
        # launch button (jumps home & selects)
        launch_btn = QPushButton(t("instances.launch"))
        launch_btn.setProperty("cls", "accent")
        launch_btn.setMinimumHeight(36)
        launch_btn.setIcon(icon("play"))
        launch_btn.setIconSize(QSize(16, 16))
        launch_btn.clicked.connect(lambda: self._launch(inst.id))
        name_row.addWidget(launch_btn)
        lay.addLayout(name_row)

        # badges: version pill · loader badge · java
        meta = QHBoxLayout()
        meta.setSpacing(8)
        ver_pill = QLabel(inst.game_version or "?")
        ver_pill.setProperty("cls", "pill")
        meta.addWidget(ver_pill)
        loader_color = LOADER_BADGE.get(inst.loader, LOADER_BADGE["vanilla"])
        ld_badge = QLabel(loader_name(inst.loader))
        ld_badge.setStyleSheet(_badge_style(loader_color))
        meta.addWidget(ld_badge)
        if inst.loader_version:
            lv = QLabel(inst.loader_version)
            lv.setStyleSheet(_badge_style(loader_color))
            meta.addWidget(lv)
        if inst.java_path:
            jl = QLabel("☕ " + os.path.basename(inst.java_path))
            jl.setStyleSheet(_badge_style("#F59E0B"))
            meta.addWidget(jl)
        meta.addStretch(1)
        lay.addLayout(meta)

        # info grid
        grid = QFormLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        grid.setLabelAlignment(Qt.AlignRight)
        grid.addRow(QLabel(t("instances.detail_path")), self._mono(inst.mc_dir))
        grid.addRow(QLabel(t("instances.detail_source")),
                    QLabel(inst.launcher or "AC"))
        if inst.created_at:
            grid.addRow(QLabel(t("instances.detail_created")),
                        QLabel(inst.created_at))
        if inst.version_id and inst.version_id != inst.game_version:
            grid.addRow(QLabel("ID"), self._mono(inst.version_id))
        lay.addLayout(grid)

        # ── actions ──
        actions = QHBoxLayout()
        actions.setSpacing(8)
        open_btn = QPushButton(t("instances.open_folder"))
        open_btn.setMinimumHeight(34)
        open_btn.setIcon(icon("folder"))
        open_btn.setIconSize(QSize(15, 15))
        open_btn.clicked.connect(lambda: self._open_folder(inst))
        actions.addWidget(open_btn)

        cur_btn = QPushButton(t("instances.set_current"))
        cur_btn.setMinimumHeight(34)
        cur_btn.setIcon(icon("check"))
        cur_btn.setIconSize(QSize(15, 15))
        cur_btn.setEnabled(inst.id != self.mgr.current_id)
        cur_btn.clicked.connect(lambda: self._set_current(inst.id))
        actions.addWidget(cur_btn)

        crash_btn = QPushButton(t("instances.crash_analyze"))
        crash_btn.setMinimumHeight(34)
        crash_btn.setIcon(icon("repair"))
        crash_btn.setIconSize(QSize(15, 15))
        crash_btn.clicked.connect(lambda: self._analyze_crash(inst))
        actions.addWidget(crash_btn)

        actions.addStretch(1)
        del_btn = QPushButton(t("instances.delete"))
        del_btn.setProperty("cls", "danger")
        del_btn.setMinimumHeight(34)
        del_btn.setIcon(icon("delete"))
        del_btn.setIconSize(QSize(15, 15))
        del_btn.clicked.connect(lambda: self._remove(inst.id))
        actions.addWidget(del_btn)
        lay.addLayout(actions)

        # ── section entries ──
        sec_title = QLabel(t("instances.sections"))
        sec_title.setProperty("cls", "group")
        lay.addWidget(sec_title)
        sec_grid = QGridLayout()
        sec_grid.setSpacing(10)
        sections = [
            ("mods",      "instances.sec_mods",      "mods"),
            ("respack",   "instances.sec_respacks",  "image"),
            ("shaders",   "instances.sec_shaders",   "sparkles"),
            ("saves",     "instances.sec_saves",     "folder"),
        ]
        for i, (key, label_key, ico) in enumerate(sections):
            b = QPushButton(t(label_key))
            b.setMinimumHeight(44)
            b.setIcon(icon(ico))
            b.setIconSize(QSize(16, 16))
            b.clicked.connect(
                lambda _c=False, k=key: self.section_requested.emit(k, inst.id))
            sec_grid.addWidget(b, i // 2, i % 2)
        lay.addLayout(sec_grid)

        self.detail_lay.addWidget(card)
        self.detail_lay.addStretch(1)

    @staticmethod
    def _mono(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-family: Consolas, monospace; "
            f"font-size: 12px; background: {COLORS['bg_input']}; "
            f"border-radius: 6px; padding: 4px 10px;"
        )
        lbl.setWordWrap(True)
        return lbl

    def _select(self, inst_id: str):
        self._selected_id = inst_id
        for rid, row in self._rows.items():
            row.set_selected(rid == inst_id)
        self._render_detail()

    def _launch(self, inst_id: str):
        """Select in manager and jump to home (the launch button lives there)."""
        self.mgr.set_current(inst_id)
        self._refresh()
        self.current_changed.emit(inst_id)

    def _open_folder(self, inst: Instance):
        from PySide6.QtGui import QDesktopServices
        p = inst.mc_dir
        if os.path.isdir(p):
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    # ------------------------------------------------------------------ util
    def _empty_state(self) -> QWidget:
        """Friendly first-run state: hint + one big 'create instance' button."""
        box = RoundedCard(radius=12)
        box.setMinimumHeight(220)
        l = QVBoxLayout(box)
        l.setContentsMargins(40, 36, 40, 36)
        l.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icon("instances").pixmap(40, 40))
        icon_lbl.setAlignment(Qt.AlignCenter)
        l.addWidget(icon_lbl)

        title = QLabel(t("instances.empty_title"))
        title.setProperty("cls", "big")
        title.setAlignment(Qt.AlignCenter)
        l.addWidget(title)

        hint = QLabel(t("instances.empty"))
        hint.setProperty("cls", "sub")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        l.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        create_btn = QPushButton(t("instances.new"))
        create_btn.setProperty("cls", "accent")
        create_btn.setMinimumHeight(40)
        create_btn.setIcon(icon("add"))
        create_btn.setIconSize(QSize(16, 16))
        create_btn.clicked.connect(self._new)
        btn_row.addWidget(create_btn)
        btn_row.addStretch(1)
        l.addLayout(btn_row)
        return box

    # ------------------------------------------------------------------ ops
    def _new(self):
        dlg = NewInstanceDialog(self)
        if dlg.exec() == QDialog.Accepted:
            name, version, loader, java_path, ldver = dlg.result_data()
            inst = self.mgr.add(name, version, loader, loader_version=ldver,
                                java_path=java_path)
            self._selected_id = inst.id
            self._refresh()

    def _open_scan(self):
        """Open the scan dialog to import existing MC folders from elsewhere."""
        from .scan_dialog import ScanDialog
        ScanDialog(self).exec()
        # refresh in case the user took over / copied instances
        self._refresh()

    def _import_mrpack(self):
        """Pick a .mrpack file, preview its metadata, install into a new instance."""
        from .win_rounded import pick_files
        import minecraft_launcher_lib

        path = pick_files(self, t("mrpack.file_pick"), "", t("mrpack.filter"))
        if not path or not path.lower().endswith(".mrpack"):
            return
        try:
            raw = minecraft_launcher_lib.mrpack.get_mrpack_information(path)
            launch_version = minecraft_launcher_lib.mrpack.get_mrpack_launch_version(path)
        except Exception:
            confirm(self, t("mrpack.title"), t("mrpack.bad_file"))
            return
        info = _parse_mrpack_info(raw)
        info["launch_version"] = launch_version
        dlg = _MrpackDialog(path, info, self)
        dlg.exec()
        self._refresh()
        cur = self.mgr.current_id
        if cur:
            self.current_changed.emit(cur)

    def _analyze_crash(self, inst):
        from .crash_dialog import CrashAnalyzerDialog
        CrashAnalyzerDialog(inst=inst, parent=self).exec()
        # 修复可能改了 mods/ 目录 → 刷新
        try:
            self.current_changed.emit(inst.id)
        except Exception:  # noqa: BLE001
            pass

    def _set_current(self, inst_id: str):
        self.mgr.set_current(inst_id)
        self._refresh()
        self.current_changed.emit(inst_id)

    def _remove(self, inst_id: str):
        inst = self.mgr.get(inst_id)
        if inst is None:
            return
        if not confirm(
            self,
            t("instances.delete_title"),
            t("instances.delete_confirm", name=inst.name),
            detail=t("instances.delete_path", path=inst.mc_dir)
                   + "\n\n"
                   + t("instances.delete_warn"),
        ):
            return
        self.mgr.remove(inst_id)
        if self._selected_id == inst_id:
            self._selected_id = None
        self._refresh()
        cur = self.mgr.current_id
        if cur:
            self.current_changed.emit(cur)

    def retranslate_ui(self):
        self.title_lbl.setText(t("instances.title"))
        self.new_btn.setText(t("instances.new"))
        self.list_lbl.setText(t("instances.list_title"))
        self._refresh()  # refreshes rows/details (which use t() dynamically)


# ---------------------------------------------------------------- Mods
class ModCard(RoundedCard):
    toggled = Signal(str, bool)  # path, enabled
    removed = Signal(str)

    def __init__(self, path: str, enabled: bool, parent=None):
        super().__init__(radius=10, parent=parent)
        self.path = path
        self.enabled = enabled
        self.setMinimumHeight(56)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(12)

        ic = QLabel()
        ic.setPixmap(icon("mods").pixmap(16, 16))
        lay.addWidget(ic)

        name = QLabel(os.path.basename(path))
        name.setProperty("cls", "sub" if not enabled else "title")
        lay.addWidget(name, 1)

        tog = QPushButton(t("mods.enable") if not enabled else t("mods.disable"))
        tog.setMinimumHeight(30)
        tog.clicked.connect(lambda: self.toggled.emit(path, not self.enabled))
        lay.addWidget(tog)

        del_btn = QPushButton(t("mods.delete"))
        del_btn.setProperty("cls", "danger")
        del_btn.setMinimumHeight(30)
        del_btn.clicked.connect(lambda: self.removed.emit(path))
        lay.addWidget(del_btn)


class ModsPage(QWidget):
    """Per-instance mod manager: pick an instance, toggle .jar files."""

    def __init__(self, list_instances, get_current_instance, parent=None):
        super().__init__(parent)
        self.list_instances = list_instances
        self.get_current = get_current_instance
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        head = QHBoxLayout()
        self.title_lbl = QLabel(t("mods.title"))
        self.title_lbl.setProperty("cls", "big")
        head.addWidget(self.title_lbl)
        head.addSpacing(16)

        self.target_lbl = QLabel(t("mods.target_label"))
        self.target_lbl.setProperty("cls", "sub")
        head.addWidget(self.target_lbl)
        self.inst_combo = QComboBox()
        self.inst_combo.setMinimumHeight(34)
        self.inst_combo.setMinimumWidth(240)
        self.inst_combo.currentIndexChanged.connect(self._on_target_changed)
        head.addWidget(self.inst_combo)
        head.addStretch(1)
        self.add_btn = QPushButton(t("mods.add"))
        self.add_btn.setProperty("cls", "accent")
        self.add_btn.setMinimumHeight(38)
        self.add_btn.setIcon(icon("add"))
        self.add_btn.setIconSize(QSize(16, 16))
        self.add_btn.clicked.connect(self._add)
        head.addWidget(self.add_btn)
        root.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._vbox = QVBoxLayout(self._content)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(12)
        self.scroll.setWidget(self._content)
        root.addWidget(self.scroll, stretch=1)

        QTimer.singleShot(0, self.refresh)

    def _target(self) -> Instance | None:
        if not hasattr(self, "inst_combo"):
            return None
        inst_id = self.inst_combo.currentData() or None
        if not inst_id:
            return None
        for i in self.list_instances():
            if i.id == inst_id:
                return i
        return None

    def _on_target_changed(self, _index: int):
        self._render_mods()

    def refresh(self):
        if not hasattr(self, "inst_combo"):
            return
        keep = self.inst_combo.currentData()
        instances = self.list_instances()
        self.inst_combo.blockSignals(True)
        self.inst_combo.clear()
        self.inst_combo.addItem(t("mods.no_instance"), "")
        for i in instances:
            self.inst_combo.addItem(i.name, i.id)
        cur = self.get_current()
        target = cur.id if cur else None
        if target is None and instances:
            target = instances[0].id
        idx = self.inst_combo.findData(target)
        if idx >= 0:
            self.inst_combo.setCurrentIndex(idx)
        self.inst_combo.blockSignals(False)
        self._render_mods()

    def _render_mods(self):
        # Guard against re-entrancy: combo spam / rapid toggles can fire
        # _render_mods twice before the first finishes; a stale render would
        # rebuild over a fresh one. Skip if we're already rendering.
        if getattr(self, "_rendering", False):
            return
        self._rendering = True
        try:
            self._render_mods_inner()
        finally:
            self._rendering = False

    def _render_mods_inner(self):
        # Synchronously destroy old cards: deleteLater() leaves them alive
        # until the event loop turns, so a rapid second call (instance combo
        # spam, refresh during animation) would addWidget over still-alive
        # C++ objects → layout corruption / crash.
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                try:
                    from shiboken6 import delete as _shib_delete
                    _shib_delete(w)
                except Exception:
                    w.deleteLater()
        inst = self._target()
        if inst is None:
            empty = QLabel(t("mods.select_instance"))
            empty.setProperty("cls", "sub")
            empty.setAlignment(Qt.AlignCenter)
            self._vbox.addWidget(empty)
            return
        mods_dir = inst.mods_dir
        os.makedirs(mods_dir, exist_ok=True)
        jars = sorted(os.listdir(mods_dir))
        if not jars:
            empty = QLabel(t("mods.empty"))
            empty.setProperty("cls", "sub")
            empty.setAlignment(Qt.AlignCenter)
            self._vbox.addWidget(empty)
            return
        for f in jars:
            path = os.path.join(mods_dir, f)
            enabled = not f.endswith(".disabled")
            card = ModCard(path, enabled)
            card.toggled.connect(self._toggle)
            card.removed.connect(self._remove)
            self._vbox.addWidget(card)

    def _toggle(self, path: str, enabled: bool):
        try:
            new_path = path
            if path.endswith(".disabled"):
                new_path = path[: -len(".disabled")]
            elif path.endswith(".jar"):
                new_path = path + ".disabled"
            shutil.move(path, new_path)
            self._render_mods()
        except OSError as e:
            warn(self, t("mods.fail_title"), str(e))

    def _remove(self, path: str):
        try:
            os.remove(path)
            self._render_mods()
        except OSError as e:
            warn(self, t("mods.fail_title"), str(e))

    def _add(self):
        inst = self._target()
        if inst is None:
            info(self, t("common.hint"), t("mods.add_hint"))
            return
        files = pick_files(self, t("mods.add_title"), "", t("mods.add_filter"), multi=True)
        if not files:
            return
        copied = 0
        for src in files:
            try:
                shutil.copy2(src, os.path.join(inst.mods_dir, os.path.basename(src)))
                copied += 1
            except OSError as e:
                warn(self, t("mods.copy_fail"), str(e))
        if copied:
            from .achievements import achievements
            achievements().unlock("first_mod")
        self._render_mods()

    def retranslate_ui(self):
        self.title_lbl.setText(t("mods.title"))
        self.target_lbl.setText(t("mods.target_label"))
        self.refresh()


# ---------------------------------------------------------------- mrpack import
def _parse_mrpack_info(raw: dict) -> dict:
    name = raw.get("name") or t("new_instance.unnamed")
    deps = raw.get("dependencies") or []
    mc_version = ""
    loader = "vanilla"
    for d in deps:
        did = (d.get("id") or "").lower()
        if did.startswith("minecraft"):
            mc_version = did.split(":")[-1] if ":" in did else did
        elif did in ("fabric-loader", "quilt-loader"):
            loader = "fabric" if did == "fabric-loader" else "quilt"
        elif did == "forge":
            loader = "forge"
        elif did == "neoforge":
            loader = "neoforge"
    mods = raw.get("files") or []
    return {
        "name": name,
        "mc_version": mc_version,
        "loader": loader,
        "mods": len(mods),
    }


class _MrpackDialog(QDialog):
    """Show modpack metadata, then install into a fresh instance on confirm."""

    def __init__(self, path: str, info: dict, parent=None):
        super().__init__(parent)
        self.path = path
        self.info = info
        self.mgr = manager()
        self._inst = None
        self.setWindowTitle(t("mrpack.title"))
        self.setMinimumWidth(480)
        self.setMinimumHeight(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self, title=t("mrpack.title"), height=38)
        root.addWidget(self.titlebar)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        grid = QFormLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addRow(QLabel(t("mrpack.name")), QLabel(info.get("name") or "?"))
        grid.addRow(QLabel(t("mrpack.version")),
                    QLabel(info.get("mc_version") or "?"))
        grid.addRow(QLabel(t("mrpack.loader")),
                    QLabel(loader_name(info.get("loader") or "vanilla")))
        grid.addRow(QLabel(t("mrpack.mods")),
                    QLabel(str(info.get("mods") or 0)))
        lay.addLayout(grid)

        self.hint = QLabel(t("mrpack.choose_hint"))
        self.hint.setProperty("cls", "sub")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setProperty("cls", "sub")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.cancel_btn = QPushButton(t("new_instance.cancel"))
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton(t("common.ok"))
        self.ok_btn.setProperty("cls", "accent")
        self.ok_btn.setMinimumHeight(38)
        self.ok_btn.clicked.connect(self._start)
        foot.addWidget(self.cancel_btn)
        foot.addWidget(self.ok_btn)
        lay.addLayout(foot)
        root.addWidget(body)

        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

    def _start(self):
        """Install the pack into a fresh instance (async)."""
        self.ok_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setText(t("mrpack.installing", name=self.info.get("name") or ""))
        name = self.info.get("name") or t("new_instance.unnamed")
        inst = self.mgr.add(
            name=name,
            game_version=self.info.get("mc_version") or "1.21.4",
            loader=self.info.get("loader") or "vanilla")
        inst.version_id = self.info.get("launch_version") or ""
        self.mgr._save()
        self._inst = inst
        from .core import install
        self._worker = Worker(
            install.install_mrpack, self.path, inst.mc_dir,
            mirror="bmclapi")
        self._worker.finished.connect(self._done)
        self._worker.error.connect(self._err)
        self._worker.start()

    def _done(self, _result):
        self.bar.setVisible(False)
        self.status.setText(t("mrpack.done"))
        self.ok_btn.setEnabled(False)
        self.cancel_btn.setText(t("common.close"))
        self.cancel_btn.setEnabled(True)
        # keep dialog open so the user sees the confirmation, then close
        from PySide6.QtCore import QTimer as _T
        _T.singleShot(1500, self.accept)

    def _err(self, e: str):
        self.bar.setVisible(False)
        self.status.setText(t("mrpack.error", e=e))
        self.ok_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
