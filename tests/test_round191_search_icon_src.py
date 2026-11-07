"""round-191：中文搜索 / 图标通路 / 模组来源 / 内存优化默认值。

四条用户反馈一次验：
1. **中文搜索**：Modrinth 不认中文 → 本地名库 + 机器翻译兜底（含 MyMemory
   的 langpair 方向 bug）；
2. **图标加载**：QNAM 默认吃系统代理，API 走 requests → 两者可能不一致，
   造成「搜索正常、图标全白」；
3. **区分模组下载**：资源中心下载时登记来源，列表标「资源中心」，更新检测
   优先用登记的真 slug；
4. **启动前内存优化默认开**：含老配置的一次性迁移。
"""
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

DEV = tempfile.mkdtemp(prefix="ac_r191_")
os.chdir(DEV)          # dev 模式 get_data_dir() 是 cwd 相对的

fails = []


def check(label, cond, extra=""):
    print("  %s %-56s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


print("① 启动前内存优化默认开 + 一次性迁移")
from src.settings_dialog import _DEFAULTS, _migrate_mem_optimize  # noqa: E402

check("默认值是 True", _DEFAULTS["mem_optimize"] is True)
old_cfg = {"mem_optimize": False}
check("老配置被迁移", _migrate_mem_optimize(old_cfg) is True)
check("迁移后为 True", old_cfg["mem_optimize"] is True)
check("迁移打标记", old_cfg.get("mem_optimize_defaulted") is True)
again = {"mem_optimize": False, "mem_optimize_defaulted": True}
check("已迁移过就不再改（尊重玩家关掉）",
      _migrate_mem_optimize(again) is False and again["mem_optimize"] is False)

print("② 中文搜索：名库命中 / 翻译兜底接线")
from src.net_api import has_cjk, _lookup_cn_slugs  # noqa: E402

check("has_cjk 认中文", has_cjk("小地图") and not has_cjk("minimap"))
check("名库命中「小地图」", bool(_lookup_cn_slugs("小地图")),
      str(_lookup_cn_slugs("小地图")))
check("名库精确优先", _lookup_cn_slugs("小地图")[0] == "xaeros-minimap",
      str(_lookup_cn_slugs("小地图")[:2]))
# MyMemory langpair 方向：中译英必须 zh|en，不能 en|en
src = io.open(os.path.join(HERE, "src", "net_api.py"), encoding="utf-8").read()
check("翻译源语言不再写死 en",
      'langpair": f"{_src}|{_dst}"' in src)
check("按 CJK 判定源语言", '_src = "zh-CN" if has_cjk(chunk) else "en"' in src)
check("中文搜索会走翻译兜底", "translate_text(query, \"en\")" in src)

print("③ 图标：QNAM 代理对齐 download_proxy + 直连兜底")
img = io.open(os.path.join(HERE, "src", "async_image.py"),
              encoding="utf-8").read()
check("初始化时应用代理", "self._apply_proxy()" in img)
check("有直连重试", "def _retry_direct" in img)
check("读 download_proxy", 'load_config().get("download_proxy"' in img)
check("失败先直连再负缓存", "if not self._direct_fallback:" in img)
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from src.async_image import get_image_loader  # noqa: E402
from PySide6.QtNetwork import QNetworkProxy  # noqa: E402

loader = get_image_loader()
pinfo = loader._mgr.proxy()
check("默认走直连（不吃系统代理）", pinfo.type() == QNetworkProxy.NoProxy,
      str(pinfo.type()))

print("④ 模组来源：登记 / 读回 / 清理 / slug_map")
from src.core import mod_sources  # noqa: E402
from src.instances import Instance  # noqa: E402

inst = Instance(id="src1", name="S", game_version="1.20.1")
n = mod_sources.record(inst, [
    {"filename": "sodium.jar", "project_id": "AANobbMI", "slug": "sodium",
     "title": "Sodium", "source": "modrinth"},
    {"filename": "fabric-api.jar", "project_id": "P7dR8mSH",
     "slug": "fabric-api", "title": "Fabric API", "source": "modrinth"},
])
check("登记两条", n == 2, str(n))
data = mod_sources.load(inst)
check("读回 sodium", data.get("sodium.jar", {}).get("slug") == "sodium")
check("slug_map 只含有 slug 的",
      mod_sources.slug_map(inst) == {"sodium.jar": "sodium",
                                     "fabric-api.jar": "fabric-api"},
      str(mod_sources.slug_map(inst)))
mod_sources.prune(inst, ["sodium.jar"])
check("prune 清掉不存在的文件", list(mod_sources.load(inst)) == ["sodium.jar"],
      str(list(mod_sources.load(inst))))
mod_sources.forget(inst, "sodium.jar")
check("forget 删单条", mod_sources.load(inst) == {})

print("⑤ 模组列表把来源画出来")
from src.mod_list import ModListPanel  # noqa: E402


def make_jar(path, name):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("fabric.mod.json", json.dumps(
            {"id": name.lower(), "name": name, "version": "1.0"}))


mc = os.path.join(DEV, "mc")
mods = os.path.join(mc, "mods")
os.makedirs(mods, exist_ok=True)
make_jar(os.path.join(mods, "sodium.jar"), "Sodium")
make_jar(os.path.join(mods, "local.jar"), "LocalMod")

inst2 = Instance(id="src2", name="S2", game_version="1.20.1", _base=mc)
mod_sources.record(inst2, [{"filename": "sodium.jar",
                            "project_id": "AANobbMI", "slug": "sodium"}])
panel = ModListPanel(None, inst2)
rows = {os.path.basename(r.path): r for r in panel._all}
check("sodium 带来源记录", rows["sodium.jar"].source.get("slug") == "sodium")
check("local 没有来源记录", not rows["local.jar"].source)
from PySide6.QtWidgets import QLabel  # noqa: E402

pills = [w.text() for w in rows["sodium.jar"].findChildren(QLabel)]
check("行上出现「资源中心」标", "资源中心" in pills, str(pills))
pills2 = [w.text() for w in rows["local.jar"].findChildren(QLabel)]
check("本地 mod 没有这个标", "资源中心" not in pills2, str(pills2))
panel.deleteLater()

print("⑥ 更新检测优先用登记的真 slug")
upd = io.open(os.path.join(HERE, "src", "mod_updater.py"),
              encoding="utf-8").read()
check("check_updates 接受 slug_map", "slug_map: dict | None = None" in upd)
check("优先用 slug_map", '(slug_map or {}).get(filename) or _resolve_slug' in upd)

shutil.rmtree(DEV, ignore_errors=True)
print()
if fails:
    print("FAILED %d 项：" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-191 中文搜索 / 图标 / 来源 / 内存优化）")
