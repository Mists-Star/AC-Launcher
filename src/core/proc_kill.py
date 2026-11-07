"""round-206：结束游戏进程的统一入口（批量 / 有反馈 / 不吞异常）。

旧实现在 UI 主线程里对每个存活进程**串行** ``taskkill(timeout=10)``：
多开 N 个最坏阻塞 10N 秒，整段 ``except Exception: pass`` 又把失败全吞，
玩家看到的就是「点了结束游戏没反应」。

现在 Windows 用**一条** taskkill 带上全部 ``/PID``（单次外部命令，
超时压到 3s），结果结构化返回给 UI；非 Windows 走 ``Popen.kill()``
（本来就不起子进程，不存在串行阻塞）。
"""
from __future__ import annotations

import subprocess
import sys

WINDOWS_KILL_TIMEOUT = 3.0


def build_taskkill_args(pids) -> list[str]:
    """把多个 PID 拼成**一条** taskkill 命令；没有有效 PID 时返回 []。"""
    cleaned = []
    for pid in pids:
        try:
            value = int(pid)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in cleaned:
            cleaned.append(value)
    if not cleaned:
        return []
    args = ["taskkill", "/F", "/T"]
    for pid in cleaned:
        args.extend(("/PID", str(pid)))
    return args


def terminate_all(procs, timeout: float = WINDOWS_KILL_TIMEOUT) -> dict:
    """批量结束游戏进程；永不向 UI 抛异常，但**不吞掉**错误（放进 errors）。

    返回 ``{"attempted": int, "failed": [pid...], "errors": [str...]}``。
    ``procs`` 里的元素只需提供 ``poll()`` / ``pid``，非 Windows 还需 ``kill()``。
    """
    alive: list = []
    errors: list[str] = []
    for proc in procs:
        try:
            if proc.poll() is None:
                alive.append(proc)
        except Exception as e:  # noqa: BLE001 - 单个进程状态坏了不影响其余
            errors.append("poll: %s" % e)
    if not alive:
        return {"attempted": 0, "failed": [], "errors": errors}

    pids = [getattr(proc, "pid", 0) for proc in alive]
    if sys.platform != "win32":
        failed = []
        for proc in alive:
            try:
                proc.kill()
            except Exception as e:  # noqa: BLE001
                failed.append(getattr(proc, "pid", "?"))
                errors.append(str(e))
        return {"attempted": len(alive), "failed": failed, "errors": errors}

    args = build_taskkill_args(pids)
    if not args:
        return {"attempted": len(alive), "failed": pids,
                "errors": errors + ["no valid pid"]}
    try:
        done = subprocess.run(args, capture_output=True, timeout=timeout)
        if done.returncode != 0:
            raw = (done.stderr or done.stdout or b"")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            errors.append(str(raw).strip() or "taskkill exit=%s" % done.returncode)
            return {"attempted": len(alive), "failed": pids, "errors": errors}
    except Exception as e:  # noqa: BLE001 - 超时 / 无权限都要回报给 UI
        errors.append(str(e))
        return {"attempted": len(alive), "failed": pids, "errors": errors}
    return {"attempted": len(alive), "failed": [], "errors": errors}
