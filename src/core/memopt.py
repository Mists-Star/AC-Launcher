"""启动前内存优化（round-188，对齐 PCL 的「启动游戏前进行内存优化」）。

PCL2 的设置页「内存分配」卡里有一项：**启动游戏前进行内存优化**（跟随全局 /
开启 / 关闭）。它做的事是：启动游戏之前把**启动器自己**占着的内存尽量还给
系统，让游戏能拿到更多物理内存（启动器自身往往已经吃掉几百 MB）。

这里的实现走 Windows API，两步：

1. ``EmptyWorkingSet(GetCurrentProcess())`` —— 把本进程的工作集裁到最小，
   物理内存立刻还给系统（这一步是本进程能自己做的，不需要管理员）；
2. ``GC.collect()`` —— Python 堆里的垃圾顺手回收掉。

**做不到**的：清空系统 standby list（需要 ``EmptyStandbyList``，要管理员权限，
而且会拖慢整机）。所以这里只做「自己那部分」，不假装能做全局的。

对外只暴露一个函数 :func:`optimize_memory`，返回释放的大致字节数（供 UI 报
一句「已释放 XX MB」）。
"""
from __future__ import annotations

import gc
import os


def _current_rss_bytes() -> int:
    """当前进程常驻内存（字节）。用 ctypes 读 ProcessMemoryCounters。"""
    import ctypes

    class _PMC(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    try:
        psapi = ctypes.WinDLL("psapi")
        kernel32 = ctypes.WinDLL("kernel32")
        counter = _PMC()
        counter.cb = ctypes.sizeof(_PMC)
        handle = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counter),
                                     ctypes.sizeof(_PMC)):
            return int(counter.WorkingSetSize)
    except Exception:  # noqa: BLE001 - 非 Windows / API 失败
        pass
    return 0


def optimize_memory() -> int:
    """启动游戏前回收启动器自己占的内存。返回**大约**释放的字节数。

    失败一律静默返回 0 —— 这是「锦上添花」的优化，绝不能因为它让启动失败。
    """
    before = _current_rss_bytes()
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        # EmptyWorkingSet 在 psapi；老系统上退回 SetProcessWorkingSetSize(-1,-1)
        try:
            psapi = ctypes.WinDLL("psapi")
            psapi.EmptyWorkingSet(kernel32.GetCurrentProcess())
        except Exception:  # noqa: BLE001
            try:
                kernel32.SetProcessWorkingSetSize(kernel32.GetCurrentProcess(),
                                                  ctypes.c_size_t(-1),
                                                  ctypes.c_size_t(-1))
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001 - 非 Windows
        pass
    try:
        gc.collect()
    except Exception:  # noqa: BLE001
        pass
    after = _current_rss_bytes()
    if before and after:
        return max(0, before - after)
    return 0


def should_optimize(inst, settings: dict) -> bool:
    """这个实例要不要做启动前内存优化。

    实例级 ``mem_optimize``：``"on"`` / ``"off"`` / ``""``（跟随全局）。
    """
    mode = (getattr(inst, "mem_optimize", "") or "").strip().lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    return bool((settings or {}).get("mem_optimize", False))
