"""Scan dialog / panel — discover & import existing MC instances.

Two public classes are provided:

* :class:`ScanPanel` — the scanner UI as a plain QWidget. It can be embedded
  directly into another page (home / instances) so no modal dialog is needed.
* :class:`ScanDialog` — a thin frameless dialog wrapper around :class:`ScanPanel`
  for callers that still want a popup.

The disk scan runs on a Worker thread so the UI never freezes.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QWidget, QProgressBar, QLineEdit,
    QScrollArea, QApplication, QProgressDialog, QToolButton,
)
from PySide6.QtCore import Qt, QSize, QTimer, Signal

import time

from .icons import icon
from .theme import COLORS, with_alpha
from .i18n import t
from .worker import Worker
from .scan import discover_instances, ScannedInstance
from .instances import manager as instances_manager, _CopyFailed, launcher_label
from .frameless import FramelessHelper, TitleBar
from .win_rounded import _msgbox, info, warn


class _InstanceRow(QWidget):
    """One discovered instance: details + an Import button."""

    def __init__(self, inst: ScannedInstance, on_import):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        info = QLabel()
        info.setTextFormat(Qt.RichText)
        extra = []
        if inst.mods:
            extra.append(t("scan.mods") + f" {inst.mods}")
        if inst.resource_packs:
            extra.append(t("scan.respacks") + f" {inst.resource_packs}")
        if inst.shaders:
            extra.append(t("scan.shaders") + f" {inst.shaders}")
        if inst.saves:
            extra.append(t("scan.saves") + f" {inst.saves}")
        sub_color = COLORS.get("text_sub", "#6B7280")
        warn_color = COLORS.get("warn", "#EAB308")
        from .instances import launcher_label
        detail = f"{t('scan.launcher')} {launcher_label(inst.launcher, show_original=True)}  ·  " \
                 f"{t('scan.version')} {inst.game_version}  ·  " \
                 f"{t('scan.loader')} {inst.loader}"
        if inst.version_id and inst.version_id != inst.game_version:
            detail += f"  ·  ID: {inst.version_id}"
        if extra:
            detail += f"<br><span style='color:{sub_color};font-size:11px'>" + \
                "  ·  ".join(extra) + "</span>"
        if inst.note:
            note_text = t("scan.note_" + inst.note)
            detail += f"<br><span style='color:{warn_color};font-size:11px'>注意：{note_text}</span>"
        if not inst.isolated:
            detail += f"<br><span style='color:{warn_color};font-size:11px'>注意：{t('scan.row_shared')}</span>"
        info.setText(f"<b>{inst.name}</b><br><span style='color:{sub_color}'>{detail}</span>")

        lay.addWidget(info, stretch=1)

        # 未导入标记：让玩家一眼看出"这只是发现，还没归 AC 管"。
        self.state_lbl = QLabel(t("scan.not_imported"))
        self.state_lbl.setStyleSheet(
            f"color: {COLORS['warn']};"
            f" background: {with_alpha(COLORS['warn'], 0x1F)}; "
            f"border-radius: 9px; padding: 2px 10px; font-size: 11px;"
        )
        lay.addWidget(self.state_lbl)

        self.btn = QPushButton(t("scan.import"))
        self.btn.setMinimumHeight(32)
        self.btn.setIcon(icon("import"))
        self.btn.setIconSize(QSize(16, 16))
        self.btn.clicked.connect(lambda: on_import(inst, self.btn))
        lay.addWidget(self.btn)

        self._path = inst.mc_dir

    @property
    def path(self):
        return self._path

    def mark_imported(self):
        self.state_lbl.setText(t("scan.imported"))
        self.state_lbl.setStyleSheet(
            f"color: {COLORS['success']};"
            f" background: {with_alpha(COLORS['success'], 0x1F)}; "
            f"border-radius: 9px; padding: 2px 10px; font-size: 11px;"
        )
        self.btn.setText(t("scan.imported"))
        self.btn.setEnabled(False)
        self.btn.setStyleSheet(
            f"QPushButton {{ background:{COLORS['bg_panel']}; "
            f"color:{COLORS['text_sub']}; border:1px solid {COLORS['border']}; }}"
        )


class ScanPanel(QWidget):
    """Reusable scanner widget: search disk for MC instances and import them.

    Emits :attr:`done` when the user clicks the back/close button. Imported
    directories are accumulated in :attr:`imported_dirs` so the host page can
    refresh itself and unlock achievements.
    """

    done = Signal()

    def __init__(self, parent=None, auto_scan: bool = True):
        super().__init__(parent)
        self._imported: set[str] = set()
        self._build_ui()
        if auto_scan:
            QTimer.singleShot(50, self._run_scan)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── scrollable content (head, toolbar, cols) ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        scroll_content = QWidget()
        bl = QVBoxLayout(scroll_content)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(14)

        head = QLabel(t("scan.help"))
        head.setProperty("cls", "sub")
        head.setWordWrap(True)
        bl.addWidget(head)

        # toolbar
        bar = QHBoxLayout()
        self.scan_btn = QPushButton(t("scan.start"))
        self.scan_btn.setMinimumHeight(38)
        self.scan_btn.setIcon(icon("refresh"))
        self.scan_btn.setIconSize(QSize(18, 18))
        self.scan_btn.clicked.connect(self._run_scan)
        bar.addWidget(self.scan_btn)
        # 一键导入全部（快速配置）
        self.import_all_btn = QPushButton(t("scan.import_all"))
        self.import_all_btn.setProperty("cls", "accent")
        self.import_all_btn.setMinimumHeight(38)
        self.import_all_btn.setIcon(icon("import"))
        self.import_all_btn.setIconSize(QSize(18, 18))
        self.import_all_btn.clicked.connect(self._import_all)
        self.import_all_btn.setEnabled(False)
        bar.addWidget(self.import_all_btn)
        self.summary = QLabel("")
        self.summary.setProperty("cls", "sub")
        self.summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar.addWidget(self.summary, stretch=1)
        bl.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setMaximum(0)  # indeterminate
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        bl.addWidget(self.progress)

        # body: instances | java (wider ratio: 3:2 instead of 3:1)
        cols = QHBoxLayout()
        cols.setSpacing(14)

        # ── instances column ──
        col_l = QVBoxLayout()
        col_l.setSpacing(6)
        lbl_l = ui_kit.group_label(t("scan.instances"))
        col_l.addWidget(lbl_l)

        # search box + manual import
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("search.placeholder", default="搜索实例…"))
        self.search_input.setMinimumHeight(30)
        self.search_input.setMinimumWidth(180)  # prevent placeholder clipping
        self.search_input.textChanged.connect(self._filter_instances)
        search_row.addWidget(self.search_input, stretch=1)
        self.search_count = QLabel("")
        self.search_count.setProperty("cls", "sub")
        search_row.addWidget(self.search_count)
        import_folder_btn = QPushButton(t("scan.import_folder"))
        import_folder_btn.setMinimumHeight(30)
        import_folder_btn.clicked.connect(self._import_folder)
        search_row.addWidget(import_folder_btn)
        col_l.addLayout(search_row)

        self.inst_list = QListWidget()
        self.inst_list.setSpacing(6)
        col_l.addWidget(self.inst_list, stretch=1)
        cols.addLayout(col_l, stretch=1)

        bl.addLayout(cols, stretch=1)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, stretch=1)

        # ── footer (always visible) ──
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 10, 20, 10)
        foot.addStretch(1)
        close_btn = QPushButton(t("common.close"))
        close_btn.setMinimumHeight(34)
        close_btn.clicked.connect(self.done.emit)
        foot.addWidget(close_btn)
        root.addLayout(foot)

    # ------------------------------------------------------------------ properties
    @property
    def imported_dirs(self) -> set[str]:
        """Directories that were successfully imported during this session."""
        return set(self._imported)

    # ---------- scanning ----------
    def _run_scan(self):
        self.scan_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.summary.setText(t("scan.scanning"))
        self._worker = Worker(self._do_scan)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(lambda e: self.summary.setText(f"Error: {e}"))
        self._worker.start()

    @staticmethod
    def _do_scan():
        # Java scanning now lives in Settings → Manage / Download Java.
        # The instance scanner only finds importable .minecraft instances.
        return discover_instances()

    def _on_done(self, instances):
        self._populate(instances)
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.summary.setText(t("scan.scan_summary", n=len(instances)))
        # 一键导入全部：有未导入实例时启用
        self.import_all_btn.setEnabled(
            bool(self._all_instances) and
            any(i.mc_dir not in self._imported for i in self._all_instances)
        )

    # ---------- display ----------
    def _populate(self, instances: list[ScannedInstance]):
        # store full list for search filtering
        self._all_instances = instances
        self._rebuild_instance_list(instances)

    def _rebuild_instance_list(self, instances: list[ScannedInstance]):
        """Rebuild the instance list, optionally filtered by search text."""
        self.inst_list.clear()
        query = self.search_input.text().strip().lower() if hasattr(self, 'search_input') else ""

        if query:
            instances = [i for i in instances if query in i.name.lower() or
                         query in i.launcher.lower() or
                         query in (i.game_version or "").lower()]

        if not instances:
            item = QListWidgetItem(t("scan.no_instances"))
            item.setFlags(Qt.NoItemFlags)
            item.setTextAlignment(Qt.AlignCenter)
            self.inst_list.addItem(item)
        else:
            groups: dict[str, list[ScannedInstance]] = {}
            for inst in instances:
                groups.setdefault(inst.launcher, []).append(inst)
            # round-44 折叠按钮：可点击 ▾/▸ 切换显隐，_group_rows 维护映射
            # round-97：组键是内部码（如 "PCL-CE"），组头文字是显示名（"PCL2"），
            # 无法靠文字匹配回键——必须直接持有组头按钮引用（_group_headers）。
            self._group_rows: dict[str, list] = {}
            self._group_headers: dict[str, QToolButton] = {}
            for launcher, grp in groups.items():
                hdr = QListWidgetItem()
                hbtn = QToolButton()  # round-44：折叠按钮可点
                hbtn.setText(f"▾ {launcher_label(launcher, show_original=True)}  ({len(grp)})")
                hbtn.setProperty("cls", "group")
                hbtn.setMinimumHeight(30)
                hbtn.setStyleSheet(
                    "background: transparent; border: none; padding: 4px 8px;"
                    "text-align: left; font-weight: 600;")
                hbtn.setCursor(Qt.PointingHandCursor)
                row_items: list[QListWidgetItem] = []
                hbtn.clicked.connect(
                    lambda _=False, k=launcher: self._toggle_group(k))
                hdr.setSizeHint(QSize(100, 30))
                self.inst_list.addItem(hdr)
                self.inst_list.setItemWidget(hdr, hbtn)
                for inst in grp:
                    row = _InstanceRow(inst, self._import)
                    item = QListWidgetItem()
                    hint = row.sizeHint()
                    # round-97：行宽封顶到列表视口宽。QListWidget 的 sizeHint 会随
                    # 行内容（长实例名/长详情）无限撑宽，把整个面板顶出横向溢出，
                    # 右侧"导入/计数/导入文件"被裁掉。封顶后行内布局自动压缩详情区。
                    hint.setWidth(max(self.inst_list.viewport().width() - 24, 320))
                    item.setSizeHint(hint)
                    self.inst_list.addItem(item)
                    self.inst_list.setItemWidget(item, row)
                    row_items.append(item)
                self._group_rows[launcher] = row_items
                self._group_headers[launcher] = hbtn

        # update count label
        if hasattr(self, 'search_count'):
            total = len(self._all_instances) if hasattr(self, '_all_instances') else len(instances)
            shown = len(instances)
            if query and shown != total:
                self.search_count.setText(f"{shown} / {total}")
            else:
                self.search_count.setText(f"{total}")

    def _filter_instances(self):
        """Called on every keystroke in the search box."""
        if hasattr(self, '_all_instances'):
            self._rebuild_instance_list(self._all_instances)

    def _toggle_group(self, launcher: str) -> None:
        """round-44：切换某个 launcher 折叠/展开（▾/▸）。"""
        items = getattr(self, "_group_rows", {}).get(launcher)
        hbtn = getattr(self, "_group_headers", {}).get(launcher)
        if not items or hbtn is None:
            return
        any_visible = any(not it.isHidden() for it in items)
        target = any_visible  # 当前可见 → 折叠；当前隐藏 → 展开
        for row in items:
            row.setHidden(target)
        # 只替换行首 ▾/▸ 箭头，保留其余文字（round-97：老实现截断字符会
        # 累积空格，且靠文字反查按钮在显示名≠内部码时永远匹配不上）。
        text = hbtn.text()
        while text and text[0] in ("▾", "▸", " "):
            text = text[1:]
        hbtn.setText(("▸" if target else "▾") + " " + text)

    # ---------- import ----------
    def _choose_mode(self, inst: ScannedInstance) -> str | None:
        """Ask the user: take over in place, or copy into AC.

        Returns "link" / "copy" / None (cancelled).
        """
        detail = ""
        if inst.needs_convert:
            detail = t("scan.import_warn_convert")
        elif not inst.isolated:
            detail = t("scan.import_shared_warn")
        detail += "\n\n" + f"{t('scan.import_link_hint')}\n\n{t('scan.import_copy_hint')}"

        result = _msgbox(
            self.window(),
            t("scan.import_title"),
            t("scan.import_body", launcher=launcher_label(inst.launcher, show_original=True),
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

    def _do_import(self, inst: ScannedInstance, btn: QPushButton, mode: str) -> bool:
        self._copy_cancelled = False
        if mode == "copy":
            return self._do_import_copy(inst, btn)
        return self._do_import_link(inst, btn)

    def _do_import_link(self, inst: ScannedInstance, btn: QPushButton) -> bool:
        try:
            instances_manager().import_external(
                mc_dir=inst.mc_dir,
                name=inst.name,
                game_version=inst.game_version,
                loader=inst.loader,
                loader_version=inst.loader_version,
                version_id=inst.version_id,
                kind=inst.kind,
                needs_convert=inst.needs_convert,
                mode="link",
                launcher=inst.launcher,
            )
            return True
        except Exception as e:  # noqa: BLE001
            btn.setText(f"Error: {e}")
            return False

    def _do_import_copy(self, inst: ScannedInstance, btn: QPushButton) -> bool:
        """Copy into AC with a live progress dialog.

        Returns True on success. On an explicit user cancel we import nothing
        (never silently fall back to a link); on a genuine copy failure we
        fall back to an in-place link exactly like before.
        """
        progress = QProgressDialog(self.window())
        progress.setWindowTitle(t("scan.copying_title"))
        progress.setLabelText(t("scan.copying", name=inst.name))
        progress.setCancelButtonText(t("common.cancel"))
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)   # show immediately
        progress.setAutoClose(False)     # we close it ourselves
        progress.setAutoReset(False)     # don't reset value on setValue
        progress.setMinimumWidth(420)
        progress.setValue(0)

        last_refresh = [0.0]

        def on_progress(copied: int, total: int, rel: str) -> bool:
            now = time.monotonic()
            # Throttle to ~20 Hz so fast copies don't repaint per file.
            if now - last_refresh[0] < 0.05 and copied < total:
                return not progress.wasCanceled()
            last_refresh[0] = now
            progress.setMaximum(total or 1)
            progress.setValue(copied)
            if rel:
                progress.setLabelText(t("scan.copying_file", file=rel))
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            instances_manager().import_external(
                mc_dir=inst.mc_dir,
                name=inst.name,
                game_version=inst.game_version,
                loader=inst.loader,
                loader_version=inst.loader_version,
                version_id=inst.version_id,
                kind=inst.kind,
                needs_convert=inst.needs_convert,
                mode="copy",
                launcher=inst.launcher,
                on_progress=on_progress,
            )
            progress.setValue(progress.maximum())
            progress.close()
            return True
        except _CopyFailed as e:
            progress.close()
            if progress.wasCanceled():
                # User pressed Cancel — import nothing, don't silently link.
                self._copy_cancelled = True
                warn(self.window(), t("scan.copying_title"), t("scan.copy_aborted"))
                return False
            # Genuine copy failure — fall back to an in-place link.
            try:
                instances_manager().import_external(
                    mc_dir=inst.mc_dir,
                    name=inst.name,
                    game_version=inst.game_version,
                    loader=inst.loader,
                    loader_version=inst.loader_version,
                    version_id=inst.version_id,
                    kind=inst.kind,
                    needs_convert=inst.needs_convert,
                    mode="link",
                    launcher=inst.launcher,
                )
                info(
                    self.window(), t("scan.import_title"),
                    t("scan.copy_failed", err=str(e)),
                )
                return True
            except Exception as e2:  # noqa: BLE001
                btn.setText(f"Error: {e2}")
                return False
        except Exception as e:  # noqa: BLE001
            progress.close()
            btn.setText(f"Error: {e}")
            return False

    def _import(self, inst: ScannedInstance, btn: QPushButton):
        if inst.mc_dir in self._imported:
            return
        mode = self._choose_mode(inst)
        if mode is None:
            return
        if self._do_import(inst, btn, mode):
            self._imported.add(inst.mc_dir)
            for i in range(self.inst_list.count()):
                w = self.inst_list.itemWidget(self.inst_list.item(i))
                if isinstance(w, _InstanceRow) and w.path == inst.mc_dir:
                    w.mark_imported()
                    break

    def _import_all(self):
        """一键导入所有未导入实例：先统一问一次接管/复制，再批量执行。

        Reuses the same link/copy choice as the per-row import so behaviour
        is consistent; just asks once up front.
        """
        pending = [
            i for i in self._all_instances if i.mc_dir not in self._imported
        ]
        if not pending:
            return
        detail = t("scan.import_all_hint") + "\n\n" + \
            f"{t('scan.import_link_hint')}\n\n{t('scan.import_copy_hint')}"
        result = _msgbox(
            self.window(),
            t("scan.import_all_title"),
            t("scan.import_all_body", n=len(pending)),
            detail=detail,
            icon="question",
            buttons=(t("scan.import_link"), t("scan.import_copy")),
        )
        if result == t("scan.import_copy"):
            mode = "copy"
        elif result == t("scan.import_link"):
            mode = "link"
        else:
            return
        ok, fail = 0, 0
        for inst in pending:
            if self._do_import(inst, self._dummy_btn(), mode):
                self._imported.add(inst.mc_dir)
                ok += 1
            else:
                fail += 1
                if getattr(self, "_copy_cancelled", False):
                    break  # user cancelled mid-copy — stop the rest
            for i in range(self.inst_list.count()):
                w = self.inst_list.itemWidget(self.inst_list.item(i))
                if isinstance(w, _InstanceRow) and w.path == inst.mc_dir:
                    w.mark_imported()
                    break
        self.import_all_btn.setEnabled(False)
        if fail:
            self.summary.setText(t("scan.import_all_done_partial", ok=ok, fail=fail))
        else:
            self.summary.setText(t("scan.import_all_done", n=ok))

    @staticmethod
    def _dummy_btn():
        class _DummyBtn:
            def setText(self, t): ...
            def setEnabled(self, e): ...
            def setStyleSheet(self, s): ...
        return _DummyBtn()

    def _import_folder(self):
        """Let the user pick a .minecraft folder manually and import it."""
        from .win_rounded import pick_files
        folder = pick_files(
            self.window(), t("scan.select_folder"), "", dir_only=True,
        )
        if not folder:
            return

        # Validate: must look like a MC game directory
        from .scan import _is_mc_dir, _guess_launcher, _loader_from_text
        import os

        # If user selected the parent of .minecraft, accept both
        mc_dir = folder
        alt_mc = os.path.join(folder, ".minecraft")
        if not _is_mc_dir(mc_dir) and _is_mc_dir(alt_mc):
            mc_dir = alt_mc

        if not _is_mc_dir(mc_dir):
            warn(
                self.window(), t("scan.import_title"),
                t("scan.not_mc_dir", path=folder),
            )
            return

        # Auto-detect basic info from the folder structure
        name = os.path.basename(os.path.dirname(mc_dir)) or os.path.basename(mc_dir)
        game_version = "?"
        versions_dir = os.path.join(mc_dir, "versions")
        if os.path.isdir(versions_dir):
            try:
                for e in os.scandir(versions_dir):
                    if e.is_dir() and os.path.isfile(
                        os.path.join(e.path, e.name + ".json")
                    ):
                        game_version = e.name
                        break
            except OSError:
                pass

        launcher = _guess_launcher(mc_dir)
        loader = "vanilla"
        # Check for mods folder to detect loaders
        mods_dir = os.path.join(mc_dir, "mods")
        if os.path.isdir(mods_dir):
            try:
                for f in os.listdir(mods_dir):
                    fl = f.lower()
                    if fl.endswith(".jar"):
                        loader = _loader_from_text(f)
                        break
            except OSError:
                pass

        inst = ScannedInstance(
            launcher=launcher,
            name=name or t("scan.manual_instance"),
            game_version=game_version,
            loader=loader,
            mc_dir=mc_dir,
            kind="standard",
        )

        # Show the instance in the list and let user confirm import mode
        # (re-use the existing _choose_mode flow)
        mode = self._choose_mode(inst)
        if mode is None:
            return

        # Use a dummy button reference for error display
        class _DummyBtn:
            def setText(self, t): ...
            def setEnabled(self, e): ...
            def setStyleSheet(self, s): ...

        if self._do_import(inst, _DummyBtn(), mode):
            self._imported.add(mc_dir)
            # Re-run scan to pick up the newly imported instance
            self.summary.setText(t("scan.folder_imported", name=name))
            # Refresh instance list by re-running scan
            self._run_scan()


class ScanDialog(QDialog):
    """Frameless popup wrapper around :class:`ScanPanel`.

    Kept for callers that still need a dialog; the main home/instances pages
    now embed :class:`ScanPanel` directly instead.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("scan.title"))
        self.resize(960, 660)
        self.setMinimumSize(840, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Only the close button — minimize/maximize on a modal dialog can
        # resize the parent window or leave the dialog in a weird state.
        self.titlebar = TitleBar(
            self, title=t("scan.title"), height=38, controls="close"
        )
        root.addWidget(self.titlebar)

        self.panel = ScanPanel(self, auto_scan=True)
        self.panel.done.connect(self.accept)
        root.addWidget(self.panel, stretch=1)

        # frameless + DWM shadow + win11 rounded corners
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)
