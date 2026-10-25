"""Modpack format detection + import helpers.

Supports:
- Modrinth .mrpack (via minecraft-launcher-lib)
- CurseForge .zip (manifest.json + overrides/)
- Generic .zip containing a .minecraft/ tree
- Plain folder import

All heavy work is synchronous so callers must run it in a QThread Worker.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from typing import Callable

from .i18n import t


def detect_pack_format(path: str) -> str | None:
    """Return one of 'mrpack'/'curseforge'/'zip_mc'/'folder'/None."""
    if os.path.isdir(path):
        return "folder"
    if not os.path.isfile(path):
        return None
    lower = path.lower()
    if lower.endswith(".mrpack"):
        return "mrpack"
    if not lower.endswith(".zip"):
        return None

    try:
        with zipfile.ZipFile(path, "r") as z:
            names = z.namelist()
    except zipfile.BadZipFile:
        return None

    if "modrinth.index.json" in names or any(n.endswith(".mrpack") for n in names):
        return "mrpack"
    if "manifest.json" in names:
        try:
            with zipfile.ZipFile(path, "r") as z:
                raw = z.read("manifest.json")
            manifest = json.loads(raw)
        except Exception:  # noqa: BLE001
            manifest = {}
        if manifest.get("manifestType") == "minecraftModpack" or (
            "minecraft" in manifest and "files" in manifest
        ):
            return "curseforge"
    if any(n.startswith(".minecraft/") or n == ".minecraft" for n in names):
        return "zip_mc"
    return None


def _parse_curseforge_manifest(manifest: dict) -> dict:
    """Extract mc_version/loader/loader_version/files/overrides from manifest."""
    mc = manifest.get("minecraft", {})
    mc_version = mc.get("version", "")
    loaders = mc.get("modLoaders", [])
    loader = "vanilla"
    loader_version = ""
    for ld in loaders:
        lid = ld.get("id", "")
        if ld.get("primary") and lid:
            parts = lid.split("-", 1)
            loader = parts[0] if parts[0] else "vanilla"
            loader_version = parts[1] if len(parts) > 1 else ""
            break
    if not loader_version and loaders:
        lid = loaders[0].get("id", "")
        parts = lid.split("-", 1)
        loader = parts[0] if parts[0] else "vanilla"
        loader_version = parts[1] if len(parts) > 1 else ""
    files = manifest.get("files", [])
    overrides = manifest.get("overrides", "overrides")
    return {
        "name": manifest.get("name", t("new_instance.unnamed")),
        "version": manifest.get("version", ""),
        "mc_version": mc_version,
        "loader": loader,
        "loader_version": loader_version,
        "files": files,
        "overrides": overrides,
        "author": manifest.get("author", ""),
    }


def _parse_mrpack_info(raw: dict) -> dict:
    name = raw.get("name") or t("new_instance.unnamed")
    deps = raw.get("dependencies") or []
    mc_version = ""
    loader = "vanilla"
    for d in deps:
        did = (d.get("id") or "").lower()
        if did.startswith("minecraft"):
            mc_version = did.split(":")[-1] if ":" in did else did
        elif did in ("fabric-loader", "quilt-loader"):
            loader = "fabric" if did == "fabric-loader" else "quilt"
        elif did == "forge":
            loader = "forge"
        elif did == "neoforge":
            loader = "neoforge"
    mods = raw.get("files") or []
    return {
        "name": name,
        "mc_version": mc_version,
        "loader": loader,
        "mods": len(mods),
    }


def import_mrpack(path: str, mgr, mirror: str = "official") -> object:
    """Install a Modrinth .mrpack into a fresh AC instance."""
    import minecraft_launcher_lib
    from .core import install

    raw = minecraft_launcher_lib.mrpack.get_mrpack_information(path)
    launch_version = minecraft_launcher_lib.mrpack.get_mrpack_launch_version(path)
    name = raw.get("name") or t("new_instance.unnamed")
    deps = raw.get("dependencies") or []
    mc_version = ""
    loader = "vanilla"
    for d in deps:
        did = (d.get("id") or "").lower()
        if did.startswith("minecraft"):
            mc_version = did.split(":")[-1] if ":" in did else did
        elif did in ("fabric-loader", "quilt-loader"):
            loader = "fabric" if did == "fabric-loader" else "quilt"
        elif did == "forge":
            loader = "forge"
        elif did == "neoforge":
            loader = "neoforge"
    inst = mgr.add(name=name, game_version=mc_version or "1.21.4", loader=loader)
    inst.version_id = launch_version or ""
    mgr._persist(inst)
    install.install_mrpack(path, inst.mc_dir, mirror=mirror)
    return inst


def import_curseforge_zip(
    path: str,
    mgr,
    mirror: str = "official",
    progress: Callable[[str, int, int], bool] | None = None,
) -> object:
    """Install a CurseForge-format .zip modpack into a fresh AC instance.

    ``progress`` receives (file_name, current, total) and may return False to
    cancel. Returns the new instance object.
    """
    from .net_api import download_curseforge_mod, NetError

    with zipfile.ZipFile(path, "r") as z:
        manifest = json.loads(z.read("manifest.json"))
    info = _parse_curseforge_manifest(manifest)

    inst = mgr.add(
        name=info["name"],
        game_version=info["mc_version"] or "1.21.4",
        loader=info["loader"],
        loader_version=info["loader_version"],
    )
    # copy overrides into instance root
    # round-40 P0 安全：overrides 相对路径必须仍在实例目录内（防 `..` 穿越
    # 把文件写到任意路径，覆盖启动器配置/用户文件）。
    import posixpath as _posixpath
    overrides = info["overrides"] or "overrides"
    mc_abs = os.path.abspath(inst.mc_dir)
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()
        override_prefix = overrides + "/"
        for n in names:
            if n.startswith(override_prefix) and not n.endswith("/"):
                rel = n[len(override_prefix):]
                if not rel:
                    continue
                # 拒绝 .. 逃逸 / 绝对路径
                norm = _posixpath.normpath(rel.replace("\\", "/"))
                if norm.startswith("..") or norm.startswith("/") or ":" in norm.split("/")[0]:
                    print(f"[modpack_import] 跳过越界 overrides 条目: {n!r}")
                    continue
                dest = os.path.join(mc_abs, norm)
                if not (dest == mc_abs or dest.startswith(mc_abs + os.sep)):
                    print(f"[modpack_import] 跳过越界 overrides 条目: {n!r}")
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(n) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    # create mods dir and download required files
    os.makedirs(inst.mods_dir, exist_ok=True)
    files = [f for f in info["files"] if f.get("required", True)]
    total = len(files)
    # round-73：单个文件逐个顺序下载 + 一个失败就中断整批 → 改为并发批下载，
    # 失败记录继续（对齐 MCLauncher 20-worker 队列 / 主流 LoaderDownload）。
    from .batch_download import BatchDownloader, BatchItem

    batch: list[BatchItem] = []
    for f in files:
        pid = str(f.get("projectID", ""))
        if not pid:
            continue
        fid = f.get("fileID", "")
        label = f"CurseForge #{pid}/{fid}"

        def _task(pid=pid):
            download_curseforge_mod(pid, inst.mods_dir)

        batch.append(BatchItem(name=label, task=_task))

    failures: list[str] = []

    def _on_progress(done, total_dl):
        if progress is not None:
            progress(f"{done}/{total_dl}", done, total)

    def _on_finish(items) -> None:
        failed = [it for it in items if not it.ok and not it.cancelled]
        failures.extend(f"{it.name}: {it.detail}" for it in failed)

    # 失败继续但整包级别仍要收敛：任一失败 → NetError 汇总（保留原语义：
    # CurseForge API key 缺失时明确提示）
    dl = BatchDownloader(batch, workers=8,
                         on_progress=_on_progress, on_finish=_on_finish)
    dl.start()
    dl.join()
    if failures:
        raise NetError(
            f"{t('modpack.curse_batch_fail', n=len(failures))}\n" +
            "\n".join(failures[:5])
            + ("" if len(failures) <= 5 else f"\n… 另有 {len(failures)-5} 个失败")
        ) from None
    mgr._persist(inst)
    return inst


def import_zip_as_instance(path: str, mgr) -> object:
    """Extract a generic .zip containing a .minecraft/ tree into a fresh instance.

    If the zip root is a .minecraft/ folder, it is used as the game dir.
    Otherwise the zip contents are extracted as-is into a new instance and a
    vanilla instance is registered.
    """
    name = os.path.splitext(os.path.basename(path))[0]
    tmp = tempfile.mkdtemp(prefix="ac_pack_")
    try:
        with zipfile.ZipFile(path, "r") as z:
            # round-40 P0 安全：safe_extract_zip 拒绝 .. 逃逸/绝对路径条目
            # （之前裸 extractall = 恶意 zip 任意文件写入漏洞）
            from .core.utils import safe_extract_zip
            safe_extract_zip(z, tmp)
        roots = [os.path.join(tmp, d) for d in os.listdir(tmp)
                 if os.path.isdir(os.path.join(tmp, d))]
        # prefer a folder that contains .minecraft
        mc_dir = None
        for r in roots:
            if os.path.isdir(os.path.join(r, ".minecraft")):
                mc_dir = os.path.join(r, ".minecraft")
                break
        if mc_dir is None and len(roots) == 1:
            # single top-level folder: treat it as the instance dir
            top = roots[0]
            if os.path.isdir(os.path.join(top, "versions")):
                mc_dir = top
        if mc_dir is None:
            mc_dir = tmp

        game_version = _guess_mc_version_from_dir(mc_dir) or "?"
        loader = _guess_loader_from_dir(mc_dir)
        inst = mgr.add(name=name, game_version=game_version, loader=loader)
        # copy contents into AC instance dir
        _copy_tree(mc_dir, inst.mc_dir)
        mgr._persist(inst)
        return inst
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def import_folder_as_instance(folder: str, mgr) -> object:
    """Import an existing .minecraft/ or instance folder into AC."""
    name = os.path.basename(os.path.dirname(folder)) or os.path.basename(folder)
    # If user picked the parent of .minecraft
    if os.path.isdir(os.path.join(folder, ".minecraft")):
        folder = os.path.join(folder, ".minecraft")
    game_version = _guess_mc_version_from_dir(folder) or "?"
    loader = _guess_loader_from_dir(folder)
    inst = mgr.add(name=name, game_version=game_version, loader=loader)
    _copy_tree(folder, inst.mc_dir)
    mgr._persist(inst)
    return inst


def _guess_mc_version_from_dir(mc_dir: str) -> str:
    versions_dir = os.path.join(mc_dir, "versions")
    if not os.path.isdir(versions_dir):
        return ""
    try:
        for e in os.scandir(versions_dir):
            if e.is_dir() and os.path.isfile(
                os.path.join(e.path, e.name + ".json")
            ):
                return e.name
    except OSError:
        pass
    return ""


def _guess_loader_from_dir(mc_dir: str) -> str:
    mods_dir = os.path.join(mc_dir, "mods")
    if not os.path.isdir(mods_dir):
        return "vanilla"
    from .scan import _loader_from_text
    try:
        for f in os.listdir(mods_dir):
            fl = f.lower()
            if fl.endswith(".jar"):
                return _loader_from_text(f)
    except OSError:
        pass
    return "vanilla"


def _copy_tree(src: str, dst: str):
    """Copy directory contents, overwriting existing files."""
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target = os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(target, f))
