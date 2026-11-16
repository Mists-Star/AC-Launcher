"""round-234：首页健康扫描后台化，不阻塞主线程（离线）。"""
import os
import sys
import threading
import time
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.core.home_summary as HS  # noqa: E402
import src.main_window as MW  # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


win = MW.MainWindow()
inst = SimpleNamespace(id="i1", name="probe", last_played=1.0,
                       mc_dir="", game_dir="", loader="vanilla",
                       game_version="1.20.1")

orig = HS.diagnose_instances
seen_threads: list[threading.Thread] = []
rendered: list[object] = []


def slow_diagnose(*a, **k):
    seen_threads.append(threading.current_thread())
    time.sleep(0.12)
    return SimpleNamespace(continue_with="", needs_attention=[])


orig_render = win.home._render_home_summary
HS.diagnose_instances = slow_diagnose
win.home._render_home_summary = lambda summary, instances, cur_id: rendered.append(summary)
try:
    t = time.perf_counter()
    win.home._refresh_home_summary([inst], inst)
    ms = (time.perf_counter() - t) * 1000
    check("刷新调用不阻塞主线程", ms < 30, "%.1f ms" % ms)

    deadline = time.time() + 3
    while len(rendered) < 1 and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    check("扫描在后台线程执行",
          bool(seen_threads) and seen_threads[0] is not threading.main_thread(),
          str([getattr(t, "name", "?") for t in seen_threads]))
    check("结果回到主线程渲染", len(rendered) == 1, str(len(rendered)))

    # 连续两次刷新：只让最后一代结果上屏
    rendered.clear()
    win.home._refresh_home_summary([inst], inst)
    win.home._refresh_home_summary([inst], inst)
    deadline = time.time() + 3
    while len(rendered) < 1 and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    check("过期扫描结果被丢弃", len(rendered) == 1, str(len(rendered)))
finally:
    HS.diagnose_instances = orig
    win.home._render_home_summary = orig_render

# 预热边界：只碰安全页，资源中心的 worker/网络在退出时销毁顺序不稳
print("== 页面预热 ==")
win2 = MW.MainWindow()
ensured: list[int] = []
orig_ensure = win2._ensure_page
win2._ensure_page = lambda idx: ensured.append(idx)
win2._warm_pages()
deadline = time.time() + 3
while len(ensured) < 3 and time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)
check("预热三页完成", len(ensured) == 3, str(ensured))
check("预热不含资源中心",
      MW.STACK_INDEX["store"] not in ensured, str(ensured))
win2._ensure_page = orig_ensure

print("\n%d checks, %d failed" % (total, len(fails)))
if fails:
    print("FAILED:", ", ".join(fails))
    sys.exit(1)
print("ALL CHECKS PASSED（round-234 首页扫描后台化）")
