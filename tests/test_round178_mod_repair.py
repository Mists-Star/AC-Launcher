# -*- coding: utf-8 -*-
"""round-178 C/D 组：模组依赖扫描/补装的统一能力与 UI 终态判据。"""
from __future__ import annotations

import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import crash_analysis, i18n, net_api  # noqa: E402
from src.core import mod_repair  # noqa: E402

FAILS: list[str] = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         (" | " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


# ── 1. scan_missing：不把「跳过」误报成「齐全」 ─────────────────────
with tempfile.TemporaryDirectory() as td:
    inst = types.SimpleNamespace(mods_dir=td, game_version="1.20.1",
                                 loader="fabric")
    r = mod_repair.scan_missing(inst)
    check("空 mods 目录 → 依赖齐全且不跳过",
          r["missing"] == [] and not r["skipped"])
    for i in range(mod_repair.MAX_SCAN_JARS + 1):
        open(os.path.join(td, "m%03d.jar" % i), "wb").close()
    r2 = mod_repair.scan_missing(inst)
    check("jar 超上限 → skipped=True", r2["skipped"])
    check("跳过时明确说「已跳过」且声明不代表齐全",
          "跳过" in r2["message"] and "不代表依赖齐全" in r2["message"],
          r2["message"])

# ── 2. match_project：拒绝模糊命中 ──────────────────────────────────
check("slug 完全相等命中",
      mod_repair.match_project("fabric-api", [
          {"slug": "fabric-api", "project_id": "P"}])["project_id"] == "P")
check("title 完全相等命中",
      mod_repair.match_project("fabric-api", [
          {"slug": "x", "title": "Fabric API", "project_id": "Q"}])["project_id"] == "Q")
check("不做 startswith 宽松匹配（避免误装同前缀项目）",
      mod_repair.match_project("fabric", [
          {"slug": "fabric-api", "project_id": "R"}]) is None)
check("fabric-api 不再误命中 fabric-api-base",
      mod_repair.match_project("fabric-api", [
          {"slug": "fabric-api-base", "project_id": "S"}]) is None)
check("完全无关项目不命中",
      mod_repair.match_project("some-dep", [
          {"slug": "totally-unrelated", "project_id": "T"}]) is None)

# ── 3. repair_missing：分阶段失败 + 成功 ────────────────────────────
with tempfile.TemporaryDirectory() as td:
    inst = types.SimpleNamespace(mods_dir=td, game_version="1.20.1",
                                 loader="fabric")
    orig_s, orig_d = net_api.search_mods, net_api.download_mod_to
    try:
        # search 阶段失败
        def boom(*a, **k):
            raise RuntimeError("offline")

        net_api.search_mods = boom
        r = mod_repair.repair_missing(inst, ["dep-a"])
        check("搜索失败 → stage=search 且带原因",
              r["failed"] and r["failed"][0]["stage"] == "search"
              and "offline" in r["failed"][0]["reason"])

        # match 阶段失败
        net_api.search_mods = lambda *a, **k: [
            {"slug": "unrelated", "project_id": "X"}]
        r = mod_repair.repair_missing(inst, ["dep-b"])
        check("无精确命中 → stage=match，不下载无关模组",
              r["failed"][0]["stage"] == "match" and not r["downloaded"])

        # download 阶段失败
        net_api.search_mods = lambda *a, **k: [
            {"slug": "dep-c", "project_id": "C"}]

        def dl_fail(*a, **k):
            raise net_api.NetError("403")

        net_api.download_mod_to = dl_fail
        r = mod_repair.repair_missing(inst, ["dep-c"])
        check("下载失败 → stage=download",
              r["failed"][0]["stage"] == "download"
              and "403" in r["failed"][0]["reason"])

        # 成功 + 版本 / 加载器透传
        calls = []
        net_api.search_mods = lambda *a, **k: [
            {"slug": "dep-d", "project_id": "C"}]

        def dl_ok(project_id, dest, *a, **k):
            calls.append((project_id, dest, a))
            return os.path.join(dest, "dep-d.jar")

        net_api.download_mod_to = dl_ok
        r = mod_repair.repair_missing(inst, ["dep-d"])
        check("精确命中 → 下载成功并计入 downloaded",
              r["downloaded"] == ["dep-d.jar"] and not r["failed"],
              "result=%r" % r)
        check("补装带实例 MC 版本 / 加载器",
              calls and calls[0][2][:2] == ("1.20.1", "fabric"),
              str(calls[:1]))
        check("结果带人读终态", "已补装 1 个依赖" in r["message"],
              r["message"])
    finally:
        net_api.search_mods, net_api.download_mod_to = orig_s, orig_d

# ── 4. failed_lines 可读 ────────────────────────────────────────────
lines = mod_repair.failed_lines({"failed": [
    {"id": "x", "stage": "match", "reason": "no hit"}]})
check("失败明细含 id / 阶段 / 原因",
      len(lines) == 1 and "x" in lines[0] and "未找到匹配项目" in lines[0])

# ── 5. 旧入口保持兼容 ───────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    inst = types.SimpleNamespace(mods_dir=td, game_version="1.20.1",
                                 loader="fabric")
    orig_s, orig_d = net_api.search_mods, net_api.download_mod_to
    net_api.search_mods = lambda *a, **k: []
    net_api.download_mod_to = lambda *a, **k: ""
    try:
        ok, bad = crash_analysis.search_and_download_missing(inst, ["z"])
    finally:
        net_api.search_mods, net_api.download_mod_to = orig_s, orig_d
    check("crash_analysis 旧签名仍返回 (list, list)",
          isinstance(ok, list) and bad == ["z"], "bad=%r" % bad)

# ── 6. UI 接线静态判据 ──────────────────────────────────────────────
cd = read("src/crash_dialog.py")
pi = read("src/pages_instances.py")
check("崩溃弹窗一键修复有汇总终态（不再只调 deps）",
      "crash.repair_all_note" in cd and "_repair_all" in cd
      and "for k in (\"java_version\", \"out_of_memory\"" in cd)
check("崩溃弹窗跳过扫描时给明确提示",
      "crash.deps_skipped" in cd and "mod_repair.scan_missing" in cd)
check("崩溃弹窗失败明细用结构化阶段",
      "failed_lines(result)" in cd)
check("实例右键新增「补装缺失依赖」入口",
      "instances.repair_deps" in pi and "def _repair_mod_deps" in pi)
check("右键入口走统一模块",
      "Worker(mod_repair.repair_missing, inst)" in pi)

zh, en = i18n._STRINGS["zh-CN"], i18n._STRINGS["en-US"]
new_keys = {"crash.deps_skipped", "crash.repair_all_note",
            "instances.repair_deps", "instances.repair_deps_result"}
check("4 个新文案中英都有且键数一致",
      len(zh) == len(en) and not (set(zh) ^ set(en))
      and new_keys <= set(zh), "zh=%d en=%d" % (len(zh), len(en)))

print("RESULT:", "PASS" if not FAILS else "FAIL %d: %r" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
