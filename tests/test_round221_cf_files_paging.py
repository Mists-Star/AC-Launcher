"""round-221：CurseForge 文件列表分页拉全回归（离线，零真实 HTTP）。

复现并修复的现象：``_cf_files_mirror`` 曾硬编码 ``pageSize=50``，且只取
第一页。老项目文件数远超 50（FTB Library / NeoForge 404465 实测 **183** 个），
按日期倒序时 MC 1.21 / 1.20.6 / 1.19 / 1.18.1 / 1.16.2~4 / 1.15.2 这些
版本线**整条被截掉**，表现为：

  * 资源中心详情页看不到该 MC 版本的任何文件、offset 翻页越界即空；
  * 依赖解析 ``_cf_resolve_dep_file`` 挑不到匹配前置 → 装完缺库崩游戏；
  * 免 key 下载按 file_id 找文件名时也找不到老文件。

本测试用打桩验证：
  * 镜像一次 pageSize=200 拿全 183 个文件，不增加往返；
  * >200 文件的项目会按 index 继续翻页，且按 id 去重；
  * 服务端忽略 index 反复返回同一页时能收敛（不死循环）；
  * 中途某页失败时保留已拿到的页，不整体失败；
  * 缓存 key 升级到 ``cffi2:``（旧的 50 条磁盘缓存不再生效）；
  * 官方 keyed 分支也分页并带 sortField/sortOrder；
  * 拉全后 ``_cf_filter_files`` 能筛到原本被截掉的老 MC 版本线。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import net_api as na  # noqa: E402

fails = []
total = 0


def check(label, cond, extra=""):
    global total
    total += 1
    print("  %s %-66s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


class _Resp:
    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self._rows}


def _mk_rows(start, n, gv=None):
    return [{"id": start + i,
             "fileName": "mod-%d.jar" % (start + i),
             "displayName": "mod %d" % (start + i),
             "gameVersions": gv or ["26.1.2"]} for i in range(n)]


class _FakeGet:
    """按 index 切片一个虚拟文件表；可注入重复页 / 失败页。"""

    def __init__(self, total_files, repeat_first=False, fail_at=None):
        self.total_files = total_files
        self.repeat_first = repeat_first
        self.fail_at = fail_at
        self.calls = []

    def __call__(self, url, params=None, headers=None, timeout=None,
                 proxies=None, **kw):
        params = params or {}
        self.calls.append(dict(params))
        page = int(params.get("pageSize", 50))
        idx = int(params.get("index", 0))
        if self.fail_at is not None and idx == self.fail_at:
            raise na.requests.RequestException("injected page failure")
        if self.repeat_first:
            rows = _mk_rows(0, page)
        else:
            n = max(0, min(page, self.total_files - idx))
            rows = _mk_rows(idx, n)
        return _Resp(rows)


def _patch_get(fake):
    na.requests.get = fake
    # 缓存打桩：不读也不写磁盘，避免测试污染真实缓存
    na._cached = lambda key, ttl=None: None
    na._store = lambda key, val: None


def _restore(orig):
    na.requests.get = orig["get"]
    na._cached = orig["cached"]
    na._store = orig["store"]


def _snapshot():
    return {"get": na.requests.get, "cached": na._cached, "store": na._store}


# ── 1) 镜像单请求拿全 183 个文件 ──────────────────────────────────────────
orig = _snapshot()
fake = _FakeGet(183)
_patch_get(fake)
rows = na._cf_files_mirror("404465")
check("mirror 拉全 183 个文件（旧实现只有 50）", len(rows) == 183,
      "got=%d" % len(rows))
check("mirror 只发 1 次请求（不增加往返）", len(fake.calls) == 1,
      "calls=%d" % len(fake.calls))
check("mirror pageSize=200", fake.calls[0].get("pageSize") == 200,
      str(fake.calls[0]))
check("mirror index 从 0 开始", fake.calls[0].get("index") == 0)
_restore(orig)

# ── 2) >200 文件按 index 翻页 + 去重 ──────────────────────────────────────
orig = _snapshot()
fake = _FakeGet(430)
_patch_get(fake)
rows = na._cf_files_all("https://unit.test/v1", "x", {}, 200)
check("430 文件项目拉全", len(rows) == 430, "got=%d" % len(rows))
check("翻 3 页（200/200/30）", len(fake.calls) == 3,
      "calls=%d" % len(fake.calls))
check("index 递增 0,200,400",
      [c.get("index") for c in fake.calls] == [0, 200, 400],
      str([c.get("index") for c in fake.calls]))
check("文件 id 无重复", len({r["id"] for r in rows}) == len(rows))
_restore(orig)

# ── 3) 服务端忽略 index 反复返回同一页 → 收敛不死循环 ─────────────────────
orig = _snapshot()
fake = _FakeGet(200, repeat_first=True)
_patch_get(fake)
rows = na._cf_files_all("https://unit.test/v1", "x", {}, 200)
check("重复页时请求次数远小于上限", len(fake.calls) < na._CF_FILES_MAX_PAGES,
      "calls=%d / max=%d" % (len(fake.calls), na._CF_FILES_MAX_PAGES))
check("重复页只保留去重后的 200 条", len(rows) == 200, "got=%d" % len(rows))
_restore(orig)

# ── 4) 中途失败保留已拿到的页 ────────────────────────────────────────────
orig = _snapshot()
fake = _FakeGet(430, fail_at=200)
_patch_get(fake)
rows = na._cf_files_all("https://unit.test/v1", "x", {}, 200)
check("第二页失败时保留第一页 200 条", len(rows) == 200, "got=%d" % len(rows))
_restore(orig)

# ── 5) 缓存 key 升级到 cffi2: ────────────────────────────────────────────
orig = _snapshot()
fake = _FakeGet(183)
_patch_get(fake)
stored = []
na._store = lambda key, val: stored.append(key)
na._cf_files_mirror("404465")
check("缓存 key 为 cffi2:（旧 cffi: 缓存失效）",
      bool(stored) and stored[0].startswith("cffi2:"), str(stored))
_restore(orig)

# ── 5b) 版本列表自身缓存也要换 key（否则旧的无 sha1 / 50 条切片会复活）───
import inspect  # noqa: E402
_ver_src = inspect.getsource(na._curseforge_versions)
_vkl_src = inspect.getsource(na._curseforge_versions_keyless)
check("官方版本列表缓存 key 升到 cfv2:",
      'cache_key = f"cfv2:' in _ver_src)
check("keyless 版本列表缓存 key 升到 cfvw2:",
      'cache_key = f"cfvw2:' in _vkl_src)

# ── 6) 官方 keyed 分支也分页 + sortField ─────────────────────────────────
orig = _snapshot()
fake = _FakeGet(120)
_patch_get(fake)
orig_key = na._curseforge_key
na._curseforge_key = lambda: "UNIT-TEST-KEY"
rows = na._cf_raw_files("404465")
na._curseforge_key = orig_key
check("官方分支拉全 120 个文件", len(rows) == 120, "got=%d" % len(rows))
check("官方 pageSize=50 且翻 3 页", len(fake.calls) == 3,
      "calls=%d" % len(fake.calls))
check("官方分支带 sortField=2/sortOrder=desc",
      fake.calls[0].get("sortField") == 2
      and fake.calls[0].get("sortOrder") == "desc", str(fake.calls[0]))
_restore(orig)

# ── 7) 端到端：老 MC 版本线不再被截掉 ────────────────────────────────────
# 模拟 FTB Library 真实排序：前 50 条都是 26.1.x / 1.21.1，
# 1.20.6 落在 index=78、1.15.2 落在 index=181（实测位置）。
orig = _snapshot()
all_rows = _mk_rows(0, 183, ["26.1.2"])
for i, gv in ((78, "1.20.6"), (118, "1.19"), (127, "1.18.1"),
              (161, "1.16.2"), (181, "1.15.2")):
    all_rows[i]["gameVersions"] = [gv, "NeoForge"]
fake = _FakeGet(183)
_patch_get(fake)
# 让 fake 返回带真实 gameVersions 的表
def _get_with_gv(url, params=None, headers=None, timeout=None, proxies=None, **kw):
    params = params or {}
    page = int(params.get("pageSize", 50))
    idx = int(params.get("index", 0))
    fake.calls.append(dict(params))
    return _Resp(all_rows[idx:idx + page])
na.requests.get = _get_with_gv
full = na._cf_files_mirror("404465")
old_first50 = all_rows[:50]
check("拉全后 1.20.6 能筛到文件",
      len(na._cf_filter_files(full, "1.20.6", "neoforge")) == 1)
check("拉全后 1.15.2 能筛到文件",
      len(na._cf_filter_files(full, "1.15.2", "neoforge")) == 1)
check("旧实现（仅前 50 条）确实筛不到 1.20.6（证明 bug 存在）",
      len(na._cf_filter_files(old_first50, "1.20.6", "neoforge")) == 0)
check("拉全后 26.1.2 仍正常（未破坏主线）",
      len(na._cf_filter_files(full, "26.1.2", "neoforge")) > 0)
_restore(orig)

# ── 7b) sha1 端到端：元数据 → 版本条目 → 本体下载 ────────────────────────
# round-220 把详情页 CF 下载改走 download_cf_with_deps 后，版本结构里从没写过
# sha1 字段，导致详情页那个 f0.get("sha1") 是死值、官方 keyed 通道本体不再校验。
_SHA1 = "58ec854134ab5953a8c293636025e690c1ad1d46"
_cf_file = {"id": 9456005, "displayName": "lib.jar",
            "fileName": "lib.jar", "gameVersions": ["26.1.2", "NeoForge"],
            "hashes": [{"algo": 1, "value": _SHA1},
                       {"algo": 2, "value": "deadbeef-md5"}]}
entry = na._cf_version_entry(
    _cf_file["id"], _cf_file["displayName"], _cf_file["fileName"], 1024,
    "2026-11-05T00:00:00", _cf_file["gameVersions"], "", na._cf_sha1(_cf_file))
check("版本条目 files[0] 带正确 sha1（不拿 MD5 冒充）",
      entry["files"][0].get("sha1") == _SHA1, str(entry["files"][0].get("sha1")))

orig = _snapshot()
_patch_get(_FakeGet(183))
orig_key = na._curseforge_key
na._curseforge_key = lambda: ""          # keyless 通道（用户没 CF key）
seen_sha1 = []


def _fake_one(pid, fid, dest_dir, callback, manifest_out, existing_by_pid,
              sha1=""):
    seen_sha1.append(sha1)
    return "/fake/%s.jar" % fid


orig_one = na._cf_download_one
orig_resolve = na.resolve_cf_dependencies
na._cf_download_one = _fake_one
na.resolve_cf_dependencies = lambda *a, **k: []
na.download_cf_with_deps("404465", "9456005", "/tmp/x",
                         primary_sha1=entry["files"][0]["sha1"])
na._cf_download_one = orig_one
na.resolve_cf_dependencies = orig_resolve
na._curseforge_key = orig_key
_restore(orig)
check("download_cf_with_deps 把 primary_sha1 透传给本体下载",
      seen_sha1 == [_SHA1], str(seen_sha1))

# ── 8) 详情页 offset 翻页不再越界即空 ────────────────────────────────────
orig = _snapshot()
fake = _FakeGet(183)
_patch_get(fake)
# 清空版本列表缓存，确保走打桩
versions = na._curseforge_versions_keyless("404465", limit=20, offset=100)
check("版本列表 offset=100 仍能取到 20 条", len(versions) == 20,
      "got=%d" % len(versions))
_restore(orig)

print()
print("%d/%d checks passed" % (total - len(fails), total))
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    print("ALL CHECKS FAILED（round-221 CF 文件列表分页回归）")
    sys.exit(1)
print("ALL CHECKS PASSED（round-221 CF 文件列表分页回归）")
