"""Safe JSON parsing + small filesystem helpers for the launcher core.

The JSON helpers exist because we will parse untrusted data (Microsoft tokens,
version manifests, mod metadata). A single malformed byte must never crash the
launcher — we either fall back to a default or raise a typed JsonError.
"""
from __future__ import annotations

import json
import os


class JsonError(Exception):
    """Raised when safe_json_loads is asked to fail on bad input."""


def safe_json_loads(text: str | None, *, default=None, max_chars: int = 10_000_000):
    """Parse JSON, never raising on malformed input unless no default given.

    - None / empty  -> default (or JsonError)
    - oversized      -> default (or JsonError)  (guards against pathological input)
    - malformed      -> default (or JsonError)
    - never uses eval; only json.loads
    """
    if text is None or text.strip() == "":
        if default is None:
            raise JsonError("empty input")
        return default
    if len(text) > max_chars:
        if default is None:
            raise JsonError("input too large")
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError) as e:  # noqa: BLE001
        if default is None:
            raise JsonError(str(e)) from e
        return default


def read_json(path: str, default=None):
    """Read a JSON file safely; returns default if missing/corrupt."""
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return safe_json_loads(f.read(), default=default)
    except OSError:
        return default


def write_json(path: str, data) -> None:
    """Write data as pretty JSON, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
