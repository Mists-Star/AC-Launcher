"""模组列表（round-185 重做）—— 对齐 PCL2 / Prism 的模组管理页。

旧实现（``pages_instances.ModCard`` + 编辑面板里一串卡片）的问题：

* 名字取**文件名**，加载器徽章靠文件名子串猜 → 装 40 个模组时认不出谁是谁；
* 没有搜索、没有筛选、没有多选、没有全选 → 只能一条条滚、一条条点；
* 每张卡 74px，一屏 6 条。

本文件按 PCL2 的 ``PageInstanceMod`` 重做：

    搜索框（名称 / 描述 / 作者 / 文件名）
    工具条：添加模组 · 打开文件夹 · 刷新 · 全选
    筛选：全部 / 已启用 / 已禁用 / 可更新
    列表：紧凑行（图标 · 名称 · 版本 · 作者 · 描述 · 启用开关）
    选中后底部浮条：已选 N 项 → 启用 / 禁用 / 删除 / 更新 / 取消

真实名称/版本/描述/图标来自 :mod:`core.modmeta`（读 jar 里的
``fabric.mod.json`` / ``quilt.mod.json`` / ``META-INF/mods.toml`` / ``mcmod.info``）。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from . import ui_kit
from .core import modmeta
from .i18n import loader_name, t
from .icons import pixmap as icon_pixmap, pixmap_large
from .theme import COLORS
from .win_rounded import confirm, toast, warn
from .worker import Worker

_ROW_H = 58
_ICON = 34


# ── 小工具 ───────────────────────────────────────────────────────────────────
def _round_pixmap(src: QPixmap, size: int) -> QPixmap:
    """把图标裁成圆角方块（模组自带的 logo 多为直角 PNG，直接放很突兀）。"""
    if src.isNull():
        return src
    scaled = src.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, 9, 9)
    p.setClipPath(path)
    p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2,
                 scaled)
    p.end()
    return out


def mod_icon(meta: dict | None, size: int = _ICON) -> QPixmap:
    """jar 里的图标 → 圆角 pixmap；没有就退回通用字形。"""
    data = (meta or {}).get("icon") or b""
    if data:
        img = QImage.fromData(data)
        if not img.isNull():
            pm = QPixmap.fromImage(img)
            if not pm.isNull():
                return _round_pixmap(pm, size)
    return icon_pixmap("mods", size)


def _elide(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _wrap_by_width(text: str, fm, width: int, max_lines: int = 2) -> str:
    """按**像素宽度**折行，最多 *max_lines* 行；放不下的部分在末行省略。

    round-195：原来描述是按**字符数**砍到 78（``_elide(desc, 78)``），
    「Fabric API」的描述被砍成 "FabricMC · Core API module providing key ho" ——
    玩家看到的是半句话。加上一句 "Core API module providing key hooks…" 这种
    断法还不如直接显示两行完整。
    """
    text = " ".join((text or "").split())
    if not text or width <= 40:
        return text
    lines: list[str] = []
    cur = ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if fm.horizontalAdvance(trial) <= width or not cur:
            cur = trial
            continue
        lines.append(cur)
        cur = word
        if len(lines) >= max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if not lines:
        return text
    if len(lines) == max_lines:
        # 最后一行可能还有被截掉的尾巴 → 用 elidedText 收尾
        consumed = " ".join(lines)
        rest = text[len(consumed):].strip()
        if rest:
            lines[-1] = fm.elidedText(lines[-1] + " " + rest,
                                      Qt.ElideRight, width)
    return "\n".join(lines)


class ModRow(QFrame):
    """列表里的一行。勾选框负责批量选择，右侧按钮负责启停。"""

    toggled = Signal(str, bool)   # path, want_enabled
    selection_changed = Signal()

    def __init__(self, path: str, enabled: bool, meta: dict | None,
                 parent=None, source: dict | None = None):
        super().__init__(parent)
        self.path = path
        self.enabled = enabled
        self.meta = meta or {}
        self.source = source or {}
        self.setObjectName("modRow")
        self.setFixedHeight(_ROW_H)
        self.setCursor(Qt.PointingHandCursor)
        # ☠ 全局 QSS 的 checkbox 选中态是「一块纯紫方块」，没有勾形标记 ——
        # 列表里几十行都这样，分不清是「已勾选」还是「一个色块」。
        # 这里靠**整行高亮**表达选中（PCL 也是整行变色），勾选框只做开关。
        self.setStyleSheet(
            "#modRow { background: transparent; border-radius: 9px;"
            " border-left: 3px solid transparent; }"
            "#modRow:hover { background: %s; }"
            "#modRow[selected=\"true\"] { background: %s;"
            " border-left: 3px solid %s; }"
            % (COLORS["bg_hover"], COLORS["bg_frost"], COLORS["accent"]))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(11)

        self.check = QCheckBox()
        self.check.setFixedWidth(20)
        self.check.stateChanged.connect(self._on_check)
        lay.addWidget(self.check)

        tile = QLabel()
        tile.setFixedSize(_ICON, _ICON)
        tile.setPixmap(mod_icon(self.meta, _ICON))
        tile.setStyleSheet("background:%s;border-radius:9px;"
                           % COLORS["bg_frost"])
        lay.addWidget(tile)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.name_lbl = QLabel(modmeta.display_name(path, self.meta))
        self.name_lbl.setStyleSheet(
            "font-size:13px;font-weight:600;color:%s;" % COLORS["text_main"])
        top.addWidget(self.name_lbl)
        ver = (self.meta.get("version") or "").strip()
        self.version = ver          # 给筛选/测试用，别只画出来
        if ver:
            top.addWidget(self._pill(ver))
        ldr = (self.meta.get("loader") or "").strip()
        if ldr:
            top.addWidget(self._pill(loader_name(ldr), dim=True))
        # round-191/197：区分来源 —— 「资源中心 / 整合包 / 导入 / 手动放入」。
        # round-197：整合包与导入带来的 jar 也要标出来（它们本来没有可靠的
        # project_id，但玩家需要知道"这不是我手动放的"）。
        _src = str(self.source.get("source") or "")
        if _src in ("modrinth", "curseforge"):
            src_pill = self._pill(t("mods.from_store"), dim=True)
            src_pill.setToolTip(
                t("mods.from_store_tip",
                  slug=self.source.get("slug") or self.source.get("title", "")))
            top.addWidget(src_pill)
        elif _src in ("modpack", "imported"):
            key = ("mods.from_pack" if _src == "modpack"
                   else "mods.from_import")
            src_pill = self._pill(t(key), dim=True)
            src_pill.setToolTip(
                t("mods.from_pack_tip", name=self.source.get("title", "")))
            top.addWidget(src_pill)
        top.addStretch(1)
        col.addLayout(top)

        authors = list(self.meta.get("authors") or [])
        self._authors_txt = ", ".join(authors[:3])
        self._desc_full = (self.meta.get("description") or "").strip()
        self._fallback = os.path.basename(path)

        head2 = QLabel(self._authors_txt or self._fallback)
        head2.setStyleSheet("font-size:11px;color:%s;" % COLORS["text_sub"])
        if self._authors_txt:
            head2.setToolTip(self._authors_txt)
        col.addWidget(head2)

        # 描述：按像素宽度折成最多两行，随窗口宽度重排；悬停给全文。
        self.desc_lbl = QLabel("")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setStyleSheet("font-size:11px;color:%s;"
                                    % COLORS["text_sub"])
        if self._desc_full:
            self.desc_lbl.setToolTip(self._desc_full)
            col.addWidget(self.desc_lbl)
        self._desc_width = 0
        self._relayout_desc()
        # round-210 P0：列表刷新会先 deleteLater 旧行，QTimer(0) 的回调可能在
        # C++ 对象已销毁后才派发 → 访问 self.desc_lbl 抛
        # 「wrapped C/C++ object ... has been deleted」并写进 crash.log
        # （真机同一位置累计 705 条）。用 safe 包装吞掉对象已死的回调。
        QTimer.singleShot(0, self._relayout_desc_safe)
        lay.addLayout(col, 1)

        self.toggle_btn = ui_kit.make_button(
            t("mods.disable") if enabled else t("mods.enable"),
            kind="secondary", min_h=28)
        self.toggle_btn.setFixedWidth(64)
        self.toggle_btn.clicked.connect(
            lambda: self.toggled.emit(self.path, not self.enabled))
        lay.addWidget(self.toggle_btn)

        if not enabled:
            self.name_lbl.setStyleSheet(
                "font-size:13px;font-weight:600;color:%s;"
                % COLORS["text_sub"])

    def _on_check(self, _state: int) -> None:
        self.setProperty("selected", "true" if self.check.isChecked() else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.selection_changed.emit()

    def resizeEvent(self, ev) -> None:  # noqa: N802 - Qt 命名
        """窗口变宽变窄时，描述要按新宽度重新折行（不能只按旧宽度排一次）。"""
        super().resizeEvent(ev)
        self._relayout_desc()

    def _relayout_desc_safe(self) -> None:
        """异步重排入口：行已被销毁时静默跳过，不写崩溃日志。"""
        try:
            self._relayout_desc()
        except RuntimeError:
            # PySide6 对象已 deleteLater → Qt wrapper 失效，属于正常刷新竞态。
            return

    def _relayout_desc(self) -> None:
        """按当前可用宽度重排描述（最多两行）。

        构造时行还没布局（width=0）→ 用默认宽度 620 排一次，等第一次
        resizeEvent 再按真实宽度重排。对象销毁后所有 Qt 访问都要能安全退化。
        """
        try:
            if not getattr(self, "_desc_full", ""):
                return
            fm = self.desc_lbl.fontMetrics()
            w = self.width()
            avail = max(160, (w - 210) if w > 400 else 620)
            if abs(avail - getattr(self, "_desc_width", 0)) < 24:
                return
            self._desc_width = avail
            self.desc_lbl.setText(
                _wrap_by_width(self._desc_full, fm, avail, 2))
        except RuntimeError:
            return

    @staticmethod
    def _pill(text: str, dim: bool = False) -> QLabel:
        lb = QLabel(text)
        lb.setStyleSheet(
            "font-size:10px;padding:1px 6px;border-radius:6px;"
            "background:%s;color:%s;"
            % (COLORS["bg_frost"],
               COLORS["text_sub"] if dim else COLORS["text_main"]))
        return lb

    def mousePressEvent(self, ev) -> None:  # noqa: N802 - Qt 命名
        # 点行任意空白处也能勾选（PCL 就是整行可选）：勾选框 18px 太小，
        # 40 行时每行都要精准点那个小方块很难受。子控件（启停按钮）会自己
        # 吃掉事件，不会误触。
        if ev.button() == Qt.LeftButton and not self.check.geometry().contains(
                ev.position().toPoint()):
            self.check.setChecked(not self.check.isChecked())
        super().mousePressEvent(ev)

    def is_checked(self) -> bool:
        return self.check.isChecked()

    def set_checked(self, on: bool) -> None:
        self.check.setChecked(on)


class ModListPanel(QWidget):
    """一个实例的模组管理面板（搜索 / 筛选 / 批量）。"""

    changed = Signal()          # 磁盘上的 mods 目录变了（外层刷新状态用）

    def __init__(self, parent, inst, *, on_open_folder=None):
        super().__init__(parent)
        self._inst = inst
        self._rows: list[ModRow] = []
        self._all: list[ModRow] = []       # 不过滤的全集（筛选后重建）
        self._updatable: dict[str, dict] = {}
        self._updating = False
        self._on_open_folder = on_open_folder

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)

        # ── 搜索 ──
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("mods.search_hint"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _s: self._apply_filter())
        root.addWidget(self.search)

        # ── 工具条 ──
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.add_btn = ui_kit.make_button(
            t("inst.mods_add"), kind="accent", icon_key="add",
            on_click=self._add_files, min_h=32)
        bar.addWidget(self.add_btn)
        bar.addWidget(ui_kit.make_button(
            t("inst.open_folder"), kind="secondary", icon_key="folder",
            on_click=self._open_folder, min_h=32))
        bar.addWidget(ui_kit.make_button(
            t("inst.mods_refresh"), kind="secondary", icon_key="refresh",
            on_click=self.reload, min_h=32))
        bar.addStretch(1)
        self.sel_all_btn = ui_kit.make_button(
            t("mods.select_all"), kind="secondary", on_click=self._toggle_all,
            min_h=32)
        bar.addWidget(self.sel_all_btn)
        root.addLayout(bar)

        # ── 筛选 ──
        self.chips = ui_kit.ChipGroup([
            ("all", t("mods.filter_all")),
            ("on", t("mods.filter_enabled")),
            ("off", t("mods.filter_disabled")),
            ("upd", t("mods.filter_updatable")),
        ], on_change=self._on_chip)
        self.chips.set("all")
        # 不给 Max 尺寸策略的话 QHBoxLayout 会把 4 个 chip 拉成四等分，
        # 每个都撑到 190px —— PCL 是左侧一排紧凑按钮
        self.chips.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        root.addWidget(self.chips)

        self.path_lbl = QLabel("")
        self.path_lbl.setStyleSheet("font-size:10px;color:%s;"
                                    % COLORS["text_sub"])
        self.path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.path_lbl)

        # ── 列表 ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.list_lay = QVBoxLayout(holder)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(2)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(holder)
        root.addWidget(self.scroll, 1)

        self.empty_box = QWidget()
        self.empty_lay = QVBoxLayout(self.empty_box)
        self.empty_lay.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.empty_box)
        self.empty_box.setVisible(False)

        # ── 批量条 ──
        self.batch = QFrame()
        self.batch.setObjectName("modBatch")
        self.batch.setStyleSheet(
            "#modBatch { background:%s; border:1px solid %s;"
            " border-radius:10px; }"
            % (COLORS["bg_frost"], COLORS["border"]))
        bl = QHBoxLayout(self.batch)
        bl.setContentsMargins(12, 8, 10, 8)
        bl.setSpacing(8)
        self.batch_lbl = QLabel("")
        self.batch_lbl.setStyleSheet("font-size:12px;color:%s;"
                                     % COLORS["text_main"])
        bl.addWidget(self.batch_lbl)
        bl.addStretch(1)
        self.en_btn = ui_kit.make_button(
            t("mods.enable"), kind="secondary", on_click=self._batch_enable,
            min_h=28)
        self.dis_btn = ui_kit.make_button(
            t("mods.disable"), kind="secondary", on_click=self._batch_disable,
            min_h=28)
        self.upd_btn = ui_kit.make_button(
            t("mods.update_selected"), kind="secondary",
            on_click=self._batch_update, min_h=28)
        self.del_btn = ui_kit.make_button(
            t("inst.content_delete"), kind="danger",
            on_click=self._batch_delete, min_h=28)
        self.clear_btn = ui_kit.make_button(
            t("mods.clear_selection"), kind="secondary",
            on_click=self._clear_selection, min_h=28)
        for b in (self.upd_btn, self.en_btn, self.dis_btn, self.del_btn,
                  self.clear_btn):
            bl.addWidget(b)
        root.addWidget(self.batch)
        self.batch.setVisible(False)

        self._build_empty()
        self.reload()

    # ── 空态 ────────────────────────────────────────────────────────────────
    def _build_empty(self) -> None:
        acts = QHBoxLayout()
        acts.setSpacing(10)
        acts.setAlignment(Qt.AlignCenter)
        acts.addWidget(ui_kit.make_button(
            t("mods.empty_install"), kind="accent", icon_key="add",
            on_click=self._add_files, min_h=34))
        acts.addWidget(ui_kit.make_button(
            t("mods.empty_open"), kind="secondary", icon_key="folder",
            on_click=self._open_folder, min_h=34))
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)
        bl.setAlignment(Qt.AlignCenter)
        ic = QLabel()
        ic.setPixmap(pixmap_large("mods", 56))
        ic.setAlignment(Qt.AlignCenter)
        bl.addWidget(ic, alignment=Qt.AlignCenter)
        tt = QLabel(t("inst.mods_empty_title"))
        tt.setAlignment(Qt.AlignCenter)
        tt.setStyleSheet("font-size:14px;font-weight:700;color:%s;"
                         % COLORS["text_main"])
        bl.addWidget(tt, alignment=Qt.AlignCenter)
        hint = QLabel(t("mods.empty_hint"))
        hint.setWordWrap(True)
        hint.setMaximumWidth(430)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("font-size:11px;color:%s;" % COLORS["text_sub"])
        bl.addWidget(hint, alignment=Qt.AlignCenter)
        bl.addLayout(acts)
        self.empty_lay.addWidget(box)

    # ── 数据 ────────────────────────────────────────────────────────────────
    def reload(self) -> None:
        """重读 mods 目录并重建行。"""
        while self.list_lay.count() > 1:
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows = []
        self._all = []

        try:
            d = self._inst.mods_dir
            os.makedirs(d, exist_ok=True)
            names = sorted(os.listdir(d))
        except OSError as exc:
            self.path_lbl.setText(str(exc))
            self._update_empty()
            return
        self.path_lbl.setText(d)

        jars = [n for n in names if n.lower().endswith((".jar", ".jar.disabled"))]
        # round-191：来源表（资源中心下载的才有记录）
        try:
            from .core import mod_sources
            self._sources = mod_sources.load(self._inst)
            mod_sources.prune(self._inst, jars)
        except Exception:  # noqa: BLE001 - 记录不可用不影响列表
            self._sources = {}
        for name in jars:
            path = os.path.join(d, name)
            enabled = not name.endswith(".disabled")
            meta = modmeta.read_meta(path)
            row = ModRow(path, enabled, meta,
                         source=self._sources.get(name))
            row.toggled.connect(self._toggle)
            row.selection_changed.connect(self._on_selection)
            self._all.append(row)
            self.list_lay.insertWidget(self.list_lay.count() - 1, row)
        self._apply_filter()
        self._update_empty()

    def _update_empty(self) -> None:
        has = bool(self._all)
        self.empty_box.setVisible(not has)
        self.scroll.setVisible(has)
        self.chips.setVisible(has)
        self.path_lbl.setVisible(has)

    def _on_chip(self, key: str) -> None:
        if key == "upd":
            self._check_updates()
        self._apply_filter()

    def _apply_filter(self) -> None:
        mode = self.chips.current() or "all"
        q = self.search.text().strip().lower()
        for row in self._all:
            show = True
            if mode == "on":
                show = row.enabled
            elif mode == "off":
                show = not row.enabled
            elif mode == "upd":
                show = row.path in self._updatable
            if show and q:
                show = q in modmeta.search_blob(row.path, row.meta)
            row.setVisible(show)
        self._on_selection()

    # ── 选择 ────────────────────────────────────────────────────────────────
    def _visible(self) -> list[ModRow]:
        return [r for r in self._all if not r.isHidden()]

    def _selected(self) -> list[ModRow]:
        return [r for r in self._all if r.is_checked()]

    def _toggle_all(self) -> None:
        vis = self._visible()
        on = not all(r.is_checked() for r in vis) if vis else False
        for r in vis:
            r.set_checked(on)
        self._on_selection()

    def _clear_selection(self) -> None:
        for r in self._all:
            r.set_checked(False)
        self._on_selection()

    def _on_selection(self) -> None:
        sel = self._selected()
        self.batch.setVisible(bool(sel))
        self.batch_lbl.setText(t("mods.selected_n", n=len(sel)))
        has_upd = any(r.path in self._updatable for r in sel)
        self.upd_btn.setVisible(has_upd)
        self.sel_all_btn.setText(
            t("mods.clear_selection")
            if sel and len(sel) == len(self._visible())
            else t("mods.select_all"))

    # ── 操作 ────────────────────────────────────────────────────────────────
    def _open_folder(self) -> None:
        if self._on_open_folder is not None:
            self._on_open_folder(self._inst.mods_dir)
            return
        try:
            os.startfile(self._inst.mods_dir)  # noqa: S606 - Windows 打开目录
        except Exception as exc:  # noqa: BLE001
            warn(self, t("inst.open_folder"), str(exc))

    def _add_files(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        files, _f = QFileDialog.getOpenFileNames(
            self, t("inst.mods_add"), "", t("mods.pick_filter"))
        if not files:
            return
        n = 0
        for src in files:
            try:
                dst = os.path.join(self._inst.mods_dir, os.path.basename(src))
                if os.path.abspath(src) == os.path.abspath(dst):
                    continue
                with open(src, "rb") as fh, open(dst, "wb") as out:
                    out.write(fh.read())
                n += 1
            except OSError as exc:
                warn(self, t("inst.mods_add"), str(exc))
        if n:
            toast(self, t("inst.mods_add"), t("inst.mods_added", n=n))
        self.reload()
        self.changed.emit()

    def _toggle(self, path: str, want_enabled: bool) -> None:
        try:
            if want_enabled and path.endswith(".disabled"):
                os.replace(path, path[: -len(".disabled")])
            elif not want_enabled and not path.endswith(".disabled"):
                os.replace(path, path + ".disabled")
        except OSError as exc:
            warn(self, t("mods.fail_title"), str(exc))
        self.reload()
        self.changed.emit()

    def _batch_enable(self, want: bool = True) -> None:
        for row in self._selected():
            p = row.path
            try:
                if want and p.endswith(".disabled"):
                    os.replace(p, p[: -len(".disabled")])
                elif not want and not p.endswith(".disabled"):
                    os.replace(p, p + ".disabled")
            except OSError:
                continue
        self.reload()
        self.changed.emit()

    def _batch_disable(self) -> None:
        self._batch_enable(False)

    def _batch_delete(self) -> None:
        sel = self._selected()
        if not sel:
            return
        if not confirm(self, t("inst.content_delete"),
                       t("mods.delete_n", n=len(sel))):
            return
        gone = 0
        for row in sel:
            try:
                os.remove(row.path)
                gone += 1
            except OSError:
                continue
        if gone:
            toast(self, t("inst.content_delete"),
                  t("mods.deleted_n", n=gone))
        self.reload()
        self.changed.emit()

    # ── 更新检查（复用 mod_updater，网络失败不影响列表）────────────────────
    def _check_updates(self) -> None:
        if self._updatable:
            return
        from .mod_updater import check_updates
        from .core import mod_sources
        app = self
        self.chips.set_text("upd", t("mods.filter_checking"))
        try:
            _smap = mod_sources.slug_map(self._inst)
        except Exception:  # noqa: BLE001
            _smap = {}
        w = Worker(check_updates, self._inst, slug_map=_smap)
        app._upd_worker = w

        def _fin(res) -> None:
            # ☠ check_updates 回的是 filename（不是 path）—— 直接当路径用会
            # 悄悄一条都对不上，表现为「检查完还是 0 个可更新」。
            updates = (res or {}).get("updates") if isinstance(res, dict) else None
            base = ""
            try:
                base = app._inst.mods_dir
            except Exception:  # noqa: BLE001
                base = ""
            for u in updates or []:
                fn = u.get("filename") or ""
                if fn and base:
                    app._updatable[os.path.join(base, fn)] = u
            app.chips.set_text(
                "upd", t("mods.filter_updatable_n", n=len(app._updatable)))
            app._apply_filter()

        def _err(_e) -> None:
            app.chips.set_text("upd", t("mods.filter_updatable"))
            app.chips.set("all")
            toast(self, t("mods.update_check_failed"))

        w.finished.connect(_fin)
        w.error.connect(_err)
        w.start()

    def _batch_update(self) -> None:
        sel = [r for r in self._selected() if r.path in self._updatable]
        if not sel or self._updating:
            return
        from .mod_updater import update_mods
        updates = [self._updatable[r.path] for r in sel]
        self._updating = True
        self.upd_btn.setEnabled(False)
        self.batch_lbl.setText(t("mods.updating", n=len(updates)))
        w = Worker(update_mods, self._inst, updates)
        self._upd2 = w

        def _fin(n) -> None:
            self._updating = False
            self.upd_btn.setEnabled(True)
            self._updatable.clear()
            self.chips.set_text("upd", t("mods.filter_updatable"))
            self.reload()
            toast(self, t("mods.update_selected"), t("mods.updated_n", n=n or 0))

        def _err(e) -> None:
            self._updating = False
            self.upd_btn.setEnabled(True)
            warn(self, t("mods.update_selected"), str(e))

        w.finished.connect(_fin)
        w.error.connect(_err)
        w.start()
