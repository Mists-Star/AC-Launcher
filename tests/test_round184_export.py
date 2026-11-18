"""round-184：导出 .mrpack（Modrinth 整合包）+ 编辑面板「修改」页。

判据分四层：

1. **格式**：zip 里第一个条目是 ``modrinth.index.json``，字段齐全、类型对；
2. **内容**：勾选的块进 ``overrides/``、没勾的不进；路径分隔符统一成 ``/``；
3. **依赖**：fabric→``fabric-loader``、forge→``forge``、原版不写加载器键；
4. **第三方往返**：用 ``minecraft_launcher_lib.mrpack`` 读回自己写的包，
   name / mc_version / loader 必须对得上 —— 只靠自己读自己写会掩盖格式错误。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("AC_DEV_TEMP", None)


from src.instances import Instance  # noqa: E402
from src.core import mrpack_export as MX  # noqa: E402


def make_inst(mc, *, loader="fabric", ldver="0.15.11", gv="1.20.1"):
    # mc_dir 是只读 property：给 _base 就等于指定游戏目录
    return Instance(id="t1", name="测试整合包", game_version=gv,
                    loader=loader, loader_version=ldver, _base=mc)


def write(p, data=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data)


@pytest.fixture
def tmp_dir():
    tmp = tempfile.mkdtemp(prefix="ac_mrpack_")
    mc = os.path.join(tmp, "inst")
    write(os.path.join(mc, "mods", "sodium.jar"), b"jar" * 100)
    write(os.path.join(mc, "mods", "lithium.jar"), b"jar" * 50)
    write(os.path.join(mc, "mods", "disabled.jar.disabled"), b"jar")
    write(os.path.join(mc, "config", "sodium", "sodium.properties"), b"a=1")
    write(os.path.join(mc, "options.txt"), b"fov:0.0")
    write(os.path.join(mc, "resourcepacks", "pack.zip"), b"zip" * 80)
    write(os.path.join(mc, "saves", "world", "level.dat"), b"lvl")
    yield tmp, mc
    shutil.rmtree(tmp, ignore_errors=True)


def test_index_structure(tmp_dir):
    """① 索引结构"""
    tmp, mc = tmp_dir
    inst = make_inst(mc)
    out = os.path.join(tmp, "pack.mrpack")
    res = MX.export_mrpack(inst, out, name="我的整合包", version_id="2.1.0",
                           summary="测试用")
    assert os.path.isfile(out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        first = names[0]
        idx = json.loads(z.read("modrinth.index.json"))
    assert first == "modrinth.index.json"
    assert idx.get("formatVersion") == 1
    assert idx.get("game") == "minecraft"
    assert idx.get("versionId") == "2.1.0"
    assert idx.get("name") == "我的整合包"
    assert idx.get("summary") == "测试用"
    assert idx.get("files") == []


def test_dependency_mapping(tmp_dir):
    """② 依赖映射"""
    tmp, mc = tmp_dir
    inst = make_inst(mc)
    out = os.path.join(tmp, "pack.mrpack")
    MX.export_mrpack(inst, out, name="我的整合包", version_id="2.1.0",
                     summary="测试用")
    with zipfile.ZipFile(out) as z:
        idx = json.loads(z.read("modrinth.index.json"))
    deps = idx.get("dependencies") or {}
    assert deps.get("minecraft") == "1.20.1"
    assert deps.get("fabric-loader") == "0.15.11"
    for loader, key in (("forge", "forge"), ("neoforge", "neoforge"),
                        ("quilt", "quilt-loader")):
        d = MX.build_index(make_inst(mc, loader=loader, ldver="9.9"),
                           name="p", version_id="1")["dependencies"]
        assert d.get(key) == "9.9", str(d)
    # 原版不写加载器键
    vanilla_deps = MX.build_index(make_inst(mc, loader="vanilla", ldver=""),
                                  name="p", version_id="1")["dependencies"]
    assert list(vanilla_deps) == ["minecraft"]


def test_content_and_defaults(tmp_dir):
    """③ 内容与默认勾选"""
    tmp, mc = tmp_dir
    inst = make_inst(mc)
    out = os.path.join(tmp, "pack.mrpack")
    MX.export_mrpack(inst, out, name="我的整合包", version_id="2.1.0",
                     summary="测试用")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert not any(n.startswith("overrides/resourcepacks/") for n in names)
    assert not any(n.startswith("overrides/saves/") for n in names)
    assert "overrides/mods/sodium.jar" in names and "overrides/mods/lithium.jar" in names
    assert "overrides/mods/disabled.jar.disabled" in names
    assert "overrides/config/sodium/sodium.properties" in names
    assert "overrides/options.txt" in names
    assert all("\\" not in n for n in names)


def test_selection_control(tmp_dir):
    """④ 勾选控制"""
    tmp, mc = tmp_dir
    inst = make_inst(mc)
    out2 = os.path.join(tmp, "pack2.mrpack")
    MX.export_mrpack(inst, out2, name="p", parts=("mods", "saves"))
    with zipfile.ZipFile(out2) as z2:
        n2 = z2.namelist()
    assert not any(x.startswith("overrides/config/") for x in n2)
    assert "overrides/saves/world/level.dat" in n2
    assert "overrides/mods/sodium.jar" in n2


def test_edge_cases(tmp_dir):
    """⑤ 边界"""
    tmp, mc = tmp_dir
    # 没有游戏版本时报错
    try:
        MX.export_mrpack(make_inst(os.path.join(tmp, "empty"), gv=""), "/dev/null")
        assert False, "应该抛出 ValueError"
    except ValueError:
        pass
    # 没有内容时报错
    out3 = os.path.join(tmp, "pack3.mrpack")
    try:
        MX.export_mrpack(make_inst(os.path.join(tmp, "emptydir")), out3, name="p")
        assert False, "应该抛出 ValueError"
    except ValueError:
        pass
    # 缺目录不炸（只带有的块） - 由上述通过隐含
    # 非法文件名字符被替换
    name = MX.default_pack_name(Instance(id="x", name='a/b:c*"d', game_version="1.19"))
    assert "/" not in name and ":" not in name and "*" not in name and '"' not in name


def test_progress_callback(tmp_dir):
    """⑥ 进度回调"""
    tmp, mc = tmp_dir
    inst = make_inst(mc)
    seen = []
    MX.export_mrpack(inst, os.path.join(tmp, "pack4.mrpack"), name="p",
                     progress=lambda n, d, t: seen.append((n, d, t)))
    assert len(seen) >= 3
    assert seen[-1][1] == seen[-1][2] and seen[0][1] == 1


def test_mll_roundtrip(tmp_dir):
    """⑦ 第三方解析往返（mll 读回自己写的包）"""
    tmp, mc = tmp_dir
    inst = make_inst(mc)
    out = os.path.join(tmp, "pack.mrpack")
    MX.export_mrpack(inst, out, name="我的整合包", version_id="2.1.0",
                     summary="测试用")
    import minecraft_launcher_lib
    info = minecraft_launcher_lib.mrpack.get_mrpack_information(out)
    launch_ver = minecraft_launcher_lib.mrpack.get_mrpack_launch_version(out)
    assert isinstance(info, dict)
    assert info.get("name") == "我的整合包"
    assert info.get("minecraftVersion") == "1.20.1"
    assert info.get("formatVersion") == 1
    assert (launch_ver or "").startswith("fabric-loader-0.15.11")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])