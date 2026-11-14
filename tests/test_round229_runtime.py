"""round-229：整合包导入卡住 / 实例不刷新 / 兼容误判的行为回归（离线）。"""
import os
import sys
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.pages_browse as PB             # noqa: E402
import src.store_detail as SD             # noqa: E402
import src.store_compat as SC             # noqa: E402
import src.modpack_import as MI           # noqa: E402
import src.core.install as CI             # noqa: E402
from src.i18n import _STRINGS, t          # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── [1] 底层状态字符串不再泄漏到界面 ────────────────────────────────────
_orig_install = CI.install_instance


def fake_install(inst, **kw):
    cb = kw.get("callback") or {}
    fn = cb.get("setStatus")
    if fn:
        fn("Installation complete")


labels = []
CI.install_instance = fake_install
try:
    MI._install_after_import(
        types.SimpleNamespace(id="i1", name="p", game_version="1.20.1",
                              loader="fabric"),
        lambda *a: labels.append(a[0]))
finally:
    CI.install_instance = _orig_install
check("导入阶段状态不含底层英文字符串",
      bool(labels) and not any("Installation complete" in x for x in labels),
      str(labels[:1]))
check("导入阶段仍是本地化文案",
      bool(labels) and t("modpack.installing_loader") == labels[0])


# ── [2] 同一主版本系列不再误判不兼容 ────────────────────────────────────
check("精确匹配 = ok", SC.mc_compat("1.20.1", ["1.20.1", "1.19.2"]) == "ok")
check("同系列未标注 = unverified",
      SC.mc_compat("1.20.4", ["1.20.1"]) == "unverified")
check("跨主版本 = mismatch",
      SC.mc_compat("1.20.4", ["1.16.5", "1.18.2"]) == "mismatch")
check("快照串不误判为同系列",
      SC.same_minor_series("25w14craftmine", "1.20.1") is False)

inst = types.SimpleNamespace(game_version="1.20.4", loader="fabric")
fake_page = types.SimpleNamespace(_current_inst=lambda: inst)
ok, note = PB.StorePage._compat_of_card(
    fake_page, {"game_versions": ["1.20.1"], "loaders": ["fabric"]})
check("列表卡片：同系列判兼容 + 带说明",
      ok is True and bool(note), "%s / %s" % (ok, note))
ok, reason = PB.StorePage._compat_of_card(
    fake_page, {"game_versions": ["1.16.5"], "loaders": ["fabric"]})
check("列表卡片：跨主版本仍判不兼容", ok is False and bool(reason))
ok, reason = PB.StorePage._compat_of_card(
    fake_page, {"game_versions": ["1.20.4"], "loaders": ["forge"]})
check("列表卡片：加载器冲突仍判不兼容", ok is False and bool(reason))

fake_detail = types.SimpleNamespace(_current_inst=lambda: inst, _inst=None)
ok, _ = SD.StoreDetailPanel._compat_of(
    fake_detail, {"game_versions": ["1.20.1"], "loaders": ["fabric"]})
check("详情页版本行：同系列不再被过滤", ok is True)
ok, _ = SD.StoreDetailPanel._compat_of(
    fake_detail, {"game_versions": ["1.16.5"], "loaders": ["fabric"]})
check("详情页版本行：跨主版本仍不兼容", ok is False)


# ── [3] 安装完成后刷新实例列表 ─────────────────────────────────────────
refreshed = []
fake_self = types.SimpleNamespace(
    window=lambda: types.SimpleNamespace(
        instances_page=types.SimpleNamespace(
            _refresh=lambda: refreshed.append(1))))
PB.StorePage._refresh_instance_list(fake_self)
check("_refresh_instance_list 触发实例页重绘", refreshed == [1])
refreshed.clear()
PB.StorePage._refresh_instance_list(
    types.SimpleNamespace(window=lambda: types.SimpleNamespace()))
check("主窗没有实例页时静默跳过", refreshed == [])

with open(os.path.join(HERE, "src", "pages_browse.py"), encoding="utf-8") as f:
    pb_src = f.read()
check("_done 完成后调用刷新", "_refresh_instance_list()" in pb_src)
check("CF 导入 + mrpack 对话框两条完成链都刷了新",
      pb_src.count("self._refresh_instance_list()") == 2)


# ── [4] 进度框有退路：取消按钮 + 看门狗 ─────────────────────────────────
check("进度框不再禁用取消按钮",
      "setCancelButtonText(t(\"common.cancel\"))" in pb_src
      and "setCancelButton(None)" not in pb_src)
check("取消信号接了收尾", "progress.canceled.connect" in pb_src)
check("看门狗已接线", "watchdog.timeout.connect" in pb_src
      and "watchdog.start()" in pb_src)
check("完成/失败/取消三条终态都停看门狗",
      pb_src.count("watchdog.stop()") == 3)
check("看门狗提示文案存在", "modpack.import_bg" in pb_src)

for key in ("store.unverified_mc", "modpack.import_bg"):
    check("i18n 中英对称 " + key,
          key in _STRINGS["zh-CN"] and key in _STRINGS["en-US"])

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-229 运行时回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-229 运行时回归）")
