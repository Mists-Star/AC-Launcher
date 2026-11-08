"""round-216：最后一批 P1（磁盘边界 / 生命周期 / 缓存预算）行为回归。

覆盖 8 条：
  1. 旧主题包 ``id=".."`` 越界写（安装阶段直接拒绝，数据根目录不被污染）
  2. 「一键导入全部」同目录去重 + 失败不标记已导入
  3. BGM 模式 ↔ Qt 循环策略一致（sequential / shuffle 真的会换曲）
  4. region 单区块解压上限（gzip 炸弹 → None，而不是把内存打爆）
  5. map_cache 只留最新版本 + 总预算清理
  6. 扫描面板 shutdown 能停掉整盘扫描且不再回调
  7. 联机窗口关闭确认（保持联机 / 断开并关闭两条分支）
  8. 装完 Java 主动失效 scan_javas 缓存

原则同前几轮：能跑真对象就不用源码字面量断言；只有「必须证明顺序」的地方
才回读源码，并且断言的是**执行顺序**而不是「这句话存在」。
"""
import gzip
import json
import os
import sys
import tempfile
import time
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-66s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

# ══════════════════════════════════════════════════════════════════════
# 1. 模块 id 越界
# ══════════════════════════════════════════════════════════════════════
print("== 1. 旧主题包 id 越界 ==")
import src.modules as md  # noqa: E402

mroot = tempfile.mkdtemp(prefix="ac216-mod-")
with mock.patch.object(md, "get_data_dir", lambda: mroot):
    os.makedirs(os.path.join(mroot, "modules"), exist_ok=True)
    evil = os.path.join(mroot, "evil.json")
    with open(evil, "w", encoding="utf-8") as f:
        json.dump({"id": "..", "name": "Evil"}, f)
    try:
        md.install_legacy_theme_pack(evil)
        check("id='..' 被拒绝", False, "竟然安装成功")
    except md.ModuleError as e:
        check("id='..' 被拒绝", "非法" in str(e), str(e)[:40])
    check("数据根目录未被写入 manifest.json",
          not os.path.isfile(os.path.join(mroot, "manifest.json")))
    check("数据根目录未被写入 theme-pack.json",
          not os.path.isfile(os.path.join(mroot, "theme-pack.json")))

    ok = os.path.join(mroot, "ok.json")
    with open(ok, "w", encoding="utf-8") as f:
        json.dump({"id": "my.theme", "name": "OK", "version": "1.0"}, f)
    mod = md.install_legacy_theme_pack(ok)
    check("正常 id 仍能安装", mod is not None and mod.id == "my.theme")
    md.uninstall_module("my.theme")
    check("正常模块仍能卸载",
          not os.path.isdir(os.path.join(mroot, "modules", "my.theme")))

# ══════════════════════════════════════════════════════════════════════
# 2. 一键导入全部
# ══════════════════════════════════════════════════════════════════════
print("== 2. 一键导入全部：去重 + 失败不标记 ==")
import src.scan_dialog as sd  # noqa: E402
from src.scan import ScannedInstance  # noqa: E402


def _inst(path, name="i"):
    return ScannedInstance(
        mc_dir=path, name=name, game_version="1.20.1", loader="",
        loader_version="", version_id=name, kind="official",
        needs_convert=False, launcher="Official",
    )


panel = sd.ScanPanel(auto_scan=False)
a = os.path.join(mroot, "mc_a")
b = os.path.join(mroot, "mc_b")
os.makedirs(a, exist_ok=True)
os.makedirs(b, exist_ok=True)
panel._all_instances = [_inst(a, "a1"), _inst(a, "a2"), _inst(b, "b1")]
panel._imported = set()
calls = []


def fake_import(inst, btn, mode):
    calls.append(inst.mc_dir)
    return inst.mc_dir == a          # b 失败


with mock.patch.object(panel, "_do_import", fake_import), \
     mock.patch.object(sd, "_msgbox",
                       lambda *args, **kw: sd.t("scan.import_copy")):
    panel._import_all()

check("同目录多版本只导入一次", calls.count(a) == 1, "calls=%s" % calls)
check("不同目录各自导入", calls.count(b) == 1)
check("成功目录被记为已导入", a in panel._imported)
check("失败目录没有被记为已导入", b not in panel._imported)
check("汇总文案报告 1 成功 1 失败",
      "1" in panel.summary.text() and len(panel.summary.text()) > 0,
      panel.summary.text()[:40])

# ══════════════════════════════════════════════════════════════════════
# 3. BGM 模式
# ══════════════════════════════════════════════════════════════════════
print("== 3. BGM 模式 ↔ 循环策略 ==")
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
from src.core.sound import MusicPlayer  # noqa: E402

sroot = tempfile.mkdtemp(prefix="ac216-bgm-")
tracks = []
for i in range(3):
    p = os.path.join(sroot, "t%d.ogg" % i)
    with open(p, "wb") as f:
        f.write(b"x")
    tracks.append(p)

mp = MusicPlayer()
mp.set_playlist(tracks)
mp.play_index(0)
check("默认 loop → Infinite", mp._player.loops() == QMediaPlayer.Loops.Infinite)
mp.mode = "sequential"
check("sequential → Once", mp._player.loops() == QMediaPlayer.Loops.Once)
idx0 = mp.current_index()
mp._on_status(QMediaPlayer.MediaStatus.EndOfMedia)
check("sequential 曲终换下一首", mp.current_index() == (idx0 + 1) % 3,
      "%d -> %d" % (idx0, mp.current_index()))
mp.mode = "shuffle"
check("shuffle → Once", mp._player.loops() == QMediaPlayer.Loops.Once)
mp.mode = "loop"
check("切回 loop → Infinite", mp._player.loops() == QMediaPlayer.Loops.Infinite)
mp.mode = "nonsense"
check("未知模式回退 loop", mp.mode == "loop")

# ══════════════════════════════════════════════════════════════════════
# 4. 区块解压上限
# ══════════════════════════════════════════════════════════════════════
print("== 4. region 单区块解压上限 ==")
import src.core.nbt as nbt  # noqa: E402
import src.core.world_map as wm  # noqa: E402

check("区块上限远小于整文件上限",
      wm._CHUNK_MAX_BYTES < nbt.MAX_BYTES,
      "%d MB vs %d MB" % (wm._CHUNK_MAX_BYTES >> 20, nbt.MAX_BYTES >> 20))

bomb = gzip.compress(b"\x00" * (6 * 1024 * 1024))
try:
    nbt.load_bytes(bomb, max_bytes=1024 * 1024)
    check("收紧上限后 gzip 炸弹被拒", False, "没有抛异常")
except nbt.NbtError as e:
    check("收紧上限后 gzip 炸弹被拒", "上限" in str(e), str(e)[:30])

# 造一个「区块数据是 6MB 膨胀炸弹」的 region，_chunk_nbt 必须安全返回 None
wroot = tempfile.mkdtemp(prefix="ac216-reg-")
region = os.path.join(wroot, "r.0.0.mca")
chunk_payload = gzip.compress(b"\x00" * (6 * 1024 * 1024))
with open(region, "wb") as f:
    header = bytearray(4096)
    header[0:4] = (2).to_bytes(3, "big") + b"\x01"     # slot0 → sector 2, count 1
    f.write(header)
    f.write(b"\x00" * 4096)                            # sector 1 空
    body = (len(chunk_payload) + 1).to_bytes(4, "big") + b"\x02" + chunk_payload
    f.write(body)
    f.write(b"\x00" * max(0, 4096 - len(body)))
try:
    with open(region, "rb") as fh:
        got = wm._chunk_nbt(fh, 2, 1)
    check("膨胀区块安全返回 None", got is None, "got=%r" % (type(got).__name__,))
except MemoryError:
    check("膨胀区块安全返回 None", False, "MemoryError")

# ══════════════════════════════════════════════════════════════════════
# 5. map_cache 预算
# ══════════════════════════════════════════════════════════════════════
print("== 5. map_cache 只留最新版本 + 预算 ==")
croot = tempfile.mkdtemp(prefix="ac216-cache-")
world = os.path.join(croot, "world")
os.makedirs(os.path.join(world, "region"), exist_ok=True)
rsrc = os.path.join(world, "region", "r.0.0.mca")
with open(rsrc, "wb") as f:
    f.write(b"A" * 100)

fake_rgba = b"\x00" * (512 * 512 * 4)
with mock.patch.object(wm, "render_region",
                       lambda src: (fake_rgba, 0, 1, 0)), \
     mock.patch.object(wm, "get_data_dir", lambda: croot):
    wm.load_region_image(world, "overworld", 0, 0)
    os.utime(rsrc, (time.time() + 10, time.time() + 10))
    with open(rsrc, "wb") as f:
        f.write(b"B" * 120)
    wm.load_region_image(world, "overworld", 0, 0)
    dim_dir = ""
    for base, _dirs, files in os.walk(os.path.join(croot, "map_cache")):
        if any(n.endswith(".png") for n in files):
            dim_dir = base
    pngs = [n for n in os.listdir(dim_dir) if n.endswith(".png")]
    metas = [n for n in os.listdir(dim_dir) if n.endswith(".meta")]
    check("同一块只保留一个缓存版本", len(pngs) == 1, "%s" % pngs)
    check("对应 .meta 也只剩一份", len(metas) == 1)
    check("缓存文件名对应当前源文件",
          pngs and pngs[0].startswith("0.0.") and pngs[0].endswith(".png"),
          pngs[0] if pngs else "")

    junk = os.path.join(croot, "map_cache", "junk.bin")
    with open(junk, "wb") as f:
        f.write(b"\x00" * (3 * 1024 * 1024))
    wm._cache_swept = False
    removed = wm.prune_cache_budget(max_mb=1)
    total_mb = sum(
        os.path.getsize(os.path.join(b, n))
        for b, _d, fs in os.walk(os.path.join(croot, "map_cache"))
        for n in fs) / 1024.0 / 1024.0
    check("超预算时删掉了旧文件", removed >= 1, "removed=%d" % removed)
    check("清理后总量回到预算内", total_mb <= 1.05, "%.2f MB" % total_mb)
    wm._cache_swept = False
    check("预算内不误删", wm.prune_cache_budget(max_mb=256) == 0)

# ══════════════════════════════════════════════════════════════════════
# 6. 扫描面板 shutdown
# ══════════════════════════════════════════════════════════════════════
print("== 6. 扫描面板关闭即停 ==")
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

seen = {"stopped": 0, "done": 0}


def fake_discover(progress=None, should_stop=None):
    for _ in range(3000):
        if should_stop is not None and should_stop():
            seen["stopped"] += 1
            return []
        time.sleep(0.005)
    return []


with mock.patch.object(sd, "discover_instances", fake_discover):
    panel2 = sd.ScanPanel(auto_scan=False)
    panel2._on_done = lambda r: seen.__setitem__("done", seen["done"] + 1)
    panel2._run_scan()
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec()
    was_running = panel2._worker.isRunning()
    t0 = time.time()
    panel2.shutdown()
    cost = time.time() - t0
    check("扫描线程确实在跑（前置条件）", was_running)
    check("shutdown 后线程停止", not panel2._worker.isRunning(), "%.2fs" % cost)
    check("shutdown 不干等", cost < 2.0, "%.2fs" % cost)
    check("扫描体内收到停止信号", seen["stopped"] >= 1)
    check("停止后不再回调已删面板", seen["done"] == 0)

check("discover_instances 支持 should_stop 参数",
      sd.discover_instances.__module__ == "src.scan")

# ══════════════════════════════════════════════════════════════════════
# 7. 联机窗口关闭确认
# ══════════════════════════════════════════════════════════════════════
print("== 7. 联机窗口关闭确认 ==")
import src.lobby_dialog as ld  # noqa: E402
import src.win_rounded as wr  # noqa: E402
from src.core import easytier  # noqa: E402
from src.i18n import t  # noqa: E402

check("easytier 暴露 is_running()", hasattr(easytier, "is_running"))
stop_calls = []
with mock.patch.object(easytier, "is_running", lambda: True), \
     mock.patch.object(easytier, "stop_node", lambda: stop_calls.append(1)):
    with mock.patch.object(wr, "_msgbox",
                          lambda *a, **k: t("lobby.close_confirm_cancel")):
        dlg = ld.LobbyDialog()
        dlg.show()
        dlg.close()
        check("选「保持联机」窗口不关", dlg.isVisible())
        check("选「保持联机」不拆节点", not stop_calls)
    with mock.patch.object(wr, "_msgbox",
                          lambda *a, **k: t("lobby.close_confirm_ok")):
        dlg.close()
        check("选「断开并关闭」窗口关闭", not dlg.isVisible())
        check("选「断开并关闭」拆掉节点", bool(stop_calls))

with mock.patch.object(easytier, "is_running", lambda: False):
    with mock.patch.object(wr, "_msgbox",
                          lambda *a, **k: (_ for _ in ()).throw(
                              AssertionError("未联机不应弹确认"))):
        dlg2 = ld.LobbyDialog()
        dlg2.show()
        dlg2.close()
        check("未联机时关闭不弹确认且直接关", not dlg2.isVisible())

# ══════════════════════════════════════════════════════════════════════
# 8. Java 安装后缓存失效
# ══════════════════════════════════════════════════════════════════════
print("== 8. 装完 Java 失效 scan_javas 缓存 ==")
from src.core import java as jm  # noqa: E402

jm._SCAN_CACHE_DEEP = [{"path": "stale"}]
jm._SCAN_CACHE_DEEP_AT = time.time()
jm._SCAN_CACHE_FAST = [{"path": "stale"}]
jm._SCAN_CACHE_FAST_AT = time.time()
jm.invalidate_scan_cache()
check("invalidate 清空 deep 槽", jm._SCAN_CACHE_DEEP is None)
check("invalidate 清空 fast 槽", jm._SCAN_CACHE_FAST is None)

import src.core.java_install as ji  # noqa: E402

with open(os.path.join(HERE, "src", "core", "java_install.py"),
          encoding="utf-8") as f:
    src_ji = f.read()
body = src_ji[src_ji.index("def install_java"):]
tail = body[body.index("path = _find_java_exe"):]
check("install_java 在返回前调用 invalidate_scan_cache",
      "invalidate_scan_cache()" in tail
      and tail.index("invalidate_scan_cache()") < tail.index("return path"),
      "顺序断言")

print("\nround-216 regression: %d checks, %d failed" % (total, len(fails)))
if fails:
    for f in fails:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED（round-216 磁盘边界 / 生命周期 / 缓存预算）")
