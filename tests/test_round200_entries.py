"""round-200：实例页入口重构（用户反馈「部分功能藏太深了，换入口」）。

用户点名要提上来的功能：
  体检 / 崩溃分析 / 启动诊断 / 编辑实例 / 备份·还原·复制 / 内容分区。

判据：
  1. 详情卡新增「管理与诊断」一级网格（2×4），8 个入口全部可见；
  2. 「⋯ 更多」只剩 4 项低频（打开存档 / 应用整合包 / 重构实例 / 导出整合包）；
  3. 名称行主按钮 = 编辑实例（不再是混装的「体检 / 启动诊断」）；
  4. 启动诊断从 QDialog 改为**页内**面板（与体检 / 崩溃分析同一套栈），
     弹窗壳只包一层 panel，不复制逻辑；
  5. i18n 新增 3 键、删除 instances.launch，中英对称。
"""
import io
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

DEV = tempfile.mkdtemp(prefix="ac_r200_")
os.chdir(DEV)

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    return io.open(os.path.join(HERE, "src", rel), encoding="utf-8").read()


pages_src = read("pages_instances.py")
diag_src = read("launch_diagnostics_dialog.py")
i18n_src = read("i18n.py")

print("① 详情页「管理与诊断」一级入口")
check("有分组标题", 't("instances.manage_group")' in pages_src)
mgmt_block = pages_src.split("mgmt = [", 1)[1].split(
    "mgmt_grid = QGridLayout()", 1)[0]
GRID_KEYS = [
    "health.title", "instances.crash_analyze", "instances.launch_diag",
    "instances.repair_deps_short", "instances.backup", "instances.restore",
    "instances.duplicate", "instances.open_folder",
]
missing = [k for k in GRID_KEYS if k not in mgmt_block]
check("8 个一级入口全在网格里", not missing, "缺：" + ",".join(missing))
check("网格 4 列", "i // 4, i % 4" in pages_src)
check("每格至少 40 高", "b.setMinimumHeight(40)" in pages_src)

print("② 更多菜单只剩低频")
more_block = pages_src.split(
    "_more_menu = QMenu(more_btn)", 1)[1].split(
    "more_btn.setMenu(_more_menu)", 1)[0]
check("体检已移出更多菜单", "health.title" not in more_block)
check("崩溃分析已移出更多菜单", "crash_analyze" not in more_block)
check("低频 4 项保留",
      all(k in more_block for k in (
          "instances.open_saves", "instances.apply_pack",
          "instances.rebuild", "instances.export_pack")))

print("③ 名称行主按钮 = 编辑实例")
check("accent 按钮走编辑接口",
      'QPushButton(t("instances.edit_instance"))' in pages_src
      and "on_accent(\"settings\")" in pages_src)
check("不再有旧混装键", "instances.launch\"" not in pages_src)
check("不再有旧 _launch 方法", "def _launch(" not in pages_src)
check("不再从实例页开诊断弹窗", "open_launch_diagnostics" not in pages_src)

print("④ 启动诊断页内化")
check("有页内面板类", "class LaunchDiagnosticsPanel(QWidget)" in diag_src)
check("面板有 closed 信号", "closed = Signal()" in diag_src)
check("面板有 open_health 信号", "open_health = Signal()" in diag_src)
check("实例页推入页内栈",
      "def _show_launch_diag(" in pages_src
      and "self._push_feature(panel)" in pages_src
      and "LaunchDiagnosticsPanel" in pages_src)
check("弹窗壳只包一层 panel",
      "self.panel = LaunchDiagnosticsPanel(inst, mgr=mgr, parent=self)" in diag_src
      and "self.panel.closed.connect(self.accept)" in diag_src)
check("报告判据未复制（仍只有一份）",
      diag_src.count("def _command_report(") == 1
      and diag_src.count("def _health_report(") == 1)

print("⑤ i18n")
from src import i18n  # noqa: E402

zh, en = i18n._STRINGS["zh-CN"], i18n._STRINGS["en-US"]
NEW = {
    "instances.manage_group": "管理与诊断",
    "instances.launch_diag": "启动诊断",
    "instances.repair_deps_short": "补装依赖",
}
check("新 3 键中文文案齐全",
      all(zh.get(k) == v for k, v in NEW.items()))
check("新 3 键英文文案非空",
      all(en.get(k) for k in NEW))
check("旧键已删除", "instances.launch" not in zh and "instances.launch" not in en)
check("中英键集合对称", set(zh) == set(en), "zh=%d en=%d" % (len(zh), len(en)))

print("⑥ 运行时：面板可构造且两页齐全")
from src.launch_diagnostics_dialog import (  # noqa: E402
    LaunchDiagnosticsPanel, _command_report,
)

TMP = tempfile.mkdtemp(prefix="ac_r200_inst_")
inst = types.SimpleNamespace(
    id="demo", name="Demo", game_dir=TMP, mc_dir=TMP,
    game_version="1.20.1", version_id="1.20.1", loader="fabric",
    java_path="", ram_mb=4096, jvm_args="", mods_dir=TMP,
)
panel = LaunchDiagnosticsPanel(inst)
check("面板构造无异常、两个 tab", panel._tabs.count() == 2)
check("两个信号都可连", hasattr(panel, "closed") and hasattr(panel, "open_health"))
check("命令页至少写了实例名",
      "Demo" in panel._cmd_view.toPlainText())
check("体检页非空", bool(panel._health_view.toPlainText().strip()))
panel.deleteLater()

report = _command_report(inst)
check("报告是字符串且非空", isinstance(report, str) and bool(report.strip()))
check("拼不出命令时如实写原因，不假装成功",
      "无法生成启动命令" in report or "classpath 条目" in report,
      report.splitlines()[-1][:40] if report else "")

print("== %s ==" % ("PASS" if not fails else "FAIL %d" % len(fails)))
sys.exit(1 if fails else 0)
