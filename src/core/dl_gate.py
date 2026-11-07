"""Download gate — 进程级「同一资源只允许一个下载」闸门（round-203）。

启动器有多条下载入口，它们各自开 worker、互不知情：

* 启动前补全（``launch.py`` → ``install_instance``）
* 实例页「补全文件」按钮（``_start_instance_download`` → ``install_instance``）
* 商店详情页「下载」（本体 + 依赖树）
* 整合包应用 / mod 更新 / Java 下载

两条 install 同时指向同一个实例时，会重复下载同一批文件、互相覆盖
``.part``，表现为「怎么总有好几个下载在占带宽」。本模块只做闸门，不接管
下载执行：调用方先 ``claim``，拿不到就别开跑（或 ``wait_free`` 等前一个结束）。

key 约定（全部经 :func:`_norm` 规范化，大小写 / 尾斜杠不敏感）：

* ``inst:<mc_dir>`` — 一次实例安装（补全 / 修复 / 启动前补）
* ``file:<abs path>`` — 单个文件落盘
* ``store:<project>:<version>`` — 商店详情页一次下载（含依赖）

线程安全；只记进程内状态，进程退出即清零（不需要持久化，「谁在下载」本身
就是进程内事实）。
"""
from __future__ import annotations

import os
import threading
import time

_ACTIVE: set[str] = set()
_LOCK = threading.Lock()


def _norm(key: str) -> str:
    """统一 key：去空白、转小写、去掉 Windows 尾分隔符。"""
    text = str(key or "").strip().lower()
    if text and text.endswith(("/", "\\")):
        text = text.rstrip("/\\")
    return text


def inst_key(mc_dir: str) -> str:
    """实例安装键：同一目录即同一资源（不区分布局）。"""
    try:
        path = os.path.normpath(os.path.abspath(str(mc_dir or "")))
    except (OSError, ValueError):
        path = str(mc_dir or "")
    return "inst:" + path


def file_key(path: str) -> str:
    """单文件落盘键。"""
    try:
        path = os.path.normpath(os.path.abspath(str(path or "")))
    except (OSError, ValueError):
        path = str(path or "")
    return "file:" + path


def claim(key: str) -> bool:
    """尝试占用 ``key``。成功 True；已在跑 False（调用方不要重复开下载）。"""
    k = _norm(key)
    if not k:
        return True
    with _LOCK:
        if k in _ACTIVE:
            return False
        _ACTIVE.add(k)
        return True


def release(key: str) -> None:
    """释放占用（重复释放无害）。"""
    k = _norm(key)
    if not k:
        return
    with _LOCK:
        _ACTIVE.discard(k)


def is_active(key: str) -> bool:
    with _LOCK:
        return _norm(key) in _ACTIVE


def active_keys() -> list[str]:
    """当前被占用的键（诊断 / 提示用，最新顺序无保证）。"""
    with _LOCK:
        return sorted(_ACTIVE)


def wait_free(key: str, timeout: float = 0.0, poll: float = 0.5,
              should_abort=None) -> bool:
    """等 ``key`` 被释放后占用它。

    ``timeout`` 秒内没等到 → 返回 False（不占用）。``should_abort`` 是可选
    回调，返回 True 时立即放弃等待（用于「取消启动」这类协作式取消）。
    等待期间每秒最多检查 ``1/poll`` 次，CPU 开销可忽略。
    """
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        if claim(key):
            return True
        if should_abort is not None:
            try:
                if should_abort():
                    return False
            except Exception:  # noqa: BLE001 - 取消判定失败就继续等
                pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(max(0.05, min(float(poll), 1.0)))


def reset_for_tests() -> None:
    """清空闸门（测试用；不要在产品路径调用）。"""
    with _LOCK:
        _ACTIVE.clear()
