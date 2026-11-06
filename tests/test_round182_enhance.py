"""round-182 回归测试：客户端增强包（一键装 / 卸客户端 mod）。

覆盖：
  1. CATALOG 完整性：slug 唯一、分组合法、每条的中英文案键都真实存在。
  2. 加载器候选链：vanilla / optifine / liteloader 装不了；quilt 可以退
     fabric；neoforge **不能**拿 forge 顶替（1.20.2 后已分家）。
  3. 记录文件：缺失 / 坏 JSON / schema 不符一律当空表；写入原子、不留 .tmp。
  4. 已装识别三层：记录主文件 → mod id 兜底 → 未装。
  5. ☠ 卸载只删自己的主文件，自动带上的前置库必须保留。
  6. resolve_status 状态机：可用 / 没这个版本 / 加载器不支持 / 没构建 /
     单条目查不到网络时降级为 unreachable 且不影响其它条目。
  7. i18n 中英键集合对齐（新增键两边都要有）。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import types
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AC_DEV_TEMP"] = "1"

import src.core.enhance as EH  # noqa: E402
import src.net_api as net_api  # noqa: E402
from src.i18n import _STRINGS  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


ZH = _STRINGS["zh-CN"]
EN = _STRINGS[[k for k in _STRINGS if k != "zh-CN"][0]]


class FakeInst:
    def __init__(self, root, mc="1.20.1", loader="fabric"):
        self._root = root
        self.game_version = mc
        self.loader = loader
        self.name = "t"
        self.id = "t1"

    @property
    def mc_dir(self):
        return self._root

    @property
    def mods_dir(self):
        return os.path.join(self._root, "mods")


def make_jar(path, mod_id, loader="fabric"):
    """造一个能被 _manifest_from_zip 解析的最小 mod jar。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        if loader == "fabric":
            z.writestr("fabric.mod.json",
                       json.dumps({"id": mod_id, "name": mod_id,
                                   "version": "1.0"}))
        else:
            z.writestr("META-INF/mods.toml",
                       'modLoader="javafml"\n[[mods]]\nmodId="%s"\n'
                       'version="1.0"\ndisplayName="%s"\n'
                       % (mod_id, mod_id))


# ── 1. CATALOG ────────────────────────────────────────────────────
print("\n[1] CATALOG 完整性")
slugs = [it.slug for it in EH.CATALOG]
check("slug 全部唯一", len(slugs) == len(set(slugs)), f"n={len(slugs)}")
check("分组都在 GROUP_ORDER 内",
      all(it.group in EH.GROUP_ORDER for it in EH.CATALOG))
check("鼠标手势条目在列（用户诉求本体）",
      "mouse-tweaks" in slugs)
check("名称非空", all(it.name.strip() for it in EH.CATALOG))
missing_desc = [it.desc_key for it in EH.CATALOG
                if f"enhance.desc.{it.desc_key}" not in ZH
                or f"enhance.desc.{it.desc_key}" not in EN]
check("每条都有中英描述", not missing_desc, str(missing_desc))
check("extra_key 都有中英文案",
      all(f"enhance.extra.{it.extra_key}" in ZH and
          f"enhance.extra.{it.extra_key}" in EN
          for it in EH.CATALOG if it.extra_key))

# ── 2. 加载器候选链 ────────────────────────────────────────────────
print("\n[2] 加载器候选链")


def chain_of(loader):
    tmp = tempfile.mkdtemp(prefix="ac_e2_")
    try:
        return EH.loader_chain(FakeInst(tmp, loader=loader))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


for ldr in ("vanilla", "optifine", "liteloader"):
    check(f"{ldr} 装不了客户端 mod", chain_of(ldr) == (), str(chain_of(ldr)))
check("quilt 退 fabric", chain_of("quilt") == ("quilt", "fabric"),
      str(chain_of("quilt")))
check("fabric 只走 fabric", chain_of("fabric") == ("fabric",))
check("forge 只走 forge", chain_of("forge") == ("forge",))
check("neoforge 不拿 forge 顶替", chain_of("neoforge") == ("neoforge",),
      str(chain_of("neoforge")))
check("cleanroom 走 forge", chain_of("cleanroom") == ("forge",))
check("legacyfabric 退 fabric",
      chain_of("legacyfabric") == ("legacyfabric", "fabric"))

# ── 3. 记录文件 ────────────────────────────────────────────────────
print("\n[3] 记录文件读写")
tmp = tempfile.mkdtemp(prefix="ac_e3_")
try:
    inst = FakeInst(tmp)
    check("没有文件 → 空表", EH.load_record(inst) == {})
    EH.save_record(inst, {"mouse-tweaks": {"primary": "a.jar"}})
    check("写完能读回", EH.load_record(inst).get("mouse-tweaks", {})
          .get("primary") == "a.jar")
    check("不留 .tmp", not os.path.exists(EH.record_path(inst) + ".tmp"))
    with open(EH.record_path(inst), "w", encoding="utf-8") as f:
        f.write("{not json")
    check("坏 JSON → 空表", EH.load_record(inst) == {})
    with open(EH.record_path(inst), "w", encoding="utf-8") as f:
        f.write(json.dumps({"schema": 999, "items": {"x": {}}}))
    check("schema 不符 → 空表", EH.load_record(inst) == {})
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ── 4. 已装识别三层 ────────────────────────────────────────────────
print("\n[4] 已装识别")
tmp = tempfile.mkdtemp(prefix="ac_e4_")
try:
    inst = FakeInst(tmp)
    mw = EH._BY_SLUG["mouse-tweaks"]
    os.makedirs(inst.mods_dir, exist_ok=True)
    make_jar(os.path.join(inst.mods_dir, "MouseTweaks-2.24.jar"), "mousetweaks")
    check("无记录 → 靠 mod id 认出",
          EH.installed_files(inst, mw) == ["MouseTweaks-2.24.jar"],
          str(EH.installed_files(inst, mw)))
    EH.save_record(inst, {"mouse-tweaks": {"primary": "MouseTweaks-2.24.jar",
                                           "deps": ["fabric-api-0.9.jar"]}})
    check("有记录 → 认记录的主文件",
          EH.installed_files(inst, mw) == ["MouseTweaks-2.24.jar"])
    EH.save_record(inst, {"mouse-tweaks": {"primary": "gone.jar", "deps": []}})
    check("记录文件被手删 → 退回 mod id 识别",
          EH.installed_files(inst, mw) == ["MouseTweaks-2.24.jar"])
    os.remove(os.path.join(inst.mods_dir, "MouseTweaks-2.24.jar"))
    check("彻底没有 → 未装", EH.installed_files(inst, mw) == [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ── 5. ☠ 卸载只删自己的 ────────────────────────────────────────────
print("\n[5] 卸载保留前置库")
tmp = tempfile.mkdtemp(prefix="ac_e5_")
try:
    inst = FakeInst(tmp)
    os.makedirs(inst.mods_dir, exist_ok=True)
    make_jar(os.path.join(inst.mods_dir, "MouseTweaks-2.24.jar"), "mousetweaks")
    make_jar(os.path.join(inst.mods_dir, "fabric-api-0.92.jar"), "fabric-api")
    make_jar(os.path.join(inst.mods_dir, "Other-1.0.jar"), "othermod")
    EH.save_record(inst, {"mouse-tweaks": {
        "primary": "MouseTweaks-2.24.jar",
        "deps": ["fabric-api-0.92.jar"],
        "version_number": "2.24"}})
    res = EH.remove_item(inst, "mouse-tweaks")
    left = sorted(os.listdir(inst.mods_dir))
    check("主文件已删", "MouseTweaks-2.24.jar" not in left, str(left))
    check("前置库保留", "fabric-api-0.92.jar" in left, str(left))
    check("不误删别人的 mod", "Other-1.0.jar" in left, str(left))
    check("kept_deps 标记为真", res.get("kept_deps") is True)
    check("记录已清空", "mouse-tweaks" not in EH.load_record(inst))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ── 6. resolve_status 状态机 ───────────────────────────────────────
print("\n[6] resolve_status 状态机")
_orig_ps = net_api.project_supports
_orig_fmv = net_api.find_mod_version


def fake_supports(project_id, mc_version="", loader=""):
    if project_id == "mouse-tweaks":
        return {"exists": True, "loaders": ["fabric", "forge", "neoforge"],
                "game_versions": ["1.20.1"], "version_ok": True,
                "loader_ok": True}
    if project_id == "sodium":
        return {"exists": True, "loaders": ["fabric", "neoforge"],
                "game_versions": ["1.20.1"], "version_ok": True,
                "loader_ok": True}
    if project_id == "jade":
        return {"exists": True, "loaders": ["fabric"], "game_versions": ["1.21"],
                "version_ok": False, "loader_ok": True}
    if project_id == "modmenu":
        return {"exists": True, "loaders": ["fabric"], "game_versions": [],
                "version_ok": None, "loader_ok": True}
    if project_id == "modernfix":
        raise RuntimeError("boom")
    return {"exists": True, "loaders": ["fabric"], "game_versions": ["1.20.1"],
            "version_ok": True, "loader_ok": True}


def fake_find(project_id, mc_version="", loader=""):
    if project_id == "lithium":
        return None
    return {"id": f"{project_id}-vid", "version_number": "9.9"}


net_api.project_supports = fake_supports
net_api.find_mod_version = fake_find
try:
    tmp = tempfile.mkdtemp(prefix="ac_e6_")
    try:
        inst = FakeInst(tmp, "1.20.1", "fabric")
        st = EH.resolve_status(inst)
        by = {r["item"].slug: r for r in st["items"]}
        check("loader_ok 为真", st["loader_ok"] is True)
        check("mouse-tweaks 可用", by["mouse-tweaks"]["state"] == "available")
        check("挑中的构建带 version_id",
              by["mouse-tweaks"].get("version_id") == "mouse-tweaks-vid")
        check("sodium（无 forge 版）在 fabric 上可用",
              by["sodium"]["state"] == "available")
        check("jade 没有该版本 → version_unsupported",
              by["jade"]["state"] == "version_unsupported",
              by["jade"]["state"])
        check("lithium 查不到构建 → no_build",
              by["lithium"]["state"] == "no_build", by["lithium"]["state"])
        check("modernfix 抛错 → 只这一条 unreachable",
              by["modernfix"]["state"] == "unreachable")
        check("抛错没有毁掉其它条目",
              by["modmenu"]["state"] == "available")

        # 原版实例：全部 loader_unsupported，且**不联网**
        net_api.project_supports = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("原版实例不该联网查询"))
        vanilla = FakeInst(os.path.join(tmp, "v"), "1.20.1", "vanilla")
        st2 = EH.resolve_status(vanilla)
        check("vanilla → loader_ok 假", st2["loader_ok"] is False)
        check("vanilla → 全部 loader_unsupported",
              all(r["state"] == "loader_unsupported" for r in st2["items"]))

        # forge 实例：sodium 只支持 fabric/neoforge → loader_unsupported
        net_api.project_supports = _orig_ps
        net_api.project_supports = lambda p, mc="", ld="": {
            "exists": True, "loaders": ["fabric", "neoforge"],
            "game_versions": ["1.20.1"], "version_ok": True,
            "loader_ok": False}
        net_api.find_mod_version = lambda p, mc="", ld="": None
        forge = FakeInst(os.path.join(tmp, "f"), "1.20.1", "forge")
        st3 = EH.resolve_status(forge)
        fs = next(r for r in st3["items"] if r["item"].slug == "sodium")
        check("forge 上 sodium → loader_unsupported",
              fs["state"] == "loader_unsupported", fs["state"])
        check("拒绝原因写明支持哪些加载器",
              "fabric" in str(fs.get("detail")), str(fs.get("detail")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
finally:
    net_api.project_supports = _orig_ps
    net_api.find_mod_version = _orig_fmv

# ── 7. i18n 中英对齐 ──────────────────────────────────────────────
print("\n[7] i18n 中英对齐")
eh_zh = {k for k in ZH if k.startswith("enhance.")}
eh_en = {k for k in EN if k.startswith("enhance.")}
check("enhance.* 键数一致",
      len(eh_zh) == len(eh_en), f"zh={len(eh_zh)} en={len(eh_en)}")
check("缺失的英文键为空", not (eh_zh - eh_en), str(sorted(eh_zh - eh_en)))
check("缺失的中文键为空", not (eh_en - eh_zh), str(sorted(eh_en - eh_zh)))
check("中英整表键数一致", len(ZH) == len(EN), f"{len(ZH)} vs {len(EN)}")
bad = [k for k in eh_zh if not ZH.get(k, "").strip() or not EN.get(k, "").strip()]
check("没有空翻译", not bad, str(bad))

# ── 8. 界面模块可导入 ─────────────────────────────────────────────
print("\n[8] 界面模块")
try:
    import src.enhance_dialog as dl
    check("enhance_dialog 可导入", hasattr(dl, "EnhanceDialog"))
except Exception as e:  # noqa: BLE001
    check("enhance_dialog 可导入", False, f"{type(e).__name__}: {e}")

print("\n" + ("ALL PASS (%d checks)" % (len(fails) + 0) if not fails
             else "FAILED: %d" % len(fails)))
sys.exit(1 if fails else 0)
