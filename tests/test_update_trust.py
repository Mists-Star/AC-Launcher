"""round-160 回归：更新签名信任链（Ed25519 / 清单校验 / 资产哈希）。

不依赖真实发布私钥：测试自己生成临时密钥，并通过 ``keys=`` 注入信任表。
覆盖 RFC 8032 向量、篡改、未知密钥、字段边界、file:// 拉取与资产哈希。
"""
import base64
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import ed25519, update_trust as ut  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-54s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def _raises(code, fn):
    try:
        fn()
        return False
    except ut.TrustError as exc:
        return exc.code == code


# ── 1. RFC 8032 test vectors ──
seed1 = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
pub1 = ed25519.public_from_seed(seed1)
check("RFC8032 公钥", pub1.hex() ==
      "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
check("RFC8032 空消息签名", ed25519.sign(seed1, b"").hex() ==
      "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
      "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
check("RFC8032 验签", ed25519.verify(pub1, b"", ed25519.sign(seed1, b"")))
check("篡改消息被拒", not ed25519.verify(pub1, b"x", ed25519.sign(seed1, b"")))

seed2 = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
pub2 = ed25519.public_from_seed(seed2)
check("RFC8032 向量 2 公钥", pub2.hex() ==
      "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
check("RFC8032 向量 2 验签", ed25519.verify(pub2, bytes([0x72]),
                                             ed25519.sign(seed2, bytes([0x72]))))
check("错误公钥被拒", not ed25519.verify(pub2, bytes([0x72]),
                                          ed25519.sign(seed1, bytes([0x72]))))
check("截断签名被拒", not ed25519.verify(pub2, bytes([0x72]),
                                          ed25519.sign(seed2, b"x")[:32]))

# ── 2. 版本比较 ──
check("1.0.0-beta < 1.0.0", ut.compare_versions("1.0.0-beta", "1.0.0") < 0)
check("1.0.1 > 1.0.0", ut.compare_versions("1.0.1", "1.0.0") > 0)
check("1.1.0 > 1.0.9", ut.compare_versions("1.1.0", "1.0.9") > 0)
check("alpha < beta", ut.compare_versions("1.0.0-alpha", "1.0.0-beta") < 0)
check("rc.2 < rc.10（数字比较）",
      ut.compare_versions("1.0.0-rc.2", "1.0.0-rc.10") < 0)
check("相同版本 = 0", ut.compare_versions("1.0.0", "1.0.0") == 0)
check("is_newer", ut.is_newer("1.1.0", "1.0.0-beta"))
check("is_newer 拒绝旧版", not ut.is_newer("0.9.0", "1.0.0"))
check("非法版本被拒", _raises("manifest_version", lambda: ut.parse_version("1.0")))

# ── 3. 临时密钥 + 合法清单 ──
test_seed, test_pub = ed25519.generate_keypair()
key_id = "test-key"
keys = {key_id: base64.b64encode(test_pub).decode("ascii")}

content = b"fake zip content"
sha = hashlib.sha256(content).hexdigest()
payload = {
    "schema": 1,
    "kind": "ac-launcher-update",
    "version": "1.1.0",
    "published_at": "2026-10-31T12:00:00+08:00",
    "notes": ["修复下载卡住", "新增诊断包导出"],
    "terms_version": 2,
    "asset": {
        "name": "AC_Launcher_1.1.0.zip",
        "url": "https://example.com/AC_Launcher_1.1.0.zip",
        "sha256": sha,
        "size": len(content),
    },
}
manifest_raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
sig_raw = json.dumps({
    "schema": 1, "algorithm": "ed25519", "key_id": key_id,
    "sig": base64.b64encode(ed25519.sign(test_seed, manifest_raw)).decode("ascii"),
}, separators=(",", ":")).encode("utf-8")

m = ut.verify_signed_manifest(manifest_raw, sig_raw, current_version="1.0.0-beta",
                               keys=keys)
check("合法清单通过", m.version == "1.1.0" and m.sha256 == sha)
check("备注解析", m.notes == ("修复下载卡住", "新增诊断包导出"))
check("key_id 回传", m.key_id == key_id)
check("terms_version 解析", m.terms_version == 2)

# ── 4. 篡改与未知密钥 ──
bad = manifest_raw.replace(b"1.1.0", b"1.2.0")
check("清单被篡改 → signature_invalid",
      _raises("signature_invalid",
              lambda: ut.verify_signed_manifest(bad, sig_raw, keys=keys)))
wrong = json.loads(sig_raw)
wrong["key_id"] = "unknown"
check("未知密钥 → signature_unknown_key",
      _raises("signature_unknown_key",
              lambda: ut.verify_signed_manifest(
                  manifest_raw, json.dumps(wrong).encode(), keys=keys)))
wrong2 = json.loads(sig_raw)
wrong2["sig"] = "not-base64"
check("签名非 base64 → signature_json",
      _raises("signature_json",
              lambda: ut.verify_signed_manifest(
                  manifest_raw, json.dumps(wrong2).encode(), keys=keys)))
wrong3 = json.loads(sig_raw)
wrong3["algorithm"] = "rsa"
check("不支持算法 → signature_json",
      _raises("signature_json",
              lambda: ut.verify_signed_manifest(
                  manifest_raw, json.dumps(wrong3).encode(), keys=keys)))
check("空信任表 → 未知密钥",
      _raises("signature_unknown_key",
              lambda: ut.verify_signed_manifest(
                  manifest_raw, sig_raw, keys={})))


def _sign(obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    doc = {"schema": 1, "algorithm": "ed25519", "key_id": key_id,
           "sig": base64.b64encode(ed25519.sign(test_seed, raw)).decode()}
    return raw, json.dumps(doc).encode()


# ── 5. 清单字段边界 ──
bad_schema = dict(payload, schema=2)
check("schema 错 → manifest_schema",
      _raises("manifest_schema", lambda: ut.verify_signed_manifest(
          *_sign(bad_schema), keys=keys)))
bad_kind = dict(payload, kind="other")
check("kind 错 → manifest_kind",
      _raises("manifest_kind", lambda: ut.verify_signed_manifest(
          *_sign(bad_kind), keys=keys)))
bad_asset = json.loads(json.dumps(payload))
bad_asset["asset"]["name"] = "../evil.exe"
check("资产名穿越/非 zip → manifest_asset",
      _raises("manifest_asset", lambda: ut.verify_signed_manifest(
          *_sign(bad_asset), keys=keys)))
bad_sha = json.loads(json.dumps(payload))
bad_sha["asset"]["sha256"] = "zz"
check("sha256 格式错 → manifest_asset",
      _raises("manifest_asset", lambda: ut.verify_signed_manifest(
          *_sign(bad_sha), keys=keys)))
bad_size = json.loads(json.dumps(payload))
bad_size["asset"]["size"] = -1
check("size 非法 → manifest_asset",
      _raises("manifest_asset", lambda: ut.verify_signed_manifest(
          *_sign(bad_size), keys=keys)))
bad_url = json.loads(json.dumps(payload))
bad_url["asset"]["url"] = "http://example.com/a.zip"
check("默认拒绝 http → manifest_https",
      _raises("manifest_https", lambda: ut.verify_signed_manifest(
          *_sign(bad_url), keys=keys)))
check("allow_insecure 放行 http",
      ut.verify_signed_manifest(*_sign(bad_url), keys=keys,
                                allow_insecure=True).asset_url.startswith("http://"))
bad_notes = dict(payload, notes=["x"] * (ut.MAX_NOTES + 1))
check("备注过多 → manifest_notes",
      _raises("manifest_notes", lambda: ut.verify_signed_manifest(
          *_sign(bad_notes), keys=keys)))
bad_min = dict(payload, min_launcher_version="2.0.0")
check("要求更高启动器 → manifest_requires_newer",
      _raises("manifest_requires_newer", lambda: ut.verify_signed_manifest(
          *_sign(bad_min), keys=keys, current_version="1.0.0")))
dupe = b'{"schema":1,"schema":1,"kind":"ac-launcher-update"}'
dupe_sig = json.dumps({
    "schema": 1, "key_id": key_id,
    "sig": base64.b64encode(ed25519.sign(test_seed, dupe)).decode(),
}).encode()
check("重复键被拒 → manifest_json",
      _raises("manifest_json", lambda: ut.verify_signed_manifest(
          dupe, dupe_sig, keys=keys)))

# ── 6. file:// 拉取 + check_for_update ──
with tempfile.TemporaryDirectory(prefix="ac_upd_") as td:
    mf = os.path.join(td, "latest.json")
    sf = mf + ".sig"
    with open(mf, "wb") as f:
        f.write(manifest_raw)
    with open(sf, "wb") as f:
        f.write(sig_raw)
    url = "file:///" + mf.replace("\\", "/").lstrip("/")
    check("签名 URL 推导",
          ut.manifest_signature_url(url) ==
          "file:///" + sf.replace("\\", "/").lstrip("/"))
    res = ut.check_for_update("1.0.0-beta", url, allow_insecure=True, keys=keys)
    check("check_for_update 发现新版", res.status == "update" and res.manifest.version == "1.1.0")
    res2 = ut.check_for_update("1.1.0", url, allow_insecure=True, keys=keys)
    check("同版本 → current", res2.status == "current")

    # 大文件读取上限
    big = os.path.join(td, "big.bin")
    with open(big, "wb") as f:
        f.write(b"x" * 100)
    check("fetch 上限 → too_large",
          _raises("too_large", lambda: ut.fetch_bytes(
              "file:///" + big.replace("\\", "/").lstrip("/"), max_bytes=10,
              allow_insecure=True)))

# ── 7. 资产哈希 ──
with tempfile.TemporaryDirectory(prefix="ac_asset_") as td:
    good = os.path.join(td, "good.zip")
    with open(good, "wb") as f:
        f.write(content)
    ut.verify_asset_file(good, m)
    check("资产哈希正确通过", True)
    bad = os.path.join(td, "bad.zip")
    with open(bad, "wb") as f:
        f.write(b"tampered content")
    check("资产哈希不匹配 → asset_hash",
          _raises("asset_hash", lambda: ut.verify_asset_file(bad, m)))
    short = os.path.join(td, "short.zip")
    with open(short, "wb") as f:
        f.write(b"x")
    check("资产大小不匹配 → asset_size",
          _raises("asset_size", lambda: ut.verify_asset_file(short, m)))
    check("资产不存在 → asset_missing",
          _raises("asset_missing", lambda: ut.verify_asset_file(
              os.path.join(td, "none.zip"), m)))

print()
if fails:
    print("FAILED: %d 项 → %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL CHECKS PASSED")
