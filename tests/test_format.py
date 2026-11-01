"""round-135 回归测试：启动格式（磁盘布局）识别。

背景（真缺陷）：「启动格式」只分 vanilla/iso/multimc/curseforge/modrinth/custom，
AC 自己的实例布局（独立 .minecraft + libraries 走共享池联接）被误标成「原版」；
Modrinth App 的 profile.json 不在特征表里 → Modrinth 实例也显示「原版」；
导入时判定的 kind（权威值）完全没被用上。

覆盖：
  1. AC 自有布局 → ac
  2. 手动指定优先于探测
  3. 各来源的磁盘特征 → 对应格式
  4. 特征全 miss → 按 kind 兜底
  5. versions_root：iso 上溯两级，其余取 mc_dir
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

# AC_DEV_TEMP=1 下 get_data_dir() 每次调用都新建临时目录 → Instance.mc_dir
# 会漂移，断言不可靠。这里打桩成固定目录（只影响本次测试进程）。
_FIXED_DATA = os.path.join(tempfile.gettempdir(), "ac_fmt_data")
os.makedirs(_FIXED_DATA, exist_ok=True)
_inst_mod.get_data_dir = lambda: _FIXED_DATA

from src.instances import (Instance, INSTANCE_FORMATS, detect_format,  # noqa: E402
                           _KIND_TO_FORMAT, adapt_format, layout_of)
from src.launch import versions_root  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


TMP = tempfile.mkdtemp(prefix="ac_fmt_")
try:
    def mk(name, files=(), dirs=()):
        """造一个目录：files = 相对文件名列表（内容任意），dirs = 子目录列表。"""
        root = os.path.join(TMP, name)
        os.makedirs(root, exist_ok=True)
        for d in dirs:
            os.makedirs(os.path.join(root, d), exist_ok=True)
        for f in files:
            p = os.path.join(root, f)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{}")
        return root

    def inst(mc_dir, **kw):
        """导入型实例（external=True，_base=mc_dir）——走磁盘特征探测。"""
        kw.setdefault("id", "t")
        kw.setdefault("name", "t")
        kw.setdefault("game_version", "1.20.1")
        return Instance(external=True, _base=mc_dir, **kw)

    # ── 1. AC 自有布局 → ac ──
    ac = Instance(id="a", name="a", game_version="1.20.1")  # _base 空、external False
    check("AC 自建实例 → ac", detect_format(ac) == "ac", detect_format(ac))
    check("AC 实例 _base 为空", ac._base == "" and not ac.external)

    # 复制导入的实例同样落在 AC 自有布局（_base 空）→ ac
    ac_copy = Instance(id="b", name="b", game_version="1.20.1",
                       kind="standard", external=False)
    check("复制导入（_base 空）→ ac", detect_format(ac_copy) == "ac",
          detect_format(ac_copy))

    # ── 2. 手动指定 vs 结构判定 ──
    forced = Instance(id="c", name="c", game_version="1.20.1", format="multimc")
    check("AC 自有布局压过手动格式（round-163）", detect_format(forced) == "ac",
          detect_format(forced))
    forced2 = inst(mk("f_multimc", ["mmc-pack.json"]), format="custom")
    check("外来实例手动指定优先于磁盘特征", detect_format(forced2) == "custom",
          detect_format(forced2))
    bad = Instance(id="d", name="d", game_version="1.20.1", format="nonsense")
    check("非法手动值退回探测", detect_format(bad) == "ac", detect_format(bad))

    # ── 3. 磁盘特征 ──
    # 原版共享 .minecraft：versions/<v>/<v>.json，无任何来源元数据
    van = mk("vanilla", ["versions/1.20.1/1.20.1.json"])
    i_van = inst(van, kind="standard")
    check("原版共享 .minecraft → vanilla", detect_format(i_van) == "vanilla",
          detect_format(i_van))

    # 外来版本隔离：mc_dir 就是 versions/<id>，json 扁平躺着
    iso = mk("iso", ["1.20.1-forge.json"])
    i_iso = inst(iso, version_id="1.20.1-forge", kind="standard")
    check("外来版本隔离 → iso", detect_format(i_iso) == "iso",
          detect_format(i_iso))

    # MMC：mmc-pack.json 在实例根
    mmc = mk("mmc", ["mmc-pack.json"], ["minecraft"])
    i_mmc = inst(os.path.join(mmc, "minecraft"), kind="mmc")
    check("MMC（父目录 mmc-pack.json）→ multimc", detect_format(i_mmc) == "multimc",
          detect_format(i_mmc))

    # CurseForge：minecraftinstance.json 在实例根
    cf = mk("cf", ["minecraftinstance.json"])
    i_cf = inst(cf, kind="curseforge")
    check("CurseForge → curseforge", detect_format(i_cf) == "curseforge",
          detect_format(i_cf))

    # Modrinth App：profile.json（此前漏检 → 会误标原版）
    mr = mk("mr", ["profile.json"])
    i_mr = inst(mr, kind="modrinth")
    check("Modrinth profile.json → modrinth", detect_format(i_mr) == "modrinth",
          detect_format(i_mr))

    # Modrinth 旧布局：instance.cfg
    mr_old = mk("mr_old", ["instance.cfg"])
    i_mr_old = inst(mr_old, kind="modrinth")
    check("Modrinth instance.cfg → modrinth", detect_format(i_mr_old) == "modrinth",
          detect_format(i_mr_old))

    # ── 4. 特征全 miss → kind 兜底 ──
    empty = mk("empty")
    for kind, want in _KIND_TO_FORMAT.items():
        i = inst(empty, kind=kind)
        got = detect_format(i)
        check("kind=%s 兜底 → %s" % (kind, want), got == want, got)
    i_nokind = inst(empty, kind="")
    check("无 kind 无特征 → vanilla", detect_format(i_nokind) == "vanilla",
          detect_format(i_nokind))
    # 目录不存在也要按 kind 兜底
    i_gone = inst(os.path.join(TMP, "does_not_exist"), kind="modrinth")
    check("目录不存在 → kind 兜底", detect_format(i_gone) == "modrinth",
          detect_format(i_gone))

    # ── 5. versions_root ──
    check("iso 的解析根上溯两级",
          versions_root(i_iso) == os.path.dirname(os.path.dirname(iso)),
          versions_root(i_iso))
    check("vanilla 的解析根 = mc_dir", versions_root(i_van) == van,
          versions_root(i_van))
    check("ac 的解析根 = mc_dir", versions_root(ac) == ac.mc_dir,
          versions_root(ac))
    check("multimc 的解析根 = mc_dir", versions_root(i_mmc) == i_mmc.mc_dir,
          versions_root(i_mmc))

    # ── 6. 识别结果联动补全/启动（round-164）──
    # 6.1 读到实例即纠正 AC 自有布局上的外来格式残留
    stale = Instance(id="s", name="s", game_version="1.20.1",
                     format="curseforge", external=False)
    check("AC 实例残留 curseforge 被纠正",
          adapt_format(stale) is True and stale.format == "ac", stale.format)
    check("外来实例的手动格式不被改写",
          adapt_format(forced2) is False and forced2.format == "custom",
          forced2.format)
    check("auto 保持不变", adapt_format(Instance(
        id="s2", name="s2", game_version="1.20.1", format="")) is False)

    # 6.2 补全写盘根与启动解析根必须同一口径
    lo_ac = layout_of(ac)
    check("AC 补全根 = mc_dir", lo_ac["install_dir"] == ac.mc_dir,
          lo_ac["install_dir"])
    lo_iso = layout_of(i_iso)
    check("iso 补全根上溯两级", lo_iso["install_dir"] == os.path.dirname(
        os.path.dirname(iso)), lo_iso["install_dir"])
    check("iso 标记 flat", lo_iso["flat"] is True)
    check("iso 版本 id 取 version_id", lo_iso["version"] == "1.20.1-forge",
          lo_iso["version"])
    check("启动根 = 补全根", versions_root(i_iso) == lo_iso["install_dir"])
    lo_van = layout_of(i_van)
    check("vanilla 补全根 = mc_dir", lo_van["install_dir"] == van,
          lo_van["install_dir"])
    check("vanilla 不标记 flat", lo_van["flat"] is False)
    # AC 目录里即使有同名扁平 json，也不得把根移到上级（保护自有布局）
    ac_flat = Instance(id="af", name="af", game_version="1.20.1")
    os.makedirs(ac_flat.mc_dir, exist_ok=True)
    with open(os.path.join(ac_flat.mc_dir, "1.20.1.json"), "w",
              encoding="utf-8") as fh:
        fh.write("{}")
    lo_af = layout_of(ac_flat)
    check("AC 扁平 json 不切根", lo_af["install_dir"] == ac_flat.mc_dir and
          lo_af["flat"] is False, lo_af["install_dir"])

    # ── 7. 枚举与 UI 契约 ──
    check("INSTANCE_FORMATS 含 ac", "ac" in INSTANCE_FORMATS,
          str(INSTANCE_FORMATS))
    check("INSTANCE_FORMATS 含 auto", "auto" in INSTANCE_FORMATS)
    check("detect_format 返回值恒在枚举内",
          all(detect_format(x) in INSTANCE_FORMATS
              for x in (ac, i_van, i_iso, i_mmc, i_cf, i_mr, i_nokind)))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print()
if fails:
    print("失败 %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("ALL CHECKS PASSED")
