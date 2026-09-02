"""Store detail dialog — per-mod info, version picker, translate, download.

round-66 资源中心详情页：
* 展示项目信息（图标 / 标题 / 作者 / 下载量 / 简介）
* 列出该资源的**全部版本**（Modrinth versions API），可按 MC 版本过滤，
  选中任意版本下载（含依赖树，download_mod_version_to）
* "获取翻译"：用免费在线翻译把简介/README 机翻成中文（无需 API key）
* 一键打开 Modrinth 官网详情页

挂在后台 Worker(QThread) 上执行网络请求，绝不阻塞 UI；所有错误体现在
对话框内状态显示而不是崩溃。
"""
from __future__ import annotations

import os
import re

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QComboBox, QTextEdit, QMessageBox, QAbstractItemView,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

from .theme import COLORS
from .i18n import t
from .worker import Worker
from .async_image import ImageLoader
from .win_rounded import info


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


class StoreDetailDialog(QDialog):
    """资源中心详情：信息 + 全部版本选择 + 获取翻译 + 下载到目标实例。"""

    def __init__(self, parent, card: dict, category: str, inst, subdir: str):
        super().__init__(parent)
        self._card = card
        self._category = category
        self._inst = inst
        self._subdir = subdir
        self._versions: list[dict] = []
        self._workers: list = []
        self._img = ImageLoader(self)

        self.setWindowTitle(t("store.detail_title"))
        self.setModal(True)
        self.setMinimumSize(720, 560)
        self.resize(760, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        # ── 头部：图标 + 标题 + 元信息 ──
        head = QHBoxLayout()
        head.setSpacing(14)
        self.thumb = QLabel()
        self.thumb.setFixedSize(56, 56)
        head.addWidget(self.thumb)

        ti = QVBoxLayout()
        ti.setSpacing(3)
        self.title = QLabel(card.get("title", ""))
        self.title.setProperty("cls", "title")
        self.title.setStyleSheet("font-size: 17px; font-weight: 700;")
        self.meta = QLabel(t("store.meta",
                             downloads=card.get("downloads", 0),
                             author=card.get("author", "")))
        self.meta.setProperty("cls", "sub")
        self.desc = QLabel(self._short(card.get("description", ""), 160))
        self.desc.setProperty("cls", "sub")
        self.desc.setWordWrap(True)
        ti.addWidget(self.title)
        ti.addWidget(self.meta)
        ti.addWidget(self.desc)
        head.addLayout(ti, stretch=1)

        self.open_btn = QPushButton(t("store.detail_open"))
        self.open_btn.setProperty("cls", "surface")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        link = (f"https://modrinth.com/{_type_slug(self._category)}/"
                f"{card.get('slug') or card.get('project_id')}")
        self.open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(link)))
        head.addWidget(self.open_btn, alignment=Qt.AlignTop)
        root.addLayout(head)

        if self._img and card.get("icon_url"):
            from PySide6.QtGui import QPixmap
            fb = QPixmap(56, 56)
            fb.fill(Qt.transparent)
            self._img.load(card.get("icon_url", ""), 56, self.thumb, fb)

        # ── 版本区 ──
        self.filter_lbl = QLabel(t("store.detail_filter"))
        self.filter_lbl.setProperty("cls", "sub")
        ver_bar = QHBoxLayout()
        ver_bar.addWidget(self.filter_lbl)
        self.mc_filter = QComboBox()
        self.mc_filter.setProperty("cls", "surface")
        self.mc_filter.setMinimumWidth(170)
        self.mc_filter.currentIndexChanged.connect(self._apply_filter)
        ver_bar.addWidget(self.mc_filter)
        ver_bar.addStretch(1)

        self.versions_lbl = QLabel(t("store.detail_loading"))
        self.versions_lbl.setProperty("cls", "sub")
        ver_bar.addWidget(self.versions_lbl, alignment=Qt.AlignRight)
        root.addLayout(ver_bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            t("store.detail_col_version"), t("store.detail_col_mc"),
            t("store.detail_col_loader"), t("store.detail_col_date"),
            t("store.detail_col_file"),
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 100)
        self.table.itemDoubleClicked.connect(lambda _i: self._download_selected())
        self.table.setMinimumHeight(230)
        root.addWidget(self.table, stretch=1)

        # ── 翻译区 ──
        tl_row = QHBoxLayout()
        self.translate_btn = QPushButton(t("store.detail_translate"))
        self.translate_btn.setProperty("cls", "surface")
        self.translate_btn.setCursor(Qt.PointingHandCursor)
        self.translate_btn.clicked.connect(self._translate)
        tl_row.addWidget(self.translate_btn)
        self.tr_status = QLabel("")
        self.tr_status.setProperty("cls", "sub")
        tl_row.addWidget(self.tr_status, stretch=1)
        root.addLayout(tl_row)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText(t("store.detail_text_hint"))
        self.text.setMaximumHeight(120)
        root.addWidget(self.text)

        # ── 底部操作 ──
        self.status = QLabel("")
        self.status.setProperty("cls", "sub")
        root.addWidget(self.status)

        self.dl_btn = QPushButton(t("store.detail_download"))
        self.dl_btn.setProperty("cls", "accent")
        self.dl_btn.setCursor(Qt.PointingHandCursor)
        self.dl_btn.clicked.connect(self._download_selected)
        self.close_btn = QPushButton(t("common.cancel"))
        self.close_btn.setProperty("cls", "secondary")
        self.close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.dl_btn)
        btn_row.addWidget(self.close_btn)
        root.addLayout(btn_row)

        self._load_versions()

    # ---------- helpers ----------
    def _short(self, s: str, n: int) -> str:
        s = (s or "").strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    def _load_versions(self):
        from .net_api import _modrinth_versions
        self.dl_btn.setEnabled(False)
        w = Worker(_modrinth_versions, self._card.get("project_id", ""))
        w.finished.connect(self._on_versions)
        w.error.connect(lambda e: self.versions_lbl.setText(
            t("store.detail_ver_err", e=e)))
        self._track(w)
        w.start()

    def _track(self, w):
        self._workers.append(w)
        w.finished.connect(lambda _p: self._retire(w))
        w.error.connect(lambda _e: self._retire(w))

    def _retire(self, w):
        try:
            self._workers.remove(w)
        except ValueError:
            pass

    def _on_versions(self, versions: list[dict]):
        self._versions = versions if isinstance(versions, list) else []
        self.versions_lbl.setText(t("store.detail_n_versions", n=len(self._versions)))
        # 过滤下拉：聚合所有版本支持的 MC 版本（保持首次出现顺序）
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
        self._apply_filter()
        self.dl_btn.setEnabled(bool(self._versions))

    def _apply_filter(self, *_):
        mc = self.mc_filter.currentData() or ""
        rows = [v for v in self._versions
                if (not mc) or mc in v.get("game_versions", [])]
        self.table.setRowCount(len(rows))
        # round-66 修：行号映射必须按**过滤后** rows 的枚举，不能按全量
        # self._versions 的索引——此前过滤后选中行会取到全量里的错位版本。
        self._row_map = {i: v for i, v in enumerate(rows)}
        for i, v in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(v.get("version_number", "")))
            self.table.setItem(i, 1, QTableWidgetItem(", ".join(v.get("game_versions", []))))
            self.table.setItem(i, 2, QTableWidgetItem(", ".join(v.get("loaders", []))))
            self.table.setItem(i, 3, QTableWidgetItem((v.get("date_published", "") or "")[:10]))
            files = v.get("files", [])
            fname = files[0].get("filename", "") if files else ""
            self.table.setItem(i, 4, QTableWidgetItem(fname))
        # round-66：过滤切换后默认选中第一行——避免选了版本再切过滤
        # 后"当前行"被清空，用户以为没版本可选。
        if self.table.rowCount() > 0:
            self.table.setCurrentCell(0, 0)

    def _selected_version(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or not hasattr(self, "_row_map"):
            return None
        return self._row_map.get(row)

    def _download_selected(self):
        v = self._selected_version()
        if v is None:
            info(self, t("common.hint"), t("store.detail_pick_first"))
            return
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
        self.dl_btn.setEnabled(False)
        self.status.setText(t("store.downloading",
                              slug=self._card.get("slug", "")))
        w = Worker(
            download_mod_version_to,
            self._card.get("project_id", ""), v.get("id", ""), dest,
            getattr(self._inst, "game_version", "") or "",
            getattr(self._inst, "loader", "") or "",
        )

        def _ok(p: str):
            self.dl_btn.setEnabled(True)
            self.status.setText(t("store.downloaded", file=os.path.basename(p)))

        def _err(e):
            self.dl_btn.setEnabled(True)
            self.status.setText(t("store.download_fail", e=e))

        w.finished.connect(_ok)
        w.error.connect(_err)
        self._track(w)
        w.start()

    def _translate(self):
        self.tr_status.setText(t("store.detail_translating"))
        self.translate_btn.setEnabled(False)
        w = Worker(_fetch_and_translate, self._card)

        def _ok(pair):
            self.translate_btn.setEnabled(True)
            src, tr = pair
            # 译文太长时截断，避免整个对话框被撑到不可读
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

    def closeEvent(self, e):
        for w in self._workers:
            if w.isRunning():
                w.requestInterruption()
        super().closeEvent(e)


def _type_slug(category: str) -> str:
    # store 内部 project_type → Modrinth URL path
    return {
        "mod": "mod", "modpack": "modpack", "shader": "shader",
        "resourcepack": "resourcepack", "datapack": "datapack",
    }.get(category, "mod")