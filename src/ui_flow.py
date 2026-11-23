"""FlowLayout / FlowGrid —— 按可用宽度自动换行的布局（round-243）。

为什么需要它们
--------------
QHBoxLayout / QGridLayout 的**最小宽度是各子项最小宽度之和**：一行 4 颗按钮、
5 个徽章，加起来 500~600px 就是硬下限。把这个布局塞进 QScrollArea（横向滚动
条关闭）时，内容会被直接裁掉右半边，而且没有任何视觉提示——用户只会觉得
"版本信息/按钮不见了"。

改成按**当前宽度**摆放后，卡片的最小宽度退化成「最宽的那一颗」：宽度够就一排
4 颗，不够自动 2 颗 1 排。这才是响应式的正解，不需要为每个宽度写死列数。

两个类怎么选
-----------
    FlowLayout  子项宽度差异大（徽章）→ 逐颗自然摆放，最省横向空间
    FlowGrid    子项宽度相近（按钮组）→ 先算列数再等宽铺满，永远是整齐网格

用法
----
    flow = FlowLayout(h_spacing=8, v_spacing=8)
    flow.addWidget(badge)
    lay.addLayout(flow)                       # 直接挂到 QVBoxLayout 里

    grid = FlowGrid(h_spacing=8, v_spacing=8, min_item_width=104, max_cols=4)
    grid.addWidget(btn)
    lay.addLayout(grid)

注意：两者都**不分配多余空间**（expandingDirections 为空），子项左对齐；
行高取该行最高子项，行与行之间留 v_spacing。
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    """按可用宽度换行的布局（Qt 官方 FlowLayout 示例的加固版）。"""

    def __init__(self, parent=None, margin: int = 0,
                 h_spacing: int = 8, v_spacing: int = 8):
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = int(h_spacing)
        self._v_spacing = int(v_spacing)
        self.setContentsMargins(QMargins(margin, margin, margin, margin))

    # ------------------------------------------------------------------ items
    def addItem(self, item):  # noqa: N802 - Qt 命名
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt 命名
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802 - Qt 命名
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802 - Qt 命名
        return Qt.Orientations(Qt.Orientation(0))

    # ------------------------------------------------------------------ spacing
    def horizontalSpacing(self) -> int:  # noqa: N802 - Qt 命名
        return self._h_spacing

    def verticalSpacing(self) -> int:  # noqa: N802 - Qt 命名
        return self._v_spacing

    def setHorizontalSpacing(self, px: int) -> None:  # noqa: N802 - Qt 命名
        self._h_spacing = max(0, int(px))
        self.invalidate()

    def setVerticalSpacing(self, px: int) -> None:  # noqa: N802 - Qt 命名
        self._v_spacing = max(0, int(px))
        self.invalidate()

    # ------------------------------------------------------------------ size
    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt 命名
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt 命名
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        # 只有一颗子项时宽度取最宽的那颗 —— 由它决定卡片的宽度下限。
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt 命名
        size = QSize()
        for item in self._items:
            if self._skip(item):
                continue
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    # ------------------------------------------------------------------ layout
    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt 命名
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    @staticmethod
    def _skip(item) -> bool:
        """隐藏子项当作空气；QSpacerItem 保留（可能是在占位）。"""
        w = item.widget()
        return w is not None and w.isHidden()

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = eff.x()
        y = eff.y()
        line_h = 0
        for item in self._items:
            if self._skip(item):
                continue
            hint = item.sizeHint()
            w = max(hint.width(), item.minimumSize().width())
            h = max(hint.height(), item.minimumSize().height())
            # 放不下就换行（第一颗永远不换，避免宽度极小时死循环）
            if x > eff.x() and x + w > eff.right() + 1:
                x = eff.x()
                y = y + line_h + self._v_spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x = x + w + self._h_spacing
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()


class FlowGrid(QLayout):
    """自适应列数的等宽网格：列数由可用宽度算，每行等宽铺满。

    和 FlowLayout 的分工
    -------------------
    - FlowLayout：子项宽度差异大（徽章：版本号 60px、布局说明 190px）→ 逐颗
      自然摆放最省空间。
    - FlowGrid：子项宽度相近（按钮组）→ 若用 FlowLayout，宽度 649 时会排成
      「5 + 3」这种参差形状；FlowGrid 会先算列数（`(W + gap) // (min_w + gap)`，
      再夹到 `max_cols`），把每颗拉成等宽 → 永远是整齐的 N×M 网格。

    列数会随宽度变化：窄窗口 2 列、宽窗口 4 列，卡片最小宽度只受 `min_item_width`
    约束，不会再把 QScrollArea 撑出可视区。
    """

    def __init__(self, parent=None, margin: int = 0, h_spacing: int = 8,
                 v_spacing: int = 8, min_item_width: int = 104,
                 max_cols: int = 4):
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = int(h_spacing)
        self._v_spacing = int(v_spacing)
        self._min_w = max(1, int(min_item_width))
        self._max_cols = max(1, int(max_cols))
        self.setContentsMargins(QMargins(margin, margin, margin, margin))

    # ------------------------------------------------------------------ items
    def addItem(self, item):  # noqa: N802 - Qt 命名
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt 命名
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802 - Qt 命名
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802 - Qt 命名
        return Qt.Orientations(Qt.Orientation(0))

    # ------------------------------------------------------------------ size
    def _visible(self) -> list:
        out = []
        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            out.append(item)
        return out

    def _cell_height(self) -> int:
        h = 0
        for item in self._visible():
            h = max(h, item.sizeHint().height(), item.minimumSize().height())
        return h

    def _cols(self, width: int) -> int:
        inner = max(1, width - self.contentsMargins().left()
                    - self.contentsMargins().right())
        n = (inner + self._h_spacing) // (self._min_w + self._h_spacing)
        return max(1, min(self._max_cols, int(n)))

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt 命名
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt 命名
        items = self._visible()
        if not items:
            return 0
        cols = self._cols(width)
        rows = (len(items) + cols - 1) // cols
        m = self.contentsMargins()
        return (rows * self._cell_height()
                + (rows - 1) * self._v_spacing
                + m.top() + m.bottom())

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        m = self.contentsMargins()
        items = self._visible()
        if not items:
            return QSize(m.left() + m.right(), m.top() + m.bottom())
        cols = min(self._max_cols, max(1, len(items)))
        return QSize(cols * self._min_w + (cols - 1) * self._h_spacing
                     + m.left() + m.right(),
                     self._cell_height() + m.top() + m.bottom())

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt 命名
        m = self.contentsMargins()
        return QSize(self._min_w + m.left() + m.right(),
                     self._cell_height() + m.top() + m.bottom())

    # ------------------------------------------------------------------ layout
    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt 命名
        super().setGeometry(rect)
        items = self._visible()
        if not items:
            return
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        cols = self._cols(rect.width())
        cell_h = self._cell_height()
        total_gap = (cols - 1) * self._h_spacing
        cell_w = max(self._min_w, (eff.width() - total_gap) // cols)
        for i, item in enumerate(items):
            r, c = divmod(i, cols)
            x = eff.x() + c * (cell_w + self._h_spacing)
            y = eff.y() + r * (cell_h + self._v_spacing)
            item.setGeometry(QRect(QPoint(x, y), QSize(cell_w, cell_h)))
