"""Launch orchestration: build options, assemble the command, spawn Minecraft.

Re-exports ``find_java`` for Settings backward-compat. The heavy lifting
(install + loader) lives in ``core.install``; here we only compose the launch
options, ask minecraft-launcher-lib for the command line, and spawn the process
with the Java console hidden on Windows. Game output is streamed to a log file
so the future crash-analyzer can read it.
"""
from __future__ import annotations

import os
import sys
import subprocess
import threading

from .core.java import find_java, select_java, required_java_major
from .core.install import install_instance
from .paths import get_data_dir
from .brand import APP_NAME
from .core.authlib import ensure_authlib

__all__ = ["find_java", "build_options", "get_command", "launch_process", "launch_instance",
           "run_hook_cmd", "resolve_game_dir", "parse_game_args"]

# round-55 JVM 参数预设「Aikar 优化」组（对齐主流预设里社区推荐的 Aikar 调优，
# 多数整合包作者亦沿用此组）。带引号的参数交给 JVM 前由 shlex 保持完整。
_AIKAR_FLAGS = [
    "-XX:+UseG1GC",
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:MaxGCPauseMillis=40",
    "-XX:G1NewSizePercent=20",
    "-XX:G1ReservePercent=20",
    "-XX:MaxTenuringThreshold=1",
    "-XX:G1MixedGCLiveThresholdPercent=50",
    "-XX:+ParallelRefProcEnabled",
    "-XX:+DisableExplicitGC",
    "-XX:+AlwaysPreTouch",
]


def parse_game_args(text: str) -> tuple[str | None, str | None, list[str]]:
    """把「游戏附加参数」字符串拆成 (server, port, extra)。

    ``--server <ip>`` / ``--server=<ip>`` 与 ``--port <p>`` / ``--port=<p>``
    抽出交给 minecraft-launcher-lib 的 options（它会正确追加 ``--server/--port``
    两段式启动参数），其余令牌原样返回，由调用方追加到游戏命令末尾（MC 接受
    尾随参数，与主流的「游戏附加参数」行为一致）。
    """
    import shlex
    try:
        toks = shlex.split(text or "")
    except ValueError:
        toks = (text or "").split()  # 引号不闭合时降级
    server: str | None = None
    port: str | None = None
    extra: list[str] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok.startswith("--server="):
            server = tok.split("=", 1)[1]
            i += 1
            continue
        if tok == "--server" and i + 1 < len(toks):
            server = toks[i + 1]
            i += 2
            continue
        if tok.startswith("--port="):
            port = tok.split("=", 1)[1]
            i += 1
            continue
        if tok == "--port" and i + 1 < len(toks):
            port = toks[i + 1]
            i += 2
            continue
        extra.append(tok)
        i += 1
    return server, port, extra


def resolve_game_dir(inst, settings: dict) -> str:
    """版本隔离 / 自定义游戏目录解析（对齐主流「版本隔离」三选项）。

    - 默认：游戏数据读写 <mc_dir>（.minecraft，各版本共享存档/模组）；
    - 版本隔离：读写 <mc_dir>/versions/<version_id>（每版本独立存档/模组）；
    - 自定义目录：用玩家指定的路径。相对路径按 <mc_dir>/<值> 解析（round-57
      确定性修复：之前原样 normpath，相对路径会飘移到启动器进程 CWD 下）。
    实例级 ``isolation`` 为空时回退全局 ``version_isolation``。返回路径保证存在。
    """
    iso = (getattr(inst, "isolation", "") or "").strip() \
        or (settings.get("version_isolation") or "default")
    if iso == "isolated":
        sub = inst.version_id or inst.game_version
        # round-78 其他启动器版本隔离（导入）：mc_dir 本身就是该版本
        # 的隔离目录，真实 json 在 mc_dir/<sub>.json。再套 versions/<sub> 会让
        # options.txt/存档等写到不存在的嵌套目录（同 instances.game_dir 规则）。
        try:
            if os.path.isfile(os.path.join(inst.mc_dir, f"{sub}.json")):
                return inst.mc_dir
        except OSError:
            pass
        return os.path.join(inst.mc_dir, "versions", sub)
    if iso == "custom":
        custom = (getattr(inst, "game_dir_override", "") or "").strip()
        if custom:
            if not os.path.isabs(custom):
                return os.path.join(inst.mc_dir, os.path.normpath(custom))
            return os.path.normpath(custom)
    return inst.mc_dir


def run_hook_cmd(cmd: str, cwd: str = "") -> None:
    """执行一条玩家自定义的「启动后/退出后命令」，不阻塞游戏进程。

    整串交给系统 shell（Windows 用 cmd /c 以支持 &&、路径带空格等写法；
    与主流的启动后命令语义一致）。失败静默——钩子绝不影响游戏。
    """
    cmd = (cmd or "").strip()
    if not cmd:
        return
    try:
        subprocess.Popen(
            cmd,
            cwd=cwd or None,
            shell=sys.platform == "win32",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
    except Exception:  # noqa: BLE001 - 钩子失败不影响启动器
        pass


def build_options(
    username: str,
    uuid: str,
    token: str,
    *,
    mc_dir: str,
    java: str,
    ram_mb: int = 4096,
    jvm_args: str = "",
    res=None,
    launcher_name: str = APP_NAME,
    launcher_version: str = "0.1",
    authlib_injector: str | None = None,
    yggdrasil_server: str | None = None,
    renderer: str = "auto",
    perf_g1gc: bool = True,
    perf_disable_explicit_gc: bool = False,
    # round-55 启动高级设置（对齐主流启动游戏/版本设置）：
    game_dir: str | None = None,   # 运行时游戏目录（版本隔离/自定义目录以 mll 的
                                   # gameDirectory 下发）；None = 默认 mc_dir
    jvm_preset: str = "default",   # default/aikar/custom 三档（custom 只看 jvm_args）
    server: str | None = None,     # --server 直连服务器 IP
    port: str | None = None,       # --port 直连端口
) -> dict:
    """Build the MinecraftOptions dict for command.get_minecraft_command."""
    # round-39 P2-1 加固：ram_mb 非法/过小 → 兜底 2048；确保 Xms ≤ Xmx
    try:
        ram_mb = max(int(ram_mb or 0), 1024)
    except (TypeError, ValueError):
        ram_mb = 2048
    xms = min(max(ram_mb // 2, 512), ram_mb)
    opts: dict = {
        "username": username,
        "uuid": uuid,
        "token": token,
        "executablePath": java,
        "gameDirectory": game_dir or mc_dir,
        "launcherName": launcher_name,
        "launcherVersion": launcher_version,
        "jvmArguments": [f"-Xmx{ram_mb}M", f"-Xms{xms}M"],
    }
    # round-55 JVM 参数预设（对齐主流「JVM 参数」预设下拉）：
    #   default = 不注入额外调优；aikar = 注入社区推荐 Aikar 组（默认即此组）；
    #   auto  = 智能推荐（round-80）：按内存自动选组——富裕给完整 Aikar，
    #           小内存给轻量 G1GC 组（避免 AlwaysPreTouch 等预占内存挤压堆）；
    #   custom = 只用玩家在 jvm_args 里手填的。实例级 jvm_args 始终叠加在预设之上。
    if jvm_preset == "aikar":
        opts["jvmArguments"] += list(_AIKAR_FLAGS)
    elif jvm_preset == "auto":
        if ram_mb >= 8192:
            opts["jvmArguments"] += list(_AIKAR_FLAGS)
        else:
            opts["jvmArguments"] += [
                "-XX:+UseG1GC",
                "-XX:MaxGCPauseMillis=40",
                "-XX:+UseStringDeduplication",
                "-XX:+DisableExplicitGC",
            ]
    if jvm_args and jvm_args.strip():
        # round-34 加固：shlex.split 正确解析带引号的参数（-Dfoo="a b" 等），
        # 之前 .split() 会把引号内空格拆成多个参数。
        import shlex
        try:
            opts["jvmArguments"] += shlex.split(jvm_args)
        except ValueError:
            opts["jvmArguments"] += jvm_args.split()  # 引号不闭合时降级
    # round-53 实例级渲染器（对齐主流「版本设置→渲染器」）：
    #   software = 软件 OpenGL 兜底（老显卡 / 虚拟机黑屏 / 缺驱动）；
    #   legacy   = 旧驱动兼容（关共享上下文，LWJGL2 版本防切换卡死）。
    # 两项都是纯 JVM 属性，1.13+ 注入也被忽略，安全。
    if renderer == "software":
        opts["jvmArguments"].append("-Dorg.lwjgl.opengl.Display.allowSoftwareOpenGL=true")
    elif renderer == "legacy":
        opts["jvmArguments"].append("-Dorg.lwjgl.opengl.Display.enableSharedContext=false")
    # round-53 实例级实验性 GC（对齐主流「性能」高级设置）：
    # 默认开 G1GC 参数组（多数整合包作者推荐），关显式 GC 可减少突发停顿。
    # round-56 修重：preset=aikar 时该组 G1GC 参数已在 _AIKAR_FLAGS 注入，
    # 再注入会整组重复（JVM 后者覆盖前者、不崩，但命令冗余且易误导调参）。
    # 此时仅补 Aikar 组缺失的 UseStringDeduplication，语义等价不丢功能。
    if perf_g1gc and jvm_preset not in ("aikar", "auto"):
        opts["jvmArguments"] += [
            "-XX:+UseG1GC",
            "-XX:+UnlockExperimentalVMOptions",
            "-XX:+UseStringDeduplication",
            "-XX:G1NewSizePercent=20",
            "-XX:G1ReservePercent=20",
            "-XX:MaxGCPauseMillis=40",
        ]
    elif perf_g1gc and jvm_preset == "aikar":
        opts["jvmArguments"].append("-XX:+UseStringDeduplication")
    # round-56 修重：_AIKAR_FLAGS 已含 -XX:+DisableExplicitGC，aikar 预设下跳过。
    if perf_disable_explicit_gc and jvm_preset not in ("aikar", "auto"):
        opts["jvmArguments"].append("-XX:+DisableExplicitGC")
    # External / third-party (Yggdrasil) login: route auth through the
    # authlib-injector javaagent so Minecraft talks to the custom server.
    if authlib_injector and yggdrasil_server:
        import json

        cfg_path = os.path.join(os.path.dirname(authlib_injector), "authlib-injector-config.json")
        # round-57 加固：原子写（tmp + os.replace），避免启动途中崩溃留下半个
        # JSON，下次启动 authlib 读坏配置导致外置登录失效（项目约束：配置原子写）。
        try:
            _payload = json.dumps(
                {
                    "authServer": f"{yggdrasil_server.rstrip('/')}/authserver",
                    "sessionServer": f"{yggdrasil_server.rstrip('/')}/sessionserver",
                    "servicesServer": yggdrasil_server.rstrip("/"),
                },
                indent=2,
            )
            _tmp = cfg_path + ".tmp"
            with open(_tmp, "w", encoding="utf-8") as f:
                f.write(_payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(_tmp, cfg_path)
        except OSError:
            # 原子写失败（只读目录等）退回首写，authlib 仍尽力可用
            try:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(_payload)
            except OSError:
                pass
        opts["jvmArguments"].append(f"-javaagent:{authlib_injector}={cfg_path}")
    if res:
        # round-39 P2-1 加固：res 元组缺项/非法 → 跳过自定义分辨率（不传 None）
        try:
            w, h = int(res[0]), int(res[1])
            if w > 0 and h > 0:
                opts["customResolution"] = True
                opts["resolutionWidth"] = str(w)
                opts["resolutionHeight"] = str(h)
        except (TypeError, ValueError, IndexError):
            pass
    # round-55 服务器直连：minecraft-launcher-lib 会在命令尾部追加
    # ``--server <ip> [--port <p>]``，让游戏启动后直接进指定服务器。
    if server:
        opts["server"] = server
        if port:
            opts["port"] = str(port)
    return opts


def versions_root(inst, version: str = "") -> str:
    """mll 解析版本 json 用的 .minecraft 根目录（round-78 对齐主流解析器）。

    round-82 起按启动格式（inst.format / detect_format）分流：
    - iso（版本隔离）→ mc_dir 本身就是隔离目录，真实 json 扁平躺在
      mc_dir/<version>.json，mll 固定按 ``<root>/versions/<id>/<id>.json`` 解析，
      把解析根指到 mc_dir 的上级两层（原 .minecraft），让 mll 直接食用玩家真实
      json——重建、伪造一律不发生（即「按他的格式启动」）。
    - 其余布局（原版共享 / AC 自建 / 其它整合布局的 .minecraft）
      根即 mc_dir；`<mc>/<version>.json` 特征兜底自适应，改装/奇怪目录也尽量
      按外来隔离式扁平布局解析（round-78）。
    """
    mc = getattr(inst, "mc_dir", "")
    if not mc:
        return ""
    version = version or getattr(inst, "version_id", "") or getattr(inst, "game_version", "")
    try:
        from .instances import detect_format
        if detect_format(inst) == "iso":
            return os.path.dirname(os.path.dirname(os.path.normpath(mc)))
    except Exception:  # noqa: BLE001 - 检测失败退回特征兜底
        pass
    if version and os.path.isfile(os.path.join(mc, f"{version}.json")):
        return os.path.dirname(os.path.dirname(os.path.normpath(mc)))
    return mc


def _apply_game_window_mode(mc_dir: str, window_mode: str) -> None:
    """Make the launched Minecraft honor the chosen window mode.

    ``minecraft-launcher-lib`` exposes no fullscreen option, so we write the
    game's own ``options.txt`` ``fullscreen`` flag. For MC 1.20+ the
    fullscreen state is also stored in ``options_fullscreen.txt``.
    Vanilla MC has no native borderless fullscreen (needs OptiFine/Sodium),
    so ``borderless`` falls back to ordinary fullscreen.
    """
    if not mc_dir or not os.path.isdir(mc_dir):
        return
    full = window_mode in ("fullscreen", "borderless")
    target_files = ["options.txt", "options_fullscreen.txt"]
    for fname in target_files:
        fpath = os.path.join(mc_dir, fname)
        data: dict[str, str] = {}
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.rstrip("\n")
                        if ":" in line:
                            k, _, v = line.partition(":")
                            data[k] = v
            except OSError:
                data = {}
        data["fullscreen"] = "true" if full else "false"
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                for k, v in data.items():
                    f.write(f"{k}:{v}\n")
        except OSError:
            pass


def get_command(version: str, mc_dir: str, options: dict) -> list[str]:
    """Return the java command line for a version via minecraft-launcher-lib."""
    import minecraft_launcher_lib

    return minecraft_launcher_lib.command.get_minecraft_command(version, mc_dir, options)


def _version_has_natives(version: str, mc_dir: str) -> bool:
    """只读判断一个版本（含继承）是否声明了原生库（natives）。

    Java.library.path 目录只在确有 natives 依赖时才需要解压；原版 1.12.2-
    用 minecraftArguments 的版本同样带 natives。返回 False 时启动方不用建
    natives 目录、也无需注入 --nativesDirectory。
    """
    import json as _json
    try:
        with open(os.path.join(mc_dir, "versions", version, f"{version}.json"),
                  "r", encoding="utf-8") as _f:
            data = _json.load(_f)
    except OSError:
        return False
    if data.get("inheritsFrom"):
        # 继承父版本：父版本的 natives 也不能漏（粗略：只要继承就按有 natives 处理）
        return True
    return any(isinstance(lib, dict) and bool(lib.get("natives")) for lib in data.get("libraries", []))


def _classpath_entries(cmd: list[str]) -> list[str]:
    """抽出 -cp 之后的所有 classpath 条目。"""
    for i, a in enumerate(cmd):
        if a == "-cp" and i + 1 < len(cmd):
            return [e for e in cmd[i + 1].split(os.pathsep) if e]
    return []


def _missing_classpath(cmd: list[str]) -> list[str]:
    """返回 classpath 中磁盘上不存在的条目。"""
    return [e for e in _classpath_entries(cmd) if not os.path.isfile(e)]


def _needs_repair(missing: list[str]) -> bool:
    """仅缺 natives 分类器 dll jar 的缺失可在启动前安全忽略。

    这类 jar 的唯一作用是用压缩包携带 .dll，运行时 dll 已被 _prepare_natives
    解压到 java.library.path，JVM 并不从 classpath 加载它。除此之外的任何缺失
    （lwjgl-platform 基础包、游戏主库等）都会让 JVM 一起动就崩 → 必须修复。
    """
    if not missing:
        return False
    import re as _re
    purely_natives = [
        p for p in missing
        if _re.search(r"-natives-[A-Za-z0-9_.-]+\.jar$", os.path.basename(p))
    ]
    return len(purely_natives) < len(missing)


def _prepare_natives(version: str, mc_dir: str, *, on_repair: callable | None = None) -> str | None:
    """启动前把原生库解压到 java.library.path 指向的目录（对齐主流做法）。

    关键：minecraft-launcher-lib 的 :func:`command.get_minecraft_command` 只拼
    classpath、**从不解压 natives**——LWJGL/OpenAL 的 dll 缺省会触发
    ``NativeLibraryNotFound``，游戏进程立即以 exit 1 崩溃（正是「启动即秒退」的主因）。
    这里在每次启动前显式 ``extract_natives`` 到 ``versions/<version>/natives``，
    并把该目录通过 ``options["nativesDirectory"]`` 回传给命令构造，保证
    ``-Djava.library.path`` 与真实解压位置一致。

    返回 natives 目录；无 natives 依赖或解压失败返回 None（调用方回退 mll 默认）。
    """
    import minecraft_launcher_lib.natives as _nat

    if not _version_has_natives(version, mc_dir):
        return None
    natives_dir = os.path.join(mc_dir, "versions", version, "natives")
    try:
        os.makedirs(natives_dir, exist_ok=True)
        # extract_natives 幂等：覆盖同名 dll，仅当某些 jar 缺失时才抛错
        _nat.extract_natives(version, mc_dir, natives_dir)
        return natives_dir
    except Exception as _e:  # noqa: BLE001 - 缺 natives jar/损坏 → 走补全
        if on_repair is not None:
            try:
                on_repair()
            except Exception:  # noqa: BLE001
                pass
        try:
            os.makedirs(natives_dir, exist_ok=True)
            _nat.extract_natives(version, mc_dir, natives_dir)
            return natives_dir
        except Exception:  # noqa: BLE001 - 补全仍失败 → 回退，启动让 crash 分析兜底
            return None


def _emit_step(callback, key: str) -> None:
    """向进度回调报告启动阶段（对齐主流的「启动检查步骤」）。

    mll 的 CallbackDict 只认 setStatus/setProgress/setMax；这里额外读
    可选的 ``setStep`` 键（ProgressWorker 已注入），让对话框能逐行点亮
    「检查环境 → 安装版本 → 补齐库 → 预检 → 启动」。失败静默，不拦启动。
    """
    if callback and hasattr(callback, "get"):
        try:
            f = callback.get("setStep")
            if callable(f):
                f(key)
        except Exception:  # noqa: BLE001
            pass


def _priority_bits(priority: str) -> int:
    """Map a config priority value to Windows process-creation flag bits.

    Uses the native CreateProcess flags directly (no psutil dependency):
    CREATE_HIGH_PRIORITY_CLASS (0x80) / CREATE_REALTIME_PRIORITY_CLASS
    (0x100). Values are OR-safe with CREATE_NO_WINDOW. Non-Windows and
    unknown values return 0 (normal priority).
    """
    if sys.platform != "win32":
        return 0
    return {
        "high": 0x00000080,
        "realtime": 0x00000100,
    }.get(priority, 0)


def launch_process(cmd: list[str], mc_dir: str, log_path: str | None = None,
                   priority: str = "normal"):
    """Spawn Minecraft. Hides the Java console on Windows (CREATE_NO_WINDOW).

    When ``log_path`` is given, stdout+stderr go to that file (no pipe buffer).
    Otherwise a daemon thread drains the pipes so Minecraft never blocks.
    ``priority`` ("normal"/"high"/"realtime", round-69) is applied through the
    Windows creation flags at spawn time. Returns (proc, log_file_or_None).
    """
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creationflags |= _priority_bits(priority)

    logf = None
    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            logf = open(log_path, "w", encoding="utf-8", errors="replace")
        except OSError:
            logf = None

    if logf is not None:
        proc = subprocess.Popen(
            cmd, cwd=mc_dir, stdout=logf, stderr=subprocess.STDOUT, creationflags=creationflags
        )
        return proc, logf

    proc = subprocess.Popen(
        cmd,
        cwd=mc_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        text=True,
    )

    def _drain(stream) -> None:
        try:
            for _ in stream:
                pass
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_drain, args=(proc.stdout,), daemon=True).start()
    return proc, None


def launch_instance(
    inst,
    account: dict,
    settings: dict,
    *,
    callback=None,
    log_dir: str | None = None,
    # round-83 服务器收藏一键直连：非空时覆盖 game_args / 全局里的 --server/--port，
    # 用于「收藏服务器 → 用当前实例直连启动」而不用手改实例的附加参数。
    server_override: str | None = None,
    port_override: str | None = None,
):
    """Install (if needed) + assemble command + spawn. Returns (proc, log_path)."""
    # round-41 玩家视角加固：实例目录被玩家删了 / 移动后点启动——
    # 给友好中文错误而不是裸 FileNotFoundError（玩家看不懂原始异常）。
    if not os.path.isdir(inst.mc_dir):
        from .i18n import t as _t
        raise RuntimeError(
            _t("err.launch_missing_dir", default="实例目录不存在（{path}）——可能已被移动或删除。请删除该实例后重新扫描导入。", path=inst.mc_dir)
        )
    # round-52 启动阶段上报：检查启动环境（给启动进度对话框点第 1 步）。
    _emit_step(callback, "check")
    # round-48 共享 libraries 去重：存量实例的 libraries 还是独立实际目录的话，
    # 启动前一次性合并进全局共享池并改为目录联接。external（链接他人目录）实例
    # 绝不改用户真实文件。失败只退回独立目录，不影响启动。
    if not getattr(inst, "external", False):
        try:
            from .core.shared_libs import ensure_shared_libraries
            ensure_shared_libraries(inst.mc_dir)
        except Exception:  # noqa: BLE001
            pass
    # Per-instance Java (instance.java_path) wins over the global setting; the
    # global setting wins over auto-detect. This lets one instance pin a JDK
    # without disturbing the launcher-wide default.
    inst_java = (getattr(inst, "java_path", "") or "").strip()
    user_java_global = (settings.get("java_path") or "").strip()
    user_java = inst_java or user_java_global
    # 版本已完整安装时跳过 install/repair，零下载直接启动（round-34 修复）：
    # ⚠️ 之前对 AC 创建的加载器实例（version_id 空）检查基础版 json——
    # 装了 Fabric/Forge 后 `versions/<mcver>/<mcver>.json` 必然存在，导致
    # 二次启动跳过安装并用 game_version（原版）启动，加载器静默失效。
    # 正确判据：加载器实例必须匹配 <loader> 相关的 version json
    # （fabric-loader-0.15.11-1.20.1 / 1.20.1-forge-47.2.0 等）。
    import glob as _glob
    import os as _os
    _loader = (getattr(inst, "loader", "") or "").strip().lower()
    _skip = False
    installed = inst.version_id or inst.game_version
    if inst.version_id:
        # 基线版本隔离布局：导入实例为隔离目录时 mc_dir 直接就是 versions/<id> 目录，真实 json 躺在
        # mc_dir/<id>.json —— 两种布局任一命中都算「已安装」，直接按玩家的
        # 真实 json 启动；绝不往用户实例里塞假补全。
        _skip = _os.path.isfile(_os.path.join(
            inst.mc_dir, "versions", inst.version_id, f"{inst.version_id}.json")) \
            or _os.path.isfile(_os.path.join(
            inst.mc_dir, f"{inst.version_id}.json"))
    elif _loader and _loader != "vanilla":
        # AC 创建加载器实例：找 <loader>-<...>-<mcver> 的 version json
        installed = None
        _pat = _os.path.join(inst.mc_dir, "versions", f"*{_loader}*{inst.game_version}*")
        for _d in sorted(_glob.glob(_pat)):
            _base = _os.path.basename(_d)
            if _os.path.isfile(_os.path.join(_d, f"{_base}.json")):
                installed = _base
                break
        _skip = installed is not None
        installed = installed or inst.game_version
    else:
        # 原版实例
        _skip = _os.path.isfile(_os.path.join(
            inst.mc_dir, "versions", inst.game_version, f"{inst.game_version}.json"))
    if not _skip:
        # round-52 阶段上报：安装/修复游戏版本（点第 2 步）。
        _emit_step(callback, "install")
        installed = install_instance(
            inst,
            java_auto=settings.get("java_auto", True),
            java_path=user_java,
            mirror=settings.get("download_mirror", "bmclapi"),
            proxy=settings.get("download_proxy", ""),
            callback=callback,
        )
    # Prefer the scanned versions/<id> folder name (version_id) when present —
    # it is what minecraft-launcher-lib resolves versions by, and differs from
    # the base game_version for imported instances (e.g. "1.20.1-forge-47.2.0").
    # For AC-created instances version_id is empty, so we fall back to the
    # version install_instance actually installed.
    version = inst.version_id or installed
    # round-78：mll 解析版本 json 的根目录——外国启动器版本隔离实例指向原
    # .minecraft（mc_dir 上级两级），其余布局就是 mc_dir 本身。
    vroot = versions_root(inst, version)
    # select_java takes java_auto / user_path as KEYWORD-only args — passing the
    # bool positionally raised TypeError and broke every launch.
    java_auto = settings.get("java_auto", True)
    java = select_java(inst.game_version, java_auto=java_auto, user_path=user_java)
    # round-46：select_java 返回 None = 没有任何兼容该 MC 版本的 Java。
    # 之前会 fallback find_java()/裸 "java" → 老版本被高版本 Java 启动 → 崩 exit 1。
    if not java:
        from .i18n import t as _t
        need = required_java_major(inst.game_version)
        raise RuntimeError(
            _t("err.java_compat_missing",
               default="此版本需要 Java {need}，但未检测到兼容的 Java 运行时。\n"
                       "请到 设置 → Java → 管理，安装 Java {need} 后再启动。",
               need=need)
        )
    if not java_auto and user_java and not os.path.isfile(user_java):
        from .i18n import t as _t
        raise RuntimeError(
            _t("err.java_path_invalid", default="指定的 Java 路径不存在：{path}\n请在 设置 → Java 里重新选择，或开启「自动检测」。", path=user_java)
        )
    if not os.path.isfile(java):
        from .i18n import t as _t
        raise RuntimeError(
            _t("err.java_missing", default="未找到可用的 Java 运行时。\n请到 设置 → Java 安装一个（或开启自动检测）。")
        )
    # round-55 启动高级设置（对齐主流「启动游戏/版本设置」）：全局默认 + 实例覆盖。
    # game_dir 先解析出来——窗口模式 options.txt 也要写到运行时目录才生效。
    game_dir = resolve_game_dir(inst, settings)
    try:
        os.makedirs(game_dir, exist_ok=True)  # 版本隔离 / 自定义目录首启前建好
    except OSError:
        pass
    jvm_preset = (getattr(inst, "jvm_preset", "") or "").strip() \
        or settings.get("jvm_preset", "default")
    if jvm_preset not in ("default", "aikar", "auto", "custom"):
        jvm_preset = "default"
    # 游戏附加参数：--server/--port 走 mll 直连，其余令牌追加到命令尾部
    game_args = (getattr(inst, "game_args", "") or "").strip() \
        or settings.get("game_args", "")
    _server, _port, extra_game = parse_game_args(game_args)
    if server_override:   # round-83 收藏服务器直连优先于附加参数里的 --server
        _server = server_override
        _port = port_override if port_override else _port

    # Honor the game window mode (fullscreen / borderless / windowed). This is
    # the launcher-side counterpart to the "窗口模式" setting — it must run
    # before the process spawns so options.txt is in place at launch.
    _apply_game_window_mode(game_dir, settings.get("window_mode", "windowed"))

    # External login: route auth through authlib-injector (third-party
    # Yggdrasil server). Jar path comes from settings (default
    # data/authlib-injector.jar, fetched on demand). round-53：每次启动后台
    # 检查 GitHub latest release，有新版自动替换（随版本更新，不阻塞启动）。
    authlib_args: dict = {}
    if account.get("type") == "yggdrasil" and account.get("server"):
        # round-45 修复：局部 import os 会把整个函数内的 os 变局部（模块级
        # os 在 11 行已导入）→ 190 行 os.path.isdir 报 UnboundLocalError
        inj = settings.get("authlib_path") or os.path.join(get_data_dir(), "authlib-injector.jar")
        if not os.path.exists(inj):
            inj = ensure_authlib(inj) or inj
        if os.path.exists(inj):
            authlib_args = {"authlib_injector": inj, "yggdrasil_server": account["server"]}
            try:
                from .core.authlib import try_update_authlib
                try_update_authlib(inj)
            except Exception:  # noqa: BLE001 - 更新失败绝不影响启动
                pass
        else:
            if callback:
                callback(f"警告：未找到 authlib-injector.jar（{inj}），外置登录可能无法生效")

    # round-53：一次构建所有选项（含 authlib agent）——之前 yggdrasil 分支
    # 会第二遍 build_options 且只传全局 ram/jvm，把实例级覆盖丢回全局值
    # （round-42 的 ram_mb/jvm_args/renderer/perf 全部失效）。现在实例级
    # 覆盖一次注入，yggdrasil 只追加 javaagent 参数。
    opts = build_options(
        account.get("username", "Player"),
        account.get("uuid", ""),
        account.get("token", ""),
        mc_dir=inst.mc_dir,
        java=java,
        # round-42 实例级覆盖（对齐主流做法）：ram/jvm 优先实例，0/空回退全局
        ram_mb=int(getattr(inst, "ram_mb", 0) or 0) or settings.get("ram_mb", 4096),
        jvm_args=(getattr(inst, "jvm_args", "") or "").strip()
                 or settings.get("jvm_args", ""),
        res=(settings.get("res_w"), settings.get("res_h")) if settings.get("res_w") else None,
        renderer=getattr(inst, "renderer", "auto") or "auto",
        perf_g1gc=bool(getattr(inst, "perf_g1gc", True)),
        perf_disable_explicit_gc=bool(getattr(inst, "perf_disable_explicit_gc", False)),
        # round-55 启动高级设置：运行时游戏目录 / JVM 预设 / 服务器直连
        game_dir=game_dir,
        jvm_preset=jvm_preset,
        server=_server,
        port=_port,
        **authlib_args,
    )
    # round-47 集成 natives 解压（MH「启动即秒退 exit 1」的根治之一）：
    # minecraft-launcher-lib 只把 nativesDirectory 写进 -Djava.library.path，
    # 但从不真正解压 LWJGL/OpenAL 的 dll。缺 dll → 游戏 JVM 直接抛
    # NativeLibraryNotFound 崩掉。启动前先解压到 versions/<id>/natives，
    # 并把该目录显式回传给命令构造，保证路径一致。

    def _assemble_command(set_natives=True) -> list[str]:
        """(解压 natives + 构造命令) 的单一出口，repair 后复用。"""
        nonlocal_cmd = opts
        if set_natives:
            nd = _prepare_natives(version, vroot)
            if nd:
                nonlocal_cmd["nativesDirectory"] = nd
        cmd = get_command(version, vroot, nonlocal_cmd)
        # round-55 游戏附加参数：--server/--port 已由 mll 处理，其余令牌原文追加
        if extra_game:
            cmd = cmd + extra_game
        return cmd

    # round-52 阶段上报：补齐缺失库与原生文件（点第 3 步，解压 natives /
    # classpath 补装期间可见）。
    _emit_step(callback, "prepare")
    cmd = _assemble_command()

    # round-47 根治之二：classpath 完整性自愈（对齐主流启动器的
    # 启动前校验）。之前反复「exit 1 修不好」的真正根因不只是 natives dll——
    # 1.8.9 等老版本的 lwjgl-platform 基础包 / 各主库 jar 若缺失，JVM 一起动
    # 就 ClassNotFound / UnsatisfiedLinkError 秒退。这里在启动前扫描客户端的
    # -cp，凡有游戏真正需要的库缺失，就先补装再重建命令；仅缺 natives 分类器
    # jar（只装 dll）则忽略（dll 已由 _prepare_natives 解压到 java.library.path）。
    missing = _missing_classpath(cmd)
    if _needs_repair(missing):
        _repair_status = callback.get("setStatus") if callback else None
        if _repair_status:
            _repair_status(f"检测到 {len(missing)} 个缺失库文件，正在补全…")
        import minecraft_launcher_lib as _mll
        # 修复目标用基础游戏版本：老版平台库（lwjgl-platform 等）都属 base install；
        # 加载器实例的库在 versions/<loader> 下，安装后即在，不走此分支。
        try:
            _mll.install.install_minecraft_version(
                inst.game_version, vroot, callback=callback or None
            )
        except Exception:  # noqa: BLE001 - 补全失败不阻塞启动，由 crash 分析兜底
            pass
        cmd = _assemble_command()
        # 修复后再扫一次：若仍有可选遗留库（如 1.8.9 的 jinput/twitch 平台包，
        # Mojang 已停供）缺失——它们不参与游戏主线程加载，JVM 会静默忽略缺失的
        # classpath 条目，**不影响启动**。这里只提示、不拦截（拦截会把本来能玩的
        # 版本误判为启动失败）。真正会崩的主库（lwjgl-platform 等）已由上面修复。
        still_missing = _missing_classpath(cmd)
        if _needs_repair(still_missing) and _repair_status:
            _heads = "、".join(os.path.basename(p) for p in still_missing[:4])
            _repair_status(f"提示：{len(still_missing)} 个可选遗留库不可用（{_heads}…），游戏仍会正常启动")

    log_path = None
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{inst.id}.log")

    # round-49 N5 启动前模组冲突预检：非阻塞提示。真正会致崩的 missing_dep /
    # loader 不匹配等原因，在游戏起来前给玩家一个口头警告 + 指引（不拦截启动——
    # 有些实例能容忍缺失前置照常进主菜单）。完整报告走 实例→右键→「冲突预检」。
    # round-52 阶段上报：启动前模组冲突预检（点第 4 步）。
    _emit_step(callback, "precheck")
    try:
        from .core import mod_check
        from .i18n import t as _t
        _mc = mod_check.scan_conflicts(inst)
        _crit = _mc.get("critical", 0)
        if _crit and callback and hasattr(callback, "get") and callback.get("setStatus"):
            callback["setStatus"](_t("status.modcheck_crit", n=_crit))
    except Exception:  # noqa: BLE001 - 预检失败绝不影响启动
        pass

    # round-71 借鉴主流实现做启动前预检：游戏目录含非 ASCII 字符
    # （如中文路径）在部分 UTF-8 环境下会让老版本 MC 启动失败——只警告
    # 不拦截，且玩家可在设置里关闭；与主流的「不再提示」开关语义一致。
    try:
        from .i18n import t as _t2
        if settings.get("warn_non_ascii_path", True) and not game_dir.isascii():
            _warn = callback.get("setStatus") if callback and hasattr(callback, "get") else None
            if callable(_warn):
                _warn(_t2("launch.warn_non_ascii_path"))
    except Exception:  # noqa: BLE001 - 警告失败绝不影响启动
        pass

    # round-52 阶段上报：即将拉起游戏进程（点第 5 步）。
    _emit_step(callback, "start")
    # round-69 进程优先级：读全局设置（实例级暂无独立覆盖），随 creationflags 生效。
    _pri = (settings.get("process_priority") or "normal")
    proc, logf = launch_process(cmd, inst.mc_dir, log_path, priority=_pri)
    # round-55 启动后命令：游戏进程拉起后由启动器执行（不等待、失败静默）。
    # 退出后命令由 UI 层在轮询到游戏进程退出时执行（main_window._poll_game），
    # 这里只负责「游戏已启动」这一半。
    post_cmd = (getattr(inst, "post_launch_cmd", "") or "").strip() \
        or settings.get("post_launch_cmd", "")
    run_hook_cmd(post_cmd, inst.mc_dir)
    return proc, log_path


# round-48 C：进程退出原因分类。返回 (i18n_key, kwargs)，UI 据此给出可操作提示。
_CRASH_LOG_TAIL = 4000


def classify_exit(returncode: int, log_path: str | None = None) -> tuple[str, dict]:
    """把游戏退出码 + 崩溃日志特征归类为一句可操作的中文提示。

    优先读日志末尾的关键特征（比裸退出码更能定位根因）；找不到特征再退到
    退出码本身。返回 (i18n_key, format_kwargs)。
    """
    from .i18n import t as _t

    tail = ""
    if log_path and os.path.isfile(log_path):
        try:
            with open(log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - _CRASH_LOG_TAIL))
                raw = f.read()
            tail = raw.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 读日志失败不阻塞分类
            tail = ""

    def has(*keys: str) -> bool:
        low = tail.lower()
        return any(k in low for k in keys)

    if returncode == 0:
        return "exit.normal", {}

    # 内存不足 → 指导加 RAM（最常见、玩家能自己改）
    if has("outofmemoryerror", "unable to create new native thread", "caused by: java.lang.outofmemoryerror"):
        return "exit.oom", {}

    # Java 版本不匹配
    if has("unsupportedclassversionerror", "class file has wrong version"):
        return "exit.java_version", {}

    # 主类/启动配置错误
    if has("could not find or load main class", "mainclassnotfoundexception", "no main manifest attribute"):
        return "exit.main_class", {}

    # 原生库缺失/加载失败
    if has("unsatisfiedlinkerror", "failed to load jni dll", "natives not found", "native librarynot found"):
        return "exit.native", {}

    # 普通库(classpath)缺失
    if has("noclassdeffounderror", "classnotfoundexception", "symbol not found:"):
        return "exit.classpath", {}

    # JVM 致命错误 → 一般伴随 hs_err_pid<N>.log
    if has("hs_err_pid", "# a fatal error has been detected"):
        return "exit.jvm_fatal", {}

    # Windows 退出码特殊值（0xC0000005 = 3221225477 = 非法内存访问）
    if returncode in (-1073741819, 3221225477):
        return "exit.access_violation", {}

    # 其余非零 → 通用崩溃
    if returncode in (1,):
        return "exit.crash_one", {}
    return "exit.generic", {"code": returncode}


def explain_exit(returncode: int, log_path: str | None = None) -> str:
    """把 classify_exit 的 i18n 结果渲染成一句完整的状态栏文案。"""
    from .i18n import t as _t
    key, kw = classify_exit(returncode, log_path)
    return _t(key, default=_t("exit.generic", default="游戏异常退出（退出码 {code}）", code=returncode), **kw)
