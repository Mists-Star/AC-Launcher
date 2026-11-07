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
_NAV = (
    ("basic", "inst.tab_basic", "instances"),
    ("launch", "inst.tab_launch", "play"),
    ("modify", "inst.tab_modify", "repair"),
    ("java", "inst.tab_java", "java"),
    ("dir", "inst.tab_dir", "folder"),
    ("mods", "inst.tab_mods", "mods"),
    ("content", "inst.tab_content", "resourcepack"),
    ("adv", "inst.tab_adv", "tools"),
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


class InstanceEditorDialog(QDialog):
    """实例整页编辑器。"""

    saved = Signal(str)          # 实例 id：字段已写盘
    versionChanged = Signal(str)  # 实例 id：版本/加载器字段变了，外层触发补全
    loaderChanged = Signal(str)   # 实例 id：加载器真装/真卸完成

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

        self.setWindowTitle(t("inst.edit_title", name=inst.name or ""))
        self.resize(900, 660)
        self.setMinimumSize(780, 540)
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
            "basic": self._page_basic,
            "launch": self._page_launch,
            "modify": self._page_modify,
            "java": self._page_java,
            "dir": self._page_dir,
            "mods": self._page_mods,
            "content": self._page_content,
            "adv": self._page_adv,
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
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton(t("common.save"))
        self.save_btn.setProperty("cls", "accent")
        self.save_btn.clicked.connect(self._on_save)
        foot.addWidget(cancel)
        foot.addWidget(self.save_btn)
        root.addLayout(foot)

    # ── ① 基础 ──────────────────────────────────────────────
    def _page_basic(self) -> _Page:
        p = _Page(self)
        p.section(t("inst.basic_section"))
        self.name_edit = p.field(t("instances.setting_name"))
        self.name_edit.setText(self._inst.name or "")
        self.group_edit = p.field(t("instances.group_title"))
        self.group_edit.setText(self._inst.group or "")
        self.group_edit.setPlaceholderText(t("instances.group_hint"))

        p.section(t("inst.status_section"))
        self.status_box = QLabel("")
        self.status_box.setWordWrap(True)
        self.status_box.setTextFormat(Qt.RichText)
        p.add(self.status_box)

        p.stretch()
        self._refresh_status()
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

    # ── ② 启动 ──────────────────────────────────────────────
    def _page_launch(self) -> _Page:
        p = _Page(self)
        inst = self._inst
        p.section(t("inst.performance_section"))
        self.mem_spin = QSpinBox()
        # ☠ 全局 QSS 给 QSpinBox 定了 border/padding 但没定义 ::up-button，
        # 原生箭头会画到框外（实测截图右侧那根怪线）→ 关掉步进按钮，靠输入。
        # 滚轮误改由 ui_kit 的全局 QSpinBox 补丁负责（round-183）。
        self.mem_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.mem_spin.setRange(0, 32768)
        self.mem_spin.setSingleStep(512)
        self.mem_spin.setValue(int(inst.ram_mb or 0))
        self.mem_spin.setSuffix(t("inst.mem_suffix"))
        p.row(t("instances.setting_mem"), self.mem_spin)

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

        p.section(t("inst.game_section"))
        self.game_args_edit = p.field(t("instances.game_args"))
        self.game_args_edit.setText((inst.game_args or "").strip())
        self.game_args_edit.setPlaceholderText(t("instances.game_args_hint"))

        p.stretch()
        return p

    # ── ③ 修改（PCL 同名页：只管加载器装卸） ────────────────
    def _page_modify(self) -> _Page:
        """对齐 PCL 的「修改」页 —— 它不是一个字段表单，而是**换加载器**的
        操作入口（PCL 里叫「修改」，对应 PageDownloadModify）。

        为什么单独一页：换加载器是「会真下文件、真删目录」的重操作，和调内存
        那种改个数就生效的设置混在一起，玩家分不清哪一下会动磁盘。
        """
        p = _Page(self)
        inst = self._inst

        p.hint(t("inst.modify_hint"))
        p.section(t("inst.modify_current"))
        self.ld_state = p.hint(t("inst.loader_state_unknown"))

        p.section(t("inst.modify_section"))
        self.ver_edit = p.field(t("instances.setting_game_version"))
        self.ver_edit.setText(inst.game_version or "")
        self.ver_edit.setToolTip(t("inst.modify_version_hint"))

        # Fabric API 勾选项要先建好 —— 下面重建加载器下拉时会同步它的可见性。
        self.fabapi_chk = QCheckBox(t("inst.fabapi_label"))
        self.fabapi_chk.setChecked(True)
        self.fabapi_chk.setToolTip(t("inst.fabapi_hint"))
        self.fabapi_hint = p.hint("")

        self.loader_combo = QComboBox()
        p.row(t("instances.setting_loader"), self.loader_combo)
        # 只列「这个 MC 版本真有的」加载器（1.12.2 不该出现 NeoForge）
        self._rebuild_loader_choices(inst.loader or "vanilla")
        self.ver_edit.editingFinished.connect(self._on_version_edited)

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
        p.add(self.fabapi_chk)
        p.add(self.fabapi_hint)

        for w in (self.ver_edit, self.loader_combo, self.ldver_combo):
            w.setEnabled(self._ver_editable)

        self.install_btn = ui_kit.make_button(
            t("inst.loader_install"), kind="accent", icon_key="download",
            on_click=self._install_loader, min_h=34)
        act = QHBoxLayout()
        act.setSpacing(8)
        act.addWidget(self.install_btn)
        act.addStretch(1)
        p.add_layout(act)
        self.loader_combo.currentIndexChanged.connect(self._on_loader_picked)

        p.section(t("inst.modify_danger"))
        p.hint(t("inst.modify_uninstall_hint"))
        self.uninstall_btn = ui_kit.make_button(
            t("inst.loader_uninstall"), kind="secondary", icon_key="delete",
            on_click=self._uninstall_loader, min_h=34)
        drow = QHBoxLayout()
        drow.addWidget(self.uninstall_btn)
        drow.addStretch(1)
        p.add_layout(drow)

        if not self._ver_editable:
            p.hint(t("instances.setting_external_hint"))
            for b in (self.install_btn, self.uninstall_btn):
                b.setEnabled(False)

        p.stretch()
        return p

    # ── ④ Java ──────────────────────────────────────────────
    def _page_java(self) -> _Page:
        p = _Page(self)
        inst = self._inst
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
        row = p.row(t("inst.java_pick"), self.java_combo)
        browse = ui_kit.make_button(
            t("inst.java_browse"), kind="secondary", icon_key="folder",
            on_click=self._browse_java, min_h=30)
        row.addWidget(browse)
        p.hint(t("inst.java_hint"))

        self.java_force_chk = QCheckBox(t("instances.java_force_label"))
        self.java_force_chk.setChecked(bool(getattr(inst, "java_force", False)))
        p.add(self.java_force_chk)

        p.stretch()
        self._load_java_list()
        return p

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

    # ── ④ 目录与格式 ────────────────────────────────────────
    def _page_dir(self) -> _Page:
        p = _Page(self)
        inst = self._inst
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

        p.section(t("inst.isolation_section"))
        self.iso_combo = QComboBox()
        self.iso_combo.addItem(t("instances.isolation_follow"), "")
        self.iso_combo.addItem(t("instances.isolation_isolated"), "isolated")
        self.iso_combo.addItem(t("instances.isolation_custom"), "custom")
        idx = self.iso_combo.findData(inst.isolation or "")
        self.iso_combo.setCurrentIndex(idx if idx >= 0 else 0)
        p.row(t("instances.isolation"), self.iso_combo)

        # ☠ 整行一起藏：只 hide 输入框会把「自定义目录」这个标签留在原地，
        # 选「跟随全局」时出现一行没有控件的孤立标签（截图实测）。
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
        self._refresh_status()

    def _pick_game_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("inst.game_dir_label"))
        if path:
            self.game_dir_edit.setText(path)

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
    def _page_adv(self) -> _Page:
        p = _Page(self)
        inst = self._inst
        p.section(t("inst.hooks_section"))
        self.post_cmd_edit = p.field(t("inst.post_cmd_label"))
        self.post_cmd_edit.setText((inst.post_launch_cmd or "").strip())
        self.post_cmd_edit.setPlaceholderText(t("instances.hook_ph"))
        self.exit_cmd_edit = p.field(t("inst.exit_cmd_label"))
        self.exit_cmd_edit.setText((inst.exit_cmd or "").strip())
        self.exit_cmd_edit.setPlaceholderText(t("instances.hook_ph"))

        p.section(t("inst.meta_section"))
        id_edit = QLineEdit(inst.id or "")
        id_edit.setReadOnly(True)
        p.row(t("inst.meta_id"), id_edit)
        src_edit = QLineEdit(
            "%s%s" % (loader_name(inst.loader or "vanilla"),
                       (" · " + inst.kind) if inst.kind else ""))
        src_edit.setReadOnly(True)
        p.row(t("inst.meta_source"), src_edit)
        dir_edit = QLineEdit(inst.mc_dir or "")
        dir_edit.setReadOnly(True)
        # 只读长路径默认把光标放在末尾 → 显示成「\Appdata\AC_Launcher\…」，
        # 盘符被截掉（截图实测）。归零后从 D:\ 开始显示。
        dir_edit.setCursorPosition(0)
        self.adv_dir_edit = dir_edit
        d_row = p.row(t("inst.meta_dir"), dir_edit)
        d_row.addWidget(ui_kit.make_button(
            t("inst.open_folder"), kind="secondary", icon_key="folder",
            on_click=lambda: _open_path(self, inst.mc_dir), min_h=30))
        p.hint(t("inst.meta_ro_hint"))

        # round-184：导出整合包（.mrpack）—— 对应 PCL 概览页的「高级管理」区
        p.section(t("export.title"))
        p.hint(t("export.overrides_hint"))
        ex_row = QHBoxLayout()
        ex_row.setSpacing(8)
        ex_row.addWidget(ui_kit.make_button(
            t("instances.export_pack"), kind="secondary", icon_key="export",
            on_click=self._export_pack, min_h=32))
        ex_row.addStretch(1)
        p.add_layout(ex_row)

        p.stretch()
        return p

    def _export_pack(self) -> None:
        from .export_pack_dialog import ExportPackDialog
        # 先落字段：导出读的是实例对象，玩家刚改的版本号/加载器要用上
        self._collect(trigger=False)
        ExportPackDialog(self, self._inst).exec()

    # ── 加载器版本列表 ──────────────────────────────────────
    def _current_loader(self) -> str:
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
        mc = self.ver_edit.text().strip() or self._inst.game_version or ""
        keep = (keep or self._inst.loader or "vanilla").strip().lower()
        allowed = loaders_for(mc, LOADERS)
        if keep and keep not in allowed:
            allowed = [keep] + allowed
        self.loader_combo.blockSignals(True)
        self.loader_combo.clear()
        for lid in allowed:
            self.loader_combo.addItem(loader_name(lid), lid)
        idx = self.loader_combo.findData(keep)
        self.loader_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.loader_combo.blockSignals(False)
        self._sync_fabapi_visibility()

    def _on_version_edited(self) -> None:
        """MC 版本改了 → 加载器可选集与版本列表都要跟着变。"""
        self._rebuild_loader_choices()
        self._load_loader_versions()

    def _on_loader_picked(self, _idx: int) -> None:
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
        mc = self.ver_edit.text().strip() or self._inst.game_version or ""
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
            self.ldver_combo.addItem(label, meta)
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
                "color:%s;font-size:11px;" % COLORS["success"])
        else:
            self.ld_state.setText(t("inst.loader_state_absent"))
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
        self.accept()

    def _collect(self, trigger: bool = False) -> bool:
        """把表单写回实例。返回「版本/加载器是否变了」。"""
        inst = self._inst
        inst.name = self.name_edit.text().strip() or inst.name
        inst.group = self.group_edit.text().strip()
        if self._ver_editable:
            inst.game_version = (self.ver_edit.text().strip()
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
        inst.game_args = self.game_args_edit.text().strip()
        inst.java_path = self.java_combo.currentData() or ""
        inst.java_force = self.java_force_chk.isChecked()
        inst.format = self.fmt_combo.currentData() or ""
        inst.isolation = self.iso_combo.currentData() or ""
        inst.game_dir_override = self.game_dir_edit.text().strip()
        inst.post_launch_cmd = self.post_cmd_edit.text().strip()
        inst.exit_cmd = self.exit_cmd_edit.text().strip()

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
