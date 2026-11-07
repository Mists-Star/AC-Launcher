"""round-206 回归：P0 两条假死 + 占位页不漏英文裸键。

纯逻辑 + 静态契约，不联网、不真杀进程、不拉 Qt 窗口：
1. proc_kill 把多个 PID 合成**一条** taskkill（不再串行 N 次）；
2. terminate_all 把失败 / 超时结构化返回（不再 ``except: pass`` 吞掉）；
3. search_all 用 daemon 线程 + 严格总预算；慢源超时写 ``meta.partial``，
   快源结果仍保留，且总耗时不随慢源个数累加；
4. 占位页四个键中英齐全、body 用独立键、不再把内部 key 当文案。
"""
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import net_api  # noqa: E402
from src.core import proc_kill  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def _read(rel):
    with open(os.path.join(HERE, rel), "r", encoding="utf-8") as f:
        return f.read()


# ── 1. 批量强杀：一条命令、去重、空列表不出命令 ──
args = proc_kill.build_taskkill_args([111, 222, 333])
check("三个 PID 合成一条 taskkill",
      args[:3] == ["taskkill", "/F", "/T"] and args.count("/PID") == 3)
check("PID 去重并过滤非法值",
      proc_kill.build_taskkill_args([111, 111, 0, "x"]).count("/PID") == 1)
check("空列表不产生命令", proc_kill.build_taskkill_args([]) == [])


class _Proc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None

    def kill(self):
        raise RuntimeError("kill denied")


class _BadResult:
    returncode = 1
    stdout = b""
    stderr = b"access denied"


_orig_sys = proc_kill.sys
_orig_run = proc_kill.subprocess.run

# 非 Windows 分支：kill() 抛异常必须逐项回报，而不是静默吞掉
proc_kill.sys = types.SimpleNamespace(platform="linux")
try:
    r = proc_kill.terminate_all([_Proc(1), _Proc(2)])
finally:
    proc_kill.sys = _orig_sys
check("kill 失败逐项回报", r["attempted"] == 2 and r["failed"] == [1, 2]
      and len(r["errors"]) == 2, str(r["errors"]))

# Windows 分支：taskkill 非零退出要带原因
proc_kill.subprocess.run = lambda *a, **kw: _BadResult()
proc_kill.sys = types.SimpleNamespace(platform="win32")
try:
    r2 = proc_kill.terminate_all([_Proc(11), _Proc(22)])
finally:
    proc_kill.subprocess.run = _orig_run
    proc_kill.sys = _orig_sys
check("taskkill 非零退出也报错", r2["failed"] == [11, 22]
      and any("access denied" in e for e in r2["errors"]))

# 5 个进程只发一次外部命令（旧实现是 5 次，每次 timeout=10）
calls = []


def _record(args, **kw):
    calls.append(args)
    return _BadResult()


proc_kill.subprocess.run = _record
proc_kill.sys = types.SimpleNamespace(platform="win32")
try:
    proc_kill.terminate_all([_Proc(i) for i in range(1, 6)])
finally:
    proc_kill.subprocess.run = _orig_run
    proc_kill.sys = _orig_sys
check("5 个进程只发 1 次命令",
      len(calls) == 1 and calls[0].count("/PID") == 5)

mw = _read("src/main_window.py")
check("首页与取消启动共用批量入口", mw.count("terminate_all(") >= 2)
check("不再有串行 taskkill 循环",
      '["taskkill", "/F", "/T", "/PID", str(p.pid)]' not in mw
      and '["taskkill", "/F", "/T", "/PID", str(proc.pid)]' not in mw)
check("强杀前先给可见反馈",
      "status.game_killing" in mw and "QApplication.processEvents()" in mw)
check("失败不再全吞",
      "status.game_kill_partial" in mw)

# ── 2. 搜索：daemon 线程 + 严格总预算 + partial 出参 ──
api = _read("src/net_api.py")
i = api.find("def search_all")
snip = api[i:api.find("def _norm_title", i)]
check("不再用线程池 executor（退出会被 join）",
      "from concurrent.futures" not in snip
      and "ex = ThreadPoolExecutor" not in snip
      and "ex.shutdown" not in snip)
check("改用 daemon 线程", "daemon=True" in snip)
check("单调时钟扣减总预算",
      "time.monotonic()" in snip and "th.join(" in snip)
check("部分结果写出参",
      'meta["partial"]' in snip and 'meta["timed_out"]' in snip)

_orig = {
    "search_mods": net_api.search_mods,
    "search_curseforge": net_api.search_curseforge,
    "curseforge_available": net_api.curseforge_available,
    "curseforge_keyless_enabled": net_api.curseforge_keyless_enabled,
    "_SEARCH_BUDGET": net_api._SEARCH_BUDGET,
}


def _fast(*a, **kw):
    return [{"slug": "alpha", "title": "Alpha", "source": "modrinth",
             "description": "fast"}]


def _slow(*a, **kw):
    time.sleep(0.6)
    return []


def _restore():
    for key, value in _orig.items():
        setattr(net_api, key, value)


try:
    net_api.search_mods = _fast
    net_api.search_curseforge = _slow
    net_api.curseforge_available = lambda: True
    net_api.curseforge_keyless_enabled = lambda: False
    net_api._SEARCH_BUDGET = 0.15
    meta = {}
    rows = net_api.search_all("q", meta=meta)
    check("慢源超时但快源结果保留",
          len(rows) == 1 and rows[0]["slug"] == "alpha")
    check("partial 只列超时的源",
          meta.get("partial") is True
          and meta.get("timed_out") == ["CurseForge"], str(meta))
finally:
    _restore()

try:
    net_api.search_mods = _slow
    net_api.search_curseforge = _slow
    net_api.curseforge_available = lambda: True
    net_api.curseforge_keyless_enabled = lambda: False
    net_api._SEARCH_BUDGET = 0.15
    t0 = time.monotonic()
    net_api.search_all("q", meta={})
    dt = time.monotonic() - t0
finally:
    _restore()
# 逐个 join(0.15) 会耗 0.30s；单调时钟扣减只等 0.15s。
check("两源都慢也不累加等待（<0.25s）", dt < 0.25, "%.3fs" % dt)

browse = _read("src/pages_browse.py")
check("UI 显示部分结果提示",
      "store.partial" in browse and "_search_meta" in browse)

# ── 3. 占位页：中英键齐全、body 独立、不回显内部 key ──
i18n_src = _read("src/i18n.py")
ph_keys = ("pcl2.ph_launch_title", "pcl2.ph_launch_body",
           "pcl2.ph_download_title", "pcl2.ph_download_body",
           "pcl2.ph_default_title", "status.game_killing",
           "status.game_kill_partial", "store.partial")
for key in ph_keys:
    check("中英都有 " + key, i18n_src.count('"%s"' % key) == 2)
check("body 不再误用 title 键",
      '"launch": "pcl2.ph_launch_body"' in mw
      and '"download": "pcl2.ph_download_body"' in mw)
check("占位页不再把内部 key 当文案",
      "t(title_key, default=key)" not in mw
      and "if title_key else key" not in mw)
check("联机占位文案去掉开发术语", "主线程写完" not in i18n_src)

print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ALL CHECKS PASSED（round-206 假死 / 占位页）")
