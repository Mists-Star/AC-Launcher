"""Java discovery + smart version selection.

We reuse minecraft-launcher-lib's scanner (it already knows the standard
Windows / Linux roots) and extend it with the extra vendors Minecraft players
commonly install (Adoptium, Zulu, Microsoft Build, BellSoft Liberica). The
smart selector maps a game version to the Java major it requires, then picks
the closest installed JRE >= that major.
"""
from __future__ import annotations

import os
import re

import minecraft_launcher_lib

# Extra roots beyond what the lib scans by default.
EXTRA_JAVA_DIRS = [
    r"C:\Program Files\Eclipse Adoptium",
    r"C:\Program Files\Zulu",
    r"C:\Program Files\Microsoft\jdk",
    r"C:\Program Files\BellSoft\Liberica",
    r"C:\Program Files\Java",
    r"C:\Program Files (x86)\Java",
]


def _extra_dirs() -> list[str]:
    dirs = list(EXTRA_JAVA_DIRS)
    appdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        dirs.append(os.path.join(appdata, "Programs"))
    return dirs


def find_java() -> str | None:
    """Scan PATH then common install dirs for javaw.exe; return path or None.

    Kept for backward-compat (Settings auto-detect) and as a last-resort
    fallback when the smart selector finds nothing.
    """
    try:
        from shutil import which

        p = which("javaw.exe") or which("java.exe")
        if p:
            return p
    except Exception:  # noqa: BLE001
        pass
    for root in _extra_dirs():
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            if "javaw.exe" in files:
                return os.path.join(dirpath, "javaw.exe")
    return None


def _major_from_path(path: str) -> int:
    """Last-resort major guess from folder names like 'jdk-21' / 'java17' / 'jre1_8'."""
    m = re.search(r"(?:jdk|jre|java|openjdk)[-_ ]?(\d{1,2})", path, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        return 8 if n == 1 else n
    return 0


# round-40 P2-5 性能：scan_javas 进程级缓存（60s TTL）——之前每次启动游戏
# 都全盘扫 Java（含 discover_javas 整盘 os.walk），慢盘卡数秒。PCL2/HMCL 均
# 缓存扫描结果。deep=True 全盘扫更慢，TTL 更长。
_SCAN_CACHE: list | None = None
_SCAN_CACHE_AT: float = 0.0
_SCAN_TTL_DEEP = 300.0   # deep 全盘扫：5 分钟复用
_SCAN_TTL_FAST = 30.0    # 浅扫：30s 复用


def scan_javas(deep: bool = True) -> list[dict]:
    """Return list of installed JREs: {path, name, version, major, is_64bit}.

    Merges two sources:
      1. minecraft-launcher-lib's scanner (standard install roots)
      2. our own scanner in ``src.scan`` — registry, PATH, other launchers'
         bundled runtimes and (when ``deep``) a whole-disk sweep that finds
         *portable* unzipped JDKs the standard scanner can never see.
    """
    global _SCAN_CACHE, _SCAN_CACHE_AT
    import time as _time
    now = _time.time()
    ttl = _SCAN_TTL_DEEP if deep else _SCAN_TTL_FAST
    if _SCAN_CACHE is not None and now - _SCAN_CACHE_AT < ttl:
        return _SCAN_CACHE

    out: list[dict] = []
    seen: set[str] = set()

    def push(exe: str, name: str, ver: str, is_64: bool = True) -> None:
        if not exe:
            return
        key = os.path.normcase(os.path.normpath(exe))
        if key in seen or not os.path.isfile(exe):
            return
        seen.add(key)
        major = java_major(ver) or _major_from_path(exe)
        out.append({"path": exe, "name": name, "version": ver,
                    "major": major, "is_64bit": is_64})

    try:
        infos = minecraft_launcher_lib.java_utils.find_system_java_versions_information(
            additional_directories=_extra_dirs()
        )
    except Exception:  # noqa: BLE001
        infos = []
    for info in infos:
        push(info.get("javaw_path") or info.get("java_path"),
             info.get("name", ""), info.get("version", ""),
             info.get("is_64bit", True))

    try:
        from ..scan import discover_javas

        for j in discover_javas(deep=deep):
            push(j.path, os.path.basename(os.path.dirname(os.path.dirname(j.path))),
                 j.version)
    except Exception:  # noqa: BLE001 - never let discovery break a launch
        pass

    _SCAN_CACHE = out
    _SCAN_CACHE_AT = _time.time()
    return out


def java_major(version_str: str) -> int:
    """Extract the major version number from a Java version string.

    "1.8.0_421" -> 8, "17.0.12" -> 17, "26.0.1" -> 26
    """
    if not version_str:
        return 0
    if version_str.startswith("1."):
        m = re.match(r"1\.(\d+)", version_str)
        if m:
            return int(m.group(1))
    m = re.search(r"(\d+)", version_str)
    return int(m.group(1)) if m else 0


def required_java_major(game_version: str) -> int:
    """Map a Minecraft version to the Java major it requires.

    Sources: Mojang's stated requirements per release.
    """
    parts = re.findall(r"\d+", game_version)
    if not parts:
        return 17
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0

    if major == 1 and minor <= 16:
        return 8
    if major == 1 and minor == 17:
        return 16
    if major == 1 and 18 <= minor <= 20:
        # 1.20.5+ moved to Java 21; 1.18–1.20.4 stay on 17
        if minor == 20 and len(parts) > 2 and int(parts[2]) >= 5:
            return 21
        return 17
    if major == 1 and minor >= 21:
        return 21
    # Future mainline (e.g. 26.2) — require at least the version's major.
    if major >= 22:
        return major
    if major >= 21:
        return 21
    if major >= 17:
        return 17
    return 8


def select_java(game_version: str, *, java_auto: bool = True, user_path: str = "") -> str | None:
    """Pick the best Java executable for a game version.

    Priority:
      1. explicit user path (when auto is off)
      2. an installed JRE whose major exactly matches the requirement
      3. the nearest installed JRE inside the compatible range (need..need+max_ok)
      4. None → 调用方提示"需要安装 Java X"（绝不 fallback 到任意高版本/裸 java）

    round-46 修复：老版本（如 1.8.9 需 Java 8）用高版本（17/21）启动会直接
    崩溃 exit 1。兼容区间：need=8→仅 8；16→16-17；17→17-21；21→21-24。
    """
    if not java_auto and user_path:
        return user_path if os.path.isfile(user_path) else None

    need = required_java_major(game_version)
    javas = [j for j in scan_javas() if j["major"] > 0]  # drop unidentifiable stubs
    exact = [j for j in javas if j["major"] == need]
    if exact:
        return exact[0]["path"]
    # 兼容上限（借鉴 BlockHelm：老版本拒绝高版本，新版本接受小范围更高）
    max_ok = {8: 8, 16: 17, 17: 21, 21: 24}.get(need, need + 3)
    compat = sorted(
        (j for j in javas if need <= j["major"] <= max_ok),
        key=lambda x: x["major"])
    if compat:
        # 优先 64 位，其次最低可用（离 need 最近）
        c64 = [j for j in compat if j.get("is_64bit", True)]
        pick = (c64 or compat)[0]
        return pick["path"]
    # 没有任何兼容 Java → None（调用方给出明确安装提示），不再 fallback
    return None
