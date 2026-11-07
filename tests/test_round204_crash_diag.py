"""round-204 回归：崩溃分析要「说人话」——类别 + 可疑模组 + 原始证据。

Qt offscreen；全部纯文件 I/O，不联网：
1. `guess_culprit` 识别 Fabric 的指名格式（Suspected mods / Mod file /
   Mixin apply），并只采信 mods 目录里真实存在的 jar。
2. `diagnose_latest` 从 latest.log 得出 kind / culprit / exception / evidence。
3. `analyze_instance` 的 finding 带上 culprit 与匹配行上下文（不再只有
   `m.group(0)[:160]` 一个词）。
4. `launch.classify_exit` 按真实报错分类（mixin / mod resolution / OOM），
   不再一律落到「退出码 1 → 重装实例」。
"""
import os
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import crash_analysis as crash  # noqa: E402
from src.launch import classify_exit  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── 1. 可疑对象提取 ──
TMP = tempfile.mkdtemp(prefix="_r204_")
MODS = os.path.join(TMP, "mods")
os.makedirs(MODS, exist_ok=True)
for jar in ("examplemod.jar", "sodium-0.5.3.jar"):
    open(os.path.join(MODS, jar), "wb").close()

t1 = ("Mod File: /mods/examplemod.jar\n"
      "Suspected mods: examplemod\n"
      "java.lang.NoClassDefFoundError: net/examplemod/ModInit\n")
check("识别 Mod File 的行", crash.guess_culprit(t1) == "examplemod.jar"
      or crash.guess_culprit(t1) == "examplemod", crash.guess_culprit(t1))

t2 = ("[main/ERROR] Mixin apply for mod examplemod failed\n"
      "Caused by: org.spongepowered.asm.mixin.injection.throwables.InjectionError: "
      "Critical injection failure: @Inject\n"
      "\tat net.examplemod.MixinInit.apply(MixinInit.java:31)\n")
check("识别 Mixin apply 的 mod id", crash.guess_culprit(t2) == "examplemod",
      crash.guess_culprit(t2))

t3 = ("java.lang.RuntimeError: boom\n"
      "Failed to load mod sodium-0.5.3\n")
check("识别 Failed to load mod", crash.guess_culprit(t3, MODS) ==
      "sodium-0.5.3", crash.guess_culprit(t3, MODS))

t4 = "at net.minecraft.client.Main.main(Main.java:1)\n"
check("无指名信息时不瞎猜", crash.guess_culprit(t4, MODS) == "")

t5 = "Mod File: /mods/ghost-1.0.jar\n"
check("mods 目录里不存在的 jar 不当强证据",
      crash.guess_culprit(t5, MODS) != "ghost-1.0.jar")

# ── 2. diagnose_latest ──
mc = os.path.join(TMP, "mc")
os.makedirs(os.path.join(mc, "logs"), exist_ok=True)
os.makedirs(os.path.join(mc, "crash-reports"), exist_ok=True)
os.makedirs(os.path.join(mc, "mods"), exist_ok=True)
open(os.path.join(mc, "mods", "examplemod.jar"), "wb").close()

LOG = os.path.join(mc, "logs", "latest.log")
with open(LOG, "w", encoding="utf-8") as f:
    f.write(
        "[12:00:00] [main/INFO]: Loading Minecraft 1.20.1 with Fabric Loader 0.15.0\n"
        "[12:00:01] [main/ERROR]: Mixin apply for mod examplemod failed\n"
        "org.spongepowered.asm.mixin.transformer.throwables.MixinTransformerError: "
        "Critical injection failure: @Inject\n"
        "\tat net.examplemod.MixinInit.apply(MixinInit.java:31)\n"
        "Caused by: java.lang.NoSuchMethodError: "
        "net.minecraft.class_310.method_1551()V\n"
        "[12:00:01] [main/ERROR]: Crash report saved to crash-reports\n")

d = crash.diagnose_latest(mc)
check("diagnose 识别出 mixin 类别", d.get("kind") == "mixin_error", str(d.get("kind")))
check("diagnose 给出可疑模组", d.get("culprit") == "examplemod", str(d.get("culprit")))
check("diagnose 给出关键错误行",
      "Mixin" in (d.get("exception") or "") or
      "NoSuchMethod" in (d.get("exception") or ""), str(d.get("exception")))
check("diagnose 带原始证据（含 Caused by）",
      any("Caused by" in x for x in (d.get("evidence") or [])),
      str(d.get("evidence")))

# ── 3. analyze_instance ──
inst = SimpleNamespace(mc_dir=mc, mods_dir=os.path.join(mc, "mods"),
                       game_dir=mc)
findings = crash.analyze_instance(inst)
kinds = {f.kind for f in findings}
check("analysis 命中 mixin_error", "mixin_error" in kinds, str(kinds))
mf = next(f for f in findings if f.kind == "mixin_error")
check("finding 带 culprit", bool(mf.culprit), mf.culprit)
check("finding 详情含匹配行上下文",
      "Injection" in mf.detail or "Caused by" in mf.detail, mf.detail[:80])
check("finding 详情不再只有一条短片段", len(mf.detail.splitlines()) >= 2,
      str(len(mf.detail.splitlines())))

# ── 4. classify_exit 按真实报错分类 ──
key, _ = classify_exit(1, LOG)
check("启动崩溃不再一律报 crash_one", key == "exit.mixin", key)

log2 = os.path.join(TMP, "modres.log")
with open(log2, "w", encoding="utf-8") as f:
    f.write("net.fabricmc.loader.impl.FormattedException: Mod resolution failed\n"
            "requires cloth-config2 11.x but could not find it\n")
key2, _ = classify_exit(1, log2)
check("依赖解析失败 → mod_resolution", key2 == "exit.mod_resolution", key2)

log3 = os.path.join(TMP, "oom.log")
with open(log3, "w", encoding="utf-8") as f:
    f.write("java.lang.OutOfMemoryError: Java heap space\n")
key3, _ = classify_exit(1, log3)
check("OOM 仍优先分类", key3 == "exit.oom", key3)

print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ALL PASS")
