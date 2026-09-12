"""Store detail dialog — per-mod info, version picker, translate, download.

round-66+85 资源中心详情页（round-85 重构为行卡片流，对齐主流启动器：
PCL2/HMCL 风格 = 头部信息 + 最新版本条 + 版本卡片列表，每行右侧直接下载：
* 展示项目信息（图标 / 标题 / 分类 / 下载量 / 作者 / 简介）
* 顶部「最新版本」条——最新版本一眼可见，点「下载」即装
* 其余版本以行卡片流展示（版本号 + MC + 加载器彩章 + 大小 + 日期 + 下载），
  按 MC 版本 + 加载器双重筛选；分页加载（每页 50），大项目不再一次拉全部
  （round-85：Fabric API 上千版本，分页后秒开）
* "获取翻译"：用免费在线翻译把简介/README 机翻成中文（无需 API key）
* 一键打开项目官网详情页
* AC 无边框窗口：自定义标题栏 + 圆角，与主窗口风格统一

挂在后台 Worker(QThread) 上执行网络请求，绝不阻塞 UI；所有错误体现在
对话框内状态显示而不是崩溃。
"""
from __future__ import annotations

import os
import re

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTextEdit, QMessageBox, QFrame, QWidget, QButtonGroup,
    QScrollArea,
)
from PySide6.QtCore import Qt, QUrl, QSize, QPoint
from PySide6.QtGui import QDesktopServices, QColor

from .theme import COLORS
from .i18n import t
from .worker import Worker
from .async_image import ImageLoader
from .win_rounded import info, enable_win11_round_corners
from .frameless import FramelessHelper, TitleBar

PAGE_SIZE = 50


# 加载器 → 徽章配色（对齐各加载器自身的品牌色，让加载器一眼可辨）。
LOADER_BADGE_COLORS = {
    "fabric":     "#B0633A",   # Fabric 沙金棕
    "forge":      "#E04E14",   # Forge 橙红
    "neoforge":   "#8B5CF6",   # NeoForge 紫
    "quilt":      "#2C9E8F",   # Quilt 青
    "liteloader": "#3B82F6",
    "legacyfabric": "#7C6BD6",
    "optifine":   "#F59E0B",
    "bukkit":     "#E2723B",
    "spigot":     "#E2723B",
    "paper":      "#C9B45B",
    "purpur":     "#C57B9A",
    "vanilla":    "#6B7280",
    "datapack":   "#0D9488",
}
LOADER_DEFAULT = "#6B7280"


def _human_size(n) -> str:
    """文件字节数 → 可读大小；空值给占位符。"""
    if not n:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fetch_and_translate(card: dict) -> tuple[str, str]:
    """后台线程任务：取项目简介/README（body 优先）并机翻成中文。

    返回 (原文, 译文)。
    """
    from .net_api import get_project_info, translate_text, NetError
    desc = (card.get("description") or "").strip()
    body = ""
    try:
        p = get_project_info(card.get("slug") or card.get("project_id") or "")
        if p:
            body = (p.get("body") or "").strip()
    except NetError:
        pass  # 拿不到 README 就只翻译简介
    src = body if len(body) > len(desc) else desc
    if not src:
        raise NetError("该资源没有可翻译的简介/说明")
    src = re.sub(r"[#>*`\[\]()~-]{1,3}", " ", src[:5000])
    src = re.sub(r"\s{2,}", " ", src).strip()
    return src, translate_text(src)


class _VersionRow(QFrame):
    """一行版本卡片：版本号 | MC 版本 | 加载器彩章 | 大小 | 日期 | 下载按钮。

    点击整行或右侧「下载」即下载该版本（对齐主流启动器的行内下载）。
    """

    def __init__(self, parent, ver: dict, is_latest: bool, on_download):
        super().__init__(parent)
        self._ver = ver
        self.setObjectName("vrow")
        self.setCursor(Qt.PointingHandCursor)
        accent = COLORS.get("accent", "#7C3AED")
        brd = COLORS.get("border", "#E5E7EB")
        self.setStyleSheet(
            f"#vrow {{ background: {COLORS.get('bg_card', '#FFFFFF')}; "
            f"border: 1px solid {brd}; border-radius: 10px; }}"
            f"#vrow:hover {{ border: 1px solid {accent}66; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(12)

        # 版本号（推荐加星：自绘星标，不用文本 ★）
        v_wrap = QWidget()
        vh = QHBoxLayout(v_wrap)
        vh.setContentsMargins(0, 0, 0, 0)
        vh.setSpacing(6)
        if is_latest:
            from .ui_kit import state_pix
            si = QLabel()
            si.setPixmap(state_pix("star", accent, 14))
            si.setFixedSize(15, 15)
            vh.addWidget(si)
        v_lbl = QLabel(ver.get("version_number", "—"))
        v_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: {'800' if is_latest else '600'}; "
            f"color: {accent if is_latest else COLORS['text_main']};")
        v_lbl.setToolTip(t("store.detail_latest_tip") if is_latest else "")
        vh.addWidget(v_lbl)
        lay.addWidget(v_wrap)

        # MC 版本
        gvs = ver.get("game_versions", [])
        mc_lbl = QLabel("MC " + ", ".join(gvs[:2]) + (f" +{len(gvs)-2}" if len(gvs) > 2 else "") if gvs else "—")
        mc_lbl.setProperty("cls", "sub")
        lay.addWidget(mc_lbl)

        # 加载器彩章
        loaders = ver.get("loaders", [])
        if loaders:
            ld0 = loaders[0].lower()
            colr = LOADER_BADGE_COLORS.get(ld0, LOADER_DEFAULT)
            ld_lbl = QLabel(loaders[0])
            ld_lbl.setStyleSheet(
                f"color: {colr}; background: {colr}1F; border-radius: 8px; "
                f"padding: 1px 8px; font-size: 11px; font-weight: 600;")
            if len(loaders) > 1:
                ld_lbl.setText(f"{loaders[0]} +{len(loaders)-1}")
                ld_lbl.setToolTip(", ".join(loaders))
            lay.addWidget(ld_lbl)
        else:
            lay.addSpacing(1)

        lay.addStretch(1)

        # 大小 / 日期
        files = ver.get("files", [])
        size = files[0].get("size") if files else None
        s_lbl = QLabel(_human_size(size))
        s_lbl.setProperty("cls", "sub")
        s_lbl.setMinimumWidth(48)
        lay.addWidget(s_lbl)

        d_lbl = QLabel((ver.get("date_published", "") or "")[:10])
        d_lbl.setProperty("cls", "sub")
        d_lbl.setMinimumWidth(70)
        lay.addWidget(d_lbl)

        dl = QPushButton(t("store.download"))
        dl.setProperty("cls", "accent")
        dl.setCursor(Qt.PointingHandCursor)
        dl.setMinimumHeight(30)
        dl.setMinimumWidth(76)
        dl.clicked.connect(lambda: on_download(self._ver))
        lay.addWidget(dl)

        self._on_dl = on_download

    def mouseReleaseEvent(self, e):  # 整行点击 = 下载（与主流交互一致）
        if e.button() == Qt.LeftButton and self._on_dl:
            self._on_dl(self._ver)
        super().mouseReleaseEvent(e)


class StoreDetailDialog(QDialog):
    """资源中心详情：信息头 + 最新版本条 + 版本卡片流（分页）+ 翻译 + 下载。"""

    def __init__(self, parent, card: dict, category: str, inst, subdir: str):
        super().__init__(parent)
        self._card = card
        self._category = category
        self._inst = inst
        self._subdir = subdir
        self._versions: list[dict] = []      # 已分页累积的全量版本
        self._workers: list = []
        self._img = ImageLoader(self)
        self._offset = 0                     # 服务端分页游标
        self._has_more = False

        self.setWindowTitle(t("store.detail_title"))
        self.setModal(True)
        self.setMinimumSize(880, 620)
        self.resize(900, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── AC 无边框标题栏 ──
        self.titlebar = TitleBar(
            self, title=t("store.detail_title"), height=38, controls="close")
        root.addWidget(self.titlebar)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 12, 18, 14)
        bl.setSpacing(8)

        # ── ① 信息头：图标 + 标题 + 徽章 + 简介 + 在线页面 ──
        bl.addWidget(self._build_header())

        # ── ② 最新版本条 ──
        bl.addWidget(self._build_latest())

        # ── ③ 筛选栏 ──
        bl.addLayout(self._build_filter_bar())

        # ── ④ 版本卡片流 ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 4, 0)
        self._rows.setSpacing(6)
        self._rows.addStretch(1)
        self.scroll.setWidget(self._rows_host)
        self.scroll.setMinimumHeight(220)
        bl.addWidget(self.scroll, stretch=1)

        # 加载更多
        more_row = QHBoxLayout()
        self.more_btn = QPushButton(t("store.detail_load_more"))
        self.more_btn.setProperty("cls", "surface")
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setMinimumHeight(32)
        self.more_btn.clicked.connect(self._load_more)
        more_row.addStretch(1)
        more_row.addWidget(self.more_btn)
        more_row.addStretch(1)
        bl.addLayout(more_row)

        # ── ⑤ 翻译区 ──
        tl_row = QHBoxLayout()
        self.translate_btn = QPushButton(t("store.detail_translate"))
        self.translate_btn.setProperty("cls", "surface")
        self.translate_btn.setCursor(Qt.PointingHandCursor)
        self.translate_btn.clicked.connect(self._translate)
        tl_row.addWidget(self.translate_btn)
        self.tr_status = QLabel("")
        self.tr_status.setProperty("cls", "sub")
        tl_row.addWidget(self.tr_status, stretch=1)
        bl.addLayout(tl_row)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText(t("store.detail_text_hint"))
        self.text.setMaximumHeight(96)
        bl.addWidget(self.text)

        # ── ⑥ 底部状态 + 关闭 ──
        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setProperty("cls", "sub")
        foot.addWidget(self.status, stretch=1)
        self.close_btn = QPushButton(t("common.cancel"))
        self.close_btn.setProperty("cls", "secondary")
        self.close_btn.setMinimumHeight(32)
        self.close_btn.clicked.connect(self.close)
        foot.addWidget(self.close_btn)
        bl.addLayout(foot)

        root.addWidget(body, stretch=1)

        # ── AC 窗口：无边框 + 拖拽 + 圆角 ──
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        enable_win11_round_corners(self)

        self._load_first_page()

    # ---------------- UI 构建 ----------------
    def _build_header(self) -> QFrame:
        card = self._card
        accent = COLORS.get("accent", "#7C3AED")
        soft = COLORS.get("accent_soft", "#EDE9FE")

        head = QFrame()
        head.setObjectName("hdr")
        head.setStyleSheet(
            f"#hdr {{ border-radius: 14px; background: "
            f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {soft}, stop:1 {accent}18); }}"
        )
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 14, 14, 14)
        hl.setSpacing(14)

        self.thumb = QLabel()
        self.thumb.setFixedSize(72, 72)
        hl.addWidget(self.thumb, 0, Qt.AlignTop)
        if self._img and card.get("icon_url"):
            from PySide6.QtGui import QPixmap
            fb = QPixmap(72, 72)
            fb.fill(Qt.transparent)
            self._img.load(card.get("icon_url", ""), 72, self.thumb, fb)

        ti = QVBoxLayout()
        ti.setSpacing(5)
        self.title = QLabel(card.get("title", ""))
        self.title.setStyleSheet(
            f"font-size: 20px; font-weight: 800; color: {COLORS['text_main']};")
        self.title.setWordWrap(True)
        ti.addWidget(self.title)

        meta = QHBoxLayout()
        meta.setSpacing(10)
        cat_b = QLabel(t(_cat_key(self._category)))
        cat_b.setStyleSheet(
            f"color: {accent}; background: {soft}; "
            f"border-radius: 8px; padding: 2px 10px; font-size: 11px; font-weight: 600;")
        meta.addWidget(cat_b)
        self.meta = QLabel(t("store.meta",
                             downloads=card.get("downloads", 0),
                             author=card.get("author", "")))
        self.meta.setProperty("cls", "sub")
        meta.addWidget(self.meta)
        meta.addStretch(1)
        # 在线页面（子行右侧）
        self.open_btn = QPushButton(t("store.detail_open"))
        self.open_btn.setProperty("cls", "surface")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setMinimumHeight(28)
        link = (f"https://modrinth.com/{_type_slug(self._category)}/"
                f"{card.get('slug') or card.get('project_id')}")
        self.open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(link)))
        meta.addWidget(self.open_btn)
        ti.addLayout(meta)

        self.desc = QLabel(self._short(card.get("description", ""), 240))
        self.desc.setProperty("cls", "sub")
        self.desc.setWordWrap(True)
        self.desc.setMaximumHeight(44)
        ti.addWidget(self.desc)
        hl.addLayout(ti, stretch=1)
        return head

    def _build_latest(self) -> QFrame:
        accent = COLORS.get("accent", "#7C3AED")
        box = QFrame()
        box.setObjectName("latest")
        box.setStyleSheet(
            f"#latest {{ border-radius: 12px; background: {accent}14; "
            f"border: 1px solid {accent}40; }}")
        bi = QHBoxLayout(box)
        bi.setContentsMargins(13, 9, 11, 9)
        bi.setSpacing(10)

        tag = QWidget()
        tag.setAttribute(Qt.WA_StyledBackground, True)
        tag.setStyleSheet(
            f"background: {accent}22; border-radius: 9px;")
        tag_lay = QHBoxLayout(tag)
        tag_lay.setContentsMargins(10, 2, 12, 2)
        tag_lay.setSpacing(6)
        from .ui_kit import state_pix
        si = QLabel()
        si.setPixmap(state_pix("star", accent, 14))
        si.setFixedSize(15, 15)
        tag_lay.addWidget(si)
        st = QLabel(t("store.detail_latest"))
        st.setStyleSheet(
            f"color: {accent}; font-size: 12px; font-weight: 800;")
        tag_lay.addWidget(st)
        bi.addWidget(tag)

        self.latest_ver = QLabel("—")
        self.latest_ver.setStyleSheet(
            f"color: {COLORS['text_main']}; font-size: 14px; font-weight: 700;")
        self.latest_ver.setToolTip(t("store.detail_latest_tip"))
        bi.addWidget(self.latest_ver)

        self.latest_loader = QLabel("")
        bi.addWidget(self.latest_loader)
        self.latest_mc = QLabel("")
        self.latest_mc.setProperty("cls", "sub")
        bi.addWidget(self.latest_mc)
        self.latest_size = QLabel("")
        self.latest_size.setProperty("cls", "sub")
        bi.addWidget(self.latest_size)
        self.latest_date = QLabel("")
        self.latest_date.setProperty("cls", "sub")
        bi.addWidget(self.latest_date)
        bi.addStretch(1)

        self.latest_btn = QPushButton(t("store.download"))
        self.latest_btn.setProperty("cls", "accent")
        self.latest_btn.setCursor(Qt.PointingHandCursor)
        self.latest_btn.setMinimumHeight(32)
        self.latest_btn.setEnabled(False)
        self.latest_btn.clicked.connect(self._download_latest)
        bi.addWidget(self.latest_btn)
        box.setVisible(False)
        self._latest_box = box
        return box

    def _build_filter_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.loader_lbl = QLabel(t("store.detail_filter_loader"))
        self.loader_lbl.setProperty("cls", "sub")
        bar.addWidget(self.loader_lbl)
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        self._chips_box = QHBoxLayout()
        self._chips_box.setSpacing(6)
        self._loader_options: list[str] = []
        self._add_loader_chip("", t("store.detail_all_loader"), True)
        bar.addLayout(self._chips_box)

        self.filter_lbl = QLabel(t("store.detail_filter"))
        self.filter_lbl.setProperty("cls", "sub")
        bar.addWidget(self.filter_lbl)
        self.mc_filter = QComboBox()
        self.mc_filter.setProperty("cls", "surface")
        self.mc_filter.setMinimumWidth(128)
        self.mc_filter.currentIndexChanged.connect(self._rebuild_rows)
        bar.addWidget(self.mc_filter)

        bar.addStretch(1)
        self.versions_lbl = QLabel(t("store.detail_loading"))
        self.versions_lbl.setProperty("cls", "sub")
        bar.addWidget(self.versions_lbl, alignment=Qt.AlignRight)
        return bar

    def _add_loader_chip(self, value: str, text: str, checked: bool = False):
        from PySide6.QtWidgets import QPushButton
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(checked)
        b.setCursor(Qt.PointingHandCursor)
        style = (
            "QPushButton { background: transparent; color: $SUB; border: 1px solid $BRD;"
            " border-radius: 13px; padding: 3px 12px; font-size: 12px; }"
            "QPushButton:checked { background: $ACCENT15; color: $ACCENT;"
            " border-color: $ACCENT; font-weight: 700; }"
            "QPushButton:hover { background: $HOVER; }"
        )
        c = COLORS
        style = (style
                 .replace("$SUB", c.get("text_sub", "#6B7280"))
                 .replace("$BRD", c.get("border", "#E5E7EB"))
                 .replace("$ACCENT15", c.get("accent", "#7C3AED") + "26")
                 .replace("$ACCENT", c.get("accent", "#7C3AED"))
                 .replace("$HOVER", c.get("bg_hover", "#F0F1F3")))
        b.setStyleSheet(style)
        b.clicked.connect(self._rebuild_rows)
        self._chip_group.addButton(b, len(self._loader_options))
        self._loader_options.append(value)
        self._chips_box.addWidget(b)

    # ---------- helpers ----------
    def _short(self, s: str, n: int) -> str:
        s = (s or "").strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    def _loader(self) -> str:
        """当前选中的加载器筛选值（"" = 全部）。"""
        if not hasattr(self, "_chip_group"):
            return ""
        bid = self._chip_group.checkedId()
        if bid < 0 or bid >= len(self._loader_options):
            return ""
        return self._loader_options[bid]

    def _filtered(self) -> list[dict]:
        mc = self.mc_filter.currentData() or ""
        ld = self._loader()
        return [v for v in self._versions
                if (not mc or mc in v.get("game_versions", []))
                and (not ld or ld in v.get("loaders", []))]

    # ---------- 数据加载（分页） ----------
    def _load_first_page(self):
        self.versions_lbl.setText(t("store.detail_loading"))
        self.more_btn.setEnabled(False)
        self._fetch_page(offset=0, append=False)

    def _load_more(self):
        self.more_btn.setEnabled(False)
        self._fetch_page(offset=self._offset, append=True)

    def _fetch_page(self, offset: int, append: bool):
        from .net_api import _modrinth_versions
        w = Worker(_modrinth_versions, self._card.get("project_id", ""),
                   "", "", PAGE_SIZE, offset)

        def _on_ok(page: list):
            self.more_btn.setEnabled(True)
            page = page if isinstance(page, list) else []
            self._has_more = len(page) >= PAGE_SIZE
            self._offset = offset + len(page)
            if append:
                # 追加前先剔除已存在 id，避免重复行
                exist = {v.get("id") for v in self._versions}
                self._versions.extend(v for v in page if v.get("id") not in exist)
            else:
                self._versions = page
            self._on_versions_ready(appending=append)

        def _on_err(e):
            self.more_btn.setEnabled(True)
            self.versions_lbl.setText(t("store.detail_ver_err", e=e))
            if not self._versions:
                self._latest_box.setVisible(False)

        w.finished.connect(_on_ok)
        w.error.connect(_on_err)
        self._track(w)
        w.start()

    def _on_versions_ready(self, appending: bool):
        self.versions_lbl.setText(t("store.detail_n_versions", n=len(self._versions)))

        # 最新版本条：全量第一条 = 最新（Modrinth 默认按发布时间倒序）
        if self._versions and not appending:
            self._fill_latest(self._versions[0])
            self._latest_box.setVisible(True)

        # MC 版本下拉聚合
        if not appending:
            seen = []
            for v in self._versions:
                for gv in v.get("game_versions", []):
                    if gv not in seen:
                        seen.append(gv)
            self.mc_filter.blockSignals(True)
            self.mc_filter.clear()
            self.mc_filter.addItem(t("store.detail_all_mc"), "")
            for gv in seen:
                self.mc_filter.addItem(gv, gv)
            self.mc_filter.blockSignals(False)

            # 加载器 chips：全量 + 各加载器
            seen_loaders = []
            for v in self._versions:
                for ld in v.get("loaders", []):
                    if ld not in seen_loaders:
                        seen_loaders.append(ld)
            for ld in seen_loaders:
                self._add_loader_chip(ld, ld)

        self.more_btn.setVisible(self._has_more)
        self.more_btn.setText(
            t("store.detail_more_n", n=len(self._versions) + PAGE_SIZE)
            if self._has_more else t("store.detail_all_loaded"))
        self.more_btn.setEnabled(self._has_more)
        self._rebuild_rows()

    def _fill_latest(self, v: dict):
        self.latest_ver.setText(v.get("version_number", "—"))
        files = v.get("files", [])
        if files:
            self.latest_ver.setToolTip(files[0].get("filename", ""))
        loaders = v.get("loaders", [])
        if loaders:
            text = ""
            for ld in loaders[:2]:
                colr = LOADER_BADGE_COLORS.get(ld.lower(), LOADER_DEFAULT)
                # round-91 去掉文本 ● 圆点：Windows 下可能渲染成彩色 emoji，
                # 加载器名本身已带品牌色，点多余。
                text += (f"<span style='color:{colr}; font-weight:700;'>{ld}</span>  ")
            self.latest_loader.setTextFormat(Qt.RichText)
            self.latest_loader.setText(text.strip())
        else:
            self.latest_loader.setText("—")
        gvs = v.get("game_versions", [])
        self.latest_mc.setText("MC " + ", ".join(gvs[:3]) if gvs else "")
        self.latest_size.setText(_human_size(files[0].get("size") if files else None))
        self.latest_date.setText((v.get("date_published", "") or "")[:10])
        self.latest_btn.setEnabled(True)
        self._latest_box.setVisible(True)

    # ---------- 行卡片渲染 ----------
    def _rebuild_rows(self, *_):
        # 清空旧行（保留末尾 stretch）
        while self._rows.count() > 1:
            item = self._rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        latest_id = self._versions[0].get("id") if self._versions else None
        for v in self._filtered():
            self._rows.insertWidget(self._rows.count() - 1,
                                    _VersionRow(self._rows_host, v,
                                                v.get("id") == latest_id,
                                                self._download_version))
        self.versions_lbl.setText(
            t("store.detail_shown", shown=len(self._filtered()),
              total=len(self._versions)))
        self.scroll.verticalScrollBar().setValue(0)

    # ---------- 下载 ----------
    def _download_latest(self):
        if self._versions:
            self._download_version(self._versions[0])

    def _download_version(self, v: dict):
        if self._inst is None:
            info(self, t("common.hint"), t("store.download_hint"))
            return
        reply = QMessageBox.question(
            self, t("store.download_confirm_title"),
            t("store.detail_ver_confirm",
              slug=self._card.get("slug", ""),
              ver=v.get("version_number", ""),
              name=self._inst.name),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from .net_api import download_mod_version_to, NetError
        dest = os.path.join(self._inst.game_dir, self._subdir)
        self.status.setText(t("store.downloading",
                              slug=self._card.get("slug", "")))
        w = Worker(
            download_mod_version_to,
            self._card.get("project_id", ""), v.get("id", ""), dest,
            getattr(self._inst, "game_version", "") or "",
            getattr(self._inst, "loader", "") or "",
        )

        def _ok(p: str):
            self.status.setText(t("store.downloaded", file=os.path.basename(p)))

        def _err(e):
            self.status.setText(t("store.download_fail", e=e))

        w.finished.connect(_ok)
        w.error.connect(_err)
        self._track(w)
        w.start()

    # ---------- 翻译 ----------
    def _translate(self):
        self.tr_status.setText(t("store.detail_translating"))
        self.translate_btn.setEnabled(False)
        w = Worker(_fetch_and_translate, self._card)

        def _ok(pair):
            self.translate_btn.setEnabled(True)
            src, tr = pair
            disp = tr if len(tr) <= 6000 else tr[:6000] + "…"
            self.text.setPlainText(
                f"── {t('store.detail_original')} ──\n{src[:1200] if len(src) > 1200 else src}"
                f"\n\n── {t('store.detail_translated')} ──\n{disp}"
            )
            self.tr_status.setText(t("store.detail_translated_ok"))

        def _err(e):
            self.translate_btn.setEnabled(True)
            self.tr_status.setText(t("store.detail_translate_fail", e=e))

        w.finished.connect(_ok)
        w.error.connect(_err)
        self._track(w)
        w.start()

    # ---------- 生命周期 ----------
    def _track(self, w):
        self._workers.append(w)
        w.finished.connect(lambda _p: self._retire(w))
        w.error.connect(lambda _e: self._retire(w))

    def _retire(self, w):
        try:
            self._workers.remove(w)
        except ValueError:
            pass

    def closeEvent(self, e):
        for w in self._workers:
            if w.isRunning():
                w.requestInterruption()
        super().closeEvent(e)


def _cat_key(category: str) -> str:
    """store 内部 project_type → i18n key（分类徽章文案）。"""
    return {
        "mod": "store.cat_mod", "modpack": "store.cat_modpack",
        "shader": "store.cat_shader", "resourcepack": "store.cat_respack",
        "datapack": "store.cat_datapack",
    }.get(category, "store.cat_mod")


def _type_slug(category: str) -> str:
    # store 内部 project_type → Modrinth URL path
    return {
        "mod": "mod", "modpack": "modpack", "shader": "shader",
        "resourcepack": "resourcepack", "datapack": "datapack",
    }.get(category, "mod")