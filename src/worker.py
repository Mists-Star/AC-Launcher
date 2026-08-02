"""Background workers: fire-and-forget (Worker) + progress-reporting (ProgressWorker).

ProgressWorker bridges minecraft-launcher-lib's callback dict
({"setStatus", "setProgress", "setMax"}) to Qt signals so the UI can show a
live progress bar during install / repair / launch.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:  # noqa: BLE001 - surface to UI
            self.error.emit(str(e))


class ProgressWorker(QThread):
    """Runs a blocking fn that reports progress via an mll callback dict.

    ``fn`` must accept ``callback`` as a keyword (the mll dict) plus any extra
    positional/keyword args passed to ``__init__``.
    """

    status = Signal(str)
    progress = Signal(int, int)  # value, max  (-1 = unknown)
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

        return {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}

    def run(self) -> None:
        kwargs = dict(self._kwargs)
        kwargs["callback"] = self._mll_callback()
        try:
            result = self._fn(*self._args, **kwargs)
            self.finished.emit(result)
        except Exception as e:  # noqa: BLE001 - surface to UI
            self.error.emit(str(e))
