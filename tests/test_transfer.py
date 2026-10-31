"""round-155 回归测试：来源链（SourceProvider / SourceChain / SourceTrace）。

覆盖三件事：
1. 规则匹配边界（前缀必须落在路径边界，不误伤同前缀主机）；
2. 三档偏好顺序 + 去重 + 失效主机只跳过镜像候选；
3. 逐源失败记录（环形上限 / summary / describe），以及 mirror.send 的换源行为。

Qt-free；镜像 transport 用假 `_try_source` 替换，不发真实请求。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import requests  # noqa: E402

from src.core import transfer as tr  # noqa: E402
from src.core import mirror  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


BMCL = "https://bmclapi2.bangbang93.com"
META = "https://launchermeta.mojang.com"
RULE = tr.MirrorRule(META, BMCL)

# ── 1. MirrorRule：前缀必须落在路径边界 ──
check("精确主机命中（rest 为空）", RULE.match(META) == BMCL, RULE.match(META) or "")
check("主机 + 路径命中",
      RULE.match(META + "/mc/game/version_manifest_v2.json")
      == BMCL + "/mc/game/version_manifest_v2.json")
check("同前缀主机不误伤（.evil）", RULE.match(META + ".evil/x") is None)
check("其它主机不命中", RULE.match("https://piston-meta.mojang.com/x") is None)

# ── 2. Provider 展开 ──
off = tr.OfficialProvider()
check("官方 provider 只接受 http(s)", off.candidates("modrinth.com") == [])
oc = off.candidates(META + "/x")
check("官方候选 origin_host 正确",
      len(oc) == 1 and oc[0].source == "official"
      and oc[0].origin_host == "launchermeta.mojang.com"
      and not oc[0].mirrored)

mp = tr.PrefixMirrorProvider(
    [RULE, tr.MirrorRule("https://libraries.minecraft.net", BMCL + "/maven")],
    name="bmclapi", max_concurrency=48)
mc = mp.candidates(META + "/x")
check("镜像候选 mirrored=True 且保留 origin",
      len(mc) == 1 and mc[0].mirrored
      and mc[0].origin_host == "launchermeta.mojang.com"
      and mc[0].source == "bmclapi", mc[0].url if mc else "")
named = mp.candidates("https://libraries.minecraft.net/a/b.jar")
check("路径型规则仍走 provider 名",
      named and named[0].url == BMCL + "/maven/a/b.jar")
rule_named = tr.PrefixMirrorProvider(
    [tr.MirrorRule(META, BMCL, name="custom-mirror")]).candidates(META + "/x")
check("规则级名字优先",
      rule_named and rule_named[0].source == "custom-mirror")

# ── 3. SourceChain：三档偏好 / 去重 / 失效过滤 ──
chain = tr.SourceChain([off, mp])
url = META + "/x"
c_of = chain.candidates(url, prefer=tr.OFFICIAL_ONLY)
c_first = chain.candidates(url, prefer=tr.OFFICIAL_FIRST)
c_mirror = chain.candidates(url, prefer=tr.MIRROR_FIRST)
check("official_only 只有官方",
      len(c_of) == 1 and c_of[0].source == "official")
check("official_first 官方在前",
      [c.source for c in c_first] == ["official", "bmclapi"])
check("mirror_first 镜像在前",
      [c.source for c in c_mirror] == ["bmclapi", "official"])
check("默认偏好为 official_first",
      [c.source for c in chain.candidates(url)] == ["official", "bmclapi"])
check("非镜像主机只有官方候选",
      len(chain.candidates("https://api.modrinth.com/v2/project")) == 1)
dup = tr.SourceChain([off, tr.PrefixMirrorProvider([RULE, RULE])])
check("相同 URL 候选去重（官方 + 镜像）",
      len(dup.candidates(url, prefer=tr.MIRROR_FIRST)) == 2)
dead = {"launchermeta.mojang.com"}
d_mirror = chain.candidates(url, dead=dead, prefer=tr.MIRROR_FIRST)
check("失效主机只跳过镜像候选",
      [c.source for c in d_mirror] == ["official"])

check("preferred_concurrency 取首个非零",
      chain.preferred_concurrency() == 48)
check("全零上限时返回 0",
      tr.SourceChain([off]).preferred_concurrency() == 0)

# ── 4. SourceTrace：只记失败 + 环形上限 + 摘要 ──
trace = tr.SourceTrace(max_failures=20)
for i in range(25):
    trace.failure("bmclapi", "https://x/%d" % i, "HTTP 404", 404)
check("失败记录环形上限 20", len(trace.failures()) == 20)
check("只保留最近 20 条",
      trace.failures()[0].url.endswith("/5")
      and trace.failures()[-1].url.endswith("/24"))
trace.success("official", url)
check("成功记录最后一条",
      trace.last_ok() is not None and trace.last_ok().source == "official")
sum_rows = trace.summary()
check("summary 最多 4 失败 + 1 成功", len(sum_rows) == 5
      and sum_rows[-1] == "ok official", str(sum_rows[-1]))
check("summary 失败行带状态", "HTTP 404" in sum_rows[0], sum_rows[0])
check("describe 带最后成功源",
      trace.describe().endswith("→ official"), trace.describe())
check("sources 按首次出现排序",
      trace.sources() == ["bmclapi", "official"])
trace.reset()
check("reset 清空", trace.failures() == [] and trace.last_ok() is None)

# ── 5. mirror._rewrite 与旧重写表等价 ──
mirror.set_mirror(True)
rw = mirror._rewrite
check("launchermeta → bmclapi",
      rw(META + "/mc/game/v.json") == BMCL + "/mc/game/v.json")
check("libraries → /maven",
      rw("https://libraries.minecraft.net/a/b.jar") == BMCL + "/maven/a/b.jar")
check("fabric meta → /fabric-meta",
      rw("https://meta.fabricmc.net/v2/versions/loader")
      == BMCL + "/fabric-meta/v2/versions/loader")
check("未收录主机原样透传",
      rw("https://api.modrinth.com/v2/project") == "https://api.modrinth.com/v2/project")
check("非字符串原样返回", rw(None) is None)
mirror.set_mirror(False)
check("镜像关闭 → 原样", rw(META + "/x") == META + "/x")
mirror.set_mirror(True)

# ── 6. MirrorSession.send：逐源换源 + 失败可见 ──
class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.headers = {}

    def close(self):
        pass


def _send_with(fake):
    mirror.set_mirror(True)
    sess = mirror.MirrorSession()
    sess._ctx = mirror.InstallContext()
    req = requests.Request("GET", url).prepare()
    sess._try_source = fake
    return sess, req


def fallback_ok(request, *, last=False, strict=False, **kwargs):
    """镜像 404 → 官方 200。"""
    if "bmclapi" in request.url:
        sess._last_status = 404
        return None
    sess._last_status = 200
    return _Resp(200)


sess, req = _send_with(fallback_ok)
resp = sess.send(req)
tr_ = sess._ctx.trace
check("镜像失败 → 官方兜底成功", resp.status_code == 200)
check("响应用的是官方 URL", req.url == url, req.url)
check("逐源记录镜像 404", len(tr_.failures()) == 1
      and tr_.failures()[0].source == "bmclapi"
      and tr_.failures()[0].status == 404)
check("最后成功源为 official",
      tr_.last_ok() is not None and tr_.last_ok().source == "official")


def both_fail(request, *, last=False, strict=False, **kwargs):
    """两源都失败：镜像 500，官方严格模式抛 HTTPError。"""
    if "bmclapi" in request.url:
        sess2._last_status = 500
        return None
    sess2._last_status = 500
    raise requests.HTTPError("500 Server Error")


sess2, req2 = _send_with(both_fail)
raised = False
try:
    sess2.send(req2)
except requests.RequestException:
    raised = True
tr2 = sess2._ctx.trace
check("两源皆失败 → 显式抛错", raised)
check("失败逐源记录 2 条", len(tr2.failures()) == 2,
      str([(a.source, a.reason) for a in tr2.failures()]))
check("第二条为官方 HTTP 500",
      tr2.failures()[-1].source == "official"
      and tr2.failures()[-1].status == 500)
check("无成功记录（不说谎）", tr2.last_ok() is None)


def passthrough(request, *, last=False, strict=False, **kwargs):
    sess3._last_status = 200
    return _Resp(200)


mirror.set_mirror(False)
sess3, req3 = _send_with(passthrough)
mirror.set_mirror(False)
resp3 = sess3.send(req3)
check("镜像关闭 → 单候选透传", resp3.status_code == 200)
check("官方透传不写成功噪声", sess3._ctx.trace.last_ok() is None
      and sess3._ctx.trace.failures() == [])
mirror.set_mirror(False)

print()
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("ALL PASS")
