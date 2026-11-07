"""round-187：编辑面板 8 页 → 5 页（对齐 PCL 的 概览/设置/修改/Mod管理/内容）。"""
import io

p = "src/instance_editor.py"
s = io.open(p, encoding="utf-8").read()

# ── 1) 导航 ──────────────────────────────────────────────────────────────
old_nav = '''_NAV = (
    ("basic", "inst.tab_basic", "instances"),
    ("launch", "inst.tab_launch", "play"),
    ("modify", "inst.tab_modify", "repair"),
    ("java", "inst.tab_java", "java"),
    ("dir", "inst.tab_dir", "folder"),
    ("mods", "inst.tab_mods", "mods"),
    ("content", "inst.tab_content", "resourcepack"),
    ("adv", "inst.tab_adv", "tools"),
)'''
new_nav = '''_NAV = (
    ("overview", "inst.tab_overview", "instances"),
    ("setup", "inst.tab_setup", "settings"),
    ("modify", "inst.tab_modify", "repair"),
    ("mods", "inst.tab_mods", "mods"),
    ("content", "inst.tab_content", "resourcepack"),
)'''
assert s.count(old_nav) == 1
s = s.replace(old_nav, new_nav)

# ── 2) builders ──────────────────────────────────────────────────────────
old_b = '''        builders = {
            "basic": self._page_basic,
            "launch": self._page_launch,
            "modify": self._page_modify,
            "java": self._page_java,
            "dir": self._page_dir,
            "mods": self._page_mods,
            "content": self._page_content,
            "adv": self._page_adv,
        }'''
new_b = '''        builders = {
            "overview": self._page_overview,
            "setup": self._page_setup,
            "modify": self._page_modify,
            "mods": self._page_mods,
            "content": self._page_content,
        }'''
assert s.count(old_b) == 1
s = s.replace(old_b, new_b)

# ── 3) 用 _page_overview + _page_setup 替换 basic/launch 两页 ────────────
start = s.index("    def _page_basic(self) -> _Page:")
end = s.index("    # ── ③ 修改（PCL 同名页：只管加载器装卸） ────────────────")
new_pages = '''    def _page_overview(self) -> _Page:
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
        mg.addStretch(1)
        p.add_layout(mg)

        p.stretch()
        return p

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

'''
s = s[:start] + new_pages + s[end:]

# ── 4) 删掉 _page_adv（其内容已并入上面两页），保留 _export_pack ─────────
adv_start = s.index("    def _page_adv(self) -> _Page:")
adv_end = s.index("    # ── 加载器版本列表 ──────────────────────────────────────")
keep_export = '''    def _export_pack(self) -> None:
        """导出整合包（概览页「高级管理」入口）。"""
        from .export_pack_dialog import ExportPackDialog
        # 先落字段：导出读的是实例对象，玩家刚改的版本号/加载器要用上
        self._collect(trigger=False)
        ExportPackDialog(self, self._inst).exec()

'''
s = s[:adv_start] + keep_export + s[adv_end:]

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("restructured")
