# -*- coding: utf-8 -*-
"""round-177：构建退出码必须由产物完整性决定，不由瘦身结果决定。

复现的真实事故：PyInstaller 已 ``Build complete``，但 ``_trim_dist`` 删第 50 个
``.qm`` 时被批量删除保护抛出的非 OSError 异常打断，异常穿透 ``except OSError``
→ ``build.py`` 退出 1。产物其实完整，极易被误判成「构建失败要重跑」。
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         (" | " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)


def make_dist(root: str, n_extra: int = 6) -> str:
    tr = os.path.join(root, "dist_beta", "AC_Launcher", "_internal",
                      "PySide6", "translations")
    os.makedirs(tr, exist_ok=True)
    for name in ("qt_zh_CN.qm", "qt_en.qm", "qt_base_en.qm"):
        with open(os.path.join(tr, name), "wb") as f:
            f.write(b"KEEP" * 16)
    for i in range(n_extra):
        with open(os.path.join(tr, "qtmultimedia_%02d.qm" % i), "wb") as f:
            f.write(b"DROP" * 16)
    with open(os.path.join(root, "dist_beta", "AC_Launcher",
                           "AC_Launcher.exe"), "wb") as f:
        f.write(b"EXE")
    return os.path.join(root, "dist_beta", "AC_Launcher")


def remaining(dist: str) -> list[str]:
    tr = os.path.join(dist, "_internal", "PySide6", "translations")
    return sorted(x for x in os.listdir(tr) if x.endswith(".qm"))


# ── 1. 正常瘦身：只删非 zh_CN / en ──────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    dist = make_dist(td, 6)
    removed, failed, saved = build._trim_dist(dist)
    left = remaining(dist)
    check("正常瘦身删掉 6 个多余 .qm", removed == 6, "removed=%d" % removed)
    check("正常瘦身无失败", failed == 0, "failed=%d" % failed)
    check("瘦身统计了节省字节", saved > 0, "saved=%d" % saved)
    check("zh_CN / en 三个 .qm 保留",
          left == ["qt_base_en.qm", "qt_en.qm", "qt_zh_CN.qm"],
          "left=%r" % left)

# ── 2. 删除抛非 OSError 异常（模拟批量删除保护）────────────────────
orig_remove = build.os.remove
for exc in (SystemExit(1), RuntimeError("bulk delete blocked"),
            OSError("permission denied")):
    calls = {"n": 0}

    def flaky(path, _exc=exc, _calls=calls):
        _calls["n"] += 1
        if _calls["n"] == 3:
            raise _exc
        return orig_remove(path)

    with tempfile.TemporaryDirectory() as td:
        dist = make_dist(td, 6)
        build.os.remove = flaky
        try:
            removed, failed, _ = build._trim_dist(dist)
        except BaseException as e:  # noqa: BLE001
            check("%s 不穿透 build.py" % type(exc).__name__, False,
                  "raised %r" % e)
        else:
            check("%s 被吞掉且不影响其余删除" % type(exc).__name__,
                  removed == 5 and failed == 1,
                  "removed=%d failed=%d" % (removed, failed))
            check("%s 后中文翻译仍在" % type(exc).__name__,
                  "qt_zh_CN.qm" in remaining(dist))
        finally:
            build.os.remove = orig_remove

# ── 3. _build 退出码：trim 失败但产物完整 → 0 ───────────────────────
orig_call = build.subprocess.call
orig_trim = build._trim_dist
orig_size = build._print_size
try:
    build.subprocess.call = lambda *a, **k: 0
    build._print_size = lambda *a, **k: (0, 0)
    build._trim_dist = lambda root: (0, 5, 0)  # 模拟全部瘦身失败

    with tempfile.TemporaryDirectory() as td:
        dist = make_dist(td, 2)
        rc = build._build(td)
        check("PyInstaller 成功 + trim 全失败仍返回 0", rc == 0,
              "rc=%d" % rc)

    with tempfile.TemporaryDirectory() as td:
        dist = make_dist(td, 2)
        os.remove(os.path.join(dist, "AC_Launcher.exe"))
        rc = build._build(td)
        check("产物缺 exe 时返回 1", rc == 1, "rc=%d" % rc)

    with tempfile.TemporaryDirectory() as td:
        dist = make_dist(td, 2)
        import shutil
        shutil.rmtree(os.path.join(dist, "_internal", "PySide6"))
        rc = build._build(td)
        check("产物缺 _internal/PySide6 时返回 1", rc == 1, "rc=%d" % rc)
finally:
    build.subprocess.call = orig_call
    build._trim_dist = orig_trim
    build._print_size = orig_size

# ── 4. 静态防再犯 ──────────────────────────────────────────────────
src = open(os.path.join(ROOT, "build.py"), encoding="utf-8").read()
check("_rm 使用 except BaseException 兜底",
      "except BaseException" in src and "except OSError:\n            pass" not in src)
check("KeyboardInterrupt 仍可穿透（不吞用户中断）",
      src.count("except KeyboardInterrupt:\n            raise") >= 2)
check("_build 末尾由产物完整性决定 rc",
      "if not os.path.isfile(os.path.join(dist, \"AC_Launcher.exe\"))" in src)

print("RESULT:", "PASS" if not FAILS else "FAIL %d: %r" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
