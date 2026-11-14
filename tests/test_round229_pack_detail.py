"""round-229：整合包详情页不再「当模组下载进现有实例」的行为回归（离线）。

覆盖：详情页目标栏 / 按钮文案 / 安装信号 / 另存为兜底 / 版本透传 /
列表页兜底分流 / i18n 对称。
"""
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.pages_browse as PB             # noqa: E402
import src.store_detail as SD             # noqa: E402
import src.paths as PATHS                 # noqa: E402
import src.core.dl_gate as GATE          # noqa: E402
from src.i18n import t, _STRINGS         # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


TMP = tempfile.mkdtemp(prefix="ac229_")
CARD = {"project_id": "p1", "slug": "testpack", "title": "Test Pack",
        "source": "modrinth"}
VER = {"id": "v1", "version_number": "1.0", "files": [{"id": 123}]}


def panel(category="modpack", card=None, instances=None):
    return SD.StoreDetailPanel(
        None, dict(card or CARD), category, None, "mods",
        instances=instances or [])


# ── [1] 整合包详情页：一眼看出是「安装新实例」 ─────────────────────────
p = panel()
check("整合包判定（category）", p._is_pack is True)
check("目标栏不提供实例选择",
      p.target_combo.count() == 1
      and p.target_combo.currentData() == "__save__",
      "%s / %s" % (p.target_combo.count(), p.target_combo.currentData()))
check("_current_inst() 恒为 None", p._current_inst() is None)
check("主按钮文案是「安装」", p.latest_btn.text() == t("store.install"),
      p.latest_btn.text())
check("提示文案写明了不动现有实例",
      "不会改动现有实例" in t("store.pack_target_hint")
      or "untouched" in t("store.pack_target_hint"))
check("有「另存为文件」按钮",
      p.save_as_btn.text() == t("store.pack_save_as"), p.save_as_btn.text())

p2 = panel(category="modpack", card=dict(CARD, project_type="modpack"))
check("卡片 project_type 也能判整合包", p2._is_pack is True)
p3 = panel(category="mod")
check("普通模组不受影响（按钮仍是「下载」）",
      p3.latest_btn.text() == t("store.download"), p3.latest_btn.text())
check("普通模组仍能选实例", p3.target_combo.count() >= 1)


# ── [2] 安装信号带选中版本 ─────────────────────────────────────────────
got = []
p.install_pack_requested.connect(lambda payload: got.append(payload))
p._recommended = lambda: VER
p._on_latest_action()
check("点「安装」发出安装请求", len(got) == 1, str(len(got)))
check("请求带 card 与选中版本",
      bool(got) and got[0].get("card", {}).get("slug") == "testpack"
      and got[0].get("version", {}).get("id") == "v1")

p._on_row_action(dict(VER, id="v2"))
check("版本行「安装」带该行版本",
      len(got) == 2 and got[1]["version"]["id"] == "v2")

called = []
p3._download_version = lambda v: called.append(v)
p3._on_row_action(VER)
check("普通模组版本行仍走下载", called and called[0]["id"] == "v1")


# ── [3] 防御：即使拿到实例也强制另存为，不写进 mods/ ───────────────────
msgs = []
_orig_q = QMessageBox.question
_orig_dir = QFileDialog.getExistingDirectory
_orig_dd = PATHS.get_data_dir
_orig_claim = GATE.claim
try:
    QMessageBox.question = lambda *a, **k: (
        msgs.append(a[2] if len(a) > 2 else "") or QMessageBox.StandardButton.Yes)
    QFileDialog.getExistingDirectory = lambda *a, **k: TMP
    PATHS.get_data_dir = lambda: TMP
    GATE.claim = lambda key: False          # 不真下载，走到闸门就停
    p._current_inst = lambda: types.SimpleNamespace(
        id="i1", name="实例A", game_dir=TMP, game_version="1.20.1",
        loader="fabric")
    p._download_version(VER)
finally:
    QMessageBox.question = _orig_q
    QFileDialog.getExistingDirectory = _orig_dir
    PATHS.get_data_dir = _orig_dd
    GATE.claim = _orig_claim
check("确认文案是「另存为」而不是「下载到实例」",
      bool(msgs) and ("保存到" in msgs[0] or "Save" in msgs[0]),
      str(msgs[:1]))
check("没有在实例目录里留下 .mrpack",
      not any(f.endswith(".mrpack") for f in os.listdir(TMP)))


# ── [4] 资源页：所有整合包入口都汇到安装链 ─────────────────────────────
calls = []
fake = types.SimpleNamespace(
    _category="modpack",
    _install_modpack=lambda *a, **k: calls.append((a, k)))
PB.StorePage._download(fake, "p1", "testpack", card=CARD)
check("列表页 _download 兜底转安装",
      len(calls) == 1 and calls[0][0][:2] == ("p1", "testpack"))

PB.StorePage._on_detail_install_pack(
    fake, {"card": CARD, "version": VER})
check("详情页安装请求带上 version",
      len(calls) == 2 and calls[1][1].get("version", {}).get("id") == "v1")


# ── [5] 版本精确透传到下载函数 ─────────────────────────────────────────
class _Sig:
    def connect(self, *a, **k):
        pass


created = []


class FakePW:
    def __init__(self, fn, *args, **kwargs):
        created.append((getattr(fn, "__name__", str(fn)), args, kwargs))
        self.progress = self.speed = self.error = self.finished = _Sig()

    def start(self):
        pass


_orig_confirm, _orig_pw, _orig_dd = PB.confirm, PB.ProgressWorker, PATHS.get_data_dir


def bare_page():
    widget = types.SimpleNamespace(
        setVisible=lambda *a: None, setRange=lambda *a: None,
        setText=lambda *a: None)
    noop = lambda *a, **k: None
    return types.SimpleNamespace(
        status=widget, _dl_bar=widget, _dl_speed=widget, _pworker=None,
        _on_pack_downloaded=noop, _on_cf_pack_downloaded=noop,
        _on_pack_progress=noop, _on_pack_speed=noop, _on_pack_error=noop)


try:
    PB.confirm = lambda *a, **k: True
    PB.ProgressWorker = FakePW
    PATHS.get_data_dir = lambda: TMP
    created.clear()
    PB.StorePage._install_modpack(bare_page(), "p1", "testpack", CARD,
                                  version=VER)
    check("Modrinth 安装透传 version_id",
          bool(created) and created[0][2].get("version_id") == "v1",
          str(created[0][2]) if created else "无调用")
    created.clear()
    PB.StorePage._install_modpack(
        bare_page(), "77", "cfpack", dict(CARD, source="curseforge"),
        version=VER)
    check("CF 安装透传 file_id",
          bool(created) and created[0][2].get("file_id") == 123,
          str(created[0][2]) if created else "无调用")
    created.clear()
    PB.StorePage._install_modpack(bare_page(), "p1", "testpack", CARD)
    check("卡片入口不传版本时沿用最新兼容版",
          bool(created) and created[0][2].get("version_id") == "")
finally:
    PB.confirm, PB.ProgressWorker, PATHS.get_data_dir = (
        _orig_confirm, _orig_pw, _orig_dd)

for key in ("store.pack_target_hint", "store.pack_save_as"):
    check("i18n 中英对称 " + key,
          key in _STRINGS["zh-CN"] and key in _STRINGS["en-US"])

print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-229 整合包详情页回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-229 整合包详情页回归）")
