"""round-111 集成测试：整合包下载进度桥接（诊断脚本，不入库）。

验证 net_api.download_modpack_to 把 mll 风格 callback 正确桥接到字节级进度：
  1. setMax 只被调用一次，且值 = 文件总长
  2. setProgress 被多次调用且单调不减
  3. 文件字节正确
  4. callback=None（裸 Worker 场景）仍能正常下载
  5. progress 回调抛异常不会拖垮下载
"""
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
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY"):
    os.environ.pop(_k, None)

SIZE = 3 * 1024 * 1024          # 3MB（小于 8MB 阈值 → 单流，验证进度而非分片）
DATA = os.urandom(SIZE)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = DATA
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    url = "http://127.0.0.1:%d/pack.mrpack" % port
    tmp = tempfile.mkdtemp(prefix="ac_r111b_")
    fails = []

    def check(label, cond, extra=""):
        print("  %s %-44s %s" % ("OK  " if cond else "FAIL", label, extra))
        if not cond:
            fails.append(label)

    try:
        from src import net_api

        # 把 get_mod_download 指向本地服务器
        net_api.get_mod_download = lambda pid: ("pack.mrpack", url)

        # ── 1~3. 带 mll 风格 callback ──
        maxes, prog = [], []

        def set_max(m):
            maxes.append(m)

        def set_progress(v):
            prog.append(v)

        dest_dir = os.path.join(tmp, "a")
        path = net_api.download_modpack_to(
            "proj", dest_dir,
            callback={"setProgress": set_progress, "setMax": set_max,
                      "setStatus": lambda s: None})
        with open(path, "rb") as fh:
            got = fh.read()
        check("下载成功且字节正确", got == DATA, "(%d bytes)" % len(got))
        check("setMax 只调一次", len(maxes) == 1, "maxes=%s" % maxes)
        check("setMax 值 = 文件总长", maxes == [SIZE])
        check("setProgress 被多次调用", len(prog) >= 2,
              "%d 次" % len(prog))
        check("setProgress 单调不减",
              all(b >= a for a, b in zip(prog, prog[1:])),
              "末值=%s" % (prog[-1] if prog else None))
        check("setProgress 最终到达总量",
              bool(prog) and prog[-1] >= SIZE, "末值=%d" % (prog[-1] if prog else 0))

        # ── 4. callback=None（裸 Worker 场景）──
        dest2 = os.path.join(tmp, "b")
        path2 = net_api.download_modpack_to("proj", dest2, callback=None)
        with open(path2, "rb") as fh:
            got2 = fh.read()
        check("callback=None 仍能下载", got2 == DATA)

        # ── 5. progress 回调抛异常不拖垮下载 ──
        def boom(v):
            raise RuntimeError("ui exploded")

        dest3 = os.path.join(tmp, "c")
        path3 = net_api.download_modpack_to(
            "proj", dest3, callback={"setProgress": boom, "setMax": boom})
        with open(path3, "rb") as fh:
            got3 = fh.read()
        check("回调抛异常不拖垮下载", got3 == DATA)

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
