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
import time

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
    rc = 0
    try:
        done = subprocess.run(args, capture_output=True, timeout=timeout)
        rc = done.returncode
        if rc != 0:
            raw = (done.stderr or done.stdout or b"")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            errors.append(str(raw).strip() or "taskkill exit=%s" % rc)
    except Exception as e:  # noqa: BLE001 - 超时 / 无权限都要回报给 UI
        errors.append(str(e))

    # round-217：taskkill 只要有一个 PID 报错（已退出 / 无权限 / PID 被复用）
    # 整体 returncode 就是非 0。原实现据此把**整批**都算失败，UI 于是显示
    # 「3 个都没关掉」，而实际只挂了 1 个。这里改为逐个复核存活状态——
    # 进程对象是我们自己 Popen 出来的，poll() 判据最准。
    failed = []
    deadline = time.monotonic() + 1.0
    pending = list(alive)
    while True:
        failed = []
        for proc in pending:
            try:
                if proc.poll() is None:
                    failed.append(proc)
            except Exception:  # noqa: BLE001 - 句柄坏了按「没关掉」处理
                failed.append(proc)
        if not failed or time.monotonic() >= deadline:
            break
        pending = failed
        time.sleep(0.05)      # 给 terminated 的进程一点回收时间
    failed_pids = [getattr(p, "pid", "?") for p in failed]
    if failed_pids and rc == 0:
        errors.append("taskkill exit=0 但仍有进程存活：%s" % failed_pids)
    return {"attempted": len(alive), "failed": failed_pids, "errors": errors}
