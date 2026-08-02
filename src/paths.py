"""Path helpers — packaging-safe resource & config resolution.

Mirrors the PyInstaller packaging guide but tuned for a Qt6 / PySide6 launcher:

  - get_resource_path(): read-only bundled assets (images, default configs).
    After PyInstaller bundles, these live in the temp _MEIPASS dir.
  - get_config_path(): read-write config files. MUST NOT live in _MEIPASS
    (it is read-only and deleted on exit). We put them beside the exe so the
    launcher stays a green/portable app.
  - get_data_dir(): runtime data (accounts cache, logs, downloaded assets).
"""
import sys
import os


def get_resource_path(relative_path: str) -> str:
    """Absolute path to a bundled read-only resource (assets/, default configs…).

    Supports three packaging layouts:
      - dev:              cwd-relative (project root)
      - PyInstaller:      sys._MEIPASS temp dir
      - Nuitka standalone: exe dir, or exe_dir/_internal for newer Nuitka
        versions that group dependencies there.
    """
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, relative_path)
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        internal = os.path.join(base, "_internal")
        if os.path.isdir(internal):
            return os.path.join(internal, relative_path)
        return os.path.join(base, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def _base_dir() -> str:
    """Config/data base: exe dir when frozen, project dir otherwise."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")


def get_config_path(filename: str) -> str:
    """Absolute path to a read-write config file (lives beside the exe)."""
    return os.path.join(_base_dir(), filename)


def get_data_dir() -> str:
    """Directory for runtime data; created on first use.

    Honour ``AC_DEV_TEMP=1`` for dev / QA runs: write to a fresh tempdir every
    launch so test imports / settings are never persisted into the project (or
    exe-side) data folder and accidentally bundled into a release.
    """
    if os.environ.get("AC_DEV_TEMP") == "1":
        import tempfile
        return tempfile.mkdtemp(prefix="ac_dev_")
    d = os.path.join(_base_dir(), "data")
    os.makedirs(d, exist_ok=True)
    return d
