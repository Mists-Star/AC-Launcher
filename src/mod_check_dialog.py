"""ModCheckDialog — 展示启动前模组冲突预检结果（N5）。

对实例 ``mods/`` 做静态扫描，把 ``core.mod_check`` 返回的 findings 渲染成
可读的中/英文报告：每条发现带严重度色标、发生了什么、涉及哪些 .jar、怎么修。
无发现时给一句「没问题」。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QWidget, QFrame,
)
from .theme import COLORS
from .i18n import t, loader_name
from . import ui_kit
from .core import mod_check

_SEV_COLOR = {
    mod_check.SEV_CRITICAL: "#EF4444",
    mod_check.SEV_WARNING: "#F59E0B",
}


def _family_name(family: str) -> str:
    """把 family 值（fabric/quilt/forge）转成可读加载器名。"""
    try:
        return loader_name(family)
    except Exception:  # noqa: BLE001
        return family or "?"


def _localize(f: "mod_check.Finding") -> tuple[str, str, str]:
    """返回 (title, reason, suggestion) 的本地化文案。"""
    meta = dict(f.meta)
    if f.kind == "loader_mismatch":
        meta = dict(meta)
        meta["family"] = _family_name(meta.get("family", ""))
        meta["inst_loader"] = _family_name(meta.get("inst_loader", ""))
    title = t(f.title, default=f.kind)
    reason = t(f.reason, default="", **meta)
    suggestion = t(f.suggestion, default="", **meta)
    return title, reason, suggestion


class ModCheckDialog(QDialog):
    def __init__(self, inst, result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("modcheck.dialog_title"))
        self.setMinimumSize(560, 460)
        result = result or {}
        findings = result.get("findings") or []
        scanned = result.get("scanned", 0)
        n_crit = result.get("critical", 0)
        n_warn = result.get("warning", 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # header
        if not findings:
            root.addWidget(ui_kit.page_header(
                t("modcheck.title"), f"{t('modcheck.ok')} · {t('modcheck.scanned', n=scanned, c=0)}"))
            btn = ui_kit.make_button(t("common.close"), kind="accent",
                                     on_click=self.accept, min_h=36)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(btn)
            root.addLayout(row)
            return

        root.addWidget(ui_kit.page_header(
            t("modcheck.title"),
            t("modcheck.scanned", n=scanned, c=n_crit + n_warn)))

        # scrollable finding cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(10)

        for f in findings:
            color = _SEV_COLOR.get(f.severity, COLORS["text_sub"])
            title, reason, suggestion = _localize(f)
            card = _FindingCard(color, title, reason, suggestion, f.filenames)
            col.addWidget(card)
        col.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        close = ui_kit.make_button(t("common.close"), kind="accent",
                                   on_click=self.accept, min_h=36)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)


class _FindingCard(QFrame):
    def __init__(self, color: str, title: str, reason: str,
                 suggestion: str, filenames: list[str]):
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet(
            f"#card {{ background: {COLORS.get('card', '#FFFFFF')};"
            f" border-radius: 10px; border: 1px solid {COLORS.get('border', '#E5E7EB')}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 800; color: {color};")
        v.addWidget(title_lbl)

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


def open_check_dialog(parent, inst):
    """便捷入口：扫描一次并弹窗展示结果（跑在 UI 线程，纯静态读取、毫秒级）。"""
    result = mod_check.scan_conflicts(inst)
    ModCheckDialog(inst, result, parent=parent).exec()