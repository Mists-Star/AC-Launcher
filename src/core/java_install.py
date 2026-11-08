"""Download & install any Minecraft-supported Java runtime, no admin rights.

Source: Eclipse Adoptium (Temurin) — the same builds mainstream launchers hand out.
We fetch the portable ZIP and unpack it under our own data dir, so nothing
touches the system, no installer UAC prompt, and several majors can coexist.

Every Java major Minecraft has ever needed is offered:
    8  → 1.0 – 1.16.5
    11 → optional for old modpacks
    16 → 1.17.x
    17 → 1.18 – 1.20.4
    21 → 1.20.5+ / 1.21+
    22/23/24 → future / snapshot builds
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import zipfile

import requests

from ..paths import get_data_dir

_API = "https://api.adoptium.net/v3/binary/latest"
_RELEASES_API = "https://api.adoptium.net/v3/info/available_releases"

# round-177：官方 API 的 307 会跳到 GitHub Releases（国内实测 ~10 KB/s，
# 55.9 MB 要 ~95 分钟）。USTC 镜像同一文件实测 22.8 MB/s / 2.57 秒，
# Content-Length 与官方逐字节一致，且支持 Range。镜像发现失败一律回退官方。
_MIRROR_ROOT = "https://mirrors.ustc.edu.cn/adoptium/releases"

# major -> which Minecraft versions it covers (shown in the UI)
JAVA_CHOICES = [
    (8,  "1.0 – 1.16.5"),
    (11, "旧整合包 / Legacy modpacks"),
    (16, "1.17 – 1.17.1"),
    (17, "1.18 – 1.20.4"),
    (21, "1.20.5+ / 1.21+"),
    (24, "快照 / Snapshot"),
    (25, "未来版本 / Snapshot"),
]

_DEFAULT_MAJORS = [8, 17, 21]


def java_root() -> str:
    """Where our downloaded runtimes live."""
    return os.path.join(get_data_dir(), "java")


def installed_majors() -> dict[int, str]:
    """Return {major: java_exe_path} for runtimes WE installed."""
    out: dict[int, str] = {}
    root = java_root()
    if not os.path.isdir(root):
        return out
    exe = "java.exe" if platform.system() == "Windows" else "java"
    for name in os.listdir(root):
        if not name.startswith("jdk-") and not name.startswith("jre-"):
            continue
        try:
            major = int(name.split("-")[1].split(".")[0])
        except (IndexError, ValueError):
            continue
        # Adoptium zips unpack to <root>/<tag>/<jdk-xx+yy-jre>/bin/java.exe
        for base, _dirs, files in os.walk(os.path.join(root, name)):
            if exe in files and os.path.basename(base) == "bin":
                out[major] = os.path.join(base, exe)
                break
    return out


def available_majors() -> list[int]:
    """可选择的 Java major = 官方在售 ∪ 静态表 ∪ **本机已安装**。

    round-177：旧实现离线时只回退到 ``JAVA_CHOICES``（最大 24），而
    ``installed_majors()`` 只被拿去渲染「已安装」卡片、从不进版本下拉。
    结果是用镜像/手动装好的 Java 25 路径能选、能正常启动，下拉里却
    永远看不见。把已装 major 并进来，在线离线表现一致。
    """
    majors = {m for m, _ in JAVA_CHOICES}
    try:
        r = requests.get(_RELEASES_API, timeout=10)
        r.raise_for_status()
        data = r.json()
        for m in (data.get("available_releases") or []):
            try:
                majors.add(int(m))
            except (TypeError, ValueError):
                continue
    except Exception:  # noqa: BLE001 - 离线就用静态表 + 本机已装
        pass
    try:
        majors.update(int(m) for m in installed_majors())
    except Exception:  # noqa: BLE001 - 目录不可读也不能让下拉空掉
        pass
    return sorted(majors)


def _os_arch() -> tuple[str, str]:
    sysname = platform.system().lower()
    os_name = {"windows": "windows", "darwin": "mac", "linux": "linux"}.get(sysname, "linux")
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        arch = "x64"
    elif machine in ("arm64", "aarch64"):
        arch = "aarch64"
    elif machine in ("i386", "i686", "x86"):
        arch = "x86"
    else:
        arch = "x64"
    return os_name, arch


def download_url(major: int, image_type: str = "jre") -> str:
    os_name, arch = _os_arch()
    return (
        f"{_API}/{major}/ga/{os_name}/{arch}/{image_type}/hotspot/normal/eclipse"
        f"?project=jdk"
    )


def mirror_url(major: int, image_type: str = "jre", timeout: int = 8) -> str:
    """从国内镜像目录里找出与当前平台匹配的 JRE/JDK 包；找不到返回 ""。

    目录结构：``temurin<major>-binaries/<tag>/OpenJDK<major>U-jre_<arch>_<os>_hotspot_<ver>.zip``。
    major 8 的 tag 是 ``jdk8u512-b09`` 这种（没有 ``jdk-`` 前缀），所以两个
    正则分支都要有。整个过程只读目录 HTML，不做大文件请求。
    """
    try:
        os_name, arch = _os_arch()
        if arch not in ("x64", "aarch64"):
            return ""
        base = f"{_MIRROR_ROOT}/temurin{major}-binaries/"
        html = requests.get(base, timeout=(4, timeout)).text
        tags = [x for x in re.findall(r'href="[^"]*/([^"/]+)/"', html or "")
                if x.startswith("jdk") and x != "LatestRelease"]
        if not tags:
            return ""
        tag = sorted(set(tags))[-1]
        listing = requests.get(f"{base}{tag}/", timeout=(4, timeout)).text
        ext = r"(?:zip|tar\.gz)"
        pattern = (rf"OpenJDK{major}U-{image_type}_{arch}_{os_name}_hotspot_"
                   rf"[^<>\"\s]+\.{ext}")
        files = sorted(set(re.findall(pattern, listing or "")))
        if not files:
            return ""
        return f"{base}{tag}/{files[-1]}"
    except Exception:  # noqa: BLE001 - 镜像不可达/结构变了 → 静默回退官方
        return ""


def candidate_urls(major: int, image_type: str = "jre") -> list[str]:
    """镜像优先、官方兜底；镜像发现失败时列表里就只有官方一条。"""
    urls: list[str] = []
    m = mirror_url(major, image_type)
    if m:
        urls.append(m)
    urls.append(download_url(major, image_type))
    return urls


def _find_java_exe(root: str, exe_name: str) -> str:
    """目录里是否已经有可用的 java 可执行文件（用于「绝不误删已装运行时」）。"""
    if not os.path.isdir(root):
        return ""
    for base, _dirs, files in os.walk(root):
        if exe_name in files and os.path.basename(base) == "bin":
            return os.path.join(base, exe_name)
    return ""


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


class JavaInstallCancelled(Exception):
    """玩家取消了 Java 下载（与网络失败区分，UI 按「已取消」显示）。"""


def install_java(major: int, progress=None, image_type: str = "jre",
                 cancel=None) -> str:
    """Download + unpack Java *major*. Returns the java executable path.

    ``progress(done_bytes, total_bytes, phase)`` is called during the download
    (``total`` may be 0 when the server omits Content-Length). ``phase`` 取
    ``connect`` / ``download`` / ``extract``，UI 据此显示「连接 / 下载 / 解压」。

    ``cancel`` 是返回 bool 的可调用对象（通常是 ``threading.Event.is_set``）：
    每读一块检查一次，取消时删掉半截 zip 并抛 :class:`JavaInstallCancelled`。

    round-177：镜像优先 + 官方兜底 + 同 URL Range 断点续传；取消只清半成品，
    绝不删目录里已经可用的 ``java.exe``（外部补装 / 上次装好的运行时）。
    """
    exe_name = "java.exe" if platform.system() == "Windows" else "java"
    already = installed_majors().get(major)
    if already and os.path.isfile(already):
        return already

    root = java_root()
    os.makedirs(root, exist_ok=True)
    target = os.path.join(root, f"jre-{major}")
    tmp_zip = os.path.join(root, f"_dl_{major}.zip")
    part = tmp_zip + ".part"
    part_src = part + ".src"

    def _fetch(url: str) -> None:
        """单源下载（同一 URL 支持 Range 续传），成功后原子改名为 tmp_zip。"""
        offset = 0
        if os.path.isfile(part) and os.path.isfile(part_src):
            try:
                with open(part_src, "r", encoding="utf-8") as f:
                    prev = f.read().strip()
                size = os.path.getsize(part)
                # 换源后字节不一定一致 → 不复用，从头下。
                if prev == url and size > 0:
                    offset = size
            except (OSError, ValueError):
                offset = 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        # 先落来源标记：下载中途断网时 .part 才有归属，下次启动能续传。
        # 放在请求之前，否则失败路径根本来不及写，断点续传等于白做。
        with open(part_src, "w", encoding="utf-8") as f:
            f.write(url)
        if progress:
            progress(offset, 0, "connect")
        with requests.get(url, stream=True, timeout=(10, 30),
                          headers=headers, allow_redirects=True) as r:
            status = getattr(r, "status_code", 200)
            if offset and status == 200:
                offset = 0  # 服务端忽略 Range → 重新从头写
            r.raise_for_status()
            if status not in (200, 206):
                raise RuntimeError(f"HTTP {status}")
            total = int((r.headers or {}).get("Content-Length") or 0) + offset
            done = offset
            with open(part, "ab" if offset else "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if cancel is not None and cancel():
                        raise JavaInstallCancelled("java download cancelled")
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total, "download")
        os.replace(part, tmp_zip)
        _remove_quietly(part_src)

    if cancel is not None and cancel():
        raise JavaInstallCancelled("java download cancelled")

    try:
        urls = candidate_urls(major, image_type)
        last_err = None
        ok = False
        for idx, url in enumerate(urls):
            if cancel is not None and cancel():
                raise JavaInstallCancelled("java download cancelled")
            try:
                _fetch(url)
                ok = True
                break
            except JavaInstallCancelled:
                raise
            except Exception as e:  # noqa: BLE001 - 换下一个来源
                last_err = e
                # 还有备用源时丢弃上一源的 .part（字节可能不同）；
                # 最后一个源失败则保留 .part/.src，供下次启动断点续传。
                if idx < len(urls) - 1:
                    _remove_quietly(part)
                    _remove_quietly(part_src)
        if not ok:
            raise RuntimeError(
                f"Java {major} 下载失败（已尝试 {len(urls)} 个来源）：{last_err}")

        if cancel is not None and cancel():
            raise JavaInstallCancelled("java download cancelled")
        if progress:
            progress(0, 0, "extract")
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        os.makedirs(target, exist_ok=True)
        try:
            if tmp_zip.endswith(".zip") and zipfile.is_zipfile(tmp_zip):
                with zipfile.ZipFile(tmp_zip) as z:
                    from .utils import safe_extract_zip
                    safe_extract_zip(z, target)  # round-35 zip-slip 防护
            else:  # linux/mac tarballs
                shutil.unpack_archive(tmp_zip, target)
            # 解压本身不可中断（zipfile 没有取消点）：解完再查一次。
            if cancel is not None and cancel():
                raise JavaInstallCancelled("java extract cancelled")
        finally:
            _remove_quietly(tmp_zip)
    except BaseException:
        _remove_quietly(tmp_zip)
        cancelled = bool(cancel is not None and cancel())
        if cancelled:
            # 用户明确要求：取消就把未下完的包删掉，不挤占空间。
            # 网络失败则保留 .part/.src，下次启动可从断点继续。
            _remove_quietly(part)
            _remove_quietly(part_src)
        # ☠ round-177：只清本次下载的半成品目录。若 target 里已经有可用的
        # java.exe（外部镜像补装、或上一次已装好的运行时），绝不能 rmtree。
        if not _find_java_exe(target, exe_name):
            shutil.rmtree(target, ignore_errors=True)
        raise

    path = _find_java_exe(target, exe_name)
    if not path:
        raise RuntimeError(f"解压后未找到 {exe_name}（{target}）")
    if platform.system() != "Windows":
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass
    # round-216：装了新运行时就把 scan_javas 缓存清掉，否则自动选择 / 体检
    # 在 TTL（deep 5 分钟）内仍然看不到它。
    try:
        from .java import invalidate_scan_cache
        invalidate_scan_cache()
    except Exception:  # noqa: BLE001 - 缓存失效失败不影响安装结果
        pass
    return path
