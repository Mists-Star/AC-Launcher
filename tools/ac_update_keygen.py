"""Generate the AC updater Ed25519 key pair (one-time, offline).

Writes the private seed to ``~/.ac_launcher_update_key`` (outside this repo) and
prints the public key / key id to paste into ``src/core/update_keys.py``.
The private file must never be committed, copied into the build, or logged.

Usage:
    python tools/ac_update_keygen.py            # refuse if key already exists
    python tools/ac_update_keygen.py --force    # rotate (invalidates old sigs)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import ed25519  # noqa: E402

KEY_PATH = os.path.join(os.path.expanduser("~"), ".ac_launcher_update_key")


def key_id_for(public_b64: str) -> str:
    return "ac-" + hashlib.sha256(public_b64.encode("ascii")).hexdigest()[:16]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Generate AC updater key pair")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing private key (rotation)")
    ap.add_argument("--path", default=KEY_PATH, help="private key file path")
    args = ap.parse_args(argv)

    path = os.path.expanduser(args.path)
    if os.path.exists(path) and not args.force:
        print(f"key already exists: {path}\n"
              "refusing to overwrite (use --force only for rotation)")
        return 1

    seed, public = ed25519.generate_keypair()
    seed_b64 = base64.b64encode(seed).decode("ascii")
    pub_b64 = base64.b64encode(public).decode("ascii")
    key_id = key_id_for(pub_b64)
    payload = {
        "format": "ac-update-key-v1",
        "key_id": key_id,
        "seed_b64": seed_b64,
        "public_b64": pub_b64,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        print(f"failed to write {path}: {exc}")
        return 1

    print(f"private key written: {path}")
    print("（不要把该文件提交进仓库，也不要贴到日志/聊天）")
    print()
    print("把下面两行合并进 src/core/update_keys.py：")
    print(f'    "{key_id}": "{pub_b64}",')
    print()
    print(f"key_id: {key_id}")
    print(f"public : {pub_b64}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
