"""round-177：模组下载真缺口 + 实例页启动诊断按钮。

覆盖：
  A. 下载层：分片不预删已存在的 dest、`_safe_filename` 挡路径穿越、
     `_verify_sha1` 命中/不匹配、依赖树本体失败不再静默吞掉；
  B. 崩溃补前置：带 MC 版本/加载器、不再用 `hits[0]` 模糊兜底；
  C. 实例页按钮：文案不再是「启动」、`_launch` 真的打开诊断；
  D. 诊断对话框：两页都有实内容、token 恒为占位符、中英 20 个键对齐。
"""
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

fails = []


def check(label, cond, extra=""):
    print("  %s %-58s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(HERE, rel), "r", encoding="utf-8") as f:
        return f.read()


from src import net_api, crash_analysis, i18n  # noqa: E402

print("== round-177 模组链路 / 启动诊断 ==")

# ── A. 下载层 ──────────────────────────────────────────────────────
na = read("src/net_api.py")
check("分片下载不再预删 dest（避免删掉已装 mod/jar）",
      "if os.path.exists(dest):\n        os.remove(dest)" not in na
      and "绝不预删 dest" in na)
check("_safe_filename 挡住 ../ 路径穿越",
      net_api._safe_filename("../../evil.jar") == "evil.jar"
      and net_api._safe_filename("..\\nested\\x.jar") == "x.jar"
      and net_api._safe_filename("") == "download.jar")
check("5 处文件名拼接都走了清洗",
      na.count("_safe_filename(filename)") == 4
      and na.count('_safe_filename(item["filename"])') == 2,
      "fn=%d item=%d" % (na.count("_safe_filename(filename)"),
                         na.count('_safe_filename(item["filename"])')))

TMP = tempfile.mkdtemp(prefix="_r177_")
good = os.path.join(TMP, "ok.jar")
open(good, "wb").write(b"abc123")
import hashlib  # noqa: E402
sha = hashlib.sha1(b"abc123").hexdigest()
net_api._verify_sha1(good, sha)
check("sha1 匹配时保留文件", os.path.isfile(good))
bad = os.path.join(TMP, "bad.jar")
open(bad, "wb").write(b"tampered")
err = ""
try:
    net_api._verify_sha1(bad, sha)
except Exception as e:  # noqa: BLE001
    err = type(e).__name__
check("sha1 不匹配抛错并删除坏文件",
      err == "NetError" and not os.path.exists(bad), err)

orig_versions = net_api._modrinth_versions
net_api._modrinth_versions = lambda *a, **k: (_ for _ in ()).throw(
    net_api.NetError("offline"))
err2 = ""
try:
    net_api.resolve_mod_dependencies("P7dR8mSH", "1.21.1", "fabric")
except Exception as e:  # noqa: BLE001
    err2 = type(e).__name__
check("依赖树本体网络错误不再静默返回空清单", err2 == "NetError", err2)
net_api._modrinth_versions = orig_versions

# ── B. 崩溃补前置 ──────────────────────────────────────────────────
ca = read("src/crash_analysis.py")
check("自动补前置带 MC 版本 + 加载器",
      'getattr(inst, "game_version", "")' in ca
      and 'getattr(inst, "loader", "")' in ca
      and "download_mod_to(" in ca)
check("不再用 hits[0] 模糊兜底装无关模组",
      "target = hits[0]" not in ca)

calls = []


def fake_search(*a, **k):
    return [{"slug": "totally-unrelated", "title": "Unrelated",
             "project_id": "XXXX"}]


def fake_download(project_id, dest, *a, **k):
    calls.append((project_id, dest, a))
    return os.path.join(dest, "fake.jar")


# search_and_download_missing 内部是 `from .net_api import ...`，
# 所以直接 monkeypatch 模块属性即可，全程不联网。
import src.net_api as _na  # noqa: E402
_s0, _d0 = _na.search_mods, _na.download_mod_to
_na.search_mods, _na.download_mod_to = fake_search, fake_download
try:
    downloaded, failed = crash_analysis.search_and_download_missing(
        types.SimpleNamespace(mods_dir=TMP, game_version="1.21.1",
                              loader="fabric"),
        ["some-dep"])
finally:
    _na.search_mods, _na.download_mod_to = _s0, _d0
check("模糊未命中时标 failed、不下载无关模组",
      not downloaded and failed == ["some-dep"] and not calls,
      "downloaded=%r failed=%r" % (downloaded, failed))

_na.search_mods = lambda *a, **k: [
    {"slug": "fabric-api", "title": "Fabric API", "project_id": "P7dR8mSH"}]
_na.download_mod_to = fake_download
try:
    crash_analysis.search_and_download_missing(
        types.SimpleNamespace(mods_dir=TMP, game_version="1.21.1",
                              loader="fabric"), ["fabric-api"])
finally:
    _na.search_mods, _na.download_mod_to = _s0, _d0
check("精确命中时把版本/加载器传给 download_mod_to",
      calls and calls[0][2][:2] == ("1.21.1", "fabric"),
      str(calls[:1]))

# ── C. 实例页按钮 ──────────────────────────────────────────────────
pi = read("src/pages_instances.py")
check("按钮文案改为诊断键且注释说明旧行为",
      'QPushButton(t("instances.launch"))' in pi
      and "体检 / 启动诊断" in pi and "名不副实" in pi)
check("_launch 真的打开诊断对话框",
      "open_launch_diagnostics" in pi.split("def _launch")[1][:900]
      and "self.mgr.set_current(inst_id)" in pi.split("def _launch")[1][:900])
check("文案不再是光秃秃的「启动」",
      i18n.t("instances.launch") == "体检 / 启动诊断")

# ── D. 诊断对话框行为 ──────────────────────────────────────────────
from src.launch_diagnostics_dialog import LaunchDiagnosticsDialog  # noqa: E402

inst = types.SimpleNamespace(
    id="x", name="Demo", game_dir=TMP, mc_dir=TMP,
    game_version="1.21.1", version_id="1.21.1", loader="fabric",
    java_path="", ram_mb=4096, jvm_args="", mods_dir=TMP,
)
dlg = LaunchDiagnosticsDialog(inst)
cmd_txt = dlg._cmd_view.toPlainText()
health_txt = dlg._health_view.toPlainText()
check("命令页有实例/版本/Java/游戏目录四行实信息",
      "Demo" in cmd_txt and "1.21.1" in cmd_txt and "fabric" in cmd_txt
      and TMP in cmd_txt)
check("命令拼不出来时如实写原因，不假装成功",
      "无法生成启动命令" in cmd_txt or "classpath 条目" in cmd_txt,
      cmd_txt.splitlines()[-1][:50] if cmd_txt else "")
diag_src = read("src/launch_diagnostics_dialog.py")
check("build_options 的 token 恒为占位常量、不读真实账号",
      '_PLACEHOLDER_TOKEN = "<ACCESS_TOKEN>"' in diag_src
      and "launch.build_options(" in diag_src
      and "_PLACEHOLDER_TOKEN," in diag_src
      and "access_token" not in diag_src)
check("体检页有摘要且非空",
      bool(health_txt.strip()) and ("严重" in health_txt
                                   or "未发现问题" in health_txt))
check("两个 tab 都在", dlg._tabs.count() == 2)
dlg.deleteLater()

zh, en = i18n._STRINGS["zh-CN"], i18n._STRINGS["en-US"]
NEW_KEYS = ["diag.title", "diag.subtitle", "diag.tab_command",
            "diag.tab_health", "diag.copy", "diag.copied",
            "diag.open_health", "diag.close", "diag.info.instance",
            "diag.info.version", "diag.info.java", "diag.info.gamedir",
            "diag.info.classpath", "diag.info.missing",
            "diag.info.classpath_ok", "diag.cmd_failed", "diag.cmd_hint",
            "diag.health_summary", "diag.health_failed", "diag.no_findings"]
# 仓库里本来就有 diag.* 旧键，所以只验「本轮新增的 20 个」两边都齐，
# 不能拿 diag.* 总数当尺子。
check("i18n 中英键数一致且本轮 20 个新键两边都有实文案",
      len(zh) == len(en) and not (set(zh) ^ set(en))
      and all(k in zh and k in en and zh[k] and en[k] for k in NEW_KEYS),
      "zh=%d en=%d new=%d" % (len(zh), len(en), len(NEW_KEYS)))

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print("== %s ==" % ("PASS" if not fails else "FAIL %d" % len(fails)))
sys.exit(1 if fails else 0)
