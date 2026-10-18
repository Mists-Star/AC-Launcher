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
    QScrollArea, QLineEdit, QComboBox, QDialog, QProgressBar,
)
from PySide6.QtCore import Signal, QSize, QTimer, Qt
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont

from .theme import COLORS, RoundedCard
from .effects import LightTrailCard, fade_in_widget  # round-50 商店卡流光；round-100 列表淡入
from . import ui_kit
from .icons import icon
from .i18n import t, version_type_name, loader_name
from .win_rounded import info, confirm, toast
from .instances import manager
from .pages_instances import NewInstanceDialog
from .net_api import (
    fetch_versions, search_mods, download_mod_to, download_modpack_to,
    STORE_CATEGORIES,
)
from .worker import ProgressWorker, Worker
from .async_image import ImageLoader, make_version_pixmap
from .store_detail import StoreDetailDialog  # round-66 资源详情页（版本/翻译）


def _letter_fallback(title: str, size: int = 48) -> QPixmap:
    """Generate a neutral letter icon as fallback when mod CDN fails.

    round-99 极简：原实现用 ``hash(title) % 360`` 生成随机饱和色块——列表
    里每张卡片一个颜色，花而杂。改为中性灰底（bg_hover）+ 次级文字色
    首字母，颜色按需读 COLORS（随主题刷新）。
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # Round background
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(COLORS.get("bg_hover", "#F0F1F3")))
    p.drawRoundedRect(0, 0, size, size, size * 0.18, size * 0.18)
    # First letter
    letter = title[0].upper() if title else "?"
    f = QFont("Microsoft YaHei", size // 2, QFont.Bold)
    p.setFont(f)
    p.setPen(QColor(COLORS.get("text_sub", "#6B7280")))
    p.drawText(pm.rect(), Qt.AlignCenter, letter)
    p.end()
    return pm


# 版本类型 → 标签色 token 名。round-99：原 TYPE_COLOR 字典在导入时就把
# COLORS 值快照写死（切主题不刷新），april 还硬编码品牌粉 #DB2777（最刺眼
# 的硬编码，并入中性）。改为按需读 token，随主题刷新。
_TYPE_TOKEN = {
    "release": "success", "snapshot": "warn",
    "april": "text_sub",
    "old_beta": "text_sub", "old_alpha": "text_sub",
}


def _type_color(type_key: str) -> str:
    """版本类型 → 标签文字色（实时读 COLORS）。"""
    return COLORS.get(_TYPE_TOKEN.get(type_key, "text_sub"),
                      COLORS.get("text_sub", "#6B7280"))


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
        self._workers: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        # 对照模板 Versions.svg：过滤标签用 pill（激活=紫 / 非激活=白卡），
        # 替代下拉框，一眼看到所有版本分类。复用 ui_kit.ChipGroup，
        # 激活态由 QSS ``:checked`` 驱动，无需手动描样式。
        self._filter_key = "all"
        self.filter = ui_kit.ChipGroup(
            [("all", t("versions.filter_all")),
             ("release", t("versions.filter_release")),
             ("snapshot", t("versions.filter_snapshot")),
             ("april", t("versions.filter_april")),
             ("legacy", t("versions.filter_legacy"))],
            on_change=self._on_filter_pill, spacing=6, min_h=32)
        self.filter.set("all")

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("versions.filter_placeholder"))
        self.search.setMinimumHeight(36)
        # round-52 自适应：search 用 stretch 弹性伸展而非固定 180 最小宽度，
        # 窄窗口下 header 不溢出（filter 保持固定宽度）。
        self.search.setMinimumWidth(0)
        self.search.textChanged.connect(self._apply_filter)

        self.refresh_btn = ui_kit.make_button(
            t("versions.refresh"), icon_key="refresh",
            on_click=self._load, min_h=36)

        self._header = ui_kit.page_header(
            t("versions.title"), action=self.refresh_btn, icon_key="versions")
        self.title_lbl = self._header.title_lbl
        root.addWidget(self._header)

        # 过滤 pill 单独一行（对照 Versions.svg）。放独立行而非塞进 header，
        # 避免窄窗口下 5 个 pill + 搜索 + 刷新挤在一行溢出（round-52 约束）。
        fil_row = QHBoxLayout()
        fil_row.setSpacing(10)
        fil_row.addWidget(self.filter)
        fil_row.addStretch(1)
        self.search.setMaximumWidth(320)
        fil_row.addWidget(self.search, stretch=1)
        root.addLayout(fil_row)

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
        old = getattr(self, "_worker", None)
        if old is not None and old.isRunning():
            self._workers.append(old)
        worker = Worker(fetch_versions)
        self._worker = worker

        def _on_fin(data):
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            if gen == self._load_gen:
                self._on_loaded(data)

        def _on_err(e):
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            if gen == self._load_gen:
                self.status.setText(t("versions.error", e=e))

        worker.finished.connect(_on_fin)
        worker.error.connect(_on_err)
        worker.start()

    def _on_loaded(self, data):
        _, versions = data
        self._versions = versions
        self.status.setText(t("versions.count", n=len(versions)))
        self._apply_filter()

    def _fmt_date(self, rt: str) -> str:
        return rt[:10] if rt else ""

    def _on_filter_pill(self, key: str) -> None:
        """Pill filter clicked (round-53: combo 下拉框 → pill 标签栏)."""
        self._filter_key = key
        self._apply_filter()

    def _apply_filter(self):
        q = self.search.text().strip().lower()
        only_group = self._filter_key
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
            # group header
            hdr = QLabel(t(f"versions.group.{g}"))
            hdr.setProperty("cls", "group")
            self._vbox.addWidget(hdr)
            for v in members:
                self._vbox.addWidget(self._fade(self._make_card(v, v["id"] in installed)))
        self._vbox.addStretch(1)

    @staticmethod
    def _fade(w):
        """round-107：列表卡片淡入动画（效果总开关关闭时静默跳过）。"""
        fade_in_widget(w)
        return w

    def _make_card(self, v: dict, is_installed: bool) -> QFrame:
        # round-50 版本列表流光：低强度慢速，视觉整洁
        card = LightTrailCard(radius=12, strength=0.4, speed=0.55)
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
            tag_color = _type_color("april")
        else:
            tag_text = version_type_name(v["type"])
            tag_color = _type_color(v["type"])
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
        对齐主流做法的"选版本 → 选加载器 → 安装"流程。"""
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
        # Rebuild filter chip labels in place — self.filter is a
        # ui_kit.ChipGroup (not a QComboBox), so plain label updates via
        # set_text() keep the current selection while following the new
        # i18n strings (round-64 fix: previous code called currentData()/
        # addItem()/findData(), which ChipGroup doesn't have → AttributeError
        # on every save / language switch once the versions page was built).
        for key, lbl in [
            ("all", t("versions.filter_all")),
            ("release", t("versions.filter_release")),
            ("snapshot", t("versions.filter_snapshot")),
            ("april", t("versions.filter_april")),
            ("legacy", t("versions.filter_legacy")),
        ]:
            self.filter.set_text(key, lbl)


# ---------------------------------------------------------------- Store
# 下载目标子目录（按 Modrinth project_type 映射到实例内目录）
_TYPE_SUBDIR = {
    "mod":          "mods",
    "shader":       "shaderpacks",
    "resourcepack": "resourcepacks",
    "datapack":     "datapacks",
}


class StorePage(QWidget):
    # round-107 版本库入口已从侧栏移除 → 资源中心页头提供「版本库」按钮跳转。
    open_versions_requested = Signal()

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
        # Keep in-flight workers referenced until they finish. Overwriting
        # self._worker used to drop the only strong ref to a still-running
        # QThread, so Python GC deleted it mid-flight →
        # "QThread destroyed while still running" crash on fast category
        # switching (resource center). See _track().
        self._workers: list = []
        # Debounce: rapid category/source clicks collapse into one fetch.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._search)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        # 第一行：标题 + 目标实例 + 源切换（round-104：目标实例上移到页头，
        # 搜索行只留搜索框——「搜索」按钮被搜索框吃掉）
        self.source_combo = QComboBox()
        self.source_combo.setMinimumHeight(36)
        self.source_combo.setMinimumWidth(120)
        self.source_combo.addItem(t("store.source_modrinth"), "modrinth")
        self.source_combo.addItem(t("store.source_curseforge"), "curseforge")
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)

        target_w = QWidget()
        tw = QHBoxLayout(target_w)
        tw.setContentsMargins(0, 0, 0, 0)
        tw.setSpacing(8)
        self.target_lbl = QLabel(t("store.target_label"))
        self.target_lbl.setProperty("cls", "sub")
        tw.addWidget(self.target_lbl)
        self.inst_combo = QComboBox()
        self.inst_combo.setMinimumHeight(32)
        self.inst_combo.setMinimumWidth(160)
        self.inst_combo.currentIndexChanged.connect(self._on_target_changed)
        tw.addWidget(self.inst_combo)

        ver_btn = QPushButton(t("nav.versions"))
        ver_btn.setMinimumHeight(34)
        ver_btn.setCursor(Qt.PointingHandCursor)
        ver_btn.setToolTip(t("versions.title"))
        ver_btn.clicked.connect(lambda: self.open_versions_requested.emit())
        self._header = ui_kit.page_header(
            t("store.title"), action=[target_w, self.source_combo, ver_btn], icon_key="store")
        self.title_lbl = self._header.title_lbl
        root.addWidget(self._header)

        # 第二行：分类标签栏（像主流下载页一样横向排开，一眼看到所有类型）
        # 复用 ui_kit.ChipGroup，激活态纯 QSS 驱动。
        self.category_chips = ui_kit.ChipGroup(
            [(pt, t(key)) for pt, key in STORE_CATEGORIES],
            on_change=self._set_category, spacing=8, min_h=34)
        self._cat_btns = self.category_chips.buttons
        self._cat_row = QHBoxLayout()
        self._cat_row.setSpacing(8)
        self._cat_row.addStretch(1)
        self._cat_row.addWidget(self.category_chips)
        self._cat_row.addStretch(1)
        root.addLayout(self._cat_row)

        # 第三行：搜索框（无独立按钮——输入即防抖搜索，Enter 立即搜索）
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("store.search_placeholder"))
        self.search.setMinimumHeight(34)
        self.search.textChanged.connect(lambda _=None: self._search_timer.start())
        self.search.returnPressed.connect(self._search_timer.start)
        root.addWidget(self.search)

        self.status = QLabel(t("store.loading"))
        self.status.setProperty("cls", "sub")
        root.addWidget(self.status)

        # round-111：整合包下载的字节级进度 + 实时速度（与启动/下载对话框同一
        # slim 进度条范式）。平时隐藏，只在下载整合包时出现。
        self._dl_bar = QProgressBar()
        self._dl_bar.setProperty("cls", "slim")
        self._dl_bar.setTextVisible(False)
        self._dl_bar.setFixedHeight(8)
        self._dl_bar.setVisible(False)
        root.addWidget(self._dl_bar)
        self._dl_speed = QLabel("")
        self._dl_speed.setProperty("cls", "sub")
        self._dl_speed.setVisible(False)
        root.addWidget(self._dl_speed)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self._load_gen = 0  # guards against stale search results
        self._loading_more = False  # 防止滚动到底部时连续触发多次
        self._content = QWidget()
        self._vbox = QVBoxLayout(self._content)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(10)
        self.scroll.setWidget(self._content)
        root.addWidget(self.scroll, stretch=1)

        # 滚动到底自动加载下一页（round-107：移除手动「加载更多」按钮——
        # 之前那个按钮被 setVisible(False) 隐藏却仍留着，属冗余 UI）
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # 默认选中第一个分类
        self._set_category("mod", initial=True)
        QTimer.singleShot(0, self._sync_target)
        self._search()

    # ---- category selection ----
    def _set_category(self, category: str, initial: bool = False):
        """Switch the visible resource category. Active pill is painted by the
        ``chip:checked`` QSS via ChipGroup, so no manual styling here."""
        self._category = category
        self.category_chips.set(category)
        if not initial:
            self._search_timer.start()

    def _on_source_changed(self, _index: int):
        """切换源时同步搜索框提示与状态栏文案。

        CurseForge 有三态：配置了 key → 官方 API 关键词搜索；没 key 但开了
        免 key 通道 → 只能输入精确 slug / 完整链接解析；两者都没有 → 提示
        去设置里填 key（公开发布版默认走这条，不捆绑 key）。
        """
        self._source = self.source_combo.currentData()
        if self._source == "curseforge":
            from .net_api import curseforge_available, curseforge_keyless_enabled
            if curseforge_available():
                self.search.setPlaceholderText(t("store.search_placeholder"))
                self.status.setText(t("store.cf_hint_key"))
            elif curseforge_keyless_enabled():
                self.search.setPlaceholderText(t("store.cf_link_placeholder"))
                self.status.setText(t("store.cf_hint"))
            else:
                self.search.setPlaceholderText(t("store.cf_link_placeholder"))
                self.status.setText(t("store.cf_no_key"))
        else:
            self.search.setPlaceholderText(t("store.search_placeholder"))
        self._search_timer.start()

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
        self._loading_more = False
        # Invalidate any in-flight icon loads — the list is about to be wiped,
        # so stale replies must not touch widgets that are being deleted.
        self._img.bump()
        self._load(reset=True)

    def _track(self, worker, gen, reset):
        """Start `worker`, keeping the previously-running worker referenced until
        it finishes so Python GC cannot delete a still-running QThread (which
        used to crash the app on fast category switching)."""
        old = getattr(self, "_worker", None)
        if old is not None and old is not worker and old.isRunning():
            self._workers.append(old)
        self._worker = worker

        def _on_fin(m):
            self._retire(worker)
            if gen == self._load_gen:
                self._on_loaded(m, reset)

        def _on_err(e):
            self._retire(worker)
            if gen == self._load_gen:
                self.status.setText(t("store.error", e=e))
                self._loading_more = False

        worker.finished.connect(_on_fin)
        worker.error.connect(_on_err)
        worker.start()

    def _retire(self, worker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    def _on_scroll(self, value: int):
        """Auto-load next page when the user scrolls near the bottom."""
        if self._loading_more:
            return
        vbar = self.scroll.verticalScrollBar()
        if vbar.maximum() <= 0:
            return
        # 提前 120px 触发，避免到底才加载的顿挫感
        if value >= vbar.maximum() - 120:
            self._more()

    def _more(self):
        if self._loading_more:
            return
        self._loading_more = True
        self._offset += 20
        self._load(reset=False)

    def _load(self, reset: bool):
        if self._source == "curseforge":
            self._load_curseforge(reset)
            return
        self.status.setText(t("store.fetching"))
        self._load_gen += 1
        gen = self._load_gen
        worker = Worker(search_mods, self._query, self._offset,
                        project_type=self._category)
        self._track(worker, gen, reset)

    def _load_curseforge(self, reset: bool):
        """CurseForge 源：有 key → 官方 API；无 key 且开启免 key 通道 → slug/链接解析。

        两者都没有时明确提示去设置里填 key —— 公开发布版默认走官方 API，
        不默认绕过作者的分发授权（cfwidget + forgecdn 直链只能自用兜底）。
        """
        from .net_api import curseforge_available, curseforge_keyless_enabled
        if curseforge_available():
            from .net_api import search_curseforge
            worker_fn = search_curseforge
        elif curseforge_keyless_enabled():
            from .net_api import curseforge_link_search
            worker_fn = curseforge_link_search
        else:
            self._on_loaded([], reset)
            self.status.setText(t("store.cf_no_key"))
            return
        self._load_gen += 1
        gen = self._load_gen
        worker = Worker(worker_fn, self._query)
        self._track(worker, gen, reset)

    def _on_loaded(self, mods: list[dict], reset: bool):
        self._loading_more = False
        self._mods = mods if reset else self._mods + mods
        if reset:
            while self._vbox.count():
                item = self._vbox.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self.status.setText(t("store.results", n=len(self._mods)))
        for m in mods:
            card = self._make_card(m)
            self._vbox.addWidget(card)
            # round-107：加载更多时新卡片逐条淡入（整页重置仍走 viewport 整体淡入）
            if not reset:
                fade_in_widget(card)
        # round-100 列表淡入（克制）：只在整页重置时淡入，加载更多不闪整屏
        if reset and mods:
            fade_in_widget(self.scroll.viewport())
        # 策略变更：结果一到就把每个资源的「详情页 72px 封面」预取进缓存，
        # 不必等用户点进详情才开始下载（详情页 StoreDetailDialog 用的正是 72
        # 尺寸）。失败静默——详情页仍会按需加载，不会因此空白。
        for m in mods:
            self._img.prefetch(m.get("icon_url", ""), 72)

    def _make_card(self, m: dict) -> QFrame:
        # round-50 商店卡流光：低强度慢速，视觉整洁
        card = LightTrailCard(radius=12, strength=0.4, speed=0.55)
        card.setMinimumHeight(84)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(14)

        thumb = QLabel()
        thumb.setFixedSize(48, 48)
        # 使用首字母彩色图标作为 fallback（主流风格），比通用 store 图标更有辨识度
        fallback = _letter_fallback(m["title"], 48)
        self._img.load(m.get("icon_url", ""), 48, thumb, fallback)
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
                cf=m.get("_cf_file"):
                self._download(pid, pslug, cf_file=cf)
            )
        dl.setMinimumHeight(34)
        dl.setIcon(icon("download"))
        dl.setIconSize(QSize(16, 16))
        lay.addWidget(dl)

        # round-66：modrinth 源卡片点击 → 详情页（全部版本 / 翻译 / 按版本下载）。
        # 下载/安装按钮会消费鼠标事件，不会误触卡片的点击打开。
        if self._source == "modrinth":
            card.setCursor(Qt.PointingHandCursor)
            card.mousePressEvent = lambda _e, m=m: self._open_detail(m)
        return card

    def _open_detail(self, m: dict):
        """打开资源详情页：列出全部版本（可按 MC 版本过滤）、获取中文翻译、
        选择任意版本下载到目标实例对应子目录。"""
        inst = self._target()
        if inst is None:
            info(self, t("common.hint"), t("store.download_hint"))
            return
        dlg = StoreDetailDialog(
            self, m, self._category, inst,
            _TYPE_SUBDIR.get(self._category, "mods"))
        dlg.exec()

    def _download(self, project_id: str, slug: str, cf_file: dict | None = None):
        inst = self._target()
        if inst is None:
            toast(self, t("common.hint"), t("store.download_hint"))
            return
        reply = confirm(
            self, t("store.download_confirm_title"),
            t("store.download_confirm", slug=slug, name=inst.name),
        )
        if reply != True:
            return
        self.status.setText(t("store.downloading", slug=slug))
        sub = _TYPE_SUBDIR.get(self._category, "mods")
        # round-57 修：隔离/自定义目录下游戏真实的 mods/shaders/resourcepacks
        # 在 <game_dir>/<sub>，之前固定 inst.mc_dir 会让下载的模组游戏里不生效。
        dest = os.path.join(inst.game_dir, sub)
        # round-111：改用 ProgressWorker（裸 Worker 没有 callback/速度），
        # 复用整合包那条 slim 进度条 + 速度标签。
        if self._source == "curseforge":
            from .net_api import download_cfwidget_file, download_curseforge_mod
            if cf_file:
                # 免 key 通道解析出的文件（含 id/name）→ forgecdn 直链
                self._dworker = ProgressWorker(download_cfwidget_file,
                                               cf_file, dest)
            else:
                # 官方 API 搜索命中只有 project_id → 走官方下载接口
                self._dworker = ProgressWorker(download_curseforge_mod,
                                               project_id, dest)
        else:
            # round-37：传入实例的 MC 版本 + 加载器，让 Modrinth 过滤兼容版本
            # 并自动拉取 required 依赖树（download_mod_to 已支持依赖解析）
            self._dworker = ProgressWorker(
                download_mod_to, project_id, dest,
                getattr(inst, "game_version", "") or "",
                getattr(inst, "loader", "") or "",
            )
        self._dworker.progress.connect(self._on_pack_progress)
        self._dworker.speed.connect(self._on_pack_speed)
        self._dworker.finished.connect(self._on_mod_downloaded)
        self._dworker.error.connect(self._on_pack_error)
        self._dl_bar.setVisible(True)
        self._dl_bar.setRange(0, 0)          # 依赖树文件数未知 → 忙指示
        self._dl_speed.setVisible(True)
        self._dl_speed.setText("")
        self._dworker.start()

    def _on_mod_downloaded(self, p):
        self._dl_bar.setVisible(False)
        self._dl_speed.setVisible(False)
        self.status.setText(t("store.downloaded", file=os.path.basename(p)))

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
        # round-111：改用 ProgressWorker（而非裸 Worker）——它会注入 mll 风格
        # callback，经 net_api.download_modpack_to 桥接成字节级进度 + 实时速度。
        self._pworker = ProgressWorker(download_modpack_to, project_id,
                                       cache_dir)
        self._pworker.progress.connect(self._on_pack_progress)
        self._pworker.speed.connect(self._on_pack_speed)
        self._pworker.finished.connect(self._on_pack_downloaded)
        self._pworker.error.connect(self._on_pack_error)
        self._dl_bar.setVisible(True)
        self._dl_bar.setRange(0, 0)          # 未知总量 → 忙指示
        self._dl_speed.setVisible(True)
        self._dl_speed.setText("")
        self._pworker.start()

    def _on_pack_progress(self, value: int, maximum: int):
        """整合包下载进度：maximum <= 0 表示总量未知（忙指示）。"""
        if maximum and maximum > 0:
            self._dl_bar.setRange(0, maximum)
            self._dl_bar.setValue(value)
        else:
            self._dl_bar.setRange(0, 0)

    def _on_pack_speed(self, text: str):
        self._dl_speed.setText(text)

    def _on_pack_downloaded(self, path: str):
        self._dl_bar.setVisible(False)
        self._dl_speed.setVisible(False)
        from .pages_instances import _MrpackDialog
        from .modpack_import import _parse_mrpack_info
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

    def _on_pack_error(self, e):
        self._dl_bar.setVisible(False)
        self._dl_speed.setVisible(False)
        self.status.setText(t("store.download_fail", e=e))

    def retranslate_ui(self):
        self.title_lbl.setText(t("store.title"))
        self.target_lbl.setText(t("store.target_label"))
        self.search.setPlaceholderText(t("store.search_placeholder"))
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
        # rebuild category tab labels
        for pt, key in STORE_CATEGORIES:
            if pt in self._cat_btns:
                self._cat_btns[pt].setText(t(key))
        self._sync_target()
