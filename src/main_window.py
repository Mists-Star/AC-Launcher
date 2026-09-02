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
    QProgressBar, QGridLayout, QMenu, QComboBox, QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt, QSize, QPoint, QTimer, QEvent, QObject, QPropertyAnimation, QEasingCurve, QRectF, QByteArray
from PySide6.QtGui import QFont, QIcon, QPainter, QPainterPath, QColor, QPixmap, QLinearGradient, QCursor
from PySide6.QtSvg import QSvgRenderer

from .theme import COLORS, RoundedCard, set_theme_mode, get_theme_mode, on_theme_change
from .effects import (
    LightTrailCard, set_effects_enabled, set_window_opacity, fade_page_transition,
)
from .icons import icon
from .i18n import t
from src.instances import manager, Instance
from src.pages_instances import InstancesPage, ModsPage
from src.pages_browse import VersionsPage, StorePage
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
    ("nav.group.system", [("nav.account", "account"), ("nav.console", "console"), ("nav.settings", "settings")]),
]

# Stack index of every page — single source of truth for BOTH nav layouts
# (AC left sidebar and the optional PCL2 top-bar). Add a new page here and it
# becomes reachable from whichever nav includes its key.
STACK_INDEX = {
    "home": 0, "instances": 1, "mods": 2, "store": 3,
    "versions": 4, "lobby": 5, "settings": 6, "toolbox": 7,
    "music": 8, "achievements": 9, "console": 10,
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


class _InstanceCard(LightTrailCard):
    """A clickable instance tile for the home instance-grid (GDLauncher / HMCL
    style). Clicking the card body selects it as the current instance; the
    embedded play button launches it directly."""

    def __init__(self, inst, is_current, on_select, on_play, parent=None):
        # round-50 首页实例网格流光：低强度慢速，视觉整洁
        super().__init__(
            radius=14, parent=parent,
            border_color=COLORS["accent"] if is_current else COLORS["border"],
            border_width=2 if is_current else 1,
            strength=0.5, speed=0.7,
        )
        self._inst = inst
        self._on_select_cb = on_select
        self._on_play_cb = on_play
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(144)
        # 允许高度随内容撑开（早年固定高度会裁掉底部播放钮/时间行）
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icon("instances").pixmap(22, 22))
        top.addWidget(ic)
        name = QLabel(inst.name or "—")
        name.setProperty("cls", "big")
        name.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        top.addWidget(name, stretch=1)
        src = getattr(inst, "launcher", "AC") or "AC"
        if src != "AC":
            badge = QLabel(src)
            badge.setStyleSheet(
                f"background:{COLORS['accent']}22; color:{COLORS['accent']}; "
                f"border-radius:6px; padding:1px 8px; font-size:10px; font-weight:600;"
            )
            top.addWidget(badge)
        if is_current:
            cur = QLabel("▶ " + t("home.current"))
            cur.setStyleSheet(f"color:{COLORS['accent']}; font-size:10px; font-weight:600;")
            top.addWidget(cur)
        vl.addLayout(top)

        det = QLabel(
            f"{inst.game_version or '?'}  ·  {getattr(inst, 'loader', 'vanilla') or 'vanilla'}"
        )
        det.setProperty("cls", "sub")
        vl.addWidget(det)
        vl.addStretch(1)

        bot = QHBoxLayout()
        bot.setSpacing(8)
        last = getattr(inst, "last_played", None)
        last_txt = ""
        if last:
            try:
                import datetime as _dt
                last_txt = t("home.last_played",
                             time=_dt.datetime.fromtimestamp(last).strftime("%m-%d %H:%M"))
            except Exception:
                last_txt = ""
        last_lbl = QLabel(last_txt)
        last_lbl.setProperty("cls", "sub")
        bot.addWidget(last_lbl, stretch=1)
        play_btn = QPushButton()
        play_btn.setIcon(icon("play"))
        play_btn.setIconSize(QSize(20, 20))
        play_btn.setProperty("cls", "accent")
        play_btn.setCursor(Qt.PointingHandCursor)
        play_btn.setFixedSize(40, 40)
        play_btn.setToolTip(t("home.play"))
        # 紫底 + 白字 + 深紫边框（round-33 修复 inline 样式覆盖 bug）
        play_btn.setStyleSheet(
            "QPushButton { background: #7C3AED; color: #FFFFFF; border: 2px solid #5B21B6; border-radius: 10px; padding: 0; font-weight: 600; }"
            "QPushButton:hover { background: #8B5CF6; border: 2px solid #6D28D9; }"
        )
        play_btn.clicked.connect(lambda *a: self._emit_play())
        bot.addWidget(play_btn)
        vl.addLayout(bot)

    def _emit_play(self):
        self._on_play_cb(self._inst.id)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on_select_cb(self._inst.id)
        super().mouseReleaseEvent(e)


class HomePage(QWidget):
    def __init__(self, on_play, get_current_instance, cfg,
                 on_open_settings=None, on_open_instances=None,
                 on_open_versions=None, on_open_mods=None,
                 list_instances=None, set_current_instance=None,
                 on_scan_done=None, inst_mgr=None, parent=None):
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
        self.on_scan_done = on_scan_done  # fired after the scan dialog closes
        self.inst_mgr = inst_mgr  # optional; used by the "refresh list" chip
        self._rebuilding = False  # guard against rapid-fire rebuild() calls
        self._scan_panel = None  # embedded ScanPanel, when active
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
        QTimer.singleShot(0, lambda: self._apply_wallpaper(version_id=self._current_version_id()))
        self._build()
        # 延后到事件循环再扫盘刷新，避免阻塞 MainWindow 构造（启动提速）。
        QTimer.singleShot(0, self._refresh)

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
        if style != "ac_default" and not self.cfg.get("dev_mode", False):
            style = "ac_default"
        # 整个首页包一层 QScrollArea：1100×720 窗口下垂直内容（统计条 + hero
        # + 实例网格 + 日志 + 快捷行）远超视口，不滚动就会被 Qt 硬压缩导致
        # 显示不全。滚动时背景壁纸保持固定（scroll 透明、backdrop 在底层）。
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        inner = QWidget()
        inner.setAttribute(Qt.WA_TranslucentBackground, True)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        lay = QVBoxLayout(inner)
        lay.setContentsMargins(48, 32, 48, 32)
        lay.setSpacing(16)
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
        # Detach first, then schedule deletion — using deleteLater (not shiboken
        # delete) avoids the C++ object surviving across the new insertWidget
        # call when the widget still has queued paint events, which previously
        # manifested as "double home/instances" cards.
        old = self.content
        root.removeWidget(old)
        old.hide()  # drop any pending paints before delete
        old.setParent(None)
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
            self._apply_wallpaper(version_id=self._current_version_id())
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
        # 紧凑品牌行：标题 + 副语并排，减少首页纵向堆叠感（对齐简洁启动器）。
        row = QHBoxLayout()
        row.setSpacing(14)
        head = QLabel(t("home.title"))
        head.setProperty("cls", "title")
        row.addWidget(head)
        sub = QLabel(t("home.subtitle"))
        sub.setProperty("cls", "sub")
        sub.setStyleSheet("font-size: 12px;")
        row.addWidget(sub, alignment=Qt.AlignBottom)
        row.addStretch(1)
        lay.addLayout(row)

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
        """Hero / lobby 的"启动游戏"大按钮——必须一眼可见。

        紫色实色 + 白字 + 明显边框 + 投影，padding 充足，minHeight 60，
        文字 18px Bold。边框用深紫（不是白——round-32 颜色统一深色系）。
        """
        b = QPushButton(t("home.play"))
        b.setProperty("cls", "accent")
        b.setMinimumHeight(60)
        b.setMinimumWidth(160)
        b.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        b.setCursor(Qt.PointingHandCursor)
        b.setIcon(icon("play"))
        b.setIconSize(QSize(24, 24))
        # 强化可见性：紫底 + 白字 + 深紫边框（round-32 颜色统一；round-33
        # 修复 inline setStyleSheet 覆盖主题 QSS 导致按钮变白底的问题——
        # 显式设 background/color，杜绝继承不一致）。
        b.setStyleSheet(
            "QPushButton {"
            "  background: #7C3AED;"
            "  color: #FFFFFF;"
            "  border: 2px solid #5B21B6;"
            "  padding: 8px 24px;"
            "  border-radius: 12px;"
            "  font-weight: 600;"
            "}"
            "QPushButton:hover { background: #8B5CF6; border: 2px solid #6D28D9; }"
            "QPushButton:pressed { background: #6D28D9; border: 2px solid #4C1D95; }"
        )
        b.clicked.connect(self._on_play)
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
        # round-46 用户反馈"统计条最右边的扳手孤立"：去掉右端 repair_btn
        # （修复入口改由 stat_repair 格点击触发——下一轮迭代做可点击统计格）
        lay.addWidget(stats)

        # ── hero 实例卡（渐变横幅）── 对照 Home.svg：紫→青线性渐变 + 白 CTA pill。
        _hero_g = QLinearGradient(0, 0, 900, 0)
        _hero_g.setColorAt(0.0, QColor("#7C3AED"))
        _hero_g.setColorAt(1.0, QColor("#28BCD8"))
        hero = RoundedCard(radius=16, fill=_hero_g)
        hero.setMinimumHeight(192)
        _white = "#FFFFFF"
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(28, 22, 28, 22)
        hl.setSpacing(24)

        # 左：当前实例身份（白字，渐变底）
        left = QVBoxLayout()
        left.setSpacing(8)
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name = QLabel("—")
        name.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        name.setStyleSheet(f"color: {_white}; background: transparent;")
        name_row.addWidget(name)
        # 来源徽章（PCL2/HMCL/Prism…）——控制中枢叙事：这个实例从哪个启动器接管
        self.src_badge = QLabel("")
        self.src_badge.setStyleSheet(
            f"background: #FFFFFF33; color: {_white}; border-radius: 8px; "
            f"padding: 2px 10px; font-size: 11px; font-weight: 600;"
        )
        self.src_badge.setVisible(False)
        name_row.addWidget(self.src_badge)
        name_row.addStretch(1)
        left.addLayout(name_row)
        detail = QLabel("")
        detail.setStyleSheet(f"color: {_white}; font-size: 13px; background: transparent;")
        left.addWidget(detail)
        left.addSpacing(8)
        self.inst_combo = QComboBox()
        self.inst_combo.setMinimumHeight(38)
        self.inst_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.inst_combo.setStyleSheet(
            "QComboBox { background: rgba(255,255,255,0.22); color: #FFFFFF; "
            "border: 1px solid rgba(255,255,255,0.45); border-radius: 10px; padding: 0 12px; }"
            "QComboBox:hover { background: rgba(255,255,255,0.32); }"
            "QComboBox QAbstractItemView { background: #2D2B36; color: #FFFFFF; "
            "selection-background-color: #7C3AED; border-radius: 8px; }"
            "QComboBox::drop-down { border: none; width: 24px; }"
        )
        self.inst_combo.currentIndexChanged.connect(self._on_inst_changed)
        left.addWidget(self.inst_combo)
        left.addStretch(1)
        hl.addLayout(left, stretch=1)

        # 右：渐变底上的白色 pill 启动按钮 + 结束游戏按钮
        play = self._make_play_btn()
        play.setMinimumHeight(56)
        play.setMinimumWidth(200)
        play.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        play.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        play.setStyleSheet(
            "QPushButton { background:#FFFFFF; color:#5B21B6; border:none; "
            "border-radius: 28px; padding:8px 26px; font-weight:700; }"
            "QPushButton:hover { background:#F3EEFF; }"
            "QPushButton:pressed { background:#E9E2FB; }"
            "QPushButton:disabled { background:#F0F0F0; color:#A9A9B0; }"
        )
        self.play_btn = play
        hl.addWidget(play, alignment=Qt.AlignVCenter | Qt.AlignRight)
        kill = QPushButton(t("home.kill_game"))
        kill.setMinimumHeight(40)
        kill.setCursor(Qt.PointingHandCursor)
        kill.setVisible(False)
        kill.setStyleSheet(
            "QPushButton { background:rgba(255,255,255,0.92); color:#EF4444; border:none; "
            "border-radius: 20px; padding:6px 18px; font-weight:600; }"
            "QPushButton:hover { background:#FFFFFF; }"
        )
        kill.clicked.connect(self._on_kill_game)
        self.kill_btn = kill
        hl.addWidget(kill, alignment=Qt.AlignVCenter | Qt.AlignRight)

        self.inst_lbl = name
        self.detail_lbl = detail
        lay.addWidget(hero)
        lay.addSpacing(14)

        # ── 实例卡片网格（GDLauncher / HMCL 风格：点选切换 + 直接启动）──
        grid_card = RoundedCard(radius=12)
        grid_card.setMinimumHeight(96)
        # round-46 用户反馈"首页实例网格被挤压"：maxHeight 320 太小——卡片
        # minHeight 144 + 间距，2 行就超 → 卡片被压扁。提高到 520，滚动接管。
        grid_card.setMaximumHeight(520)
        self.inst_grid_card = grid_card
        ginner = QVBoxLayout(grid_card)
        ginner.setContentsMargins(16, 16, 16, 16)
        ginner.setSpacing(10)

        grid_head = QHBoxLayout()
        grid_title = QLabel(t("home.instances_grid"))
        grid_title.setProperty("cls", "group")
        grid_head.addWidget(grid_title)
        grid_head.addStretch(1)
        grid_manage = QPushButton(t("home.manage_all"))
        grid_manage.setCursor(Qt.PointingHandCursor)
        grid_manage.setStyleSheet(
            f"QPushButton {{ font-size:12px; border:none; background:transparent; "
            f"color:{COLORS['accent']}; padding:4px 8px; border-radius:6px; }} "
            f"QPushButton:hover {{ background:{COLORS['accent_soft']}; text-decoration:underline; }}"
        )
        grid_manage.clicked.connect(self._open_instances)
        grid_head.addWidget(grid_manage)
        ginner.addLayout(grid_head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent; border:none;")
        self.inst_grid = QWidget()
        self.inst_grid_lay = QGridLayout(self.inst_grid)
        self.inst_grid_lay.setContentsMargins(0, 0, 0, 0)
        self.inst_grid_lay.setSpacing(14)
        scroll.setWidget(self.inst_grid)
        ginner.addWidget(scroll, stretch=1)
        lay.addWidget(grid_card)

        # ── 修复日志流（direction A：看得见的自修复）──
        log_card = RoundedCard(radius=12)
        log_card.setMinimumHeight(64)
        log_card.setMaximumHeight(108)
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
        v.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        v.setAlignment(Qt.AlignCenter)
        v.setMinimumWidth(56)
        # 显式配色兜底：跟随当前主题（dark/light）的 text_main
        from .theme import COLORS as _C
        v.setStyleSheet(
            f"color: {_C['text_main']}; font-size: 18px; font-weight: 700;"
        )
        cl.addWidget(v)
        cap = QLabel(label)
        cap.setProperty("cls", "sub")
        cap.setStyleSheet(
            f"font-size: 10px; color: {_C['text_sub']};"
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
        ft.setStyleSheet("color: rgba(30,30,50,0.92); font-weight: 600; font-size: 13px;")
        pl.addWidget(ft)
        self.inst_lbl = QLabel("—")
        self.inst_lbl.setStyleSheet("color: #FFFFFF; font-weight: 700; font-size: 22px;")
        pl.addWidget(self.inst_lbl)
        self.detail_lbl = QLabel("")
        self.detail_lbl.setStyleSheet("color: rgba(30,30,50,0.85);")
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
        """Hero 卡片标题（QSS cls 默认 'big' = 主标题深色）。

        round-33 修复：之前默认 cls='sub' 导致"当前实例"主标题渲染成次要灰，
        看起来像看不清。改为主标题大字号深色。
        """
        l = QLabel(text)
        l.setProperty("cls", "big")
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
        # 实例卡片网格（无论是否有当前实例都刷新）
        self._refresh_inst_grid(instances, inst.id if inst else "")

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

    # ── 实例卡片网格 ──
    def _make_instance_card(self, inst, is_current):
        return _InstanceCard(inst, is_current, self._select_instance, self._play_instance)

    def _refresh_inst_grid(self, instances, cur_id):
        if not (hasattr(self, "inst_grid_lay") and self._alive(self.inst_grid_lay)):
            return
        lay = self.inst_grid_lay
        # 清空旧卡片（同步删除，避免残留）
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                try:
                    from shiboken6 import delete as _sh
                    _sh(w)
                except Exception:
                    w.deleteLater()
        if not instances:
            # 单行空状态：图标 + 文字 + 两按钮 一排。
            # 注意：empty_w 嵌在 grid_card 的 QScrollArea 里，scroll viewport
            # 高度有限（card max 148 - header 40 ≈ 108），多行布局会裁掉底部
            # 按钮。单行布局整体高度 ~50px，舒适放进 viewport，且更贴近
            # BlockHelm 的极简留白。
            if self._alive(getattr(self, "inst_grid_card", None)):
                self.inst_grid_card.setMaximumHeight(130)
            empty_w = QWidget()
            empty_lay = QHBoxLayout(empty_w)
            empty_lay.setContentsMargins(4, 0, 4, 0)
            empty_lay.setSpacing(14)
            empty_lay.setAlignment(Qt.AlignVCenter)

            icon_lbl = QLabel()
            icon_lbl.setPixmap(icon("instances").pixmap(36, 36))
            icon_lbl.setAlignment(Qt.AlignCenter)
            empty_lay.addWidget(icon_lbl, alignment=Qt.AlignVCenter)

            txt = QLabel(t("home.no_instance_grid"))
            txt.setProperty("cls", "sub")
            txt.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            empty_lay.addWidget(txt, stretch=1)

            dl_btn = QPushButton(t("home.download_version"))
            dl_btn.setProperty("cls", "accent")
            dl_btn.setCursor(Qt.PointingHandCursor)
            dl_btn.setMinimumHeight(32)
            dl_btn.clicked.connect(self._open_versions)
            empty_lay.addWidget(dl_btn)

            scan_btn = QPushButton(t("home.scan_import"))
            scan_btn.setCursor(Qt.PointingHandCursor)
            scan_btn.setMinimumHeight(32)
            scan_btn.clicked.connect(self._open_scan)
            empty_lay.addWidget(scan_btn)

            lay.addWidget(empty_w, 0, 0)
            return
        # 有实例时恢复网格最大高度（round-46：320 → 520 防挤压）
        if self._alive(getattr(self, "inst_grid_card", None)):
            self.inst_grid_card.setMaximumHeight(520)
        # 响应式列数：按内容宽度估算，限制 1~4 列
        width = self.content.width() if self.content.width() > 0 else 900
        cols = max(1, min(4, width // 320))
        for idx, i in enumerate(instances):
            r = idx // cols
            c = idx % cols
            card = self._make_instance_card(i, i.id == cur_id)
            lay.addWidget(card, r, c)
        for c in range(cols):
            lay.setColumnStretch(c, 1)

    def _select_instance(self, inst_id):
        if inst_id:
            self.set_current_instance(inst_id)
            self._refresh()

    def _play_instance(self, inst_id):
        if inst_id:
            self.set_current_instance(inst_id)
        inst = self.get_current_instance()
        if inst is not None:
            self.on_play(inst)

    def _on_play(self):
        inst = self.get_current_instance()
        if inst is None:
            return
        self.play_btn.setEnabled(False)
        self.on_play(inst)

    def _on_kill_game(self):
        """首页「结束游戏」按钮：强杀运行中的游戏进程（round-37 轴心3）。"""
        try:
            win = self.window()
            if win is not None and hasattr(win, "kill_game"):
                if not win.kill_game():
                    win.statusBar().showMessage(t("status.no_game_running"))
        except Exception:
            pass

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
                    # round-34 性能：seek 到尾部只读 20KB，之前 f.read()[-20000:]
                    # 会把整个 latest.log（可达数百 MB）读进内存卡 UI 线程。
                    with open(logf, "r", encoding="utf-8", errors="ignore") as f:
                        try:
                            f.seek(max(0, os.path.getsize(logf) - 20000))
                        except OSError:
                            pass
                        tail = f.read()
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
        """Embed the scanner directly into the home page (no modal dialog).

        The panel replaces the normal content area; closing it restores the
        home page and refreshes dependent lists.
        """
        if self._scan_panel is not None:
            return
        from .scan_dialog import ScanPanel

        self.content.setVisible(False)
        self._scan_panel = ScanPanel(self)
        self._scan_panel.done.connect(self._close_scan_panel)
        self.layout().addWidget(self._scan_panel, stretch=1)

    def _close_scan_panel(self):
        """Remove the embedded scanner and refresh the home page."""
        if self._scan_panel is None:
            return
        imported = self._scan_panel.imported_dirs
        panel = self._scan_panel
        self._scan_panel = None
        panel.setVisible(False)
        panel.setParent(None)
        panel.deleteLater()
        self.content.setVisible(True)

        # Achievements: taking over instances from other launchers.
        if imported:
            from .achievements import achievements as _ach
            non_ac = [
                i for i in self.list_instances()
                if getattr(i, "launcher", "AC") != "AC"
            ]
            if non_ac:
                _ach.unlock("first_instance")
                if len(non_ac) >= 3:
                    _ach.unlock("takeover_3")

        # Defer refresh so any pending focus-change / nav signals settle first.
        QTimer.singleShot(100, self.on_scan_done or self._refresh)

    def _current_version_id(self) -> str | None:
        """Version id of the currently selected instance (for version-theme bg)."""
        inst = self.get_current_instance()
        return getattr(inst, "version_id", None) if inst is not None else None

    def _apply_wallpaper(self, cfg: dict | None = None, version_id: str | None = None):
        """Re-apply the backdrop (solid / image / animated GIF / video / version theme)."""
        if cfg is not None:
            self.cfg = cfg
        try:
            # 毛玻璃已删除（round-32）——壁纸层始终正常绘制
            self.backdrop.apply(self.cfg, version_id)
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

    round-54 兜底：无边框 + WA_TranslucentBackground（Acrylic 透底）在
    Win11/Qt6 下 ``startSystemMove`` 经常失效（窗口纹丝不动）。这里改为
    「原生优先 + 手动移动兜底」：按下时优先请求系统移动；若失效，来自系统
    的 Move 事件仍会送到本 filter，此时按鼠标全局位移手动 ``move()``。
    系统移动一旦接手，应用收不到 Move 事件，二者天然互斥、永不打架。
    """

    def __init__(self, window: "MainWindow", bar: QWidget):
        super().__init__(bar)
        self._window = window
        self._bar = bar
        self._drag: tuple[QPoint, QPoint] | None = None  # (press_global, win_pos)
        bar.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is not self._bar:
            return False
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if pos.y() < 6:            # resize zone — FramelessHelper's job
                self._drag = None
                return False
            if isinstance(self._bar.childAt(pos), QPushButton):
                self._drag = None
                return False           # buttons handle their own clicks
            cursor = QCursor.pos()
            self._drag = (cursor, self._window.pos())
            try:
                self._window.startSystemMove()
            except AttributeError:
                pass
            return True
        if etype == QEvent.Type.MouseButtonRelease and event.button() == Qt.LeftButton:
            self._drag = None
            return False
        if etype == QEvent.Type.MouseMove and self._drag is not None:
            # 手动兜底：仅在系统移动未接管（仍能收到 Move）时生效
            if (event.buttons() & Qt.LeftButton) and not self._window.isMaximized():
                press_global, start_win = self._drag
                delta = event.globalPosition().toPoint() - press_global
                self._window.move(start_win + delta)
            return True
        if etype == QEvent.Type.MouseButtonDblClick and event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if pos.y() >= 6 and not isinstance(self._bar.childAt(pos), QPushButton):
                self._window._toggle_max()
                return True
        return False


# ── window-control vector glyphs (replaces Unicode chars — □ ✕) ──
def _win_svg_pixmap(kind: str, color: str, size: int = 18) -> QPixmap:
    """Render a crisp vector glyph for a window-control button.

    The old Unicode chars (— □ ✕) rendered inconsistently across fonts/DPI
    and looked "off" next to native chrome (Edge/Chrome use vector lines).
    """
    paths = {
        # round-47 修复：min 横线在 viewBox 10×10 底部 "M2,7" → 居中 "M2,5"，
        # 让最小化/最大化/关闭三个图标的视觉重心在同一水平线上。
        "min": "M2,5 H8",
        "max": "M2.5,2.5 H7.5 V7.5 H2.5 Z",
        "restore": "M2,3.2 H6.2 V7.4 H2 Z M3.4,2 H7.6 V6.2 H3.4 Z",
        "close": "M2.6,2.6 L7.4,7.4 M7.4,2.6 L2.6,7.4",
    }
    d = paths.get(kind, paths["close"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 10 10">'
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p)
    p.end()
    return pm


def _win_btn_colors() -> dict:
    """High-contrast colors for the window-control glyphs.

    Using fixed dark/light greys instead of ``text_main`` guarantees the
    buttons remain visible against both the light and dark title-bar
    backgrounds, regardless of the active theme pack.
    """
    if get_theme_mode() == "dark":
        return {
            "normal": "#D1D5DB",
            "hover": "#FFFFFF",
            "hover_bg": "#333333",
            "close_hover": "#FFFFFF",
            "close_bg": "#EF4444",
        }
    return {
        "normal": "#374151",
        "hover": "#111827",
        "hover_bg": "#E5E7EB",
        "close_hover": "#FFFFFF",
        "close_bg": "#EF4444",
    }


class _WinBtn(QPushButton):
    """Window-control button with a vector icon that recolors on hover.

    ``normal_color`` / ``hover_color`` let the close button flip to white on a
    red hover, matching Edge/Chrome. ``hover_bg`` is applied via stylesheet so
    the glyph stays readable over the hover surface.
    """

    def __init__(self, kind, normal_color, hover_color, hover_bg, slot, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._normal = normal_color
        self._hover = hover_color
        self._hover_bg = hover_bg
        self.setFixedSize(46, 40)
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(QIcon(_win_svg_pixmap(kind, normal_color, 18)))
        self.setIconSize(QSize(18, 18))
        self.clicked.connect(slot)
        self._update_style()

    def _update_style(self):
        # Base keeps the button transparent; hover adds a subtle surface.
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; }}\n"
            f"QPushButton:hover {{ background: {self._hover_bg}; border-radius: 6px; }}"
        )

    def set_kind(self, kind):
        self._kind = kind
        self.setIcon(QIcon(_win_svg_pixmap(kind, self._normal, 18)))

    def enterEvent(self, event):
        self.setIcon(QIcon(_win_svg_pixmap(self._kind, self._hover, 18)))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setIcon(QIcon(_win_svg_pixmap(self._kind, self._normal, 18)))
        super().leaveEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_DISPLAY)
        _icon_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "icons")
        _icon_path = None
        # PNG preferred: the .ico is ~360KB and decoding it 7× stalls startup
        # (one QIcon per pixmap call). One QIcon + .pixmap() reuses the cache.
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
                ico.addPixmap(ico.pixmap(_sz, _sz))
            self.setWindowIcon(ico)
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)

        self.inst_mgr = manager()
        self.accounts_manager = accounts_manager()
        self.current_account = self.accounts_manager.current()
        self._play_worker = None
        self._game_proc = None      # round-34：运行中游戏进程
        self._game_name = ""
        self._game_poll_timer = None
        self._active_toasts = []
        self.cfg = load_config()

        # Apply persisted theme before any UI is built. Default is now light.
        set_theme_mode(self.cfg.get("theme_mode", "light"))
        # round-49 修复「启动后 accent 始终是紫色」：此前只调用 set_theme_mode，
        # 自定义 accent_color 从未被应用。先设模式再设强调色（set_theme_mode
        # 现在会自动保留自定义 accent，顺序无碍）。
        from .theme import set_accent_color
        set_accent_color(self.cfg.get("accent_color", "#7C3AED"))
        # round-49 液态流光 effect：按配置开启流光卡片 + 全局透明度。
        set_effects_enabled(self.cfg.get("effect_light_trail", True))
        set_window_opacity(self, self.cfg.get("window_opacity", 1.0))

        # round-51 透底效果：系统 Acrylic 在 FramelessHelper 设置完窗口标志后
        # 再应用（见 __init__ 末尾 _apply_transparent_window），此处仅占位。
        # 圆角由 enable_acrylic / enable_win11_round_corners 处理。

        # Round window corners on Win11 — call after the native window exists.
        # Safe no-op elsewhere (the function checks the platform itself).
        enable_win11_round_corners(self)

        # The app chime spins up QMediaPlayer, which costs a few hundred ms on
        # first use. Doing that here froze the splash animation, so it is
        # deferred until after the window is on screen.
        QTimer.singleShot(0, self._play_app_chime)
        self._register_shortcuts()  # round-42 全局快捷键（Ctrl+N/D、F5）

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
            on_scan_done=self._refresh_after_import,
            inst_mgr=self.inst_mgr,
        )
        self.stack.addWidget(self.home)  # 0 Home

        # ── 延迟加载：仅主页（index 0）立即构建；其余页面（1-9）用轻量占位
        # QWidget 占住 QStackedWidget 的索引，首次切换到该页时（_ensure_page）
        # 再真正构建并连接信号。这样启动期不再同步构造 7 个页面，显著提速。
        self._built = {0}
        self._placeholders = {}
        self._page_builders = {
            1: self._build_instances,
            2: self._build_mods,
            3: self._build_store,
            4: self._build_versions,
            5: self._build_lobby,
            6: self._build_settings,
            7: self._build_toolbox,
            8: self._build_music,
            9: self._build_achievements,
            10: self._build_console,
        }
        for _idx in range(1, 11):
            _ph = QWidget()
            self._placeholders[_idx] = _ph
            self.stack.addWidget(_ph)

        right.addWidget(self.stack, stretch=1)

        # ── nav (layout-specific; both layouts share the stack above) ──
        self.nav_layout = self.cfg.get("nav_layout", "ac")
        # PCL2 顶栏导航是开发者模式实验功能
        if self.nav_layout == "pcl2" and not self.cfg.get("dev_mode", False):
            self.nav_layout = "ac"
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

        # round-51 透底效果：系统级 Acrylic 真毛玻璃（透桌面模糊）+ 圆角镂空。
        # 必须在窗口标志最终确定后调用（winId/create 不会再用 setWindowFlags
        # 重建原生窗口，避免 DWM 属性丢失）。
        self._apply_transparent_window()

        # ── Achievement toast (direction B 彩蛋) ──
        from .achievements import achievements as _ach
        _ach.toast.connect(self._show_achievement_toast)

        # ── round-65 版本页预热 ──
        # 版本清单磁盘缓存会放宽到 24h 语义（net_api.fetch_versions），这里再
        # 在后台预热一遍：用户首次切到版本页时命中内存缓存秒开，不再干等网络。
        self._preheat_versions()

    def _preheat_versions(self) -> None:
        """启动后立即后台拉一遍版本清单（失败静默，进页面时页面自己再拉）。

        用 Worker（QThread）避免阻塞启动；结果写入 net_api 缓存，
        结果未就绪时版本页的 Worker 会正常再发一次请求兜底。
        """
        try:
            from .worker import Worker
            from .net_api import fetch_versions
            w = Worker(fetch_versions)
            w.finished.connect(lambda _r: None)   # 结果已写入 net_api 缓存
            w.error.connect(lambda _e: None)       # 预热失败静默：页面再拉
            self._preheat_worker = w               # 防 GC（退出时 drain_workers 兜底）
            w.start()
        except Exception:
            pass

    def _apply_transparent_window(self) -> None:
        """透底效果：全局半透明无边框窗口 + 圆角镂空。

        开启时用系统 Acrylic（DWM 桌面模糊透出）+ WA_TranslucentBackground
        实现真半透明；应用层背景已由 theme 切半透明（main.py 里按配置设置），
        否则 Acrylic 会被实色背景盖住。关闭时回退圆角即可。
        """
        try:
            if self.cfg.get("transparent_window", True):
                from .win_acrylic import enable_acrylic
                self.setAttribute(Qt.WA_TranslucentBackground, True)
                enable_acrylic(self, dark=get_theme_mode() == "dark")
            else:
                from .win_acrylic import disable_acrylic
                disable_acrylic(self, dark=get_theme_mode() == "dark")
        except Exception:
            # 非 Windows 或 DWM 不可用 → 静默回退实色圆角窗口
            pass

    def _show_achievement_toast(self, aid: str):
        """round-46 升级：MC 风格成就解锁 toast——右下角滑入 + 金边 + 大图标 + 淡出。

        从右→左 250ms 滑入 → 持续 4s → 250ms 淡出 → 删除。
        自绘 QWidget 子类（金色边框 + 棕色背景 + 🏆大图标 + 标题 + 描述）。
        防 GC：_active_toasts 列表兜底。
        """
        try:
            from .achievements import ACHIEVEMENTS
            from .i18n import t as _t
            title = _t(ACHIEVEMENTS[aid][0])
            desc = _t(ACHIEVEMENTS[aid][1])
        except Exception:
            return

        from PySide6.QtGui import QPainter, QLinearGradient, QFont
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Qt as _Qt

        W, H = 320, 110
        # 自绘 toast widget —— 比 RoundedCard 更可控（金边/渐变/不裁剪 icon）
        class _AchToast(QWidget):
            def paintEvent(self, e):
                p = QPainter(self)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                r = self.rect()
                # 棕色渐变背景（MC 风格：深棕 → 中棕）
                grad = QLinearGradient(0, 0, 0, r.height())
                grad.setColorAt(0.0, QColor(67, 51, 35))
                grad.setColorAt(1.0, QColor(45, 33, 21))
                p.setBrush(grad)
                p.setPen(QColor(255, 215, 0))  # 金色边框
                _pen = p.pen()
                _pen.setWidth(3)
                p.setPen(_pen)
                from PySide6.QtGui import QPainterPath
                path = QPainterPath()
                path.addRoundedRect(1.5, 1.5, r.width() - 3, r.height() - 3, 10, 10)
                p.drawPath(path)

        toast = _AchToast()
        toast.setFixedSize(W, H)
        toast.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        toast.setAttribute(Qt.WA_TranslucentBackground, True)
        # 内容布局：左侧大图标 + 右侧标题/描述/已解锁
        outer = QHBoxLayout(toast)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)
        # 左侧 🏆 大图标（用 label + emoji，emoji 系统字体渲染）
        icon_lbl = QLabel("🏆")
        f = QFont("Segoe UI Emoji", 32)
        icon_lbl.setFont(f)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setFixedWidth(56)
        outer.addWidget(icon_lbl, alignment=Qt.AlignVCenter)
        # 右侧文字栈
        right = QVBoxLayout()
        right.setSpacing(2)
        unlocked_lbl = QLabel("§l§6§o" if False else "已解锁！")  # 中文"已解锁！"
        unlocked_lbl.setStyleSheet(
            "color: #FFD700; font-size: 11px; font-weight: 700; letter-spacing: 1px;"
        )
        right.addWidget(unlocked_lbl)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "color: #FFFFFF; font-size: 16px; font-weight: 700;"
        )
        title_lbl.setWordWrap(True)
        right.addWidget(title_lbl)
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet(
            "color: #D8C8A0; font-size: 11px;"
        )
        desc_lbl.setWordWrap(True)
        right.addWidget(desc_lbl)
        right.addStretch(1)
        outer.addLayout(right, stretch=1)

        # 起始位置：右外（屏幕外右侧 → 滑入到右下角）
        win_pos = self.mapToGlobal(self.rect().topRight())
        margin_right = 24
        margin_bottom = 48
        end_x = win_pos.x() - W - margin_right
        end_y = win_pos.y() + self.height() - H - margin_bottom
        start_x = win_pos.x() + 10
        toast.move(start_x, end_y)
        toast.show()
        toast.raise_()

        # 入场动画（280ms 从右滑入）
        anim_in = QPropertyAnimation(toast, b"pos")
        anim_in.setDuration(280)
        anim_in.setStartValue(toast.pos())
        anim_in.setEndValue(QPoint(end_x, end_y))
        anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _after_in():
            # 持续 4s 后淡出
            QTimer.singleShot(3800, _fade_out)

        def _fade_out():
            try:
                anim_out = QPropertyAnimation(toast, b"windowOpacity")
                anim_out.setDuration(300)
                anim_out.setStartValue(1.0)
                anim_out.setEndValue(0.0)
                anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
                anim_out.finished.connect(_dismiss)
                anim_out.start()
                # 动画对象必须 hold 防 GC
                toast._anim_out = anim_out
            except Exception:
                _dismiss()

        def _dismiss():
            try:
                if toast in self._active_toasts:
                    self._active_toasts.remove(toast)
                toast.deleteLater()
            except Exception:
                pass

        anim_in.finished.connect(_after_in)
        anim_in.start()

        # 防 GC：闭包 + 列表双保险（之前 round-46 治 double-delete 的方案）
        try:
            self._active_toasts.append(toast)
        except AttributeError:
            self._active_toasts = [toast]
        toast._anim_in = anim_in  # 保活动画对象

    def _play_app_chime(self):
        """Signature chime on app start (no-op if disabled / trigger != app)."""
        try:
            from .core.sound import play_launch_sound, start_bgm

            play_launch_sound("app", self.cfg)
            start_bgm(self.cfg)
        except Exception:  # noqa: BLE001 - audio must never block the app
            pass

    # ---- shared state ----
    def _register_shortcuts(self):
        """round-42 全局快捷键（对齐 Prism：Ctrl+N/D、F5）。"""
        try:
            from PySide6.QtGui import QShortcut, QKeySequence
            QShortcut(QKeySequence("Ctrl+N"), self,
                      activated=self._shortcut_new_instance)
            QShortcut(QKeySequence("Ctrl+D"), self,
                      activated=self._shortcut_duplicate)
            QShortcut(QKeySequence("F5"), self,
                      activated=self._shortcut_refresh)
        except Exception:
            pass

    def _shortcut_new_instance(self):
        try:
            self._switch_stack(STACK_INDEX["instances"])
            self.instances_page._new()
        except Exception:
            pass

    def _shortcut_duplicate(self):
        try:
            self._switch_stack(STACK_INDEX["instances"])
            inst = self.instances_page.selected_instance()
            if inst is not None:
                self.instances_page._duplicate(inst)
        except Exception:
            pass

    def _shortcut_refresh(self):
        try:
            self.instances_page.refresh()
        except Exception:
            pass
    def current_instance(self) -> Instance | None:
        return self.inst_mgr.current()

    def _current_version_id(self) -> str | None:
        inst = self.current_instance()
        return getattr(inst, "version_id", None) if inst is not None else None

    def _on_current_changed(self, _id: str):
        if getattr(self, "mods_page", None) is not None:
            self.mods_page.refresh()
        self.home._refresh()
        self.home._apply_wallpaper(version_id=self._current_version_id())

    def _refresh_after_import(self):
        """Refresh every page that shows the instance list after the scan /
        import dialog closes, so newly imported instances appear immediately
        instead of waiting for the next page switch."""
        try:
            self.home._refresh()
        except Exception:  # noqa: BLE001
            pass
        for name in ("instances_page", "mods_page"):
            page = getattr(self, name, None)
            if page is None:
                continue
            try:
                page.refresh()
            except Exception:  # noqa: BLE001
                pass

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

        # ── Theme toggle pill (light/dark quick switch, top-right) ──
        self.theme_btn = self._build_theme_toggle()
        lay.addWidget(self.theme_btn)

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

        # ── Window controls (frameless) — vector glyphs, not Unicode ──
        wc = _win_btn_colors()
        self._win_btns: dict[str, _WinBtn] = {}
        for name, kind, slot in [
            ("min", "min", self.showMinimized),
            ("max", "max", self._toggle_max),
            ("close", "close", self.close),
        ]:
            if name == "close":
                btn = _WinBtn(
                    kind,
                    normal_color=wc["normal"],
                    hover_color=wc["close_hover"],
                    hover_bg=wc["close_bg"],
                    slot=slot,
                )
            else:
                btn = _WinBtn(
                    kind,
                    normal_color=wc["normal"],
                    hover_color=wc["hover"],
                    hover_bg=wc["hover_bg"],
                    slot=slot,
                )
            btn.setObjectName(f"win_{name}")
            lay.addWidget(btn)
            self._win_btns[name] = btn

        # Re-render icons when the user switches theme mode/pack at runtime.
        on_theme_change(self._refresh_win_icons)

        return bar

    def _refresh_win_icons(self):
        """Re-render the window-control glyphs for the current theme colors."""
        wc = _win_btn_colors()
        btns = getattr(self, "_win_btns", None)
        if not btns:
            return
        for name, b in btns.items():
            b._normal = wc["normal"]
            b._hover = wc["close_hover"] if name == "close" else wc["hover"]
            b._hover_bg = wc["close_bg"] if name == "close" else wc["hover_bg"]
            b._update_style()
            b.setIcon(QIcon(_win_svg_pixmap(b._kind, b._normal, 18)))

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
            self._win_btns["max"].set_kind("max")
        else:
            self.showMaximized()
            self._win_btns["max"].set_kind("restore")

    # ── theme toggle pill ──────────────────────────────────────────────────
    def _build_theme_toggle(self) -> QPushButton:
        b = QPushButton()
        b.setProperty("cls", "theme-toggle")
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumWidth(86)
        b.setMinimumHeight(34)
        b.clicked.connect(self._toggle_theme)
        on_theme_change(self._refresh_theme_toggle)
        self._style_theme_toggle(b)
        return b

    def _style_theme_toggle(self, b: QPushButton) -> None:
        dark = get_theme_mode() == "dark"
        bg = "#2A2A2E" if dark else "#FFFFFF"
        brd = "#3A3A40" if dark else "#E5E7EB"
        fg = "#E5E5E5" if dark else "#1A1A2E"
        hover = "#3F3F47" if dark else "#F5F6F8"
        b.setStyleSheet(
            f"QPushButton {{ background:{bg}; color:{fg}; border:1px solid {brd};"
            f" border-radius:17px; padding:3px 14px; font-size:13px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{hover}; }}"
        )

    def _refresh_theme_toggle(self, _btn=None) -> None:
        b = _btn or getattr(self, "theme_btn", None)
        if b is None:
            return
        dark = get_theme_mode() == "dark"
        b.setText(t("theme.toggle_dark") if dark else t("theme.toggle_light"))
        b.setIcon(icon("moon" if dark else "sun"))
        b.setIconSize(QSize(16, 16))
        b.setToolTip(t("settings.theme.light") if dark else t("settings.theme.dark"))

    def _toggle_theme(self) -> None:
        from .theme import apply_qss
        mode = "dark" if get_theme_mode() == "light" else "light"
        set_theme_mode(mode)
        apply_qss()
        try:
            self.cfg["theme_mode"] = mode
            save_config(self.cfg)
        except Exception:  # noqa: BLE001 - persistence must never break switching
            pass

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
        nav.setObjectName("ac-nav")
        # round-46 用户反馈"上下留白太多"：vertical margins 4px、item height 由 QSS 控
        nav.setMinimumWidth(140)
        nav.setMaximumWidth(200)
        nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav.setIconSize(QSize(22, 22))
        nav.setSpacing(0)  # 不要额外间距，留给 QSS padding
        nav.setContentsMargins(6, 4, 6, 4)
        nav.setUniformItemSizes(True)  # 性能 + 固定行高
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
        side.setMinimumWidth(160)
        side.setMaximumWidth(240)
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
        # Note: settings used to reload() here, but rebuilding the whole page on
        # every open caused a ~1 s freeze. It is now only rebuilt when the
        # language changes (retranslate_ui) so values stay editable.
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
                      "music", "achievements", "settings", "console")
        if key in _PAGE_KEYS:
            self._last_page_row = row
        idx = {
            "home": 0, "instances": 1, "mods": 2, "store": 3,
            "versions": 4, "lobby": 5, "settings": 6, "music": 8,
            "achievements": 9, "console": 10,
        }.get(key)
        if idx is not None:
            if key == "home":
                self.home._refresh()
            # Settings no longer reload()s on every open — see _pcl2_apply_sub.
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

    # ── 延迟构建页面（首次切换时调用） ──
    def _ensure_page(self, idx: int):
        """首次切换到 idx 时构建真实页面并连接信号，替换占位 QWidget。

        占位占住 QStackedWidget 的索引，移除占位后 insertWidget(idx) 会把真实
        页面放回原索引，其余未构建占位相对顺序不变，索引始终稳定。
        """
        if idx in self._built:
            return
        builder = self._page_builders.get(idx)
        if builder is None:
            return
        page = builder()
        ph = self._placeholders.pop(idx, None)
        if ph is not None:
            self.stack.removeWidget(ph)
            ph.deleteLater()
        self.stack.insertWidget(idx, page)
        self._built.add(idx)

    def _build_instances(self):
        self.instances_page = InstancesPage()
        self.instances_page.current_changed.connect(self._on_current_changed)
        self.instances_page.section_requested.connect(self._on_instance_section)
        self.instances_page.scan_done.connect(self._refresh_after_import)
        return self.instances_page

    def _build_mods(self):
        self.mods_page = ModsPage(
            list_instances=lambda: self.inst_mgr.list(),
            get_current_instance=self.current_instance,
        )
        return self.mods_page

    def _build_store(self):
        self.store_page = StorePage(
            list_instances=lambda: self.inst_mgr.list(),
            get_current_instance=self.current_instance,
        )
        return self.store_page

    def _build_versions(self):
        self.versions_page = VersionsPage()
        self.versions_page.instance_created.connect(self._on_instance_created)
        return self.versions_page

    def _build_lobby(self):
        self.lobby_widget = QWidget()
        ll = QVBoxLayout(self.lobby_widget)
        ll.setContentsMargins(40, 32, 40, 32)
        ll.addStretch(1)
        _card = RoundedCard(radius=16)
        _card.setMaximumWidth(560)
        _cl = QVBoxLayout(_card)
        _cl.setContentsMargins(36, 30, 36, 30)
        _cl.setSpacing(12)
        _tile = QLabel()
        _tile.setPixmap(icon("lobby").pixmap(40, 40))
        _cl.addWidget(_tile)
        self._lobby_title = QLabel(t("lobby.title"))
        self._lobby_title.setProperty("cls", "title")
        _cl.addWidget(self._lobby_title)
        self._lobby_join_help = QLabel(t("lobby.join_help"))
        self._lobby_join_help.setProperty("cls", "sub")
        self._lobby_join_help.setWordWrap(True)
        _cl.addWidget(self._lobby_join_help)
        btn_row = QHBoxLayout()
        self._lobby_join = QPushButton(icon("login"), t("lobby.join"))
        self._lobby_join.setMinimumHeight(40)
        self._lobby_join.clicked.connect(self._open_lobby)
        btn_row.addWidget(self._lobby_join)
        self._lobby_create = QPushButton(icon("add"), t("lobby.create"))
        self._lobby_create.setProperty("cls", "accent")
        self._lobby_create.setMinimumHeight(40)
        self._lobby_create.clicked.connect(self._open_lobby)
        btn_row.addWidget(self._lobby_create)
        _cl.addLayout(btn_row)
        self._lobby_create_help = QLabel(t("lobby.create_help"))
        self._lobby_create_help.setProperty("cls", "sub")
        self._lobby_create_help.setWordWrap(True)
        _cl.addWidget(self._lobby_create_help)
        ll.addWidget(_card)
        ll.addStretch(1)
        return self.lobby_widget

    def _build_settings(self):
        self.settings_page = SettingsPage()
        self.settings_page._window = self  # live-refresh hook
        self.settings_page.saved.connect(self._on_settings_saved)
        self.settings_page.close_requested.connect(lambda: self._show_page("home"))
        return self.settings_page

    def _build_toolbox(self):
        self.toolbox_widget = QWidget()
        _tb = QVBoxLayout(self.toolbox_widget)
        _tb.setContentsMargins(40, 32, 40, 32)
        _tb.addStretch(1)
        _card = RoundedCard(radius=16)
        _card.setMaximumWidth(520)
        _cl = QVBoxLayout(_card)
        _cl.setContentsMargins(40, 34, 40, 34)
        _cl.setSpacing(12)
        _cl.setAlignment(Qt.AlignCenter)
        _tile = QLabel()
        _tile.setPixmap(icon("toolbox").pixmap(40, 40))
        _tile.setAlignment(Qt.AlignCenter)
        _cl.addWidget(_tile)
        _t = QLabel(t("pcl2.toolbox_title"))
        _t.setProperty("cls", "title")
        _t.setAlignment(Qt.AlignCenter)
        _cl.addWidget(_t)
        _s = QLabel(t("pcl2.toolbox_empty"))
        _s.setProperty("cls", "sub")
        _s.setWordWrap(True)
        _s.setAlignment(Qt.AlignCenter)
        _cl.addWidget(_s)
        _tag = QLabel(t("pcl2.toolbox_badge"))
        _tag.setStyleSheet(
            f"color: {COLORS['accent']}; background: {COLORS['accent']}1F; "
            f"border-radius: 9px; padding: 2px 12px; font-size: 11px; "
            f"font-weight: 600;")
        _tag.setAlignment(Qt.AlignCenter)
        _cl.addWidget(_tag)
        _tb.addWidget(_card)
        _tb.addStretch(1)
        return self.toolbox_widget

    def _build_music(self):
        from .music_page import MusicPage
        self.music_page = MusicPage()
        return self.music_page

    def _build_achievements(self):
        from .achievements_page import AchievementsPage
        self.achievements_page = AchievementsPage()
        return self.achievements_page

    def _build_console(self):
        from .pages_console import ConsolePage
        self.console_page = ConsolePage()
        # 若游戏已启动（切页前就 launch 了），把当前日志绑定进控制台
        _p = getattr(self, "_game_log_path", None)
        _n = getattr(self, "_game_name", None)
        if _p:
            self.console_page.set_game(_p, _n)
        return self.console_page

    def _switch_stack(self, idx: int):
        """Switch the content stack.

        Uses a one-shot fade-in (round-49 重启动画). The fade installs a fresh
        QGraphicsOpacityEffect and removes it on finish, so—unlike the old
        persistent-effect version that orphaned a ghost "double page" when a
        modal dialog interrupted it—no translucent residue can persist. If the
        effect or config is disabled it falls back to an instant switch.
        """
        if not 0 <= idx < self.stack.count():
            return
        cur = self.stack.currentIndex()
        if idx == cur:
            return
        # Intercept leaving the settings page with unsaved edits: ask the user
        # whether to save / discard / cancel (cancel = stay on settings).
        sp = getattr(self, "settings_page", None)
        if sp is not None and cur == self.stack.indexOf(sp):
            if not self._maybe_save_settings():
                return
        self._ensure_page(idx)  # 首次切换才真正构建该页（延迟加载）
        if self.cfg.get("page_transition", True):
            fade_page_transition(self.stack, idx)
        else:
            self.stack.setCurrentIndex(idx)

    def _maybe_save_settings(self) -> bool:
        """Ask about unsaved settings. Returns True if we may proceed navigating
        away (changes saved or discarded), False if the user cancelled."""
        sp = getattr(self, "settings_page", None)
        if sp is None or not sp.is_dirty():
            return True
        choice = sp.ask_save_dialog()
        if choice == "save":
            sp._save()
            return True
        if choice == "discard":
            sp.discard_changes()
            return True
        return False

    def _show_page(self, key: str):
        """Programmatically switch the content stack to the given nav key."""
        if self.nav_layout == "pcl2":
            self._pcl2_goto(key)
            return
        self.nav.setCurrentRow(self._nav_row(key))

    def apply_home_style(self, style_key: str):
        """Re-render the home page live with a new style (from settings / onboarding)."""
        # 非开发者模式只允许 AC 默认模板
        if style_key != "ac_default" and not self.cfg.get("dev_mode", False):
            style_key = "ac_default"
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
        # Skip the expensive home rebuild when nothing actually changed —
        # startup calls retranslate_ui() unconditionally, and a full home
        # rebuild (~0.5s) is what made the welcome screen feel like it
        # "loads forever". First call still rebuilds (builds the page).
        try:
            from .i18n import get_language
            _now = get_language()
        except Exception:
            _now = None
        _lang = getattr(self, "_app_lang", None)
        if _lang == _now and getattr(self, "_home_built", False):
            return  # no language change → skip the expensive home rebuild
        self._app_lang = _now
        self._home_built = True

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
        self._refresh_win_icons()
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

        # 7. round-44 补全：music/achievements/toolbox + 设置页设置项 label
        if hasattr(self, 'music_page') and hasattr(self.music_page, 'retranslate_ui'):
            self.music_page.retranslate_ui()
        if hasattr(self, 'achievements_page') and hasattr(self.achievements_page, 'retranslate_ui'):
            self.achievements_page.retranslate_ui()
        if hasattr(self, 'toolbox_widget') and hasattr(self.toolbox_widget, 'retranslate_ui'):
            self.toolbox_widget.retranslate_ui()
        if hasattr(self, 'settings_dialog') and self.settings_dialog is not None \
                and hasattr(self.settings_dialog, 'retranslate_ui'):
            try:
                self.settings_dialog.retranslate_ui()
            except Exception:
                pass

    def _open_lobby(self):
        from .lobby_dialog import LobbyDialog

        LobbyDialog(self).exec()

    def _open_diagnostics(self):
        from .diagnostics_dialog import DiagnosticsDialog

        DiagnosticsDialog(self).exec()

    def _handle_play(self, inst: Instance):
        self._last_inst = inst  # round-46：记住实例，Java 选完可重试
        if self._play_worker is not None and self._play_worker.isRunning():
            return
        account = self.current_account or OFFLINE_ACCOUNT
        settings = load_config()
        log_dir = get_data_dir()
        # round-71 借 PCL-CE McLogFilter：保存本次登录 token，console 展示打码用
        self._game_token = account.get("token", "")

        # signature launch chime when starting the game
        try:
            from .core.sound import play_launch_sound
            play_launch_sound("game", settings)
        except Exception:
            pass
        self._progress.setVisible(True)
        self._progress.setMaximum(0)
        self.statusBar().showMessage(t("status.play_request", ver=inst.name))

        # round-52 启动进度对话框（对齐 HMCL/PCL2 的启动检查步骤面板）：
        # 隐藏只收起点窗口，启动仍由后台 worker 继续（状态栏进度兜底）。
        from .launch_dialog import LaunchProgressDialog
        self._launch_dlg = LaunchProgressDialog(inst, parent=self)
        self._launch_dlg.show()

        self._play_worker = ProgressWorker(
            launch_instance, inst, account, settings, log_dir=log_dir
        )
        self._play_worker.status.connect(self.statusBar().showMessage)
        self._play_worker.step.connect(self._launch_dlg.set_step)
        self._play_worker.status.connect(self._launch_dlg.set_status_text)
        self._play_worker.progress.connect(self._set_progress)
        self._play_worker.progress.connect(self._launch_dlg.set_progress)
        # launch_instance 返回 (proc, log_path)；round-34 把 proc 交给进程跟踪
        self._play_worker.finished.connect(
            lambda _res: self._on_launch_done(
                inst,
                _res[0] if isinstance(_res, (tuple, list)) and _res else None,
                _res[1] if isinstance(_res, (tuple, list)) and len(_res) > 1 else None))
        self._play_worker.error.connect(self._on_launch_error)
        self._play_worker.start()

    def _on_launch_done(self, inst: Instance, _proc=None, _log_path=None):
        self._progress.setVisible(False)
        self.statusBar().showMessage(t("status.launched", name=inst.name))
        self.home.play_btn.setEnabled(True)
        # round-52：进度对话框全部点亮后稍作停留再关（玩家能看到「启动游戏✔」）
        _dlg = getattr(self, "_launch_dlg", None)
        if _dlg is not None:
            try:
                _dlg.mark_launched()
                from PySide6.QtCore import QTimer
                QTimer.singleShot(900, _dlg.close)
            except Exception:  # noqa: BLE001
                _dlg.close()
            self._launch_dlg = None
        # round-34：游戏进程生命周期——保存 proc 引用并轮询退出状态
        self._track_game_process(_proc, inst.name, _log_path, inst)

    def _track_game_process(self, proc, name: str, log_path: str | None = None, instance=None):
        """保存游戏进程句柄，启动 2s 间隔轮询，退出时状态栏提示。

        ``instance`` 可选：round-55 用于解析实例级「退出后命令」（空回退全局）。
        """
        self._game_proc = proc
        self._game_log_path = log_path
        self._game_exit_cmd = ""
        self._game_cwd = ""
        if instance is not None:
            try:
                from .settings_dialog import load_config
                _cfg = load_config()
                self._game_exit_cmd = (
                    (getattr(instance, "exit_cmd", "") or "").strip()
                    or _cfg.get("exit_cmd", ""))
                # round-57：退出命令工作目录跟随游戏真实数据目录（版本隔离感知）
                try:
                    from .launch import resolve_game_dir
                    self._game_cwd = resolve_game_dir(instance, _cfg)
                except Exception:  # noqa: BLE001 - 解析失败退回实例根目录
                    self._game_cwd = getattr(instance, "mc_dir", "")
            except Exception:  # noqa: BLE001 - 读配置失败则无退出钩子
                pass
        if proc is None:
            return
        self._game_name = name
        # 控制台页（若已构建）绑定本次运行的日志，实时显示输出
        _cp = getattr(self, "console_page", None)
        if _cp is not None:
            try:
                _cp.set_game(log_path, name, getattr(self, "_game_token", ""))
            except Exception:
                pass
        self._game_poll_timer = QTimer(self)
        self._game_poll_timer.setInterval(2000)
        self._game_poll_timer.timeout.connect(self._poll_game)
        self._game_poll_timer.start()
        # round-37 轴心3：游戏运行中显示「结束游戏」按钮
        self._set_game_running_ui(True)
        # round-50 退出释放资源：启动后游戏进程稳定存活则自动关闭启动器
        self._maybe_auto_close_launcher(name)

    def _maybe_auto_close_launcher(self, name: str) -> None:
        """round-50 退出释放资源：对齐 Prism「Kill on Launch」。

        游戏进程稳定存活一段时间（默认 5s，足以跨过 crash-on-start）后自动
        `close()` 启动器，把 ~100MB 运行时内存全部让给 Minecraft。游戏是独立
        进程，关闭启动器不会影响它；启动器开的进程轮询也随窗口销毁而停止。
        配置 `close_after_launch=False` 时保持启动器常驻。
        """
        try:
            from .settings_dialog import load_config
            if not load_config().get("close_after_launch", True):
                return
            # round-57 冲突修复：配置了「退出后命令」时必须让启动器常驻——
            # 退出钩子由本窗口的轮询定时器在游戏退出时触发，自动关闭会把
            # 定时器连同进程一起销毁，钩子永远不执行。
            if getattr(self, "_game_exit_cmd", ""):
                return
            delay = max(1, int(load_config().get("close_after_launch_delay", 5)))
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                delay * 1000,
                lambda: self._auto_close_if_game_running(name),
            )
        except Exception:  # noqa: BLE001 - 自动关闭失败绝不能崩启动器
            pass

    def _auto_close_if_game_running(self, name: str) -> None:
        """回调：到点且游戏进程仍存活 → 关闭启动器释放资源。"""
        try:
            proc = getattr(self, "_game_proc", None)
            if proc is not None and proc.poll() is None:
                self.statusBar().showMessage(
                    t("status.auto_close", name=name))
                self.close()  # 游戏独立进程，关启动器不影响游戏
        except Exception:  # noqa: BLE001
            pass

    def _poll_game(self):
        """轮询游戏进程：poll() 非 None = 已退出。"""
        proc = getattr(self, "_game_proc", None)
        if proc is None:
            try:
                self._game_poll_timer.stop()
            except Exception:
                pass
            return
        code = proc.poll()
        if code is not None:
            try:
                self._game_poll_timer.stop()
            except Exception:
                pass
            self._game_proc = None
            self._set_game_running_ui(False)
            # round-55 退出后命令：游戏进程退出时执行（实例/全局，失败静默）。
            try:
                from .launch import run_hook_cmd
                run_hook_cmd(getattr(self, "_game_exit_cmd", ""),
                             getattr(self, "_game_cwd", ""))
            except Exception:  # noqa: BLE001 - 退出钩子失败不影响状态展示
                pass
            # 控制台页：游戏退出 → 停止 tail 并追加结束标记
            _cp = getattr(self, "console_page", None)
            if _cp is not None:
                try:
                    _cp.set_game_finished(code)
                except Exception:
                    pass
            # round-48 C：退出原因分类——用退出码 + 崩溃日志特征给出可操作提示
            base = t("status.game_exited", name=getattr(self, "_game_name", ""), code=code)
            try:
                from .launch import explain_exit
                reason = explain_exit(code, getattr(self, "_game_log_path", None))
            except Exception:  # noqa: BLE001 - 分类失败退回到通用文案
                reason = ""
            self.statusBar().showMessage(f"{base} · {reason}" if reason else base)

    def _set_game_running_ui(self, running: bool):
        """同步首页 kill 按钮 / 启动按钮状态。"""
        try:
            home = getattr(self, "home", None)
            if home is None:
                return
            kill = getattr(home, "kill_btn", None)
            if kill is not None:
                kill.setVisible(running)
            play = getattr(home, "play_btn", None)
            if play is not None:
                play.setEnabled(not running)
                play.setText(t("home.game_running") if running else t("home.play"))
        except Exception:
            pass

    def kill_game(self) -> bool:
        """强制结束游戏进程（诊断/实例卡入口）。返回是否成功。"""
        proc = getattr(self, "_game_proc", None)
        if proc is None or proc.poll() is not None:
            return False
        try:
            import subprocess
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=10)
            else:
                proc.kill()
            try:
                self._game_poll_timer.stop()
            except Exception:
                pass
            self._game_proc = None
            self._set_game_running_ui(False)
            self.statusBar().showMessage(t("status.game_killed", name=getattr(self, "_game_name", "")))
            return True
        except Exception:
            return False

    def _on_launch_error(self, msg: str):
        self._progress.setVisible(False)
        # round-52：关闭启动进度对话框（避免错误弹窗与进度面板叠着）
        _dlg = getattr(self, "_launch_dlg", None)
        if _dlg is not None:
            try:
                _dlg.close()
            except Exception:  # noqa: BLE001
                pass
            self._launch_dlg = None
        self.statusBar().showMessage(t("status.launch_error", err=msg))
        self.home.play_btn.setEnabled(True)
        # 所有启动错误都显示对话框，不再只针对 Java 错误
        try:
            from PySide6.QtWidgets import QMessageBox, QFileDialog
            from .i18n import t as _t
            is_java_error = "java" in (msg or "").lower()
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(_t("err.launch_failed", default="启动失败"))
            box.setText(_t("err.launch_error_title", default="游戏启动失败"))
            box.setInformativeText(msg)
            
            if is_java_error:
                box.setDetailedText(msg)
                pick_btn = box.addButton(
                    _t("err.java_pick_btn", default="选择 Java..."),
                    QMessageBox.ButtonRole.AcceptRole)
                install_btn = box.addButton(
                    _t("err.java_install_btn", default="安装 Java"),
                    QMessageBox.ButtonRole.ActionRole)
                box.addButton(QMessageBox.StandardButton.Ok)
                box.exec()
                clicked = box.clickedButton()
                if clicked is pick_btn:
                    path, _ = QFileDialog.getOpenFileName(
                        self,
                        _t("err.java_pick_title", default="选择 java.exe"),
                        "",
                        "Java (java.exe javaw.exe);;All files (*)",
                    )
                    if path and os.path.isfile(path):
                        from .paths import get_data_dir
                        import json as _json
                        cfg_path = os.path.join(get_data_dir(), "launcher_config.json")
                        try:
                            with open(cfg_path, "r", encoding="utf-8") as _f:
                                cfg = _json.load(_f)
                        except Exception:
                            cfg = {}
                        cfg["java_auto"] = False
                        cfg["java_path"] = path
                        with open(cfg_path, "w", encoding="utf-8") as _f:
                            _json.dump(cfg, _f, ensure_ascii=False, indent=2)
                        # 重试用玩家选的 java
                        self.statusBar().showMessage(_t("status.retry_with_new_java"))
                        self._handle_play(self._last_inst or self.get_current_instance())
                elif clicked is install_btn:
                    # 打开设置页 Java 分区（让玩家一键安装）
                    self._open_settings()
                    if hasattr(self, "_sec_list") and hasattr(self, "_sec_stack"):
                        for i in range(self._sec_list.count()):
                            if self._sec_list.item(i).data(Qt.UserRole) == "java" \
                                    or i == 1:  # 第二项是 Java 分区
                                self._sec_list.setCurrentRow(i)
                                break
            else:
                # 非 Java 错误：简单显示错误信息，提供重试按钮
                retry_btn = box.addButton(
                    _t("err.retry", default="重试"),
                    QMessageBox.ButtonRole.AcceptRole)
                box.addButton(QMessageBox.StandardButton.Ok)
                box.exec()
                if box.clickedButton() is retry_btn:
                    self._handle_play(self._last_inst or self.get_current_instance())
        except Exception:
            pass
