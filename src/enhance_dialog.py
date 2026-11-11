"""客户端增强对话框（round-182）。

实例右键 →「客户端增强」：把 Mouse Tweaks 这类**客户端体验类** mod 做成
一键装 / 卸，不用去资源中心搜项目、再对着几十个构建猜该选哪个。

为什么要做这个：用户问「能不能不加 mod 直接在游戏里用 mod 的鼠标手势」。
查证后结论是**不能**——Mouse Tweaks 这类 hook 的是容器界面的鼠标事件，
启动器在进程外只有像素，硬做等于按坐标盲点，最坏会把物品丢到地上。
所以正确解法是把「装它」这件事变成一次点击。

三个原则（与 core.enhance 同源）：
  * 能不能装看**运行时查询结果**，不硬编码支持范围；
  * 只在**确认不支持**时禁用，未知一律放行；
  * 卸载只删本项目自己的文件，自动带上的前置库保留。

所有联网动作（可用性检查、下载）都走 Worker，UI 线程不做网络。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .i18n import t
from .theme import COLORS
from .worker import Worker
from .panel_shell import PanelCloseMixin, PanelShellMixin

_BTN_W = 92
_GROUP_TITLE = {
    "input": "enhance.group.input",
    "perf": "enhance.group.perf",
    "visual": "enhance.group.visual",
    "info": "enhance.group.info",
    "dep": "enhance.group.dep",
}
_STATE_COLOR = {
    "installed": "success",
    "available": "text_sub",
    "version_unsupported": "warn",
    "loader_unsupported": "warn",
    "no_build": "warn",
    "unreachable": "danger",
}


class EnhanceDialog(PanelShellMixin, QDialog):
    """**兼容壳**：窗口模式（历史调用点）。内部就是 :class:`EnhancePanel`。"""

    def __init__(self, parent, inst):
        super().__init__(parent)
        self.setWindowTitle(t("enhance.title"))
        self.resize(780, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.panel = EnhancePanel(self, inst)
        lay.addWidget(self.panel)
        self.panel.closed.connect(self.accept)



def _mk_label(text: str, *, pt: int = 9, bold: bool = False,
              color_key: str = "text_sub") -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(True)
    f = lb.font()
    f.setPointSize(pt)
    f.setBold(bold)
    lb.setFont(f)
    lb.setStyleSheet(f"color:{COLORS.get(color_key, COLORS['text_sub'])};")
    return lb


class EnhancePanel(PanelCloseMixin, QWidget):
    """实例的客户端增强包面板（**页内**，round-195）。

    原来是 QDialog 弹窗 —— 它与"实例编辑""实例体检"一样是实例相关页面，
    不该另开窗口。窗口壳 :class:`EnhanceDialog` 保留给历史调用点。
    """

    closed = Signal()

    def __init__(self, parent, inst):
        super().__init__(parent)
        self.inst = inst
        self._status: dict | None = None
        self._row_widgets: dict[str, dict] = {}
        self._worker = None
        self._busy: set[str] = set()

        self.setObjectName("enhRoot")
        self.setStyleSheet(
            f"QWidget#enhRoot{{background:{COLORS['bg_app']};}}"
            f"QScrollArea{{background:transparent;border:none;}}"
            f"QWidget#enhBody{{background:transparent;}}")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.addWidget(_mk_label(t("enhance.title"), pt=13, bold=True,
                                      color_key="text_main"))
        loader = (getattr(inst, "loader", "") or "vanilla")
        title_box.addWidget(_mk_label(
            t("enhance.subtitle", ver=getattr(inst, "game_version", "") or "-",
              loader=loader), pt=9))
        head.addLayout(title_box, 1)
        self.btn_refresh = QPushButton(t("enhance.btn_refresh"))
        self.btn_refresh.setFixedWidth(_BTN_W + 36)
        self.btn_refresh.clicked.connect(self.reload)
        head.addWidget(self.btn_refresh, 0, Qt.AlignTop)
        root.addLayout(head)

        self.hint = _mk_label("", pt=9, color_key="warn")
        self.hint.hide()
        root.addWidget(self.hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.body.setObjectName("enhBody")
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(6)
        self.body_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        btn_close = QPushButton(t("enhance.btn_close"))
        btn_close.setFixedWidth(_BTN_W)
        btn_close.clicked.connect(self._on_close)
        foot.addWidget(btn_close)
        root.addLayout(foot)

        self._reload_worker = None
        self.reload()

    # ------------------------------------------------------------------ #
    # 数据加载
    # ------------------------------------------------------------------ #
    def reload(self):
        from .core import enhance as EH

        self.btn_refresh.setEnabled(False)
        self.hint.hide()
        loader = (getattr(self.inst, "loader", "") or "vanilla")
        self._show_message(t("enhance.loading",
                             ver=getattr(self.inst, "game_version", "") or "-",
                             loader=loader))

        worker = Worker(EH.resolve_status, self.inst)
        worker.finished.connect(self._on_status)
        worker.error.connect(self._on_status_error)
        self._reload_worker = worker
        worker.start()

    def _on_status(self, status):
        self.btn_refresh.setEnabled(True)
        self._status = status if isinstance(status, dict) else None
        if not self._status:
            self._show_message(t("enhance.state.unreachable", detail="-"))
            return
        if not self._status.get("loader_ok"):
            self.hint.setText(t("enhance.hint_no_loader"))
            self.hint.show()
        self._build_rows()

    def _on_status_error(self, err):
        self.btn_refresh.setEnabled(True)
        # round-196：不再硬切 120 字符（半句话）→ 完整信息 + 换行显示
        self._show_message(t("enhance.state.unreachable", detail=str(err)))

    def _clear_body(self):
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._row_widgets.clear()

    def _show_message(self, text: str):
        self._clear_body()
        lab = _mk_label(text, pt=9)
        lab.setAlignment(Qt.AlignCenter)
        self.body_lay.addWidget(lab)
        self.body_lay.addStretch(1)

    # ------------------------------------------------------------------ #
    # 列表构建
    # ------------------------------------------------------------------ #
    def _build_rows(self):
        status = self._status or {}
        rows = status.get("items") or []
        self._clear_body()

        by_group: dict[str, list[dict]] = {}
        for row in rows:
            by_group.setdefault(row["item"].group, []).append(row)

        for group in ("input", "perf", "visual", "info", "dep"):
            bucket = by_group.get(group) or []
            if not bucket:
                continue
            self.body_lay.addWidget(self._group_header(group))
            for row in bucket:
                self.body_lay.addWidget(self._item_card(row))
        self.body_lay.addStretch(1)

    def _group_header(self, group: str) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 10, 2, 2)
        lay.setSpacing(8)
        lay.addWidget(_mk_label(t(_GROUP_TITLE.get(group, group)), pt=9,
                                bold=True, color_key="text_main"))
        line = QWidget()
        line.setFixedHeight(1)
        line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        line.setStyleSheet(f"background:{COLORS['border']};")
        lay.addWidget(line, 1)
        return w

    def _item_card(self, row: dict) -> QWidget:
        item = row["item"]
        card = QWidget()
        card.setStyleSheet(
            f"QWidget{{background:{COLORS['bg_card']};"
            f"border-radius:8px;}}")
        outer = QHBoxLayout(card)
        outer.setContentsMargins(14, 10, 12, 10)
        outer.setSpacing(12)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(_mk_label(item.name, pt=10, bold=True,
                                color_key="text_main"))
        state_key = row.get("state", "available")
        state_txt = self._state_text(row)
        if state_txt:
            color = _STATE_COLOR.get(state_key, "text_sub")
            top.addWidget(_mk_label(state_txt, pt=8, color_key=color))
        top.addStretch(1)
        text_box.addLayout(top)
        text_box.addWidget(_mk_label(t(f"enhance.desc.{item.desc_key}"), pt=9))

        extra = ""
        if item.extra_key:
            extra = t(f"enhance.extra.{item.extra_key}")
        elif item.is_dep:
            extra = t("enhance.dep_note")
        if extra:
            text_box.addWidget(_mk_label(extra, pt=8,
                                         color_key="text_disabled"))
        outer.addLayout(text_box, 1)

        btn = QPushButton()
        btn.setFixedWidth(_BTN_W)
        if item.slug in self._busy:
            btn.setText(t("enhance.btn_install"))
            btn.setEnabled(False)
        elif row.get("installed"):
            btn.setText(t("enhance.btn_remove"))
            btn.clicked.connect(
                lambda _=False, it=item: self._do_remove(it))
        elif state_key == "available":
            btn.setText(t("enhance.btn_install"))
            btn.clicked.connect(
                lambda _=False, it=item: self._do_install(it))
        else:
            btn.setText(t("enhance.btn_install"))
            btn.setEnabled(False)
        outer.addWidget(btn, 0, Qt.AlignVCenter)

        self._row_widgets[item.slug] = {"card": card, "btn": btn}
        return card

    def _state_text(self, row: dict) -> str:
        state = row.get("state", "")
        if state == "installed":
            ver = row.get("version") or ""
            base = t("enhance.state.installed")
            return f"{base} {ver}".strip() if ver else base
        if state in ("version_unsupported", "loader_unsupported",
                     "no_build", "unreachable"):
            return t(f"enhance.state.{state}",
                     ver=row.get("detail", ""),
                     detail=row.get("detail", ""))
        return ""

    # ------------------------------------------------------------------ #
    # 装 / 卸
    # ------------------------------------------------------------------ #
    def _set_busy(self, slug: str, on: bool, message: str = ""):
        if on:
            self._busy.add(slug)
        else:
            self._busy.discard(slug)
        row = self._row_widgets.get(slug)
        if not row:
            return
        btn = row.get("btn")
        if btn is None:
            return
        btn.setEnabled(not on)
        if on:
            btn.setText(message or "…")

    def _do_install(self, item):
        from .core import enhance as EH
        from .win_rounded import info, warn

        if item.slug in self._busy:
            return
        self._set_busy(item.slug, True,
                       t("enhance.busy_install", name=item.name))

        def _ok(result):
            self._set_busy(item.slug, False)
            info(self, t("enhance.title"),
                 t("enhance.ok_install", name=item.name))
            self.reload()

        def _err(err):
            self._set_busy(item.slug, False)
            msg = str(err)
            if msg == "no_build":
                msg = t("enhance.state.no_build",
                        detail=f"{self._status.get('mc_version', '')} / "
                               f"{self._status.get('loader', '')}"
                        if self._status else "")
            elif msg == "no_loader":
                msg = t("enhance.hint_no_loader")
            warn(self, t("enhance.title"), t("enhance.err", err=msg))
            self.reload()

        worker = Worker(EH.install_item, self.inst, item.slug)
        worker.finished.connect(_ok)
        worker.error.connect(_err)
        self._install_worker = worker
        worker.start()

    def _do_remove(self, item):
        from .core import enhance as EH
        from .win_rounded import info, warn

        if item.slug in self._busy:
            return
        self._set_busy(item.slug, True,
                       t("enhance.btn_remove"))

        def _ok(result):
            self._set_busy(item.slug, False)
            info(self, t("enhance.title"),
                 t("enhance.ok_remove", name=item.name))
            if isinstance(result, dict) and result.get("kept_deps"):
                warn(self, t("enhance.title"), t("enhance.warn_keep_deps"))
            self.reload()

        def _err(err):
            self._set_busy(item.slug, False)
            warn(self, t("enhance.title"), t("enhance.err", err=str(err)))
            self.reload()

        worker = Worker(EH.remove_item, self.inst, item.slug)
        worker.finished.connect(_ok)
        worker.error.connect(_err)
        self._remove_worker = worker
        worker.start()
