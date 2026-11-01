"""round-170 回归测试：启动命令双件套 / 正式版优先 / 目录向导 / 下载暂停重试。

覆盖：
  1. apply_wrapper：空前缀、前缀式、{java} 插入位置；
  2. run_pre_launch_cmd：空命令、成功、非零退出、超时；
  3. mod_updater：有正式版时优先正式版，无正式版回退首条；
  4. 目录丢失向导：新建空目录 / 取消 / 打开位置；
  5. 下载对话框暂停/继续/重试按钮与状态；
  6. TaskCenter paused 是开路状态（可继续、可结束）。
"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AC_DEV_TEMP"] = "1"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.i18n import t  # noqa: E402
from src.launch import apply_wrapper, run_pre_launch_cmd  # noqa: E402
from src.instances import Instance  # noqa: E402
from src.launch_dialog import LaunchProgressDialog  # noqa: E402
from src.core.task_center import (  # noqa: E402
    TaskCenter, STATE_PAUSED, STATE_RUNNING, STATE_DONE)
import src.mod_updater as mu  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


print("== round-170 启动命令双件套 ==")

cmd = ["java", "-Xmx2G", "-jar", "client.jar"]

# ── 1. apply_wrapper ─────────────────────────────────────────────────────
check("空 wrapper 原样返回", apply_wrapper(cmd, "") == cmd)
check("纯空白 wrapper 原样返回", apply_wrapper(cmd, "   ") == cmd)

out = apply_wrapper(cmd, "mangohud {java}")
inner = out[-1]
check("包装走系统 shell", out[0] in ("cmd", "/bin/sh"), out[0])
check("{java} 指定插入位置", inner.startswith("mangohud ") and "-Xmx2G" in inner, inner)
check("{java} 被替换为完整 Java 命令", inner.count("java") == 1 and "client.jar" in inner,
      inner)

out2 = apply_wrapper(cmd, "prime-run")
inner2 = out2[-1]
check("无 {java} 时作为前缀", inner2.startswith("prime-run ") and "-Xmx2G" in inner2, inner2)

out3 = apply_wrapper(cmd, "runwrap {java} --")
inner3 = out3[-1]
check("{java} 非首位插入", inner3.startswith("runwrap ") and "-Xmx2G" in inner3
      and inner3.endswith("--"), inner3)

# ── 2. run_pre_launch_cmd ────────────────────────────────────────────────
ok, why = run_pre_launch_cmd("")
check("空命令直接成功", ok is True and why == "")

ok2, why2 = run_pre_launch_cmd("echo hello")
check("成功命令返回 True", ok2 is True and why2 == "", why2)

ok3, why3 = run_pre_launch_cmd("exit 7")
check("非零退出返回 False 且带码", ok3 is False and "7" in why3, why3)

_slow = '"%s" -c "import time;time.sleep(5)"' % sys.executable
ok4, why4 = run_pre_launch_cmd(_slow, timeout=1)
check("超时返回 False 且提示超时", ok4 is False and ("超时" in why4 or "timed out" in why4), why4)

print("== round-170 Modrinth 正式版优先 ==")

versions = [
    {"version_type": "beta", "_file": ("demo-2.0-beta.jar", "https://x/beta.jar")},
    {"version_type": "release", "_file": ("demo-1.5.jar", "https://x/rel.jar")},
]
mu.scan_installed_mods = lambda inst: ["demo-1.0.jar"]
mu.get_project_info = lambda slug: {"id": "pid1", "title": "Demo"}
mu._modrinth_versions = lambda pid, mc, ld: versions
mu._version_primary_file = lambda v, pid: v["_file"]

inst = Instance(id="upd", name="Upd", game_version="1.20.1")
res = mu.check_updates(inst)
check("正式版优先（跳过 beta）", res["count"] == 1
      and res["updates"][0]["url"] == "https://x/rel.jar", str(res["updates"]))
check("更新条目标题/项目 id", res["updates"][0]["project_id"] == "pid1"
      and res["updates"][0]["title"] == "Demo")

versions_only_beta = [
    {"version_type": "beta", "_file": ("demo-2.0-beta.jar", "https://x/beta.jar")},
]
mu._modrinth_versions = lambda pid, mc, ld: versions_only_beta
res2 = mu.check_updates(inst)
check("无正式版回退首条（beta）", res2["count"] == 1
      and res2["updates"][0]["url"] == "https://x/beta.jar", str(res2["updates"]))

versions_same = [
    {"version_type": "release", "_file": ("demo-1.0.jar", "https://x/same.jar")},
]
mu._modrinth_versions = lambda pid, mc, ld: versions_same
res3 = mu.check_updates(inst)
check("文件名相同不算更新", res3["count"] == 0, str(res3["updates"]))

print("== round-170 目录丢失向导 ==")

import src.win_rounded as wr  # noqa: E402
from src.main_window import MainWindow  # noqa: E402

parent_widget = QWidget()
asked = {}
toasts = []


def fake_ask(parent, title, text, buttons=(), detail="", icon="warning"):
    asked["title"] = title
    asked["text"] = text
    asked["buttons"] = tuple(buttons)
    return asked.get("answer")


wr.ask = fake_ask
wr.toast = lambda *a, **k: toasts.append(a)
# 方法内部 `from .win_rounded import ask, toast` 是每次调用时导入，
# 所以替换模块属性即可生效。

tmp = tempfile.mkdtemp(prefix="ac_dirwiz_")
missing = os.path.join(tmp, "gone", "game")

asked["answer"] = t("launch.dir_new")
ok_new = MainWindow._resolve_missing_game_dir(parent_widget, inst, missing)
check("新建空目录 → 返回 True", ok_new is True and os.path.isdir(missing))
check("向导按钮三选（取消/打开/新建）", len(asked["buttons"]) == 3, str(asked["buttons"]))
check("向导文案含实例名", "Upd" in asked["text"], asked["text"])

missing2 = os.path.join(tmp, "gone2", "game")
asked["answer"] = t("common.cancel")
ok_cancel = MainWindow._resolve_missing_game_dir(parent_widget, inst, missing2)
check("取消 → 返回 False 且不建目录",
      ok_cancel is False and not os.path.exists(missing2))

opened = []
if sys.platform == "win32":
    _orig_startfile = getattr(os, "startfile")
    os.startfile = lambda p: opened.append(p)
missing3 = os.path.join(tmp, "gone3", "game")
asked["answer"] = t("launch.dir_open")
ok_open = MainWindow._resolve_missing_game_dir(parent_widget, inst, missing3)
if sys.platform == "win32":
    os.startfile = _orig_startfile
check("打开位置 → 返回 False（不启动）", ok_open is False)
if sys.platform == "win32":
    check("打开的是最近现存上级目录",
          opened and opened[0] == tmp, str(opened))

print("== round-170 下载暂停/继续/重试 ==")

dl = LaunchProgressDialog(inst, mode="download")
signals = {"pause": 0, "resume": 0, "retry": 0}
dl.pause_requested.connect(lambda: signals.__setitem__("pause", signals["pause"] + 1))
dl.resume_requested.connect(lambda: signals.__setitem__("resume", signals["resume"] + 1))
dl.retry_requested.connect(lambda: signals.__setitem__("retry", signals["retry"] + 1))

check("下载对话框有暂停按钮", dl.pause_btn.isVisibleTo(dl))
dl.pause_btn.click()
check("点暂停发 pause_requested", signals["pause"] == 1)
check("暂停后按钮暂时禁用（防连点）", dl.pause_btn.isEnabled() is False)

dl.mark_paused()
check("mark_paused → 按钮变「继续下载」",
      dl.pause_btn.text() == t("launch.resume_download"), dl.pause_btn.text())
check("暂停状态文案", "暂停" in dl.status_lbl.text(), dl.status_lbl.text())
dl.pause_btn.click()
check("点继续发 resume_requested", signals["resume"] == 1)

dl.mark_resumed()
check("mark_resumed → 按钮回「暂停下载」",
      dl.pause_btn.text() == t("launch.pause_download"), dl.pause_btn.text())

dl.mark_failed("boom")
check("失败后显示重试按钮", dl.retry_btn.isVisibleTo(dl))
check("失败后隐藏暂停按钮", not dl.pause_btn.isVisibleTo(dl))
check("失败后取消按钮变「关闭」",
      dl.cancel_btn.text() == t("common.close"), dl.cancel_btn.text())
dl.retry_btn.click()
check("点重试发 retry_requested", signals["retry"] == 1)

dl.show()
dl.cancel_btn.click()
check("失败态点关闭直接关窗", dl.isVisible() is False)

ln = LaunchProgressDialog(inst, mode="launch")
check("启动模式不显示暂停按钮", not ln.pause_btn.isVisibleTo(ln))

print("== round-170 任务中心 paused ==")

tc = TaskCenter()
task = tc.start("download", "demo")
tc.update(task.id, state="paused")
check("running → paused", tc.get(task.id).state == STATE_PAUSED)
check("paused 属于进行中任务", any(r.id == task.id for r in tc.running("download")))
tc.update(task.id, state="running")
check("paused → running 可继续", tc.get(task.id).state == STATE_RUNNING)
tc.finish(task.id, "done")
check("paused 链路可正常结束", tc.get(task.id).state == STATE_DONE)
tc.update(task.id, state="running")
check("结束后 update 不复活", tc.get(task.id).state == STATE_DONE)

print("== round-170 i18n 键 ==")
for key in ("settings.pre_launch_cmd", "settings.pre_launch_hint",
            "settings.wrapper_cmd", "settings.wrapper_ph", "settings.wrapper_hint",
            "launch.pre_cmd_running", "launch.pre_cmd_timeout",
            "err.pre_launch_failed", "launch.pause_download",
            "launch.resume_download", "launch.retry_download",
            "launch.dl_paused", "launch.resuming", "launch.resume_wait",
            "launch.retry_wait", "launch.dl_failed_retry",
            "launch.dir_missing_title", "launch.dir_missing_msg",
            "launch.dir_new", "launch.dir_open", "launch.dir_new_failed",
            "launch.dir_created", "status.download_paused",
            "instances.task_paused"):
    val = t(key)
    check("i18n %s" % key, bool(val) and val != key, val)

print()
if fails:
    print("FAILED %d:" % len(fails))
    for f in fails:
        print(" - %s" % f)
    sys.exit(1)
print("全部通过")
