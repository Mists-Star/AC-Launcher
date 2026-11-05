"""Shared ``libraries`` / ``assets`` pools — 去重（round-48 / round-175）.

mll 把每个版本的库解析成 ``<minecraft_directory>/libraries/<maven-path>/<artifact>.jar``，
每个实例各存一份（lwjgl、glfw、netty…单版本 500MB+）。round-48 让每个 AC 自有实例的
``<mc_dir>/libraries`` 通过 Windows 目录联接（``mklink /J``，无需管理员权限）指向
一个全局共享池，所有安装共用一份磁盘副本。

round-175 把同一机制扩展到 ``assets``：现代版本一个实例的 assets 有 300–600 MB
（objects 按 sha1 内容寻址、indexes 按版本号命名，天然可共享），此前每实例都重复
下载。现在 ``<mc_dir>/assets`` 同样指向全局池。

Design constraints we respect:
  - Only AC-owned instances (``external=False``) get the junction. Linking to
    another launcher's real game folder must never be modified.
  - Deleting an instance must NOT nuke the shared pool → we strip the junction
    (``os.rmdir`` removes the reparse point, not the target) before any rmtree.
  - If a junction cannot be created (non-NTFS, mklink blocked, …) we fall back
    to a real directory and keep working — dedup degrades gracefully.
  - Idempotent: safe to call on every launch; a real, already-junctioned dir is
    a no-op. Existing real dirs are lazily merged into the pool once.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from ..paths import get_data_dir

POOL_SUBDIR = os.path.join("shared", "libraries")
ASSETS_POOL_SUBDIR = os.path.join("shared", "assets")


def pool_dir() -> str:
    """The single on-disk copy of all libraries, shared across instances."""
    p = os.path.join(get_data_dir(), POOL_SUBDIR)
    os.makedirs(p, exist_ok=True)
    return p


def assets_pool_dir() -> str:
    """The single on-disk copy of all assets, shared across instances."""
    p = os.path.join(get_data_dir(), ASSETS_POOL_SUBDIR)
    os.makedirs(p, exist_ok=True)
    return p


def is_junction(path: str) -> bool:
    """True if ``path`` is a reparse point (junction / symlink).

    round-48 修复：之前误用 ``os.path.lstat``——Windows 下 ``os.path``
    (ntpath) 根本没有 ``lstat``，每次抛 AttributeError 回落 ``os.path.islink``，
    而 islink 对 junction 返回 False，导致联接永远识别不出（mklink 其实成功了）。
    正确做法是用顶层 ``os.lstat``，它带 ``st_reparse_tag``。非 Windows 的
    ``os.lstat`` 没有该属性，再用 islink 兜底。
    """
    try:
        st = os.lstat(path)
    except OSError:
        return False
    tag = getattr(st, "st_reparse_tag", None)
    if tag is not None:
        return bool(tag)
    return os.path.islink(path)


def _remove_junction(path: str) -> None:
    """Remove a directory junction *link* without touching its target."""
    if is_junction(path):
        try:
            os.rmdir(path)  # removes the reparse point itself
        except OSError:
            pass


def _make_junction(link: str, target: str) -> bool:
    """Create a directory junction via ``mklink /J`` (no admin needed)."""
    link = os.path.abspath(link)
    target = os.path.abspath(target)
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", link, target],
            # mklink 输出是本地化编码（中文系统=GBK），必须 errors='replace'，
            # 否则 text=True 解码直接抛 UnicodeDecodeError，junction 永远建不成
            capture_output=True, text=True, errors="replace", timeout=30,
            creationflags=creationflags,
        )
        return r.returncode == 0 and is_junction(link)
    except Exception:  # noqa: BLE001 - any failure ⇒ fall back to real dir
        return False


def _file_digest(path: str) -> str:
    """Content hash for dedup — comparing only ``getsize`` can collide."""
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _merge_real_dir_into_pool(src_dir: str, pool: str | None = None) -> int:
    """Move a real shared-dir's contents into ``pool`` (default: libraries pool).

    Keeps pool-relative layout (so already-installed jars/assets are reused, not
    re-downloaded). Returns the number of files that could **not** be merged;
    those files stay in ``src_dir`` and the caller must keep the directory for a
    later retry. The old implementation compared only file size, swallowed every
    per-file failure and then unconditionally ``rmtree``d the source — one failed
    move silently destroyed jars/assets forever, because the junction was already
    live and later launches short-circuited on ``is_junction()``.
    """
    pool = pool or pool_dir()
    failed = 0
    for dirpath, _dirnames, filenames in os.walk(src_dir):
        rel = os.path.relpath(dirpath, src_dir)
        for fn in filenames:
            src = os.path.join(dirpath, fn)
            out_dir = os.path.join(pool, rel) if rel != "." else pool
            tgt = os.path.join(out_dir, fn)
            try:
                os.makedirs(out_dir, exist_ok=True)
                if os.path.exists(tgt):
                    if _file_digest(tgt) == _file_digest(src):
                        os.remove(src)      # content-identical → safe to drop
                        continue
                    # 同坐标但内容不同：两边都保留，不覆盖池、也不删源。
                    failed += 1
                    continue
                shutil.move(src, tgt)       # cross-volume move falls back to copy
            except (OSError, shutil.Error, ValueError):
                failed += 1                 # 文件留在 __pending，下次重试
    return failed


def _retry_pending_merge(pending: str, pool: str) -> None:
    """Retry leftovers from a previously failed merge; never delete stragglers."""
    if not os.path.isdir(pending) or not os.listdir(pending):
        return
    try:
        if _merge_real_dir_into_pool(pending, pool) == 0:
            shutil.rmtree(pending, ignore_errors=True)
    except Exception:  # noqa: BLE001 - dedup must never break startup
        pass


def _ensure_shared_dir(game_dir: str, name: str, pool: str) -> bool:
    """Idempotently make ``<game_dir>/<name>`` point at ``pool``.

    Returns True if the dir now resolves to the pool, False if it stays a
    private real dir (fallback). Never loses data: all mutation happens under
    an ``X.__pending`` name, and the original real dir is restored if the
    junction can't be created.
    """
    if not game_dir or not os.path.isdir(game_dir):
        return False
    target = os.path.join(game_dir, name)
    pending = target + "__pending"

    if is_junction(target):
        # 上次合并有残留（单文件 move 失败）→ 每次启动重试；旧实现直接 return，
        # 失败文件永远躺在 __pending 且再没人碰。
        _retry_pending_merge(pending, pool)
        return True

    _remove_junction(pending)
    # pending 里可能还留着上次没搬成功的文件，禁止无条件 rmtree（会永久丢文件）。
    _retry_pending_merge(pending, pool)
    if os.path.isdir(pending):
        if os.listdir(pending):
            return False        # 残留仍搬不动 → 本轮不改造目录，真实文件保持原样
        try:
            os.rmdir(pending)
        except OSError:
            pass

    had_content = os.path.isdir(target) and os.listdir(target)
    if had_content:
        # 先挪到一边再建联接，确保失败可回滚（否则实例会变成空目录）
        try:
            os.rename(target, pending)
        except OSError:
            had_content = False
    else:
        try:
            os.rmdir(target)  # drop empty/missing slot before mklink binds
        except OSError:
            pass

    if _make_junction(target, pool):
        if had_content:
            if _merge_real_dir_into_pool(pending, pool) == 0:
                shutil.rmtree(pending, ignore_errors=True)
            # 有搬不动的文件 → 保留 pending，下次启动继续重试，绝不删残留
        return True

    # junction 失败 → 恢复原状（个人目录继续用，去重优雅降级）
    if had_content and os.path.isdir(pending):
        try:
            os.rename(pending, target)
        except OSError:
            shutil.move(pending, target)
    elif had_content and not os.path.isdir(pending):
        # pending 已清空合并但 junction 失败——极罕见，直接当个人目录用
        os.makedirs(target, exist_ok=True)
    else:
        os.makedirs(target, exist_ok=True)
    return False


def should_use_shared_pool(inst) -> bool:
    """True ⇒ 该实例可以把 libraries/assets 指向全局共享池（目录联接）。

    审查 P0-4：旧判定只有 ``not external``，会把「复制导入」的外来实例也
    套上池，与 round-92「绝不改外来客户端布局」直接冲突，且补库写 jar 会
    穿透联接污染所有实例。只放行 AC 自建实例：

      * ``external``：原地接管其它启动器目录，绝不改用户真实文件；
      * ``version_id`` 非空：外来完整客户端，自带 libraries/assets 布局；
      * ``kind`` 非空：外来导入（standard / mmc / curseforge / modrinth…）；
      * ``launcher != "AC"``：来源启动器标记。
    """
    if getattr(inst, "external", False):
        return False
    if (getattr(inst, "version_id", "") or "").strip():
        return False
    if (getattr(inst, "kind", "") or "").strip():
        return False
    launcher = (getattr(inst, "launcher", "") or "").strip()
    if launcher and launcher != "AC":
        return False
    return True


def ensure_shared_libraries(game_dir: str) -> bool:
    """Idempotently make ``<game_dir>/libraries`` point at the libraries pool."""
    return _ensure_shared_dir(game_dir, "libraries", pool_dir())


def ensure_shared_assets(game_dir: str) -> bool:
    """Idempotently make ``<game_dir>/assets`` point at the assets pool."""
    return _ensure_shared_dir(game_dir, "assets", assets_pool_dir())