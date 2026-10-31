"""Ed25519 (RFC 8032) — pure-Python sign/verify.

Why no ``cryptography``: the frozen launcher runs on clean Windows machines
with only PySide6-Essentials installed; adding a compiled crypto dependency
would grow the package and add a native build. Ed25519 is small enough to
implement safely here (RFC 8032 test vectors are covered by
``tests/test_update_trust.py``).

This module is used by:
  * ``tools/ac_update_keygen.py`` / ``tools/ac_update_sign.py`` (offline);
  * ``src/core/update_trust.py`` (manifest signature verification).
"""
from __future__ import annotations

import hashlib
import secrets

__all__ = ["generate_keypair", "public_from_seed", "sign", "verify"]

# Curve constants (RFC 8032 §5.1).
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = 4 * _inv(5) % _P
_BX = _xrecover(_BY)
_B = (_BX, _BY, 1, _BX * _BY % _P)


def _edwards(p1, p2):
    x1, y1, z1, t1 = p1
    x2, y2, z2, t2 = p2
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = t1 * 2 * _D * t2 % _P
    d = z1 * 2 * z2 % _P
    e = b - a
    f = d - c
    g = d + c
    h = b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _scalarmult(point, scalar: int):
    # Neutral element in extended coordinates is (0, 1, 1, 0) — z MUST be 1,
    # not 0, otherwise encoding divides by zero and yields (0, 0).
    if scalar == 0:
        return (0, 1, 1, 0)
    q = _scalarmult(point, scalar // 2)
    q = _edwards(q, q)
    if scalar & 1:
        q = _edwards(q, point)
    return q


def _encode(point) -> bytes:
    x, y, z, _t = point
    zi = _inv(z)
    x = x * zi % _P
    y = y * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(raw: bytes):
    if len(raw) != 32:
        raise ValueError("ed25519: public key must be 32 bytes")
    y = int.from_bytes(raw, "little") & ((1 << 255) - 1)
    x = _xrecover(y)
    if (x & 1) != (raw[31] >> 7):
        x = _P - x
    point = (x, y, 1, x * y % _P)
    # Verify the point is on the curve: -x² + y² = 1 + d·x²·y².
    if (-x * x + y * y - 1 - _D * x * x * y * y) % _P != 0:
        raise ValueError("ed25519: point is not on the curve")
    return point


def _clamp(seed: bytes) -> tuple[int, bytes]:
    h = _sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_from_seed(seed: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte private seed."""
    if len(seed) != 32:
        raise ValueError("ed25519: seed must be 32 bytes")
    a, _prefix = _clamp(seed)
    return _encode(_scalarmult(_B, a))


def generate_keypair() -> tuple[bytes, bytes]:
    """Return ``(seed, public_key)``; both 32-byte values."""
    seed = secrets.token_bytes(32)
    return seed, public_from_seed(seed)


def sign(seed: bytes, message: bytes) -> bytes:
    """Produce the 64-byte detached signature."""
    if len(seed) != 32:
        raise ValueError("ed25519: seed must be 32 bytes")
    a, prefix = _clamp(seed)
    pub = _encode(_scalarmult(_B, a))
    r = int.from_bytes(_sha512(prefix + message), "little") % _L
    r_encoded = _encode(_scalarmult(_B, r))
    h = int.from_bytes(_sha512(r_encoded + pub + message), "little") % _L
    s = (r + h * a) % _L
    return r_encoded + s.to_bytes(32, "little")


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Return True only for a valid signature over ``message``."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        r_point = _decode(signature[:32])
        a_point = _decode(public_key)
    except ValueError:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(
        _sha512(signature[:32] + public_key + message), "little"
    ) % _L
    # [S]B == R + [h]A
    left = _scalarmult(_B, s)
    right = _edwards(r_point, _scalarmult(a_point, h))
    return _encode(left) == _encode(right)
