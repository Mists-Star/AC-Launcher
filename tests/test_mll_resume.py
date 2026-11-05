"""round-176 回归测试：mll 下载路径的断点续传 / 低速判据 / 429 分支。

被测：src/core/mirror.py 的 `_resume_mll_download`、`_wrap_download_file`、
`_try_source` 的 429 处理。全部用假响应，不联网。
"""
import hashlib
import os
import sys
import tempfile

os.environ["AC_DEV_TEMP"] = "1"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import requests  # noqa: E402
from src.core import mirror  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


print("== round-176 mll 断点续传 / 低速 / 429 ==")

TMP = tempfile.mkdtemp(prefix="_resume176_")


class _Resp:
    def __init__(self, status=200, headers=None, chunks=()):
        self.status_code = status
        self.headers = dict(headers or {})
        self._chunks = list(chunks)
        self.closed = False

    def iter_content(self, n):
        for c in self._chunks:
            yield c

    def close(self):
        self.closed = True


class _Sess:
    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)

    def get(self, url, stream=True, headers=None):
        self.calls.append(dict(headers or {}))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


DATA = bytes(range(256)) * 4          # 1024 B
SHA = hashlib.sha1(DATA).hexdigest()


def _case(name):
    d = os.path.join(TMP, name)
    os.makedirs(d, exist_ok=True)
    return d


def _dl(path, sess, sha1=SHA, overwrite=False, callback=None):
    return mirror._resume_mll_download(
        "https://launchermeta.mojang.com/x", path, callback=callback or {},
        sha1=sha1, session=sess, minecraft_directory=None, overwrite=overwrite)


# ── 1. 有 .part：发 Range、206 追加、sha1 通过、原子替换 ────────────────
d = _case("resume")
p = os.path.join(d, "a.jar")
part = p + ".part"
with open(part, "wb") as f:
    f.write(DATA[:300])
sess = _Sess([_Resp(206, {"Content-Range": "bytes 300-1023/1024",
                          "Content-Length": "724"},
                    [DATA[300:]])])
ok = _dl(p, sess)
check("续传返回 True", ok is True)
check("发出了 Range 头", sess.calls[0].get("Range") == "bytes=300-",
      sess.calls[0].get("Range"))
check("文件内容完整", open(p, "rb").read() == DATA)
check("临时文件已清理", not os.path.exists(part))

# ── 2. 服务器忽略 Range（200）→ 从头写，内容正确 ──────────────────────
d = _case("ignore_range")
p = os.path.join(d, "b.jar")
part = p + ".part"
with open(part, "wb") as f:
    f.write(b"garbage-prefix")
sess = _Sess([_Resp(200, {"Content-Length": "1024"}, [DATA[:512], DATA[512:]])])
check("200 时返回 True", _dl(p, sess) is True)
check("200 时文件内容正确", open(p, "rb").read() == DATA)

# ── 3. 目标已存在且 sha1 一致 → False，并清理残留 .part ────────────────
d = _case("already")
p = os.path.join(d, "c.jar")
with open(p, "wb") as f:
    f.write(DATA)
part = p + ".part"
with open(part, "wb") as f:
    f.write(b"stale")
sess = _Sess([])
check("已存在且校验通过 → False", _dl(p, sess) is False)
check("未发起请求", sess.calls == [])
check("残留 .part 被清理", not os.path.exists(part))

# ── 4. sha1 不符 → InvalidChecksum，且不留坏 .part ──────────────────────
d = _case("badsha")
p = os.path.join(d, "d.jar")
sess = _Sess([_Resp(200, {"Content-Length": "1024"}, [b"X" * 1024])])
from minecraft_launcher_lib.exceptions import InvalidChecksum  # noqa: E402
try:
    _dl(p, sess)
    check("应抛 InvalidChecksum", False)
except InvalidChecksum:
    check("应抛 InvalidChecksum", True)
check("校验失败后目标文件不存在", not os.path.exists(p))
check("校验失败后 .part 已删除", not os.path.exists(p + ".part"))

# ── 5. 低速判据：两轮都慢 → 退回原实现（_ResumeFallback） ─────────────
d = _case("slow")
p = os.path.join(d, "e.bin")
_old = (mirror._SLOW_WINDOW, mirror._SLOW_BPS, mirror._SLOW_MIN_BYTES,
        mirror._RESUME_MIN_BYTES)
mirror._SLOW_WINDOW = 0.0
mirror._SLOW_BPS = 10 ** 9
mirror._SLOW_MIN_BYTES = 1
mirror._RESUME_MIN_BYTES = 1
try:
    sess = _Sess([
        _Resp(200, {"Content-Length": "1024"}, [b"Y" * 1024]),
        _Resp(200, {"Content-Length": "1024"}, [b"Y" * 1024]),
    ])
    try:
        _dl(p, sess)
        check("低速两轮后应退回原实现", False)
    except mirror._ResumeFallback:
        check("低速两轮后应退回原实现", True)
    check("低速时发起了 2 次请求", len(sess.calls) == 2)
finally:
    (mirror._SLOW_WINDOW, mirror._SLOW_BPS, mirror._SLOW_MIN_BYTES,
     mirror._RESUME_MIN_BYTES) = _old

# ── 6. 429：按 Retry-After 等一次再试，成功且不计入源健康失败 ─────────
mirror.reset_source_health()
_orig_send = requests.Session.send
_orig_sleep = mirror.time.sleep
calls = {"n": 0}


def _fake_send(self, request, **kwargs):
    calls["n"] += 1
    if calls["n"] == 1:
        return _Resp(429, {"Retry-After": "1"})
    return _Resp(200, {"Content-Length": "2"}, [b"ok"])


slept = []
mirror.time.sleep = lambda s: slept.append(s)
requests.Session.send = _fake_send
try:
    s = mirror.MirrorSession()
    req = requests.Request("GET", "https://launchermeta.mojang.com/x").prepare()
    # mirror 关闭 → 只有官方候选；官方 retries=1，但 429 只等一次
    resp = s.send(req, timeout=(5, 10))
    check("429 后最终拿到 200", getattr(resp, "status_code", None) == 200)
    check("只等了一次", slept == [1.0], slept)
    check("共发两次请求", calls["n"] == 2, calls["n"])
    snap = mirror.source_health().snapshot()
    official = snap.get("official", {})
    check("429 未计入官方失败", official.get("fails", 0) == 0,
          official)
finally:
    requests.Session.send = _orig_send
    mirror.time.sleep = _orig_sleep
    mirror.reset_source_health()

# ── 7. _retry_after_seconds 解析 ─────────────────────────────────────
check("Retry-After 数值解析", mirror._retry_after_seconds(
    _Resp(429, {"Retry-After": "3"})) == 3.0)
check("Retry-After 缺失取默认", mirror._retry_after_seconds(_Resp(429)) == 5.0)
check("Retry-After 非法取默认", mirror._retry_after_seconds(
    _Resp(429, {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})) == 5.0)

# ── 8. 包装器：接管成功的路径不再调用原实现 ────────────────────────────
d = _case("wrap")
p = os.path.join(d, "f.jar")
seen = []


def _orig(url, path, callback={}, sha1=None, lzma_compressed=False,
          session=None, minecraft_directory=None, overwrite=False):
    seen.append(path)
    return "orig"


wrapped = mirror._wrap_download_file(_orig)
sess = _Sess([_Resp(200, {"Content-Length": "1024"}, [DATA[:512], DATA[512:]])])
check("包装器走续传路径", wrapped(
    "https://launchermeta.mojang.com/x", p, {}, SHA, False, sess, None,
    False) is True)
check("成功时未调用原实现", seen == [])
check("包装器产物正确", os.path.exists(p) and open(p, "rb").read() == DATA)

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)

print()
if fails:
    print("FAILED: %d 项 -> %s" % (len(fails), fails))
    sys.exit(1)
print("ALL PASS")
