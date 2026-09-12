"""Download & install any Minecraft-supported Java runtime, no admin rights.

Source: Eclipse Adoptium (Temurin) — the same builds mainstream launchers hand out.
We fetch the portable ZIP and unpack it under our own data dir, so nothing
touches the system, no installer UAC prompt, and several majors can coexist.

Every Java major Minecraft has ever needed is offered:
    8  → 1.0 – 1.16.5
    11 → optional for old modpacks
    16 → 1.17.x
    17 → 1.18 – 1.20.4
    21 → 1.20.5+ / 1.21+
    22/23/24 → future / snapshot builds
"""
from __future__ import annotations

import os
import platform
import shutil
import zipfile

import requests

from ..paths import get_data_dir

_API = "https://api.adoptium.net/v3/binary/latest"
_RELEASES_API = "https://api.adoptium.net/v3/info/available_releases"

# major -> which Minecraft versions it covers (shown in the UI)
JAVA_CHOICES = [
    (8,  "1.0 – 1.16.5"),
    (11, "旧整合包 / Legacy modpacks"),
    (16, "1.17 – 1.17.1"),
    (17, "1.18 – 1.20.4"),
    (21, "1.20.5+ / 1.21+"),
    (24, "快照 / Snapshot"),
]

_DEFAULT_MAJORS = [8, 17, 21]


def java_root() -> str:
    """Where our downloaded runtimes live."""
    return os.path.join(get_data_dir(), "java")


def installed_majors() -> dict[int, str]:
    """Return {major: java_exe_path} for runtimes WE installed."""
    out: dict[int, str] = {}
    root = java_root()
    if not os.path.isdir(root):
        return out
    exe = "java.exe" if platform.system() == "Windows" else "java"
    for name in os.listdir(root):
        if not name.startswith("jdk-") and not name.startswith("jre-"):
            continue
        try:
            major = int(name.split("-")[1].split(".")[0])
        except (IndexError, ValueError):
            continue
        # Adoptium zips unpack to <root>/<tag>/<jdk-xx+yy-jre>/bin/java.exe
        for base, _dirs, files in os.walk(os.path.join(root, name)):
            if exe in files and os.path.basename(base) == "bin":
                out[major] = os.path.join(base, exe)
                break
    return out


def available_majors() -> list[int]:
    """Ask Adoptium which LTS/current majors exist right now (best effort)."""
    try:
        r = requests.get(_RELEASES_API, timeout=10)
        r.raise_for_status()
        data = r.json()
        return sorted(set(data.get("available_releases", [])))
    except Exception:  # noqa: BLE001 - offline → fall back to our static list
        return [m for m, _ in JAVA_CHOICES]


def _os_arch() -> tuple[str, str]:
    sysname = platform.system().lower()
    os_name = {"windows": "windows", "darwin": "mac", "linux": "linux"}.get(sysname, "linux")
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        arch = "x64"
    elif machine in ("arm64", "aarch64"):
        arch = "aarch64"
    elif machine in ("i386", "i686", "x86"):
        arch = "x86"
    else:
        arch = "x64"
    return os_name, arch


def download_url(major: int, image_type: str = "jre") -> str:
    os_name, arch = _os_arch()
    return (
        f"{_API}/{major}/ga/{os_name}/{arch}/{image_type}/hotspot/normal/eclipse"
        f"?project=jdk"
    )


def install_java(major: int, progress=None, image_type: str = "jre") -> str:
    """Download + unpack Java *major*. Returns the java executable path.

    ``progress(done_bytes, total_bytes, phase)`` is called during the download
    (``total`` may be 0 when the server omits Content-Length).
    """
    exe_name = "java.exe" if platform.system() == "Windows" else "java"
    already = installed_majors().get(major)
    if already and os.path.isfile(already):
        return already

    root = java_root()
    os.makedirs(root, exist_ok=True)
    target = os.path.join(root, f"jre-{major}")
    tmp_zip = os.path.join(root, f"_dl_{major}.zip")

    url = download_url(major, image_type)
    if progress:
        progress(0, 0, "connect")
    with requests.get(url, stream=True, timeout=60, allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp_zip, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total, "download")

    if progress:
        progress(0, 0, "extract")
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)
    try:
        if tmp_zip.endswith(".zip") and zipfile.is_zipfile(tmp_zip):
            with zipfile.ZipFile(tmp_zip) as z:
                from .utils import safe_extract_zip
                safe_extract_zip(z, target)  # round-35 zip-slip 防护
        else:  # linux/mac tarballs
            shutil.unpack_archive(tmp_zip, target)
    finally:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass

    for base, _dirs, files in os.walk(target):
        if exe_name in files and os.path.basename(base) == "bin":
            path = os.path.join(base, exe_name)
            if platform.system() != "Windows":
                try:
                    os.chmod(path, 0o755)
                except OSError:
                    pass
            return path
    raise RuntimeError(f"解压后未找到 {exe_name}（{target}）")


def recommended_majors(existing: list[int] | None = None) -> list[int]:
    """Which majors a fresh machine should grab to cover all of Minecraft."""
    have = set(existing or [])
    return [m for m in _DEFAULT_MAJORS if m not in have]
