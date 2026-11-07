"""AC 实例编辑器（round-183）—— PCL 式整页编辑面板。

替代此前那个「480×620 一长条滚动框」的实例设置对话框。交互对齐 PCL2 /
HMCL 的版本设置窗口：

* 左侧竖排导航（基础 / 启动 / Java / 目录格式 / 模组 / 内容 / 高级）
* 右侧单页内容，改完点「保存」统一写回；加载器装卸是**立即执行**的长任务，
  带内联进度与结果提示
* 模组、资源包、光影、存档都在本面板内直接增删，不再跳页

设计约束（沿用项目既有规矩）：

* 不引入新的全局状态：写盘一律走 ``instances.manager().save()``
* 加载器装卸的实质动作下沉到 :mod:`core.loader_swap`，本文件只管交互
* 与 ``pages_instances`` 互相引用一律**延迟导入**，避免模块级循环
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout,
    QWidget,
)

from . import ui_kit
from .i18n import loader_name, t
from .icons import icon
from .instances import (INSTANCE_FORMATS, LOADERS, detect_format, layout_of,
                        manager)
from .theme import COLORS
from .win_rounded import confirm, info, toast, warn
from .worker import Worker

# 导航项：(key, 标题键, 图标键)


def _sys_memory_bytes():
    """(总内存, 可用内存) 字节。用 ctypes 读 GlobalMemoryStatusEx ——
    psutil 在本机 venv 里是坏的（缺 _psutil_windows），不要引。"""
    import ctypes

    class _MSE(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    st = _MSE()
    st.dwLength = ctypes.sizeof(_MSE)
    try:
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullTotalPhys), int(st.ullAvailPhys)
    except Exception:  # noqa: BLE001 - API 失败/非 Windows
        pass
    return 0, 0


class _MemBar(QWidget):
    """PCL 同款三段内存条：其他程序已用 | 本实例分配 | 剩余。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self._total = 0      # 字节
        self._other = 0      # 其他程序占用
        self._game = 0       # 本实例分配

    def set_values(self, game_mb: int) -> None:
        total, avail = _sys_memory_bytes()
        self._total = total
        self._game = max(0, int(game_mb)) * 1024 * 1024
        self._other = max(0, total - avail - self._game)
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802 - Qt 命名
        from PySide6.QtGui import QColor, QPainter
        pt = QPainter(self)
        pt.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pt.setPen(Qt.NoPen)
        pt.setBrush(QColor(COLORS["bg_frost"]))
        pt.drawRoundedRect(0, 0, w, h, 6, 6)
        total = max(1, self._total)
        seg_used = min(w, int(w * self._other / total))
        seg_game = min(w - seg_used, int(w * self._game / total))
        if seg_used:
            pt.setBrush(QColor(COLORS["border_light"]))
            pt.drawRoundedRect(0, 0, seg_used, h, 6, 6)
        if seg_game:
            pt.setBrush(QColor(COLORS["accent"]))
            pt.drawRoundedRect(seg_used, 0, seg_game, h, 6, 6)
        pt.end()

_NAV = (
    ("overview", "inst.tab_overview", "instances"),
    ("setup", "inst.tab_setup", "settings"),
    ("modify", "inst.tab_modify", "repair"),
    ("mods", "inst.tab_mods", "mods"),
    ("content", "inst.tab_content", "resourcepack"),
)

_SUB_STYLE = "color:%s;font-size:11px;" % COLORS["text_sub"]
_SECTION_STYLE = ("color:%s;font-size:12px;font-weight:600;" %
                  COLORS["text_main"])


class _Page(QWidget):
    """单页容器：纵向滚动 + **分组卡片**。

    每次 ``section()`` 开一张卡片，之后的 ``row`` / ``field`` / ``hint`` /
    ``add`` 都落进当前卡片——对齐 PCL2 / HMCL 版本设置窗口的分块观感，而不是
    一长条没有分隔的控件瀑布（第一版就是那样，实测「一眼看不出在改什么」）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        # 与实例设置页同款：内容强制收缩到视口宽度，长文本自动省略/换行
        self.body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(2, 2, 14, 10)
        self.lay.setSpacing(12)
        self._card = self.lay
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll)

    # ── 排版助手 ──
    def section(self, title: str) -> QLabel:
        card = QFrame()
        card.setObjectName("instCard")
        card.setStyleSheet(
            "#instCard { background: %s; border: 1px solid %s;"
            " border-radius: 10px; }" % (COLORS["bg_card"], COLORS["border"]))
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 11, 14, 13)
        cl.setSpacing(8)
        head = QLabel(title)
        head.setStyleSheet(
            "color:%s;font-size:12px;font-weight:600;border:none;"
            "background:transparent;" % COLORS["text_sub"])
        cl.addWidget(head)
        self.lay.addWidget(card)
        self._card = cl
        return head

    def add(self, widget, stretch: int = 0) -> None:
        self._card.addWidget(widget, stretch)

    def add_layout(self, lay) -> None:
        self._card.addLayout(lay)

    def intro(self, text: str) -> QLabel:
        """页首说明：加在**任意卡片之外**（第一张卡上面），不带框。"""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(_SUB_STYLE)
        self.lay.addWidget(lbl)
        self._card = self.lay
        return lbl

    def label(self, text: str) -> QLabel:
        """统一标签列（宽 108、左对齐），与 ``row()`` 里的标签同规格。"""
        lab = QLabel(text)
        lab.setFixedWidth(108)
        lab.setStyleSheet("color:%s;font-size:12px;" % COLORS["text_sub"])
        return lab

    def stretch(self) -> None:
        """内容顶对齐（加在外层，不能加到卡片里——那会把卡片撑高）。"""
        self.lay.addStretch(1)

    def hint(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(_SUB_STYLE)
        self._card.addWidget(lbl)
        return lbl

    def row(self, label: str, widget, stretch: int = 1) -> QHBoxLayout:
        r = QHBoxLayout()
        r.setSpacing(10)
        # 固定标签列：每条设置的控件左边缘对齐；标签本身不换行（换行会让
        # 整行高度跳变，「JVM 参数（覆盖全局）」那种长文案已改成短标签）。
        r.addWidget(self.label(label))
        r.addWidget(widget, stretch)
        self._card.addLayout(r)
        return r

    def field(self, label: str) -> QLineEdit:
        edit = QLineEdit()
        self.row(label, edit)
        return edit


class InstanceEditorPanel(QWidget):
    """实例整页编辑器（**页内面板**）。

    round-195：原来它是 QDialog（弹窗）。用户诉求：「为什么这么多实用功能的
    页面你不直接换页而是用窗口？」—— 实例编辑是最典型的"页面"，弹窗既割裂
    上下文（看不到自己正在改哪个实例），又和旁边的实例列表长得不一样。

    本类只管内容；窗口壳见 :class:`InstanceEditorDialog`（历史调用点仍可用）。
    """

    saved = Signal(str)          # 实例 id：字段已写盘
    versionChanged = Signal(str)  # 实例 id：版本/加载器字段变了，外层触发补全
    loaderChanged = Signal(str)   # 实例 id：加载器真装/真卸完成
    closed = Signal()             # 页内模式：请求返回上一层
    exportRequested = Signal(object)   # round-196：请求打开导出整合包面板

    def __init__(self, parent, inst):
        super().__init__(parent)
        self._inst = inst
        self._old_ver = (inst.game_version or "", inst.loader or "vanilla",
                         inst.loader_version or "")
        self._ver_editable = not bool(getattr(inst, "external", False))
        self._busy = False
        self._java_worker = None
        self._ldver_worker = None
        self._pages: dict[str, _Page] = {}

        self._build()
        self._load_java_plan()
        self._load_loader_versions(initial=True)

    # ── 骨架 ────────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.title_lbl = QLabel(t("inst.edit_title", name=self._inst.name or ""))
        self.title_lbl.setStyleSheet(
            "color:%s;font-size:16px;font-weight:700;" % COLORS["text_main"])
        head.addWidget(self.title_lbl, stretch=1)
        self.state_lbl = QLabel("")
        self.state_lbl.setStyleSheet(_SUB_STYLE)
        head.addWidget(self.state_lbl)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.nav = QListWidget()
        self.nav.setFixedWidth(150)
        self.nav.setFrameShape(QFrame.NoFrame)
        self.nav.setStyleSheet(f"""
            QListWidget {{ background: {COLORS['bg_panel']};
                           border-radius: 10px; padding: 6px; }}
            QListWidget::item {{ padding: 9px 8px; border-radius: 7px;
                                 color: {COLORS['text_main']}; }}
            QListWidget::item:selected {{ background: {COLORS['bg_hover']};
                                          color: {COLORS['text_main']}; }}
        """)
        self.stack = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.stack, stretch=1)
        root.addLayout(body, stretch=1)

        builders = {
            "overview": self._page_overview,
            "setup": self._page_setup,
            "modify": self._page_modify,
            "mods": self._page_mods,
            "content": self._page_content,
        }
        for key, title_key, icon_key in _NAV:
            item = QListWidgetItem(icon(icon_key), t(title_key))
            self.nav.addItem(item)
            page = builders[key]()
            self._pages[key] = page
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.foot_lbl = QLabel("")
        self.foot_lbl.setStyleSheet(_SUB_STYLE)
        self.foot_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        foot.addWidget(self.foot_lbl, stretch=1)
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self._on_cancel)
        self.cancel_btn = cancel
        self.save_btn = QPushButton(t("common.save"))
        self.save_btn.setProperty("cls", "accent")
        self.save_btn.clicked.connect(self._on_save)
        foot.addWidget(cancel)
        foot.addWidget(self.save_btn)
        root.addLayout(foot)

    def set_page_mode(self, on: bool = True) -> None:
        """页内模式：底部按钮从「取消」改成「返回」，标题旁标出实例名。

        页内打开时玩家看到的是「实例列表 → 这个面板」，不是新开了一个窗口，
        按钮语义必须跟着变（"取消"像在撤销编辑，"返回"才是换页）。
        """
        self._page_mode = on
        btn = getattr(self, "cancel_btn", None)
        if btn is not None:
            btn.setText(t("common.back") if on else t("common.cancel"))

    def _on_cancel(self) -> None:
        """取消 / 返回：页内模式通知外层返回；窗口壳由 reject 接管。"""
        self.closed.emit()

    # ── ① 基础 ──────────────────────────────────────────────
    def _page_overview(self) -> _Page:
        """对齐 PCL 的「概览」页：改名 + 只读信息 + 快捷方式 + 高级管理。

        round-187 重排：原来这页叫「基础」，只有两个输入框半屏空白；PCL 的
        概览页是「打开面板第一眼就该看完所有信息」的一页，我们把 ID/来源、
        目录快捷方式、导出整合包全部收进来。
        """
        p = _Page(self)
        inst = self._inst

        p.section(t("inst.basic_section"))
        self.name_edit = p.field(t("instances.setting_name"))
        self.name_edit.setText(inst.name or "")
        self.group_edit = p.field(t("instances.group_title"))
        self.group_edit.setText(inst.group or "")
        self.group_edit.setPlaceholderText(t("instances.group_hint"))

        # 个性化（PCL 概览同名卡片）：换图标 + 加入收藏夹
        p.section(t("inst.personalize_section"))
        prow = QHBoxLayout()
        prow.setSpacing(10)
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(40, 40)
        self.icon_preview.setAlignment(Qt.AlignCenter)
        self.icon_preview.setStyleSheet("background:%s;border-radius:9px;"
                                        % COLORS["bg_frost"])
        prow.addWidget(self.icon_preview)
        prow.addWidget(ui_kit.make_button(
            t("inst.pick_icon"), kind="secondary", icon_key="folder",
            on_click=self._pick_icon, min_h=32))
        prow.addWidget(ui_kit.make_button(
            t("inst.reset_icon"), kind="secondary", icon_key="refresh",
            on_click=self._reset_icon, min_h=32))
        prow.addStretch(1)
        self.fav_btn = ui_kit.make_button(
            t("inst.favorite_add"), kind="secondary", icon_key="check",
            on_click=self._toggle_favorite, min_h=32)
        prow.addWidget(self.fav_btn)
        p.add_layout(prow)
        self._refresh_icon_preview()
        self._refresh_fav_btn()

        p.section(t("inst.status_section"))
        self.status_box = QLabel("")
        self.status_box.setWordWrap(True)
        self.status_box.setTextFormat(Qt.RichText)
        p.add(self.status_box)
        self._refresh_status()

        # 实例 ID / 来源：平时不看，排查问题时发给支持的人
        p.section(t("inst.meta_section"))
        id_edit = QLineEdit(inst.id or "")
        id_edit.setReadOnly(True)
        p.row(t("inst.meta_id"), id_edit)
        src_edit = QLineEdit(
            "%s%s" % (loader_name(inst.loader or "vanilla"),
                      (" · " + inst.kind) if inst.kind else ""))
        src_edit.setReadOnly(True)
        p.row(t("inst.meta_source"), src_edit)
        p.hint(t("inst.meta_ro_hint"))

        # 快捷方式（PCL 概览同名卡片：版本文件夹 / 存档 / Mod 文件夹）
        p.section(t("inst.shortcuts_section"))
        sc = QHBoxLayout()
        sc.setSpacing(8)
        sc.addWidget(ui_kit.make_button(
            t("inst.sc_game_dir"), kind="secondary", icon_key="folder",
            on_click=lambda: _open_path(self, inst.mc_dir), min_h=32))
        sc.addWidget(ui_kit.make_button(
            t("inst.sc_mods"), kind="secondary", icon_key="mods",
            on_click=lambda: _open_path(self, inst.mods_dir), min_h=32))
        try:
            saves = os.path.join(inst.game_dir, "saves")
        except Exception:  # noqa: BLE001
            saves = os.path.join(inst.mc_dir, "saves")
        sc.addWidget(ui_kit.make_button(
            t("inst.sc_saves"), kind="secondary", icon_key="folder",
            on_click=lambda: _open_path(self, saves), min_h=32))
        sc.addStretch(1)
        p.add_layout(sc)

        # 高级管理（PCL 概览同名卡片）：导出整合包
        p.section(t("inst.manage_section"))
        p.hint(t("export.overrides_hint"))
        mg = QHBoxLayout()
        mg.setSpacing(8)
        mg.addWidget(ui_kit.make_button(
            t("instances.export_pack"), kind="secondary", icon_key="export",
            on_click=self._export_pack, min_h=32))
        # PCL「补全文件」同款：校验游戏文件完整性并重下缺失/损坏的
        mg.addWidget(ui_kit.make_button(
            t("inst.repair_files"), kind="secondary", icon_key="repair",
            on_click=self._repair_files, min_h=32))
        mg.addStretch(1)
        p.add_layout(mg)

        p.stretch()
        return p

    def _refresh_status(self) -> None:
        """把「版本 / 加载器 / 格式 / 目录」画成一张只读信息卡。"""
        inst = self._inst
        try:
            fmt = detect_format(inst)
        except Exception:  # noqa: BLE001
            fmt = "auto"
        try:
            d = layout_of(inst)
            install_dir = d.get("install_dir") or inst.mc_dir
            layout_txt = inst.mc_dir
            extra = (" · " + t("inst.from_marker")) if d.get("from_marker") else ""
        except Exception:  # noqa: BLE001
            install_dir = inst.mc_dir
            layout_txt = inst.mc_dir
            extra = ""
        rows = (
            (t("inst.status_version"), inst.game_version or "-"),
            (t("inst.status_loader"), ("%s %s" % (
                loader_name(inst.loader or "vanilla"),
                inst.loader_version or "")).strip()),
            (t("inst.status_format"), "%s%s" % (t("instances.fmt_" + fmt), extra)),
        )
        # 三行两列（标签 | 值），路径单独段落——全部「标签换行 + 值」堆叠会
        # 拉出半屏高的小灰字墙（第一版实测）。
        html = ["<table cellspacing='0' cellpadding='1'>"]
        for k, v in rows:
            html.append(
                "<tr><td style='color:%s;padding-right:18px'>%s</td>"
                "<td style='color:%s'>%s</td></tr>"
                % (COLORS["text_sub"], k, COLORS["text_main"], _esc(v)))
        html.append("</table>")
        for k, v in ((t("inst.status_dir"), layout_txt),
                     (t("inst.status_install_dir"), install_dir or "-")):
            html.append(
                "<div style='margin-top:7px'>"
                "<span style='color:%s;font-size:11px'>%s</span><br/>"
                "<span style='color:%s;font-size:11px'>%s</span></div>"
                % (COLORS["text_sub"], k, COLORS["text_main"], _esc(v)))
        self.status_box.setText("".join(html))
        if hasattr(self, "foot_lbl"):
            self.foot_lbl.setText(inst.mc_dir or "")

    def _page_setup(self) -> _Page:
        """对齐 PCL 的「设置」页：所有「改个数就生效」的字段收在一页。

        round-187 重排：原来拆成 启动 / Java / 目录与格式 三个页签，每个
        只有一张卡、大半屏空白（实测 Java 页一张卡下面 60% 空白）。PCL 的
        设置页就是一页多卡片滚下去。
        """
        p = _Page(self)
        inst = self._inst

        # ── 启动格式 ──
        p.section(t("instances.fmt_title"))
        self.fmt_combo = QComboBox()
        for k in INSTANCE_FORMATS:
            self.fmt_combo.addItem(t("instances.fmt_" + k), k)
        cur = (inst.format or "auto").strip()
        idx = self.fmt_combo.findData(cur if cur in INSTANCE_FORMATS else "auto")
        self.fmt_combo.setCurrentIndex(idx if idx >= 0 else 0)
        p.row(t("inst.fmt_current"), self.fmt_combo)
        self.fmt_hint = p.hint("")
        self.fmt_combo.currentIndexChanged.connect(
            lambda _i: self._update_fmt_hint())
        self._update_fmt_hint()

        # ── 版本隔离 / 自定义游戏目录 ──
        p.section(t("inst.isolation_section"))
        self.iso_combo = QComboBox()
        self.iso_combo.addItem(t("instances.isolation_follow"), "")
        self.iso_combo.addItem(t("instances.isolation_isolated"), "isolated")
        self.iso_combo.addItem(t("instances.isolation_custom"), "custom")
        idx = self.iso_combo.findData(inst.isolation or "")
        self.iso_combo.setCurrentIndex(idx if idx >= 0 else 0)
        p.row(t("instances.isolation"), self.iso_combo)

        # 整行一起藏：只 hide 输入框会把「自定义目录」标签留在原地（实测）
        self.game_dir_host = QWidget()
        gd_row = QHBoxLayout(self.game_dir_host)
        gd_row.setContentsMargins(0, 0, 0, 0)
        gd_row.setSpacing(10)
        gd_row.addWidget(p.label(t("inst.game_dir_label")))
        self.game_dir_edit = QLineEdit((inst.game_dir_override or "").strip())
        self.game_dir_edit.setPlaceholderText(
            t("instances.game_dir_override_hint"))
        gd_row.addWidget(self.game_dir_edit, 1)
        gd_pick = ui_kit.make_button(
            t("inst.java_browse"), kind="secondary", icon_key="folder",
            on_click=self._pick_game_dir, min_h=30)
        gd_row.addWidget(gd_pick)
        p.add(self.game_dir_host)
        self.game_dir_host.setVisible(self.iso_combo.currentData() == "custom")
        self.iso_combo.currentIndexChanged.connect(
            lambda _i: self.game_dir_host.setVisible(
                self.iso_combo.currentData() == "custom"))

        # ── 布局标识 ──
        p.section(t("inst.marker_section"))
        self.marker_lbl = QLabel("")
        self.marker_lbl.setWordWrap(True)
        self.marker_lbl.setTextFormat(Qt.RichText)
        p.add(self.marker_lbl)
        recheck = ui_kit.make_button(
            t("inst.marker_recheck"), kind="secondary", icon_key="refresh",
            on_click=self._recheck_marker, min_h=32)
        rr = QHBoxLayout()
        rr.addWidget(recheck)
        rr.addStretch(1)
        p.add_layout(rr)
        self._refresh_marker()

        # ── Java ──
        p.section(t("inst.java_section"))
        # 两行必须自带前缀：都写「未找到兼容的 Java」时分不清哪行是「需要」
        # 哪行是「将使用」（第一版实测）。
        self.java_need_lbl = QLabel(t("inst.java_need_unknown"))
        self.java_need_lbl.setWordWrap(True)
        self.java_need_lbl.setStyleSheet(_SUB_STYLE)
        p.add(self.java_need_lbl)
        self.java_use_lbl = QLabel(t("inst.java_use_none"))
        self.java_use_lbl.setWordWrap(True)
        self.java_use_lbl.setStyleSheet(_SUB_STYLE)
        p.add(self.java_use_lbl)

        self.java_combo = QComboBox()
        self.java_combo.addItem(t("inst.java_follow_global"), "")
        jrow = p.row(t("inst.java_pick"), self.java_combo)
        browse = ui_kit.make_button(
            t("inst.java_browse"), kind="secondary", icon_key="folder",
            on_click=self._browse_java, min_h=30)
        jrow.addWidget(browse)
        p.hint(t("inst.java_hint"))

        self.java_force_chk = QCheckBox(t("instances.java_force_label"))
        self.java_force_chk.setChecked(bool(getattr(inst, "java_force", False)))
        p.add(self.java_force_chk)

        # ── 内存与性能 ──
        p.section(t("inst.performance_section"))
        self.mem_spin = QSpinBox()
        # 全局 QSS 给 QSpinBox 定了 border/padding 但没定义 ::up-button，
        # 原生箭头会画到框外（实测截图右侧那根怪线）→ 关掉步进按钮。
        # 滚轮误改由 ui_kit 的全局 QSpinBox 补丁负责（round-183）。
        self.mem_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.mem_spin.setRange(0, 32768)
        self.mem_spin.setSingleStep(512)
        self.mem_spin.setValue(int(inst.ram_mb or 0))
        self.mem_spin.setSuffix(t("inst.mem_suffix"))
        p.row(t("instances.setting_mem"), self.mem_spin)

        # round-187 内存可视化条（PCL 同款）：其他程序已用 | 本实例分配 | 剩余。
        # 有它才看得清「4 GB 到底够不够」—— 一个孤零零的数字没这个信息量。
        self.mem_bar = _MemBar()
        self.mem_bar.set_values(int(inst.ram_mb or 0))
        p.add(self.mem_bar)
        self.mem_info_lbl = QLabel("")
        self.mem_info_lbl.setStyleSheet(_SUB_STYLE)
        self.mem_info_lbl.setWordWrap(True)
        p.add(self.mem_info_lbl)
        self._refresh_mem_info()
        self.mem_spin.valueChanged.connect(self._on_mem_changed)

        self.renderer_combo = QComboBox()
        self.renderer_combo.addItem(t("instances.renderer_auto"), "auto")
        self.renderer_combo.addItem(t("instances.renderer_software"), "software")
        self.renderer_combo.addItem(t("instances.renderer_legacy"), "legacy")
        idx = self.renderer_combo.findData(inst.renderer or "auto")
        self.renderer_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.renderer_combo.setToolTip(t("instances.renderer_hint"))
        p.row(t("instances.setting_renderer_title"), self.renderer_combo)

        self.g1gc_chk = QCheckBox(t("instances.perf_g1gc"))
        self.g1gc_chk.setChecked(bool(getattr(inst, "perf_g1gc", True)))
        self.g1gc_chk.setToolTip(t("instances.perf_g1gc_hint"))
        p.add(self.g1gc_chk)
        self.noexgc_chk = QCheckBox(t("instances.perf_disable_explicit_gc"))
        self.noexgc_chk.setChecked(
            bool(getattr(inst, "perf_disable_explicit_gc", False)))
        self.noexgc_chk.setToolTip(t("instances.perf_disable_explicit_gc_hint"))
        p.add(self.noexgc_chk)

        # 内存管理（GC）—— 对齐 PCL「内存分配 → 内存管理」下拉。
        # 显式选 GC 时不再叠加上面那组 G1GC 参数（ZGC 与 G1GC 互斥，
        # 同时下发 JVM 起不来），所以要在两个控件之间联动。
        self.gc_combo = QComboBox()
        self.gc_combo.addItem(t("inst.gc_follow"), "follow")
        self.gc_combo.addItem(t("inst.gc_zgc"), "zgc")
        self.gc_combo.addItem(t("inst.gc_zgc_gen"), "zgc_gen")
        self.gc_combo.addItem(t("inst.gc_g1"), "g1")
        self.gc_combo.addItem(t("inst.gc_g1_tuned"), "g1_tuned")
        self.gc_combo.addItem(t("inst.gc_none"), "none")
        _gc = (inst.gc_mode or "").strip().lower()
        idx = self.gc_combo.findData(_gc if _gc else "follow")
        self.gc_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.gc_combo.setToolTip(t("inst.gc_hint"))
        p.row(t("inst.gc_label"), self.gc_combo)

        # 启动前内存优化（PCL 同名开关）：把启动器自己的内存还给系统
        self.memopt_combo = QComboBox()
        self.memopt_combo.addItem(t("inst.memopt_follow"), "")
        self.memopt_combo.addItem(t("inst.memopt_on"), "on")
        self.memopt_combo.addItem(t("inst.memopt_off"), "off")
        _mo = (inst.mem_optimize or "").strip().lower()
        idx = self.memopt_combo.findData(_mo if _mo else "")
        self.memopt_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.memopt_combo.setToolTip(t("inst.memopt_hint"))
        p.row(t("inst.memopt_label"), self.memopt_combo)
        self.gc_combo.currentIndexChanged.connect(self._sync_gc_related)
        self._sync_gc_related()

        # ── JVM 与游戏参数 ──
        p.section(t("inst.game_section"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem(t("instances.jvm_preset_follow"), "")
        self.preset_combo.addItem(t("instances.jvm_preset_default"), "default")
        self.preset_combo.addItem(t("instances.jvm_preset_auto"), "auto")
        self.preset_combo.addItem(t("instances.jvm_preset_aikar"), "aikar")
        self.preset_combo.addItem(t("instances.jvm_preset_custom"), "custom")
        idx = self.preset_combo.findData(inst.jvm_preset or "")
        self.preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
        p.row(t("instances.jvm_preset"), self.preset_combo)

        self.jvm_edit = p.field(t("inst.jvm_label"))
        self.jvm_edit.setText(inst.jvm_args or "")
        self.jvm_edit.setPlaceholderText(t("instances.setting_jvm_hint"))

        self.game_args_edit = p.field(t("instances.game_args"))
        self.game_args_edit.setText((inst.game_args or "").strip())
        self.game_args_edit.setPlaceholderText(t("instances.game_args_hint"))

        # ── 服务器 ──
        p.section(t("inst.server_section"))
        self.auto_server_edit = p.field(t("inst.auto_server_label"))
        self.auto_server_edit.setText((inst.auto_server or "").strip())
        self.auto_server_edit.setPlaceholderText(t("inst.auto_server_ph"))
        p.hint(t("inst.auto_server_hint"))

        # ── 启动前后命令 ──
        p.section(t("inst.hooks_section"))
        self.post_cmd_edit = p.field(t("inst.post_cmd_label"))
        self.post_cmd_edit.setText((inst.post_launch_cmd or "").strip())
        self.post_cmd_edit.setPlaceholderText(t("instances.hook_ph"))
        self.exit_cmd_edit = p.field(t("inst.exit_cmd_label"))
        self.exit_cmd_edit.setText((inst.exit_cmd or "").strip())
        self.exit_cmd_edit.setPlaceholderText(t("instances.hook_ph"))

        p.stretch()
        self._load_java_list()
        return p

    # ── ③ 修改（PCL 同名页：只管加载器装卸） ────────────────
    def _page_modify(self) -> _Page:
        """对齐 PCL 的「修改」页 —— 它不是一个字段表单，而是**换加载器**的
        操作入口（PCL 里叫「修改」，对应 PageDownloadModify）。

        round-189 重做：原来是一个纯文本框 + 两个下拉 + 两颗按钮，看着像
        调试面板。现在是**带 logo 的加载器卡片**（一眼扫过去就知道每个加载器
        是什么）+ 可搜索的版本选择 + 标注了「最新」的版本列表 + 说清楚
        「会删什么、会留什么」的危险区。
        """
        p = _Page(self)
        inst = self._inst

        p.hint(t("inst.modify_hint"))

        # ── 当前加载器 ──
        p.section(t("inst.modify_current"))
        cur = QWidget()
        cl = QHBoxLayout(cur)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(12)
        self.ld_logo = QLabel()
        self.ld_logo.setFixedSize(38, 38)
        self.ld_logo.setAlignment(Qt.AlignCenter)
        self.ld_logo.setStyleSheet("background:%s;border-radius:9px;"
                                   % COLORS["bg_frost"])
        cl.addWidget(self.ld_logo)
        self.ld_state = p.hint(t("inst.loader_state_unknown"))
        self.ld_state.setStyleSheet(_SUB_STYLE)
        cl.addWidget(self.ld_state, 1)
        p.add(cur)

        # ── 安装 / 更换 ──
        p.section(t("inst.modify_section"))

        # 游戏版本：可输入 + 候选（官方版本列表异步拉），避免打进不存在的版本
        self.ver_edit = QComboBox()
        self.ver_edit.setEditable(True)
        self.ver_edit.setInsertPolicy(QComboBox.NoInsert)
        self.ver_edit.addItem(inst.game_version or "")
        self.ver_edit.setCurrentText(inst.game_version or "")
        self.ver_edit.setToolTip(t("inst.modify_version_hint"))
        self.ver_edit.currentTextChanged.connect(self._on_version_edited)
        vrow = p.row(t("instances.setting_game_version"), self.ver_edit)
        vrow.addWidget(ui_kit.make_button(
            t("inst.modify_pick_version"), kind="secondary", icon_key="search",
            on_click=self._fill_version_choices, min_h=30))
        p.hint(t("inst.modify_version_hint"))

        # 加载器：卡片选择器（logo + 名称 + 说明）
        from .loader_picker import LoaderPicker
        entries = []
        for lid in LOADERS:
            entries.append((lid, loader_name(lid),
                            t("inst.loader_card_" + lid)))
        self.loader_picker = LoaderPicker(entries)
        self.loader_picker.changed.connect(self._on_loader_picked)
        p.add(self.loader_picker)
        self.loader_combo = QComboBox()   # 兼容旧逻辑的隐藏镜像
        self.loader_combo.addItem(loader_name(inst.loader or "vanilla"),
                                  inst.loader or "vanilla")
        self.loader_combo.setCurrentIndex(0)

        self.ldver_combo = QComboBox()
        self.ldver_combo.setEditable(True)
        self.ldver_combo.addItem(inst.loader_version or "")
        self.ldver_combo.setCurrentText(inst.loader_version or "")
        self.ldver_combo.setPlaceholderText(
            t("instances.setting_loader_version_hint"))
        self.ldver_combo.lineEdit().setPlaceholderText(
            t("instances.setting_loader_version_hint"))
        p.row(t("instances.setting_loader_version"), self.ldver_combo)

        self.ldver_hint = p.hint(t("inst.loader_ver_hint"))

        # Fabric API：装 Fabric/Quilt 时默认一起装（缺了它绝大多数模组进游戏就报
        # 缺前置）。勾选项只在 fabric/quilt 时出现。
        self.fabapi_chk = QCheckBox(t("inst.fabapi_label"))
        self.fabapi_chk.setChecked(True)
        self.fabapi_chk.setToolTip(t("inst.fabapi_hint"))
        self.fabapi_hint = p.hint("")
        p.add(self.fabapi_chk)
        p.add(self.fabapi_hint)

        self.install_btn = ui_kit.make_button(
            t("inst.loader_install"), kind="accent", icon_key="download",
            on_click=self._install_loader, min_h=36)
        act = QHBoxLayout()
        act.setSpacing(8)
        act.addWidget(self.install_btn)
        act.addStretch(1)
        p.add_layout(act)

        # ── 退回原版（危险区）──
        p.section(t("inst.modify_danger"))
        d = QWidget()
        dl = QVBoxLayout(d)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(4)
        for key, color in (("inst.modify_deletes", COLORS["danger"]),
                           ("inst.modify_keeps", COLORS["text_sub"])):
            lb = QLabel(t(key))
            lb.setWordWrap(True)
            lb.setStyleSheet("font-size:11px;color:%s;" % color)
            dl.addWidget(lb)
        p.add(d)
        self.uninstall_btn = ui_kit.make_button(
            t("inst.loader_uninstall"), kind="danger", icon_key="delete",
            on_click=self._uninstall_loader, min_h=36)
        drow = QHBoxLayout()
        drow.setSpacing(8)
        drow.addWidget(self.uninstall_btn)
        drow.addStretch(1)
        p.add_layout(drow)

        if not self._ver_editable:
            p.hint(t("instances.setting_external_hint"))
            for b in (self.install_btn, self.uninstall_btn):
                b.setEnabled(False)
            self.loader_picker.enable(False)

        # 初始状态
        self._rebuild_loader_choices(inst.loader or "vanilla")
        self._refresh_loader_state()
        self._sync_fabapi_visibility()
        p.stretch()
        return p

    def _update_fmt_hint(self) -> None:
        data = self.fmt_combo.currentData() or "auto"
        try:
            det = detect_format(self._inst)
            if data == "auto":
                self.fmt_hint.setText(
                    t("instances.fmt_detected", name=t("instances.fmt_" + det)))
            else:
                txt = t("instances.fmt_forced", name=t("instances.fmt_" + data))
                if det != data:
                    txt += "\n" + t("instances.fmt_mismatch_hint",
                                    selected=t("instances.fmt_" + data),
                                    detected=t("instances.fmt_" + det))
                self.fmt_hint.setText(txt)
        except Exception:  # noqa: BLE001
            self.fmt_hint.setText("")

    def _refresh_marker(self) -> None:
        """展示 ``.ac-layout.json`` 是否存在、指纹是否还有效。"""
        from .core import instance_marker
        inst = self._inst
        data = {}
        try:
            data = instance_marker.read(inst) or {}
        except Exception:  # noqa: BLE001
            data = {}
        ok = bool(data)
        head = t("inst.marker_present") if ok else t("inst.marker_absent")
        color = COLORS["success"] if ok else COLORS["text_sub"]
        lines = ["<div style='color:%s;font-weight:600'>%s</div>"
                 % (color, _esc(head))]
        if ok:
            # 用中文标签：直接显示 owner / declared_format 这类内部键名，
            # 玩家看不懂（实测「标识有效」下面一堆英文字段）。
            for k, key in (("owner", "inst.marker_k_owner"),
                           ("kind", "inst.marker_k_kind"),
                           ("launcher", "inst.marker_k_launcher"),
                           ("game_version", "inst.marker_k_game_version"),
                           ("declared_format", "inst.marker_k_format")):
                if data.get(k):
                    lines.append(
                        "<div style='margin:1px 0'><span style='color:%s'>%s："
                        "</span><span style='color:%s'>%s</span></div>"
                        % (COLORS["text_sub"], _esc(t(key)),
                           COLORS["text_main"], _esc(str(data.get(k)))))
        else:
            lines.append("<div style='color:%s'>%s</div>"
                         % (COLORS["text_sub"], _esc(t("inst.marker_absent_hint"))))
        self.marker_lbl.setText("".join(lines))

    def _recheck_marker(self) -> None:
        """重新查验：走一次完整探测（含自动补写标识），再刷新展示。"""
        try:
            fmt = detect_format(self._inst)
            toast(self, t("inst.marker_recheck"),
                  t("inst.marker_recheck_done", name=t("instances.fmt_" + fmt)))
        except Exception as exc:  # noqa: BLE001
            warn(self, t("inst.marker_recheck"), str(exc))
        self._refresh_marker()
        self._update_fmt_hint()
    def _pick_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("inst.game_dir_label"))
        if path:
            self.game_dir_edit.setText(path)

    def _load_java_list(self) -> None:
        """后台扫已装 Java 再填下拉——``scan_javas`` 会摸注册表与磁盘，
        放在 UI 线程里会让「点开面板」卡一下（实例设置页当初就踩过）。"""
        self._javas_worker = Worker(_java_choices)
        self._javas_worker.finished.connect(self._fill_java_combo)
        self._javas_worker.error.connect(lambda _e: None)
        self._javas_worker.start()

    def _fill_java_combo(self, choices: list | None = None) -> None:
        """把已扫描到的 Java 填进手选下拉（失败就只剩「跟随全局」）。"""
        api = getattr(self, "java_combo", None)
        if api is None:
            return
        if choices is None:
            choices = _java_choices()
        cur = (self._inst.java_path or "").strip()
        api.blockSignals(True)
        while api.count() > 1:
            api.removeItem(1)
        for j in choices or []:
            api.addItem("Java %s · %s" % (j.get("major") or "?", j.get("path")),
                        j.get("path"))
        # 扫描失败 / 手填路径不在候选里时补一项：否则 findData 落空 → 保存时
        # 把玩家原来的手选路径清成「跟随全局」，改个内存就把 Java 弄丢。
        if cur and api.findData(cur) < 0:
            api.addItem("Java · %s" % cur, cur)
        idx = api.findData(cur)
        api.setCurrentIndex(idx if idx >= 0 else 0)
        api.blockSignals(False)

    def _browse_java(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self, t("inst.java_browse"), "", "java*")
        if not path:
            return
        idx = self.java_combo.findData(path)
        if idx < 0:
            self.java_combo.addItem("Java · %s" % path, path)
            idx = self.java_combo.count() - 1
        self.java_combo.setCurrentIndex(idx)

    def _load_java_plan(self) -> None:
        """后台算「需要 / 将使用」的 Java，避免进页面卡一次深扫。"""
        from .settings_dialog import load_config
        from .core.java import java_plan
        self._java_worker = Worker(java_plan, self._inst, load_config())
        self._java_worker.finished.connect(self._on_java_plan)
        self._java_worker.error.connect(lambda _e: None)
        self._java_worker.start()

    def _on_java_plan(self, plan: dict) -> None:
        try:
            self.java_need_lbl.setText(
                t("inst.java_need_line", need=int(plan.get("need") or 0)))
            path = plan.get("path") or ""
            if path:
                self.java_use_lbl.setText(t(
                    "inst.java_use_line",
                    major=int(plan.get("major") or 0), path=path))
            else:
                self.java_use_lbl.setText(t("inst.java_use_none"))
        except Exception:  # noqa: BLE001
            pass

    # ── ⑤ 模组 ──────────────────────────────────────────────
    def _page_mods(self) -> _Page:
        """round-185：整页换成 ModListPanel（搜索 / 筛选 / 多选 / 批量）。

        旧实现是「一堆 74px 大卡片 + 三颗按钮」，名字取文件名、没有搜索和
        多选 —— 装到 40 个模组时完全没法用。新面板对齐 PCL 的 Mod 管理页，
        真实名称/版本/图标来自 jar 里的清单（core.modmeta）。
        """
        p = _Page(self)
        from .mod_list import ModListPanel
        self.mod_panel = ModListPanel(
            self, self._inst, on_open_folder=lambda d: _open_path(self, d))
        # 面板自带滚动区：外层 _Page 已经在一个 QScrollArea 里，
        # 再套一层会让滚轮事件打架（内层吃掉滚轮，外层滚不动）。
        self.mod_panel.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.mod_panel.setMinimumHeight(430)
        self.mod_panel.changed.connect(self._refresh_status)
        p.add(self.mod_panel)
        return p

    # 兼容旧调用点（保留同名薄封装）
    def _reload_mods(self) -> None:
        if getattr(self, "mod_panel", None) is not None:
            self.mod_panel.reload()

    def _add_mods(self) -> None:
        if getattr(self, "mod_panel", None) is not None:
            self.mod_panel._add_files()

    def _add_mods(self) -> None:
        files, _f = QFileDialog.getOpenFileNames(
            self, t("mods.add_title"), "", t("mods.add_filter"))
        if not files:
            return
        dest = self._inst.mods_dir
        os.makedirs(dest, exist_ok=True)
        ok = 0
        for src in files:
            try:
                import shutil
                shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
                ok += 1
            except OSError as exc:
                warn(self, t("mods.copy_fail"), str(exc))
        if ok:
            try:
                from .achievements import achievements
                achievements().unlock("first_mod")
            except Exception:  # noqa: BLE001
                pass
            toast(self, t("mods.add"), t("inst.mods_added", n=ok))
        self._reload_mods()

    # ── ⑥ 内容（资源包 / 光影 / 存档）──────────────────────
    def _page_content(self) -> _Page:
        p = _Page(self)
        self._content_lists: dict[str, QListWidget] = {}
        p.intro(t("inst.content_hint"))
        for key, subdir, title_key in (
                ("resourcepacks", "resourcepacks", "inst.content_packs"),
                ("shaderpacks", "shaderpacks", "inst.content_shaders"),
                ("saves", "saves", "inst.content_saves")):
            p.section(t(title_key))
            lst = QListWidget()
            # 三块同屏可见：列表给 78–96px 就够（110–150 会把存档挤到滚动区外）
            lst.setMinimumHeight(78)
            lst.setMaximumHeight(96)
            self._content_lists[key] = lst
            p.add(lst)
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(ui_kit.make_button(
                t("inst.open_folder"), kind="secondary", icon_key="folder",
                on_click=lambda k=key: _open_path(self, self._content_dir(k)),
                min_h=30))
            row.addWidget(ui_kit.make_button(
                t("inst.content_delete"), kind="secondary", icon_key="delete",
                on_click=lambda k=key: self._delete_content(k), min_h=30))
            row.addStretch(1)
            p.add_layout(row)
        p.stretch()
        self._reload_content()
        return p

    def _content_dir(self, key: str) -> str:
        try:
            base = self._inst.game_dir
        except Exception:  # noqa: BLE001
            base = self._inst.mc_dir
        return os.path.join(base or "", key)

    def _reload_content(self) -> None:
        for key, lst in getattr(self, "_content_lists", {}).items():
            lst.clear()
            d = self._content_dir(key)
            try:
                names = sorted(os.listdir(d))
            except OSError:
                names = []
            if not names:
                item = QListWidgetItem(t("inst.content_empty"))
                item.setFlags(Qt.NoItemFlags)
                lst.addItem(item)
                continue
            for n in names:
                lst.addItem(n)

    def _delete_content(self, key: str) -> None:
        lst = self._content_lists.get(key)
        item = lst.currentItem() if lst else None
        if item is None or not (item.flags() & Qt.ItemIsSelectable):
            return
        name = item.text()
        if not confirm(self, t("inst.content_delete"), name):
            return
        target = os.path.join(self._content_dir(key), name)
        try:
            if os.path.isdir(target):
                import shutil
                shutil.rmtree(target)
            else:
                os.remove(target)
        except OSError as exc:
            warn(self, t("inst.content_delete"), str(exc))
        self._reload_content()

    # ── ⑦ 高级 ──────────────────────────────────────────────
    def _sync_gc_related(self) -> None:
        """选了具体 GC 就别再叠 G1GC 参数组（ZGC 与 G1GC 互斥）。"""
        explicit = (self.gc_combo.currentData() or "follow") != "follow"
        self.g1gc_chk.setEnabled(not explicit)
        self.g1gc_chk.setToolTip(
            t("instances.perf_g1gc_hint_conflict") if explicit
            else t("instances.perf_g1gc_hint"))

    def _on_mem_changed(self, value: int) -> None:
        self.mem_bar.set_values(int(value))
        self._refresh_mem_info()

    def _refresh_mem_info(self) -> None:
        """内存条下的一行说明；分配超过 85% 系统内存时黄字提醒。"""
        game_mb = int(self.mem_spin.value() or 0)
        total, avail = _sys_memory_bytes()
        total_gb = total / (1024 ** 3)
        avail_gb = avail / (1024 ** 3)
        txt = t("inst.mem_info", total="%.1f" % total_gb,
                avail="%.1f" % avail_gb, game="%.1f" % (game_mb / 1024.0))
        # PCL 同款护栏：分配 > 85% 物理内存大概率把系统挤死
        if total and game_mb * 1024 * 1024 > total * 0.85:
            self.mem_info_lbl.setStyleSheet(
                "font-size:11px;color:%s;" % COLORS["danger"])
            txt += " " + t("inst.mem_too_big")
        else:
            self.mem_info_lbl.setStyleSheet(_SUB_STYLE)
        self.mem_info_lbl.setText(txt)

    def _repair_files(self) -> None:
        """PCL「补全文件」同款：校验 + 重下缺失/损坏的游戏文件。

        复用 install_instance 的幂等补全（启动前自动修复走的就是它），
        这里只是给玩家一个手动入口，不用等启动失败才知道文件缺了。
        """
        if self._busy:
            return
        from .core.install import install_instance
        from .worker import ProgressWorker
        self._set_busy(True, t("inst.repair_working"))
        self._repair_worker = ProgressWorker(
            install_instance, self._inst,
            java_auto=True, java_path="", mirror="official", proxy="")
        self._repair_worker.finished.connect(self._on_repair_done)
        self._repair_worker.error.connect(self._on_repair_failed)
        self._repair_worker.start()

    def _on_repair_done(self, _result) -> None:
        self._set_busy(False, "")
        toast(self, t("inst.repair_files"), t("inst.repair_done"))

    def _on_repair_failed(self, err: str) -> None:
        self._set_busy(False, "")
        warn(self, t("inst.repair_files"), t("inst.repair_failed", e=str(err)))

    def _refresh_icon_preview(self) -> None:
        from . import instance_art
        pm = instance_art.icon_pixmap(
            getattr(self._inst, "icon_path", ""), 36, radius=8)
        if pm is None:
            pm = icon("instances").pixmap(22, 22)
        self.icon_preview.setPixmap(pm)

    def _refresh_fav_btn(self) -> None:
        fav = bool(getattr(self._inst, "favorite", False))
        self.fav_btn.setText(t("inst.favorite_remove" if fav
                               else "inst.favorite_add"))
        self.fav_btn.setProperty("cls", "accent" if fav else "secondary")
        self.fav_btn.style().unpolish(self.fav_btn)
        self.fav_btn.style().polish(self.fav_btn)

    def _toggle_favorite(self) -> None:
        self._inst.favorite = not bool(getattr(self._inst, "favorite", False))
        self._refresh_fav_btn()
        # 收藏影响列表/首页顺序，立刻落盘（不必等「保存」）
        manager().save(self._inst)
        # 列表顺序（收藏置顶）由外层在对话框关闭时统一刷新（dlg.exec() 之后）

    def _pick_icon(self) -> None:
        from . import instance_art
        path, _f = QFileDialog.getOpenFileName(
            self, t("inst.pick_icon"), "", t("inst.icon_filter"))
        if not path:
            return
        try:
            self._inst.icon_path = instance_art.set_instance_icon(
                self._inst, path)
        except ValueError as exc:
            msg = (t("inst.icon_too_big") if "large" in str(exc)
                   else t("inst.icon_bad"))
            warn(self, t("inst.pick_icon"), msg)
            return
        manager().save(self._inst)
        self._refresh_icon_preview()

    def _reset_icon(self) -> None:
        from . import instance_art
        instance_art.clear_instance_icon(self._inst)
        self._inst.icon_path = ""
        manager().save(self._inst)
        self._refresh_icon_preview()

    def _export_pack(self) -> None:
        """导出整合包（概览页「高级管理」入口）。

        round-196：不再自己弹窗 —— 页内面板里再 `exec()` 就是「页内套窗口」。
        改为发信号，由外层（实例页）用同一个页内栈打开导出面板。
        """
        # 先落字段：导出读的是实例对象，玩家刚改的版本号/加载器要用上
        self._collect(trigger=False)
        self.exportRequested.emit(self._inst)

    # ── 加载器版本列表 ──────────────────────────────────────
    def _current_loader(self) -> str:
        """当前选中的加载器 id。

        卡片选择器是真相（玩家点的是卡片），隐藏 combo 只是给旧逻辑用的镜像。
        """
        picker = getattr(self, "loader_picker", None)
        if picker is not None:
            cur = picker.current()
            if cur:
                return cur
        return self.loader_combo.currentData() or "vanilla"

    def _current_ldver(self) -> str:
        """当前加载器版本。

        ☠ 列表项会把 Beta 标成「<版本> · Beta」，直接读 ``currentText()`` 会把
        这个后缀一起写进实例字段。所以：文本与当前项显示文本一致 → 取 data
        （纯版本号）；不一致 → 玩家手输了新版本号，用文本。
        """
        text = self.ldver_combo.currentText().strip()
        idx = self.ldver_combo.currentIndex()
        if idx >= 0:
            if text and text != self.ldver_combo.itemText(idx):
                return text                       # 手输的新版本号
            data = self.ldver_combo.currentData()
            if isinstance(data, str) and data.strip():
                return data.strip()
        return text

    # ── 加载器可选性（round-186）─────────────────────────────
    def _rebuild_loader_choices(self, keep: str = "") -> None:
        """按当前 MC 版本重建加载器下拉 —— 只列**这个版本真有的**加载器。

        用户报「修改的选项中会出现不存在的加载器」：原来直接列 ``LOADERS``
        全表，1.12.2 的实例也能选 NeoForge（1.20.1 才有）、Quilt（1.14+）。

        实例**当前**的加载器永远保留（哪怕按规则不支持）—— 否则用户一打开面板
        就发现自己的加载器"消失"了，保存时还会被悄悄换成原版。
        """
        from .core.loader_catalog import loaders_for
        mc = self.ver_edit.currentText().strip() or self._inst.game_version or ""
        keep = (keep or self._inst.loader or "vanilla").strip().lower()
        allowed = loaders_for(mc, LOADERS)
        if keep and keep not in allowed:
            allowed = [keep] + allowed
        # 隐藏的 combo 只作「当前值」的镜像（_collect / _load_loader_versions 读它）
        self.loader_combo.blockSignals(True)
        self.loader_combo.clear()
        for lid in allowed:
            self.loader_combo.addItem(loader_name(lid), lid)
        idx = self.loader_combo.findData(keep)
        self.loader_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.loader_combo.blockSignals(False)
        # 卡片选择器：按可用性显隐 + 选中态
        picker = getattr(self, "loader_picker", None)
        if picker is not None:
            picker.set_available(allowed)
            picker.set_current(keep if keep in allowed else "vanilla")
        self._sync_fabapi_visibility()

    def _on_version_edited(self) -> None:
        """MC 版本改了 → 加载器可选集与版本列表都要跟着变。

        带去抖：版本框是自由输入，每敲一个字都去拉一次版本列表会把网络打爆。
        """
        mc = self.ver_edit.currentText().strip()
        if mc == getattr(self, "_last_mc_queried", None):
            return
        self._last_mc_queried = mc
        self._rebuild_loader_choices()
        self._load_loader_versions()

    def _fill_version_choices(self) -> None:
        """拉官方版本列表填进版本框（后台线程，缓存命中就秒回）。"""
        from .net_api import fetch_versions
        from .worker import Worker

        self.ver_edit.setEnabled(False)
        self.ldver_hint.setText(t("inst.modify_versions_loading"))
        w = Worker(fetch_versions)
        self._ver_worker = w

        def _fin(data) -> None:
            self.ver_edit.setEnabled(True)
            try:
                _, versions = data
            except Exception:  # noqa: BLE001
                versions = []
            cur = self.ver_edit.currentText().strip()
            self.ver_edit.blockSignals(True)
            self.ver_edit.clear()
            for v in (versions or [])[:400]:
                vid = v.get("id") if isinstance(v, dict) else str(v)
                if vid:
                    self.ver_edit.addItem(str(vid))
            if cur:
                self.ver_edit.setCurrentText(cur)
            self.ver_edit.blockSignals(False)
            self.ldver_hint.setText(t("inst.modify_versions_ready",
                                       n=len(versions or [])))
            self._last_mc_queried = None
            self._on_version_edited()

        def _err(_e) -> None:
            self.ver_edit.setEnabled(True)
            self.ldver_hint.setText(t("inst.modify_versions_failed"))

        w.finished.connect(_fin)
        w.error.connect(_err)
        w.start()

    def _on_loader_picked(self, loader_id: str) -> None:
        """卡片被点选：同步隐藏镜像 + 刷新加载器版本列表。"""
        lid = (loader_id or "").strip().lower()
        if not lid:
            return
        idx = self.loader_combo.findData(lid)
        if idx < 0:
            self.loader_combo.blockSignals(True)
            self.loader_combo.addItem(loader_name(lid), lid)
            self.loader_combo.setCurrentIndex(self.loader_combo.count() - 1)
            self.loader_combo.blockSignals(False)
        else:
            self.loader_combo.setCurrentIndex(idx)
        self._sync_fabapi_visibility()
        self._load_loader_versions()

    def _sync_fabapi_visibility(self) -> None:
        """Fabric API 勾选项只在 fabric / quilt 时出现。"""
        from .core.loader_swap import wants_fabric_api
        show = wants_fabric_api(self._current_loader())
        chk = getattr(self, "fabapi_chk", None)
        hint = getattr(self, "fabapi_hint", None)
        if chk is None:
            return
        chk.setVisible(show)
        if hint is not None:
            hint.setVisible(show)
            hint.setText(t("inst.fabapi_hint") if show else "")

    def _load_loader_versions(self, initial: bool = False) -> None:
        loader = self._current_loader()
        self._refresh_loader_state()
        if loader == "vanilla":
            self.ldver_combo.blockSignals(True)
            self.ldver_combo.clear()
            self.ldver_combo.addItem("")
            self.ldver_combo.setEnabled(False)
            self.ldver_combo.blockSignals(False)
            self.ldver_hint.setText(t("inst.loader_vanilla_hint"))
            self._refresh_loader_state()
            self._sync_fabapi_visibility()
            return
        self.ldver_combo.setEnabled(self._ver_editable)
        self.ldver_hint.setText(t("inst.loader_ver_loading"))
        if initial and self.ldver_combo.currentText().strip():
            # 已装过：先显示当前值，等列表回来再补全候选
            pass
        from .pages_instances import _fetch_loader_versions
        mc = self.ver_edit.currentText().strip() or self._inst.game_version or ""
        self._ldver_worker = Worker(_fetch_loader_versions, mc, loader)
        self._ldver_worker.finished.connect(self._on_loader_versions)
        self._ldver_worker.error.connect(
            lambda _e: self.ldver_hint.setText(t("inst.loader_ver_failed")))
        self._ldver_worker.start()

    def _on_loader_versions(self, versions: list) -> None:
        keep = self._current_ldver()
        self.ldver_combo.blockSignals(True)
        self.ldver_combo.clear()
        seen = set()
        first = True
        for v in versions or []:
            meta = str(v.get("meta") or "")
            if not meta or meta in seen:
                continue
            seen.add(meta)
            title = str(v.get("title") or meta)
            chan = v.get("channel") or "unknown"
            label = title
            if chan == "beta":
                label = "%s · %s" % (title, t("new_instance.ldver_beta"))
            elif first:
                # 列表第一个就是最新构建（各 meta API 都是新→旧）
                label = "%s · %s" % (title, t("inst.loader_ver_latest"))
            self.ldver_combo.addItem(label, meta)
            first = False
        if keep:
            idx = self.ldver_combo.findData(keep)
            if idx < 0:
                self.ldver_combo.insertItem(0, keep, keep)
                idx = 0
            self.ldver_combo.setCurrentIndex(idx)
        elif self.ldver_combo.count():
            self.ldver_combo.setCurrentIndex(0)
        self.ldver_combo.blockSignals(False)
        n = len(versions or [])
        if n:
            self.ldver_hint.setText(t("inst.loader_ver_ready", n=n))
        else:
            # ☠ 空列表 ≠ 网络失败：多半是这个 MC 版本**真没有**该加载器
            # （1.12.2 + NeoForge / 1.21 + LiteLoader）。说清楚，别让人以为是网断了。
            mc = self.ver_edit.text().strip() or self._inst.game_version or ""
            self.ldver_hint.setText(t("inst.loader_ver_none", mc=mc))
        self.install_btn.setEnabled(bool(n) and self._ver_editable)
        self._refresh_loader_state()

    def _refresh_loader_state(self) -> None:
        """状态行：已装的加载器版本 id / 没装。"""
        from .core.loader_swap import current_loader_version_id
        try:
            vid = current_loader_version_id(self._inst)
        except Exception:  # noqa: BLE001
            vid = None
        if vid:
            self.ld_state.setText(t("inst.loader_state_installed", id=vid))
            self.ld_state.setStyleSheet(
                "color:%s;font-size:12px;font-weight:600;" % COLORS["success"])
        else:
            self.ld_state.setText(t("inst.loader_state_absent"))
            self.ld_state.setStyleSheet(_SUB_STYLE)
        # logo：跟着当前加载器走
        logo = getattr(self, "ld_logo", None)
        if logo is not None:
            from .loader_picker import loader_logo
            pm = loader_logo(self._current_loader(), 30)
            if pm.isNull():
                pm = icon("mods").pixmap(26, 26)
            logo.setPixmap(pm)
            self.ld_state.setStyleSheet(_SUB_STYLE)

    # ── 加载器真装 / 真卸 ──────────────────────────────────
    def _install_loader(self) -> None:
        if self._busy:
            return
        from .core.loader_swap import swap_loader
        from .worker import ProgressWorker
        loader = self._current_loader()
        ldver = self._current_ldver() if loader != "vanilla" else ""
        # 先落字段：用户可能只改了版本号没点保存就想装
        self._collect(trigger=False)
        self._set_busy(True, t("inst.loader_working"))
        self._ld_worker = ProgressWorker(swap_loader, self._inst, loader, ldver)
        self._ld_worker.status.connect(
            lambda s: self.ld_state.setText(str(s)))
        self._ld_worker.finished.connect(self._on_loader_installed)
        self._ld_worker.error.connect(self._on_loader_error)
        self._ld_worker.start()

    def _on_loader_installed(self, result: dict) -> None:
        self._set_busy(False, "")
        manager().save(self._inst)
        vid = result.get("version_id") or ""
        removed = result.get("removed") or []
        msg = t("inst.loader_install_done", id=vid)
        if removed:
            msg += "\n" + t("inst.loader_old_removed", ids=", ".join(removed))
        self._refresh_loader_state()
        self._refresh_status()
        self.loaderChanged.emit(self._inst.id)

        # 装完 Fabric / Quilt 顺手把 Fabric API 也装上（用户明确要求）。
        # 这一步失败**不能**把「加载器已装好」说成失败 —— 两件事分开报。
        from .core.loader_swap import wants_fabric_api
        if self.fabapi_chk.isChecked() and wants_fabric_api(
                self._inst.loader or ""):
            self._install_fabric_api(msg)
            return
        info(self, t("inst.loader_install"), msg)

    def _install_fabric_api(self, base_msg: str) -> None:
        """加载器装好后补装 Fabric API。"""
        from .core.loader_swap import install_fabric_api
        self._set_busy(True, t("inst.fabapi_working"))
        self._fab_worker = Worker(install_fabric_api, self._inst)
        self._fab_worker.finished.connect(
            lambda name: self._on_fabric_api_done(base_msg, name))
        self._fab_worker.error.connect(
            lambda e: self._on_fabric_api_failed(base_msg, e))
        self._fab_worker.start()

    def _on_fabric_api_done(self, base_msg: str, name: str) -> None:
        self._set_busy(False, "")
        msg = base_msg + "\n" + t("inst.fabapi_done", name=name or "Fabric API")
        info(self, t("inst.loader_install"), msg)

    def _on_fabric_api_failed(self, base_msg: str, err: str) -> None:
        self._set_busy(False, "")
        # 加载器已经装好了，这里只提示补充件没成，别让人以为要重装一遍
        msg = base_msg + "\n" + t("inst.fabapi_failed", e=str(err))
        warn(self, t("inst.loader_install"), msg)

    def _on_loader_error(self, err: str) -> None:
        self._set_busy(False, "")
        warn(self, t("inst.loader_install"), str(err))

    def _uninstall_loader(self) -> None:
        if self._busy:
            return
        inst = self._inst
        if (inst.loader or "vanilla") == "vanilla":
            info(self, t("inst.loader_uninstall"), t("inst.loader_no_loader"))
            return
        if getattr(inst, "external", False):
            warn(self, t("inst.loader_uninstall"), t("inst.loader_external_guard"))
            return
        if not confirm(self, t("inst.loader_uninstall"),
                       t("inst.loader_uninstall_confirm",
                         name=loader_name(inst.loader or "")),
                       detail=t("inst.loader_uninstall_detail")):
            return
        from .core.loader_swap import uninstall_loader
        self._set_busy(True, t("inst.loader_working"))
        self._ld_exec = Worker(uninstall_loader, inst)
        self._ld_exec.finished.connect(self._on_loader_uninstalled)
        self._ld_exec.error.connect(self._on_loader_error)
        self._ld_exec.start()

    def _on_loader_uninstalled(self, result: dict) -> None:
        self._set_busy(False, "")
        if not result.get("ok"):
            reason = result.get("reason") or ""
            if reason == "external":
                warn(self, t("inst.loader_uninstall"),
                     t("inst.loader_external_guard"))
            elif reason == "busy":
                warn(self, t("inst.loader_uninstall"),
                     result.get("error") or t("inst.loader_busy"))
            else:
                info(self, t("inst.loader_uninstall"), t("inst.loader_no_loader"))
            return
        manager().save(self._inst)
        removed = result.get("removed") or []
        msg = t("inst.loader_uninstall_done",
                ids=", ".join(removed) if removed else "-")
        info(self, t("inst.loader_uninstall"), msg)
        # 字段已被 uninstall_loader 改成 vanilla，界面同步
        idx = self.loader_combo.findData("vanilla")
        self.loader_combo.blockSignals(True)
        self.loader_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.loader_combo.blockSignals(False)
        self.ldver_combo.blockSignals(True)
        self.ldver_combo.clear()
        self.ldver_combo.addItem("")
        self.ldver_combo.blockSignals(False)
        self._refresh_loader_state()
        self._refresh_status()
        self.loaderChanged.emit(self._inst.id)

    def _set_busy(self, busy: bool, text: str) -> None:
        self._busy = busy
        self.install_btn.setEnabled(not busy and self._ver_editable)
        self.uninstall_btn.setEnabled(not busy and self._ver_editable)
        self.save_btn.setEnabled(not busy)
        if text:
            self.ld_state.setText(text)

    # ── 保存 ────────────────────────────────────────────────
    def _on_save(self) -> None:
        if self._busy:
            return
        changed = self._collect(trigger=True)
        manager().save(self._inst)
        self.saved.emit(self._inst.id)
        if changed:
            self.versionChanged.emit(self._inst.id)
        # 页内模式：通知外层返回（窗口壳的 accept 由壳自己处理）
        self.closed.emit()

    def _collect(self, trigger: bool = False) -> bool:
        """把表单写回实例。返回「版本/加载器是否变了」。"""
        inst = self._inst
        inst.name = self.name_edit.text().strip() or inst.name
        inst.group = self.group_edit.text().strip()
        if self._ver_editable:
            inst.game_version = (self.ver_edit.currentText().strip()
                                 or inst.game_version)
            inst.loader = self._current_loader()
            inst.loader_version = ("" if inst.loader == "vanilla"
                                   else self._current_ldver())
        inst.ram_mb = int(self.mem_spin.value())
        inst.jvm_args = self.jvm_edit.text().strip()
        inst.jvm_preset = self.preset_combo.currentData() or ""
        inst.renderer = self.renderer_combo.currentData() or "auto"
        inst.perf_g1gc = self.g1gc_chk.isChecked()
        inst.perf_disable_explicit_gc = self.noexgc_chk.isChecked()
        _gc = self.gc_combo.currentData() or "follow"
        inst.gc_mode = "" if _gc == "follow" else _gc
        inst.mem_optimize = self.memopt_combo.currentData() or ""
        inst.game_args = self.game_args_edit.text().strip()
        inst.java_path = self.java_combo.currentData() or ""
        inst.java_force = self.java_force_chk.isChecked()
        inst.format = self.fmt_combo.currentData() or ""
        inst.isolation = self.iso_combo.currentData() or ""
        inst.game_dir_override = self.game_dir_edit.text().strip()
        inst.post_launch_cmd = self.post_cmd_edit.text().strip()
        inst.exit_cmd = self.exit_cmd_edit.text().strip()
        inst.auto_server = self.auto_server_edit.text().strip()

        now = (inst.game_version or "", inst.loader or "vanilla",
               inst.loader_version or "")
        if now != self._old_ver:
            inst.version_id = ""
            inst.needs_convert = False
            self._old_ver = now
            return True
        return False

    # ── 其它 ────────────────────────────────────────────────
    def retranslate_ui(self) -> None:
        self.setWindowTitle(t("inst.edit_title", name=self._inst.name or ""))
        self.title_lbl.setText(t("inst.edit_title", name=self._inst.name or ""))
        for i, (key, title_key, _icon) in enumerate(_NAV):
            item = self.nav.item(i)
            if item is not None:
                item.setText(t(title_key))


# ── 模块级助手 ──────────────────────────────────────────────
def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _java_choices() -> list[dict]:
    """已装 Java 列表（失败返回空，不影响面板打开）。"""
    try:
        from .core.java import scan_javas
        return [j for j in scan_javas() if int(j.get("major") or 0) > 0]
    except Exception:  # noqa: BLE001
        return []


def _open_path(parent, path: str) -> None:
    if not path:
        return
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    try:
        import subprocess
        if os.name == "nt":
            os.startfile(os.path.normpath(path))  # noqa: S606 - 用户主动打开目录
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as exc:
        warn(parent, t("inst.open_folder"), str(exc))


class InstanceEditorDialog(QDialog):
    """**兼容壳**：仍以模态窗口使用（历史调用点）。

    内部就是 :class:`InstanceEditorPanel` —— 页内与弹窗**同一套实现**，
    不会出现"两个页面两套逻辑"。round-195 起新入口一律走页内面板。
    """

    saved = Signal(str)
    versionChanged = Signal(str)
    loaderChanged = Signal(str)

    def __init__(self, parent, inst):
        super().__init__(parent)
        self.setWindowTitle(t("inst.edit_title", name=inst.name or ""))
        self.resize(900, 660)
        self.setMinimumSize(780, 540)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.panel = InstanceEditorPanel(self, inst)
        lay.addWidget(self.panel)
        # 转发常用属性，老代码/测试不用改
        self.stack = self.panel.stack
        self.nav = self.panel.nav
        self.panel.saved.connect(self.saved)
        self.panel.versionChanged.connect(self.versionChanged)
        self.panel.loaderChanged.connect(self.loaderChanged)
        self._closing = False
        self.panel.closed.connect(self._on_panel_closed)

    def _on_panel_closed(self) -> None:
        """面板内部请求关闭 → 窗口壳随之关闭（页内模式则由外层接管）。"""
        if self._closing:
            return
        self._closing = True
        self.accept()

    def reject(self) -> None:
        self._closing = True
        self.panel.closed.emit()
        super().reject()

    def __getattr__(self, name):
        """壳上没定义的属性一律转发给内部面板（老代码不用改）。"""
        if name == "panel":
            raise AttributeError(name)
        return getattr(self.panel, name)


def _reveal_path(parent, path: str) -> None:
    try:
        import subprocess
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)],
                             creationflags=0x08000000)
        else:
            _open_path(parent, os.path.dirname(path))
    except OSError:
        _open_path(parent, os.path.dirname(path))
