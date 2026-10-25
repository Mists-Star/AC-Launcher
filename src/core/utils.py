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


def safe_extract_zip(zf, dest_dir: str) -> None:
    """Extract a zipfile with zip-slip protection (round-35).

    恶意 zip 可用 ``../../`` 或绝对路径把文件写到解压目录之外（zip-slip）。
    逐成员校验解析后的目标路径必须仍在 dest_dir 内，否则跳过并记日志。
    """
    import posixpath
    dest_abs = os.path.abspath(dest_dir)
    for member in zf.infolist():
        # 统一用 posix 规则解析，拒绝绝对路径与 .. 逃逸
        rel = posixpath.normpath(member.filename.replace("\\", "/"))
        if rel.startswith("..") or rel.startswith("/") or ":" in rel.split("/")[0]:
            print(f"[safe_extract] 跳过越界 zip 条目: {member.filename!r}")
            continue
        target = os.path.abspath(os.path.join(dest_abs, rel))
        if not (target == dest_abs or target.startswith(dest_abs + os.sep)):
            print(f"[safe_extract] 跳过越界 zip 条目: {member.filename!r}")
            continue
        zf.extract(member, dest_abs)
