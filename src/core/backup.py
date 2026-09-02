"""Instance backup & rollback — 对齐 Prism「一键备份 / 更新坏了一键回滚」。

快照存到 ``data/backups/<instance_id>/<snapshot_id>/``（portable，与启动器并列）。

每个快照：
  backups/<id>/<snapshot>/
    minecraft/        # 该实例 .minecraft 的完整副本，唯一跳过 libraries
    manifest.json     # 实例元数据 + 快照时间

为什么跳过 ``libraries``：round-48 起 AC 自有实例的 ``<mc_dir>/libraries`` 是
指向全局共享池的**目录联接**。备份时克隆它会把整个去重池复制一遍（既占盘又
没意义）；回滚时顺着联接还会覆盖共享池。所以存取都跳过，回滚后由
``Instance.ensure_dirs()`` 重建联接即可。

回滚 = 摘掉 libraries 联接 → 清空当前 mc_dir → 用快照内容覆盖 → 重建联接。
"""
from __future__ import annotations

import json
import os
import shutil
import time

from ..paths import get_data_dir

# mc_dir 里既不属于用户内容、又可能是共享池联接的目录 → 备份/回滚时跳过。
# versions/ 保留（游戏本体，回滚后离线也能直接启动）。
_SKIP_DIRS = ("libraries",)


def backups_root(inst) -> str:
    """快照根目录 ``data/backups/<instance_id>``。"""
    return os.path.join(get_data_dir(), "backups", inst.id)


def snapshot_dir(inst, snapshot_id: str) -> str:
    return os.path.join(backups_root(inst), snapshot_id)


def _snapshot_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _walk_files(src: str) -> list[tuple[str, str]]:
    """列 ``src`` 下所有文件 ``(abs, rel_to_src)``，跳过 _SKIP_DIRS。"""
    files: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            ap = os.path.join(dirpath, fn)
            files.append((ap, os.path.relpath(ap, src)))
    return files


def _write_manifest(inst, dst_root: str, snapshot_id: str) -> None:
    manifest = {
        "instance_id": inst.id,
        "instance_name": inst.name,
        "game_version": inst.game_version,
        "loader": inst.loader,
        "loader_version": inst.loader_version,
        "version_id": inst.version_id,
        "kind": inst.kind,
        "needs_convert": inst.needs_convert,
        "java_path": inst.java_path,
        "ram_mb": inst.ram_mb,
        "jvm_args": inst.jvm_args,
        "group": inst.group,
        "created_at": inst.created_at,
        "snapshot_id": snapshot_id,
        # ISO 8601(本地时间)，用于列表展示，比私有编号可读。
        "snapshot_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(dst_root, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def create_backup(inst) -> str:
    """为实例创建一份完整快照，返回快照目录。同名秒内重复会加后缀避免覆盖。"""
    snapshot_id = _snapshot_id()
    n = 0
    while os.path.exists(snapshot_dir(inst, snapshot_id)):
        n += 1
        snapshot_id = f"{_snapshot_id()}_{n}"
    dst_root = snapshot_dir(inst, snapshot_id)
    mc = os.path.join(dst_root, "minecraft")
    os.makedirs(mc, exist_ok=True)

    src = inst.mc_dir
    if os.path.isdir(src):
        for abs_src, rel in _walk_files(src):
            out = os.path.join(mc, os.path.dirname(rel)) if os.path.dirname(rel) else mc
            os.makedirs(out, exist_ok=True)
            shutil.copy2(abs_src, os.path.join(out, os.path.basename(rel)))

    _write_manifest(inst, dst_root, snapshot_id)
    return dst_root


def list_backups(inst) -> list[str]:
    """该实例的所有快照目录，新的在前（snapshot_id 是零填充时间戳，字典序即时间序）。"""
    root = backups_root(inst)
    if not os.path.isdir(root):
        return []
    snaps = [os.path.join(root, d) for d in os.listdir(root)
             if os.path.isdir(os.path.join(root, d))]
    snaps.sort(reverse=True)
    return snaps


def load_manifest(snapshot: str) -> dict:
    """读快照的 manifest.json（损坏/缺失时回退空 dict，不让 UI 崩）。"""
    try:
        with open(os.path.join(snapshot, "manifest.json"),
                  encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def restore_backup(inst, snapshot: str) -> dict:
    """用快照覆盖实例当前 mc_dir。返回该快照的 manifest。

    - 会删除实例当前的 mods / config / saves ——调用方必须先用确认框兜底。
    - 先摘 libraries 联接再清空，避免误删共享池；回滚后 ensure_dirs 重建联接。
    """
    src = os.path.join(snapshot, "minecraft")
    if not os.path.isdir(src):
        raise FileNotFoundError(f"备份损坏：缺少 {src!r}")

    mc = inst.mc_dir
    os.makedirs(mc, exist_ok=True)

    # 1) 摘掉共享池联接（清空时不能顺着它删池）
    inst._strip_library_junction(mc)

    # 2) 清空当前内容（避开符号链接/联接，防止顺链接越出边界）
    for name in os.listdir(mc):
        p = os.path.join(mc, name)
        if name in _SKIP_DIRS:
            continue
        if os.path.isdir(p) and not _is_link(p):
            shutil.rmtree(p, ignore_errors=True)
        elif not _is_link(p):
            try:
                os.remove(p)
            except OSError:
                pass

    # 2b) round-49：libraries 在 _SKIP_DIRS 被上面的循环跳过；若它是去重前
    # 遗留的「真实目录」（非联接），也一并清掉——否则 ensure_dirs 会把它的
    # 陈旧内容（如 keep.me）迁进共享池，回滚后 mc_dir 里仍残留旧文件。
    _lib = os.path.join(mc, "libraries")
    if os.path.isdir(_lib) and not _is_link(_lib):
        shutil.rmtree(_lib, ignore_errors=True)

    # 3) 覆盖
    shutil.copytree(src, mc, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*_SKIP_DIRS))

    # 4) 重建 libraries 联接（去重池）
    inst.ensure_dirs()

    return load_manifest(snapshot)


def _is_link(path: str) -> bool:
    try:
        if os.path.islink(path):
            return True
    except OSError:
        return True
    # Windows 目录联接 (mklink /J)：islink 不一定返回 True，再看 reparse 属性。
    try:
        from .shared_libs import is_junction
        return is_junction(path)
    except Exception:  # noqa: BLE001 - 能力缺失时不阻断，按普通目录处理
        return False