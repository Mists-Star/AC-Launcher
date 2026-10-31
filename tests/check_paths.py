"""round-159 回归测试：IA 用户路径表是否与源码标记同步。

`tools/gen_paths.py` 从 `# ia[page]: 操作 | 层/组件 | 结果` 标记生成
`docs/ia/paths.md`；本脚本以 --check 模式比对，文档过期即失败。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(HERE, "tools", "gen_paths.py")

if not os.path.isfile(GEN):
    print("缺少 tools/gen_paths.py（跳过）")
    sys.exit(0)

p = subprocess.run(
    [sys.executable, GEN, "--check"],
    cwd=HERE, capture_output=True, text=True,
)
out = (p.stdout or "").strip()
err = (p.stderr or "").strip()
if out:
    print(out)
if err:
    print(err)
sys.exit(p.returncode)
