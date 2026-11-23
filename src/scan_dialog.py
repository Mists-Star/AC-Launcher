"""扫描导入面板 —— 发现本机其他启动器的实例，按需导入成 AC 实例。

模块边界（round-243 重整）
-------------------------
* :mod:`src.scan`           —— **纯发现逻辑**（遍历磁盘，不碰 Qt）
* :class:`_ScanJob`         —— 发现逻辑的线程壳，把 progress / on_found 转成信号
* :class:`_ScanRow`         —— 一条发现的「卡片行」（纯表现）
* :class:`_GroupBlock`      —— 按启动器分组的可折叠区块
* :class:`ScanPanel`        —— 组装以上三者 + 导入流程（本文件）
* :class:`ScanDialog`       —— 无边框弹窗外壳（保留给旧调用点）

设计要点
--------
1. **边扫边出结果**：``discover_instances`` 新增的 ``on_found`` 回调把每条发现
   立刻推上来，不再等整盘扫完（以前几十秒里结果区一片空白）。
2. **实时路径**：``progress`` 回调收到的目录写在状态条上（中间省略），玩家能
   看见"还在动"，而不是对着一条满格的不确定进度条猜。
3. **可停止**：扫描中「开始扫描」变成「停止扫描」，点一下立刻收工并保留已发现
   的结果（``should_stop`` 早就支持，只是以前没接到 UI 上）。
4. **已导入判定走 manager**：以前只在内存 set 里记本次会话导入过的目录，重开
   面板后已导入的实例又显示成"未导入"。现在直接比对 manager 里实例的 mc_dir。
5. **导入后不再重扫**：以前手动导入一个文件夹后要重新跑整盘扫描，现在直接把
   这条结果插进列表。
"""
from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import Qt, QSize, QTimer, Signal, QThread
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QProgressDialog, QPushButton, QScrollArea, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from .icons import icon
from . import ui_kit
from .theme import COLORS, RoundedCard, with_alpha
from .i18n import t
from .worker import Worker
from .scan import discover_instances, ScannedInstance
from .instances import manager as instances_manager, _CopyFailed, launcher_label
from .frameless import FramelessHelper, TitleBar
from .win_rounded import _msgbox, info, warn


# ────────────────────────────────────────────────── 数据侧：已导入判定
def _norm_path(p: str) -> str:
    return os.path.normcase(os.path.abspath(p)) if p else ""


def _inst_key(dir_: str, version: str) -> str:
    return "%s|%s" % (dir_, version or "*")


def managed_index() -> set[str]:
    """AC 当前**已经管着**的实例索引（持久事实，不看内存状态）。

    键有两种形态：

    * ``<目录>|<版本ID>`` —— 链接进来的共享 .minecraft：AC 只接管了其中一个
      版本，同目录下别的版本仍然可以导入；
    * ``<目录>|*``        —— AC 自有的独立目录（``_base`` 为空，目录归实例独占）。

    以前"已导入"只是面板里的一个内存 set，重开面板后已导入的实例又变回
    "待导入"，玩家会重复导入。
    """
    out: set[str] = set()
    try:
        insts = instances_manager().list()
    except Exception:  # noqa: BLE001 - 实例库异常不该让扫描页打不开
        return out
    for inst in insts:
        try:
            dir_ = _norm_path(inst.mc_dir)
        except Exception:  # noqa: BLE001
            continue
        if not dir_:
            continue
        version = ""
        try:
            version = getattr(inst, "version_id", "") or ""
            owned = not (getattr(inst, "_base", "") or "")
        except Exception:  # noqa: BLE001
            owned = True
        out.add(_inst_key(dir_, "") if (owned or not version)
                else _inst_key(dir_, version))
    return out


def is_imported(inst: ScannedInstance, index: set[str]) -> bool:
    dir_ = _norm_path(inst.mc_dir)
    return (_inst_key(dir_, getattr(inst, "version_id", "") or "") in index
            or _inst_key(dir_, "") in index)


def _short_path(path: str, limit: int = 76) -> str:
    """中间省略路径：``C:\\Users\\…\\instances\\foo``。"""
    p = path or ""
    if len(p) <= limit:
        return p
    head = max(10, (limit - 3) // 3)
    tail = limit - 3 - head
    return p[:head] + "…" + p[-tail:]


def _content_tags(inst: ScannedInstance) -> list[str]:
    """实例内容的角标：只显示非零项，避免一排「Mods 0」。"""
    pairs = (
        ("scan.mods", inst.mods),
        ("scan.respacks", inst.resource_packs),
        ("scan.shaders", inst.shaders),
        ("scan.saves", inst.saves),
    )
    return ["%s %d" % (t(k), int(v)) for k, v in pairs if v]


# ────────────────────────────────────────────────── 表现侧：卡片行
class _ScanRow(RoundedCard):
    """一条发现的实例：图标 + 名称/徽章 + 路径 + 内容角标 + 导入按钮。"""

    def __init__(self, inst: ScannedInstance, imported: bool, on_import):
        super().__init__(radius=12)
        self.inst = inst
        self._on_import = on_import
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)

        lay.addWidget(ui_kit.tile("instances", 40, 22))

        col = QVBoxLayout()
        col.setSpacing(4)

        line1 = QHBoxLayout()
        line1.setSpacing(8)
        self.nm = ui_kit.ElidedLabel(inst.name)
        self.nm.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {COLORS['text_main']};")
        line1.addWidget(self.nm, 1)
        line1.addWidget(ui_kit.badge(inst.game_version or "?",
                                    COLORS["accent"]))
        if inst.loader and inst.loader != "vanilla":
            line1.addWidget(ui_kit.badge(loader_label(inst), COLORS["info"]))
        self.state_badge = ui_kit.badge(
            t("scan.imported") if imported else t("scan.not_imported"),
            COLORS["success"] if imported else COLORS["warn"])
        line1.addWidget(self.state_badge)
        col.addLayout(line1)

        self.path_lbl = ui_kit.ElidedLabel(_short_path(inst.mc_dir))
        self.path_lbl.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_sub']};")
        self.path_lbl.setToolTip(inst.mc_dir)
        col.addWidget(self.path_lbl)

        tags = _content_tags(inst)
        note = t("scan.note_" + inst.note) if inst.note else ""
        if not inst.isolated:
            note = t("scan.row_shared")
        if tags or note:
            line3 = QHBoxLayout()
            line3.setSpacing(6)
            for txt in tags:
                lb = QLabel(txt)
                lb.setStyleSheet(
                    f"font-size: 11px; color: {COLORS['text_sub']};")
                line3.addWidget(lb)
            if note:
                note_lbl = ui_kit.ElidedLabel(note)
                note_lbl.setStyleSheet(
                    f"font-size: 11px; color: {COLORS['warn']};")
                note_lbl.setToolTip(note)
                line3.addWidget(note_lbl, 1)
            else:
                line3.addStretch(1)
            col.addLayout(line3)
        lay.addLayout(col, 1)

        self.btn = QPushButton(t("scan.imported") if imported else t("scan.import"))
        self.btn.setMinimumHeight(32)
        self.btn.setMinimumWidth(84)
        if imported:
            self.btn.setEnabled(False)
            self.btn.setProperty("cls", "secondary")
        else:
            self.btn.setProperty("cls", "accent")
            self.btn.setIcon(icon("import"))
            self.btn.setIconSize(QSize(15, 15))
        self.btn.clicked.connect(lambda: self._on_import(self.inst, self))
        lay.addWidget(self.btn)

    def mark_imported(self) -> None:
        """导入成功后就地改状态，不重建整张列表。"""
        self.state_badge.setText(t("scan.imported"))
        self.state_badge.setStyleSheet(
            f"color: {COLORS['success']}; "
            f"background: {with_alpha(COLORS['success'], 0x1F)}; "
            f"border-radius: 9px; padding: 2px 10px; font-size: 11px; "
            f"font-weight: 600;")
        self.btn.setText(t("scan.imported"))
        self.btn.setEnabled(False)
        self.btn.setIcon(icon("check"))
        self.btn.setProperty("cls", "secondary")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)


def loader_label(inst: ScannedInstance) -> str:
    """加载器显示名：有具体版本就带上（Fabric 0.15.11）。"""
    from .i18n import loader_name
    name = loader_name(inst.loader)
    ver = getattr(inst, "loader_version", "") or ""
    return "%s %s" % (name, ver) if ver else name


class _GroupBlock(QWidget):
    """一个启动器的分组：可折叠的表头 + 卡片列表。"""

    def __init__(self, launcher_key: str, display: str, count: int):
        super().__init__()
        self.launcher_key = launcher_key
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self.head = QToolButton()
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.setMinimumHeight(28)
        self.head.setStyleSheet(
            "QToolButton { background: transparent; border: none;"
            " padding: 2px 6px; text-align: left; font-weight: 700;"
            f" font-size: 12px; color: {COLORS['text_sub']}; }}"
            f"QToolButton:hover {{ color: {COLORS['text_main']}; }}")
        self._display = display
        self._count = count
        self._collapsed = False
        self._sync_head()
        self.head.clicked.connect(self.toggle)
        v.addWidget(self.head)

        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(6)
        v.addWidget(self.body)

    # ---- header state ----
    def _sync_head(self) -> None:
        arrow = "▸" if self._collapsed else "▾"
        self.head.setText("%s  %s  (%d)" % (arrow, self._display, self._count))

    def set_count(self, n: int) -> None:
        self._count = n
        self._sync_head()

    def toggle(self) -> None:
        self._collapsed = not self._collapsed
        self.body.setVisible(not self._collapsed)
        self._sync_head()

    def add_row(self, row: _ScanRow) -> None:
        self.body_lay.addWidget(row)
        self._count = self.body_lay.count()
        self._sync_head()


# ────────────────────────────────────────────────── 线程壳
class _ScanJob(Worker):
    """把 ``discover_instances`` 的进度/发现结果转成 Qt 信号。

    ``Worker`` 只提供 finished/error，这里补两条：``progress``（阶段名或正在
    遍历的目录）与 ``found``（每发现一条）。信号从 worker 线程发出，Qt 会自动
    排队到 UI 线程执行槽函数，不会出现跨线程碰控件。
    """

    progress = Signal(str)
    found = Signal(object)

    def __init__(self, stop: threading.Event):
        super().__init__(self._body, stop)

    def _body(self, stop: threading.Event):
        cur = QThread.currentThread()   # 退出时的 drain_workers() 也靠这个停

        def on_progress(msg: str) -> None:
            self.progress.emit(str(msg))

        def on_found(inst) -> None:
            self.found.emit(inst)

        return discover_instances(
            progress=on_progress,
            on_found=on_found,
            should_stop=lambda: stop.is_set() or cur.isInterruptionRequested(),
        )


# ────────────────────────────────────────────────── 面板
class ScanPanel(QWidget):
    """可嵌入的扫描面板（实例页 / 首页都用它，不再弹窗）。"""

    done = Signal()
    # 导入成功后通知宿主：宿主据此刷新实例列表（不必重扫）
    imported = Signal(str)

    def __init__(self, parent=None, auto_scan: bool = True):
        super().__init__(parent)
        self._all: list[ScannedInstance] = []
        self._rows: dict[str, _ScanRow] = {}
        self._groups: dict[str, _GroupBlock] = {}
        self._managed: set[str] = set()
        self._imported_now: set[str] = set()
        self._worker: _ScanJob | None = None
        self._scan_stop = threading.Event()
        self._scanning = False
        self._cancel_requested = False
        self._pending_rows: list = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(120)
        self._flush_timer.timeout.connect(self._flush_pending)
        self._build_ui()
        if auto_scan:
            QTimer.singleShot(60, self._run_scan)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 状态条 ──
        status = QWidget()
        status.setStyleSheet("background: transparent;")
        sl = QVBoxLayout(status)
        sl.setContentsMargins(20, 14, 20, 10)
        sl.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.state_dot = QLabel()
        self.state_dot.setFixedSize(8, 8)
        self._paint_dot(COLORS["text_sub"])
        top.addWidget(self.state_dot)
        self.state_lbl = QLabel(t("scan.status_ready"))
        self.state_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {COLORS['text_main']};")
        top.addWidget(self.state_lbl)

        self.count_lbl = ui_kit.badge(t("scan.found_n", n=0), COLORS["accent"])
        self.pending_lbl = ui_kit.badge(t("scan.pending_n", n=0), COLORS["warn"])
        self.done_lbl = ui_kit.badge(t("scan.imported_n", n=0), COLORS["success"])
        top.addWidget(self.count_lbl)
        top.addWidget(self.pending_lbl)
        top.addWidget(self.done_lbl)
        top.addStretch(1)

        self.scan_btn = QPushButton(t("scan.start"))
        self.scan_btn.setMinimumHeight(34)
        self.scan_btn.setMinimumWidth(124)
        self.scan_btn.setIcon(icon("refresh"))
        self.scan_btn.setIconSize(QSize(16, 16))
        self.scan_btn.clicked.connect(self._on_scan_btn)
        top.addWidget(self.scan_btn)
        sl.addLayout(top)

        # 实时路径 / 提示行
        self.hint_lbl = ui_kit.ElidedLabel(t("scan.status_ready_hint"))
        self.hint_lbl.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_sub']};")
        self.hint_lbl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.hint_lbl)

        self.progress = QProgressBar()
        self.progress.setMaximum(0)          # indeterminate：扫描没有已知总量
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setVisible(False)
        sl.addWidget(self.progress)
        root.addWidget(status)

        # ── 工具条：搜索 / 只看未导入 / 导入文件夹 / 一键导入 ──
        bar = QHBoxLayout()
        bar.setContentsMargins(20, 0, 20, 8)
        bar.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            t("search.placeholder", default="搜索实例…"))
        self.search_input.setMinimumHeight(32)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._rebuild)
        bar.addWidget(self.search_input, 1)

        self.only_pending = QCheckBox(t("scan.only_pending"))
        self.only_pending.setMinimumHeight(32)
        self.only_pending.toggled.connect(self._rebuild)
        bar.addWidget(self.only_pending)

        folder_btn = QPushButton(t("scan.import_folder"))
        folder_btn.setMinimumHeight(32)
        folder_btn.setIcon(icon("folder"))
        folder_btn.setIconSize(QSize(15, 15))
        folder_btn.clicked.connect(self._import_folder)
        bar.addWidget(folder_btn)

        self.import_all_btn = QPushButton(t("scan.import_all"))
        self.import_all_btn.setMinimumHeight(32)
        self.import_all_btn.setProperty("cls", "accent")
        self.import_all_btn.setIcon(icon("import"))
        self.import_all_btn.setIconSize(QSize(15, 15))
        self.import_all_btn.clicked.connect(self._import_all)
        self.import_all_btn.setEnabled(False)
        bar.addWidget(self.import_all_btn)
        root.addLayout(bar)

        # ── 结果区 ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(20, 4, 20, 24)
        cl.setSpacing(14)
        self.list_lay = QVBoxLayout()
        self.list_lay.setSpacing(10)
        cl.addLayout(self.list_lay)
        self.empty_lbl = QLabel(t("scan.status_ready_hint"))
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setWordWrap(True)
        self.empty_lbl.setStyleSheet(
            f"font-size: 12px; color: {COLORS['text_sub']}; padding: 40px 0;")
        cl.addWidget(self.empty_lbl)
        cl.addStretch(1)
        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)

        # ── 底部 ──
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 8, 20, 12)
        foot.setSpacing(10)
        self.footer_lbl = QLabel("")
        self.footer_lbl.setStyleSheet(
            f"font-size: 11px; color: {COLORS['text_sub']};")
        foot.addWidget(self.footer_lbl, 1)
        close_btn = QPushButton(t("common.close"))
        close_btn.setMinimumHeight(34)
        close_btn.clicked.connect(self.done.emit)
        foot.addWidget(close_btn)
        root.addLayout(foot)

        self._refresh_counts()

    def _paint_dot(self, color: str) -> None:
        self.state_dot.setStyleSheet(
            f"background: {color}; border-radius: 4px;")

    # ------------------------------------------------------------- properties
    @property
    def imported_dirs(self) -> set[str]:
        """本次面板里成功导入过的目录（宿主用它解锁成就/刷新列表）。"""
        return set(self._imported_now)

    # ------------------------------------------------------------- 扫描
    def _on_scan_btn(self) -> None:
        if self._scanning:
            self._request_stop()
        else:
            self._run_scan()

    def _request_stop(self) -> None:
        """停止扫描：立刻收工并保留已发现结果。"""
        if not self._scanning:
            return
        self._cancel_requested = True
        self._scan_stop.set()
        self.state_lbl.setText(t("scan.status_stopped"))
        self.scan_btn.setEnabled(False)   # 等线程真正退出后再恢复

    def _run_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._cancel_requested = False
        self._scan_stop = threading.Event()
        self._managed = managed_index()
        # 清空上次结果
        self._all.clear()
        self._imported_now.clear()
        self._rebuild()
        self.progress.setVisible(True)
        self._paint_dot(COLORS["accent"])
        self.state_lbl.setText(t("scan.status_scanning"))
        self.hint_lbl.setText(t("scan.status_scanning_hint"))
        self.scan_btn.setText(t("scan.stop"))
        self.scan_btn.setIcon(icon("pause"))
        self.scan_btn.setEnabled(True)
        self.scan_btn.setProperty("cls", "secondary")
        self.scan_btn.style().unpolish(self.scan_btn)
        self.scan_btn.style().polish(self.scan_btn)
        self.import_all_btn.setEnabled(False)
        self._refresh_counts()
        self._flush_timer.start()

        job = _ScanJob(self._scan_stop)
        job.progress.connect(self._on_progress)
        job.found.connect(self._on_found)
        job.finished.connect(self._on_scan_finished)
        job.error.connect(self._on_scan_error)
        self._worker = job
        job.start()

    def _on_progress(self, msg: str) -> None:
        if not self._scanning:
            return
        # 阶段名（"CurseForge"）与目录路径混着来：路径中间省略，阶段名原样显示
        if os.path.sep in msg or "/" in msg:
            self.hint_lbl.setText(_short_path(msg, 96))
        else:
            self.hint_lbl.setText(msg)

    def _on_found(self, inst) -> None:
        # 线程里逐条来；先攒着，由 120ms 定时器批量插进布局，避免频繁重排
        self._pending_rows.append(inst)

    def _flush_pending(self) -> None:
        if not self._pending_rows:
            return
        batch = self._pending_rows
        self._pending_rows = []
        for inst in batch:
            self._all.append(inst)
            self._add_row(inst)
        self._refresh_counts()
        self._update_empty()

    def _on_scan_finished(self, instances) -> None:
        self._flush_timer.stop()
        self._flush_pending()
        self._scanning = False
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText(t("scan.rescan"))
        self.scan_btn.setIcon(icon("refresh"))
        self.scan_btn.setProperty("cls", "")
        self.scan_btn.style().unpolish(self.scan_btn)
        self.scan_btn.style().polish(self.scan_btn)
        stopped = self._cancel_requested
        self._paint_dot(COLORS["success"] if self._all else COLORS["text_sub"])
        self.state_lbl.setText(
            t("scan.status_stopped") if stopped else t("scan.status_done"))
        if stopped:
            self.hint_lbl.setText(t("scan.status_stopped_hint", n=len(self._all)))
        else:
            self.hint_lbl.setText(t("scan.scan_summary", n=len(self._all)))
        self._worker = None
        self._refresh_counts()
        self._update_empty()
        self._import_dirs_snapshot()

    def _on_scan_error(self, err: str) -> None:
        self._flush_timer.stop()
        self._scanning = False
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText(t("scan.rescan"))
        self.scan_btn.setIcon(icon("refresh"))
        self._paint_dot(COLORS["danger"])
        self.state_lbl.setText(t("scan.status_stopped"))
        self.hint_lbl.setText(str(err))
        self._worker = None

    def shutdown(self) -> None:
        """面板销毁前调用：让磁盘扫描尽快收工，别再回调已删控件。"""
        self._cancel_requested = True
        self._scan_stop.set()
        self._flush_timer.stop()
        w = self._worker
        if w is None:
            return
        for sig, slot in ((w.finished, self._on_scan_finished),
                          (w.error, self._on_scan_error),
                          (w.progress, self._on_progress),
                          (w.found, self._on_found)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        try:
            w.requestInterruption()
            w.wait(1500)
        except RuntimeError:   # C++ 对象已销毁
            pass

    # ------------------------------------------------------------- 列表
    def _passes_filter(self, inst: ScannedInstance) -> bool:
        if self.only_pending.isChecked() and is_imported(inst, self._managed):
            return False
        q = self.search_input.text().strip().lower()
        if not q:
            return True
        hay = " ".join((inst.name or "", inst.game_version or "",
                        inst.loader or "", inst.launcher or "",
                        inst.mc_dir or "")).lower()
        return q in hay

    def _rebuild(self, *_ignored) -> None:
        """按当前筛选条件重建整张列表（切筛选 / 导入后调用）。"""
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()
        self._groups.clear()
        for inst in self._all:
            self._add_row(inst)
        self._refresh_counts()
        self._update_empty()

    def _add_row(self, inst: ScannedInstance) -> None:
        if not self._passes_filter(inst):
            return
        # ☠ 行键必须带版本：同一个 .minecraft 下常有多个版本，只按目录去重
        # 会把它们合并成一行，而计数仍按 N 条算（列表 3 行、角标写 7）。
        key = _inst_key(_norm_path(inst.mc_dir),
                        getattr(inst, "version_id", "") or inst.name)
        if key in self._rows:
            return
        gkey = inst.launcher or "Other"
        grp = self._groups.get(gkey)
        if grp is None:
            grp = _GroupBlock(gkey, launcher_label(gkey, show_original=True), 0)
            self._groups[gkey] = grp
            self.list_lay.addWidget(grp)
        row = _ScanRow(inst, is_imported(inst, self._managed), self._import)
        self._rows[key] = row
        grp.add_row(row)

    def _update_empty(self) -> None:
        has_rows = bool(self._rows)
        self.empty_lbl.setVisible(not has_rows)
        if has_rows:
            return
        if self._scanning:
            self.empty_lbl.setText(t("scan.status_scanning_hint"))
        elif self.search_input.text().strip() or self.only_pending.isChecked():
            self.empty_lbl.setText(
                t("scan.no_match") + "\n" + t("scan.no_match_hint"))
        elif self._all:
            # 有结果但全被筛掉了
            self.empty_lbl.setText(t("scan.no_match_hint"))
        else:
            self.empty_lbl.setText(t("scan.status_empty_hint"))

    def _refresh_counts(self) -> None:
        total = len(self._all)
        imported = sum(1 for i in self._all if is_imported(i, self._managed))
        pending = total - imported
        self.count_lbl.setText(t("scan.found_n", n=total))
        self.pending_lbl.setText(t("scan.pending_n", n=pending))
        self.done_lbl.setText(t("scan.imported_n", n=imported))
        self.pending_lbl.setVisible(total > 0)
        self.done_lbl.setVisible(imported > 0)
        self.import_all_btn.setEnabled(pending > 0 and not self._scanning)
        if pending:
            self.import_all_btn.setText(
                "%s (%d)" % (t("scan.import_all"), pending))
        else:
            self.import_all_btn.setText(t("scan.import_all"))

    def _import_dirs_snapshot(self) -> None:
        """扫描结束后再对一次账：这期间可能已经导入过新的实例。"""
        fresh = managed_index()
        if fresh != self._managed:
            self._managed = fresh
            self._rebuild()
            return
        if self._imported_now:
            self._managed |= self._imported_now

    # ------------------------------------------------------------- 导入
    def _choose_mode(self, inst: ScannedInstance) -> str | None:
        """问玩家：原地接管，还是复制进 AC。返回 "link" / "copy" / None。"""
        detail = ""
        if inst.needs_convert:
            detail = t("scan.import_warn_convert")
        elif not inst.isolated:
            detail = t("scan.import_shared_warn")
        detail += "\n\n" + f"{t('scan.import_link_hint')}\n\n{t('scan.import_copy_hint')}"

        result = _msgbox(
            self.window(),
            t("scan.import_title"),
            t("scan.import_body",
              launcher=launcher_label(inst.launcher, show_original=True),
              name=inst.name),
            detail=detail,
            icon="question",
            buttons=(t("scan.import_link"), t("scan.import_copy")),
        )
        if result == t("scan.import_copy"):
            return "copy"
        if result == t("scan.import_link"):
            return "link"
        return None

    def _do_import(self, inst: ScannedInstance, btn, mode: str) -> bool:
        self._copy_cancelled = False
        if mode == "copy":
            return self._do_import_copy(inst, btn)
        return self._do_import_link(inst, btn)

    def _import_kwargs(self, inst: ScannedInstance, mode: str) -> dict:
        return dict(
            mc_dir=inst.mc_dir,
            name=inst.name,
            game_version=inst.game_version,
            loader=inst.loader,
            loader_version=inst.loader_version,
            version_id=inst.version_id,
            kind=inst.kind,
            needs_convert=inst.needs_convert,
            mode=mode,
            launcher=inst.launcher,
        )

    def _do_import_link(self, inst: ScannedInstance, btn) -> bool:
        try:
            instances_manager().import_external(**self._import_kwargs(inst, "link"))
            return True
        except Exception as e:  # noqa: BLE001
            btn.setText(f"Error: {e}")
            return False

    def _do_import_copy(self, inst: ScannedInstance, btn) -> bool:
        """复制进 AC，带实时进度对话框。

        用户主动取消 → 什么都不导入（绝不悄悄退化成链接）；复制真失败 → 回退
        原地接管（与旧行为一致），并提示原因。
        """
        progress = QProgressDialog(self.window())
        progress.setWindowTitle(t("scan.copying_title"))
        progress.setLabelText(t("scan.copying", name=inst.name))
        progress.setCancelButtonText(t("common.cancel"))
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumWidth(420)
        bar = progress.findChild(QProgressBar)
        if bar is not None:
            bar.setTextVisible(False)
        progress.setValue(0)

        last = [0.0]

        def on_progress(copied: int, total: int, rel: str) -> bool:
            now = time.monotonic()
            if now - last[0] < 0.05 and copied < total:
                return not progress.wasCanceled()
            last[0] = now
            progress.setMaximum(total or 1)
            progress.setValue(copied)
            if rel:
                progress.setLabelText(t("scan.copying_file", file=rel))
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            instances_manager().import_external(
                on_progress=on_progress, **self._import_kwargs(inst, "copy"))
            progress.setValue(progress.maximum())
            progress.close()
            return True
        except _CopyFailed as e:
            progress.close()
            if progress.wasCanceled():
                self._copy_cancelled = True
                warn(self.window(), t("scan.copying_title"), t("scan.copy_aborted"))
                return False
            try:
                instances_manager().import_external(
                    **self._import_kwargs(inst, "link"))
                info(self.window(), t("scan.import_title"),
                     t("scan.copy_failed", err=str(e)))
                return True
            except Exception as e2:  # noqa: BLE001
                btn.setText(f"Error: {e2}")
                return False
        except Exception as e:  # noqa: BLE001
            progress.close()
            btn.setText(f"Error: {e}")
            return False

    def _after_import(self, inst: ScannedInstance) -> None:
        """导入成功后的统一收尾：状态、计数、宿主通知。"""
        key = _inst_key(_norm_path(inst.mc_dir),
                        getattr(inst, "version_id", "") or inst.name)
        self._imported_now.add(key)
        self._managed.add(_inst_key(_norm_path(inst.mc_dir),
                                    getattr(inst, "version_id", "") or ""))
        row = self._rows.get(key)
        if row is not None:
            row.mark_imported()
        self._refresh_counts()
        self.imported.emit(inst.mc_dir)

    def _import(self, inst: ScannedInstance, row: _ScanRow | None = None) -> None:
        if is_imported(inst, self._managed):
            return
        mode = self._choose_mode(inst)
        if mode is None:
            return
        btn = row.btn if row is not None else _NullBtn()
        if self._do_import(inst, btn, mode):
            self._after_import(inst)
            if self.only_pending.isChecked():
                QTimer.singleShot(0, self._rebuild)

    def _import_all(self) -> None:
        """一键导入所有未导入实例：先统一问一次接管/复制，再批量执行。"""
        pending = [i for i in self._all if not is_imported(i, self._managed)]
        if not pending:
            return
        detail = (t("scan.import_all_hint") + "\n\n" +
                  f"{t('scan.import_link_hint')}\n\n{t('scan.import_copy_hint')}")
        result = _msgbox(
            self.window(), t("scan.import_all_title"),
            t("scan.import_all_body", n=len(pending)),
            detail=detail, icon="question",
            buttons=(t("scan.import_link"), t("scan.import_copy")),
        )
        if result == t("scan.import_copy"):
            mode = "copy"
        elif result == t("scan.import_link"):
            mode = "link"
        else:
            return
        # ☠ 复制模式下**必须按目录去重**：同一个 .minecraft 下有 3 个版本时，
        # 复制 3 次就是把同一个目录抄三份、白占 3 倍磁盘。原地接管不复制文件，
        # 所以链接模式保留每个版本（每版一条实例才有意义）。
        if mode == "copy":
            seen: set[str] = set()
            deduped = []
            for inst in pending:
                k = _norm_path(inst.mc_dir)
                if k in seen:
                    continue
                seen.add(k)
                deduped.append(inst)
            pending = deduped
        ok = fail = 0
        for inst in pending:
            if self._do_import(inst, _NullBtn(), mode):
                self._after_import(inst)
                ok += 1
            else:
                fail += 1
                if getattr(self, "_copy_cancelled", False):
                    break   # 用户中途取消复制 → 不再继续后面的
        self._refresh_counts()
        if self.only_pending.isChecked():
            self._rebuild()
        self.footer_lbl.setText(
            t("scan.import_all_done_partial", ok=ok, fail=fail) if fail
            else t("scan.import_all_done", n=ok))

    # ------------------------------------------------------------- 手动导入
    def _import_folder(self) -> None:
        """手动指定一个 .minecraft 目录并导入（不再触发整盘重扫）。"""
        from .win_rounded import pick_files
        folder = pick_files(self.window(), t("scan.select_folder"), "",
                            dir_only=True)
        if not folder:
            return
        from .scan import _is_mc_dir, _guess_launcher, _loader_from_text

        mc_dir = folder
        alt = os.path.join(folder, ".minecraft")
        if not _is_mc_dir(mc_dir) and _is_mc_dir(alt):
            mc_dir = alt
        if not _is_mc_dir(mc_dir):
            warn(self.window(), t("scan.import_title"),
                 t("scan.not_mc_dir", path=folder))
            return

        name = (os.path.basename(os.path.dirname(mc_dir))
                or os.path.basename(mc_dir) or t("scan.manual_instance"))
        game_version, version_id = "?", ""
        versions_dir = os.path.join(mc_dir, "versions")
        if os.path.isdir(versions_dir):
            try:
                for e in os.scandir(versions_dir):
                    if e.is_dir() and os.path.isfile(
                            os.path.join(e.path, e.name + ".json")):
                        game_version = version_id = e.name
                        break
            except OSError:
                pass

        loader = "vanilla"
        mods_dir = os.path.join(mc_dir, "mods")
        if os.path.isdir(mods_dir):
            try:
                for f in os.listdir(mods_dir):
                    if f.lower().endswith(".jar"):
                        loader = _loader_from_text(f)
                        break
            except OSError:
                pass

        inst = ScannedInstance(
            launcher=_guess_launcher(mc_dir), name=name,
            game_version=game_version, loader=loader, mc_dir=mc_dir,
            version_id=version_id, kind="standard",
        )
        self._all.append(inst)
        self._add_row(inst)
        self._refresh_counts()
        self._update_empty()

        mode = self._choose_mode(inst)
        if mode is None:
            return
        if self._do_import(inst, _NullBtn(), mode):
            self._after_import(inst)
            self.footer_lbl.setText(t("scan.folder_imported", name=name))
            if self.only_pending.isChecked():
                self._rebuild()


class _NullBtn:
    """批量导入/手动导入时没有真实按钮可回写错误信息。"""

    def setText(self, _t): ...
    def setEnabled(self, _e): ...
    def setStyleSheet(self, _s): ...


class ScanDialog(QDialog):
    """无边框弹窗外壳（保留给还需要弹窗的调用点）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("scan.title"))
        self.resize(960, 680)
        self.setMinimumSize(840, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self, title=t("scan.title"), height=38,
                                 controls="close")
        root.addWidget(self.titlebar)

        self.panel = ScanPanel(self, auto_scan=True)
        self.panel.done.connect(self.accept)
        root.addWidget(self.panel, 1)

        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

    def closeEvent(self, ev):  # noqa: N802 - Qt 约定
        self.panel.shutdown()
        super().closeEvent(ev)

    def done(self, r: int):
        self.panel.shutdown()
        super().done(r)
