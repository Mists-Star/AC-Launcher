"""Background workers: fire-and-forget (Worker) + progress-reporting (ProgressWorker).

ProgressWorker bridges minecraft-launcher-lib's callback dict
({"setStatus", "setProgress", "setMax"}) to Qt signals so the UI can show a
live progress bar during install / repair / launch.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

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

    def _mll_callback(self) -> dict:
        holder = self

        def set_status(s: str) -> None:
            holder.status.emit(s)

        def set_progress(v: int) -> None:
            holder.progress.emit(v, holder._max)

        def set_max(m: int) -> None:
            holder._max = m
            holder.progress.emit(0, m)

        def set_step(key: str) -> None:
            holder.step.emit(key)

        return {"setStatus": set_status, "setProgress": set_progress,
                "setMax": set_max, "setStep": set_step}

    def run(self) -> None:
        _register(self)
        kwargs = dict(self._kwargs)
        kwargs["callback"] = self._mll_callback()
        try:
            result = self._fn(*self._args, **kwargs)
            if not self.isInterruptionRequested():
                self.finished.emit(result)
        except Exception as e:  # noqa: BLE001 - surface to UI
            if not self.isInterruptionRequested():
                self.error.emit(str(e))
        finally:
            _unregister(self)
