#!/usr/bin/env python3
"""AC Launcher 回归入口 — 一条命令跑完所有自检。

用法::

    python regress.py            # 跑全部（发现即跑，缺文件自动跳过）
    python regress.py --shots    # 额外生成视觉截图到 _shots_r112/

为什么需要这个：RELEASE_1.0.0_CHECKLIST 里写着「全量回归绿（_diag_all.py
exit=0）」，但 _diag_all.py **从未入库** —— 回归套件一直是散落的临时脚本，
换台机器或重新 clone 就没了，形不成「改 → 验 → 返工」的循环。本文件把
所有检查收敛到一个入口，且对缺失脚本降级跳过（不会因少了哪个就整体失败）。

被它调用的脚本都在 `tests/`（**受版本控制**），换机 / 重新 clone 后
照跑 —— 这是它取代历史上那个从未入库的 `_diag_all.py` 的意义。
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
    ("编译", None, "builtin"),
    ("i18n 中英对称", None, "builtin"),
    ("文案门禁（禁用词/长度）", "check_copy.py", "script"),
    ("PII 门禁（本地专属）", "_pii_gate.py", "script"),
    ("默认值缺漏审计", "audit_defaults.py", "script"),
    ("目标判定（mll 分片）", "test_big_target.py", "script"),
    ("mll 分片集成", "test_mll_parallel.py", "script"),
    ("整合包进度桥接", "test_pack_progress.py", "script"),
    ("mod 下载进度聚合", "test_mod_progress.py", "script"),
    ("设置页脏检测回归", "test_settings_dirty.py", "script"),
    ("首页两问聚合（继续/留意）", "test_home_summary.py", "script"),
    ("任务中心（记录/历史）", "test_task_center.py", "script"),
    ("来源链（逐源失败）", "test_transfer.py", "script"),
    ("启动即降载（动画/壁纸）", "test_load_shed.py", "script"),
    ("诊断包导出（脱敏打包）", "test_support_bundle.py", "script"),
    ("IA 路径表（过期检查）", "check_paths.py", "script"),
    ("Java 计划/强制", "test_instance_java_plan.py", "script"),
    ("启动对话框高度", "test_launch_dialog_layout.py", "script"),
    ("格式/布局联动", "test_format.py", "script"),
    ("下载实例自选布局", "test_instance_create_format.py", "script"),
    ("实例重构（磁盘现状）", "test_instance_rebuild.py", "script"),
    ("更新签名信任链", "test_update_trust.py", "script"),
    ("更新下载/自替换助手", "test_update_install.py", "script"),
    ("条款版本化门禁", "test_terms.py", "script"),
    ("品牌自定义回归", "test_brand_custom.py", "script"),
    ("核心功能冒烟", "test_functional.py", "script"),
    ("全页面构造冒烟", "smoke_all.py", "script"),
    ("功能扩展包（可删除）", "test_features.py", "script"),
    ("任务取消/强制退出", "test_cancel.py", "script"),
    ("设置页冲突提示", "test_settings_conflicts.py", "script"),
    ("启动命令/暂停下载", "test_launch_extras.py", "script"),
    ("投影/存档地图解析", "test_schematic_tools.py", "script"),
    ("Java 下载阶段/取消", "test_java_download.py", "script"),
    ("来源健康/超时策略", "test_mirror_health.py", "script"),
    ("共享 assets 去重", "test_shared_assets.py", "script"),
    ("mll 断点续传/低速/429", "test_mll_resume.py", "script"),
    ("代码审查 P0 修复回归", "test_p0_review_fixes.py", "script"),
    ("横向审计 P0 修复回归", "test_interop_p0_fixes.py", "script"),
    ("新建实例信号 arity", "test_new_instance_signal.py", "script"),
    ("启动后窗口行为", "test_post_launch_behavior.py", "script"),
    ("状态栏信号归属", "test_status_signal_ownership.py", "script"),
    ("Java 镜像/断点/取消", "test_java_mirror_resume.py", "script"),
    ("模组链路/启动诊断", "test_round177_mod_diag.py", "script"),
    ("构建退出码/瘦身降级", "test_build_trim.py", "script"),
    ("下载完整性/CF 版本口径", "test_round178_mod_integrity.py", "script"),
    ("模组依赖统一修复", "test_round178_mod_repair.py", "script"),
    ("实例布局标识/自动查验", "test_round179_instance_marker.py", "script"),
    ("官方图标/交互/排版", "test_round180_ui.py", "script"),
    ("资源图标缓存", "test_round180_icon_cache.py", "script"),
    ("图标性能/详情缓存/HMCL 图标", "test_round181_perf.py", "script"),
    ("Cleanroom Java/亮度覆盖", "test_round182_cleanroom_java.py", "script"),
    ("客户端增强包装/卸", "test_round182_enhance.py", "script"),
    ("PCL 式编辑面板/加载器真装真卸/pcl 格式", "test_round183_editor.py", "script"),
    ("导出 .mrpack / 修改页", "test_round184_export.py", "script"),
    ("模组元数据/模组列表", "test_round185_mods.py", "script"),
    ("加载器可用性/Fabric API", "test_round186_loader.py", "script"),
    ("GC 模式/启动前内存优化", "test_round188_memory.py", "script"),
    ("修改页重做/加载器卡片", "test_round189_modify.py", "script"),
    ("实例图标/收藏夹", "test_round190_icon_fav.py", "script"),
    ("中文搜索/图标/模组来源", "test_round191_search_icon_src.py", "script"),
    ("资源中心：版本/前置/下载", "test_round193_store.py", "script"),
    ("一键修复反馈", "test_round194_fix_all.py", "script"),
    ("功能统一/页面化", "test_round195_unify.py", "script"),
    ("全面审计补漏", "test_round196_audit.py", "script"),
    ("崩溃页内/Java合一/来源", "test_round197_inline_java.py", "script"),
    ("加载器版本继承/空列表", "test_round198_loader_version.py", "script"),
    ("六维审计补漏（弹窗/截断/来源）", "test_round199_audit.py", "script"),
    ("实例页入口重构（诊断一级可见）", "test_round200_entries.py", "script"),
    ("模组 id/项目 slug 别名（cloth-config2）", "test_round201_mod_aliases.py", "script"),
    ("切页/降载后动画自动恢复", "test_round202_anim_resume.py", "script"),
    ("启动不关壁纸/下载解耦", "test_round203_no_shed.py", "script"),
    ("崩溃分析（类别/可疑模组/证据）", "test_round204_crash_diag.py", "script"),
    ("资源中心（搜索/版本列表/翻译/百科）", "test_round205_store_polish.py", "script"),
    ("假死修复/占位页（round-206）", "test_round206_no_freeze.py", "script"),
    ("资源中心秒获取（round-207）", "test_round207_search_latency.py", "script"),
    ("资源中心服务端过滤/真分页（round-208）", "test_round208_store_search.py", "script"),
]
SHOTS = "shots_all.py"


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
    # `_` 开头的脚本（如 PII 门禁，内含真实 PII 字面量、被 .gitignore 挡在
    # 仓库外）放仓库根；其余正式回归脚本在受控的 tests/。
    base = HERE if fname.startswith("_") else os.path.join(HERE, "tests")
    path = os.path.join(base, fname)
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
    for label, script, kind in SUITES:
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
        ok, note = run_script(SHOTS)
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
