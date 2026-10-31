"""round-162 回归：条款版本化门禁（纯逻辑，无 Qt）。

覆盖首次/已同意/改版/脏值回落，以及正文源与版本号一致性。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src import terms  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


check("条款版本为正整数", isinstance(terms.TERMS_VERSION, int) and terms.TERMS_VERSION >= 1,
      str(terms.TERMS_VERSION))
check("首次启动需要同意", terms.needs_acceptance({}))
check("旧版本同意记录不足", terms.needs_acceptance({"terms_accepted_version": 0}))
check("同版本已同意不再弹", not terms.needs_acceptance(
    {"terms_accepted_version": terms.TERMS_VERSION}))
check("更高版本记录视为已同意", not terms.needs_acceptance(
    {"terms_accepted_version": terms.TERMS_VERSION + 1}))
check("更低版本需重新同意", terms.needs_acceptance(
    {"terms_accepted_version": terms.TERMS_VERSION - 1}))
check("字符串脏值回落为 0", terms.accepted_version(
    {"terms_accepted_version": "abc"}) == 0)
check("None 脏值回落为 0", terms.accepted_version(
    {"terms_accepted_version": None}) == 0)

body = terms.combined_text()
check("正文含隐私协议", "隐私协议" in body)
check("正文含用户守则", "用户守则" in body)
check("正文含免责声明", "免责声明" in body)
check("正文带最后更新日期", terms.TERMS_UPDATED in body)
check("三段正文都已填充", all(terms.legal_text(k) for k in ("privacy", "tos", "disclaimer")))
check("未知 key 返回空串", terms.legal_text("nope") == "")

print()
if fails:
    print("FAILED: %d 项 → %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL CHECKS PASSED")
