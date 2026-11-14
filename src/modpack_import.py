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


def tick_import_progress(state: dict, progress) -> None:
    """整合包导入进度的 200ms 轮询回调（round-222 抽取公共实现）。

    ``pages_browse`` / ``pages_instances`` 曾各有一份逐字相同的 32 行闭包，
    只靠 ``state``（跨线程零信号管道）和 ``QProgressDialog`` 驱动。两处逻辑
    分叉的风险很实：下面这些坑都是踩过才补上的——

    * ``done < 0`` = 不定长阶段（装游戏版本 / 加载器），用回调自定义文案；
    * 满值后**不能**再 ``setValue(max)``：QProgressDialog 会自动关 → reset
      清空 label → 再 show，玩家看到「导入包」空提示一直闪（round-150）。
      改为一次性切不定长转圈 + 收尾文案，稳定显示到完成；
    * label 只在文案变化时写，避免每 200ms 无谓重绘。

    ``state`` 键：``done`` / ``total`` / ``label`` / ``txt`` / ``finishing``。
    """
    d, tot = state["done"], state["total"]
    if d < 0:
        txt = state.get("label") or t("modpack.finishing")
        if progress.maximum() != 0:
            progress.setRange(0, 0)
        if state.get("txt") != txt:
            state["txt"] = txt
            progress.setLabelText(txt)
        if not progress.isVisible():
            progress.show()
        return
    if not tot:
        return
    if d < tot:
        if progress.maximum() != tot:
            progress.setRange(0, tot)
        if progress.value() != d:
            progress.setValue(d)
        txt = f"{t('modpack.importing')}（{d}/{tot} · {d * 100 // tot}%）"
        if state.get("txt") != txt:
            state["txt"] = txt
            progress.setLabelText(txt)
    elif not state.get("finishing"):
        state["finishing"] = True
        progress.setRange(0, 0)
        progress.setLabelText(t("modpack.finishing"))
        progress.show()


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
    inst = mgr.add(name=name, game_version=mc_version or "1.21.4", loader=loader,
                   isolation="default")
    inst.version_id = launch_version or ""
    mgr._persist(inst)
    install.install_mrpack(path, inst.mc_dir, game_dir=inst.game_dir,
                           mirror=mirror)
    # round-197：登记模组来源（整合包里的 jar 本来没有可靠的 project_id，
    # 但至少要让玩家在模组列表里看得出"这是整合包带来的"）
    _record_pack_sources(inst, source="modpack", title=name)
    return inst


def _record_pack_sources(inst, source: str, title: str = "",
                         project_ids: dict | None = None) -> int:
    """登记「整合包 / 导入」带来的模组来源（round-197）。

    这些 jar 没有可靠的 project_id（整合包只声明"要下哪些文件"，玩家还能
    overrides 覆盖），但**来源要标出来** —— 否则它们和玩家手动放进来的在
    模组列表里长得一模一样，更新检测也认不出。

    ``project_ids``: ``{project_id: 文件名}``（CF 整合包有，能精确登记）。
    """
    mods_dir = getattr(inst, "mods_dir", "") or ""
    if not mods_dir or not os.path.isdir(mods_dir):
        return 0
    names = [n for n in os.listdir(mods_dir)
             if n.lower().endswith((".jar", ".jar.disabled"))]
    if not names:
        return 0
    entries = []
    for n in names:
        entries.append({
            "filename": n,
            "project_id": "",
            "slug": "",
            "title": title or "",
            "source": source,
        })
    try:
        from .core import mod_sources
        return mod_sources.record(inst, entries)
    except Exception:  # noqa: BLE001 - 登记失败不影响导入本身
        return 0


def _launcher_settings() -> dict:
    """Best-effort launcher config for install-time options (round-150)."""
    try:
        from .settings_dialog import load_config
        return load_config() or {}
    except Exception:  # noqa: BLE001 - 配置读不到就按默认值处理
        return {}


def _install_after_import(inst, progress) -> None:
    """Install the game version + loader as part of the import (round-150).

    旧行为只写元数据：首次启动时 ``launch_instance`` 才发现版本/加载器没装，
    弹「安装 / 修复游戏版本」（用户感知为「重启后打开又在补全版本」）；安装
    失败（官方 maven 超时）时每次启动都会重跑一遍。导入时一次性装好，
    之后的启动就是零下载直启。

    绝不抛出：已经下载好的整合包内容必须保留。错误挂到实例上，由 UI 提示
    「首次启动会再试一次」。
    """
    from .core.install import install_instance

    cfg = _launcher_settings()
    cb = None
    if progress is not None:
        def _status(raw: str) -> None:
            # 只显示本地化阶段文案。底层安装器会把内部状态字符串（例如
            # "Installation complete"）塞进 setStatus，那是它的某个子步骤，
            # 不代表导入流程结束；拼到界面上既泄漏英文实现细节，也会让
            # 玩家误以为已经装完、进而把后面的等待当成卡死。
            progress(t("modpack.installing_loader"), -1, 0)
        cb = {"setStatus": _status}
    try:
        install_instance(
            inst,
            java_auto=bool(cfg.get("java_auto", True)),
            java_path=(cfg.get("java_path") or "").strip(),
            mirror=(cfg.get("download_mirror") or "official"),
            proxy=(cfg.get("download_proxy") or ""),
            callback=cb,
        )
    except Exception as e:  # noqa: BLE001 - 安装失败不丢整合包
        print(f"[modpack_import] 游戏版本/加载器安装失败: {e}")
        try:
            inst.loader_install_error = str(e)
        except Exception:  # noqa: BLE001
            pass


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
        isolation="default",
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

        # round-142：传 file_id —— manifest 指定的文件版本必须精确下载
        # （此前丢弃 fileID 只取最新版，装出来的包和作者声明的不一致）；
        # 无 key 时 download_curseforge_mod 内部自动走免 key 通道。
        def _task(pid=pid, fid=fid):
            download_curseforge_mod(pid, inst.mods_dir, file_id=fid)

        batch.append(BatchItem(name=label, task=_task))

    failures: list[str] = []

    def _on_progress(done, total_dl):
        # round-150：total 用批任务数（total_dl），不再用 manifest 条目数——
        # 两者可能不等（缺 projectID 的条目不入批），会导致百分比永远到不了
        # 100%、收尾状态提前/滞后。
        if progress is not None:
            progress(f"{done}/{total_dl}", done, total_dl)

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
    # 先落盘再安装：安装失败也不至于丢掉已下载的整合包内容（round-150）。
    mgr._persist(inst)
    # round-197：CF 整合包的文件**带 projectID** → 可以精确登记来源
    _record_pack_sources(inst, source="curseforge", title=inst.name,
                         project_ids={str(f.get("projectID", "")): f
                                      for f in info.get("files", [])
                                      if f.get("projectID")})
    if progress is not None:
        progress(t("modpack.installing_loader"), -1, 0)
    _install_after_import(inst, progress)
    # 安装阶段可能补全了 loader_version（manifest 未指定时）→ 再落盘一次。
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
        inst = mgr.add(name=name, game_version=game_version, loader=loader,
                   isolation="default")
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
    inst = mgr.add(name=name, game_version=game_version, loader=loader,
                   isolation="default")
    _copy_tree(folder, inst.mc_dir)
    mgr._persist(inst)
    # round-197：导入的实例里那些 jar 标成「导入」来源（区别于手动放入）
    _record_pack_sources(inst, source="imported", title=name)
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
