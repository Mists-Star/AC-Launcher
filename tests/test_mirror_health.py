"""round-174 回归测试：来源健康表 + 按源超时 / 重试策略。

覆盖：
  1. 超时策略：镜像 (5,15) / 官方 (10,30)；镜像失败不重试、官方保留 1 次；
  2. SourceHealth：连续 2 次连接类失败 → 冷却；冷却结束自动恢复；
     401/403 立刻冷却；慢源（EWMA）判定；
  3. _rank_candidates：健康镜像在前；不健康只剩官方；慢镜像让位官方；
  4. MirrorSession.send 真流程：前两次「镜像失败 → 官方」，第三次起直接官方，
     且镜像那几次拿到的是短超时 + 0 重试；
  5. _rewrite（客户端 jar 分片路径）：镜像不健康时不再改写为 BMCLAPI。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import requests  # noqa: E402

from src.core import mirror  # noqa: E402
from src.core.transfer import Candidate  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


print("== round-174 来源健康 / 超时策略 ==")

URL = "https://piston-data.mojang.com/v1/objects/aa/client.jar"
MC = Candidate("bmclapi", "https://bmclapi2.bangbang93.com/v1/objects/aa/client.jar",
               "piston-data.mojang.com", mirrored=True)
OC = Candidate("official", URL, "piston-data.mojang.com", mirrored=False)

# ── 1. 超时 / 重试策略 ─────────────────────────────────────────────────
check("镜像超时更短 (5,15)", mirror._timeout_for(MC) == (5, 15),
      str(mirror._timeout_for(MC)))
check("官方超时保持 (10,30)", mirror._timeout_for(OC) == (10, 30),
      str(mirror._timeout_for(OC)))
check("镜像失败不重试", mirror._retries_for(MC) == 0,
      str(mirror._retries_for(MC)))
check("官方保留一次重试", mirror._retries_for(OC) == 1,
      str(mirror._retries_for(OC)))
check("健康表键按来源名", mirror._source_key(MC) == "bmclapi"
      and mirror._source_key(OC) == "official")

# ── 2. SourceHealth 单元 ───────────────────────────────────────────────
mirror.reset_source_health()
h = mirror.SourceHealth(fail_limit=2, cooldown=0.4, slow_ms=1000,
                        slow_samples=3)
check("初始健康", not h.is_down("bmclapi"))
h.note_fail("bmclapi", "ReadTimeout")
check("1 次失败还不算不健康", not h.is_down("bmclapi"))
h.note_fail("bmclapi", "ReadTimeout")
check("连续 2 次失败进入冷却", h.is_down("bmclapi"))
check("冷却期内记录原因", h.reason("bmclapi").startswith("ReadTimeout")
      or "ReadTimeout" in h.reason("bmclapi"), h.reason("bmclapi"))
time.sleep(0.45)
check("冷却结束自动恢复", not h.is_down("bmclapi"))

h.note_rejected("bmclapi", "HTTP 403")
check("403 立刻冷却", h.is_down("bmclapi"))
h.reset()
check("reset 清空", not h.is_down("bmclapi"))

for _ in range(3):
    h.note_ok("bmclapi", 4.0)     # 每次 4000ms
check("慢源判定（EWMA ≥ 阈值）", h.is_slow("bmclapi"),
      str(h.snapshot().get("bmclapi")))

h.note_fail("bmclapi", "timeout")
check("慢源仍健康时不算 down", not h.is_down("bmclapi"))
check("慢源 down 后 is_slow 清样本", h.snapshot().get("bmclapi", {}).get("samples", 0) >= 3)

# ── 3. 候选排序 ────────────────────────────────────────────────────────
mirror.reset_source_health()
ranked = mirror._rank_candidates([MC, OC])
check("健康时镜像在前", ranked[0].mirrored and len(ranked) == 2,
      str([c.source for c in ranked]))

mirror.source_health().note_fail("bmclapi", "ReadTimeout")
mirror.source_health().note_fail("bmclapi", "ReadTimeout")
ranked = mirror._rank_candidates([MC, OC])
check("不健康时只剩官方", [c.source for c in ranked] == ["official"],
      str([c.source for c in ranked]))

mirror.reset_source_health()
for _ in range(mirror._SLOW_SAMPLES):
    mirror.source_health().note_ok("bmclapi", 5.0)
ranked = mirror._rank_candidates([MC, OC])
check("慢镜像让位官方（镜像仍作回退）",
      [c.source for c in ranked] == ["official", "bmclapi"],
      str([c.source for c in ranked]))

# ── 4. MirrorSession.send 真流程 ───────────────────────────────────────
mirror.reset_source_health()
mirror.set_mirror(True)
calls = []


class _Resp:
    status_code = 200
    raw = None

    def close(self):
        pass


def _fake_try(self, request, *, last=False, strict=False, retries=None, **kw):
    calls.append({"url": request.url, "timeout": kw.get("timeout"),
                  "retries": retries, "last": last, "strict": strict})
    if "bmclapi" in request.url:
        return None            # 镜像没响应 → 上层换源
    return _Resp()


_orig_try = mirror.MirrorSession._try_source
mirror.MirrorSession._try_source = _fake_try
try:
    sess = mirror.MirrorSession()
    for _ in range(3):
        req = requests.Request("GET", URL).prepare()
        sess.send(req)

    first_mirror = calls[0]
    check("首发尝试镜像", "bmclapi" in first_mirror["url"], first_mirror["url"])
    check("镜像用短超时", first_mirror["timeout"] == (5, 15),
          str(first_mirror["timeout"]))
    check("镜像不重试", first_mirror["retries"] == 0, str(first_mirror["retries"]))
    check("随后回退官方", calls[1]["url"] == URL and calls[1]["last"] is True,
          calls[1]["url"])
    check("官方超时/重试保持", calls[1]["timeout"] == (10, 30)
          and calls[1]["retries"] == 1)
    check("第 3 次请求跳过不健康镜像", len(calls) == 5,
          "calls=%d 最后=%s" % (len(calls), calls[-1]["url"]))
    check("第 3 次直接走官方", calls[-1]["url"] == URL)
    check("镜像被剔除后官方仍 strict", calls[-1]["strict"] is True,
          str(calls[-1]))
finally:
    mirror.MirrorSession._try_source = _orig_try
    mirror.set_mirror(False)
    mirror.reset_source_health()

# ── 5. _rewrite（分片并行路径）────────────────────────────────────────
mirror.set_mirror(True)
mirror.reset_source_health()
check("健康时改写为 BMCLAPI", "bmclapi" in mirror._rewrite(URL),
      mirror._rewrite(URL))
mirror.source_health().note_fail("bmclapi", "timeout")
mirror.source_health().note_fail("bmclapi", "timeout")
check("不健康时不改写（大文件走官方）", mirror._rewrite(URL) == URL,
      mirror._rewrite(URL))
mirror.set_mirror(False)
mirror.reset_source_health()

print()
if fails:
    print("FAILED %d:" % len(fails))
    for f in fails:
        print(" - %s" % f)
    sys.exit(1)
print("全部通过")
