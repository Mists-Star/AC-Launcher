"""CrashAnalyzerDialog — read an instance's logs / crash reports, explain the
crash in plain language, and offer one-click auto-repair for fixable causes
(mod dependency download, Java switch, memory bump).

Opened from the instance card / home page "崩溃分析" button. Pure Qt, reuses
the worker-thread pattern for anything network-ish.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QProgressBar, QWidget,
)
from PySide6.QtCore import Qt, Signal, QRect

from .theme import COLORS, RoundedCard
from .icons import icon
from .i18n import t
from .win_rounded import _msgbox
from .fix_feedback import attach, report, summarize
from .worker import Worker
from .panel_shell import PanelCloseMixin, PanelShellMixin
from . import crash_analysis as crash
from .instances import manager


_SEV_COLOR = {
    "critical": "#EF4444",
    "warning":  "#F59E0B",
    "info":     "#6B7280",
}


class _FindingCard(RoundedCard):
    """One crash finding: severity dot + title + reason + suggestion + actions."""

    def __init__(self, finding: crash.CrashFinding, on_repair, on_fix_java, on_fix_ram,
                 parent=None):
        super().__init__(radius=12, parent=parent)
        self.finding = finding
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # ── header: severity dot + title ──
        head = QHBoxLayout()
        dot = QLabel()
        dot.setFixedSize(10, 10)
        color = _SEV_COLOR.get(finding.severity, COLORS["text_sub"])
        dot.setStyleSheet(f"background:{color}; border-radius:5px;")
        head.addWidget(dot)
        title = QLabel(t(finding.title))
        title.setProperty("cls", "big")
        title.setStyleSheet(f"color:{color};")
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        # ── reason + suggestion ──
        reason = QLabel(t(finding.reason))
        reason.setProperty("cls", "sub")
        reason.setWordWrap(True)
        lay.addWidget(reason)
        # round-204：点名可疑模组 —— 光说「日志里有 Exception」不构成结论。
        if getattr(finding, "culprit", ""):
            cl = QLabel(t("crash.culprit", default="可疑模组：{name}",
                          name=finding.culprit))
            cl.setProperty("cls", "sub")
            cl.setStyleSheet(
                "color:%s; font-weight:600;" % COLORS.get("warning", "#F59E0B"))
            cl.setWordWrap(True)
            lay.addWidget(cl)
        # round-91 去掉文本 💡 前缀（Windows 下渲染成彩色 emoji，风格突兀）；用 QHBox 自带圆点色块即表达建议层级
        sug = QLabel(t(finding.suggestion))
        sug.setProperty("cls", "sub")
        sug.setWordWrap(True)
        lay.addWidget(sug)

        # ── raw detail (collapsible-ish: show excerpt) ──
        if finding.detail:
            # round-196：原来按字符硬切 220（半句话，没省略号）→ 改成完整显示
            # （最多 6 行）+ tooltip 给全文，不再"截断"。
            det = QLabel(finding.detail.strip())
            det.setWordWrap(True)
            det.setToolTip(finding.detail.strip())
            _fm = det.fontMetrics()
            _w = max(240, det.width() or 420)
            # round-218：原来调的是 ``boundingRect(w, 0, Qt.TextWordWrap, text)``——
            # 这个重载在 PySide6 里**不存在**（只有 QRect 版 / 纯文本版），
            # 于是每张带 detail 的结论卡都在构造时抛 TypeError。异常冒到
            # ``_on_analyzed`` 的循环里 → **后面的卡全没了**，而且
            # ``repair_all_btn.setEnabled(...)`` 那行根本执行不到 →
            # 「发现 2 个问题」但列表空白、「一键修复」按钮永远点不动。
            _lines = max(1, _fm.boundingRect(
                QRect(0, 0, _w, 4096), Qt.TextWordWrap,
                finding.detail.strip()).height()
                // max(1, _fm.lineSpacing()))
            det.setMaximumHeight(min(_lines, 6) * _fm.lineSpacing() + 4)
            det.setProperty("cls", "sub")
            det.setStyleSheet(
                f"font-size:11px; color:{COLORS['text_sub']};"
                f"background:{COLORS['bg_panel']}; border-radius:6px;"
                f"padding:8px; font-family:'Consolas','Menlo',monospace;"
            )
            det.setWordWrap(True)
            det.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(det)

        # ── actions ──
        acts = QHBoxLayout()
        acts.addStretch(1)
        if finding.kind == "mod_dep_missing":
            btn = QPushButton(icon("repair"), t("crash.btn_repair_deps"))
            btn.setProperty("cls", "accent")
            btn.setMinimumHeight(32)
            btn.clicked.connect(lambda: on_repair(finding))
            acts.addWidget(btn)
        elif finding.kind == "java_version":
            btn = QPushButton(icon("java"), t("crash.btn_fix_java"))
            btn.setProperty("cls", "accent")
            btn.setMinimumHeight(32)
            btn.clicked.connect(on_fix_java)
            acts.addWidget(btn)
        elif finding.kind == "out_of_memory":
            btn = QPushButton(icon("settings"), t("crash.btn_fix_ram"))
            btn.setProperty("cls", "accent")
            btn.setMinimumHeight(32)
            btn.clicked.connect(on_fix_ram)
            acts.addWidget(btn)
        lay.addLayout(acts)


# round-219：一条崩溃结论「要不要玩家自己处理」的**唯一判定**。
# 优先用规则表里的 repairable 标记（单一事实来源）；老对象没有这个属性时
# 回退到历史 kind 名单（避免外部/旧代码构造的结论被静默丢掉）。
_ACTIONABLE_KINDS = ("mod_dep_missing", "java_version", "out_of_memory",
                     "loader_mismatch")


def _is_actionable(f) -> bool:
    rep = getattr(f, "repairable", None)
    if rep is None:
        return getattr(f, "kind", "") in _ACTIONABLE_KINDS
    return bool(rep)


class CrashAnalyzerPanel(PanelCloseMixin, QWidget):
    """崩溃分析面板（**页内**，round-197）。

    原来�� QDialog 弹窗。它是**实例相关**的分析（崩溃日志、缺前置修复），
    应该在实例页里换页打开，而不是另开窗口 —— round-195 起编辑 / 体检 /
    增强包 / 导出都已经页内化了，崩溃分析是最后一个还在弹窗的实例功能。
    窗口壳 :class:`CrashAnalyzerDialog` 保留给历史调用点。
    """

    closed = Signal()

    def __init__(self, inst=None, parent=None):
        super().__init__(parent)
        self.inst = inst or manager().current()
        self._inst_name = getattr(self.inst, "name", "")
        self._findings: list[crash.CrashFinding] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 页内模式不要 frameless 标题栏（页面自己有标题）→ 普通标题标签
        from .frameless import TitleBar
        self.titlebar = TitleBar(self, title=t("crash.title"), height=38)
        self.titlebar.setVisible(False)      # 页内隐藏；窗口模式再显示
        root.addWidget(self.titlebar)

        # ── head: instance label + analyze button ──
        head = QHBoxLayout()
        head.setContentsMargins(20, 14, 20, 8)
        self.inst_lbl = QLabel()
        self.inst_lbl.setProperty("cls", "big")
        head.addWidget(self.inst_lbl)
        head.addStretch(1)
        self.analyze_btn = QPushButton(icon("refresh"), t("crash.analyze"))
        self.analyze_btn.setMinimumHeight(36)
        self.analyze_btn.clicked.connect(self._run_analyze)
        head.addWidget(self.analyze_btn)
        root.addLayout(head)

        # ── progress / status ──
        self.status = QLabel("")
        self.status.setProperty("cls", "sub")
        self.status.setContentsMargins(20, 0, 20, 4)
        root.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setVisible(False)
        self.bar.setFixedHeight(4)
        root.addWidget(self.bar)

        # ── scrollable findings ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self._content = QWidget()
        self._vbox = QVBoxLayout(self._content)
        self._vbox.setContentsMargins(20, 8, 20, 8)
        self._vbox.setSpacing(12)
        self.scroll.setWidget(self._content)
        root.addWidget(self.scroll, stretch=1)

        # ── footer ──
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 8, 20, 12)
        self.repair_all_btn = QPushButton(icon("repair"), t("crash.repair_all"))
        self.repair_all_btn.setProperty("cls", "accent")
        self.repair_all_btn.setMinimumHeight(36)
        self.repair_all_btn.clicked.connect(self._repair_all)
        self.repair_all_btn.setEnabled(False)
        foot.addWidget(self.repair_all_btn)
        foot.addStretch(1)
        close_btn = QPushButton(t("common.close"))
        close_btn.setMinimumHeight(34)
        close_btn.clicked.connect(self._on_close)
        foot.addWidget(close_btn)

        root.addLayout(foot)

        # round-209：一键修复的可见反馈条。以前结果只写进一行 status 小灰字，
        # 既会被异步 Worker 覆盖，也可能停在 hidden 状态；确认/告警弹窗在
        # frameless 窗口里还可能跑到后面，玩家就看到「点了没反应」。
        self.fix_note = attach(root, self)
        self._repair_manual: list = []
        self._last_deps_note: str = ""

        # ☠ round-197：frameless 只在**窗口模式**启用 —— 页内面板套 frameless
        # 会把控件当成窗口处理（标题栏、圆角、拖拽），在页面里表现为布局跑偏。
        self._frameless = None

        self._update_header()
        self._run_analyze()

    def enable_window_chrome(self) -> None:
        """窗口模式：补上 frameless 标题栏与圆角（页内模式不需要）。"""
        if self._frameless is not None:
            return
        from .frameless import enable_panel_window_chrome
        self.titlebar.setVisible(True)
        self._frameless = enable_panel_window_chrome(self)

    # ------------------------------------------------------------- analyze
    def _update_header(self):
        # round-124：无实例时不再把「请先选择一个实例」拼进标题（与正文重复）
        if self.inst is not None:
            self.inst_lbl.setText(f"{t('crash.title')} — {self.inst.name}")
        else:
            self.inst_lbl.setText(t("crash.title"))

    def _run_analyze(self):
        self.analyze_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setVisible(True)
        self.status.setText(t("crash.analyzing"))
        # analysis is file-I/O only, but keep it off the UI thread anyway
        self._worker = Worker(self._analyze)
        self._worker.finished.connect(self._on_analyzed)
        self._worker.error.connect(lambda e: self.status.setText(str(e)))
        self._worker.start()

    def _analyze(self):
        if self.inst is None:
            return []
        return crash.analyze_instance(self.inst)

    def _on_analyzed(self, findings: list[crash.CrashFinding]):
        self._findings = findings
        self._repair_manual = []
        self.bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        # clear — takeAt removes every item (widgets AND spacers) so repeated
        # analysis cannot pile up stale rows inside the scroll layout.
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not findings:
            # round-124：空态只在正文说一次，头部状态行不再复述同一句话；
            # 无实例时给「请先选择一个实例」，而不是误报「最近一次运行正常」。
            if self.inst is None:
                msg, color = t("crash.no_instance"), COLORS["text_sub"]
            else:
                msg, color = t("crash.no_crash"), COLORS["success"]
            ok = QLabel(msg)
            ok.setProperty("cls", "sub")
            ok.setAlignment(Qt.AlignCenter)
            ok.setWordWrap(True)
            ok.setStyleSheet(f"color:{color}; font-size:14px;")
            self._vbox.addWidget(ok)
            self.status.clear()
            self.status.setVisible(False)
            self.repair_all_btn.setEnabled(False)
            return
        self.status.setVisible(True)
        self.status.setText(t("crash.found", n=len(findings)))
        repairable = 0
        card_errors = 0
        for f in findings:
            # round-218：单张卡渲染失败**不许**拖垮整页 —— 以前异常直接冒到
            # 循环外，后面的结论全没了、按钮也永远保持禁用。现在逐张兜住，
            # 失败的那张跳过并计数，末尾明确告诉玩家「有 N 条没显示出来」。
            try:
                card = _FindingCard(
                    f, self._repair_deps, self._fix_java, self._fix_ram)
            except Exception:  # noqa: BLE001 - 一张坏卡不能带塌整页
                card_errors += 1
                continue
            # round-219：可用性以**规则表自己的 repairable 标记**为准。
            # 原来写死 ("mod_dep_missing", "java_version", "out_of_memory")，
            # 漏了 loader_mismatch —— 而它在 _RULES 里明明标着 repairable=True。
            # 结果：玩家实例命中「加载器不匹配 + 致命异常」时按钮**永久禁用**，
            # 点了像没反应（禁用按钮根本不响应点击）。
            if _is_actionable(f):
                repairable += 1
            self._vbox.addWidget(card)
        self.repair_all_btn.setEnabled(repairable > 0)
        self._vbox.addStretch(1)
        if card_errors:
            report(self, t("crash.card_render_failed", n=card_errors), "warn")

    # ------------------------------------------------------------- repairs
    def _repair_deps(self, _finding=None) -> bool:
        """Scan mods dir for missing deps, then download them (Modrinth).

        round-178：改走 ``core.mod_repair`` 的唯一实现。旧路径把
        「jar 过多导致深扫被跳过」当成「依赖齐全」，且失败原因全折叠成
        一个 modid，玩家分不清「搜不到」还是「下载失败」。
        round-209：所有终态改用页内可见反馈条，返回「是否启动了后台任务」，
        让 ``_repair_all`` 能区分「异步中」与「当场就能汇总」。
        """
        if self.inst is None:
            self._last_deps_note = t("crash.no_instance")
            report(self, self._last_deps_note, "warn")
            return False
        from .core import mod_repair
        scan = mod_repair.scan_missing(self.inst)
        if scan["skipped"]:
            self._last_deps_note = t("crash.deps_skipped", n=scan["jar_count"])
            report(self, self._last_deps_note, "warn")
            return False
        missing = scan["missing"]
        if not missing:
            self._last_deps_note = t("fix.deps_none")
            report(self, self._last_deps_note, "info")
            return False
        if not _msgbox(
            self, t("crash.deps_found_title"),
            t("crash.deps_found_body", n=len(missing)),
            detail="\n".join(f"• {m}" for m in missing),
            icon="question",
            buttons=(t("crash.btn_download"), t("common.cancel")),
        ) == t("crash.btn_download"):
            self._last_deps_note = t("common.cancel")
            report(self, self._last_deps_note, "info")
            return False
        report(self, t("fix.deps_start", n=len(missing)), "busy")
        self.bar.setVisible(True)
        self.status.setText(t("crash.deps_fixing"))
        self._worker = Worker(self._fix_deps_worker, missing)
        self._worker.finished.connect(self._on_deps_done)
        self._worker.error.connect(
            lambda e: report(self, str(e), "warn"))
        self._worker.start()
        return True

    def _fix_deps_worker(self, missing: list[str]):
        from .core import mod_repair
        return mod_repair.repair_missing(self.inst, missing)

    def _on_deps_done(self, result):
        downloaded = result.get("downloaded", []) or []
        failed = result.get("failed", []) or []
        self.bar.setVisible(False)
        self.status.setText(
            t("crash.deps_done", n=len(downloaded)) if downloaded else
            t("crash.deps_failed"))
        if downloaded:
            from .repair_log import append
            from .achievements import achievements as _ach
            inst_name = getattr(self, "_inst_name", "")
            append("mod_dep", t("crash.log_fixed_deps", n=len(downloaded)),
                   instance=inst_name)
            _ach.unlock("first_repair")
        # round-209：结构化汇总终态写进页内反馈条；status 那行小灰字只是兼容。
        manual_findings = list(getattr(self, "_repair_manual", []) or [])
        manual = len(manual_findings)
        text, tone = summarize(len(downloaded), len(failed), manual)
        if failed:
            from .core.mod_repair import failed_lines
            text += "\n" + "\n".join(failed_lines(result))
        # round-219：把要玩家自己处理的条目也列出来（原来只给个数字）
        for line in self._manual_lines(manual_findings):
            text += "\n" + line
        report(self, text, tone)
        self._repair_manual = []

    def _fix_java(self):
        """去管理 Java（round-197）。

        原来这里弹 Java 管理器，而**设置页里也有同一个管理器**（两个入口）。
        现在统一：跳到设置页的 Java 分区（主窗口本来就有
        ``_select_settings_section``）；拿不到主窗口时回退到窗口壳。
        """
        win = self.window() if self is not None else None
        jump = getattr(win, "_select_settings_section", None)
        if callable(jump):
            try:
                jump("java")
                return
            except Exception:  # noqa: BLE001 - 跳不过去就退回弹窗
                pass
        from .java_manager_dialog import JavaManagerDialog
        JavaManagerDialog(self).exec()

    def _fix_ram(self):
        report(self, t("crash.ram_hint"), "info")

    def _repair_all(self):
        """一键修复：先给即时可见反馈，再分流「可自动 / 需手动」，最后汇总终态。

        round-209 修掉三个老毛病：
        1. 点击后没有任何页内可见变化（反馈只写进可能被隐藏的 status 小字）。
        2. 异步还没跑完就写「已自动补装缺失依赖」——谎报成功。
        3. java_version / out_of_memory / loader_mismatch 什么都不做也不说。

        round-219：把「哪些能自动、哪些要玩家配合」改成**按结论逐条分流**，
        并且**每条都要有话说**：
        - ``mod_dep_missing`` → 真能自动补装（走 _repair_deps）；
        - ``java_version`` / ``out_of_memory`` / ``loader_mismatch`` →
          启动器不能替玩家改 Java / 内存 / 换成对的模组，但可以**点名说清**
          哪一条、为什么、该做什么（带建议与可疑模组名）；
        - 其余（致命异常等）→ 明确告知「需人工查看」，并指向可疑模组。

        交互型动作（切 Java、改内存）不塞进异步流程，但会明确列进汇总，
        玩家不会再以为「按钮没用」。
        """
        findings = list(getattr(self, "_findings", None) or [])
        auto_kinds = ("mod_dep_missing",)
        manual = [f for f in findings
                  if f.kind not in auto_kinds and _is_actionable(f)]
        other = [f for f in findings
                 if f.kind not in auto_kinds and not _is_actionable(f)]
        self._repair_manual = manual
        report(self, t("fix.progress"), "busy")

        self._last_deps_note = ""
        started = False
        if any(f.kind in auto_kinds for f in findings):
            started = self._repair_deps()

        if not started:
            # 没有后台任务 = 当场就能给终态；异步路径由 _on_deps_done 汇总。
            # round-219：把「依赖那边说了什么」「哪些要玩家自己处理」「其它结论」
            # **合并成一条**反馈，别互相覆盖（原来只留最后一句，玩家看到的是
            # 「已自动处理 0 项」这种没有信息量的话）。
            parts = []
            note = getattr(self, "_last_deps_note", "") or ""
            if note:
                parts.append(note)
            lines = self._manual_lines(manual)
            if lines:
                parts.append("\n".join(lines))
            if other:
                parts.append(t("fix.need_manual", n=len(other)))
            tone = "warn" if (lines or other) else "info"
            report(self, "\n".join(parts) if parts else
                   t("fix.nothing_to_do"), tone)
            self._repair_manual = []

    @staticmethod
    def _manual_lines(findings) -> list[str]:
        """把「要玩家自己处理」的结论逐条说清楚（含建议与可疑模组）。"""
        lines = []
        for f in findings:
            try:
                title = t(f.title) if getattr(f, "title", "") else ""
                sug = t(f.suggestion) if getattr(f, "suggestion", "") else ""
            except Exception:  # noqa: BLE001 - 缺键就退化成 kind
                title = ""
                sug = ""
            if not title:
                title = getattr(f, "kind", "") or "?"
            line = "• %s" % title
            culprit = getattr(f, "culprit", "") or ""
            if culprit:
                line += "（%s）" % culprit
            if sug:
                line += "：%s" % sug
            lines.append(line)
        return lines


class CrashAnalyzerDialog(PanelShellMixin, QDialog):
    """**兼容壳**：窗口模式（历史调用点）。内部就是 :class:`CrashAnalyzerPanel`。"""

    def __init__(self, inst=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("crash.title"))
        self.resize(720, 620)
        self.setMinimumSize(640, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.panel = CrashAnalyzerPanel(inst, parent=self)
        self.panel.enable_window_chrome()
        lay.addWidget(self.panel)
        self.panel.closed.connect(self.accept)

