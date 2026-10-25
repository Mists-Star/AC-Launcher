"""
EasyTier — virtual LAN (P2P) integration for the out-of-game lobby.

Runs a local ``easytier-core`` node so that players on the same lobby
(virtual network) can reach each other's virtual IPs and play Minecraft
"局域网开放" across the internet — same pattern as 网易我的世界 / 苦力怕联机.

Everything here is best-effort: if easytier-core is missing we surface a
download prompt; if a node fails to start we report the error and keep the
lobby usable (the local lobby bookkeeping in ``lobby.py`` still works).

Command model (verified against official docs, 2026-08):
    easytier-core -d --network-name <name> --network-secret <secret> \\
        -p tcp://public.easytier.cn:11010
  -d              DHCP: auto-assign a virtual IP on 10.126.126.0/24
  --network-name  virtual network id (lobby code)
  --network-secret  network password
  -p              shared relay node (public.easytier.cn is the official free one)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import urllib.request
import urllib.parse

from ..paths import get_data_dir

# Official public shared node (free; P2P NAT traversal with relay fallback).
DEFAULT_PEER = "tcp://public.easytier.cn:11010"

# Release download base (GitHub) — Windows x86_64.
# Primary URL + mirrors for regions where GitHub is blocked.
EASYTIER_VERSION = "v2.6.4"
EASYTIER_FILENAME = f"easytier-windows-x86_64-{EASYTIER_VERSION}.zip"
EASYTIER_RELEASE_URLS = [
    f"https://github.com/EasyTier/EasyTier/releases/download/{EASYTIER_VERSION}/{EASYTIER_FILENAME}",
    f"https://ghfast.top/https://github.com/EasyTier/EasyTier/releases/download/{EASYTIER_VERSION}/{EASYTIER_FILENAME}",
    f"https://v6.gh-proxy.org/https://github.com/EasyTier/EasyTier/releases/download/{EASYTIER_VERSION}/{EASYTIER_FILENAME}",
    f"https://cdn.gh-proxy.org/https://github.com/EasyTier/EasyTier/releases/download/{EASYTIER_VERSION}/{EASYTIER_FILENAME}",
    f"https://edgeone.gh-proxy.org/https://github.com/EasyTier/EasyTier/releases/download/{EASYTIER_VERSION}/{EASYTIER_FILENAME}",
]
EASYTIER_RELEASE_URL = EASYTIER_RELEASE_URLS[0]
EASYTIER_DOCS_URL = "https://easytier.cn"

_BIN_DIR = os.path.join(get_data_dir(), "easytier")

_shared_lock = threading.Lock()
_node_proc: subprocess.Popen | None = None
_node_lock = threading.Lock()


# ---------------------------------------------------------------- detection
def find_easytier() -> str | None:
    """Locate easytier-core.exe on PATH or in the bundled bin dir."""
    # 1) bundled (downloaded) copy
    bundled = os.path.join(_BIN_DIR, "easytier-core.exe")
    if os.path.isfile(bundled):
        return bundled
    # 2) PATH
    exe = shutil.which("easytier-core") or shutil.which("easytier-core.exe")
    if exe:
        return exe
    return None


def easytier_installed() -> bool:
    return find_easytier() is not None


def bundled_dir() -> str:
    return _BIN_DIR


def download_url() -> str:
    return EASYTIER_RELEASE_URL


def download_easytier(dest_dir: str, progress=None) -> str:
    """Download + unzip easytier-core into dest_dir. Returns the exe path.

    Tries multiple mirrors (GitHub direct → ghproxy mirrors) for regions where
    GitHub is blocked. Raises on failure so the UI can show an error.
    """
    os.makedirs(dest_dir, exist_ok=True)
    import io
    import zipfile

    last_error = None
    for url in EASYTIER_RELEASE_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AC-Launcher/0.2"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                data = io.BytesIO()
                got = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    data.write(chunk)
                    got += len(chunk)
                    if total and progress:
                        progress(got / total)
            data.seek(0)
            with zipfile.ZipFile(data) as z:
                from .utils import safe_extract_zip
                safe_extract_zip(z, dest_dir)
            exe = os.path.join(dest_dir, "easytier-core.exe")
            if not os.path.isfile(exe):
                # zip may nest one folder deep
                for name in os.listdir(dest_dir):
                    cand = os.path.join(dest_dir, name, "easytier-core.exe")
                    if os.path.isfile(cand):
                        exe = cand
                        break
            if os.path.isfile(exe):
                return exe
            else:
                last_error = "下载成功但解压后未找到 easytier-core.exe"
        except Exception as e:
            last_error = str(e)
            continue

    raise RuntimeError(f"EasyTier 下载失败（所有镜像均不可用）：{last_error}")


# ------------------------------------------------------------------ running
def start_node(network_name: str, network_secret: str,
               hostname: str = "", peer: str = DEFAULT_PEER) -> dict:
    """Start a local easytier-core node joining ``network_name``.

    Returns a status dict {ok, ip?, error?, pid?}. Blocking only until the
    process is spawned (the node keeps running in the background).
    """
    global _node_proc
    exe = find_easytier()
    if not exe:
        return {"ok": False, "error": "easytier-core 未安装"}

    # round-39 P2-7 安全：network_secret 走环境变量 ET_NETWORK_SECRET
    # （easytier-core 官方支持），不落在命令行/进程列表（之前 --network-secret
    # 直接暴露给 tasklist / 其他进程可读）。
    cmd = [exe, "-d", "--network-name", network_name, "-p", peer]
    if hostname:
        cmd += ["--hostname", hostname]
    env = dict(os.environ)
    env["ET_NETWORK_SECRET"] = network_secret
    # Hide the console window on Windows.
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        with _node_lock:
            # Stop any previous node first (one at a time is plenty for a launcher).
            if _node_proc is not None and _node_proc.poll() is None:
                _node_proc.terminate()
                try:
                    _node_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _node_proc.kill()
            _node_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
            )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}

    # Give the node a moment to bring up the virtual interface, then read its IP.
    ip = _probe_ip(network_name)
    return {"ok": True, "ip": ip or "", "pid": _node_proc.pid}


def stop_node() -> None:
    """Stop the currently running easytier node (if any)."""
    global _node_proc
    with _node_lock:
        if _node_proc is not None and _node_proc.poll() is None:
            try:
                _node_proc.terminate()
                _node_proc.wait(timeout=5)
            except Exception:
                try:
                    _node_proc.kill()
                except Exception:
                    pass
        _node_proc = None


def _probe_ip(network_name: str) -> str:
    """Try to read the node's DHCP-assigned virtual IP.

    Prefers `easytier-cli` if available; falls back to `ipconfig` parsing.
    Best effort — returns "" if we can't determine it quickly.
    """
    exe = find_easytier()
    if not exe:
        return ""
    cli = exe.replace("easytier-core", "easytier-cli")
    candidates: list[str] = []
    # 1) easytier-cli node → {"ipv4": "10.126.126.x"}
    if os.path.isfile(cli):
        try:
            out = subprocess.run(
                [cli, "node"], capture_output=True, text=True, timeout=10
            ).stdout or ""
            import re
            m = re.search(r'10\.126\.\d+\.\d+', out)
            if m:
                candidates.append(m.group(0))
        except Exception:
            pass
    # 2) ipconfig parse (Windows): any 10.126.126.x interface
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["ipconfig"], capture_output=True, text=True, timeout=10
            ).stdout or ""
            import re
            for m in re.finditer(r'10\.126\.\d+\.\d+', out):
                candidates.append(m.group(0))
        except Exception:
            pass
    return candidates[0] if candidates else ""
