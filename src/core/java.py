"""Java discovery + smart version selection.

We reuse minecraft-launcher-lib's scanner (it already knows the standard
Windows / Linux roots) and extend it with the extra vendors Minecraft players
commonly install (Adoptium, Zulu, Microsoft Build, BellSoft Liberica). The
smart selector maps a game version to the Java major it requires, then picks
the closest installed JRE >= that major.
"""
from __future__ import annotations

import json
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
    # Cleanroom's installer provisions its own JRE 25 here (--provision-java);
    # without this root the launcher would never see the Java it just fetched.
    home = os.path.expanduser("~")
    if home:
        dirs.append(os.path.join(home, ".cleanroom", "java"))
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
# 都全盘扫 Java（含 discover_javas 整盘 os.walk），慢盘卡数秒。各主流启动器均
# 缓存扫描结果。deep=True 全盘扫更慢，TTL 更长。
# round-96 修复：浅扫/深扫缓存槽分离。原先单一缓存被浅扫结果（30s TTL 之外
# 深扫也复用同槽）污染，导致先浅后深时 deep 调用错用浅扫结果（只看到
# Oracle javapath 1 条）。deep 是全盘超集：fresh deep 缓存可直接供浅扫复用，
# 但浅扫结果绝不进 deep 槽。
_SCAN_CACHE_DEEP: list | None = None
_SCAN_CACHE_DEEP_AT: float = 0.0
_SCAN_CACHE_FAST: list | None = None
_SCAN_CACHE_FAST_AT: float = 0.0
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
    global _SCAN_CACHE_DEEP, _SCAN_CACHE_DEEP_AT, _SCAN_CACHE_FAST, _SCAN_CACHE_FAST_AT
    import time as _time
    now = _time.time()
    if deep:
        if _SCAN_CACHE_DEEP is not None and now - _SCAN_CACHE_DEEP_AT < _SCAN_TTL_DEEP:
            return _SCAN_CACHE_DEEP
    else:
        if _SCAN_CACHE_DEEP is not None and now - _SCAN_CACHE_DEEP_AT < _SCAN_TTL_DEEP:
            return _SCAN_CACHE_DEEP
        if _SCAN_CACHE_FAST is not None and now - _SCAN_CACHE_FAST_AT < _SCAN_TTL_FAST:
            return _SCAN_CACHE_FAST

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

    if deep:
        _SCAN_CACHE_DEEP = out
        _SCAN_CACHE_DEEP_AT = _time.time()
    else:
        _SCAN_CACHE_FAST = out
        _SCAN_CACHE_FAST_AT = _time.time()
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
    gv = (game_version or "").strip().lower()
    # round-146：快照 ID（25w14craftmine / 24w14potato / 23w13a_or_b …）里的
    # 数字是「年份+周」，不是版本号 —— 旧逻辑会把 25w14 当成主版本 25，于是
    # 4 月愚人节版本被判成「需要 Java 25」，玩家装了 Java 26 也被拒。快照按
    # 所属正式版定 Java：24w 起 = 1.20.5+ → 21；22w/23w = 1.17–1.20.4 → 17；
    # 21w = 1.17 → 16；20w 及更早 = 1.16- → 8。
    m = re.match(r"^(\d{2})w(\d{2})", gv)
    if m:
        year = int(m.group(1))
        if year >= 24:
            return 21
        if year >= 22:
            return 17
        if year >= 21:
            return 16
        return 8
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


# round-146：兼容上限表从 select_java/launch/health 三处重复定义收拢到这里。
# 25 只到 25：Cleanroom 0.7.x 的安装器明确拒绝 Java 24 和 26。
# 21 → 30：1.20.5+ 在 22–26 上均可运行，旧上限 24 会误杀玩家的 Java 26。
# （4 月快照 25w14craftmine 不在此列：版本 json 的 javaVersion=21 → 走 21 档，
#  Java 26 已可启动；「要 25」来自旧逻辑把快照 ID 当主版本号。）
JAVA_MAX_OK = {8: 8, 16: 17, 17: 21, 21: 30, 25: 25}


def java_max_ok(need: int) -> int:
    return JAVA_MAX_OK.get(need, need + 3)


def is_java_compatible(need: int, major: int) -> bool:
    """Does a Java of ``major`` satisfy a version that needs ``need``?

    Old clients (Java 8/16) crash on newer JVMs, so they must match closely;
    17+ tolerate a newer runtime (and 1.20.5+ runs fine on 22–26). Cleanroom
    (25) is strict by its installer's own rule.
    """
    if need <= 0 or major <= 0:
        return True  # unknown → don't block
    return need <= major <= java_max_ok(need)


def find_version_json(mc_dir: str, version_id: str) -> str:
    """Locate the installed version json for ``version_id`` (best effort).

    round-146：用版本 json 里的 ``javaVersion.majorVersion`` 取代纯 ID 推断，
    这样快照 / 新编号正式版的 Java 要求都以 Mojang 的真实元数据为准。
    """
    if not mc_dir or not version_id:
        return ""
    parent = os.path.dirname(os.path.normpath(mc_dir))
    for cand in (
        os.path.join(mc_dir, "versions", version_id, f"{version_id}.json"),
        os.path.join(mc_dir, f"{version_id}.json"),
        os.path.join(parent, "versions", version_id, f"{version_id}.json"),
    ):
        if os.path.isfile(cand):
            return cand
    return ""


def _java_major_from_json(path: str) -> int:
    if not path or not os.path.isfile(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return int((data.get("javaVersion") or {}).get("majorVersion") or 0)
    except Exception:  # noqa: BLE001 - a broken json just falls back to the table
        return 0


def reset_scan_cache() -> None:
    """Drop the cached scan results (call after provisioning a new JRE)."""
    global _SCAN_CACHE_DEEP, _SCAN_CACHE_DEEP_AT, _SCAN_CACHE_FAST, _SCAN_CACHE_FAST_AT
    _SCAN_CACHE_DEEP = None
    _SCAN_CACHE_FAST = None
    _SCAN_CACHE_DEEP_AT = 0.0
    _SCAN_CACHE_FAST_AT = 0.0


def java25_path() -> str | None:
    """Path of an installed Java 25, if any.

    Cleanroom 0.7.x's installer accepts exactly Java 25 (it rejects both 24
    and 26), and its installer can provision one into ~/.cleanroom/java.
    """
    for j in scan_javas(deep=False):
        if int(j.get("major") or 0) == 25 and os.path.isfile(j.get("path") or ""):
            return j["path"]
    return None


def required_java_major_for(game_version: str, loader: str = "",
                            version_json: str = "") -> int:
    """Java major an *instance* needs, not just its game version.

    Cleanroom is the exception to the version table: it is a 1.12.2 fork that
    runs on a much newer JVM (0.7.x installers demand exactly Java 25 and
    refuse newer ones), so the version-derived "1.12.2 → 8" answer would hand
    it a JRE it cannot load.
    """
    if (loader or "").strip().lower() == "cleanroom":
        return 25
    from_json = _java_major_from_json(version_json)
    if from_json > 0:
        return from_json
    return required_java_major(game_version)


def select_java(game_version: str, *, java_auto: bool = True, user_path: str = "",
                need_override: int = 0) -> str | None:
    """Pick the best Java executable for a game version.

    Priority:
      1. explicit user path (when auto is off)
      2. an installed JRE whose major exactly matches the requirement
      3. the nearest installed JRE inside the compatible range (need..need+max_ok)
      4. None → 调用方提示"需要安装 Java X"（绝不 fallback 到任意高版本/裸 java）

    round-46 修复：老版本（如 1.8.9 需 Java 8）用高版本（17/21）启动会直接
    崩溃 exit 1。兼容区间：need=8→仅 8；16→16-17；17→17-21；21→21-24。
    ``need_override`` 用于看加载器而非 MC 版本的场景（Cleanroom → 21）。
    """
    if not java_auto and user_path:
        return user_path if os.path.isfile(user_path) else None

    need = need_override or required_java_major(game_version)
    javas = [j for j in scan_javas() if j["major"] > 0]  # drop unidentifiable stubs
    exact = [j for j in javas if j["major"] == need]
    if exact:
        return exact[0]["path"]
    # 兼容上限（借鉴主流做法：老版本拒绝高版本，新版本接受小范围更高）
    # round-146：统一走模块级 JAVA_MAX_OK（Cleanroom 25 仍只认 25）。
    max_ok = java_max_ok(need)
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
