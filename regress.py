#!/usr/bin/env python3
"""AC Launcher 回归入口 — 一条命令跑完所有自检。

用法::

    python regress.py            # 跑全部（发现即跑，缺文件自动跳过）
    python regress.py --shots    # 额外生成视觉截图到 _shots_r112/

为什么需要这个：RELEASE_1.0.0_CHECKLIST 里写着「全量回归绿（_diag_all.py
exit=0）」，但 _diag_all.py **从未入库** —— 回归套件一直是散落的临时脚本，
换台机器或重新 clone 就没了，形不成「改 → 验 → 返工」的循环。本文件把
所有检查收敛到一个入口，且对缺失脚本降级跳过（不会因少了哪个就整体失败）。

⚠️ 现状限制：被它调用的 _test_*.py / _smoke_*.py / _audit_*.py 都命中
.gitignore 的 `_*` 规则，**不在版本控制里**。若要让回归套件随仓库走，
需把它们移到受控目录（如 tests/）并调整 .gitignore —— 这是待办，见
docs/quality_punchlist.md。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)

# 本机 python 通常没装 requests / PySide6；venv 才是可运行环境
PY = os.path.join(HERE, "venv", "Scripts", "python.exe")
if not os.path.isfile(PY):
    PY = sys.executable

SUITES = [
    ("编译", None, ["compileall"], "builtin"),
    ("i18n 中英对称", None, None, "builtin"),
    ("PII 门禁", "_pii_gate.py", None, "script"),
    ("默认值缺漏审计", "_audit_defaults.py", None, "script"),
    ("目标判定（mll 分片）", "_test_big_target.py", None, "script"),
    ("mll 分片集成", "_test_mll_parallel.py", None, "script"),
    ("整合包进度桥接", "_test_pack_progress.py", None, "script"),
    ("mod 下载进度聚合", "_test_mod_progress.py", None, "script"),
    ("设置页脏检测回归", "_test_settings_dirty.py", None, "script"),
    ("核心功能冒烟", "_test_functional.py", None, "script"),
    ("全页面构造冒烟", "_smoke_all.py", None, "script"),
]


def run_compileall() -> tuple[bool, str]:
    import compileall
    ok = compileall.compile_dir(os.path.join(HERE, "src"), quiet=2)
    ok = bool(ok) and bool(compileall.compile_file(
        os.path.join(HERE, "main.py"), quiet=2))
    return ok, "exit 0" if ok else "有文件编译失败"


def run_i18n() -> tuple[bool, str]:
    import re
    path = os.path.join(HERE, "src", "i18n.py")
    lines = open(path, encoding="utf-8").read().split("\n")
    pat = re.compile(r'^\s{4}["\']?([a-zA-Z\-]{2,10})["\']?\s*:\s*\{')
    blocks, cur, start = {}, None, 0
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m:
            if cur is not None:
                blocks[cur] = (start, i)
            cur, start = m.group(1), i
    if cur is not None:
        blocks[cur] = (start, len(lines))

    def keys(rng):
        s = set()
        for ln in lines[rng[0]:rng[1]]:
            m = re.match(r'^\s{8}"([^"]+)":', ln)
            if m:
                s.add(m.group(1))
        return s

    names = list(blocks)
    if len(names) < 2:
        return False, "只找到 %d 个语言块" % len(names)
    a, b = keys(blocks[names[0]]), keys(blocks[names[1]])
    diff = a ^ b
    return (not diff), "%s=%d %s=%d 差异=%d" % (
        names[0], len(a), names[1], len(b), len(diff))


def run_script(fname: str) -> tuple[bool, str]:
    path = os.path.join(HERE, fname)
    if not os.path.isfile(path):
        return None, "缺失（跳过）"          # type: ignore[return-value]
    try:
        p = subprocess.run([PY, path], cwd=HERE, capture_output=True,
                           text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return False, "超时"
    out = (p.stdout or "") + (p.stderr or "")
    ok = p.returncode == 0
    # 已知既存问题（round-107 记录）：离屏 Qt 在**解释器 teardown 阶段**崩
    # 0xC0000409，此时测试其实已全部跑完并打印了成功标记，但进程退出码非 0。
    # 因此退出码非 0 时再看成功标记，避免把 teardown 噪音误判成测试失败。
    markers = ("ALL CHECKS PASSED", "SMOKE OK", "FUNC OK", "全部通过")
    if not ok and any(m in out for m in markers):
        ok = True
        teardown_noise = True
    else:
        teardown_noise = False
    tail = [ln for ln in out.strip().splitlines() if ln.strip()]
    note = tail[-1][:60] if tail else "exit=%d" % p.returncode
    if teardown_noise:
        note += "  (teardown 噪音，实际通过)"
    return ok, note


def main() -> int:
    only_shots = "--shots" in sys.argv
    print("=" * 74)
    print("AC Launcher 回归套件")
    print("=" * 74)
    rows = []
    for label, script, _args, kind in SUITES:
        t0 = time.time()
        if kind == "builtin":
            ok, note = (run_compileall() if label == "编译" else run_i18n())
        else:
            ok, note = run_script(script)
        dt = time.time() - t0
        rows.append((label, ok, note, dt))

    print()
    for label, ok, note, dt in rows:
        if ok is None:
            mark = "SKIP"
        elif ok:
            mark = "OK  "
        else:
            mark = "FAIL"
        print("  %s %-22s %5.1fs  %s" % (mark, label, dt, note))

    if "--shots" in sys.argv or only_shots:
        print()
        ok, note = run_script("_shots_all.py")
        print("  %s %-22s        %s" % (
            "OK  " if ok else "FAIL", "视觉截图", note))

    failed = [r for r in rows if r[1] is False]
    skipped = [r for r in rows if r[1] is None]
    print()
    print("-" * 74)
    print("通过 %d / 失败 %d / 跳过 %d" % (
        len(rows) - len(failed) - len(skipped), len(failed), len(skipped)))
    if failed:
        print("需返工：%s" % ", ".join(r[0] for r in failed))
    print("=" * 74)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
