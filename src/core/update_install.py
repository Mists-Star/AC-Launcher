"""Update download + self-replace helper.

Flow (all Qt-free so it can run on a worker thread):

1. :func:`download_update` streams the signed manifest's asset into
   ``data/updates/<version>/<asset>.zip.part`` with a hard size cap, checks
   sha256/size against the *verified* manifest, then atomically renames it.
2. :func:`write_upgrade_script` writes a hidden PowerShell helper that waits
   for the launcher PID to exit, renames the old ``AC_Launcher.exe`` and
   ``_internal`` aside (fast, same volume), extracts the zip, relaunches, and
   rolls the names back on failure. Config/accounts/data beside the exe are
   left untouched.
3. :func:`launch_upgrade_helper` starts that script detached; the UI then quits.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from urllib.parse import urlsplit
from urllib.request import url2pathname

from ..paths import get_data_dir
from .update_trust import (
    TrustError,
    UpdateManifest,
    _check_url,
    file_sha256,
    verify_asset_file,
)

__all__ = [
    "UpdateCancelled",
    "download_update",
    "write_upgrade_script",
    "launch_upgrade_helper",
    "prepare_install",
    "pending_notes_path",
    "read_pending_notes",
    "clear_pending_notes",
]


class UpdateCancelled(Exception):
    """Raised when the user cancels a download."""


# --------------------------------------------------------------------------- #
# download + verify
# --------------------------------------------------------------------------- #
def download_update(
    manifest: UpdateManifest,
    *,
    dest_dir: str | None = None,
    progress=None,
    cancel=None,
    timeout: float = 30.0,
    allow_insecure: bool = False,
) -> str:
    """Download, verify and return the local zip path.

    ``progress(received, total)`` is called while streaming; ``cancel()`` is
    polled per chunk and raises :class:`UpdateCancelled` when true. A failed
    download never leaves a usable ``.zip`` behind (only a deleted ``.part``).
    """
    folder = dest_dir or os.path.join(get_data_dir(), "updates", manifest.version)
    os.makedirs(folder, exist_ok=True)
    final = os.path.join(folder, manifest.asset_name)
    if os.path.isfile(final):
        try:
            verify_asset_file(final, manifest)
            if progress:
                progress(manifest.size, manifest.size)
            return final
        except TrustError:
            try:
                os.remove(final)
            except OSError:
                pass

    part = final + ".part"
    try:
        os.remove(part)
    except OSError:
        pass

    url = _check_url(manifest.asset_url, allow_insecure)
    received = 0
    digest = hashlib.sha256()
    try:
        if urlsplit(url).scheme.lower() == "file":
            path = url2pathname(urlsplit(url).path)
            src = open(path, "rb")
        else:
            req = urllib.request.Request(
                url, headers={"User-Agent": f"AC-Launcher/{manifest.version}"}
            )
            src = urllib.request.urlopen(req, timeout=timeout)
        with src, open(part, "wb") as out:
            while True:
                if cancel and cancel():
                    raise UpdateCancelled()
                chunk = src.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > manifest.size:
                    raise TrustError(
                        "asset_size", f"stream exceeds {manifest.size} bytes"
                    )
                digest.update(chunk)
                out.write(chunk)
                if progress:
                    progress(received, manifest.size)
            out.flush()
            os.fsync(out.fileno())
    except Exception as exc:
        try:
            os.remove(part)
        except OSError:
            pass
        if isinstance(exc, (TrustError, UpdateCancelled)):
            raise
        raise TrustError("network", str(exc)) from exc

    if received != manifest.size:
        try:
            os.remove(part)
        except OSError:
            pass
        raise TrustError("asset_size", f"{received} != {manifest.size}")
    if digest.hexdigest() != manifest.sha256:
        try:
            os.remove(part)
        except OSError:
            pass
        raise TrustError("asset_hash", "sha256 mismatch")
    try:
        os.replace(part, final)
    except OSError as exc:
        raise TrustError("asset_write", str(exc)) from exc
    # Defensive re-check after the rename.
    verify_asset_file(final, manifest)
    return final


# --------------------------------------------------------------------------- #
# upgrade helper script
# --------------------------------------------------------------------------- #
def _ps(value: str) -> str:
    """Single-quoted PowerShell literal (apostrophes doubled)."""
    return "'" + str(value).replace("'", "''") + "'"


def pending_notes_path(data_dir: str | None = None) -> str:
    return os.path.join(data_dir or get_data_dir(), "updates", "pending_notes.json")


def read_pending_notes(data_dir: str | None = None) -> dict | None:
    try:
        with open(pending_notes_path(data_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


def clear_pending_notes(data_dir: str | None = None) -> None:
    try:
        os.remove(pending_notes_path(data_dir))
    except OSError:
        pass


def _write_pending_notes(manifest: UpdateManifest, data_dir: str | None = None) -> None:
    path = pending_notes_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    payload = {
        "version": manifest.version,
        "notes": list(manifest.notes),
        "terms_version": manifest.terms_version,
        "key_id": manifest.key_id,
    }
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def write_upgrade_script(
    manifest: UpdateManifest,
    asset_path: str,
    *,
    app_dir: str | None = None,
    pid: int | None = None,
    exe_name: str | None = None,
    data_dir: str | None = None,
) -> str:
    """Write the PowerShell self-replace helper and return its path."""
    if not getattr(sys, "frozen", False) and app_dir is None:
        raise TrustError("upgrade_dev_build", "自动替换只支持打包版")
    app_dir = app_dir or os.path.dirname(sys.executable)
    if not os.path.isdir(app_dir):
        raise TrustError("upgrade_app_dir", app_dir)
    if not os.path.isfile(asset_path):
        raise TrustError("asset_missing", asset_path)
    exe_name = exe_name or os.path.basename(sys.executable)
    pid = pid or os.getpid()
    data_dir = data_dir or get_data_dir()
    folder = os.path.join(data_dir, "updates")
    os.makedirs(folder, exist_ok=True)

    script = os.path.join(folder, f"upgrade_{manifest.version}.ps1")
    log = os.path.join(folder, "upgrade.log")
    notes = os.path.join(folder, "pending_notes.json")
    bak = ".upd_bak"

    # NOTE: only the exe and _internal are swapped; launcher_config.json,
    # accounts.json, data/ and logs stay in place.
    body = f"""$ErrorActionPreference = 'Stop'
$AppDir = {_ps(app_dir)}
$Zip = {_ps(asset_path)}
$Exe = {_ps(exe_name)}
$Log = {_ps(log)}
$LauncherPid = {pid}
$Bak = {_ps(bak)}
$Notes = {_ps(notes)}
function Write-UpdLog([string]$m) {{
    Add-Content -Path $Log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $m)
}}
try {{
    Write-UpdLog 'waiting for launcher to exit'
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Process -Id $LauncherPid -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {{
        Start-Sleep -Milliseconds 500
    }}
    Start-Sleep -Milliseconds 800
    $internal = Join-Path $AppDir '_internal'
    $exePath = Join-Path $AppDir $Exe
    if (Test-Path ($internal + $Bak)) {{ Remove-Item -Recurse -Force ($internal + $Bak) }}
    if (Test-Path ($exePath + $Bak)) {{ Remove-Item -Force ($exePath + $Bak) }}
    if (Test-Path $internal) {{ Rename-Item -Path $internal -NewName ('_internal' + $Bak) }}
    if (Test-Path $exePath) {{ Rename-Item -Path $exePath -NewName ($Exe + $Bak) }}
    Write-UpdLog 'old files moved aside; extracting'
    Expand-Archive -Path $Zip -DestinationPath $AppDir -Force
    if (-not (Test-Path $exePath)) {{ throw 'updated exe missing after extract' }}
    Write-UpdLog 'update applied'
    Remove-Item -Recurse -Force ($internal + $Bak) -ErrorAction SilentlyContinue
    Remove-Item -Force ($exePath + $Bak) -ErrorAction SilentlyContinue
    Start-Process -FilePath $exePath -WorkingDirectory $AppDir
    Write-UpdLog 'relaunched'
    Remove-Item -Force $Zip -ErrorAction SilentlyContinue
}} catch {{
    Write-UpdLog ('FAILED: ' + $_)
    try {{
        if (Test-Path $internal) {{ Remove-Item -Recurse -Force $internal }}
        if (Test-Path $exePath) {{ Remove-Item -Force $exePath }}
        if (Test-Path ($internal + $Bak)) {{ Rename-Item -Path ($internal + $Bak) -NewName '_internal' }}
        if (Test-Path ($exePath + $Bak)) {{ Rename-Item -Path ($exePath + $Bak) -NewName $Exe }}
        Remove-Item -Force $Notes -ErrorAction SilentlyContinue
        Start-Process -FilePath $exePath -WorkingDirectory $AppDir
        Write-UpdLog 'rollback relaunched'
    }} catch {{
        Write-UpdLog ('ROLLBACK FAILED: ' + $_)
    }}
}}
"""
    tmp = script + ".tmp"
    try:
        # utf-8-sig: Windows PowerShell 5.1 按 ANSI 读取无 BOM 的 .ps1，
        # 中文安装路径会变乱码 → 必须带 BOM。
        with open(tmp, "w", encoding="utf-8-sig") as f:
            f.write(body)
        os.replace(tmp, script)
        _write_pending_notes(manifest, data_dir)
    except OSError as exc:
        raise TrustError("upgrade_script", str(exc)) from exc
    return script


def launch_upgrade_helper(script_path: str) -> None:
    """Start the helper detached; the caller should quit the launcher."""
    if sys.platform != "win32":
        raise TrustError("upgrade_platform", sys.platform)
    if not os.path.isfile(script_path):
        raise TrustError("upgrade_script", script_path)
    flags = 0
    for name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS"):
        flags |= getattr(subprocess, name, 0)
    try:
        subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                "-File", script_path,
            ],
            cwd=os.path.dirname(script_path),
            creationflags=flags,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise TrustError("upgrade_launch", str(exc)) from exc


def prepare_install(
    manifest: UpdateManifest,
    *,
    progress=None,
    cancel=None,
    app_dir: str | None = None,
    pid: int | None = None,
) -> str:
    """Download + verify + write helper. Returns the helper script path."""
    asset = download_update(manifest, progress=progress, cancel=cancel)
    return write_upgrade_script(
        manifest, asset, app_dir=app_dir, pid=pid or os.getpid()
    )
