# -*- coding: utf-8 -*-
"""round-201：mod id ↔ Modrinth slug 别名（cloth-config2 能识别、能补装）。

背景：Cloth Config 的 jar 里 mod id 是 ``cloth-config2``，Modrinth 项目 slug
是 ``cloth-config``。旧逻辑拿 dep id 搜索再要求 slug/title 完全相等，
「补装缺失依赖」恒报「未在 Modrinth 找到同名项目」；按 id 字符串判「已装」
也会把已装的 Cloth Config 误报成缺。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import crash_analysis, i18n, net_api  # noqa: E402
from src.core import mod_check, mod_repair  # noqa: E402

FAILS: list[str] = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         (" | " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def fabric_jar(path, mod_id, depends=None, provides=None):
    """写一个最小可解析的 Fabric jar（只带 fabric.mod.json）。"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("fabric.mod.json", json.dumps({
            "id": mod_id, "version": "1.0.0",
            "depends": depends or {}, "provides": provides or [],
        }))
    return path


def make_inst(td):
    return types.SimpleNamespace(mods_dir=td, game_version="1.20.1",
                                 loader="fabric")


# ── 1. mod id → 项目 slug 归一 ──────────────────────────────────────
check("cloth-config2 归一为 Modrinth slug cloth-config",
      mod_repair.canonical_id("cloth-config2") == "cloth-config")
check("下划线写法 cloth_config2 同样归一",
      mod_repair.canonical_id("cloth_config2") == "cloth-config")
check("architectury 归一为 architectury-api",
      mod_repair.canonical_id("Architectury") == "architectury-api")
check("未知 id 只归一化，不猜项目",
      mod_repair.canonical_id("Some_Mod") == "some-mod")

# ── 2. 精确匹配仍拒绝模糊命中 ───────────────────────────────────────
check("别名项目可精确命中",
      mod_repair.match_project("cloth-config2", [
          {"slug": "cloth-config", "title": "Cloth Config API",
           "project_id": "CC"}])["project_id"] == "CC")
check("仍拒绝同前缀项目（cloth-config2-extra）",
      mod_repair.match_project("cloth-config2", [
          {"slug": "cloth-config2-extra", "project_id": "X"}]) is None)
check("不相关项目不命中",
      mod_repair.match_project("cloth-config2", [
          {"slug": "sodium", "project_id": "Y"}]) is None)

# ── 3. 补装：按项目 slug 搜索并下载 ─────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    inst = make_inst(td)
    queries, calls = [], []
    orig_s, orig_d = net_api.search_mods, net_api.download_mod_to
    try:
        def fake_search(q, *a, **k):
            queries.append(q)
            return [{"slug": "cloth-config", "title": "Cloth Config API",
                     "project_id": "CC"}]

        def fake_dl(pid, dest, *a, **k):
            calls.append((pid, a[:2]))
            return os.path.join(dest, "cloth-config-11.1.106.jar")

        net_api.search_mods = fake_search
        net_api.download_mod_to = fake_dl
        r = mod_repair.repair_missing(inst, ["cloth-config2"])
    finally:
        net_api.search_mods, net_api.download_mod_to = orig_s, orig_d
    check("补装按项目 slug 搜索（不是 mod id）",
          queries == ["cloth-config"], str(queries))
    check("cloth-config2 成功补装并下载项目本体",
          r["downloaded"] == ["cloth-config-11.1.106.jar"]
          and not r["failed"], "result=%r" % r)
    check("下载仍带实例 MC 版本 / 加载器",
          calls and calls[0][1] == ("1.20.1", "fabric"), str(calls[:1]))

# ── 4. 已装判定：mod id 与 dep id 不同也要认 ─────────────────────────
with tempfile.TemporaryDirectory() as td:
    inst = make_inst(td)
    fabric_jar(os.path.join(td, "cloth-config.jar"), "cloth-config2")
    fabric_jar(os.path.join(td, "some-mod.jar"), "some-mod",
               depends={"cloth-config": ">=8.0", "fabric-api": "*"})
    miss = crash_analysis.find_missing_dependencies(inst)
    check("装了 cloth-config2 后不再误报缺 cloth-config",
          "cloth-config" not in miss, str(miss))
    check("真正缺的依赖仍然报出来", miss == ["fabric-api"], str(miss))

# ── 5. provides 计入「已装」 ─────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    inst = make_inst(td)
    fabric_jar(os.path.join(td, "renamed.jar"), "renamed-config-lib",
               provides=["cloth-config2"])
    fabric_jar(os.path.join(td, "some-mod.jar"), "some-mod",
               depends={"cloth-config2": ">=8.0"})
    miss = crash_analysis.find_missing_dependencies(inst)
    check("jar 声明的 provides 计入已装", miss == [], str(miss))

# ── 6. 启动前预检（mod_check）同一套判据 ────────────────────────────
with tempfile.TemporaryDirectory() as td:
    inst = make_inst(td)
    fabric_jar(os.path.join(td, "some-mod.jar"), "some-mod",
               depends={"cloth-config2": ">=8.0"})
    scan = mod_repair.scan_missing(inst)
    check("scan_missing 直接给出可补装的规范 id",
          scan["missing"] == ["cloth-config"], str(scan["missing"]))
    r = mod_check.scan_conflicts(inst)
    miss = [f for f in r["findings"] if f.kind == "missing_dep"]
    check("预检：真缺时报缺，提示用能搜到的规范名",
          len(miss) == 1 and miss[0].meta["dep"] == "cloth-config"
          and miss[0].meta["dep_raw"] == "cloth-config2",
          str(miss[0].meta if miss else None))

    fabric_jar(os.path.join(td, "cloth-config.jar"), "cloth-config2",
               provides=["cloth-config"])
    r2 = mod_check.scan_conflicts(inst)
    miss2 = [f for f in r2["findings"] if f.kind == "missing_dep"]
    dup = [f for f in r2["findings"] if f.kind == "duplicate_id"]
    check("预检：装了 Cloth Config 后不再报缺（id/provides 互通）",
          miss2 == [], str([f.meta for f in miss2]))
    check("同一 jar 的 id/provides 归一后不误报重复",
          dup == [], str([f.meta for f in dup]))

# ── 7. 静态接线判据 ─────────────────────────────────────────────────
ca = read("src/crash_analysis.py")
mr = read("src/core/mod_repair.py")
mc = read("src/core/mod_check.py")
en = read("src/core/enhance.py")
check("崩溃/依赖清单解析读出 Fabric provides",
      'data.get("provides")' in ca and '"provides": provides' in ca)
check("缺失依赖按 canonical id 比较", "canonical_id" in ca)
check("补装搜索用 canonical（query = canonical_id(dep)）",
      "query = canonical_id(dep)" in mr)
check("启动前预检按 canonical 比较并收 provides",
      "canonical_id(dep)" in mc and 'data.get("provides")' in mc
      and "provides=provides" in mc)
check("增强包把 cloth-config2 认作 Cloth Config",
      '"cloth-config2"' in en)

# ── 8. 中英文案仍对称（本轮不新增键） ──────────────────────────────
zh, en_us = i18n._STRINGS["zh-CN"], i18n._STRINGS["en-US"]
check("round-201 未新增文案，中英键集合仍对称",
      len(zh) == len(en_us) and not (set(zh) ^ set(en_us)),
      "zh=%d en=%d" % (len(zh), len(en_us)))

print("RESULT:", "PASS" if not FAILS else "FAIL %d: %r" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
