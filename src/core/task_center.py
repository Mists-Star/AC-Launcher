"""Task center（任务中心第一步）— Qt-free 统一任务记录 + 持久历史。

对齐 LumilioCL 的任务模型：下载 / 安装 / 修复 / 更新 / 导入 / 启动不再各管
各的，而是同一张 ``TaskRecord`` 表 + 一台状态机：

    queued → running → done | failed | cancelled

本轮只做**地基**：记录、状态转换、事件查询、完成后落盘（最近 N 条）。
不做任务页 UI、不做任务级重试/暂停（第二步）。

调用约定（全部在主线程调用；内部加锁，重复上报无害）：

    tc = get_task_center()
    task = tc.start("download", inst.name, target_page="instances")
    tc.update(task.id, stage="正在下载依赖库", completed=3, total=10)
    tc.finish(task.id, detail="完成")

存储：``<data_dir>/task_history.json`` → ``{"version": 1, "tasks": [...]}``。
只持久化**已结束**的任务；进行中的任务属于进程内状态，进程被杀即丢弃
（不把半截任务当成历史）。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

from ..paths import get_data_dir

STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

_FINAL_STATES = {STATE_DONE, STATE_FAILED, STATE_CANCELLED}
_OPEN_STATES = {STATE_QUEUED, STATE_RUNNING}

# 历史文件只留最近 N 条已结束任务。
_KEEP_HISTORY = 50

_MAX_LABEL = 80
_MAX_STAGE = 80
_MAX_DETAIL = 200
_MAX_SOURCES = 8


@dataclass
class TaskRecord:
    """一条任务记录（可序列化；状态转换只经 TaskCenter）。"""
    id: str
    kind: str                      # download / install / repair / update / import / launch
    label: str                     # 人读标题（实例名 / 文件名的简短描述）
    state: str = STATE_RUNNING
    stage: str = ""                # 当前阶段（人读）
    completed: int = 0
    total: int = 0                 # 0 = 未定长
    detail: str = ""               # 结束原因 / 备注
    sources: list[str] = field(default_factory=list)  # 来源链（round-155 填入）
    target_page: str = ""          # 完成后可跳转的页面 key
    created_at: float = 0.0
    updated_at: float = 0.0

    def ratio(self) -> float:
        """进度比例（0~1）；未定长返回 0。"""
        if not self.total or self.total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.completed / self.total))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskRecord | None":
        try:
            if not isinstance(data, dict) or not data.get("id"):
                return None
            sources = data.get("sources")
            return cls(
                id=str(data["id"]),
                kind=str(data.get("kind") or "task"),
                label=str(data.get("label") or ""),
                state=str(data.get("state") or STATE_DONE),
                stage=str(data.get("stage") or ""),
                completed=int(data.get("completed") or 0),
                total=int(data.get("total") or 0),
                detail=str(data.get("detail") or ""),
                sources=[str(s) for s in sources] if isinstance(sources, list) else [],
                target_page=str(data.get("target_page") or ""),
                created_at=float(data.get("created_at") or 0.0),
                updated_at=float(data.get("updated_at") or 0.0),
            )
        except (TypeError, ValueError):
            return None


class TaskCenter:
    """进程内任务表 + 完成后落盘。线程安全（可被后台线程直接调用）。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._tasks: dict[str, TaskRecord] = {}
        with self._lock:
            self._load_locked()

    # ---- lifecycle -------------------------------------------------- #
    def start(self, kind: str, label: str, *, target_page: str = "",
              stage: str = "", total: int = 0, detail: str = "",
              sources: list[str] | None = None) -> TaskRecord:
        """登记并启动一条任务；返回记录（调用方用 ``task.id`` 后续上报）。"""
        now = time.time()
        rec = TaskRecord(
            id=uuid.uuid4().hex[:12],
            kind=(kind or "task")[:32],
            label=(label or "")[:_MAX_LABEL],
            state=STATE_RUNNING,
            stage=(stage or "")[:_MAX_STAGE],
            completed=0,
            total=max(0, int(total or 0)),
            detail=(detail or "")[:_MAX_DETAIL],
            sources=self._clip_sources(sources),
            target_page=(target_page or "")[:32],
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._tasks[rec.id] = rec
        return rec

    def update(self, task_id: str, *, stage: str | None = None,
               completed: int | None = None, total: int | None = None,
               detail: str | None = None, state: str | None = None,
               sources: list[str] | None = None) -> TaskRecord | None:
        """更新进行中的任务；任务不存在 / 已结束则忽略（返回 None）。"""
        with self._lock:
            rec = self._tasks.get(task_id or "")
            if rec is None or rec.state in _FINAL_STATES:
                return None
            if stage is not None:
                rec.stage = str(stage)[:_MAX_STAGE]
            if completed is not None:
                rec.completed = max(0, int(completed))
            if total is not None:
                rec.total = max(0, int(total))
            if detail is not None:
                rec.detail = str(detail)[:_MAX_DETAIL]
            if sources is not None:
                rec.sources = self._clip_sources(sources)
            if state in _OPEN_STATES:
                rec.state = state
            rec.updated_at = time.time()
            return rec

    def finish(self, task_id: str, detail: str = "") -> TaskRecord | None:
        return self._close(task_id, STATE_DONE, detail)

    def fail(self, task_id: str, detail: str = "") -> TaskRecord | None:
        return self._close(task_id, STATE_FAILED, detail)

    def cancel(self, task_id: str, detail: str = "") -> TaskRecord | None:
        return self._close(task_id, STATE_CANCELLED, detail)

    def _close(self, task_id: str, state: str, detail: str) -> TaskRecord | None:
        with self._lock:
            rec = self._tasks.get(task_id or "")
            if rec is None or rec.state in _FINAL_STATES:
                return None
            rec.state = state
            if detail:
                rec.detail = str(detail)[:_MAX_DETAIL]
            now = time.time()
            rec.updated_at = now
            if rec.created_at <= 0:
                rec.created_at = now
            self._persist_locked()
            return rec

    # ---- queries ---------------------------------------------------- #
    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id or "")

    def running(self, kind: str | None = None) -> list[TaskRecord]:
        """进行中的任务（最新在前）。"""
        with self._lock:
            rows = [r for r in self._tasks.values()
                    if r.state in _OPEN_STATES and (not kind or r.kind == kind)]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)

    def recent(self, limit: int = 20) -> list[TaskRecord]:
        """已结束任务（最新在前），最多 ``limit`` 条。"""
        with self._lock:
            rows = [r for r in self._tasks.values() if r.state in _FINAL_STATES]
        return sorted(rows, key=lambda r: r.updated_at, reverse=True)[:max(0, limit)]

    def clear_history(self) -> None:
        """清空已结束任务（进行中的保留）。"""
        with self._lock:
            for tid in [r.id for r in self._tasks.values()
                        if r.state in _FINAL_STATES]:
                self._tasks.pop(tid, None)
            self._persist_locked()

    # ---- persistence ------------------------------------------------ #
    def _hist_path(self) -> str:
        return os.path.join(get_data_dir(), "task_history.json")

    def _load_locked(self) -> None:
        try:
            with open(self._hist_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        rows = data.get("tasks") if isinstance(data, dict) else None
        for item in rows if isinstance(rows, list) else []:
            rec = TaskRecord.from_dict(item)
            if rec is None:
                continue
            if rec.state not in _FINAL_STATES:
                rec.state = STATE_CANCELLED   # 历史里不该出现进行中
            self._tasks[rec.id] = rec
        # 超出上限的旧记录在加载时就裁掉
        finished = sorted((r for r in self._tasks.values()
                           if r.state in _FINAL_STATES),
                          key=lambda r: r.updated_at, reverse=True)
        for old in finished[_KEEP_HISTORY:]:
            self._tasks.pop(old.id, None)

    def _persist_locked(self) -> None:
        finished = sorted((r for r in self._tasks.values()
                           if r.state in _FINAL_STATES),
                          key=lambda r: r.updated_at, reverse=True)
        finished = finished[:_KEEP_HISTORY]
        path = self._hist_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "tasks": [r.to_dict() for r in finished]},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError:
            try:
                if os.path.exists(path + ".tmp"):
                    os.remove(path + ".tmp")
            except OSError:
                pass

    @staticmethod
    def _clip_sources(sources: list[str] | None) -> list[str]:
        if not sources:
            return []
        return [str(s)[:_MAX_DETAIL] for s in list(sources)[:_MAX_SOURCES]]


_CENTER: TaskCenter | None = None


def get_task_center() -> TaskCenter:
    """进程内单例（首次调用时读历史）。"""
    global _CENTER
    if _CENTER is None:
        _CENTER = TaskCenter()
    return _CENTER


def _reset_for_tests() -> None:
    """丢弃单例（测试用；下一次 get_task_center() 会重新读盘）。"""
    global _CENTER
    _CENTER = None
