"""打开本地目录/文件 —— 全项目唯一实现（round-223）。

此前同一个「打开目录」按钮有 4 套写法，行为各不同：

* ``instance_editor._open_path``：``makedirs`` 后 ``startfile``，失败静默；
* ``pages_instances._open_folder``：**只在目录已存在时** ``QDesktopServices``，
  不存在就什么都不做 —— 玩家点了按钮毫无反应，最容易被当成「按钮坏了」；
* ``pages_instances._open_saves``：先 makedirs 再开，但失败也静默；
* ``mod_list._open_folder``：``startfile`` + warn，另有一条委托分支。

现在统一走这里：目录不存在 / 系统拒绝打开都会**明确提示**，不再静默吞掉。
``create=True`` 用于「存档 / mods 这类一定该存在的目录」，先建再开。
"""
import os
import subprocess

from .i18n import t


def open_local_path(parent, path: str, *, create: bool = False) -> bool:
    """打开目录（或文件）。返回是否真的交给了系统。

    :param parent: 提示框的父窗口
    :param path:   目标路径；空值直接返回 False（不弹框，历史调用里空值是常态）
    :param create: True 时先 ``makedirs``（存档/mods 等「应当存在」的目录）
    """
    if not path:
        return False
    target = os.path.normpath(str(path))
    if create:
        try:
            os.makedirs(target, exist_ok=True)
        except OSError:
            pass  # 建不出来就按「不存在」处理，下面统一提示
    if not os.path.exists(target):
        _notify(parent, t("common.open_missing", path=target))
        return False
    try:
        if os.name == "nt":
            os.startfile(target)  # noqa: S606 - 本地路径，无外部输入
        else:
            subprocess.Popen(["xdg-open", target])
        return True
    except Exception as exc:  # noqa: BLE001 - 系统拒绝 startfile 时常见
        _notify(parent, t("common.open_failed", e=exc))
        return False


def _notify(parent, message: str) -> None:
    """提示框本身失败（无 GUI / 父窗口已销毁）不许再抛。"""
    try:
        from .win_rounded import warn

        warn(parent, t("inst.open_folder"), message)
    except Exception:  # noqa: BLE001
        pass
