"""Java 下载链路回归（round-177）：镜像优先 / 断点续传 / 取消不误删。

事故链（2026-11-06 真机）：
  - `java_install.py` 直接 GET `api.adoptium.net` → 307 到 GitHub Releases，
    国内实测 ~10 KB/s，55.9 MB 要 ~95 分钟；项目自己的 Range 分片 / 来源
    健康 / 断点续传一条都没接上。
  - 取消/失败分支 `shutil.rmtree(target)` 会把目录里**已装好的完整 JRE**
    一起删掉（外部用国内镜像补装的运行时就这么被删）。
  - 用户明确要求：取消要删掉未下完的包（不挤占空间），但别删已装好的。

判据全部是真实调用 `install_java()` 的行为判据，用 fake requests 控源，
不看日志文案、不靠注释。
"""
import io
import os
import sys
import tempfile
import threading
import types
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core import java_install  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-60s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def zip_payload() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("jdk-21.0.9-jre/bin/java.exe", b"MZ")
        z.writestr("jdk-21.0.9-jre/release", b"JAVA_VERSION=21\n")
    return buf.getvalue()


class Resp:
    def __init__(self, payload=b"", status=200, text="", on_chunk=None,
                 headers=None, fail=False):
        self._payload = payload
        self.status_code = status
        self.text = text
        self.headers = headers if headers is not None else {
            "Content-Length": str(len(payload))}
        self._on_chunk = on_chunk
        self._fail = fail

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP %d" % self.status_code)

    def iter_content(self, size):
        if self._fail:
            yield b"partial"
            raise OSError("network dropped")
        for i in range(0, len(self._payload), 8192):
            if self._on_chunk:
                self._on_chunk()
            yield self._payload[i:i + 8192]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


TMP = tempfile.mkdtemp(prefix="_java177_")
ORIG = {
    "get_data_dir": java_install.get_data_dir,
    "requests": java_install.requests,
    "mirror_url": java_install.mirror_url,
}
java_install.get_data_dir = lambda: TMP
ROOT = os.path.join(TMP, "java")
os.makedirs(ROOT, exist_ok=True)


def fresh_major(major):
    import shutil
    target = os.path.join(ROOT, "jre-%d" % major)
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    for suffix in (".zip", ".zip.part", ".zip.part.src"):
        p = os.path.join(ROOT, "_dl_%d%s" % (major, suffix))
        if os.path.isfile(p):
            os.remove(p)
    return target


print("== Java 镜像 / 断点 / 取消语义 ==")

# ── 1. 镜像优先，镜像失败回退官方 ──────────────────────────────────
fresh_major(21)
MIRROR = "https://mirror.test/OpenJDK21U-jre_x64_windows_hotspot.zip"
java_install.mirror_url = lambda *a, **k: MIRROR
calls = []
payload = zip_payload()


def get_mirror_then_official(url, **kw):
    calls.append((url, kw.get("headers", {})))
    if url == MIRROR:
        raise OSError("mirror unreachable")
    return Resp(payload)


java_install.requests = types.SimpleNamespace(get=get_mirror_then_official)
path = java_install.install_java(21)
check("候选源顺序：镜像在前、官方在后",
      len(calls) >= 2 and calls[0][0] == MIRROR
      and "api.adoptium.net" in calls[1][0],
      str([c[0][:40] for c in calls]))
check("镜像失败后官方源仍能装出 java.exe",
      os.path.isfile(path or ""), str(path))
check("成功后不残留 .part / .src",
      not os.path.exists(os.path.join(ROOT, "_dl_21.zip.part"))
      and not os.path.exists(os.path.join(ROOT, "_dl_21.zip.part.src")))

# ── 2. 同一 URL Range 断点续传 ─────────────────────────────────────
fresh_major(22)
java_install.mirror_url = lambda *a, **k: ""
OFFICIAL22 = java_install.download_url(22)
part = os.path.join(ROOT, "_dl_22.zip.part")
cut = 40
open(part, "wb").write(payload[:cut])
open(part + ".src", "w", encoding="utf-8").write(OFFICIAL22)
seen_headers = []


def get_range(url, **kw):
    seen_headers.append(kw.get("headers", {}))
    # 真实支持 Range 的源返回 206 + 剩余字节；fake 必须还原这个语义。
    return Resp(payload[cut:], status=206)


java_install.requests = types.SimpleNamespace(get=get_range)
path2 = java_install.install_java(22)
check("续传请求带 Range: bytes=40-",
      seen_headers and seen_headers[0].get("Range") == "bytes=40-",
      str(seen_headers[:1]))
check("续传拼接后 zip 完整可用",
      os.path.isfile(path2 or ""), str(path2))

# ── 3. 换源后不复用旧 .part（避免字节混拼） ────────────────────────
fresh_major(23)
open(os.path.join(ROOT, "_dl_23.zip.part"), "wb").write(b"X" * 99)
open(os.path.join(ROOT, "_dl_23.zip.part.src"), "w",
     encoding="utf-8").write("https://some.other.source/x.zip")
hdrs = []
java_install.requests = types.SimpleNamespace(
    get=lambda url, **kw: (hdrs.append(kw.get("headers", {})), Resp(payload))[1])
java_install.install_java(23)
check("来源变化时忽略旧断点、从头下载",
      hdrs and not hdrs[0].get("Range"), str(hdrs[:1]))

# ── 4. ☠ 取消绝不误删目录里已装好的 java.exe ────────────────────────
target = fresh_major(24)
java_install.mirror_url = lambda *a, **k: ""
ev = threading.Event()
installed_exe = os.path.join(target, "jdk-24.0.1-jre", "bin", "java.exe")


def plant_then_cancel():
    """模拟「下载进行中，外部把完整 JRE 放进 target」后用户点取消。

    注意：不能在调用 install_java 之前就放好，否则 installed_majors()
    会直接短路返回，测的就不是取消分支了。
    """
    if not os.path.isfile(installed_exe):
        os.makedirs(os.path.dirname(installed_exe), exist_ok=True)
        open(installed_exe, "wb").write(b"PRE-INSTALLED-JRE")
    if not ev.is_set():
        ev.set()


java_install.requests = types.SimpleNamespace(
    get=lambda url, **kw: Resp(b"x" * 65536, on_chunk=plant_then_cancel))
err = ""
try:
    java_install.install_java(24, cancel=ev.is_set)
except BaseException as e:  # noqa: BLE001
    err = type(e).__name__
check("取消仍抛 JavaInstallCancelled", err == "JavaInstallCancelled", err)
check("☠ 已装好的 java.exe 没有被误删",
      os.path.isfile(installed_exe)
      and open(installed_exe, "rb").read() == b"PRE-INSTALLED-JRE")
check("取消清掉半截 .part / .src（不挤占空间）",
      not os.path.exists(os.path.join(ROOT, "_dl_24.zip.part"))
      and not os.path.exists(os.path.join(ROOT, "_dl_24.zip.part.src")))

# ── 5. 网络失败（非取消）保留断点供下次续传 ─────────────────────────
fresh_major(25)
java_install.mirror_url = lambda *a, **k: ""
java_install.requests = types.SimpleNamespace(
    get=lambda url, **kw: Resp(b"", fail=True))
err2 = ""
try:
    java_install.install_java(25)
except BaseException as e:  # noqa: BLE001
    err2 = type(e).__name__
check("多源全失败抛 RuntimeError", err2 == "RuntimeError", err2)
check("非取消的失败保留 .part / .src 供续传",
      os.path.isfile(os.path.join(ROOT, "_dl_25.zip.part"))
      and os.path.isfile(os.path.join(ROOT, "_dl_25.zip.part.src")))

# ── 6. mirror_url 能解析 USTC 真实目录结构 ──────────────────────────
DIR_HTML = ('<a href="/adoptium/releases/temurin21-binaries/'
            'jdk-21.0.9%2B10/">jdk-21.0.9+10/</a>')
FILE_HTML = ('<a href="OpenJDK21U-jre_x64_windows_hotspot_21.0.9_10.zip">'
             'OpenJDK21U-jre_x64_windows_hotspot_21.0.9_10.zip</a>')


def get_listing(url, **kw):
    return Resp(text=(FILE_HTML if "jdk-21.0.9" in url else DIR_HTML))


java_install.mirror_url = ORIG["mirror_url"]
java_install.requests = types.SimpleNamespace(get=get_listing)
guessed = java_install.mirror_url(21)
check("镜像目录解析出确切 zip URL",
      "temurin21-binaries/jdk-21.0.9%2B10/" in guessed
      and guessed.endswith("OpenJDK21U-jre_x64_windows_hotspot_21.0.9_10.zip"),
      guessed[-60:])

# ── 7. 静态防再犯 ──────────────────────────────────────────────────
src = open(os.path.join(HERE, "src/core/java_install.py"),
           "r", encoding="utf-8").read()
check("取消分支不再无条件 rmtree(target)",
      "shutil.rmtree(target, ignore_errors=True)" in src
      and "if not _find_java_exe(target, exe_name):" in src)
check("候选源含官方兜底",
      "urls.append(download_url(major, image_type))" in src)

# ── 8. ☠ 已装 Java 25 必须出现在版本下拉里（真机反馈） ────────────
java_install.mirror_url = ORIG["mirror_url"]
java_install.requests = types.SimpleNamespace(
    get=lambda url, **kw: (_ for _ in ()).throw(OSError("offline")))
j25 = os.path.join(ROOT, "jre-25", "jdk-25.0.5-jre", "bin")
os.makedirs(j25, exist_ok=True)
open(os.path.join(j25, "java.exe"), "wb").write(b"MZ")
majors = java_install.available_majors()
check("离线时已装的 Java 25 仍出现在候选列表",
      25 in majors, str(majors))
check("静态 JAVA_CHOICES 也补了 25",
      any(m == 25 for m, _d in java_install.JAVA_CHOICES))

# ── 还原 ───────────────────────────────────────────────────────────
java_install.get_data_dir = ORIG["get_data_dir"]
java_install.requests = ORIG["requests"]
java_install.mirror_url = ORIG["mirror_url"]
import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)

print("== %s ==" % ("PASS" if not fails else "FAIL %d" % len(fails)))
sys.exit(1 if fails else 0)
