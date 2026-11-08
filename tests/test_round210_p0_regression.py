"""round-210：全启动器审查 §十六 的 7 条 P0 回归（离线、零真实网络）。

审查报告里的 7 条 P0 全部由「代码轨 + 运行轨」证据确认，但 79 项旧回归
一项都没覆盖。本文件不查源码字符串了事，而是**重放故障本身**：

  1. 备份还原 copytree 半途失败 → 存档必须原样回来（旧实现先删后拷，必丢）。
  2. 分片下载后续请求被服务端降级成 200 → 必须回退单流，坏文件不能落盘；
     同时用正常 206 证明分片成功路径没被改哑。
  3. 自更新脚本必须「先启动验证、后删备份」。
  4. 导出/导入设置两个按钮必须真能跑通（旧实现 from . import 必 ImportError）。
  5. aikar + zgc 不得同时下发 G1GC / ZGC；默认路径旧能力不丢。
  6. 微软静默刷新必须用签发 token 的 client_id，且不能丢 refresh_token。
  7. ModRow 销毁后的异步重排不得抛 RuntimeError（真机 705 条同类崩溃）。
"""
import ast
import json
import os
import shutil
import sys
import tempfile
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-66s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8") as f:
        return f.read()


def put(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(data)
    return p


def get(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


# ── 1. 备份还原事务 ────────────────────────────────────────────────────────
print("\n[1] 备份还原：半途失败必须原样回滚")
from src.core import backup  # noqa: E402


class FakeInst:
    def __init__(self, mc):
        self.mc_dir = mc
        self.id = "p0test"
        self.ensure_calls = 0

    def _strip_shared_junctions(self, mc):
        return None

    def ensure_dirs(self):
        self.ensure_calls += 1


def make_backup_fixture(td):
    mc = os.path.join(td, "mc")
    put(mc, "a.txt", "OLD")
    put(mc, "mods/x.jar", "oldjar")
    put(mc, "saves/keep.txt", "ADDED_AFTER_SNAPSHOT")
    snap = os.path.join(td, "snap")
    put(os.path.join(snap, "minecraft"), "a.txt", "SNAP")
    put(os.path.join(snap, "minecraft"), "saves/w.txt", "world")
    return mc, snap


with tempfile.TemporaryDirectory() as td:
    mc, snap = make_backup_fixture(td)
    inst = FakeInst(mc)
    backup.restore_backup(inst, snap)
    check("正常回滚写入快照内容", get(mc, "a.txt") == "SNAP"
          and get(mc, "saves/w.txt") == "world")
    check("快照后新增文件按确认框说明被删除",
          not os.path.exists(os.path.join(mc, "saves/keep.txt"))
          and not os.path.exists(os.path.join(mc, "mods/x.jar")))
    check("成功提交后暂存区被清理、联接已重建",
          not [d for d in os.listdir(td) if d.startswith(".ac-restore-tx-")]
          and inst.ensure_calls >= 1)

with tempfile.TemporaryDirectory() as td:
    mc, snap = make_backup_fixture(td)
    inst = FakeInst(mc)
    before = {p: get(mc, p) for p in
              ("a.txt", "mods/x.jar", "saves/keep.txt")}
    orig = backup.shutil.copytree

    def boom(*_a, **_kw):
        raise OSError("disk full (simulated)")

    backup.shutil.copytree = boom
    raised = False
    try:
        try:
            backup.restore_backup(inst, snap)
        except OSError:
            raised = True
    finally:
        backup.shutil.copytree = orig
    check("copytree 抛异常时向上传递、不吞", raised)
    after = {}
    for rel in before:
        p = os.path.join(mc, rel)
        after[rel] = get(mc, rel) if os.path.isfile(p) else None
    check("失败后玩家存档 / 新增文件 / mod 全部原样搬回", after == before,
          "" if after == before else repr(after))
    check("失败后不留半成品暂存区",
          not [d for d in os.listdir(td) if d.startswith(".ac-restore-tx-")])
    check("确认框写明「新增文件也会被删除」",
          "新增的文件也会被删除" in read("src/i18n.py"))


# ── 2. 分片下载 200 误判 ───────────────────────────────────────────────────
print("\n[2] 分片下载：服务端忽略 Range 的 200 不得当成功")
from src import net_api as na  # noqa: E402

BODY = b"ABCDEFGH"
TOTAL = len(BODY)


class FakeResp:
    def __init__(self, status, headers=None, body=b""):
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def iter_content(self, _n):
        if self._body:
            yield self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http %d" % self.status_code)

    def close(self):
        pass


def run_parallel(td, worker_status, worker_headers, worker_body):
    """返回 (dest, 单流回退调用记录)。"""
    dest = os.path.join(td, "asset.jar")
    fallbacks = []
    orig_get = na.requests.get
    orig_dl = na.download_file

    def fake_get(url, headers=None, timeout=None, stream=None, proxies=None):
        rng = (headers or {}).get("Range", "")
        if rng == "bytes=0-0":
            return FakeResp(206, {"Content-Range": "bytes 0-0/%d" % TOTAL})
        return FakeResp(worker_status, worker_headers, worker_body)

    def fake_dl(url, d, **kw):
        fallbacks.append(kw.get("_allow_parallel"))
        return d

    na.requests.get = fake_get
    na.download_file = fake_dl
    try:
        na.parallel_download_file("http://probe.invalid/a.jar", dest,
                                  threads=2, chunk_mb=1, timeout=1)
    finally:
        na.requests.get = orig_get
        na.download_file = orig_dl
    return dest, fallbacks


with tempfile.TemporaryDirectory() as td:
    dest, fallbacks = run_parallel(td, 200, {}, BODY)
    check("200（Range 被忽略）触发单流回退",
          len(fallbacks) == 1 and fallbacks[0] is False)
    check("坏 jar 没有 os.replace 到正式路径",
          not os.path.exists(dest) and not os.path.exists(dest + ".part"))

with tempfile.TemporaryDirectory() as td:
    dest, fallbacks = run_parallel(
        td, 206, {"Content-Range": "bytes 0-%d/%d" % (TOTAL - 1, TOTAL)}, BODY)
    check("正常 206 仍走分片、不误回退单流", fallbacks == [])
    check("正常 206 拼出的文件字节完全一致",
          os.path.isfile(dest) and open(dest, "rb").read() == BODY)


# ── 3. 自更新脚本顺序 ──────────────────────────────────────────────────────
print("\n[3] 自更新：先验证新 exe 能跑，再删 .upd_bak")
from src.core import update_install as ui  # noqa: E402
from src.core.update_trust import UpdateManifest  # noqa: E402

manifest = UpdateManifest(
    version="9.9.9", notes=(), asset_name="a.zip",
    asset_url="https://example.invalid/a.zip", sha256="0" * 64,
    size=1, key_id="test",
)
with tempfile.TemporaryDirectory() as td:
    app = os.path.join(td, "app")
    os.makedirs(app)
    asset = os.path.join(td, "a.zip")
    with open(asset, "wb") as f:
        f.write(b"x")
    script = ui.write_upgrade_script(
        manifest, asset, app_dir=app, pid=12345,
        exe_name="AC_Launcher.exe", data_dir=td)
    ps = open(script, encoding="utf-8-sig").read()
    drop = "Remove-Item -Recurse -Force ($internal + $Bak) -ErrorAction SilentlyContinue"
    check("脚本用 -PassThru 拿进程句柄", "-PassThru" in ps)
    check("脚本检查新进程是否秒退", "$proc.HasExited" in ps)
    check("验证发生在删除备份之前",
          drop in ps and ps.index("$proc.HasExited") < ps.index(drop)
          and ps.index("-PassThru") < ps.index(drop))
    check("启动验证通过后才写 verified 日志",
          "relaunch verified" in ps and ps.index("relaunch verified") < ps.index(drop))
    check("catch 回滚分支仍保留", "ROLLBACK FAILED" in ps
          and "rollback relaunched" in ps)
    check("try 分支只启动一次新 exe（没有残留旧顺序）",
          ps.count("Start-Process -FilePath $exePath -WorkingDirectory $AppDir -PassThru") == 1)


# ── 4. 设置导出 / 导入按钮 ────────────────────────────────────────────────
print("\n[4] 设置导出/导入：两个按钮必须真能跑通")
sd_src = read("src/settings_dialog.py")
sd_tree = ast.parse(sd_src)
sd_cls = next(n for n in sd_tree.body
              if isinstance(n, ast.ClassDef) and n.name == "SettingsPage")
for name in ("_export_settings", "_import_settings"):
    fn = next(n for n in sd_cls.body
              if isinstance(n, ast.FunctionDef) and n.name == name)
    imports = [a.name for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)
               for a in n.names]
    check("%s 不再从包导入 _SENSITIVE_CFG_KEYS" % name,
          "_SENSITIVE_CFG_KEYS" not in imports)

from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication.instance() or QApplication([])
import src.win_rounded as wr  # noqa: E402
import src.settings_dialog as sd  # noqa: E402

page = sd.SettingsPage()
page.cfg = dict(sd._DEFAULTS)
page.cfg["curseforge_api_key"] = "SECRET-SHOULD-NOT-LEAK"
page.cfg["dev_mode_key"] = "SECRET-DEV"
page.cfg["ram_mb"] = 6144
export_dir = tempfile.mkdtemp(prefix="ac-r210-")
import_path = None
saved = []
info_calls = []
with mock.patch.object(sd.SettingsPage, "_sync_ui_to_cfg", lambda *a, **k: None), \
     mock.patch.object(sd.SettingsPage, "_rebuild", lambda *a, **k: None), \
     mock.patch.object(sd, "save_config", lambda cfg: saved.append(dict(cfg))), \
     mock.patch.object(wr, "pick_folder", lambda *a, **k: export_dir), \
     mock.patch.object(wr, "pick_files", lambda *a, **k: import_path), \
     mock.patch.object(wr, "info", lambda *a, **k: info_calls.append(a)), \
     mock.patch.object(wr, "warn", lambda *a, **k: info_calls.append(("WARN",) + a)):
    err = None
    try:
        page._export_settings()
    except Exception as e:  # noqa: BLE001
        err = e
    check("导出设置不抛 ImportError / UnboundLocalError",
          err is None, "" if err is None else repr(err))
    exports = [p for p in os.listdir(export_dir) if p.endswith(".json")]
    check("导出确实生成 JSON 文件", len(exports) == 1)
    if exports:
        payload = json.load(open(os.path.join(export_dir, exports[0]),
                                 encoding="utf-8"))
        check("导出不含敏感键",
              all(k not in payload for k in sd._SENSITIVE_CFG_KEYS))
        check("导出保留普通设置", payload.get("ram_mb") == 6144)
        import_path = os.path.join(export_dir, exports[0])
        # 篡改导入文件，确认敏感键不会被还原
        payload["curseforge_api_key"] = "INJECTED"
        payload["ram_mb"] = 8192
        payload["__junk__"] = 1
        with open(import_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    err2 = None
    try:
        page._import_settings()
    except Exception as e:  # noqa: BLE001
        err2 = e
    check("导入设置不抛 ImportError", err2 is None,
          "" if err2 is None else repr(err2))
    check("导入合并已知键且不还原告密",
          page.cfg.get("ram_mb") == 8192
          and page.cfg.get("curseforge_api_key") == "SECRET-SHOULD-NOT-LEAK"
          and "__junk__" not in page.cfg)
    check("导入写出配置且给了成功反馈",
          bool(saved) and any(not str(c[0]).startswith("WARN")
                              for c in info_calls))
shutil.rmtree(export_dir, ignore_errors=True)
page.deleteLater()


# ── 5. JVM GC 互斥 ─────────────────────────────────────────────────────────
print("\n[5] 启动参数：aikar + zgc 不得同时下发 G1GC / ZGC")
from src.launch import build_options, normalize_gc_flags, _AIKAR_FLAGS  # noqa: E402

G1_MARKERS = ("-XX:+UseG1GC", "-XX:G1NewSizePercent", "-XX:G1ReservePercent",
              "-XX:G1MixedGCLiveThresholdPercent", "-XX:MaxGCPauseMillis=40")


def opts(preset, gc, **kw):
    return build_options("u", "i", "t", mc_dir="x", java="j",
                         jvm_preset=preset, gc_mode=gc, **kw)["jvmArguments"]


for preset in ("aikar", "auto"):
    s = opts(preset, "zgc", ram_mb=16384)
    check("%s + zgc 清掉所有 G1 专用参数" % preset,
          not any(m in s for m in G1_MARKERS))
    check("%s + zgc 保留 UseZGC" % preset, "-XX:+UseZGC" in s)
s = opts("aikar", "zgc_gen", ram_mb=16384)
check("aikar + zgc_gen 不带 G1 且保留 ZGenerational",
      not any(m in s for m in G1_MARKERS) and "-XX:+ZGenerational" in s)
s = opts("aikar", "g1_tuned", jvm_args="-XX:+UseZGC")
check("g1_tuned 清掉玩家手填的 UseZGC", "-XX:+UseZGC" not in s)
s = opts("aikar", "")
check("未显式选 GC 时 Aikar 组完整保留（旧能力不丢）",
      all(f in s for f in _AIKAR_FLAGS))
check("normalize_gc_flags 对空 / follow 是恒等的",
      normalize_gc_flags(["-XX:+UseG1GC"], "") == ["-XX:+UseG1GC"]
      and normalize_gc_flags(["-XX:+UseG1GC"], "follow") == ["-XX:+UseG1GC"])
check("normalize_gc_flags 不改原列表",
      (lambda src: (normalize_gc_flags(src, "zgc"),
                    src == ["-XX:+UseG1GC"]))(["-XX:+UseG1GC"])[1])


# ── 6. 微软静默刷新 client_id ─────────────────────────────────────────────
print("\n[6] 认证：refresh_token 必须用它自己的 client_id 兑换")
from src.core import auth  # noqa: E402
from src.brand import MS_CLIENT_ID  # noqa: E402


class PostResp:
    def json(self):
        # 微软刷新响应通常不回传 refresh_token
        return {"access_token": "NEW-MS-TOKEN", "expires_in": 3600}


posts = []
completed = []
with mock.patch.object(auth.requests, "post",
                       lambda url, **kw: (posts.append(kw), PostResp())[1]), \
     mock.patch.object(auth, "complete_login_with_token",
                       lambda cid, tok: (completed.append(cid), {
                           "id": "fresh", "name": "Tester",
                           "access_token": "MC-NEW",
                       })[1]):
    prof = {"id": "acct-1", "refresh_token": "RT-OLD",
            "ms_client_id": "cid-custom-1234"}
    out = auth.refresh_microsoft(prof)
    check("POST 使用 profile 里记录的 client_id",
          posts and posts[0]["data"]["client_id"] == "cid-custom-1234")
    check("不再使用硬编码 MICROSOFT_CLIENT_ID",
          posts and posts[0]["data"]["client_id"] != auth.MICROSOFT_CLIENT_ID)
    check("重走登录链路也传同一个 client_id",
          completed == ["cid-custom-1234"])
    check("refresh_token 未被刷新响应清空",
          out is not None and out.get("refresh_token") == "RT-OLD")
    check("账号 id 不漂移", out is not None and out.get("id") == "acct-1")

    posts.clear()
    completed.clear()
    prof2 = {"id": "acct-2", "refresh_token": "RT-2"}
    auth.refresh_microsoft(prof2)
    check("老档案无记录时回退到 get_active_client_id()",
          posts and posts[0]["data"]["client_id"] == MS_CLIENT_ID
          and posts[0]["data"]["client_id"] != auth.MICROSOFT_CLIENT_ID)
check("complete_login_with_token 记录签发 client_id",
      'profile["ms_client_id"] = client_id' in read("src/core/auth.py"))


# ── 7. ModRow 销毁后的异步重排 ────────────────────────────────────────────
print("\n[7] 模组行：deleteLater 后的 QTimer 回调不得崩溃")
from PySide6.QtCore import QEvent  # noqa: E402
from src.mod_list import ModRow  # noqa: E402

row = ModRow("demo.jar", True,
             {"name": "Demo", "description": "long description " * 12})
row._desc_width = 0
row._relayout_desc()
check("未销毁时描述重排仍真的改写文本（没把功能改哑）",
      bool(row.desc_lbl.text()) and row._desc_width > 0)
row.deleteLater()
app.sendPostedEvents(None, QEvent.DeferredDelete)
try:
    row._relayout_desc()
    direct_ok = True
except RuntimeError:
    direct_ok = False
check("对象销毁后直接调 _relayout_desc 不抛", direct_ok)
try:
    row._relayout_desc_safe()
    safe_ok = True
except RuntimeError:
    safe_ok = False
check("对象销毁后 safe 入口不抛", safe_ok)
ml_tree = ast.parse(read("src/mod_list.py"))
ml_cls = next(n for n in ml_tree.body
              if isinstance(n, ast.ClassDef) and n.name == "ModRow")
init_fn = next(n for n in ml_cls.body
               if isinstance(n, ast.FunctionDef) and n.name == "__init__")
calls = [ast.get_source_segment(read("src/mod_list.py"), n) or ""
         for n in ast.walk(init_fn) if isinstance(n, ast.Call)]
check("QTimer 回调指向 safe 包装而非裸 _relayout_desc",
      any("singleShot" in c and "_relayout_desc_safe" in c for c in calls)
      and not any("singleShot" in c and "_relayout_desc_safe" not in c
                  and "singleShot" in c for c in calls))

print("\nround-210 P0 regression: %d checks, %d failed" % (total, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-210 七条 P0 行为回归）")
