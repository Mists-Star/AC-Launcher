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
)
from PySide6.QtCore import Signal, QSize, QTimer, Qt
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont

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
from .async_image import ImageLoader, make_version_pixmap
from .store_detail import StoreDetailPanel  # round-66 资源详情；round-132 页内面板


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
        # round-142b 修（crash.log 18:43）：CF 整合包装完要在本页 set_current，
        # 但 StorePage 此前没有 mgr —— 回调里 AttributeError，Worker 根本没启动，
        # 用户看到的就是「导入一直没动静」。
        self.mgr = manager()
        self._mods: list[dict] = []
        self._offset = 0
        self._query = ""
        self._category = "mod"
        # round-140：默认源 = 「全部」（Modrinth + CurseForge 合并）；
        # _has_more = 无限滚动的到底闸门（不足一页 → 停止，杜绝重复加载）。
        self._source = "all"
        self._has_more = True
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

        # round-132：列表与详情在同一页内用栈切换（详情不再是独立弹窗）
        self._list_view = QWidget()
        lv = QVBoxLayout(self._list_view)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(16)
        self._detail_panel = None

        # 第一行：标题 + 目标实例 + 源切换（round-104：目标实例上移到页头，
        # 搜索行只留搜索框——「搜索」按钮被搜索框吃掉）
        self.source_combo = QComboBox()
        self.source_combo.setMinimumHeight(36)
        self.source_combo.setMinimumWidth(120)
        self.source_combo.addItem(t("store.source_all"), "all")
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
        lv.addWidget(self._header)

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
        lv.addLayout(self._cat_row)

        # 第三行：搜索框（无独立按钮——输入即防抖搜索，Enter 立即搜索）
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("store.search_placeholder"))
        self.search.setMinimumHeight(34)
        self.search.textChanged.connect(lambda _=None: self._search_timer.start())
        self.search.returnPressed.connect(self._search_timer.start)
        lv.addWidget(self.search)

        self.status = QLabel(t("store.loading"))
        self.status.setProperty("cls", "sub")
        lv.addWidget(self.status)

        # round-111：整合包下载的字节级进度 + 实时速度（与启动/下载对话框同一
        # slim 进度条范式）。平时隐藏，只在下载整合包时出现。
        self._dl_bar = QProgressBar()
        self._dl_bar.setProperty("cls", "slim")
        self._dl_bar.setTextVisible(False)
        self._dl_bar.setFixedHeight(8)
        self._dl_bar.setVisible(False)
        lv.addWidget(self._dl_bar)
        self._dl_speed = QLabel("")
        self._dl_speed.setProperty("cls", "sub")
        self._dl_speed.setVisible(False)
        lv.addWidget(self._dl_speed)

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
        lv.addWidget(self.scroll, stretch=1)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._list_view)
        root.addWidget(self._stack, stretch=1)

        # round-124：首帧骨架屏（首次检索 1.2s 内不再是一片空白）
        for _ in range(6):
            self._vbox.addWidget(_skeleton_row(64))

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

    def _on_source_changed(self, _index: int):
        """切换源时同步搜索框提示与状态栏文案。

        CurseForge 有三态：配置了 key → 官方 API 关键词搜索；没 key 但开了
        免 key 通道 → MCIM 镜像关键词搜索（round-140）；两者都没有 → 提示
        去设置里填 key。
        """
        self._source = self.source_combo.currentData()
        if self._source == "curseforge":
            from .net_api import curseforge_available, curseforge_keyless_enabled
            self._update_search_placeholder()
            if curseforge_available():
                self.status.setText(t("store.cf_hint_key"))
            elif curseforge_keyless_enabled():
                self.status.setText(t("store.cf_hint_mirror"))
            else:
                self.status.setText(t("store.cf_no_key"))
        elif self._source == "all":
            # round-140：合并源提示（CF 通道全关时退回「只搜 Modrinth」语义）
            from .net_api import curseforge_available, curseforge_keyless_enabled
            self._update_search_placeholder()
            self.status.setText(
                t("store.source_all_hint")
                if (curseforge_available() or curseforge_keyless_enabled())
                else t("store.source_all_hint_mr"))
        else:
            self._update_search_placeholder()
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
        self._has_more = True  # round-140：新搜索重新武装到底闸门
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
                if reset:
                    _clear_skeleton(self._vbox)
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
        if self._loading_more or not self._has_more:
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
        if self._source == "all":
            # round-140：「全部」源 = 两源并行合并（net_api.search_all）
            from .net_api import search_all
            worker = Worker(search_all, self._query, self._offset, 20,
                            self._category)
        else:
            worker = Worker(search_mods, self._query, self._offset,
                            project_type=self._category)
        self._track(worker, gen, reset)

    def _load_curseforge(self, reset: bool):
        """CurseForge 源：有 key → 官方 API；无 key 且开免 key 通道 → MCIM 镜像
        关键词搜索（round-140，输入里带链接时仍走 slug/链接解析）。

        两者都没有时明确提示去设置里填 key —— 关掉免 key 通道即回到
        仅官方 API 的保守模式。
        """
        from .net_api import (curseforge_available, curseforge_keyless_enabled,
                              search_curseforge, curseforge_link_search)
        has_key = curseforge_available()
        if not has_key and not curseforge_keyless_enabled():
            self._on_loaded([], reset)
            self.status.setText(t("store.cf_no_key"))
            return
        # 粘贴完整链接 → 免 key 的 slug 解析；关键词 → 镜像/官方搜索
        # （带 category=CF classId + 翻页 offset —— 此前写死模组类且
        # offset 恒 0，导致分类不生效 + 无限滚动重复拉同一页）。
        if not has_key and "/" in self._query:
            worker_fn, args = curseforge_link_search, (self._query,)
        else:
            worker_fn = search_curseforge
            args = (self._query, self._offset, 20, self._category)
        self._load_gen += 1
        gen = self._load_gen
        worker = Worker(worker_fn, *args)
        self._track(worker, gen, reset)

    def _on_loaded(self, mods: list[dict], reset: bool):
        self._loading_more = False
        # round-140：不足一页 = 已到底 → 关闸（此前 CF 源 offset 恒 0，
        # 无限滚动会把第一页无限重复塞进列表）。
        if len(mods) < 20:
            self._has_more = False
        self._mods = mods if reset else self._mods + mods
        if reset:
            while self._vbox.count():
                item = self._vbox.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        # round-128：中文查询走本地名库反查，名库没收录时是「搜不到」而不是
        # 「没有这个资源」——状态栏要说清楚，别让用户以为功能坏了。
        try:
            from .net_api import has_cjk
            _zh = has_cjk(self._query)
        except Exception:  # noqa: BLE001
            _zh = False
        if not self._mods and _zh:
            self.status.setText(t("store.zh_no_hit"))
        else:
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
        # 不必等用户点进详情才开始下载（页内详情面板用的正是 72 尺寸）。
        # 失败静默——详情页仍会按需加载，不会因此空白。
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
            from .net_api import (download_cfwidget_file, download_curseforge_mod,
                                  download_cfwidget_slug, curseforge_available,
                                  curseforge_keyless_enabled)
            if cf_file:
                # 免 key 通道解析出的文件（含 id/name）→ forgecdn 直链
                self._dworker = ProgressWorker(download_cfwidget_file,
                                               cf_file, dest)
            elif not curseforge_available() and curseforge_keyless_enabled():
                # 免 key 镜像搜索的命中只有 slug → slug → cfwidget → forgecdn
                self._dworker = ProgressWorker(download_cfwidget_slug,
                                               slug, dest)
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
        from .modpack_import import detect_pack_format, import_curseforge_zip
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

        # round-142b：实时 n/N 计数（轮询 state，跨线程零信号管道）
        state = {"done": 0, "total": 0}

        def _pr(label, done, total):
            state.update(done=done, total=total)
            return True

        worker = Worker(import_curseforge_zip, path, self.mgr, progress=_pr)
        from PySide6.QtCore import QTimer
        tick = QTimer(self)
        tick.setInterval(200)

        def _on_tick():
            d, tot = state["done"], state["total"]
            if not tot:
                return
            if d < tot:
                if progress.maximum() != tot:
                    progress.setRange(0, tot)
                if progress.value() != d:
                    progress.setValue(d)
                txt = f"{t('modpack.importing')}（{d}/{tot}）"
                if state.get("txt") != txt:
                    state["txt"] = txt
                    progress.setLabelText(txt)
            elif not state.get("finishing"):
                # 收尾阶段（补全版本/装加载器）：不再 setValue(max) 触发
                # 自动关→reset→show 循环（「导入包」空提示闪烁的根因）。
                #一次性切不定长转圈 + 收尾文案，稳定显示到完成。
                state["finishing"] = True
                progress.setRange(0, 0)
                progress.setLabelText(t("modpack.finishing"))
                progress.show()

        def _done(inst):
            tick.stop()
            progress.hide()
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

    def retranslate_ui(self):
        # round-132：详情面板是页内组件，切换语言时先退回列表（避免英文界面
        # 里残留中文详情文案），下次再点开即按新语言重建。
        self._close_detail()
        self.title_lbl.setText(t("store.title"))
        self.target_lbl.setText(t("store.target_label"))
        self.search.setPlaceholderText(t("store.search_placeholder"))
        # rebuild source combo, keep selection
        keep = self.source_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem(t("store.source_all"), "all")
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
