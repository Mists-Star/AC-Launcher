"""round-153 回归测试：首页两问（继续哪个 / 哪些挡住你）。

覆盖 ``src/core/home_summary.py`` 的纯聚合语义 + Java 三档（Error/Warning/Info）
+ 健康扫描缓存。全部 Qt-free，可离屏 / 无 GUI 跑。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import home_summary as hs  # noqa: E402
from src.core.mod_check import (  # noqa: E402
    SEV_CRITICAL, SEV_INFO, SEV_WARNING, Finding,
)

fails = []


def check(label, cond, extra=""):
    print("  %s %-54s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


class Inst:
    """首页聚合只需要 id/name/last_played/mc_dir + 体检字段。"""

    def __init__(self, iid, name="", last_played=0.0, mc_dir=""):
        self.id = iid
        self.name = name
        self.last_played = last_played
        self.mc_dir = mc_dir
        self.game_version = "1.20.1"
        self.version_id = ""
        self.loader = ""
        self.java_path = ""
        self.ram_mb = 0
        self.jvm_preset = ""
        self.jvm_args = ""
        self.game_args = ""
        self.perf_g1gc = True
        self.mods_dir = ""


def prob(sev, kind="k", title="t", **kw):
    return hs.Problem(kind=kind, severity=sev, title_key=title, **kw)


tmp_ok = tempfile.mkdtemp(prefix="_hs_ok_")
tmp_missing = os.path.join(tmp_ok, "gone")

# ── 1. summarize：继续避开 Critical；排序 severity → last_played → id ──
a = Inst("a", "Alpha", last_played=100)
b = Inst("b", "Beta", last_played=200)
c = Inst("c", "Gamma", last_played=300)
summary = hs.summarize([a, b, c], {
    "a": [prob(SEV_WARNING)],
    "c": [prob(SEV_CRITICAL, kind="game_dir_missing",
               title="home.attn.game_dir_missing")],
})
check("继续 = 最近玩过且未被 Error 挡住（b）", summary.continue_with == "b",
      summary.continue_with)
check("errors/warnings 计数", (summary.errors, summary.warnings) == (1, 1),
      "%d/%d" % (summary.errors, summary.warnings))
check("Critical 排在 Warning 之前", [i.instance_id for i in summary.needs_attention]
      == ["c", "a"])
check("每条带实例名", summary.needs_attention[0].instance_name == "Gamma")

# ── 2. 同一实例多条 → 只显示最严重一条 + more 计数 ──
d = Inst("d", "Delta", last_played=50)
summary = hs.summarize([d], {"d": [
    prob(SEV_WARNING, kind="b"), prob(SEV_WARNING, kind="a"),
    prob(SEV_CRITICAL, kind="z"),
]})
check("只留一条 + more=2", len(summary.needs_attention) == 1
      and summary.needs_attention[0].more == 2,
      "more=%d" % summary.needs_attention[0].more)
check("最严重的一条胜出", summary.needs_attention[0].kind == "z")
check("有 Error 时不给继续", summary.continue_with == "")

# ── 3. Info 不计入「需要留意」，也不挡继续 ──
e = Inst("e", "Echo", last_played=400, mc_dir=tmp_ok)
info = Finding(kind="java_advice", severity=SEV_INFO,
               title="health.kind.java_advice", reason="", suggestion="")
problems = hs.diagnose_instance(e, findings=[info])
check("Info 不产生 Problem", problems == [], str(problems))
summary = hs.summarize([e], {"e": problems})
check("Info 不进 needs_attention", summary.needs_attention == []
      and summary.warnings == 0)
check("Info 不挡继续", summary.continue_with == "e", summary.continue_with)

# ── 4. 目录缺失 = Critical；上次会话失败 = Warning ──
f = Inst("f", "Foxtrot", mc_dir=tmp_missing)
p = hs.diagnose_instance(f, findings=[])
check("目录缺失 → Critical",
      any(x.severity == SEV_CRITICAL and x.kind == "game_dir_missing"
          for x in p), str([x.kind for x in p]))

g = Inst("g", "Golf", mc_dir=tmp_ok)
p = hs.diagnose_instance(g, findings=[],
                         session={"outcome": "failed", "reason": "Exit code 1"})
check("上次失败 → Warning 且带原因",
      len(p) == 1 and p[0].severity == SEV_WARNING
      and p[0].kind == "last_session_failed"
      and p[0].meta.get("reason") == "Exit code 1", str(p))
p = hs.diagnose_instance(g, findings=[], session={"outcome": "crashed"})
check("崩溃无原因 → 通用文案",
      len(p) == 1 and p[0].title_key == "home.attn.last_session_failed_generic")
p = hs.diagnose_instance(g, findings=[], session={"outcome": "ok"})
check("正常会话不产生问题", p == [])

# ── 5. 未登录 → 全局 Warning（排在最后） ──
summary = hs.summarize([a], {"a": [prob(SEV_WARNING)]},
                       with_account=True, has_account=False)
check("未登录追加一条", len(summary.needs_attention) == 2
      and summary.needs_attention[-1].kind == "no_account"
      and summary.needs_attention[-1].action == "login")
summary = hs.summarize([a], {"a": []}, with_account=True, has_account=False)
check("无实例问题也提示未登录", summary.needs_attention[-1].kind == "no_account")
summary = hs.summarize([], {}, with_account=True, has_account=False)
check("零实例不刷未登录", summary.needs_attention == [])

# ── 6. Java 三档（monkeypatch core.java 的探测函数） ──
import src.core.java as J  # noqa: E402
from src.core import instance_health as ih  # noqa: E402

_NAMES = ("required_java_major_for", "select_java", "scan_javas",
          "find_version_json", "is_java_compatible")
_ORIG = {n: getattr(J, n) for n in _NAMES}
JDK17 = os.path.join(tmp_ok, "jdk17", "javaw.exe")
JDK21 = os.path.join(tmp_ok, "jdk21", "javaw.exe")
_JAVAS = [{"path": JDK17, "major": 17}, {"path": JDK21, "major": 21}]


def _patch(need, select_ret, javas=None):
    J.required_java_major_for = lambda *a, **k: need
    J.find_version_json = lambda *a, **k: None
    J.is_java_compatible = lambda n, m: m >= n
    J.scan_javas = lambda deep=False: (javas if javas is not None else _JAVAS)
    J.select_java = lambda *a, **k: select_ret


try:
    # 6.1 指定 Java 不兼容但有替代 → Warning（启动前确认后本次切换）
    _patch(21, JDK21)
    x = Inst("x")
    x.java_path = JDK17
    finds = ih._check_java(x, None)
    check("不兼容+有替代 → Warning",
          len(finds) == 1 and finds[0].severity == SEV_WARNING
          and finds[0].kind == "java_mismatch"
          and finds[0].fix and finds[0].fix.get("action") == "set_java_path", str(finds))
    check("修复标签带 advised",
          finds and finds[0].fix.get("label_kwargs", {}).get("advised") == 21)

    # 6.2 指定 Java 不兼容且无替代 → Critical，建议去装 Java
    _patch(21, None)
    finds = ih._check_java(x, None)
    check("不兼容+无替代 → Critical",
          len(finds) == 1 and finds[0].severity == SEV_CRITICAL
          and finds[0].suggestion == "health.fix.java_mismatch_install", str(finds))

    # 6.3 能跑但非推荐版本，且已装精确版本 → Info（只建议，不拦）
    _patch(17, JDK17)
    y = Inst("y")
    y.java_path = JDK21
    finds = ih._check_java(y, None)
    check("兼容但非推荐 → Info",
          len(finds) == 1 and finds[0].severity == SEV_INFO
          and finds[0].kind == "java_advice", str(finds))
    check("Info 建议文案可切换",
          bool(finds) and finds[0].suggestion == "health.fix.java_advice"
          and finds[0].fix and finds[0].fix.get("action") == "set_java_path")

    # 6.4 自动模式且无任何兼容 JDK → Critical java_missing
    _patch(21, None, javas=[{"path": JDK17, "major": 17}])
    z = Inst("z")
    finds = ih._check_java(z, None)
    check("自动模式无兼容 JDK → Critical",
          len(finds) == 1 and finds[0].severity == SEV_CRITICAL
          and finds[0].kind == "java_missing", str(finds))
finally:
    for n, fn in _ORIG.items():
        setattr(J, n, fn)

# ── 7. 健康扫描 90s 缓存：同实例同设定只扫一次 ──
_calls = {"n": 0}
_real_scan = ih.scan_health


def _count_scan(inst, settings=None):
    _calls["n"] += 1
    return {"findings": [], "critical": 0, "warning": 0, "info": 0}


ih.scan_health = _count_scan
try:
    w = Inst("w", "Whiskey", mc_dir=tmp_ok)
    r1 = hs.scan_health_cached(w, {"ram_mb": 4096})
    r2 = hs.scan_health_cached(w, {"ram_mb": 4096})
    check("第二次命中缓存", _calls["n"] == 1, "scan 调用 %d 次" % _calls["n"])
    r3 = hs.scan_health_cached(w, {"ram_mb": 8192})
    check("设置变化 → 缓存失效", _calls["n"] == 2, "scan 调用 %d 次" % _calls["n"])
finally:
    ih.scan_health = _real_scan

print()
if fails:
    print("FAILED %d: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL CHECKS PASSED")
