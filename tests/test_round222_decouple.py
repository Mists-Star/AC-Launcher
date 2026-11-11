"""round-222：全项目解耦 / 功能查重 / 修复回归（离线，零真实 HTTP / 零窗口）。

本轮四处改动：

1. **P0 列表页 CF 卡片直下缺依赖**（真 bug）：round-220 只把详情页改走
   ``download_cf_with_deps``，列表页仍分三条通道（cfwidget_file /
   cfwidget_slug / keyed project_id），只下本体、不解析 required 依赖、不删
   同 mod 旧 jar → 从列表页装 FTB Ultimine 照样缺 FTB Library 崩游戏。
   新增 ``download_cf_card`` 收敛三通道，归一化出数字 pid + file_id 后统一委托。
2. **P1 manifest id 静默清洗**：``modules.validate_manifest`` 曾把
   ``"ok/../evil"`` 净化成 ``"ok..evil"`` 后放行，与 ``features`` 明确拒绝的
   口径不一致；``install_legacy_theme_pack`` 同源遗漏一并收。
3. **解耦**：5 个对话框壳的 ``__getattr__/__setattr__/closeEvent`` 逐字重复，
   抽成 ``panel_shell.PanelShellMixin``。
4. **查重**：``pages_browse`` / ``pages_instances`` 各有一份逐字相同的 32 行
   ``_on_tick``，抽成 ``modpack_import.tick_import_progress``。

判据全部是**行为断言**，不靠源码字面量（round-221 教训）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import net_api as na            # noqa: E402
from src import modules, features        # noqa: E402
from src.panel_shell import PanelShellMixin  # noqa: E402
from src.modpack_import import tick_import_progress  # noqa: E402
from src.i18n import t                   # noqa: E402

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── 1) P0：download_cf_card 三通道收敛 + 依赖树 ────────────────────────────
print("\n[1] P0 CF card convergence")

calls = []
orig = {
    "with_deps": na.download_cf_with_deps,
    "resolve": na._cf_resolve_dep_file,
    "info": na._cfwidget_info,
    "filter": na._cf_filter_files,
    "key": na._curseforge_key,
}


def _fake_with_deps(pid, fid, dest, mc="", ld="", callback=None,
                    manifest_out=None, with_deps=True, inst=None,
                    primary_sha1=""):
    calls.append({"pid": pid, "fid": fid, "with_deps": with_deps,
                  "inst": inst, "sha1": primary_sha1, "mc": mc, "ld": ld})
    return "/fake/%s.jar" % fid


na.download_cf_with_deps = _fake_with_deps
na._cf_resolve_dep_file = lambda pid, mc, ld: {
    "project_id": str(pid), "file_id": "9205002", "filename": "u.jar",
    "url": "", "sha1": "libsha1"}
na._cfwidget_info = lambda proj: {"id": 448231, "files": []}
na._cf_filter_files = lambda rows, mc="", ld="": rows
na._curseforge_key = lambda: ""

try:
    # (a) cfwidget 命中：带文件 id + 数字 pid
    calls.clear()
    na.download_cf_card("448231", "ftb-ultimine",
                        {"id": 9205002, "name": "u.jar"}, "/tmp/x",
                        mc_version="26.1.2", loader="fabric", inst="INST")
    check("cfwidget 通道委托 with_deps",
          len(calls) == 1 and calls[0]["with_deps"] is True
          and calls[0]["pid"] == "448231" and calls[0]["fid"] == "9205002",
          str(calls[:1]))
    check("cfwidget 通道 inst 透传（删旧 jar 生效的前提）",
          calls[0]["inst"] == "INST", str(calls[0].get("inst")))

    # (b) 只有 slug → 反查数字 pid
    calls.clear()
    na.download_cf_card("ftb-ultimine", "ftb-ultimine", None, "/tmp/x",
                        mc_version="26.1.2", loader="fabric")
    check("slug 通道反查成数字 project_id",
          len(calls) == 1 and calls[0]["pid"] == "448231",
          str(calls[:1]))

    # (c) 只有数字 pid、无 cf_file → 复用 _cf_resolve_dep_file 挑文件
    calls.clear()
    na.download_cf_card("448231", "", None, "/tmp/x",
                        mc_version="26.1.2", loader="fabric")
    check("数字 pid 通道复用 _cf_resolve_dep_file 得到 file_id",
          len(calls) == 1 and calls[0]["fid"] == "9205002",
          str(calls[:1]))

    # (d) 兼容校验：明确不兼容时必须拒绝（round-178 口径）
    na._cf_filter_files = lambda rows, mc="", ld="": []
    calls.clear()
    refused = False
    try:
        na.download_cf_card("448231", "",
                            {"id": 9205002, "name": "u.jar",
                             "gameVersions": ["1.20.1"]}, "/tmp/x",
                            mc_version="26.1.2", loader="fabric")
    except na.NetError:
        refused = True
    check("cf_file 声明不兼容时拒绝下载（不静默装）",
          refused and not calls, "calls=%d" % len(calls))
    na._cf_filter_files = lambda rows, mc="", ld="": rows

    # (e) 整合包链路未被误改：download_curseforge_mod 仍然存在且带 file_id
    import inspect
    sig = str(inspect.signature(na.download_curseforge_mod))
    check("整合包精确下载入口保留 file_id 参数",
          "file_id" in sig, sig)
finally:
    for k, v in orig.items():
        setattr(na, {"with_deps": "download_cf_with_deps",
                     "resolve": "_cf_resolve_dep_file", "info": "_cfwidget_info",
                     "filter": "_cf_filter_files", "key": "_curseforge_key"}[k], v)


# ── 2) P1：manifest id 不再静默清洗 ───────────────────────────────────────
print("\n[2] P1 manifest id strictness")

def _accepts(fn, m, exc):
    try:
        fn(m)
        return True
    except exc:
        return False


_good = {"id": "ok-id", "name": "n", "version": "1", "type": "theme_pack"}
# 前半是必须拒绝的非法 id；"  spaced  " strip 后是合法 id，两处都应放行
# （口径一致 = 同进同退，不是一律拒绝）。
for raw, want in (("my/module", False), ("a b", False),
                  ("ok/../evil", False), ("a\\b", False), ("..", False),
                  ("  spaced  ", True)):
    m = dict(_good, id=raw)
    mod_ok = _accepts(modules.validate_manifest, m, modules.ModuleError)
    feat_ok = _accepts(features.validate_manifest, dict(m, type="page"),
                       features.FeatureError)
    check("两处 validate_manifest 对 %-16s 口径一致" % repr(raw),
          mod_ok == feat_ok == want,
          "modules=%s features=%s want=%s" % (mod_ok, feat_ok, want))

check("合法 id 仍通过", modules.validate_manifest(_good) == "ok-id")
check("非字符串 id 被拒",
      not _accepts(modules.validate_manifest,
                   dict(_good, id=123), modules.ModuleError))
check("空 id 被拒",
      not _accepts(modules.validate_manifest,
                   dict(_good, id=""), modules.ModuleError))

# 行为断言（不靠源码字面量）：临时 legacy 包里的非法 id 必须被拒绝，
# 且不能污染数据目录。用真实的 install_legacy_theme_pack 走一遍。
import tempfile  # noqa: E402
import json  # noqa: E402

_orig_dir = modules.get_modules_dir
_tmp = tempfile.mkdtemp(prefix="r222_modules_")
modules.get_modules_dir = lambda: _tmp
try:
    for raw in ("ok/../evil", "..", "a b"):
        p = os.path.join(_tmp, "legacy.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"id": raw, "name": "evil", "version": "1"}, f)
        raised = False
        try:
            modules.install_legacy_theme_pack(p)
        except modules.ModuleError:
            raised = True
        except Exception:  # noqa: BLE001 - 任何失败都算没写进去
            raised = True
        check("legacy 主题包 id %-14s 被拒绝（不再静默清洗）" % repr(raw),
              raised)
    check("数据根目录未被污染",
          not os.path.isfile(os.path.join(_tmp, "manifest.json")))
finally:
    modules.get_modules_dir = _orig_dir


# ── 3) 解耦：PanelShellMixin 转发语义 ─────────────────────────────────────
print("\n[3] PanelShellMixin behaviour")


class _FakePanel:
    def __init__(self):
        self.value = 1
        self._dl_phase = "idle"
        self.closed = False

    def closeEvent(self, ev):
        self.closed = True


class _FakeQtBase:
    def __init__(self):
        pass

    def closeEvent(self, ev):
        self.qt_closed = True


class _Shell(PanelShellMixin, _FakeQtBase):
    def __init__(self):
        _FakeQtBase.__init__(self)
        self.panel = _FakePanel()


sh = _Shell()
check("读取转发给 panel", sh.value == 1 and sh._dl_phase == "idle")
sh._dl_phase = "download"
check("写入转发给 panel（round-197 坑：只转发读不够）",
      sh.panel._dl_phase == "download")
check("panel 属性本身不被转发拦截", sh.panel is sh.__dict__["panel"])
sh.closeEvent(None)
check("closeEvent 转发给 panel", sh.panel.closed is True)
check("panel 未处理时不误触 Qt 基类 closeEvent",
      not hasattr(sh, "qt_closed"))


class _NoPanel(PanelShellMixin, _FakeQtBase):
    pass


np_ = _NoPanel()
np_.closeEvent(None)
check("panel 缺席时安全回退到基类 closeEvent",
      getattr(np_, "qt_closed", False) is True)


# ── 4) 查重：tick_import_progress 状态机 ──────────────────────────────────
print("\n[4] tick_import_progress state machine")


class _FakeProgress:
    def __init__(self):
        self.maximum_v = 0
        self.value_v = 0
        self.label = ""
        self.visible = False
        self.range_calls = 0
        self.label_writes = 0

    def maximum(self):
        return self.maximum_v

    def value(self):
        return self.value_v

    def setRange(self, a, b):
        self.range_calls += 1
        self.maximum_v = b

    def setValue(self, v):
        self.value_v = v

    def setLabelText(self, s):
        self.label_writes += 1
        self.label = s

    def isVisible(self):
        return self.visible

    def show(self):
        self.visible = True


st = {"done": 3, "total": 10, "txt": "", "finishing": False}
pg = _FakeProgress()
tick_import_progress(st, pg)
check("进行中：显示 n/N 百分比", "3/10" in pg.label and pg.value_v == 3,
      pg.label)
check("进行中：不重复写 label", pg.label_writes == 1,
      "writes=%d" % pg.label_writes)
tick_import_progress(st, pg)
check("状态未变时不重绘 label", pg.label_writes == 1,
      "writes=%d" % pg.label_writes)

st2 = {"done": 10, "total": 10, "txt": "", "finishing": False}
pg2 = _FakeProgress()
tick_import_progress(st2, pg2)
check("满值收尾：切不定长 + 收尾文案，不 setValue(max)",
      pg2.maximum_v == 0 and pg2.label == t("modpack.finishing")
      and st2["finishing"] is True, pg2.label)
before = pg2.label_writes
tick_import_progress(st2, pg2)
check("收尾阶段不闪烁（不再重复 setLabelText/show）",
      pg2.label_writes == before)

st3 = {"done": -1, "total": 0, "label": "正在装加载器", "txt": ""}
pg3 = _FakeProgress()
tick_import_progress(st3, pg3)
check("不定长阶段用回调自定义文案", pg3.label == "正在装加载器", pg3.label)

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-222 解耦 / 查重 / 修复回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-222 解耦 / 查重 / 修复回归）")
