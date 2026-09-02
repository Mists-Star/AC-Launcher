"""Shared UI kit for AC Launcher — consistent, token-driven building blocks.

Every helper reads from ``theme.COLORS`` so the light/dark themes and player
theme packs stay in sync automatically. Pages should prefer these over ad-hoc
inline stylesheets to keep the visual language uniform across the app.

Purely additive — safe to import anywhere; never mutates global state.
"""
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy,
    QButtonGroup,
)
from PySide6.QtCore import Qt, QSize, Signal

from .theme import COLORS, RoundedCard, R_CARD, R_BTN, F_SM, F_MD, F_LG
from .icons import icon


# ── badge / pill ───────────────────────────────────────────────────────────
def badge(text: str, color: str, font_size: int = 11) -> QLabel:
    """Small rounded pill. ``color`` drives the text and a translucent bg."""
    lb = QLabel(text)
    lb.setStyleSheet(
        f"color: {color}; background: {color}1F; border-radius: 9px; "
        f"padding: 2px 10px; font-size: {font_size}px; font-weight: 600;"
    )
    return lb


def tag(text: str, bg: str, fg: str = None, font_size: int = 11,
        radius: int = 10, pad: str = "4px 12px") -> QLabel:
    """Generic solid-ish tag (e.g. the green "✓ 当前" mark)."""
    fg = fg or COLORS["text_main"]
    lb = QLabel(text)
    lb.setStyleSheet(
        f"color: {fg}; background: {bg}; font-weight: 600; "
        f"border-radius: {radius}px; padding: {pad}; font-size: {font_size}px;"
    )
    return lb


# ── icon tile ─────────────────────────────────────────────────────────────
def tile(icon_key: str, size: int = 44, icon_size: int = 24,
         bg: str = None) -> QLabel:
    """Rounded square icon tile used on cards (instance/mod/version icons)."""
    box = QLabel()
    box.setFixedSize(size, size)
    box.setAlignment(Qt.AlignCenter)
    box.setProperty("cls", "tile")
    box.setPixmap(icon(icon_key).pixmap(icon_size, icon_size))
    if bg:
        box.setStyleSheet(f"background: {bg}; border-radius: 10px;")
    return box


# ── buttons ─────────────────────────────────────────────────────────────────
def make_button(text: str, kind: str = None, icon_key: str = None,
                on_click=None, min_h: int = 34, min_w: int = 0,
                checkable: bool = False, tooltip: str = "") -> QPushButton:
    """Factory for a styled button. ``kind`` ∈ {None,'accent','danger',
    'secondary','seg'} maps to the QSS ``cls`` classes in theme.py."""
    b = QPushButton(text)
    if kind:
        b.setProperty("cls", kind)
    if icon_key:
        b.setIcon(icon(icon_key))
        b.setIconSize(QSize(16, 16))
    if checkable:
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
    if tooltip:
        b.setToolTip(tooltip)
    if min_h:
        b.setMinimumHeight(min_h)
    if min_w:
        b.setMinimumWidth(min_w)
    if on_click:
        b.clicked.connect(on_click)
    return b


# ── section header (card-internal title row) ───────────────────────────────
def section_header(title: str, subtitle: str = "", action=None,
                   icon_key: str = None, spacing: int = 10) -> QWidget:
    """A header row for inside a card: [icon] Title  subtitle … action.

    ``action`` may be a QWidget (added as-is) or a (label, callback) tuple
    (turned into a secondary button).
    """
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(spacing)
    if icon_key:
        ic = QLabel()
        ic.setPixmap(icon(icon_key).pixmap(18, 18))
        ic.setStyleSheet(f"color: {COLORS['text_sub']};")
        h.addWidget(ic)
    t = QLabel(title)
    t.setStyleSheet(
        f"font-size: {F_LG}px; font-weight: 700; color: {COLORS['text_main']};")
    h.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setStyleSheet(f"font-size: {F_SM}px; color: {COLORS['text_sub']};")
        h.addWidget(s)
    h.addStretch(1)
    if action is not None:
        if isinstance(action, QWidget):
            h.addWidget(action)
        elif isinstance(action, tuple):
            lbl, cb = action
            h.addWidget(make_button(lbl, kind="secondary", on_click=cb,
                                    min_h=32))
    return w


# ── page header (top of a content page) ─────────────────────────────────────
def page_header(title: str, desc: str = "", action=None,
                icon_key: str = None) -> QWidget:
    """Big page title with optional description and right-aligned action.

    ``action`` may be a QWidget, a (label, callback) tuple, or a list mixing
    both (added right-aligned in order). The description label is exposed as
    ``w.desc_lbl`` so callers can refresh it at runtime.
    """
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(12)
    if icon_key:
        ic = QLabel()
        ic.setPixmap(icon(icon_key).pixmap(26, 26))
        ic.setStyleSheet(f"color: {COLORS['accent']};")
        h.addWidget(ic)
    col = QVBoxLayout()
    col.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet(
        f"font-size: 22px; font-weight: 800; color: {COLORS['text_main']};")
    col.addWidget(t)
    if desc:
        d = QLabel(desc)
        d.setStyleSheet(f"font-size: {F_SM}px; color: {COLORS['text_sub']};")
        d.setWordWrap(True)
        col.addWidget(d)
        w.desc_lbl = d
    h.addLayout(col, stretch=1)
    if action is not None:
        if isinstance(action, QWidget):
            h.addWidget(action, alignment=Qt.AlignVCenter)
        elif isinstance(action, tuple):
            lbl, cb = action
            h.addWidget(make_button(lbl, kind="accent", on_click=cb, min_h=36),
                        alignment=Qt.AlignVCenter)
        else:  # list of widgets/actions
            al = QHBoxLayout()
            al.setSpacing(8)
            for a in action:
                if isinstance(a, QWidget):
                    al.addWidget(a)
                elif isinstance(a, tuple):
                    lbl, cb = a
                    al.addWidget(make_button(lbl, kind="accent", on_click=cb,
                                             min_h=36))
            h.addLayout(al)
    w.title_lbl = t
    if not hasattr(w, "desc_lbl"):
        w.desc_lbl = None
    return w


# ── empty state ──────────────────────────────────────────────────────────────
def empty_state(icon_key: str, title: str, hint: str = "",
                actions: list = None, icon_size: int = 56) -> QWidget:
    """Compact centered empty state with optional action buttons."""
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    v = QVBoxLayout(w)
    v.setAlignment(Qt.AlignCenter)
    v.setSpacing(12)
    ic = QLabel()
    ic.setPixmap(icon(icon_key).pixmap(icon_size, icon_size))
    ic.setStyleSheet(f"color: {COLORS['text_sub']}; opacity: 0.7;")
    v.addWidget(ic, alignment=Qt.AlignCenter)
    tt = QLabel(title)
    tt.setStyleSheet(
        f"font-size: {F_LG}px; font-weight: 700; color: {COLORS['text_main']};")
    tt.setAlignment(Qt.AlignCenter)
    v.addWidget(tt, alignment=Qt.AlignCenter)
    if hint:
        hh = QLabel(hint)
        hh.setStyleSheet(f"font-size: {F_SM}px; color: {COLORS['text_sub']};")
        hh.setWordWrap(True)
        hh.setMaximumWidth(460)
        hh.setAlignment(Qt.AlignCenter)
        v.addWidget(hh, alignment=Qt.AlignCenter)
    if actions:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.setAlignment(Qt.AlignCenter)
        for a in actions:
            row.addWidget(a)
        v.addLayout(row)
    return w


# ── card convenience ─────────────────────────────────────────────────────────
def card(radius: int = R_CARD, fill=None, border=None, parent=None,
         min_h: int = 0, max_h: int = 0) -> RoundedCard:
    c = RoundedCard(radius=radius, parent=parent)
    if fill:
        c.set_fill(fill)
    if border:
        c.set_border(border, 1)
    if min_h:
        c.setMinimumHeight(min_h)
    if max_h:
        c.setMaximumHeight(max_h)
    return c


# ── pill filter group (Versions / Store category tabs) ──────────────────────
class ChipGroup(QWidget):
    """Mutually-exclusive pill filter row — the reusable replacement for the
    clipboard'd chip loops in Versions & Store.

    Active state is 100 % QSS-driven: buttons carry the ``chip`` cls whose
    ``:checked`` pseudo-state paints the accent pill (see theme.py), so the
    caller never hand-paints styles. Just add it to a layout.
    """

    #: emitted with the newly-active ``key`` on a *user* click.
    changed = Signal(str)

    def __init__(self, options, on_change=None, spacing: int = 6,
                 min_h: int = 32, parent=None):
        """``options``: iterable of ``(key, label)`` pairs."""
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict = {}            # key → QPushButton (for extra meta)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(spacing)
        for key, label in options:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setMinimumHeight(min_h)
            b.setProperty("cls", "chip")
            b.clicked.connect(lambda _c=False, k=key: self._emit(k))
            self._group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        if on_change:
            self.changed.connect(on_change)

    def _emit(self, key):
        self.changed.emit(key)

    def current(self) -> str:
        """The active key (``""`` if none)."""
        for key, b in self.buttons.items():
            if b.isChecked():
                return key
        return ""

    def set(self, key: str):
        """Programmatically select a key (no ``changed`` emission)."""
        b = self.buttons.get(key)
        if b is not None:
            b.setChecked(True)

    def set_text(self, key: str, text: str):
        """Update a button's label (for retranslate)."""
        b = self.buttons.get(key)
        if b is not None:
            b.setText(text)
