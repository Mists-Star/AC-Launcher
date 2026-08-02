"""Scan dialog — discover & import existing MC instances and Java runtimes.

Opened from the home page. Runs the (potentially slow) disk scan on a Worker
thread so the UI never freezes, then shows every instance found across other
launchers plus all detected Java installs. Each instance row has an "Import"
button that links it into AC via InstancesManager.import_external().
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QWidget, QProgressBar, QLineEdit,
    QScrollArea,
)
from PySide6.QtCore import Qt, QSize, QTimer

from .icons import icon
from .theme import COLORS
from .i18n import t
from .worker import Worker
from .scan import discover_instances, ScannedInstance
from .instances import manager as instances_manager, _CopyFailed
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
        detail = f"{t('scan.launcher')} {inst.launcher}  ·  " \
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
            f"color: {COLORS['warn']}; background: {COLORS['warn']}1F; "
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
            f"color: {COLORS['success']}; background: {COLORS['success']}1F; "
            f"border-radius: 9px; padding: 2px 10px; font-size: 11px;"
        )
        self.btn.setText(t("scan.imported"))
        self.btn.setEnabled(False)
        self.btn.setStyleSheet(
            f"QPushButton {{ background:{COLORS['bg_panel']}; "
            f"color:{COLORS['text_sub']}; border:1px solid {COLORS['border']}; }}"
        )


class ScanDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("scan.title"))
        self.resize(960, 660)
        self.setMinimumSize(840, 560)
        self._imported: set[str] = set()

        # ── frameless shell ──
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self, title=t("scan.title"), height=38)
        root.addWidget(self.titlebar)

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
        lbl_l = QLabel(t("scan.instances"))
        lbl_l.setProperty("cls", "group")
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
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        root.addLayout(foot)

        # frameless + DWM shadow + win11 rounded corners
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

        # auto-run on open
        QTimer.singleShot(50, self._run_scan)

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
            for launcher, grp in groups.items():
                hdr = QListWidgetItem()
                hlabel = QLabel(f"▾ {launcher}  ({len(grp)})")
                hlabel.setProperty("cls", "group")
                hlabel.setMinimumHeight(30)
                hdr.setSizeHint(QSize(100, 30))
                self.inst_list.addItem(hdr)
                self.inst_list.setItemWidget(hdr, hlabel)
                for inst in grp:
                    row = _InstanceRow(inst, self._import)
                    item = QListWidgetItem()
                    item.setSizeHint(row.sizeHint())
                    self.inst_list.addItem(item)
                    self.inst_list.setItemWidget(item, row)

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
            self,
            t("scan.import_title"),
            t("scan.import_body", launcher=inst.launcher, name=inst.name),
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
                mode=mode,
                launcher=inst.launcher,
            )
            return True
        except _CopyFailed as e:
            # Copy failed (locked file / permission) — silently fall back to a
            # link so the import still succeeds, and tell the user why.
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
                    self, t("scan.import_title"),
                    t("scan.copy_failed", err=str(e)),
                )
                return True
            except Exception as e2:  # noqa: BLE001
                btn.setText(f"Error: {e2}")
                return False
        except Exception as e:  # noqa: BLE001
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
            self,
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
            self, t("scan.select_folder"), "", dir_only=True,
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
                self, t("scan.import_title"),
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
