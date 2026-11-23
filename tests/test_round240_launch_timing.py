"""round-240：启动阶段耗时可观测性。

用户反馈「点启动后等待时间长」但启动器没有耗时日志，无法定位瓶颈。
本测试验证 _emit_step 会把「阶段 + 距上一阶段耗时」写进 launch_timing.log，
且：① 失败静默（不拦启动）② 新一轮从 check 起算（不串上一次的耗时）。

判据针对日志内容本身，不用「没报错」这种间接信号。
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


td = tempfile.mkdtemp()
import src.paths as paths  # noqa: E402
paths.get_data_dir = lambda: td

from src import launch  # noqa: E402

logp = os.path.join(td, "launch_timing.log")

print("== 1. 阶段耗时写入 ==")
launch._emit_step({}, "check")
time.sleep(0.04)
launch._emit_step({}, "install")
time.sleep(0.02)
launch._emit_step({}, "start")
lines = open(logp, encoding="utf-8").read().splitlines() if os.path.isfile(logp) else []
check("日志文件生成", len(lines) >= 3, "%d lines" % len(lines))
check("第一行是 check 且 +0", "step=check" in lines[0] and "+0 ms" in lines[0], lines[0] if lines else "")
check("第二行含 install 且耗时>0", "step=install" in lines[1] and "+0 ms" not in lines[1],
      lines[1] if len(lines) > 1 else "")
check("第三行 prev=install", "prev=install" in lines[2], lines[2] if len(lines) > 2 else "")

print("== 2. 新一轮从 check 归零 ==")
before = len(lines)
launch._emit_step({}, "check")  # 新一轮第一阶段
lines2 = open(logp, encoding="utf-8").read().splitlines()
check("新一轮 check 耗时归零", "step=check" in lines2[before] and "+0 ms" in lines2[before],
      lines2[before] if len(lines2) > before else "")

print("== 3. 失败静默 ==")
def broken_data_dir():
    raise RuntimeError("boom")
paths.get_data_dir = broken_data_dir
try:
    launch._emit_step({}, "prepare")  # 不该抛
    ok = True
except Exception as e:
    ok = False
    print("   raised:", e)
check("日志失败不影响启动流程", ok)

print("\nround-240 launch timing: 6 checks, %d failed" % len(fails))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED（启动阶段耗时可观测）")
sys.stdout.flush()
