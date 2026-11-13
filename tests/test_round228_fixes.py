"""round-228：按 round-227 审计报告 §9 第 1 批修复的**行为回归**（离线）。

判据是「跑了之后结果对不对」，不是改了哪行源码：
P0-2 破坏性确认框回车、P1-1 批量启用、P1-7 资源路径口径、
P1-10 Java 路径错误归因、P1-12 Forge optional 依赖、P1-16 零兼容版本。
"""
import os
import sys
import tempfile
import types
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AC_DEV_TEMP", "1")

from PySide6.QtCore import Qt, QTimer                 # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402
from PySide6.QtTest import QTest                      # noqa: E402

app = QApplication.instance() or QApplication([])

from src import paths                                 # noqa: E402
from src import win_rounded                           # noqa: E402
from src.mod_list import ModListPanel                 # noqa: E402
from src.core.mod_check import _parse_jar             # noqa: E402
from src.store_detail import StoreDetailPanel         # noqa: E402

fails: list[str] = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-68s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


# ── [1] P0-2 确认框：回车必须落在安全侧 ────────────────────────────────
def _press_enter(fn):
    """弹真对话框，按一次回车，返回 (结果, 按钮状态快照)。"""
    snap = {}

    def fire():
        w = QApplication.activeModalWidget()
        if w is None:
            return
        btns = w.findChildren(QPushButton)
        snap["autodefault"] = [b.autoDefault() for b in btns]
        snap["defaults"] = [b.text() for b in btns if b.isDefault()]
        QTest.keyClick(w, Qt.Key_Return)
        if w.isVisible():
            QTimer.singleShot(30, w.reject)

    QTimer.singleShot(0, fire)
    return fn(), snap


res, snap = _press_enter(
    lambda: win_rounded.confirm(None, "删除实例", "确定删除？"))
check("P0-2 删除确认框按回车不再删除", res is False, str(res))
check("P0-2 所有按钮 autoDefault 已关", not any(snap.get("autodefault", [True])))
check("P0-2 键盘默认落在 No", snap.get("defaults") == ["No"],
      str(snap.get("defaults")))

res, _ = _press_enter(
    lambda: win_rounded.ask(None, "取消下载", "确定？",
                            ("继续下载", "取消下载")))
check("P0-2 ask 回车落在第一个（取消侧）", res == "继续下载", str(res))


def _click_yes():
    def fire():
        w = QApplication.activeModalWidget()
        if w is None:
            return
        for b in w.findChildren(QPushButton):
            if b.text() == "Yes":
                b.click()
                return
        if w.isVisible():
            QTimer.singleShot(30, w.reject)
    QTimer.singleShot(0, fire)
    return win_rounded.confirm(None, "删除实例", "确定删除？")


check("P0-2 鼠标点 Yes 仍能正常确认", _click_yes() is True)


# ── [2] P1-1 批量启用 / 禁用 ───────────────────────────────────────────
tmp = tempfile.mkdtemp(prefix="ac228_")
mods = os.path.join(tmp, "mods")
os.makedirs(mods)
for _n in ("a", "b"):
    with open(os.path.join(mods, _n + ".jar.disabled"), "wb") as f:
        f.write(b"x")
inst = types.SimpleNamespace(mc_dir=tmp, mods_dir=mods, game_dir=tmp,
                             name="probe", version_id="", game_version="1.20.1",
                             loader="fabric", java_path="")
panel = ModListPanel(None, inst)
panel._selected = lambda: [types.SimpleNamespace(
    path=os.path.join(mods, n + ".jar.disabled")) for n in ("a", "b")]
panel.en_btn.click()
check("P1-1 点「批量启用」真的改成 .jar",
      sorted(os.listdir(mods)) == ["a.jar", "b.jar"], str(sorted(os.listdir(mods))))
panel._selected = lambda: [types.SimpleNamespace(
    path=os.path.join(mods, n + ".jar")) for n in ("a", "b")]
panel.dis_btn.click()
check("P1-1 点「批量禁用」真的改成 .jar.disabled",
      sorted(os.listdir(mods)) == ["a.jar.disabled", "b.jar.disabled"])


# ── [3] P1-7 资源路径不依赖 cwd ────────────────────────────────────────
_cwd = os.getcwd()
try:
    os.chdir(tmp)
    rp = paths.get_resource_path(os.path.join("assets", "foo.png"))
    check("P1-7 资源路径与配置路径同口径",
          rp == paths.get_config_path(os.path.join("assets", "foo.png")), rp)
    check("P1-7 资源路径不落到 cwd",
          not os.path.abspath(rp).startswith(os.path.abspath(tmp)))
finally:
    os.chdir(_cwd)


# ── [4] P1-10 Java 路径检查顺序 ────────────────────────────────────────
with open(os.path.join(HERE, "src", "launch.py"), encoding="utf-8") as f:
    lines = f.read().splitlines()
ln_path = next(i for i, l in enumerate(lines) if '_t("err.java_path_invalid"' in l)
ln_select = next(i for i, l in enumerate(lines) if "java = select_java(" in l)
ln_compat = next(i for i, l in enumerate(lines)
                 if '_t("err.java_compat_missing_list"' in l)
check("P1-10 路径检查在 select_java 之前",
      ln_path < ln_select < ln_compat,
      "%d < %d < %d" % (ln_path + 1, ln_select + 1, ln_compat + 1))
check("P1-10 旧的下置检查块已删除",
      sum('_t("err.java_path_invalid"' in l for l in lines) == 1)


# ── [5] P1-12 Forge 依赖类型 ───────────────────────────────────────────
TOML = """modLoader="javafml"
loaderVersion="[47,)"
[[mods]]
modId="optdep"
version="1.0"
displayName="Optional Dep Demo"
[[dependencies.optdep]]
modId="minecraft"
mandatory=true
type="required"
versionRange="[1.20,1.21)"
[[dependencies.optdep]]
modId="jei"
mandatory=false
type="optional"
versionRange="[15,)"
[[dependencies.optdep]]
modId="cloth_config"
mandatory=true
type="required"
versionRange="[11,)"
"""
jar = os.path.join(tmp, "optdep-1.0.jar")
with zipfile.ZipFile(jar, "w") as z:
    z.writestr("META-INF/mods.toml", TOML)
deps = dict(getattr(_parse_jar(jar, "optdep-1.0.jar"), "deps", {}) or {})
check("P1-12 optional 的 jei 不再进必需 deps", "jei" not in deps, str(deps))
check("P1-12 required 的 cloth_config 仍在 deps", "cloth_config" in deps, str(deps))
check("P1-12 minecraft 自身仍被排除", "minecraft" not in deps)


# ── [6] P1-16 零兼容版本不崩 ───────────────────────────────────────────
class _Anything:
    def __getattr__(self, name):
        return self

    def __call__(self, *a, **k):
        return self

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0

    def __bool__(self):
        return True


fake = _Anything()
fake._versions = []
try:
    StoreDetailPanel._on_versions_ready(fake, False)
    crashed = None
except Exception as e:  # noqa: BLE001
    crashed = e
check("P1-16 空版本列表不抛 UnboundLocalError", crashed is None,
      "" if crashed is None else "%s: %s" % (type(crashed).__name__, crashed))


print("\n%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-228 修复回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-228 修复回归）")
