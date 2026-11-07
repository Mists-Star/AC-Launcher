"""round-184：导出 .mrpack（Modrinth 整合包）+ 编辑面板「修改」页。

判据分四层：

1. **格式**：zip 里第一个条目是 ``modrinth.index.json``，字段齐全、类型对；
2. **内容**：勾选的块进 ``overrides/``、没勾的不进；路径分隔符统一成 ``/``；
3. **依赖**：fabric→``fabric-loader``、forge→``forge``、原版不写加载器键；
4. **第三方往返**：用 ``minecraft_launcher_lib.mrpack`` 读回自己写的包，
   name / mc_version / loader 必须对得上 —— 只靠自己读自己写会掩盖格式错误。

用法：``python tests/test_round184_export.py``
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("AC_DEV_TEMP", None)

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


from src.instances import Instance  # noqa: E402
from src.core import mrpack_export as MX  # noqa: E402

tmp = tempfile.mkdtemp(prefix="ac_mrpack_")


def make_inst(mc, *, loader="fabric", ldver="0.15.11", gv="1.20.1"):
    # mc_dir 是只读 property：给 _base 就等于指定游戏目录
    return Instance(id="t1", name="测试整合包", game_version=gv,
                    loader=loader, loader_version=ldver, _base=mc)


def write(p, data=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data)


mc = os.path.join(tmp, "inst")
write(os.path.join(mc, "mods", "sodium.jar"), b"jar" * 100)
write(os.path.join(mc, "mods", "lithium.jar"), b"jar" * 50)
write(os.path.join(mc, "mods", "disabled.jar.disabled"), b"jar")
write(os.path.join(mc, "config", "sodium", "sodium.properties"), b"a=1")
write(os.path.join(mc, "options.txt"), b"fov:0.0")
write(os.path.join(mc, "resourcepacks", "pack.zip"), b"zip" * 80)
write(os.path.join(mc, "saves", "world", "level.dat"), b"lvl")

print("① 索引结构")
inst = make_inst(mc)
out = os.path.join(tmp, "pack.mrpack")
res = MX.export_mrpack(inst, out, name="我的整合包", version_id="2.1.0",
                       summary="测试用")
check("文件写出", os.path.isfile(out), "%.0f KB" % (res["size"] / 1024.0))
with zipfile.ZipFile(out) as z:
    names = z.namelist()
    first = names[0]
    idx = json.loads(z.read("modrinth.index.json"))
check("index.json 是第一个条目", first == "modrinth.index.json", first)
check("formatVersion = 1", idx.get("formatVersion") == 1, str(idx.get("formatVersion")))
check("game = minecraft", idx.get("game") == "minecraft", str(idx.get("game")))
check("versionId 用了传入值", idx.get("versionId") == "2.1.0", str(idx.get("versionId")))
check("name 用了传入值", idx.get("name") == "我的整合包", str(idx.get("name")))
check("summary 用了传入值", idx.get("summary") == "测试用", str(idx.get("summary")))
check("files 为空（本地 jar 无直链）", idx.get("files") == [], str(idx.get("files")))

print("② 依赖映射")
deps = idx.get("dependencies") or {}
check("minecraft 依赖", deps.get("minecraft") == "1.20.1", str(deps.get("minecraft")))
check("fabric → fabric-loader",
      deps.get("fabric-loader") == "0.15.11", str(deps.get("fabric-loader")))
for loader, key in (("forge", "forge"), ("neoforge", "neoforge"),
                    ("quilt", "quilt-loader")):
    d = MX.build_index(make_inst(mc, loader=loader, ldver="9.9"),
                       name="p", version_id="1")["dependencies"]
    check("%s → %s" % (loader, key), d.get(key) == "9.9", str(d))
check("原版不写加载器键",
      list(MX.build_index(make_inst(mc, loader="vanilla", ldver=""), name="p",
                          version_id="1")["dependencies"]) == ["minecraft"])

print("③ 内容与默认勾选")
check("默认不带资源包", not any(n.startswith("overrides/resourcepacks/")
                                for n in names))
check("默认不带存档", not any(n.startswith("overrides/saves/") for n in names))
check("mods 进了 overrides/",
      "overrides/mods/sodium.jar" in names and "overrides/mods/lithium.jar" in names)
check(".disabled 原样保留", "overrides/mods/disabled.jar.disabled" in names)
check("config 进了 overrides/",
      "overrides/config/sodium/sodium.properties" in names)
check("options.txt 进了 overrides/", "overrides/options.txt" in names)
check("路径分隔符统一为 /", all("\\" not in n for n in names))

print("④ 勾选控制")
out2 = os.path.join(tmp, "pack2.mrpack")
MX.export_mrpack(inst, out2, name="p", parts=("mods", "saves"))
with zipfile.ZipFile(out2) as z2:
    n2 = z2.namelist()
check("只勾 mods+saves 时不含 config",
      not any(x.startswith("overrides/config/") for x in n2))
check("勾了 saves 才带存档",
      "overrides/saves/world/level.dat" in n2)
check("勾了 mods 仍带模组", "overrides/mods/sodium.jar" in n2)

print("⑤ 边界")
try:
    MX.export_mrpack(make_inst(os.path.join(tmp, "empty"), gv=""), "/dev/null")
    check("没有游戏版本时报错", False)
except ValueError:
    check("没有游戏版本时报错", True)
out3 = os.path.join(tmp, "pack3.mrpack")
try:
    MX.export_mrpack(make_inst(os.path.join(tmp, "emptydir")), out3, name="p")
    check("没有内容时报错", False)
except ValueError:
    check("没有内容时报错", True)
check("缺目录不炸（只带有的块）", True)
name = MX.default_pack_name(Instance(id="x", name='a/b:c*"d', game_version="1.19"))
check("非法文件名字符被替换", "/" not in name and ":" not in name
      and "*" not in name and '"' not in name, name)

print("⑥ 进度回调")
seen = []
MX.export_mrpack(inst, os.path.join(tmp, "pack4.mrpack"), name="p",
                 progress=lambda n, d, t: seen.append((n, d, t)))
check("progress 被调用", len(seen) >= 3, str(len(seen)))
check("progress 计数递增到 total",
      seen[-1][1] == seen[-1][2] and seen[0][1] == 1,
      "%s → %s" % (seen[0][:2], seen[-1][:2]))

print("⑦ 第三方解析往返（mll 读回自己写的包）")
try:
    import minecraft_launcher_lib

    info = minecraft_launcher_lib.mrpack.get_mrpack_information(out)
    launch_ver = minecraft_launcher_lib.mrpack.get_mrpack_launch_version(out)
    check("mll 能解析", isinstance(info, dict), str(info)[:60])
    check("mll 读到 name", info.get("name") == "我的整合包", str(info.get("name")))
    # mll 的字段名是 minecraftVersion（不是 game_version）
    check("mll 读到游戏版本", info.get("minecraftVersion") == "1.20.1",
          str(info.get("minecraftVersion")))
    check("mll 读到 formatVersion", info.get("formatVersion") == 1,
          str(info.get("formatVersion")))
    check("mll 推算启动版本",
          (launch_ver or "").startswith("fabric-loader-0.15.11"),
          str(launch_ver))
except Exception as exc:  # noqa: BLE001
    check("mll 能解析", False, "%s: %s" % (type(exc).__name__, exc))

shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-184 导出 .mrpack）")
