"""Version + mod-loader installation on top of minecraft-launcher-lib.

Key fact we rely on: ``install.install_minecraft_version`` already *verifies and
repairs* an existing install — it only re-downloads missing/corrupt files. That
is exactly the engine behind the "auto-repair" feature: point it at any
``.minecraft`` directory (ours or another launcher's) and it heals it.
"""
from __future__ import annotations

import os

import minecraft_launcher_lib

from .java import select_java

SUPPORTED_LOADERS = [
    "vanilla", "fabric", "forge", "quilt", "neoforge", "liteloader",
    "legacyfabric", "cleanroom", "optifine",
]


def _diag_enabled() -> bool:
    """round-110 C：下载诊断日志开关（配置缺失或读取失败一律视为关闭）。"""
    try:
        from ..settings_dialog import load_config
        return bool(load_config().get("download_diag_log", False))
    except Exception:  # noqa: BLE001
        return False


def install_instance(inst, *, java_auto: bool = True, java_path: str = "", mirror: str = "official", proxy: str = "", callback=None) -> str:
    """Install (or repair) an instance's game version + loader into its mc_dir.

    Returns the installed Minecraft version string to pass to
    ``command.get_minecraft_command``.

    ``mirror`` is "official" (Mojang) or "bmclapi" (BMCLAPI China mirror) — when
    bmclapi, game-file downloads are transparently redirected via core.mirror.
    ``proxy`` is the download_proxy setting ("none"/"system"/custom URL) so a
    user behind a proxy can still fetch game files.
    """
    # round-42 auto 源：测速决定是否走 bmclapi 重写（对齐主流做法）
    if mirror == "auto":
        try:
            from ..net_api import _pick_auto_mirror
            mirror = "bmclapi" if "bmclapi" in _pick_auto_mirror() else "official"
        except Exception:
            mirror = "official"
    # round-109：打补丁与走镜像解耦 —— 镜像与否由 set_mirror 在请求时决定，
    # 补丁本身永远打上，好让官方源也拿到「超时 + 重试 + 可取消」。
    from .mirror import patch_install_session, set_diag, set_mirror, set_proxy
    set_proxy(proxy or None)
    set_mirror(mirror == "bmclapi")
    set_diag(_diag_enabled())
    patch_install_session()

    mc_dir = inst.mc_dir
    loader = inst.loader if inst.loader in SUPPORTED_LOADERS else "vanilla"
    java = select_java(inst.game_version, java_auto=java_auto, user_path=java_path) or "java"

    # Persist the resolved loader version so later runs are deterministic.
    # Only lib-managed loaders (fabric/forge/quilt/neoforge) expose
    # get_latest_loader_version; the custom ones resolve inside their own
    # install functions when loader_version is empty.
    if loader in ("fabric", "forge", "quilt", "neoforge") and not inst.loader_version:
        ml = minecraft_launcher_lib.mod_loader.get_mod_loader(loader)
        inst.loader_version = ml.get_latest_loader_version(inst.game_version)

    if loader == "vanilla":
        minecraft_launcher_lib.install.install_minecraft_version(
            inst.game_version, mc_dir, callback=callback
        )
        return inst.game_version

    if loader == "liteloader":
        # Legacy loader (MC ≤1.12.2): compose a LiteLoader version json over
        # the base Minecraft install instead of using the lib's loader API.
        return install_liteloader(
            inst.game_version, mc_dir,
            build_version=inst.loader_version or "",
            tweak_class="",
            libraries=None,
            callback=callback,
        )

    if loader == "legacyfabric":
        # Legacy Fabric (MC 1.3–1.13 era): same installer protocol as Fabric
        # but hosted on meta.legacyfabric.net. The lib's Fabric class can't be
        # pointed at it, so we fetch the loader version json ourselves and let
        # the lib install the base version; the loader's own jar + libraries
        # come from the legacyfabric maven (handled by _install_legacyfabric).
        return _install_legacyfabric(
            inst.game_version, mc_dir,
            loader_version=inst.loader_version or "",
            callback=callback,
        )

    if loader == "cleanroom":
        # Cleanroom: Forge continuation fork (1.12.2 on Java 21 + LWJGL3).
        # Official installer jar does the whole job (it writes its own version
        # json into versions/). We just run it with --installClient.
        return _install_cleanroom(
            inst.game_version, mc_dir,
            installer_url=inst.loader_version or "",
            java=java,
            callback=callback,
        )

    if loader == "optifine":
        # OptiFine as a standalone loader entry: install the base version,
        # then run the OptiFine installer jar (BMCLAPI path) into the game dir
        # so it produces a "<mc>-OptiFine_<build>" version entry.
        return _install_optifine(
            inst.game_version, mc_dir,
            build=inst.loader_version or "",
            java=java,
            callback=callback,
        )

    ml = minecraft_launcher_lib.mod_loader.get_mod_loader(loader)
    installed = ml.install(
        inst.game_version,
        mc_dir,
        loader_version=inst.loader_version or None,
        callback=callback,
        java=java,
    )
    return installed


def list_installed_versions(mc_dir: str) -> list[str]:
    """Return all version ids present under a .minecraft/versions directory."""
    vdir = os.path.join(mc_dir, "versions")
    if not os.path.isdir(vdir):
        return []
    out = []
    for name in os.listdir(vdir):
        if os.path.isfile(os.path.join(vdir, name, f"{name}.json")):
            out.append(name)
    return out


def repair_minecraft_dir(mc_dir: str, callback=None) -> list[str]:
    """Re-verify & repair every version found under a .minecraft directory.

    This is the core of the cross-launcher "auto-repair" feature: given any
    other launcher's game directory we make it launchable. Returns the list of
    repaired version ids (empty if none found).
    """
    # round-109：体检修复同样是 mll 的网络下载路径，之前没有任何加固 —— 如果本次
    # 会话的第一个网络动作就是体检修复（patch_install_session 的 _PATCHED 幂等门
    # 还没被 install_instance 打开），就仍会裸连接挂死。这里补上与 install_instance
    # 一致的「超时 + 重试 + 可取消 + 按用户设置走镜像」。
    try:
        from ..settings_dialog import load_config
        cfg = load_config()
    except Exception:  # noqa: BLE001 - config may be unavailable in some contexts
        cfg = {}
    mirror = cfg.get("download_mirror", "official")
    if mirror == "auto":
        try:
            from ..net_api import _pick_auto_mirror
            mirror = "bmclapi" if "bmclapi" in _pick_auto_mirror() else "official"
        except Exception:
            mirror = "official"
    from .mirror import patch_install_session, set_diag, set_mirror, set_proxy
    set_proxy(cfg.get("download_proxy", "") or None)
    set_mirror(mirror == "bmclapi")
    set_diag(bool(cfg.get("download_diag_log", False)))
    patch_install_session()

    repaired = []
    for version in list_installed_versions(mc_dir):
        try:
            minecraft_launcher_lib.install.install_minecraft_version(
                version, mc_dir, callback=callback
            )
            repaired.append(version)
        except Exception:  # noqa: BLE001 - skip versions we can't repair
            continue
    return repaired


def install_mrpack(mrpack_path: str, mc_dir: str, *, mirror: str = "official",
                   proxy: str = "", callback=None) -> str:
    """Install a ``.mrpack`` Modrinth modpack into a ``.minecraft`` directory.

    A thin wrapper over ``minecraft_launcher_lib.mrpack`` (the library has
    native mrpack support since 8.0). It extracts the pack, downloads the base
    game version + mod loader + every mod into ``mc_dir``, and returns the
    launch version id to pass to ``command.get_minecraft_command``.

    The same bmclapi/proxy redirect as :func:`install_instance` is applied so
    any game-file downloads the pack triggers go through the chosen mirror.
    """
    from .mirror import patch_install_session, set_diag, set_mirror, set_proxy
    set_proxy(proxy or None)
    set_mirror(mirror == "bmclapi")
    set_diag(_diag_enabled())
    patch_install_session()
    minecraft_launcher_lib.mrpack.install_mrpack(
        mrpack_path, mc_dir, callback=callback
    )
    return minecraft_launcher_lib.mrpack.get_mrpack_launch_version(mrpack_path)


def apply_mrpack_to_instance(mrpack_path: str, inst, *, mirror: str = "official",
                             proxy: str = "", callback=None) -> str:
    """把整合包应用到**已有实例**（中轴：二次安装/升级，round-38）。

    对齐主流做法的"对现有实例更新整合包"：
    1. 备份会被覆盖的 mods/config/options.txt → data/backups/<inst_id>_<ts>/
    2. install_mrpack 覆盖安装（mll 原生支持已有目录升级：解压 overrides、
       下载 base game + loader + 全部 mod）
    3. 更新实例元数据：version_id（启动用）、loader/loader_version（从
       mrpack index.json 推断）

    返回新的 launch version id。``inst`` 会被就地更新（调用方负责 _save）。
    """
    import shutil
    import zipfile
    import time as _time

    from ..paths import get_data_dir

    # 1) 备份被覆盖内容
    backup_root = os.path.join(get_data_dir(), "backups")
    backup_dir = os.path.join(backup_root, f"{getattr(inst, 'id', 'inst')}_{int(_time.time())}")
    try:
        for sub in ("mods", "config"):
            src = os.path.join(inst.mc_dir, sub)
            if os.path.isdir(src) and os.listdir(src):
                shutil.copytree(src, os.path.join(backup_dir, sub),
                                dirs_exist_ok=True)
        for name in ("options.txt", "servers.dat"):
            src = os.path.join(inst.mc_dir, name)
            if os.path.isfile(src):
                os.makedirs(backup_dir, exist_ok=True)
                shutil.copy2(src, os.path.join(backup_dir, name))
    except OSError:
        pass  # 备份失败不阻塞应用（尽量备份即可）

    # 2) 覆盖安装
    launch_version = install_mrpack(
        mrpack_path, inst.mc_dir, mirror=mirror, proxy=proxy, callback=callback)

    # 3) 从 mrpack 推断 loader（index.json: {"dependencies": {"minecraft":…, "fabric-loader":…}}）
    try:
        with zipfile.ZipFile(mrpack_path) as z:
            index = _safe_json(z.read("index.json"))
        deps = index.get("dependencies", {}) if isinstance(index, dict) else {}
        mc_ver = deps.get("minecraft", inst.game_version)
        inst.game_version = mc_ver or inst.game_version
        for key in ("fabric-loader", "quilt-loader", "forge", "neoforge", "liteloader"):
            if deps.get(key):
                inst.loader = key.split("-")[0] if key != "neoforge" else "neoforge"
                inst.loader_version = deps[key]
                break
    except Exception:
        pass
    if launch_version:
        inst.version_id = launch_version
    return launch_version


def _safe_json(data: bytes):
    """minified json → dict；容错返回 {}。"""
    import json as _json
    try:
        return _json.loads(data)
    except Exception:
        return {}


def install_liteloader(mc_version: str, mc_dir: str, *,
                       build_version: str = "", tweak_class: str = "",
                       libraries: list | None = None,
                       callback=None) -> str:
    """Install LiteLoader (legacy MC ≤1.12.2) into a game directory.

    LiteLoader isn't a normal mod loader install: we download its jar into the
    version folder and write a custom version json that *inherits* the base
    Minecraft version, adds LiteLoader's tweak class + libraries, and uses
    launchwrapper as the main class. ``minecraft-launcher-lib`` handles the
    inherited base-version install; LiteLoader itself is composed by hand.

    Returns the version id to launch (``<mc>-LiteLoader``).
    """
    import json

    # 1) base game version (inherited by the LiteLoader json)
    minecraft_launcher_lib.install.install_minecraft_version(
        mc_version, mc_dir, callback=callback
    )

    # 2) resolve jar url (snapshots maven repo; try timestamped then SNAPSHOT)
    from ..net_api import liteloader_jar_url, parallel_download_file
    jar_name = f"liteloader-{build_version}.jar" if build_version else "liteloader.jar"
    jar_url = liteloader_jar_url(mc_version, build_version) if build_version else ""
    ver_dir = os.path.join(mc_dir, "versions", f"{mc_version}-LiteLoader")
    os.makedirs(ver_dir, exist_ok=True)
    jar_path = os.path.join(ver_dir, jar_name)

    if jar_url:
        parallel_download_file(jar_url, jar_path, timeout=120)

    # 3) version json: inherits base, launchwrapper main, tweak class
    liteloader_libs = [
        {"name": "net.minecraft:launchwrapper:1.12"},
        {"name": "org.spongepowered:mixin:0.7.4-SNAPSHOT",
         "url": "https://repo.spongepowered.org/maven/"},
        {"name": f"com.mumfrey:liteloader:{build_version or mc_version}-SNAPSHOT",
         "url": "https://repo.mumfrey.com/content/repositories/snapshots/"},
    ]
    if libraries:
        liteloader_libs = libraries
    ver_id = f"{mc_version}-LiteLoader"
    vjson = {
        "id": ver_id,
        "inheritsFrom": mc_version,
        "type": "release",
        "mainClass": "net.minecraft.launchwrapper.Launch",
        "minecraftArguments": "--tweakClass "
        + (tweak_class or "com.mumfrey.liteloader.launch.LiteLoaderTweaker"),
        "libraries": liteloader_libs,
    }
    with open(os.path.join(ver_dir, f"{ver_id}.json"), "w", encoding="utf-8") as f:
        json.dump(vjson, f, ensure_ascii=False, indent=2)

    # 4) let minecraft-launcher-lib resolve the inherited version's libraries
    try:
        from minecraft_launcher_lib.utils import get_required_libraries
        get_required_libraries(ver_id, mc_dir)
    except Exception:  # noqa: BLE001 - best effort; launch will surface real errors
        pass
    return ver_id



def _install_legacyfabric(mc_version, mc_dir, *, loader_version="", callback=None):
    """Install Legacy Fabric loader over a base MC install.

    Legacy Fabric mirrors Fabric's meta API on meta.legacyfabric.net. We
    install the base game, download the loader jar from their maven, and write
    a version json that inherits the base version and adds the loader jar +
    intermediary libraries (same shape Fabric produces).
    """
    import json
    import requests

    minecraft_launcher_lib.install.install_minecraft_version(
        mc_version, mc_dir, callback=callback
    )

    from ..net_api import LEGACY_FABRIC_LOADER_API
    ver = loader_version or ""
    if not ver:
        try:
            r = requests.get(
                LEGACY_FABRIC_LOADER_API + "/" + mc_version,
                headers={"User-Agent": "MC-Launcher/0.1"}, timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            if data:
                ver = data[0]["loader"]["version"]
        except Exception:
            ver = ""
    if not ver:
        raise RuntimeError("Legacy Fabric: no loader version resolved")

    # The version json the legacyfabric meta exposes is directly usable —
    # download it and drop it into versions/<mc>-LegacyFabric/<id>.json
    version_id = f"{mc_version}-LegacyFabric"
    ver_dir = os.path.join(mc_dir, "versions", version_id)
    os.makedirs(ver_dir, exist_ok=True)
    meta_url = f"https://meta.legacyfabric.net/v2/versions/loader/{mc_version}/{ver}/profile/json"
    try:
        r = requests.get(meta_url, headers={"User-Agent": "MC-Launcher/0.1"}, timeout=60)
        r.raise_for_status()
        vjson = r.json()
        vjson["id"] = version_id
        if vjson.get("inheritsFrom") == mc_version:
            with open(os.path.join(ver_dir, f"{version_id}.json"), "w", encoding="utf-8") as f:
                json.dump(vjson, f, indent=2)
        else:
            # fallback: write a minimal inherits json
            minimal = {
                "id": version_id,
                "inheritsFrom": mc_version,
                "mainClass": vjson.get("mainClass", "net.fabricmc.loader.impl.launch.knot.KnotClient"),
                "libraries": vjson.get("libraries", []),
            }
            with open(os.path.join(ver_dir, f"{version_id}.json"), "w", encoding="utf-8") as f:
                json.dump(minimal, f, indent=2)
    except Exception:
        raise RuntimeError("Legacy Fabric: failed to fetch loader profile")
    return version_id


def _install_cleanroom(mc_version, mc_dir, *, installer_url="", java="java", callback=None):
    """Install Cleanroom by running its official installer jar.

    Cleanroom targets 1.12.2. The installer writes its own version entry under
    versions/<mc>-Cleanroom; we then return that id for launch.
    """
    import subprocess
    import tempfile
    from ..net_api import parallel_download_file

    if not installer_url:
        raise RuntimeError("Cleanroom: missing installer URL (need loader_version)")
    tmp_dir = tempfile.mkdtemp(prefix="ac_cleanroom_")
    try:
        jar_path = os.path.join(tmp_dir, "cleanroom-installer.jar")
        parallel_download_file(installer_url, jar_path, timeout=180)
        if callback:
            callback({"stage": "cleanroom", "progress": 0.6, "status": "运行 Cleanroom 安装器…"})
        subprocess.run(
            [java, "-jar", jar_path, "--installClient", mc_dir],
            check=True, capture_output=True, timeout=300,
        )
    finally:
        # round-40 P2 泄漏修复：清理临时安装器（10-100MB jar）
        shutil.rmtree(tmp_dir, ignore_errors=True)
    # Locate the produced version id: <mc>-Cleanroom_<build> or similar
    version_id = f"{mc_version}-Cleanroom"
    vdir = os.path.join(mc_dir, "versions")
    if os.path.isdir(vdir):
        for name in os.listdir(vdir):
            if name.lower().startswith(mc_version.lower()) and "cleanroom" in name.lower():
                if os.path.isfile(os.path.join(vdir, name, f"{name}.json")):
                    version_id = name
                    break
    return version_id


def _install_optifine(mc_version, mc_dir, *, build="", java="java", callback=None):
    """Install OptiFine as a standalone loader entry.

    Installs the base version, then runs the OptiFine installer jar
    (--installDir) so it creates a "<mc>-OptiFine_<build>" version json.
    ``build`` is the OptiFine build label (e.g. HD_U_I5) or "" for latest.
    """
    import subprocess
    import tempfile
    from ..net_api import fetch_optifine_versions, download_optifine_to

    minecraft_launcher_lib.install.install_minecraft_version(
        mc_version, mc_dir, callback=callback
    )
    builds = fetch_optifine_versions(mc_version)
    if not builds:
        raise RuntimeError("OptiFine: no builds for this MC version")
    target = None
    if build:
        for b in builds:
            if build.lower() in b.get("title", "").lower():
                target = b
                break
    if target is None:
        target = builds[0]
    filename = target["_filename"]
    tmp_dir = tempfile.mkdtemp(prefix="ac_optifine_")
    try:
        jar_path = download_optifine_to(filename, tmp_dir)
        if callback:
            callback({"stage": "optifine", "progress": 0.6, "status": "运行 OptiFine 安装器…"})
        subprocess.run(
            [java, "-jar", jar_path, "--installDir", mc_dir],
            check=True, capture_output=True, timeout=300,
        )
    finally:
        # round-40 P2 泄漏修复：清理临时安装器目录
        shutil.rmtree(tmp_dir, ignore_errors=True)
    # produced version id: <mc>-OptiFine_<build>
    version_id = f"{mc_version}-OptiFine_{target.get('title', build)}"
    vdir = os.path.join(mc_dir, "versions")
    if os.path.isdir(vdir):
        for name in os.listdir(vdir):
            if name.lower().startswith(mc_version.lower()) and "optifine" in name.lower():
                if os.path.isfile(os.path.join(vdir, name, f"{name}.json")):
                    version_id = name
                    break
    return version_id
