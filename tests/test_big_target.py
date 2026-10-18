"""round-111 单元测试：_is_big_target 目标判定（诊断脚本，不入库）。"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.mirror import _is_big_target  # noqa: E402

BS = chr(92)  # backslash

CASES = [
    ("C:/mc/versions/1.20.1/1.20.1.jar", True, "客户端 jar (正斜杠)"),
    ("C:" + BS + "mc" + BS + "versions" + BS + "1.20.1" + BS + "1.20.1.jar",
     True, "客户端 jar (反斜杠)"),
    ("C:/mc/versions/1.20.1/1.20.1.jar.part", False, "part 残件"),
    ("C:/mc/libraries/com/mojang/xyz-1.0.jar", False, "普通 library"),
    ("C:/mc/versions/1.20.1/1.20.1.json", False, "版本 json"),
    ("C:/mc/assets/objects/ab/cdef", False, "asset object"),
    ("C:/mc/runtime/java-21/bin/java", False, "runtime 文件"),
    ("C:/mc/versions/1.20.1/other.jar", False, "同目录别的 jar"),
    ("1.20.1.jar", False, "裸文件名"),
    ("", False, "空串"),
    (None, False, "None"),
    ("/home/user/.minecraft/versions/1.19/1.19.jar", True, "Linux 风格"),
]

bad = 0
for path, want, label in CASES:
    got = _is_big_target(path)
    ok = got == want
    if not ok:
        bad += 1
    print("  %s %-24s want=%-5s got=%s" % ("OK  " if ok else "FAIL",
                                           label, want, got))
print()
print("全部通过" if bad == 0 else "%d 个失败" % bad)
sys.exit(1 if bad else 0)
