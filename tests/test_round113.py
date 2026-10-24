"""round-113 offline verification: mirror rewrite table + concurrency patch + pool.

Run:  venv\\Scripts\\python.exe tests\\test_round113.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import mirror  # noqa: E402

FAILED = []


def check(label, got, want):
    if got == want:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")
        FAILED.append(label)


print("=== A) rewrite table (mirror ON) ===")
mirror.set_mirror(True)
B = "https://bmclapi2.bangbang93.com"

CASES = [
    # Mojang hosts
    ("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json",
     B + "/mc/game/version_manifest_v2.json"),
    ("https://launcher.mojang.com/x.json", B + "/x.json"),
    ("https://piston-meta.mojang.com/v1/packages/abc/1.21.json",
     B + "/v1/packages/abc/1.21.json"),
    ("https://piston-data.mojang.com/v1/objects/sha/client.jar",
     B + "/v1/objects/sha/client.jar"),
    ("https://libraries.minecraft.net/org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar",
     B + "/maven/org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar"),
    ("https://resources.download.minecraft.net/c4/c4dbabc",
     B + "/assets/c4/c4dbabc"),
    # loader maven / meta
    ("https://meta.fabricmc.net/v2/versions/loader", B + "/fabric-meta/v2/versions/loader"),
    ("https://meta.quiltmc.org/v3/versions/loader", B + "/quilt-meta/v3/versions/loader"),
    ("https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml",
     B + "/maven/net/minecraftforge/forge/maven-metadata.xml"),
    ("https://maven.fabricmc.net/net/fabricmc/fabric-installer/0.16.9/x.jar",
     B + "/maven/net/fabricmc/fabric-installer/0.16.9/x.jar"),
    ("https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/maven-metadata.xml",
     B + "/maven/org/quiltmc/quilt-installer/maven-metadata.xml"),
    ("https://maven.neoforged.net/releases/net/neoforged/neoforge/20.4.190/neoforge-20.4.190-installer.jar",
     B + "/maven/net/neoforged/neoforge/20.4.190/neoforge-20.4.190-installer.jar"),
    # untouched
    ("https://api.modrinth.com/v2/search", "https://api.modrinth.com/v2/search"),
    ("https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge",
     "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"),
    ("https://example.com/x", "https://example.com/x"),
    # boundary safety: similar prefix must NOT match
    ("https://libraries.minecraft.net.evil.com/x.jar",
     "https://libraries.minecraft.net.evil.com/x.jar"),
]
for src, want in CASES:
    check(src[:72], mirror._rewrite(src), want)

print()
print("=== B) mirror OFF -> identity ===")
mirror.set_mirror(False)
for src, _ in CASES:
    check(f"off {src[:60]}", mirror._rewrite(src), src)

print()
print("=== C) dead-host latch ===")
mirror.set_mirror(True)
ctx = mirror.InstallContext()
mirror._SCOPE.ctx = ctx
ctx.mirror_dead.add("libraries.minecraft.net")
check("dead host falls through",
      mirror._rewrite("https://libraries.minecraft.net/org/lwjgl/x.jar"),
      "https://libraries.minecraft.net/org/lwjgl/x.jar")
check("other host still rewritten",
      mirror._rewrite("https://piston-data.mojang.com/v1/objects/s/client.jar"),
      B + "/v1/objects/s/client.jar")
mirror._SCOPE.ctx = None

print()
print("=== D) concurrency patch (mll install_libraries/install_assets) ===")
import minecraft_launcher_lib.install as mll_install  # noqa: E402

seen = {}


def _fake_libs(id, libraries, path, callback, max_workers=None):
    seen["lib"] = max_workers


def _fake_assets(data, path, callback, max_workers=None):
    seen["assets"] = max_workers


orig_lib = mll_install.install_libraries
orig_assets = mll_install.install_assets
mll_install.install_libraries = _fake_libs
mll_install.install_assets = _fake_assets
try:
    mirror._patch_install_concurrency()
    mll_install.install_libraries("id", [], "p", {})
    mll_install.install_assets({}, "p", {})
    check("install_libraries max_workers", seen.get("lib"), 48)
    check("install_assets max_workers", seen.get("assets"), 48)

    # explicit max_workers must win
    seen.clear()
    mll_install.install_libraries("id", [], "p", {}, max_workers=4)
    check("explicit max_workers preserved", seen.get("lib"), 4)

    # idempotent: patching twice must not double-wrap
    mirror._patch_install_concurrency()
    seen.clear()
    mll_install.install_libraries("id", [], "p", {})
    check("idempotent re-patch", seen.get("lib"), 48)

    # forge's direct reference must also be patched
    import minecraft_launcher_lib.mod_loader._forge as mll_forge
    if hasattr(mll_forge, "install_libraries"):
        fseen = {}

        def _fake_f(*a, **kw):
            fseen["v"] = kw.get("max_workers")
        mll_forge.install_libraries = _fake_f
        mirror._patch_install_concurrency()
        mll_forge.install_libraries("id", [], "p", {})
        check("forge direct ref patched", fseen.get("v"), 48)
    else:
        print("  SKIP forge direct ref (attr absent)")
finally:
    mll_install.install_libraries = orig_lib
    mll_install.install_assets = orig_assets

print()
print("=== E) connection pool on MirrorSession ===")
s = mirror.MirrorSession()
ad = s.get_adapter("https://example.com")
check("https pool_maxsize", ad._pool_maxsize, 64)
check("https pool_connections", ad._pool_connections, 64)
ad2 = s.get_adapter("http://example.com")
check("http pool_maxsize", ad2._pool_maxsize, 64)

print()
print("=== F) parallel chunk sizing ===")
import src.net_api as net_api  # noqa: E402
check("_MAX_WORKERS", mirror._MAX_WORKERS, 48)
check("_POOL_SIZE", mirror._POOL_SIZE, 64)

print()
if FAILED:
    print(f"FAILED {len(FAILED)}:")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
print("ALL PASS")
