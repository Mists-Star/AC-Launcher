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

from .core.java import find_java, select_java
from .core.install import install_instance
from .paths import get_data_dir
from .brand import APP_NAME
from .core.authlib import ensure_authlib

__all__ = ["find_java", "build_options", "get_command", "launch_process", "launch_instance"]


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
) -> dict:
    """Build the MinecraftOptions dict for command.get_minecraft_command."""
    opts: dict = {
        "username": username,
        "uuid": uuid,
        "token": token,
        "executablePath": java,
        "gameDirectory": mc_dir,
        "launcherName": launcher_name,
        "launcherVersion": launcher_version,
        "jvmArguments": [f"-Xmx{ram_mb}M", f"-Xms{max(ram_mb // 2, 512)}M"],
    }
    if jvm_args and jvm_args.strip():
        opts["jvmArguments"] += jvm_args.split()
    # External / third-party (Yggdrasil) login: route auth through the
    # authlib-injector javaagent so Minecraft talks to the custom server.
    if authlib_injector and yggdrasil_server:
        import json
        import os

        cfg_path = os.path.join(os.path.dirname(authlib_injector), "authlib-injector-config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "authServer": f"{yggdrasil_server.rstrip('/')}/authserver",
                    "sessionServer": f"{yggdrasil_server.rstrip('/')}/sessionserver",
                    "servicesServer": yggdrasil_server.rstrip("/"),
                },
                f,
            )
        opts["jvmArguments"].append(f"-javaagent:{authlib_injector}={cfg_path}")
    if res:
        w, h = res
        opts["customResolution"] = True
        opts["resolutionWidth"] = str(w)
        opts["resolutionHeight"] = str(h)
    return opts


def _apply_game_window_mode(mc_dir: str, window_mode: str) -> None:
    """Make the launched Minecraft honor the chosen window mode.

    ``minecraft-launcher-lib`` exposes no fullscreen option, so we write the
    game's own ``options.txt`` ``fullscreen`` flag. Vanilla MC has no native
    borderless fullscreen (that needs OptiFine/Sodium), so ``borderless``
    falls back to ordinary fullscreen — the closest vanilla behaviour.
    """
    if not mc_dir or not os.path.isdir(mc_dir):
        return
    options_path = os.path.join(mc_dir, "options.txt")
    full = window_mode in ("fullscreen", "borderless")
    data: dict[str, str] = {}
    if os.path.exists(options_path):
        try:
            with open(options_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if ":" in line:
                        k, _, v = line.partition(":")
                        data[k] = v
        except OSError:
            data = {}
    data["fullscreen"] = "true" if full else "false"
    try:
        with open(options_path, "w", encoding="utf-8") as f:
            for k, v in data.items():
                f.write(f"{k}:{v}\n")
    except OSError:
        pass


def get_command(version: str, mc_dir: str, options: dict) -> list[str]:
    """Return the java command line for a version via minecraft-launcher-lib."""
    import minecraft_launcher_lib

    return minecraft_launcher_lib.command.get_minecraft_command(version, mc_dir, options)


def launch_process(cmd: list[str], mc_dir: str, log_path: str | None = None):
    """Spawn Minecraft. Hides the Java console on Windows (CREATE_NO_WINDOW).

    When ``log_path`` is given, stdout+stderr go to that file (no pipe buffer).
    Otherwise a daemon thread drains the pipes so Minecraft never blocks.
    Returns (proc, log_file_or_None).
    """
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

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
):
    """Install (if needed) + assemble command + spawn. Returns (proc, log_path)."""
    # Per-instance Java (instance.java_path) wins over the global setting; the
    # global setting wins over auto-detect. This lets one instance pin a JDK
    # without disturbing the launcher-wide default.
    inst_java = (getattr(inst, "java_path", "") or "").strip()
    user_java_global = (settings.get("java_path") or "").strip()
    user_java = inst_java or user_java_global
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
    # select_java takes java_auto / user_path as KEYWORD-only args — passing the
    # bool positionally raised TypeError and broke every launch.
    java_auto = settings.get("java_auto", True)
    java = (
        select_java(inst.game_version, java_auto=java_auto, user_path=user_java)
        or find_java()
        or "java"
    )
    # Honor the game window mode (fullscreen / borderless / windowed). This is
    # the launcher-side counterpart to the "窗口模式" setting — it must run
    # before the process spawns so options.txt is in place at launch.
    _apply_game_window_mode(inst.mc_dir, settings.get("window_mode", "windowed"))

    opts = build_options(
        account.get("username", "Player"),
        account.get("uuid", ""),
        account.get("token", ""),
        mc_dir=inst.mc_dir,
        java=java,
        ram_mb=settings.get("ram_mb", 4096),
        jvm_args=settings.get("jvm_args", ""),
        res=(settings.get("res_w"), settings.get("res_h")) if settings.get("res_w") else None,
    )
    # External login: inject authlib-injector so the game uses the third-party
    # auth server instead of Mojang's. Jar path comes from settings (default
    # data/authlib-injector.jar, which the user must supply).
    if account.get("type") == "yggdrasil" and account.get("server"):
        import os
        inj = settings.get("authlib_path") or os.path.join(get_data_dir(), "authlib-injector.jar")
        if not os.path.exists(inj):
            inj = ensure_authlib(inj) or inj
        if os.path.exists(inj):
            opts = build_options(
                account.get("username", "Player"),
                account.get("uuid", ""),
                account.get("token", ""),
                mc_dir=inst.mc_dir,
                java=java,
                ram_mb=settings.get("ram_mb", 4096),
                jvm_args=settings.get("jvm_args", ""),
                res=(settings.get("res_w"), settings.get("res_h")) if settings.get("res_w") else None,
                authlib_injector=inj,
                yggdrasil_server=account["server"],
            )
        else:
            if callback:
                callback(f"警告：未找到 authlib-injector.jar（{inj}），外置登录可能无法生效")
    cmd = get_command(version, inst.mc_dir, opts)

    log_path = None
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{inst.id}.log")

    proc, logf = launch_process(cmd, inst.mc_dir, log_path)
    return proc, log_path
