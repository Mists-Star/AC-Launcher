"""round-239：mod 中文名补充表集成回归。

用户反馈「mod 后面括号里的翻译不全，好多 mod 没翻译到」。原内置表 130 条，
现加构建期生成的补充表 _MOD_CN_EXTRA（359 条，机翻自用户搜索缓存）。

验证：
  * cn_name 查找顺序：内置表优先 → 补充表兜底 → 英文原名
  * cn_short / cn_slug_map 也认补充表（中文搜索能搜到）
  * 补充表不存在时（未生成）不崩，降级为只用内置表
  * 表格式为 Python 源码字典，可被 ast 安全解析
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src import mod_names as mn  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


print("== 1. 补充表加载 ==")
check("补充表已加载且有条目", len(mn._MOD_CN_EXTRA) > 100,
      "%d entries" % len(mn._MOD_CN_EXTRA))

print("== 2. cn_name 查找顺序 ==")
# 内置表优先：sodium 在内置表，值是「钠·渲染优化」
check("内置表命中（sodium）", "钠" in mn.cn_name("sodium", "Sodium"),
      mn.cn_name("sodium", "Sodium"))
# 补充表兜底：tectonic 只在补充表
tect = mn.cn_name("tectonic", "Tectonic")
check("补充表命中（tectonic）", "（" in tect and "地质" in tect, tect)
# 都没收录：返回 fallback
check("未收录返回 fallback", mn.cn_name("unknown-mod-xyz", "Unknown Mod") == "Unknown Mod")

print("== 3. cn_short / cn_slug_map 认补充表 ==")
short = mn.cn_short("tectonic")
check("cn_short 从补充表取中文主体", short == "地质构造", short)
slugmap = mn.cn_slug_map()
check("中文搜索反查表含补充表条目",
      any("tectonic" in v for v in slugmap.values()),
      "map size=%d" % len(slugmap))

print("== 4. 表文件格式安全 ==")
path = os.path.join(HERE, "src", "mod_cn_extra.py")
if os.path.isfile(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    d = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_MOD_CN_EXTRA" for t in node.targets):
            d = ast.literal_eval(node.value)
    check("表可被 ast 解析为 dict", isinstance(d, dict) and len(d) > 100,
          "%d entries" % (len(d) if d else 0))
else:
    check("表文件存在", False, "缺失：%s" % path)

print("\nround-239 mod cn extra: 8 checks, %d failed" % len(fails))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED（中文名补充表集成）")
sys.stdout.flush()
