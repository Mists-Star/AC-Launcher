"""Support bundle — one-click, masked diagnostic package for bug reports.

Contains just enough context for the author to reproduce a problem:

  * ``summary.txt``      — version / platform / diagnostic verdicts;
  * ``config.json``      — launcher config with secrets redacted;
  * ``diagnostics.txt``  — the same self-check results, one line each;
  * ``logs/…``           — tail of every log under the data dir.

Everything is masked **before** it is written (access tokens and the Windows
user name), so the archive can be attached to a public issue without leaking
credentials or PII. Pure logic, no Qt — safe to run on a worker thread and to
unit-test head-less.
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time
import zipfile

from .. import brand
from ..log_mask import mask_launch_text
from ..paths import get_config_path, get_data_dir

__all__ = [
    "SENSITIVE_CONFIG_KEYS",
    "redact_config",
    "default_bundle_name",
    "build_support_bundle",
]

# Keys whose values must never leave the machine. Mirrors
# ``settings_dialog._SENSITIVE_CFG_KEYS`` at the export boundary (kept local so
# this module stays Qt-free).
SENSITIVE_CONFIG_KEYS = frozenset({
    "dev_mode_key",          # developer unlock key
    "curseforge_api_key",    # user's own third-party API key
})

_REDACTED = "<redacted>"
_MAX_LOG_BYTES = 256 * 1024      # per file
_MAX_LOG_FILES = 12


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _mask(text: str) -> str:
    """Mask tokens / user name in free text."""
    return mask_launch_text(text or "")


def redact_config(cfg: dict) -> dict:
    """Return a copy of ``cfg`` safe to attach to a report."""
    out: dict = {}
    for key, value in (cfg or {}).items():
        if key in SENSITIVE_CONFIG_KEYS:
            out[key] = _REDACTED
        elif isinstance(value, str):
            out[key] = _mask(value)
        elif isinstance(value, dict):
            out[key] = redact_config(value)
        elif isinstance(value, list):
            out[key] = [_mask(v) if isinstance(v, str) else v for v in value]
        else:
            out[key] = value
    return out


def _read_config() -> dict:
    try:
        with open(get_config_path("launcher_config.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _tail_text(path: str, max_bytes: int = _MAX_LOG_BYTES) -> str:
    """Read the last ``max_bytes`` of a file and mask it."""
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size > max_bytes:
            f.seek(size - max_bytes)
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    if size > max_bytes:
        text = "[…truncated, showing last %d KB…]\n" % (max_bytes // 1024) + text
    return _mask(text)


def _collect_logs(data_dir: str) -> list[tuple[str, str]]:
    """Return ``[(archive_name, masked_text)]`` for logs under ``data_dir``.

    Two locations are covered: ``<data_dir>/logs/*.log`` (download diagnostic
    log) and ``<data_dir>/*.log`` (game logs written as ``<instance>.log``).
    Newest files win when more than ``_MAX_LOG_FILES`` exist.
    """
    if not os.path.isdir(data_dir):
        return []
    found: list[str] = []
    # Only the data root and its immediate ``logs`` folder — never recurse into
    # instance/game directories (could be huge and full of irrelevant logs).
    for folder in (data_dir, os.path.join(data_dir, "logs")):
        if not os.path.isdir(folder):
            continue
        try:
            entries = os.listdir(folder)
        except OSError:
            continue
        for name in entries:
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name.lower().endswith(".log"):
                found.append(path)

    def _mtime(p: str) -> float:
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0

    found.sort(key=_mtime, reverse=True)
    out: list[tuple[str, str]] = []
    used: dict[str, int] = {}
    for path in found[:_MAX_LOG_FILES]:
        rel = os.path.relpath(path, data_dir).replace(os.sep, "/")
        arc = "logs/" + rel
        if arc in used:
            used[arc] += 1
            stem, ext = os.path.splitext(arc)
            arc = f"{stem}-{used[arc]}{ext}"
        else:
            used[arc] = 0
        try:
            out.append((arc, _tail_text(path)))
        except OSError:
            continue
    return out


def _result_fields(result) -> tuple[str, str, str]:
    if isinstance(result, dict):
        return (str(result.get("id", "?")), str(result.get("status", "?")),
                str(result.get("detail", "")))
    return (str(getattr(result, "id", "?")), str(getattr(result, "status", "?")),
            str(getattr(result, "detail", "")))


def _diagnostics_text(results: list) -> str:
    if not results:
        return "(no diagnostics were run)\n"
    lines = []
    for r in results:
        rid, status, detail = _result_fields(r)
        lines.append(f"[{status}] {rid}: {_mask(detail)}")
    return "\n".join(lines) + "\n"


def _summary_text(results: list, logs: list[tuple[str, str]]) -> str:
    ok = warn = err = skip = 0
    for r in results or []:
        status = _result_fields(r)[1].lower()
        if status == "ok":
            ok += 1
        elif status == "warn":
            warn += 1
        elif status == "error":
            err += 1
        else:
            skip += 1
    mask = platform.platform()
    lines = [
        "AC Launcher support bundle",
        "",
        f"Generated : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Version   : {brand.APP_VERSION}",
        f"Platform  : {mask}",
        f"Python    : {platform.python_version()}",
        f"Packaged  : {'yes' if getattr(sys, 'frozen', False) else 'no (dev run)'}",
        f"Data dir  : {_mask(get_data_dir())}",
        "",
        f"Diagnostics: {ok} ok / {warn} warn / {err} error / {skip} skip"
        f" (total {len(results or [])})",
        f"Logs       : {len(logs)} file(s), see logs/",
        "",
        "Secrets (API keys / dev key) and the Windows user name are masked.",
        "See config.json and diagnostics.txt for details.",
        "",
    ]
    return "\n".join(lines)


def default_bundle_name(now: time.struct_time | None = None) -> str:
    """``AC_support_YYYYMMDD_HHMMSS.zip``."""
    stamp = time.strftime("%Y%m%d_%H%M%S", now or time.localtime())
    return f"AC_support_{stamp}.zip"


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def build_support_bundle(
    dest: str,
    results: list | None = None,
    *,
    config: dict | None = None,
    data_dir: str | None = None,
) -> str:
    """Write the masked bundle to ``dest`` and return the final path.

    ``config`` / ``data_dir`` default to the real ones and exist mainly so the
    unit tests can point at a temporary tree. The archive is written to a
    ``.tmp`` sibling first and then moved into place (atomic, never a half zip).
    """
    data_dir = data_dir or get_data_dir()
    if config is None:
        config = _read_config()
    logs = _collect_logs(data_dir)

    parent = os.path.dirname(os.path.abspath(dest))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = dest + ".tmp"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("summary.txt", _summary_text(results or [], logs))
            zf.writestr(
                "config.json",
                json.dumps(redact_config(config), ensure_ascii=False, indent=2),
            )
            zf.writestr("diagnostics.txt", _diagnostics_text(results or []))
            for arc, text in logs:
                zf.writestr(arc, text)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return dest
