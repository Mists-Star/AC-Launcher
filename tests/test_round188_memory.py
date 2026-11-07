"""round-188：内存管理（GC）+ 启动前内存优化。

用户补了一句：「启动前内存优化呢」—— PCL 设置页「内存分配」卡里还有这一项，
上一轮只补了内存可视化条，漏了。

判据：
1. **GC 模式真的换了参数**：zgc → -XX:+UseZGC；zgc_gen 额外 -XX:+ZGenerational；
   g1 → -XX:+UseG1GC；g1_tuned → G1NewSizePercent/G1ReservePercent/MaxGCPauseMillis；
   none → 不加 GC 参数。
2. **互斥**：显式选 GC 时**不能**再叠加 G1GC 参数组（ZGC 与 G1GC 互斥，
   同时下发 JVM 直接起不来）—— 这是真会炸游戏的组合，必须钉死。
3. **启动前内存优化**：实例 on/off 覆盖全局；optimize_memory 不抛异常，
   释放量 ≥ 0。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


from src.launch import build_options  # noqa: E402


def opts(**kw):
    base = dict(username="u", uuid="i", token="t", mc_dir="C:/mc",
                java="C:/java.exe")
    base.update(kw)
    return build_options(**base)


print("① GC 模式注入")
jvm = opts(gc_mode="zgc")["jvmArguments"]
check("zgc 加 UseZGC", "-XX:+UseZGC" in jvm, str(jvm))
check("zgc 不带 ZGenerational", "-XX:+ZGenerational" not in jvm)
jvm = opts(gc_mode="zgc_gen")["jvmArguments"]
check("zgc_gen 带 ZGenerational",
      "-XX:+UseZGC" in jvm and "-XX:+ZGenerational" in jvm, str(jvm))
jvm = opts(gc_mode="g1")["jvmArguments"]
check("g1 加 UseG1GC", "-XX:+UseG1GC" in jvm, str(jvm))
jvm = opts(gc_mode="g1_tuned")["jvmArguments"]
check("g1_tuned 带调优项",
      "-XX:G1NewSizePercent=20" in jvm and "-XX:MaxGCPauseMillis=40" in jvm,
      str(jvm))
jvm = opts(gc_mode="none", perf_g1gc=True)["jvmArguments"]
check("none 不加任何 GC 参数",
      "-XX:+UseG1GC" not in jvm and "-XX:+UseZGC" not in jvm, str(jvm))
jvm = opts(gc_mode="")["jvmArguments"]
check("跟随全局时保持原行为（默认带 G1GC 组）",
      "-XX:+UseG1GC" in jvm, str(jvm))

print("② 显式 GC 与 G1GC 组互斥")
for mode in ("zgc", "zgc_gen", "g1", "none"):
    jvm = opts(gc_mode=mode, perf_g1gc=True)["jvmArguments"]
    check("%s 不再叠加 G1NewSizePercent 组" % mode,
          "-XX:G1NewSizePercent=20" not in jvm, str(jvm))
    check("%s 不同时出现 ZGC 与 G1GC" % mode,
          not ("-XX:+UseZGC" in jvm and "-XX:+UseG1GC" in jvm), str(jvm))
# g1_tuned 自带调优组：不能被"通用 G1GC 组"重复注入一次
jvm = opts(gc_mode="g1_tuned", perf_g1gc=True)["jvmArguments"]
check("g1_tuned 的调优参数只出现一次",
      jvm.count("-XX:G1NewSizePercent=20") == 1, str(jvm))
check("g1_tuned 也不重复 UseG1GC",
      jvm.count("-XX:+UseG1GC") == 1, str(jvm))

print("③ 启动前内存优化")
from src.core.memopt import optimize_memory, should_optimize  # noqa: E402
from src.instances import Instance  # noqa: E402

inst = Instance(id="t", name="T", game_version="1.20.1")
inst.mem_optimize = "on"
check("实例 on → 要优化", should_optimize(inst, {"mem_optimize": False}))
inst.mem_optimize = "off"
check("实例 off → 不优化", not should_optimize(inst, {"mem_optimize": True}))
inst.mem_optimize = ""
check("跟随全局 on → 要优化", should_optimize(inst, {"mem_optimize": True}))
check("跟随全局 off → 不优化", not should_optimize(inst, {"mem_optimize": False}))
freed = optimize_memory()
check("optimize_memory 不抛异常且非负", isinstance(freed, int) and freed >= 0,
      "%d bytes" % freed)

print("④ 面板：两个下拉都在")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.instance_editor import InstanceEditorDialog  # noqa: E402

dlg = InstanceEditorDialog(None, inst)
check("有 GC 下拉", hasattr(dlg, "gc_combo") and dlg.gc_combo.count() == 6,
      str(dlg.gc_combo.count()) if hasattr(dlg, "gc_combo") else "-")
check("有启动前内存优化下拉",
      hasattr(dlg, "memopt_combo") and dlg.memopt_combo.count() == 3,
      str(dlg.memopt_combo.count()) if hasattr(dlg, "memopt_combo") else "-")
check("GC 下拉默认跟随全局",
      dlg.gc_combo.currentData() == "follow", str(dlg.gc_combo.currentData()))
# 选 ZGC → G1GC 勾选被禁用（互斥）
dlg.gc_combo.setCurrentIndex(dlg.gc_combo.findData("zgc"))
dlg._sync_gc_related()
check("选 ZGC 后 G1GC 勾选被禁用", not dlg.g1gc_chk.isEnabled(), "")
dlg.gc_combo.setCurrentIndex(dlg.gc_combo.findData("follow"))
dlg._sync_gc_related()
check("改回跟随后 G1GC 勾选恢复", dlg.g1gc_chk.isEnabled(), "")
# 写回
dlg.gc_combo.setCurrentIndex(dlg.gc_combo.findData("g1_tuned"))
dlg.memopt_combo.setCurrentIndex(dlg.memopt_combo.findData("on"))
dlg._collect()
check("gc_mode 写回", inst.gc_mode == "g1_tuned", str(inst.gc_mode))
check("mem_optimize 写回", inst.mem_optimize == "on", str(inst.mem_optimize))
dlg.deleteLater()

print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-188 GC 模式 + 启动前内存优化）")
