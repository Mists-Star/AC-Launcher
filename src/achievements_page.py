"""Achievements page (direction B 彩蛋).

Renders all achievements grouped by category, with an overall progress
header. Unlocked items get a filled badge; locked ones stay dimmed with a
hint. Listens to the singleton's toast signal for live updates.
"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QProgressBar, QGridLayout,
)

from .theme import COLORS, RoundedCard
from .i18n import t
from . import ui_kit
from .achievements import ACHIEVEMENTS, CATEGORY_KEYS, achievements

_CAT_LABEL = {
    "start": "ach.cat_start",
    "account": "ach.cat_account",
    "instance": "ach.cat_instance",
    "content": "ach.cat_content",
    "multiplayer": "ach.cat_multiplayer",
    "repair": "ach.cat_repair",
    "custom": "ach.cat_custom",
}


class _AchCard(RoundedCard):
    def __init__(self, aid: str, unlocked: bool, parent=None):
        super().__init__(radius=12, parent=parent)
        self.setMinimumHeight(96)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        title = QLabel(t(ACHIEVEMENTS[aid][0]))
        title.setProperty("cls", "big" if unlocked else "sub")
        title.setStyleSheet(
            f"font-size: 13px; font-weight: {'600' if unlocked else '400'};"
            f" color: {COLORS['accent'] if unlocked else COLORS['text_main']};"
        )
        title.setWordWrap(True)
        lay.addWidget(title)
        desc = QLabel(t(ACHIEVEMENTS[aid][1]))
        desc.setProperty("cls", "sub")
        desc.setStyleSheet("font-size: 11px; opacity: 0.75;")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        lay.addStretch(1)
        if unlocked:
            from .ui_kit import state_pix
            badge = QWidget()
            badge.setAttribute(Qt.WA_StyledBackground, True)
            badge.setStyleSheet(
                f"background: {COLORS['success']}22;"
                f" border-radius: 8px;"
            )
            bh = QHBoxLayout(badge)
            bh.setContentsMargins(10, 2, 12, 2)
            bh.setSpacing(5)
            bi = QLabel()
            bi.setPixmap(state_pix("done", COLORS["success"], 13))
            bi.setFixedSize(14, 14)
            bt = QLabel(t("ach.unlocked"))
            bt.setStyleSheet(
                f"color: {COLORS['success']}; font-size: 11px; font-weight: 600;")
            bh.addWidget(bi)
            bh.addWidget(bt)
            lay.addWidget(badge, alignment=Qt.AlignLeft)
        else:
            hint = QLabel(t("ach.locked"))
            hint.setStyleSheet(
                f"color: {COLORS['text_disabled']}; font-size: 11px; font-style: italic;"
            )
            hint.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lay.addWidget(hint)


class AchievementsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._built = False
        achievements.toast.connect(lambda _aid: self._refresh())

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        root.addWidget(ui_kit.page_header(t("ach.title"), icon_key="achievements"))

        # progress bar
        self.progress = QProgressBar()
        self.progress.setFixedHeight(14)
        self.progress.setTextVisible(False)
        self.progress.setFormat("")
        # Confined to the progress widget only via objectName selector so the
        # default QSS styles (which target QProgressBar globally) don't leak in.
        self.progress.setObjectName("achProgress")
        self.progress.setStyleSheet(
            f"#achProgress {{ background: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']};"
            f" border-radius: 7px; }}"
            f"#achProgress::chunk {{ background: {COLORS['accent']}; border-radius: 7px;"
            f" margin: 1px; }}"
        )
        root.addWidget(self.progress)
        self.progress_lbl = QLabel("")
        self.progress_lbl.setProperty("cls", "sub")
        root.addWidget(self.progress_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self._content = QVBoxLayout(content)
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(14)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        self._build()
        self._refresh()

    def _build(self):
        if self._built:
            return
        self._built = True
        for cat in CATEGORY_KEYS:
            ids = [a for a in ACHIEVEMENTS if ACHIEVEMENTS[a][2] == cat]
            if not ids:
                continue
            cat_lbl = QLabel(t(_CAT_LABEL[cat]))
            cat_lbl.setProperty("cls", "group")
            self._content.addWidget(cat_lbl)
            grid = QGridLayout()
            grid.setSpacing(10)
            for i, aid in enumerate(ids):
                grid.addWidget(_AchCard(aid, achievements.is_unlocked(aid)), i // 2, i % 2)
            self._content.addLayout(grid)
        self._content.addStretch(1)

    def _refresh(self):
        n, total = achievements.progress()
        self.progress.setRange(0, total)
        self.progress.setValue(n)
        self.progress_lbl.setText(t("ach.progress", n=n, total=total))
        # rebuild cards (cheap at this scale)
        while self._content.count():
            item = self._content.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
        self._built = False
        self._build()

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                AchievementsPage._clear_layout(item.layout())

    def retranslate_ui(self):
        self._refresh()
