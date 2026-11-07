"""round-194：一键修复安全项的反馈。

用户：「一键修复安全项点了没有用，而且如果是修补，一点提示都没有」。

真因：`_fix_all` 调 `toast(self, ...)` —— 体检对话框**没有**主窗口的浮层
toast 能力，`toast()` 会回落到 `info()`（**模态** QMessageBox），在 frameless
对话框后面弹出来 → 玩家看不见 → 「点了没反应 / 没提示」。而且对话框内那条
反馈行当时压根没被用（一键修复没调 `_note`）。

判据：
1. 一键修复**不弹模态框**（源码里不再有 toast/info 调用）；
2. 修复后对话框内反馈行**可见且有文字**（含修了哪些项）；
3. 没有可修项时给的是明确文案，不是空白；
4. 修复**真的生效**（实例字段变了）；
5. 单条修复同样走反馈行（round-163 已有）。
"""
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

DEV = tempfile.mkdtemp(prefix="ac_r194_")
os.chdir(DEV)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


src = io.open(os.path.join(HERE, "src", "mod_check_dialog.py"),
              encoding="utf-8").read()

print("① 源码层：一键修复不再弹模态框")
fix_all_body = src.split("def _fix_all", 1)[1].split("def _rescan", 1)[0]
# 用 AST 精确判：只看真正的函数调用（注释与 docstring 里提到 toast 是说明
# 问题由来，不能算调用）
import ast  # noqa: E402

_fn = next(n for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.FunctionDef) and n.name == "_fix_all")
_calls = [n.func.id for n in ast.walk(_fn)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
check("_fix_all 没有调用 toast/info",
      "toast" not in _calls and "info" not in _calls, str(_calls))
check("_fix_all 里没有 info(", "info(" not in fix_all_body)
check("_fix_all 会调用 _note", "_note(" in fix_all_body)

print("② 反馈行做得醒目")
check("反馈行有底色/边框样式", "border-radius" in src and "note_lbl" in src)

print("③ 运行时：修复真的生效 + 有反馈")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.instances import Instance  # noqa: E402
from src.core import instance_health  # noqa: E402
from src.mod_check_dialog import HealthDialog  # noqa: E402

inst = Instance(id="h", name="体检", game_version="1.20.1", loader="fabric",
                perf_g1gc=False, perf_disable_explicit_gc=False)
res = instance_health.scan_health(inst, None)
dlg = HealthDialog(inst, res, None)
check("有可修项时按钮可用", dlg.fixall_btn.isEnabled())
dlg._fix_all()
check("反馈行不再隐藏", not dlg.note_lbl.isHidden())
note = dlg.note_lbl.text()
check("反馈有文字", bool(note.strip()), note[:40])
check("反馈提到修了什么", "项" in note or "Fixed" in note, note[:40])
check("修复真的生效",
      bool(getattr(inst, "perf_g1gc", False) or
           getattr(inst, "perf_disable_explicit_gc", False)),
      "g1gc=%s degc=%s" % (getattr(inst, "perf_g1gc", None),
                           getattr(inst, "perf_disable_explicit_gc", None)))

print("④ 没有可修项时给明确文案")
inst2 = Instance(id="h2", name="体检2", game_version="1.20.1", loader="fabric",
                 perf_g1gc=True, perf_disable_explicit_gc=True)
res2 = instance_health.scan_health(inst2, None)
dlg2 = HealthDialog(inst2, res2, None)
check("无安全项时按钮禁用", not dlg2.fixall_btn.isEnabled())
check("禁用时 tooltip 说明原因",
      bool(dlg2.fixall_btn.toolTip()), dlg2.fixall_btn.toolTip()[:30])

dlg.deleteLater(); dlg2.deleteLater()
shutil.rmtree(DEV, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-194 一键修复反馈）")
