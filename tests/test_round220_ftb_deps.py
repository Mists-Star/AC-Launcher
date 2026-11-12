"""round-220：FTB Ultimine / FTB Library 依赖解析回归（离线，零真实 HTTP）。

复现并修复的现象：FTB Ultimine 是 CurseForge 独占项目（448231），但资源中心
的 CF 下载通道此前**不解析任何依赖**——装完只剩本体，FTB Library / Architectury
全靠玩家自己凑，版本不对就崩退出码 1；Ultimine Unchained（Modrinth rGNPldmX）是
FTB Ultimine 的 mixin 修复补丁，自身只声明 Fabric API + Cloth Config，却**必须**
有 FTB Ultimine(CF) + FTB Library 才能真正工作。

本测试用打桩验证：
  * resolve_cf_dependencies 会拉 FTB Library（438495）、但跳过 Fabric API
    （306612，加载器级、实例已自带，不能重下成双 jar）；
  * 递归深度正确、不爆 / 不成环；
  * _override_companions 把 Ultimine Unchained 桥到 FTB Ultimine + FTB Library；
  * download_cf_with_deps 装依赖时**删掉同 mod 旧版本 jar**，避免新旧共存崩游戏。
"""
import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import net_api as na  # noqa: E402

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-64s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── 打桩：CF 依赖图（relationType 已在桩里按实测只暴露 required）──────────
# 448231 FTB Ultimine → [438495 FTB Library, 306612 Fabric API(加载器级)]
# 438495 FTB Library  → [306612 Fabric API(加载器级)]
# 306612 Fabric API  → []  （会被 _CF_LOADER_API_IDS 跳过）
# 桩按 project_id 暴露依赖（同项目不同文件的依赖在测试场景里一致）。
_DEP_GRAPH = {
    "448231": ["438495", "306612"],
    "438495": ["306612"],
    "306612": [],
    "419699": [],
}


def _fake_required_deps(pid, fid):
    return list(_DEP_GRAPH.get(str(pid), []))


def _fake_resolve_dep_file(pid, mc_version, loader):
    return {
        "project_id": str(pid),
        "file_id": "%s-f" % pid,
        "filename": "%s.jar" % pid,
        "url": "http://cdn.example/%s.jar" % pid,
        "sha1": "",
    }


na._cf_file_required_deps = _fake_required_deps
na._cf_resolve_dep_file = _fake_resolve_dep_file
na._curseforge_key = lambda: ""  # 走免 key 桩路径


print("\n[1] resolve_cf_dependencies：拉 FTB Library、跳过 Fabric API")
files = na.resolve_cf_dependencies("448231", "9205002", "26.1.2", "fabric")
got = {f["project_id"] for f in files}
check("FTB Library(438495) 被拉", "438495" in got)
check("Fabric API(306612) 被跳过（加载器级，不重下）", "306612" not in got)
check("递归深度正确（不含本体自身）", "448231" not in got)
check("只拉 1 个依赖（FTB Library）", len(files) == 1,
      "got=%s" % sorted(got))


print("\n[2] _override_companions：Ultimine Unchained → FTB Ultimine + FTB Library")
comp = na._override_companions("rGNPldmX", "26.1.2", "fabric")
cgot = {c["project_id"] for c in comp}
check("FTB Ultimine(448231) 桥接生效", "448231" in cgot)
check("FTB Library(438495) 经 CF 依赖递归拉到", "438495" in cgot)
check("Fabric API(306612) 仍被跳过", "306612" not in cgot)


print("\n[3] download_cf_with_deps：装依赖时删掉同 mod 旧版本 jar")
# 桩下载函数：只落地一个 <pid>.jar，便于断言
def _stub_keyed(pid, fid, dest_dir, callback=None, sha1="", cancel=None):
    p = os.path.join(dest_dir, "%s.jar" % pid)
    open(p, "w").close()
    return p


def _stub_keyless(pid, fid, dest_dir, callback=None, manifest_out=None, cancel=None):
    p = os.path.join(dest_dir, "%s.jar" % pid)
    open(p, "w").close()
    if manifest_out is not None:
        manifest_out.append({"filename": "%s.jar" % pid, "project_id": str(pid)})
    return p


na.download_curseforge_file = _stub_keyless  # _curseforge_key()=="" 时不会走到 keyed
na._download_cf_keyless = _stub_keyless

tmpd = tempfile.mkdtemp(prefix="ac_ftb_test_")
try:
    # 玩家之前手装过一个旧版 FTB Library jar —— 模拟「新旧共存」场景
    old_jar = os.path.join(tmpd, "old-ftb-library-26.1.2.6.jar")
    open(old_jar, "w").close()
    na._cf_existing_pid_map = lambda inst, dest: {
        "438495": ["old-ftb-library-26.1.2.6.jar"]}
    manifest = []
    primary = na.download_cf_with_deps(
        "448231", "9205002", tmpd, "26.1.2", "fabric",
        manifest_out=manifest, with_deps=True, inst="dummy")
    check("本体 FTB Ultimine 落地", os.path.exists(os.path.join(tmpd, "448231.jar")))
    check("依赖 FTB Library 落地", os.path.exists(os.path.join(tmpd, "438495.jar")))
    check("旧版 FTB Library jar 已被删除（避免双 jar 共存）", not os.path.exists(old_jar))
    check("manifest 记录了依赖文件", any(m.get("project_id") == "438495"
                                         for m in manifest))
finally:
    shutil.rmtree(tmpd, ignore_errors=True)


print("\n[4] download_cf_with_deps：with_deps=False 只下本体")
na._cf_existing_pid_map = lambda inst, dest: {}
tmpd2 = tempfile.mkdtemp(prefix="ac_ftb_test2_")
try:
    primary2 = na.download_cf_with_deps(
        "448231", "9205002", tmpd2, "26.1.2", "fabric", with_deps=False, inst="dummy")
    check("只下本体（FTB Ultimine）", os.path.exists(os.path.join(tmpd2, "448231.jar")))
    check("未拉依赖（FTB Library 不存在）",
          not os.path.exists(os.path.join(tmpd2, "438495.jar")))
finally:
    shutil.rmtree(tmpd2, ignore_errors=True)


print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("ALL CHECKS PASSED（round-220 FTB 依赖解析回归）")
