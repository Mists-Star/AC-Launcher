"""Components 组件库参考预览。

把 ui_kit 的共享组件渲染成一张参考图（``_shots/components.png``），
对应设计稿 Components.svg。给开发者快速核对所有组件在浅色/深色主题下的
外观，避免各页面各自手写样式。

用法：python components_preview.py
"""
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QFrame,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AC_DEV_TEMP", "1")

from src.theme import set_theme_mode, apply_qss, COLORS
from src import ui_kit

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
os.makedirs(OUT, exist_ok=True)


def _out(name: str, widget: QWidget):
    win = QMainWindow()
    win.setCentralWidget(widget)
    win.resize(1080, 1500)
    win.show()

    def grab():
        apply_qss()
        img = win.grab().toImage()
        img.save(os.path.join(OUT, name + ".png"))
        print("saved", name + ".png")
        win.close()

    _win_holder[0] = win
    QTimer.singleShot(400, grab)


_win_holder = [None]


def _section(title: str, body: QWidget, into: QVBoxLayout):
    lbl = QLabel(title)
    lbl.setStyleSheet(
        f"font-size: 15px; font-weight: 800; color: {COLORS['text_main']}; "
        f"margin-top: 8px;")
    into.addWidget(lbl)
    into.addWidget(ui_kit.card(radius=12))
    # re-add body into the card
    top = into.itemAt(into.count() - 1).widget()
    bl = QVBoxLayout(top)
    bl.setContentsMargins(18, 14, 18, 14)
    bl.setSpacing(10)
    bl.addWidget(body)


def build() -> QWidget:
    root = QWidget()
    v = QVBoxLayout(root)
    v.setContentsMargins(30, 24, 30, 24)
    v.setSpacing(14)

    # header
    v.addWidget(ui_kit.page_header(
        "Components 组件库", "共享设计语言：紫色 accent、白色圆角卡片、pill 标签。"))

    # chips
    c = ui_kit.ChipGroup(
        [("a", "正式版"), ("b", "快照"), ("c", "愚人节"), ("d", "遗留")],
        spacing=8, min_h=34)
    c.set("b")
    _section("ChipGroup · pill 筛选组", c, v)

    # buttons
    btns = QWidget()
    bh = QHBoxLayout(btns)
    bh.setSpacing(10)
    for text, kind in [("默认", None), ("主要", "accent"), ("次要", "secondary"),
                       ("危险", "danger"), ("分段", "seg")]:
        bh.addWidget(ui_kit.make_button(text, kind=kind, min_h=36))
    _section("Buttons · 按钮", btns, v)

    # badge / tag / tile
    mix = QWidget()
    mh = QHBoxLayout(mix)
    mh.setSpacing(14)
    mh.addWidget(ui_kit.tile("store", 44, 22))
    mh.addWidget(ui_kit.badge("徽章", COLORS["accent"]))
    mh.addWidget(ui_kit.badge("成功", COLORS.get("success", "#22C55E")))
    mh.addWidget(ui_kit.tag("当前", "#22C55E22", COLORS.get("success", "#22C55E")))
    mh.addWidget(ui_kit.tag("标签", f"{COLORS['accent']}26"))
    _section("Tile / Badge / Tag", mix, v)

    # section header
    sh = ui_kit.section_header("区块标题", "副标题说明",
                               action=("操作", lambda: None), icon_key="versions")
    _section("SectionHeader · 卡片区块标题", sh, v)

    # empty state
    es = ui_kit.empty_state(
        "toolbox", "空状态标题", "这里是空状态说明——用于列表无数据时的引导，居中排版。",
        actions=[ui_kit.make_button("去创建", kind="accent", min_h=36)])
    _section("EmptyState · 空状态", es, v)
    return root


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    set_theme_mode("light")
    for theme in ("light", "dark"):
        set_theme_mode(theme)
        _out("components_" + theme, build())
    QTimer.singleShot(2500, app.quit)
    app.exec()


if __name__ == "__main__":
    main()