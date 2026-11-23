"""把所有**本会话新增**的 round-240 / round-241 标记统一改成 round-243。

为什么需要这一步：本会话之前项目已经用到 round-242（启动可观测性 / 实时日志窗），
我写代码时按"记忆里的上一条注释"续了 240/241 —— 编号撞车了。注释里的 round 号是
这套工程的**变更溯源锚点**，错了会让后来人（和下一位 AI）顺着错误线索去查。

做法：逐行白名单外一律替换；白名单是**启动相关**的既有标记，必须原样保留。
带断言：改动条数、白名单行未被触碰、替换后不再有本会话的旧标记。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# 既有标记（不是本会话的），原样保留——它们的主题是"启动可观测性/实时日志窗"
KEEP_SUBSTR = (
    "游戏启动后进度框变实时日志窗",
    "live game log panel after launch",
    "round-240 可观测性",
    "游戏日志窗点「打开完整控制台」",
    "游戏起来后从「步骤列表」切到「实时日志」视图",
    "切到实时日志后为 True",
    "游戏运行中的实时日志视图",
    "日志 tail 定时器必须先停",
    "游戏运行中改为可召回",
    "apply_qss() 会重生成整棵样式表",
    "游戏退出 → 日志窗停止 tail",
)
# 整个文件都是既有标记（文件名里就带 round 号）
KEEP_FILES = {"tests/test_round240_launch_timing.py",
              "tests/test_round241_live_log.py"}

TARGETS = [
    "src/i18n.py", "src/launch.py", "src/launch_dialog.py", "src/main_window.py",
    "src/pages_instances.py", "src/panorama.py", "src/scan.py", "src/scan_dialog.py",
    "src/settings_dialog.py", "src/theme.py", "src/ui_flow.py", "src/wallpaper.py",
    "src/win_rounded.py", "tests/test_round216_regression.py",
    "tests/test_round228_batch2.py", "data/features/achievements/entry.py",
    "assets/features/achievements/entry.py",
    "_probe_ach_page.py", "_probe_page_fade.py", "_probe_retheme_veil.py",
    "CHANGELOG.md",
]

PAT = re.compile(r"round-(240|241)")
total = 0
kept = 0
per_file = {}
for rel in TARGETS:
    path = os.path.join(ROOT, rel)
    if rel in KEEP_FILES or not os.path.isfile(path):
        continue
    with io.open(path, "r", encoding="utf-8", newline="") as f:
        lines = f.readlines()
    n = 0
    out = []
    for ln in lines:
        if PAT.search(ln):
            if any(k in ln for k in KEEP_SUBSTR):
                kept += 1
            else:
                ln = PAT.sub("round-243", ln)
                n += 1
        out.append(ln)
    if n:
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.writelines(out)
        per_file[rel] = n
        total += n

for rel, n in sorted(per_file.items()):
    print("  %-46s %3d 处" % (rel, n))
print("\n共改 %d 处；保留既有标记 %d 处；涉及 %d 个文件"
      % (total, kept, len(per_file)))

# ── 自校验：改完之后不许再剩本会话的旧标记 ────────────────────────────
left = []
for rel in TARGETS:
    if rel in KEEP_FILES:
        continue
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        continue
    with io.open(path, "r", encoding="utf-8", newline="") as f:
        for i, ln in enumerate(f, 1):
            if PAT.search(ln) and not any(k in ln for k in KEEP_SUBSTR):
                left.append("%s:%d" % (rel, i))
if left:
    print("\n!! 仍有未替换：", left[:8])
    sys.exit(1)
print("自校验通过：除既有启动标记外，已无 round-240/241")
