"""「模块」设置分区 — 功能扩展包 + 内容模块市场 + 从文件安装。

四个分组（自上而下）：
  1. 功能扩展     可物理删除的页面扩展（音乐/成就/控制台…）安装 / 删除 / 从链接装
  2. 内容模块     已安装模块的开关 / 应用 / 导出 / 卸载
  3. 模块市场     内置精选（主题 / JVM 预设 / 音效包 / 崩溃策略）
  4. 从文件安装   .zip 模块包 / 旧版主题包 .json 自动转模块

模块数据操作在 src/modules.py；功能扩展数据操作在 src/features.py；
本页只管编排 UI。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QGroupBox, QCheckBox, QFrame, QMenu,
)

from . import modules as M
from . import features as F
from .i18n import t, get_language
from .theme import COLORS, with_alpha
from .icons import icon
from .win_rounded import info, warn, confirm, pick_files, pick_folder

# round-100：模块类型徽章改中性（cls="badge"）。旧版按类型给 4 种品牌色，
# 与加载器徽章同一问题——多色同屏显花，且硬编码色不随主题/自定义 accent
# 联动。类型名文字已足够区分，颜色不再承担语义。


def _lname(name: str, name_en: str) -> str:
    return name_en if get_language().startswith("en") else name


def _mod_name(m: M.ModuleInfo) -> str:
    return _lname(m.name, m.name_en)


def _type_label(mtype: str) -> str:
    key = M.MODULE_TYPES.get(mtype)
    return t(key) if key else mtype


def _more_btn(entries) -> QPushButton:
    """行尾「⋯」菜单（round-104）：把导出/卸载等次要操作收进一个下拉按钮，
    避免每行堆一排图标钮。``entries``: [(label, icon_key, callback), ...]。"""
    btn = QPushButton("⋯")
    btn.setToolTip(t("common.more"))
    btn.setFixedSize(30, 30)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setProperty("cls", "surface")
    menu = QMenu(btn)
    for label, ico, cb in entries:
        a = menu.addAction(icon(ico), label)
        a.triggered.connect(lambda _c=False, f=cb: f())
    btn.setMenu(menu)
    return btn


class ModulesPage(QWidget):
    """Embedded into the settings page as its own left-section."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    # ── scaffold ─────────────────────────────────────────────────────────
    def _build(self):
        existing = self.layout()
        lay = existing if existing else QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(16)

        # ── round-167 功能扩展包：可物理删除的页面 ──
        self._feat_grp = QGroupBox(t("features.group"))
        fg = QVBoxLayout(self._feat_grp)
        fg.setSpacing(8)
        fhint = QLabel(t("features.hint"))
        fhint.setProperty("cls", "sub")
        fhint.setWordWrap(True)
        fg.addWidget(fhint)
        self._feat_lay = QVBoxLayout()
        fg.addLayout(self._feat_lay)
        frow = QHBoxLayout()
        fb_file = QPushButton(t("features.install_file"))
        fb_file.setMinimumHeight(32)
        fb_file.clicked.connect(self._install_feature_file)
        fb_url = QPushButton(t("features.install_url"))
        fb_url.setMinimumHeight(32)
        fb_url.clicked.connect(self._install_feature_url)
        frow.addWidget(fb_file)
        frow.addWidget(fb_url)
        frow.addStretch(1)
        fg.addLayout(frow)
        lay.addWidget(self._feat_grp)

        self._inst_grp = QGroupBox(t("modules.installed"))
        self._inst_lay = QVBoxLayout(self._inst_grp)
        self._inst_lay.setSpacing(6)
        lay.addWidget(self._inst_grp)

        self._market_grp = QGroupBox(t("modules.market"))
        ml = QVBoxLayout(self._market_grp)
        ml.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(QLabel(t("modules.filter")))
        self._market_filter = QComboBox()
        self._market_filter.addItem(t("modules.filter_all"), "")
        for mtype in M.TYPE_ORDER:
            self._market_filter.addItem(_type_label(mtype), mtype)
        self._market_filter.currentIndexChanged.connect(self._fill_market)
        head.addWidget(self._market_filter, stretch=1)
        ml.addLayout(head)
        self._market_lay = QVBoxLayout()
        ml.addLayout(self._market_lay)
        lay.addWidget(self._market_grp)

        ff_grp = QGroupBox(t("modules.from_file"))
        fl = QVBoxLayout(ff_grp)
        fl.setSpacing(8)
        hint = QLabel(t("modules.from_file_hint"))
        hint.setProperty("cls", "sub")
        hint.setWordWrap(True)
        fl.addWidget(hint)
        brow = QHBoxLayout()
        zip_b = QPushButton(icon("import"), t("modules.install_zip_btn"))
        zip_b.setMinimumHeight(32)
        zip_b.clicked.connect(self._install_module_zip)
        leg_b = QPushButton(icon("import"), t("modules.import_theme_btn"))
        leg_b.setMinimumHeight(32)
        leg_b.clicked.connect(self._import_legacy_theme)
        brow.addWidget(zip_b)
        brow.addWidget(leg_b)
        brow.addStretch(1)
        fl.addLayout(brow)
        lay.addWidget(ff_grp)

        self._refresh()

    def _refresh(self):
        self._fill_features()
        self._fill_installed()
        self._fill_market()

    @staticmethod
    def _clear(lay: QVBoxLayout):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    # ── 0. 功能扩展包（round-167）─────────────────────────────────────────
    def _fill_features(self):
        """已装扩展 + 可恢复的内置包。删除/安装后主窗口会重建导航。"""
        self._clear(self._feat_lay)
        try:
            packs = F.scan_installed()
            builtin_ids = F.bundled_ids()
        except Exception:  # noqa: BLE001 - 扩展目录坏掉不拖垮设置页
            packs, builtin_ids = [], set()
        if not packs:
            empty = QLabel(t("features.none"))
            empty.setProperty("cls", "sub")
            empty.setWordWrap(True)
            self._feat_lay.addWidget(empty)
        for p in packs:
            self._feat_lay.addWidget(
                self._feature_row(p, p.id in builtin_ids))
        try:
            avail = F.list_builtins()
        except Exception:  # noqa: BLE001
            avail = []
        for item in avail:
            self._feat_lay.addWidget(self._feature_avail_row(item))

    def _feature_row(self, pack, is_builtin: bool) -> QFrame:
        row = QFrame()
        row.setProperty("cls", "card")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(f"{_lname(pack.name, pack.name_en)}  v{pack.version}")
        name.setStyleSheet("font-size: 13px; font-weight: 700;")
        col.addWidget(name)
        desc = QLabel(_lname(pack.description, pack.description_en) or " ")
        desc.setProperty("cls", "sub")
        desc.setWordWrap(True)
        col.addWidget(desc)
        h.addLayout(col, stretch=1)
        badge = QLabel(t("features.builtin") if is_builtin else t("features.manual"))
        badge.setProperty("cls", "badge")
        h.addWidget(badge)
        del_b = QPushButton(t("features.delete"))
        del_b.setProperty("cls", "secondary")
        del_b.setMinimumHeight(30)
        del_b.clicked.connect(lambda _=False, p=pack: self._uninstall_feature(p))
        h.addWidget(del_b)
        return row

    def _feature_avail_row(self, item: dict) -> QFrame:
        row = QFrame()
        row.setProperty("cls", "card")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(
            f"{_lname(item.get('name', ''), item.get('name_en', ''))}"
            f"  v{item.get('version', '')}")
        name.setStyleSheet("font-size: 13px; font-weight: 700;")
        col.addWidget(name)
        desc = QLabel(
            _lname(item.get("description", ""), item.get("description_en", "")) or " ")
        desc.setProperty("cls", "sub")
        desc.setWordWrap(True)
        col.addWidget(desc)
        h.addLayout(col, stretch=1)
        badge = QLabel(t("features.builtin"))
        badge.setProperty("cls", "badge")
        h.addWidget(badge)
        ins_b = QPushButton(t("features.install"))
        ins_b.setMinimumHeight(30)
        ins_b.clicked.connect(lambda _=False, it=item: self._restore_feature(it))
        h.addWidget(ins_b)
        return row

    def _uninstall_feature(self, pack):
        if not confirm(self, t("features.delete"),
                       t("features.delete_confirm",
                         name=_lname(pack.name, pack.name_en))):
            return
        try:
            F.uninstall(pack.id)
        except Exception as e:  # noqa: BLE001
            warn(self, t("features.failed"), str(e))
            return
        self._fill_features()
        self._notify_features_changed()

    def _restore_feature(self, item: dict):
        try:
            pack = F.restore_builtin(item.get("id", ""))
        except Exception as e:  # noqa: BLE001
            warn(self, t("features.failed"), str(e))
            return
        self._after_feature_install(pack)

    def _install_feature_file(self):
        path = pick_files(self, t("features.install_file"), "",
                          t("features.file_filter"))
        if not path:
            return
        try:
            if path.lower().endswith(".py"):
                # 单脚本扩展拥有启动器同等权限 → 安装前必须明示确认
                if not confirm(self, t("features.script_warn_title"),
                               t("features.script_warn")):
                    return
                pack = F.install_from_script(path)
            else:
                # zip 里同样是可执行代码，装前必须确认来源可信
                if not confirm(self, t("features.pack_warn_title"),
                               t("features.pack_warn")):
                    return
                pack = F.install_from_zip(path)
        except Exception as e:  # noqa: BLE001
            warn(self, t("features.failed"), str(e))
            return
        self._after_feature_install(pack)

    def _install_feature_url(self):
        from PySide6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(
            self, t("features.url_title"), t("features.url_hint"))
        if not ok or not str(url).strip():
            return
        if not confirm(self, t("features.pack_warn_title"),
                       t("features.pack_warn")):
            return
        try:
            pack = F.install_from_url(str(url).strip())
        except Exception as e:  # noqa: BLE001
            warn(self, t("features.failed"), str(e))
            return
        self._after_feature_install(pack)

    def _after_feature_install(self, pack):
        info(self, t("features.ok"),
             t("features.installed", name=_lname(pack.name, pack.name_en)))
        self._fill_features()
        self._notify_features_changed()

    def _notify_features_changed(self):
        """安装/删除后让主窗口重建导航与栈槽（本页嵌在设置页里）。"""
        try:
            win = self.window()
            fn = getattr(win, "_reload_feature_packs", None)
            if callable(fn):
                fn()
        except Exception:  # noqa: BLE001 - 导航刷新失败不影响设置页
            pass

    # ── 1. 已安装模块 ────────────────────────────────────────────────────
    def _fill_installed(self):
        self._clear(self._inst_lay)
        mods = M.scan_modules()
        if not mods:
            empty = QLabel(t("modules.installed_empty"))
            empty.setProperty("cls", "sub")
            empty.setWordWrap(True)
            self._inst_lay.addWidget(empty)
            return
        applied = self._applied_flags()
        for m in mods:
            self._inst_lay.addWidget(self._module_row(m, applied.get(m.id)))

    def _applied_flags(self) -> dict:
        cfg = M._cfg()
        flags: dict[str, str] = {}
        for m in M.scan_modules():
            if m.type == "theme_pack" and cfg.get("theme_pack") == m.id:
                flags[m.id] = "theme_pack"
            elif m.type == "jvm_preset" and cfg.get("_jvm_module") == m.id:
                flags[m.id] = "jvm_preset"
            elif m.type == "sfx_pack" and cfg.get("_sfx_module") == m.id:
                flags[m.id] = "sfx_pack"
            elif m.type == "crash_pol" and cfg.get("_crash_module") == m.id:
                flags[m.id] = "crash_pol"
            elif m.type == "effect" and m.id in (cfg.get("_effect_owners") or {}).values():
                flags[m.id] = "effect"
        return flags

    def _module_row(self, m: M.ModuleInfo, applied: str) -> QFrame:
        row = QFrame()
        row.setProperty("cls", "card")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        enable = QCheckBox()
        enable.setChecked(m.enabled)
        enable.setToolTip(t("modules.enable_tip"))
        enable.stateChanged.connect(
            lambda st, mid=m.id: (M.set_module_enabled(mid, bool(st)),
                                  self._fill_installed()))
        h.addWidget(enable)

        col = QVBoxLayout()
        col.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = QLabel(f"{_mod_name(m)}  v{m.version}")
        name.setStyleSheet("font-size: 13px; font-weight: 700;")
        name_row.addWidget(name)
        if m.author:
            au = QLabel(t("modules.by", author=m.author))
            au.setProperty("cls", "sub")
            name_row.addWidget(au)
        name_row.addStretch(1)
        col.addLayout(name_row)
        desc = QLabel(_lname(m.description, m.description_en) or " ")
        desc.setProperty("cls", "sub")
        desc.setWordWrap(True)
        col.addWidget(desc)
        h.addLayout(col, stretch=1)

        badge = QLabel(_type_label(m.type))
        badge.setProperty("cls", "badge")
        h.addWidget(badge)
        if applied:
            ok = QLabel(t("modules.applied"))
            ok.setStyleSheet(
                f"color: {COLORS['success']};"
                f" background: {with_alpha(COLORS['success'], 0x1F)};"
                " border-radius: 9px; "
                "padding: 2px 10px; font-size: 11px; font-weight: 600;")
            h.addWidget(ok)

        apply_b = QPushButton(t("modules.apply"))
        apply_b.setMinimumHeight(30)
        apply_b.clicked.connect(lambda _=False, mm=m: self._apply_module(mm))
        h.addWidget(apply_b)
        h.addWidget(_more_btn([
            (t("modules.export_tip"), "export",
             lambda mm=m: self._export_module(mm)),
            (t("modules.uninstall_tip"), "delete",
             lambda mm=m: self._uninstall_module(mm)),
        ]))
        return row

    def _apply_module(self, m: M.ModuleInfo):
        try:
            if m.type == "theme_pack":
                M.apply_theme_module(m)
            elif m.type == "jvm_preset":
                M.apply_jvm_module(m)
            elif m.type == "sfx_pack":
                M.apply_sfx_module(m)
            elif m.type == "crash_pol":
                M.apply_crash_module(m)
            elif m.type == "effect":
                M.apply_effect_module(m)
            else:
                warn(self, t("modules.apply"), t("modules.type_unknown"))
                return
        except Exception as e:  # noqa: BLE001
            warn(self, t("modules.apply"), str(e))
            return
        info(self, t("modules.apply_ok_title"),
             t("modules.apply_ok", name=_mod_name(m)))
        self._fill_installed()

    def _export_module(self, m: M.ModuleInfo):
        dest = pick_folder(self, t("modules.export_title"), "")
        if not dest:
            return
        try:
            path = os.path.join(dest, f"{m.id}.zip")
            M.export_module_zip(m, path)
        except Exception as e:  # noqa: BLE001
            warn(self, t("modules.export_fail"), str(e))
            return
        info(self, t("modules.export_ok_title"), path)

    def _uninstall_module(self, m: M.ModuleInfo):
        if not confirm(self, t("modules.uninstall"),
                       t("modules.uninstall_confirm", name=_mod_name(m))):
            return
        try:
            M.uninstall_module(m.id)
        except Exception as e:  # noqa: BLE001
            warn(self, t("modules.uninstall"), str(e))
            return
        self._fill_installed()

    # ── 2. 模块市场 ──────────────────────────────────────────────────────
    def _fill_market(self):
        self._clear(self._market_lay)
        ft = self._market_filter.currentData() or ""
        entries = [e for e in M.load_catalog() if not ft or e.get("type") == ft]
        installed = {m.id: m for m in M.scan_modules()}
        if not entries:
            empty = QLabel(t("modules.market_empty"))
            empty.setProperty("cls", "sub")
            self._market_lay.addWidget(empty)
            return
        for e in entries:
            eid = e.get("id", "")
            row = QFrame()
            row.setProperty("cls", "card")
            h = QHBoxLayout(row)
            h.setContentsMargins(12, 8, 12, 8)
            h.setSpacing(10)
            col = QVBoxLayout()
            col.setSpacing(2)
            nr = QHBoxLayout()
            nr.setSpacing(6)
            nm = QLabel(_lname(e.get("name", eid), e.get("name_en", "") or e.get("name", eid)))
            nm.setStyleSheet("font-size: 13px; font-weight: 700;")
            nr.addWidget(nm)
            if e.get("author"):
                au = QLabel(t("modules.by", author=e.get("author", "")))
                au.setProperty("cls", "sub")
                nr.addWidget(au)
            nr.addStretch(1)
            col.addLayout(nr)
            ds = QLabel(_lname(e.get("description", ""), e.get("description_en", "") or e.get("description", "")))
            ds.setProperty("cls", "sub")
            ds.setWordWrap(True)
            col.addWidget(ds)
            h.addLayout(col, stretch=1)
            badge = QLabel(_type_label(e.get("type", "")))
            badge.setProperty("cls", "badge")
            h.addWidget(badge)
            if eid in installed:
                ok = QLabel(t("modules.installed_label"))
                ok.setStyleSheet(
                    f"color: {COLORS['success']};"
                    f" background: {with_alpha(COLORS['success'], 0x1F)};"
                    " border-radius: 9px; "
                    "padding: 2px 10px; font-size: 11px; font-weight: 600;")
                h.addWidget(ok)
            else:
                ins = QPushButton(t("modules.install"))
                ins.setProperty("cls", "secondary")
                ins.setMinimumHeight(30)
                ins.clicked.connect(lambda _=False, en=e: self._install_bundle(en))
                h.addWidget(ins)
            self._market_lay.addWidget(row)
        h = QHBoxLayout()
        note = QLabel(t("modules.market_hint"))
        note.setProperty("cls", "sub")
        note.setWordWrap(True)
        self._market_lay.addWidget(note)

    def _install_bundle(self, entry: dict):
        try:
            mod = M.install_bundle(entry)
        except Exception as e:  # noqa: BLE001
            warn(self, t("modules.install_fail"), str(e))
            return
        info(self, t("modules.install_ok_title"),
             t("modules.install_ok", name=_mod_name(mod)))
        self._fill_market()
        self._fill_installed()

    # ── 3. 从文件安装 ────────────────────────────────────────────────────
    # ia[settings]: 点「从文件安装」 | 模块分区 | 选择 .zip 安装模块，成功/失败弹窗后刷新列表
    def _install_module_zip(self):
        path = pick_files(self, t("modules.install_zip_title"), "",
                          t("modules.zip_filter"))
        if not path:
            return
        try:
            mod = M.install_module_zip(path)
        except Exception as e:  # noqa: BLE001
            warn(self, t("modules.install_fail"), str(e))
            return
        info(self, t("modules.install_ok_title"),
             t("modules.install_ok", name=_mod_name(mod)))
        self._fill_installed()

    def _import_legacy_theme(self):
        path = pick_files(self, t("modules.import_theme_title"), "",
                          t("modules.json_filter"))
        if not path:
            return
        try:
            mod = M.install_legacy_theme_pack(path)
        except Exception as e:  # noqa: BLE001
            warn(self, t("modules.import_theme_fail"), str(e))
            return
        info(self, t("modules.import_theme_ok_title"),
             t("modules.import_theme_ok", name=_mod_name(mod)))
        self._fill_installed()
