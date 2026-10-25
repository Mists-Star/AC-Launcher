"""Shared ``libraries`` pool — "共享 libraries 去重" (round-48).

minecraft-launcher-lib resolves every install/launch library path as
``<minecraft_directory>/libraries/<maven-path>/<artifact>.jar``. Individually
that is correct but every instance re-downloads the same jars into its own
folder (lwjgl, glfw, netty, … can be 500MB+ per version), so dozens of
instances blow up disk usage.

This module makes each AC-created instance's ``<mc_dir>/libraries`` resolve to a
*single global pool directory* via a Windows directory junction (``mklink /J``,
which — unlike a symlink — does **not** need administrator rights). All installs
then share one on-disk copy; the launcher/launch path logic is untouched.

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


def pool_dir() -> str:
    """The single on-disk copy of all libraries, shared across instances."""
    p = os.path.join(get_data_dir(), POOL_SUBDIR)
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


def _merge_real_dir_into_pool(src_dir: str) -> None:
    """Move a real ``libraries`` directory's contents into the pool.

    Keeps pool-relative layout (so already-installed jars are reused, not
    re-downloaded). ``src_dir`` is fully removed after a successful merge.
    """
    pool = pool_dir()
    for dirpath, _dirnames, filenames in os.walk(src_dir):
        rel = os.path.relpath(dirpath, src_dir)
        for fn in filenames:
            src = os.path.join(dirpath, fn)
            out_dir = os.path.join(pool, rel) if rel != "." else pool
            try:
                os.makedirs(out_dir, exist_ok=True)
                tgt = os.path.join(out_dir, fn)
                if os.path.exists(tgt) and os.path.getsize(tgt) == os.path.getsize(src):
                    os.remove(src)         # already present & same size → skip
                else:
                    shutil.move(src, tgt)  # cross-volume move falls back to copy
            except OSError:
                pass  # a single file failing shouldn't abort the whole merge
    shutil.rmtree(src_dir, ignore_errors=True)


def ensure_shared_libraries(game_dir: str) -> bool:
    """Idempotently make ``<game_dir>/libraries`` point at the shared pool.

    Returns True if the libraries dir now resolves to the pool, False if it
    stays a private real dir (fallback). Safe to call on every launch.

    Never loses data: all mutation happens under an ``X.__pending`` name, and
    the original real dir is restored if the junction can't be created.
    """
    if not game_dir or not os.path.isdir(game_dir):
        return False
    libraries = os.path.join(game_dir, "libraries")
    if is_junction(libraries):
        return True

    pending = libraries + "__pending"
    _remove_junction(pending)
    shutil.rmtree(pending, ignore_errors=True)

    had_content = os.path.isdir(libraries) and os.listdir(libraries)
    if had_content:
        # 先挪到一边再建联接，确保失败可回滚（否则实例会变成空 libraries）
        try:
            os.rename(libraries, pending)
        except OSError:
            had_content = False
    else:
        try:
            os.rmdir(libraries)  # drop empty/missing slot before mklink binds
        except OSError:
            pass

    if _make_junction(libraries, pool_dir()):
        if had_content:
            _merge_real_dir_into_pool(pending)  # 合并原库进池，已完成收集
        return True

    # junction 失败 → 恢复原状（个人目录继续用，去重优雅降级）
    if had_content and os.path.isdir(pending):
        try:
            os.rename(pending, libraries)
        except OSError:
            shutil.move(pending, libraries)
    elif had_content and not os.path.isdir(pending):
        # pending 已清空合并但 junction 失败——极罕见，直接当个人目录用
        os.makedirs(libraries, exist_ok=True)
    else:
        os.makedirs(libraries, exist_ok=True)
    return False