"""Discovery of existing Minecraft instances and Java runtimes on this machine.

Powers the home-page "Scan" feature: find instances managed by other
launchers (official, HMCL, PCL2, MultiMC/Prism, CurseForge, ATlauncher,
TLauncher, Modrinth App, …) plus any Java installations, so AC can import
them instead of forcing a fresh download.

Pure logic (no Qt) so it can run on a Worker thread and be unit-tested.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import string
from dataclasses import dataclass

# Folders we never descend into during the recursive sweep — they are huge,
# irrelevant, or would make a "whole-disk" scan pathologically slow.
#
# NOTE: "appdata" is intentionally omitted here because users may have a
# custom folder named "AppData" on drive roots (e.g. D:\Appdata) that
# contains game instances.  System AppData is handled separately below.
_SKIP_DIRS = {
    "node_modules", "$recycle.bin", "library", ".git",
    "venv", ".venv", "site-packages", "windows", "program files",
    "program files (x86)", "programdata", "system volume information",
    "android", ".android", ".gradle",
}

# Java vendor folders that live under Program Files.
_JAVA_FAMILIES = (
    "Java", "Eclipse Adoptium", "AdoptOpenJDK", "Zulu", "BellSoft",
    "Microsoft", "Amazon Corretto", "GraalVM", "Semeru", "Liberica",
)


@dataclass
class ScannedInstance:
    launcher: str          # human label, e.g. "Official", "HMCL", "MultiMC"
    name: str              # instance / profile name
    game_version: str
    loader: str            # vanilla / fabric / forge / quilt / neoforge
    mc_dir: str            # game directory (the folder holding saves/ mods/)
    mods: int = 0
    resource_packs: int = 0
    shaders: int = 0
    saves: int = 0
    # --- cross-launcher metadata -------------------------------------------
    # version_id: the versions/<id> folder name. Empty when the launcher does
    #   not use the official layout (MultiMC/Prism keep patches instead).
    version_id: str = ""
    # kind: how the instance is stored on disk.
    #   standard   — official versions/<id>/<id>.json layout (official/HMCL/PCL2)
    #   mmc        — MultiMC / Prism / PolyMC component pack (mmc-pack.json)
    #   curseforge — CurseForge App (minecraftinstance.json)
    #   modrinth   — Modrinth App profile (profile.json)
    kind: str = "standard"
    # needs_convert: there is no launchable <id>.json in this game dir, so AC
    #   must resolve/rebuild the version before it can start the game.
    needs_convert: bool = False
    # isolated: this game dir belongs to this instance alone. False means it is
    #   a shared .minecraft used by several versions (official / HMCL global).
    isolated: bool = True
    # loader_version: exact loader build when the metadata states one.
    loader_version: str = ""
    # note: short human hint shown in the scan dialog (why it needs work).
    note: str = ""


@dataclass
class JavaInstall:
    path: str              # absolute path to the java executable
    version: str
    major: int = 0


# ---------- small helpers ----------

def _count_jars(folder: str) -> int:
    if not folder or not os.path.isdir(folder):
        return 0
    try:
        return sum(
            1 for e in os.scandir(folder)
            if e.is_file() and e.name.lower().endswith(".jar")
        )
    except OSError:
        return 0


def _count_subdirs(folder: str) -> int:
    if not folder or not os.path.isdir(folder):
        return 0
    try:
        return sum(1 for e in os.scandir(folder) if e.is_dir())
    except OSError:
        return 0



def _is_system_appdata(path: str) -> bool:
    """Return True if *path* is a system AppData under a user profile
    (e.g. C:\\Users\\<name>\\AppData), NOT a custom folder like D:\\Appdata."""
    if os.path.basename(path).lower() != "appdata":
        return False
    grandparent = os.path.dirname(os.path.dirname(path))
    return os.path.basename(grandparent).lower() == "users"


def _is_mc_dir(folder: str) -> bool:
    """A real game dir has versions/<id>/<id>.json (standard MC layout)."""
    vd = os.path.join(folder, "versions")
    if not os.path.isdir(vd):
        return False
    try:
        for e in os.scandir(vd):
            if e.is_dir() and os.path.isfile(os.path.join(e.path, e.name + ".json")):
                return True
    except OSError:
        return False
    return False


def _loader_from_text(text: str) -> str:
    """Classify a loader from any free-form id / name string."""
    s = text.lower()
    if "neoforge" in s or "neoforged" in s:
        return "neoforge"
    if "quilt" in s:
        return "quilt"
    if "fabric" in s:
        return "fabric"
    if "forge" in s:
        return "forge"
    if "liteloader" in s:
        return "forge"
    return "vanilla"


# Matches a bare Minecraft release / snapshot id inside a composite version
# folder name such as "1.20.1-forge-47.2.0" or "fabric-loader-0.15.7-1.20.4".
_MC_VER_RE = re.compile(
    r"(1\.\d{1,2}(?:\.\d{1,2})?)"                 # 1.20 / 1.20.1
    r"|(\d{2}w\d{2}[a-z])"                        # 24w14a snapshot
    r"|(\d\.\d+(?:\.\d+)?-(?:pre|rc)\d+)"         # 1.20-pre1
)


def _base_mc_version(version_id: str, data: dict | None = None) -> str:
    """Best-effort "what vanilla version is this really" from a version json."""
    if data:
        # A modded version json inherits from the vanilla one — that is the
        # single most reliable signal available.
        inherits = str(data.get("inheritsFrom", "")).strip()
        if inherits:
            return inherits
        # PCL2 writes *flattened* jsons with no inheritsFrom; it stamps the real
        # version into clientVersion instead.
        for key in ("clientVersion", "jar"):
            val = str(data.get(key, "")).strip()
            if val and val != version_id:
                return val
    m = _MC_VER_RE.search(version_id)
    if m:
        return next(g for g in m.groups() if g)
    if data:
        # Last resort: the asset index is named after the vanilla version.
        ai = data.get("assetIndex")
        if isinstance(ai, dict) and ai.get("id"):
            return str(ai["id"])
        if data.get("assets"):
            return str(data["assets"])
    return version_id


# mainClass → loader. The most reliable signal for *flattened* version jsons
# (PCL2 / HMCL merged manifests have no inheritsFrom and no loader in the id).
_MAINCLASS_LOADERS = (
    ("org.quiltmc.loader", "quilt"),
    ("net.fabricmc.loader", "fabric"),
    ("cpw.mods.bootstraplauncher", "forge"),   # modern forge *or* neoforge
    ("cpw.mods.modlauncher", "forge"),
    ("net.minecraftforge", "forge"),
    ("net.neoforged", "neoforge"),
)


def _detect_loader(data: dict, version_id: str) -> str:
    """Identify the mod loader of a version json, flattened or not."""
    # 1) explicit hints in the id / inheritsFrom
    loader = _loader_from_text(version_id + " " + str(data.get("inheritsFrom", "")))
    if loader != "vanilla":
        return loader
    # 2) mainClass — survives flattening
    main = str(data.get("mainClass", ""))
    for prefix, ld in _MAINCLASS_LOADERS:
        if main.startswith(prefix):
            loader = ld
            break
    # 3) full library scan — also disambiguates forge vs neoforge, which share
    #    the same BootstrapLauncher mainClass.
    names = " ".join(
        str(lib.get("name", "")) for lib in data.get("libraries", [])
        if isinstance(lib, dict)
    ).lower()
    if "net.neoforged:" in names or "neoforge" in names:
        return "neoforge"
    if loader != "vanilla":
        return loader
    if "net.minecraftforge:" in names:
        return "forge"
    if "org.quiltmc:" in names:
        return "quilt"
    if "net.fabricmc:" in names:
        return "fabric"
    return "vanilla"


def _read_version_json(vjson: str) -> dict:
    try:
        with open(vjson, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _enum_standard_versions(root: str) -> list[tuple[str, str, str, str]]:
    """List every launchable version inside a standard game directory.

    Returns (version_id, base_mc_version, loader, version_dir) tuples. This is
    the fix for the PCL2 / HMCL case: one ``.minecraft`` routinely holds many
    versions, and the old scanner only ever surfaced the newest one.
    """
    vdir = os.path.join(root, "versions")
    if not os.path.isdir(vdir):
        return []
    out = []
    try:
        entries = list(os.scandir(vdir))
    except OSError:
        return []
    for e in entries:
        if not e.is_dir():
            continue
        vjson = os.path.join(e.path, e.name + ".json")
        if not os.path.isfile(vjson):
            continue
        data = _read_version_json(vjson)
        # Use the folder name, not data["id"]: launchers rename the folder and
        # minecraft-launcher-lib resolves versions by *folder*, so the folder
        # name is what we must hand back for launching.
        vid = e.name
        base = _base_mc_version(str(data.get("id") or vid), data)
        loader = _detect_loader(data, vid)
        out.append((vid, base, loader, e.path))
    return out


def _is_isolated_version_dir(version_dir: str) -> bool:
    """True when a launcher put this version's saves/mods inside its own dir.

    Both HMCL (``gameDirType=ISOLATED``) and PCL2 (版本隔离) do this; instead of
    parsing each launcher's private config we just look for the tell-tale
    per-version game folders, which works for every launcher uniformly.
    """
    for marker in ("saves", "mods", "config", "resourcepacks", "options.txt"):
        if os.path.exists(os.path.join(version_dir, marker)):
            return True
    # HMCL states it explicitly — honour that when present.
    cfg = os.path.join(version_dir, "hmclversion.cfg")
    if os.path.isfile(cfg):
        try:
            with open(cfg, encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            if '"ISOLATED"' in raw or '"VERSION_FOLDER"' in raw:
                return True
        except OSError:
            pass
    return False


def _detect_version(mc_dir: str):
    """Return (game_version, loader) from the newest version manifest."""
    versions = _enum_standard_versions(mc_dir)
    if not versions:
        return ("unknown", "vanilla")
    versions.sort(
        key=lambda v: os.path.getmtime(os.path.join(v[3], v[0] + ".json"))
        if os.path.isfile(os.path.join(v[3], v[0] + ".json")) else 0,
        reverse=True,
    )
    vid, base, loader, _ = versions[0]
    return (base or vid, loader)


# ---------- launcher-specific metadata parsers ----------

# mmc-pack.json component uid → our loader id. Source: PrismLauncher meta repo.
_MMC_LOADER_UIDS = {
    "net.fabricmc.fabric-loader": "fabric",
    "org.quiltmc.quilt-loader": "quilt",
    "net.minecraftforge": "forge",
    "net.neoforged": "neoforge",
    "com.mumfrey.liteloader": "forge",
}


def _read_instance_cfg(path: str) -> dict:
    """Parse MultiMC/Prism ``instance.cfg`` (a flat INI without a section)."""
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(("#", "[")):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _read_mmc_pack(path: str) -> tuple[str, str, str]:
    """Return (mc_version, loader, loader_version) from ``mmc-pack.json``."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return ("unknown", "vanilla", "")
    mc = "unknown"
    loader = "vanilla"
    loader_ver = ""
    for comp in data.get("components", []):
        if not isinstance(comp, dict):
            continue
        uid = str(comp.get("uid", ""))
        ver = str(comp.get("version", ""))
        if uid == "net.minecraft":
            mc = ver or mc
        elif uid in _MMC_LOADER_UIDS:
            loader = _MMC_LOADER_UIDS[uid]
            loader_ver = ver
    return (mc, loader, loader_ver)


def _read_curseforge(path: str) -> tuple[str, str, str, str]:
    """Return (name, mc_version, loader, loader_version) from CurseForge json."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return ("", "unknown", "vanilla", "")
    name = str(data.get("name") or "")
    bml = data.get("baseModLoader") or {}
    mc = str(bml.get("minecraftVersion") or data.get("gameVersion") or "unknown")
    raw = str(bml.get("name") or bml.get("forgeVersion") or "")
    loader = _loader_from_text(raw)
    loader_ver = raw.split("-", 1)[1] if "-" in raw else ""
    return (name, mc, loader, loader_ver)


def _read_modrinth_profile(path: str) -> tuple[str, str, str, str]:
    """Return (name, mc_version, loader, loader_version) from profile.json."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return ("", "unknown", "vanilla", "")
    name = str(data.get("name") or "")
    mc = str(data.get("game_version") or "unknown")
    loader = str(data.get("loader") or "vanilla").lower()
    if loader not in ("vanilla", "fabric", "forge", "quilt", "neoforge"):
        loader = _loader_from_text(loader)
    lv = data.get("loader_version")
    loader_ver = str(lv.get("id", "")) if isinstance(lv, dict) else str(lv or "")
    return (name, mc, loader, loader_ver)


def _official_profile_names(mc_dir: str) -> dict[str, str]:
    """version id → profile name, read from ``launcher_profiles.json``."""
    p = os.path.join(mc_dir, "launcher_profiles.json")
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    out: dict[str, str] = {}
    for prof in (data.get("profiles") or {}).values():
        if not isinstance(prof, dict):
            continue
        vid = str(prof.get("lastVersionId") or "")
        nm = str(prof.get("name") or "").strip()
        if vid and nm:
            out.setdefault(vid, nm)
    return out


# ---------- instance discovery ----------

class _Collector:
    """Accumulates discovered instances, de-duplicated by (game dir, version)."""

    def __init__(self) -> None:
        self.results: list[ScannedInstance] = []
        self._seen: set[tuple[str, str]] = set()
        self._roots_done: set[str] = set()

    # -- generic --------------------------------------------------------
    def emit(self, inst: ScannedInstance) -> None:
        key = (os.path.normcase(os.path.normpath(inst.mc_dir)), inst.version_id)
        if key in self._seen:
            return
        self._seen.add(key)
        inst.mc_dir = os.path.normpath(inst.mc_dir)
        inst.mods = _count_jars(os.path.join(inst.mc_dir, "mods"))
        inst.resource_packs = _count_subdirs(os.path.join(inst.mc_dir, "resourcepacks"))
        inst.shaders = _count_subdirs(os.path.join(inst.mc_dir, "shaderpacks"))
        inst.saves = _count_subdirs(os.path.join(inst.mc_dir, "saves"))
        self.results.append(inst)

    def claimed(self, root: str) -> bool:
        """True when *root* was already processed by a more specific handler."""
        return os.path.normcase(os.path.normpath(root)) in self._roots_done

    def claim(self, root: str) -> bool:
        key = os.path.normcase(os.path.normpath(root))
        if key in self._roots_done:
            return False
        self._roots_done.add(key)
        return True

    # -- standard (official / HMCL / PCL2 / TLauncher / custom) ----------
    def add_standard(self, root: str, launcher: str, name_hint: str = "") -> int:
        """Emit ONE ENTRY PER VERSION found in a standard game directory.

        A single ``.minecraft`` managed by PCL2 or HMCL routinely contains a
        dozen versions; treating the folder as one instance (the old
        behaviour) is exactly why most of the user's games never showed up.
        """
        root = os.path.normpath(root)
        if not self.claim(root):
            return 0
        versions = _enum_standard_versions(root)
        if not versions:
            return 0
        profile_names = _official_profile_names(root)
        count = 0
        for vid, base, loader, vdir in versions:
            isolated = _is_isolated_version_dir(vdir)
            game_dir = vdir if isolated else root
            label = profile_names.get(vid) or vid
            if name_hint:
                label = f"{name_hint} · {label}"
            self.emit(ScannedInstance(
                launcher=launcher,
                name=label,
                game_version=base or vid,
                loader=loader,
                mc_dir=game_dir,
                version_id=vid,
                kind="standard",
                needs_convert=False,
                isolated=isolated,
                note="isolated" if isolated else "",
            ))
            count += 1
        return count

    # -- MultiMC / Prism / PolyMC ---------------------------------------
    def add_mmc(self, inst_dir: str, launcher: str) -> bool:
        cfg_path = os.path.join(inst_dir, "instance.cfg")
        pack_path = os.path.join(inst_dir, "mmc-pack.json")
        if not os.path.isfile(cfg_path):
            return False
        cfg = _read_instance_cfg(cfg_path)
        name = cfg.get("name") or os.path.basename(inst_dir)
        # Prism/MultiMC use "minecraft"; very old MultiMC used ".minecraft".
        game_dir = os.path.join(inst_dir, "minecraft")
        if not os.path.isdir(game_dir):
            alt = os.path.join(inst_dir, ".minecraft")
            game_dir = alt if os.path.isdir(alt) else game_dir
        mc, loader, loader_ver = ("unknown", "vanilla", "")
        if os.path.isfile(pack_path):
            mc, loader, loader_ver = _read_mmc_pack(pack_path)
        if mc == "unknown":
            mc = cfg.get("IntendedVersion", "unknown")
        # Prism keeps *patches*, not a Mojang version json — nothing here is
        # directly launchable by minecraft-launcher-lib until we rebuild it.
        std = _enum_standard_versions(game_dir)
        needs_convert = not std
        self.claim(inst_dir)
        self.claim(game_dir)
        self.emit(ScannedInstance(
            launcher=launcher,
            name=name,
            game_version=mc,
            loader=loader,
            loader_version=loader_ver,
            mc_dir=game_dir,
            version_id=std[0][0] if std else "",
            kind="mmc",
            needs_convert=needs_convert,
            isolated=True,
            note="mmc_convert" if needs_convert else "",
        ))
        return True

    # -- CurseForge ------------------------------------------------------
    def add_curseforge(self, inst_dir: str) -> bool:
        meta = os.path.join(inst_dir, "minecraftinstance.json")
        if not os.path.isfile(meta):
            return False
        name, mc, loader, loader_ver = _read_curseforge(meta)
        # CurseForge uses the instance folder itself as the game directory.
        std = _enum_standard_versions(inst_dir)
        self.claim(inst_dir)
        self.emit(ScannedInstance(
            launcher="CurseForge",
            name=name or os.path.basename(inst_dir),
            game_version=mc,
            loader=loader,
            loader_version=loader_ver,
            mc_dir=inst_dir,
            version_id=std[0][0] if std else "",
            kind="curseforge",
            needs_convert=not std,
            isolated=True,
            note="shared_libs" if not std else "",
        ))
        return True

    # -- Modrinth App ----------------------------------------------------
    def add_modrinth(self, prof_dir: str) -> bool:
        meta = os.path.join(prof_dir, "profile.json")
        if not os.path.isfile(meta):
            # Legacy layout: instances/<id>/.minecraft
            legacy = os.path.join(prof_dir, ".minecraft")
            if os.path.isdir(legacy):
                return bool(self.add_standard(legacy, "Modrinth",
                                              os.path.basename(prof_dir)))
            return False
        name, mc, loader, loader_ver = _read_modrinth_profile(meta)
        std = _enum_standard_versions(prof_dir)
        self.claim(prof_dir)
        self.emit(ScannedInstance(
            launcher="Modrinth",
            name=name or os.path.basename(prof_dir),
            game_version=mc,
            loader=loader,
            loader_version=loader_ver,
            mc_dir=prof_dir,
            version_id=std[0][0] if std else "",
            kind="modrinth",
            needs_convert=not std,
            isolated=True,
            note="modrinth_shared" if not std else "",
        ))
        return True


def discover_instances(progress=None) -> list[ScannedInstance]:
    col = _Collector()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    public = os.environ.get("PUBLIC") or str(Path.home().parent / "Public")

    def tick(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:  # noqa: BLE001
                pass

    # ---- 1) MMC-family roots (MultiMC / Prism / PolyMC) ----------------
    tick("MultiMC / Prism")
    for launcher, base in (
        ("MultiMC", os.path.join(appdata, "MultiMC")),
        ("Prism", os.path.join(appdata, "PrismLauncher")),
        ("Prism", os.path.join(local, "PrismLauncher")),
        ("PolyMC", os.path.join(appdata, "PolyMC")),
    ):
        _scan_mmc_root(os.path.join(base, "instances"), launcher, col)

    # ---- 2) CurseForge --------------------------------------------------
    tick("CurseForge")
    for cf in (
        os.path.join(public, "Games", "CurseForge", "Minecraft", "Instances"),
        os.path.join(profile, "curseforge", "minecraft", "Instances"),
        os.path.join(profile, "Documents", "curseforge", "minecraft", "Instances"),
    ):
        if os.path.isdir(cf):
            for e in _safe_scandir(cf):
                if e.is_dir():
                    col.add_curseforge(e.path)

    # ---- 3) Modrinth App ------------------------------------------------
    tick("Modrinth")
    for mr in (
        os.path.join(appdata, "com.modrinth.theseus", "profiles"),
        os.path.join(appdata, "ModrinthApp", "profiles"),
        os.path.join(appdata, ".modrinth", "instances"),
    ):
        if os.path.isdir(mr):
            for e in _safe_scandir(mr):
                if e.is_dir():
                    col.add_modrinth(e.path)

    # ---- 4) ATLauncher --------------------------------------------------
    tick("ATLauncher")
    for base in (os.path.join(profile, "ATLauncher"),
                 os.path.join(local, "ATLauncher")):
        inst = os.path.join(base, "Instances")
        if os.path.isdir(inst):
            for e in _safe_scandir(inst):
                if e.is_dir():
                    col.add_standard(e.path, "ATLauncher", e.name)

    # ---- 5) Standard-layout launchers (official / HMCL / PCL2 / TL) -----
    tick("Official / HMCL / PCL2")
    official = os.path.join(appdata, ".minecraft")
    # HMCL and PCL2 both default to %APPDATA%/.minecraft; label by whichever
    # launcher's own config dir exists so the row is meaningful.
    label = "Official"
    if os.path.isdir(os.path.join(appdata, ".hmcl")):
        label = "HMCL"
    elif os.path.isdir(os.path.join(appdata, "PCL")) or \
            os.path.isfile(os.path.join(official, "PCL", "Setup.ini")):
        label = "PCL2"
    col.add_standard(official, label)

    for root, launcher in (
        (os.path.join(appdata, ".tlauncher", "minecraft"), "TLauncher"),
        (os.path.join(appdata, ".tlauncher", "legacy", "Minecraft", "game"), "TLauncher"),
        (os.path.join(profile, ".minecraft"), "Other"),
        (os.path.join(local, ".minecraft"), "Other"),
    ):
        col.add_standard(root, launcher)

    # PCL2 is usually *portable*: the exe sits next to a .minecraft folder.
    for pcl_root in (
        os.path.join(appdata, ".pcl2"), os.path.join(profile, ".pcl2"),
        os.path.join(local, "Programs", "pcl2"), os.path.join(local, "pcl2"),
    ):
        if os.path.isdir(pcl_root):
            col.add_standard(os.path.join(pcl_root, ".minecraft"), "PCL2")
            col.add_standard(pcl_root, "PCL2")

    # ---- 6) Disk sweep: portable launchers + stray game dirs ------------
    tick("扫描磁盘")
    _sweep(profile, col, max_depth=5, progress=progress)
    for drive in _drive_roots():
        _sweep(drive, col, max_depth=4, progress=progress)

    return col.results


def _safe_scandir(path: str):
    try:
        return list(os.scandir(path))
    except (OSError, PermissionError):
        return []


def _scan_mmc_root(instances_dir: str, launcher: str, col: _Collector) -> int:
    """Import every instance under a MultiMC-family ``instances/`` folder."""
    if not os.path.isdir(instances_dir):
        return 0
    n = 0
    for e in _safe_scandir(instances_dir):
        if e.is_dir() and col.add_mmc(e.path, launcher):
            n += 1
    return n


def _looks_like_mmc_root(path: str) -> bool:
    """A MultiMC/Prism ``instances`` dir: at least one child has instance.cfg."""
    for e in _safe_scandir(path)[:60]:
        if e.is_dir() and os.path.isfile(os.path.join(e.path, "instance.cfg")):
            return True
    return False


def _sweep(root: str, col: _Collector, max_depth: int, progress=None) -> None:
    """Depth-capped walk looking for game dirs *and* portable launcher roots.

    Portable installs (PCL2 / Prism / HMCL unzipped anywhere) are the common
    case on Chinese setups, so a name-only lookup in %APPDATA% misses most of
    them. We instead recognise the on-disk markers each launcher leaves.
    """
    stack = [(root, 0)]
    visited = 0
    while stack:
        path, depth = stack.pop()
        visited += 1
        if progress and visited % 500 == 0:
            try:
                progress(path)
            except Exception:  # noqa: BLE001
                pass
        for e in _safe_scandir(path):
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = e.name
            low = name.lower()
            if low in _SKIP_DIRS or name.startswith("$"):
                continue

            # Skip system AppData only under user-profile trees.
            # A custom "AppData" / "appdata" folder on a drive root (e.g.
            # D:\Appdata) may contain game instances and must NOT be pruned.
            if low == "appdata" and _is_system_appdata(e.path):
                continue

            # a) MultiMC / Prism / PolyMC portable root
            if low == "instances" and _looks_like_mmc_root(e.path):
                parent = os.path.basename(os.path.dirname(e.path)).lower()
                launcher = ("Prism" if "prism" in parent else
                            "PolyMC" if "poly" in parent else "MultiMC")
                _scan_mmc_root(e.path, launcher, col)
                continue

            # b) CurseForge instance folder
            if os.path.isfile(os.path.join(e.path, "minecraftinstance.json")):
                col.add_curseforge(e.path)
                continue

            # c) standard game dir (.minecraft / minecraft / anything with versions/)
            if low in (".minecraft", "minecraft") and _is_mc_dir(e.path):
                launcher_root = os.path.dirname(e.path)
                col.add_standard(
                    e.path, _guess_launcher(e.path),
                    name_hint=os.path.basename(launcher_root),
                )
                continue
            if depth > 0 and _is_mc_dir(e.path) and not col.claimed(e.path):
                launcher_root = os.path.dirname(e.path)
                col.add_standard(
                    e.path, _guess_launcher(e.path),
                    name_hint=os.path.basename(launcher_root),
                )
                continue

            if depth < max_depth:
                stack.append((e.path, depth + 1))


def _guess_launcher(mc_dir: str) -> str:
    """Name the owning launcher from marker files next to the game dir."""
    parent = os.path.dirname(mc_dir)
    checks = [
        ("PCL2", ("PCL", "Plain Craft Launcher.exe", "PCL.ini")),
        ("HMCL", ("hmcl.json", "HMCL.exe")),
        ("BakaXL", ("BakaXL.exe",)),
        ("TLauncher", ("TLauncher.exe",)),
    ]
    for label, markers in checks:
        for m in markers:
            if os.path.exists(os.path.join(parent, m)) or \
                    os.path.exists(os.path.join(mc_dir, m)):
                return label
    # HMCL/PCL2 leave per-version configs inside the game dir
    vdir = os.path.join(mc_dir, "versions")
    for e in _safe_scandir(vdir)[:20]:
        if e.is_dir():
            if os.path.isfile(os.path.join(e.path, "hmclversion.cfg")):
                return "HMCL"
            if os.path.isfile(os.path.join(e.path, "PCL", "Setup.ini")):
                return "PCL2"
    return "Other"


def _drive_roots() -> list[str]:
    if platform.system() != "Windows":
        return [os.path.expanduser("~")]
    roots = []
    for letter in string.ascii_uppercase:
        d = f"{letter}:/"
        if os.path.isdir(d):
            roots.append(d)
    return roots


# ---------- Java discovery ----------

def _read_java_version(home: str):
    rel = os.path.join(home, "release")
    ver = ""
    major = 0
    if os.path.isfile(rel):
        try:
            with open(rel, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("JAVA_VERSION"):
                        ver = line.split("=", 1)[1].strip().strip('"')
                        m = re.match(r'"?(\d+)(?:\.(\d+))?', ver)
                        if m:
                            major = int(m.group(1))
                            if major == 1 and m.group(2):
                                major = int(m.group(2))  # legacy 1.8 -> 8
                        break
        except OSError:
            pass
    return ver, major


def discover_javas(deep: bool = False, progress=None) -> list[JavaInstall]:
    """Find installed Java runtimes.

    ``deep=True`` additionally sweeps every drive for *portable* JDK/JRE
    folders (unzipped archives that were never registered anywhere: no
    JAVA_HOME, no registry entry, not on PATH). That is the only way to find
    the "I just unzipped it to D:\\AppData" case.
    """
    out: list[JavaInstall] = []
    seen: set[str] = set()
    is_win = platform.system() == "Windows"
    exe = "java.exe" if is_win else "java"
    # These were previously referenced without being defined, which raised
    # NameError and made the whole Java scan silently return nothing.
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))

    def add_java(path: str) -> None:
        path = os.path.normpath(path)
        if path in seen or not os.path.isfile(path):
            return
        seen.add(path)
        ver, major = _read_java_version(os.path.dirname(os.path.dirname(path)))
        out.append(JavaInstall(path=path, version=ver, major=major))

    # 1) JAVA_HOME
    jh = os.environ.get("JAVA_HOME")
    if jh:
        add_java(os.path.join(jh, "bin", exe))

    # 2) Program Files families (Oracle / Adoptium / Zulu / Microsoft / Corretto …)
    for base in (os.environ.get("ProgramFiles", "C:/Program Files"),
                 os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")):
        if not base or not os.path.isdir(base):
            continue
        for fam in _JAVA_FAMILIES:
            d = os.path.join(base, fam)
            if not os.path.isdir(d):
                continue
            for e in os.scandir(d):
                if e.is_dir():
                    add_java(os.path.join(e.path, "bin", exe))

    # 3) Official launcher bundled runtimes (%APPDATA%/.minecraft/runtime)
    rt = os.path.join(os.environ.get("APPDATA", ""), ".minecraft", "runtime")
    if os.path.isdir(rt):
        for e in os.scandir(rt):
            if not e.is_dir():
                continue
            for sub in os.scandir(e.path):
                if sub.is_dir() and os.path.isfile(os.path.join(sub.path, "bin", exe)):
                    add_java(os.path.join(sub.path, "bin", exe))

    # 4) Windows Registry (JavaSoft entries) — finds JDK/JRE installed via MSI
    if is_win:
        try:
            import winreg
            for hive_key, hive in [
                (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
                (winreg.HKEY_CURRENT_USER, "HKCU"),
            ]:
                for reg_path in (
                    r"SOFTWARE\JavaSoft\Java Development Kit",
                    r"SOFTWARE\JavaSoft\Java Runtime Environment",
                    r"SOFTWARE\JavaSoft\JRE",
                ):
                    try:
                        key = winreg.OpenKey(hive_key, reg_path)
                        i = 0
                        while True:
                            ver_name = winreg.EnumKey(key, i)
                            i += 1
                            try:
                                subkey = winreg.OpenKey(key, ver_name)
                                java_home_val, _ = winreg.QueryValueEx(subkey, "JavaHome")
                                winreg.CloseKey(subkey)
                                if java_home_val:
                                    add_java(os.path.join(java_home_val, "bin", exe))
                            except (OSError, FileNotFoundError):
                                pass
                        winreg.CloseKey(key)
                    except (OSError, FileNotFoundError):
                        pass
        except Exception:
            pass  # registry read not critical

    # 5) PATH environment — picks up Java added to system/user PATH
    path_env = os.environ.get("PATH", "")
    for p in path_env.split(os.pathsep):
        if not p:
            continue
        candidate = os.path.join(p, exe)
        # Only check obvious java bin dirs (avoid scanning every PATH entry)
        parent_lower = os.path.basename(p).lower()
        if any(k in parent_lower for k in ("java", "jdk", "jre", "bin")):
            add_java(candidate)

    # 6) Common portable / third-party locations
    portable_roots = []
    if is_win:
        program_data = os.environ.get("ProgramData", "C:/ProgramData")
        portable_roots.extend([
            os.path.join(local, "Programs"),             # user-local installs
            os.path.join(profile, "scoop", "apps"),      # scoop
            os.path.join(program_data, "scoop", "apps"), # scoop global
            os.path.join(profile, ".chocolatey", "lib"), # chocolatey
            os.path.join(local, "JetBrains"),            # JetBrains Runtime
            os.path.join(profile, ".gradle", "jdks"),    # Gradle JDKs
            os.path.join(appdata, "JetBrains"),          # JetBrains AppData
            os.path.join(local, "Android", "Sdk"),       # Android Studio bundled JDK
            os.path.join(profile, ".jdks"),              # IntelliJ downloaded JDKs
            os.path.join(local, "Temp", "jdk"),
        ])
    else:
        portable_roots.extend([
            os.path.expanduser("~/.sdkman/candidates/java"),
            os.path.expanduser("/usr/lib/jvm"),
            os.path.expanduser("/usr/local/lib/jvm"),
        ])
    for root in portable_roots:
        if not os.path.isdir(root):
            continue
        try:
            for e in os.scandir(root):
                if e.is_dir():
                    # Check for both direct bin/java.exe and nested JDK layouts
                    add_java(os.path.join(e.path, "bin", exe))
                    # Some layouts: <root>/<version>/Contents/Home/bin (macOS)
                    # or <root>/<version>/bin (linux)
                    for sub in ("Contents/Home", "jre"):
                        add_java(os.path.join(e.path, sub, "bin", exe))
        except OSError:
            pass

    # 7) Other launchers ship their own runtimes — reuse them
    for rt_root in _launcher_runtime_roots(appdata, local, profile):
        _sweep_java(rt_root, add_java, exe, max_depth=4, progress=progress)

    # 8) DEEP: portable / unzipped JDKs anywhere on disk. This is the only way
    #    to find a runtime the user just extracted to e.g. D:\AppData\jdk-21.
    if deep:
        for drive in _drive_roots():
            _sweep_java(drive, add_java, exe, max_depth=5, progress=progress)

    return out


def _launcher_runtime_roots(appdata: str, local: str, profile: str) -> list[str]:
    """Runtime folders bundled by other Minecraft launchers."""
    cands = [
        os.path.join(appdata, ".minecraft", "runtime"),
        os.path.join(appdata, ".hmcl", "java"),
        os.path.join(appdata, "PrismLauncher", "java"),
        os.path.join(appdata, "MultiMC", "java"),
        os.path.join(appdata, ".modrinth", "meta", "java_versions"),
        os.path.join(local, "Packages"),  # MS Store official launcher (shallow)
        os.path.join(profile, "AppData", "Roaming", ".minecraft", "runtime"),
        os.path.join(local, "Programs", "pcl2", "java"),
        os.path.join(profile, "PCL", "Java"),
    ]
    return [c for c in cands if os.path.isdir(c)]


# Directory names that can never contain a JDK worth scanning — pruning these
# is what keeps the whole-disk sweep down to a few seconds instead of minutes.
_JAVA_SKIP = {
    "$Recycle.Bin", "System Volume Information", "Windows", "WinSxS",
    "node_modules", ".git", "site-packages", "__pycache__", "venv", ".venv",
    "Microsoft SQL Server", "WindowsApps", "assets", "libraries", "mods",
    "resourcepacks", "saves", "shaderpacks", "versions", "logs", "screenshots",
}


def _sweep_java(root: str, add_java, exe: str, max_depth: int, progress=None) -> None:
    """Breadth-limited hunt for <something>/bin/<java exe> under *root*."""
    stack = [(root, 0)]
    visited = 0
    while stack:
        path, depth = stack.pop()
        visited += 1
        if progress and visited % 400 == 0:
            try:
                progress(path)
            except Exception:  # noqa: BLE001 - progress must never break the scan
                pass
        # A JDK/JRE root is recognised by bin/<exe>; "release" confirms it.
        cand = os.path.join(path, "bin", exe)
        if os.path.isfile(cand):
            add_java(cand)
            continue  # don't descend into a runtime we already matched
        if depth >= max_depth:
            continue
        try:
            entries = list(os.scandir(path))
        except (OSError, PermissionError):
            continue
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if e.name in _JAVA_SKIP or e.name.startswith("$"):
                continue
            stack.append((e.path, depth + 1))


def scan_all():
    """Convenience: run both discoveries. Returns (instances, javas)."""
    return discover_instances(), discover_javas()
