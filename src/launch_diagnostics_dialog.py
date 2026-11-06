"""启动诊断对话框（round-177）。

实例详情页原来有一个叫「启动」的按钮，实际只 ``set_current()`` + 刷新，
既不启动游戏也不跳首页，玩家点了像死了一样。按用户要求保留按钮但换成
「体检 / 启动诊断」——把 PCL2 类启动器的「版本诊断」补上，同时承接真机
验收需要的「启动命令 / classpath / 缺库」对照视图。

两页：
  1. 启动命令：用占位账号调用真正的 ``build_options`` + ``get_command``，
     展示完整 Java 命令行（token 恒为占位符，不泄露凭证）、classpath 条目
     数与缺失条目。拼不出来时明确显示原因，不假装成功。
  2. 实例体检：复用 ``core.instance_health.scan_health``，列出发现项摘要，
     并提供「打开完整体检」跳到已有的一键修复对话框。

所有读取都是静态的、毫秒级；不联网、不改文件、不启动游戏。
"""
from __future__ import annotations

import os
import subprocess

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QPlainTextEdit,
    QPushButton, QLabel,
)

from .i18n import t
from .theme import COLORS


_PLACEHOLDER_TOKEN = "<ACCESS_TOKEN>"
_PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"


def _setting(inst, key, default=""):
    try:
        from .settings_dialog import load_config
        cfg = load_config() or {}
    except Exception:  # noqa: BLE001 - 配置读不到不阻断诊断
        cfg = {}
    val = getattr(inst, key, "")
    return val if val not in (None, "") else cfg.get(key, default)


def _command_report(inst) -> str:
    """拼一份可核对的启动命令报告；任何失败都如实写进报告。"""
    lines = []
    mc_dir = getattr(inst, "game_dir", "") or getattr(inst, "mc_dir", "")
    version = (getattr(inst, "version_id", "") or
               getattr(inst, "game_version", "") or "")
    java = _setting(inst, "java_path", "java")
    loader = getattr(inst, "loader", "") or "vanilla"
    lines.append(t("diag.info.instance", name=getattr(inst, "name", "")))
    lines.append(t("diag.info.version", version=version, loader=loader))
    lines.append(t("diag.info.java", java=java or "java"))
    lines.append(t("diag.info.gamedir", path=mc_dir))
    lines.append("")
    try:
        from . import launch
        try:
            ram = int(getattr(inst, "ram_mb", 0) or
                      (_setting(inst, "ram_mb", 4096) or 4096))
        except (TypeError, ValueError):
            ram = 4096
        options = launch.build_options(
            "Player", _PLACEHOLDER_UUID, _PLACEHOLDER_TOKEN,
            mc_dir=mc_dir,
            java=java or "java",
            ram_mb=ram,
            jvm_args=getattr(inst, "jvm_args", "") or "",
        )
        cmd = launch.get_command(version, mc_dir, options)
    except Exception as e:  # noqa: BLE001 - 诊断必须能显示「为什么拼不出来」
        lines.append(t("diag.cmd_failed", err=e))
        lines.append(t("diag.cmd_hint"))
        return "\n".join(lines)

    entries = launch._classpath_entries(cmd)
    missing = launch._missing_classpath(cmd)
    lines.append(t("diag.info.classpath", count=len(entries)))
    if missing:
        lines.append(t("diag.info.missing", count=len(missing)))
        for p in missing[:20]:
            lines.append("  - " + p)
        if len(missing) > 20:
            lines.append("  ... (%d)" % (len(missing) - 20))
    else:
        lines.append(t("diag.info.classpath_ok"))
    lines.append("")
    lines.append(t("diag.cmd_hint"))
    lines.append("")
    if os.name == "nt":
        lines.append(subprocess.list2cmdline(list(cmd)))
    else:
        lines.append(" ".join(cmd))
    return "\n".join(lines)


def _health_report(inst) -> str:
    lines = []
    try:
        from .core import instance_health
        result = instance_health.scan_health(inst, None)
    except Exception as e:  # noqa: BLE001
        return t("diag.health_failed", err=e)
    lines.append(t("diag.health_summary",
                   critical=result.get("critical", 0),
                   warning=result.get("warning", 0),
                   info=result.get("info", 0),
                   fixable=result.get("fixable", 0),
                   scanned=result.get("scanned", 0)))
    lines.append("")
    findings = result.get("findings", []) or []
    if not findings:
        lines.append(t("diag.no_findings"))
        return "\n".join(lines)
    for f in findings:
        sev = getattr(f, "severity", "info")
        mark = {"critical": "[!!]", "warning": "[! ]", "info": "[i ]"}.get(sev, "[i ]")
        title = getattr(f, "title", "") or ""
        try:
            title = t(title, default=title, **(getattr(f, "meta", {}) or {}))
        except Exception:  # noqa: BLE001 - 占位符不齐就显示原文
            pass
        names = getattr(f, "filenames", []) or []
        suffix = ("  " + ", ".join(names[:3])) if names else ""
        lines.append("%s %s%s" % (mark, title, suffix))
    return "\n".join(lines)


class LaunchDiagnosticsDialog(QDialog):
    def __init__(self, inst, mgr=None, parent=None):
        super().__init__(parent)
        self.inst = inst
        self.mgr = mgr
        self.setWindowTitle(t("diag.title", name=getattr(inst, "name", "")))
        self.resize(900, 580)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QLabel(t("diag.subtitle"))
        head.setStyleSheet("color: %s; font-size: 12px;" % COLORS["text_sub"])
        root.addWidget(head)

        self._tabs = QTabWidget()
        self._cmd_view = self._text_view()
        self._cmd_view.setPlainText(_command_report(inst))
        self._tabs.addTab(self._cmd_view, t("diag.tab_command"))
        self._health_view = self._text_view()
        self._health_view.setPlainText(_health_report(inst))
        self._tabs.addTab(self._health_view, t("diag.tab_health"))
        root.addWidget(self._tabs, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        self._copy_btn = QPushButton(t("diag.copy"))
        self._copy_btn.clicked.connect(self._copy)
        row.addWidget(self._copy_btn)
        self._health_btn = QPushButton(t("diag.open_health"))
        self._health_btn.clicked.connect(self._open_health)
        row.addWidget(self._health_btn)
        close_btn = QPushButton(t("diag.close"))
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        root.addLayout(row)

    @staticmethod
    def _text_view() -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        view.setStyleSheet(
            "QPlainTextEdit { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 8px; padding: 10px; font-family: Consolas, monospace;"
            " font-size: 12px; }" % (
                COLORS.get("bg_input", "#F8F9FA"),
                COLORS["text_main"], COLORS["border"]))
        return view

    def _copy(self):
        from PySide6.QtWidgets import QApplication
        text = (self._cmd_view.toPlainText() if self._tabs.currentIndex() == 0
                else self._health_view.toPlainText())
        QApplication.clipboard().setText(text)
        self._copy_btn.setText(t("diag.copied"))

    def _open_health(self):
        from .mod_check_dialog import open_health_dialog
        open_health_dialog(self, self.inst, mgr=self.mgr)


def open_launch_diagnostics(parent, inst, mgr=None) -> None:
    """便捷入口：静态扫描一次并弹诊断框。"""
    LaunchDiagnosticsDialog(inst, mgr=mgr, parent=parent).exec()
