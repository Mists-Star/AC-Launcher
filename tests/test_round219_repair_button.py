"""round-219：「一键修复」按钮点了没反应 的行为回归。

主理人实机反馈：实例「26.3」崩溃分析里点「一键修复」没有任何反应。

根因：按钮可用性写死了 ``("mod_dep_missing", "java_version", "out_of_memory")``
三个 kind，**漏了 loader_mismatch** —— 而它在规则表 ``_RULES`` 里明明标着
``repairable=True``。于是这类实例的按钮**永久禁用**（禁用按钮根本不响应点击，
玩家看到的就是「点了没反应」）。

本文件断言：
  1. 可用性以规则表的 ``repairable`` 标记为准（不再写死 kind 列表）；
  2. 只有「不可自动修」的结论时按钮才禁用；
  3. 点击后必须有**可见**反馈，且点名说出要玩家处理的是哪一条；
  4. 反馈里同时保留依赖修复自己的结论（不再互相覆盖成「已自动处理 0 项」）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-62s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


from unittest import mock  # noqa: E402

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.crash_dialog as cd  # noqa: E402
from src.crash_analysis import CrashFinding, _RULES  # noqa: E402


class _Inst:
    id = "i1"
    name = "26.3"
    mc_dir = os.getcwd()


def _f(kind, repairable=True, culprit=""):
    return CrashFinding(
        kind=kind, severity="critical",
        title="crash.kind.%s" % kind,
        reason="crash.reason.%s" % kind,
        suggestion="crash.fix.%s" % kind,
        repairable=repairable, detail="", culprit=culprit)


_HOSTS = []      # 保住 host，否则函数返回后 Qt 回收 → 面板 C++ 对象被删


def _panel(findings):
    with mock.patch.object(cd.crash, "analyze_instance", lambda inst: findings):
        host = QWidget()
        host.resize(900, 600)
        panel = cd.CrashAnalyzerPanel(_Inst(), parent=host)
        host.show()
        for _ in range(6):
            app.processEvents()
    _HOSTS.append(host)
    return panel


# ══════════════════════════════════════════════════════════════════════
# 1. 规则表与按钮可用性
# ══════════════════════════════════════════════════════════════════════
print("== 1. 按钮可用性 ==")
rule_kinds = {r[0] for r in _RULES}
check("规则表里有 loader_mismatch",
      "loader_mismatch" in rule_kinds)
check("loader_mismatch 在规则表里标着可修",
      any(r[0] == "loader_mismatch" and r[5] for r in _RULES))

panel = _panel([_f("loader_mismatch", True, "sodium-fabric-1.jar")])
check("只命中 loader_mismatch 时按钮可用",
      panel.repair_all_btn.isEnabled())

panel2 = _panel([_f("fatal_exception", False)])
check("只有不可自动修的结论时按钮禁用",
      not panel2.repair_all_btn.isEnabled())

panel3 = _panel([_f("mod_dep_missing", True), _f("fatal_exception", False)])
check("混合结论时按钮可用", panel3.repair_all_btn.isEnabled())

# ══════════════════════════════════════════════════════════════════════
# 2. 点击后的可见反馈
# ══════════════════════════════════════════════════════════════════════
print("== 2. 点击后有可见反馈 ==")

with mock.patch.object(cd.CrashAnalyzerPanel, "_repair_deps",
                       lambda self: False):
    panel.repair_all_btn.click()
    for _ in range(6):
        app.processEvents()

text = panel.fix_note.text() or ""
check("反馈条可见", panel.fix_note.isVisible())
check("反馈条有内容", bool(text.strip()), text[:60])
check("反馈里点名了要手动处理的结论",
      "加载器" in text or "loader" in text.lower(), text[:80])
check("反馈里带上了可疑模组名",
      "sodium-fabric-1.jar" in text, text[:120])

# 依赖那边的结论不能被覆盖掉
panel4 = _panel([_f("mod_dep_missing", True), _f("loader_mismatch", True)])
with mock.patch.object(cd.CrashAnalyzerPanel, "_repair_deps",
                       lambda self: False):
    panel4.repair_all_btn.click()
    for _ in range(6):
        app.processEvents()
t4 = panel4.fix_note.text() or ""
check("没有自动处理时不再只说「已自动处理 0 项」",
      "已自动处理 0 项" not in t4, t4[:80])
check("手动清单仍然列出", "加载器" in t4 or "loader" in t4.lower(), t4[:80])

# ══════════════════════════════════════════════════════════════════════
# 3. _manual_lines 内容
# ══════════════════════════════════════════════════════════════════════
print("== 3. 手动清单文案 ==")
lines = cd.CrashAnalyzerPanel._manual_lines(
    [_f("loader_mismatch", True, "jei-1.0.jar")])
check("每条结论一行", len(lines) == 1, str(lines))
check("含标题 + 可疑模组", lines and "jei-1.0.jar" in lines[0], str(lines))
check("含建议", lines and len(lines[0]) > 10, str(lines))

print("\nround-219 regression: %d checks, %d failed" % (total, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.stdout.flush()
    os._exit(1)
print("ALL CHECKS PASSED（round-219 一键修复按钮）")
sys.stdout.flush()
os._exit(0)
