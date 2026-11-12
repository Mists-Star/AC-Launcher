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
    QScrollArea, QLineEdit, QComboBox, QDialog, QProgressBar, QStackedWidget,
    QSplitter,
)
from PySide6.QtCore import Signal, QSize, QTimer, Qt
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QFontMetrics

from .theme import COLORS, with_alpha
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
from .async_image import get_image_loader, make_version_pixmap
from .store_detail import StoreDetailPanel  # round-66 资源详情；round-132 页内面板
from . import net_api as _na
from .store_filter import StoreFilterPanel  # round-208 筛选侧栏
from .store_search import (  # round-208 服务端过滤 / 双源游标 / 真分页
    STORE_PAGE_SIZE, cache_lookup, filters_key, search_store_page,
)


# ── 首帧骨架屏（round-124）─────────────────────────────────────────────
# 版本库 / 资源中心首次进入要等 0.6–1.2s 的网络往返，此前整页只有一行
# 「正在获取…」，观感像卡死。先铺几行静态骨架占位，数据到达后整页清空重绘。
def _skeleton_row(row_h: int = 56) -> QWidget:
    w = QWidget()
    w.setFixedHeight(row_h)
    w.setProperty("skeleton", True)
    w.setStyleSheet(f"background:{COLORS['bg_input']}; border-radius:10px;")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(12)
    tile = QWidget()
    tile.setFixedSize(32, 32)
    tile.setStyleSheet(
        f"background:{with_alpha(COLORS['border'], 0x80)}; border-radius:8px;")
    lay.addWidget(tile)
    bars = QVBoxLayout()
    bars.setSpacing(6)
    for width in (220, 120):
        bar = QWidget()
        bar.setFixedSize(width, 10)
        bar.setStyleSheet(
            f"background:{with_alpha(COLORS['border'], 0x80)}; border-radius:5px;")
        bars.addWidget(bar, 0, Qt.AlignLeft)
    lay.addLayout(bars, stretch=1)
    return w


def _clear_skeleton(layout) -> None:
    """Remove any skeleton rows still in ``layout`` (error paths)."""
    for i in reversed(range(layout.count())):
        w = layout.itemAt(i).widget()
        if w is not None and w.property("skeleton"):
            layout.takeAt(i)
            w.deleteLater()


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
        self._img = get_image_loader()
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

        # round-124：首帧骨架屏（首次加载 0.6s 内不再是一片空白）
        for _ in range(6):
            self._vbox.addWidget(_skeleton_row(56))
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
                _clear_skeleton(self._vbox)
                self.status.setText(t("versions.error", e=e))

        worker.finished.connect(_on_fin)
        worker.error.connect(_on_err)
        worker.start()

    def _on_loaded(self, data):
        _, versions = data
        self._versions = versions
        self.status.setText(t("versions.count", n=len(versions)))
        # round-141 性能：数据到达才重建卡片（含淡入）；此后 pill/搜索
        # 过滤只走 _apply_filter 的显隐切换。
        self._rebuild()
        self._apply_filter()

    def _fmt_date(self, rt: str) -> str:
        return rt[:10] if rt else ""

    def _on_filter_pill(self, key: str) -> None:
        """Pill filter clicked (round-53: combo 下拉框 → pill 标签栏)."""
        self._filter_key = key
        self._apply_filter()

    def _rebuild(self):
        """一次性建好全部分组卡片 + 淡入（仅数据到达时调用）。

        round-141 性能：旧实现把「建卡」和「过滤」耦在 _apply_filter 里，
        每次点分类 pill 都整列 tear-down 重建 —— 上百张 LightTrailCard 同时
        销毁/创建 + 上百个 170ms 淡入动画同跑 + QSS 重新 polish，切换明显
        卡顿。现在 pill/搜索只翻显隐，重建只发生在数据刷新。
        """
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards: list[tuple] = []    # (widget, group, id_lower)
        self._headers: list[tuple] = []  # (widget, group)
        installed = {i.game_version for i in self.mgr.list()}
        for g in _GROUP_ORDER:
            members = [v for v in self._versions if _group_of(v) == g]
            if not members:
                continue
            hdr = ui_kit.group_label(t(f"versions.group.{g}"))
            self._vbox.addWidget(self._fade(hdr))
            self._headers.append((hdr, g))
            for v in members:
                card = self._fade(self._make_card(v, v["id"] in installed))
                self._vbox.addWidget(card)
                self._cards.append((card, g, v["id"].lower()))
        self._vbox.addStretch(1)

    def _apply_filter(self):
        """分类 pill / 搜索框过滤 = 纯显隐切换（不再重建，见 _rebuild）。"""
        q = self.search.text().strip().lower()
        only_group = self._filter_key
        counts: dict[str, int] = {}
        for w, g, vid in getattr(self, "_cards", []):
            show = (only_group == "all" or g == only_group) and (
                not q or q in vid)
            if show:
                counts[g] = counts.get(g, 0) + 1
            w.setVisible(show)
        for w, g in getattr(self, "_headers", []):
            w.setVisible(counts.get(g, 0) > 0)

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
        # round-129：把当前页面的 DPR 传进去，图标按实际显示屏幕的超采样
        # 渲染（默认读主屏 DPR，多屏不同缩放时会拿错尺寸）。
        tile.setPixmap(make_version_pixmap(
            v["id"], "april" if v.get("april") else v["type"], 56,
            self.devicePixelRatioF()))
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
        name, version, loader, java_path, ldver, fmt, base = dlg.result_data()
        inst = self.mgr.add(name, version, loader, loader_version=ldver,
                            java_path=java_path, format=fmt, base=base)
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
    # round-207：搜索按源回调。search_all 的 daemon 线程直接 emit，Qt 自动
    # queued 到主线程 → 快源一到就渲染，不必等另一源 / 等满 8s 预算。
    sourcePartial = Signal(str, object, int)

    def __init__(self, list_instances, get_current_instance, parent=None):
        super().__init__(parent)
        self.list_instances = list_instances
        self.get_current = get_current_instance
        # round-142b 修（crash.log 18:43）：CF 整合包装完要在本页 set_current，
        # 但 StorePage 此前没有 mgr —— 回调里 AttributeError，Worker 根本没启动，
        # 用户看到的就是「导入一直没动静」。
        self.mgr = manager()
        self._mods: list[dict] = []
        self._query = ""
        self._category = "mod"
        # round-140：默认源 = 「全部」双源合并；对齐上游时**不**偷偷改这个决策。
        self._source = "all"
        self._img = get_image_loader()
        # Keep in-flight workers referenced until they finish. Overwriting
        # self._worker used to drop the only strong ref to a still-running
        # QThread, so Python GC deleted it mid-flight (see _track()).
        self._workers: list = []
        # round-208 §2.7：防抖 350ms，对齐 prism ResourcePage.cpp:95-105
        # （原 180ms 太急，中文输入法每敲一个字都会触发一次重搜）。
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._search)
        self.sourcePartial.connect(self._on_source_partial)
        self._partial_enabled = False
        self._partial_done_gen = -1
        # round-211：gen -> request_key，供迟到回调做 (gen, key) 联合判据。
        self._partial_keys: dict[int, str] = {}

        # round-208 §2.5/§2.6：PCL-CE 真分页状态（ProjectStorage.cs:5-22）。
        self._store_page = 0
        self._store_cursors = None
        self._store_results: list[dict] = []
        self._store_meta: dict = {}
        self._filters: dict = {}
        self._search_meta: dict = {}
        self._last_request_key = ""
        self._can_next = False
        # §2.8 视口懒加载队列 / §2.9 SWR 页面级快照（只存内存，不落大对象）
        self._icon_pending: list = []
        self._swr_cache: dict = {}
        self._swr = "miss"

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        # 主理人 2026-11-07 拍板：列表 ↔ 详情继续用 _stack 整页切换，
        # 不改成 Prism 式第三栏，也不新开窗口 / QDialog。
        self._list_view = QWidget()
        lv = QVBoxLayout(self._list_view)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(16)
        self._detail_panel = None

        # 页头：目标实例 / 筛选折叠 / 版本库。来源下拉已移到筛选侧栏
        # （§2.2：来源提升为侧栏一级控件）。
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

        self.filter_toggle_btn = QPushButton(t("store.filter_collapse"))
        self.filter_toggle_btn.setMinimumHeight(34)
        self.filter_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.filter_toggle_btn.clicked.connect(self._toggle_filter)

        ver_btn = QPushButton(t("nav.versions"))
        ver_btn.setMinimumHeight(34)
        ver_btn.setCursor(Qt.PointingHandCursor)
        ver_btn.setToolTip(t("versions.title"))
        ver_btn.clicked.connect(lambda: self.open_versions_requested.emit())
        self._header = ui_kit.page_header(
            t("store.title"),
            action=[target_w, self.filter_toggle_btn, ver_btn], icon_key="store")
        self.title_lbl = self._header.title_lbl
        lv.addWidget(self._header)

        # round-208 §2.1：QSplitter 两栏 = 筛选侧栏 / 结果区。
        # 依据 prism:ResourcePage.ui:29-62（三栏）与 ModPage.cpp:103-128
        # （replaceWidget 注入 + 可折叠 filterWidget）；拍板后第三格详情
        # 不在 splitter 内，故 count()==2。
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.filter_panel = StoreFilterPanel()
        self.filter_panel.filterChanged.connect(self._on_filters_changed)
        # 兼容 _update_search_placeholder / retranslate_ui 里对来源的既有引用
        self.source_combo = self.filter_panel.source_combo
        self.splitter.addWidget(self.filter_panel)

        results_host = QWidget()
        rv = QVBoxLayout(results_host)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(12)

        self.category_chips = ui_kit.ChipGroup(
            [(pt, t(key)) for pt, key in STORE_CATEGORIES],
            on_change=self._set_category, spacing=8, min_h=34)
        self._cat_btns = self.category_chips.buttons
        self._cat_row = QHBoxLayout()
        self._cat_row.setSpacing(8)
        self._cat_row.addStretch(1)
        self._cat_row.addWidget(self.category_chips)
        self._cat_row.addStretch(1)
        rv.addLayout(self._cat_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("store.search_placeholder"))
        self.search.setMinimumHeight(34)
        self.search.textChanged.connect(lambda _=None: self._search_timer.start())
        self.search.returnPressed.connect(self._search_timer.start)
        rv.addWidget(self.search)

        self.status = QLabel(t("store.loading"))
        self.status.setProperty("cls", "sub")
        rv.addWidget(self.status)

        self._dl_bar = QProgressBar()
        self._dl_bar.setProperty("cls", "slim")
        self._dl_bar.setTextVisible(False)
        self._dl_bar.setFixedHeight(8)
        self._dl_bar.setVisible(False)
        rv.addWidget(self._dl_bar)
        self._dl_speed = QLabel("")
        self._dl_speed.setProperty("cls", "sub")
        self._dl_speed.setVisible(False)
        rv.addWidget(self._dl_speed)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        # round-218：结果区**永远不出横向滑块**（主理人明确要求）。配合
        # ElidedLabel，内容宽度恒等于视口宽度；这行是最后一道闸。
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._load_gen = 0  # guards against stale search results
        self._content = QWidget()
        self._vbox = QVBoxLayout(self._content)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(10)
        self.scroll.setWidget(self._content)
        # round-208：滚动只驱动「视口内图标懒加载」，不再触发无限翻页。
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        rv.addWidget(self.scroll, stretch=1)

        self._pager = self._build_pager()
        rv.addWidget(self._pager)

        self.splitter.addWidget(results_host)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        lv.addWidget(self.splitter, stretch=1)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._list_view)
        root.addWidget(self._stack, stretch=1)

        for _ in range(6):
            self._vbox.addWidget(_skeleton_row(64))

        self._set_category("mod", initial=True)
        self._sync_target()
        self._search()

    # ---- category selection ----
    # ia[store]: 点分类胶囊 | 资源中心分类栏 | 切换资源类型并回到第 1 页重新搜索
    def _set_category(self, category: str, initial: bool = False):
        """Switch the visible resource category. Active pill is painted by the
        ``chip:checked`` QSS via ChipGroup, so no manual styling here."""
        self._category = category
        self.category_chips.set(category)
        self._update_search_placeholder()
        if not initial:
            self._search_timer.start()

    def _update_search_placeholder(self):
        """Search hint follows the selected category (round-125).

        It used to be the literal "搜索模组…" on every tab, so the 整合包 /
        光影 / 资源包 / 数据包 pages all claimed to search mods.
        """
        if self._source == "curseforge":
            from .net_api import curseforge_available, curseforge_keyless_enabled
            # 免 key 镜像支持关键词搜索 → 关键词 placeholder；只有「无 key 且
            # 关掉免 key 通道」时才退回到 slug/链接精确匹配的提示。
            if not curseforge_available() and not curseforge_keyless_enabled():
                self.search.setPlaceholderText(t("store.cf_link_placeholder"))
                return
        self.search.setPlaceholderText(t("store.search_ph_" + self._category))

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
        """目标实例变了 → 更新侧栏提示与详情页推荐口径，防抖后重搜。

        round-209：搜索范围不再随目标实例隐式收窄，但卡片兼容性徽章 /
        详情页推荐版本仍按实例计算，因此切换实例仍需刷新列表。
        """
        self.filter_panel.set_target(self._target())
        self._search_timer.start()

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
        self.filter_panel.set_target(self._target())

    # ---- round-208：筛选 / 防抖去重 / 真分页 / SWR ----
    def _collect_filters(self) -> dict:
        """只收集玩家在侧栏显式选择的筛选（round-209）。

        上游 prism:ModFilterWidget.ui:198-224 与 pclce:PageComp.xaml:33-106
        的版本 / 加载器都是玩家在控件里**显式选**的，从不在玩家没选时按当前
        实例偷偷收窄。round-208 曾自动把目标实例的 MC 版本与加载器下推服务端，
        联网实测把 CF「FTB」从 409 条砍到 58 条（-86%）、「FTB Quests」从
        140 砍到 27 条，FTB 官方 Forge/NeoForge 版本整批消失，且 can_next
        变 False 直接翻不到底 —— 这是主理人报的「一部分 mod 搜不到」主因。

        版本 / 加载器仍然参与详情页推荐版本与卡片兼容性徽章，只是不再静默
        改变搜索范围；玩家想按当前实例筛，在侧栏选版本 / 加载器即可。
        """
        f = dict(self.filter_panel.get_filter())
        self._filters = f
        return f

    # ia[store]: 改筛选侧栏（来源/排序/版本/加载器/分类/隐藏已装） | 筛选侧栏 | 350ms 防抖后按服务端参数重搜
    def _on_filters_changed(self):
        self._store_page = 0
        self._store_cursors = None
        self._store_results = []
        self._search_timer.start()

    # ia[store]: 点「显示/收起筛选」 | 资源中心页头 | 折叠或展开筛选侧栏，不重建结果
    def _toggle_filter(self):
        visible = not self.filter_panel.isVisible()
        self.filter_panel.setVisible(visible)
        self.filter_toggle_btn.setText(
            t("store.filter_collapse") if visible else t("store.filter_expand"))

    def _swr_key(self) -> str:
        return "r208-page:%s:%s:%s:%d" % (
            self._query, self._category, filters_key(self._filters),
            self._store_page)

    def _swr_snapshot(self):
        """§2.9 stale-while-revalidate：三态由 net_api TTL 判定，页面数据
        只留内存快照（不把 40 条结果写进磁盘缓存）。"""
        state, _sig = cache_lookup(self._swr_key())
        return state, self._swr_cache.get(self._swr_key())

    def _store_swr(self, data: dict):
        key = self._swr_key()
        self._swr_cache[key] = data
        try:
            _na._store(key, {"n": len(data.get("results") or [])})
        except Exception:  # noqa: BLE001 - 缓存失败不影响展示
            pass

    def _request_key(self) -> str:
        """§2.7 请求去重：关键词 / 分类 / 页码 / 全部筛选 / 隐藏已装都进 key。"""
        f = self._filters
        return "%s|%s|%d|%s|%s" % (
            self._query, self._category, self._store_page,
            filters_key(f), "1" if f.get("hide_installed") else "0")

    # ia[store]: 输入关键词并回车 | 资源中心搜索框 | 350ms 防抖后重搜，页码归零、旧结果不回灌
    def _search(self):
        """新关键词 / 新筛选 / 换目标实例 → 回到第 1 页并重新武装。"""
        self._query = self.search.text().strip()
        self._store_page = 0
        self._store_cursors = None
        self._store_results = []
        self._filters = self._collect_filters()
        self._source = self._filters.get("source", "all")
        self._update_search_placeholder()
        self._img.bump()
        self._icon_pending = []
        self._last_request_key = ""
        self._load(reset=True)

    def _track(self, worker, gen, reset):
        """Start `worker`, keeping the previously-running worker referenced until
        it finishes so Python GC cannot delete a still-running QThread."""
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
                if reset:
                    _clear_skeleton(self._vbox)
                # §2.9：刷新失败但已有旧数据 → 保留列表，只提示。
                if self._swr == "stale" and self._mods:
                    self.status.setText(t("store.swr_keep_old"))
                else:
                    self.status.setText(t("store.error", e=e))

        worker.finished.connect(_on_fin)
        worker.error.connect(_on_err)
        worker.start()

    def _retire(self, worker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    def _on_scroll(self, _value: int):
        """§2.8：滚动只泵「进入视口的图标」，不再自动翻页。"""
        self._pump_icons()

    # ia[store]: 滚动结果列表 | 资源中心结果区 | 只加载进入视口的图标，占位图先上屏
    def _pump_icons(self):
        if not self._icon_pending:
            return
        vh = self.scroll.viewport().height()
        rest = []
        for url, size, target, fallback in self._icon_pending:
            try:
                y = target.mapTo(self.scroll.viewport(),
                                 target.rect().topLeft()).y()
            except RuntimeError:
                continue  # 卡片已被 deleteLater
            if -120 <= y <= vh + 240:
                self._img.load(url, size, target, fallback)
                if url:
                    self._img.prefetch(url, 72)  # 详情页 72px 封面共用原图
            else:
                rest.append((url, size, target, fallback))
        self._icon_pending = rest

    def _build_pager(self) -> QWidget:
        """§2.6：PCL-CE 真页码器（PageComp.xaml:160 / ViewModel.cs:55-69）。"""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.page_first_btn = QPushButton(t("store.page_first"))
        self.page_prev_btn = QPushButton(t("store.page_prev"))
        self.page_label = QLabel(t("store.page_label", page=1))
        self.page_label.setProperty("cls", "sub")
        self.page_next_btn = QPushButton(t("store.page_next"))
        for b in (self.page_first_btn, self.page_prev_btn, self.page_next_btn):
            b.setMinimumHeight(32)
            b.setCursor(Qt.PointingHandCursor)
        self.page_first_btn.clicked.connect(self._goto_first)
        self.page_prev_btn.clicked.connect(lambda: self._goto_page(-1))
        self.page_next_btn.clicked.connect(lambda: self._goto_page(1))
        h.addStretch(1)
        for wdg in (self.page_first_btn, self.page_prev_btn,
                    self.page_label, self.page_next_btn):
            h.addWidget(wdg)
        h.addStretch(1)
        self.page_prev_btn.setEnabled(False)
        self.page_first_btn.setEnabled(False)
        self.page_next_btn.setEnabled(False)
        return w

    # ia[store]: 点「上一页 / 下一页 / 回到首页」 | 资源中心页码器 | 按双源 offset/total 游标切片，结果已缓存则零请求
    def _goto_page(self, delta: int):
        page = self._store_page + delta
        if page < 0 or (delta > 0 and not self._can_next):
            return
        self._store_page = page
        self.scroll.verticalScrollBar().setValue(0)
        self._img.bump()
        self._icon_pending = []
        self._load(reset=True)

    def _goto_first(self):
        if self._store_page == 0:
            return
        self._store_page = 0
        self._img.bump()
        self._icon_pending = []
        self._load(reset=True)

    def _update_pager(self, data: dict):
        self.page_label.setText(t("store.page_label", page=data["page"] + 1))
        self._can_next = bool(data["can_next"])
        self.page_prev_btn.setEnabled(bool(data["can_prev"]))
        self.page_first_btn.setEnabled(bool(data["can_prev"]))
        self.page_next_btn.setEnabled(self._can_next)

    def _load(self, reset: bool, force: bool = False):
        """一次搜索 = 一次分页请求；相同条件不重复发（§2.7）。"""
        f = self._collect_filters()
        self._source = f.get("source", "all")
        self._update_search_placeholder()
        key = self._request_key()
        if not force and key == self._last_request_key:
            return
        self._last_request_key = key

        # round-140 既有能力不能丢：CF 三态提示 + 粘贴链接的 slug 解析。
        if self._source == "curseforge":
            from .net_api import (curseforge_available, curseforge_keyless_enabled,
                                  curseforge_link_search)
            has_key = curseforge_available()
            if not has_key and not curseforge_keyless_enabled():
                self._on_loaded([], reset, empty_hint="cf_no_key")
                return
            if "/" in self._query and not has_key:
                self._load_gen += 1
                gen = self._load_gen
                self._track(Worker(curseforge_link_search, self._query),
                            gen, reset)
                return

        # §2.9 SWR：新鲜直接复用；过期先画旧数据再后台刷新。
        state, snap = self._swr_snapshot()
        if state == "fresh" and isinstance(snap, dict) and not force:
            self._swr = "fresh"
            # round-211：缓存命中绝不能重写 signet 时间戳。旧实现在这里走
            # _on_loaded → _store_swr → _na._store 刷 time.time()，于是
            # _cached 永远 fresh，SWR 的 stale/miss 两态在会话内不可达。
            self._on_loaded(snap, reset, cache_hit=True)
            return
        if state == "stale" and isinstance(snap, dict):
            self._swr = "stale"
            self._on_loaded(snap, reset, swr=True)

        # stale 首帧已经写了「正在更新结果…」，这一行不能再把它覆盖成
        # 「正在获取资源…」——否则先画旧数据的行为玩家完全看不见。
        if self._swr != "stale":
            self.status.setText(t("store.fetching"))
        self._load_gen += 1
        gen = self._load_gen
        meta = {}
        self._search_meta = meta
        # round-211：记录本轮请求的完整 key；迟到回调要同时匹配 gen 与 key，
        # 否则「切语言 / 切来源 / 改筛选」后旧请求的结果会补进新列表。
        self._partial_keys[gen] = key
        if len(self._partial_keys) > 16:
            for old in sorted(self._partial_keys)[:-16]:
                self._partial_keys.pop(old, None)
        # §2.6 拍板：按源渐进渲染保留，只负责「同一页内两源先后到达」的首帧。
        self._partial_enabled = bool(reset and self._source == "all"
                                     and self._store_page == 0)
        self._partial_done_gen = -1
        on_source = None
        if self._partial_enabled:
            on_source = (lambda label, hits, g=gen:
                         self.sourcePartial.emit(label, hits, g))
        worker = Worker(
            search_store_page, self._query, self._store_page,
            STORE_PAGE_SIZE, self._category, self._source, f,
            self._store_cursors, self._store_results, meta, on_source)
        self._track(worker, gen, reset)

    def _on_loaded(self, result, reset: bool, partial: bool = False,
                   swr: bool = False, empty_hint: str | None = None,
                   cache_hit: bool = False):
        """渲染入口：dict = 完整分页结果；list = 渐进首帧 / CF 链接结果。"""
        if isinstance(result, dict) and not partial:
            data = result
            self._store_cursors = data["cursors"]
            self._store_results = data["results"]
            self._store_meta = data.get("meta") or {}
            self._store_page = data["page"]
            mods = list(data["hits"])
            self._update_pager(data)
            if not swr and not cache_hit:
                self._store_swr(data)
        else:
            mods = list(result)
            if not partial:
                # CF 链接解析 / 无 key：没有分页信息，页码器全部禁用。
                for b in (self.page_first_btn, self.page_prev_btn,
                          self.page_next_btn):
                    b.setEnabled(False)
                self._can_next = False

        # §2.11：隐藏已装是客户端过滤（服务端无此字段），口径与详情页一致。
        if self._filters.get("hide_installed"):
            mods = [m for m in mods if not self._is_installed(m)]

        if not partial and not swr:
            self._swr = "fresh"
        self._mods = mods if reset else self._mods + mods
        if reset:
            while self._vbox.count():
                item = self._vbox.takeAt(0)
                wdg = item.widget()
                if wdg is not None:
                    wdg.deleteLater()
        try:
            from .net_api import has_cjk
            _zh = has_cjk(self._query)
        except Exception:  # noqa: BLE001
            _zh = False
        n_total = len(self._store_results) if self._store_results else len(self._mods)
        if partial:
            self.status.setText(t("store.partial_loading", n=len(self._mods)))
        elif empty_hint == "cf_no_key":
            self.status.setText(t("store.cf_no_key"))
        elif swr:
            self.status.setText(t("store.swr_refreshing"))
        elif not self._mods and _zh:
            self.status.setText(t("store.zh_no_hit"))
        elif not self._mods:
            self.status.setText(t("store.no_results"))
        else:
            self.status.setText(t("store.results", n=n_total))
        meta = self._search_meta or self._store_meta
        if not partial and not swr and meta.get("partial"):
            self.status.setText(t(
                "store.partial",
                sources="、".join(meta.get("timed_out") or [])))
        for m in mods:
            card = self._make_card(m)
            self._vbox.addWidget(card)
            if not reset:
                fade_in_widget(card)
        if reset and mods and not partial:
            fade_in_widget(self.scroll.viewport())
        QTimer.singleShot(0, self._pump_icons)
        if not partial:
            # 完整结果已上屏：之后迟到的源回调走去重增量补卡，不整页覆盖。
            self._partial_done_gen = self._load_gen

    def _on_source_partial(self, label: str, hits, gen: int):
        """某个源一返回就渲染（round-207）。

        信号由 search_all 的 daemon 线程 emit，Qt 自动 queued 到主线程；
        gen 守卫挡住「换了关键词之后，旧 worker 的迟到结果」污染新列表。
        """
        if not self._partial_enabled or gen != self._load_gen or not hits:
            return
        # round-211：gen 相同不代表请求相同 —— ``_load`` 在 key 未变时会提前
        # return 而不递增 gen。必须再用 request_key 校验，否则切语言 / 切来源
        # 后旧请求的慢源结果会补进新列表。
        try:
            if self._partial_keys.get(gen) != self._request_key():
                return
        except RuntimeError:
            return
        if self._partial_done_gen == gen:
            # 最终结果（或另一个源）已上屏 → 只做去重增量补卡。这样即使
            # 慢源在 8s 预算之后才回来，结果也不会被静默丢弃。
            self._append_source_rows(hits, label)
            return
        self._partial_done_gen = gen
        self._on_loaded(list(hits), True, partial=True)

    def _append_source_rows(self, hits: list[dict], label: str = ""):
        """去重后把迟到 / 后到的源结果追加到当前列表。

        round-211：补卡必须**同时写回分页结果集**。旧实现只写 ``_mods`` 和
        ``_vbox``，翻到下一页时 ``search_store_page`` 收到的 ``results`` 不含
        这批卡 → 它们凭空消失、页码器与真实数据量脱节。
        游标（cursors）刻意不在这里推进：数据层已按实际返回数推进过；超时源
        被判定「到底」是有意降级，重复推进会造成 offset 翻倍、下一页重拉。
        """
        known = {
            str(m.get("project_id") or m.get("slug") or "").lower()
            for m in self._mods
        }
        added = []
        for m in hits:
            key = str(m.get("project_id") or m.get("slug") or "").lower()
            if not key or key in known:
                continue
            known.add(key)
            added.append(m)
        if not added:
            return
        self._mods = self._mods + added
        if isinstance(self._store_results, list):
            seen = {
                str(m.get("project_id") or m.get("slug") or "").lower()
                for m in self._store_results
            }
            extra = []
            for m in added:
                k = str(m.get("project_id") or m.get("slug") or "").lower()
                if k and k not in seen:
                    seen.add(k)
                    extra.append(m)
            if extra:
                self._store_results = self._store_results + extra
        for m in added:
            self._vbox.addWidget(self._make_card(m))
        QTimer.singleShot(0, self._pump_icons)
        # 迟到慢源是「补充」，别把状态栏覆盖成最终总数而抹掉部分结果提示。
        self.status.setText(t("store.partial_loading", n=len(self._mods)))

    def _make_card(self, m: dict) -> QFrame:
        # round-50 商店卡流光：低强度慢速，视觉整洁
        card = LightTrailCard(radius=12, strength=0.4, speed=0.55)
        card.setMinimumHeight(84)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(14)

        thumb = QLabel()
        thumb.setFixedSize(48, 48)
        # round-208 §2.8：占位图立即上屏（断网也不空白），真实图标只在
        # 卡片进入视口后才交给 ImageLoader，回来只换该卡图标不重建卡片。
        # 依据 prism:.../ModrinthModel.cpp:111-119 / ResourceModel.cpp:385-431。
        fallback = _letter_fallback(m["title"], 48)
        thumb.setPixmap(fallback)
        self._icon_pending.append((m.get("icon_url", ""), 48, thumb, fallback))
        lay.addWidget(thumb)

        info = QVBoxLayout()
        info.setSpacing(4)
        # round-218：标题必须「按可用宽度省略」。QLabel 的 sizeHint 是整段
        # 文本宽度，120 字的 mod 名会把卡片最小宽度顶到几千像素，QScrollArea
        # 的内容跟着变宽 → 右侧内容被挤出窗口 / 底部冒横向滑块（主理人实测）。
        title = ui_kit.ElidedLabel(m["title"])
        title.setProperty("cls", "title")
        _f = title.font()
        _f.setBold(True)          # 只加字重，颜色仍走 QSS token
        title.setFont(_f)
        title.setToolTip(m["title"])
        info.addWidget(title)

        # round-180：描述单行省略。旧代码 wordWrap(True) 让长描述把
        # 84px 的卡片撑成两三行高，整列节奏忽松忽紧（主流启动器都是
        # 固定行高 + 省略号）。完整描述放到 tooltip，不丢信息。
        # round-218：省略宽度不再写死 460 —— 交给 ElidedLabel 按真实宽度算，
        # 否则窄分栏时 460 本身就会把卡片顶宽。
        raw_desc = " ".join((m["description"] or "").split())
        desc = ui_kit.ElidedLabel(raw_desc)
        desc.setProperty("cls", "sub")
        if raw_desc:
            desc.setToolTip(raw_desc[:400])
        info.addWidget(desc)

        # meta 行：来源标签 + 下载量/作者。次信息用最淡的 token，
        # 与标题/描述拉开层级（旧的三行全用 sub，看着一样重）。
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        _src = ("CurseForge" if m.get("source") == "curseforge"
                else "Modrinth")
        meta_row.addWidget(ui_kit.tag(
            _src, COLORS["bg_hover"], COLORS["text_sub"],
            font_size=10, radius=6, pad="2px 8px"))
        _meta_text = t("store.meta",
                       downloads=ui_kit.format_count(m["downloads"]),
                       author=m["author"])
        meta = ui_kit.ElidedLabel(_meta_text)
        meta.setProperty("cls", "sub")
        meta.setStyleSheet(f"color: {COLORS['text_disabled']};")
        meta.setToolTip(_meta_text)
        meta_row.addWidget(meta, stretch=1)
        # round-193：已装的标出来 —— 避免重复下载同一个 mod（用户「下载为啥
        # 不可见」的一部分：装没装、装了什么要一眼看见）
        if self._is_installed(m):
            done = ui_kit.tag(t("store.installed_tag"),
                              COLORS["bg_hover"], COLORS["success"],
                              font_size=10, radius=6, pad="2px 8px")
            meta_row.addWidget(done)
        # round-199：兼容徽章 —— 搜索响应自带 game_versions / loaders，
        # 不额外发请求就能在列表上直接标「兼容 / 不兼容」，不用点进详情。
        comp = self._compat_of_card(m)
        if comp is not None:
            ok, reason = comp
            badge = ui_kit.tag(
                t("store.compat_tag") if ok else t("store.incompat_tag"),
                COLORS["bg_hover"],
                COLORS["success"] if ok else COLORS["warn"],
                font_size=10, radius=6, pad="2px 8px")
            if reason:
                badge.setToolTip(reason)
            meta_row.addWidget(badge)
        meta_row.addStretch(1)
        info.addLayout(meta_row)
        lay.addLayout(info, stretch=1)

        if self._category == "modpack":
            dl = QPushButton(t("store.install"))
            dl.clicked.connect(lambda _, pid=m["project_id"], pslug=m["slug"], mm=m:
                               self._install_modpack(pid, pslug, mm))
        else:
            dl = QPushButton(t("store.download"))
            dl.clicked.connect(
                lambda _, pid=m["project_id"], pslug=m["slug"],
                cf=m.get("_cf_file"), mm=m:
                self._download(pid, pslug, cf_file=cf, card=mm)
            )
        dl.setMinimumHeight(34)
        dl.setIcon(icon("download"))
        dl.setIconSize(QSize(16, 16))
        lay.addWidget(dl)

        # round-66 / round-120：两种源的卡片点击都进详情页（全部版本 / 翻译 /
        # 按版本下载）。下载/安装按钮会消费鼠标事件，不会误触卡片的点击打开。
        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda _e, m=m: self._open_detail(m)
        return card

    def _current_inst(self):
        """当前目标实例（页头下拉选中的那个）。"""
        iid = self.inst_combo.currentData() if hasattr(self, "inst_combo") else ""
        if not iid:
            return None
        for i in (self.list_instances() or []):
            if i.id == iid:
                return i
        return None

    def _is_installed(self, m: dict) -> bool:
        """这个资源是不是已经装在目标实例里了（round-199：判定收到 mod_sources）。"""
        inst = self._current_inst()
        if inst is None:
            return False
        try:
            from .core import mod_sources
            return mod_sources.is_installed(
                inst,
                project_id=str(m.get("project_id", "") or ""),
                slug=str(m.get("slug", "") or ""),
                title=str(m.get("title", "") or ""),
            )
        except Exception:  # noqa: BLE001 - 判定失败就按未安装处理
            return False

    def _compat_of_card(self, m: dict):
        """列表卡片的兼容判定：只用搜索响应里带的版本/加载器。

        返回 ``None``（没有版本数据，不画徽章）/ ``(True, "")`` / ``(False, 原因)``。
        """
        inst = self._current_inst()
        if inst is None:
            return None
        gv = [str(x) for x in (m.get("game_versions") or [])]
        lds = [str(x).lower() for x in (m.get("loaders") or [])]
        if not gv and not lds:
            return None
        mc = str(getattr(inst, "game_version", "") or "")
        ld = str(getattr(inst, "loader", "") or "vanilla").lower()
        reason = ""
        if mc and gv and mc not in gv:
            reason = t("store.incompat_mc", mc=mc)
        elif ld and ld != "vanilla" and lds and ld not in lds:
            reason = t("store.incompat_loader", loader=loader_name(ld))
        if reason:
            return False, reason
        return True, ""

    # ia[store]: 点资源卡片 | 资源中心结果卡片 | 页内栈切到详情（全部版本 / 前置 / 下载），不新开窗口
    def _open_detail(self, m: dict):
        """在页内打开资源详情（round-132：不再弹独立 QDialog）。

        列出全部版本（可按 MC 版本过滤）、获取中文翻译、选择任意版本下载到
        目标实例对应子目录。没有实例也能打开——可切到「不指定版本 · 另存为…」
        只下载文件，与主流启动器一致。
        """
        if self._detail_panel is not None:
            return
        inst = self._target()
        panel = StoreDetailPanel(
            self, m, self._category, inst,
            _TYPE_SUBDIR.get(self._category, "mods"),
            instances=self.list_instances())
        panel.back_requested.connect(self._close_detail)
        self._detail_panel = panel
        self._stack.addWidget(panel)
        self._stack.setCurrentWidget(panel)

    def _close_detail(self):
        """关闭页内详情，恢复资源列表（先隐藏再延迟删除，避免残留绘制）。"""
        panel = self._detail_panel
        if panel is None:
            return
        self._detail_panel = None
        panel.shutdown()
        self._stack.setCurrentWidget(self._list_view)
        self._stack.removeWidget(panel)
        panel.hide()
        panel.deleteLater()

    # ia[store]: 点「下载 / 安装」 | 资源中心卡片按钮 | 按目标实例下载，缺前置时先询问补齐
    def _download(self, project_id: str, slug: str, cf_file: dict | None = None,
                  card: dict | None = None):
        inst = self._target()
        if inst is None:
            # round-119/120：没选实例时不再直接拦下——详情页可按任意版本下载
            # 或另存为，两种资源源都支持。
            if card is not None:
                self._open_detail(card)
                return
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
        # round-140：合并源下按卡片归属分流（card.source 优先于页面源）
        src = (card or {}).get("source") or self._source
        if src == "curseforge":
            # round-222：三条并行通道（cfwidget_file / cfwidget_slug / keyed
            # project_id）收敛到 download_cf_card。此前它们只下本体，不解析
            # required 依赖、不删同 mod 旧 jar —— 从列表页装 FTB Ultimine
            # 照样缺 FTB Library 崩游戏（round-220 只修了详情页入口）。
            # ⚠ ProgressWorker 用 keyword 注入 callback，新增参数一律走
            #   kwargs，别占位置参数位（会撞 multiple values）。
            mc = getattr(inst, "game_version", "") or ""
            ld = getattr(inst, "loader", "") or ""
            # round-192：CF 下载也回报 manifest，模组列表照样标「资源中心」
            self._dl_manifest = []
            self._dl_meta = {
                "inst": inst,
                "slug": slug,
                "project_id": project_id,
                "title": (card or {}).get("title", "") or slug,
                "source": "curseforge",
            }
            from .net_api import download_cf_card
            self._dworker = ProgressWorker(
                download_cf_card, str(project_id or ""), slug, cf_file, dest,
                mc_version=mc, loader=ld,
                manifest_out=self._dl_manifest,
                inst=inst, with_deps=True)
        else:
            # round-37：传入实例的 MC 版本 + 加载器，让 Modrinth 过滤兼容版本
            # 并自动拉取 required 依赖树（download_mod_to 已支持依赖解析）
            # round-191：带回「下了哪些文件」，下载完成后登记模组来源
            self._dl_manifest = []
            self._dl_meta = {
                "inst": inst,
                "slug": slug,
                "project_id": project_id,
                "title": (card or {}).get("title", "") or slug,
            }
            self._dworker = ProgressWorker(
                download_mod_to, project_id, dest,
                getattr(inst, "game_version", "") or "",
                getattr(inst, "loader", "") or "",
                manifest_out=self._dl_manifest,
            )
        self._dworker.progress.connect(self._on_pack_progress)
        self._dworker.speed.connect(self._on_pack_speed)
        self._dworker.finished.connect(self._on_mod_downloaded)
        self._dworker.error.connect(self._on_pack_error)
        self._dworker.cancelled.connect(self._on_pack_cancelled)
        self._dl_bar.setVisible(True)
        self._dl_bar.setRange(0, 0)          # 依赖树文件数未知 → 忙指示
        self._dl_speed.setVisible(True)
        self._dl_speed.setText("")
        self._dworker.start()

    def _on_mod_downloaded(self, p):
        self._dl_bar.setVisible(False)
        self._dl_speed.setVisible(False)
        self.status.setText(t("store.downloaded", file=os.path.basename(p)))
        # round-191：登记来源（区分「资源中心下的」与「自己放进去的」）
        meta = getattr(self, "_dl_meta", None) or {}
        manifest = getattr(self, "_dl_manifest", None) or []
        inst = meta.get("inst")
        if inst is not None and manifest:
            try:
                from .core import mod_sources
                entries = []
                for item in manifest:
                    pid = str(item.get("project_id") or "")
                    entries.append({
                        "filename": item.get("filename", ""),
                        "project_id": pid,
                        "slug": meta.get("slug", "") if pid == meta.get(
                            "project_id") else "",
                        "title": meta.get("title", "") if pid == meta.get(
                            "project_id") else "",
                        "source": meta.get("source", "modrinth"),
                    })
                mod_sources.record(inst, entries)
            except Exception:  # noqa: BLE001 - 记录失败不影响下载结果
                pass
        self._dl_manifest = []
        self._dl_meta = {}

    # ---- modpack: download .mrpack / CF zip → install as a new instance ----
    def _install_modpack(self, project_id: str, slug: str, card: dict | None = None):
        if not confirm(
            self, t("store.install_pack_title"),
            t("store.install_pack_confirm", slug=slug),
        ):
            return
        self.status.setText(t("store.downloading_pack", slug=slug))
        from .paths import get_data_dir
        cache_dir = os.path.join(get_data_dir(), "cache")
        # round-142：CF 整合包一键安装 —— 主 zip 走免 key 文件列表最新条目
        # （cfwidget 对整合包 slug 404，必须用数字 project_id 走镜像），
        # 下载完由 _on_cf_pack_downloaded 走 manifest 逐文件安装链。
        if (card or {}).get("source") == "curseforge":
            from .net_api import download_curseforge_mod
            self._pworker = ProgressWorker(download_curseforge_mod,
                                           project_id, cache_dir)
            self._pworker.finished.connect(self._on_cf_pack_downloaded)
        else:
            # round-111：改用 ProgressWorker（而非裸 Worker）——它会注入 mll 风格
            # callback，经 net_api.download_modpack_to 桥接成字节级进度 + 实时速度。
            self._pworker = ProgressWorker(download_modpack_to, project_id,
                                           cache_dir)
            self._pworker.finished.connect(self._on_pack_downloaded)
        self._pworker.progress.connect(self._on_pack_progress)
        self._pworker.speed.connect(self._on_pack_speed)
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

    def _on_cf_pack_downloaded(self, path: str):
        """CF 整合包主 zip 下载完成 → 免 key 逐文件解析安装为新实例（round-142）。"""
        self._dl_bar.setVisible(False)
        self._dl_speed.setVisible(False)
        from PySide6.QtWidgets import QProgressDialog
        from .win_rounded import warn
        from .modpack_import import (detect_pack_format, import_curseforge_zip,
                                  tick_import_progress)
        from .net_api import NetError
        if detect_pack_format(path) != "curseforge":
            info(self, t("mrpack.title"), t("mrpack.bad_file"))
            return
        progress = QProgressDialog(self)
        progress.setWindowTitle(t("modpack.title"))
        progress.setLabelText(t("modpack.importing"))
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        # 防闪加固：关自动关/自动重置（见 pages_instances 同段注释）。
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setRange(0, 0)  # 先 indeterminate 解析 manifest，随后 n/N
        progress.setMinimumWidth(420)
        # round-149：全局 QSS 把 QProgressBar 定死 8px 高，内嵌百分比文字会被
        # 裁掉一半。与 pages_instances 同款导入流程一起关掉内嵌文字。
        _bar = progress.findChild(QProgressBar)
        if _bar is not None:
            _bar.setTextVisible(False)

        # round-142b：实时 n/N 计数（轮询 state，跨线程零信号管道）
        state = {"done": 0, "total": 0}

        def _pr(label, done, total):
            state.update(label=str(label), done=done, total=total)
            return True

        worker = Worker(import_curseforge_zip, path, self.mgr, progress=_pr)
        from PySide6.QtCore import QTimer
        tick = QTimer(self)
        tick.setInterval(200)

        def _on_tick():
            tick_import_progress(state, progress)

        def _done(inst):
            tick.stop()
            progress.hide()
            # round-150：导入时已尝试安装版本/加载器；失败时提示首次启动会重试。
            err = getattr(inst, "loader_install_error", "")
            if err:
                warn(self, t("modpack.title"), t("modpack.loader_failed_hint", e=err))
            else:
                toast(self, t("modpack.title"), t("modpack.done"))
            if inst and getattr(inst, "id", None):
                self.mgr.set_current(inst.id)

        def _err(e):
            tick.stop()
            progress.hide()
            if isinstance(e, NetError):
                warn(self, t("modpack.title"), str(e))
            else:
                warn(self, t("modpack.title"), t("modpack.error", e=e))

        tick.timeout.connect(_on_tick)
        tick.start()
        worker.finished.connect(_done)
        worker.error.connect(_err)
        worker.start()

    def _on_pack_error(self, e):
        self._dl_bar.setVisible(False)
        self._dl_speed.setVisible(False)
        self.status.setText(t("store.download_fail", e=e))

    def _on_pack_cancelled(self, _result=None):
        """round-226：取消是 worker 的第三个终态，不接就永远转圈。"""
        self._dl_bar.setVisible(False)
        self._dl_speed.setVisible(False)
        self.status.setText(t("store.download_cancelled"))

    def retranslate_ui(self):
        # 详情面板是页内组件，切语言时先退回列表，避免残留旧语言文案。
        self._close_detail()
        self.title_lbl.setText(t("store.title"))
        self.target_lbl.setText(t("store.target_label"))
        self.search.setPlaceholderText(t("store.search_placeholder"))
        self.filter_panel.retranslate_ui()
        self.filter_toggle_btn.setText(
            t("store.filter_collapse") if self.filter_panel.isVisible()
            else t("store.filter_expand"))
        self.page_first_btn.setText(t("store.page_first"))
        self.page_prev_btn.setText(t("store.page_prev"))
        self.page_next_btn.setText(t("store.page_next"))
        self.page_label.setText(t("store.page_label", page=self._store_page + 1))
        for pt, key in STORE_CATEGORIES:
            if pt in self._cat_btns:
                self._cat_btns[pt].setText(t(key))
        self._sync_target()
        self._last_request_key = ""
        self._search_timer.start()
