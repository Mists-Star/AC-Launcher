# -*- coding: utf-8 -*-
"""round-178 A/B 组：下载完整性 + CF 版本/依赖口径的行为判据（不联网）。"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import src.net_api as na  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         (" | " + detail) if detail else ""))
    if not ok:
        FAILS.append(label)


class Resp:
    def __init__(self, payload: bytes = b"", status: int = 200, data=None):
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Length": str(len(payload))}
        self._data = data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise na.requests.RequestException("HTTP %d" % self.status_code)

    def iter_content(self, _n):
        if self._payload:
            yield self._payload

    def json(self):
        return {"data": self._data} if self._data is not None else {}

    def close(self):
        pass


ORIG = {k: getattr(na, k) for k in (
    "requests", "_curseforge_key", "_download_once", "_try_parallel",
    "download_file", "_cf_files_mirror", "_cfwidget_info",
    "_modrinth_versions", "_version_primary_file", "get_mod_download")}


def restore():
    for k, v in ORIG.items():
        setattr(na, k, v)


try:
    # ── B1. _cf_sha1 兼容三种元数据形状 ──────────────────────────────
    check("CF hashes 列表取 sha1（algo=1）",
          na._cf_sha1({"hashes": [{"algo": 2, "value": "md5"},
                                  {"algo": 1, "value": "ABC"}]}) == "ABC")
    check("cfwidget hashes 字典取 sha1",
          na._cf_sha1({"hashes": {"sha1": "DEF"}}) == "DEF")
    check("顶层 sha1 字段兜底", na._cf_sha1({"sha1": "GHI"}) == "GHI")
    check("MD5 / fingerprint 绝不冒充 sha1",
          na._cf_sha1({"hashes": [{"algo": 2, "value": "X"}],
                       "fileFingerprint": 123}) == "")

    # ── B2. _download_once：hash 在 .part 阶段校验，坏文件不落盘 ─────
    payload = b"AC-ROUND178-JAR" * 64
    good = hashlib.sha1(payload).hexdigest()  # noqa: S324 - 校验用
    with tempfile.TemporaryDirectory() as td:
        dest = os.path.join(td, "mod.jar")
        na.requests = type("R", (), {"get": lambda *a, **k: Resp(payload),
                                     "RequestException": Exception})()
        na._download_once("http://x/jar", dest, dest + ".part", resume=False,
                          expected_sha1=good)
        check("正确 sha1 → 落盘且无 .part",
              os.path.isfile(dest) and not os.path.exists(dest + ".part")
              and open(dest, "rb").read() == payload)

    with tempfile.TemporaryDirectory() as td:
        dest = os.path.join(td, "mod.jar")
        na.requests = type("R", (), {"get": lambda *a, **k: Resp(payload),
                                     "RequestException": Exception})()
        try:
            na._download_once("http://x/jar", dest, dest + ".part",
                              resume=False, expected_sha1="0" * 40)
            raised = None
        except na._TransientDownloadError as e:
            raised = e
        check("错误 sha1 → 抛瞬时错误（可重下）", raised is not None)
        check("错误 sha1 → 目标文件未生成、.part 已清",
              not os.path.exists(dest) and not os.path.exists(dest + ".part"))

    # ── B3. download_file 把 expected_sha1 透传给两条路径 ────────────
    seen = {}
    na._try_parallel = lambda *a, **k: (seen.update(parallel=k) or False)
    na._download_once = lambda *a, **k: (seen.update(single=k) or a[1])
    na.download_file("http://x", "/tmp/does-not-matter", expected_sha1="H")
    check("download_file → 并行路径带 sha1",
          seen.get("parallel", {}).get("expected_sha1") == "H")
    check("download_file → 单流路径带 sha1",
          seen.get("single", {}).get("expected_sha1") == "H")

    # ── B4. Modrinth 两条下载路径不再「先落盘再验」 ──────────────────
    src = open(os.path.join(ROOT, "src", "net_api.py"), encoding="utf-8").read()
    check("download_mod_to / version_to 改用 expected_sha1",
          src.count("expected_sha1=item.get(\"sha1\", \"\")") == 2
          and "_verify_sha1(dest, item.get" not in src)
    check("CF 三条下载路径都接 hash",
          src.count("expected_sha1=_cf_sha1(") >= 3
          and "expected_sha1=sha1" in src)

    # ── A1. 依赖树：跳过 embedded + 按声明 version_id 递归 ───────────
    calls = []

    def versions(pid, mc="", loader=""):
        # 真实 Modrinth：依赖声明的 version_id 就是该项目版本列表里的一项
        if pid == "dep":
            return [{"id": "v-pin", "project_id": pid, "dependencies": []}]
        return [{"id": "v-" + pid, "project_id": pid,
                 "dependencies": ([
                     {"project_id": "emb", "dependency_type": "embedded"},
                     {"project_id": "opt", "dependency_type": "optional"},
                     {"project_id": "dep", "dependency_type": "required",
                      "version_id": "v-pin"},
                 ] if pid == "root" else [])}]

    na._modrinth_versions = versions
    na._version_primary_file = lambda v, pid: (pid + ".jar", "http://x/" + pid)
    files = na.resolve_mod_dependencies("root", "1.20.1", "fabric")
    ids = [f["project_id"] for f in files]
    check("embedded / optional 依赖不进清单",
          "emb" not in ids and "opt" not in ids, "ids=%r" % ids)
    check("required 依赖仍在", "dep" in ids, "ids=%r" % ids)
    na._modrinth_versions = lambda pid, mc="", loader="": (
        calls.append((pid, mc, loader)) or versions(pid, mc, loader))
    na.resolve_mod_dependencies("root", "1.21", "neoforge")
    check("递归时 MC 版本 / 加载器继续透传",
          all(c[1] == "1.21" and c[2] == "neoforge" for c in calls),
          "calls=%r" % calls)

    # 锁住「递归传依赖声明的 version_id」，别退回最新版
    na._modrinth_versions = versions
    na._version_primary_file = lambda v, pid: (pid + ".jar", "http://x/" + pid)
    real_resolve = na.resolve_mod_dependencies
    vids: list[tuple[str, str]] = []

    def spy(project_id, mc_version="", loader="", version_id="",
            _seen=None, _depth=0):
        vids.append((project_id, version_id))
        return real_resolve(project_id, mc_version, loader, version_id,
                            _seen, _depth)

    na.resolve_mod_dependencies = spy
    try:
        na.resolve_mod_dependencies("root")
    finally:
        na.resolve_mod_dependencies = real_resolve
    check("required 依赖按声明的 version_id 精确解析",
          ("dep", "v-pin") in vids, "vids=%r" % vids)

    # 顶层指定不存在的版本 → 明确报错，不静默退回最新
    na._modrinth_versions = versions
    try:
        na.resolve_mod_dependencies("root", "", "", version_id="NOPE")
        err = None
    except na.NetError as e:
        err = e
    check("顶层指定版本不存在 → 抛 NetError", err is not None)

    # ── A2. CF 版本过滤 ──────────────────────────────────────────────
    rows = [
        {"id": 1, "gameVersions": ["1.21", "Fabric"], "fileName": "new.jar"},
        {"id": 2, "gameVersions": ["1.20.1", "Forge"], "fileName": "ok.jar"},
        {"id": 3, "fileName": "unknown.jar"},
    ]
    check("CF 过滤：MC 版本不匹配被排除",
          [r["id"] for r in na._cf_filter_files(rows, "1.20.1")] == [2, 3])
    check("CF 过滤：加载器明确不兼容被排除",
          [r["id"] for r in na._cf_filter_files(rows, "", "forge")] == [2, 3])
    check("CF 过滤：未知字段不误杀（资源包 / 光影）",
          na._cf_filter_files([rows[2]], "1.20.1", "fabric") != [])
    check("CF 过滤：cfwidget 的 versions 字段也认",
          na._cf_filter_files([{"versions": ["1.20.1"]}], "1.20.1") != [])
    check("CF 过滤：完全无匹配返回空（调用方会拒绝下载）",
          na._cf_filter_files(rows[:1], "1.20.1", "forge") == [])

    # ── A3. 官方卡片下载：无匹配版本不装最新 ────────────────────────
    na._curseforge_key = lambda: "FAKE-KEY"
    na.requests = type("R", (), {
        "get": lambda *a, **k: Resp(data=rows[:1]),
        "RequestException": Exception})()
    try:
        na.download_curseforge_mod("pid", os.path.join(tempfile.gettempdir(),
                                                       "_ac178"),
                                   mc_version="1.20.1", loader="forge")
        refused = False
    except na.NetError as e:
        refused = "没有匹配" in str(e)
    check("官方 CF 卡片：无匹配版本直接拒绝（不取最新）", refused)

    # ── A4. cfwidget：字符串 id 容错 + 不兼容版本拒绝 ────────────────
    with tempfile.TemporaryDirectory() as td:
        captured = {}
        na.download_file = lambda url, dest, **kw: (
            captured.update(url=url, kw=kw) or dest)
        na.download_cfwidget_file({"id": "1234567", "name": "m.jar"}, td)
        check("cfwidget 字符串 file id 不再 TypeError",
              "/1234/567/" in captured.get("url", ""),
              captured.get("url", ""))
    try:
        na.download_cfwidget_file(
            {"id": 9, "name": "m.jar", "gameVersions": ["1.21", "Fabric"]},
            tempfile.gettempdir(), mc_version="1.20.1")
        cf_refused = False
    except na.NetError:
        cf_refused = True
    check("cfwidget 明确不兼容 → 拒绝下载", cf_refused)

    # ── A5. 整合包版本口径 ───────────────────────────────────────────
    na._modrinth_versions = lambda pid: [
        {"id": "v1"}, {"id": "v2"}]
    na._version_primary_file = lambda v, pid: (v["id"] + ".mrpack", "http://x")
    check("get_mod_download 默认取最新", na.get_mod_download("p")[0] == "v1.mrpack")
    check("get_mod_download 指定版本精确解析",
          na.get_mod_download("p", "v2")[0] == "v2.mrpack")
    try:
        na.get_mod_download("p", "NOPE")
        pack_err = None
    except na.NetError as e:
        pack_err = e
    check("整合包指定版本不存在 → 明确报错", pack_err is not None)

    # ── A6. keyless 指定 fileID 找不到 → 不静默退回最新 ──────────────
    na._curseforge_key = lambda: ""
    na._cf_files_mirror = lambda pid: [{"id": 999, "fileName": "other.jar"}]
    na._cfwidget_info = lambda pid: {"files": [{"id": 888, "name": "other.jar"}]}
    na.requests = type("R", (), {"get": lambda *a, **k: Resp(status=404),
                                 "RequestException": Exception})()
    try:
        na.download_curseforge_mod(
            "pid", tempfile.gettempdir(), file_id=12345)
        strict = False
    except na.NetError as e:
        strict = "不会退回最新版" in str(e)
    check("整合包 manifest 指定 fileID 找不到 → 明确报错", strict)

    # ── A7. UI 接线静态判据 ─────────────────────────────────────────
    browse = open(os.path.join(ROOT, "src", "pages_browse.py"),
                  encoding="utf-8").read()
    detail = open(os.path.join(ROOT, "src", "store_detail.py"),
                  encoding="utf-8").read()
    check("资源中心三路 CF 卡片下载都带版本 / 加载器",
          browse.count("mc_version=mc, loader=ld") == 3)
    # round-221：详情页 CF 分支已改走 download_cf_with_deps，判据随之改为
    # 「版本条目的 sha1 透传给本体下载」。真行为断言见
    # tests/test_round221_cf_files_paging.py（打桩验证 _cf_download_one 收到 sha1）。
    check("详情页 CF 指定版本下载带 sha1",
          "primary_sha1=f0.get(\"sha1\", \"\")" in detail)
finally:
    restore()

print("RESULT:", "PASS" if not FAILS else "FAIL %d: %r" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
