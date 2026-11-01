"""round-163 回归测试：Java 计划（java_plan）、加载器已安装判定与强制开关。

覆盖：
  1. detect_format：磁盘布局压过导入时留下的 stale format
  2. find_installed_loader：Cleanroom / Forge / NeoForge 的版本目录识别（不误吞）
  3. required_java_major_for：Cleanroom → 25，1.20.1 Forge → 17
  4. java_plan：自动选择 / 无兼容 Java / 实例强制 / 全局强制 / 手动不兼容
  5. instance_health.apply_fix：set_java_force / clear_java_force 的写字段与幂等
"""
import os
import shutil
import sys
import tempfile

# tests/ 下运行：仓库根 = tests 的上一级
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AC_DEV_TEMP"] = "1"  # 不污染真实 data 目录

import src.instances as _inst_mod  # noqa: E402

# AC_DEV_TEMP=1 下 get_data_dir() 每次调用都新建临时目录 → Instance.root
# 会漂移。这里打桩成固定目录（只影响本次测试进程）。
_DATA = os.path.join(tempfile.gettempdir(), "ac_java_plan_data")
shutil.rmtree(_DATA, ignore_errors=True)
os.makedirs(_DATA, exist_ok=True)
_inst_mod.get_data_dir = lambda: _DATA

from src.instances import Instance, detect_format  # noqa: E402
from src.core.install import find_installed_loader  # noqa: E402
from src.core.java import (java_plan, required_java_major_for,  # noqa: E402
                           reset_scan_cache)
import src.core.java as _java_mod  # noqa: E402
from src.core.instance_health import apply_fix  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(payload)


TMP = tempfile.mkdtemp(prefix="ac_java_plan_")
try:
    # ── 1. detect_format：磁盘布局压过 stale format ──
    ac_id = "ac1"
    ac_json = os.path.join(_DATA, "instances", ac_id, ".minecraft",
                           "versions", "1.20.1", "1.20.1.json")
    write_json(ac_json, "{}")
    ac = Instance(id=ac_id, name="ac", game_version="1.20.1",
                  format="curseforge", _base="")
    got = detect_format(ac)
    check("AC 自有布局压过 stale curseforge", got == "ac", got)

    # 外来版本隔离：_base 就是 versions/<id>，<id>.json 扁平躺着
    iso_id = "1.20.1-iso"
    iso_dir = os.path.join(TMP, "iso_versions", iso_id)
    write_json(os.path.join(iso_dir, f"{iso_id}.json"), "{}")
    iso = Instance(id="iso1", name="iso", game_version="1.20.1",
                   version_id=iso_id, format="", _base=iso_dir)
    got = detect_format(iso)
    check("外来版本隔离识别为非 ac", got == "iso" and got != "ac", got)

    # ── 2. find_installed_loader ──
    mc_a = os.path.join(TMP, "mc_a")
    vdir = os.path.join(mc_a, "versions", "1.12.2-cleanroom")
    write_json(os.path.join(vdir, "1.12.2-cleanroom.json"),
               '{"inheritsFrom": "1.12.2"}')
    hit = find_installed_loader(mc_a, "cleanroom", "1.12.2")
    check("Cleanroom 命中版本目录", hit == "1.12.2-cleanroom", str(hit))

    mc_b = os.path.join(TMP, "mc_b")
    for name in ("1.20.1-forge-47.4.0", "1.20.1-neoforge-21.1.0"):
        write_json(os.path.join(mc_b, "versions", name, f"{name}.json"),
                   '{"inheritsFrom": "1.20.1"}')
    forge_hit = find_installed_loader(mc_b, "forge", "1.20.1")
    neo_hit = find_installed_loader(mc_b, "neoforge", "1.20.1")
    check("Forge 只命中 forge 目录",
          forge_hit == "1.20.1-forge-47.4.0" and "neoforge" not in (forge_hit or ""),
          str(forge_hit))
    check("NeoForge 命中 neoforge 目录",
          neo_hit == "1.20.1-neoforge-21.1.0", str(neo_hit))

    # ── 3. required_java_major_for ──
    check("Cleanroom 1.12.2 → Java 25",
          required_java_major_for("1.12.2", "cleanroom") == 25,
          str(required_java_major_for("1.12.2", "cleanroom")))
    check("1.20.1 Forge → Java 17",
          required_java_major_for("1.20.1", "forge") == 17,
          str(required_java_major_for("1.20.1", "forge")))

    # ── 4. java_plan（打桩 scan_javas，绝不触真实扫描）──
    JAVAS = [
        {"path": "C:/j8/java.exe", "major": 8},
        {"path": "C:/j17/java.exe", "major": 17},
        {"path": "C:/j21/java.exe", "major": 21},
        {"path": "C:/j24/java.exe", "major": 24},
        {"path": "C:/j26/java.exe", "major": 26},
    ]

    def _fake_scan(*_a, **_kw):
        return list(JAVAS)

    _REAL_SCAN = _java_mod.scan_javas
    _java_mod.scan_javas = _fake_scan
    reset_scan_cache()

    def plan_inst(**kw):
        kw.setdefault("id", "jp")
        kw.setdefault("name", "jp")
        kw.setdefault("_base", os.path.join(TMP, "jp_mc"))
        return Instance(**kw)

    # 4a. 自动选择：1.20.1 + forge（need 17）→ 精确命中 j17
    p = java_plan(plan_inst(game_version="1.20.1", loader="forge"),
                  {"java_auto": True})
    check("自动选择 1.20.1 Forge → Java 17",
          p["path"] == "C:/j17/java.exe" and p["compatible"] is True
          and p["major"] == 17, "%s / %s" % (p["path"], p["compatible"]))

    # 4b. Cleanroom 需要 Java 25，已装列表里没有 25 → 无可用（路径为空）
    cr = plan_inst(game_version="1.12.2", loader="cleanroom")
    p = java_plan(cr, {"java_auto": True})
    check("Cleanroom 无 Java 25 → 路径为空",
          p["path"] == "" and p["compatible"] is False
          and p["need"] == 25, "%r / %s" % (p["path"], p["compatible"]))
    check("无可用时 detected 非空且 ≤5",
          0 < len(p["detected"]) <= 5, str(len(p["detected"])))

    # 4c. 实例级强制 → 不兼容也标记 forced
    cr.java_force = True
    p = java_plan(cr, {"java_auto": True})
    check("实例 java_force → forced", p["forced"] is True, str(p["forced"]))
    cr.java_force = False

    # 4d. 全局强制
    p = java_plan(cr, {"java_auto": True, "java_force_incompatible": True})
    check("全局 java_force_incompatible → forced",
          p["forced"] is True, str(p["forced"]))

    # 4e. 手动 Java 26 跑 1.12.2 原版（need 8）→ 不兼容且未强制
    man = plan_inst(game_version="1.12.2", loader="vanilla",
                    java_path="C:/j26/java.exe")
    p = java_plan(man, {"java_auto": False})
    check("手动 Java 26 跑 1.12.2 → 不兼容、未强制",
          p["path"] == "C:/j26/java.exe" and p["major"] == 26
          and p["compatible"] is False and p["forced"] is False,
          "%s / %s / %s" % (p["major"], p["compatible"], p["forced"]))

    # ── 5. apply_fix：强制开关 ──
    fx = plan_inst(game_version="1.12.2", loader="cleanroom")
    ok = apply_fix(fx, {"action": "set_java_force",
                        "params": {"path": "C:/j26/java.exe"}})
    check("set_java_force 写入路径并置位",
          ok is True and fx.java_path == "C:/j26/java.exe"
          and fx.java_force is True,
          "%s / %s" % (fx.java_path, fx.java_force))
    check("set_java_force 重复调用返回 False",
          apply_fix(fx, {"action": "set_java_force",
                         "params": {"path": "C:/j26/java.exe"}}) is False)
    check("clear_java_force 首次返回 True",
          apply_fix(fx, {"action": "clear_java_force"}) is True)
    check("clear_java_force 再次返回 False",
          apply_fix(fx, {"action": "clear_java_force"}) is False)
finally:
    if "_REAL_SCAN" in dir():
        _java_mod.scan_javas = _REAL_SCAN
    shutil.rmtree(TMP, ignore_errors=True)
    shutil.rmtree(_DATA, ignore_errors=True)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("ALL CHECKS PASSED")
