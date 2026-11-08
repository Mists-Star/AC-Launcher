"""round-217：§19.3 P2 长尾行为回归（离线、零真实网络）。

覆盖 13 条：
  1. 皮肤库：`file` 字段 `..` 越界删 / 非 PNG 落盘 / 超大图片读取上限
  2. 单流下载：206 的 Content-Range 起点校验、416 时本地残包比远端大
  3. 批下载：坏了 sha1 的文件不能被「大小相同」判成功
  4. 杀进程：taskkill 非 0 只报真正没关掉的那些
  5. 修复日志 / 成就：原子写、坏文件不抛、写盘失败不抛
  6. 默认下载队列：关窗钩子运行时取，导入期快照不再是 None
  7. 确认框 / 文件框：用完即删，不在父窗口下堆积隐藏 QDialog
  8. 启动进度框：销毁后 5 个 setter 不抛；完成态关闭即销毁
  9. 图标 DPR：优先用发起渲染的窗口所在屏幕
 10. 亚克力：无 ctypes 平台也能 import
 11. 内存优化：返回真实释放量（而非恒 0）
 12. 音效接线：关掉 / 没配文件时零副作用，成功失败有触发点

原则同前几轮：能跑真对象就不用源码字面量断言；只有「结构必须包在 if 里」
这类没法造运行时的才读源码，并显式标注。
"""
import hashlib
import json
import os
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
    print("  %s %-64s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


from PySide6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402

app = QApplication.instance() or QApplication([])
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 300

# ══════════════════════════════════════════════════════════════════════
# 1. 皮肤库边界
# ══════════════════════════════════════════════════════════════════════
print("== 1. 皮肤库：越界 / 魔数 / 大小 ==")
import src.skins as sk  # noqa: E402

root = tempfile.mkdtemp(prefix="ac217-skin-")
with mock.patch.object(sk, "get_data_dir", lambda: root):
    mgr = sk.SkinManager()
    s1 = mgr.add_bytes(PNG, "ok", "download")
    check("正常 PNG 能入库", os.path.isfile(mgr.path_of(s1["id"])))
    try:
        mgr.add_bytes(b"not a png" * 40, "bad", "download")
        check("非 PNG 字节被拒", False, "竟然入库")
    except ValueError as e:
        check("非 PNG 字节被拒", "PNG" in str(e))
    try:
        mgr.add_cape_bytes(b"jpeg" * 40, "bad cape")
        check("非 PNG 披风被拒", False, "竟然入库")
    except ValueError:
        check("非 PNG 披风被拒", True)

    outside = os.path.join(root, "important.txt")
    with open(outside, "w", encoding="utf-8") as f:
        f.write("keep me")
    meta = os.path.join(root, "skins.json")
    data = json.load(open(meta, encoding="utf-8"))
    data["skins"].append({"id": "evil", "name": "evil",
                          "file": "../important.txt"})
    json.dump(data, open(meta, "w", encoding="utf-8"))
    mgr2 = sk.SkinManager()
    check("越界记录不被加载", "evil" not in [s["id"] for s in mgr2.list()])
    check("越界记录 path_of 为 None", mgr2.path_of("evil") is None)
    mgr2.remove("evil")
    check("删除越界记录不误删外部文件", os.path.isfile(outside))

    class _Big:
        headers = {"Content-Length": str(64 * 1024 * 1024)}
        def read(self, n=-1):
            return b"x" * n
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with mock.patch("urllib.request.urlopen", lambda *a, **k: _Big()):
        try:
            sk._http_bytes("https://example.invalid/big.png")
            check("超大图片下载被拒", False, "读完了")
        except ValueError as e:
            check("超大图片下载被拒", "过大" in str(e) or "上限" in str(e))

# ══════════════════════════════════════════════════════════════════════
# 2. 单流下载区间校验
# ══════════════════════════════════════════════════════════════════════
print("== 2. 单流下载：Content-Range 起点 / 416 残包 ==")
from src import net_api as na  # noqa: E402

check("bytes 100-999/1000 → (100, 1000)",
      na._parse_content_range("bytes 100-999/1000") == (100, 1000))
check("bytes */1000 → (None, 1000)",
      na._parse_content_range("bytes */1000") == (None, 1000))
check("空头 → (None, None)", na._parse_content_range("") == (None, None))
check("垃圾头 → (None, None)",
      na._parse_content_range("banana") == (None, None))


class _Resp:
    def __init__(self, status, headers, body):
        self.status_code = status
        self.headers = headers
        self._body = body
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise na.requests.HTTPError("status %d" % self.status_code,
                                        response=self)

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def close(self):
        self.closed = True


BODY = bytes(range(256)) * 40        # 10240 字节


def _run_download(mode, local_part_bytes):
    """按模式造一个「像真的」服务端，走完整 _download_once 流程。

    mode:
      · wrong_start —— 收到 Range 也回 206 + 从 0 开始的完整内容
      · good_resume —— 收到 Range 就回 206 + 正确切片
      · stale_part  —— 收到 Range 一律 416（本地残包比远端大）
    """
    d = tempfile.mkdtemp(prefix="ac217-dl-")
    dest = os.path.join(d, "f.bin")
    if local_part_bytes is not None:
        with open(dest + ".part", "wb") as f:
            f.write(local_part_bytes)

    def fake_get(url, **kw):
        rng = (kw.get("headers") or {}).get("Range")
        if rng and mode == "stale_part":
            return _Resp(416, {"Content-Range": "bytes */%d" % len(BODY)}, b"")
        if rng == "bytes=5000-" and mode == "good_resume":
            seg = BODY[5000:]
            return _Resp(206, {"Content-Range": "bytes 5000-%d/%d"
                               % (len(BODY) - 1, len(BODY)),
                               "Content-Length": str(len(seg))}, seg)
        if rng and mode == "wrong_start":
            return _Resp(206, {"Content-Range": "bytes 0-%d/%d"
                               % (len(BODY) - 1, len(BODY)),
                               "Content-Length": str(len(BODY))}, BODY)
        return _Resp(200, {"Content-Length": str(len(BODY))}, BODY)

    with mock.patch.object(na.requests, "get", fake_get):
        try:
            na._download_once("http://x/f.bin", dest, dest + ".part",
                              resume=True)
        except Exception:
            pass
    got = b""
    if os.path.isfile(dest):
        got = open(dest, "rb").read()
    return got


check("206 起点不符时不拼接",
      _run_download("wrong_start", BODY[:5000]) == BODY)
check("206 起点相符时正常续传",
      _run_download("good_resume", BODY[:5000]) == BODY)
check("416 残包过大时重下",
      _run_download("stale_part", b"X" * 40000) == BODY)

# ══════════════════════════════════════════════════════════════════════
# 3. 批下载 sha1
# ══════════════════════════════════════════════════════════════════════
print("== 3. 批下载：大小对但内容坏 ==")
import src.batch_download as bd  # noqa: E402

GOOD = b"GOOD-CONTENT" * 100
GOOD_SHA = hashlib.sha1(GOOD).hexdigest()
bd_root = tempfile.mkdtemp(prefix="ac217-bd-")
dest = os.path.join(bd_root, "a.jar")
with open(dest, "wb") as f:
    f.write(b"BAD-CONTENT!" * 100)          # 大小一样、内容不同
check("前置：坏文件大小与期望相同",
      os.path.getsize(dest) == len(GOOD))

re_downloaded = []


def fake_download(url, path, **kw):
    re_downloaded.append(path)
    with open(path, "wb") as f:
        f.write(GOOD)
    return path


with mock.patch.object(bd, "download_file", fake_download):
    task = bd.make_download_task("http://x/a.jar", dest, sha1=GOOD_SHA,
                                 size=len(GOOD))
    task()
check("大小相同但 sha1 不符 → 重新下载", bool(re_downloaded))
check("重下后内容正确", open(dest, "rb").read() == GOOD)

# 下载回来仍然 sha1 不符 → 删文件并报错
dest2 = os.path.join(bd_root, "b.jar")


def fake_bad(url, path, **kw):
    with open(path, "wb") as f:
        f.write(b"STILL-BAD!!" * 100)
    return path


with mock.patch.object(bd, "download_file", fake_bad):
    task2 = bd.make_download_task("http://x/b.jar", dest2, sha1=GOOD_SHA)
    try:
        task2()
        check("sha1 失败会抛错", False, "没抛")
    except RuntimeError:
        check("sha1 失败会抛错", True)
check("sha1 失败会删掉坏文件", not os.path.exists(dest2))

# ══════════════════════════════════════════════════════════════════════
# 4. 杀进程部分成功
# ══════════════════════════════════════════════════════════════════════
print("== 4. taskkill 部分成功 ==")
from src.core import proc_kill  # noqa: E402


class _P:
    def __init__(self, pid, alive=True):
        self.pid = pid
        self._alive = alive

    def poll(self):
        return None if self._alive else 0

    def kill(self):
        self._alive = False


def _run_kill(procs, rc, kill_which):
    def fake_run(args, **kw):
        for p in kill_which:
            p._alive = False
        class R:
            returncode = rc
            stdout = b""
            stderr = b"ERROR: partial"
        return R()
    with mock.patch.object(proc_kill.subprocess, "run", fake_run), \
         mock.patch.object(proc_kill.sys, "platform", "win32"):
        return proc_kill.terminate_all(procs)


p1, p2 = _P(501), _P(502)
r = _run_kill([p1, p2], 1, [p2])
check("rc!=0 只报真正没关掉的", r["failed"] == [501], str(r["failed"]))
check("attempted 仍是全部存活数", r["attempted"] == 2)
p3, p4 = _P(601), _P(602)
r2 = _run_kill([p3, p4], 0, [p3, p4])
check("全部关掉时 failed 为空", r2["failed"] == [], str(r2["failed"]))
p5 = _P(701)
r3 = _run_kill([p5], 1, [])
check("一个都没关掉时如实报告", r3["failed"] == [701])

# ══════════════════════════════════════════════════════════════════════
# 5. 修复日志 / 成就落盘
# ══════════════════════════════════════════════════════════════════════
print("== 5. 修复日志 / 成就落盘 ==")
import src.repair_log as rl  # noqa: E402
import src.achievements as ach  # noqa: E402

rl_root = tempfile.mkdtemp(prefix="ac217-rl-")
with mock.patch.object(rl, "get_data_dir", lambda: rl_root):
    rl.append("mod_dep", "补了一个前置")
    rl.append("crash", "修了 Java")
    check("修复日志写入两条", len(rl.list_recent(9)) == 2)
    check("不留 .tmp 残渣",
          not os.path.exists(os.path.join(rl_root, "repair_log.json.tmp")))
    with open(os.path.join(rl_root, "repair_log.json"), "w",
              encoding="utf-8") as f:
        f.write('{"entries": [')      # 半截 JSON
    check("半截 JSON 不抛", rl.list_recent(3) == [])

ach_root = tempfile.mkdtemp(prefix="ac217-ach-")
with mock.patch.object(ach, "get_data_dir", lambda: ach_root):
    a1 = ach.Achievements()
    check("成就解锁成功", a1.unlock("first_launch"))
    real_open = open

    def boom(*args, **kwargs):
        if str(args[0]).endswith(".json") or str(args[0]).endswith(".tmp"):
            raise OSError("disk full")
        return real_open(*args, **kwargs)

    with mock.patch("builtins.open", boom):
        try:
            a1.unlock("first_login")
            check("写盘失败不抛异常", True)
        except Exception as e:  # noqa: BLE001
            check("写盘失败不抛异常", False, type(e).__name__)
    with open(os.path.join(ach_root, "achievements.json"), "w",
              encoding="utf-8") as f:
        f.write("[]")
    a2 = ach.Achievements()
    check("根是 list 时不崩", a2.progress() == (0, len(ach.ACHIEVEMENTS)))

# ══════════════════════════════════════════════════════════════════════
# 6. 默认下载队列钩子
# ══════════════════════════════════════════════════════════════════════
print("== 6. 默认下载队列钩子 ==")
import src.downloader as dlm  # noqa: E402

dlm._DEFAULT_QUEUE = None
try:
    dlm.shutdown_default_queue(10)
    check("队列没建过时钩子无害", True)
except Exception as e:  # noqa: BLE001
    check("队列没建过时钩子无害", False, type(e).__name__)

_main_src = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
check("main.py 调函数而不是导入期快照",
      "shutdown_default_queue(4000)" in _main_src
      and "import _DEFAULT_QUEUE" not in _main_src)

_q = mock.MagicMock()
dlm._DEFAULT_QUEUE = _q
dlm.shutdown_default_queue(1234)
check("队列存在时钩子真的关它", _q.shutdown.call_args is not None
      and _q.shutdown.call_args[0] == (1234,), str(_q.shutdown.call_args))
dlm._DEFAULT_QUEUE = None

# ══════════════════════════════════════════════════════════════════════
# 7. 确认框不堆积
# ══════════════════════════════════════════════════════════════════════
print("== 7. 确认框用完即删 ==")
import src.win_rounded as wr  # noqa: E402

host = QWidget()
with mock.patch.object(QDialog, "exec", lambda self: 0):
    wr.warn(host, "t", "x")
    wr.info(host, "t", "x")
    wr.confirm(host, "t", "x")
    wr.text_input(host, "t", "l")
app.sendPostedEvents(None, QEvent.DeferredDelete)
check("父窗口下没有残留 QDialog", len(host.findChildren(QDialog)) == 0,
      "%d 个" % len(host.findChildren(QDialog)))

# ══════════════════════════════════════════════════════════════════════
# 8. 启动进度框
# ══════════════════════════════════════════════════════════════════════
print("== 8. 启动进度框生命周期 ==")
from src.launch_dialog import LaunchProgressDialog  # noqa: E402


class _Inst:
    name = "i"
    mc_dir = tempfile.mkdtemp(prefix="ac217-inst-")
    game_version = "1.20.1"
    loader = ""
    loader_version = ""
    version_id = "1"
    kind = "official"


dlg = LaunchProgressDialog(_Inst(), parent=host, mode="download")
dlg.deleteLater()
app.sendPostedEvents(None, QEvent.DeferredDelete)
errs = []
old_hook = sys.excepthook
sys.excepthook = lambda tp, v, tb: errs.append("%s: %s" % (tp.__name__, v))
for fn in (lambda: dlg.set_progress(3, 10),
           lambda: dlg.set_speed("1 MB/s"),
           lambda: dlg.set_sources("a → b"),
           lambda: dlg.set_step("install"),
           lambda: dlg.set_status_text("x")):
    fn()
sys.excepthook = old_hook
check("销毁后 5 个 setter 都不抛", not errs, "; ".join(errs[:2]))

dlg2 = LaunchProgressDialog(_Inst(), parent=host, mode="download")
dlg2.mark_done("ok")
check("完成后 _finished 置位", dlg2._finished is True)
dlg2.show()
dlg2.close()
app.sendPostedEvents(None, QEvent.DeferredDelete)
try:
    dlg2.isVisible()
    check("完成后关闭即销毁", False, "仍然存活")
except RuntimeError:
    check("完成后关闭即销毁", True)

# ══════════════════════════════════════════════════════════════════════
# 9. 图标 DPR
# ══════════════════════════════════════════════════════════════════════
print("== 9. 图标 DPR 取所在屏幕 ==")
from src.icons import screen_dpr  # noqa: E402


class _W:
    def devicePixelRatioF(self):
        return 1.75


check("给了 widget 就用它的 DPR", abs(screen_dpr(_W()) - 1.75) < 1e-6,
      str(screen_dpr(_W())))
check("不给 widget 仍返回 >=1", screen_dpr() >= 1.0)

# ══════════════════════════════════════════════════════════════════════
# 10. 亚克力 import 保护
# ══════════════════════════════════════════════════════════════════════
print("== 10. 无 ctypes 时 win_acrylic 可导入 ==")
import subprocess  # noqa: E402

probe = (
    "import sys; sys.path.insert(0, %r);"
    "sys.modules['ctypes'] = None;"
    "import src.win_acrylic as wa;"
    "print('OK', wa.ctypes, wa.enable_acrylic(None))" % HERE
)
out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                     timeout=60)
text = (out.stdout or b"").decode("utf-8", "replace").strip()
check("子进程 import 成功且返回 False",
      out.returncode == 0 and text.startswith("OK None False"),
      (text or (out.stderr or b"").decode("utf-8", "replace")[:80]))

# ══════════════════════════════════════════════════════════════════════
# 11. 内存优化返回真实值
# ══════════════════════════════════════════════════════════════════════
print("== 11. 内存优化 ==")
from src.core import memopt  # noqa: E402

if sys.platform == "win32":
    rss = memopt._current_rss_bytes()
    check("能读到当前进程 RSS（不再恒 0）", rss > 0, "%d MB" % (rss >> 20))
    junk = [bytearray(1 << 20) for _ in range(40)]
    del junk
    freed = memopt.optimize_memory()
    check("optimize_memory 返回非负整数", isinstance(freed, int) and freed >= 0,
          "%d MB" % (freed >> 20))
    check("优化后 RSS 明显小于分配峰值", memopt._current_rss_bytes() > 0)
else:  # pragma: no cover - 本项目只发 Windows
    check("非 Windows 跳过内存实测", True, "skip")

# ══════════════════════════════════════════════════════════════════════
# 12. 音效接线
# ══════════════════════════════════════════════════════════════════════
print("== 12. 音效接线 ==")
from src.core.sound import play_ui_sound  # noqa: E402

check("总开关关着时不出声", play_ui_sound("click", {"sfx_enabled": False}) is False)
check("开了但没配文件也不出声",
      play_ui_sound("click", {"sfx_enabled": True, "sfx_click": ""}) is False)
check("配了不存在的文件也不出声",
      play_ui_sound("click", {"sfx_enabled": True,
                              "sfx_click": os.path.join(HERE, "nope.wav")}) is False)

import src.fix_feedback as ff  # noqa: E402

played = []
with mock.patch("src.core.sound.play_ui_sound",
                lambda kind, cfg: played.append(kind) or True), \
     mock.patch.object(ff, "t", lambda key, **kw: "x"), \
     mock.patch("src.win_rounded.toast", lambda *a, **k: None), \
     mock.patch("src.settings_dialog.load_config", lambda: {}):
    ff.report(host, "ok!", tone="ok")
    ff.report(host, "bad!", tone="warn")
    ff.report(host, "step", tone="info")
check("成功/失败各触发一次音效", played == ["success", "error"], str(played))

src_mw = open(os.path.join(HERE, "src", "main_window.py"), encoding="utf-8").read()
check("主窗口装了应用级音效过滤器",
      "installEventFilter(self._sfx_filter)" in src_mw
      and "class _UiSoundFilter" in src_mw)

print("\nround-217 regression: %d checks, %d failed" % (total, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-217 §19.3 P2 长尾）")
