"""Instance management pages: instance list/details + mods page.

Contains:
- InstanceCard      compact instance row used in the old list layout
- _InstRow          compact row for the new left-side instance list
- loader cards      统一用 src/loader_picker.py（round-196 合并）
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
    QFileDialog,
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QIcon, QTransform

from .theme import COLORS, RoundedCard, with_alpha, loader_vivid
from .os_open import open_local_path
from .effects import LightTrailCard, fade_in_widget  # round-50 卡片混合：实例详情卡流光；round-100 列表淡入
from .ui_flow import FlowLayout, FlowGrid  # round-243：按宽度自动换行，避免窄窗口把卡片撑爆
from . import ui_kit
from .icons import icon, on_accent
from .frameless import FramelessHelper, TitleBar
from .win_rounded import confirm, pick_files, info, warn, toast
from .i18n import t, loader_name
from . import instance_art
from .instances import (sorted_instances, manager, Instance, LOADERS,
                       detect_format, launcher_label)
from .net_api import fetch_versions
from .settings_dialog import load_config
from .worker import Worker
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


def _loader_badge(text: str, loader_id: str) -> "QLabel":
    """加载器徽章：默认中性 ``badge`` 类；主题包 loader_vivid 时走品牌色。"""
    from PySide6.QtWidgets import QLabel
    b = QLabel(text)
    if loader_vivid():
        b.setStyleSheet(
            _badge_style(LOADER_BADGE.get(loader_id, LOADER_BADGE["vanilla"])))
    else:
        b.setProperty("cls", "badge")
    return b


# round-82 启动格式徽章配色（与来源 launcher 徽章区分，见 detect_format）。
FORMAT_BADGE = {
    "auto":      "#8B5CF6",   # 自适应紫
    "ac":        "#7C3AED",   # AC 自有布局（品牌紫）
    "vanilla":   "#22C55E",   # 原版绿
    "iso":       "#F59E0B",   # 隔离橙
    "multimc":   "#3B82F6",   # 整合蓝
    "curseforge": "#EC4899",  # CurseForge 粉
    "modrinth":  "#14B8A6",   # Modrinth 青
    "pcl":       "#0EA5E9",   # PCL2 天蓝（round-183）
    "custom":    "#6B7280",   # 自定义灰
}

_fmt_keys = {  # format 值 → i18n key（label/tooltip 共用前缀）
    "auto": "instances.fmt_auto",
    "ac": "instances.fmt_ac",
    "vanilla": "instances.fmt_vanilla",
    "iso": "instances.fmt_iso",
    "multimc": "instances.fmt_multimc",
    "curseforge": "instances.fmt_curseforge",
    "modrinth": "instances.fmt_modrinth",
    "pcl": "instances.fmt_pcl",
    "custom": "instances.fmt_custom",
}


def _fmt_badge(inst) -> "QLabel":
    """构造格式徽章：自适应时显示实时探测结果，tooltip 说明"格式=磁盘布局"。"""
    from PySide6.QtWidgets import QLabel
    fmt = detect_format(inst)
    key = _fmt_keys.get(fmt, "instances.fmt_auto")
    b = QLabel(t(key))
    if loader_vivid():
        b.setStyleSheet(_badge_style(FORMAT_BADGE.get(fmt, FORMAT_BADGE["auto"])))
    else:
        b.setProperty("cls", "badge")
    b.setToolTip(t("instances.fmt_tooltip"))
    b.setCursor(Qt.PointingHandCursor)
    return b


def version_channel(title: str) -> str:
    """round-180：从上游版本标题识别渠道，识别不了返回 ``unknown``。

    ☠ 不假造：上游 API 大多只给版本字符串（Forge / Fabric / Quilt 都是纯
    版本号），这时一律 ``unknown``、不加角标，绝不把「没标记」当成稳定版。
    """
    low = str(title or "").lower()
    if any(k in low for k in ("beta", "preview", "snapshot", "alpha",
                              "pre-release", "prerelease", "-rc", "测试", "预览")):
        return "beta"
    if any(k in low for k in ("stable", "release", "recommended", "推荐", "稳定")):
        return "stable"
    return "unknown"


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
                {"title": h["title"], "meta": h.get("_loader_version", ""),
                 "channel": version_channel(h["title"])}
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
                {"title": b["title"], "meta": b.get("_version", ""),
                 "channel": version_channel(b["title"])}
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
                {"title": b["title"], "meta": b.get("_installer_url", ""),
                 "channel": version_channel(b["title"])}
                for b in fetch_cleanroom_builds()
            ]
        except Exception:
            return []
    if loader == "optifine":
        from .net_api import fetch_optifine_versions
        try:
            return [
                {"title": v["title"], "meta": v.get("_filename", ""),
                 "channel": version_channel(v["title"])}
                for v in fetch_optifine_versions(mc_version)
            ]
        except Exception:
            return []
    # forge / neoforge via minecraft-launcher-lib
    try:
        from minecraft_launcher_lib.mod_loader import Forge, Neoforge
        if loader == "forge":
            return [
                {"title": v["version"], "meta": v["version"],
                 "channel": version_channel(v["version"])}
                for v in Forge.forge_versions(mc_version)
            ]
        if loader == "neoforge":
            # ☠ round-186：原来直接 get_loader_versions() —— 那是**所有 MC 版本**
            # 的 NeoForge 版本（20.1.x / 20.4.x / 21.x 混在一起）。选 1.20.1 的
            # 实例能在下拉里看到 21.x，装上去必崩。按版本号前缀裁掉。
            from .core.loader_catalog import filter_neoforge
            raw = [v["version"] for v in Neoforge.get_loader_versions()]
            return [
                {"title": v, "meta": v, "channel": version_channel(v)}
                for v in filter_neoforge(raw, mc_version)
            ]
    except Exception:
        pass
    # quilt via minecraft-launcher-lib（round-68 补齐分支）
    try:
        from minecraft_launcher_lib.mod_loader import Quilt
        if loader == "quilt":
            return [
                {"title": v, "meta": v, "channel": version_channel(v)}
                for v in Quilt().get_loader_versions(mc_version, True)
            ]
    except Exception:
        pass
    # fabric / quilt：走官方 meta 的**按 MC 版本**接口
    # ☠ round-186：原来用 mll 的 get_all_loader_versions()，返回的是 Fabric
    # 全历史构建（0.4.x 到最新），不看 MC 版本 —— 下拉里会冒出装不上的旧版。
    if loader in ("fabric", "quilt"):
        from .net_api import fetch_loader_builds
        try:
            return [
                {"title": b["title"], "meta": b["meta"],
                 "channel": version_channel(b["title"])}
                for b in fetch_loader_builds(mc_version, loader)
            ]
        except Exception:
            # 网络失败：退回 mll 的全量列表（至少能手动输版本），不静默空
            pass
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
        # round-190：自定义图标优先（圆角），没有再用默认字形
        _pm = instance_art.icon_pixmap(getattr(inst, "icon_path", ""), 40,
                                       radius=9)
        icon_box.setPixmap(_pm if _pm is not None
                           else icon("instances").pixmap(24, 24))
        lay.addWidget(icon_box)

        # ── info column: name + (version pill · loader badge) ──
        info = QVBoxLayout()
        info.setSpacing(6)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = ui_kit.ElidedLabel(inst.name)
        name.setProperty("cls", "title")
        name_row.addWidget(name)
        if getattr(inst, "favorite", False):
            star = QLabel("★")
            star.setStyleSheet("color:%s;font-size:13px;"
                               % COLORS["accent"])
            star.setToolTip(t("inst.favorite"))
            name_row.addWidget(star)
        name_row.addStretch(1)
        info.addLayout(name_row)

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

        self._icon_box = QLabel()
        self._icon_box.setFixedSize(32, 32)
        self._icon_box.setAlignment(Qt.AlignCenter)
        self._icon_box.setProperty("cls", "tile")
        lay.addWidget(self._icon_box)
        self._apply_icon()

        col = QVBoxLayout()
        col.setSpacing(2)
        self.nm = ui_kit.ElidedLabel(inst.name)
        self.nm.setProperty("cls", "title")
        # round-100：字色交给 title 类（内联色不随主题切换刷新）
        self.nm.setStyleSheet("font-size: 13px;")
        # ElidedLabel handles elision internally; WordWrap not needed
        col.addWidget(self.nm)
        self.sub = QLabel(f"{inst.game_version or '?'}  ·  {loader_name(inst.loader)}")
        self.sub.setProperty("cls", "sub")
        self.sub.setStyleSheet("font-size: 11px;")
        col.addWidget(self.sub)
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

    def _apply_icon(self):
        """round-243：列表行显示玩家自选的实例图标。

        这里原本写死 `icon("instances")`——不管玩家在编辑器里换没换图标，左侧
        列表永远是那颗默认矢量图，看起来就像"自定义图标没做"。空路径/读不出
        图时回落到默认图标（`icon_pixmap` 返回 None 即代表回落）。
        """
        pm = instance_art.icon_pixmap(
            getattr(self.inst, "icon_path", ""), 28, radius=8)
        if pm is None:
            self._icon_box.setPixmap(icon("instances").pixmap(18, 18))
        else:
            self._icon_box.setPixmap(pm)

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
        elif kind == "paused":
            # round-170：暂停中的下载既不是「下载中」也不是「就绪」。
            self._task_lbl.setText(t("instances.task_paused", pct=pct))
            self._task_lbl.setStyleSheet(
                f"font-size: 11px; color: {COLORS['warn']};")
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
        """round-38 性能：更新 ✓ 标签而不重建行（快切卡顿优化）。
        同步更新实例名称、版本、加载器（编辑保存后同步）。
        """
        self._cur_tag.setVisible(is_current)
        self.nm.setText(self.inst.name)
        self.sub.setText(f"{self.inst.game_version or '?'}  ·  {loader_name(self.inst.loader)}")
        self._apply_icon()   # round-243：编辑器换过图标后增量刷新也要跟上

    def mousePressEvent(self, e):
        self.clicked.emit(self.inst.id)
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        # round-42 右键菜单（对齐主流鼠标流）：on_menu(inst, global_pos)
        if self._on_menu is not None:
            self._on_menu(self.inst, e.globalPos())
        e.accept()


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

    # round-165 起 result_data() 返回 7 元组（末尾新增 format / base，用于
    # 玩家自选已有游戏目录）。信号必须同步扩到 7 参：PySide6 对超参 emit
    # 直接抛 TypeError，而 Qt 槽里的异常只会被 sys.excepthook 写进 crash.log，
    # 界面表现为「点创建毫无反应」（2026-11-06 真机复现 15 次）。
    created = Signal(str, str, str, str, str, str, str)  # name, version, loader, java_path, loader_version, fmt, base
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
        self._loader_cards: dict[str, object] = {}
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
            # round-145 ④：嵌入式向导是一块贴在壁纸上的白底面板（背景来自
            # 全局 QDialog 规则），没有 DWM 窗口圆角可用 → 直角白框很突兀。
            # 控件级 QSS 只加 radius（底色仍走全局 token，随主题刷新）；子页
            # 在壁纸模式下透明，四角圆角可见。
            self.setStyleSheet("QDialog { border-radius: 14px; }")

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

        # round-46：新建实例先显示 loading 占位，
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
        # 版本折叠成「显示全部 N 个」按钮，需玩家手动点开；
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
            hdr = ui_kit.group_label(t(f"versions.group.{g}"))
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
        # round-129：同上，按当前窗口 DPR 渲染，避免多屏缩放拿错尺寸。
        tile.setPixmap(make_version_pixmap(ver_id, vtype, 48,
                                           self.devicePixelRatioF()))
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
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # round-143 修复「选非默认加载器后卡片互相重叠」：内容高度超出容器时
        # QGridLayout 会把行高压缩到卡片固定高度(82)以下 → 上下行卡片重叠
        # 28~73px（实测 760x560 选 cleanroom 即触发：加载器版本行一出现，
        # 总高超限）。改为内容整体进 QScrollArea —— 高度不足时滚动，绝不压缩
        # 卡片；footer 固定在页底不随滚动。
        content = QWidget()
        lay = QVBoxLayout(content)
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
        # round-196：加载器卡片**只有一套**（src/loader_picker.py）——
        # 原来这里还有一份 pages_instances._LoaderCard，与实例编辑「修改」页的
        # 卡片长得不一样（logo 大小、选中反馈、描述文案都不同）。
        cols = 3
        ui_loaders = [l for l in LOADERS if l != "vanilla"]
        # round-68 设置开关：show_quilt=False 时新建实例页不出现 Quilt 卡片
        if not load_config().get("show_quilt", True):
            ui_loaders = [l for l in ui_loaders if l != "quilt"]
        from .loader_picker import LoaderCard as _LCard
        for i, loader_id in enumerate(ui_loaders):
            card = _LCard(self, loader_id, loader_name(loader_id),
                          t(_LOADER_DESC.get(loader_id,
                                             "new_instance.ld_vanilla")))
            card.picked.connect(self._select_loader)
            self._loader_cards[loader_id] = card
            self._loader_grid.addWidget(card, i // cols, i % cols)
        # LabyMod is not installable in-app; keep it as a link card
        labymod_card = _LCard(self, "labymod", loader_name("labymod"),
                              t(_LOADER_DESC.get("labymod",
                                                 "new_instance.ld_labymod")))
        labymod_card.picked.connect(self._select_loader)
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
        ldver_title = ui_kit.group_label(t("new_instance.loader_version"))
        ldver_lay.addWidget(ldver_title)
        self.ldver_combo = QComboBox()
        self.ldver_combo.setMinimumHeight(36)
        self.ldver_combo.addItem(t("new_instance.ldver_latest"))
        self.ldver_combo.setToolTip(t("new_instance.ldver_hint"))
        ldver_lay.addWidget(self.ldver_combo)
        self.ldver_box = ldver_box
        lay.addWidget(ldver_box)

        # Java
        java_title = ui_kit.group_label(t("new_instance.java_section"))
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

        # round-165：下载实例允许玩家自选布局（写盘位置）。
        # AC 独立目录 = 原行为；其余选项写入玩家指选的已有游戏目录
        # （external 实例，删除实例不会动真实文件）。
        # round-183：补 "pcl" —— 直接写进 PCL2 的 .minecraft，格式标成 pcl，
        # 这样「各种启动器的实例」在新建阶段就选得出来、看得见。
        dir_title = ui_kit.group_label(t("new_instance.dir_section"))
        lay.addWidget(dir_title)
        self.dir_combo = QComboBox()
        self.dir_combo.setMinimumHeight(36)
        for _k in ("ac", "vanilla", "iso", "pcl", "custom"):
            self.dir_combo.addItem(t(f"new_instance.dir_{_k}"), _k)
        self.dir_combo.currentIndexChanged.connect(self._on_dir_changed)
        lay.addWidget(self.dir_combo)
        self.dir_hint = QLabel(t("new_instance.dir_hint_ac"))
        self.dir_hint.setProperty("cls", "sub")
        self.dir_hint.setWordWrap(True)
        lay.addWidget(self.dir_hint)
        # round-183：把「这个选择会标成哪种启动格式」显式写出来——玩家抱怨
        # 「新建时看不到各种格式」，此前确实一处都没显示。
        self.fmt_lbl = QLabel(t("new_instance.fmt_preview",
                                name=t("instances.fmt_ac")))
        self.fmt_lbl.setProperty("cls", "sub")
        self.fmt_lbl.setWordWrap(True)
        lay.addWidget(self.fmt_lbl)
        self.dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setMinimumHeight(36)
        self.dir_edit.setPlaceholderText(t("new_instance.dir_placeholder"))
        self.dir_edit.textChanged.connect(lambda _s: self._update_path())
        self.dir_choose = QPushButton(t("new_instance.dir_pick"))
        self.dir_choose.setMinimumHeight(36)
        self.dir_choose.clicked.connect(self._pick_dir)
        self.dir_row.addWidget(self.dir_edit, 1)
        self.dir_row.addWidget(self.dir_choose)
        self.dir_row_w = QWidget()
        self.dir_row_w.setLayout(self.dir_row)
        self.dir_row_w.setVisible(False)
        lay.addWidget(self.dir_row_w)

        # name
        name_lbl = ui_kit.group_label(t("new_instance.name"))
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)
        foot_m = QHBoxLayout()
        foot_m.setContentsMargins(24, 4, 24, 16)
        foot_m.addLayout(foot)
        outer.addLayout(foot_m)
        return page

    def _go_to_loader_page(self):
        if not self._selected_version:
            return
        # 防抖：round-29 快速连续点击会闪退。
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
            # Re-adding a widget that is still in the grid does NOT move it in
            # Qt — it leaves the old cell item in place, so two cards end up
            # drawn on top of each other (round-126: Cleanroom covering Forge).
            # Take it out of the layout first, then place it at its new cell.
            try:
                self._loader_grid.removeWidget(card)
            except (RuntimeError, TypeError):
                pass
            ok = loader_id in allowed
            card.setVisible(ok)
            if ok:
                # round-88：隐藏掉不兼容的卡后，把剩余可见卡重新按 3 列
                # 连续铺排，避免留下空洞。
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
        show_ldver = loader_id not in ("vanilla", "optifine", "labymod")
        # round-180：重复点同一张卡不该再发一次网络请求、再重建一次下拉
        if (getattr(self, "_loader", "") == loader_id
                and getattr(self, "_ldver_visible", False) == show_ldver
                and (not show_ldver
                     or getattr(self, "_ldver_loaded_for", "") == loader_id)):
            return
        self._loader = loader_id
        self._ldver_visible = show_ldver
        for lid, card in self._loader_cards.items():
            # 旧代码 `and card.isVisible()` 会让刚 show 的卡片漏掉选中态
            card.set_selected(lid == loader_id)
        # 用高度占位代替 setVisible：隐藏时保留同样的布局槽位，
        # 切换加载器不再整页跳动。
        self.ldver_box.setMaximumHeight(0 if not show_ldver else 16777215)
        if show_ldver:
            self._load_loader_versions()
        self._update_path()

    def _open_labymod(self):
        """Download the official LabyMod installer in-app and start it.

        There is no standalone Forge mod jar to drop into ``mods/``: LabyMod 4
        is distributed only through its installer, which writes the client jar
        plus a dedicated version JSON. We still avoid the browser detour —
        fetch the installer here and launch it (round-126 request). Non-premium
        accounts cannot get into the game, which the confirmation states.
        """
        if getattr(self, "_lm_worker", None) is not None and self._lm_worker.isRunning():
            toast(self, t("common.hint"), t("new_instance.labymod_busy"))
            return
        if not confirm(self, t("new_instance.labymod_title"),
                       t("new_instance.labymod_confirm")):
            return
        from .paths import get_data_dir
        from .net_api import download_labymod_installer
        dest_dir = os.path.join(get_data_dir(), "downloads")
        self._lm_worker = Worker(download_labymod_installer, dest_dir)
        self._lm_worker.finished.connect(self._on_labymod_downloaded)
        self._lm_worker.error.connect(self._on_labymod_error)
        self._lm_worker.start()

    def _on_labymod_downloaded(self, path: str):
        try:
            os.startfile(path)  # noqa: S606 - official installer, Windows only
        except OSError as e:
            warn(self, t("new_instance.labymod_title"),
                 t("new_instance.labymod_fail", err=str(e)))
            return
        info(self, t("new_instance.labymod_title"),
             t("new_instance.labymod_started", path=path))

    def _on_labymod_error(self, msg: str):
        warn(self, t("new_instance.labymod_title"),
             t("new_instance.labymod_fail", err=msg))

    # ---------------- loader versions ----------------
    def _load_loader_versions(self):
        mc = self._selected_version
        loader = self._loader
        cache = getattr(self, "_ldver_cache", None)
        if cache is None:
            cache = self._ldver_cache = {}
        key = (mc, loader)
        self.ldver_combo.blockSignals(True)
        self.ldver_combo.clear()
        if key in cache:
            self._on_loader_versions(cache[key])  # 内部会填默认项 + 列表
            self._ldver_loaded_for = loader
            self.ldver_combo.blockSignals(False)
            return
        self.ldver_combo.addItem(t("new_instance.ldver_latest"))
        self.ldver_combo.blockSignals(False)
        gen = getattr(self, "_ldver_gen", 0) + 1
        self._ldver_gen = gen
        self._ldver_worker = Worker(_fetch_loader_versions, mc, loader)

        def _done(versions: list[dict], g=gen):
            if getattr(self, "_ldver_gen", 0) != g:
                return
            cache[key] = versions or []
            self._ldver_loaded_for = loader
            self._on_loader_versions(versions)

        def _err(_e, g=gen):
            if getattr(self, "_ldver_gen", 0) != g:
                return

        self._ldver_worker.finished.connect(_done)
        self._ldver_worker.error.connect(_err)
        self._ldver_worker.start()

    def _on_loader_versions(self, versions: list[dict]):
        rows = [v for v in (versions or []) if isinstance(v, dict)]
        self.ldver_combo.blockSignals(True)
        self.ldver_combo.clear()
        # ☠ round-198：空列表时原来照样加一条「最新稳定版（推荐）」—— 玩家
        # 选了它，装的时候才发现这个 MC 版本根本没有该加载器的版本。
        # 现在：写明"没有可用版本"并禁用下拉。
        if not rows:
            self.ldver_combo.addItem(t("inst.loader_ver_empty_item"), "")
            self.ldver_combo.setCurrentIndex(0)
            self.ldver_combo.setEnabled(False)
            self.ldver_combo.blockSignals(False)
            # 向导里没有独立的 MC 版本输入框（版本来自版本列表页）→
            # 没有 mc 就不写空提示，避免出现" 没有这个加载器的可用版本"。
            mc = getattr(self, "_current_mc", "") or ""
            if mc and hasattr(self, "ldver_hint"):
                self.ldver_hint.setText(t("inst.loader_ver_none", mc=mc))
            return
        self.ldver_combo.setEnabled(True)
        # round-180：默认项把「会装哪个版本」写清楚，不再只有一句
        # 「最新稳定版（推荐）」让玩家盲选。
        first = (rows[0].get("title") if rows else "") or ""
        label = (t("new_instance.ldver_latest_ver", ver=first)
                 if first else t("new_instance.ldver_latest"))
        self.ldver_combo.addItem(label, "")
        for v in rows:
            title = v.get("title") or ""
            ch = v.get("channel") or version_channel(title)
            if ch == "beta":
                title = title + "  ·  " + t("new_instance.ldver_beta")
            elif ch == "stable":
                title = title + "  ·  " + t("new_instance.ldver_stable")
            # ch == "unknown" 时不加任何角标：不假造稳定性
            self.ldver_combo.addItem(title, v.get("meta") or "")
        self.ldver_combo.blockSignals(False)

    def selected_loader_version(self) -> str:
        # round-180：ldver_box 现在用高度占位隐藏（isVisible 仍为 True），
        # 必须改用显式标志，否则 vanilla/optifine 会误选到加载器版本。
        if not getattr(self, "_ldver_visible", False):
            return ""
        return self.ldver_combo.currentData() or ""

    # ---------------- java ----------------
    def _on_java_default(self, on: bool):
        self.java_row_w.setVisible(not on)
        if on:
            self._java_path = ""
            self.java_path_lbl.setText("")

    def _choose_java(self):
        """选 Java 可执行文件（round-197）。

        原来这里弹的是**完整的 Java 管理器**（扫描/下载/删除一整套）—— 但向导
        只需要"选一个 java.exe"。而 Java 管理器在设置页里（唯一入口）。
        这里改成**文件选择器**：场景对、重量轻，也消掉了一个重复入口。
        """
        from .win_rounded import pick_files
        path = pick_files(self, t("new_instance.java_pick_title"), "",
                          "Java (*.exe)")
        if path:
            self._java_path = path
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

    # ---------------- round-165：自选下载布局 ----------------
    def _on_dir_changed(self, *_args):
        key = self.dir_combo.currentData() or "ac"
        self.dir_row_w.setVisible(key != "ac")
        self.dir_hint.setText(t(f"new_instance.dir_hint_{key}"))
        # round-183：显式展示「这次新建会标成哪种启动格式」
        self.fmt_lbl.setText(t(
            "new_instance.fmt_preview", name=t(f"instances.fmt_{key}")))
        self._update_path()

    def _pick_dir(self):
        key = self.dir_combo.currentData() or "ac"
        start = self.dir_edit.text().strip() or ""
        path = QFileDialog.getExistingDirectory(
            self, t(f"new_instance.dir_pick_title_{key}"), start)
        if path:
            self.dir_edit.setText(os.path.normpath(path))

    def current_layout(self) -> tuple[str, str]:
        """当前选择的 (format, base)。base 为空 ⇒ 走 AC 自有布局。

        vanilla = 玩家指选的已有 .minecraft；iso = 指选 .minecraft，实例目录
        自动定位到 versions/<版本>；pcl = 指选 PCL2 的 .minecraft（格式标 pcl）；
        custom = 指选的游戏目录本体。
        """
        fmt = self.dir_combo.currentData() or "ac"
        if fmt == "ac":
            return "ac", ""
        raw = self.dir_edit.text().strip()
        if not raw or not os.path.isdir(raw):
            return fmt, ""
        root = os.path.normpath(raw)
        if fmt == "iso":
            ver = self._selected_version.strip() or "1.20.1"
            return "iso", os.path.join(root, "versions", ver)
        return fmt, root

    def _update_path(self):
        name = self.name_edit.text().strip()
        auto = self._auto_name()
        if not name:
            self.name_edit.setPlaceholderText(auto)
        else:
            self.name_edit.setPlaceholderText(t("new_instance.name_placeholder"))
        fmt, base = self.current_layout()
        if fmt != "ac":
            self.path_lbl.setText(t("new_instance.save_to",
                                     path=base or t("new_instance.dir_none")))
            return
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
        fmt, base = self.current_layout()
        if fmt != "ac" and not base:
            warn(self, t("new_instance.dir_title"), t("new_instance.dir_missing"))
            return
        if self._embedded:
            self.created.emit(*self.result_data())
        else:
            self.accept()

    def result_data(self) -> tuple[str, str, str, str, str, str, str]:
        name = self.name_edit.text().strip()
        if not name:
            name = self._auto_name()
        fmt, base = self.current_layout()
        return (name, self._selected_version, self._loader, self._java_path,
                self.selected_loader_version(), fmt, base)


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
    # round-243：实例字段被就地改动（图标 / 收藏），需要首页等其它页面同步刷新
    instance_updated = Signal(str)
    # round-107 T8：页面内新建实例后上报 id，由 MainWindow 统一发起后台下载。
    instance_created = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # round-244 P0：dragEnterEvent/dropEvent 从 round-42 就有，但从来没人
        # 调 setAcceptDrops(True) —— Qt 默认拒收，拖整合包进窗口永远没反应。
        self.setAcceptDrops(True)
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
        # round-195/196：页内功能栈（编辑 / 体检 / 增强包 / 导出）的页索引栈
        self._feature_stack: list[int] = []
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
        self.trash_btn = self._mk_header_btn(
            t("instances.trash_title"), "delete", self._open_trash, w=80, accent=False)
        head_actions = QWidget()
        self._head_actions = head_actions   # round-195：功能页时隐藏（新建/扫描/导入包会跳走）
        head_actions.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(head_actions)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        hl.addWidget(self.new_btn)
        hl.addWidget(self.scan_btn)
        hl.addWidget(self.mrpack_btn)
        hl.addWidget(self.trash_btn)
        # round-107 收起键重做：原按钮随列表一起折叠 → 位置来回跳动。
        # 改为一颗**常驻页头**的图标按钮：无论列表
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
        # We use a QStackedWidget for the body so only one view is ever visible.
        # 固定页索引约定（round-243 修正，勿再插入）：
        #   0 = 空状态   (还没有实例)
        #   1 = 分栏视图 (左列表 + 右详情)   ← _refresh 唯一会切回的页
        #   2 = 回收站
        #   3+ = 动态挂载的功能页（新建向导 / 扫描 / 编辑 / 体检 / 导出…）
        # ☠ round-243：这里曾经把 split view **创建了两遍**，第二份带着真正的
        #   数据被 addWidget 成 index 3，而 _refresh 只切 index 1（空壳）→
        #   整个实例页看起来一片空白。只允许存在一份，任何"再建一次"都是坑。
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
        self.list_lbl = ui_kit.group_label(t("instances.list_title"))
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

        body.addWidget(self._splitter, stretch=1)
        self._body_stack.addWidget(self._split_view)

        # page 2: trash
        self._trash_page = self._trash_state()
        self._body_stack.addWidget(self._trash_page)

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
        # round-190：收藏的排最前面（sorted_instances 里统一这条规则）
        insts = sorted_instances(self.mgr.list())
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

    # ia[instances]: 点左侧实例行 | 实例列表 | 右侧详情切换到该实例
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
        # round-243：详情卡左侧加实例图标（44px 圆角）。没设图标时退回默认
        # tile + 矢量图标，与列表行保持同一套回落规则。
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(44, 44)
        icon_lbl.setAlignment(Qt.AlignCenter)
        _ipm = instance_art.icon_pixmap(
            getattr(inst, "icon_path", ""), 44, radius=11)
        if _ipm is None:
            icon_lbl.setProperty("cls", "tile")
            icon_lbl.setPixmap(icon("instances").pixmap(24, 24))
        else:
            icon_lbl.setPixmap(_ipm)
        icon_lbl.setToolTip(t("inst.pick_icon"))
        name_row.addWidget(icon_lbl)
        nm = ui_kit.ElidedLabel(inst.name)
        nm.setProperty("cls", "big")
        nm.setStyleSheet("font-size: 20px;")
        # ☠ round-243：ElidedLabel 的水平策略是 Ignored（它靠"绝不用文本宽度
        # 顶布局"来防溢出），而这一行末尾又有 addStretch(1)——两者相遇时布局
        # 把多余空间全给了 spacer，标签拿到 **0 宽**：详情卡里实例名字整个
        # 消失（实测 w=0 / sizeHint=260）。必须给它 stretch 才能分到宽度。
        name_row.addWidget(nm, 1)
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
        # round-200：主按钮从混装的「体检 / 启动诊断」换成「编辑实例」——
        # 出问题才用的诊断类操作全部下沉到下方「管理与诊断」一级网格。
        # ia[instances]: 点「编辑实例」 | 详情名称行主按钮 | 页内打开编辑面板（换版本/加载器/内存/模组）
        edit_btn = QPushButton(t("instances.edit_instance"))
        edit_btn.setProperty("cls", "accent")
        edit_btn.setMinimumHeight(36)
        edit_btn.setIcon(on_accent("settings"))
        edit_btn.setIconSize(QSize(16, 16))
        edit_btn.clicked.connect(lambda: self._edit_instance_settings(inst))
        name_row.addWidget(edit_btn)
        lay.addLayout(name_row)

        # badges: version pill · loader badge · format badge (round-82) · java
        # round-243：QHBoxLayout → FlowLayout。原来一行徽章的最小宽度是**所有
        # 徽章之和**（实测 524px：版本 99 + 加载器 97 + 布局 196 + 加载器版本
        # 108），窗口收窄到 900（应用最小宽）时详情区只有 369px → 整张卡溢出
        # 211px 被硬裁。换成流式后宽度不够自动换行，卡片下限退化成最宽那颗。
        meta = FlowLayout(h_spacing=8, v_spacing=8)
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
        lay.addLayout(meta)

        # ── 路径（round-124）──
        # QFormLayout 只按 wordWrap 标签的「单行 sizeHint」分配行高（Qt 已知
        # 限制），长 mc_dir 因此被裁到只剩盘符。改由纵向布局承载——
        # QWidget + QVBoxLayout 会正确走 heightForWidth，完整路径才能换行展开。
        path_box = QWidget()
        path_lay = QVBoxLayout(path_box)
        path_lay.setContentsMargins(0, 0, 0, 0)
        path_lay.setSpacing(6)
        path_cap = QLabel(t("instances.detail_path"))
        path_cap.setProperty("cls", "sub")
        path_lay.addWidget(path_cap)
        path_lay.addWidget(self._mono(inst.mc_dir))
        lay.addWidget(path_box)

        # info grid
        grid = QFormLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        grid.setLabelAlignment(Qt.AlignRight)
        # 字段列伸展填满详情面板宽度，长路径不再被压成一行截断
        grid.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        # round-124：AC 自己的实例没有「来源启动器」可显示，空值行会留下
        # 一个 8×19 的空白 label，直接不插入该行。
        src_text = launcher_label(inst.launcher, show_original=True)
        if src_text:
            grid.addRow(QLabel(t("instances.detail_source")), QLabel(src_text))
        if inst.created_at:
            grid.addRow(QLabel(t("instances.detail_created")),
                        QLabel(inst.created_at))
        if inst.version_id and inst.version_id != inst.game_version:
            grid.addRow(QLabel("ID"), self._mono(inst.version_id))
        lay.addLayout(grid)

        # ── 管理与诊断（round-200：一级入口）──
        # 体检 / 崩溃分析原来埋在「⋯ 更多」里，
        # 备份 / 还原 / 复制只存在于右键菜单（详情页根本看不到）。
        # 改为按用途分组的一级网格：上排全是"查问题 / 修问题"，下排是实例数据操作。
        # ia[instances]: 点「实例体检」 | 详情「管理与诊断」网格 | 页内体检面板（静态扫描 + 一键本地修复）
        # ia[instances]: 点「崩溃分析」 | 详情「管理与诊断」网格 | 页内崩溃分析面板（崩溃原因 + 修复建议）
        # ia[instances]: 点「启动诊断」 | 详情「管理与诊断」网格 | 页内面板：启动命令 / classpath / 体检摘要
        # ia[instances]: 点「补装依赖」 | 详情「管理与诊断」网格 | 扫描缺失前置并自动安装（后台 Worker）
        # ia[instances]: 点「创建备份」 | 详情「管理与诊断」网格 | 后台打包实例快照到备份目录
        # ia[instances]: 点「回滚备份…」 | 详情「管理与诊断」网格 | 选历史快照，二次确认后恢复 mods / config / 存档
        # ia[instances]: 点「复制实例」 | 详情「管理与诊断」网格 | 输入新名后后台克隆实例目录
        lay.addWidget(ui_kit.group_label(t("instances.manage_group")))
        mgmt = [
            ("health.title", "tools", lambda: self._health_check(inst)),
            ("instances.crash_analyze", "crash",
             lambda: self._show_crash(inst)),
            ("instances.launch_diag", "console",
             lambda: self._show_launch_diag(inst)),
            ("instances.repair_deps_short", "download",
             lambda: self._repair_mod_deps(inst)),
            ("instances.backup", "export", lambda: self._backup(inst)),
            ("instances.restore", "refresh", lambda: self._restore(inst)),
            ("instances.duplicate", "add", lambda: self._duplicate(inst)),
            ("instances.open_folder", "folder",
             lambda: self._open_folder(inst)),
        ]
        # round-243：4 列 QGridLayout（最小 502px）→ FlowGrid。列数按宽度算：
        # 宽窗口 4 列、900px 最小窗口自动 2 列，不再有"写死列数 = 写死下限"。
        mgmt_grid = FlowGrid(h_spacing=8, v_spacing=8, min_item_width=104,
                             max_cols=4)
        for label_key, ico, slot in mgmt:
            b = QPushButton(t(label_key))
            b.setMinimumHeight(40)
            b.setIcon(icon(ico))
            b.setIconSize(QSize(15, 15))
            b.clicked.connect(lambda _c=False, f=slot: f())
            mgmt_grid.addWidget(b)
        lay.addLayout(mgmt_grid)

        # ── 底部行：设为当前 / 更多（低频） / 删除 ──
        actions = QHBoxLayout()
        actions.setSpacing(8)
        cur_btn = QPushButton(t("instances.set_current"))
        cur_btn.setMinimumHeight(34)
        cur_btn.setIcon(icon("check"))
        cur_btn.setIconSize(QSize(15, 15))
        cur_btn.setEnabled(inst.id != self.mgr.current_id)
        cur_btn.clicked.connect(lambda: self._set_current(inst.id))
        actions.addWidget(cur_btn)

        actions.addStretch(1)

        # ── 更多操作 ──
        # ☠ 别再用文字「⋯」：① 它依赖字体回退（U+22EF 不在雅黑里，缺字时是豆腐块）；
        # ② QPushButton 带菜单时 Qt 还会在文字旁再画一个 ⌄，30px 的小方钮里挤成
        # 「⋯⌄」两个符号。改用 SVG 图标 + 隐藏 menu-indicator。
        more_btn = QPushButton()
        more_btn.setToolTip(t("instances.more_actions"))
        more_btn.setFixedSize(34, 34)
        more_btn.setIcon(icon("more"))
        more_btn.setIconSize(QSize(18, 18))
        more_btn.setCursor(Qt.PointingHandCursor)
        more_btn.setProperty("cls", "surface")
        _more_menu = QMenu(more_btn)
        # round-200：只剩低频项。体检 / 崩溃分析已升为上方网格一级入口。
        for key, ico, slot in [
            # round-42：打开存档目录
            (t("instances.open_saves"), "folder", (lambda: self._open_saves(inst))),
            # round-38 中轴：把整合包应用到已有实例（二次安装/升级）
            (t("instances.apply_pack"), "download", (lambda: self._apply_mrpack_to(inst))),
            # round-166：按磁盘现状重构实例定义（版本/加载器/布局重新推导）
            (t("instances.rebuild"), "refresh",
             (lambda: self._rebuild_instance(inst))),
            # round-184：导出成 Modrinth 整合包（.mrpack）
            (t("instances.export_pack"), "export",
             (lambda: self._export_pack(inst))),
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
        sec_title = ui_kit.group_label(t("instances.sections"))
        lay.addWidget(sec_title)
        sec_grid = FlowGrid(h_spacing=10, v_spacing=10, min_item_width=120,
                            max_cols=4)
        sections = [
            ("mods",      "instances.sec_mods",      "mods"),
            ("respack",   "instances.sec_respacks",  "resourcepack"),
            ("shaders",   "instances.sec_shaders",   "shader"),
            ("saves",     "instances.sec_saves",     "folder"),
        ]
        for key, label_key, ico in sections:
            b = QPushButton(t(label_key))
            b.setMinimumHeight(44)
            b.setIcon(icon(ico))
            b.setIconSize(QSize(16, 16))
            b.clicked.connect(
                lambda _c=False, k=key: self.section_requested.emit(k, inst.id))
            sec_grid.addWidget(b)
        lay.addLayout(sec_grid)

        self.detail_lay.addWidget(card)
        self.detail_lay.addStretch(1)

    @staticmethod
    def _mono(text: str) -> QLabel:
        # round-44 路径完整展示：wordWrap + ToolTip + 可选中复制
        lbl = QLabel(text)
        # round-120：路径用 text_main（text_sub 在 bg_input 上对比不足，真机
        # 截图里盘符后的内容几乎看不清）。
        lbl.setStyleSheet(
            f"color: {COLORS['text_main']}; font-family: Consolas, monospace; "
            f"font-size: 12px; background: {COLORS['bg_input']}; "
            f"border-radius: 6px; padding: 4px 10px;"
        )
        lbl.setWordWrap(True)
        # ☠ round-243：QLabel 开了 wordWrap 之后 minimumSizeHint() 仍然按**最长
        # 不可断片段**算宽度。Windows 路径（`C:\Users\...\.minecraft`）整串没有
        # 空格 → 最小宽度 ≈ 整串像素宽（实测 920px）→ 顺着 QVBoxLayout 撑大整张
        # 详情卡（976px），而 QScrollArea 视口只有 ~549px 且横向滚动条关闭 →
        # 卡片右侧被硬裁掉：4 列按钮只剩 2.5 列、分区入口全被切。
        # 横向策略设 Ignored：布局不再参考它的 sizeHint，直接给满可用宽度；
        # wordWrap + heightForWidth 仍会按实际宽度折行显示完整路径。
        lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
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
        # round-148：尺寸与 iconSize 对齐（15），否则 QIcon 会把位图缩放一次
        # 再显示；state_pix 已按物理像素绘制并带 DPR 标记。
        pix = state_pix("chev", COLORS["text_sub"], 15)
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
        # round-183：PCL 式整页编辑（加载器真装真卸 / 模组内嵌增删）
        m.addAction(t("instances.edit_instance"),
                    lambda: self._edit_instance_settings(inst))
        # round-243：图标 / 收藏原来只能在编辑器里改，列表和右键都摸不到
        m.addAction(t("inst.pick_icon"),
                    lambda: self._pick_instance_icon(inst))
        if getattr(inst, "icon_path", ""):
            m.addAction(t("inst.reset_icon"),
                        lambda: self._reset_instance_icon(inst))
        m.addAction(t("inst.favorite_remove" if getattr(inst, "favorite", False)
                      else "inst.favorite_add"),
                    lambda: self._toggle_instance_favorite(inst))
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
        # round-178：补装依赖原来只能「先崩溃 → 崩溃弹窗」才摸得到
        m.addAction(t("instances.repair_deps"),
                    lambda: self._repair_mod_deps(inst))
        # round-182：客户端增强包（鼠标手势类 mod 一键装/卸）
        m.addAction(t("enhance.title"),
                    lambda: self._open_enhance(inst))
        m.addSeparator()
        m.addAction(t("instances.open_folder"),
                    lambda: self._open_folder(inst))
        m.addAction(t("instances.crash_analyze"),
                    lambda: self._show_crash(inst))
        m.addSeparator()
        m.addAction(t("tool.materials"),
                    lambda: self._export_materials(inst))
        m.addAction(t("preview.title"),
                    lambda: self._open_preview(inst))
        m.addAction(t("map.menu"),
                    lambda: self._open_map(inst))
        m.addSeparator()
        m.addAction(t("instances.group_move_to"),
                    lambda: self._edit_group(inst))
        m.addAction(t("common.delete"),
                    lambda: self._delete_instance(inst))
        m.exec(pos)

    # ── 图标 / 收藏（round-243：从编辑器搬到列表也能操作） ────────────
    def _after_inst_field_change(self, inst: Instance) -> None:
        """图标/收藏落盘后：刷新列表行、详情卡，并通知外层同步首页。"""
        self.mgr.save(inst)
        row = self._rows.get(inst.id)
        if row is not None:
            row.refresh_state(inst.id == self.mgr.current_id)
        if inst.id == self._selected_id:
            self._render_detail()
        self.instance_updated.emit(inst.id)

    def _pick_instance_icon(self, inst: Instance) -> None:
        from PySide6.QtWidgets import QFileDialog
        from .win_rounded import warn
        path, _f = QFileDialog.getOpenFileName(
            self, t("inst.pick_icon"), "", t("inst.icon_filter"))
        if not path:
            return
        try:
            inst.icon_path = instance_art.set_instance_icon(inst, path)
        except ValueError as exc:
            warn(self, t("inst.pick_icon"),
                 t("inst.icon_too_big") if "large" in str(exc)
                 else t("inst.icon_bad"))
            return
        self._after_inst_field_change(inst)

    def _reset_instance_icon(self, inst: Instance) -> None:
        instance_art.clear_instance_icon(inst)
        inst.icon_path = ""
        self._after_inst_field_change(inst)

    def _toggle_instance_favorite(self, inst: Instance) -> None:
        inst.favorite = not bool(getattr(inst, "favorite", False))
        self._after_inst_field_change(inst)
        # 收藏影响排序（置顶），顺序变了要重建列表
        self._refresh(switch=False)

    def _open_export_pack(self, inst: Instance):
        """导出整合包：**页内**（round-196）。

        原来实例页是弹窗、而实例编辑面板里又弹一次 —— 页内套窗口最刺眼，
        现在两处都走同一个页内栈。
        """
        from .export_pack_dialog import ExportPackPanel
        panel = ExportPackPanel(self, inst)
        panel.closed.connect(self._close_feature)
        self._push_feature(panel)

    def _open_enhance(self, inst: Instance):
        """round-182：右键「客户端增强」→ 一键装 / 卸客户端体验类 mod。

        round-195：改成**页内**（与编辑面板、体检同一套栈）。
        """
        from .enhance_dialog import EnhancePanel
        panel = EnhancePanel(self, inst)
        panel.closed.connect(self._close_feature)
        self._push_feature(panel)

    def _repair_mod_deps(self, inst: Instance):
        """round-178：右键「补装缺失依赖」→ 统一走 core.mod_repair。

        网络动作放 Worker，避免卡 UI；结果是结构化终态（成功 / 失败阶段 /
        jar 过多跳过），不再误报「依赖齐全」。
        round-209：以前全程只有模态 info/warn —— frameless 主窗口里可能弹到
        后面，表现为「点了没反应、修补没提示」。现在和另外两条一键
        修复入口共用 fix_feedback.report()（主窗口浮层 toast），并在点击瞬间
        就给出「正在处理」。
        """
        from .fix_feedback import report, summarize
        from .worker import Worker
        from .core import mod_repair

        report(self, t("fix.progress"), "busy")
        scan = mod_repair.scan_missing(inst)
        if scan["skipped"]:
            report(self, t("crash.deps_skipped", n=scan["jar_count"]), "warn")
            return
        missing = scan["missing"]
        if not missing:
            report(self, t("fix.deps_none"), "info")
            return
        report(self, t("fix.deps_start", n=len(missing)), "busy")

        def _done(result):
            ok = len(result.get("downloaded") or [])
            fail = len(result.get("failed") or [])
            text, tone = summarize(ok, fail)
            if result.get("failed"):
                text += "\n" + "\n".join(mod_repair.failed_lines(result))
            report(self, text, tone)

        self._repair_worker = Worker(mod_repair.repair_missing, inst, missing)
        self._repair_worker.finished.connect(_done)
        self._repair_worker.error.connect(
            lambda e: report(self, str(e), "warn"))
        self._repair_worker.start()

    def _duplicate(self, inst: Instance):
        """克隆实例（Worker 复制目录，防大实例卡 UI）。"""
        from .win_rounded import text_input, warn
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
        from .core.backup import list_backups, restore_backup

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
        from .win_rounded import text_input
        from .i18n import t as _t
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
        from .crash_dialog import CrashAnalyzerPanel
        panel = CrashAnalyzerPanel(inst, parent=self)
        panel.closed.connect(self._close_feature)

        # round-199：修复可能改了 mods/ 目录 → 关面板时发一次刷新信号
        # （旧实现是弹窗 exec() 返回后补发，改成页内后挪到这里）。
        def _done(_iid=inst.id):
            try:
                self.current_changed.emit(_iid)
            except Exception:  # noqa: BLE001
                pass
        panel.closed.connect(_done)
        self._push_feature(panel)

    def _show_launch_diag(self, inst: Instance):
        """启动诊断：**页内**（round-200）。

        round-177 起它是 QDialog 弹窗，而体检（round-195）/ 崩溃分析
        （round-197）都已页内化——同一类实例功能不该有窗口 / 页面两套呈现。
        """
        from .launch_diagnostics_dialog import LaunchDiagnosticsPanel
        panel = LaunchDiagnosticsPanel(inst, mgr=self.mgr, parent=self)
        panel.closed.connect(self._close_feature)
        # 「打开完整体检」在当前诊断面板之上再压一层体检面板；关闭体检后
        # 回到诊断面板（页内栈天然支持）。
        panel.open_health.connect(lambda _i=inst: self._health_check(_i))
        self._push_feature(panel)

    # ── 页内功能栈（round-195）：编辑 / 体检 / 增强包都是"页面"，不是窗口 ──
    def _push_feature(self, panel) -> None:
        """把一个功能面板压到实例页上方（页内切换，不是新开窗口）。

        round-196：改成**真正的栈** —— 导出整合包是从「实例编辑」里点进去的，
        导出完要能回到编辑面板，而不是被踢回列表。
        """
        idx = self._body_stack.addWidget(panel)
        self._feature_stack.append(idx)
        self._body_stack.setCurrentIndex(idx)
        # 页头动作（新建/扫描/导入包）在功能页里会跳走 → 先收起来
        head = getattr(self, "_head_actions", None)
        if head is not None:
            head.setVisible(False)

    def _close_feature(self) -> None:
        """收起栈顶功能面板，回到上一层（栈空则回实例列表）。"""
        stack = getattr(self, "_feature_stack", None)
        if not stack:
            return
        idx = stack.pop()
        w = self._body_stack.widget(idx)
        if w is not None:
            self._body_stack.removeWidget(w)
            w.setParent(None)
            try:
                from shiboken6 import delete as _shib_delete
                _shib_delete(w)
            except Exception:
                w.deleteLater()
        if stack:
            # 还有上一层（例：导出面板是从编辑面板进来的）→ 回上一层
            self._body_stack.setCurrentIndex(stack[-1])
            return
        self._body_stack.setCurrentIndex(1)
        head = getattr(self, "_head_actions", None)
        if head is not None:
            head.setVisible(True)

    def _open_instance_editor(self, inst: Instance) -> None:
        """实例编辑：**页内**打开（不再弹窗）。"""
        from .instance_editor import InstanceEditorPanel
        panel = InstanceEditorPanel(self, inst)
        panel.set_page_mode(True)
        panel.saved.connect(self._on_editor_saved)
        panel.versionChanged.connect(self._on_editor_version_changed)
        panel.loaderChanged.connect(lambda _i: self._refresh())
        panel.exportRequested.connect(
            lambda inst: self._open_export_pack(inst))
        panel.closed.connect(self._close_feature)
        self._push_feature(panel)

    def _on_editor_saved(self, _inst_id: str) -> None:
        self._refresh()
        self._close_feature()

    def _health_check(self, inst: Instance):
        """实例体检（N5 冲突预检的升级）：静态扫描 + **页内**报告 + 一键本地修复。

        round-195：原来是弹窗。体检是实例相关的信息，页内打开能一直看到
        "在给哪个实例体检"，也不会挡住下面的实例列表。
        修复只改实例字段并落盘保存，不联网、不动用户游戏文件。
        """
        from .core import instance_health
        from .mod_check_dialog import HealthPanel
        try:
            from .settings_dialog import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001
            cfg = None
        try:
            result = instance_health.scan_health(inst, cfg)
        except Exception as exc:  # noqa: BLE001
            warn(self, t("health.title"), str(exc))
            return
        panel = HealthPanel(self, result, mgr=self.mgr)
        panel.closed.connect(self._close_feature)
        self._push_feature(panel)

    def _mod_check(self, inst: Instance):
        """旧入口（模组冲突预检）→ 转调体检，保持兼容。"""
        self._health_check(inst)

    def _guard_running(self, inst_id: str) -> bool:
        """round-228 P0-1：删**正在运行**的实例 = 边玩边 rmtree。

        进程表由主窗按实例 id 登记（``MainWindow._game_procs``）。删之前先看一眼，
        拦下并提示；返回 True 表示调用方应当直接放弃本次删除。
        """
        win = self.window()
        procs = getattr(win, "_game_procs", None) or {}
        if inst_id not in procs:
            return False
        warn(self, t("instances.delete_title"),
             t("instances.delete_while_running"))
        return True

    def _report_delete_leftovers(self, inst, failed: list[str]) -> None:
        """round-228 P2-6：rmtree 删不掉的文件不再静默，明确告诉玩家残骸在哪。"""
        if failed:
            warn(self, t("instances.delete_title"),
                 t("instances.delete_partial", n=len(failed),
                   path=getattr(inst, "root", "") or inst.mc_dir))

    # ia[instances]: 点「删除」 | 详情底部操作行 | 二次确认后移除实例并刷新列表
    def _delete_instance(self, inst: Instance):
        from .win_rounded import confirm, toast
        if self._guard_running(inst.id):
            return
        # round-250：与列表页删除入口统一——都带上路径与"会删真实文件"警告。
        # 旧实现详情底部按钮的确认框只有一句"确认删除？"，玩家看不到
        # 会删掉哪些内容（功能分化/对外显示问题）。
        if not confirm(
            self, t("instances.delete_title"),
            t("instances.delete_confirm", name=inst.name),
            detail=t("instances.delete_path", path=inst.mc_dir)
                   + "\n\n"
                   + t("instances.delete_warn"),
        ):
            return
        failed = self.mgr.remove(inst.id)
        self._report_delete_leftovers(inst, failed)
        self._refresh()
        toast(self, t("instances.delete_title"),
              t("instances.delete_toast", name=inst.name), duration=3000)

    # ia[instances]: 点「打开文件夹」 | 详情「管理与诊断」网格 | 用系统文件管理器打开实例目录
    def _open_folder(self, inst: Instance):
        """打开实例目录（round-223：统一走 os_open，目录缺失会明确提示，
        不再像以前那样点了没反应）。"""
        open_local_path(self, inst.mc_dir)

    def _open_saves(self, inst: Instance):
        """打开存档目录（不存在则创建）。round-42 新增，round-57 修：版本隔离
        下游戏存档实际读写 <game_dir>/saves，之前固定 mc_dir/saves 打开的是
        错误目录（同 round-56 mods_dir 的脱节）。"""
        open_local_path(self, os.path.join(inst.game_dir, "saves"), create=True)

    # ── round-171 投影材料清单 / 存档地图（右侧菜单入口）──
    def _export_materials(self, inst: Instance):
        """选一个 .litematic → 后台解析 → 同目录导出 CSV 材料清单。"""
        from .win_rounded import pick_files, toast, warn
        from .core import schematic as sch_mod
        from .worker import Worker

        path = pick_files(self, t("tool.materials_title"),
                          filt=t("tool.materials_filter"))
        if not path:
            return

        def work():
            sch = sch_mod.load(path)
            out = os.path.join(os.path.dirname(path),
                               sch_mod.default_csv_name(sch))
            rows = sch_mod.export_materials_csv(sch, out)
            return rows, out, sch.total_blocks(), sch.meta_blocks, \
                sch.unknown_blocks()

        w = Worker(work)
        self._mat_worker = w

        def done(res):
            rows, out, real, meta, unknown = res
            if not rows:
                toast(self, t("tool.materials_title"), t("tool.materials_empty"))
                return
            msg = t("tool.materials_done", rows=rows, path=out)
            if unknown:
                msg += "\n" + t("tool.materials_unknown", n=unknown)
            if meta and meta != real:
                msg += "\n" + t("tool.materials_meta_warn", meta=meta, real=real)
            toast(self, t("tool.materials_title"), msg, duration=6000)

        w.finished.connect(done)
        w.error.connect(lambda e: warn(self, t("tool.materials_failed"), str(e)))
        w.start()

    def _open_preview(self, inst: Instance):
        """选 .litematic → 后台解析 → 分层预览窗口（可顺手导出材料清单）。"""
        from .win_rounded import pick_files, warn
        from .core import schematic as sch_mod
        from .worker import Worker

        path = pick_files(self, t("preview.title"),
                          filt=t("tool.materials_filter"))
        if not path:
            return
        w = Worker(sch_mod.load, path)
        self._preview_worker = w

        def done(sch):
            from .schematic_dialog import SchematicDialog
            SchematicDialog(sch, self).exec()

        w.finished.connect(done)
        w.error.connect(lambda e: warn(self, t("preview.title"), str(e)))
        w.start()

    def _open_map(self, inst: Instance):
        """打开当前实例的存档地图（只读 .mca，绝不写存档）。"""
        from .map_dialog import MapDialog
        game_dir = inst.game_dir
        if not game_dir or not os.path.isdir(game_dir):
            from .win_rounded import warn
            warn(self, t("map.title"), t("err.launch_missing_dir", path=game_dir or ""))
            return
        MapDialog(game_dir, self).exec()

    def _export_pack(self, inst: Instance):
        """round-184：把实例导出成 Modrinth 整合包（.mrpack）。

        round-196：改成**页内**（与编辑面板里的入口走同一个页内栈）。
        """
        self._open_export_pack(inst)

    def _rebuild_instance(self, inst: Instance):
        """round-166：按磁盘现状重构实例定义（只读扫描，不删游戏文件）。

        适用：手工搬过目录、整合包覆盖、来源启动器升级后，实例记录里的
        版本 / 加载器 / 启动版本 id / 布局格式与磁盘漂移。用磁盘上的版本
        json 重新推导这些字段并落盘，不动任何游戏文件。
        """
        from .core.instance_rebuild import reconstruct
        if not confirm(self, t("instances.rebuild_title"),
                       t("instances.rebuild_confirm", name=inst.name),
                       detail=t("instances.rebuild_hint")):
            return
        try:
            res = reconstruct(inst)
        except Exception as e:  # noqa: BLE001 - 扫描失败给出明确错误
            warn(self, t("instances.rebuild_title"), str(e))
            return
        if not res.get("ok"):
            warn(self, t("instances.rebuild_title"),
                 t(res.get("reason") or "instances.rebuild_no_files"))
            return
        self.mgr.save(inst)
        self._refresh()
        n = len(res.get("changed") or [])
        if n:
            info(self, t("instances.rebuild_title"),
                 t("instances.rebuild_done", n=n,
                   version=res.get("version") or inst.game_version))
        else:
            info(self, t("instances.rebuild_title"),
                 t("instances.rebuild_same"))

    def _edit_instance_settings(self, inst: Instance):
        """打开 PCL 式整页编辑面板（**页内**，round-195）。

        原来这里是 480x620 的一条长滚动框，字段虽全但「换加载器」只是改字段、
        加删 mod 要跳页；round-183 整页化后仍是**弹窗**，round-195 改成页内切换
        —— 换页而不是另开窗口，实例列表始终在下面，编辑完直接回去。
        """
        self._open_instance_editor(inst)

    def _on_editor_version_changed(self, inst_id: str) -> None:
        """编辑面板里版本/加载器字段变了 → 后台补全游戏文件。

        与 round-166 一致：幂等补全，保留存档与模组，失败不阻塞已保存的字段。
        """
        inst = self.mgr.get(inst_id)
        if inst is None:
            self._refresh()
            return
        self._refresh()
        info(self, t("instances.setting_modified_title"),
             t("instances.version_changed"))
        mw = self.window()
        if hasattr(mw, "_start_instance_download"):
            try:
                mw._start_instance_download(inst.id)
            except Exception:  # noqa: BLE001 - 补全失败不影响已保存的设置
                pass

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
        # round-154：整合包应用 → 任务中心（完成后落历史）
        try:
            from .core.task_center import get_task_center
            _task = get_task_center().start(
                "import", inst.name or "Minecraft", target_page="instances")
            self._pack_task_id = _task.id
        except Exception:  # noqa: BLE001 - 任务记录失败不阻断导入
            self._pack_task_id = ""
        self._pack_worker = ProgressWorker(
            apply_mrpack_to_instance, path, inst,
            mirror=settings.get("download_mirror", "official"),
            proxy=settings.get("download_proxy", ""),
        )
        self._pack_worker.status.connect(
            lambda s: self.window().statusBar().showMessage(s))
        self._pack_worker.status.connect(self._on_pack_status)
        self._pack_worker.finished.connect(
            lambda v: self._on_pack_applied(inst, v))
        self._pack_worker.error.connect(
            lambda e: self._on_pack_error(e))
        self._pack_worker.start()

    def _on_pack_status(self, text: str) -> None:
        """round-154：导入阶段写入任务记录。"""
        try:
            from .core.task_center import get_task_center
            tid = getattr(self, "_pack_task_id", "")
            if tid:
                get_task_center().update(tid, stage=text)
        except Exception:  # noqa: BLE001
            pass

    def _on_pack_applied(self, inst: Instance, launch_version):
        try:
            self.mgr.save(inst)
            self._refresh()
        except Exception:
            pass
        try:
            from .core.task_center import get_task_center
            tid = getattr(self, "_pack_task_id", "")
            if tid:
                get_task_center().finish(
                    tid, t("instances.apply_pack_done", ver=launch_version or ""))
                self._pack_task_id = ""
        except Exception:  # noqa: BLE001
            pass
        from .win_rounded import toast
        toast(self, t("instances.apply_pack_title"),
              t("instances.apply_pack_done", ver=launch_version or ""))

    def _on_pack_error(self, msg: str):
        try:
            from .core.task_center import get_task_center
            tid = getattr(self, "_pack_task_id", "")
            if tid:
                get_task_center().fail(tid, msg or "")
                self._pack_task_id = ""
        except Exception:  # noqa: BLE001
            pass
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
                        java_path: str, ldver: str, fmt: str = "ac",
                        base: str = ""):
        inst = self.mgr.add(name, version, loader, loader_version=ldver,
                            java_path=java_path, format=fmt, base=base)
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
        # Hide before the deferred delete: deleteLater only runs on the next
        # event-loop turn, and until then a still-visible panel kept painting
        # over the restored page ("退出后双页" report, round-126).
        panel.hide()
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
        # round-243：每导入成功一个就增量刷新左侧列表，玩家不用等关面板才看到
        # 新实例（扫描面板自己不再整盘重扫）。
        self._scan_panel.imported.connect(self._on_scan_imported)
        idx = self._body_stack.addWidget(self._scan_panel)
        self._body_stack.setCurrentIndex(idx)

    def _on_scan_imported(self, _mc_dir: str) -> None:
        """扫描面板导入成功 → 后台刷新实例列表（不切走面板）。"""
        self._refresh(switch=False)

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
        panel.hide()  # same deferred-delete paint guard as _close_new_panel
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
        from .win_rounded import pick_files, warn
        from .modpack_import import detect_pack_format

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

        # ☠ round-244 P0：这里原本漏了 `fn = fn_map[fmt]` 就直接
        # `Worker(fn, ...)` → 按钮一点必抛 NameError（用户实测「根本导不进去」）。
        # 同时把拖拽那条路径的重复实现合并进来，避免两边再次跑偏。
        self._run_pack_import(path, fmt)

    def _run_pack_import(self, path: str, fmt: str) -> None:
        """按钮/拖拽共用的导入实现：选对应 importer → 后台 worker → 任务中心。

        ``fmt`` 取值见 :func:`modpack_import.detect_pack_format`：
        ``curseforge`` / ``zip_mc`` / ``folder``（``mrpack`` 由调用方先弹预览框）。
        """
        from .modpack_import import (
            import_curseforge_zip, import_zip_as_instance,
            import_folder_as_instance,
        )
        from .net_api import NetError
        from .core.task_center import get_task_center
        from .win_rounded import warn, toast

        fn_map = {
            "curseforge": import_curseforge_zip,
            "zip_mc": import_zip_as_instance,
            "folder": import_folder_as_instance,
        }
        fn = fn_map.get(fmt)
        if fn is None:
            warn(self, t("modpack.title"), t("modpack.unknown_format"))
            return

        # 进度与结果统一进任务中心（状态栏「任务」→ 页内任务分区），不再弹
        # 独立进度对话框：导入期间可继续浏览，失败原因留在历史里。
        _tid = get_task_center().start(
            "import", os.path.basename(path), target_page="instances",
            stage=t("modpack.importing")).id

        def _pr(label, done, total):
            if done and done > 0:
                get_task_center().update(
                    _tid, stage=str(label), completed=done, total=total)
            return True

        # CurseForge 是逐文件下载，进度可报；zip/文件夹是一次性拷贝，不传 progress。
        kw = {"progress": _pr} if fmt == "curseforge" else {}
        worker = Worker(fn, path, self.mgr, **kw)

        def _done(inst):
            # 导入时已尝试安装版本/加载器；失败不丢整合包，但要明确提示
            # 首次启动还会再装一次。
            err = getattr(inst, "loader_install_error", "")
            if err:
                warn(self, t("modpack.title"), t("modpack.loader_failed_hint", e=err))
            else:
                toast(self, t("modpack.title"), t("modpack.done"))
            get_task_center().finish(
                _tid, detail=(getattr(inst, "name", "") or ""))
            self._refresh()
            if inst and getattr(inst, "id", None):
                self.mgr.set_current(inst.id)
                self.current_changed.emit(inst.id)

        def _err(e):
            get_task_center().fail(_tid, detail=str(e))
            if isinstance(e, NetError):
                warn(self, t("modpack.title"), str(e))
            else:
                warn(self, t("modpack.title"), t("modpack.error", e=e))

        worker.finished.connect(_done)
        worker.error.connect(_err)
        self._pack_worker = worker
        worker.start()
        toast(self, t("modpack.title"), t("modpack.import_bg"))

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
        # ☠ round-246：必须传 path！_parse_mrpack_info 要从 zip 里的
        # modrinth.index.json 读 loader/mods 数；上轮漏传 → UI 仍显示
        # vanilla/0，用户实测「模组数量看不到、加载器识别不到」。
        info = _parse_mrpack_info(raw, path)
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
        """拖拽入口：识别格式后复用按钮那条导入实现。round-244。"""
        from .win_rounded import warn
        from .modpack_import import detect_pack_format

        fmt = detect_pack_format(path)
        if fmt is None:
            warn(self, t("modpack.title"), t("modpack.unknown_format"))
            return
        # ☠ 原实现写 `elif fmt == "zip"`，而 detect_pack_format() 返回的是
        # "zip_mc" → 拖普通 .zip 进去哪个分支都不进，静默无反应。
        if fmt == "mrpack":
            self._show_mrpack_dialog(path)
            return
        self._run_pack_import(path, fmt)

    def _on_pack_imported(self, inst):
        self._refresh()
        if inst is not None and getattr(inst, "id", None):
            self._set_current(inst.id)

    # ia[instances]: 点「设为当前」 | 详情底部操作行 | 切换当前实例并刷新列表/首页
    def _set_current(self, inst_id: str):
        self.mgr.set_current(inst_id)
        self._refresh()
        self.current_changed.emit(inst_id)

    def _remove(self, inst_id: str):
        inst = self.mgr.get(inst_id)
        if inst is None:
            return
        if self._guard_running(inst_id):
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
        self._report_delete_leftovers(inst, self.mgr.remove(inst_id))
        if self._selected_id == inst_id:
            self._selected_id = None
        self._refresh()
        toast(self, t("instances.delete_title"),
              t("instances.delete_toast", name=inst.name), duration=3000)
        cur = self.mgr.current_id
        if cur:
            self.current_changed.emit(cur)

    # ── 回收站 ──
    def _trash_state(self) -> QWidget:
        """Build the trash page widget (page 4 in body stack)."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        # Title row with back button and clear-all button
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        self._trash_back_btn = QPushButton()
        self._trash_back_btn.setFixedSize(34, 34)
        self._trash_back_btn.setCursor(Qt.PointingHandCursor)
        self._trash_back_btn.setIcon(icon("home"))
        self._trash_back_btn.setIconSize(QSize(15, 15))
        self._trash_back_btn.setToolTip(t("common.back"))
        self._trash_back_btn.setStyleSheet(
            f"QPushButton {{ background: {COLORS['bg_btn']}; color: {COLORS['text_main']};"
            f" border: 1px solid {COLORS['border']}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {COLORS['bg_hover']}; }}"
        )
        self._trash_back_btn.clicked.connect(self._close_trash)
        title_row.addWidget(self._trash_back_btn)

        title_lbl = ui_kit.group_label(t("instances.trash_title"))
        title_row.addWidget(title_lbl)
        title_row.addStretch(1)
        self._trash_clear_btn = QPushButton(t("instances.trash_clear"))
        self._trash_clear_btn.setCursor(Qt.PointingHandCursor)
        self._trash_clear_btn.setMinimumHeight(32)
        self._trash_clear_btn.setStyleSheet(
            f"QPushButton {{ background: {COLORS['bg_btn']}; color: {COLORS['text_sub']};"
            f" border: 1px solid {COLORS['border']}; border-radius: 8px;"
            f" padding: 6px 14px; font-size: 13px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {COLORS['danger']}; color: white; border-color: {COLORS['danger']}; }}"
        )
        self._trash_clear_btn.clicked.connect(self._clear_trash)
        title_row.addWidget(self._trash_clear_btn)
        lay.addLayout(title_row)

        # Scrollable list of trashed instances
        self._trash_scroll = QScrollArea()
        self._trash_scroll.setWidgetResizable(True)
        self._trash_scroll.setFrameShape(QFrame.NoFrame)
        self._trash_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._trash_content = QWidget()
        self._trash_vbox = QVBoxLayout(self._trash_content)
        self._trash_vbox.setContentsMargins(0, 0, 0, 0)
        self._trash_vbox.setSpacing(8)
        self._trash_scroll.setWidget(self._trash_content)
        lay.addWidget(self._trash_scroll, stretch=1)

        # Empty state placeholder (will be shown/hidden by _refresh_trash)
        self._trash_empty = ui_kit.empty_state(
            "instances",
            t("instances.trash_empty"),
            "",
            actions=[],
            icon_size=64,
        )
        self._trash_empty.hide()
        self._trash_vbox.addWidget(self._trash_empty)
        self._trash_vbox.addStretch(1)

        # Initial populate
        self._refresh_trash()
        return page

    def _refresh_trash(self):
        """Rebuild the trash list from the manager."""
        # Clear existing cards (except empty state and stretch)
        while self._trash_vbox.count() > 2:  # keep empty + stretch at the end
            item = self._trash_vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        items = self.mgr.list_trash()
        if not items:
            self._trash_empty.show()
            self._trash_clear_btn.setEnabled(False)
            return

        self._trash_empty.hide()
        self._trash_clear_btn.setEnabled(True)

        from datetime import datetime
        for item in items:
            inst_id = item.get("id", "")
            name = item.get("name", "")
            version = item.get("game_version", "")
            loader = item.get("loader", "")
            deleted_at = item.get("deleted_at", 0)

            card = RoundedCard(radius=10)
            card.setMinimumHeight(80)
            cl = QHBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.setSpacing(16)

            # Icon tile (instance type)
            tile = ui_kit.tile("instances", 44, 22)
            cl.addWidget(tile)

            # Info column
            info_col = QVBoxLayout()
            info_col.setSpacing(4)
            name_lbl = ui_kit.ElidedLabel(name or "—")
            name_lbl.setProperty("cls", "title")
            info_col.addWidget(name_lbl)

            meta = QHBoxLayout()
            meta.setSpacing(8)
            if version:
                v_lbl = QLabel(version)
                v_lbl.setProperty("cls", "sub")
                meta.addWidget(v_lbl)
            if loader:
                ld = _loader_badge(loader_name(loader), loader)
                meta.addWidget(ld)
            # Deletion time
            if deleted_at:
                dt = datetime.fromtimestamp(deleted_at).strftime("%Y-%m-%d %H:%M")
                dt_lbl = QLabel(t("instances.trash_deleted_at", dt=dt))
                dt_lbl.setProperty("cls", "sub")
                meta.addWidget(dt_lbl)
            meta.addStretch(1)
            info_col.addLayout(meta)
            cl.addLayout(info_col, stretch=1)

            # Action buttons: Restore / Delete permanently
            restore_btn = QPushButton(t("instances.trash_restore"))
            restore_btn.setMinimumHeight(30)
            restore_btn.setCursor(Qt.PointingHandCursor)
            restore_btn.setStyleSheet(
                f"QPushButton {{ background: {COLORS['accent']}; color: {COLORS['text_on_accent']};"
                f" border: none; border-radius: 6px; padding: 4px 12px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: {with_alpha(COLORS['accent'], 0xCC)}; }}"
            )
            restore_btn.clicked.connect(lambda _checked=False, iid=inst_id, n=name: self._restore_from_trash(iid, n))

            delete_btn = QPushButton(t("instances.trash_delete"))
            delete_btn.setMinimumHeight(30)
            delete_btn.setCursor(Qt.PointingHandCursor)
            delete_btn.setProperty("cls", "danger")
            delete_btn.setStyleSheet(
                f"QPushButton {{ background: {COLORS['bg_btn']}; color: {COLORS['danger']};"
                f" border: 1px solid {COLORS['danger']}; border-radius: 6px; padding: 4px 12px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: {COLORS['danger']}; color: white; }}"
            )
            delete_btn.clicked.connect(lambda _checked=False, iid=inst_id, n=name: self._delete_from_trash(iid, n))

            btn_row = QHBoxLayout()
            btn_row.setSpacing(8)
            btn_row.addWidget(restore_btn)
            btn_row.addWidget(delete_btn)
            cl.addLayout(btn_row)

            # Insert before the empty state + stretch (which are the last 2 items)
            self._trash_vbox.insertWidget(self._trash_vbox.count() - 2, card)

    def _open_trash(self):
        """Switch the body stack to the trash page."""
        self._body_stack.setCurrentWidget(self._trash_page)
        self._refresh_trash()  # ensure up-to-date when opened
        # Hide header action buttons while on trash page (consistent with other embedded panels)
        self._set_header_buttons_enabled(False)

    def _restore_from_trash(self, instance_id: str, name: str):
        if not confirm(self, t("instances.trash_restore_confirm", name=name), ""):
            return
        if self.mgr.restore_from_trash(instance_id):
            toast(self, t("common.hint"), t("instances.trash_toast_restored", name=name))
            self._refresh_trash()
            self._refresh()  # also refresh main list

    def _delete_from_trash(self, instance_id: str, name: str):
        if not confirm(self, t("instances.trash_delete_confirm", name=name), ""):
            return
        if self.mgr.delete_from_trash(instance_id):
            toast(self, t("common.hint"), t("instances.trash_toast_deleted", name=name))
            self._refresh_trash()

    def _clear_trash(self):
        if not confirm(self, t("instances.trash_clear_confirm"), ""):
            return
        count = self.mgr.clear_trash()
        if count:
            toast(self, t("common.hint"), t("instances.trash_toast_cleared", n=count))
        self._refresh_trash()

    def _close_trash(self):
        """Return from trash page to the main instance list (page 1)."""
        self._body_stack.setCurrentWidget(self._split_view)
        self._set_header_buttons_enabled(True)

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
    """Mod 展示名。

    round-185：改为优先读 jar 里的清单（``fabric.mod.json`` / ``mods.toml`` /
    ``mcmod.info``）—— 以前拿文件名凑，``fabric-api-0.92.2+1.20.1`` 会显示成
    「fabric api 0.92.2+1.20.1」。读不到才退回文件名。
    """
    from .core.modmeta import display_name
    return display_name(path)


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
            bg=(LOADER_BADGE.get(loader) if loader_vivid() else None))
        lay.addWidget(tile)

        # ── info column: name + meta (loader pill · state) ──
        col = QVBoxLayout()
        col.setSpacing(4)
        name = ui_kit.ElidedLabel(_mod_display_name(path))
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
        # round-195：旧的「检查更新」按钮去掉 —— ModListPanel 自带「可更新」
        # 筛选（点它就查），两处都留着又是「同一个功能两个入口」。
        self.update_btn = None

        self._header = ui_kit.page_header(
            t("mods.title"), icon_key="mods")
        self.title_lbl = self._header.title_lbl
        root.addWidget(self._header)

        # round-52 操作行独立成一行：目标实例 + 组合 + 两个按钮。
        # combo 用 stretch 弹性伸展，窄窗口下按钮不被挤压、内容不溢出。
        action_widget = QWidget()
        # round-122: an inline "background: transparent" here cascades to every
        # child and wiped the combo / accent-button backgrounds (offscreen
        # sampling returned alpha 0, leaving white text on a white page).
        # QWidget paints no background by default, so no stylesheet is needed.
        al = QHBoxLayout(action_widget)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(10)
        al.addWidget(self.target_lbl)
        al.addWidget(self.inst_combo, stretch=1)
        al.addWidget(self.add_btn)
        root.addWidget(action_widget)

        # round-195：模组管理**只有一套**。
        # 原来这里是一套独立实现（大卡片 + 启用/删除按钮），实例编辑面板里又
        # 是另一套（紧凑行 + 搜索 + 批量）—— 同一功能两个页面两套逻辑，玩家
        # 看到的就是「长得不一样、功能不一样」。现在两处都用 ModListPanel。
        self._panel_host = QWidget()
        self._panel_lay = QVBoxLayout(self._panel_host)
        self._panel_lay.setContentsMargins(0, 0, 0, 0)
        self._panel_lay.setSpacing(10)
        root.addWidget(self._panel_host, stretch=1)
        self._mod_panel = None

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
    def refresh(self):
        if not hasattr(self, "inst_combo"):
            return
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
        # round-195：换成 ModListPanel（与实例编辑面板的模组页同一组件）。
        # 旧卡片同步销毁：deleteLater() 会让控件活到事件循环转圈，快速切换
        # 实例时会在还活着的 C++ 对象上 addWidget → 布局损坏。
        while self._panel_lay.count():
            item = self._panel_lay.takeAt(0)
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
            self._panel_lay.addWidget(empty)
            self._mod_panel = None
            return
        from .mod_list import ModListPanel
        self._mod_panel = ModListPanel(
            self._panel_host, inst, on_open_folder=self._open_mods_folder)
        self._panel_lay.addWidget(self._mod_panel)

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
        # round-44 补全：add_btn 文本刷新（round-195：update_btn 已移除，
        # 「检查更新」由 ModListPanel 的「可更新」筛选承担）
        if hasattr(self, "add_btn"):
            self.add_btn.setText(t("mods.add"))
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
        _loader = info.get("loader") or "vanilla"
        _ldver = info.get("loader_version") or ""
        grid.addRow(QLabel(t("mrpack.loader")),
                    QLabel(loader_name(_loader) +
                           (f" {_ldver}" if _ldver and _loader != "vanilla" else "")))
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
            loader=self.info.get("loader") or "vanilla",
            loader_version=self.info.get("loader_version") or "",
            isolation="default")
        inst.version_id = self.info.get("launch_version") or ""
        self.mgr._persist(inst)
        self._inst = inst
        # 登记到任务中心：任务分区里能看到这次安装，失败原因也会进历史。
        from .core.task_center import get_task_center
        self._task_id = get_task_center().start(
            "import", name, target_page="instances").id
        from .core import install
        # round-113：跟随用户设置的下载源，不再硬编码 BMCLAPI
        _cfg = load_config()
        # ☠ round-246 P0：这里原来用 Worker，而 Worker 只有 finished/error，
        # 根本没有 progress/status —— 对话框进度条从显示到结束一动不动，
        # 用户实测「进度不涨」。换成 ProgressWorker 并接上状态/进度。
        from .worker import ProgressWorker
        self._worker = ProgressWorker(
            install.install_mrpack, self.path, inst.mc_dir,
            game_dir=inst.game_dir,
            mirror=_cfg.get("download_mirror", "official"),
            proxy=_cfg.get("download_proxy", ""))
        self._worker.status.connect(self._on_pack_status)
        self._worker.progress.connect(self._on_pack_progress)
        self._worker.step.connect(self._on_pack_step)
        self._worker.finished.connect(self._done)
        self._worker.error.connect(self._err)
        self._worker.start()

    def _on_pack_status(self, text: str) -> None:
        self.status.setText(str(text))

    def _on_pack_progress(self, value: int, maximum: int) -> None:
        if maximum and maximum > 0:
            self.bar.setVisible(True)
            self.bar.setRange(0, maximum)
            self.bar.setValue(max(0, min(int(value), maximum)))
        else:
            self.bar.setRange(0, 0)   # 未定长：保持"忙"指示

    def _on_pack_step(self, key: str) -> None:
        self.status.setText(str(key))

    def _done(self, result):
        self.bar.setVisible(False)
        self.status.setText(t("mrpack.done"))
        # ☠ round-245 P0：install_mrpack 返回的 launch version id 以前被当
        # `_result` 丢弃 → 新建实例只有「预览时猜的」loader/game_version，
        # version_id 空或错，启动永远 "Version xxx was not found"，补全也
        # 按错的 loader/game_version 去装（用户实测「补全了也必失败」）。
        # install_mrpack 真装的版本 id 才是启动的唯一真理源，必须回写落盘。
        if isinstance(result, str) and result:
            self._inst.version_id = result
            self.mgr._persist(self._inst)
        from .core.task_center import get_task_center
        get_task_center().finish(getattr(self, "_task_id", ""),
                                 detail=self.info.get("name") or "")
        self.ok_btn.setEnabled(False)
        self.cancel_btn.setText(t("common.close"))
        self.cancel_btn.setEnabled(True)
        # keep dialog open so the user sees the confirmation, then close
        from PySide6.QtCore import QTimer as _T
        _T.singleShot(1500, self.accept)

    def _err(self, e: str):
        self.bar.setVisible(False)
        self.status.setText(t("mrpack.error", e=e))
        from .core.task_center import get_task_center
        get_task_center().fail(getattr(self, "_task_id", ""), detail=str(e))
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
