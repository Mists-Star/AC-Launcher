"""round-113 live verification: real download throughput via patched MirrorSession.

Compares the mll default concurrency (16) against the patched one (48) on the
same real asset set, using the actual patched code path.
"""
import os
import sys
import time
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import mirror  # noqa: E402

H = {"User-Agent": "MC-Launcher/0.1 (local dev)"}


def get_asset_set(n=80):
    m = requests.get("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json",
                     headers=H, timeout=25).json()
    rel = [v for v in m["versions"] if v["type"] == "release"]
    target = next((v for v in rel if v["id"].startswith("1.21.")), rel[0])
    vj = requests.get(target["url"], headers=H, timeout=25).json()
    ai = requests.get(vj["assetIndex"]["url"], headers=H, timeout=25).json()
    hashes = sorted({v["hash"] for v in ai["objects"].values()})
    return hashes[:n], target["id"]


def run(urls, workers, label):
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.monotonic()
    total = [0]
    lock = __import__("threading").Lock()

    def one(u):
        r = requests.get(u, headers=H, timeout=30, stream=True)
        n = 0
        for c in r.iter_content(65536):
            n += len(c)
        r.close()
        with lock:
            total[0] += n
        return n

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, urls))
    dt = time.monotonic() - t0
    mb = total[0] / 1024 / 1024
    print(f"  {label:<44} {dt:6.2f}s  {mb / dt:6.2f}MB/s  ({mb:.1f}MB)")
    return dt, mb / dt


def main():
    hashes, ver = get_asset_set(80)
    urls = [f"https://resources.download.minecraft.net/{h[:2]}/{h}" for h in hashes]
    print(f"asset set: {len(urls)} objects, MC {ver}\n")

    print("=== plain requests (baseline, default pool=10) ===")
    run(urls, 16, "plain requests / 16 workers")
    run(urls, 48, "plain requests / 48 workers")

    print()
    print("=== via MirrorSession (patched pool=64) ===")
    mirror.set_mirror(False)  # official source
    s = mirror.MirrorSession()
    from concurrent.futures import ThreadPoolExecutor
    for workers in (16, 48):
        t0 = time.monotonic()
        total = [0]

        def one(u, _s=s):
            r = _s.get(u, headers=H, timeout=30, stream=True)
            n = 0
            for c in r.iter_content(65536):
                n += len(c)
            r.close()
            total[0] += n
            return n

        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(one, urls))
        dt = time.monotonic() - t0
        mb = total[0] / 1024 / 1024
        print(f"  MirrorSession / {workers:>2} workers{'':<24} {dt:6.2f}s  {mb / dt:6.2f}MB/s  ({mb:.1f}MB)")


if __name__ == "__main__":
    main()
