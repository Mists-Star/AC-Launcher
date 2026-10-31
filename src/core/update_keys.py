"""Trusted Ed25519 public keys for the update manifest.

The matching private seed is NOT in this repository. It is generated once by
``python tools/ac_update_keygen.py`` into the current user's profile
(``~/.ac_launcher_update_key``) and must be kept offline / backed up.

Key rotation: publish a release signed by the *old* key that ships a new public
key here, then sign subsequent manifests with the new key id.

Current key: ``ac-e5a35f41ce3faf1f`` (generated 2026-10-31). Only the public
half lives here; losing the private file means publishing a rotation key via a
manually verified release.
"""
from __future__ import annotations

# key_id → base64 public key (32 bytes)
TRUSTED_UPDATE_KEYS: dict[str, str] = {
    "ac-e5a35f41ce3faf1f": "3UYo4iDitu04HUMTaUex0atIKDJjaAZ7+ncq+hJ/nss=",
}
