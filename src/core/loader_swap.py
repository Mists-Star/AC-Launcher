"""加载器真装 / 真卸（round-183）。

在此之前「实例设置 → 加载器」只是**改字段**：旧加载器的版本 json 与库原样
留在 ``versions/`` 里，新加载器再叠一层。玩家点「换加载器」看到的不是换，
是叠。这个模块补上真正的装与卸：

* **装** —— 交给 :func:`core.install.install_instance`（幂等：只补缺的），
  成功后再清理不再被引用的旧加载器版本目录。
* **卸** —— 删掉实例自己 ``versions/<loader-id>/`` 目录，实例退回原版。

安全边界（宁可拒绝，不弄坏别人的东西）：

* 只删**实例自身 install_dir 下**的 ``versions``；路径越界一律不动。
* ``external`` 实例（链接到别的启动器的游戏目录）**拒绝卸载**——那是别人的
  版本目录，卸了对方就起不来。
* 版本目录名与基版 ``game_version`` 相同则不删（那是原版目录，不是加载器）。
* ``libraries/`` 是跨实例共享池，**永不删除**（PCL2 / HMCL 同样不删）。
"""
from __future__ import annotations

import os
import shutil

__all__ = [
    "current_loader_version_id", "install_dir_of", "loader_version_ids",
    "swap_loader", "uninstall_loader",
]


def install_dir_of(inst) -> str:
    """实例版本 json 所在根（与启动 / 补全同一口径）。"""
    try:
        from ..instances import layout_of
        return (layout_of(inst).get("install_dir") or inst.mc_dir or "")
    except Exception:  # noqa: BLE001 - 布局探测失败按 mc_dir 兜底
        return inst.mc_dir or ""


def _versions_root(inst) -> str:
    return os.path.join(install_dir_of(inst), "versions")


def _inside(path: str, root: str) -> bool:
    """path 是否在 root 之下（规范化后比较，挡 ``..`` 与不同盘符）。"""
    try:
        p = os.path.normcase(os.path.abspath(path))
        r = os.path.normcase(os.path.abspath(root))
        return os.path.commonpath([p, r]) == r and p != r
    except (ValueError, OSError):
        return False


def current_loader_version_id(inst) -> str | None:
    """当前实例实际使用的加载器版本目录名（vanilla / 没装 → None）。"""
    loader = (getattr(inst, "loader", "") or "vanilla").strip().lower()
    if loader in ("", "vanilla"):
        return None
    from .install import find_installed_loader
    try:
        return find_installed_loader(
            install_dir_of(inst), loader, getattr(inst, "game_version", "") or "")
    except Exception:  # noqa: BLE001 - 探测失败不阻断装/卸决策
        return None


def loader_version_ids(inst) -> list[str]:
    """``versions/`` 下所有属于「非原版」的版本目录名。

    判据：目录里有同名 json，且 json 的 ``inheritsFrom`` 指向某个基版
    （加载器版本的共同特征）——AC 自建的原版目录没有 ``inheritsFrom``。
    Cleanroom / NeoForge 这类 id 不含 MC 版本的也能认出来。
    """
    root = _versions_root(inst)
    if not os.path.isdir(root):
        return []
    base = (getattr(inst, "game_version", "") or "").strip()
    out: list[str] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    for name in names:
        if name.startswith("."):
            continue
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        jp = os.path.join(d, f"{name}.json")
        if not os.path.isfile(jp):
            continue
        if base and name == base:
            continue                    # 原版目录，永远保留
        try:
            import json
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if str(data.get("inheritsFrom") or "").strip():
            out.append(name)
    return out


def _remove_version_dir(inst, vid: str) -> tuple[bool, str]:
    """删除一个版本目录。返回 (是否删掉, 错误文本)。"""
    root = _versions_root(inst)
    target = os.path.join(root, vid)
    if not vid or not os.path.isdir(target):
        return False, ""
    if not _inside(target, root):
        return False, t_guard()
    try:
        shutil.rmtree(target)
        return True, ""
    except OSError as exc:
        return False, str(exc)


def t_guard() -> str:
    """越界删除的拒绝原因（走 i18n，保持文案统一）。"""
    try:
        from ..i18n import t
        return t("inst.loader_guard")
    except Exception:  # noqa: BLE001
        return "path guard"


def swap_loader(inst, loader: str, loader_version: str = "", *,
                callback=None) -> dict:
    """真装：切到目标加载器并把文件装好，再清理不再需要的旧版本目录。

    失败时**回滚**实例字段，不把实例留在「半个加载器」的状态。
    返回 ``{"version_id", "removed", "loader", "loader_version"}``；异常向上抛，
    由调用方（Worker）转成用户可读的错误。
    """
    old_loader = (getattr(inst, "loader", "") or "vanilla").strip().lower()
    old_ver = getattr(inst, "loader_version", "") or ""
    old_vid = current_loader_version_id(inst)

    target = (loader or "vanilla").strip().lower()
    from ..settings_dialog import load_config
    from .install import install_instance

    cfg = load_config() or {}
    inst.loader = target
    inst.loader_version = "" if target == "vanilla" else (loader_version or "").strip()
    inst.version_id = ""
    inst.needs_convert = False
    try:
        vid = install_instance(
            inst,
            java_auto=bool(cfg.get("java_auto", True)),
            java_path=cfg.get("java_path", "") or "",
            mirror=cfg.get("download_mirror", "official"),
            proxy=cfg.get("download_proxy", "") or "",
            callback=callback,
        )
    except Exception:
        inst.loader = old_loader
        inst.loader_version = old_ver
        inst.version_id = ""
        raise

    removed: list[str] = []
    # 旧加载器的版本目录若不再被使用，清掉才算「真换」而不是「叠一层」。
    if (old_loader not in ("", "vanilla") and old_vid and old_vid != vid
            and not getattr(inst, "external", False)):
        done, _err = _remove_version_dir(inst, old_vid)
        if done:
            removed.append(old_vid)

    return {"version_id": vid, "removed": removed,
            "loader": inst.loader, "loader_version": inst.loader_version or ""}


def uninstall_loader(inst) -> dict:
    """真卸：把实例退回原版（删除加载器版本目录）。不联网。

    返回 ``{"ok", "reason", "removed", "error"}``；``reason`` 取值：
    ``""`` 成功 / ``no_loader`` 本来就是原版 / ``external`` 外来实例拒绝动。
    """
    loader = (getattr(inst, "loader", "") or "vanilla").strip().lower()
    if loader in ("", "vanilla"):
        return {"ok": False, "reason": "no_loader", "removed": [], "error": ""}
    if getattr(inst, "external", False):
        return {"ok": False, "reason": "external", "removed": [], "error": ""}

    vid = current_loader_version_id(inst)
    removed: list[str] = []
    if vid:
        done, err = _remove_version_dir(inst, vid)
        if err:
            return {"ok": False, "reason": "busy", "removed": [], "error": err}
        if done:
            removed.append(vid)

    inst.loader = "vanilla"
    inst.loader_version = ""
    inst.version_id = ""
    inst.needs_convert = False
    return {"ok": True, "reason": "", "removed": removed, "error": ""}
