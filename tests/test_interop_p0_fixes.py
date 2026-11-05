"""横向实现审计 P0 三项修复的回归（2026-11-05）。

对照主流启动器实现，防止以下三处被后续 round 改回去：
  1. 账号字段错位：存储是 {id, name, access_token}，启动读 username/uuid/token
     → 所有已登录账号以 Player / '' / '' 空凭证启动；
  2. install.py 缺 import json → find_installed_loader 对 NeoForge 1.21+
     / Cleanroom 抛 NameError；
  3. LiteLoader 子 json 只写 --tweakClass 且无 jar → mll 继承后父参数全丢、
     classpath 缺原版主 jar。

静态判据 + 行为判据（用临时目录真实调用 install_liteloader 并让 mll 继承）。
"""
import io
import json
import os
import sys
import tempfile
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.accounts import launch_identity  # noqa: E402
from src.launch import build_options  # noqa: E402
from src.core import install  # noqa: E402
import minecraft_launcher_lib  # noqa: E402
from minecraft_launcher_lib._helper import inherit_json  # noqa: E402
from minecraft_launcher_lib.command import get_libraries  # noqa: E402

fails = []
checks = 0


def check(label, cond, extra=""):
    global checks
    checks += 1
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with io.open(os.path.join(HERE, rel), "r", encoding="utf-8") as fh:
        return fh.read()


print("== 横向审计 P0 修复回归 ==")

# ── 1. 账号字段归一化 ─────────────────────────────────────────────────
ms = {"id": "069a79f444e34c1b8a5a2b0f1e2c3d4e5", "name": "WuXing",
      "access_token": "MCTOKEN", "type": "microsoft",
      "refresh_token": "RT", "ms_access_token": "MS"}
i = launch_identity(ms)
check("微软 profile → 真实玩家名", i["username"] == "WuXing", repr(i["username"]))
check("微软 profile → 真实 UUID（id）", i["uuid"] == ms["id"])
check("微软 profile → 真实 access_token", i["token"] == "MCTOKEN")

off = {"id": "a1b2c3d4e5f6", "name": "Offline", "uuid": "",
       "access_token": "", "type": "offline"}
i2 = launch_identity(off)
check("离线账号不伪造 token", i2["token"] == "" and i2["username"] == "Offline")
# 只断言「非空」：合法的 OfflinePlayer:<name> UUID v3 仍属 P1 待办，
# 别把当前 12 位内部 id 这个过渡态固化成标准行为。
check("离线账号拿到非空身份 id", bool(i2["uuid"]))

legacy = {"username": "Player", "uuid": "", "token": ""}
i3 = launch_identity(legacy)
check("旧三键 OFFLINE_ACCOUNT 兼容", i3 == legacy, repr(i3))
check("空账号安全降级", launch_identity(None) == legacy)

o = build_options(i["username"], i["uuid"], i["token"],
                  mc_dir="C:/tmp", java="java")
check("build_options 收到真实凭证（非 Player/空）",
      o["username"] == "WuXing" and o["uuid"] == ms["id"]
      and o["token"] == "MCTOKEN")

lp = read(os.path.join("src", "launch.py"))
check("launch.py 不再直接读 account.get('token')",
      'account.get("token"' not in lp)
check("launch.py 走统一归一化", "launch_identity(account)" in lp)
mw = read(os.path.join("src", "main_window.py"))
check("_game_token 用归一化 token",
      'launch_identity(account)["token"]' in mw)
check("皮肤拉取用归一化 uuid", '_ident["uuid"]' in mw)

# ── 2. find_installed_loader 不再 NameError ──────────────────────────
check("install 模块导入了 json", hasattr(install, "json"))
with tempfile.TemporaryDirectory() as d:
    n = "neoforge-21.1.0"
    vd = os.path.join(d, "versions", n)
    os.makedirs(vd)
    with io.open(os.path.join(vd, n + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": n, "inheritsFrom": "1.21"}, f)
    try:
        got = install.find_installed_loader(d, "neoforge", "1.21")
        check("NeoForge 1.21+ 按 inheritsFrom 命中", got == n, repr(got))
    except Exception as e:  # noqa: BLE001
        check("NeoForge 1.21+ 按 inheritsFrom 命中", False,
              "%s: %s" % (type(e).__name__, e))

# ── 3. LiteLoader 子 json 继承 ────────────────────────────────────────
PARENT_ARGS = (
    "--username ${auth_player_name} --version ${version_name} "
    "--gameDir ${game_directory} --assetsDir ${assets_root} "
    "--assetIndex ${assets_index_name} --uuid ${auth_uuid} "
    "--accessToken ${auth_access_token} --userType ${user_type}"
)


def _make_parent(mc_dir):
    p = os.path.join(mc_dir, "versions", "1.12.2")
    os.makedirs(p, exist_ok=True)
    # 全 ASCII：mll 的 inherit_json 用无 encoding 的 open()，避免 locale 差异
    with io.open(os.path.join(p, "1.12.2.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "1.12.2", "type": "release", "assets": "1.12",
                   "mainClass": "net.minecraft.client.main.Main",
                   "minecraftArguments": PARENT_ARGS, "libraries": []}, f)


_patch_target = (minecraft_launcher_lib.install, "install_minecraft_version")
with tempfile.TemporaryDirectory() as d:
    _make_parent(d)
    with mock.patch.object(*_patch_target, lambda *a, **k: None):
        ver_id = install.install_liteloader(
            "1.12.2", d, libraries=[{"name": "net.minecraft:launchwrapper:1.12"}])
    child_path = os.path.join(d, "versions", ver_id, ver_id + ".json")
    with io.open(child_path, "r", encoding="utf-8") as f:
        child = json.load(f)
    args = str(child.get("minecraftArguments") or "")
    check("子 json 保留父 --username", "--username ${auth_player_name}" in args)
    check("子 json 保留父 --accessToken", "--accessToken ${auth_access_token}" in args)
    check("子 json 保留父 --gameDir", "--gameDir ${game_directory}" in args)
    check("子 json 追加 tweakClass",
          "--tweakClass com.mumfrey.liteloader.launch.LiteLoaderTweaker" in args)
    check("子 json 显式 jar 指回原版", child.get("jar") == "1.12.2",
          repr(child.get("jar")))

    merged = inherit_json(child, d)
    check("mll 继承后父参数不丢",
          all(tok in merged["minecraftArguments"] for tok in PARENT_ARGS.split()))
    check("mll 继承后 jar 保留", merged.get("jar") == "1.12.2")
    cp = get_libraries(merged, d)
    expect = os.path.join("versions", "1.12.2", "1.12.2.jar")
    check("classpath 指向原版主 jar（非 -LiteLoader）", cp.endswith(expect),
          cp[-58:])

with tempfile.TemporaryDirectory() as d:
    with mock.patch.object(*_patch_target, lambda *a, **k: None):
        try:
            install.install_liteloader("1.12.2", d, libraries=[])
            check("父 json 缺失时显式报错（不静默造坏 json）", False, "未抛异常")
        except RuntimeError as e:
            check("父 json 缺失时显式报错（不静默造坏 json）",
                  "minecraftArguments" in str(e), str(e)[:60])

print()
if fails:
    print("FAILED: %d → %s" % (len(fails), "; ".join(fails)))
    sys.exit(1)
print("ALL OK (%d checks)" % checks)
