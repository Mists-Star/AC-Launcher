"""Versions & Store pages (network-backed browsing).

VersionsPage: official version list, grouped by type (release / snapshot /
legacy) with per-version cover tiles + release dates, mark installed,
create instance per version.
StorePage: Modrinth mod browser + search, download into current instance's mods,
with real mod icons fetched from Modrinth's CDN.
"""
from __future__ import annotations

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QComboBox, QDialog,
)
from PySide6.QtCore import Signal, QSize, QTimer

from .theme import COLORS, RoundedCard
from .icons import icon
from .i18n import t, version_type_name, loader_name
from .win_rounded import info, confirm
from .instances import manager
from .pages_instances import NewInstanceDialog
from .net_api import (
    fetch_versions, search_mods, download_mod_to, download_modpack_to,
    fetch_optifine_versions, download_optifine_to,
    STORE_CATEGORIES,
)
from .worker import Worker
from .async_image import ImageLoader, make_version_pixmap

TYPE_COLOR = {
    "release": COLORS["success"], "snapshot": COLORS["warn"],
    "april": "#DB2777",
    "old_beta": COLORS["text_sub"], "old_alpha": COLORS["text_sub"],
}
# group -> display ordering + which raw types belong to it
_GROUP_ORDER = ["release", "snapshot", "april", "legacy"]
_GROUP_OF_TYPE = {"release": "release", "snapshot": "snapshot", "old_beta": "legacy", "old_alpha": "legacy"}


def _group_of(v: dict) -> str:
    if v.get("april"):
        return "april"
    return _GROUP_OF_TYPE.get(v["type"], "legacy")


# ---------------------------------------------------------------- Versions
class VersionsPage(QWidget):
    instance_created = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mgr = manager()
        self._versions: list[dict] = []
        self._img = ImageLoader(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        head = QHBoxLayout()
        self.title_lbl = QLabel(t("versions.title"))
        self.title_lbl.setProperty("cls", "big")
        head.addWidget(self.title_lbl)
        head.addStretch(1)

        self.filter = QComboBox()
        for key, lbl in [
            ("all", t("versions.filter_all")),
            ("release", t("versions.filter_release")),
            ("snapshot", t("versions.filter_snapshot")),
            ("april", t("versions.filter_april")),
            ("legacy", t("versions.filter_legacy")),
        ]:
            self.filter.addItem(lbl, key)
        self.filter.setMinimumHeight(36)
        self.filter.setMinimumWidth(120)
        self.filter.currentIndexChanged.connect(self._apply_filter)
        head.addWidget(self.filter)

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("versions.filter_placeholder"))
        self.search.setMinimumHeight(36)
        self.search.setMinimumWidth(200)
        self.search.textChanged.connect(self._apply_filter)
        head.addWidget(self.search)

        self.refresh_btn = QPushButton(t("versions.refresh"))
        self.refresh_btn.setMinimumHeight(36)
        self.refresh_btn.setIcon(icon("refresh"))
        self.refresh_btn.setIconSize(QSize(16, 16))
        self.refresh_btn.clicked.connect(self._load)
        head.addWidget(self.refresh_btn)
        root.addLayout(head)

        self.status = QLabel(t("versions.loading"))
        self.status.setProperty("cls", "sub")
        root.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self._load_gen = 0  # guards against stale worker results
        self._content = QWidget()
        self._vbox = QVBoxLayout(self._content)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(18)
        self.scroll.setWidget(self._content)
        root.addWidget(self.scroll, stretch=1)

        self._load()

    def _load(self):
        self.status.setText(t("versions.fetching"))
        self._load_gen += 1
        gen = self._load_gen
        self._worker = Worker(fetch_versions)
        self._worker.finished.connect(
            lambda data: self._on_loaded(data) if gen == self._load_gen else None
        )
        self._worker.error.connect(
            lambda e: self.status.setText(t("versions.error", e=e))
            if gen == self._load_gen else None
        )
        self._worker.start()

    def _on_loaded(self, data):
        _, versions = data
        self._versions = versions
        self.status.setText(t("versions.count", n=len(versions)))
        self._apply_filter()

    def _fmt_date(self, rt: str) -> str:
        return rt[:10] if rt else ""

    def _apply_filter(self):
        q = self.search.text().strip().lower()
        only_group = self.filter.currentData()
        installed = {i.game_version for i in self.mgr.list()}
        # 彻底清空 layout：takeAt 会把包括 stretch 在内的所有项从 layout
        # 移除（避免 stretch 无限堆积），widget 再单独 deleteLater 异步销毁。
        # 之前只 deleteLater widget 而从不移除 stretch 项，反复切换过滤
        # （正式版/快照/愚人节）几十次后 layout 项数爆炸 → Qt 布局崩溃闪退。
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        shown = self._versions
        if q:
            shown = [v for v in shown if q in v["id"].lower()]
        groups = _GROUP_ORDER if only_group == "all" else [only_group]

        for g in groups:
            members = [v for v in shown if _group_of(v) == g]
            if not members:
                continue
            # 「最新版本」置顶组（对齐 PCL 下载页）：正式版取最新 1 个，
            # 快照取最新 1 个，合并显示在顶部（仅"全部"过滤时出现）。
            if only_group == "all" and g == "release":
                latest = members[0]
                snap_members = [v for v in shown if _group_of(v) == "snapshot"]
                latest_snap = snap_members[0] if snap_members else None
                hdr = QLabel(t("versions.group.latest"))
                hdr.setProperty("cls", "group")
                self._vbox.addWidget(hdr)
                self._vbox.addWidget(self._make_card(latest, latest["id"] in installed))
                if latest_snap and latest_snap["id"] != latest["id"]:
                    self._vbox.addWidget(self._make_card(latest_snap, latest_snap["id"] in installed))
                continue
            # group header
            hdr = QLabel(t(f"versions.group.{g}"))
            hdr.setProperty("cls", "group")
            self._vbox.addWidget(hdr)
            for v in members:
                self._vbox.addWidget(self._make_card(v, v["id"] in installed))
        self._vbox.addStretch(1)

    def _make_card(self, v: dict, is_installed: bool) -> QFrame:
        card = RoundedCard(radius=12)
        card.setMinimumHeight(76)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(14)

        tile = QLabel()
        tile.setPixmap(make_version_pixmap(v["id"], "april" if v.get("april") else v["type"], 56))
        tile.setFixedSize(56, 56)
        lay.addWidget(tile)

        info = QVBoxLayout()
        info.setSpacing(3)
        name = QLabel(v["id"])
        name.setProperty("cls", "title")
        info.addWidget(name)
        date = QLabel(t("versions.released", date=self._fmt_date(v["releaseTime"])))
        date.setProperty("cls", "sub")
        info.addWidget(date)
        lay.addLayout(info, stretch=1)

        if v.get("april"):
            tag_text = t("versions.type.april")
            tag_color = TYPE_COLOR["april"]
        else:
            tag_text = version_type_name(v["type"])
            tag_color = TYPE_COLOR.get(v["type"], COLORS["text_sub"])
        tag = QLabel(tag_text)
        tag.setStyleSheet(f"color: {tag_color};")
        lay.addWidget(tag)

        if is_installed:
            done = QLabel(t("versions.installed"))
            done.setStyleSheet(f"color: {COLORS['success']};")
            lay.addWidget(done)
        else:
            b = QPushButton(t("versions.install"))
            b.setToolTip(t("versions.install_hint"))
            b.setMinimumHeight(32)
            b.setIcon(icon("add"))
            b.setIconSize(QSize(15, 15))
            b.clicked.connect(lambda _, vid=v["id"]: self._create(vid))
            lay.addWidget(b)
        return card

    def _create(self, version_id: str):
        """版本页"安装"入口：打开新建实例向导（预填版本 + 可选加载器），
        对齐 PCL2/HMCL 的"选版本 → 选加载器 → 安装"流程。"""
        dlg = NewInstanceDialog(self, preset_version=version_id)
        if dlg.exec() != QDialog.Accepted:
            return
        name, version, loader, java_path, ldver = dlg.result_data()
        inst = self.mgr.add(name, version, loader, loader_version=ldver,
                            java_path=java_path)
        info(
            self, t("versions.created_title"),
            t("versions.created_msg",
              name=inst.name, version=version, loader=loader_name(loader)),
        )
        self.instance_created.emit(inst.id)

    def retranslate_ui(self):
        self.title_lbl.setText(t("versions.title"))
        self.refresh_btn.setText(t("versions.refresh"))
        self.search.setPlaceholderText(t("versions.filter_placeholder"))
        # Rebuild filter combo items
        current_filter = self.filter.currentData()
        self.filter.clear()
        for key, lbl in [
            ("all", t("versions.filter_all")),
            ("release", t("versions.filter_release")),
            ("snapshot", t("versions.filter_snapshot")),
            ("april", t("versions.filter_april")),
            ("legacy", t("versions.filter_legacy")),
        ]:
            self.filter.addItem(lbl, key)
        # restore selection
        idx = self.filter.findData(current_filter)
        if idx >= 0:
            self.filter.setCurrentIndex(idx)


# ---------------------------------------------------------------- Store
# 下载目标子目录（按 Modrinth project_type 映射到实例内目录）
_TYPE_SUBDIR = {
    "mod":          "mods",
    "shader":       "shaderpacks",
    "resourcepack": "resourcepacks",
    "datapack":     "datapacks",
}


class StorePage(QWidget):
    def __init__(self, list_instances, get_current_instance, parent=None):
        super().__init__(parent)
        self.list_instances = list_instances
        self.get_current = get_current_instance
        self._mods: list[dict] = []
        self._offset = 0
        self._query = ""
        self._category = "mod"
        self._source = "modrinth"
        self._img = ImageLoader(self)
        self._fallback = icon("store").pixmap(48, 48)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        # 顶部标题栏（标题 + 源切换 + 分类）—— 第一行
        head = QHBoxLayout()
        head.setSpacing(12)
        self.title_lbl = QLabel(t("store.title"))
        self.title_lbl.setProperty("cls", "big")
        head.addWidget(self.title_lbl)
        head.addStretch(1)
        # 下载源切换（Modrinth 默认；CurseForge 免注册）
        self.source_combo = QComboBox()
        self.source_combo.setMinimumHeight(32)
        self.source_combo.setMinimumWidth(100)
        self.source_combo.addItem(t("store.source_modrinth"), "modrinth")
        self.source_combo.addItem(t("store.source_curseforge"), "curseforge")
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        head.addWidget(self.source_combo)
        # 分类下拉（对齐 PCL2 下载分类：模组/整合包/光影/资源包/数据包/OptiFine）
        self.category_combo = QComboBox()
        self.category_combo.setMinimumHeight(32)
        self.category_combo.setMinimumWidth(110)
        for pt, key in STORE_CATEGORIES:
            self.category_combo.addItem(t(key), pt)
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        head.addWidget(self.category_combo)
        root.addLayout(head)

        # 第二行：目标实例 + 搜索框 + 搜索按钮（搜索框随窗口伸缩）
        head2 = QHBoxLayout()
        head2.setSpacing(10)
        self.target_lbl = QLabel(t("store.target_label"))
        self.target_lbl.setProperty("cls", "sub")
        head2.addWidget(self.target_lbl)
        self.inst_combo = QComboBox()
        self.inst_combo.setMinimumHeight(32)
        self.inst_combo.setMinimumWidth(200)
        self.inst_combo.currentIndexChanged.connect(self._on_target_changed)
        head2.addWidget(self.inst_combo)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("store.search_placeholder"))
        self.search.setMinimumHeight(34)
        self.search.returnPressed.connect(self._search)
        head2.addWidget(self.search, stretch=1)
        self.search_btn = QPushButton(t("store.search"))
        self.search_btn.setMinimumHeight(34)
        self.search_btn.setIcon(icon("search"))
        self.search_btn.setIconSize(QSize(16, 16))
        self.search_btn.clicked.connect(self._search)
        head2.addWidget(self.search_btn)
        root.addLayout(head2)

        self.status = QLabel(t("store.loading"))
        self.status.setProperty("cls", "sub")
        root.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self._load_gen = 0  # guards against stale search results
        self._content = QWidget()
        self._vbox = QVBoxLayout(self._content)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(10)
        self.scroll.setWidget(self._content)
        root.addWidget(self.scroll, stretch=1)

        more = QPushButton(t("store.more"))
        more.clicked.connect(self._more)
        root.addWidget(more)

        QTimer.singleShot(0, self._sync_target)
        self._search()

    # ---- category selection ----
    def _on_category_changed(self, _index: int):
        self._category = self.category_combo.currentData()
        self._search()

    def _on_source_changed(self, _index: int):
        """CurseForge 无 key 时走"链接解析"模式（cfwidget+forgecdn 免 key 通道）。

        cfwidget 只支持精确 slug / 完整链接解析（无关键词搜索 API），
        所以在 CF 源下 placeholder 明确提示"slug 或链接"而不是"关键词"。
        """
        self._source = self.source_combo.currentData()
        self.search.setPlaceholderText(
            t("store.cf_link_placeholder") if self._source == "curseforge"
            else t("store.search_placeholder")
        )
        if self._source == "curseforge":
            self.status.setText(t("store.cf_hint"))
        self._search()

    # ---- target instance selection ----
    def _target(self) -> object | None:
        inst_id = self.inst_combo.currentData() if hasattr(self, "inst_combo") else None
        if not inst_id:
            return None
        for i in self.list_instances():
            if i.id == inst_id:
                return i
        return None

    def _on_target_changed(self, _index: int):
        self.status.setText(t("store.target_changed", name=self._target().name) if self._target() else t("store.no_target"))

    def _sync_target(self):
        """Populate the target-instance combo (defaults to current instance)."""
        keep = self.inst_combo.currentData() if hasattr(self, "inst_combo") else None
        instances = self.list_instances()
        self.inst_combo.blockSignals(True)
        self.inst_combo.clear()
        if not instances:
            self.inst_combo.addItem(t("mods.no_instance"), "")
        else:
            for i in instances:
                self.inst_combo.addItem(i.name, i.id)
        cur = self.get_current()
        target = keep or (cur.id if cur else "") or (instances[0].id if instances else "")
        idx = self.inst_combo.findData(target)
        if idx >= 0:
            self.inst_combo.setCurrentIndex(idx)
        self.inst_combo.blockSignals(False)

    def _search(self):
        self._query = self.search.text().strip()
        self._offset = 0
        self._load(reset=True)

    def _more(self):
        self._offset += 20
        self._load(reset=False)

    def _load(self, reset: bool):
        if self._source == "curseforge":
            self._load_curseforge(reset)
            return
        if self._category == "optifine":
            self._load_optifine(reset)
            return
        self.status.setText(t("store.fetching"))
        self._load_gen += 1
        gen = self._load_gen
        self._worker = Worker(search_mods, self._query, self._offset,
                              project_type=self._category)
        self._worker.finished.connect(
            lambda m: self._on_loaded(m, reset) if gen == self._load_gen else None
        )
        self._worker.error.connect(
            lambda e: self.status.setText(t("store.error", e=e))
            if gen == self._load_gen else None
        )
        self._worker.start()

    def _load_curseforge(self, reset: bool):
        """CurseForge 源：有 key → 官方 API 搜索；无 key → 链接/slug 解析（免 key 通道）。"""
        from .net_api import curseforge_available
        if curseforge_available():
            from .net_api import search_curseforge
            worker_fn = search_curseforge
        else:
            from .net_api import curseforge_link_search
            worker_fn = curseforge_link_search
        self._load_gen += 1
        gen = self._load_gen
        self._worker = Worker(worker_fn, self._query)
        self._worker.finished.connect(
            lambda m: self._on_loaded(m, reset) if gen == self._load_gen else None
        )
        self._worker.error.connect(
            lambda e: self.status.setText(t("store.error", e=e))
            if gen == self._load_gen else None
        )
        self._worker.start()

    def _load_optifine(self, reset: bool):
        """OptiFine 分类：按目标实例的 MC 版本列出可用构建（BMCLAPI）。"""
        inst = self._target()
        if inst is None or not inst.game_version:
            self.status.setText(t("store.optifine_no_instance"))
            if reset:
                while self._vbox.count():
                    item = self._vbox.takeAt(0)
                    w = item.widget()
                    if w is not None:
                        w.deleteLater()
            return
        self.status.setText(t("store.optifine_fetching", mc=inst.game_version))
        self._load_gen += 1
        gen = self._load_gen
        self._worker = Worker(fetch_optifine_versions, inst.game_version)
        self._worker.finished.connect(
            lambda m: self._on_loaded(m, reset) if gen == self._load_gen else None
        )
        self._worker.error.connect(
            lambda e: self.status.setText(t("store.error", e=e))
            if gen == self._load_gen else None
        )
        self._worker.start()

    def _on_loaded(self, mods: list[dict], reset: bool):
        self._mods = mods if reset else self._mods + mods
        if reset:
            while self._vbox.count():
                item = self._vbox.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self.status.setText(t("store.results", n=len(self._mods)))
        for m in mods:
            self._vbox.addWidget(self._make_card(m))

    def _make_card(self, m: dict) -> QFrame:
        card = RoundedCard(radius=12)
        card.setMinimumHeight(84)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(14)

        thumb = QLabel()
        thumb.setFixedSize(48, 48)
        self._img.load(m.get("icon_url", ""), 48, thumb, self._fallback)
        lay.addWidget(thumb)

        info = QVBoxLayout()
        info.setSpacing(3)
        title = QLabel(m["title"])
        title.setProperty("cls", "title")
        desc = QLabel(m["description"] or "")
        desc.setProperty("cls", "sub")
        desc.setWordWrap(True)
        meta = QLabel(t("store.meta", downloads=m["downloads"], author=m["author"]))
        meta.setProperty("cls", "sub")
        info.addWidget(title)
        info.addWidget(desc)
        info.addWidget(meta)
        lay.addLayout(info, stretch=1)

        if self._category == "modpack":
            dl = QPushButton(t("store.install"))
            dl.clicked.connect(lambda _, pid=m["project_id"], pslug=m["slug"]:
                               self._install_modpack(pid, pslug))
        else:
            dl = QPushButton(t("store.download"))
            dl.clicked.connect(
                lambda _, pid=m["project_id"], pslug=m["slug"],
                fname=m.get("_filename", ""), cf=m.get("_cf_file"):
                self._download(pid, pslug, fname, cf)
            )
        dl.setMinimumHeight(34)
        dl.setIcon(icon("download"))
        dl.setIconSize(QSize(16, 16))
        lay.addWidget(dl)
        return card

    def _download(self, project_id: str, slug: str, optifine_filename: str = "",
                  cf_file: dict | None = None):
        inst = self._target()
        if inst is None:
            info(self, t("common.hint"), t("store.download_hint"))
            return
        reply = confirm(
            self, t("store.download_confirm_title"),
            t("store.download_confirm", slug=slug, name=inst.name),
        )
        if reply != True:
            return
        self.status.setText(t("store.downloading", slug=slug))
        sub = _TYPE_SUBDIR.get(self._category, "mods")
        dest = os.path.join(inst.mc_dir, sub)
        if self._source == "curseforge":
            from .net_api import download_cfwidget_file
            self._dworker = Worker(download_cfwidget_file, cf_file, dest)
        elif optifine_filename:
            # OptiFine 是 mod：下载 jar 到 mods/（需 Forge/Fabric 前置生效）
            self._dworker = Worker(download_optifine_to, optifine_filename, dest)
        else:
            self._dworker = Worker(download_mod_to, project_id, dest)
        self._dworker.finished.connect(lambda p: self.status.setText(t("store.downloaded", file=os.path.basename(p))))
        self._dworker.error.connect(lambda e: self.status.setText(t("store.download_fail", e=e)))
        self._dworker.start()

    # ---- modpack: download .mrpack → install as a new instance ----
    def _install_modpack(self, project_id: str, slug: str):
        if not confirm(
            self, t("store.install_pack_title"),
            t("store.install_pack_confirm", slug=slug),
        ):
            return
        self.status.setText(t("store.downloading_pack", slug=slug))
        from .paths import get_data_dir
        cache_dir = os.path.join(get_data_dir(), "cache")
        self._pworker = Worker(download_modpack_to, project_id, cache_dir)
        self._pworker.finished.connect(self._on_pack_downloaded)
        self._pworker.error.connect(
            lambda e: self.status.setText(t("store.download_fail", e=e)))
        self._pworker.start()

    def _on_pack_downloaded(self, path: str):
        from .pages_instances import _MrpackDialog, _parse_mrpack_info
        import minecraft_launcher_lib
        try:
            raw = minecraft_launcher_lib.mrpack.get_mrpack_information(path)
            launch_version = minecraft_launcher_lib.mrpack.get_mrpack_launch_version(path)
            info_dict = _parse_mrpack_info(raw)
            info_dict["launch_version"] = launch_version
        except Exception:
            info(self, t("mrpack.title"), t("mrpack.bad_file"))
            return
        dlg = _MrpackDialog(path, info_dict, self)
        dlg.exec()

    def retranslate_ui(self):
        self.title_lbl.setText(t("store.title"))
        self.target_lbl.setText(t("store.target_label"))
        self.search.setPlaceholderText(t("store.search_placeholder"))
        self.search_btn.setText(t("store.search"))
        # rebuild source combo, keep selection
        keep = self.source_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem(t("store.source_modrinth"), "modrinth")
        self.source_combo.addItem(t("store.source_curseforge"), "curseforge")
        idx = self.source_combo.findData(keep)
        if idx >= 0:
            self.source_combo.setCurrentIndex(idx)
        self.source_combo.blockSignals(False)
        # rebuild category combo, keep selection
        keep = self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        for pt, key in STORE_CATEGORIES:
            self.category_combo.addItem(t(key), pt)
        idx = self.category_combo.findData(keep)
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        self.category_combo.blockSignals(False)
        self._sync_target()
