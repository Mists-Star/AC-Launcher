"""round-168 回归测试：任务可取消 / 取消语义 / 取消按钮。

覆盖：
  1. ProgressWorker 取消后发 cancelled（不发 finished/error）；
  2. 未取消时正常 finished；
  3. 真失败仍发 error；取消后再抛异常不发 error；
  4. abort() 立刻置 interruption + 取消标记；
  5. TaskCenter：cancel 终态、取消后 update 不复活；
  6. 下载/启动对话框都有取消按钮，文案按模式区分；点击发信号；
     set_cancelling 禁用按钮；mark_cancelled 改状态文案。
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AC_DEV_TEMP"] = "1"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.worker import ProgressWorker  # noqa: E402
from src.core.task_center import (  # noqa: E402
    TaskCenter, STATE_CANCELLED, STATE_RUNNING)
from src.instances import Instance  # noqa: E402
from src.launch_dialog import LaunchProgressDialog  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


print("== round-168 任务取消 ==")

# ── 1. ProgressWorker 取消语义 ──────────────────────────────────────────
holder = {}


def fn_cancel_ok(callback=None):
    holder["w"].abort()
    return ("proc", "log")


w = ProgressWorker(fn_cancel_ok)
holder["w"] = w
seen = {"cancelled": [], "finished": [], "error": []}
w.cancelled.connect(lambda r: seen["cancelled"].append(r))
w.finished.connect(lambda r: seen["finished"].append(r))
w.error.connect(lambda e: seen["error"].append(e))
w.run()
check("取消后 cancelled 发出一次", len(seen["cancelled"]) == 1, str(seen["cancelled"]))
check("取消后 finished 不发", len(seen["finished"]) == 0)
check("取消后 error 不发", len(seen["error"]) == 0)
check("cancelled 携带结果（可强杀已 spawn 进程）",
      seen["cancelled"] and seen["cancelled"][0] == ("proc", "log"))


def fn_ok(callback=None):
    return "ok"


w2 = ProgressWorker(fn_ok)
seen2 = {"finished": 0, "cancelled": 0}
w2.finished.connect(lambda r: seen2.__setitem__("finished", seen2["finished"] + 1))
w2.cancelled.connect(lambda r: seen2.__setitem__("cancelled", seen2["cancelled"] + 1))
w2.run()
check("未取消正常 finished", seen2["finished"] == 1 and seen2["cancelled"] == 0)


def fn_boom(callback=None):
    raise ValueError("boom")


w3 = ProgressWorker(fn_boom)
errs3 = []
w3.error.connect(errs3.append)
w3.run()
check("真失败发 error", len(errs3) == 1 and "boom" in errs3[0])


def fn_cancel_boom(callback=None):
    holder["w4"].abort()
    raise ValueError("cancelled boom")


w4 = ProgressWorker(fn_cancel_boom)
holder["w4"] = w4
errs4 = []
w4.error.connect(errs4.append)
w4.run()
check("取消后抛异常不再发 error", len(errs4) == 0)

w5 = ProgressWorker(fn_ok)
w5.abort()
check("abort 置取消标记", w5._cancel_requested is True)
# Qt 6 的 requestInterruption 在线程未运行时会被忽略，这里只验证自有标记；
# 运行期中断由 _is_cancelled() 两者取或兜底。

# ── 2. TaskCenter 取消态 ────────────────────────────────────────────────
tc = TaskCenter()
task = tc.start("download", "demo")
check("任务初始 running", tc.get(task.id).state == STATE_RUNNING)
tc.cancel(task.id, "cancelled")
check("cancel 后终态 cancelled", tc.get(task.id).state == STATE_CANCELLED)
before = tc.get(task.id).state
tc.update(task.id, stage="late")
check("取消后 update 不复活", tc.get(task.id).state == before)

# ── 3. 对话框取消按钮 ───────────────────────────────────────────────────
inst = Instance(id="cancel_test", name="Test", game_version="1.20.1")

dl_dlg = LaunchProgressDialog(inst, mode="download")
clicks = []
dl_dlg.cancel_requested.connect(lambda: clicks.append(1))
dl_dlg.cancel_btn.click()
check("下载对话框：点击发出 cancel_requested", len(clicks) == 1)
dl_dlg.set_cancelling()
check("set_cancelling 后按钮禁用", dl_dlg.cancel_btn.isEnabled() is False)
dl_dlg.mark_cancelled()
check("mark_cancelled 显示已取消", "取消" in dl_dlg.status_lbl.text(), dl_dlg.status_lbl.text())

ln_dlg = LaunchProgressDialog(inst)
check("启动对话框有取消按钮", ln_dlg.cancel_btn is not None)
check("下载/启动取消文案不同",
      dl_dlg.cancel_btn.text() != ln_dlg.cancel_btn.text(),
      "%s | %s" % (dl_dlg.cancel_btn.text(), ln_dlg.cancel_btn.text()))

# ── 4. i18n 键存在 ──────────────────────────────────────────────────────
from src.i18n import t  # noqa: E402

for key in ("launch.cancel_download", "launch.cancel_launch",
            "launch.cancel_download_msg", "launch.cancel_launch_msg",
            "launch.cancelling", "launch.cancelled", "launch.cancel_pending",
            "status.launch_cancelled", "status.launch_cancelling",
            "tray.quit_confirm_title", "tray.quit_confirm_msg",
            "tray.quit_game_note", "tray.quit_and_abort", "tray.force_quit"):
    val = t(key)
    check("i18n %s" % key, bool(val) and val != key, val)

print()
print("== round-172 取消要真正停下在途下载 ==")

import threading  # noqa: E402
import time  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

from src.core import mirror  # noqa: E402


class _SlowHandler(BaseHTTPRequestHandler):
    """慢速吐 1 MB：取消若只在「下一个请求前」生效，这文件会读满 ~3 秒。"""

    def do_GET(self):  # noqa: N802
        total = 1024 * 1024
        self.send_response(200)
        self.send_header("Content-Length", str(total))
        self.end_headers()
        chunk = b"x" * 8192
        sent = 0
        while sent < total:
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except Exception:
                return
            sent += len(chunk)
            time.sleep(0.02)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = "http://127.0.0.1:%d/f.bin" % srv.server_address[1]

mirror.patch_install_session()

inflight = {}


def _download_once():
    """在一个安装上下文里下载慢文件（模拟 mll 的 copyfileobj）。"""
    import minecraft_launcher_lib._helper as helper
    with mirror.install_scope() as ctx:
        inflight["ctx"] = ctx
        session = helper.requests.session()
        try:
            helper.download_file(url, os.path.join(HERE, "_cancel_tmp.bin"),
                                 {}, session=session)
            inflight["result"] = "finished"
        except Exception as e:  # noqa: BLE001
            inflight["result"] = "raised:" + type(e).__name__


th = threading.Thread(target=_download_once, daemon=True)
th.start()
time.sleep(0.4)
inflight["ctx"].abort()
t0 = time.time()
th.join(3.0)
elapsed = time.time() - t0
check("在途下载被立刻中断（< 1.5s）", (not th.is_alive()) and elapsed < 1.5,
      "%.2fs %s" % (elapsed, inflight.get("result")))
check("中断记为异常而不是正常完成",
      inflight.get("result", "").startswith("raised:"),
      str(inflight.get("result")))
try:
    os.remove(os.path.join(HERE, "_cancel_tmp.bin"))
except OSError:
    pass
srv.shutdown()


# ── 子进程取消（加载器安装器走这条路）────────────────────────────────────
def _run_long_subprocess():
    with mirror.install_scope() as ctx:
        inflight["ctx2"] = ctx
        try:
            mirror.run_cancellable(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=HERE, timeout=60)
            inflight["proc_result"] = "returned"
        except Exception as e:  # noqa: BLE001
            inflight["proc_result"] = type(e).__name__


th2 = threading.Thread(target=_run_long_subprocess, daemon=True)
th2.start()
time.sleep(0.4)
inflight["ctx2"].abort()
t1 = time.time()
th2.join(4.0)
check("安装器子进程被结束（< 2s）", (not th2.is_alive()) and time.time() - t1 < 2.0,
      "%.2fs %s" % (time.time() - t1, inflight.get("proc_result")))
check("取消抛 InstallCancelled（不当成网络失败）",
      inflight.get("proc_result") == "InstallCancelled",
      str(inflight.get("proc_result")))

# 取消后不再启动新的子进程
ctx3 = mirror.InstallContext()
ctx3.abort()
try:
    with mirror.install_scope():
        pass
    # install_scope 自己新建 ctx，这里直接验证无上下文时的兜底
    check("无安装上下文时 abort_requested 为 False",
          mirror.abort_requested() is False)
except Exception:  # noqa: BLE001
    check("无安装上下文时 abort_requested 为 False", False)

print()
if fails:
    print("FAILED %d:" % len(fails))
    for f in fails:
        print(" - %s" % f)
    sys.exit(1)
print("全部通过")
