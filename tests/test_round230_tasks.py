"""round-230：下载任务页内分区的行为回归（离线，零真实网络）。"""
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import (QApplication, QDialog, QStackedWidget,  # noqa: E402
                               QWidget, QLabel)

app = QApplication.instance() or QApplication([])

import src.core.task_center as TC         # noqa: E402
import src.task_panel as TP               # noqa: E402
import src.pages_browse as PB             # noqa: E402
import src.main_window as MW              # noqa: E402
from src.i18n import _STRINGS             # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


TMP = tempfile.mkdtemp(prefix="ac230_")
_orig_dd = TC.get_data_dir
TC.get_data_dir = lambda: TMP
TC._reset_for_tests()


def center():
    TC._reset_for_tests()
    return TC.get_task_center()


class Sig:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in list(self.slots):
            fn(*a)


# ── [1] 数据层：retry_key 往返与重试用 id ─────────────────────────────
c = center()
a = c.start("download", "实例甲", target_page="instances", retry_key="inst-42")
check("start 保留 retry_key", a.retry_key == "inst-42", a.retry_key)
check("retry_key 序列化往返",
      TC.TaskRecord.from_dict(a.to_dict()).retry_key == "inst-42")
check("旧记录缺 retry_key 也能读",
      TC.TaskRecord.from_dict({"id": "x"}).retry_key == "")
c.fail(a.id, detail="源站 404")
b = c.start("launch", "实例乙", target_page="home")
check("running 只含未结束任务", [r.id for r in c.running()] == [b.id])
check("recent 只含已结束任务", [r.id for r in c.recent()] == [a.id])
c.clear_history()
check("clear_history 只清已结束", c.recent() == [] and len(c.running()) == 1)
c.finish(b.id)


# ── [2] 面板：空态 / 分组 / 失败原因 / 就地操作 ───────────────────────
c = center()
c.clear_history()
p = TP.TaskListPanel()
_empty_labels = [p._rows.itemAt(i).widget() for i in range(p._rows.count())
                 if isinstance(p._rows.itemAt(i).widget(), QLabel)]
check("空态显示提示",
      any("暂无" in (w.text() or "") or "No downloads" in (w.text() or "")
          for w in _empty_labels), str([w.text() for w in _empty_labels]))

r1 = c.start("download", "进行中的包", target_page="instances",
             stage="正在下载库文件", total=100,
             sources=["bmclapi", "official"], retry_key="inst-1")
c.update(r1.id, completed=40)
r2 = c.start("import", "失败的整合包", target_page="instances",
             retry_key="inst-2")
c.fail(r2.id, detail="下载超时")
p.refresh()
check("汇总显示进行中数量", "1" in p.summary.text(), p.summary.text())
texts = [p._rows.itemAt(i).widget().text()
         for i in range(p._rows.count())
         if isinstance(p._rows.itemAt(i).widget(), QLabel)]
check("两个分组标题都在", any("进行中" == x for x in texts)
      and any("最近" == x for x in texts), str(texts[:4]))
rows = [p._rows.itemAt(i).widget()
        for i in range(p._rows.count())
        if isinstance(p._rows.itemAt(i).widget(), TP._TaskRow)]
check("渲染出两条任务行", len(rows) == 2, str(len(rows)))
all_text = " ".join(lb.text() for r in rows for lb in r.findChildren(QLabel))
check("失败原因出现在行里", "下载超时" in all_text, "")
check("清空历史按钮可用", p.clear_btn.isEnabled())

retries = []
navs = []
backs = []
p.retry_requested.connect(lambda k: retries.append(k))
p.navigate_requested.connect(lambda k: navs.append(k))
p.back_requested.connect(lambda: backs.append(1))
fail_row = next(r for r in rows if "失败的整合包" in " ".join(
    lb.text() for lb in r.findChildren(QLabel)))
for btn in fail_row.findChildren(QWidget):
    if hasattr(btn, "text") and btn.text() in ("重试", "Retry"):
        btn.click()
    if hasattr(btn, "text") and btn.text() in ("前往", "Open"):
        btn.click()
check("失败行「重试」带 retry_key", retries == ["inst-2"], str(retries))
check("「前往」带目标页面", navs == ["instances"], str(navs))

p._clear()
check("清空历史后面板同步刷新", c.recent() == [])


# ── [3] 页内接线：不弹窗、用 _stack 整页切换 ─────────────────────────
host = QWidget()
host._detail_panel = None
host._tasks_panel = None
host._stack = QStackedWidget()
host._list_view = QWidget()
host._stack.addWidget(host._list_view)
host.task_retry_requested = Sig()
host.task_navigate_requested = Sig()
host._close_tasks = lambda: PB.StorePage._close_tasks(host)
host._close_detail = lambda: None
PB.StorePage.show_tasks(host)
check("show_tasks 把面板加进页内栈", host._stack.count() == 2)
check("show_tasks 切到任务分区",
      host._stack.currentWidget() is host._tasks_panel)
check("任务面板不是 QDialog（没有新增弹窗）",
      not isinstance(host._tasks_panel, QDialog))
PB.StorePage._close_tasks(host)
check("返回后回到资源列表", host._stack.currentWidget() is host._list_view)
check("返回后面板引用已清", host._tasks_panel is None)

nav_calls = []
host.task_navigate_requested.connect(lambda k: nav_calls.append(k))
PB.StorePage.show_tasks(host, return_key="settings")
PB.StorePage._close_tasks(host)
check("跨页进入后返回原页", nav_calls == ["settings"], str(nav_calls))
nav_calls.clear()
PB.StorePage.show_tasks(host, return_key="store")
PB.StorePage._close_tasks(host)
check("资源中心内跳转不重复导航", nav_calls == [], str(nav_calls))

calls = []
fake_mw = types.SimpleNamespace(
    _current_page_key=lambda: "settings",
    _show_page=lambda k: calls.append(k),
    store_page=types.SimpleNamespace(
        show_tasks=lambda **k: calls.append(("tasks", k))),
    _start_instance_download=lambda iid, **k: calls.append(("retry", iid)))
MW.MainWindow.open_tasks(fake_mw)
check("状态栏入口先切页再开任务分区并记住来源",
      calls == ["store", ("tasks", {"return_key": "settings"})], str(calls))
calls.clear()
MW.MainWindow._on_task_retry(fake_mw, "inst-9")
check("重试转发到实例下载", calls == [("retry", "inst-9")], str(calls))

with open(os.path.join(HERE, "src", "main_window.py"), encoding="utf-8") as f:
    mw_src = f.read()
with open(os.path.join(HERE, "src", "pages_browse.py"), encoding="utf-8") as f:
    pb_src = f.read()
with open(os.path.join(HERE, "src", "pages_instances.py"), encoding="utf-8") as f:
    pi_src = f.read()
check("状态栏按钮不被召回逻辑吞掉",
      'obj is getattr(self, "_tasks_btn", None)' in mw_src)
cf_block = pb_src.split("def _on_cf_pack_downloaded", 1)[-1].split(
    "def _on_pack_error", 1)[0]
check("CF 导入登记了任务", 'start(' in cf_block and '"import"' in cf_block)
check("CF 导入登记了成功/失败终态",
      ".finish(" in cf_block and ".fail(" in cf_block)
mr = pi_src.split("class _MrpackDialog", 1)[-1]
check("mrpack 安装登记了任务与终态",
      'start(' in mr and ".finish(" in mr and ".fail(" in mr)
imp = pi_src.split("def _import_pack(self)", 1)[-1].split(
    "def dragEnterEvent", 1)[0]
check("实例页导入不再创建进度框", "QProgressDialog" not in imp)
check("实例页导入登记任务与终态",
      'start(' in imp and ".finish(" in imp and ".fail(" in imp)
check("两处导入进度框都已收口",
      "QProgressDialog" not in cf_block and "QProgressDialog" not in imp)

for key in ("tasks.title", "tasks.summary", "tasks.retry", "tasks.state_failed"):
    check("i18n 中英对称 " + key,
          key in _STRINGS["zh-CN"] and key in _STRINGS["en-US"])

TC.get_data_dir = _orig_dd
TC._reset_for_tests()

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-230 任务分区回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-230 任务分区回归）")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
