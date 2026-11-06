"""状态栏信号归属回归（round-177，2026-11-06 真机「左下角一直闪」）。

事故：下载 / 启动 worker 把 status / speed / progress 三路信号直连全局
状态栏；取消或失败时只把 worker 从 ``_dl_workers`` 里 pop 掉，从不
disconnect。而 ProgressWorker 的速度轮询线程与 stall 定时器仍在发信号，
``_set_progress`` 甚至 ``setVisible(True)`` 把进度条重新点亮。旧任务的
残留计数（用户看到的「后面都是 9」）与新任务的正确值交替刷 → 闪烁。
代码注释还误称「残留信号因 worker 已移出表而被丢弃」——被挡住的只有
``_on_download_progress`` 那一个带 guard 的槽。

新语义：三路状态栏信号走带 worker 归属的槽；只有仍在登记表里的 worker
能写；任务所有终态（完成/失败/取消/暂停/启动完成/启动失败/启动取消）
显式 disconnect 并清空显示。

判据分两层：
  1. 行为真相：轻量 fake 直接绑定未绑定方法 + 真实 Qt Signal，断言
     「在册能写 / 出册即丢 / unbind 后彻底断」；
  2. 静态防再犯：源码不得再出现三处直连，所有终态路径都要 unbind，
     失败对话框要有醒目终态。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(HERE, rel), "r", encoding="utf-8") as f:
        return f.read()


from PySide6.QtCore import QObject, Signal  # noqa: E402
from src.main_window import MainWindow  # noqa: E402


class _Worker(QObject):
    status = Signal(str)
    speed = Signal(str)
    progress = Signal(int, int)


class _Bar:
    def __init__(self):
        self.msgs = []

    def showMessage(self, text, *_a):
        self.msgs.append(text)


class _Widget:
    def __init__(self):
        self.visible = False

    def setVisible(self, v):
        self.visible = bool(v)

    def setMaximum(self, _v):
        pass

    def setValue(self, _v):
        pass

    def setText(self, _v):
        pass


class _Stub:
    # 直接复用 MainWindow 的实现，避免构造真实主窗口（依赖配置/网络/UI）。
    _bind_status_worker = MainWindow._bind_status_worker
    _unbind_status_worker = MainWindow._unbind_status_worker
    _status_worker_alive = MainWindow._status_worker_alive
    _status_text = MainWindow._status_text
    _status_speed = MainWindow._status_speed
    _status_progress = MainWindow._status_progress

    def __init__(self):
        self._status_links = {}
        self._dl_workers = {}
        self._play_worker = None
        self._bar = _Bar()
        self._progress = _Widget()
        self._speed_lbl = _Widget()
        self.speeds = []
        self.progress_calls = []

    def statusBar(self):
        return self._bar

    def _set_speed(self, text):
        self.speeds.append(text)
        self._speed_lbl.setVisible(bool(text))

    def _set_progress(self, value, maximum):
        self.progress_calls.append((value, maximum))
        self._progress.setVisible(True)


print("== 状态栏信号归属 ==")

# ── 1. 行为：在册 worker 能写状态栏 ─────────────────────────────
s = _Stub()
w1 = _Worker()
s._dl_workers["inst-a"] = w1
s._bind_status_worker(w1)
w1.status.emit("下载中 A")
w1.speed.emit("1.2 MB/s")
w1.progress.emit(38, 113)
check("在册 worker 的 status/speed/progress 都能写状态栏",
      s._bar.msgs == ["下载中 A"] and s.speeds == ["1.2 MB/s"]
      and s.progress_calls == [(38, 113)],
      "msgs=%r" % s._bar.msgs[-1:])

# ── 2. 行为：出册（模拟取消/完成）后信号被丢弃 ───────────────────
s._dl_workers.pop("inst-a", None)
w1.status.emit("旧任务残留 A")
w1.speed.emit("9")
w1.progress.emit(9, 9)
check("出册 worker 的三路信号全部被丢弃（旧计数不再盖新值）",
      s._bar.msgs == ["下载中 A"] and len(s.speeds) == 1
      and len(s.progress_calls) == 1,
      "msgs=%r speeds=%r prog=%r" % (s._bar.msgs, s.speeds, s.progress_calls))

# ── 3. 行为：unbind 后旧 worker 彻底断连，新 worker 正常接管 ──────
s._unbind_status_worker(w1)
w2 = _Worker()
s._dl_workers["inst-b"] = w2
s._bind_status_worker(w2)
w1.status.emit("旧任务竞态 A")
w1.speed.emit("9")
w1.progress.emit(9, 9)
w2.status.emit("下载中 B")
w2.progress.emit(3058, 5146)
check("unbind 后旧 worker 彻底不抢状态栏，新 worker 独占",
      s._bar.msgs == ["下载中 A", "下载中 B"]
      and s.progress_calls[-1] == (3058, 5146)
      and w1 not in s._status_links,
      "msgs=%r" % s._bar.msgs)
check("unbind 后旧 worker 的连接记录已移除",
      w1 not in s._status_links and w2 in s._status_links)

# ── 4. 行为：最后一个任务终态 → 收起进度条/速度 ───────────────────
s._dl_workers.pop("inst-b", None)
s._unbind_status_worker(w2)
check("无在册任务时收起进度条、清空速度",
      not s._progress.visible and s.speeds[-1] == ""
      and not s._speed_lbl.visible,
      "progress_visible=%r last_speed=%r" % (s._progress.visible, s.speeds[-1]))

# ── 5. 行为：_play_worker 走独立归属判据 ─────────────────────────
s2 = _Stub()
pw = _Worker()
s2._play_worker = pw
s2._bind_status_worker(pw)
pw.status.emit("启动准备中")
check("启动 worker 不在 _dl_workers 里也能写状态栏",
      s2._bar.msgs == ["启动准备中"])
s2._play_worker = None
pw.status.emit("启动残留")
check("启动 worker 置空后残留信号被丢弃",
      s2._bar.msgs == ["启动准备中"])

# ── 6. 静态防再犯：不得回到直连 ──────────────────────────────────
mw = read("src/main_window.py")
check("不再直连 status → statusBar().showMessage",
      "status.connect(self.statusBar().showMessage)" not in mw
      and "self._play_worker.status.connect(self.statusBar().showMessage)" not in mw)
check("不再直连 speed → _set_speed",
      "speed.connect(self._set_speed)" not in mw)
check("不再直连 progress → _set_progress",
      "progress.connect(self._set_progress)" not in mw)
check("两路 worker 都调用 _bind_status_worker（理论值 2 处）",
      mw.count("self._bind_status_worker(") == 2,
      "count=%d" % mw.count("self._bind_status_worker("))

# ── 7. 静态防再犯：所有终态路径都 unbind ──────────────────────────
for label, anchor in (
    ("下载完成", "get_task_center().finish(tid, t(\"launch.download_ready\"))"),
    ("下载失败", "get_task_center().fail(tid, err or \"\")"),
    ("下载暂停", "self._dl_paused[inst_id] = True"),
    ("下载取消", "get_task_center().cancel(tid, t(\"launch.dl_cancelled\"))"),
    ("启动完成", "def _on_launch_done("),
    ("启动失败", "def _on_launch_error("),
    ("启动取消", "def _on_launch_cancelled("),
):
    idx = mw.find(anchor)
    check("终态路径含 unbind：%s" % label,
          idx >= 0 and "_unbind_status_worker" in mw[max(0, idx - 900):idx + 900],
          "anchor=%d" % idx)

check("错误注释（残留信号被丢弃）已修正",
      "残留 status/progress 信号因 worker 已移出表而被丢弃。" not in mw)

# ── 8. 失败对话框醒目终态 ────────────────────────────────────────
dlg = read("src/launch_dialog.py")
failed = dlg.split("def mark_failed")[1][:1400] if "def mark_failed" in dlg else ""
check("失败文案改用 danger 色 + 加粗",
      "COLORS['danger']" in failed and "font-weight: 600" in failed)
check("失败时清空速度数字并终止 indeterminate 进度条",
      "self.set_speed(\"\")" in failed and "self.bar.setMaximum(1)" in failed)

print("== %s ==" % ("PASS" if not fails else "FAIL %d" % len(fails)))
sys.exit(1 if fails else 0)
