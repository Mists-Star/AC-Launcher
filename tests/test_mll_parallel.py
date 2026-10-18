"""round-111 集成测试：mll download_file 大文件分片（诊断脚本，不入库）。

起一个支持 Range 的本地 HTTP 服务器，真跑 minecraft_launcher_lib.install
的 download_file，验证：
  1. 客户端 jar 形态的目标真的走了分片（多发不同 offset 的 Range 请求）
  2. 下载结果字节正确 + sha1 校验通过
  3. sha1 不符 → 抛 mll 的 InvalidChecksum
  4. 服务器不支持 Range → 回退单流，结果仍正确
  5. 目标已存在且 sha1 正确 → 跳过（零请求）
  6. 回调协议：setStatus 有，setProgress / setMax 绝不出现
  7. 小文件（普通 library 路径）→ 零探测请求（防净回归的关键断言）
"""
import hashlib
import http.server
import os
import shutil
import socketserver
import sys
import tempfile
import threading

# tests/ 下运行：仓库根 = tests 的上一级
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 确保不走任何代理（本地 127.0.0.1 服务器）
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY"):
    os.environ.pop(_k, None)

BIG = 12 * 1024 * 1024          # 12MB > _PARALLEL_MIN_BYTES(8MB)
SMALL = 64 * 1024               # 64KB < 阈值
DATA = os.urandom(BIG)
SHA1 = hashlib.sha1(DATA).hexdigest()

REQS: list[str] = []            # 记录所有请求的 Range 头
CODES: list[int] = []           # 记录所有响应的状态码
_LOCK = threading.Lock()


class Handler(http.server.BaseHTTPRequestHandler):
    # HTTP/1.0：每请求独立连接，避免 keep-alive 下客户端断开时的
    # ConnectionResetError 噪音（不影响被测逻辑）。
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        rng = self.headers.get("Range")
        with _LOCK:
            REQS.append("%s|%s" % (self.path, rng or "-"))
        no_range = self.path.startswith("/norange/")
        if rng and rng.startswith("bytes=") and not no_range:
            s, _, e = rng[6:].partition("-")
            s = int(s)
            e = min(int(e) if e else len(DATA) - 1, len(DATA) - 1)
            body = DATA[s:e + 1]
            self.send_response(206)
            with _LOCK:
                CODES.append(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (s, e, len(DATA)))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        with _LOCK:
            CODES.append(200)
        self.send_header("Content-Length", str(len(DATA)))
        self.end_headers()
        self.wfile.write(DATA)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_server():
    srv = Server(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


def main():
    srv, port = start_server()
    base = "http://127.0.0.1:%d" % port
    tmp = tempfile.mkdtemp(prefix="ac_r111_")
    fails = []

    def check(label, cond, extra=""):
        print("  %s %-46s %s" % ("OK  " if cond else "FAIL", label, extra))
        if not cond:
            fails.append(label)

    try:
        from src.core import mirror
        from src import net_api

        # ── 1. 打补丁，确认 install 模块的 download_file 被包上 ──
        mirror.patch_install_session()
        import minecraft_launcher_lib.install as mll_install
        check("install.download_file 已被包裹",
              getattr(mll_install.download_file, "_ac_parallel_wrapped", False))

        # ── 2. 客户端 jar → 分片 ──
        REQS.clear()
        CODES.clear()
        mc = os.path.join(tmp, "mc1")
        dest = os.path.join(mc, "versions", "1.20.1", "1.20.1.jar")
        cb = {"setStatus": lambda s: None, "setProgress": lambda v: None,
              "setMax": lambda m: None}
        ok = mll_install.download_file(base + "/client.jar", dest,
                                       cb, sha1=SHA1)
        with open(dest, "rb") as fh:
            got = fh.read()
        rng_reqs = [r for r in REQS if r.startswith("/client.jar|bytes=")]
        # 探测请求是 bytes=0-0；真正的分块是其它 offset
        chunks = [r for r in rng_reqs if not r.endswith("bytes=0-0")]
        check("客户端 jar 下载成功", ok is True)
        check("字节完全正确", got == DATA, "(%d bytes)" % len(got))
        check("sha1 校验通过（未抛异常）", True)
        check("真的走了分片（多个数据块）", len(chunks) >= 3,
              "共 %d 个 Range 请求 / %d 个数据块" % (len(rng_reqs), len(chunks)))
        offsets = [r.split("bytes=")[1].split("-")[0] for r in chunks]
        check("分块 offset 不重复", len(set(offsets)) == len(offsets),
              "offsets=%s" % sorted(offsets, key=int)[:8])
        check("服务器回了多个 206", CODES.count(206) >= 3,
              "206=%d 200=%d" % (CODES.count(206), CODES.count(200)))

        # ── 3. sha1 不符 → InvalidChecksum ──
        REQS.clear()
        dest2 = os.path.join(tmp, "mc2", "versions", "1.20.1", "1.20.1.jar")
        try:
            mll_install.download_file(base + "/client.jar", dest2, cb,
                                      sha1="0" * 40)
            check("sha1 不符应抛 InvalidChecksum", False, "未抛异常")
        except Exception as e:
            check("sha1 不符应抛 InvalidChecksum",
                  type(e).__name__ == "InvalidChecksum", type(e).__name__)

        # ── 4. 服务器不支持 Range → 回退单流 ──
        REQS.clear()
        CODES.clear()
        dest3 = os.path.join(tmp, "mc3", "versions", "1.20.1", "1.20.1.jar")
        ok = mll_install.download_file(base + "/norange/client.jar", dest3,
                                       cb, sha1=SHA1)
        with open(dest3, "rb") as fh:
            got3 = fh.read()
        check("无 Range 服务器仍下载成功", ok is True and got3 == DATA)
        check("无 Range 时回退单流（服务器零个 206）", CODES.count(206) == 0,
              "206=%d 200=%d" % (CODES.count(206), CODES.count(200)))
        check("无 Range 时不留 .part 残件",
              not os.path.exists(dest3 + ".part"))

        # ── 5. 已存在且 sha1 正确 → 跳过 ──
        REQS.clear()
        ok = mll_install.download_file(base + "/client.jar", dest, cb,
                                       sha1=SHA1)
        check("已存在且校验通过 → 跳过", ok is False and len(REQS) == 0,
              "请求数=%d" % len(REQS))

        # ── 6. 回调协议：只发 setStatus，不发 setProgress/setMax ──
        REQS.clear()
        seen = []
        cb2 = {"setStatus": lambda s: seen.append(("status", s)),
               "setProgress": lambda v: seen.append(("progress", v)),
               "setMax": lambda m: seen.append(("max", m))}
        dest4 = os.path.join(tmp, "mc4", "versions", "1.20.1", "1.20.1.jar")
        mll_install.download_file(base + "/client.jar", dest4, cb2, sha1=SHA1)
        kinds = {k for k, _ in seen}
        check("setStatus 被调用", "status" in kinds)
        check("setProgress 未被调用（保文件计数进度）", "progress" not in kinds)
        check("setMax 未被调用", "max" not in kinds)

        # ── 7. 小文件（普通 library 路径）→ 零探测请求 ──
        REQS.clear()
        libdir = os.path.join(tmp, "mc5", "libraries", "com", "mojang", "xyz-1.0.jar")
        ok = mll_install.download_file(base + "/lib.jar", libdir, cb)
        # mll 会真去下载（返回 True），但绝不能有 Range 探测
        check("小文件不触发分片探测",
              not any("|bytes=" in r for r in REQS),
              "请求数=%d（应只有 1 个普通 GET）" % len(REQS))

        # ── 8. 阈值常量未被意外改动 ──
        check("_PARALLEL_MIN_BYTES 仍为 8MB",
              net_api._PARALLEL_MIN_BYTES == 8 * 1024 * 1024)

    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print("失败 %d 项: %s" % (len(fails), fails))
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
