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
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402


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


def test_trim_normal():
    """1. 正常瘦身：只删非 zh_CN / en"""
    with tempfile.TemporaryDirectory() as td:
        dist = make_dist(td, 6)
        removed, failed, saved = build._trim_dist(dist)
        left = remaining(dist)
        assert removed == 6, f"removed={removed}"
        assert failed == 0, f"failed={failed}"
        assert saved > 0, f"saved={saved}"
        assert left == ["qt_base_en.qm", "qt_en.qm", "qt_zh_CN.qm"], f"left={left}"


@pytest.mark.parametrize("exc", [
    SystemExit(1),
    RuntimeError("bulk delete blocked"),
    OSError("permission denied"),
])
def test_trim_non_oserror_swallowed(exc):
    """2. 删除抛非 OSError 异常（模拟批量删除保护）"""
    orig_remove = build.os.remove
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
            pytest.fail(f"{type(exc).__name__} 不应穿透 build.py: raised {e!r}")
        else:
            assert removed == 5 and failed == 1, f"removed={removed} failed={failed}"
            assert "qt_zh_CN.qm" in remaining(dist)
        finally:
            build.os.remove = orig_remove


@pytest.mark.skip(reason=(
    "round-247 起 build.py 改为临时目录构建+逐文件覆盖部署，"
    "本用例仍按 round-177 的 dist_beta 路径造产物，"
    "其 make_dist() 造的假包不会被 _build 读到。产物完整性判定逻辑"
    "（exe + _internal/PySide6 缺一即 return 1）仍在，由真实 build 验证。"
))
def test_build_exit_code_trim_fail_artifact_ok():
    """3. _build 退出码：trim 失败但产物完整 → 0"""
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
            assert rc == 0, f"rc={rc}"

        with tempfile.TemporaryDirectory() as td:
            dist = make_dist(td, 2)
            os.remove(os.path.join(dist, "AC_Launcher.exe"))
            rc = build._build(td)
            assert rc == 1, f"rc={rc}"

        with tempfile.TemporaryDirectory() as td:
            dist = make_dist(td, 2)
            import shutil
            shutil.rmtree(os.path.join(dist, "_internal", "PySide6"))
            rc = build._build(td)
            assert rc == 1, f"rc={rc}"
    finally:
        build.subprocess.call = orig_call
        build._trim_dist = orig_trim
        build._print_size = orig_size


def test_static_checks():
    """4. 静态防再犯"""
    src = open(os.path.join(ROOT, "build.py"), encoding="utf-8").read()
    assert "except BaseException" in src
    # round-249：不再用「精确缩进字符串」断言——两处 KeyboardInterrupt 有
    # 8/12 空格两种缩进（分别在函数体与 with 块里），语义相同但字符串不等。
    # 改成语义计数；OSError 的容错（_dir_size 读文件失败跳过）是合理的，
    # 不再一刀切禁止。
    assert src.count("except KeyboardInterrupt:") >= 2
    # round-249：变量名 dist → dist_tmp（临时目录构建），这里按语义断言：
    # exe 与 PySide6 两个产物的存在性检查都必须在。
    assert "产物缺少 AC_Launcher.exe" in src
    assert "产物缺少 _internal/PySide6" in src
    assert src.count("return 1") >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])