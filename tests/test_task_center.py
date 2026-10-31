"""round-154 回归测试：任务中心（TaskRecord + 状态机 + 持久历史）。

重点验证「杀进程重启后历史仍在」——用同一个临时数据目录重建 TaskCenter。
Qt-free。
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import task_center as tc  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-54s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


TMP = tempfile.mkdtemp(prefix="_tc_")
tc.get_data_dir = lambda: TMP
tc._reset_for_tests()
center = tc.get_task_center()
HIST = os.path.join(TMP, "task_history.json")


def _fresh():
    tc._reset_for_tests()
    return tc.get_task_center()


# ── 1. start / update ──
t1 = center.start("download", "Alpha", target_page="instances")
check("start → running", t1.state == tc.STATE_RUNNING and t1.id)
check("未定长 ratio=0", t1.ratio() == 0.0)
center.update(t1.id, stage="正在下载依赖库", completed=3, total=10)
r = center.get(t1.id)
check("update 写入阶段/进度",
      r.stage == "正在下载依赖库" and r.ratio() == 0.3,
      "ratio=%.2f" % r.ratio())

# ── 2. finish 落盘，重启后仍在 ──
center.finish(t1.id, "下载完成")
r = center.get(t1.id)
check("finish → done", r.state == tc.STATE_DONE and r.detail == "下载完成")
check("历史文件已生成", os.path.isfile(HIST))
data = json.load(open(HIST, encoding="utf-8"))
check("历史只含已结束任务", all(x["state"] in tc._FINAL_STATES
                                for x in data["tasks"]), str(data["tasks"]))

center = _fresh()          # 模拟杀进程重启
r = center.get(t1.id)
check("重启后历史可读", r is not None and r.state == tc.STATE_DONE
      and r.label == "Alpha", str(r))
check("重启后历史列表非空", len(center.recent()) == 1)

# ── 3. 已结束任务忽略后续 update（防止迟到信号改写状态） ──
old = center.get(t1.id)
center.update(t1.id, stage="迟到的进度", completed=99, total=100)
r = center.get(t1.id)
check("结束后 update 无效", r.stage == old.stage and r.state == tc.STATE_DONE)

# ── 4. fail / cancel ──
t2 = center.start("launch", "Beta")
center.fail(t2.id, "Java 不兼容")
check("fail → failed + 原因", center.get(t2.id).state == tc.STATE_FAILED
      and center.get(t2.id).detail == "Java 不兼容")
t3 = center.start("import", "Gamma")
center.cancel(t3.id)
check("cancel → cancelled", center.get(t3.id).state == tc.STATE_CANCELLED)
check("running 为空", center.running() == [])

# ── 5. 进行中任务不落盘（避免半截任务变历史） ──
t4 = center.start("download", "Delta")
data = json.load(open(HIST, encoding="utf-8"))
check("running 不进历史文件", all(x["id"] != t4.id for x in data["tasks"]))
check("running() 能查到", [x.id for x in center.running()] == [t4.id])

# ── 6. 历史上限 50 条 ──
for i in range(60):
    t = center.start("download", "task-%d" % i)
    center.finish(t.id, "ok")
data = json.load(open(HIST, encoding="utf-8"))
check("历史裁剪到 50 条", len(data["tasks"]) == tc._KEEP_HISTORY,
      "len=%d" % len(data["tasks"]))
check("裁剪保留最新", all(x["label"] != "task-0" for x in data["tasks"]))
check("recent(5) 返回 5 条", len(center.recent(5)) == 5)

# ── 7. 清洗：坏历史文件不应崩 ──
with open(HIST, "w", encoding="utf-8") as f:
    f.write("{not json")
center = _fresh()
check("坏文件 → 空历史", center.recent() == []) 
with open(HIST, "w", encoding="utf-8") as f:
    json.dump({"version": 1, "tasks": [{"id": "", "kind": "x"},
                                       {"id": "ok", "kind": "x", "state": "done",
                                        "created_at": 1.0, "updated_at": 2.0}]}, f)
center = _fresh()
check("坏记录被丢弃", [r.id for r in center.recent()] == ["ok"],
      str([r.id for r in center.recent()]))

print()
if fails:
    print("FAILED %d: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL CHECKS PASSED")
