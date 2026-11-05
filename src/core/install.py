"""Version + mod-loader installation on top of minecraft-launcher-lib.

Key fact we rely on: ``install.install_minecraft_version`` already *verifies and
repairs* an existing install — it only re-downloads missing/corrupt files. That
is exactly the engine behind the "auto-repair" feature: point it at any
``.minecraft`` directory (ours or another launcher's) and it heals it.
"""
from __future__ import annotations

import os
import shutil
import json

import minecraft_launcher_lib

from ..i18n import t
from .java import java25_path, select_java

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


def _start_source_watchdog(meter, callback=None, timeout: float = 30.0) -> None:
    """round-151：下载源 30s 没有任何字节进展 → 自动切到 BMCLAPI。

    只对「慢但没报错」的源生效（请求超时 / 4xx 由 MirrorSession 的逐文件回退和
    ``_retry_with_mirror`` 处理）。字节数来自 round-110 的传输层计量
    （``InstallContext.meter``），比 mll 的文件计数更细。
    """
    if meter is None:
        return
    import threading
    import time
    import weakref

    ref = weakref.ref(meter)
    state = {"total": -1, "ts": time.monotonic(), "switched": False}

    def _loop() -> None:
        while True:
            time.sleep(5.0)
            m = ref()
            if m is None:  # 安装结束，计量器已释放 → 退出
                return
            total, _ = m.snapshot()
            # 关键：立刻丢掉强引用。局部变量会在下一轮 sleep 期间继续持有着
            # 计量器，弱引用永远不为空 → 看门狗线程永不退出（round-151 实测）。
            del m
            now = time.monotonic()
            if total != state["total"]:
                state["total"] = total
                state["ts"] = now
                continue
            if state["switched"] or now - state["ts"] < timeout:
                continue
            from .mirror import set_mirror
            set_mirror(True)
            state["switched"] = True
            print(f"[install] 下载源 {int(timeout)}s 无进展 → 自动切换 BMCLAPI")
            try:
                from ..i18n import t
                msg = t("dl.switch_source")
                if callback:
                    callback.get("setStatus", lambda _s: None)(msg)
            except Exception:  # noqa: BLE001 - 提示失败不影响安装
                pass

    threading.Thread(target=_loop, daemon=True, name="ac-source-watchdog").start()


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
    from .mirror import (InstallCancelled, abort_requested, active_meter,
                         patch_install_session, set_diag, set_mirror, set_proxy)
    if abort_requested():
        # round-172：上一阶段刚被取消，别再开下一段下载。
        raise InstallCancelled("install cancelled by user")
    set_proxy(proxy or None)
    set_mirror(mirror == "bmclapi")
    set_diag(_diag_enabled())
    patch_install_session()
    if mirror != "bmclapi":
        # round-151：官方源「能连但极慢」时 30s 无字节进展自动切 BMCLAPI。
        _start_source_watchdog(active_meter(), callback)

    # round-164：补全写盘根必须与启动解析根同一口径。外来版本隔离实例
    # （mc_dir 就是 versions/<id> 目录）如果按 mc_dir 安装，mll 会写出
    # <mc>/versions/<id>/<id>.json 的嵌套目录，而启动只认 <mc>/<id>.json
    # ——体检/启动永远判定「缺失」，玩家看到「补不完」。layout_of 在
    # flat/iso 布局下把根上移两层，安装产物正好落在真实 json 位置。
    from ..instances import layout_of
    mc_dir = layout_of(inst).get("install_dir") or inst.mc_dir
    loader = inst.loader if inst.loader in SUPPORTED_LOADERS else "vanilla"
    if loader == "cleanroom":
        # Cleanroom 0.7.x 的安装器自己要求 Java 25，但它也提供
        # --provision-java：只要用来「运行安装器 jar」的 JVM 足够新（17+），
        # 目标 Java 25 可以由安装器自己下载。之前这里只走
        # select_java(need=25)，机器没有 25 时就退化成 21/裸 java，
        # 无法保证安装器能跑；现在统一由 cleanroom_installer_java() 决策。
        java = cleanroom_installer_java()
        if not java:
            raise RuntimeError(t("err.cleanroom_installer_java"))
    else:
        java = select_java(inst.game_version, java_auto=java_auto,
                           user_path=java_path, need_override=0)
    java = java or "java"

    def _retry_with_mirror(fn):
        """round-150：官方源失败 → 换 BMCLAPI 再试一次。

        实测（国内网络）maven.minecraftforge.net 的 maven-metadata.xml 读超时 +
        Forge 库下载也不稳定；官方源下 ``ml.install`` 会在写版本 json 之前就抛错，
        用户看到的就是「每次重启后打开都在补全版本」。
        """
        try:
            return fn()
        except Exception:
            if mirror == "bmclapi" or abort_requested():
                # round-172：用户取消不是「源不好」——绝不能换源把整个安装
                # 再跑一遍（那正是「点了取消还在下载」的观感来源）。
                raise
            set_mirror(True)
            try:
                return fn()
            finally:
                set_mirror(False)

    # Persist the resolved loader version so later runs are deterministic.
    # Only lib-managed loaders (fabric/forge/quilt/neoforge) expose
    # get_latest_loader_version; the custom ones resolve inside their own
    # install functions when loader_version is empty.
    if loader in ("fabric", "forge", "quilt", "neoforge") and not inst.loader_version:
        ml = minecraft_launcher_lib.mod_loader.get_mod_loader(loader)
        inst.loader_version = _retry_with_mirror(
            lambda: ml.get_latest_loader_version(inst.game_version))

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
        # Cleanroom: Forge continuation fork (1.12.2 on Java 25 + LWJGL3).
        # Official 0.7.x installer does the whole job (it writes its own version
        # json into versions/ and can provision the Java 25 runtime).
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
    return _retry_with_mirror(lambda: ml.install(
        inst.game_version,
        mc_dir,
        loader_version=inst.loader_version or None,
        callback=callback,
        java=java,
    ))


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


def find_installed_loader(mc_dir: str, loader: str, game_version: str) -> str | None:
    """在 versions/ 下找该加载器对应当前 MC 版本的已安装版本 id（round-163）。

    多数加载器的版本 id 自带 MC 版本（``fabric-loader-0.15.11-1.20.1`` /
    ``1.20.1-forge-47.2.0``），子串匹配即可；但 NeoForge 1.21+ 的 id 是
    ``neoforge-21.1.0``、Cleanroom 是 ``Cleanroom-0.7.12-alpha``——都不含
    MC 版本，只能读版本 json 的 ``inheritsFrom`` 判定。

    这是启动「已安装」判定与体检「完整性」层的共同真理源；放在 install.py
    避免 instance_health / launch 互相 import 成环。
    """
    loader = (loader or "").strip().lower()
    if not mc_dir or not loader or not os.path.isdir(mc_dir):
        return None
    vdir = os.path.join(mc_dir, "versions")
    if not os.path.isdir(vdir):
        return None
    try:
        names = sorted(os.listdir(vdir))
    except OSError:
        return None
    for name in names:
        low = name.lower()
        if loader not in low:
            continue
        # 子串撞名防护：*forge* 会命中 neoforge、*fabric* 会命中 legacyfabric。
        if loader == "forge" and "neoforge" in low:
            continue
        if loader == "fabric" and "legacyfabric" in low:
            continue
        jp = os.path.join(vdir, name, f"{name}.json")
        if not os.path.isfile(jp):
            continue
        if game_version and game_version in name:
            return name
        try:
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if str(data.get("inheritsFrom") or "") == game_version:
            return name
    return None


def cleanroom_installer_java() -> str | None:
    """运行 Cleanroom 安装器 jar 的 JVM（与游戏实际使用的 Java 25 分离）。

    优先 Java 25；没有则取「最高且 >=17」的已装 JDK——安装器 jar 自身只
    需要现代 JVM，目标 Java 25 交给安装器的 ``--provision-java`` 下载到
    ``~/.cleanroom/java``。一个 Java 都没有时返回 None，由调用方给出明确
    中文错误（round-163）。
    """
    from .java import java25_path, scan_javas
    j25 = java25_path()
    if j25:
        return j25
    javas = [j for j in scan_javas(deep=True) if int(j.get("major") or 0) > 0]
    modern = [j for j in javas if int(j["major"]) >= 17]
    if modern:
        modern.sort(key=lambda j: (int(j["major"]), bool(j.get("is_64bit", True)),
                                   j.get("path", "")))
        return modern[-1]["path"]
    if javas:
        javas.sort(key=lambda j: (int(j["major"]), j.get("path", "")))
        return javas[-1]["path"]
    return None


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
    # P0（横向审计）：mll 的 inherit_json 对标量是「子覆盖父」。此前只写
    # --tweakClass，父版本的 --username/--uuid/--accessToken/--gameDir/
    # --assetsDir/--assetIndex 全被覆盖丢失 → 客户端秒退。另外 mll 在没有
    # "jar" 键时用子 id 拼主 jar（versions/<ver_id>/<ver_id>.jar 并不存在），
    # classpath 里会缺原版主 jar。标准做法：完整继承父串后追加 tweakClass，
    # 并显式把主 jar 指回原版版本。
    parent_json_path = os.path.join(mc_dir, "versions", mc_version,
                                    f"{mc_version}.json")
    try:
        with open(parent_json_path, "r", encoding="utf-8") as _pf:
            parent_args = str(json.load(_pf).get("minecraftArguments") or "").strip()
    except (OSError, ValueError):
        parent_args = ""
    if not parent_args:
        raise RuntimeError(
            "LiteLoader: 读不到原版版本的 minecraftArguments，"
            "生成的启动参数会让客户端秒退（请先完整安装该版本）"
        )
    _tweak = tweak_class or "com.mumfrey.liteloader.launch.LiteLoaderTweaker"
    vjson = {
        "id": ver_id,
        "inheritsFrom": mc_version,
        "type": "release",
        "jar": mc_version,
        "mainClass": "net.minecraft.launchwrapper.Launch",
        "minecraftArguments": parent_args + " --tweakClass " + _tweak,
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
    import re
    import subprocess
    import tempfile
    from ..net_api import (CLEANROOM_LATEST_FALLBACK, cleanroom_installer_url,
                           fetch_cleanroom_builds, parallel_download_file)

    # The wizard may pass a bare build version, or nothing at all when the
    # build list failed to load. Resolve a real installer URL here instead of
    # aborting with "missing installer URL" (round-126).
    if installer_url and "://" not in installer_url:
        installer_url = cleanroom_installer_url(installer_url.strip())
    if not installer_url:
        try:
            builds = fetch_cleanroom_builds()
            installer_url = (builds[0]["_installer_url"] if builds
                             else cleanroom_installer_url(CLEANROOM_LATEST_FALLBACK))
        except Exception:
            installer_url = cleanroom_installer_url(CLEANROOM_LATEST_FALLBACK)
    _m = re.search(r"cleanroom-(\d[\w.\-]*)-installer\.jar", installer_url)
    build = _m.group(1) if _m else ""
    # Cleanroom's version json inherits from vanilla 1.12.2, so the base has to
    # be present before its installer merges the profile in.
    minecraft_launcher_lib.install.install_minecraft_version(
        mc_version, mc_dir, callback=callback
    )
    tmp_dir = tempfile.mkdtemp(prefix="ac_cleanroom_")
    cleanroom_java = False
    try:
        jar_path = os.path.join(tmp_dir, "cleanroom-installer.jar")
        try:
            parallel_download_file(installer_url, jar_path, timeout=180)
        except Exception:
            from .mirror import abort_requested
            if abort_requested():
                raise  # round-172：取消时不再换另一个主机重下安装器
            # GitHub release vs Maven mirror: retry on the other host before
            # surfacing the download error (CN networks often block one).
            alt = cleanroom_installer_url(
                build or CLEANROOM_LATEST_FALLBACK,
                maven=("repo.cleanroommc.com" not in installer_url))
            parallel_download_file(alt, jar_path, timeout=180)
        # round-143 修复「启动失败：'dict' object is not callable」：
        # ProgressWorker 传入的 callback 是 mll 风格 dict（setStatus/...），
        # 此前直接 callback({...}) 把 dict 当函数调 → Cleanroom 实例首启必炸。
        if callable(callback):
            callback({"stage": "cleanroom", "progress": 0.6,
                      "status": "运行 Cleanroom 安装器…"})
        elif isinstance(callback, dict):
            st = callback.get("setStatus")
            if callable(st):
                st("运行 Cleanroom 安装器…")
        # 0.7.x installer CLI: `client -d <dir> --version <id> -y --json`.
        # It insists on Java 25; `--provision-java` fetches one into
        # ~/.cleanroom/java when the machine has none (round-126: the old
        # `--installClient <dir>` call is from the pre-0.7 Forge-style
        # installer and made every Cleanroom install fail).
        # javaw 也能跑 jar，但 stderr/stdout 为空会让安装失败只剩「no output」。
        # 安装器是控制台程序，统一归一为同目录 java.exe 以保留错误详情。
        from .mirror import run_cancellable
        if java.lower().endswith("javaw.exe"):
            _java_exe = os.path.join(os.path.dirname(java), "java.exe")
            if os.path.isfile(_java_exe):
                java = _java_exe
        cmd = [java, "-jar", jar_path, "client", "-d", mc_dir, "-y",
               "--json", "--quiet"]
        if build:
            cmd += ["--version", build]
        j25 = java25_path()
        if j25:
            cmd += ["--java", j25]
        else:
            cmd += ["--provision-java"]
            cleanroom_java = True
            # round-163：让玩家知道「为什么这一步很慢」——安装器会自行下载
            # 一个 Java 25 到 ~/.cleanroom/java。
            if callback:
                st = callback.get("setStatus") if isinstance(callback, dict) else None
                if callable(st):
                    st(t("launch.cleanroom_provision"))
        # round-172：安装器自己会下载库 / 可用 --provision-java 下载 Java 25，
        # 必须走可取消版本，否则「取消启动」停不下它。
        r = run_cancellable(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            # Pre-0.7 builds still use the Forge-style installer, which
            # installs into its working directory.
            r2 = run_cancellable([java, "-jar", jar_path, "--installClient"],
                                 cwd=mc_dir, capture_output=True, text=True,
                                 timeout=900)
            if r2.returncode != 0:
                detail = ((r.stderr or "") + (r.stdout or "")).strip()
                raise RuntimeError(
                    "Cleanroom installer failed (exit "
                    f"{r.returncode}): {detail[-400:] or 'no output'}")
    finally:
        # round-40 P2 泄漏修复：清理临时安装器（10-100MB jar）
        shutil.rmtree(tmp_dir, ignore_errors=True)
    if cleanroom_java:
        # The freshly provisioned JRE lives in ~/.cleanroom/java; drop the
        # scan cache so select_java() sees it on the very next launch.
        try:
            from .java import reset_scan_cache
            reset_scan_cache()
        except Exception:
            pass
    # Locate the produced version id: "Cleanroom-<build>" (0.7.x) or
    # "<mc>-Cleanroom" (legacy installer) — match any cleanroom folder.
    version_id = f"{mc_version}-Cleanroom"
    vdir = os.path.join(mc_dir, "versions")
    if os.path.isdir(vdir):
        for name in os.listdir(vdir):
            if "cleanroom" not in name.lower():
                continue
            if os.path.isfile(os.path.join(vdir, name, f"{name}.json")):
                version_id = name
                if build and build.lower() in name.lower():
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
        # round-143：同 Cleanroom 分支 —— dict 回调不能当函数调用。
        if callable(callback):
            callback({"stage": "optifine", "progress": 0.6, "status": "运行 OptiFine 安装器…"})
        elif isinstance(callback, dict):
            st = callback.get("setStatus")
            if callable(st):
                st("运行 OptiFine 安装器…")
        from .mirror import run_cancellable
        run_cancellable(
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
