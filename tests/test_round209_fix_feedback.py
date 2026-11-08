"""round-209：一键修复「点了没用 / 修补无反馈」回归（离线，零真实网络）。

三条入口以前各写各的反馈：崩溃分析只写一行可能被隐藏的 status 小灰字、
实例右键只有 frameless 下会跑到窗口后面的模态 info/warn、体检另有一套
反馈条。统一到 src/fix_feedback.py 后，这里用离屏点击验证「玩家真的看得见」。
"""
from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-64s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8") as f:
        return f.read()


crash_src = read("src/crash_dialog.py")
health_src = read("src/mod_check_dialog.py")
inst_src = read("src/pages_instances.py")
fb_src = read("src/fix_feedback.py")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from src.i18n import _STRINGS, t                    # noqa: E402
from src import fix_feedback as fb                  # noqa: E402

app = QApplication.instance() or QApplication([])

print("\n[1] 静态契约：三条入口导向同一实现")
check("crash_dialog 不再直接 import 模态 info/warn",
      "from .win_rounded import _msgbox" in crash_src
      and "from .win_rounded import _msgbox, info, warn" not in crash_src)
check("三条入口都使用 fix_feedback.report",
      all("report(" in s for s in (crash_src, health_src, inst_src))
      and "from .fix_feedback import" in crash_src
      and "from .fix_feedback import" in health_src
      and "from .fix_feedback import" in inst_src)
check("右键补装不再用模态 info/warn 汇报结果",
      "from .win_rounded import info, warn" not in inst_src
      and 'info(self, t("health.title")' not in inst_src)
check("共享组件提供 attach / report / FeedbackBar / summarize",
      all(x in fb_src for x in ("class FeedbackBar", "def attach(",
                                "def report(", "def summarize(")))
check("中英文案对称且新增键齐全",
      set(_STRINGS["zh-CN"]) == set(_STRINGS["en-US"])
      and all(k in _STRINGS["zh-CN"] for k in
              ("fix.title", "fix.progress", "fix.summary",
               "fix.manual_hint", "fix.deps_start",
               "fix.deps_deferred", "fix.deps_none")))
summary, tone = fb.summarize(2, 1, 3)
check("summarize 三参数齐全，不泄漏 {placeholder}",
      "{" not in summary and "2" in summary and "1" in summary
      and "3" in summary and tone == "warn")
check("summarize 全成功时 tone=ok / 全零时 tone=info",
      fb.summarize(1, 0)[1] == "ok" and fb.summarize(0, 0)[1] == "info")

bar = fb.FeedbackBar()
check("FeedbackBar 空文本时隐藏", bar.isHidden() and bar.text() == "")
bar.show_message("done", "ok")
check("FeedbackBar 有文本时显示且可清空",
      not bar.isHidden() and bar.text() == "done")
bar.show_message("", "info")
check("FeedbackBar 清空后重新隐藏", bar.isHidden())


# ── 共用 mock ─────────────────────────────────────────────────────────────
import src.crash_dialog as cd            # noqa: E402
import src.mod_check_dialog as mcd       # noqa: E402
import src.win_rounded as wr             # noqa: E402
import src.core.mod_repair as mr         # noqa: E402
import src.core.instance_health as ih    # noqa: E402
import src.crash_analysis as crash       # noqa: E402
import src.pages_instances as pi         # noqa: E402
import src.worker as worker_mod          # noqa: E402

modals = []
toasts = []


def fake_info(parent, title, text, detail="", **kw):
    modals.append(("info", text))


def fake_warn(parent, title, text, detail="", **kw):
    modals.append(("warn", text))


def fake_msgbox(parent, title, text, detail="", icon="warning",
                buttons=("Yes", "No")):
    modals.append(("msgbox", text))
    return buttons[0]


wr.info = fake_info
wr.warn = fake_warn
wr.toast = lambda parent, title, text="", duration=3200: toasts.append(text)
cd._msgbox = fake_msgbox


class Inst:
    id = "i1"
    name = "Smoke"
    game_version = "1.20.1"
    loader = "fabric"
    mc_dir = ""


inst = Inst()


def pump(n=60):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


print("\n[2] 崩溃分析「一键修复」：即时反馈 + 汇总终态")
cd.crash.analyze_instance = lambda _inst: []
mr.scan_missing = lambda _inst: {"skipped": False, "missing": ["jei"],
                                 "jar_count": 1, "message": ""}
mr.repair_missing = lambda _inst, missing=None, callback=None: {
    "downloaded": ["jei-1.jar"], "failed": [], "skipped": False,
    "missing": [], "message": "已补装 1 个依赖"}
modals.clear()
toasts.clear()
p = cd.CrashAnalyzerPanel(inst)
pump()
p._findings = [SimpleNamespace(kind="mod_dep_missing"),
               SimpleNamespace(kind="java_version")]
p.repair_all_btn.setEnabled(True)
check("修复前反馈条为空且隐藏",
      p.fix_note.isHidden() and p.fix_note.text() == "")
p.repair_all_btn.click()
immediate = p.fix_note.text()
check("点击瞬间就有可见反馈", not p.fix_note.isHidden() and bool(immediate))
check("即时文案不谎报「已补装」",
      "正在" in immediate and "已自动补装" not in immediate, immediate)
pump(80)
final = p.fix_note.text()
check("异步完成后显示结构化汇总",
      "已自动处理 1 项" in final and "失败 0 项" in final, final)
check("汇总明确说明需手动处理的项（不再假装全修好）",
      "需手动处理 1 项" in final and "另有 1 项" in final)
check("不再用模态 info/warn 汇报终态",
      not any(k in ("info", "warn") for k, _ in modals))
check("仍保留下载前的确认对话框",
      any(k == "msgbox" for k, _ in modals))

# 失败分支：tone 必须是 warn 且明细可见
cd.crash.analyze_instance = lambda _inst: []
mr.repair_missing = lambda _inst, missing=None, callback=None: {
    "downloaded": [], "failed": [{"id": "jei", "stage": "download",
                                  "reason": "timeout"}],
    "skipped": False, "missing": [], "message": "未能补装依赖"}
modals.clear()
p2 = cd.CrashAnalyzerPanel(inst)
pump()
p2._findings = [SimpleNamespace(kind="mod_dep_missing")]
p2.repair_all_btn.setEnabled(True)
p2.repair_all_btn.click()
pump(80)
check("失败分支显示失败数与明细",
      "失败 1 项" in p2.fix_note.text() and "jei" in p2.fix_note.text(),
      p2.fix_note.text()[:100])


print("\n[3] 实例体检「一键修复安全项」：共用反馈条 + 不漏占位符")
fx = {"action": "set_java_path", "params": {}, "safety": "safe",
      "label": "health.fixlabel.set_java_path", "label_kwargs": {}}
f = SimpleNamespace(kind="java_mismatch", severity="warning",
                    fix=fx, extra_fixes=[],
                    title="health.kind.java_mismatch",
                    reason="health.reason.java_mismatch",
                    suggestion="health.fix.java_mismatch",
                    meta={}, filenames=[])
ih.apply_fix = lambda _inst, _fx: True
ih.scan_health = lambda _inst, _cfg: {"findings": [], "groups": [],
                                      "fixable": 0}
hp = mcd.HealthPanel(inst, {"findings": [f], "groups": [], "fixable": 1})
check("体检反馈条就是共享 FeedbackBar",
      isinstance(hp.note_lbl, fb.FeedbackBar) and hp.fix_note is hp.note_lbl)
hp.fixall_btn.click()
check("点击后有可见反馈且写明修复数",
      not hp.fix_note.isHidden() and "已修复 1 项" in hp.fix_note.text())
check("缺 label_kwargs 时不泄漏 {advised} 占位符",
      "{" not in hp.fix_note.text(), hp.fix_note.text())


print("\n[4] 实例右键「补装缺失依赖」：浮层 toast，不再只有模态框")
class FakeSyncWorker:
    def __init__(self, fn, *args, **kwargs):
        self.finished, self.error = _Sig(), _Sig()
        self._fn, self._args = fn, args

    def start(self):
        try:
            self.finished.emit(self._fn(*self._args))
        except Exception as e:
            self.error.emit(str(e))


class _Sig:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, value):
        for s in list(self._slots):
            s(value)


worker_mod.Worker = FakeSyncWorker
mr.scan_missing = lambda _inst: {"skipped": False, "missing": ["jei"],
                                 "jar_count": 1, "message": ""}
mr.repair_missing = lambda _inst, missing=None, callback=None: {
    "downloaded": ["jei-1.jar"], "failed": [], "skipped": False,
    "missing": [], "message": "已补装 1 个依赖"}
modals.clear()
toasts.clear()
host = QWidget()
host._repair_worker = None
pi.InstancesPage._repair_mod_deps.__get__(host, QWidget)(inst)
pump(20)
check("点击瞬间即上报浮层反馈",
      len(toasts) >= 2 and "正在" in toasts[0], str(toasts[:2]))
check("终态浮层含结构化结果",
      any("已自动处理 1 项" in x for x in toasts), str(toasts[-1:]))
check("全程零模态 info/warn", len(modals) == 0, str(modals))

print("\nround-209 fix feedback: %d checks, %d failed" % (total, len(fails)))
if fails:
    for x in fails:
        print("  FAILED:", x)
    sys.exit(1)
print("ALL CHECKS PASSED（round-209 一键修复反馈统一）")
