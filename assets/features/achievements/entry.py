"""Achievements page (direction B 彩蛋).

round-243 重做。改了三件事：

1. **进度显示**：原来是一条 14px 的裸进度条 + 一行小字，看不出"差在哪"。
   现在是一张进度卡：主数字（已解锁 n / 总 total）+ 百分比 + 细进度条 +
   **分区进度条带**（每个分区一枚 chip，显示该分区 n/total，未开始/进行中/
   已完成三态用同一色相的明度分层区分——不靠第二种颜色说话）。
2. **解锁时不再重建整页**：旧实现 `toast → _rebuild()` 把全部卡片拆了重建，
   解锁一枚成就整页闪一下、滚动位置也丢。现在只就地改那一张卡 + 头部。
   `_rebuild()` 只留给换语言（文案全变，重建才合理）。
3. **卡片状态就地切换**：`_AchCard.set_unlocked()` 改字重/颜色/页脚徽章，
   不重建控件。

页脚徽章与文案沿用原有 i18n 键，不新增词条。
"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QGridLayout, QSizePolicy,
)

from .theme import COLORS, RoundedCard, with_alpha
from .i18n import t
from . import ui_kit
from .ui_flow import FlowGrid
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


class _ThinBar(QWidget):
    """自绘细进度条（圆头、单色相两段明度）。

    不用 QProgressBar：全局 QSS 里有 QProgressBar 规则，靠 objectName 拦
    容易漏（旧实现就得写 ``#achProgress::chunk`` 才能压住），而且 chunk 的
    两端阴影在小尺寸下很脏。自绘 20 行，尺寸/圆角/颜色全部可控。
    """

    def __init__(self, height: int = 8, ratio: float = 0.0, parent=None):
        super().__init__(parent)
        self._ratio = max(0.0, min(1.0, ratio))
        self._h = height
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_ratio(self, ratio: float) -> None:
        r = max(0.0, min(1.0, float(ratio)))
        if abs(r - self._ratio) > 1e-4:
            self._ratio = r
            self.update()

    def paintEvent(self, _e):  # noqa: N802 - Qt 约定
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self._h
        rad = h / 2.0
        track = QRectF(0, 0, self.width(), h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["bg_panel"]))
        p.drawRoundedRect(track, rad, rad)
        # 边框用画笔补（fillPath 画不出描边）
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor(COLORS["border"]))
        p.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        if self._ratio <= 0:
            return
        w = max(h, self.width() * self._ratio)   # 至少一个圆头的宽度，别画成小方块
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["accent"]))
        p.drawRoundedRect(QRectF(0, 0, min(w, self.width()), h), rad, rad)


class _CatChip(QLabel):
    """分区进度 chip：未开始 / 进行中 / 已完成 三态。"""

    def set_stat(self, done: int, total: int) -> None:
        text = f"{self._name} {done}/{total}"
        if self.text() != text:
            self.setText(text)
        if total and done >= total:
            fg = COLORS["success"]
            bg = with_alpha(COLORS["success"], 0x1F)
        elif done:
            fg = COLORS["accent"]
            bg = with_alpha(COLORS["accent"], 0x1F)
        else:
            fg = COLORS["text_sub"]
            bg = with_alpha(COLORS["text_sub"], 0x12)
        self.setStyleSheet(
            f"color: {fg}; background: {bg}; border-radius: 9px;"
            f" padding: 3px 10px; font-size: 11px; font-weight: 600;")

    def __init__(self, name: str, parent=None):
        super().__init__("", parent)
        self._name = name
        self.setAlignment(Qt.AlignCenter)


class _ProgressCard(RoundedCard):
    """顶部进度卡：主数字 + 百分比 + 主进度条 + 分区 chip 条带。"""

    def __init__(self, parent=None):
        super().__init__(radius=14, parent=parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.num_lbl = QLabel("0")
        self.num_lbl.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 26px; font-weight: 700;")
        self.total_lbl = QLabel("/ 0")
        self.total_lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: 13px; padding-bottom: 5px;")
        top.addWidget(self.num_lbl)
        top.addWidget(self.total_lbl)
        top.addStretch(1)
        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setStyleSheet(
            f"color: {COLORS['text_sub']}; font-size: 15px; font-weight: 600;")
        top.addWidget(self.pct_lbl)
        lay.addLayout(top)

        self.bar = _ThinBar(8)
        lay.addWidget(self.bar)

        self.chips = FlowGrid(min_item_width=82, max_cols=99,
                              h_spacing=8, v_spacing=8)
        lay.addLayout(self.chips)     # FlowGrid 是 QLayout，不是 QWidget
        self._chip_map: dict[str, _CatChip] = {}
        for cat in CATEGORY_KEYS:
            ids = [a for a in ACHIEVEMENTS if ACHIEVEMENTS[a][2] == cat]
            if not ids:
                continue
            chip = _CatChip(t(_CAT_LABEL[cat]))
            self._chip_map[cat] = chip
            self.chips.addWidget(chip)

    def set_values(self, n: int, total: int) -> None:
        total = max(0, int(total))
        n = max(0, min(int(n), total))
        self.num_lbl.setText(str(n))
        self.total_lbl.setText("/ %d" % total)
        pct = int(round(n * 100.0 / total)) if total else 0
        self.pct_lbl.setText("%d%%" % pct)
        self.bar.set_ratio((n / total) if total else 0.0)
        for cat, chip in self._chip_map.items():
            ids = [a for a in ACHIEVEMENTS if ACHIEVEMENTS[a][2] == cat]
            done = sum(1 for a in ids if achievements.is_unlocked(a))
            chip.set_stat(done, len(ids))


class _AchCard(RoundedCard):
    def __init__(self, aid: str, unlocked: bool, parent=None):
        super().__init__(radius=12, parent=parent)
        self._aid = aid
        self.setMinimumHeight(96)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        self.title = QLabel(t(ACHIEVEMENTS[aid][0]))
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.desc = QLabel(t(ACHIEVEMENTS[aid][1]))
        self.desc.setProperty("cls", "sub")
        self.desc.setStyleSheet("font-size: 11px; opacity: 0.75;")
        self.desc.setWordWrap(True)
        lay.addWidget(self.desc)
        lay.addStretch(1)

        # 页脚：徽章（已解锁）与提示（未解锁）都建好，切状态只切可见性，
        # 避免每次解锁都新建/销毁控件。
        self.badge = QWidget()
        self.badge.setAttribute(Qt.WA_StyledBackground, True)
        self.badge.setStyleSheet(
            f"background: {with_alpha(COLORS['success'], 0x22)};"
            f" border-radius: 8px;")
        bh = QHBoxLayout(self.badge)
        bh.setContentsMargins(10, 2, 12, 2)
        bh.setSpacing(5)
        bi = QLabel()
        bi.setPixmap(ui_kit.state_pix("done", COLORS["success"], 13))
        bi.setFixedSize(14, 14)
        bt = QLabel(t("ach.unlocked"))
        bt.setStyleSheet(
            f"color: {COLORS['success']}; font-size: 11px; font-weight: 600;")
        bh.addWidget(bi)
        bh.addWidget(bt)
        lay.addWidget(self.badge, alignment=Qt.AlignLeft)

        self.hint = QLabel(t("ach.locked"))
        self.hint.setStyleSheet(
            f"color: {COLORS['text_disabled']}; font-size: 11px; font-style: italic;")
        self.hint.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lay.addWidget(self.hint)

        self.set_unlocked(unlocked)

    def set_unlocked(self, unlocked: bool) -> None:
        """就地切状态（不重建控件）。"""
        self.title.setProperty("cls", "big" if unlocked else "sub")
        self.title.setStyleSheet(
            f"font-size: 13px; font-weight: {'600' if unlocked else '400'};"
            f" color: {COLORS['accent'] if unlocked else COLORS['text_main']};")
        self.badge.setVisible(unlocked)
        self.hint.setVisible(not unlocked)


class AchievementsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._built = False
        self._cards: dict[str, _AchCard] = {}
        self._root = None
        # 解锁时只刷那一张卡 + 头部，不重建整页（round-243）
        achievements.toast.connect(self._on_unlocked)
        self._construct()
        self._refresh_header()

    # ---- 构建 -------------------------------------------------------------
    def _construct(self):
        """把整页内容铺进 self（可重复调用：换语言时清空重铺）。"""
        root = self._root
        if root is None:
            root = QVBoxLayout(self)
            self._root = root
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        root.addWidget(ui_kit.page_header(t("ach.title"), icon_key="achievements"))

        self.progress_card = _ProgressCard()
        root.addWidget(self.progress_card)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self._content = QVBoxLayout(content)
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(14)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        self._built = False
        self._build()

    def _build(self):
        if self._built:
            return
        self._built = True
        self._cards.clear()
        for cat in CATEGORY_KEYS:
            ids = [a for a in ACHIEVEMENTS if ACHIEVEMENTS[a][2] == cat]
            if not ids:
                continue
            cat_lbl = ui_kit.group_label(t(_CAT_LABEL[cat]))
            self._content.addWidget(cat_lbl)
            grid = QGridLayout()
            grid.setSpacing(10)
            # round-120：单数分区最后一张卡跨两列，避免半宽空档破坏网格节奏。
            for i, aid in enumerate(ids):
                span = 2 if (len(ids) % 2 == 1 and i == len(ids) - 1) else 1
                card = _AchCard(aid, achievements.is_unlocked(aid))
                self._cards[aid] = card
                grid.addWidget(card, i // 2, i % 2, 1, span)
            self._content.addLayout(grid)
        self._content.addStretch(1)

    # ---- 刷新 -------------------------------------------------------------
    def _refresh_header(self):
        n, total = achievements.progress()
        self.progress_card.set_values(n, total)

    def _on_unlocked(self, aid: str = "") -> None:
        """解锁回调：只动受影响的卡 + 头部（不重建整页）。"""
        card = self._cards.get(aid)
        if card is None:
            # 未知 id（包与核心版本不一致等）：保守起见整页重建一次
            self._refresh()
            return
        card.set_unlocked(True)
        self._refresh_header()

    def _refresh(self):
        self._refresh_header()
        for aid, card in self._cards.items():
            card.set_unlocked(achievements.is_unlocked(aid))

    def _rebuild(self):
        """清掉旧卡片并重建（只用于换语言这类"文案全变"的场合）。

        round-112 修：旧控件必须先 :meth:`setParent(None)` **立即从视口摘除**，
        再 ``deleteLater()`` 回收内存。只 ``deleteLater()`` 是不够的 ——
        DeferredDelete 事件在**同一层**事件循环/``processEvents()`` 里不投递，
        旧控件会继续活着叠画在新内容上（本页历史遗留的「第一张卡片被裁切、
        与分组标题重叠」即此根因 + sizeHint 坑两者叠加）。
        """
        while self._content.count():
            item = self._content.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
        self._built = False
        self._build()
        self._refresh_header()

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                AchievementsPage._clear_layout(item.layout())

    def retranslate_ui(self):
        """换语言：文案全变（含页头 / 分区 chip），整页重铺一遍。

        旧实现只 ``_refresh()``，页头标题与分区 chip 的 `n/total` 文案都停在
        旧语言上——因为它们在构建时就把 t() 的结果烤死了。
        """
        while self._root is not None and self._root.count():
            item = self._root.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
        self._cards.clear()
        self._construct()
        self._refresh()


def create_page(ctx=None):
    """round-167 功能扩展入口：由 src/features.py 动态调用。"""
    return AchievementsPage()
