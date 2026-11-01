"""round-166 回归：按磁盘现状重构实例定义（只读扫描，不改游戏文件）。

覆盖：
  1. 原版实例：版本 json 无 inheritsFrom → vanilla，记录一致时 changed 为空
  2. Forge：从 <mc>-forge-<ver> + libraries 推导版本/加载器/加载器版本
  3. Fabric：fabric-loader-<ver>-<mc> → loader_version 精确提取
  4. NeoForge：neoforge-<ver>（不含 MC 版本）靠 inheritsFrom 判原版
  5. 无版本文件 → ok=False 且给出 rebuild_no_files
  6. 格式残留 → 清回自适应（交给 round-164 的 layout_of 重新判定）
  7. 外部版本隔离（扁平 json）同样能重构
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AC_DEV_TEMP"] = "1"

import src.instances as _inst_mod  # noqa: E402

_FIXED_DATA = os.path.join(tempfile.gettempdir(), "ac_rebuild_data")
shutil.rmtree(_FIXED_DATA, ignore_errors=True)
os.makedirs(_FIXED_DATA, exist_ok=True)
_inst_mod.get_data_dir = lambda: _FIXED_DATA

from src.instances import Instance  # noqa: E402
from src.core.instance_rebuild import (  # noqa: E402
    reconstruct, infer_loader, loader_version_of)

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


TMP = tempfile.mkdtemp(prefix="ac_rebuild_")
try:
    def ac(iid, game_version="1.20.1", **kw):
        inst = Instance(id=iid, name=iid, game_version=game_version, **kw)
        os.makedirs(os.path.join(inst.mc_dir, "versions"), exist_ok=True)
        return inst

    def add_version(inst, vid, data):
        d = os.path.join(inst.mc_dir, "versions", vid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{vid}.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    # ── 1. 原版：记录已一致 → changed 为空 ──
    van = ac("van")
    add_version(van, "1.20.1", {"id": "1.20.1"})
    res = reconstruct(van)
    check("原版重构 ok", res["ok"] is True)
    check("原版 loader=vanilla", van.loader == "vanilla", van.loader)
    check("原版 version_id 留空（按 game_version 解析）", van.version_id == "",
          van.version_id)
    check("原版一致时 changed 为空", res["changed"] == [], res["changed"])

    # ── 2. Forge：记录漂移（写着 1.19.2 原版）──
    fr = ac("fr", game_version="1.19.2", loader="vanilla")
    add_version(fr, "1.20.1-forge-47.2.0", {
        "id": "1.20.1-forge-47.2.0",
        "inheritsFrom": "1.20.1",
        "libraries": [{"name": "net.minecraftforge:forge:1.20.1-47.2.0"}],
    })
    res = reconstruct(fr)
    check("Forge 重构 game_version", fr.game_version == "1.20.1", fr.game_version)
    check("Forge 重构 loader", fr.loader == "forge", fr.loader)
    check("Forge 重构 loader_version", fr.loader_version == "47.2.0",
          fr.loader_version)
    check("Forge 重构 version_id", fr.version_id == "1.20.1-forge-47.2.0",
          fr.version_id)
    check("Forge changed 含 4 个字段", set(res["changed"]) == {
        "game_version", "loader", "loader_version", "version_id"},
        res["changed"])

    # ── 3. Fabric：从 id 精确提取加载器版本 ──
    fb = ac("fb", loader="fabric")
    add_version(fb, "1.20.1", {"id": "1.20.1"})
    add_version(fb, "fabric-loader-0.15.11-1.20.1", {
        "id": "fabric-loader-0.15.11-1.20.1",
        "inheritsFrom": "1.20.1",
        "libraries": [{"name": "net.fabricmc:fabric-loader:0.15.11"}],
    })
    res = reconstruct(fb)
    check("Fabric 优先于同目录原版 json", fb.version_id == "fabric-loader-0.15.11-1.20.1",
          fb.version_id)
    check("Fabric loader_version", fb.loader_version == "0.15.11",
          fb.loader_version)

    # ── 4. NeoForge：id 不含 MC 版本，靠 inheritsFrom ──
    neo = ac("neo", game_version="1.20.1", loader="neoforge")
    add_version(neo, "neoforge-21.1.0", {
        "id": "neoforge-21.1.0",
        "inheritsFrom": "1.21.1",
        "libraries": [{"name": "net.neoforged:neoforge:21.1.0"}],
    })
    res = reconstruct(neo)
    check("NeoForge game_version 取 inheritsFrom", neo.game_version == "1.21.1",
          neo.game_version)
    check("NeoForge loader", neo.loader == "neoforge", neo.loader)
    check("NeoForge loader_version", neo.loader_version == "21.1.0",
          neo.loader_version)
    check("NeoForge 不会被误判成 forge", infer_loader("neoforge-21.1.0") == "neoforge")

    # ── 5. 无版本文件 ──
    empty = ac("empty")
    res = reconstruct(empty)
    check("无版本文件 ok=False", res["ok"] is False)
    check("无版本文件 reason", res["reason"] == "instances.rebuild_no_files",
          res["reason"])

    # ── 6. 格式残留清回自适应 ──
    stale = ac("stale", format="curseforge")
    add_version(stale, "1.20.1", {"id": "1.20.1"})
    res = reconstruct(stale)
    check("残留格式清空", stale.format == "", stale.format)
    check("changed 含 format", "format" in res["changed"], res["changed"])

    # ── 7. 外部版本隔离（扁平 json）──
    mc = os.path.join(TMP, "iso_mc")
    base = os.path.join(mc, "versions", "1.20.1-forge")
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "1.20.1-forge.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "id": "1.20.1-forge",
            "inheritsFrom": "1.20.1",
            "libraries": [{"name": "net.minecraftforge:forge:1.20.1-47.4.0"}],
        }, fh)
    iso = Instance(id="iso", name="iso", game_version="1.20.1",
                   loader="forge", external=True, _base=base)
    res = reconstruct(iso)
    check("隔离布局重构 ok", res["ok"] is True)
    check("隔离布局 version_id", iso.version_id == "1.20.1-forge", iso.version_id)
    check("隔离布局 loader_version", iso.loader_version == "47.4.0",
          iso.loader_version)
    check("隔离布局保留 external", iso.external is True)

    # ── 8. 解析辅助函数 ──
    check("infer forge", infer_loader("1.20.1-forge-47.2.0") == "forge")
    check("infer legacyfabric 优先",
          infer_loader("legacyfabric-loader-0.16.0-1.8.9") == "legacyfabric")
    check("infer cleanroom", infer_loader("Cleanroom-0.7.12-alpha") == "cleanroom")
    check("loader_version forge",
          loader_version_of("forge", "1.20.1-forge-47.2.0", (), "1.20.1") == "47.2.0")
    check("loader_version fabric",
          loader_version_of("fabric", "fabric-loader-0.15.11-1.20.1",
                            (), "1.20.1") == "0.15.11")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
    shutil.rmtree(_FIXED_DATA, ignore_errors=True)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("ALL CHECKS PASSED")
