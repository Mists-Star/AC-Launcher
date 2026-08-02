"""Crash analysis — turn raw game logs / crash reports into plain-language
reasons + fix suggestions, and link them to the launcher's self-repair.

Two inputs are read for a given instance:
  - ``<mc_dir>/logs/latest.log`` — the run the game died on
  - ``<mc_dir>/crash-reports/*.txt`` — Mojang's structured crash dumps

Patterns are matched against both and folded into a single list of
``CrashFinding`` items, each with a severity, a human-readable cause, a fix
suggestion, and whether the launcher can attempt an automatic repair.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

SEV_CRITICAL = "critical"
SEV_WARNING = "warning"
SEV_INFO = "info"


@dataclass
class CrashFinding:
    kind: str                  # stable id, e.g. "mod_dep_missing"
    severity: str              # critical / warning / info
    title: str                 # short label
    reason: str                # what happened (plain language)
    suggestion: str            # what the player can do
    repairable: bool = False   # launcher can attempt auto-fix
    detail: str = ""           # raw log line / stack excerpt
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# pattern library
# --------------------------------------------------------------------------- #
# Each rule: (kind, severity, title_i18n_key, reason_i18n_key,
#             suggestion_i18n_key, repairable, regex_flags)
# The *text* is resolved later (analysis returns keys; UI localizes). To keep
# this module UI-free we store i18n keys and let the dialog translate.

_RULES = [
    # ---- Fabric / Quilt mandatory dependencies ----
    (
        "mod_dep_missing", SEV_CRITICAL, "crash.kind.mod_dep_missing",
        "crash.reason.mod_dep_missing", "crash.fix.mod_dep_missing", True,
        re.compile(r"(Missing or unsupported mandatory dependencies|"
                   r"requires .* but could not find|"
                   r"missing dependency)", re.IGNORECASE),
    ),
    # ---- NoClassDefFound / NoSuchMethod (loader/version mismatch) ----
    (
        "loader_mismatch", SEV_CRITICAL, "crash.kind.loader_mismatch",
        "crash.reason.loader_mismatch", "crash.fix.loader_mismatch", True,
        re.compile(r"(NoClassDefFoundError|NoSuchMethodError|"
                   r"ClassNotFoundException: .*Mod|"
                   r"Failed to load mod .* was compiled for)", re.IGNORECASE),
    ),
    # ---- Java version too old / too new ----
    (
        "java_version", SEV_CRITICAL, "crash.kind.java_version",
        "crash.reason.java_version", "crash.fix.java_version", True,
        re.compile(r"(UnsupportedClassVersionError|"
                   r"Bad class file|Java (SE )?Runtime Environment version|"
                   r"Unsupported major\.minor version|"
                   r"requires Java \d+)", re.IGNORECASE),
    ),
    # ---- OutOfMemory ----
    (
        "out_of_memory", SEV_CRITICAL, "crash.kind.out_of_memory",
        "crash.reason.out_of_memory", "crash.fix.out_of_memory", True,
        re.compile(r"(OutOfMemoryError|not enough memory|"
                   r"GC overhead limit exceeded)", re.IGNORECASE),
    ),
    # ---- Graphics / driver ----
    (
        "gpu_driver", SEV_WARNING, "crash.kind.gpu_driver",
        "crash.reason.gpu_driver", "crash.fix.gpu_driver", False,
        re.compile(r"(GLFW error|OpenGL [Ee]rror|Failed to create window|"
                   r"Couldn't initialize GL|D3D11 device removed)", re.IGNORECASE),
    ),
    # ---- Mixin / transformer ----
    (
        "mixin_error", SEV_WARNING, "crash.kind.mixin_error",
        "crash.reason.mixin_error", "crash.fix.mixin_error", False,
        re.compile(r"(Mixin apply failed|MixinTransformerError|"
                   r"@Inject.*failed|mixin.*injection.*error)", re.IGNORECASE),
    ),
    # ---- Generic fatal exception ----
    (
        "fatal_exception", SEV_CRITICAL, "crash.kind.fatal_exception",
        "crash.reason.fatal_exception", "crash.fix.fatal_exception", False,
        re.compile(r"(Exception in thread \"(main|Client thread|Render thread)\"|"
                   r"A fatal error has been detected|"
                   r"E \[Terraria|Caused by: java\.)", re.IGNORECASE),
    ),
]


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
def _read_text(path: str, limit: int = 4_000_000) -> str:
    """Read a file up to *limit* chars; never raise on missing/unreadable."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def latest_log_path(mc_dir: str) -> str:
    return os.path.join(mc_dir, "logs", "latest.log")


def crash_report_paths(mc_dir: str) -> list[str]:
    """Newest-first crash report files under crash-reports/."""
    d = os.path.join(mc_dir, "crash-reports")
    if not os.path.isdir(d):
        return []
    try:
        files = [
            os.path.join(d, n) for n in os.listdir(d)
            if n.lower().endswith((".txt", ".log"))
        ]
    except OSError:
        return []
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[:3]


def analyze_instance(inst) -> list[CrashFinding]:
    """Analyze an instance's logs + crash reports. Returns findings (may be empty)."""
    mc_dir = getattr(inst, "mc_dir", None) or ""
    if not mc_dir:
        return []
    findings: list[CrashFinding] = []
    seen_kinds: set[str] = set()
    evidence: dict[str, list[str]] = {}

    # ---- latest.log (the run the game died on) ----
    log = _read_text(latest_log_path(mc_dir))
    if log:
        for kind, sev, tkey, rkey, fkey, rep, rx in _RULES:
            m = rx.search(log)
            if m:
                seen_kinds.add(kind)
                evidence.setdefault(kind, []).append(m.group(0)[:160])
        # crash marker at the very end of a successful shutdown is normal
        if not seen_kinds:
            tail = log[-4000:].strip()
            if tail and "Stopping!" not in tail[-200:]:
                # generic "something happened" fallback only if it looks abnormal
                if re.search(r"(Exception|Error|FATAL)", tail, re.IGNORECASE):
                    seen_kinds.add("fatal_exception")
                    evidence.setdefault("fatal_exception", []).append(tail[-160:])

    # ---- crash-reports (structured dumps are more specific) ----
    for cp in crash_report_paths(mc_dir):
        text = _read_text(cp, limit=1_500_000)
        if not text:
            continue
        for kind, sev, tkey, rkey, fkey, rep, rx in _RULES:
            if kind in seen_kinds:
                continue
            m = rx.search(text)
            if m:
                seen_kinds.add(kind)
                evidence.setdefault(kind, []).append(m.group(0)[:160])
                break  # one kind per report, most specific first
        # extract the top "Caused by" chain for the report's primary finding
        if "fatal_exception" not in seen_kinds and \
                re.search(r"(Exception in thread|Description:|java\.)", text):
            seen_kinds.add("fatal_exception")
            for m in re.finditer(r"(Caused by: [^\n]+)", text):
                evidence.setdefault("fatal_exception", []).append(m.group(1)[:160])
                if len(evidence["fatal_exception"]) >= 3:
                    break

    # ---- build findings ----
    for kind, sev, tkey, rkey, fkey, rep, _rx in _RULES:
        if kind not in seen_kinds:
            continue
        findings.append(CrashFinding(
            kind=kind, severity=sev,
            title=tkey, reason=rkey, suggestion=fkey,
            repairable=rep,
            detail="\n".join(evidence.get(kind, [])),
        ))
    # severity ordering: critical first
    findings.sort(key=lambda f: 0 if f.severity == SEV_CRITICAL else 1)
    return findings


# --------------------------------------------------------------------------- #
# mod dependency scan (auto-repair target)
# --------------------------------------------------------------------------- #
def scan_mod_manifests(inst) -> list[dict]:
    """Read dependency declarations from every jar in the instance's mods dir.

    Returns list of {mod_id, name, version, depends: [dep_id, ...]}.
    Recognises Fabric (fabric.mod.json) and Forge/NeoForge
    (META-INF/mods.toml) manifests.
    """
    import zipfile

    mods_dir = getattr(inst, "mods_dir", None) or os.path.join(
        getattr(inst, "mc_dir", ""), "mods")
    out: list[dict] = []
    if not os.path.isdir(mods_dir):
        return out
    for name in sorted(os.listdir(mods_dir)):
        if not name.lower().endswith(".jar"):
            continue
        path = os.path.join(mods_dir, name)
        try:
            with zipfile.ZipFile(path) as z:
                info = _manifest_from_zip(z)
        except (OSError, zipfile.BadZipFile):
            continue
        if info:
            out.append(info)
    return out


def _manifest_from_zip(z) -> dict | None:
    import json

    names = set(z.namelist())
    # ---- Fabric ----
    for cand in ("fabric.mod.json", "Fabric.mod.json", "fabric_mod.json"):
        if cand in names:
            try:
                data = json.loads(z.read(cand).decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                return None
            deps = []
            for d in (data.get("depends") or {}):
                deps.append(str(d))
            return {
                "mod_id": str(data.get("id", "")),
                "name": str(data.get("name") or data.get("id", "")),
                "version": str(data.get("version", "")),
                "depends": deps,
            }
    # ---- Forge / NeoForge (mods.toml) ----
    if "META-INF/mods.toml" in names:
        try:
            text = z.read("META-INF/mods.toml").decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return None
        mod_id = _toml_attr(text, "modId")
        deps = re.findall(r"^\s*modId\s*=\s*\"([^\"]+)\"", text, re.MULTILINE)
        deps = [d for d in deps if d and d != mod_id]
        return {
            "mod_id": mod_id or "",
            "name": _toml_attr(text, "displayName") or mod_id or "",
            "version": _toml_attr(text, "version"),
            "depends": deps,
        }
    return None


def _toml_attr(text: str, key: str) -> str:
    m = re.search(rf"^{key}\s*=\s*\"([^\"]+)\"", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def find_missing_dependencies(inst) -> list[str]:
    """Return dependency ids declared by installed mods but not present
    anywhere in the same mods folder (best-effort)."""
    mods = scan_mod_manifests(inst)
    present = {m["mod_id"] for m in mods if m["mod_id"]}
    missing: set[str] = set()
    for m in mods:
        for dep in m.get("depends", []):
            if dep and dep not in present and dep not in missing:
                # skip known "always-present" ids that aren't mods
                if dep in ("minecraft", "java", "fabricloader", "forge",
                           "neoforge", "quilt_loader", "fabric-api-base"):
                    continue
                missing.add(dep)
    # drop deps that ARE provided by another installed mod id
    return sorted(missing)


def search_and_download_missing(inst, missing_ids: list[str],
                                callback=None) -> tuple[list[str], list[str]]:
    """Try to auto-fix missing deps: search Modrinth by mod id, download the
    first hit into the mods folder. Returns (downloaded, failed)."""
    from .net_api import search_mods, download_mod_to

    downloaded, failed = [], []
    for dep in missing_ids:
        if callback:
            callback(f"正在查找依赖：{dep} …")
        try:
            hits = search_mods(dep, 0, 5, project_type="mod")
        except Exception:  # noqa: BLE001
            failed.append(dep)
            continue
        target = None
        for h in hits:
            slug = h.get("slug", "").lower()
            title = h.get("title", "").lower()
            if slug == dep.lower() or title == dep.lower() or \
                    slug.startswith(dep.lower()) or dep.lower() in slug:
                target = h
                break
        if target is None and hits:
            target = hits[0]  # best-effort: top hit
        if target is None:
            failed.append(dep)
            continue
        if callback:
            callback(f"下载依赖：{target.get('title', dep)} …")
        try:
            p = download_mod_to(target["project_id"], inst.mods_dir)
            downloaded.append(os.path.basename(p))
        except Exception:  # noqa: BLE001
            failed.append(dep)
    return downloaded, failed
