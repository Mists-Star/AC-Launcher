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

from PySide6.QtCore import QSize, Qt, Signal, QEvent
from PySide6.QtGui import QFontDatabase, QFont

from PySide6.QtWidgets import (
    QApplication,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QTextEdit, QGroupBox, QCheckBox, QComboBox,
    QWidget, QTabWidget, QRadioButton, QButtonGroup,
    QSlider,
    QScrollArea, QListWidget, QListWidgetItem, QStackedWidget, QFrame,
    QSizePolicy, QStyledItemDelegate, QStyleOptionViewItem,
)
from PySide6.QtCore import QObject as _QObject

from .theme import COLORS, RoundedCard, set_accent_color, set_theme_mode, apply_qss
from . import ui_kit
from .icons import icon
from .paths import get_config_path, get_data_dir
from .launch import find_java
from .i18n import t, set_language
from .worker import Worker
from .core import authlib as authlib_dl
from .core.java import scan_javas, java_major
from .win_rounded import info, warn, pick_files, dark_color, enable_dark_titlebar

CONFIG_FILE = get_config_path("launcher_config.json")
# round-83 设置导出/导入：这些键永不写入/还原备份文件（密钥/脏开关）。
_SENSITIVE_CFG_KEYS = frozenset({
    "dev_mode_key",        # 开发者模式密钥
    "win_geometry",        # 窗口几何是本机 UI 态，跨机还原会飘出屏幕
})
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
    "wallpaper_mode": "none",      # none / solid / image / version / gif / video
    "wallpaper_color": "#1E1E1E",
    "wallpaper_image": "",
    "wallpaper_opacity": 1.0,          # 0..1
    "wallpaper_video_vol": 0.0,        # 0..1, video wallpaper volume
    # round-52 玻璃拟态恢复：半透明卡片（配合系统 Acrylic 透底）
    "frosted_theme": True,
    "home_style": "ac_default",        # 固定 AC 默认模板（模板切换已删除 round-32）
    # ---- advanced ----
    "java_auto": True,
    "java_path": "",
    "jvm_args": "",
    # round-55 启动高级设置（对齐主流「启动游戏/版本设置」）：
    "jvm_preset": "default",           # default / aikar / custom
    "game_args": "",                   # 游戏附加参数（--server <ip> 直连等）
    "version_isolation": "default",    # default / isolated
    "post_launch_cmd": "",             # 游戏启动后执行命令（shell）
    "exit_cmd": "",                    # 游戏退出后执行命令（shell）
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
    "bgm_mode": "loop",                 # loop / sequential / shuffle
    "bgm_files": [],                    # multi-file playlist (replaces bgm_file)
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
    "theme_mode": "light",           # light / dark
    "theme_pack": "",                # ""=none (built-in) / "control" / user pack id
    # ---- 液态流光 effect（round-49 新增）----
    "effect_light_trail": True,      # 卡片流体曳光 + 反射扫光
    "window_opacity": 1.0,           # 全局透明度 0.5..1.0（1.0=不透）
    # round-51 透底效果：系统级 Acrylic 真毛玻璃（半透明无边框窗口 + 圆角镂空）
    "transparent_window": True,      # 开启后窗口透桌面模糊（可读性依赖实色卡片）
    "page_transition": True,         # 页面切换淡入动画
    # ---- 退出释放资源（round-50）----
    "close_after_launch": True,      # 游戏启动并稳定运行后自动关闭启动器
    "close_after_launch_delay": 5,   # 检测游戏稳定运行的等待秒数
    # round-83 系统托盘（关窗藏托盘）：True = 点关闭按钮只是隐藏到托盘，
    # 游戏进程/下载任务不受影响；False = 恢复「关闭即退出」。
    "tray_minimize": True,
    # ---- download mirror ----
    # round-46 用户要求"全部优先镜像/速度优先"——默认 BMCLAPI（国内镜像速度快）
    "download_mirror": "bmclapi",   # official (官方 Mojang) / bmclapi (国内镜像，速度优先)
    # ---- network proxy for downloads ----
    "download_proxy": "",            # ""=system proxy, "none"=direct, or "http://host:port"
    # round-68 Quilt 加载器显示开关（close → 新建实例页隐藏 Quilt）
    "show_quilt": True,
    # round-78 联机工具偏好（round-64 三选一弹窗完善）：ask=每次弹选择器；
    # easytier=未安装时自动内置下载，不再询问（可在设置里改回 ask）
    "lobby_tool": "ask",
    # round-69 游戏进程优先级（对齐主流「进程优先级」；Windows creationflags）
    "process_priority": "normal",   # normal / high / realtime
    # ---- developer mode (gates experimental/test features) ----
    "dev_mode": False,               # enabled only after key verification
    "dev_mode_key": "",              # stored only for UI display; real key comes from env/file
    # round-80 设置折叠（常见做法）：记录被玩家收起的分组标题（i18n 当前语言标题）
    "collapsed_groups": [],
}


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # round-34 加固：合法 JSON 但非 dict（如 "[1]"、"\"str\""）→ 用默认值，
        # 否则 `{**_DEFAULTS, **data}` 抛 TypeError 导致启动崩溃。
        if isinstance(data, dict):
            cfg = {**_DEFAULTS, **data}
        else:
            return dict(_DEFAULTS)
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return dict(_DEFAULTS)
    # round-62 默认合规：顶部导航是实验功能（round-32 已删除设置入口，
    # 正常玩家无任何 UI 路径切过去）。配置文件里残留 "pcl2" 一律视为脏数据/
    # 手工编辑/测试脚本残留——除非同时显式开启了开发者模式（dev_mode=True），
    # 否则强制回退 AC 侧边导航默认值。
    if cfg.get("nav_layout") != "ac" and not cfg.get("dev_mode", False):
        cfg["nav_layout"] = "ac"
        cfg["dev_mode"] = False
    return cfg


def save_config(cfg: dict) -> None:
    tmp_path = CONFIG_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def _cfg_float(cfg: dict, key: str, default: float) -> float:
    """round-39 P2-4 加固：非法配置值（None/字符串/缺失）→ 默认值，不抛异常。"""
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


class _FoldMgr(_QObject):
    """round-80 自研折叠分组（另一种方法，不用 checkable 勾选框）。

    常见「可折叠卡片」：标题栏整条可点击，标题前缀用 ▸/▾ 指示
    折叠状态，点击即收起/展开组内内容控件。折叠状态即时写入配置并持久化
    （key: collapsed_groups -> 收起的分组标题列表）。

    绑定用事件过滤器 + title 前缀，完全不动现有分组创建/布局代码——
    只需要在分组建完后对根布局跑一次 apply()。标题作为持久化 key 会随
    语言切换而变化，切换后旧 key 匹配不上会退回默认折叠，可接受。
    """

    # 标题栏点击带：字体行高 + 上下留白
    _STRIP = 12

    def __init__(self, get_cfg, save_cfg):
        _QObject.__init__(self)
        self._get_cfg = get_cfg
        self._save_cfg = save_cfg
        try:
            self._folded: set = set(get_cfg().get("collapsed_groups", []) or [])
        except Exception:  # noqa: BLE001 - 折叠配置损坏不影响界面
            self._folded = set()

    # ── 绑定 ──────────────────────────────────────────────
    def apply(self, layout, default_collapsed: bool) -> None:
        """把根布局里的顶层 QGroupBox 全部绑定为可折叠。

        ``default_collapsed`` 仅在玩家从未碰过该分组时生效（未出现在
        配置里）；一旦玩家手动切换过，以玩家状态为准。
        """
        for i in range(layout.count()):
            it = layout.itemAt(i)
            w = it.widget() if it else None
            if isinstance(w, QGroupBox):
                self._bind(w, default_collapsed)

    def _bind(self, box: QGroupBox, default_collapsed: bool) -> None:
        plain = box.title()
        if plain.startswith(("▸ ", "▾ ")):
            plain = plain[2:].strip()
        box.setProperty("fold_plain", plain)
        if plain in self._folded:
            folded = True
        elif default_collapsed:
            # 玩家从未操作过 → 默认收起（仅内存标记；首次手动展开时才会
            # 写入配置，避免首启就塞满一大串 collapsed_groups）
            folded = True
        else:
            folded = False
        box.setProperty("folded", folded)
        box.installEventFilter(self)
        self._render(box)

    # ── 事件：点标题栏切换 ────────────────────────────────
    def eventFilter(self, obj, ev):
        if not isinstance(obj, QGroupBox):
            return False
        # 用 MouseButtonPress：避免从标题栏起手拖动滚动时，松手在条带内
        # 误触发折叠；press 阶段即接受事件，标题行不再参与滚动拖动。
        if ev.type() == QEvent.MouseButtonPress and obj.isEnabled():
            strip = obj.fontMetrics().height() + self._STRIP
            if 0 < ev.position().y() <= strip:
                self._toggle(obj)
                return True               # 点击已消费，不再进入滚动等
        return False

    def _toggle(self, box: QGroupBox) -> None:
        folded = not bool(box.property("folded"))
        box.setProperty("folded", folded)
        self._render(box)
        plain = box.property("fold_plain") or ""
        try:
            cfg = self._get_cfg()
            if not isinstance(cfg.get("collapsed_groups"), list):
                cfg["collapsed_groups"] = []
            lst = set(cfg["collapsed_groups"])
            if folded:
                lst.add(plain)
            else:
                lst.discard(plain)
            cfg["collapsed_groups"] = sorted(lst)
            self._folded = lst
            self._save_cfg(cfg)
        except Exception:  # noqa: BLE001 - 持久化失败不影响折叠交互
            pass

    def _render(self, box: QGroupBox) -> None:
        """标题加 ▸/▾ 前缀；折叠时隐藏全部内容子控件，仅剩标题一行。"""
        folded = bool(box.property("folded"))
        plain = box.property("fold_plain") or box.title()
        box.setTitle(("▸ " if folded else "▾ ") + plain)
        for ch in box.children():
            # 布局对象是 QObject 不是 QWidget，自动跳过；内容控件全部隐藏
            if isinstance(ch, QWidget) and isinstance(ch, QGroupBox) is False:
                ch.setVisible(not folded)


def dev_mode_key() -> str:
    """Return the developer unlock key from environment or local file.

    The key is intentionally NOT shipped in the repository. Packagers or
    testers set AC_LAUNCHER_DEV_KEY in the environment, or place it in
    <data_dir>/.dev_key, to unlock experimental UI options.
    """
    env = os.environ.get("AC_LAUNCHER_DEV_KEY", "").strip()
    if env:
        return env
    p = os.path.join(get_data_dir(), ".dev_key")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


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

# round-91 字体下拉：不再枚举候选列表，改为自动检测系统全部已安装字体
# （QFontDatabase.families()），每项用自身字形预览（_FontItemDelegate）。
class _FontItemDelegate(QStyledItemDelegate):
    """全量字体下拉的列表项 delegate：每项用其字体族名渲染，即时预览效果。

    普通 QComboBox 只列名字，全系统几百个字体时来回切换看不出差别；
    此 delegate 在弹层列表里把每个字体以自身字形渲染，所见即所得。
    「跟随系统默认」首项 data 为空字符串，走默认字体（不套字体族）。
    """

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        fam = index.data(Qt.UserRole) or ""
        if fam:
            opt.font.setFamily(fam)
            opt.font.setPointSize(11)
        super().paint(painter, opt, index)


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

    def eventFilter(self, obj, event):
        # Disable mouse-wheel on scroll-sensitive controls so scrolling the
        # settings page does NOT accidentally bump resolution / memory /
        # combo-box values. round-66：从仅 QSpinBox 扩展到 QComboBox + QSlider
        # （此前内存滑条、语言/JVM 预设、透明度等悬停滚轮仍会误调数值）。
        if event.type() == QEvent.Wheel and isinstance(obj, (QSpinBox, QComboBox, QSlider)):
            event.ignore()
            return True
        return super().eventFilter(obj, event)

    # ═══════════════════════════════════════════════════════════════════════
    # UI BUILD
    # ═══════════════════════════════════════════════════════════════════════
    def _sync_font_btn(self, *_):
        """round-91 字体下拉按钮文字用当前选中的字体族渲染。

        列表项预览由 _FontItemDelegate 负责；按钮（折叠态）文字也同步成
        该字体字形，「跟随系统默认」恢复 QFont()。
        """
        fam = self.font_combo.currentData() or ""
        self.font_combo.setFont(QFont(fam, 11) if fam else QFont())

    def _wrap_hint(self, text: str) -> QLabel:
        """round-52 自适应：创建可换行的次级说明标签。

        长 hint 文本若不换行，会把所在 GroupBox 的 minimumSizeHint 撑到
        700+px，窄窗口下横向溢出（且横向滚动条被禁用 → 内容被截断）。
        """
        lbl = QLabel(text)
        lbl.setProperty("cls", "sub")
        lbl.setWordWrap(True)
        return lbl

    def _wrap_scroll(self, content: QWidget) -> QScrollArea:
        """Wrap a tab page in a QScrollArea so overflowing content stays reachable.

        round-90 UI 原则：不出现底部横条滚动。横向溢出改由内容自身收缩
        （sizePolicy=Ignored：忽略内容固有宽度、强制贴合视口宽），长文本
        文本自动换行、QGroupBox 标题自动省略，右侧内容永远完整可见。
        纵向仍然保留滚动。
        """
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sa.setWidget(content)
        sa.setFrameShape(QScrollArea.NoFrame)
        return sa

    def _build_ui(self):
        self.cfg = load_config()
        self._custom_color = ""
        # round-66：对整个设置对话框安装事件过滤器，覆盖窗口内所有
        # QSpinBox / QComboBox / QSlider —— 滚动页面时悬停不再误调数值。
        self.installEventFilter(self)

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

        # ── page header ──
        root.addWidget(ui_kit.page_header(
            t("settings.title"), icon_key="settings"))

        # ── round-46 左分区菜单 + 右内容（用户：不要底部滑动）──
        # round-68 设置简化：左分区从三分区（快速设置/Java/高级设置）
        # 合并为两分区（设置 / Java 管理）；右：QStackedWidget
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        self._sec_list = QListWidget()
        self._sec_list.setObjectName("settings-sections")
        self._sec_list.setFixedWidth(168)
        self._sec_list.setIconSize(QSize(18, 18))
        self._sec_list.setSpacing(2)
        self._sec_list.setContentsMargins(8, 12, 8, 12)
        for key, ico in (("settings", "sliders"), ("java", "java")):
            it = QListWidgetItem(icon(ico), t(f"settings.sec_{key}"))
            self._sec_list.addItem(it)
        bl.addWidget(self._sec_list)

        self._sec_stack = QStackedWidget()
        # round-46 设置页挤压根治：内容多必然超一屏（快速设置 6+ grp），
        # 不滚动 = grp 被压扁（用户反馈"挤压问题没解决"）。恢复每页独立
        # QScrollArea（纵向滚动正常；横向滚动条禁用），内容按 Preferred 排满。
        for page in (self._build_settings(), self._build_java_group()):
            wrapper = QWidget()
            wl = QVBoxLayout(wrapper)
            wl.setContentsMargins(0, 0, 0, 0)
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            # round-90 横溢出修复：不出现底部横条（UI 原则），改为内容
            # 强制收缩到视口宽度（sizePolicy=Ignored 忽略内容固有宽度），
            # 长文本/QGroupBox 标题由 Qt 自动换行/省略，右侧永远完整可见。
            page.setMinimumWidth(0)
            page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            sa.setWidget(page)
            wl.addWidget(sa)
            self._sec_stack.addWidget(wrapper)
        bl.addWidget(self._sec_stack, stretch=1)
        self._sec_list.currentRowChanged.connect(self._sec_stack.setCurrentIndex)
        self._sec_list.setCurrentRow(0)
        root.addWidget(body, stretch=1)

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
    # SETTINGS PANEL（round-68 合并页：原「快速设置」+「高级设置」）
    # ═══════════════════════════════════════════════════════════════════════
    def _build_settings(self) -> QWidget:
        """round-68 设置简化：把原三分区的前两页（快速设置/高级设置）
        纵向合并为单一「设置」页（放到 QScrollArea 里滚动查看）。
        Java 相关仍留在独立的「Java 管理」分区（_build_java_group）。
        round-80 折叠简化：quick 分组默认展开，advanced 分组默认收起，
        点击标题栏切换，状态即时持久化。"""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        quick = self._build_quick()
        adv = self._build_advanced()
        # round-83 设置导出/导入：备份/还原全局设置（跳过敏感字段）。
        # 独立成组不参与折叠——玩家找"备份"时永远能直接看到。
        lay.addWidget(quick)
        bk_grp = QGroupBox(t("settings.cfg_backup"))
        bkl = QVBoxLayout(bk_grp)
        bkl.setSpacing(8)
        bk_hint = QLabel(t("settings.cfg_backup_hint"))
        bk_hint.setProperty("cls", "sub")
        bk_hint.setWordWrap(True)
        bkl.addWidget(bk_hint)
        bk_row = QHBoxLayout()
        ex_b = QPushButton(t("settings.cfg_export_btn"))
        im_b = QPushButton(t("settings.cfg_import_btn"))
        ex_b.clicked.connect(self._export_settings)
        im_b.clicked.connect(self._import_settings)
        bk_row.addWidget(ex_b)
        bk_row.addWidget(im_b)
        bk_row.addStretch(1)
        bkl.addLayout(bk_row)
        lay.addWidget(bk_grp)
        # round-80 折叠绑定：标题栏点击切换，▸/▾ 前缀指示状态。
        # 默认收起只发生在玩家从未碰过该分组时；手动切换后以玩家为准。
        # 注意：必须用 self 持有引用——事件过滤器被 GC 会悬垂崩溃。
        self._fold_mgr = _FoldMgr(load_config, save_config)
        self._fold_mgr.apply(quick.layout(), default_collapsed=False)
        self._fold_mgr.apply(adv.layout(), default_collapsed=True)
        lay.addWidget(adv)
        # round-86 关于/守则置底：放在所有设置项最后（备份组、高级折叠组之后）
        lay.addWidget(self._build_about())
        return w

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
        # round-79b：预设从 3 档扩到 8 档（16:9 / 16:10 / 超宽 / 4K），
        # 每行 4 个分两行排，避免一行挤爆对话框宽度。
        for row_res in [
            [(1280, 720, t("settings.res_hd")),
             (1600, 900, t("settings.res_900p")),
             (1920, 1080, t("settings.res_fhd")),
             (1920, 1200, t("settings.res_16x10_fhd"))],
            [(2560, 1440, t("settings.res_2k")),
             (2560, 1600, t("settings.res_16x10_2k")),
             (3440, 1440, t("settings.res_ultrawide")),
             (3840, 2160, t("settings.res_4k"))],
        ]:
            res_row = QHBoxLayout()
            for rw, rh, label in row_res:
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
            # round-79：英文标“实验性”（未全量中文化）
            ("en-US", t("settings.lang_en_lab")),
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

        # ── Interface font (round-87 玩家可改全局字体；round-91 全量字体) ──
        font_grp = QGroupBox(t("settings.font_family"))
        fntl = QVBoxLayout(font_grp)
        fntl.setSpacing(8)
        self.font_combo = QComboBox()
        # 自动检测系统全部已安装字体（字母序，中文系统返回中文字体名）
        _families = list(QFontDatabase.families()) if QFontDatabase is not None else []
        _families = sorted({f for f in _families if f}, key=str.lower)
        self.font_combo.addItem(t("settings.font_default"), "")   # 跟随系统默认
        for _fam in _families:
            self.font_combo.addItem(_fam, _fam)
        # round-91 列表项各用自身字形预览；按钮文字跟随当前选中字体
        self.font_combo.setItemDelegate(_FontItemDelegate(self.font_combo))
        self.font_combo.currentIndexChanged.connect(self._sync_font_btn)
        _cur_font = self.cfg.get("font_family", "") or ""
        _fi = self.font_combo.findData(_cur_font)
        self.font_combo.setCurrentIndex(_fi if _fi >= 0 else 0)
        self._sync_font_btn()
        fntl.addWidget(self.font_combo)
        fntl.addWidget(self._wrap_hint(t("settings.font_family_hint")))
        lay.addWidget(font_grp)

        # ── Appearance: color picker + wallpaper + home style ──
        # ── 拆分：原来一个外观 grp 塞 4 类内容，按常见风格独立成 4 个 grp ──
        # 1. 外观（主题色 + 主题模式）
        app_grp = QGroupBox(t("settings.appearance"))
        apl = QVBoxLayout(app_grp)
        apl.setSpacing(12)

        # Accent color dots
        cl = QHBoxLayout()
        cl.addWidget(QLabel(t("settings.color_label")))
        self.color_btns = []
        current_accent = self.cfg.get("accent_color", "#7C3AED")
        self._selected_color = current_accent
        for hex_c, name in ACCENT_PRESETS:
            dot = QPushButton()
            dot.setFixedSize(30, 30)
            dot.setCursor(Qt.PointingHandCursor)
            dot.setToolTip(name)
            dot.color_hex = hex_c
            dot._is_selected = (hex_c == current_accent)
            dot.clicked.connect(lambda checked, h=hex_c: self._pick_color(h))
            self._apply_dot_style(dot)
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
        self.theme_btns.buttonClicked.connect(self._on_theme_toggle)

        # round-49 液态流光 effect：流光卡片 / 页面动画 / 全局透明度
        fx_row = QHBoxLayout()
        fx_row.setSpacing(18)
        self.effect_trail_chk = QCheckBox(t("settings.effect_light_trail"))
        self.effect_trail_chk.setChecked(self.cfg.get("effect_light_trail", True))
        self.effect_trail_chk.toggled.connect(self._on_effect_trail)
        fx_row.addWidget(self.effect_trail_chk)
        self.page_trans_chk = QCheckBox(t("settings.page_transition"))
        self.page_trans_chk.setChecked(self.cfg.get("page_transition", True))
        fx_row.addWidget(self.page_trans_chk)
        # round-51 透底效果开关（系统 Acrylic 半透明窗口）
        self.transparent_chk = QCheckBox(t("settings.transparent_window"))
        self.transparent_chk.setChecked(self.cfg.get("transparent_window", True))
        self.transparent_chk.toggled.connect(self._on_transparent_toggle)
        fx_row.addWidget(self.transparent_chk)
        # round-52 玻璃拟态开关（半透明卡片样式）
        self.frosted_chk = QCheckBox(t("settings.frosted_theme"))
        self.frosted_chk.setChecked(self.cfg.get("frosted_theme", True))
        self.frosted_chk.setToolTip(t("settings.frosted_theme_hint"))
        self.frosted_chk.toggled.connect(self._on_frosted_toggle)
        fx_row.addWidget(self.frosted_chk)
        # round-50 退出释放资源：游戏启动后自动关闭启动器
        self.close_launch_chk = QCheckBox(t("settings.close_after_launch"))
        self.close_launch_chk.setChecked(self.cfg.get("close_after_launch", True))
        fx_row.addWidget(self.close_launch_chk)
        # round-83 系统托盘：关窗最小化到托盘（无窗口图标全托给托盘常驻）
        self.tray_chk = QCheckBox(t("settings.tray_minimize"))
        self.tray_chk.setChecked(self.cfg.get("tray_minimize", True))
        self.tray_chk.setToolTip(t("settings.tray_minimize_hint"))
        fx_row.addWidget(self.tray_chk)
        # round-79b 窗口置顶（B 节补完）：阅读/写关卡时固定在最前
        self.topmost_chk = QCheckBox(t("settings.always_on_top"))
        self.topmost_chk.setChecked(self.cfg.get("topmost", False))
        self.topmost_chk.toggled.connect(self._on_topmost_toggle)
        fx_row.addWidget(self.topmost_chk)
        fx_row.addStretch(1)
        apl.addLayout(fx_row)

        op_row = QHBoxLayout()
        op_row.setSpacing(8)
        op_row.addWidget(QLabel(t("settings.window_opacity")))
        self.win_opacity = QSlider(Qt.Horizontal)
        self.win_opacity.setRange(50, 100)
        self.win_opacity.setValue(
            int(round(self.cfg.get("window_opacity", 1.0) * 100)))
        self.win_opacity.setFixedWidth(220)
        self.win_opacity.valueChanged.connect(self._on_opacity_changed)
        op_row.addWidget(self.win_opacity)
        self.opacity_lbl = QLabel(f"{self.win_opacity.value()}%")
        self.opacity_lbl.setProperty("cls", "sub")
        op_row.addWidget(self.opacity_lbl)
        op_row.addStretch(1)
        apl.addLayout(op_row)
        lay.addWidget(app_grp)

        # 2. 主题包（独立 grp：下拉 + 导入/导出 + 提示）
        pack_grp = QGroupBox(t("settings.theme_pack_section"))
        pkl = QVBoxLayout(pack_grp)
        pkl.setSpacing(10)
        pk_row = QHBoxLayout()
        self.pack_combo = QComboBox()
        self.pack_combo.setMinimumHeight(30)
        self.pack_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.pack_combo.setMaximumWidth(320)
        pk_row.addWidget(self.pack_combo, stretch=1)
        import_btn = QPushButton(t("settings.theme_pack_import"))
        import_btn.setMinimumHeight(30)
        import_btn.clicked.connect(self._import_theme_pack)
        pk_row.addWidget(import_btn)
        export_btn = QPushButton(t("settings.theme_pack_export"))
        export_btn.setMinimumHeight(30)
        export_btn.clicked.connect(self._export_theme_pack)
        pk_row.addWidget(export_btn)
        pkl.addLayout(pk_row)
        pk_hint = QLabel(t("settings.theme_pack_hint"))
        pk_hint.setProperty("cls", "sub")
        pk_hint.setWordWrap(True)
        pkl.addWidget(pk_hint)
        lay.addWidget(pack_grp)
        self._reload_pack_combo()
        self.pack_combo.currentIndexChanged.connect(self._on_pack_changed)

        # 3. 缓存清理（独立 grp，避免和外观挤一起）
        cache_grp = QGroupBox(t("settings.cache_section"))
        cgl = QVBoxLayout(cache_grp)
        cl_row = QHBoxLayout()
        cl_btn = QPushButton(t("settings.clear_cache"))
        cl_btn.setMinimumHeight(30)
        cl_btn.clicked.connect(self._clear_cache)
        cl_row.addWidget(cl_btn)
        cl_hint = QLabel(t("settings.clear_cache_hint"))
        cl_hint.setProperty("cls", "sub")
        cl_row.addWidget(cl_hint, stretch=1)
        cgl.addLayout(cl_row)
        lay.addWidget(cache_grp)

        # 4. 主页背景（独立 grp：模式 + 浏览 + 不透明度/音量 + hint）
        wp_grp = QGroupBox(t("settings.wallpaper_section"))
        wpl = QVBoxLayout(wp_grp)
        wpl.setSpacing(10)

        wp_row = QHBoxLayout()
        wp_row.addWidget(QLabel(t("settings.wallpaper_label")))
        self.wp_modes = QButtonGroup()
        # round-52 自适应：6 个 radio 拆成两行（3+3），窄窗口下不再横向溢出。
        wp_items = [
            ("none", t("settings.wp_none")),
            ("solid", t("settings.wp_solid")),
            ("image", t("settings.wp_image")),
            ("version", t("settings.wp_version")),
            ("gif", t("settings.wp_gif")),
            ("video", t("settings.wp_video")),
        ]
        for mode, label in wp_items[:3]:
            rb = QRadioButton(label)
            rb.setChecked(self.cfg.get("wallpaper_mode", "none") == mode)
            rb.wp_mode = mode
            self.wp_modes.addButton(rb)
            wp_row.addWidget(rb)
        wp_row.addStretch(1)
        wpl.addLayout(wp_row)
        wp_row2 = QHBoxLayout()
        for mode, label in wp_items[3:]:
            rb = QRadioButton(label)
            rb.setChecked(self.cfg.get("wallpaper_mode", "none") == mode)
            rb.wp_mode = mode
            self.wp_modes.addButton(rb)
            wp_row2.addWidget(rb)
        self.wp_browse = QPushButton(t("settings.wp_browse_btn"))
        self.wp_browse.setCursor(Qt.PointingHandCursor)
        self.wp_browse.setMinimumHeight(30)
        self.wp_browse.setProperty("cls", "accent")
        self.wp_browse.clicked.connect(self._browse_wallpaper)
        wp_row2.addWidget(self.wp_browse)
        wp_row2.addStretch(1)
        wpl.addLayout(wp_row2)

        wp_more = QHBoxLayout()
        self.wp_opacity = QSlider(Qt.Horizontal)
        self.wp_opacity.setRange(0, 100)
        self.wp_opacity.setMinimumWidth(120)
        self.wp_opacity.setMaximumWidth(240)
        self.wp_opacity.setValue(int(_cfg_float(self.cfg, "wallpaper_opacity", 1.0) * 100))
        wp_more.addWidget(QLabel(t("settings.wp_opacity")))
        wp_more.addWidget(self.wp_opacity, stretch=1)
        self.wp_vol = QSlider(Qt.Horizontal)
        self.wp_vol.setRange(0, 100)
        self.wp_vol.setMinimumWidth(120)
        self.wp_vol.setMaximumWidth(240)
        self.wp_vol.setValue(int(_cfg_float(self.cfg, "wallpaper_video_vol", 0.0) * 100))
        wp_more.addWidget(QLabel(t("settings.wp_volume")))
        wp_more.addWidget(self.wp_vol, stretch=1)
        wpl.addLayout(wp_more)
        # round-52 自适应：长 hint 文本必须换行，否则把 GroupBox 最小宽度撑到
        # 700+px，窄窗口下横向溢出（无法滚动）。
        wpl.addWidget(self._wrap_hint(t("settings.wp_hint")))
        lay.addWidget(wp_grp)

        # 主页模板 / 导航布局切换已删除（round-32 用户反馈：切换会导致窗口
        # 卡在一起）。固定使用 ac_default 主页 + AC 左侧导航。
        # 保留注释以便追溯：原 style_combo（4 模板）+ nav_combo（2 布局）。
        # 相关 _on_style_combo_changed / _on_nav_changed 处理函数保留为空实现。

        # 开发者模式块已删除（round-32 后续）："实验性功能"（模板/导航切换）
        # 已被删除，dev_mode 块没有功能可解锁——开放给玩家 = 直接可用，
        # 密钥输入/启用按钮/状态整体移除。dev_mode / dev_mode_key 字段保留
        # 以兼容历史 config。

        lay.addWidget(app_grp)

        # round-86 关于/守则类已移出 quick 折叠组，置底到设置页最下方
        # （见 _build_about），保证隐私/守则/免责永远在页面最底下。
        lay.addStretch(1)
        return w

    # round-86 关于/守则独立成组，置于设置页最底部：无论快速/高级怎么折叠，
    # 隐私协议/用户守则/免责声明永远在页面最底下（用户的排版直觉）。
    def _build_about(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(18)

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

        # ── JVM 启动优化（GC 调优，对应主流优化参数）──
        opt_grp = QGroupBox(t("settings.jvm_opts"))
        ol = QVBoxLayout(opt_grp)
        opt_hint = QLabel(t("settings.jvm_opts_hint"))
        opt_hint.setProperty("cls", "sub")
        opt_hint.setWordWrap(True)
        ol.addWidget(opt_hint)
        # round-55：Aikars 单勾选 → 三档预设下拉（默认 / Aikar 优化 / 自定义）。
        # 旧配置 jvm_aikars=True 自动映射到 aikar，不丢用户已有选择。
        _preset = self.cfg.get("jvm_preset", "") or (
            "aikar" if self.cfg.get("jvm_aikars", True) else "default")
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel(t("settings.jvm_preset")))
        self.jvm_preset_combo = QComboBox()
        self.jvm_preset_combo.addItem(t("settings.jvm_preset_default"), "default")
        self.jvm_preset_combo.addItem(t("settings.jvm_preset_auto"), "auto")
        self.jvm_preset_combo.addItem(t("settings.jvm_preset_aikar"), "aikar")
        self.jvm_preset_combo.addItem(t("settings.jvm_preset_custom"), "custom")
        _idx = self.jvm_preset_combo.findData(_preset)
        self.jvm_preset_combo.setCurrentIndex(_idx if _idx >= 0 else 0)
        preset_row.addWidget(self.jvm_preset_combo, stretch=1)
        ol.addLayout(preset_row)
        lay.addWidget(opt_grp)

        # ── 游戏附加参数 + 版本隔离（round-55，对齐主流「启动游戏 / 版本设置」）──
        ga_grp = QGroupBox(t("settings.game_args"))
        gal = QVBoxLayout(ga_grp)
        self.game_args_edit = QLineEdit(self.cfg.get("game_args", ""))
        self.game_args_edit.setPlaceholderText(t("settings.game_args_hint"))
        self.game_args_edit.setMinimumWidth(0)
        self.game_args_edit.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        gal.addWidget(self.game_args_edit)
        iso_row = QHBoxLayout()
        iso_row.addWidget(QLabel(t("settings.version_isolation")))
        self.version_iso_combo = QComboBox()
        self.version_iso_combo.addItem(
            t("settings.version_isolation_default"), "default")
        self.version_iso_combo.addItem(
            t("settings.version_isolation_isolated"), "isolated")
        _idx = self.version_iso_combo.findData(
            self.cfg.get("version_isolation", "default"))
        self.version_iso_combo.setCurrentIndex(_idx if _idx >= 0 else 0)
        iso_row.addWidget(self.version_iso_combo, stretch=1)
        gal.addLayout(iso_row)
        gal.addWidget(self._wrap_hint(t("settings.version_isolation_hint")))
        # round-69 进程优先级（对齐主流「进程优先级」，Windows creationflags 生效）
        pri_row = QHBoxLayout()
        pri_row.addWidget(QLabel(t("settings.process_priority")))
        self.priority_combo = QComboBox()
        self.priority_combo.addItem(t("settings.priority_normal"), "normal")
        self.priority_combo.addItem(t("settings.priority_high"), "high")
        self.priority_combo.addItem(t("settings.priority_realtime"), "realtime")
        _p = self.cfg.get("process_priority", "normal")
        _idx = self.priority_combo.findData(_p)
        self.priority_combo.setCurrentIndex(_idx if _idx >= 0 else 0)
        pri_row.addWidget(self.priority_combo, stretch=1)
        gal.addLayout(pri_row)
        gal.addWidget(self._wrap_hint(t("settings.process_priority_hint")))
        lay.addWidget(ga_grp)

        # ── 启动后 / 退出后命令（round-55，对齐主流「启动后执行命令」）──
        hook_grp = QGroupBox(t("settings.hook_cmd"))
        hl = QVBoxLayout(hook_grp)
        hl.addWidget(QLabel(t("settings.post_launch_cmd")))
        self.post_cmd_edit = QLineEdit(self.cfg.get("post_launch_cmd", ""))
        self.post_cmd_edit.setPlaceholderText(t("settings.hook_ph"))
        self.post_cmd_edit.setMinimumWidth(0)
        self.post_cmd_edit.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        hl.addWidget(self.post_cmd_edit)
        hl.addWidget(QLabel(t("settings.exit_cmd")))
        self.exit_cmd_edit = QLineEdit(self.cfg.get("exit_cmd", ""))
        self.exit_cmd_edit.setPlaceholderText(t("settings.hook_ph"))
        self.exit_cmd_edit.setMinimumWidth(0)
        self.exit_cmd_edit.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        hl.addWidget(self.exit_cmd_edit)
        hl.addWidget(self._wrap_hint(t("settings.hook_hint")))
        lay.addWidget(hook_grp)

        # Resolution spinboxes (wheel disabled to avoid accidental changes)
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

        # Java —— round-46 独立分区（用户：Java 管理反人类，别埋在高级设置里）
        # Java 由设置页左菜单独立分区展示（_build_ui 中 _build_java_group()）

        # Download mirror (BMCLAPI)
        mirror_grp = QGroupBox(t("settings.mirror"))
        ml = QVBoxLayout(mirror_grp)
        self.mirror_btns = QButtonGroup()
        self.mirror_btns.setExclusive(True)
        mrow = QHBoxLayout()
        for key, label in [
            ("auto", t("settings.mirror_auto")),
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
        # round-52 自适应：长 hint 文本换行，避免撑大 GroupBox 最小宽度。
        ml.addWidget(self._wrap_hint(t("settings.mirror_hint")))
        # round-79b 下载源测速（B 节补完）：一键探测并自动勾选最快源
        st_row = QHBoxLayout()
        self.mirror_test_btn = QPushButton(t("settings.mirror_speedtest"))
        self.mirror_test_btn.setProperty("cls", "secondary")
        self.mirror_test_btn.clicked.connect(self._on_mirror_speedtest)
        st_row.addWidget(self.mirror_test_btn)
        self.mirror_test_lbl = QLabel("")
        self.mirror_test_lbl.setProperty("cls", "sub")
        st_row.addWidget(self.mirror_test_lbl, stretch=1)
        ml.addLayout(st_row)
        lay.addWidget(mirror_grp)

        # 联机工具（round-78：未安装虚拟局域网工具时的 3 选 1 弹窗完善——
        # 可选「每次询问」或「自动用内置 EasyTier」；默认每次询问）
        lobby_grp = QGroupBox(t("settings.lobby_tool"))
        lg = QVBoxLayout(lobby_grp)
        self.lobby_tool_btns = QButtonGroup()
        self.lobby_tool_btns.setExclusive(True)
        lt_row = QHBoxLayout()
        for key, label in [
            ("ask", t("settings.lobby_tool_ask")),
            ("easytier", t("settings.lobby_tool_easytier")),
        ]:
            rb = QRadioButton(label)
            rb.setChecked(self.cfg.get("lobby_tool", "ask") == key)
            rb.lobby_key = key
            self.lobby_tool_btns.addButton(rb)
            lt_row.addWidget(rb)
        lt_row.addStretch(1)
        lg.addLayout(lt_row)
        lg.addWidget(self._wrap_hint(t("settings.lobby_tool_hint")))
        lay.addWidget(lobby_grp)

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
        # round-52 自适应：placeholder 长文本会撑大 minimumSizeHint 导致窄窗口
        # 横向溢出。禁止按 placeholder 撑宽 + 弹性伸缩，输入框随窗口收缩。
        self.proxy_edit.setMinimumWidth(0)
        self.proxy_edit.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.proxy_edit.textChanged.connect(lambda _: self._on_proxy_toggle())
        pl.addWidget(self.proxy_edit)
        # round-52 自适应：长 hint 文本必须换行，否则撑大 GroupBox 最小宽度。
        pl.addWidget(self._wrap_hint(t("settings.proxy_hint")))
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
        self.sound_vol.setValue(int(_cfg_float(self.cfg, "launch_sound_vol", 0.8) * 100))
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
        self.bgm_vol.setValue(int(_cfg_float(self.cfg, "bgm_vol", 0.4) * 100))
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
        self.sfx_vol.setValue(int(_cfg_float(self.cfg, "sfx_vol", 0.6) * 100))
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

        # round-68 Quilt 加载器显示开关（对齐主流「不显示 Quilt 加载器」：
        # 关闭后新建实例页不再出现 Quilt 卡片/版本）
        loader_grp = QGroupBox(t("settings.loader"))
        lg = QVBoxLayout(loader_grp)
        lg.setSpacing(8)
        self.show_quilt_chk = QCheckBox(t("settings.show_quilt"))
        self.show_quilt_chk.setChecked(bool(self.cfg.get("show_quilt", True)))
        lg.addWidget(self.show_quilt_chk)
        lg.addWidget(self._wrap_hint(t("settings.show_quilt_hint")))
        # round-71 非 ASCII 路径警告开关（对齐主流「不再提示」语义）
        self.warn_non_ascii_chk = QCheckBox(t("settings.warn_non_ascii_path"))
        self.warn_non_ascii_chk.setChecked(bool(self.cfg.get("warn_non_ascii_path", True)))
        lg.addWidget(self.warn_non_ascii_chk)
        lg.addWidget(self._wrap_hint(t("settings.warn_non_ascii_path_hint")))
        lay.addWidget(loader_grp)

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

    def _apply_dot_style(self, dot: QPushButton):
        """Apply a visible selection ring: dark border guarantees visibility on any theme.

        Uses a dark (#1F2937) 3px border for selected state — visible on both light
        and dark themes regardless of the accent color.
        """
        if dot._is_selected:
            dot.setStyleSheet(
                f"QPushButton {{ background: {dot.color_hex}; border-radius: 12px; "
                f"border: 3px solid #1F2937; }}"
                f"QPushButton:hover {{ border: 3px solid #1F2937; }}"
            )
        else:
            dot.setStyleSheet(
                f"QPushButton {{ background: {dot.color_hex}; border-radius: 12px; "
                f"border: 2px solid transparent; }}"
                f"QPushButton:hover {{ border: 2px solid #9CA3AF; }}"
            )

    def _pick_color(self, hex_color: str):
        """Preset color dot clicked — apply immediately."""
        from .theme import set_accent_color, apply_qss
        from .achievements import achievements as _ach
        _ach.unlock("first_theme")
        self._selected_color = hex_color
        for dot in self.color_btns:
            dot._is_selected = (dot.color_hex == hex_color)
            self._apply_dot_style(dot)
        # Apply accent color globally so user sees the change instantly
        set_accent_color(hex_color)
        app = QApplication.instance()
        if app:
            apply_qss()

    def _pick_color_custom(self):
        from .theme import set_accent_color, apply_qss
        c = dark_color(self, self._custom_color or "#3B82F6")
        if c:
            self._selected_color = c
            self._custom_color = c
            for dot in self.color_btns:
                dot._is_selected = False
                self._apply_dot_style(dot)
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

        # "version" mode also browses for a still image, but keeps the mode
        # so the image acts as an override on top of the version theme.
        if mode in ("none", "solid", "version"):
            mode = "image"
            filt = filters["image"]
            title = title_map["image"]

        path = pick_files(self, title, "", filt)
        if path:
            self.cfg["wallpaper_image"] = path
            # In version mode keep the mode; otherwise auto-detect from extension.
            if checked and getattr(checked, "wp_mode", None) != "version":
                self.cfg["wallpaper_mode"] = guess_mode(path)
                for rb in self.wp_modes.buttons():
                    if rb.wp_mode == self.cfg["wallpaper_mode"]:
                        rb.setChecked(True)
            # Preview immediately on home page
            try:
                from .main_window import MainWindow
                parent = self.parent()
                if isinstance(parent, MainWindow) and hasattr(parent, 'home'):
                    parent.home._apply_wallpaper(version_id=parent._current_version_id())
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

    def _build_java_group(self) -> QWidget:
        """round-46：Java 设置独立分区（设置页左菜单「Java」）。

        从旧 _build_advanced 里提取：Java 管理单独成区，不再埋在高级设置。
        卡片化美化：顶部自动/手动+路径 + 已知 Java 列表卡片。
        """
        # 顶层卡片容器（外边距+背景）
        wrap = QWidget()
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(24, 20, 24, 24)
        vl.setSpacing(14)

        # 卡片 1：Java 运行时选择（自动/手动模式 + 路径）
        card_sel = QGroupBox(t("settings.java"))
        sl = QVBoxLayout(card_sel)
        sl.setContentsMargins(16, 18, 16, 16)
        sl.setSpacing(10)

        self.java_auto = QCheckBox(t("settings.java_auto"))
        self.java_auto.setChecked(bool(self.cfg["java_auto"]))
        sl.addWidget(self.java_auto)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.java_path = QLineEdit(self.cfg["java_path"])
        self.java_path.setPlaceholderText(t("settings.java_path"))
        browse = QPushButton(t("settings.browse"))
        browse.setProperty("cls", "secondary")
        browse.clicked.connect(self._browse_java)
        detect = QPushButton(t("settings.detect"))
        detect.setProperty("cls", "secondary")
        detect.clicked.connect(self._detect_java)
        row.addWidget(self.java_path, stretch=1)
        row.addWidget(browse)
        row.addWidget(detect)
        sl.addLayout(row)
        vl.addWidget(card_sel)

        # 卡片 2：已识别的 Java 列表
        card_list = QGroupBox(t("settings.java_quick_label"))
        ll = QVBoxLayout(card_list)
        ll.setContentsMargins(16, 18, 16, 16)
        ll.setSpacing(8)
        self.java_quick_list = QWidget()
        qlay = QVBoxLayout(self.java_quick_list)
        qlay.setContentsMargins(0, 0, 0, 0)
        qlay.setSpacing(4)
        ll.addWidget(self.java_quick_list)
        # round-46 用户反馈"设置打开慢"：scan_javas() 扫注册表可能 1-2 秒，
        # 改为 Worker 后台线程执行，完成后更新 UI。
        self._java_scan_worker = Worker(scan_javas)
        self._java_scan_worker.finished.connect(self._on_java_scan_done)
        self._java_scan_worker.start()
        vl.addWidget(card_list, stretch=1)

        # 底部：管理按钮
        manage_row = QHBoxLayout()
        manage_btn = QPushButton(t("settings.java_manage"))
        manage_btn.setProperty("cls", "accent")
        manage_btn.setMinimumHeight(34)
        manage_btn.clicked.connect(self._open_java_manager)
        manage_row.addStretch(1)
        manage_row.addWidget(manage_btn)
        vl.addLayout(manage_row)

        return wrap

    def _browse_java(self):
        path = pick_files(
            self, t("settings.java_browse_title"), "", "Java (*.exe)"
        )
        if path:
            self.java_path.setText(path)
            self.java_auto.setChecked(False)
            self._refresh_java_quick_list()

    def _on_mirror_speedtest(self):
        """round-79b：测速选优——后台 HEAD 两源，完成自动勾选最快源。"""
        if getattr(self, "_mirror_testing", False):
            return
        self._mirror_testing = True
        self.mirror_test_btn.setEnabled(False)
        self.mirror_test_lbl.setText(t("settings.mirror_speedtesting"))
        from . import net_api
        self._mirror_worker = Worker(net_api.mirror_latencies)
        self._mirror_worker.finished.connect(self._finish_mirror_test)
        self._mirror_worker.start()

    def _finish_mirror_test(self, res: dict):
        """round-79b：测速完成——展示结果并勾选最快源。"""
        try:
            o = res.get("official")
            b = res.get("bmclapi")

            def _fmt(v):
                return f"{v:.0f}ms" if v is not None else "\u2014"

            best = None
            for key, ms in (("official", o), ("bmclapi", b)):
                if ms is not None and (best is None or ms < best[1]):
                    best = (key, ms)
            text = ("  ·  ").join([
                f"{t('settings.mirror_lbl_official')} {_fmt(o)}",
                f"{t('settings.mirror_lbl_bmclapi')} {_fmt(b)}",
            ])
            if best:
                for rb in self.mirror_btns.buttons():
                    if getattr(rb, "mirror_key", None) == best[0]:
                        rb.setChecked(True)
                        break
                text += f"   \u2192  {t('settings.mirror_recommend')}"
            self.mirror_test_lbl.setText(text)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.mirror_test_btn.setEnabled(True)
            self._mirror_testing = False

    def _on_java_scan_done(self, entries: list):
        """Slot called on main thread when the background Java scan finishes."""
        self._refresh_java_quick_list_with(entries)

    def _refresh_java_quick_list(self):
        """Rebuild the "快速选择" Java list — called when user triggers a manual
        refresh (e.g. after browsing for a Java). Uses a Worker to avoid blocking.
        """
        self._java_scan_worker = Worker(scan_javas)
        self._java_scan_worker.finished.connect(self._on_java_scan_done)
        self._java_scan_worker.start()

    def _refresh_java_quick_list_with(self, entries: list):
        """Populate the Java quick list from pre-scanned entries (on main thread).

        Each row: Java major + version + path + "使用" button. One click
        sets the path + disables auto-select. Mirrors mainstream launchers' quick-pick UX.
        """
        from PySide6.QtWidgets import QFrame
        # Tear down previous rows
        qlay = self.java_quick_list.layout()
        while qlay.count():
            item = qlay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
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
                from .ui_kit import state_pix
                warn_box = QWidget()
                wl = QHBoxLayout(warn_box)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.setSpacing(6)
                wi = QLabel()
                wi.setPixmap(state_pix("warn", COLORS["danger"], 14))
                wi.setFixedSize(15, 15)
                wt = QLabel(t("javamgr.not_recommended"))
                wt.setStyleSheet(
                    f"font-size:11px; color:{COLORS['danger']};")
                wt.setWordWrap(True)
                wl.addWidget(wi, 0, Qt.AlignTop)
                wl.addWidget(wt, 1)
                info.addWidget(warn_box)
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

    def _on_frosted_toggle(self, on: bool):
        """Live 玻璃拟态开关（round-52）：半透明卡片 / 实色卡片即时切换。"""
        try:
            from .theme import set_frosted
            set_frosted(on)
            apply_qss()
        except Exception:  # noqa: BLE001
            pass

    def _on_topmost_toggle(self, on: bool):
        """Live 窗口置顶开关（round-79b）：即时让主窗置顶/取消置顶。"""
        win = self._window
        if win is not None:
            try:
                win.apply_topmost(on)
            except Exception:  # noqa: BLE001 - 个别平台不支持时不打扰
                pass

    def _on_effect_trail(self, on: bool):
        """Live-toggle 流光卡片 / 页面动画（round-49）。"""
        from .effects import set_effects_enabled
        try:
            win = self._window
            set_effects_enabled(on)
            if win is not None and hasattr(win, "home"):
                win.home.rebuild()
        except Exception:  # noqa: BLE001
            pass

    def _on_opacity_changed(self, val: int):
        """Live 应用全局透明度（round-49）。"""
        from .effects import set_window_opacity
        try:
            self.opacity_lbl.setText(f"{val}%")
            win = self._window
            if win is not None:
                set_window_opacity(win, val / 100.0)
        except Exception:  # noqa: BLE001
            pass

    def _on_transparent_toggle(self, on: bool):
        """Live 透底效果开关（round-51）：切系统 Acrylic + 半透明背景。"""
        try:
            from .theme import set_app_background_translucent, apply_qss
            set_app_background_translucent(on)
            apply_qss()
            win = self._window
            if win is not None and hasattr(win, "_apply_transparent_window"):
                win._apply_transparent_window()
        except Exception:  # noqa: BLE001
            pass

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

    def _export_settings(self):
        """round-83 设置导出：收集当前 UI 值 → JSON（跳过敏感字段）保存。"""
        from .win_rounded import pick_folder, warn, info
        dlg_dir = pick_folder(self, t("settings.cfg_export_title"))
        if not dlg_dir:
            return
        try:
            from . import _SENSITIVE_CFG_KEYS
            self._sync_ui_to_cfg()
        except Exception:  # noqa: BLE001 - 收集失败仍可导出已持久化档
            pass
        target = dict(self.cfg)
        for k in _SENSITIVE_CFG_KEYS:
            target.pop(k, None)
        import time as _time
        dest = os.path.join(dlg_dir, f"ac-config-{_time.strftime('%Y%m%d-%H%M%S')}.json")
        try:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(target, f, ensure_ascii=False, indent=2)
        except OSError as e:
            warn(self, t("settings.cfg_export_fail"), str(e))
            return
        info(self, t("settings.cfg_export"), t("settings.cfg_export_done", path=dest))

    def _import_settings(self):
        """round-83 设置导入：读 JSON → 仅合并已知键 → 写回并重建设置页/外观。"""
        from .win_rounded import pick_files, warn, info
        from . import _SENSITIVE_CFG_KEYS
        path = pick_files(self, t("settings.cfg_import_title"), "", "配置文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("bad config payload")
        except Exception as e:  # noqa: BLE001
            warn(self, t("settings.cfg_import_fail"), str(e))
            return
        # 只取已知键（防脏 json 塞入未知字段污染 cfg）；敏感键一律不还原
        n = 0
        for k in _DEFAULTS:
            if k in _SENSITIVE_CFG_KEYS:
                continue
            if k in data and data[k] is not None:
                self.cfg[k] = data[k]
                n += 1
        save_config(self.cfg)
        # 重建设置页（控件取新值）并即时套用外观
        try:
            self._rebuild()
            from .theme import set_theme_mode, set_accent_color, apply_qss, set_frosted
            set_frosted(self.cfg.get("frosted_theme", True))
            set_theme_mode(self.cfg.get("theme_mode", "light"))
            set_accent_color(self.cfg.get("accent_color", "#7C3AED"))
            apply_qss()
        except Exception:  # noqa: BLE001 - 外观失败不阻断导入本身
            pass
        info(self, t("settings.cfg_import"), t("settings.cfg_import_done", n=n))

    def _clear_cache(self):
        """清理下载/图标缓存（不删配置与实例数据）。round-42。"""
        from .paths import get_data_dir
        import shutil
        freed = 0
        for sub in ("cache/icons", "cache"):
            p = os.path.join(get_data_dir(), sub)
            if os.path.isdir(p):
                for name in os.listdir(p):
                    fp = os.path.join(p, name)
                    try:
                        if os.path.isfile(fp):
                            freed += os.path.getsize(fp)
                            os.remove(fp)
                        elif os.path.isdir(fp):
                            freed += sum(
                                os.path.getsize(os.path.join(r, f))
                                for r, _, ns in os.walk(fp) for f in ns)
                            shutil.rmtree(fp, ignore_errors=True)
                    except OSError:
                        pass
        info(self, t("settings.clear_cache"),
             t("settings.clear_cache_done", mb=freed / 1024 / 1024))

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
        # round-40 P3 泄漏修复：复用实例而不是每次新建 QMediaPlayer
        # （之前反复点预览累积未释放的 SoundPlayer）
        if getattr(self, "_preview_player", None) is None:
            self._preview_player = SoundPlayer(self)
        self._preview_player.play(f, self.sound_vol.value() / 100.0)

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
            # round-46 用户反馈"英文切不回中文"：原逻辑只在内存改 cfg，
            # 重启后 load_config 读旧值 → 看似切不回去。改为切语言即时落盘。
            try:
                save_config(self.cfg)
            except Exception:
                pass
            self._rebuild()
            # round-44 E2：切语言即时同步主窗口 retranslate（否则
            # 「设置页英文 / 主页中文」割裂，需要手动重启才会统一）。
            try:
                win = self.parent()
                while win is not None and not hasattr(win, "retranslate_ui"):
                    win = win.parent()
                if win is not None and win is not self:
                    win.retranslate_ui()
            except Exception:
                pass

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

    def _sync_ui_to_cfg(self, target=None):
        """Read all current control values back into ``target`` (default
        ``self.cfg``). Used for both saving and for dirty-checking (pass a
        copy so the original cfg stays intact for comparison).

        Every widget read is funneled through ``self._safe`` so a C++-deleted
        reference (which can occur during a teardown/rebuild race when the
        user opens the page while ``reload()`` / ``retranslate_ui()`` is in
        flight) cannot crash the whole save. The previous value in ``cfg``
        is kept as the fallback for any field whose control has gone away.
        """
        if target is None:
            target = self.cfg
        checked_ram = self._safe(self.ram_btns.checkedButton, None)
        if checked_ram:
            target["ram_mb"] = getattr(checked_ram, "val", target["ram_mb"])
        else:
            target["ram_mb"] = self._safe(self.ram.value, target["ram_mb"])
            target["launcher_ram_mb"] = self._safe(
                self.launcher_ram.value, target["launcher_ram_mb"])
        # round-55 JVM 预设（三档下拉）替代 Aikars 单勾选；旧 key 同步写回保持兼容
        target["jvm_preset"] = self._safe(
            lambda: self.jvm_preset_combo.currentData() or "default",
            target.get("jvm_preset", "default"))
        target["jvm_aikars"] = target["jvm_preset"] == "aikar"
        # round-55 游戏附加参数 / 版本隔离 / 启动后、退出后命令
        target["game_args"] = self._safe(
            lambda: self.game_args_edit.text().strip(), target.get("game_args", ""))
        target["version_isolation"] = self._safe(
            lambda: self.version_iso_combo.currentData() or "default",
            target.get("version_isolation", "default"))
        target["post_launch_cmd"] = self._safe(
            lambda: self.post_cmd_edit.text().strip(), target.get("post_launch_cmd", ""))
        target["exit_cmd"] = self._safe(
            lambda: self.exit_cmd_edit.text().strip(), target.get("exit_cmd", ""))
        checked_mode = self._safe(self.mode_btns.checkedButton, None)
        if checked_mode:
            target["window_mode"] = getattr(checked_mode, "mode_key", target["window_mode"])
        checked_res = self._safe(self.res_btns.checkedButton, None)
        if checked_res:
            target["res_w"], target["res_h"] = getattr(
                checked_res, "res_val", (target["res_w"], target["res_h"]))
        else:
            target["res_w"] = self._safe(self.rw.value, target["res_w"])
            target["res_h"] = self._safe(self.rh.value, target["res_h"])
        checked_lang = self._safe(self.lang_btns.checkedButton, None)
        if checked_lang:
            target["language"] = getattr(checked_lang, "lang_code", target["language"])
        # round-87 全局字体（"" = 跟随系统默认）
        target["font_family"] = self._safe(
            lambda: self.font_combo.currentData() or "",
            target.get("font_family", ""))
        checked_wp = self._safe(self.wp_modes.checkedButton, None)
        if checked_wp:
            target["wallpaper_mode"] = getattr(checked_wp, "wp_mode", target["wallpaper_mode"])
        target["wallpaper_opacity"] = self._safe(
            lambda: self.wp_opacity.value() / 100.0, target["wallpaper_opacity"])
        target["wallpaper_video_vol"] = self._safe(
            lambda: self.wp_vol.value() / 100.0, target["wallpaper_video_vol"])
        # 主页模板 / 导航布局切换已删除（round-32）——固定 ac_default + AC 侧边导航；
        # 但保留已存值（如 dev 配置中的 pcl2），避免 is_dirty 误判 / 保存时悄悄改回。
        target["home_style"] = "ac_default"
        target["nav_layout"] = target.get("nav_layout", "ac")
        checked_theme = self._safe(self.theme_btns.checkedButton, None)
        if checked_theme:
            target["theme_mode"] = getattr(checked_theme, "theme_mode_val", target["theme_mode"])
        target["frosted_theme"] = self._safe(
            lambda: self.frosted_chk.isChecked(), bool(target.get("frosted_theme", True)))
        target["theme_pack"] = self._safe(
            lambda: self.pack_combo.currentData() or "", target["theme_pack"])
        target["java_auto"] = self._safe(
            self.java_auto.isChecked, bool(target["java_auto"]))
        target["java_path"] = self._safe(self.java_path.text, target["java_path"])
        target["jvm_args"] = self._safe(self.jvm.toPlainText, target["jvm_args"])
        checked_mirror = self._safe(self.mirror_btns.checkedButton, None)
        if checked_mirror:
            target["download_mirror"] = getattr(checked_mirror, "mirror_key", target["download_mirror"])
        checked_lobby = self._safe(self.lobby_tool_btns.checkedButton, None)
        if checked_lobby:
            target["lobby_tool"] = getattr(checked_lobby, "lobby_key", target.get("lobby_tool", "ask"))
        checked_proxy = self._safe(self.proxy_btns.checkedButton, None)
        if checked_proxy:
            key = getattr(checked_proxy, "proxy_key", "custom")
            # round-58：'system' 与默认值 '' 语义等价（见 _proxy_is / proxy_dict），
            # 写回时归一化为 ''，避免未改动时 is_dirty 误判弹出"未保存"对话框。
            target["download_proxy"] = self._safe(
                lambda: self.proxy_edit.text().strip() if key == "custom" else
                ("" if key == "system" else key),
                target["download_proxy"],
            )
        target["authlib_path"] = self._safe(
            lambda: self.authlib.text().strip(), target["authlib_path"])
        target["launch_sound"] = self._safe(
            self.sound_on.isChecked, bool(target["launch_sound"]))
        _rev = {
            t("settings.sound_trigger_game"): "game",
            t("settings.sound_trigger_app"): "app",
            t("settings.sound_trigger_both"): "both",
            t("settings.sound_trigger_off"): "off",
        }
        target["launch_sound_trigger"] = _rev.get(
            self._safe(self.sound_trig.currentText, t("settings.sound_trigger_game")),
            "game",
        )
        target["launch_sound_file"] = self._safe(
            lambda: self.sound_file.text().strip(), target["launch_sound_file"])
        target["launch_sound_vol"] = self._safe(
            lambda: self.sound_vol.value() / 100.0, target["launch_sound_vol"])
        target["bgm_enabled"] = self._safe(
            self.bgm_on.isChecked, bool(target["bgm_enabled"]))
        _mode_rev = {v: k for k, v in {
            "loop": t("settings.bgm_mode_loop"),
            "sequential": t("settings.bgm_mode_sequential"),
            "shuffle": t("settings.bgm_mode_shuffle"),
        }.items()}
        target["bgm_mode"] = _mode_rev.get(
            self._safe(self.bgm_mode.currentText, t("settings.bgm_mode_loop")),
            "loop",
        )
        # 多文件列表（替代单文件字段）
        try:
            target["bgm_files"] = [
                self.bgm_list.item(i).text() for i in range(self.bgm_list.count())
            ]
        except RuntimeError:
            pass  # bgm_list torn down — keep previous cfg["bgm_files"]
        if self.cfg.get("bgm_files"):
            target["bgm_file"] = target["bgm_files"][0]
        else:
            target["bgm_file"] = ""
        target["bgm_vol"] = self._safe(
            lambda: self.bgm_vol.value() / 100.0, target["bgm_vol"])
        target["sfx_enabled"] = self._safe(
            self.sfx_on.isChecked, bool(target["sfx_enabled"]))
        if hasattr(self, "sfx_files"):
            for _key, _le in self.sfx_files.items():
                target[f"sfx_{_key}"] = self._safe(
                    lambda le=_le: le.text().strip(), self.cfg.get(f"sfx_{_key}", ""))
        target["sfx_vol"] = self._safe(
            lambda: self.sfx_vol.value() / 100.0, target["sfx_vol"])
        target["splash_enabled"] = self._safe(
            self.splash_on.isChecked, bool(target["splash_enabled"]))
        if hasattr(self, '_selected_color') and self._selected_color:
            target["accent_color"] = self._selected_color
        # round-49 液态流光 effect 设置
        target["effect_light_trail"] = self._safe(
            self.effect_trail_chk.isChecked, bool(target["effect_light_trail"]))
        target["page_transition"] = self._safe(
            self.page_trans_chk.isChecked, bool(target["page_transition"]))
        target["window_opacity"] = self._safe(
            lambda: self.win_opacity.value() / 100.0, target["window_opacity"])
        # round-51 透底效果
        target["transparent_window"] = self._safe(
            self.transparent_chk.isChecked, bool(target["transparent_window"]))
        # round-50 退出释放资源
        target["close_after_launch"] = self._safe(
            self.close_launch_chk.isChecked, bool(target["close_after_launch"]))
        # round-83 系统托盘（关窗藏托盘）
        target["tray_minimize"] = self._safe(
            self.tray_chk.isChecked, bool(target.get("tray_minimize", True)))
        # round-79b 窗口置顶
        target["topmost"] = self._safe(
            self.topmost_chk.isChecked, bool(target.get("topmost", False)))
        # round-68 Quilt 加载器显示开关
        target["show_quilt"] = self._safe(
            self.show_quilt_chk.isChecked, bool(target.get("show_quilt", True)))
        # round-71 非 ASCII 路径警告开关
        target["warn_non_ascii_path"] = self._safe(
            self.warn_non_ascii_chk.isChecked, bool(target.get("warn_non_ascii_path", True)))
        # round-69 进程优先级
        target["process_priority"] = self._safe(
            lambda: self.priority_combo.currentData() or "normal",
            target.get("process_priority", "normal"))

    # ── dirty detection + unsaved-changes prompt ──
    def is_dirty(self) -> bool:
        """True if the current UI differs from the config snapshot loaded at
        build time (i.e. the user has unsaved edits)."""
        import copy, json
        if not hasattr(self, "cfg"):
            return False
        snap = copy.deepcopy(self.cfg)
        try:
            self._sync_ui_to_cfg(snap)
        except Exception:
            # During a teardown/rebuild race, reads may fail — treat as not dirty
            # so we never block navigation spuriously.
            return False
        a = json.dumps(self.cfg, sort_keys=True, ensure_ascii=False)
        b = json.dumps(snap, sort_keys=True, ensure_ascii=False)
        return a != b

    def ask_save_dialog(self) -> str:
        """Prompt what to do about unsaved changes. Returns one of:
        ``"save"`` / ``"discard"`` / ``"cancel"``."""
        from PySide6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        try:
            from .win_rounded import enable_dark_titlebar
            enable_dark_titlebar(msg)
        except Exception:
            pass
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle(t("settings.title"))
        msg.setText(t("settings.unsaved_title", default="有未保存的更改"))
        msg.setInformativeText(
            t("settings.unsaved_msg", default="是否保存这些更改？"))
        save = msg.addButton(
            t("settings.save", default="保存"), QMessageBox.AcceptRole)
        discard = msg.addButton(
            t("common.discard", default="不保存"), QMessageBox.DestructiveRole)
        cancel = msg.addButton(
            t("common.cancel", default="取消"), QMessageBox.RejectRole)
        msg.setDefaultButton(save)
        msg.setEscapeButton(cancel)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is save:
            return "save"
        if clicked is discard:
            return "discard"
        return "cancel"

    def discard_changes(self):
        """Revert live-applied theme/accent/wallpaper to the last saved config
        (the user chose not to keep their edits)."""
        from .theme import set_accent_color, set_theme_mode, apply_qss
        disk = load_config()
        set_theme_mode(disk.get("theme_mode", "light"))
        set_accent_color(disk.get("accent_color", "#7C3AED"))
        # round-87 放弃修改时字体也还原
        from .theme import set_font_family
        set_font_family(disk.get("font_family", ""))
        apply_qss()
        self.cfg = disk
        try:
            win = self._window
            if win is not None and hasattr(win, "home"):
                win.home._apply_wallpaper(version_id=win._current_version_id())
        except Exception:
            pass

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
        # round-52 玻璃拟态：半透明卡片样式即时生效（配合系统 Acrylic）。
        from .theme import set_frosted as _set_frosted
        _set_frosted(self.cfg.get("frosted_theme", True))

        # Theme mode (light/dark) —— 先设模式，再设强调色/主题包，避免强
        # 调色被重置（round-49 已让 set_theme_mode 自动保留自定义 accent，
        # 顺序在此仅为可读性）。
        set_theme_mode(self.cfg.get("theme_mode", "light"))

        # Accent color（无主题包时生效；有主题包时由下方的包覆盖其 accent）
        set_accent_color(self.cfg.get("accent_color", "#7C3AED"))

        # round-87 全局字体：先于 apply_qss，让 build_qss 用新字体重建
        from .theme import set_font_family
        set_font_family(self.cfg.get("font_family", ""))

        # Theme pack（若已配置）：最后套用，保证包的修饰色/圆角在其它选项
        # 保存后仍生效，且包的 accent 优先于自定义 accent。
        _pack_id = self.cfg.get("theme_pack", "")
        if _pack_id:
            from .theme import find_theme_pack, apply_theme_pack
            apply_theme_pack(find_theme_pack(_pack_id))

        apply_qss()

        # round-49 全局透明度（透底）即时生效
        try:
            from .effects import set_window_opacity, set_effects_enabled
            set_effects_enabled(self.cfg.get("effect_light_trail", True))
            set_window_opacity(self._window, self.cfg.get("window_opacity", 1.0))
        except Exception:  # noqa: BLE001
            pass

        # Wallpaper — refresh home page background
        try:
            win = self._window
            if win is not None and hasattr(win, 'home'):
                win.home._apply_wallpaper(version_id=win._current_version_id())
                # 主页模板切换已删除（round-32）——固定 ac_default，无需 rebuild
                # NOTE: window_mode / resolution are GAME settings — applied at
                # launch time inside launch.py (resolutionWidth/Height +
                # options.txt `fullscreen`), NOT to the launcher window. Do not
                # resize/flag the launcher here: it conflicts with the frameless
                # helper and would break the custom title bar. The launcher's own
                # window size is persisted separately (see MainWindow geometry).
        except Exception:
            pass

        self.saved.emit()

    def _refresh_dev_mode_ui(self):
        """No-op：开发者模式块已删除（round-32 后续）。保留防历史引用。"""
        pass

    def _on_dev_toggle(self):
        """No-op：开发者模式块已删除（round-32 后续）。保留防历史引用。"""
        pass

    def _on_style_combo_changed(self, idx: int):
        """No-op：主页模板切换已删除（round-32，切换会导致窗口卡在一起）。"""
        pass
