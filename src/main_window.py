"""
MainWindow: left nav + top bar + content stack + status bar.

Phase 3 scope:
  - Home page: launches the current instance with a real, progress-reporting
    install + launch pipeline (minecraft-launcher-lib under the hood).
  - Instances / Mods / Store / Versions: fully populated pages.
  - Account: real Microsoft device-code login (or offline) via LoginDialog.
"""
import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QListWidget, QListWidgetItem, QStackedWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QProgressBar, QGridLayout, QMenu, QComboBox,
)
from PySide6.QtCore import Qt, QSize, QTimer, QEvent, QObject, QPropertyAnimation, QEasingCurve, QRectF

from .theme import COLORS, RoundedCard
from .icons import icon
from .i18n import t
from .instances import manager, Instance
from .pages_instances import InstancesPage, ModsPage
from .pages_browse import VersionsPage, StorePage
from .frameless import FramelessHelper
from .worker import ProgressWorker
from .launch import launch_instance
from .settings_dialog import load_config, save_config, SettingsPage
from .accounts import manager as accounts_manager, type_label
from .paths import get_data_dir
from .skins import manager as skin_manager
from .skin_render import render_head
from .brand import APP_DISPLAY, APP_VERSION
from .win_rounded import enable_win11_round_corners

# Nav keys are stable; labels are resolved lazily so a language switch really
# re-translates the sidebar (t() is evaluated at call time, not import time).
NAV_KEYS = [
    ("nav.home", "home"),
    ("nav.instances", "instances"),
    ("nav.mods", "mods"),
    ("nav.store", "store"),
    ("nav.versions", "versions"),
    ("lobby.nav_lobby", "lobby"),
    ("nav.account", "account"),
    ("nav.settings", "settings"),
]


def nav_items() -> list[tuple[str, str]]:
    """(label, key) pairs translated for the *current* language."""
    return [(t(tk), key) for tk, key in NAV_KEYS]


NAV_ITEMS = NAV_KEYS  # index-compatible alias: NAV_ITEMS[i][1] is still the key

# AC 布局左侧导航分组（对标 HMCL/PCL2 的功能区分化）。
# 每项：(分组标题键 or None=不分组的独立主项, [(label键, key), ...])
NAV_GROUPS = [
    (None, [("nav.home", "home")]),                             # 启动（主项）
    ("nav.group.game", [("nav.instances", "instances"), ("nav.mods", "mods")]),
    ("nav.group.resource", [("nav.store", "store"), ("nav.versions", "versions")]),
    ("nav.group.fun", [("nav.music", "music"), ("nav.achievements", "achievements")]),                # 音乐（direction B 彩蛋）
    ("nav.group.multiplayer", [("lobby.nav_lobby", "lobby")]),
    ("nav.group.system", [("nav.account", "account"), ("nav.settings", "settings")]),
]

# Stack index of every page — single source of truth for BOTH nav layouts
# (AC left sidebar and the optional PCL2 top-bar). Add a new page here and it
# becomes reachable from whichever nav includes its key.
STACK_INDEX = {
    "home": 0, "instances": 1, "mods": 2, "store": 3,
    "versions": 4, "lobby": 5, "settings": 6, "toolbox": 7,
    "music": 8, "achievements": 9,
}

# ── PCL2 top-bar navigation model (optional layout, chosen in settings) ──
# 对齐 PCL2 真实顶栏（FormMain.xaml BtnTitleSelect0-4）：
# 启动 / 下载 / 联机 / 设置 / 更多。
# 未实现的功能走 placeholder 页面（"敬请期待"），入口先占位。
PCL2_TOP = [
    ("pcl2.nav_launch", "launch"),     # BtnTitleSelect0 → 启动
    ("pcl2.nav_download", "download"), # BtnTitleSelect1 → 下载
    ("pcl2.nav_online", "online"),     # BtnTitleSelect2 → 联机
    ("nav.settings", "settings"),      # BtnTitleSelect3 → 设置
    ("pcl2.nav_more", "more"),         # BtnTitleSelect4 → 更多
]
# Context sidebar shown under each top pill (empty list = no sidebar for that tab).
PCL2_SIDEBAR = {
    # 启动页：主页 + 实例列表（PCL2 启动页左侧是实例/版本选择）
    "launch": [
        ("nav.home", "home"),
        ("nav.instances", "instances"),
    ],
    # 下载页：版本库 / 资源中心 / 模组（PCL2 下载分类）
    "download": [
        ("nav.versions", "versions"),
        ("nav.store", "store"),
        ("nav.mods", "mods"),
    ],
    # 联机页：暂无实现 → 敬请期待
    "online": [],
    # 设置页
    "settings": [],
    # 更多页：工具 / 大厅 / 占位
    "more": [
        ("pcl2.nav_toolbox", "toolbox"),
        ("lobby.title", "lobby"),
    ],
}

# Fallback account used when the user hasn't logged in (offline single-player).
OFFLINE_ACCOUNT = {"username": "Player", "uuid": "", "token": ""}


def _yield():
    """Let the splash animation repaint between heavy construction steps."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.processEvents()


class HomePage(QWidget):
    def __init__(self, on_play, get_current_instance, cfg,
                 on_open_settings=None, on_open_instances=None,
                 on_open_versions=None, on_open_mods=None,
                 list_instances=None, set_current_instance=None, parent=None):
        super().__init__(parent)
        self.on_play = on_play
        self.get_current_instance = get_current_instance
        self.list_instances = (list_instances or (lambda: []))
        self.set_current_instance = (set_current_instance or (lambda _id: None))
        self.cfg = cfg
        self.on_open_settings = on_open_settings
        self.on_open_instances = on_open_instances
        self.on_open_versions = on_open_versions
        self.on_open_mods = on_open_mods
        self._rebuilding = False  # guard against rapid-fire rebuild() calls
        # Backdrop sits behind everything and never eats clicks.
        from .wallpaper import WallpaperWidget

        self.backdrop = WallpaperWidget(self)
        self.backdrop.setGeometry(self.rect())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.content = QWidget()
        self.content.setAttribute(Qt.WA_TranslucentBackground, True)
        root.addWidget(self.content, stretch=1)
        # Defer wallpaper (esp. video) init OFF the constructor: a media-backend
        # hiccup during synchronous QMediaPlayer init must never stall
        # MainWindow construction or leave the splash screen hanging.
        QTimer.singleShot(0, self._apply_wallpaper)
        self._build()
        self._refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "backdrop"):
            self.backdrop.setGeometry(self.rect())
            self.backdrop.lower()

    # ── (re)build the layout for the current home_style ──
    @staticmethod
    def _clear_layout(layout):
        """Recursively tear down a layout and **synchronously** delete all child
        widgets / sub-layouts.

        Uses ``shiboken6.delete`` (C++-level immediate disposal) instead of
        ``deleteLater()`` so that a rapid second ``_build()`` call never sees
        orphan widgets from the previous pass still alive in the widget tree.
        ``shiboken6.delete`` is the PySide6 equivalent of PyQt's ``sip.delete``;
        falling back to ``deleteLater()`` if shiboken isn't available or the
        object is already gone.
        """
        if layout is None:
            return
        try:
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)       # detach immediately
                    try:
                        from shiboken6 import delete as _sh_delete
                        _sh_delete(w)      # synchronous C++ deletion
                    except Exception:
                        w.deleteLater()   # fallback async
                else:
                    HomePage._clear_layout(item.layout())
            # Detach from parent so a new layout can be installed.
            if layout.parentWidget() is not None:
                QWidget().setLayout(layout)
        except RuntimeError:
            # C++ object already deleted (libshiboken) — nothing to clear.
            pass

    def _build(self):
        # 彻底替换 content 容器（旧 widget 同步删除），避免快速 rebuild
        # 时旧控件异步删除导致屏幕上出现"双面板"残留。
        self._replace_content()
        style = self.cfg.get("home_style", "ac_default")
        lay = QVBoxLayout(self.content)
        lay.setContentsMargins(48, 40, 48, 40)
        lay.setSpacing(20)
        builder = {
            "pcl_card": self._build_pcl_card,
            "hmcl_list": self._build_hmcl_list,
            "modrinth_modern": self._build_modrinth,
        }.get(style, self._build_ac_default)
        builder(lay)
        lay.addStretch(1)

    def _replace_content(self):
        """Swap ``self.content`` out for a fresh QWidget, deleting the old one
        synchronously. Single-widget tear-down is more bulletproof than walking
        an entire layout (which can leave transient orphans during very rapid
        rebuilds) — the old C++ object is destroyed immediately, so its visual
        frame cannot bleed into the next."""
        root = self.layout()
        if root is None:
            return
        idx = root.indexOf(self.content)
        if idx < 0:
            return
        root.removeWidget(self.content)
        old = self.content
        try:
            from shiboken6 import delete as _sh_delete
            _sh_delete(old)
        except Exception:
            old.deleteLater()
        new_content = QWidget()
        new_content.setAttribute(Qt.WA_TranslucentBackground, True)
        root.insertWidget(idx, new_content, stretch=1)
        self.content = new_content

    def rebuild(self):
        """Tear down and rebuild (used on style / language change)."""
        if self._rebuilding:
            return
        self._rebuilding = True
        try:
            self._apply_wallpaper()
            self._build()
            self._refresh()
        finally:
            self._rebuilding = False

    def retranslate_ui(self):
        """Language switched — re-render all text from scratch."""
        self.rebuild()
        # home 已通过 rebuild 重建；其他页面是独立 stack widget，必须各自
        # reload 才能用新语言重画文字（否则切到 settings 后仍是英文标签）。
        if hasattr(self, "settings_page") and self.settings_page is not None:
            self.settings_page.reload()

    # ── shared widget factories ──
    def _title_block(self, lay):
        head = QLabel(t("home.title"))
        head.setProperty("cls", "title")
        sub = QLabel(t("home.subtitle"))
        sub.setProperty("cls", "sub")
        lay.addWidget(head)
        lay.addWidget(sub)

    def _instance_card(self) -> RoundedCard:
        card = RoundedCard(radius=12)
        card.setMinimumHeight(170)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setSpacing(10)
        cl.addWidget(self._label(t("home.instance")))

        # ── instance selector dropdown ──
        self.inst_combo = QComboBox()
        self.inst_combo.setProperty("cls", "instance-selector")
        self.inst_combo.setMinimumHeight(36)
        self.inst_combo.currentIndexChanged.connect(self._on_inst_changed)
        cl.addWidget(self.inst_combo)

        self.detail_lbl = QLabel("")
        self.detail_lbl.setProperty("cls", "sub")
        cl.addWidget(self.detail_lbl)
        return card

    def _on_inst_changed(self, index: int):
        if index < 0:
            return
        inst_id = self.inst_combo.currentData()
        if inst_id:
            self.set_current_instance(inst_id)
            self._refresh()

    def _make_play_btn(self) -> QPushButton:
        b = QPushButton(t("home.play"))
        b.setProperty("cls", "accent")
        b.setMinimumHeight(52)
        b.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        b.clicked.connect(self._on_play)
        b.setIcon(icon("play"))
        b.setIconSize(QSize(22, 22))
        return b

    def _make_scan_btn(self) -> QPushButton:
        b = QPushButton(t("scan.title"))
        b.setMinimumHeight(40)
        b.setIcon(icon("search"))
        b.setIconSize(QSize(18, 18))
        b.clicked.connect(self._open_scan)
        return b

    def _make_settings_btn(self) -> QPushButton:
        b = QPushButton(t("nav.settings"))
        b.setMinimumHeight(40)
        b.setIcon(icon("settings"))
        b.setIconSize(QSize(18, 18))
        b.clicked.connect(self._open_settings)
        return b

    def _action_card(self, title, sub, ic, cb) -> QPushButton:
        b = QPushButton()
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(104)
        b.setProperty("cls", "surface")
        vl = QVBoxLayout(b)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(8)
        ic_l = QLabel()
        ic_l.setPixmap(icon(ic).pixmap(26, 26))
        vl.addWidget(ic_l)
        tl = QLabel(title)
        tl.setProperty("cls", "big")
        vl.addWidget(tl)
        sl = QLabel(sub)
        sl.setProperty("cls", "sub")
        sl.setWordWrap(True)
        vl.addWidget(sl)
        vl.addStretch(1)
        b.clicked.connect(cb)
        return b

    def _list_row(self, ic, title, sub, cb) -> QPushButton:
        row = QPushButton()
        row.setCursor(Qt.PointingHandCursor)
        row.setMinimumHeight(58)
        row.setProperty("cls", "row")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(16, 8, 16, 8)
        hl.setSpacing(12)
        il = QLabel()
        il.setPixmap(icon(ic).pixmap(22, 22))
        hl.addWidget(il)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(QLabel(title))
        if sub:
            sl = QLabel(sub)
            sl.setProperty("cls", "sub")
            col.addWidget(sl)
        hl.addLayout(col)
        hl.addStretch(1)
        ch = QLabel("›")
        ch.setProperty("cls", "sub")
        hl.addWidget(ch)
        row.clicked.connect(cb)
        return row

    def _quick_chip(self, ic, text, cb) -> QPushButton:
        """Compact icon+label action chip used in the AC default home's
        quick-action row.  Plain QPushButton with icon — no custom cls so it
        inherits the theme's standard button styling.  Falls back to text-only
        if the icon is missing so the chip never renders as an empty box."""
        from .icons import icon as _icon
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(40)
        b.setMinimumWidth(120)
        pix = _icon(ic).pixmap(18, 18) if _icon(ic) else None
        if pix and not pix.isNull():
            b.setIcon(pix)
            b.setIconSize(QSize(18, 18))
        b.clicked.connect(cb)
        return b

    def _quick_btn(self, ic, text, cb) -> QPushButton:
        """Accent-coloured big quick action button."""
        from .icons import icon as _icon
        b = QPushButton(text)
        b.setProperty("cls", "accent")
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(44)
        b.setMinimumWidth(110)
        pix = _icon(ic).pixmap(18, 18) if _icon(ic) else None
        if pix and not pix.isNull():
            b.setIcon(pix)
            b.setIconSize(QSize(18, 18))
        b.clicked.connect(cb)
        return b

    # ── four style layouts ──
    def _build_ac_default(self, lay):
        self._title_block(lay)

        # ── 统御统计条（direction A: 控制中枢叙事）──
        # 已接管实例数 · 来源启动器数 · 待修复实例数，一眼看清 AC 的"统御力"。
        # 用 RoundedCard 自绘圆角 —— QSS border-radius 不裁剪容器背景，
        # QFrame 会是黑框直角（用户多次反馈"统计次数的黑框没圆角"）。
        stats = RoundedCard(radius=12)
        stats.setMinimumHeight(64)
        sl = QHBoxLayout(stats)
        sl.setContentsMargins(24, 12, 24, 12)
        sl.setSpacing(28)
        self.stat_instances = self._stat_cell(sl, "0", t("home.stat_taken"))
        self.stat_sources = self._stat_cell(sl, "0", t("home.stat_sources"))
        self.stat_repair = self._stat_cell(sl, "0", t("home.stat_repair"))
        sl.addStretch(1)
        self.repair_btn = QPushButton(t("home.stat_repair_btn"))
        self.repair_btn.setProperty("cls", "accent")
        self.repair_btn.setMinimumHeight(32)
        self.repair_btn.setIcon(icon("repair"))
        self.repair_btn.setIconSize(QSize(15, 15))
        self.repair_btn.clicked.connect(self._open_scan)
        sl.addWidget(self.repair_btn)
        lay.addWidget(stats)

        # ── hero 实例卡（AC 品牌默认样式：左信息 / 右大启动按钮）──
        hero = RoundedCard(radius=12)
        hero.setMinimumHeight(190)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(28, 22, 28, 22)
        hl.setSpacing(24)

        # 左：当前实例身份
        left = QVBoxLayout()
        left.setSpacing(8)
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name = QLabel("—")
        name.setProperty("cls", "big")
        name.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        name_row.addWidget(name)
        # 来源徽章（PCL2/HMCL/Prism…）——控制中枢叙事：这个实例从哪个启动器接管
        self.src_badge = QLabel("")
        self.src_badge.setStyleSheet(
            f"background: {COLORS['accent']}22; color: {COLORS['accent']}; "
            f"border-radius: 8px; padding: 2px 10px; font-size: 11px; font-weight: 600;"
        )
        self.src_badge.setVisible(False)
        name_row.addWidget(self.src_badge)
        name_row.addStretch(1)
        left.addLayout(name_row)
        detail = QLabel("")
        detail.setProperty("cls", "sub")
        left.addWidget(detail)
        left.addSpacing(8)
        self.inst_combo = QComboBox()
        self.inst_combo.setProperty("cls", "instance-selector")
        self.inst_combo.setMinimumHeight(38)
        self.inst_combo.setMinimumWidth(260)
        self.inst_combo.currentIndexChanged.connect(self._on_inst_changed)
        left.addWidget(self.inst_combo)
        left.addStretch(1)
        hl.addLayout(left, stretch=1)

        # 右：醒目启动按钮
        play = self._make_play_btn()
        play.setMinimumHeight(60)
        play.setMinimumWidth(220)
        play.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.play_btn = play
        hl.addWidget(play, alignment=Qt.AlignVCenter | Qt.AlignRight)

        self.inst_lbl = name
        self.detail_lbl = detail
        lay.addWidget(hero)

        # ── 修复日志流（direction A：看得见的自修复）──
        log_card = RoundedCard(radius=12)
        log_card.setMinimumHeight(88)
        log_card.setMaximumHeight(140)
        ll2 = QVBoxLayout(log_card)
        ll2.setContentsMargins(20, 10, 20, 10)
        ll2.setSpacing(6)
        log_head = QHBoxLayout()
        log_title = QLabel(t("home.repair_log"))
        log_title.setProperty("cls", "group")
        log_head.addWidget(log_title)
        log_head.addStretch(1)
        self.log_clear_btn = QPushButton(t("home.repair_log_clear"))
        self.log_clear_btn.setProperty("cls", "sub")
        self.log_clear_btn.setCursor(Qt.PointingHandCursor)
        self.log_clear_btn.setStyleSheet("font-size: 11px; border: none; background: transparent;")
        self.log_clear_btn.clicked.connect(self._clear_repair_log)
        log_head.addWidget(self.log_clear_btn)
        ll2.addLayout(log_head)
        self.log_stream = QLabel(t("home.repair_log_empty"))
        self.log_stream.setProperty("cls", "sub")
        self.log_stream.setWordWrap(True)
        self.log_stream.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ll2.addWidget(self.log_stream, stretch=1)
        lay.addWidget(log_card)

        # ── 快捷操作行 ──
        actions = QHBoxLayout()
        actions.setSpacing(10)
        # 第一个按钮 accent 色突出"扫描"——玩家最常用的入口
        # 注意：底部"扫描实例"chip 与顶部"扫描接管"按钮功能重复。
        # 顶部 CTA 是从其他启动器（PCL2/HMCL/MultiMC…）接管实例，
        # 底部这里改成"刷新列表"——从磁盘重新读取已存在的实例清单，
        # 便于玩家手动拷入新实例目录后立即可见，无需重启 AC。
        actions.addWidget(self._quick_chip("refresh", t("home.refresh_list"), self._refresh_instances))
        actions.addWidget(self._quick_chip("instances", t("nav.instances"), self._open_instances))
        actions.addWidget(self._quick_chip("download", t("nav.versions"), self._open_versions))
        actions.addWidget(self._quick_chip("settings", t("nav.settings"), self._open_settings))
        actions.addStretch(1)
        lay.addLayout(actions)

    def _stat_cell(self, layout, value: str, label: str) -> QLabel:
        """One statistic cell (big number + caption) in the 统御统计条."""
        from PySide6.QtWidgets import QVBoxLayout as _VL
        cell = QWidget()
        cl = _VL(cell)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        # 数字标签：cls=big 给 QSS 配色 + 显式 setStyleSheet 兜底（避免 cls 属性
        # 在某些主题下不生效导致深色背景看不清）。同时 setMinimumWidth 给数字固定
        # 列宽避免 0/1/2/10 切换时整列跳动。
        v = QLabel(value)
        v.setProperty("cls", "big")
        v.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        v.setAlignment(Qt.AlignCenter)
        v.setMinimumWidth(72)
        # 显式配色兜底：跟随当前主题（dark/light）的 text_main
        from .theme import COLORS as _C
        v.setStyleSheet(
            f"color: {_C['text_main']}; font-size: 22px; font-weight: 700;"
        )
        cl.addWidget(v)
        cap = QLabel(label)
        cap.setProperty("cls", "sub")
        cap.setStyleSheet(
            f"font-size: 11px; color: {_C['text_sub']};"
        )
        cap.setAlignment(Qt.AlignCenter)
        cap.setWordWrap(True)
        cl.addWidget(cap)
        layout.addWidget(cell)
        return v

    def _build_pcl_card(self, lay):
        """PCL2 主页（像素级对齐截图）。

        布局复刻自 PCL2 真实界面（图2）：
        ┌─────────────────────────────────────────────┐
        │  ┌────左栏(~280px)────┐  ┌──右栏(壁纸)───┐  │
        │  │     [头像]         │  │               │  │
        │  │    Mists_Star      │  │  你知道吗 💡   │  │
        │  │    正版验证        │  │  ...提示文字..│  │
        │  │  ┌──────────────┐  │  │               │  │
        │  │  │  ▶ 启动游戏   │  │  │   壁纸背景    │  │
        │  │  │  版本号...    │  │  │               │  │
        │  │  └──────────────┘  │  │               │  │
        │  │ [实例选择][实例设置]│  │               │  │
        │  └────────────────────┘  └───────────────┘  │
        └─────────────────────────────────────────────┘
        """
        # ── 水平分割：左控制面板 + 右壁纸区 ──
        split = QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)

        # ═══ 左侧面板（固定宽度，浅色卡片）═══
        left_panel = RoundedCard(radius=12)
        left_panel.setMinimumWidth(280)
        left_panel.setMaximumWidth(320)
        ll = QVBoxLayout(left_panel)
        ll.setContentsMargins(24, 28, 24, 28)
        ll.setSpacing(14)
        ll.setAlignment(Qt.AlignCenter)

        # ── 头像区域（显示皮肤头像，无皮肤时用默认图标）──
        avatar_container = QWidget()
        avatar_container.setFixedSize(80, 80)
        av_lay = QVBoxLayout(avatar_container)
        av_lay.setContentsMargins(0, 0, 0, 0)
        self.pcl_avatar_lbl = QLabel()
        self.pcl_avatar_lbl.setAlignment(Qt.AlignCenter)
        self.pcl_avatar_lbl.setFixedSize(64, 64)
        self.pcl_avatar_lbl.setToolTip(t("pcl.avatar_hint", default="玩家头像"))
        av_lay.addWidget(self.pcl_avatar_lbl, alignment=Qt.AlignCenter)
        ll.addWidget(avatar_container, alignment=Qt.AlignCenter)

        # 用户名
        username = QLabel("Player")
        username.setProperty("cls", "big")
        username.setAlignment(Qt.AlignCenter)
        username.setFont(QFont("Segoe UI", 15, QFont.Weight.DemiBold))
        ll.addWidget(username, alignment=Qt.AlignCenter)
        self.pcl_username = username

        # 验证状态
        auth_status = QLabel(t("pcl.auth_pending", default="验证中…"))
        auth_status.setProperty("cls", "sub")
        auth_status.setAlignment(Qt.AlignCenter)
        auth_status.setFont(QFont("Segoe UI", 10))
        ll.addWidget(auth_status, alignment=Qt.AlignCenter)
        self.pcl_auth_status = auth_status

        ll.addSpacing(12)

        # ── 大启动按钮（PCL2 标志性：描边风格、全宽、高50+）──
        play_btn = self._make_play_btn()
        play_btn.setMinimumHeight(52)
        play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn = play_btn
        ll.addWidget(play_btn)

        # 版本号（按钮下方小字）
        ver_text = QLabel("")
        ver_text.setProperty("cls", "sub")
        ver_text.setAlignment(Qt.AlignCenter)
        ver_text.setFont(QFont("Segoe UI", 9))
        ll.addWidget(ver_text)
        self.pcl_ver_text = ver_text

        ll.addSpacing(8)

        # ── 实例选择 / 实例设置（并排两按钮）──
        inst_row = QHBoxLayout()
        inst_row.setSpacing(10)

        sel_btn = QPushButton(t("pcl.instance_select", default="实例选择"))
        sel_btn.setProperty("cls", "diag_btn")
        sel_btn.setCursor(Qt.PointingHandCursor)
        sel_btn.setMinimumHeight(36)
        sel_btn.clicked.connect(self._open_instances)
        inst_row.addWidget(sel_btn)

        cfg_btn = QPushButton(t("pcl.instance_config", default="实例设置"))
        cfg_btn.setProperty("cls", "diag_btn")
        cfg_btn.setCursor(Qt.PointingHandCursor)
        cfg_btn.setMinimumHeight(36)
        cfg_btn.clicked.connect(self._open_settings)
        inst_row.addWidget(cfg_btn)

        ll.addLayout(inst_row)
        ll.addStretch(1)

        split.addWidget(left_panel)

        # ═══ 右侧面板（壁纸 + 可选浮动提示卡）═══
        right_panel = QFrame()
        right_panel.setObjectName("pcl_right_panel")
        right_panel.setStyleSheet("#pcl_rightPanel { background: transparent; }")
        rl = QVBoxLayout(right_panel)
        rl.setContentsMargins(16, 16, 16, 16)
        rl.setSpacing(0)

        # 「你知道吗」提示卡（右上角浮动）
        tip_card = RoundedCard(radius=12)
        tip_card.setMaximumHeight(120)
        tip_lay = QVBoxLayout(tip_card)
        tip_lay.setContentsMargins(16, 12, 16, 12)
        tip_lay.setSpacing(6)

        tip_header = QHBoxLayout()
        tip_title = QLabel(t("pcl.did_you_know", default="你知道吗"))
        tip_title.setProperty("cls", "body-bold")
        tip_header.addWidget(tip_title)
        tip_header.addStretch(1)
        refresh_icon = QLabel("🔄")
        refresh_icon.setCursor(Qt.PointingHandCursor)
        refresh_icon.setToolTip(t("pcl.tip_refresh", default="换一条提示"))
        tip_header.addWidget(refresh_icon)
        tip_lay.addLayout(tip_header)

        tip_body = QLabel(t("pcl.tip_default",
            default="按 Ctrl+W 可以在游戏中唤醒启动器窗口。"))
        tip_body.setProperty("cls", "sub")
        tip_body.setWordWrap(True)
        tip_lay.addWidget(tip_body)

        rl.addWidget(tip_card, alignment=Qt.AlignTop | Qt.AlignRight)
        rl.addStretch(1)

        split.addWidget(right_panel, stretch=1)

        lay.addLayout(split, stretch=1)

    def _build_hmcl_list(self, lay):
        self._title_block(lay)
        lay.addWidget(self._instance_card())
        self.play_btn = self._list_row("play", t("home.play"), "", self._on_play)
        lay.addWidget(self.play_btn)
        lay.addWidget(self._list_row("search", t("scan.title"), "", self._open_scan))
        lay.addWidget(self._list_row("settings", t("nav.settings"), "", self._open_settings))

    def _build_modrinth(self, lay):
        self._title_block(lay)
        grad = QLinearGradient(0, 0, 1, 1)
        grad.setCoordinateMode(QLinearGradient.ObjectBoundingMode)
        grad.setColorAt(0, QColor(COLORS["accent"]))
        grad.setColorAt(1, QColor(COLORS["accent_press"]))
        panel = RoundedCard(radius=16, fill=grad)
        panel.setMinimumHeight(168)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(24, 22, 24, 22)
        pl.setSpacing(10)
        ft = QLabel(t("home.featured"))
        ft.setStyleSheet("color: rgba(255,255,255,0.92); font-weight: 600; font-size: 13px;")
        pl.addWidget(ft)
        self.inst_lbl = QLabel("—")
        self.inst_lbl.setStyleSheet("color: #FFFFFF; font-weight: 700; font-size: 22px;")
        pl.addWidget(self.inst_lbl)
        self.detail_lbl = QLabel("")
        self.detail_lbl.setStyleSheet("color: rgba(255,255,255,0.8);")
        pl.addWidget(self.detail_lbl)
        self.play_btn = self._make_play_btn()
        self.play_btn.setStyleSheet(
            "background: #FFFFFF; color: #1F2937; border-radius: 10px; font-weight: 700;")
        pl.addWidget(self.play_btn)
        lay.addWidget(panel)
        pills = QHBoxLayout()
        pills.setSpacing(10)
        pills.addWidget(self._list_row("search", t("scan.title"), "", self._open_scan))
        pills.addWidget(self._list_row("settings", t("nav.settings"), "", self._open_settings))
        pills.addWidget(self._list_row("instances", t("nav.instances"), "", self._open_instances))
        lay.addLayout(pills)

    # ── navigation callbacks ──
    def _open_settings(self):
        if self.on_open_settings:
            self.on_open_settings()

    def _open_instances(self):
        if self.on_open_instances:
            self.on_open_instances()

    def _open_versions(self):
        if self.on_open_versions:
            self.on_open_versions()

    def _refresh_instances(self):
        """Re-read the instance list from disk and repaint the home page.

        Triggered by the bottom-row "刷新列表" chip — distinct from the
        top-right "扫描接管" CTA which actively scans other launchers.
        """
        if self.inst_mgr is None:
            return
        try:
            self.inst_mgr.refresh()
        except Exception:
            pass  # never let a bad instances.json break the home view
        self._refresh()

    def _open_mods(self):
        if self.on_open_mods:
            self.on_open_mods()

    def _label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setProperty("cls", "sub")
        return l

    @staticmethod
    def _alive(w) -> bool:
        """True only if *w* is a still-live C++ widget.

        ``_clear_layout()`` synchronously deletes widgets of the previous
        template, but the Python attributes (``self.inst_lbl`` etc.) keep
        pointing at the dead C++ objects. ``hasattr`` cannot detect that —
        only ``shiboken6.isValid`` can — so every template-specific widget
        must pass through here before use.
        """
        if w is None:
            return False
        try:
            from shiboken6 import isValid
            return isValid(w)
        except Exception:  # noqa: BLE001 - never fail the refresh on a probe
            return True

    def _refresh(self) -> None:
        inst = self.get_current_instance()
        instances = self.list_instances()

        # ── 统御统计条（direction A）──
        self._refresh_stats(instances)

        # inst_combo exists only in templates that build an instance
        # selector (ac_default). After a template switch its Python attr may
        # dangle onto a deleted C++ object — guard everything.
        if hasattr(self, "inst_combo") and self._alive(self.inst_combo):
            # Block signals while populating to avoid spurious _on_inst_changed
            self.inst_combo.blockSignals(True)
            self.inst_combo.clear()
            cur_id = inst.id if inst else ""
            for i in instances:
                self.inst_combo.addItem(i.name, i.id)
                if i.id == cur_id:
                    self.inst_combo.setCurrentIndex(self.inst_combo.count() - 1)
            # If no current instance matches, prepend a "select" placeholder
            if not inst and instances:
                self.inst_combo.insertItem(0, t("home.select_instance"), "")
                self.inst_combo.setCurrentIndex(0)
            elif not instances:
                self.inst_combo.addItem(t("home.no_instance"), "")
            self.inst_combo.blockSignals(False)

        if inst is None:
            if hasattr(self, "inst_lbl") and self._alive(self.inst_lbl):
                self.inst_lbl.setText("—")
            if hasattr(self, "src_badge") and self._alive(self.src_badge):
                self.src_badge.setVisible(False)
            if hasattr(self, "detail_lbl") and self._alive(self.detail_lbl):
                self.detail_lbl.setText("")
            if hasattr(self, "play_btn") and self._alive(self.play_btn):
                self.play_btn.setEnabled(False)
            # PCL2 模板字段
            if hasattr(self, "pcl_username") and self._alive(self.pcl_username):
                self.pcl_username.setText("Player")
            if hasattr(self, "pcl_ver_text") and self._alive(self.pcl_ver_text):
                self.pcl_ver_text.setText("")
            self._refresh_pcl_avatar()
            return

        if hasattr(self, "play_btn") and self._alive(self.play_btn):
            self.play_btn.setEnabled(True)
        if hasattr(self, "inst_lbl") and self._alive(self.inst_lbl):
            self.inst_lbl.setText(inst.name)
        # 来源徽章：显示实例从哪个启动器接管（AC 创建的显示"AC"）
        if hasattr(self, "src_badge") and self._alive(self.src_badge):
            src = getattr(inst, "launcher", "AC") or "AC"
            if src == "AC":
                self.src_badge.setVisible(False)
            else:
                self.src_badge.setText(t("home.src_badge", launcher=src))
                self.src_badge.setVisible(True)
        if hasattr(self, "detail_lbl") and self._alive(self.detail_lbl):
            self.detail_lbl.setText(
                f"{t('home.version')} {inst.game_version}  ·  "
                f"{t('home.loader')} {inst.loader}"
            )

        # ── PCL2 模板专属字段填充 ──
        if hasattr(self, "pcl_username") and self._alive(self.pcl_username):
            self.pcl_username.setText(inst.name or "Player")
        if hasattr(self, "pcl_ver_text") and self._alive(self.pcl_ver_text):
            ver_str = f"{inst.game_version or '?'}"
            if inst.loader and inst.loader.lower() not in ("vanilla", ""):
                ver_str += f"  ·  {inst.loader}"
            self.pcl_ver_text.setText(ver_str)

    def _on_play(self):
        inst = self.get_current_instance()
        if inst is None:
            return
        self.play_btn.setEnabled(False)
        self.on_play(inst)

    def _refresh_pcl_avatar(self):
        """PCL2 template avatar: skin head (or default account icon).

        Uses the global skin/account managers so the HomePage can render the
        logged-in player's head without a direct reference to MainWindow.
        """
        if not hasattr(self, "pcl_avatar_lbl") or not self._alive(self.pcl_avatar_lbl):
            return
        try:
            acc = accounts_manager().current()
            path = skin_manager().active_path(acc["id"]) if acc else None
            if path and os.path.exists(path):
                self.pcl_avatar_lbl.setPixmap(render_head(path, 64))
            else:
                self.pcl_avatar_lbl.setPixmap(icon("account").pixmap(64, 64))
        except Exception:
            pass

    def _refresh_stats(self, instances):
        """Update the 统御统计条 (direction A): taken instances / source
        launchers / instances with crash reports (待修复)."""
        if not (hasattr(self, "stat_instances") and self._alive(self.stat_instances)):
            return
        taken = len(instances)
        sources = set()
        needs_repair = 0
        for i in instances:
            src = getattr(i, "launcher", "AC") or "AC"
            if src != "AC":
                sources.add(src)
            # 轻量待修复判据：实例目录存在 crash-reports 或 logs/latest.log 有 ERROR
            try:
                mc = i.mc_dir
                if os.path.isdir(os.path.join(mc, "crash-reports")):
                    cr = os.path.join(mc, "crash-reports")
                    if any(os.path.getsize(os.path.join(cr, f)) > 0
                           for f in os.listdir(cr)):
                        needs_repair += 1
                        continue
                logf = os.path.join(mc, "logs", "latest.log")
                if os.path.isfile(logf) and os.path.getsize(logf) > 0:
                    with open(logf, "r", encoding="utf-8", errors="ignore") as f:
                        tail = f.read()[-20000:]
                    if "ERROR" in tail or "Exception" in tail:
                        needs_repair += 1
            except Exception:
                pass
        self.stat_instances.setText(str(taken))
        self.stat_sources.setText(str(len(sources)))
        self.stat_repair.setText(str(needs_repair))
        self._refresh_repair_log()

    def _refresh_repair_log(self):
        """Fill the home repair-log stream with recent auto-repair entries."""
        if not (hasattr(self, "log_stream") and self._alive(self.log_stream)):
            return
        from .repair_log import list_recent
        entries = list_recent(8)
        if not entries:
            self.log_stream.setText(t("home.repair_log_empty"))
            return
        import datetime as _dt
        lines = []
        for e in entries:
            ts = _dt.datetime.fromtimestamp(e.get("t", 0)).strftime("%H:%M")
            summary = e.get("summary", "")
            inst = e.get("instance", "")
            text = f"[{ts}] {summary}"
            if inst:
                text += f"  ·  {inst}"
            lines.append(text)
        self.log_stream.setText("\n".join(lines))

    def _clear_repair_log(self):
        from .repair_log import clear
        clear()
        self._refresh_repair_log()

    def _open_scan(self):
        from .scan_dialog import ScanDialog

        ScanDialog(self).exec()
        # 成就：接管了来自其他启动器的实例
        from .achievements import achievements as _ach
        non_ac = [i for i in self.inst_mgr.list() if getattr(i, "launcher", "AC") != "AC"]
        if non_ac:
            _ach.unlock("first_instance")
            if len(non_ac) >= 3:
                _ach.unlock("takeover_3")
        # Defer refresh so any pending focus-change / nav signals from the
        # dialog teardown fire FIRST.  Without this delay, _refresh() can run
        # and then _on_nav → _refresh() fires again immediately after,
        # causing duplicate UI if rebuild() is also in the call chain.
        QTimer.singleShot(100, self._refresh)

    def _apply_wallpaper(self, cfg: dict | None = None):
        """Re-apply the backdrop (solid / image / animated GIF / video)."""
        if cfg is not None:
            self.cfg = cfg
        try:
            self.backdrop.apply(self.cfg)
            self.backdrop.setGeometry(self.rect())
            self.backdrop.lower()
        except Exception:  # noqa: BLE001 - a bad wallpaper must not kill the page
            pass


class _TitleBarDragFilter(QObject):
    """Direct drag handling for the main window's custom title bar.

    ``FramelessHelper`` listens on the top-level window and only sees mouse
    events that propagate *up* from children. That propagation is unreliable
    in Qt6 — so the dialog ``TitleBar`` class handles the press itself. This
    filter does the same for the main-window bar: installed on the bar,
    press = native window move, double-click = maximize toggle. Edge zone
    (top 6 px) is left to FramelessHelper for resize.
    """

    def __init__(self, window: "MainWindow", bar: QWidget):
        super().__init__(bar)
        self._window = window
        self._bar = bar
        bar.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is not self._bar:
            return False
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if pos.y() < 6:            # resize zone — FramelessHelper's job
                return False
            if isinstance(self._bar.childAt(pos), QPushButton):
                return False           # buttons handle their own clicks
            try:
                self._window.startSystemMove()
            except AttributeError:
                pass
            return True
        if etype == QEvent.Type.MouseButtonDblClick and event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if pos.y() >= 6 and not isinstance(self._bar.childAt(pos), QPushButton):
                self._window._toggle_max()
                return True
        return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_DISPLAY)
        _icon_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "icons")
        _icon_path = None
        for _ext in ("png", "ico"):
            _p = os.path.normpath(os.path.join(_icon_base, f"logo.{_ext}"))
            if os.path.isfile(_p):
                _icon_path = _p
                break
        if _icon_path:
            # Windows taskbar needs multiple sizes; QIcon auto-scales but we
            # explicitly add common sizes so the preview thumbnail and alt-tab
            # both render crisply.
            ico = QIcon(_icon_path)
            for _sz in (16, 24, 32, 48, 64, 128, 256):
                ico.addPixmap(QIcon(_icon_path).pixmap(_sz, _sz))
            self.setWindowIcon(ico)
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)

        self.inst_mgr = manager()
        self.accounts_manager = accounts_manager()
        self.current_account = self.accounts_manager.current()
        self._play_worker = None
        self.cfg = load_config()

        # Round window corners on Win11 — call after the native window exists.
        # Safe no-op elsewhere (the function checks the platform itself).
        enable_win11_round_corners(self)

        # The app chime spins up QMediaPlayer, which costs a few hundred ms on
        # first use. Doing that here froze the splash animation, so it is
        # deferred until after the window is on screen.
        QTimer.singleShot(0, self._play_app_chime)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── full-width custom title bar (drag area + window controls) ──
        self.titlebar = self._build_titlebar()
        root.addWidget(self.titlebar)
        # Drag handled directly on the bar (FramelessHelper's top-level filter
        # cannot reliably see presses that start on a child widget).
        self._titlebar_drag = _TitleBarDragFilter(self, self.titlebar)

        # ── body: nav + right content (both start below the title bar) ──
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ---- right column: content stack (shared by both nav layouts) ----
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        self.stack = QStackedWidget()
        self.home = HomePage(
            on_play=self._handle_play,
            get_current_instance=self.current_instance,
            cfg=self.cfg,
            on_open_settings=self._open_settings,
            on_open_instances=lambda: self._show_page("instances"),
            on_open_versions=lambda: self._show_page("versions"),
            on_open_mods=lambda: self._show_page("mods"),
            list_instances=lambda: self.inst_mgr.list(),
            set_current_instance=lambda _id: self.inst_mgr.set_current(_id),
        )
        self.stack.addWidget(self.home)  # 0 Home

        _yield()
        self.instances_page = InstancesPage()
        self.instances_page.current_changed.connect(self._on_current_changed)
        # 详情页"内容分区"按钮 → 跳到对应页面并预设实例（Mods 等页面有实例选择器）
        self.instances_page.section_requested.connect(self._on_instance_section)
        self.stack.addWidget(self.instances_page)  # 1
        _yield()

        self.mods_page = ModsPage(
            list_instances=lambda: self.inst_mgr.list(),
            get_current_instance=self.current_instance,
        )
        self.stack.addWidget(self.mods_page)  # 2
        _yield()

        self.store_page = StorePage(
            list_instances=lambda: self.inst_mgr.list(),
            get_current_instance=self.current_instance,
        )
        self.stack.addWidget(self.store_page)  # 3
        _yield()

        self.versions_page = VersionsPage()
        self.versions_page.instance_created.connect(self._on_instance_created)
        self.stack.addWidget(self.versions_page)  # 4
        _yield()

        # ── Lobby (page 5) ──
        self.lobby_widget = QWidget()
        ll = QVBoxLayout(self.lobby_widget)
        ll.setContentsMargins(24, 24, 24, 24)
        ll.setSpacing(16)

        lh = QLabel(t("lobby.title"))
        lh.setProperty("cls", "title")
        ll.addWidget(lh)
        self._lobby_title = lh

        self._lobby_join_help = QLabel(t("lobby.join_help"))
        ll.addWidget(self._lobby_join_help)

        # Quick action buttons
        btn_row = QHBoxLayout()
        join_q_btn = QPushButton(t("lobby.join"))
        join_q_btn.setMinimumHeight(40)
        join_q_btn.setIcon(icon("login"))
        join_q_btn.setIconSize(QSize(18, 18))
        join_q_btn.clicked.connect(self._open_lobby)
        btn_row.addWidget(join_q_btn)
        self._lobby_join = join_q_btn

        create_q_btn = QPushButton(t("lobby.create"))
        create_q_btn.setProperty("cls", "accent")
        create_q_btn.setMinimumHeight(40)
        create_q_btn.setIcon(icon("add"))
        create_q_btn.setIconSize(QSize(18, 18))
        create_q_btn.clicked.connect(self._open_lobby)
        btn_row.addWidget(create_q_btn)
        self._lobby_create = create_q_btn
        ll.addLayout(btn_row)

        self._lobby_create_help = QLabel(t("lobby.create_help"))
        ll.addWidget(self._lobby_create_help)
        ll.addStretch(1)
        self.stack.addWidget(self.lobby_widget)  # 5

        # ── Settings (page 6) — embedded, no more popup dialog ──
        self.settings_page = SettingsPage()
        self.settings_page._window = self  # live-refresh hook
        self.settings_page.saved.connect(self._on_settings_saved)
        self.settings_page.close_requested.connect(lambda: self._show_page("home"))
        self.stack.addWidget(self.settings_page)  # 6

        # ── Toolbox placeholder (page 7) — PCL2 工具/百宝箱 右栏内容 ──
        self.toolbox_widget = QWidget()
        _tb = QVBoxLayout(self.toolbox_widget)
        _tb.setContentsMargins(24, 24, 24, 24)
        _tb.setSpacing(16)
        _tbh = QLabel(t("pcl2.toolbox_title"))
        _tbh.setProperty("cls", "title")
        _tb.addWidget(_tbh)
        _tbs = QLabel(t("pcl2.toolbox_empty"))
        _tbs.setProperty("cls", "sub")
        _tb.addWidget(_tbs)
        _tb.addStretch(1)
        self.stack.addWidget(self.toolbox_widget)  # 7

        # ── Music player (page 8) — direction B 彩蛋 ──
        from .music_page import MusicPage
        self.music_page = MusicPage()
        self.stack.addWidget(self.music_page)  # 8

        # ── Achievements (page 9) — direction B 彩蛋 ──
        from .achievements_page import AchievementsPage
        self.achievements_page = AchievementsPage()
        self.stack.addWidget(self.achievements_page)  # 9

        right.addWidget(self.stack, stretch=1)

        # ── nav (layout-specific; both layouts share the stack above) ──
        self.nav_layout = self.cfg.get("nav_layout", "ac")
        if self.nav_layout == "pcl2":
            self._build_pcl2_nav(root, body)
        else:
            self._build_ac_nav(body)

        body.addLayout(right, stretch=1)
        root.addLayout(body, stretch=1)

        # ── status bar with progress ──
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(220)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self.statusBar().addPermanentWidget(self._progress)
        self.statusBar().showMessage(t("status.ready"))
        ver = QLabel(f"{APP_DISPLAY}  {APP_VERSION}")
        ver.setProperty("cls", "sub")
        self.statusBar().addPermanentWidget(ver)

        # ── Frameless: no native window chrome ──
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)

        # Restore geometry AFTER frameless flags are applied — otherwise
        # setWindowFlags() inside FramelessHelper resets the position.
        self._restore_geometry()

        # ── Achievement toast (direction B 彩蛋) ──
        from .achievements import achievements as _ach
        _ach.toast.connect(self._show_achievement_toast)

    def _show_achievement_toast(self, aid: str):
        """Transient toast in the bottom-right corner on achievement unlock."""
        try:
            from .achievements import ACHIEVEMENTS
            from .i18n import t as _t
            title = _t(ACHIEVEMENTS[aid][0])
            desc = _t(ACHIEVEMENTS[aid][1])
        except Exception:
            return
        toast = RoundedCard(radius=10, fill=QColor(COLORS["bg_panel"]),
                            accent_border=3)
        tl = QVBoxLayout(toast)
        tl.setContentsMargins(16, 10, 16, 10)
        tl.setSpacing(2)
        h = QLabel("🏆  " + _t("ach.toast_title"))
        h.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {COLORS['accent']};")
        tl.addWidget(h)
        n = QLabel(title)
        n.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLORS['text_main']};")
        tl.addWidget(n)
        d = QLabel(desc)
        d.setStyleSheet(f"font-size: 11px; color: {COLORS['text_sub']};")
        tl.addWidget(d)
        toast.adjustSize()
        toast.move(self.width() - toast.width() - 24, self.height() - toast.height() - 48)
        toast.show()
        toast.raise_()
        QTimer.singleShot(3600, toast.deleteLater)

    def _play_app_chime(self):
        """Signature chime on app start (no-op if disabled / trigger != app)."""
        try:
            from .core.sound import play_launch_sound, start_bgm

            play_launch_sound("app", self.cfg)
            start_bgm(self.cfg)
        except Exception:  # noqa: BLE001 - audio must never block the app
            pass

    # ---- shared state ----
    def current_instance(self) -> Instance | None:
        return self.inst_mgr.current()

    def _on_current_changed(self, _id: str):
        self.mods_page.refresh()
        self.home._refresh()

    def _on_instance_section(self, section: str, inst_id: str):
        """Jump to the section page and pre-target the instance."""
        # 预设实例：让 Mods 页等带实例选择器的页面直接切到该实例
        if hasattr(self, "mods_page"):
            insts = self.inst_mgr.list()
            for i in insts:
                if i.id == inst_id:
                    self.inst_mgr.set_current(inst_id)
                    break
        idx = STACK_INDEX.get("mods", 2)
        if idx is not None and 0 <= idx < self.stack.count():
            self._switch_stack(idx)
        if hasattr(self, "mods_page"):
            self.mods_page.refresh()

    def _on_instance_created(self, _id: str):
        from .achievements import achievements as _ach
        _ach.unlock("first_instance")
        if len(self.inst_mgr.list()) >= 5:
            _ach.unlock("five_instances")
        if self.nav_layout == "pcl2":
            self._pcl2_goto("instances")
        else:
            self.nav.setCurrentRow(self._nav_row("instances"))

    def _set_progress(self, value: int, maximum: int):
        if maximum and maximum > 0:
            self._progress.setMaximum(maximum)
            self._progress.setValue(value)
        else:
            self._progress.setMaximum(0)  # indeterminate
        self._progress.setVisible(True)

    # ---- top bar (full width, custom title bar) ----
    def _build_titlebar(self):
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setProperty("cls", "titlebar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 8, 0)
        lay.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(icon("logo").pixmap(30, 30))
        logo.setFixedSize(32, 32)
        logo.setStyleSheet("padding-left: 2px;")
        lay.addWidget(logo)
        name = QLabel(APP_DISPLAY)
        name.setProperty("cls", "big")
        name.setStyleSheet(f"color: {COLORS['accent']}; font-weight: 600; font-size: 15px;")
        lay.addWidget(name)
        lay.addStretch(1)

        # ── Account button (dropdown menu for switch / add / remove) ──
        self.account_btn = QPushButton(t("topbar.login"))
        self.account_btn.setMinimumHeight(34)
        self.account_btn.setIcon(icon("account"))
        self.account_btn.setIconSize(QSize(16, 16))
        if self.current_account:
            self.account_btn.setText(self.current_account.get("name", t("topbar.login")))
        # Click behavior depends on login state (handled in _on_account_btn):
        #  - no account → open the login dialog directly (no menu)
        #  - has account → pop the dropdown (switch / skin / remove / add)
        self.account_menu = QMenu(self)
        self.account_menu.aboutToShow.connect(self._build_account_menu)
        self.account_btn.clicked.connect(self._on_account_btn_clicked)
        lay.addWidget(self.account_btn)

        # ── Diagnostics & repair ──
        self.diag_btn = QPushButton()
        self.diag_btn.setIcon(icon("repair"))
        self.diag_btn.setIconSize(QSize(18, 18))
        self.diag_btn.setFixedSize(38, 34)
        self.diag_btn.setToolTip(t("diag.title"))
        self.diag_btn.setCursor(Qt.PointingHandCursor)
        self.diag_btn.setProperty("cls", "icon-btn")
        self.diag_btn.clicked.connect(self._open_diagnostics)
        lay.addWidget(self.diag_btn)

        # ── Window controls (frameless) ──
        ctrl_base = (
            "QPushButton { background: transparent; border: none; "
            "font-size: 18px; color: #9CA3B0; }"
            "QPushButton:hover { background: #33333A; color: #E5E5E5; }"
        )
        close_hover = (
            "QPushButton#win_close:hover "
            "{ background: #EF4444; color: #FFFFFF; }"
        )
        for name, txt, slot in [
            ("min", "—", self.showMinimized),
            ("max", "□", self._toggle_max),
            ("close", "✕", self.close),
        ]:
            btn = QPushButton(txt)
            btn.setObjectName(f"win_{name}")
            btn.setFixedSize(48, 40)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            btn.setStyleSheet(ctrl_base + (close_hover if name == "close" else ""))
            lay.addWidget(btn)

        return bar

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ── launcher window geometry persistence ──
    def _restore_geometry(self):
        """Re-apply the saved window size / position / maximized state."""
        if self.cfg.get("win_maximized"):
            self.showMaximized()
            return
        geo = self.cfg.get("win_geometry")
        if isinstance(geo, (list, tuple)) and len(geo) == 4:
            x, y, w, h = (int(v) for v in geo)
            if w >= 900 and h >= 600:
                self.setGeometry(x, y, w, h)

    def closeEvent(self, event):
        """Persist the launcher window geometry so the next launch restores it."""
        try:
            self.cfg["win_maximized"] = self.isMaximized()
            if not self.isMaximized():
                g = self.geometry()
                self.cfg["win_geometry"] = list(g.getRect())
            save_config(self.cfg)
        except Exception:  # noqa: BLE001 - geometry save must never block exit
            pass
        super().closeEvent(event)

    # ── AC layout: left vertical nav (the historical default) ──
    def _build_ac_nav(self, body: QHBoxLayout):
        nav = QListWidget()
        nav.setFixedWidth(200)
        nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav.setIconSize(QSize(20, 20))
        nav.currentRowChanged.connect(self._on_nav)
        self.nav = nav
        self._populate_ac_nav()
        body.addWidget(nav)

    def _populate_ac_nav(self):
        """(Re)build the grouped left sidebar.

        Group headers are non-selectable rows (NoItemFlags) with a small grey
        label, mirroring how HMCL/PCL2 split the navigation into zones. The
        row → key mapping is rebuilt here because headers occupy rows.
        """
        nav = self.nav
        nav.blockSignals(True)
        nav.clear()
        self._nav_row_map: dict[int, str] = {}
        for group_title, items in NAV_GROUPS:
            if group_title is not None:
                hdr = QListWidgetItem()
                hdr.setFlags(Qt.NoItemFlags)          # not clickable
                hdr.setSizeHint(QSize(0, 26))
                nav.addItem(hdr)
                hlabel = QLabel("   " + t(group_title))
                hlabel.setProperty("cls", "nav-group")
                nav.setItemWidget(hdr, hlabel)
            for label_key, key in items:
                nav.addItem(QListWidgetItem(icon(key), t(label_key)))
                self._nav_row_map[nav.count() - 1] = key
        # select the home row (first entry, no header above it → row 0)
        nav.setCurrentRow(0)
        nav.blockSignals(False)

    def _nav_row(self, key: str) -> int:
        for r, k in self._nav_row_map.items():
            if k == key:
                return r
        return 0

    # ── PCL2 layout: top horizontal pill bar + context-aware left sidebar ──
    def _build_pcl2_nav(self, root: QVBoxLayout, body: QHBoxLayout):
        # Top pill bar (启动 / 下载 / 设置 / 工具).
        top = QWidget()
        top.setFixedHeight(52)
        top.setProperty("cls", "pcl2-top")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 8, 16, 8)
        tl.setSpacing(8)
        tl.addStretch(1)
        self._pcl2_top_btns: dict[str, QPushButton] = {}
        self._pcl2_top_labels: dict[str, str] = {}
        self._pcl2_last_sub: dict[str, str] = {}
        self._pcl2_active_top = "home"
        for label_key, key in PCL2_TOP:
            b = QPushButton(icon(key), t(label_key))
            b.setProperty("cls", "pcl2-pill")
            b.setCheckable(True)
            b.setMinimumHeight(36)
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda _c=False, k=key: self._pcl2_on_top(k))
            self._pcl2_top_btns[key] = b
            self._pcl2_top_labels[key] = label_key
            tl.addWidget(b)
        tl.addStretch(1)
        root.addWidget(top)

        # Context-aware left sidebar (hidden for tabs without sub-items).
        side = QListWidget()
        side.setFixedWidth(200)
        side.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side.setIconSize(QSize(20, 20))
        side.currentRowChanged.connect(self._pcl2_on_side)
        self.pcl2_side = side
        body.addWidget(side)

        self._pcl2_select_top("launch")

    def _pcl2_select_top(self, key: str):
        """Switch the active top pill and (re)build its context sidebar."""
        self._pcl2_active_top = key
        for k, b in self._pcl2_top_btns.items():
            b.setChecked(k == key)
        subs = PCL2_SIDEBAR.get(key, [])
        self.pcl2_side.blockSignals(True)
        self.pcl2_side.clear()
        if not subs:
            self.pcl2_side.setVisible(False)
            # No sidebar → the top pill maps directly to a page.
            #  settings → the settings page; online → placeholder.
            if key == "settings":
                self._pcl2_apply_sub("settings")
            else:
                self._pcl2_apply_sub(key)  # online → "敬请期待" placeholder
        else:
            self.pcl2_side.setVisible(True)
            for label_key, sub in subs:
                self.pcl2_side.addItem(QListWidgetItem(icon(sub), t(label_key)))
            # Restore the last-used sub-page for this tab, else the first one.
            last = self._pcl2_last_sub.get(key)
            idx = 0
            if last:
                for i, (_, s) in enumerate(subs):
                    if s == last:
                        idx = i
                        break
            self.pcl2_side.setCurrentRow(idx)
            self._pcl2_apply_sub(subs[idx][1])
        self.pcl2_side.blockSignals(False)

    def _pcl2_on_top(self, key: str):
        self._pcl2_select_top(key)

    def _pcl2_on_side(self, row: int):
        if row < 0:
            return
        subs = PCL2_SIDEBAR.get(self._pcl2_active_top, [])
        if 0 <= row < len(subs):
            key = subs[row][1]
            self._pcl2_last_sub[self._pcl2_active_top] = key
            self._pcl2_apply_sub(key)

    def _pcl2_apply_sub(self, key: str):
        """Show the stack page for a sidebar / top item (PCL2 layout)."""
        idx = STACK_INDEX.get(key)
        if idx is None:
            # No real page yet → show the "敬请期待" placeholder so the entry
            # is reachable but clearly marked as coming soon (用户方案：功能
            # 完全对标后面来，未实现的先预留入口)。
            self._show_pcl2_placeholder(key)
            return
        if key == "home":
            self.home._refresh()
        elif key == "settings":
            # Re-read config + rebuild so the page reflects external changes.
            self.settings_page.reload()
        self._switch_stack(idx)

    def _show_pcl2_placeholder(self, key: str):
        """Render a '敬请期待' page inside the PCL2 main area for features that
        don't exist yet (联机 / 更多 …). Keeps the top-pill reachable while the
        real page ships later."""
        if not hasattr(self, "_pcl2_placeholder_widget"):
            from PySide6.QtWidgets import QVBoxLayout, QLabel, QFrame
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(48, 40, 48, 40)
            lay.setSpacing(12)
            self._pcl2_ph_title = QLabel("")
            self._pcl2_ph_title.setProperty("cls", "title")
            lay.addWidget(self._pcl2_ph_title)
            self._pcl2_ph_body = QLabel("")
            self._pcl2_ph_body.setProperty("cls", "sub")
            self._pcl2_ph_body.setWordWrap(True)
            lay.addWidget(self._pcl2_ph_body)
            lay.addStretch(1)
            self._pcl2_placeholder_widget = w
            self.stack.addWidget(w)  # appended at the end
        # Map top-pill keys to readable titles via i18n.
        title_key = {
            "online": "pcl2.ph_online_title",
            "more": "pcl2.ph_more_title",
            "launch": "pcl2.ph_launch_title",
            "download": "pcl2.ph_download_title",
        }.get(key)
        body_key = {
            "online": "pcl2.ph_online_body",
            "more": "pcl2.ph_more_body",
            "launch": "pcl2.ph_launch_title",
            "download": "pcl2.ph_download_title",
        }.get(key)
        self._pcl2_ph_title.setText(t(title_key, default=key) if title_key else key)
        self._pcl2_ph_body.setText(t(body_key, default=t("pcl2.ph_default_body")) if body_key else t("pcl2.ph_default_body"))
        self.stack.setCurrentWidget(self._pcl2_placeholder_widget)

    def _pcl2_goto(self, key: str):
        """Programmatically jump to any page key from the PCL2 nav."""
        # home now lives under the "launch" top pill; settings is its own pill.
        if key == "home":
            self._pcl2_select_top("launch")
            for i, (_, s) in enumerate(PCL2_SIDEBAR.get("launch", [])):
                if s == "home":
                    self.pcl2_side.blockSignals(True)
                    self.pcl2_side.setCurrentRow(i)
                    self.pcl2_side.blockSignals(False)
                    self._pcl2_apply_sub("home")
                    return
            self._pcl2_apply_sub("home")
            return
        if key == "settings":
            self._pcl2_select_top("settings")
            return
        for top, subs in PCL2_SIDEBAR.items():
            for _, s in subs:
                if s == key:
                    self._pcl2_select_top(top)
                    for i, (_, s2) in enumerate(subs):
                        if s2 == key:
                            self.pcl2_side.blockSignals(True)
                            self.pcl2_side.setCurrentRow(i)
                            self.pcl2_side.blockSignals(False)
                            self._pcl2_apply_sub(key)
                            return

    def _on_nav(self, row: int):
        # Guard: QListWidget emits currentRowChanged(-1) when cleared (e.g. during
        # retranslate_ui) — never index a stale map with -1.
        if row < 0 or not hasattr(self, "_nav_row_map") or row not in self._nav_row_map:
            return
        key = self._nav_row_map[row]
        # Remember the row the user was on BEFORE clicking — used to restore
        # the nav highlight after a dialog (account / lobby) closes, so it
        # feels like a pop-up rather than a navigation.
        _PAGE_KEYS = ("home", "instances", "mods", "store", "versions",
                      "music", "achievements", "settings")
        if key in _PAGE_KEYS:
            self._last_page_row = row
        idx = {
            "home": 0, "instances": 1, "mods": 2, "store": 3,
            "versions": 4, "lobby": 5, "settings": 6, "music": 8,
            "achievements": 9,
        }.get(key)
        if idx is not None:
            if key == "home":
                self.home._refresh()
            elif key == "settings":
                # Re-read config + rebuild so the page reflects any external
                # changes (e.g. language switched in a previous session).
                self.settings_page.reload()
            self._switch_stack(idx)
            return
        # ── Dialog-only nav items (account / lobby): visually stay on the
        # previous page (no nav row jump to home), open the dialog, then
        # restore the content stack to whatever page the user came from. ──
        saved_idx = self.stack.currentIndex()
        prev_row = getattr(self, "_last_page_row", 0)
        # Block signals while we snap the nav back, otherwise the row
        # change would re-enter _on_nav and bounce the user around.
        self.nav.blockSignals(True)
        try:
            self.nav.setCurrentRow(prev_row)
        finally:
            self.nav.blockSignals(False)
        try:
            if key == "account":
                self._open_account()
            elif key == "lobby":
                self._open_lobby()
        except Exception:
            pass  # dialog failed — don't crash navigation

        def _restore_nav():
            if 0 <= saved_idx < self.stack.count():
                self._switch_stack(saved_idx)
            else:
                self._switch_stack(0)
                self.home._refresh()
        QTimer.singleShot(50, _restore_nav)

    def _switch_stack(self, idx: int):
        """Switch the content stack with a short fade-in (PCL2-style motion).

        Falls back to an instant switch if the target index is invalid or the
        window hasn't been shown yet (avoid animating during construction).
        """
        if not 0 <= idx < self.stack.count():
            return
        if idx == self.stack.currentIndex():
            return
        self.stack.setCurrentIndex(idx)
        page = self.stack.currentWidget()
        if page is None or not self.isVisible():
            return
        # Fade the incoming page in (opacity 0.25 → 1.0, 140ms).
        try:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            eff = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(140)
            anim.setStartValue(0.25)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def _cleanup():
                page.setGraphicsEffect(None)
                eff.deleteLater()

            anim.finished.connect(_cleanup)
            self._stack_anim = anim  # keep alive
            anim.start()
        except Exception:
            page.setGraphicsEffect(None)

    def _show_page(self, key: str):
        """Programmatically switch the content stack to the given nav key."""
        if self.nav_layout == "pcl2":
            self._pcl2_goto(key)
            return
        self.nav.setCurrentRow(self._nav_row(key))

    def apply_home_style(self, style_key: str):
        """Re-render the home page live with a new style (from settings / onboarding)."""
        self.cfg["home_style"] = style_key
        if hasattr(self, "home"):
            self.home.cfg = self.cfg
            self.home.rebuild()

    def _on_account_btn_clicked(self):
        """Top-bar account button: no account → straight to login; has account
        → pop the account menu (switch / skin / remove / add another)."""
        if self.current_account:
            self.account_menu.popup(
                self.account_btn.mapToGlobal(self.account_btn.rect().bottomLeft())
            )
        else:
            self._open_account()

    def _open_account(self):
        from .login_dialog import LoginDialog

        dlg = LoginDialog(self)
        dlg.exec()
        if dlg.account:
            self.current_account = dlg.account
            self.accounts_manager.set_current(dlg.account["id"])
            from .achievements import achievements as _ach
            _ach.unlock("first_login")
            self.account_btn.setText(dlg.account.get("name", t("topbar.login")))
            self._refresh_account_avatar()
            self.statusBar().showMessage(
                t("status.logged_in", name=dlg.account.get("name", ""))
            )
            # The real skin is fetched asynchronously inside LoginDialog;
            # refresh the avatar again once it lands.
            skin_w = getattr(dlg, "_skin_worker", None)
            if skin_w is not None:
                try:
                    skin_w.finished.connect(
                        lambda _r=None: self._refresh_account_avatar()
                    )
                except Exception:
                    pass

    def _open_skin_library(self):
        """Open the skin library for the current (or none) account."""
        from .skin_dialog import SkinDialog
        SkinDialog(
            self,
            self.current_account["id"] if self.current_account else None,
        ).exec()

    def _build_account_menu(self):
        """Populate the account dropdown with saved identities + add/remove."""
        menu = self.account_menu
        menu.clear()
        cur_id = (self.current_account or {}).get("id")
        for acc in self.accounts_manager.list():
            label = f"{acc.get('name', '?')}  ·  {type_label(acc.get('type', ''))}"
            a = menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(acc.get("id") == cur_id)
            aid = acc["id"]
            a.triggered.connect(lambda _checked=False, aid=aid: self._switch_account(aid))
        menu.addSeparator()
        add = menu.addAction(t("account.login_other"))
        add.triggered.connect(self._open_account)
        if self.current_account:
            rm = menu.addAction(t("account.remove_current"))
            rm.triggered.connect(self._remove_current_account)
        menu.addSeparator()
        skin_act = menu.addAction(icon("skin"), t("skin.manage"))
        skin_act.triggered.connect(self._open_skin_library)

    def _switch_account(self, account_id: str):
        acc = self.accounts_manager.get(account_id)
        if not acc:
            return
        self.accounts_manager.set_current(account_id)
        self.current_account = acc
        self.account_btn.setText(acc.get("name", t("topbar.login")))
        self._refresh_account_avatar()
        self.statusBar().showMessage(
            t("status.logged_in", name=acc.get("name", ""))
        )

    def _remove_current_account(self):
        if not self.current_account:
            return
        self.accounts_manager.remove(self.current_account["id"])
        self.current_account = self.accounts_manager.current()
        if self.current_account:
            self.account_btn.setText(self.current_account.get("name", t("topbar.login")))
            self._refresh_account_avatar()
        else:
            self.account_btn.setText(t("topbar.login"))
            self.account_btn.setIcon(icon("account"))
        self.statusBar().showMessage(t("account.remove_current"))

    def _refresh_account_avatar(self):
        """Update account button icon to show skin head (or default icon)."""
        acc = self.current_account
        path = skin_manager().active_path(acc["id"]) if acc else None
        if path and os.path.exists(path):
            self.account_btn.setIcon(render_head(path, 24))
        else:
            self.account_btn.setIcon(icon("account"))
        # keep the PCL2 template avatar in sync
        hp = getattr(self, "home", None)
        if hp is not None:
            try:
                hp._refresh_pcl_avatar()
            except Exception:
                pass

    def _open_settings(self):
        """Open the embedded settings page (nav row triggers reload + switch)."""
        try:
            self._show_page("settings")
        except Exception:
            pass  # never let a broken settings page crash the nav

    def _on_settings_saved(self):
        """Settings saved: language/theme may have changed → refresh all UI."""
        self.cfg = load_config()
        self.retranslate_ui()  # resets nav + stack to home
        self.home._refresh()

    def retranslate_ui(self):
        """Reload all user-facing strings after a language change."""
        # 1. Nav — layout-specific (the nav widget differs between AC / PCL2).
        if self.nav_layout == "pcl2":
            for k, b in self._pcl2_top_btns.items():
                b.setText(t(self._pcl2_top_labels[k]))
            self._pcl2_select_top(self._pcl2_active_top)
            self.stack.setCurrentIndex(STACK_INDEX.get(self._pcl2_active_top, 0))
        else:
            self.nav.blockSignals(True)
            self._populate_ac_nav()   # rebuilds groups + row map, resets to home
            self.nav.blockSignals(False)
            self.stack.setCurrentIndex(0)  # force stack in sync with nav

        # 2. Title bar
        self.account_btn.setText(t("topbar.login"))
        if self.current_account:
            self.account_btn.setText(self.current_account.get("name", t("topbar.login")))

        # 3. Status bar
        self.statusBar().showMessage(t("status.ready"))

        # 4. Home page
        self.home.retranslate_ui()

        # 5. Other pages (titles and static labels)
        if hasattr(self, 'instances_page'):
            self.instances_page.retranslate_ui()
        if hasattr(self, 'mods_page'):
            self.mods_page.retranslate_ui()
        if hasattr(self, 'store_page'):
            self.store_page.retranslate_ui()
        if hasattr(self, 'versions_page'):
            self.versions_page.retranslate_ui()

        # 6. Lobby page (embedded, also needs refresh)
        if hasattr(self, '_lobby_title'):
            self._lobby_title.setText(t("lobby.title"))
            self._lobby_join_help.setText(t("lobby.join_help"))
            self._lobby_join.setText(t("lobby.join"))
            self._lobby_create.setText(t("lobby.create"))
            self._lobby_create_help.setText(t("lobby.create_help"))

    def _open_lobby(self):
        from .lobby_dialog import LobbyDialog

        LobbyDialog(self).exec()

    def _open_diagnostics(self):
        from .diagnostics_dialog import DiagnosticsDialog

        DiagnosticsDialog(self).exec()

    def _open_scan(self):
        from .scan_dialog import ScanDialog

        ScanDialog(self).exec()
        # a new instance may have been imported — refresh the home card
        self.home._refresh()

    def _handle_play(self, inst: Instance):
        if self._play_worker is not None and self._play_worker.isRunning():
            return
        account = self.current_account or OFFLINE_ACCOUNT
        settings = load_config()
        log_dir = get_data_dir()

        # signature launch chime when starting the game
        try:
            from .core.sound import play_launch_sound
            play_launch_sound("game", settings)
        except Exception:
            pass
        self._progress.setVisible(True)
        self._progress.setMaximum(0)
        self.statusBar().showMessage(t("status.play_request", ver=inst.name))

        self._play_worker = ProgressWorker(
            launch_instance, inst, account, settings, log_dir=log_dir
        )
        self._play_worker.status.connect(self.statusBar().showMessage)
        self._play_worker.progress.connect(self._set_progress)
        self._play_worker.finished.connect(lambda _p: self._on_launch_done(inst))
        self._play_worker.error.connect(self._on_launch_error)
        self._play_worker.start()

    def _on_launch_done(self, inst: Instance):
        self._progress.setVisible(False)
        self.statusBar().showMessage(t("status.launched", name=inst.name))
        self.home.play_btn.setEnabled(True)

    def _on_launch_error(self, msg: str):
        self._progress.setVisible(False)
        self.statusBar().showMessage(t("status.launch_error", err=msg))
        self.home.play_btn.setEnabled(True)
