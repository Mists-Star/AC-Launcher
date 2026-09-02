"""下载队列（round-37 轴心2）：并发受限 + 断点续传任务管理。

- DownloadTask：url → dest（走 net_api.download_file 的 HTTP Range 续传）
- DownloadQueue：N 个消费线程从队列取任务，并发上限可配（默认 3）
- 线程注册到 worker._LIVE，关窗安全；队列空闲自动销毁空线程

用法：
    from src.downloader import DownloadQueue, DownloadTask
    q = DownloadQueue(max_concurrent=3)
    q.finished.connect(on_done)   # Signal(task, dest)
    q.failed.connect(on_error)    # Signal(task, error)
    q.enqueue(DownloadTask(url, dest, name="mod.jar"))
    q.start()
"""
from __future__ import annotations

import queue as _queue

from PySide6.QtCore import QObject, QThread, Signal

from .worker import _register, _unregister


class DownloadTask:
    """单个下载任务。progress(sofar, total) 在主线程回调（经信号转发）。

    ``cancelled`` 由 DownloadQueue.shutdown 置位——下载中的任务在 chunk 边界
    安全中断（.part 保留，下次断点续传）。
    """

    def __init__(self, url: str, dest: str, name: str = "",
                 progress=None, headers: dict | None = None):
        self.url = url
        self.dest = dest
        self.name = name or dest.split("/")[-1]
        self.progress = progress
        self.headers = headers or {}
        self.cancelled = False


class _QueueWorker(QThread):
    """消费队列的线程：取任务 → download_file → 发信号。"""

    finished_one = Signal(object, str)   # task, dest
    failed_one = Signal(object, str)     # task, error
    progressed = Signal(object, int, int)  # task, sofar, total

    def __init__(self, q: _queue.Queue):
        super().__init__()
        self._q = q

    def run(self) -> None:
        _register(self)
        try:
            from .net_api import download_file
            while True:
                task = self._q.get()
                if task is None:  # 关闭信号
                    self._q.task_done()
                    break
                try:
                    def _prog(sofar: int, total: int, _t=task):
                        self.progressed.emit(_t, sofar, total)

                    dest = download_file(
                        task.url, task.dest,
                        headers=task.headers or None,
                        progress=_prog if task.progress else None,
                        cancel=lambda t=task: t.cancelled,  # round-40 P2-10
                    )
                    if not task.cancelled:
                        self.finished_one.emit(task, dest)
                except Exception as e:  # noqa: BLE001 - 单个任务失败不影响队列
                    if not task.cancelled:
                        self.failed_one.emit(task, str(e))
                finally:
                    self._q.task_done()
        finally:
            _unregister(self)


class DownloadQueue(QObject):
    """并发受限的下载队列。start() 后 enqueue 即可，线程池常驻。"""

    finished = Signal(object, str)   # task, dest
    failed = Signal(object, str)     # task, error
    progressed = Signal(object, int, int)  # task, sofar, total

    def __init__(self, max_concurrent: int = 3, parent=None):
        super().__init__(parent)
        self._q: _queue.Queue = _queue.Queue()
        self._max = max(1, max_concurrent)
        self._workers: list[_QueueWorker] = []
        self._started = False
        self._closed = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for _ in range(self._max):
            w = _QueueWorker(self._q)
            w.finished_one.connect(self.finished)
            w.failed_one.connect(self.failed)
            w.progressed.connect(self.progressed)
            self._workers.append(w)
            w.start()

    def enqueue(self, task: DownloadTask) -> None:
        if self._closed:
            raise RuntimeError("DownloadQueue 已关闭")
        self.start()
        self._q.put(task)

    def active_count(self) -> int:
        return sum(1 for w in self._workers if w.isRunning())

    def shutdown(self, wait_ms: int = 4000) -> None:
        """置位取消 → 投递 None 终止信号 → join 所有消费线程（幂等）。

        round-40 P2-10：先标记在途任务 cancelled（下载在 chunk 边界安全中断，
        .part 保留下次续传），再 join——不再等大文件自然下载完。
        """
        if self._closed:
            return
        self._closed = True
        # 标记队列中 + 在途任务取消
        with self._q.mutex:
            for task in list(self._q.queue):
                task.cancelled = True
        for w in self._workers:
            w.requestInterruption()
        for _ in self._workers:
            self._q.put(None)
        for w in self._workers:
            w.wait(wait_ms)


# 默认全局队列（资源中心等模块共享；关窗时由 main.py drain_workers 兜底，
# 队列自身的 shutdown 挂在 app.aboutToQuit）。
_DEFAULT_QUEUE: DownloadQueue | None = None


def default_queue() -> DownloadQueue:
    global _DEFAULT_QUEUE
    if _DEFAULT_QUEUE is None:
        _DEFAULT_QUEUE = DownloadQueue(max_concurrent=3)
        _DEFAULT_QUEUE.start()
    return _DEFAULT_QUEUE


def enqueue(url: str, dest: str, name: str = "", progress=None,
            headers: dict | None = None) -> DownloadTask:
    """快捷入队。返回 task（可用来连 finished/failed 信号）。"""
    task = DownloadTask(url, dest, name=name, progress=progress, headers=headers)
    default_queue().enqueue(task)
    return task
