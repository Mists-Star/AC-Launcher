"""BatchDownloader — 批量下载编排（round-73，对标 MCLauncher 20-worker 队列）。

解决单文件下载之外的"整批编排"缺口：整合包有几十个文件时，此前逐个顺序
下载、一个失败整个中断。本模块提供：

  - 并发：`workers` 个 daemon 线程消费任务队列（默认 4，可调）
  - 失败继续：单任务失败记入 failed，继续跑后面的任务（不再中断整批）
  - 进度 / 取消：线程安全回调 + cancel()，任务间安全退出
  - 存在即跳过 + sha1 复核：``make_download_task`` 会先按目标大小/期望
    sha1 校验已存在文件（skipped 视为成功），下载后再复核 sha1

纯 Python + threading，不依赖 Qt——UI 侧在 QThread.Worker 里跑，回调由
调用方转成信号（线程安全由本模块内部锁保证）。

用法::

    b = BatchDownloader([
        ("mod1.jar", make_download_task(url1, dest1, sha1=...)),
        ("mod2.jar", lambda: net_api.download_file(url2, dest2)),
    ], workers=4, on_progress=lambda done, total: ..., on_finish=...)
    b.start()
"""
from __future__ import annotations

import hashlib
import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .net_api import download_file


@dataclass
class BatchItem:
    name: str                          # 展示名（日志/进度）
    task: Callable[[], None]           # 执行体（由调用方包好 url/校验/异常处理）
    ok: bool = False                   # 最终结果（已存在跳过也视为成功）
    detail: str = ""                   # 失败/取消时的人类可读说明
    cancelled: bool = False


def _sha1_of(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def make_download_task(url: str, dest: str, sha1: str = "", size: int = 0,
                       headers: dict | None = None) -> Callable[[], None]:
    """包成一个可被 BatchDownloader 消费的任务闭包。

    已存在且（size 匹配或 sha1 匹配）→ 跳过不下载；否则走 download_file
    （自带断点续传/退避重试/原子落盘），下载后再复核 sha1（给定的话）。
    失败以异常形式抛出（BatchDownloader 捕获记录到 failed 并继续）。
    """
    def _run() -> None:
        if os.path.isfile(dest):
            if size and os.path.getsize(dest) == size:
                return
            if sha1 and _sha1_of(dest) == sha1:
                return
        download_file(url, dest, headers=headers, resume=True)
        if sha1 and _sha1_of(dest) != sha1:
            raise RuntimeError(f"sha1 校验失败: {dest}")
    return _run


class BatchDownloader(threading.Thread):
    """线程池消费任务队列；单个任务失败不影响整批。"""

    def __init__(self, items: list[BatchItem], workers: int = 4, *,
                 on_progress: Callable[[int, int], None] | None = None,
                 on_finish: Callable[[list[BatchItem]], None] | None = None):
        super().__init__(daemon=True, name="AC-BatchDownloader")
        if workers < 1:
            workers = 4
        self._workers = min(workers, 16)         # round-110：上限 8→16，大包并行度更高
        self._queue: queue.Queue[BatchItem | None] = queue.Queue()
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._done = 0
        self._total = len(items)
        self._on_progress = on_progress
        self._on_finish = on_finish
        self.result: list[BatchItem] = items     # 结果写入 items[].ok（引用共享）

    # ── 线程入口 ──
    def run(self) -> None:
        for it in self.result:
            self._queue.put(it)
        for _ in range(self._workers):
            self._queue.put(None)                # 哨兵

        pool = [threading.Thread(target=self._worker,
                                 name=f"AC-Batch-{i}", daemon=True)
                for i in range(self._workers)]
        for th in pool:
            th.start()
        for th in pool:
            th.join()

        if self._on_finish is not None:
            try:
                self._on_finish(self.result)
            except Exception:
                pass

    def _worker(self) -> None:
        while True:
            it = self._queue.get()
            if it is None:
                self._queue.task_done()
                return
            try:
                if self._cancel.is_set():
                    it.cancelled = True
                    it.detail = "cancelled"
                else:
                    it.task()
                    it.ok = True
            except Exception as e:               # noqa: BLE001 - 单个文件失败继续
                it.ok = False
                it.detail = str(e)
            finally:
                with self._lock:
                    self._done += 1
                    if self._on_progress is not None:
                        try:
                            self._on_progress(self._done, self._total)
                        except Exception:
                            pass
                self._queue.task_done()

    # ── 对外 ──
    def cancel(self) -> None:
        """请求取消：已排队未开始的任务在取到时置 cancelled，不再执行。"""
        self._cancel.set()