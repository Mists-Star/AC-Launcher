"""Sign an update manifest with the offline Ed25519 private key.

The signature covers the **raw bytes** of the manifest file, so keep the file
byte-identical after signing (no re-formatting / JSON re-dump).

Usage:
    python tools/ac_update_sign.py path/to/latest.json
    python tools/ac_update_sign.py latest.json --key ~/.ac_launcher_update_key
    python tools/ac_update_sign.py latest.json --out latest.json.sig
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import ed25519  # noqa: E402
from src.core.update_trust import UPDATE_SCHEMA  # noqa: E402

DEFAULT_KEY = os.path.join(os.path.expanduser("~"), ".ac_launcher_update_key")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Sign an AC update manifest")
    ap.add_argument("manifest", help="latest.json path")
    ap.add_argument("--key", default=DEFAULT_KEY, help="private key file")
    ap.add_argument("--out", default="", help="signature output (default: <manifest>.sig)")
    args = ap.parse_args(argv)

    key_path = os.path.expanduser(args.key)
    try:
        with open(key_path, encoding="utf-8") as f:
            key = json.load(f)
        seed = base64.b64decode(key["seed_b64"], validate=True)
        key_id = key["key_id"]
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print(f"cannot read private key {key_path}: {exc}")
        return 1

    manifest_path = os.path.abspath(args.manifest)
    try:
        with open(manifest_path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        print(f"cannot read manifest {manifest_path}: {exc}")
        return 1

    sig = ed25519.sign(seed, raw)
    out = args.out or (manifest_path + ".sig")
    payload = {
        "schema": UPDATE_SCHEMA,
        "algorithm": "ed25519",
        "key_id": key_id,
        "sig": base64.b64encode(sig).decode("ascii"),
    }
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"cannot write {out}: {exc}")
        return 1

    print(f"signed with {key_id}")
    print(f"signature: {out}")
    print("上传 release 时请把 latest.json 与其 .sig 一起传，且 manifest 字节不要再改。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
