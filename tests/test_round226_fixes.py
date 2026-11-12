"""round-226：审计发现修复的**行为回归**（离线，零真实 HTTP）。

判据全部是「跑了之后结果对不对」，不是源码字面量（round-221/223 教训）。
覆盖：P0-1 OptiFine 写穿、P1-1 Java 口径、P1-2 复制布局、P1-3 CF 依赖、
P1-4 shlex、P1-5 主题包、P1-6 崩溃分析目录、P1-8 取消链、P1-9 补库校验、
P1-12 进程提示、P1-14 log4j、P2 i18n / 配置 / 图标 / 缓存 / 路径。
"""
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from src import net_api as na                # noqa: E402
from src import theme                        # noqa: E402
from src import launch                       # noqa: E402
from src import instances as I               # noqa: E402
from src import paths                        # noqa: E402
from src import crash_analysis as ca         # noqa: E402
from src import async_image as AI            # noqa: E402
from src import settings_dialog as sd        # noqa: E402
from src.i18n import t, _STRINGS             # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-70s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── [1] P0-1 OptiFine：远端文件名必须过 _safe_filename + URL quote ──────
print("\n[1] OptiFine 远端文件名")
captured = {}


class _Resp:
    text = '<a href="downloadx?f=../evil.jar&x=deadbeef">dl</a>'

    def raise_for_status(self):
        pass


class _Session:
    headers = {}
    cookies = {}

    def get(self, url, timeout=None):
        captured["adloadx"] = url
        return _Resp()


class _Req:
    Session = _Session
    RequestException = Exception


_o_req, _o_par = na.requests, na.parallel_download_file
na.requests = _Req


def _cap(url, dest, **kw):
    captured["url"], captured["dest"] = url, dest
    return dest


na.parallel_download_file = _cap
try:
    with tempfile.TemporaryDirectory() as td:
        mods = os.path.join(td, "mods")
        na.download_optifine_to("OptiFine_1.20.1.jar", mods)
        d = os.path.normpath(captured["dest"])
        check("落盘路径留在 mods 内",
              os.path.abspath(d).startswith(os.path.abspath(mods) + os.sep)
              and os.path.basename(d) == "evil.jar", d)
        check("URL 里 f= 已 percent-encode（没有裸 ../）",
              "../" not in captured["url"] and "..%2F" in captured["url"],
              captured["url"])
        check("adloadx 的 file 也做了 quote",
              "OptiFine_1.20.1.jar" in captured["adloadx"])
finally:
    na.requests, na.parallel_download_file = _o_req, _o_par


# ── [2] P1-4 参数分词：反斜杠 + 引号 ───────────────────────────────────
print("\n[2] JVM / 游戏参数分词")
a = launch.split_args(r"-Djava.library.path=C:\Program Files\natives")
check("Windows 反斜杠不再被吞", a == [r"-Djava.library.path=C:\Program",
                                    r"Files\natives"], str(a))
check("带引号的键值仍合成一个 token",
      launch.split_args(r'-Dfoo="a b"') == ["-Dfoo=a b"])
check("带引号的 Windows 路径完整保留",
      launch.split_args(r'"-Djava.library.path=C:\Program Files\natives"')
      == [r"-Djava.library.path=C:\Program Files\natives"])
check("引号不闭合时不抛异常", isinstance(launch.split_args('-Dfoo="a b'), list))
check("空串返回空列表", launch.split_args("") == [])


# ── [3] P1-5 主题包：非法字段不崩启动链 ────────────────────────────────
print("\n[3] 主题包校验")
_saved = dict(theme.COLORS), dict(theme.RADII), dict(theme.FONTS)
for bad in ({"id": "bad", "colors": "oops"},
            {"id": "bad", "radii": [1, 2, 3]},
            {"id": "bad", "fonts": None}):
    try:
        theme.apply_theme_pack(bad)
        check("apply_theme_pack(%s) 不再抛异常" % list(bad)[1], True)
    except Exception as e:
        check("apply_theme_pack(%s) 不再抛异常" % list(bad)[1], False, repr(e))
check("_validate_theme_pack 清洗掉非 dict 字段",
      theme._validate_theme_pack({"id": "x", "colors": "oops"})["colors"] == {})
check("缺 id 的包被拒绝",
      theme._validate_theme_pack({"colors": {}}) is None)
theme.COLORS.update(_saved[0]); theme.RADII.update(_saved[1]); theme.FONTS.update(_saved[2])


# ── [4] P2 i18n：缺键与占位符 ──────────────────────────────────────────
print("\n[4] i18n")
for key in ("err.config_save_failed", "err.terms_check_failed",
            "err.terms_dialog_failed", "err.terms_save_failed",
            "store.download_cancelled"):
    check("中英都有 %s" % key,
          key in _STRINGS["zh-CN"] and key in _STRINGS["en-US"])
check("Java 确认框不再泄漏占位符",
      "{" not in t("launch.java_confirm_msg2", need="17", major="21"))
check("设备码文案不再泄漏 {url}", "{" not in t("login.code_desc"))
check("导入失败文案能填 err",
      t("settings.cfg_import_fail", err="boom") == "导入失败：boom")


# ── [5] P1-3 CF required 依赖：不许假成功 ──────────────────────────────
print("\n[5] CF 依赖解析")
_o = (na._cf_file_required_deps, na._cf_resolve_dep_file, na._cf_download_one,
      na._cf_existing_pid_map)
calls = {"dl": 0}


def _dl(pid, fid, dest_dir, callback, manifest_out, existing_by_pid,
        sha1="", cancel=None):
    calls["dl"] += 1
    calls["cancel"] = cancel
    return os.path.join(dest_dir, "primary.jar")


na._cf_download_one = _dl
na._cf_existing_pid_map = lambda inst, dest: {}
na._cf_file_required_deps = lambda p, f: ["222"]
na._cf_resolve_dep_file = lambda p, m, l: None
try:
    with tempfile.TemporaryDirectory() as td:
        try:
            na.download_cf_with_deps("111", "900", td, "1.20.1", "forge",
                                     with_deps=True)
            check("缺前置时拒绝下载本体", False, "没抛 NetError")
        except na.NetError as e:
            check("缺前置时拒绝下载本体", calls["dl"] == 0 and "222" in str(e),
                  "下载次数=%d" % calls["dl"])
finally:
    pass

na._cf_resolve_dep_file = lambda p, m, l: {
    "project_id": "222", "file_id": "901", "filename": "dep.jar",
    "url": "http://x/dep.jar", "sha1": "",
}
try:
    with tempfile.TemporaryDirectory() as td:
        na.download_cf_with_deps("111", "900", td, "1.20.1", "forge",
                                 with_deps=True,
                                 callback={"cancel": lambda: False})
        check("依赖齐全时本体 + 前置都下载", calls["dl"] == 2, str(calls["dl"]))
        check("cancel 判定已透传到下载层", callable(calls.get("cancel")))
finally:
    (na._cf_file_required_deps, na._cf_resolve_dep_file,
     na._cf_download_one, na._cf_existing_pid_map) = _o

check("_cb_cancel 从 callback 取判定", na._cb_cancel({"cancel": lambda: True})() is True)
check("_cb_cancel 无 callback 返回 None", na._cb_cancel(None) is None)
check("_cb_cancel 非 callable 返回 None", na._cb_cancel({"cancel": 1}) is None)


# ── [6] P1-1 Java 口径 ─────────────────────────────────────────────────
print("\n[6] 实例固定 Java")


class _JInst:
    def __init__(self, p):
        self.java_path = p


check("全局自动 + 无固定 Java → 自动探测",
      launch.effective_java_auto({"java_auto": True}, _JInst("")) is True)
check("全局自动 + 实例固定 Java → 让位给实例",
      launch.effective_java_auto({"java_auto": True}, _JInst("C:/j/bin/java.exe")) is False)
check("全局关自动 → 固定",
      launch.effective_java_auto({"java_auto": False}, _JInst("")) is False)


# ── [7] P1-2 复制版本隔离实例 ──────────────────────────────────────────
print("\n[7] duplicate() 布局")
with tempfile.TemporaryDirectory() as td:
    data_dir = os.path.join(td, "data")
    vid = "1.20.1-forge-47.2.0"
    src_mc = os.path.join(td, "external", "versions", vid)
    os.makedirs(src_mc)
    open(os.path.join(src_mc, vid + ".json"), "w", encoding="utf-8").write("{}")
    _o_data = I.get_data_dir
    I.get_data_dir = lambda: data_dir
    try:
        src = I.Instance(id="src", name="ext", game_version="1.20.1",
                         loader="forge", version_id=vid, external=True,
                         launcher="PCL-CE", _base=src_mc, isolation="isolated",
                         favorite=True, gc_mode="zgc", auto_server="a:25565")
        mgr = I.InstancesManager()
        mgr._instances = {"src": src}
        dup = mgr.duplicate("src")
        nested = os.path.join(dup.mc_dir, "versions", vid, vid + ".json")
        check("版本 json 保留在 versions/<id>/ 层级", os.path.isfile(nested))
        check("mll 解析根能找到该 json",
              os.path.isfile(os.path.join(launch.versions_root(dup, vid),
                                          "versions", vid, vid + ".json")))
        check("副本标记 isolated", dup.isolation == "isolated")
        check("收藏 / GC / 自动进服跟着复制",
              dup.favorite is True and dup.gc_mode == "zgc"
              and dup.auto_server == "a:25565")
    finally:
        I.get_data_dir = _o_data


# ── [8] P1-6 崩溃分析读 game_dir ───────────────────────────────────────
print("\n[8] 崩溃分析目录")
with tempfile.TemporaryDirectory() as td:
    mc = os.path.join(td, "mc")
    gd = os.path.join(td, "game")
    os.makedirs(os.path.join(gd, "logs"))
    open(os.path.join(gd, "logs", "latest.log"), "w", encoding="utf-8").write(
        "[main/ERROR] java.lang.NoClassDefFoundError: net/fabricmc/loader\n"
        "Exception in thread \"main\" java.lang.NoClassDefFoundError\n")

    class _CInst:
        mc_dir = mc
        game_dir = gd

    findings = ca.analyze_instance(_CInst())
    check("隔离实例的日志能被读到（不再显示『运行正常』）", bool(findings),
          ",".join(f.kind for f in findings))
    check("归因不是空证据", any(f.detail for f in findings))


# ── [9] P1-9 补库校验 / P1-14 log4j ───────────────────────────────────
print("\n[9] 补库与启动参数")
with tempfile.TemporaryDirectory() as td:
    vj = os.path.join(td, "v.json")
    import json
    json.dump({"libraries": [
        {"downloads": {"artifact": {"path": "a/b/c.jar",
                                    "sha1": "deadbeef", "size": 1234}}}
    ]}, open(vj, "w", encoding="utf-8"))
    exp = launch._library_expectations(vj)
    check("能从版本 json 取到库 sha1/size",
          exp.get("a/b/c.jar") == ("deadbeef", 1234), str(exp))
check("坏 json 不抛异常", launch._library_expectations("/nope/nope.json") == {})
try:
    opts = launch.build_options("u", "i", "tok", mc_dir=tempfile.gettempdir(),
                                java="java")
    check("build_options 注入 log4j 配置", opts.get("enableLoggingConfig") is True)
except Exception as e:
    check("build_options 注入 log4j 配置", False, repr(e))


# ── [10] P2 配置写盘 / 键 / 路径 ───────────────────────────────────────
print("\n[10] 配置与路径")
check("_DEFAULTS 登记 nav_collapsed", sd._DEFAULTS.get("nav_collapsed") is False)
_o_cfg = sd.CONFIG_FILE
with tempfile.TemporaryDirectory() as td:
    sd.CONFIG_FILE = os.path.join(td, "cfg.json")
    errs = []

    def _write(i):
        try:
            sd.save_config({"i": i, "s": "x" * 4000})
        except Exception as e:
            errs.append(repr(e))

    ts = [threading.Thread(target=_write, args=(i,)) for i in range(8)]
    for x in ts:
        x.start()
    for x in ts:
        x.join()
    check("8 线程并发写不抛异常", not errs, str(errs[:2]))
    try:
        back = json.load(open(sd.CONFIG_FILE, encoding="utf-8"))
        check("落盘 JSON 完整可解析", isinstance(back, dict) and "s" in back)
    except Exception as e:
        check("落盘 JSON 完整可解析", False, repr(e))
    leftovers = [f for f in os.listdir(td) if f.endswith(".tmp")]
    check("并发写后没有残留 tmp", not leftovers, str(leftovers))
sd.CONFIG_FILE = _o_cfg
check("_base_dir 指向项目根而非 cwd",
      os.path.normcase(paths._base_dir()) == os.path.normcase(HERE),
      paths._base_dir())


# ── [11] P2 async_image：字节统计 + 直连回退复位 ──────────────────────
print("\n[11] 图标下载")


class _Reply:
    def __init__(self):
        self._p = {"seen": 0}

    def property(self, k):
        return self._p.get(k)

    def setProperty(self, k, v):
        self._p[k] = v
        return True

    def bytesAvailable(self):
        return 400_000

    def abort(self):
        self._p["aborted"] = True


class _Shim:
    _MAX_ICON_BYTES = 512 * 1024

    def __init__(self):
        self._reply = _Reply()

    def sender(self):
        return self._reply


sh = _Shim()
AI.ImageLoader._on_ready_read(sh)
AI.ImageLoader._on_ready_read(sh)
check("两次 readyRead 后不虚增字节数", sh._reply.property("seen") == 400_000,
      str(sh._reply.property("seen")))
check("400KB 图标不触发误 abort", not sh._reply.property("aborted"))


# ── [12] P2 .mrpack sha1 / 缓存键 / 磁盘缓存 ───────────────────────────
print("\n[12] 下载完整性")
_o = (na._modrinth_versions, na.get_mod_download, na.download_file)
seen = {}
na._modrinth_versions = lambda p, *a, **k: [
    {"id": "v1", "files": [{"primary": True, "filename": "p.mrpack",
                            "url": "http://x/p.mrpack",
                            "hashes": {"sha1": "ABCDEF"}}]}]
na.get_mod_download = lambda p, v="": ("p.mrpack", "http://x/p.mrpack")
na.download_file = lambda url, dest, **kw: (seen.update(kw), dest)[1]
try:
    with tempfile.TemporaryDirectory() as td:
        na.download_modpack_to("proj", td)
        check(".mrpack 下载带 expected_sha1",
              seen.get("expected_sha1") == "ABCDEF", str(seen.get("expected_sha1")))
finally:
    na._modrinth_versions, na.get_mod_download, na.download_file = _o

_o_path, _o_cache = na._CACHE_DISK_PATH, dict(na._cache)
with tempfile.TemporaryDirectory() as td:
    na._CACHE_DISK_PATH = os.path.join(td, "cache", "c.json")
    os.makedirs(os.path.dirname(na._CACHE_DISK_PATH), exist_ok=True)
    na._cache.clear()
    na._cache["k"] = (9999999999.0, {"v": 1})
    na._save_disk_cache()
    try:
        back = json.load(open(na._CACHE_DISK_PATH, encoding="utf-8"))
        check("磁盘缓存可解析", "k" in back)
    except Exception as e:
        check("磁盘缓存可解析", False, repr(e))
    check("写盘后没有 tmp 残留",
          not [f for f in os.listdir(os.path.dirname(na._CACHE_DISK_PATH))
               if f.endswith(".tmp")])
na._CACHE_DISK_PATH = _o_path
na._cache.clear(); na._cache.update(_o_cache)

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-226 修复回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-226 修复回归）")
