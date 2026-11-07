"""round-208: resource-center filter sidebar (code-level port of upstream IA).

Upstream evidence — see ``docs/specs/round-208-store-alignment/spec.md`` §2.2:

* ``prism:launcher/ui/widgets/ModFilterWidget.ui:85-125`` (loader checkboxes),
  ``:198-224`` (MC version combo + "show all versions"), ``:255-267``
  (hide installed / open source), ``:269-296`` (release channel).
* ``prism:launcher/ui/pages/modplatform/ModPage.cpp:103-128`` — the filter
  widget is injected into the splitter and can be collapsed; ``filterChanged``
  wires straight to ``triggerSearch``.
* ``pclce:Plain Craft Launcher 2/Pages/PageDownload/Comp/PageComp.xaml:33-106``
  — five filter groups: source / tag / sort / version / loader.
* ``pclce:.../PageDownloadMod.xaml:10-53`` — dual-segment tags ``Tag="406/worldgen"``
  (left = CurseForge ``categoryId``, right = Modrinth category slug); ONE control
  feeds BOTH sources. Splitting happens in ``store_search._category_pair()``.

Scope discipline (§7): fields AC's data layer cannot honour (release channel,
client/server environment, open-source-only) are **not** rendered as dead
controls — they are registered as P2 gaps in the punchlist. Every control in
this panel has a real effect on the HTTP request or on the rendered list, so
we never repeat the "button does nothing" defect from earlier rounds.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox,
    QPushButton, QScrollArea, QFrame,
)
from PySide6.QtCore import Signal, Qt

from . import ui_kit
from .i18n import t
from .store_search import STORE_SORTS

# pclce:.../PageComp.xaml:69-80 — the exact version list the upstream UI offers.
UPSTREAM_VERSIONS = (
    "1.21.11", "1.21.1", "1.20.6", "1.20.1", "1.19.4", "1.19.2",
    "1.18.2", "1.16.5", "1.12.2", "1.10.2", "1.8.9", "1.7.10",
)

# pclce:.../PageComp.xaml:89-95 — Tag values ARE the CurseForge modLoaderType
# enum (Forge=1 / NeoForge=6 / Fabric=4 / Quilt=5); our data-layer
# ``_CF_LOADER_TYPE`` uses the very same numbers, so no translation is needed.
UPSTREAM_LOADERS = (
    ("", "store.filter_any_loader"),
    ("forge", "store.loader_forge"),
    ("neoforge", "store.loader_neoforge"),
    ("fabric", "store.loader_fabric"),
    ("quilt", "store.loader_quilt"),
)

# pclce:.../PageDownloadMod.xaml:10-53 — keep order and dual-segment values
# verbatim; ``None`` marks the first "All" row.
UPSTREAM_TAGS = (
    ("", "store.filter_any_tag"),
    ("406/worldgen", "store.tag_worldgen"),
    ("407/", "store.tag_biomes"),
    ("410/", "store.tag_dimensions"),
    ("408/", "store.tag_ores_resources"),
    ("409/", "store.tag_structures"),
    ("412/technology", "store.tag_technology"),
    ("415/", "store.tag_pipes_logistics"),
    ("4843/", "store.tag_automation"),
    ("417/", "store.tag_energy"),
    ("4558/", "store.tag_redstone"),
    ("436/food", "store.tag_food_cooking"),
    ("416/", "store.tag_farming"),
    ("/game-mechanics", "store.tag_game_mechanics"),
    ("414/transportation", "store.tag_transportation"),
    ("420/storage", "store.tag_storage"),
    ("419/magic", "store.tag_magic"),
    ("422/adventure", "store.tag_adventure"),
    ("424/decoration", "store.tag_decoration"),
    ("411/mobs", "store.tag_mobs"),
    ("5191/utility", "store.tag_utility"),
    ("434/equipment", "store.tag_equipment"),
    ("9026/", "store.tag_creative"),
    ("6814/optimization", "store.tag_optimization"),
    ("423/", "store.tag_display"),
    ("435/social", "store.tag_server"),
    ("421/library", "store.tag_library"),
)

_SORT_KEYS = {
    "relevance": "store.sort_relevance",
    "downloads": "store.sort_downloads",
    "follows": "store.sort_follows",
    "newest": "store.sort_newest",
    "updated": "store.sort_updated",
}

_SOURCES = (
    ("all", "store.source_all"),
    ("modrinth", "store.source_modrinth"),
    ("curseforge", "store.source_curseforge"),
)


class StoreFilterPanel(QWidget):
    """Collapsible filter sidebar. Emits ``filterChanged`` exactly once per
    user action and exposes a plain ``get_filter()`` dict for the page.

    ``set_target()`` only seeds the placeholder hint — the page decides whether
    to fall back to the target instance's MC version / loader (§2.3), so the
    sidebar never silently overrides an explicit player choice.
    """

    filterChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._guard = False
        self.setMinimumWidth(192)
        self.setMaximumWidth(280)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.title_lbl = ui_kit.group_label(t("store.filter_title"))
        outer.addWidget(self.title_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self._lay = QVBoxLayout(inner)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(12)
        scroll.setWidget(inner)
        outer.addWidget(scroll, stretch=1)

        self.source_combo = self._add_combo("store.filter_source")
        self.sort_combo = self._add_combo("store.filter_sort")
        self.version_combo = self._add_combo("store.filter_version", editable=True)
        self.loader_combo = self._add_combo("store.filter_loader")
        self.tag_combo = self._add_combo("store.filter_tag")

        self.hide_installed = QCheckBox(t("store.filter_hide_installed"))
        self.hide_installed.setCursor(Qt.PointingHandCursor)
        self.hide_installed.stateChanged.connect(self._changed)
        self._lay.addWidget(self.hide_installed)

        self.reset_btn = QPushButton(t("store.filter_reset"))
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.setMinimumHeight(32)
        self.reset_btn.clicked.connect(self.reset)
        self._lay.addWidget(self.reset_btn)
        self._lay.addStretch(1)

        self.retranslate_ui()

    def _add_combo(self, label_key: str, editable: bool = False) -> QComboBox:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        lbl = QLabel(t(label_key))
        lbl.setProperty("cls", "sub")
        setattr(self, "_lbl_%s" % label_key.rsplit(".", 1)[-1], lbl)
        v.addWidget(lbl)
        combo = QComboBox()
        combo.setMinimumHeight(32)
        combo.setEditable(editable)
        combo.currentIndexChanged.connect(self._changed)
        if editable:
            combo.editTextChanged.connect(self._changed)
        v.addWidget(combo)
        self._lay.addWidget(box)
        return combo

    def _changed(self, *_args):
        if not self._guard:
            self.filterChanged.emit()

    def _fill(self, combo: QComboBox, items):
        keep = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for value, key in items:
            combo.addItem(t(key), value)
        idx = combo.findData(keep)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def retranslate_ui(self):
        self._guard = True
        self.title_lbl.setText(t("store.filter_title"))
        for label_key, attr in (
            ("store.filter_source", "source"), ("store.filter_sort", "sort"),
            ("store.filter_version", "version"), ("store.filter_loader", "loader"),
            ("store.filter_tag", "tag"),
        ):
            lbl = getattr(self, "_lbl_%s" % label_key.rsplit(".", 1)[-1], None)
            if lbl is not None:
                lbl.setText(t(label_key))
        self._fill(self.source_combo, _SOURCES)
        self._fill(self.sort_combo,
                   [(s, _SORT_KEYS[s]) for s in STORE_SORTS])
        self._fill(self.loader_combo, UPSTREAM_LOADERS)
        self._fill(self.tag_combo, UPSTREAM_TAGS)
        # Version combo is editable: keep the current text and re-seed the list.
        text = self.version_combo.currentText()
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.addItem(t("store.filter_any_version"), "")
        for v in UPSTREAM_VERSIONS:
            self.version_combo.addItem(v, v)
        self.version_combo.setCurrentText(text)
        self.version_combo.blockSignals(False)
        self.hide_installed.setText(t("store.filter_hide_installed"))
        self.reset_btn.setText(t("store.filter_reset"))
        self._guard = False

    def reset(self):
        """Restore every filter to its default, then emit ONE change signal."""
        self._guard = True
        self.source_combo.setCurrentIndex(0)
        self.sort_combo.setCurrentIndex(0)
        self.version_combo.setCurrentIndex(0)
        self.loader_combo.setCurrentIndex(0)
        self.tag_combo.setCurrentIndex(0)
        self.hide_installed.setChecked(False)
        self._guard = False
        self.filterChanged.emit()

    def set_target(self, inst) -> None:
        """Seed the editable version box hint from the target instance.

        Only fills an empty box: an explicit player filter always wins.
        """
        if inst is None or self.version_combo.currentText():
            return
        v = str(getattr(inst, "game_version", "") or "")
        if not v:
            return
        self._guard = True
        if self.version_combo.findText(v) < 0:
            self.version_combo.addItem(v, v)
        self.version_combo.setCurrentText(v)
        self._guard = False

    def get_filter(self) -> dict:
        """Plain dict consumed by ``StorePage._filters()`` and by
        ``store_search.search_store_page(filters=...)``. ``category_tag`` is
        the upstream dual-segment tag; splitting is done in the data layer.
        """
        ver = self.version_combo.currentText().strip()
        if ver == t("store.filter_any_version"):
            ver = ""
        return {
            "source": self.source_combo.currentData() or "all",
            "sort": self.sort_combo.currentData() or "relevance",
            "game_version": ver,
            "loader": self.loader_combo.currentData() or "",
            "category_tag": self.tag_combo.currentData() or "",
            "hide_installed": self.hide_installed.isChecked(),
        }
