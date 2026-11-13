"""Instance backup & rollback — 快照备份「一键备份 / 更新坏了一键回滚」。

快照存到 ``data/backups/<instance_id>/<snapshot_id>/``（portable，与启动器并列）。

每个快照：
  backups/<id>/<snapshot>/
    minecraft/        # 该实例 .minecraft 的用户内容副本（跳过 libraries 与所有目录联接）
    manifest.json     # 实例元数据 + 快照时间

为什么不备份 ``libraries`` / ``assets`` 的共享池：round-48 起 AC 自有实例的
``<mc_dir>/libraries``、``<mc_dir>/assets`` 都是指向全局共享池的**目录联接**。
备份时克隆它们会把整个去重池复制一遍（assets 1.20 约 400~700 MB、上万文件，
既占盘又没意义）；回滚时顺着联接还会覆盖共享池。所以存取都跳过，回滚后由
``Instance.ensure_dirs()`` 重建联接即可。round-228 之前只按名字跳了 libraries，
漏掉 assets —— 而 ``os.walk`` 对 junction **会**进入（``os.path.islink`` 对
junction 返回 False），于是每次备份都整份复制 assets/objects。

回滚 = 摘掉 libraries 联接 → **把当前内容整体搬进同盘暂存区** → 用快照内容覆盖
→ 验证成功后才销毁暂存区。任何一步失败都把原内容原样搬回（round-210 P0）。
"""
from __future__ import annotations

import json
import os
import shutil
import time

from ..paths import get_data_dir
from .shared_libs import is_junction

# mc_dir 里既不属于用户内容、又可能是共享池联接的目录 → 备份/回滚时跳过。
# versions/ 保留（游戏本体，回滚后离线也能直接启动）。
#
# round-228 P1-3：名字只是兜底，真正的判据是「是不是目录联接」。
# 外来导入实例的 assets 是真实目录（should_use_shared_pool=False），
# 按名字一刀切会把它的资源也丢出快照；只跳 reparse point 才能两全。
_SKIP_DIRS = ("libraries",)


def backups_root(inst) -> str:
    """快照根目录 ``data/backups/<instance_id>``。"""
    return os.path.join(get_data_dir(), "backups", inst.id)


def snapshot_dir(inst, snapshot_id: str) -> str:
    return os.path.join(backups_root(inst), snapshot_id)


def _snapshot_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _walk_files(src: str) -> list[tuple[str, str]]:
    """列 ``src`` 下所有文件 ``(abs, rel_to_src)``，跳过共享池 / 目录联接。"""
    files: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(src):
        # round-228 P1-3：os.walk 会进入 Windows junction（followlinks 只管
        # symlink，os.path.islink 对 junction 返回 False），必须逐项按
        # reparse tag 过滤，否则一次备份就把共享池的 assets/objects 全拷进来。
        dirnames[:] = [d for d in dirnames
                       if d not in _SKIP_DIRS
                       and not is_junction(os.path.join(dirpath, d))]
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


def _clear_contents(folder: str) -> None:
    """清掉 folder 的直接子项，绝不顺着符号链接/目录联接越界。"""
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        if is_junction(p):
            # Windows junction 用 rmdir 只摘链接本身，不动目标目录。
            try:
                os.rmdir(p)
            except OSError:
                pass
            continue
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except OSError:
                pass


def _move_contents(src_folder: str, dst_folder: str) -> None:
    """同盘逐项 rename（原子且可逆），用于暂存 / 搬回。"""
    os.makedirs(dst_folder, exist_ok=True)
    for name in os.listdir(src_folder):
        os.replace(os.path.join(src_folder, name),
                   os.path.join(dst_folder, name))


def restore_backup(inst, snapshot: str) -> dict:
    """用快照覆盖实例当前 mc_dir。返回该快照的 manifest。

    round-210 P0：原实现「先 rmtree 清空 → copytree」，磁盘写满 / 文件被占用 /
    快照损坏时 copytree 半途抛异常，玩家存档与新加的 mods 已永久丢失且无法回滚。
    现在改成两阶段事务：

      1. 摘掉 libraries 联接；把当前所有内容**搬进同盘暂存区**（不删除）。
      2. copytree 覆盖 + ensure_dirs 重建联接；任一步失败 → 清掉半成品、
         把暂存区原样搬回 → 原状态完整恢复后向上抛异常。
      3. 只有全部成功才销毁暂存区。

    注意：成功回滚会删除「做快照之后新增」的文件，调用方确认框必须写明。
    """
    src = os.path.join(snapshot, "minecraft")
    if not os.path.isdir(src):
        raise FileNotFoundError(f"备份损坏：缺少 {src!r}")

    mc = os.path.abspath(inst.mc_dir)
    os.makedirs(mc, exist_ok=True)

    # 1) 摘掉共享池联接（搬移时不能顺着它把整个去重池搬走）
    inst._strip_shared_junctions(mc)

    # 2) 同盘暂存区：与 mc_dir 同级，保证 os.replace 是原子 rename。
    parent = os.path.dirname(mc)
    stem = ".ac-restore-tx-%d-%d" % (os.getpid(), int(time.time() * 1000))
    stage = os.path.join(parent, stem)
    n = 0
    while os.path.exists(stage):
        n += 1
        stage = os.path.join(parent, f"{stem}_{n}")
    os.makedirs(stage)

    moved = False
    try:
        _move_contents(mc, stage)
        moved = True

        # 3) 覆盖；失败时清半成品并把暂存区原样搬回。
        try:
            # round-228 P1-3：AC 自建实例的 assets 必须是联接。修复之前创建的
            # 旧快照里可能含 assets 的真实副本，直接 copytree 会把它写回成
            # 普通目录，随后 ensure_dirs() 得把上万文件逐个搬回共享池。
            # 外来实例的 assets 本来就是真实目录，仍要照常还原。
            ignore_names = set(_SKIP_DIRS)
            try:
                from .shared_libs import should_use_shared_pool
                if should_use_shared_pool(inst):
                    ignore_names.add("assets")
            except Exception:  # noqa: BLE001 - 判定不可用就按旧行为还原
                pass
            shutil.copytree(src, mc, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*ignore_names))
            inst.ensure_dirs()
        except Exception:
            _clear_contents(mc)
            _move_contents(stage, mc)
            moved = False
            try:
                inst.ensure_dirs()
            except Exception:  # noqa: BLE001 - 回滚优先，重建联接失败不覆盖原异常
                pass
            raise
    except Exception:
        # 连「搬进暂存区」都失败：把已搬走的逐项放回，不能留半个空目录。
        if moved:
            _move_contents(stage, mc)
        try:
            os.rmdir(stage)
        except OSError:
            pass
        raise

    # 4) 提交：只有走到这里才真正销毁旧内容。
    shutil.rmtree(stage, ignore_errors=True)
    return load_manifest(snapshot)