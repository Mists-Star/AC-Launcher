"""round-173 回归测试：Java 下载「看得见 + 停得下」。

覆盖：
  1. install_java 下载中途取消 → 抛 JavaInstallCancelled，半截 zip 与半成品目录都不留；
  2. install_java 阶段顺序 connect → download → extract，成功返回 java 路径；
  3. 解压期间取消（解压后复查）→ 丢半成品并抛取消；
  4. _JavaInstallThread.cancel() → 发 cancelled 而不是 failed/done；
  5. JavaManagerDialog 有状态标签 / 取消按钮；关闭对话框会 cancel + wait 下载线程；
  6. i18n 中英各有新增的 9 个键。
"""
import io
import os
import sys
import tempfile
import threading
import time
import types
import zipfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AC_DEV_TEMP"] = "1"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.core import java_install  # noqa: E402
from src import onboarding  # noqa: E402
from src import i18n  # noqa: E402
from src.java_manager_dialog import JavaManagerDialog  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


print("== round-173 Java 下载可见 / 可取消 ==")

TMP = tempfile.mkdtemp(prefix="_java173_")
_ORIG = {
    "get_data_dir": java_install.get_data_dir,
    "requests": java_install.requests,
    "install_java": java_install.install_java,
    "available_majors": java_install.available_majors,
}


# ── 假响应：可控分块 + 延迟，便于在中途取消 ──────────────────────────────
class _FakeResp:
    def __init__(self, payload, chunk=8192, delay=0.0, total=None):
        self.headers = {
            "Content-Length": str(len(payload) if total is None else total)}
        self._payload = payload
        self._chunk = chunk
        self._delay = delay

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        for i in range(0, len(self._payload), self._chunk):
            if self._delay:
                time.sleep(self._delay)
            yield self._payload[i:i + self._chunk]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _install_fake_requests(payload, chunk=8192, delay=0.0, total=None):
    fake = types.SimpleNamespace(
        get=lambda url, **kw: _FakeResp(payload, chunk, delay, total))
    java_install.requests = fake


def _zip_payload() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("jdk-8.0.999-jre/bin/java.exe", b"MZ")
        z.writestr("jdk-8.0.999-jre/release", b"JAVA_VERSION=8\n")
    return buf.getvalue()


def _fresh_root():
    root = os.path.join(TMP, "java")
    java_install.get_data_dir = lambda: TMP
    return root


# ── 1. 下载中途取消 ────────────────────────────────────────────────────
java_install.get_data_dir = lambda: TMP
root = _fresh_root()
java_install.install_java = _ORIG["install_java"]
_install_fake_requests(b"x" * (256 * 8192), delay=0.01)   # ≈2.5s 才下得完

ev = threading.Event()
state = {"err": None}
phases = []


def _worker_cancel():
    try:
        java_install.install_java(
            17, progress=lambda d, t, p: phases.append(p) or None,
            cancel=ev.is_set)
    except BaseException as e:  # noqa: BLE001
        state["err"] = type(e).__name__


th = threading.Thread(target=_worker_cancel, daemon=True)
th.start()
deadline = time.time() + 5.0
while time.time() < deadline and "download" not in phases:
    time.sleep(0.02)
ev.set()
t0 = time.time()
th.join(3.0)
elapsed = time.time() - t0
check("下载中途取消立刻抛出", (not th.is_alive()) and elapsed < 1.0,
      "%.2fs %s" % (elapsed, state["err"]))
check("抛的是 JavaInstallCancelled", state["err"] == "JavaInstallCancelled",
      str(state["err"]))
check("半截 zip 已清理", not os.path.exists(os.path.join(root, "_dl_17.zip")))
check("半成品目录不存在", not os.path.isdir(os.path.join(root, "jre-17")))

# ── 2. 正常下载：阶段顺序 + 落盘路径 ───────────────────────────────────
payload = _zip_payload()
_install_fake_requests(payload, chunk=1024)
phases = []
path = java_install.install_java(
    8, progress=lambda d, t, p: phases.append(p))
check("阶段包含 connect/download/extract",
      phases[:1] == ["connect"] and "download" in phases and phases[-1] == "extract",
      str(sorted(set(phases)))
      + " 首=%s 尾=%s" % (phases[0], phases[-1]))
check("返回的 java 路径存在", os.path.isfile(path or ""), str(path))
check("下载完成后 zip 已删除",
      not os.path.exists(os.path.join(root, "_dl_8.zip")))

# ── 3. 解压期间取消 → 丢弃半成品 ───────────────────────────────────────
ev3 = threading.Event()
ev3.set()
state3 = {"err": None}
try:
    java_install.install_java(21, cancel=ev3.is_set)
except BaseException as e:  # noqa: BLE001
    state3["err"] = type(e).__name__
check("解压前已取消即抛取消", state3["err"] == "JavaInstallCancelled",
      str(state3["err"]))
check("取消后不留目标目录", not os.path.isdir(os.path.join(root, "jre-21")))


# ── 4. _JavaInstallThread.cancel → cancelled ──────────────────────────
def _slow_install(major, progress=None, cancel=None):
    for _ in range(80):
        if cancel is not None and cancel():
            raise java_install.JavaInstallCancelled("cancel")
        time.sleep(0.02)
    return os.path.join(TMP, "fake_java", "bin", "java.exe")


java_install.install_java = _slow_install
seen = []
thr = onboarding._JavaInstallThread(17)
thr.cancelled.connect(lambda: seen.append("cancelled"))
thr.done.connect(lambda p: seen.append("done"))
thr.failed.connect(lambda e: seen.append("failed"))
thr.start()
time.sleep(0.1)
thr.cancel()
thr.wait(3000)
app.processEvents()   # 跨线程信号是队列投递，等主线程处理一次
check("取消只发 cancelled", seen == ["cancelled"], str(seen))
check("取消后线程已结束", not thr.isRunning())

# ── 5. 对话框：状态标签 / 取消按钮 / 关闭即停 ──────────────────────────
java_install.available_majors = lambda: [8, 17, 21]
java_install.install_java = _slow_install
dlg = JavaManagerDialog(None, "")
check("对话框有下载状态标签", hasattr(dlg, "dl_status"))
check("状态标签初始隐藏", not dlg.dl_status.isVisible())
check("对话框有取消下载按钮", hasattr(dlg, "dl_cancel_btn"))
check("取消按钮初始隐藏", not dlg.dl_cancel_btn.isVisible())
dlg.dl_cancel_btn.click()          # 没有下载时点它不能崩
check("无下载时点取消不崩", dlg._dl_thread is None)

# 状态文案：下载中有大小 + 百分比
dlg._dl_phase = "download"
dlg._dl_done = 10 * 1024 * 1024
dlg._dl_total = 50 * 1024 * 1024
dlg._dl_speed = 2 * 1024 * 1024
dlg._render_dl_status()
txt = dlg.dl_status.text()
check("状态行含大小与百分比", "10.0 MB" in txt and "20%" in txt and "MB/s" in txt, txt)


class _StubThread:
    def __init__(self):
        self.cancelled_flag = False
        self.waited = 0

    def cancel(self):
        self.cancelled_flag = True

    def wait(self, ms):
        self.waited = ms
        return True


stub = _StubThread()
dlg._dl_thread = stub
dlg.done(0)
check("关闭对话框会取消下载线程", stub.cancelled_flag)
check("关闭对话框会等线程收尾", stub.waited == 2000, str(stub.waited))
dlg.deleteLater()

# ── 6. i18n 键两边都有 ──────────────────────────────────────────────────
KEYS = ["javamgr.dl_cancel", "javamgr.dl_cancelling", "javamgr.dl_cancelled",
        "javamgr.phase_connect", "javamgr.phase_extract", "javamgr.dl_progress",
        "javamgr.dl_progress_unknown", "javamgr.dl_speed",
        "onboard.java_extracting"]
zh = i18n._STRINGS["zh-CN"]
en = i18n._STRINGS["en-US"]
missing = [k for k in KEYS if k not in zh or k not in en]
check("中英都有 9 个新键", not missing, str(missing))
check("下载进度文案可格式化",
      "10.0 MB" in i18n.t("javamgr.dl_progress", done="10.0 MB",
                          total="50.0 MB", pct=20))

# ── 收尾：还原被替换的模块属性 ────────────────────────────────────────
java_install.get_data_dir = _ORIG["get_data_dir"]
java_install.requests = _ORIG["requests"]
java_install.install_java = _ORIG["install_java"]
java_install.available_majors = _ORIG["available_majors"]
try:
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
except Exception:  # noqa: BLE001
    pass

print()
if fails:
    print("FAILED %d:" % len(fails))
    for f in fails:
        print(" - %s" % f)
    sys.exit(1)
print("全部通过")
