# -*- coding: utf-8 -*-
"""round-179：AC 专属布局标识 + 启动格式自动查验的行为判据。"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import instances, settings_dialog  # noqa: E402
from src.core import instance_marker as im  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         (" | " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)


ORIG_DATA = instances.get_data_dir
ORIG_CFG = settings_dialog.load_config
CFG = {"verify_layout_integrity": True, "version_isolation": "default"}
settings_dialog.load_config = lambda: dict(CFG)


def make_inst(td, iid="x", fmt="", base=""):
    return instances.Instance(
        id=iid, name="demo", game_version="1.20.1", format=fmt,
        _base=base)


try:
    with tempfile.TemporaryDirectory() as td:
        instances.get_data_dir = lambda: td
        inst = make_inst(td)
        mc = inst.mc_dir
        os.makedirs(mc, exist_ok=True)

        # ── 1. 标识文件位置与基本形状 ──────────────────────────────
        check("标识写在 mc_dir 内且点开头",
              os.path.basename(im.marker_path(inst)) == ".ac-layout.json"
              and im.marker_path(inst).startswith(mc))
        paths = {
            "install_dir": mc, "versions_root": mc,
            "mods_dir": os.path.join(mc, "mods"),
            "saves_dir": os.path.join(mc, "saves"),
            "assets_dir": os.path.join(mc, "assets"),
            "libraries_dir": os.path.join(mc, "libraries"),
        }
        check("write 成功且落盘", im.write(inst, "ac", paths, "high"))
        with open(im.marker_path(inst), encoding="utf-8") as f:
            raw = json.load(f)
        check("schema / fmt / confidence / 路径映射齐全",
              raw.get("schema") == 1 and raw.get("fmt") == "ac"
              and raw.get("confidence") == "high"
              and set(raw.get("paths", {})) == set(im.PATH_KEYS))
        check("原子写不留 .tmp", not os.path.exists(im.marker_path(inst) + ".tmp"))

        # ── 2. read 命中和各类降级 ──────────────────────────────────
        got = im.read(inst)
        check("read 命中且给出绝对路径", bool(got) and
              got["abs_paths"]["install_dir"] == os.path.normpath(mc))
        os.makedirs(os.path.join(mc, "versions"), exist_ok=True)
        check("目录结构变化 → 指纹失效并降级", im.read(inst) is None)
        im.write(inst, "ac", paths, "high")
        bad = json.loads(json.dumps(raw))
        bad["confidence"] = "low"
        with open(im.marker_path(inst), "w", encoding="utf-8") as f:
            json.dump(bad, f)
        check("低置信度标识不被采信", im.read(inst) is None)
        with open(im.marker_path(inst), "w", encoding="utf-8") as f:
            f.write("{ broken json")
        check("损坏标识静默降级", im.read(inst) is None)
        os.remove(im.marker_path(inst))
        check("低置信度不落盘", not im.write(inst, "vanilla", paths, "low"))

        # ── 3. 路径安全 ─────────────────────────────────────────────
        check("绝对路径被拒", not im._safe_rel(r"C:\Windows"))
        check("盘符相对形式被拒", not im._safe_rel("C:evil"))
        check("过度上跳被拒", not im._safe_rel("../../../.."))
        check("flat 布局两级上跳允许", im._safe_rel("../.."))
        check("点表示 mc_dir 本身允许", im._safe_rel("."))

        # ── 4. verify 查漏补缺只读 ──────────────────────────────────
        v = im.verify(paths)
        check("verify 报告缺失目录且不擅自创建",
              not v["ok"] and "saves_dir" in v["missing"]
              and not os.path.isdir(paths["saves_dir"]))

        # ── 5. detect_format：AC 自有也要自动查验 ────────────────────
        fmt = instances.detect_format(inst)
        check("标准 AC 自建实例仍识别为 ac", fmt == "ac", fmt)
        check("探测后自动补写识别码", os.path.isfile(im.marker_path(inst)))

        # 同一个 AC 自有目录里塞进别的启动器特征 → 不能被按 ac 补
        with tempfile.TemporaryDirectory() as td2:
            instances.get_data_dir = lambda: td2
            inst2 = make_inst(td2, "y")
            mc2 = inst2.mc_dir
            os.makedirs(mc2, exist_ok=True)
            open(os.path.join(mc2, "mmc-pack.json"), "w").close()
            fmt2 = instances.detect_format(inst2)
            check("AC 目录里出现 mmc-pack.json → 自动查验判为 multimc",
                  fmt2 == "multimc", fmt2)
            lay = instances.layout_of(inst2)
            check("layout_of 不再对此外来实例返回 ac",
                  lay["format"] == "multimc", str(lay["format"]))

        # ── 6. layout_of 采用标识里的路径映射 ───────────────────────
        instances.get_data_dir = lambda: td
        up = os.path.dirname(os.path.dirname(os.path.normpath(mc)))
        custom_paths = dict(paths, install_dir=up, versions_root=up)
        im.write(inst, "iso", custom_paths, "high", flat=True)
        lay = instances.layout_of(inst)
        check("layout_of 命中标识 → 用记录的路径",
              os.path.normpath(lay["install_dir"]) == os.path.normpath(up)
              and lay["from_marker"] is True, str(lay["install_dir"]))
        check("layout_of 保持原 5 键契约", all(
            k in lay for k in ("format", "version", "flat",
                               "install_dir", "versions_root")))
        check("标识存在时不重复探测（from_marker）",
              lay["from_marker"] is True)
        os.remove(im.marker_path(inst))

        # ── 7. 关闭查验 → 不读写标识 ────────────────────────────────
        CFG["verify_layout_integrity"] = False
        instances.detect_format(inst)
        check("关闭查验完整性 → 不写标识",
              not os.path.exists(im.marker_path(inst)))
        CFG["verify_layout_integrity"] = True

        # ── 8. add() 不再丢弃向导里选的格式 ─────────────────────────
        with tempfile.TemporaryDirectory() as td3:
            instances.get_data_dir = lambda: td3
            mgr = instances.InstancesManager()
            got = mgr.add("demo", "1.20.1", format="iso")
            check("AC 自有布局下 add() 保留 format",
                  got.format == "iso", repr(got.format))

        # ── 9. 标识不能被当成版本 json（实例重构 / 其它扫描） ───────
        from src.core import instance_rebuild
        instances.get_data_dir = lambda: td
        inst3 = make_inst(td, "z")
        mc3 = inst3.mc_dir
        os.makedirs(os.path.join(mc3, "versions"), exist_ok=True)
        im.write(inst3, "ac", dict(paths, install_dir=mc3,
                                   versions_root=mc3), "high")
        res = instance_rebuild.reconstruct(inst3)
        check("标识文件不会被误当版本 json（无版本文件仍报 no_files）",
              res["ok"] is False
              and res["reason"] == "instances.rebuild_no_files",
              str(res))

        # ── 10. 只有 AC 认：探测函数的常量表里没有标识文件名 ────────
        consts = [str(c) for c in
                  instances._probe_format.__code__.co_consts]
        check("_probe_format 不把 AC 标识当外来特征",
              not any("ac-layout" in c for c in consts))
        check("标识文件名是点开头的未知 JSON（其它启动器会忽略）",
              im.MARKER_NAME.startswith(".")
              and im.MARKER_NAME.endswith(".json"))
finally:
    instances.get_data_dir = ORIG_DATA
    settings_dialog.load_config = ORIG_CFG

print("RESULT:", "PASS" if not FAILS else "FAIL %d: %r" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
