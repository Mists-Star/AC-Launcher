"""round-235：百宝箱实例下拉，三件套按所选实例工作（离线）。"""
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.main_window as MW  # noqa: E402
from src.i18n import t  # noqa: E402


@pytest.fixture
def tmp_dir():
    return tempfile.mkdtemp(prefix="ac235_")


@pytest.fixture
def fake_mgr(tmp_dir):
    a = SimpleNamespace(id="a", name="Alpha", mc_dir=tmp_dir, game_dir=tmp_dir)
    b = SimpleNamespace(id="b", name="Beta", mc_dir=tmp_dir, game_dir=tmp_dir)

    class FakeMgr:
        def list(self):
            return [a, b]

        def get(self, iid):
            return {"a": a, "b": b}.get(iid)

        def current(self):
            return None

    return FakeMgr(), a, b


class FakePage:
    def __init__(self):
        self.calls: list[object] = []

    def _open_map(self, inst):
        self.calls.append(inst)

    def _open_preview(self, inst):
        self.calls.append(inst)

    def _export_materials(self, inst):
        self.calls.append(inst)


def test_toolbox_instance_combo(qapp, fake_mgr):
    """百宝箱有实例下拉，包含所有实例"""
    mgr, a, b = fake_mgr
    win = MW.MainWindow()
    win.inst_mgr = mgr
    win.get_current_instance = lambda: None
    win._build_toolbox()
    combo = win._toolbox_inst_combo
    qapp.processEvents()

    assert isinstance(combo, QComboBox)
    assert [combo.itemText(i) for i in range(combo.count())] == ["Alpha", "Beta"]
    assert combo.currentData() == "a"
    assert t("toolbox.instance") not in ("toolbox.instance", "")


def test_toolbox_actions_use_selected_instance(qapp, fake_mgr):
    """三件套按下拉所选实例工作"""
    mgr, a, b = fake_mgr
    win = MW.MainWindow()
    win.inst_mgr = mgr
    win.get_current_instance = lambda: None
    win._build_toolbox()
    combo = win._toolbox_inst_combo

    page = FakePage()
    win._build_instances = lambda: page

    combo.setCurrentIndex(1)  # 选 Beta
    win._toolbox_action("map")
    assert page.calls == [b], str([getattr(x, "name", "?") for x in page.calls])

    page.calls.clear()
    win._toolbox_action("preview")
    assert page.calls == [b]

    page.calls.clear()
    combo.setCurrentIndex(0)  # 换回 Alpha
    win._toolbox_action("materials")
    assert page.calls == [a], str([getattr(x, "name", "?") for x in page.calls])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])