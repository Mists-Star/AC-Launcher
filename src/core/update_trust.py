"""Update trust chain — signed manifest parsing and verification.

Trust model (no TLS-only "trust me"):

    release private key (offline)
        └─ signs raw bytes of latest.json
              └─ latest.json lists version + asset sha256/size/url
                    └─ updater downloads the zip and re-hashes it

Verification rules:
  * the signature is Ed25519 over the **exact manifest bytes** (no JSON
    canonicalisation ambiguity);
  * only key ids in :data:`TRUSTED_UPDATE_KEYS` are accepted (unknown key =
    hard failure, even if the signature maths is valid);
  * manifest must be ``schema=1`` / ``kind=ac-launcher-update``;
  * asset must be a ``.zip`` with a lowercase 64-hex sha256 and a bounded size;
  * URLs are ``https`` by default; ``http`` (localhost) and ``file`` are only
    allowed with ``allow_insecure=True`` (tests / local rehearsal).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.request import url2pathname

from ..brand import APP_VERSION
from . import ed25519
from .update_keys import TRUSTED_UPDATE_KEYS

__all__ = [
    "UPDATE_SCHEMA",
    "UPDATE_KIND",
    "GITHUB_MANIFEST_URL",
    "TrustError",
    "UpdateManifest",
    "UpdateCheck",
    "parse_version",
    "compare_versions",
    "is_newer",
    "verify_signed_manifest",
    "check_for_update",
    "fetch_bytes",
    "file_sha256",
    "verify_asset_file",
]

UPDATE_SCHEMA = 1
UPDATE_KIND = "ac-launcher-update"

# Default release channel: a signed latest.json in the repo's latest release.
# Settings may override this with a custom URL (both are supported).
GITHUB_MANIFEST_URL = (
    "https://github.com/Mists-Star/AC-Launcher/releases/latest/download/latest.json"
)

MAX_MANIFEST_BYTES = 256 * 1024
MAX_SIGNATURE_BYTES = 8 * 1024
MAX_NOTES = 40
MAX_NOTE_CHARS = 300
MAX_ASSET_BYTES = 2_000_000_000

_VERSION_RE = re.compile(r"^(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-([0-9A-Za-z.-]{1,32}))?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TrustError(Exception):
    """A verification failure with a stable ``code`` for UI translation."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    notes: tuple[str, ...]
    asset_name: str
    asset_url: str
    sha256: str
    size: int
    key_id: str
    published_at: str = ""
    min_launcher_version: str = ""
    terms_version: int = 0


@dataclass(frozen=True)
class UpdateCheck:
    status: str            # "update" / "current"
    manifest: UpdateManifest | None = None


# --------------------------------------------------------------------------- #
# version comparison (semver-lite)
# --------------------------------------------------------------------------- #
def parse_version(text: str) -> tuple[int, int, int, str | None]:
    m = _VERSION_RE.match((text or "").strip())
    if not m:
        raise TrustError("manifest_version", text)
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)


def _cmp_pre(a: str | None, b: str | None) -> int:
    if a is None and b is None:
        return 0
    if a is None:
        return 1          # 1.0.0 > 1.0.0-beta
    if b is None:
        return -1
    pa, pb = a.split("."), b.split(".")
    for x, y in zip(pa, pb):
        xn, yn = x.isdigit(), y.isdigit()
        if xn and yn:
            xi, yi = int(x), int(y)
            if xi != yi:
                return 1 if xi > yi else -1
        elif xn:
            return -1     # numeric identifiers have lower precedence
        elif yn:
            return 1
        elif x != y:
            return 1 if x > y else -1
    if len(pa) != len(pb):
        return 1 if len(pa) > len(pb) else -1
    return 0


def compare_versions(a: str, b: str) -> int:
    """Return -1 / 0 / 1 for ``a`` vs ``b`` (raises on malformed input)."""
    va, vb = parse_version(a), parse_version(b)
    if va[:3] != vb[:3]:
        return 1 if va[:3] > vb[:3] else -1
    return _cmp_pre(va[3], vb[3])


def is_newer(candidate: str, current: str) -> bool:
    return compare_versions(candidate, current) > 0


# --------------------------------------------------------------------------- #
# strict JSON / fetch
# --------------------------------------------------------------------------- #
def _strict_json(raw: bytes, code: str) -> dict:
    def _pairs(pairs):
        obj: dict = {}
        for key, value in pairs:
            if key in obj:
                raise TrustError(code, f"duplicate key: {key}")
            obj[key] = value
        return obj

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrustError(code, f"not UTF-8: {exc}") from exc
    try:
        data = json.loads(text, object_pairs_hook=_pairs)
    except TrustError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise TrustError(code, str(exc)) from exc
    if not isinstance(data, dict):
        raise TrustError(code, "root must be an object")
    return data


def _check_url(url: str, allow_insecure: bool) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise TrustError("manifest_url", "missing or too long")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme == "file":
        if not allow_insecure:
            raise TrustError("manifest_https", "file:// is only allowed in tests")
        return url
    if scheme == "https":
        return url
    if scheme == "http" and allow_insecure:
        return url
    raise TrustError("manifest_https", f"unsupported scheme: {scheme or '(none)'}")


def fetch_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 10.0,
    allow_insecure: bool = False,
) -> bytes:
    """Fetch ``url`` with a hard size cap (HTTP(S) or file://)."""
    url = _check_url(url, allow_insecure)
    if urlsplit(url).scheme.lower() == "file":
        path = url2pathname(urlsplit(url).path)
        try:
            with open(path, "rb") as f:
                data = f.read(max_bytes + 1)
        except OSError as exc:
            raise TrustError("network", str(exc)) from exc
    else:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"AC-Launcher/{APP_VERSION}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                chunks = []
                total = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise TrustError("too_large", f">{max_bytes} bytes")
                    chunks.append(chunk)
                data = b"".join(chunks)
        except TrustError:
            raise
        except Exception as exc:  # urllib raises many types
            raise TrustError("network", str(exc)) from exc
    if len(data) > max_bytes:
        raise TrustError("too_large", f">{max_bytes} bytes")
    return data


# --------------------------------------------------------------------------- #
# signature + manifest validation
# --------------------------------------------------------------------------- #
def _parse_signature(raw: bytes) -> tuple[str, bytes]:
    data = _strict_json(raw, "signature_json")
    if data.get("schema") != UPDATE_SCHEMA:
        raise TrustError("signature_json", "unsupported signature schema")
    if data.get("algorithm", "ed25519") != "ed25519":
        raise TrustError("signature_json", "unsupported algorithm")
    key_id = data.get("key_id")
    if not isinstance(key_id, str) or not key_id:
        raise TrustError("signature_json", "missing key_id")
    encoded = data.get("sig")
    if not isinstance(encoded, str):
        raise TrustError("signature_json", "missing sig")
    try:
        sig = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TrustError("signature_json", "sig is not base64") from exc
    if len(sig) != 64:
        raise TrustError("signature_json", "signature must be 64 bytes")
    return key_id, sig


def _validate_manifest(
    data: dict,
    *,
    current_version: str,
    key_id: str,
    allow_insecure: bool,
) -> UpdateManifest:
    if data.get("schema") != UPDATE_SCHEMA:
        raise TrustError("manifest_schema", str(data.get("schema")))
    if data.get("kind") != UPDATE_KIND:
        raise TrustError("manifest_kind", str(data.get("kind")))

    version = data.get("version")
    if not isinstance(version, str):
        raise TrustError("manifest_version", "missing")
    parse_version(version)

    asset = data.get("asset")
    if not isinstance(asset, dict):
        raise TrustError("manifest_asset", "missing asset object")
    name = asset.get("name")
    if not isinstance(name, str) or len(name) > 160:
        raise TrustError("manifest_asset", "bad asset name")
    if not name.lower().endswith(".zip") or os.sep in name or "/" in name:
        raise TrustError("manifest_asset", "asset must be a plain .zip filename")
    url = _check_url(asset.get("url"), allow_insecure)
    sha = asset.get("sha256")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha.strip().lower()):
        raise TrustError("manifest_asset", "sha256 must be 64 hex chars")
    sha = sha.strip().lower()
    size = asset.get("size")
    if not isinstance(size, int) or isinstance(size, bool) \
            or size <= 0 or size > MAX_ASSET_BYTES:
        raise TrustError("manifest_asset", "size out of range")

    notes_raw = data.get("notes", [])
    if not isinstance(notes_raw, list) or len(notes_raw) > MAX_NOTES:
        raise TrustError("manifest_notes", "notes must be a bounded list")
    notes: list[str] = []
    for item in notes_raw:
        if not isinstance(item, str):
            raise TrustError("manifest_notes", "note entries must be strings")
        text = item.strip()
        if len(text) > MAX_NOTE_CHARS:
            raise TrustError("manifest_notes", "note too long")
        if text:
            notes.append(text)

    published = data.get("published_at", "")
    if not isinstance(published, str):
        raise TrustError("manifest_field", "published_at must be a string")

    min_ver = data.get("min_launcher_version", "")
    if min_ver:
        if not isinstance(min_ver, str):
            raise TrustError("manifest_field", "min_launcher_version")
        parse_version(min_ver)
        if compare_versions(current_version, min_ver) < 0:
            raise TrustError("manifest_requires_newer", min_ver)

    terms = data.get("terms_version", 0)
    if not isinstance(terms, int) or isinstance(terms, bool) or terms < 0:
        raise TrustError("manifest_field", "terms_version")

    return UpdateManifest(
        version=version.strip(),
        notes=tuple(notes),
        asset_name=name,
        asset_url=url,
        sha256=sha,
        size=size,
        key_id=key_id,
        published_at=published.strip(),
        min_launcher_version=min_ver.strip(),
        terms_version=terms,
    )


def verify_signed_manifest(
    manifest_raw: bytes,
    signature_raw: bytes,
    *,
    current_version: str = APP_VERSION,
    keys: dict[str, str] | None = None,
    allow_insecure: bool = False,
) -> UpdateManifest:
    """Verify signature then validate fields. Raises :class:`TrustError`."""
    if len(manifest_raw) > MAX_MANIFEST_BYTES:
        raise TrustError("manifest_too_large", str(len(manifest_raw)))
    if len(signature_raw) > MAX_SIGNATURE_BYTES:
        raise TrustError("signature_too_large", str(len(signature_raw)))

    key_id, sig = _parse_signature(signature_raw)
    keyring = TRUSTED_UPDATE_KEYS if keys is None else keys
    public_b64 = keyring.get(key_id)
    if not public_b64:
        raise TrustError("signature_unknown_key", key_id)
    try:
        public = base64.b64decode(public_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TrustError("signature_unknown_key", "bad stored public key") from exc
    if not ed25519.verify(public, manifest_raw, sig):
        raise TrustError("signature_invalid", key_id)

    data = _strict_json(manifest_raw, "manifest_json")
    return _validate_manifest(
        data,
        current_version=current_version,
        key_id=key_id,
        allow_insecure=allow_insecure,
    )


# --------------------------------------------------------------------------- #
# network entry point (used by the UI)
# --------------------------------------------------------------------------- #
def manifest_signature_url(manifest_url: str) -> str:
    """``latest.json`` → ``latest.json.sig`` (keeps query/fragment intact)."""
    parts = urlsplit(manifest_url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}.sig" + (
        f"?{parts.query}" if parts.query else ""
    ) + (f"#{parts.fragment}" if parts.fragment else "") if parts.scheme \
        else manifest_url + ".sig"


def check_for_update(
    current_version: str = APP_VERSION,
    manifest_url: str | None = None,
    *,
    timeout: float = 10.0,
    allow_insecure: bool = False,
    keys: dict[str, str] | None = None,
) -> UpdateCheck:
    """Fetch + verify the signed manifest; returns update/current."""
    url = (manifest_url or "").strip() or GITHUB_MANIFEST_URL
    raw = fetch_bytes(
        url, max_bytes=MAX_MANIFEST_BYTES, timeout=timeout,
        allow_insecure=allow_insecure,
    )
    sig = fetch_bytes(
        manifest_signature_url(url), max_bytes=MAX_SIGNATURE_BYTES,
        timeout=timeout, allow_insecure=allow_insecure,
    )
    manifest = verify_signed_manifest(
        raw, sig, current_version=current_version, keys=keys,
        allow_insecure=allow_insecure,
    )
    if is_newer(manifest.version, current_version):
        return UpdateCheck("update", manifest)
    return UpdateCheck("current", manifest)


# --------------------------------------------------------------------------- #
# artifact verification (download pipeline uses these)
# --------------------------------------------------------------------------- #
def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_asset_file(path: str, manifest: UpdateManifest) -> None:
    """Raise unless the downloaded file matches size and sha256 exactly."""
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise TrustError("asset_missing", str(exc)) from exc
    if size != manifest.size:
        raise TrustError("asset_size", f"{size} != {manifest.size}")
    if file_sha256(path) != manifest.sha256:
        raise TrustError("asset_hash", "sha256 mismatch")
