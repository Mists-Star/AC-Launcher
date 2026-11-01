"""HealthDialog — 实例体检报告（在「启动前模组冲突预检」之上扩展）。

对实例做一次静态体检（``core.instance_health.scan_health``），把发现按分区
（模组冲突 / 性能模组 / JVM 与内存 / Java / 启动参数）渲染成可读报告：每条带
严重度色标、发生了什么、涉及哪些 .jar、怎么修，以及——当该项是本地安全修复
时——一个「修复」按钮。底部支持「重新体检」与「一键修复安全项」。

修复只改实例字段并保存，不联网、不动用户游戏文件。

保留 ``ModCheckDialog`` / ``open_check_dialog`` 作为兼容别名，避免遗漏调用点。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QWidget, QFrame,
)
from .theme import COLORS
from .i18n import t, loader_name
from . import ui_kit
from .core import mod_check
from .frameless import FramelessHelper, TitleBar
from .win_rounded import enable_win11_round_corners

_SEV_COLOR = {
    mod_check.SEV_CRITICAL: "#EF4444",
    mod_check.SEV_WARNING: "#F59E0B",
    mod_check.SEV_INFO: COLORS.get("text_sub", "#6B7280"),
}


def _family_name(family: str) -> str:
    """把 family 值（fabric/quilt/forge）转成可读加载器名。"""
    try:
        return loader_name(family)
    except Exception:  # noqa: BLE001
        return family or "?"


def _localize(f) -> tuple[str, str, str]:
    """返回 (title, reason, suggestion) 的本地化文案。"""
    meta = dict(f.meta or {})
    if f.kind == "loader_mismatch":
        meta["family"] = _family_name(meta.get("family", ""))
        meta["inst_loader"] = _family_name(meta.get("inst_loader", ""))
    title = t(f.title, default=f.kind)
    reason = t(f.reason, default="", **meta)
    suggestion = t(f.suggestion, default="", **meta)
    return title, reason, suggestion


class HealthDialog(QDialog):
    def __init__(self, inst, result: dict, mgr=None, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.mgr = mgr
        self._result = result or {}
        self._first_render = True
        self.setWindowTitle(t("health.dialog_title"))
        self.setMinimumSize(600, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── AC 无边框窗口：自定义标题栏 + 圆角 ──
        self.titlebar = TitleBar(self, title=t("health.dialog_title"), height=38)
        root.addWidget(self.titlebar)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 12, 20, 16)
        bl.setSpacing(12)
        root.addWidget(body, stretch=1)

        # ── frameless + DWM shadow + win11 rounded corners ──
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        enable_win11_round_corners(self)

        # header（desc 随体检结果刷新）
        self.header = ui_kit.page_header(t("health.title"), "")
        bl.addWidget(self.header)

        # scrollable finding cards（按分区）
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._inner = QWidget()
        self._list = QVBoxLayout(self._inner)
        self._list.setContentsMargins(0, 0, 8, 0)
        self._list.setSpacing(10)
        self._scroll.setWidget(self._inner)
        bl.addWidget(self._scroll, stretch=1)

        # bottom actions
        row = QHBoxLayout()
        self.rescan_btn = ui_kit.make_button(
            t("health.rescan"), on_click=self._rescan, min_h=36)
        self.fixall_btn = ui_kit.make_button(
            t("health.fix_all"), kind="accent", on_click=self._fix_all, min_h=36)
        self.close_btn = ui_kit.make_button(
            t("common.close"), on_click=self.accept, min_h=36)
        row.addWidget(self.rescan_btn)
        row.addStretch(1)
        row.addWidget(self.fixall_btn)
        row.addWidget(self.close_btn)
        bl.addLayout(row)

        # round-163：修复反馈行——apply_fix 返回 False（已是目标状态）时
        # 之前完全没有任何提示，玩家会以为「点了没反应」。
        self.note_lbl = QLabel("")
        self.note_lbl.setProperty("cls", "sub")
        self.note_lbl.setWordWrap(True)
        self.note_lbl.setVisible(False)
        bl.addWidget(self.note_lbl)

        self._render(self._result)

    # ── 渲染 ──────────────────────────────────────────────────────────────
    def _clear_list(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render(self, result: dict) -> None:
        self._clear_list()
        findings = result.get("findings") or []
        groups = result.get("groups") or []
        n_fix = int(result.get("fixable", 0) or 0)

        try:
            self.header.desc_lbl.setText(
                t("health.summary", n=len(findings), f=n_fix) if findings
                else t("health.ok_desc"))
        except Exception:  # noqa: BLE001 - desc 刷新失败不影响报告
            pass

        if not findings:
            self.fixall_btn.setEnabled(False)
            self._list.addStretch(1)
            return

        for g in groups:
            head = ui_kit.group_label(t(f"health.groups.{g['key']}"))
            self._list.addWidget(head)
            for f in g["findings"]:
                self._list.addWidget(self._build_card(f))

        self._list.addStretch(1)
        self.fixall_btn.setEnabled(n_fix > 0)

        if self._first_render:
            self._first_render = False
            try:
                from . import effects
                effects.fade_in_widget(self._inner)
            except Exception:  # noqa: BLE001 - 动效失败不影响展示
                pass

    def _build_card(self, f) -> "_FindingCard":
        color = _SEV_COLOR.get(f.severity, COLORS["text_sub"])
        title, reason, suggestion = _localize(f)
        actions: list[tuple[str, object]] = []
        for fx in [getattr(f, "fix", None)] + list(getattr(f, "extra_fixes", []) or []):
            if not isinstance(fx, dict):
                continue
            try:
                label = t(fx.get("label") or "health.fix",
                          **(fx.get("label_kwargs") or {}))
            except Exception:  # noqa: BLE001
                label = t("health.fix")
            actions.append((
                label,
                (lambda _checked=False, ff=f, fxx=fx: self._apply(ff, fxx)),
            ))
        return _FindingCard(
            color, t(f"health.sev.{f.severity}"), title, reason, suggestion,
            list(f.filenames or []), actions)

    # ── 动作 ──────────────────────────────────────────────────────────────
    def _apply(self, f, fix: dict | None = None) -> None:
        fx = fix if fix is not None else getattr(f, "fix", None)
        # 网络补装：apply_fix 只改实例字段，绝不能在这里联网。
        if isinstance(fx, dict) and fx.get("mode") == "install":
            self._run_install()
            return
        from .core import instance_health
        try:
            label = t((fx or {}).get("label") or "health.fix",
                      **((fx or {}).get("label_kwargs") or {}))
        except Exception:  # noqa: BLE001
            label = t("health.fix")
        changed = bool(instance_health.apply_fix(self.inst, fx))
        if changed and self.mgr:
            self.mgr.save(self.inst)
        self._note(t("health.applied", label=label) if changed
                   else t("health.no_change"))
        self._rescan()

    def _note(self, text: str) -> None:
        self.note_lbl.setText(text or "")
        self.note_lbl.setVisible(bool(text))

    # ── 网络补装（round-163）─────────────────────────────────────────────
    def _run_install(self) -> None:
        """体检里点「补装」→ 复用启动进度对话框 + 安装 Worker。"""
        if getattr(self, "_installing", False):
            return
        self._installing = True
        self.close_btn.setEnabled(False)
        self._note(t("health.installing"))
        try:
            from .settings_dialog import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 - 无配置就按默认
            cfg = {}
        from .core.install import install_instance
        from .worker import ProgressWorker
        from .launch_dialog import LaunchProgressDialog
        dlg = LaunchProgressDialog(self.inst, self, mode="download")
        worker = ProgressWorker(
            install_instance, self.inst,
            java_auto=bool(cfg.get("java_auto", True)),
            java_path=(cfg.get("java_path") or ""),
            mirror=cfg.get("download_mirror", "official"),
            proxy=cfg.get("download_proxy", ""),
        )
        worker.status.connect(dlg.set_status_text)
        worker.progress.connect(dlg.set_progress)
        worker.step.connect(dlg.set_step)
        worker.speed.connect(dlg.set_speed)
        worker.finished.connect(self._on_install_finished)
        worker.error.connect(self._on_install_error)
        # 线程对象必须持有引用，否则可能被回收导致信号丢失。
        self._install_worker = worker
        self._install_dlg = dlg
        dlg.show()
        worker.start()

    def _on_install_finished(self, _result=None) -> None:
        self._installing = False
        self.close_btn.setEnabled(True)
        dlg = getattr(self, "_install_dlg", None)
        if dlg is not None:
            try:
                dlg.mark_done(t("health.install_done"))
                from PySide6.QtCore import QTimer
                QTimer.singleShot(600, dlg.accept)
            except Exception:  # noqa: BLE001 - 对话框已关闭
                pass
        if self.mgr:
            self.mgr.save(self.inst)
        self._note(t("health.install_done"))
        self._rescan()

    def _on_install_error(self, msg: str) -> None:
        self._installing = False
        self.close_btn.setEnabled(True)
        dlg = getattr(self, "_install_dlg", None)
        if dlg is not None:
            try:
                dlg.close()
            except Exception:  # noqa: BLE001
                pass
        self._note(t("health.install_failed"))
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, t("health.dialog_title"), msg or "?")

    def _fix_all(self) -> None:
        from .core import instance_health
        n = instance_health.apply_all_safe(
            self.inst, self._result.get("findings") or [])
        if n and self.mgr:
            self.mgr.save(self.inst)
        self._rescan()
        try:
            from .win_rounded import toast
            toast(self, t("health.dialog_title"),
                  t("health.fixed_toast", n=n) if n else t("health.fix_none"))
        except Exception:  # noqa: BLE001 - 提示失败不影响结果
            pass

    def _rescan(self) -> None:
        from .core import instance_health
        try:
            from .settings_dialog import load_config
            cfg = load_config()
        except Exception:  # noqa: BLE001 - 无全局配置就只看实例字段
            cfg = None
        self._result = instance_health.scan_health(self.inst, cfg)
        self._render(self._result)


class _FindingCard(QFrame):
    def __init__(self, color: str, sev_text: str, title: str, reason: str,
                 suggestion: str, filenames: list[str],
                 actions: list | None = None):
        super().__init__()
        # 走主题 QSS 的 QFrame[cls="card"]，随明暗主题自动切换，避免内联硬编码色。
        self.setProperty("cls", "card")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)

        # 标题行：标题 + 右侧严重度徽标
        head = QHBoxLayout()
        head.setSpacing(8)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 800; color: {color};")
        head.addWidget(title_lbl)
        head.addStretch(1)
        sev_lbl = QLabel(sev_text)
        sev_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {color};")
        head.addWidget(sev_lbl)
        v.addLayout(head)

        if reason:
            r_lbl = QLabel(reason)
            r_lbl.setWordWrap(True)
            r_lbl.setStyleSheet(f"color: {COLORS['text_main']}; font-size: 13px;")
            v.addWidget(r_lbl)

        if filenames:
            fnlbl = QLabel("  ·  ".join(filenames))
            fnlbl.setWordWrap(True)
            fnlbl.setStyleSheet(
                f"color: {COLORS.get('text_sub', '#6B7280')};"
                "font-family: Consolas, monospace; font-size: 12px;")
            v.addWidget(fnlbl)

        if suggestion:
            s_lbl = QLabel("→ " + suggestion)
            s_lbl.setWordWrap(True)
            s_lbl.setStyleSheet(f"color: {COLORS.get('text_sub', '#6B7280')}; font-size: 12px;")
            v.addWidget(s_lbl)

        if actions:
            brow = QHBoxLayout()
            brow.addStretch(1)
            for fix_label, on_fix in actions:
                brow.addWidget(ui_kit.make_button(
                    fix_label, kind="surface", on_click=on_fix, min_h=30))
            v.addLayout(brow)


# 兼容别名：既有调用点继续可用。
ModCheckDialog = HealthDialog


def open_health_dialog(parent, inst, mgr=None) -> None:
    """便捷入口：扫描一次并弹体检报告（UI 线程，静态读取，毫秒级）。

    ``mgr`` 为实例管理器；传入时「修复」会落盘保存，不传则只读展示。
    """
    from .core import instance_health
    try:
        from .settings_dialog import load_config
        cfg = load_config()
    except Exception:  # noqa: BLE001
        cfg = None
    result = instance_health.scan_health(inst, cfg)
    HealthDialog(inst, result, mgr=mgr, parent=parent).exec()


def open_check_dialog(parent, inst) -> None:
    """旧入口（模组冲突预检）保留：转调体检对话框，只诊断不保存。"""
    open_health_dialog(parent, inst, mgr=None)
