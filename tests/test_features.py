"""round-167 功能扩展包回归：可删除 / 可重装 / 动态加载 / 异常隔离。

纯逻辑（不建 Qt 窗口），全部在临时目录里跑，不碰真实 data/features。
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import src.features as F  # noqa: E402

FAILS = []


def check(label, cond):
    if cond:
        print("  PASS  %s" % label)
    else:
        print("  FAIL  %s" % label)
        FAILS.append(label)


def write_pack(folder, fid, entry_src="def create_page(ctx):\n    return object()\n",
               version="1.0.0"):
    os.makedirs(folder, exist_ok=True)
    m = {
        "schema_version": 1,
        "id": fid,
        "name": fid,
        "name_en": fid,
        "version": version,
        "entry": "entry.py",
        "icon": "tools",
        "nav_group": "extensions",
    }
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    with open(os.path.join(folder, "entry.py"), "w", encoding="utf-8") as f:
        f.write(entry_src)


print("== round-167 功能扩展包 ==")

tmp = tempfile.mkdtemp(prefix="ac_feat_test_")
data_root = os.path.join(tmp, "data")
bundle_root = os.path.join(tmp, "bundled")
os.makedirs(data_root, exist_ok=True)
os.makedirs(bundle_root, exist_ok=True)
write_pack(os.path.join(bundle_root, "demo"), "demo")
write_pack(os.path.join(bundle_root, "second"), "second")

# ---- 1. validate_manifest ----
check("合法清单通过", F.validate_manifest(
    {"id": "abc", "name": "n", "version": "1", "entry": "entry.py"},
    folder_name="abc") == "abc")
for bad, why in (
    ({"id": "a/b", "name": "n", "version": "1"}, "id 非法"),
    ({"id": "abc", "name": "", "version": "1"}, "缺 name"),
    ({"id": "abc", "name": "n", "version": ""}, "缺 version"),
    ({"id": "abc", "name": "n", "version": "1", "entry": "../evil.py"}, "entry 穿越"),
):
    try:
        F.validate_manifest(bad)
        check(why + " 被拒绝", False)
    except F.FeatureError:
        check(why + " 被拒绝", True)

try:
    F.validate_manifest({"id": "abc", "name": "n", "version": "1"}, folder_name="zzz")
    check("目录名与 id 不一致被拒绝", False)
except F.FeatureError:
    check("目录名与 id 不一致被拒绝", True)

# ---- 1b. 保护措施：保留 id / 字段类型与长度 / order / URL 策略 ----
for bad, why in (
    ({"id": "settings", "name": "n", "version": "1"}, "与核心页面重名的 id"),
    ({"id": "abc", "name": 123, "version": "1"}, "name 非字符串"),
    ({"id": "abc", "name": "n" * 100, "version": "1"}, "name 过长"),
    ({"id": "abc", "name": "n", "version": "1", "order": "abc"}, "order 非整数"),
    ({"id": "abc", "name": "n", "version": "1", "icon": "../x"}, "icon 非法"),
):
    try:
        F.validate_manifest(bad)
        check(why + " 被拒绝", False)
    except F.FeatureError:
        check(why + " 被拒绝", True)

check("order 越界被夹紧", F._order_of({"order": 10 ** 6}) == F._MAX_ORDER)

for url, ok in (
    ("https://github.com/x.zip", True),
    ("http://127.0.0.1:8080/x.zip", True),
    ("http://example.com/x.zip", False),
    ("file:///x.zip", False),
):
    try:
        F._check_url(url)
        check("URL 策略：" + url, ok)
    except F.FeatureError:
        check("URL 策略：" + url, not ok)

big_manifest = os.path.join(tmp, "big_manifest.json")
with open(big_manifest, "w", encoding="utf-8") as f:
    json.dump({"id": "big", "name": "n", "version": "1",
               "description": "d" * 300000}, f)
try:
    F._read_json(big_manifest)
    check("超大 manifest 被拒绝", False)
except F.FeatureError:
    check("超大 manifest 被拒绝", True)

# ---- 2. ensure_builtins：首次装、二次不重装、删除后不自动恢复 ----
installed = F.ensure_builtins(dest_root=data_root, bundled=bundle_root)
check("首次安装两个内置包", sorted(installed) == ["demo", "second"])
check("磁盘上出现 demo", os.path.isdir(os.path.join(data_root, "demo")))
installed2 = F.ensure_builtins(dest_root=data_root, bundled=bundle_root)
check("二次调用不重复安装", installed2 and installed2 == sorted(installed2))
demo_entry = os.path.join(data_root, "demo", "entry.py")
before = os.stat(demo_entry).st_mtime_ns
F.ensure_builtins(dest_root=data_root, bundled=bundle_root)
check("已在磁盘的包不被覆盖", os.stat(demo_entry).st_mtime_ns == before)

F.uninstall("demo", root=data_root)
check("uninstall 物理删除目录", not os.path.isdir(os.path.join(data_root, "demo")))
after = F.ensure_builtins(dest_root=data_root, bundled=bundle_root)
check("玩家删掉的包不会自动装回",
      not os.path.isdir(os.path.join(data_root, "demo")) and after == ["second"])

restored = F.restore_builtin("demo", dest_root=data_root, bundled=bundle_root)
check("restore_builtin 可装回", os.path.isdir(os.path.join(data_root, "demo"))
      and restored.id == "demo")

# ---- 3. scan_installed ----
packs = F.scan_installed(root=data_root)
check("scan_installed 扫到两个包", sorted(p.id for p in packs) == ["demo", "second"])
empty_root = os.path.join(tmp, "empty")
os.makedirs(empty_root, exist_ok=True)
check("空目录返回 []", F.scan_installed(root=empty_root) == [])
check("bundled_ids 含内置 id", F.bundled_ids(bundle_root) == {"demo", "second"})
check("list_builtins 只列未装的", [b["id"] for b in F.list_builtins(
    dest_root=data_root, bundled=bundle_root)] == [])

# ---- 4. install_from_script ----
script_dir = os.path.join(tmp, "scripts")
os.makedirs(script_dir, exist_ok=True)
script = os.path.join(script_dir, "myscript.py")
with open(script, "w", encoding="utf-8") as f:
    f.write("def create_page(ctx):\n    return object()\n")
pack = F.install_from_script(script, root=data_root)
check("脚本安装生成 manifest", os.path.isfile(
    os.path.join(data_root, "myscript", "manifest.json")))
check("脚本安装 id 取自文件名", pack.id == "myscript")
check("脚本安装可被扫描", "myscript" in [p.id for p in F.scan_installed(root=data_root)])
try:
    F.install_from_script(script, root=data_root)
    check("同 id 重复安装被拒绝", False)
except F.FeatureError:
    check("同 id 重复安装被拒绝", True)

for name, src, why in (
    ("nocreate.py", "VALUE = 1\n", "缺 create_page 的脚本"),
    ("bad_syntax.py", "def create_page(ctx:\n", "语法错误脚本"),
    ("settings.py", "def create_page(ctx):\n    return object()\n",
     "与核心页面重名的脚本"),
):
    p = os.path.join(script_dir, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(src)
    try:
        F.install_from_script(p, root=data_root)
        check(why + " 被拒绝", False)
    except F.FeatureError:
        check(why + " 被拒绝", True)

# ---- 5. install_from_folder ----
src_folder = os.path.join(tmp, "manualpack")
write_pack(src_folder, "manualpack", version="2.0")
pack2 = F.install_from_folder(src_folder, root=data_root)
check("文件夹安装成功", pack2.id == "manualpack")
F.uninstall("manualpack", root=data_root)
check("文件夹安装可再卸载", not os.path.isdir(
    os.path.join(data_root, "manualpack")))

# ---- 6. load_page：好包返回页面对象，坏包返回 None 且不抛 ----
good = [p for p in F.scan_installed(root=data_root) if p.id == "demo"][0]
page = F.load_page(good)
check("好包 load_page 返回对象", page is not None)

bad_folder = os.path.join(data_root, "broken")
write_pack(bad_folder, "broken", entry_src="raise RuntimeError('boom')\n")
os.makedirs(os.path.join(data_root, "broken2"), exist_ok=True)
with open(os.path.join(data_root, "broken2", "manifest.json"), "w",
          encoding="utf-8") as f:
    json.dump({"id": "broken2", "name": "b", "version": "1"}, f)
with open(os.path.join(data_root, "broken2", "entry.py"), "w",
          encoding="utf-8") as f:
    f.write("VALUE = 1\n")   # 故意不提供 create_page
bad = [p for p in F.scan_installed(root=data_root) if p.id == "broken"][0]
try:
    r = F.load_page(bad)
    check("坏包 load_page 返回 None", r is None)
    check("坏包记录 last_error", bool(F.last_error()))
    # scan 只做静态检查（不 import），所以 broken2 会被扫到；
    # 但 load_page 发现缺 create_page 时必须安全返回 None。
    scanned = [p.id for p in F.scan_installed(root=data_root)]
    check("缺 create_page 的包仍可被扫描（静态检查）", "broken2" in scanned)
    bad2 = [p for p in F.scan_installed(root=data_root) if p.id == "broken2"][0]
    check("缺 create_page 的包 load_page 返回 None", F.load_page(bad2) is None)
except Exception as e:  # noqa: BLE001
    check("坏包 load_page 不抛异常（%s）" % e, False)

# ---- 7. zip 路径穿越 fail-closed（不依赖外部网络）----
import zipfile  # noqa: E402
evil_zip = os.path.join(tmp, "evil.zip")
with zipfile.ZipFile(evil_zip, "w") as zf:
    zf.writestr("../evil.txt", "x")
try:
    F.install_from_zip(evil_zip, root=data_root)
    check("zip 路径穿越被拒绝", False)
except F.FeatureError:
    check("zip 路径穿越被拒绝", not os.path.exists(
        os.path.join(tmp, "evil.txt")))

# ---- 8. 体积/数量保护 ----
big_entry_dir = os.path.join(data_root, "bigentry")
write_pack(big_entry_dir, "bigentry")
with open(os.path.join(big_entry_dir, "entry.py"), "w",
          encoding="utf-8") as f:
    f.write("# " + "x" * (F._MAX_ENTRY_BYTES + 10)
            + "\ndef create_page(ctx):\n    return object()\n")
check("超大入口包被扫描跳过",
      "bigentry" not in [p.id for p in F.scan_installed(root=data_root)])

many_zip = os.path.join(tmp, "many.zip")
with zipfile.ZipFile(many_zip, "w") as zf:
    for i in range(F._MAX_PACK_FILES + 1):
        zf.writestr("f%04d.txt" % i, "x")
try:
    with zipfile.ZipFile(many_zip, "r") as zf:
        F._check_zip_limits(zf)
    check("超量 zip 被拒绝", False)
except F.FeatureError:
    check("超量 zip 被拒绝", True)

print()
if FAILS:
    print("FAILED %d:" % len(FAILS))
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL PASS")
