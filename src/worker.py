"""Background workers: fire-and-forget (Worker) + progress-reporting (ProgressWorker).

ProgressWorker bridges minecraft-launcher-lib's callback dict
({"setStatus", "setProgress", "setMax"}) to Qt signals so the UI can show a
live progress bar during install / repair / launch.

round-109：mll 的裸状态串（``"Download 4ab9e7d1…"``，对资源文件就是一条 sha1）
对用户毫无意义，也分不清「慢」和「挂死」。这里在回调包装层做 PCL 式格式化：

* 阶段名 —— 依赖库 / 资源文件 / Java 运行时，取自 mll 在每段下载前发出的状态；
* 计数 —— 复用 mll 已经在推的 ``setMax`` / ``setProgress``（如 12/89）；
* 文件名 —— 库文件名保留，40 位 sha1 一律折叠掉（阶段名已说明是资源文件）；
* 停滞检测 —— 超过 ``_STALL_SECONDS`` 无任何回调就提示「网络较慢，仍在等待」，
  让「卡住」对用户可见，而不是让进度条假装在动。
"""
from __future__ import annotations

import re
import threading

from PySide6.QtCore import QThread, Signal

from .i18n import t

# ── live worker registry ─────────────────────────────────────────────────────
# Every started Worker/ProgressWorker registers here and unregisters when its
# run() finishes. main.py calls drain_workers() on aboutToQuit so no QThread is
# ever destroyed while still running at interpreter shutdown — that used to
# raise "QThread destroyed while still running" → heap corruption (0xc0000374)
# when the user closed the launcher with a fetch in flight.
_LIVE: set[QThread] = set()
_LOCK = threading.Lock()


def drain_workers(timeout_ms: int = 4000) -> None:
    """Best-effort: interrupt and join every live worker. Safe to call on quit."""
    import time

    with _LOCK:
        items = list(_LIVE)
    for w in items:
        w.requestInterruption()
    deadline = time.time() + timeout_ms / 1000.0
    for w in items:
        remaining = max(0.0, deadline - time.time())
        if remaining > 0:
            w.wait(int(remaining * 1000))
        if w.isRunning():
            w.wait(500)  # final short grace before the interpreter tears down


def _register(w: QThread) -> None:
    with _LOCK:
        _LIVE.add(w)


def _unregister(w: QThread) -> None:
    with _LOCK:
        _LIVE.discard(w)


class Worker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        _register(self)
        try:
            result = self._fn(*self._args, **self._kwargs)
            if not self.isInterruptionRequested():
                self.finished.emit(result)
        except Exception as e:  # noqa: BLE001 - surface to UI
            if not self.isInterruptionRequested():
                self.error.emit(str(e))
        finally:
            _unregister(self)


# 无任何回调超过 _STALL_SECONDS 秒 → 提示用户「网络较慢，仍在等待」。
_STALL_SECONDS = 45
# mll 以 "Download <name>" 报文件名；纯 40 位十六进制的是内容哈希，对用户无意义，
# 折叠掉只留阶段与计数。
_SHA1_NAME = re.compile(r"^[0-9a-fA-F]{40}$")
# mll 的阶段状态串 → 我们的 i18n 键。
_PHASE_KEYS = {
    "Download Libraries": "dl.phase.libraries",
    "Download Assets": "dl.phase.assets",
    "Install java runtime": "dl.phase.runtime",
}
_COMPLETE_STATUS = "Installation complete"


class _DlStatus:
    """把 mll 的裸状态串翻译成「阶段 + 计数 + 文件名」的可读文案。"""

    def __init__(self) -> None:
        self._phase_key = ""
        self._phase = ""
        self._total = 0
        self._done = 0
        self._file = ""

    def on_status(self, raw: str) -> str:
        if raw in _PHASE_KEYS:
            self._phase_key = raw
            self._phase = t(_PHASE_KEYS[raw])
            self._total = 0
            self._done = 0
            self._file = ""
            return self._phase
        if raw == _COMPLETE_STATUS:
            self._phase_key = _COMPLETE_STATUS
            self._phase = t("dl.complete")
            self._file = ""
            self._total = 0
            return self._phase
        if raw.startswith("Download "):
            name = raw[len("Download "):].strip()
            self._file = "" if _SHA1_NAME.match(name) else name
            return self.line() or raw
        return raw

    def on_max(self, maximum: int) -> None:
        self._total = maximum

    def on_progress(self, value: int) -> None:
        self._done = value

    def line(self) -> str:
        """当前阶段 + 计数 + 文件名；阶段未知时返回空串（调用方透传原始串）。"""
        if not self._phase:
            return ""
        if self._phase_key == _COMPLETE_STATUS or not self._total:
            text = self._phase
        else:
            text = t("dl.downloading", phase=self._phase,
                     done=self._done, total=self._total)
        return f"{text} · {self._file}" if self._file else text


class ProgressWorker(QThread):
    """Runs a blocking fn that reports progress via an mll callback dict.

    ``fn`` must accept ``callback`` as a keyword (the mll dict) plus any extra
    positional/keyword args passed to ``__init__``.
    """

    status = Signal(str)
    progress = Signal(int, int)  # value, max  (-1 = unknown)
    step = Signal(str)           # launch-stage key (check/install/...)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._max = 0
        self._ctx = None
        self._stall = None
        self._stall_lock = threading.Lock()

    def abort(self) -> None:
        """取消本次安装：在途下载立即抛错退出（线程不再写盘）。"""
        ctx = self._ctx
        if ctx is not None:
            ctx.abort()

    def _arm_stall(self) -> None:
        """每次收到 mll 回调都重新计时；静默超时则提示用户。"""
        with self._stall_lock:
            if self._stall is not None:
                self._stall.cancel()
            timer = threading.Timer(_STALL_SECONDS, self._on_stall)
            timer.daemon = True
            self._stall = timer
            timer.start()

    def _disarm_stall(self) -> None:
        with self._stall_lock:
            if self._stall is not None:
                self._stall.cancel()
                self._stall = None

    def _on_stall(self) -> None:
        if not self.isInterruptionRequested():
            self.status.emit(t("status.download_stalled"))

    def _mll_callback(self) -> dict:
        holder = self
        dl = _DlStatus()

        def set_status(s: str) -> None:
            holder.status.emit(dl.on_status(s))
            holder._arm_stall()

        def set_progress(v: int) -> None:
            dl.on_progress(v)
            holder.progress.emit(v, holder._max)
            line = dl.line()
            if line:
                holder.status.emit(line)
            holder._arm_stall()

        def set_max(m: int) -> None:
            dl.on_max(m)
            holder._max = m
            holder.progress.emit(0, m)
            line = dl.line()
            if line:
                holder.status.emit(line)
            holder._arm_stall()

        def set_step(key: str) -> None:
            holder.step.emit(key)

        return {"setStatus": set_status, "setProgress": set_progress,
                "setMax": set_max, "setStep": set_step}

    def run(self) -> None:
        _register(self)
        kwargs = dict(self._kwargs)
        kwargs["callback"] = self._mll_callback()
        try:
            from .core.mirror import install_scope
            with install_scope() as ctx:
                self._ctx = ctx
                result = self._fn(*self._args, **kwargs)
            if not self.isInterruptionRequested():
                self.finished.emit(result)
        except Exception as e:  # noqa: BLE001 - surface to UI
            if not self.isInterruptionRequested():
                self.error.emit(str(e))
        finally:
            self._ctx = None
            self._disarm_stall()
            _unregister(self)
