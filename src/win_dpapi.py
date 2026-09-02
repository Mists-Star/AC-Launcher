"""Windows DPAPI 加密/解密（用户级）。

用于账户 access/refresh_token 的安全持久化：PCL2 / HMCL 均用 DPAPI 存令牌，
防止其他用户或文本编辑器直接读取 accounts.json 里的明文 token。

- 同一 Windows 用户可解密（不需要密码），换用户/换机器后解密失败——调用方
  回退到「重新登录」即可。
- 兼容迁移：读旧明文数据时解密函数返回 None，调用方按明文处理并顺手重写
  为密文（见 accounts.py）。

实现：CryptProtectData / CryptUnprotectData（dpapi.dll），无额外依赖。
非 Windows 平台返回 None（调用方走明文——本地开发环境无隐私要求）。
"""
import sys

try:
    import ctypes
    from ctypes import wintypes
except ImportError:
    ctypes = None
    wintypes = None

if sys.platform == "win32" and ctypes is not None:
    _crypt32 = ctypes.windll.crypt32
else:
    _crypt32 = None


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _bytes_from_blob(blob: _DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _free_blob(blob: _DATA_BLOB) -> None:
    if blob.pbData:
        ctypes.windll.kernel32.LocalFree(blob.pbData)
        blob.pbData = None


def dpapi_encrypt(plain: str) -> str | None:
    """Encrypt str → base64. Returns None when DPAPI unavailable (non-Windows)."""
    if _crypt32 is None or not plain:
        return None
    try:
        data = plain.encode("utf-8")
        in_blob = _blob_from_bytes(data)
        out_blob = _DATA_BLOB()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(in_blob), None, None, None, None, 0,
            ctypes.byref(out_blob))
        if not ok:
            return None
        try:
            import base64
            return base64.b64encode(_bytes_from_blob(out_blob)).decode("ascii")
        finally:
            _free_blob(out_blob)
    except Exception:
        return None


def dpapi_decrypt(encoded: str) -> str | None:
    """Decrypt base64 → str. Returns None on failure (unusable/not-DPAPI/non-Windows)."""
    if _crypt32 is None or not encoded:
        return None
    try:
        import base64
        raw = base64.b64decode(encoded)
        in_blob = _blob_from_bytes(raw)
        out_blob = _DATA_BLOB()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0,
            ctypes.byref(out_blob))
        if not ok:
            return None
        try:
            return _bytes_from_blob(out_blob).decode("utf-8")
        finally:
            _free_blob(out_blob)
    except Exception:
        return None
