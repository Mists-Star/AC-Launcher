"""新建实例向导信号 arity 回归（2026-11-06 真机 P0）。

事故：round-163~174（commit 4811b8f）给 `result_data()` 末尾加了
`format` / `base` 两个字段，版本页弹窗路径同步改成 7 元解包，但嵌入式
向导的 `created` 信号仍定义为 5 参 → `self.created.emit(*self.result_data())`
抛 `TypeError: created(...) only accepts 5 argument(s), 7 given!`。
Qt 槽内异常只被 sys.excepthook 写进 `data/crash.log`，界面表现为
「点创建毫无反应、不弹框、不关闭向导」，真机连点 15 次全静默失败。

判据分三层：
  1. 运行时真相：Qt 元对象里 created 的参数个数；
  2. 源头一致：result_data 返回元组长度 == 信号 arity == 槽形参数；
  3. 全仓防再犯：扫所有 Signal 定义与同类内 emit 常量参数个数。
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with io.open(os.path.join(HERE, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def find_class(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def find_func(cls, name):
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def meta_text(value):
    """QMetaMethod 的文本字段在不同 shiboken 版本可能是 bytes，也可能是
    "b'xxx'" 形态的 str（本环境实测后者）。统一还原成纯文本。"""
    if isinstance(value, bytes):
        return value.decode()
    text = str(value)
    if len(text) > 3 and text[0] == "b" and text[1] in "\"'" and text[-1] == text[1]:
        return text[2:-1]
    return text


def signal_arities(cls):
    """类体内 `xxx = Signal(...)` 的名字 → 参数个数。"""
    out = {}
    for node in cls.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        fname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        if fname != "Signal":
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = len(node.value.args)
    return out


def emits_in(cls):
    """类体内 `self.<sig>.emit(...)` 的 (信号名, 位置参数个数, 是否含 *展开)。"""
    out = []
    for node in ast.walk(cls):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "emit"):
            continue
        owner = fn.value
        if not (isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name)
                and owner.value.id == "self"):
            continue
        starred = any(isinstance(a, ast.Starred) for a in node.args)
        out.append((owner.attr, len([a for a in node.args if not isinstance(a, ast.Starred)]), starred))
    return out


print("== 新建实例信号 arity 回归 ==")

# ── 1. 运行时真相：Qt 元对象 ────────────────────────────────────────────
try:
    from PySide6.QtCore import QMetaMethod
    from src.pages_instances import NewInstanceDialog

    mo = NewInstanceDialog.staticMetaObject
    qt_arity, qt_sig = None, ""
    for i in range(mo.methodCount()):
        m = mo.method(i)
        # 用规范化 signature 匹配，而不是 name()：本环境 name() 返回的是
        # "b'created'" 形态的 str，直接比较会漏判。
        sig = meta_text(m.methodSignature())
        if sig.startswith("created(") and m.methodType() == QMetaMethod.Signal:
            qt_arity = m.parameterCount()
            qt_sig = sig
            break
    check("Qt 元对象里 created 是 7 参信号", qt_arity == 7,
          "arity=%s sig=%s" % (qt_arity, qt_sig))
except Exception as exc:  # pragma: no cover
    check("Qt 元对象里 created 是 7 参信号", False, repr(exc))

# ── 2. 源头一致：返回值 / 信号 / 槽 / 版本页解包 ────────────────────────
src_pi = read(os.path.join("src", "pages_instances.py"))
tree = ast.parse(src_pi)
cls_dlg = find_class(tree, "NewInstanceDialog")
cls_page = find_class(tree, "InstancesPage")

declared = signal_arities(cls_dlg).get("created")
check("源码声明 created 为 7 参", declared == 7, "declared=%s" % declared)

ret_len = None
func = find_func(cls_dlg, "result_data")
for node in ast.walk(func):
    if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
        ret_len = len(node.value.elts)
        break
check("result_data 返回 7 元组", ret_len == 7, "len=%s" % ret_len)
check("信号 arity 与 result_data 长度一致", declared == ret_len,
      "%s vs %s" % (declared, ret_len))

slot = find_func(cls_page, "_on_new_created")
slot_args = len(slot.args.args) - 1 if slot else -1
check("槽 _on_new_created 可接收 7 参", slot_args >= 7, "args=%s" % slot_args)
check("槽把 fmt/base 透传给 mgr.add",
      slot is not None and "format=fmt" in ast.get_source_segment(src_pi, slot),
      "")

src_pb = read(os.path.join("src", "pages_browse.py"))
check("版本页弹窗路径按 7 元解包",
      "name, version, loader, java_path, ldver, fmt, base = dlg.result_data()" in src_pb)

# ── 3. 全仓防再犯：Signal 定义 arity >= 同类 emit 常量参数个数 ───────────
scan_files = [os.path.join("src", f) for f in sorted(os.listdir(os.path.join(HERE, "src")))
              if f.endswith(".py")] + ["main.py"]
mismatch = []
scanned = 0
for rel in scan_files:
    try:
        t = ast.parse(read(rel))
    except SyntaxError:
        continue
    for cls in [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]:
        arities = signal_arities(cls)
        if not arities:
            continue
        for sig, nargs, starred in emits_in(cls):
            if starred or sig not in arities:
                continue
            scanned += 1
            if nargs > arities[sig]:
                mismatch.append("%s:%s.%s emit %d > %d" %
                                (rel, cls.name, sig, nargs, arities[sig]))
check("全仓 Signal/emit arity 无超参（检查 %d 处）" % scanned,
      not mismatch, "; ".join(mismatch[:3]))

print("== %s ==" % ("PASS" if not fails else "FAIL %d" % len(fails)))
sys.exit(1 if fails else 0)
