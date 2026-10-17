"""Instance management pages: instance list/details + mods page.

Contains:
- InstanceCard      compact instance row used in the old list layout
- _InstRow          compact row for the new left-side instance list
- _LoaderCard       loader picker card in NewInstanceDialog
- NewInstanceDialog create-instance wizard (version + loader + java)
- InstancesPage     split view: list | details
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
    QStackedWidget, QButtonGroup, QSplitter, QGraphicsOpacityEffect, QMenu,
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QTransform

from .theme import COLORS, RoundedCard, with_alpha
from .effects import LightTrailCard, fade_in_widget  # round-50 卡片混合：实例详情卡流光；round-100 列表淡入
from . import ui_kit
from .icons import icon
from .frameless import FramelessHelper, TitleBar
from .win_rounded import enable_win11_round_corners, confirm, pick_files, info, warn, toast
from .i18n import t, loader_name
from .instances import manager, Instance, LOADERS, detect_format, launcher_label
from .net_api import fetch_versions
from .settings_dialog import load_config
from .worker import Worker, ProgressWorker
from .async_image import make_version_pixmap


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
    """Small rounded pill (loader badges on cards).

    round-100：alpha 必须在**前**（#AARRGGBB）。旧写法 `{color}1F` 是
    #RRGGBBAA，Qt 按 #AARRGGBB 解析成完全无关的颜色（黄→怪绿）。
    """
    return (
        f"color: {color}; background: {with_alpha(color, 0x1F)}; border-radius: 9px; "
        f"padding: 2px 10px; font-size: 11px; font-weight: 600;"
    )


def _loader_vivid() -> bool:
    """是否启用加载器品牌彩章（默认关；主题包声明 ``loader_vivid`` 才开）。

    与 store_detail 同一开关：10+ 个品牌色同屏会花，默认走中性 badge 类。
    """
    try:
        from .theme import get_active_theme_pack_id, find_theme_pack
        pid = get_active_theme_pack_id()
        if not pid:
            return False
        pack = find_theme_pack(pid) or {}
        return bool(pack.get("loader_vivid"))
    except Exception:
        return False


def _loader_badge(text: str, loader_id: str) -> "QLabel":
    """加载器徽章：默认中性 ``badge`` 类；主题包 loader_vivid 时走品牌色。"""
    from PySide6.QtWidgets import QLabel
    b = QLabel(text)
    if _loader_vivid():
        b.setStyleSheet(
            _badge_style(LOADER_BADGE.get(loader_id, LOADER_BADGE["vanilla"])))
    else:
        b.setProperty("cls", "badge")
    return b


# round-82 启动格式徽章配色（与来源 launcher 徽章区分，见 detect_format）。
FORMAT_BADGE = {
    "auto":      "#8B5CF6",   # 自适应紫
    "vanilla":   "#22C55E",   # 原版绿
    "iso":       "#F59E0B",   # 隔离橙
    "multimc":   "#3B82F6",   # 整合蓝
    "curseforge": "#EC4899",  # CurseForge 粉
    "modrinth":  "#14B8A6",   # Modrinth 青
    "custom":    "#6B7280",   # 自定义灰
}

_fmt_keys = {  # format 值 → i18n key（label/tooltip 共用前缀）
    "auto": "instances.fmt_auto",
    "vanilla": "instances.fmt_vanilla",
    "iso": "instances.fmt_iso",
    "multimc": "instances.fmt_multimc",
    "curseforge": "instances.fmt_curseforge",
    "modrinth": "instances.fmt_modrinth",
    "custom": "instances.fmt_custom",
}


def _fmt_badge(inst) -> "QLabel":
    """构造格式徽章：自适应时显示实时探测结果，tooltip 说明"格式=磁盘布局"。"""
    from PySide6.QtWidgets import QLabel
    fmt = detect_format(inst)
    key = _fmt_keys.get(fmt, "instances.fmt_auto")
    b = QLabel(t(key))
    if _loader_vivid():
        b.setStyleSheet(_badge_style(FORMAT_BADGE.get(fmt, FORMAT_BADGE["auto"])))
    else:
        b.setProperty("cls", "badge")
    b.setToolTip(t("instances.fmt_tooltip"))
    b.setCursor(Qt.PointingHandCursor)
    return b


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
    if loader == "liteloader":
        # round-104：补全 LiteLoader 分支——之前无此分支导致版本下拉恒空，
        # 装 LiteLoader 时无法选构建，只能走默认。meta 用 _version（maven 版本串）
        # 供 install_liteloader 的 build_version 使用。
        from .net_api import fetch_liteloader_builds
        try:
            return [
                {"title": b["title"], "meta": b.get("_version", "")}
                for b in fetch_liteloader_builds(mc_version)
            ]
        except Exception:
            return []
    if loader == "cleanroom":
        from .net_api import fetch_cleanroom_builds
        try:
            # round-34 修复：字段是 _installer_url（之前误读 _build 恒空 →
            # loader_version 空 → install.py 缺 installer URL 直接抛异常）
            return [
                {"title": b["title"], "meta": b.get("_installer_url", "")}
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
    # quilt via minecraft-launcher-lib（round-68 补齐分支）
    try:
        from minecraft_launcher_lib.mod_loader import Quilt
        if loader == "quilt":
            return [
                {"title": v, "meta": v}
                for v in Quilt().get_loader_versions(mc_version, True)
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


class InstanceCard(LightTrailCard):
    set_current = Signal(str)
    removed = Signal(str)
    analyze = Signal(object)  # CrashAnalyzerDialog

    def __init__(self, inst: Instance, is_current: bool, parent=None):
        # round-50 实例列表流光：低强度慢速，视觉整洁不抢主内容
        super().__init__(radius=12, parent=parent, strength=0.45, speed=0.6)
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
        meta.addWidget(_loader_badge(loader_name(inst.loader), inst.loader))
        meta.addWidget(_fmt_badge(inst))
        meta.addStretch(1)
        info.addLayout(meta)
        lay.addLayout(info, stretch=1)

        # ── right: current tag / actions ──
        if is_current:
            tag = QWidget()
            tag.setAttribute(Qt.WA_StyledBackground, True)
            tag.setStyleSheet(
                f"background: {with_alpha(COLORS['success'], 0x1A)};"
                f" border-radius: 10px;")
            tl = QHBoxLayout(tag)
            tl.setContentsMargins(10, 4, 12, 4)
            tl.setSpacing(6)
            from .ui_kit import state_pix
            ti = QLabel()
            ti.setPixmap(state_pix("done", COLORS["success"], 14))
            ti.setFixedSize(15, 15)
            tt = QLabel(t("instances.current"))
            tt.setStyleSheet(f"color: {COLORS['success']}; font-weight: 600;")
            tl.addWidget(ti)
            tl.addWidget(tt)
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


class _InstRow(LightTrailCard):
    """Compact row for the left instance list (common style)."""

    clicked = Signal(str)

    def __init__(self, inst: Instance, is_current: bool, parent=None,
                 on_menu=None):
        # round-50 左侧实例列表流光：低强度慢速，视觉整洁
        super().__init__(radius=10, parent=parent, strength=0.4, speed=0.55)
        self.inst = inst
        self._on_menu = on_menu  # round-42 右键菜单回调
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
        # round-100：字色交给 title 类（内联色不随主题切换刷新）
        nm.setStyleSheet("font-size: 13px;")
        nm.setWordWrap(False)
        col.addWidget(nm)
        sub = QLabel(f"{inst.game_version or '?'}  ·  {loader_name(inst.loader)}")
        sub.setProperty("cls", "sub")
        sub.setStyleSheet("font-size: 11px;")
        col.addWidget(sub)
        lay.addLayout(col, stretch=1)

        self._cur_tag = QLabel()
        from .ui_kit import state_pix
        self._cur_tag.setPixmap(state_pix("done", COLORS["success"], 14))
        self._cur_tag.setFixedSize(16, 16)
        self._cur_tag.setVisible(is_current)
        lay.addWidget(self._cur_tag)

        # round-107 T8：任务徽标（下载中 / 就绪），默认隐藏，由页面按
        # _task_states 驱动（下载完成后显示「就绪」）。
        self._task_lbl = QLabel("")
        self._task_lbl.setVisible(False)
        lay.addWidget(self._task_lbl)

    def set_task_state(self, state):
        """round-107 T8 行内任务徽标：``(kind, pct)``，None/空则隐藏。"""
        if not state:
            self._task_lbl.setVisible(False)
            return
        kind, pct = state
        if kind == "downloading":
            self._task_lbl.setText(t("instances.task_downloading", pct=pct))
            self._task_lbl.setStyleSheet(
                f"font-size: 11px; color: {COLORS['accent']};")
        else:  # ready
            self._task_lbl.setText(t("instances.task_ready"))
            self._task_lbl.setStyleSheet(
                f"font-size: 11px; color: {COLORS['success']};")
        self._task_lbl.setVisible(True)

    def set_selected(self, on: bool):
        self._selected = on
        self.set_border(COLORS["accent"] if on else COLORS["border"],
                        2 if on else 1)
        self.update()

    def refresh_state(self, is_current: bool):
        """round-38 性能：更新 ✓ 标签而不重建行（快切卡顿优化）。"""
        self._cur_tag.setVisible(is_current)

    def mousePressEvent(self, e):
        self.clicked.emit(self.inst.id)
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        # round-42 右键菜单（对齐主流鼠标流）：on_menu(inst, global_pos)
        if self._on_menu is not None:
            self._on_menu(self.inst, e.globalPos())
        e.accept()


class _LoaderCard(QFrame):
    """Clickable loader picker card — card-style selection (UI 大改 Step B).

    round-88：左侧显示加载器官方风格图标（assets/icons/loader_*.svg，
    缺失时回退彩色圆点），中间标题+描述，右侧选中对勾。
    """

    def __init__(self, dlg: "NewInstanceDialog", loader_id: str, parent=None):
        super().__init__(parent)
        self.dlg = dlg
        self.loader_id = loader_id
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(66)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        from .icons import pixmap as _pix
        ic = _pix(f"loader_{loader_id}", 40)
        self._logo = QLabel()
        if not ic.isNull():
            self._logo.setPixmap(ic)
        else:
            # 图标缺失时回退中性色块（round-100：不再用品牌色，绝不留空框）
            self._logo.setStyleSheet(
                f"background: {COLORS['bg_hover']}; border-radius:7px;")
        self._logo.setFixedSize(40, 40)
        self._logo.setScaledContents(True)
        lay.addWidget(self._logo, 0, Qt.AlignVCenter)

        mid = QVBoxLayout()
        mid.setSpacing(3)
        name = QLabel(loader_name(loader_id))
        name.setProperty("cls", "title")
        mid.addWidget(name)
        desc = QLabel(t(_LOADER_DESC.get(loader_id, "new_instance.ld_vanilla")))
        desc.setProperty("cls", "sub")
        desc.setWordWrap(True)
        mid.addWidget(desc)
        lay.addLayout(mid, 1)

        # round-91 自绘对勾（Windows 下文本 ✓ 可能被 Segoe UI Emoji 渲染成彩色）
        from .ui_kit import state_pix
        self._check = QLabel()
        self._check.setPixmap(state_pix("done", COLORS["accent"], 15))
        self._check.setFixedSize(16, 16)
        self._check.setVisible(False)
        lay.addWidget(self._check, 0, Qt.AlignTop)

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
    """Two-step create-instance wizard:

    Step 1 — pick a game version (card list like VersionsPage).
    Step 2 — pick a compatible mod loader, loader version, Java and name.

    When ``embedded=True`` the widget is placed directly inside another page
    (no separate window, no title bar) and reports its outcome through the
    ``created`` / ``cancelled`` signals.  When ``embedded=False`` it behaves
    like a normal modal dialog.

    This mirrors mainstream launchers and prevents players from
    choosing loaders that do not exist for the selected Minecraft version.
    """

    created = Signal(str, str, str, str, str)   # name, version, loader, java_path, loader_version
    cancelled = Signal()

    _GROUP_ORDER = ["release", "snapshot", "april", "legacy"]
    _GROUP_OF_TYPE = {"release": "release", "snapshot": "snapshot",
                      "old_beta": "legacy", "old_alpha": "legacy"}
    # round-38 性能：版本组懒加载，每组最多渲染这些卡（其余折叠「显示全部」）
    _MAX_GROUP_VISIBLE = 12

    def __init__(self, parent=None, preset_version: str = "", embedded: bool = False):
        super().__init__(parent)
        self._group_expanded: dict[str, bool] = {}
        # round-107：滚到底自动续加载所需状态（替代手动「显示全部」按钮）
        self._ver_collapsed: list[str] = []
        self._ver_shown: set[str] = set()
        self._embedded = embedded
        self._versions: list[dict] = []
        self._selected_version: str = preset_version or ""
        self._loader = "vanilla"
        self._java_path = ""
        self._preset_version = preset_version
        self._loader_cards: dict[str, _LoaderCard] = {}
        self._version_filter = "all"
        self._version_search = ""
        self._busy = False  # 防抖：过渡期间禁止页间切换（round-29 防快速连点闪退）

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if not embedded:
            self.setWindowTitle(t("new_instance.title"))
            self.setMinimumWidth(640)
            self.setMinimumHeight(520)
            self.titlebar = TitleBar(self, title=t("new_instance.title"), height=38)
            root.addWidget(self.titlebar)
        else:
            self.titlebar = None
            # 嵌入式模式必须去掉 QDialog 的 Window/Dialog 窗口标志，否则它被
            # addWidget 进 QStackedWidget 后仍会被 Qt 渲染成「浮动独立窗口」叠加
            # 在主页之上；关闭时 deleteLater 延迟销毁，浮动窗残留 = 持续双页。
            # 设为 Qt.Widget 使其成为被 stack 正常管理的普通子控件。
            self.setWindowFlags(Qt.Widget)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        self.stack = QStackedWidget()
        self._page_version = self._build_version_page()
        self._page_loader = self._build_loader_page()
        self.stack.addWidget(self._page_version)
        self.stack.addWidget(self._page_loader)
        root.addWidget(self.stack, stretch=1)

        if not embedded:
            self._frameless = FramelessHelper(self)
            self._frameless.set_titlebar(self.titlebar)
            from .win_rounded import enable_win11_round_corners
            enable_win11_round_corners(self)
        else:
            self._frameless = None

        # round-46 用户反馈"新建实例看不到任何东西"：先显示 loading 占位，
        # fetch 完成后替换。替代方案是显示空白。
        loading = QLabel(t("versions.loading"))
        loading.setProperty("cls", "sub")
        loading.setAlignment(Qt.AlignCenter)
        loading.setMinimumHeight(80)
        self._ver_vbox.addWidget(loading)
        self._ver_loading_label = loading

        # default state
        self._select_loader("vanilla")
        if preset_version:
            self._go_to_loader_page()

        self._worker = Worker(fetch_versions)
        self._worker.finished.connect(self._on_versions)
        self._worker.error.connect(self._on_versions_error)
        self._worker.start()

        # round-104：后台预热 Legacy Fabric 支持版本缓存（不阻塞 UI），
        # 完成后刷新加载器兼容表——届时 legacyfabric 的显示即基于真实支持列表。
        try:
            from .net_api import fetch_legacy_fabric_games
            self._lf_worker = Worker(fetch_legacy_fabric_games)
            self._lf_worker.finished.connect(self._on_lf_games)
            self._lf_worker.start()
        except Exception:
            self._lf_worker = None

    def _on_lf_games(self, *_args):
        """round-104：Legacy Fabric 游戏版本缓存就绪 → 刷新加载器兼容表。"""
        from shiboken6 import isValid
        if not isValid(self):
            return
        if self._selected_version:
            self._update_compatible_loaders()

    # ------------------------------------------------------------------ page 1
    def _build_version_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        title = QLabel(t("new_instance.step_version"))
        title.setProperty("cls", "big")
        lay.addWidget(title)

        # filter chips
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        chip_row.addStretch(1)
        self._ver_filter_group = QButtonGroup(self)
        self._ver_filter_group.setExclusive(True)
        self._ver_filter_btns: dict[str, QPushButton] = {}
        for key, lbl in [
            ("all", t("versions.filter_all")),
            ("release", t("versions.filter_release")),
            ("snapshot", t("versions.filter_snapshot")),
            ("april", t("versions.filter_april")),
            ("legacy", t("versions.filter_legacy")),
        ]:
            btn = QPushButton(lbl)
            btn.setCheckable(True)
            btn.setMinimumHeight(32)
            btn.clicked.connect(lambda _checked=False, k=key: self._set_version_filter(k))
            self._ver_filter_group.addButton(btn)
            self._ver_filter_btns[key] = btn
            chip_row.addWidget(btn)
        chip_row.addStretch(1)
        lay.addLayout(chip_row)

        # search
        self._ver_search = QLineEdit()
        self._ver_search.setPlaceholderText(t("versions.filter_placeholder"))
        self._ver_search.setMinimumHeight(34)
        self._ver_search.textChanged.connect(self._on_version_search)
        lay.addWidget(self._ver_search)

        # version card list
        self._ver_scroll = QScrollArea()
        self._ver_scroll.setWidgetResizable(True)
        self._ver_scroll.setFrameShape(QFrame.NoFrame)
        self._ver_content = QWidget()
        self._ver_vbox = QVBoxLayout(self._ver_content)
        self._ver_vbox.setContentsMargins(0, 0, 0, 0)
        self._ver_vbox.setSpacing(10)
        self._ver_scroll.setWidget(self._ver_content)
        # round-107：滚到底部自动续加载（对齐主流的持续下拉），不再用手动按钮
        self._ver_scroll.verticalScrollBar().valueChanged.connect(self._on_ver_scroll)
        lay.addWidget(self._ver_scroll, stretch=1)

        # now that _ver_vbox exists, apply the default filter
        self._set_version_filter("all")

        # footer
        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton(t("new_instance.cancel"))
        cancel.setMinimumHeight(38)
        cancel.clicked.connect(self._on_cancel)
        self._next_btn = QPushButton(t("new_instance.next"))
        self._next_btn.setProperty("cls", "accent")
        self._next_btn.setMinimumHeight(38)
        self._next_btn.setEnabled(bool(self._selected_version))
        self._next_btn.clicked.connect(self._go_to_loader_page)
        foot.addWidget(cancel)
        foot.addWidget(self._next_btn)
        lay.addLayout(foot)
        return page

    def _set_version_filter(self, key: str):
        self._version_filter = key
        self._ver_shown = set()  # 换筛选 → 整列表重新淡入
        for k, btn in self._ver_filter_btns.items():
            btn.setChecked(k == key)
            self._style_filter_btn(btn, k == key)
        self._refresh_version_list()

    def _style_filter_btn(self, btn: QPushButton, active: bool):
        if active:
            # round-100：白字改 text_on_accent（浅色 accent 下自动换深字，round-44 规则）
            btn.setStyleSheet(
                f"QPushButton {{ background: {COLORS['accent']}; color: {COLORS['text_on_accent']}; "
                f"border: none; border-radius: 8px; padding: 5px 14px; font-weight: 600; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background: {COLORS['bg_panel']}; color: {COLORS['text_sub']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 5px 14px; }}"
                f"QPushButton:hover {{ background: {COLORS['bg_hover']}; color: {COLORS['text_main']}; }}"
            )

    def _on_version_search(self, text: str):
        self._version_search = text.strip().lower()
        self._ver_shown = set()  # 搜索变更 → 结果重新淡入
        self._refresh_version_list()

    def _group_of(self, v: dict) -> str:
        if v.get("april"):
            return "april"
        return self._GROUP_OF_TYPE.get(v.get("type", "release"), "legacy")

    def _refresh_version_list(self):
        # round-107：改为「滚到底部自动续加载」。此前超出 _MAX_GROUP_VISIBLE 的
        # 版本折叠成「显示全部 N 个」按钮，需玩家手动点开（用户反馈反人类）；
        # 现在首屏渲染前 _MAX_GROUP_VISIBLE 张，剩余由滚动触发展开，并给新出现
        # 的卡片做淡入动画。
        while self._ver_vbox.count():
            item = self._ver_vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        versions = [v for v in self._versions
                    if not self._version_search or self._version_search in v.get("id", "").lower()]
        groups = self._GROUP_ORDER if self._version_filter == "all" else [self._version_filter]
        expanded = getattr(self, "_group_expanded", {})
        self._ver_collapsed = []
        shown = getattr(self, "_ver_shown", None)
        if shown is None:
            shown = self._ver_shown = set()

        def add_card(v: dict) -> None:
            card = self._make_version_card(v)
            self._ver_vbox.addWidget(card)
            if v.get("id") not in shown:
                shown.add(v.get("id"))
                fade_in_widget(card)  # 新出现的卡片淡入（旧卡片不复播）

        for g in groups:
            members = [v for v in versions if self._group_of(v) == g]
            if not members:
                continue
            hdr = QLabel(t(f"versions.group.{g}"))
            hdr.setProperty("cls", "group")
            self._ver_vbox.addWidget(hdr)
            show_all = expanded.get(g, False)
            if show_all or len(members) <= self._MAX_GROUP_VISIBLE:
                visible = members
            else:
                visible = members[:self._MAX_GROUP_VISIBLE]
                self._ver_collapsed.append(g)
            for v in visible:
                add_card(v)
        self._ver_vbox.addStretch(1)

    def _on_ver_scroll(self, value: int) -> None:
        """滚到底部 → 自动展开下一组被折叠的版本（替代手动「显示全部」按钮）。"""
        if getattr(self, "_ver_suppress_scroll", False):
            return
        collapsed = getattr(self, "_ver_collapsed", [])
        if not collapsed:
            return
        vbar = self._ver_scroll.verticalScrollBar()
        if vbar.maximum() <= 0 or value < vbar.maximum() - 48:
            return
        self._group_expanded[collapsed[0]] = True
        self._ver_suppress_scroll = True
        try:
            self._refresh_version_list()
        finally:
            self._ver_suppress_scroll = False

    def _make_version_card(self, v: dict) -> QFrame:
        ver_id = v["id"]
        vtype = "april" if v.get("april") else v.get("type", "release")
        card = RoundedCard(radius=12)
        card.setMinimumHeight(72)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        tile = QLabel()
        tile.setPixmap(make_version_pixmap(ver_id, vtype, 48))
        tile.setFixedSize(48, 48)
        lay.addWidget(tile)

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(ver_id)
        name.setProperty("cls", "title")
        info.addWidget(name)
        date = QLabel(t("versions.released", date=v.get("releaseTime", "")[:10]))
        date.setProperty("cls", "sub")
        info.addWidget(date)
        lay.addLayout(info, stretch=1)

        # round-105 去重：此前被选中的版本行同时渲染绿色「✓ 当前」徽章
        # 和下方那颗「当前」按钮，同一个词出现两次。这里只保留按钮侧的状态，
        # 不再额外插一个徽章。
        btn = QPushButton(t("versions.install"))
        btn.setMinimumHeight(32)
        if ver_id == self._selected_version:
            btn.setProperty("cls", "accent")
            btn.setText(t("instances.current"))
        btn.clicked.connect(lambda _checked=False, vid=ver_id: self._select_version(vid))
        lay.addWidget(btn)
        return card

    def _select_version(self, ver_id: str):
        self._selected_version = ver_id
        self._next_btn.setEnabled(True)
        self._refresh_version_list()

    # ------------------------------------------------------------------ page 2
    def _build_loader_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        # header with back-to-version
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(t("new_instance.step_loader"))
        title.setProperty("cls", "big")
        head.addWidget(title)
        head.addStretch(1)
        self._selected_ver_lbl = QLabel()
        self._selected_ver_lbl.setProperty("cls", "sub")
        head.addWidget(self._selected_ver_lbl)
        change_ver = QPushButton(t("new_instance.browse_versions"))
        change_ver.setMinimumHeight(32)
        change_ver.clicked.connect(self._go_to_version_page)
        head.addWidget(change_ver)
        lay.addLayout(head)

        # compatible loader grid
        # round-29：移除"选择原版"卡片——玩家不选任何附加加载器即为原版，
        # 默认 _loader="vanilla"，无卡时也是原版，无需冗余选项。
        self._loader_grid = QGridLayout()
        self._loader_grid.setSpacing(10)
        cols = 3
        ui_loaders = [l for l in LOADERS if l != "vanilla"]
        # round-68 设置开关：show_quilt=False 时新建实例页不出现 Quilt 卡片
        if not load_config().get("show_quilt", True):
            ui_loaders = [l for l in ui_loaders if l != "quilt"]
        for i, loader_id in enumerate(ui_loaders):
            card = _LoaderCard(self, loader_id)
            self._loader_cards[loader_id] = card
            self._loader_grid.addWidget(card, i // cols, i % cols)
        # LabyMod is not installable in-app; keep it as a link card
        labymod_card = _LoaderCard(self, "labymod")
        self._loader_cards["labymod"] = labymod_card
        self._loader_grid.addWidget(labymod_card, len(ui_loaders) // cols, len(ui_loaders) % cols)
        lay.addLayout(self._loader_grid)

        self._no_loader_hint = QLabel(t("new_instance.no_compatible_loader"))
        self._no_loader_hint.setProperty("cls", "sub")
        self._no_loader_hint.setAlignment(Qt.AlignCenter)
        self._no_loader_hint.setVisible(False)
        lay.addWidget(self._no_loader_hint)

        # loader version
        ldver_box = QWidget()
        ldver_lay = QVBoxLayout(ldver_box)
        ldver_lay.setContentsMargins(0, 0, 0, 0)
        ldver_lay.setSpacing(6)
        ldver_title = QLabel(t("new_instance.loader_version"))
        ldver_title.setProperty("cls", "group")
        ldver_lay.addWidget(ldver_title)
        self.ldver_combo = QComboBox()
        self.ldver_combo.setMinimumHeight(36)
        self.ldver_combo.addItem(t("new_instance.ldver_latest"))
        self.ldver_combo.setToolTip(t("new_instance.ldver_hint"))
        ldver_lay.addWidget(self.ldver_combo)
        self.ldver_box = ldver_box
        lay.addWidget(ldver_box)

        # Java
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

        # name
        name_lbl = QLabel(t("new_instance.name"))
        name_lbl.setProperty("cls", "group")
        lay.addWidget(name_lbl)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("new_instance.name_placeholder"))
        self.name_edit.setMinimumHeight(36)
        self.name_edit.textChanged.connect(self._update_path)
        lay.addWidget(self.name_edit)

        # path preview
        self.path_lbl = QLabel()
        self.path_lbl.setProperty("cls", "sub")
        self.path_lbl.setWordWrap(True)
        self.path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.path_lbl)

        lay.addStretch(1)

        # footer
        foot = QHBoxLayout()
        foot.addStretch(1)
        back = QPushButton(t("new_instance.back"))
        back.setMinimumHeight(38)
        back.clicked.connect(self._go_to_version_page)
        cancel = QPushButton(t("new_instance.cancel"))
        cancel.setMinimumHeight(38)
        cancel.clicked.connect(self._on_cancel)
        ok = QPushButton(t("new_instance.create"))
        ok.setProperty("cls", "accent")
        ok.setMinimumHeight(38)
        ok.clicked.connect(self._on_create)
        foot.addWidget(back)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        lay.addLayout(foot)
        return page

    def _go_to_loader_page(self):
        if not self._selected_version:
            return
        # 防抖：round-29 用户反馈快速连续点击会闪退。
        # _busy 在过渡期间禁用所有 next/back，动画完成后重置。
        if self._busy:
            return
        self._busy = True
        try:
            self._selected_ver_lbl.setText(t("new_instance.selected_version", ver=self._selected_version))
            self._update_compatible_loaders()
            self._update_path()
            self.stack.setCurrentIndex(1)
        finally:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(200, lambda: setattr(self, '_busy', False))

    def _go_to_version_page(self):
        if getattr(self, '_busy', False):
            return
        self._busy = True
        try:
            self.stack.setCurrentIndex(0)
            self._refresh_version_list()
        finally:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(200, lambda: setattr(self, '_busy', False))

    # ---------------- loader compatibility ----------------
    def _parse_mc_version(self, ver: str) -> tuple[int, int]:
        parts = ver.split(".")
        try:
            return int(parts[0]), int(parts[1])
        except Exception:
            return 0, 0

    def _compatible_loaders(self, ver: str) -> list[str]:
        """Return loaders that make sense for the chosen MC version.

        This is a conservative allow-list. It does not guarantee the loader has
        a build for *every* patch version, but it prevents the user from seeing
        impossible choices (e.g. NeoForge on 1.12.2).
        """
        major, minor = self._parse_mc_version(ver)
        if major != 1:
            return ["vanilla"]
        loaders = ["vanilla"]
        if minor >= 14:
            loaders.append("fabric")
        if minor >= 18:
            # round-68 尊重设置开关：show_quilt=False 时 Quilt 不可选
            if load_config().get("show_quilt", True):
                loaders.append("quilt")
        if minor >= 20:
            loaders.append("neoforge")
        # Forge exists for almost every release/snapshot
        if minor >= 6:
            loaders.append("forge")
        # round-104：Legacy Fabric 支持范围——优先用 meta.legacyfabric.net 的
        # 真实游戏版本列表（后台预热缓存）；缓存未就绪时回退到启发式 ≤1.13。
        from .net_api import legacy_fabric_games_cached
        lf_games = legacy_fabric_games_cached()
        if lf_games is not None:
            if ver in set(lf_games):
                loaders.append("legacyfabric")
        elif minor <= 13:
            loaders.append("legacyfabric")
        if minor <= 12:
            loaders.extend(["liteloader", "cleanroom"])
        # OptiFine standalone install is available for many versions
        loaders.append("optifine")
        # LabyMod is always a link-out, keep it visible
        loaders.append("labymod")
        return loaders

    def _update_compatible_loaders(self):
        allowed = set(self._compatible_loaders(self._selected_version))
        visible_any = False
        cols = 3
        idx = 0
        for loader_id, card in self._loader_cards.items():
            ok = loader_id in allowed
            card.setVisible(ok)
            if ok:
                # round-88：隐藏掉不兼容的卡后，把剩余可见卡重新按 3 列
                # 连续铺排（QGridLayout 的 addWidget 会自动从旧格位移出），
                # 避免留下空洞、"选项消失后剩余的不对齐"。
                self._loader_grid.addWidget(card, idx // cols, idx % cols)
                idx += 1
                visible_any = True
        self._loader_grid.invalidate()
        self._loader_grid.activate()
        self._no_loader_hint.setVisible(not visible_any)
        # if currently selected loader became incompatible, reset to vanilla
        if self._loader not in allowed:
            self._select_loader("vanilla")
        else:
            self._select_loader(self._loader)

    def _select_loader(self, loader_id: str):
        if loader_id == "labymod":
            self._open_labymod()
            return
        self._loader = loader_id
        for lid, card in self._loader_cards.items():
            card.set_selected(lid == loader_id and card.isVisible())
        show_ldver = loader_id not in ("vanilla", "optifine", "labymod")
        self.ldver_box.setVisible(show_ldver)
        if show_ldver:
            self._load_loader_versions()
        self._update_path()

    def _open_labymod(self):
        QDesktopServices.openUrl(QUrl("https://www.labymod.net"))
        info(self, t("common.hint"), t("new_instance.labymod_visit"))

    # ---------------- loader versions ----------------
    def _load_loader_versions(self):
        mc = self._selected_version
        loader = self._loader
        self.ldver_combo.blockSignals(True)
        self.ldver_combo.clear()
        self.ldver_combo.addItem(t("new_instance.ldver_latest"))
        self.ldver_combo.blockSignals(False)
        gen = getattr(self, "_ldver_gen", 0) + 1
        self._ldver_gen = gen
        self._ldver_worker = Worker(_fetch_loader_versions, mc, loader)

        def _done(versions: list[dict], g=gen):
            if getattr(self, "_ldver_gen", 0) != g:
                return
            self._on_loader_versions(versions)

        def _err(_e, g=gen):
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
        if not self.ldver_box.isVisible():
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

    # ---------------- versions ----------------
    def closeEvent(self, e):
        """round-44 闪退修复：关闭时版本 Worker 可能还在跑（网络慢），
        它完成后 emit finished → 连到已销毁 dialog 的槽 → 崩（Internal C++
        object already deleted / heap corruption）。关闭即中断 + join。"""
        try:
            w = getattr(self, "_worker", None)
            if w is not None and w.isRunning():
                w.requestInterruption()
                w.wait(1500)
        except Exception:
            pass
        super().closeEvent(e)

    def _on_versions(self, data):
        # round-44：dialog 已销毁（用户快速关闭）时静默返回，防信号回调崩
        from shiboken6 import isValid
        if not isValid(self):
            return
        # round-48 修复：原 isinstance(data, data) 笔误（第二参必须是类型）→
        # TypeError 崩掉整个版本列表回调。Worker.finished 直接传
        # fetch_versions() 的返回值 (latest, versions)；错误走 error 信号。
        # round-57 加固：旧磁盘缓存/异常数据可能带来 list[str]，逐条过滤到
        # dict 再使用，接住 net_api 侧的 schema 校验（防 _group_of 对 str 崩）。
        data_list = data[1] if isinstance(data, tuple) and len(data) == 2 else (data or [])
        versions = [v for v in data_list if isinstance(v, dict)]
        err, versions = None, versions
        self._versions = versions or []
        # if a preset version is locked, make sure it exists in the list
        if self._preset_version and not any(v.get("id") == self._preset_version for v in self._versions):
            self._versions.insert(0, {"id": self._preset_version, "type": "release", "releaseTime": ""})
        # round-46：fetch 完成后删 loading 占位再 refresh
        try:
            if getattr(self, "_ver_loading_label", None) is not None:
                self._ver_vbox.removeWidget(self._ver_loading_label)
                self._ver_loading_label.deleteLater()
                self._ver_loading_label = None
        except Exception:
            pass
        if err and not self._versions:
            err_lbl = QLabel(t("versions.load_failed", err=str(err) if err else ""))
            err_lbl.setProperty("cls", "sub")
            err_lbl.setAlignment(Qt.AlignCenter)
            err_lbl.setMinimumHeight(80)
            err_lbl.setWordWrap(True)
            self._ver_vbox.addWidget(err_lbl)
            self._ver_vbox.addStretch(1)
            return
        self._refresh_version_list()

    def _on_versions_error(self, exc):
        """round-46：Worker.fetch_versions 失败回调（err tuple 中的 err）。

        对应 Worker.error 信号（Worker 会把异常重打包成 (err, None) 传入
        finished；此回调保留作 Worker 直接 emit error 时的兜底）。
        """
        from shiboken6 import isValid
        if not isValid(self):
            return
        try:
            if getattr(self, "_ver_loading_label", None) is not None:
                self._ver_vbox.removeWidget(self._ver_loading_label)
                self._ver_loading_label.deleteLater()
                self._ver_loading_label = None
        except Exception:
            pass
        err_lbl = QLabel(t("versions.load_failed", err=str(exc) if exc else ""))
        err_lbl.setProperty("cls", "sub")
        err_lbl.setAlignment(Qt.AlignCenter)
        err_lbl.setMinimumHeight(80)
        err_lbl.setWordWrap(True)
        self._ver_vbox.addWidget(err_lbl)
        self._ver_vbox.addStretch(1)

    # ---------------- naming / path ----------------
    def _auto_name(self) -> str:
        ver = self._selected_version.strip()
        if not ver:
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
        # round-40 P3 修复：过滤方向反了——应保留安全字符，去掉 Windows 非法字符
        # （之前 c not in "-_. " 删掉连字符/点/空格却保留 \\/:*?\"<>| ）
        safe_name = "".join(
            c for c in (name or auto)
            if c.isalnum() or c in "-_. ()"
        ) or "instance"
        preview = os.path.join(get_data_dir(), "instances", f"{safe_name}/")
        self.path_lbl.setText(t("new_instance.save_to", path=preview))

    def _on_cancel(self):
        if self._embedded:
            self.cancelled.emit()
        else:
            self.reject()

    def _on_create(self):
        if self._embedded:
            self.created.emit(*self.result_data())
        else:
            self.accept()

    def result_data(self) -> tuple[str, str, str, str, str]:
        name = self.name_edit.text().strip()
        if not name:
            name = self._auto_name()
        return (name, self._selected_version, self._loader, self._java_path,
                self.selected_loader_version())


class InstancesPage(QWidget):
    """Instance manager — split view: compact list on the left, a
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
    scan_done = Signal()  # emitted when the embedded scanner closes
    # round-107 T8：页面内新建实例后上报 id，由 MainWindow 统一发起后台下载。
    instance_created = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mgr = manager()
        self._rows: dict[str, _InstRow] = {}
        # round-107 T8 实例行任务状态（仅内存，重启即清）：
        #   id -> ("downloading", pct) | ("ready", 100)
        self._task_states: dict[str, tuple[str, int]] = {}
        self._selected_id: str | None = None
        self._scan_panel = None
        self._new_panel = None
        self._closing_new = False
        self._closing_scan = False
        self._empty_btn = None
        self._list_panel_visible = True
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        # ── header ──
        # round-45c 重做：header 按钮不再走全局 QSS（$bg_frost 替换 + 布局挤压
        # 双重干扰导致文字模糊/重叠），改为 inline 样式 + setFixedWidth 完全
        # 自控：字号 13px、明确边框、白底/紫底各一、图标+文字独立布局。
        self.new_btn = self._mk_header_btn(
            t("instances.new"), "add", self._new, w=110, accent=False)
        self.scan_btn = self._mk_header_btn(
            t("instances.scan_import"), "search", self._open_scan, w=132)
        self.mrpack_btn = self._mk_header_btn(
            t("instances.import_pack"), "download", self._import_mrpack, w=120)
        head_actions = QWidget()
        head_actions.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(head_actions)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        hl.addWidget(self.new_btn)
        hl.addWidget(self.scan_btn)
        hl.addWidget(self.mrpack_btn)
        # round-107 收起键重做：原按钮随列表一起折叠 → 位置来回跳动（用户反馈
        # 「位置会偏移、很反人类」）。改为一颗**常驻页头**的图标按钮：无论列表
        # 展开/收起，它始终停在同一个位置，状态靠图标方向 + tooltip 表达。
        self.panel_btn = QPushButton("")
        self.panel_btn.setFixedSize(34, 34)
        self.panel_btn.setCursor(Qt.PointingHandCursor)
        self.panel_btn.setToolTip(t("instances.fold_list"))
        self.panel_btn.setIconSize(QSize(15, 15))
        self.panel_btn.setStyleSheet(
            f"QPushButton {{ background: {COLORS['bg_btn']}; color: {COLORS['text_main']};"
            f" border: 1px solid {COLORS['border']}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {COLORS['bg_hover']}; }}"
        )
        self.panel_btn.clicked.connect(self._toggle_panel)
        hl.addWidget(self.panel_btn)
        hl.addStretch(1)
        self._header = ui_kit.page_header(
            t("instances.title"), action=head_actions, icon_key="instances")
        self.title_lbl = self._header.title_lbl
        root.addWidget(self._header)

        # ── body: stacked view switcher (prevents the "double page" bug) ──
        # We use a QStackedWidget for the body so only one view is ever visible:
        #   0 = empty state   (no instances yet)
        #   1 = split view    (list + details)
        #   2 = new instance wizard
        #   3 = scan panel
        # This replaces the old manual show/hide juggling that left stale
        # widgets stacked on top of each other.
        self._body_stack = QStackedWidget()

        # page 0: empty state
        self._empty_page = self._empty_state()
        self._body_stack.addWidget(self._empty_page)

        # page 1: split view (left list | right details) with resizable splitter
        self._split_view = QWidget()
        body = QVBoxLayout(self._split_view)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(3)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background: transparent; }"
            # round-100：硬编码紫 → 主题 accent 派生（换主题色时不再残留紫色）
            f"QSplitter::handle:hover {{ background: {with_alpha(COLORS['accent'], 0x3D)}; }}"
        )

        self._left_panel = QWidget()
        self._left_panel.setMinimumWidth(220)
        self._left_panel.setMaximumWidth(420)
        left_lay = QVBoxLayout(self._left_panel)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(8)

        # 列表标题行（round-107：原「折叠按钮」上移到页头常驻 panel_btn，标题行只留标题）
        self._list_head = QHBoxLayout()
        self.list_lbl = QLabel(t("instances.list_title"))
        self.list_lbl.setProperty("cls", "group")
        self._list_head.addWidget(self.list_lbl)
        self._list_head.addStretch(1)
        left_lay.addLayout(self._list_head)

        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_content = QWidget()
        self._list_vbox = QVBoxLayout(self._list_content)
        self._list_vbox.setContentsMargins(0, 0, 0, 0)
        self._list_vbox.setSpacing(6)
        self.list_scroll.setWidget(self._list_content)
        left_lay.addWidget(self.list_scroll, stretch=1)
        self._splitter.addWidget(self._left_panel)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.detail_content = QWidget()
        self.detail_lay = QVBoxLayout(self.detail_content)
        self.detail_lay.setContentsMargins(0, 0, 0, 0)
        self.detail_lay.setSpacing(16)
        self.detail_scroll.setWidget(self.detail_content)
        self._splitter.addWidget(self.detail_scroll)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([280, 720])

        # round-107：原「左侧展开条 + 折叠按钮」双按钮方案整体移除——收起按钮
        # 已常驻页头（panel_btn），这里只放分割器，位置永不偏移。
        body.addWidget(self._splitter, stretch=1)
        self._body_stack.addWidget(self._split_view)
        self._sync_panel_btn()  # 初始同步页头收起按钮图标方向

        root.addWidget(self._body_stack, stretch=1)
        QTimer.singleShot(0, self._refresh)

    # ------------------------------------------------------------------ view
    def refresh(self):
        """Public entry point: rebuild the instance list. Called by the main
        window after the scan dialog closes so imported instances appear."""
        self._refresh()

    def set_instance_task(self, inst_id: str, state: str, pct: int = 0) -> None:
        """round-107 T8：由 MainWindow 驱动某实例的「下载中 / 就绪」徽标。

        ``state`` 为空串则清除。仅内存态，不写实例字段（保持 Instance 幂等）。
        """
        if state:
            self._task_states[inst_id] = (state, int(pct or 0))
        else:
            self._task_states.pop(inst_id, None)
        row = self._rows.get(inst_id)
        if row is not None:
            row.set_task_state(self._task_states.get(inst_id))

    def _refresh(self, *, switch: bool = True):
        """Rebuild the left list + right details from the manager.

        ``switch=False`` leaves the body stack on its current page — useful
        when the user is interacting with an embedded panel and we only need
        to refresh the underlying list state before the panel closes.

        round-38 性能：实例行改**增量更新**——只增删变化的行，未变行调用
        refresh_state() 而不重建（之前每次全量销毁+重建所有行，快切卡顿）。
        """
        # 面板（新建向导 / 扫描面板）打开时，绝不切走 body stack 当前页，
        # 否则延迟刷新会把面板直接隐藏掉，表现为「面板一开就消失 / 双页」。
        if switch and (self._new_panel is not None or self._scan_panel is not None):
            switch = False

        cur = self.mgr.current_id
        # round-42 分组：同组连续显示（未分组排最后），视觉上形成分组
        insts = sorted(self.mgr.list(),
                       key=lambda i: ((i.group or "~").lower(), i.name.lower()))
        if not insts:
            # 全部清空（含删除所有行）
            for rid in list(self._rows.keys()):
                row = self._rows.pop(rid)
                row.setParent(None)
                try:
                    from shiboken6 import delete as _shibdelete
                    _shibdelete(row)
                except Exception:
                    row.deleteLater()
            if switch and self._body_stack is not None:
                self._body_stack.setCurrentIndex(0)  # empty state
            return

        # 移除不再存在的行
        new_ids = {inst.id for inst in insts}
        for rid in list(self._rows.keys()):
            if rid not in new_ids:
                row = self._rows.pop(rid)
                row.setParent(None)
                try:
                    from shiboken6 import delete as _shibdelete
                    _shibdelete(row)
                except Exception:
                    row.deleteLater()

        # 去掉末尾旧 stretch（增量插入前）
        for i in range(self._list_vbox.count() - 1, -1, -1):
            item = self._list_vbox.itemAt(i)
            if item.widget() is None:  # spacer item
                self._list_vbox.takeAt(i)
                break

        # 新增 / 更新行（insertWidget 对已存在 widget 自动移动位置）
        # round-42 分组渲染：按 group 排序，分组变化时行会移动到对应组
        for idx, inst in enumerate(insts):
            row = self._rows.get(inst.id)
            if row is None:
                row = _InstRow(inst, is_current=(inst.id == cur),
                               on_menu=self._show_row_menu)
                row.clicked.connect(self._select)
                self._rows[inst.id] = row
            else:
                row.refresh_state(inst.id == cur)
            row.set_task_state(self._task_states.get(inst.id))
            self._list_vbox.insertWidget(idx, row)
        self._list_vbox.addStretch(1)

        # restore selection (keep previous if still valid, else current/first)
        if self._selected_id not in self._rows:
            self._selected_id = cur or (insts[0].id if insts else None)
        for rid, row in self._rows.items():
            row.set_selected(rid == self._selected_id)
        self._render_detail()
        if switch and self._body_stack is not None:
            self._body_stack.setCurrentIndex(1)  # split view
        # round-100 列表淡入（克制）：重建后整列轻量淡入
        fade_in_widget(self.list_scroll.viewport())

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
        card = LightTrailCard(radius=16)  # round-50 卡片混合：详情卡流光+反射
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        # name + current tag
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        nm = QLabel(inst.name)
        nm.setProperty("cls", "big")
        nm.setStyleSheet("font-size: 20px;")
        name_row.addWidget(nm)
        if inst.id == self.mgr.current_id:
            from .ui_kit import state_pix
            tag = QWidget()
            tag.setAttribute(Qt.WA_StyledBackground, True)
            tag.setStyleSheet(
                f"background: {with_alpha(COLORS['success'], 0x1A)};"
                f" border-radius: 10px;")
            tl = QHBoxLayout(tag)
            tl.setContentsMargins(8, 3, 10, 3)
            tl.setSpacing(6)
            ti = QLabel()
            ti.setPixmap(state_pix("done", COLORS["success"], 13))
            ti.setFixedSize(14, 14)
            tt = QLabel(t("instances.current"))
            tt.setStyleSheet(f"color: {COLORS['success']}; font-weight: 600;")
            tl.addWidget(ti)
            tl.addWidget(tt)
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

        # badges: version pill · loader badge · format badge (round-82) · java
        meta = QHBoxLayout()
        meta.setSpacing(8)
        ver_pill = QLabel(inst.game_version or "?")
        ver_pill.setProperty("cls", "pill")
        meta.addWidget(ver_pill)
        meta.addWidget(_loader_badge(loader_name(inst.loader), inst.loader))
        meta.addWidget(_fmt_badge(inst))
        if inst.loader_version:
            lv = QLabel(inst.loader_version)
            lv.setProperty("cls", "badge")
            meta.addWidget(lv)
        if inst.java_path:
            jl = QLabel("☕ " + os.path.basename(inst.java_path))
            jl.setProperty("cls", "badge")
            meta.addWidget(jl)
        meta.addStretch(1)
        lay.addLayout(meta)

        # info grid
        grid = QFormLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        grid.setLabelAlignment(Qt.AlignRight)
        # 字段列伸展填满详情面板宽度，长路径不再被压成一行截断
        grid.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        grid.addRow(QLabel(t("instances.detail_path")), self._mono(inst.mc_dir))
        grid.addRow(QLabel(t("instances.detail_source")),
                    QLabel(launcher_label(inst.launcher, show_original=True)))
        if inst.created_at:
            grid.addRow(QLabel(t("instances.detail_created")),
                        QLabel(inst.created_at))
        if inst.version_id and inst.version_id != inst.game_version:
            grid.addRow(QLabel("ID"), self._mono(inst.version_id))
        lay.addLayout(grid)

        # ── actions ──
        # round-84 简洁化：一行只放高频操作（打开文件夹/实例设置/设为当前/删除），
        # 低频操作（打开存档/应用整合包/崩溃分析）收进「⋯ 更多」下拉菜单——
        # 避免按钮挤满一行把详情面板撑出横向滚动条。
        actions = QHBoxLayout()
        actions.setSpacing(8)
        open_btn = QPushButton(t("instances.open_folder"))
        open_btn.setMinimumHeight(34)
        open_btn.setIcon(icon("folder"))
        open_btn.setIconSize(QSize(15, 15))
        open_btn.clicked.connect(lambda: self._open_folder(inst))
        actions.addWidget(open_btn)

        # round-42：实例级设置覆盖（内存/JVM 参数/分组）
        inst_set_btn = QPushButton(t("instances.instance_settings"))
        inst_set_btn.setMinimumHeight(34)
        inst_set_btn.setIcon(icon("settings"))
        inst_set_btn.setIconSize(QSize(15, 15))
        inst_set_btn.clicked.connect(lambda: self._edit_instance_settings(inst))
        actions.addWidget(inst_set_btn)

        cur_btn = QPushButton(t("instances.set_current"))
        cur_btn.setMinimumHeight(34)
        cur_btn.setIcon(icon("check"))
        cur_btn.setIconSize(QSize(15, 15))
        cur_btn.setEnabled(inst.id != self.mgr.current_id)
        cur_btn.clicked.connect(lambda: self._set_current(inst.id))
        actions.addWidget(cur_btn)

        actions.addStretch(1)

        # ── 更多操作（⋯）──
        more_btn = QPushButton("⋯")
        more_btn.setToolTip(t("instances.more_actions"))
        more_btn.setMinimumHeight(34)
        more_btn.setMinimumWidth(34)
        more_btn.setCursor(Qt.PointingHandCursor)
        more_btn.setProperty("cls", "surface")
        _more_menu = QMenu(more_btn)
        for key, ico, slot in [
            # round-42：打开存档目录
            (t("instances.open_saves"), "folder", (lambda: self._open_saves(inst))),
            # round-38 中轴：把整合包应用到已有实例（二次安装/升级）
            (t("instances.apply_pack"), "download", (lambda: self._apply_mrpack_to(inst))),
            # 实例体检（含一键本地修复）：静态扫描性能模组 / JVM / Java / 启动参数
            (t("health.title"), "tools", (lambda: self._health_check(inst))),
            (t("instances.crash_analyze"), "repair", (lambda: self._analyze_crash(inst))),
        ]:
            a = _more_menu.addAction(icon(ico), key)
            a.triggered.connect(
                lambda _c=False, f=slot: f())
        more_btn.setMenu(_more_menu)
        actions.addWidget(more_btn)

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
        # round-44 路径完整展示：wordWrap + ToolTip + 可选中复制
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-family: Consolas, monospace; "
            f"font-size: 12px; background: {COLORS['bg_input']}; "
            f"border-radius: 6px; padding: 4px 10px;"
        )
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setToolTip(text)
        return lbl

    def _select(self, inst_id: str):
        self._selected_id = inst_id
        for rid, row in self._rows.items():
            row.set_selected(rid == inst_id)
        self._render_detail()

    # ── 左侧列表折叠：收起后面板隐藏 → 右侧详情全宽 ──
    # round-107 重做：按钮常驻页头（panel_btn），收起/展开位置始终不变；
    # 不再有会跳位的「列表内箭头 + 左边缘展开条」双按钮。
    def _toggle_panel(self):
        self._list_panel_visible = not self._list_panel_visible
        self._left_panel.setVisible(self._list_panel_visible)
        self._sync_panel_btn()
        if self._list_panel_visible:
            self._splitter.setSizes(
                [self._splitter.width() // 3, self._splitter.width() * 2 // 3])
        else:
            self._splitter.setSizes([0, self._splitter.width()])

    def _sync_panel_btn(self):
        """同步页头收起按钮的图标方向（展开=◀ / 收起=▶）。tooltip 复用同一键。"""
        from .ui_kit import state_pix
        pix = state_pix("chev", COLORS["text_sub"], 14)
        if self._list_panel_visible:
            pix = pix.transformed(QTransform().rotate(180))
        self.panel_btn.setIcon(QIcon(pix))
        self.panel_btn.setIconSize(QSize(15, 15))

    def selected_instance(self) -> Instance | None:
        """当前选中的实例（供快捷键/外部调用）。round-42。"""
        if self._selected_id:
            return self.mgr.get(self._selected_id)
        return None

    # ── 右键菜单（round-42，对齐主流鼠标流）──
    def _show_row_menu(self, inst: Instance, pos):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction(t("instances.set_current"),
                    lambda: self._set_current(inst.id))
        m.addAction(t("instances.duplicate"),
                    lambda: self._duplicate(inst))
        m.addSeparator()
        m.addAction(t("instances.backup"),
                    lambda: self._backup(inst))
        m.addAction(t("instances.restore"),
                    lambda: self._restore(inst))
        m.addSeparator()
        m.addAction(t("health.title"),
                    lambda: self._health_check(inst))
        m.addSeparator()
        m.addAction(t("instances.open_folder"),
                    lambda: self._open_folder(inst))
        m.addAction(t("instances.crash_analyze"),
                    lambda: self._show_crash(inst))
        m.addSeparator()
        m.addAction(t("instances.group_move_to"),
                    lambda: self._edit_group(inst))
        m.addAction(t("common.delete"),
                    lambda: self._delete_instance(inst))
        m.exec(pos)

    def _duplicate(self, inst: Instance):
        """克隆实例（Worker 复制目录，防大实例卡 UI）。"""
        from .win_rounded import text_input, warn, toast
        from .worker import Worker
        name, ok = text_input(
            self, t("instances.duplicate_title"),
            t("instances.duplicate_hint"), default=f"{inst.name} (副本)")
        if not ok or not name.strip():
            return
        self._dup_worker = Worker(self.mgr.duplicate, inst.id, name.strip())
        self._dup_worker.finished.connect(
            lambda _n: (self._refresh(), self._set_current(_n.id) if _n else None))
        self._dup_worker.error.connect(
            lambda e: warn(self, t("instances.duplicate_title"), str(e)))
        self._dup_worker.start()

    # ── 实例备份 / 回滚（N1，对齐主流一键备份 / 更新坏了一键回滚）──
    def _backup(self, inst: Instance):
        """创建一份完整快照（后台 Worker，防大实例卡 UI）。"""
        from .win_rounded import toast, warn
        from .core.backup import create_backup
        from .worker import Worker
        self._backup_worker = Worker(create_backup, inst)
        self._backup_worker.finished.connect(
            lambda _s: toast(self, t("instances.backup_title"),
                             t("instances.backup_done")))
        self._backup_worker.error.connect(
            lambda e: warn(self, t("instances.backup_title"), str(e)))
        self._backup_worker.start()

    def _restore(self, inst: Instance):
        """选一份历史快照，回滚覆盖当前 mods / config / 存档。"""
        from .win_rounded import toast, warn, confirm
        from .worker import Worker
        from .core.backup import list_backups, load_manifest, restore_backup

        snaps = list_backups(inst)
        if not snaps:
            toast(self, t("instances.restore_title"),
                  t("instances.restore_none"))
            return

        pick = self._pick_backup(inst, snaps)
        if pick is None:
            return
        # 覆写前：先警告建议做当前备份，再明确确认不可逆
        tip = t("instances.restore_warn")
        if not confirm(
            self, t("instances.restore_title"),
            t("instances.restore_confirm", name=inst.name)
            + "\n\n" + tip,
        ):
            return

        self._restore_worker = Worker(restore_backup, inst, pick)
        self._restore_worker.finished.connect(
            lambda _m: (toast(self, t("instances.restore_title"),
                              t("instances.restore_done")),
                        self._refresh(), self._render_detail()))
        self._restore_worker.error.connect(
            lambda e: warn(self, t("instances.restore_title"), str(e)))
        self._restore_worker.start()

    def _pick_backup(self, inst: Instance, snaps: list[str]):
        """列快照供选择；返回选中的快照路径，取消返回 None。"""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                       QLabel, QListWidget, QPushButton)
        from .core.backup import load_manifest

        dlg = QDialog(self)
        dlg.setWindowTitle(t("instances.restore_pick_title"))
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)
        lay.addWidget(QLabel(t("instances.restore_pick_hint")))
        lst = QListWidget()
        for snap in snaps:
            m = load_manifest(snap)
            name = m.get("instance_name") or inst.name
            when = m.get("snapshot_time") or os.path.basename(snap)
            ver = m.get("game_version") or ""
            load = m.get("loader") or ""
            lst.addItem(f"{name} · {when}\n  {ver} / {load}"
                        if ver else f"{name} · {when}")
        if snaps:
            lst.setCurrentRow(0)
        lay.addWidget(lst)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(dlg.reject)
        ok = QPushButton(t("common.ok"))
        ok.setProperty("cls", "accent")
        ok.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)
        if dlg.exec() != 1:
            return None
        row = lst.currentRow()
        if row < 0:
            return None
        return snaps[row]

    def _edit_group(self, inst: Instance):
        """设置/清除实例分组。"""
        from .win_rounded import text_input, info
        from .i18n import t as _t
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        from PySide6.QtCore import Qt as _Qt
        cur = inst.group or ""
        name, ok = text_input(
            self, _t("instances.group_title"),
            _t("instances.group_hint"), default=cur)
        if not ok:
            return
        inst.group = (name or "").strip()
        self.mgr.save(inst)
        self._refresh()

    def _show_crash(self, inst: Instance):
        from .crash_dialog import CrashDialog
        CrashDialog(inst, parent=self).exec()

    def _health_check(self, inst: Instance):
        """实例体检（N5 冲突预检的升级）：静态扫描 + 弹报告 + 一键本地修复。

        修复只改实例字段并落盘保存，不联网、不动用户游戏文件。
        """
        from .mod_check_dialog import open_health_dialog
        open_health_dialog(self, inst, self.mgr)

    def _mod_check(self, inst: Instance):
        """旧入口（模组冲突预检）→ 转调体检，保持兼容。"""
        self._health_check(inst)

    def _delete_instance(self, inst: Instance):
        from .win_rounded import confirm
        if not confirm(
            self, t("instances.delete_title"),
            t("instances.delete_confirm", name=inst.name),
        ):
            return
        self.mgr.remove(inst.id)
        self._refresh()

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

    def _open_saves(self, inst: Instance):
        """打开存档目录（不存在则创建）。round-42 新增，round-57 修：版本隔离
        下游戏存档实际读写 <game_dir>/saves，之前固定 mc_dir/saves 打开的是
        错误目录（同 round-56 mods_dir 的脱节）。"""
        from PySide6.QtGui import QDesktopServices
        p = os.path.join(inst.game_dir, "saves")
        os.makedirs(p, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _edit_instance_settings(self, inst: Instance):
        """实例级覆盖设置：内存 / JVM / 渲染器 / GC / 启动高级设置（round-42/53/55）。

        round-55 新增：游戏附加参数、JVM 预设、版本隔离（含自定义目录）、
        启动后/退出后命令——全部「空值 = 跟随全局」。
        """
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                       QLabel, QSpinBox, QLineEdit, QPushButton,
                                       QComboBox, QCheckBox, QScrollArea,
                                       QWidget, QFrame)
        from .i18n import t as _t
        dlg = QDialog(self)
        dlg.setWindowTitle(_t("instances.instance_settings"))
        dlg.resize(480, 620)
        dlg.setMinimumWidth(360)
        root = QVBoxLayout(dlg)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # round-107：禁止底部横向滑条（用户明确不允许横向滚动）——内容强制
        # 收缩到视口宽度，长文本由 Qt 自动省略/换行，永远不会被挤成两列。
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(scroll, stretch=1)
        content = QWidget()
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay = QVBoxLayout(content)
        lay.setSpacing(12)
        # 内存
        mem_row = QHBoxLayout()
        mem_row.addWidget(QLabel(_t("instances.setting_mem")))
        mem = QSpinBox()
        mem.setRange(0, 32768)
        mem.setSingleStep(512)
        mem.setValue(inst.ram_mb or 0)
        mem.setSuffix(" MB（0=全局）")
        mem_row.addWidget(mem, stretch=1)
        lay.addLayout(mem_row)
        # JVM 参数
        lay.addWidget(QLabel(_t("instances.setting_jvm")))
        jvm = QLineEdit(inst.jvm_args or "")
        jvm.setPlaceholderText(_t("instances.setting_jvm_hint"))
        lay.addWidget(jvm)
        # round-55 JVM 预设（对齐主流「JVM 参数」预设；空 = 跟随全局）
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel(_t("instances.jvm_preset")))
        jvm_preset = QComboBox()
        jvm_preset.addItem(_t("instances.jvm_preset_follow"), "")
        jvm_preset.addItem(_t("instances.jvm_preset_default"), "default")
        jvm_preset.addItem(_t("instances.jvm_preset_auto"), "auto")
        jvm_preset.addItem(_t("instances.jvm_preset_aikar"), "aikar")
        jvm_preset.addItem(_t("instances.jvm_preset_custom"), "custom")
        idx = jvm_preset.findData((inst.jvm_preset or ""))
        jvm_preset.setCurrentIndex(idx if idx >= 0 else 0)
        preset_row.addWidget(jvm_preset, stretch=1)
        lay.addLayout(preset_row)
        # round-53 渲染器（对齐主流版本设置→渲染器 / 启动设置）
        renderer_row = QHBoxLayout()
        renderer_row.addWidget(QLabel(_t("instances.setting_renderer_title")))
        renderer = QComboBox()
        renderer.addItem(_t("instances.renderer_auto"), "auto")
        renderer.addItem(_t("instances.renderer_software"), "software")
        renderer.addItem(_t("instances.renderer_legacy"), "legacy")
        idx = renderer.findData((inst.renderer or "auto"))
        renderer.setCurrentIndex(idx if idx >= 0 else 0)
        renderer.setToolTip(_t("instances.renderer_hint"))
        renderer_row.addWidget(renderer, stretch=1)
        lay.addLayout(renderer_row)
        # round-55 游戏附加参数（--server 直连等；空 = 跟随全局）
        ga_row = QHBoxLayout()
        ga_row.addWidget(QLabel(_t("instances.game_args")))
        game_args = QLineEdit((inst.game_args or "").strip())
        game_args.setPlaceholderText(_t("instances.game_args_hint"))
        ga_row.addWidget(game_args, stretch=1)
        lay.addLayout(ga_row)
        # round-82 启动格式（磁盘布局）：自适应默认，可手动覆盖/强制
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel(_t("instances.fmt_title")))
        fmt_combo = QComboBox()
        for _k, _v in (("auto", "auto"), ("vanilla", "vanilla"), ("iso", "iso"),
                       ("multimc", "multimc"), ("curseforge", "curseforge"),
                       ("modrinth", "modrinth"), ("custom", "custom")):
            fmt_combo.addItem(_t(f"instances.fmt_{_k}"), _v)
        _cur_fmt = (inst.format or "auto").strip()
        _fmt_vals = {"auto", "vanilla", "iso", "multimc", "curseforge", "modrinth", "custom"}
        _idx = fmt_combo.findData(_cur_fmt if _cur_fmt in _fmt_vals else "auto")
        fmt_combo.setCurrentIndex(_idx if _idx >= 0 else 0)
        fmt_hint = QLabel()
        fmt_hint.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: 11px; margin-left: 6px;")

        def _update_fmt_hint(data: str) -> None:
            try:
                if (data or "auto") == "auto":
                    _det = detect_format(inst)
                    fmt_hint.setText(_t("instances.fmt_detected",
                                        name=_t(f"instances.fmt_{_det}")))
                else:
                    fmt_hint.setText(_t("instances.fmt_forced", name=_t(f"instances.fmt_{data}")))
            except Exception:  # noqa: BLE001
                fmt_hint.setText("")

        fmt_combo.currentIndexChanged.connect(
            lambda _i: _update_fmt_hint(fmt_combo.currentData()))
        fmt_row.addWidget(fmt_combo)
        fmt_row.addWidget(fmt_hint, stretch=1)
        lay.addLayout(fmt_row)
        # round-55 版本隔离（空 = 跟随全局；custom 时填自定义目录）
        iso_row = QHBoxLayout()
        iso_row.addWidget(QLabel(_t("instances.isolation")))
        iso_combo = QComboBox()
        iso_combo.addItem(_t("instances.isolation_follow"), "")
        iso_combo.addItem(_t("instances.isolation_isolated"), "isolated")
        iso_combo.addItem(_t("instances.isolation_custom"), "custom")
        idx = iso_combo.findData((inst.isolation or ""))
        iso_combo.setCurrentIndex(idx if idx >= 0 else 0)
        iso_row.addWidget(iso_combo, stretch=1)
        lay.addLayout(iso_row)
        game_dir_edit = QLineEdit((inst.game_dir_override or "").strip())
        game_dir_edit.setPlaceholderText(_t("instances.game_dir_override_hint"))
        game_dir_edit.setVisible(iso_combo.currentData() == "custom")
        iso_combo.currentIndexChanged.connect(
            lambda _i: game_dir_edit.setVisible(iso_combo.currentData() == "custom"))
        lay.addWidget(game_dir_edit)
        # round-53 实验性性能（对齐主流性能高级设置）
        lay.addWidget(QLabel(_t("instances.setting_perf_title")))
        g1gc = QCheckBox(_t("instances.perf_g1gc"))
        g1gc.setChecked(bool(getattr(inst, "perf_g1gc", True)))
        g1gc.setToolTip(_t("instances.perf_g1gc_hint"))
        lay.addWidget(g1gc)
        noexgc = QCheckBox(_t("instances.perf_disable_explicit_gc"))
        noexgc.setChecked(bool(getattr(inst, "perf_disable_explicit_gc", False)))
        noexgc.setToolTip(_t("instances.perf_disable_explicit_gc_hint"))
        lay.addWidget(noexgc)
        # round-55 启动后 / 退出后命令（空 = 跟随全局）
        lay.addWidget(QLabel(_t("instances.post_launch_cmd")))
        post_cmd = QLineEdit((inst.post_launch_cmd or "").strip())
        post_cmd.setPlaceholderText(_t("instances.hook_ph"))
        lay.addWidget(post_cmd)
        lay.addWidget(QLabel(_t("instances.exit_cmd")))
        exit_cmd = QLineEdit((inst.exit_cmd or "").strip())
        exit_cmd.setPlaceholderText(_t("instances.hook_ph"))
        lay.addWidget(exit_cmd)
        # 分组
        grp_row = QHBoxLayout()
        grp_row.addWidget(QLabel(_t("instances.group_title")))
        grp = QLineEdit(inst.group or "")
        grp.setPlaceholderText(_t("instances.group_hint"))
        grp_row.addWidget(grp, stretch=1)
        lay.addLayout(grp_row)
        scroll.setWidget(content)
        # 按钮（滚动区外，始终可见）
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton(_t("common.cancel"))
        cancel.clicked.connect(dlg.reject)
        ok = QPushButton(_t("common.ok"))
        ok.setProperty("cls", "accent")
        ok.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        root.addLayout(btn_row)
        _update_fmt_hint(fmt_combo.currentData())  # 打开即显示当前识别
        if dlg.exec() != 1:
            return
        inst.ram_mb = mem.value()
        inst.jvm_args = jvm.text().strip()
        inst.jvm_preset = jvm_preset.currentData() or ""
        inst.renderer = renderer.currentData() or "auto"
        inst.format = fmt_combo.currentData() or ""   # round-82 格式（auto → 存空）
        inst.game_args = game_args.text().strip()
        inst.isolation = iso_combo.currentData() or ""
        inst.game_dir_override = game_dir_edit.text().strip()
        inst.perf_g1gc = g1gc.isChecked()
        inst.perf_disable_explicit_gc = noexgc.isChecked()
        inst.post_launch_cmd = post_cmd.text().strip()
        inst.exit_cmd = exit_cmd.text().strip()
        inst.group = grp.text().strip()
        self.mgr.save(inst)
        self._refresh()

    # ── 整合包应用到已有实例（round-38 中轴：二次安装/升级）──
    def _apply_mrpack_to(self, inst: Instance):
        from .win_rounded import pick_files, confirm, info
        from .worker import ProgressWorker
        from .core.install import apply_mrpack_to_instance

        path = pick_files(
            self, t("modpack.file_pick"), "",
            t("modpack.filter_all"),
            multi=False, dir_only=False,
        )
        if not path:
            return
        if not path.lower().endswith(".mrpack"):
            info(self, t("modpack.title"), t("instances.apply_pack_format"))
            return
        if not confirm(
            self, t("instances.apply_pack_title"),
            t("instances.apply_pack_confirm", name=inst.name),
            detail=t("instances.apply_pack_hint"),
        ):
            return

        settings = load_config()
        self._pack_worker = ProgressWorker(
            apply_mrpack_to_instance, path, inst,
            mirror=settings.get("download_mirror", "official"),
            proxy=settings.get("download_proxy", ""),
        )
        self._pack_worker.status.connect(
            lambda s: self.window().statusBar().showMessage(s))
        self._pack_worker.finished.connect(
            lambda v: self._on_pack_applied(inst, v))
        self._pack_worker.error.connect(
            lambda e: self._on_pack_error(e))
        self._pack_worker.start()

    def _on_pack_applied(self, inst: Instance, launch_version):
        try:
            self.mgr.save(inst)
            self._refresh()
        except Exception:
            pass
        from .win_rounded import toast
        toast(self, t("instances.apply_pack_title"),
              t("instances.apply_pack_done", ver=launch_version or ""))

    def _on_pack_error(self, msg: str):
        from .win_rounded import warn
        warn(self, t("instances.apply_pack_title"),
             t("instances.apply_pack_fail", err=msg))

    # ------------------------------------------------------------------ util
    def _empty_state(self) -> QWidget:
        """Friendly first-run state with a clear primary action.

        The page header already exposes 扫描并导入 / 导入包 buttons, so the
        empty-state card only surfaces the primary CTA (新建实例) to avoid
        three nearly-identical button rows competing for attention.
        """
        card = RoundedCard(radius=16)
        # 默认 fill 跟随全局 frosted 开关（半透明/实色），不显式 set_fill，
        # 开关切换时 paintEvent 自动用新的 token 重绘。
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        l = QVBoxLayout(card)
        l.setContentsMargins(24, 24, 24, 24)

        new_btn = ui_kit.make_button(
            t("instances.new"), kind="accent", icon_key="add",
            on_click=self._new, min_h=40)
        self._empty_btn = new_btn

        es = ui_kit.empty_state(
            "instances",
            t("instances.empty_title"),
            t("instances.empty"),
            actions=[new_btn],
            icon_size=80,
        )
        l.addWidget(es)
        return card

    # ------------------------------------------------------------------ ops
    def _set_header_buttons_enabled(self, on: bool):
        self.new_btn.setEnabled(on)
        self.scan_btn.setEnabled(on)
        self.mrpack_btn.setEnabled(on)
        self.panel_btn.setEnabled(on)

    def _mk_header_btn(self, text: str, icon_key: str, on_click,
                       w: int, accent: bool = False) -> QPushButton:
        """round-45e header 按钮：3 个按钮**完全统一**风格（白底+黑字+灰边+hover 灰底），
        accent 形参保留用于后续其他场景，但实例页 3 按钮统一关闭。
        宽度由调用方传入，padding 6/14 + 字号 13px，"新建实例"4 字需 w≥110 才不挤压。
        """
        b = QPushButton(text)
        b.setFixedSize(w, 34)
        b.setCursor(Qt.PointingHandCursor)
        b.setIcon(icon(icon_key))
        b.setIconSize(QSize(15, 15))
        bg = COLORS["bg_btn"]
        fg = COLORS["text_main"]
        bd = COLORS["border"]
        b.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {bd};"
            f" border-radius: 8px; padding: 6px 14px; font-size: 13px;"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ background: {COLORS['bg_hover']}; }}"
        )
        b.clicked.connect(on_click)
        return b

    def _new(self):
        """Open the create-instance wizard embedded in the body (no popup)."""
        if self._new_panel is not None or self._closing_new:
            return
        if self._scan_panel is not None:
            self._close_scan_panel()
        self._set_header_buttons_enabled(False)
        if self._empty_btn is not None:
            self._empty_btn.setEnabled(False)
        self._new_panel = NewInstanceDialog(self, embedded=True)
        self._new_panel.created.connect(self._on_new_created)
        self._new_panel.cancelled.connect(self._close_new_panel)
        idx = self._body_stack.addWidget(self._new_panel)
        self._body_stack.setCurrentIndex(idx)

    def _on_new_created(self, name: str, version: str, loader: str,
                        java_path: str, ldver: str):
        inst = self.mgr.add(name, version, loader, loader_version=ldver,
                            java_path=java_path)
        self._selected_id = inst.id
        self._close_new_panel()
        # round-107 T8：交由 MainWindow 统一发起后台下载（状态栏 + 可召回对话框）。
        self.instance_created.emit(inst.id)
        # _close_new_panel defers _refresh() via QTimer so the view rebuilds
        # after the wizard is fully destroyed.

    def _close_new_panel(self):
        """Remove the embedded create wizard and restore the instance view."""
        if self._new_panel is None:
            return
        panel = self._new_panel
        self._new_panel = None
        self._closing_new = True
        self._set_header_buttons_enabled(True)
        if self._empty_btn is not None:
            self._empty_btn.setEnabled(True)
        self._body_stack.removeWidget(panel)
        panel.deleteLater()
        # Defer the refresh so Qt can finish deleting the panel (and its
        # children/workers) before we rebuild the underlying list view.
        QTimer.singleShot(0, self._finish_close_new)

    def _finish_close_new(self):
        self._closing_new = False
        # 若关闭期间又打开了别的面板（如 _open_scan 已切到扫描面板），
        # 就不再刷新（避免把面板隐藏 / 重复重建列表）。
        if self._new_panel is None and self._scan_panel is None:
            self._refresh()

    def _open_scan(self):
        """Embed the scanner into the body area (no modal dialog)."""
        if self._scan_panel is not None or self._closing_scan:
            return
        if self._new_panel is not None:
            self._close_new_panel()
        from .scan_dialog import ScanPanel

        self._set_header_buttons_enabled(False)
        if self._empty_btn is not None:
            self._empty_btn.setEnabled(False)
        self._scan_panel = ScanPanel(self)
        self._scan_panel.done.connect(self._close_scan_panel)
        idx = self._body_stack.addWidget(self._scan_panel)
        self._body_stack.setCurrentIndex(idx)

    def _close_scan_panel(self):
        """Remove the embedded scanner and refresh the instance list."""
        if self._scan_panel is None:
            return
        panel = self._scan_panel
        self._scan_panel = None
        self._closing_scan = True
        self._set_header_buttons_enabled(True)
        if self._empty_btn is not None:
            self._empty_btn.setEnabled(True)
        self._body_stack.removeWidget(panel)
        panel.deleteLater()
        QTimer.singleShot(0, self._finish_close_scan)

    def _finish_close_scan(self):
        self._closing_scan = False
        if self._new_panel is None and self._scan_panel is None:
            self._refresh()
        self.scan_done.emit()

    def _import_pack(self):
        """Import a modpack or instance folder (.mrpack / CurseForge .zip / plain .zip / folder).

        The file picker accepts several formats; we detect the format and pick
        the right importer so the user has a single "Import pack" entry point.
        """
        from PySide6.QtWidgets import QProgressDialog, QApplication
        from .win_rounded import pick_files, info, warn
        from .modpack_import import (
            detect_pack_format, import_curseforge_zip,
            import_zip_as_instance, import_folder_as_instance,
        )
        from .net_api import NetError

        path = pick_files(
            self, t("modpack.file_pick"), "",
            t("modpack.filter_all"),
            multi=False,
            dir_only=False,
        )
        if not path:
            return

        fmt = detect_pack_format(path)
        if fmt is None:
            warn(self, t("modpack.title"), t("modpack.unknown_format"))
            return

        # Close any embedded panels before the modal import flow so the body
        # stack is in a clean state when we refresh afterwards.
        if self._new_panel is not None:
            self._close_new_panel()
        if self._scan_panel is not None:
            self._close_scan_panel()

        # .mrpack keeps the existing metadata + install dialog (has its own worker)
        if fmt == "mrpack":
            self._show_mrpack_dialog(path)
            return

        # CurseForge requires an API key; ask once before starting the worker.
        if fmt == "curseforge":
            if not confirm(
                self, t("modpack.curseforge_key_title"),
                t("modpack.curseforge_key_body"),
            ):
                return

        # Run heavy import in a worker so the UI doesn't freeze.
        fn_map = {
            "curseforge": import_curseforge_zip,
            "zip_mc": import_zip_as_instance,
            "folder": import_folder_as_instance,
        }
        fn = fn_map[fmt]
        progress = QProgressDialog(self)
        progress.setWindowTitle(t("modpack.title"))
        progress.setLabelText(t("modpack.importing"))
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setRange(0, 0)  # indeterminate
        progress.setMinimumWidth(420)

        worker = Worker(fn, path, self.mgr)

        def _done(inst):
            progress.close()
            toast(self, t("modpack.title"), t("modpack.done"))
            self._refresh()
            if inst and getattr(inst, "id", None):
                self.mgr.set_current(inst.id)
                self.current_changed.emit(inst.id)

        def _err(e):
            progress.close()
            if isinstance(e, NetError):
                warn(self, t("modpack.title"), str(e))
            else:
                warn(self, t("modpack.title"), t("modpack.error", e=e))

        worker.finished.connect(_done)
        worker.error.connect(_err)
        worker.start()

    # ── 拖拽导入（round-42，对齐主流整合构建：拖 .mrpack/.zip 进窗口即导入）──
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                p = u.toLocalFile()
                if p.lower().endswith((".mrpack", ".zip")):
                    e.acceptProposedAction()
                    return
        super().dragEnterEvent(e)

    def dropEvent(self, e):
        from .modpack_import import detect_pack_format
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if not p:
                continue
            fmt = detect_pack_format(p) if p.lower().endswith(".zip") else \
                ("mrpack" if p.lower().endswith(".mrpack") else None)
            if fmt == "mrpack":
                self._show_mrpack_dialog(p)
            elif fmt is not None:
                # 走统一的「导入包」流程（CF zip / 普通 zip）
                self._import_pack_path(p)
            else:
                info(self, t("modpack.title"), t("modpack.unknown_format"))
        e.acceptProposedAction()

    def _show_mrpack_dialog(self, path: str):
        """Keep the original mrpack preview + install dialog for .mrpack files."""
        import minecraft_launcher_lib
        from .modpack_import import _parse_mrpack_info

        try:
            raw = minecraft_launcher_lib.mrpack.get_mrpack_information(path)
            launch_version = minecraft_launcher_lib.mrpack.get_mrpack_launch_version(path)
        except Exception:
            warn(self, t("mrpack.title"), t("mrpack.bad_file"))
            return
        info = _parse_mrpack_info(raw)
        info["launch_version"] = launch_version
        dlg = _MrpackDialog(path, info, self)
        dlg.exec()
        self._refresh()
        cur = self.mgr.current_id
        if cur:
            self.current_changed.emit(cur)

    def _import_mrpack(self):
        """Backwards-compatible alias for the old 'Import Modpack' button."""
        self._import_pack()

    def _import_pack_path(self, path: str):
        """统一的整合包导入流程（拖拽/按钮共用）。round-42。"""
        from .win_rounded import warn
        from .modpack_import import (
            detect_pack_format, import_curseforge_zip,
            import_zip_as_instance, import_folder_as_instance,
        )
        fmt = detect_pack_format(path)
        if fmt is None:
            warn(self, t("modpack.title"), t("modpack.unknown_format"))
            return
        from .win_rounded import QProgressDialog, QApplication
        from .worker import Worker
        # round-74 交互反馈：导入动辄几十秒，给主窗口状态条转圈 + 文案，
        # 避免"点了没反应"的错觉；结束（成功或报错）都恢复。
        win = self.window()
        bar = getattr(win, "_progress", None)
        stat = win.statusBar() if win is not None else None
        if bar is not None:
            bar.setMaximum(0)
            bar.setVisible(True)
        if stat is not None:
            stat.showMessage(t("modpack.importing"))

        def _finish(*_a):
            if bar is not None:
                bar.setVisible(False)
            if stat is not None:
                stat.showMessage(t("status.ready"), 3000)

        if fmt == "curseforge":
            self._pack_worker = Worker(import_curseforge_zip, path, self.mgr)
            self._pack_worker.finished.connect(_finish)
            self._pack_worker.finished.connect(self._on_pack_imported)
            self._pack_worker.error.connect(
                lambda e: warn(self, t("modpack.title"), str(e)))
            self._pack_worker.error.connect(_finish)
            self._pack_worker.start()
        elif fmt == "zip":
            self._pack_worker = Worker(import_zip_as_instance, path, self.mgr)
            self._pack_worker.finished.connect(_finish)
            self._pack_worker.finished.connect(self._on_pack_imported)
            self._pack_worker.error.connect(
                lambda e: warn(self, t("modpack.title"), str(e)))
            self._pack_worker.error.connect(_finish)
            self._pack_worker.start()

    def _on_pack_imported(self, inst):
        self._refresh()
        if inst is not None and getattr(inst, "id", None):
            self._set_current(inst.id)

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
        self.scan_btn.setText(t("instances.scan_import"))
        self.mrpack_btn.setText(t("instances.import_pack"))
        self.list_lbl.setText(t("instances.list_title"))
        # Don't jump away from an embedded panel when the language changes.
        self._refresh(switch=not (self._new_panel or self._scan_panel))


# ---------------------------------------------------------------- Mods
def _mod_display_name(path: str) -> str:
    """Human-readable mod name from a jar path. Strips the extension and the
    optional ``.disabled`` toggle suffix, then prettifies dashes/underscores."""
    base = os.path.basename(path)
    if base.endswith(".disabled"):
        base = base[: -len(".disabled")]
    if base.lower().endswith(".jar"):
        base = base[: -len(".jar")]
    return base.replace("_", " ").replace("-", " ").strip() or os.path.basename(path)


_LOADER_HINT = {
    "fabric": "fabric", "neofabric": "fabric",
    "forge": "forge", "neoforge": "neoforge",
    "quilt": "quilt", "liteloader": "liteloader",
    "cleanroom": "cleanroom",
}


def _mod_loader_hint(path: str) -> str:
    """Best-effort loader tag from the mod filename (for a small badge);
    "" if none is detectable."""
    low = os.path.basename(path).lower()
    for key, loader in _LOADER_HINT.items():
        if key in low:
            return loader
    return ""


class ModCard(RoundedCard):
    toggled = Signal(str, bool)  # path, enabled
    removed = Signal(str)
    open_folder = Signal(str)
    copy_name = Signal(str)

    def __init__(self, path: str, enabled: bool, parent=None):
        super().__init__(radius=12, parent=parent)
        self.path = path
        self.enabled = enabled
        self.setMinimumHeight(74)
        # disabled mods read as muted & slightly faded — more obviously "off".
        if not enabled:
            op = QGraphicsOpacityEffect(self)
            op.setOpacity(0.62)
            self.setGraphicsEffect(op)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(14)

        # ── loader-tinted icon tile ──
        loader = _mod_loader_hint(path)
        tile_key = "mods"
        # round-100：图标块默认中性（品牌色仅主题包 loader_vivid 时启用）
        tile = ui_kit.tile(
            tile_key, 44, 22,
            bg=(LOADER_BADGE.get(loader) if _loader_vivid() else None))
        lay.addWidget(tile)

        # ── info column: name + meta (loader pill · state) ──
        col = QVBoxLayout()
        col.setSpacing(4)
        name = QLabel(_mod_display_name(path))
        name.setProperty("cls", "title")
        col.addWidget(name)
        meta = QHBoxLayout()
        meta.setSpacing(8)
        if loader:
            ld = _loader_badge(loader_name(loader), loader)
            meta.addWidget(ld)
        state = QLabel(
            t("mods.state_enabled") if enabled else t("mods.state_disabled"))
        if enabled:
            state.setStyleSheet(
                f"color: {COLORS['success']};"
                f" background: {with_alpha(COLORS['success'], 0x1A)}; "
                f"font-weight: 600; border-radius: 9px; padding: 2px 10px; "
                f"font-size: 11px;")
        else:
            state.setStyleSheet(
                f"color: {COLORS['text_sub']}; background: {COLORS['bg_hover']}; "
                f"font-weight: 600; border-radius: 9px; padding: 2px 10px; "
                f"font-size: 11px;")
        meta.addWidget(state)
        meta.addStretch(1)
        col.addLayout(meta)
        lay.addLayout(col, 1)

        # ── toggle + delete ──
        tog = QPushButton(t("mods.disable") if enabled else t("mods.enable"))
        tog.setMinimumHeight(32)
        tog.setIcon(icon("check" if enabled else "add"))
        tog.setIconSize(QSize(15, 15))
        tog.clicked.connect(lambda: self.toggled.emit(path, not self.enabled))
        lay.addWidget(tog)

        del_btn = QPushButton(t("mods.delete"))
        del_btn.setProperty("cls", "danger")
        del_btn.setMinimumHeight(32)
        del_btn.clicked.connect(lambda: self.removed.emit(path))
        lay.addWidget(del_btn)

        # round-74 右键菜单（对齐主流/CurseForge 鼠标流）：
        # 「打开所在文件夹」排查冲突、「复制文件名」查 Modrinth 时快速粘贴。
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda _pos: self._show_menu())

    def _show_menu(self):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QCursor
        m = QMenu(self)
        m.addAction(t("mods.open_folder"), lambda: self.open_folder.emit(self.path))
        m.addAction(t("mods.copy_name"), lambda: self.copy_name.emit(self.path))
        m.exec(QCursor.pos())


class ModsPage(QWidget):
    """Per-instance mod manager: pick an instance, toggle .jar files."""

    def __init__(self, list_instances, get_current_instance, parent=None):
        super().__init__(parent)
        self.list_instances = list_instances
        self.get_current = get_current_instance
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        self.target_lbl = QLabel(t("mods.target_label"))
        self.target_lbl.setProperty("cls", "sub")
        self.inst_combo = QComboBox()
        self.inst_combo.setMinimumHeight(34)
        # round-52 自适应：不再硬设 220 最小宽度（会把 header 撑爆到 >620px，
        # 窄窗口下溢出）。combo 在操作行里用 stretch=1 弹性伸展，缩到理想宽度。
        self.inst_combo.setMinimumWidth(0)
        self.inst_combo.currentIndexChanged.connect(self._on_target_changed)
        self.add_btn = ui_kit.make_button(
            t("mods.add"), kind="accent", icon_key="add",
            on_click=self._add, min_h=38)
        self.update_btn = ui_kit.make_button(
            t("mods.check_updates"), kind="secondary", icon_key="download",
            on_click=self._check_updates, min_h=38)

        self._header = ui_kit.page_header(
            t("mods.title"), icon_key="mods")
        self.title_lbl = self._header.title_lbl
        root.addWidget(self._header)

        # round-52 操作行独立成一行：目标实例 + 组合 + 两个按钮。
        # combo 用 stretch 弹性伸展，窄窗口下按钮不被挤压、内容不溢出。
        action_widget = QWidget()
        action_widget.setStyleSheet("background: transparent;")
        al = QHBoxLayout(action_widget)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(10)
        al.addWidget(self.target_lbl)
        al.addWidget(self.inst_combo, stretch=1)
        al.addWidget(self.add_btn)
        al.addWidget(self.update_btn)
        root.addWidget(action_widget)

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

    # ── 检查更新 / 批量更新（round-41，对齐主流/CF App）──
    def _check_updates(self):
        inst = self._target()
        if inst is None:
            toast(self, t("common.hint"), t("mods.no_instance"))
            return
        self.update_btn.setEnabled(False)
        self.update_btn.setText(t("mods.checking_updates"))
        from .worker import Worker
        from .mod_updater import check_updates
        self._check_worker = Worker(
            check_updates, inst,
            mc_version=getattr(inst, "game_version", "") or "",
            loader=getattr(inst, "loader", "") or "",
        )
        self._check_worker.finished.connect(self._on_updates_checked)
        self._check_worker.error.connect(self._on_updates_error)
        self._check_worker.start()

    def _on_updates_checked(self, result):
        self.update_btn.setEnabled(True)
        self.update_btn.setText(t("mods.check_updates"))
        updates = result.get("updates", [])
        unknown = result.get("unknown", [])
        if not updates:
            msg = t("mods.up_to_date")
            if unknown:
                msg = t("mods.up_to_date_unknown", n=len(unknown))
            toast(self, t("mods.check_updates"), msg)
            return
        detail = "\n".join(
            f"• {u['title']}: {u['local_version']} → {u['latest_version']}" for u in updates[:30])
        if len(updates) > 30:
            detail += f"\n… 共 {len(updates)} 个"
        if unknown:
            detail += f"\n\n（{len(unknown)} 个 mod 无法识别来源，已跳过）"
        from .win_rounded import confirm
        if not confirm(
            self, t("mods.update_found_title"),
            t("mods.update_found_body", n=len(updates)),
            detail=detail,
        ):
            return
        self.update_btn.setEnabled(False)
        self.update_btn.setText(t("mods.updating"))
        from .mod_updater import update_mods
        self._update_worker = Worker(update_mods, self._target(), updates)
        self._update_worker.finished.connect(self._on_updates_done)
        self._update_worker.error.connect(self._on_updates_error)
        self._update_worker.start()

    def _on_updates_done(self, ok_count):
        self.update_btn.setEnabled(True)
        self.update_btn.setText(t("mods.check_updates"))
        toast(self, t("mods.check_updates"),
              t("mods.update_done", n=ok_count or 0))
        self._render_mods()

    def _on_updates_error(self, msg: str):
        self.update_btn.setEnabled(True)
        self.update_btn.setText(t("mods.check_updates"))
        warn(self, t("mods.check_updates"), t("mods.update_fail", err=msg))

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
            empty = ui_kit.empty_state(
                "mods", t("mods.empty_title"), t("mods.select_instance"),
                icon_size=72)
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
            card.open_folder.connect(self._open_mods_folder)
            card.copy_name.connect(self._copy_mod_name)
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

    def _open_mods_folder(self, path: str):
        """资源管理器定位到该 mod 文件（explorer /select）——排查冲突定位更快。"""
        try:
            import subprocess
            subprocess.Popen(
                ["explorer", "/select,", os.path.normpath(path)])
        except OSError:
            from .win_rounded import warn as _warn
            _warn(self, t("mods.fail_title"), str(path))

    def _copy_mod_name(self, path: str):
        """复制文件名（含 .jar/.disabled 后缀原样）到剪贴板 + 轻提示。"""
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(os.path.basename(path))
        from .win_rounded import toast as _toast
        _toast(self, t("mods.copy_name"), t("mods.copy_name_done"))

    def _add(self):
        inst = self._target()
        if inst is None:
            toast(self, t("common.hint"), t("mods.add_hint"))
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
        # round-44 补全：add_btn / update_btn 文本刷新
        if hasattr(self, "add_btn"):
            self.add_btn.setText(t("mods.add"))
        if hasattr(self, "update_btn"):
            self.update_btn.setText(t("mods.check_updates"))
        self.refresh()


# ---------------------------------------------------------------- mrpack import
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
        self.mgr._persist(inst)
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
        # round-40 P2-11：安装失败时移除刚创建的空实例（含空目录），
        # 避免"脏实例"永久留在列表（各主流启动器均为成功后才注册）。
        try:
            inst = getattr(self, "_inst", None)
            if inst is not None:
                self.mgr.remove(inst.id)
                import shutil
                shutil.rmtree(inst.root, ignore_errors=True)
                self._inst = None
        except Exception:
            pass
        self.cancel_btn.setText(t("common.close"))
        self.ok_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
