"""round-111 补测：mod 下载进度桥接（多文件聚合）（诊断脚本，不入库）。"""
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

CHUNK = 512 * 1024
FILES = {"a.jar": CHUNK * 4, "b.jar": CHUNK * 2, "c.jar": CHUNK * 6}
BODIES = {n: os.urandom(sz) for n, sz in FILES.items()}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        name = self.path.lstrip("/")
        body = BODIES.get(name)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
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
    base = "http://127.0.0.1:%d/" % port
    tmp = tempfile.mkdtemp(prefix="ac_r111c_")
    fails = []

    def check(label, cond, extra=""):
        print("  %s %-46s %s" % ("OK  " if cond else "FAIL", label, extra))
        if not cond:
            fails.append(label)

    try:
        from src import net_api

        # 三个文件的假依赖树
        items = [{"url": base + n, "filename": n, "project_id": pid}
                 for n, pid in (("a.jar", "main"), ("b.jar", "dep1"),
                                ("c.jar", "dep2"))]
        net_api.resolve_mod_dependencies = lambda *a, **k: items

        maxes, prog = [], []

        dest = os.path.join(tmp, "mods")
        primary = net_api.download_mod_to(
            "main", dest, callback={"setProgress": lambda v: prog.append(v),
                                    "setMax": lambda m: maxes.append(m),
                                    "setStatus": lambda s: None})

        check("返回主文件路径", primary == os.path.join(dest, "a.jar"),
              os.path.basename(primary))
        check("三个文件全部落盘",
              all(os.path.isfile(os.path.join(dest, n)) for n in FILES))
        check("文件字节正确",
              all(open(os.path.join(dest, n), "rb").read() == BODIES[n]
                  for n in FILES))
        check("setMax = 文件数 × 100", maxes == [300], "maxes=%s" % maxes)
        check("setProgress 单调不减",
              all(b >= a for a, b in zip(prog, prog[1:])))
        check("setProgress 最终到 300", bool(prog) and prog[-1] == 300,
              "末值=%s" % (prog[-1] if prog else None))
        # 跨文件平滑：应出现 0~100、100~200、200~300 三段
        segs = {v // 100 for v in prog}
        check("进度跨文件平滑前进（覆盖多段）", len(segs) >= 3,
              "段=%s" % sorted(segs))

        # callback=None（裸 Worker 场景）仍可下载
        dest2 = os.path.join(tmp, "mods2")
        net_api.download_mod_to("main", dest2, callback=None)
        check("callback=None 仍可下载",
              all(os.path.isfile(os.path.join(dest2, n)) for n in FILES))

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
