"""round-114: live view —— 给 Agent 的「实际体验」工具（AC 启动器版）。

对应共享工具目录里的 liveview（Chromium CDP 版）：那边用 CDP 收帧 + CDP 注入
输入；这里是 PySide6 原生窗口，等价物是：

* **帧** —— QTimer 定时 ``win.grab()`` → QImage → JPEG → WebSocket 推给浏览器面板；
* **输入** —— Qt 级事件注入（QMouseEvent / QKeyEvent / QWheelEvent），
  **不抢系统焦点**，离屏（offscreen）模式下照样能点；
* **控制口** —— HTTP ``POST /ctl``，所有碰 QWidget 的命令都在 Qt 主线程执行
  （跨线程操作 QWidget 不安全）。

只在 ``AC_LIVE=1`` 时启用，正式启动完全不受影响。

命令集：shot / click / move / wheel / key / keys / type / nav / eval / exec /
find / info / wait。

坐标系：click / move / wheel / find 一律以**当前抓帧窗口**为原点（弹窗优先），
且统一使用**帧像素**（已含屏幕缩放），拿到坐标即可直接点，不会点到画面对
不上的地方。

点击与按键**交给事件循环投递**，不在命令槽里同步执行：Qt 里同一个
QTimer 在其槽执行期间不会再次触发，若在泵槽里同步弹出模态框，泵定时器
会被卡死，整个控制口随之失声（帧流仍在，因为那是另一个定时器）。
"""
from __future__ import annotations

import base64
import builtins
import hashlib
import importlib
import json
import os
import queue
import select
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import (QBuffer, QEvent, QIODevice, QPoint, QPointF, Qt,
                            QTimer)
from PySide6.QtGui import (QImage, QInputMethodEvent, QKeyEvent, QMouseEvent,
                           QPixmap, QWheelEvent)
from PySide6.QtWidgets import QApplication, QWidget

# RFC6455 握手 GUID
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Qt 特殊键名 → Qt.Key_*（单字符走 getattr(Qt, "Key_A")）
_SPECIAL_KEYS = {
    "enter": "Key_Enter", "return": "Key_Return", "escape": "Key_Escape",
    "esc": "Key_Escape", "tab": "Key_Tab", "backspace": "Key_Backspace",
    "delete": "Key_Delete", "space": "Key_Space", "up": "Key_Up",
    "down": "Key_Down", "left": "Key_Left", "right": "Key_Right",
    "home": "Key_Home", "end": "Key_End", "pageup": "Key_PageUp",
    "pagedown": "Key_PageDown", "insert": "Key_Insert", "plus": "Key_Plus",
    "minus": "Key_Minus", "comma": "Key_Comma", "period": "Key_Period",
    "slash": "Key_Slash", "semicolon": "Key_Semicolon", "apostrophe": "Key_Apostrophe",
}
for _i in range(1, 13):
    _SPECIAL_KEYS["f%d" % _i] = "Key_F%d" % _i


def _qt_key(name: str) -> int:
    """把 'a' / 'Enter' / 'F5' 之类的键名翻译成 Qt.Key 枚举值。"""
    if not name:
        return 0
    low = name.lower()
    attr = _SPECIAL_KEYS.get(low)
    if attr is None:
        if len(low) == 1:
            attr = "Key_" + low.upper()
        else:
            attr = "Key_" + low.capitalize()
    return int(getattr(Qt, attr, 0))


# ── eval sandbox ───────────────────────────────────────────────────────────
# AC_LIVE is a developer-only mode: the control port is mounted *only* when
# the launcher is started with AC_LIVE=1.  The sandbox below is therefore a
# guard rail, NOT a security boundary -- its job is to keep a runaway
# expression from freezing the launcher UI, not to defend against an
# attacker.
_DENIED_BUILTINS = frozenset({
    "breakpoint", "compile", "delattr", "eval", "exec", "exit", "globals",
    "help", "input", "locals", "open", "quit", "setattr", "vars",
    "__import__",
})

_EVAL_TIMEOUT_DEFAULT = 5.0
_EVAL_TIMEOUT_MAX = 30.0


def _sandbox_builtins() -> dict:
    """Builtins allowed inside eval/exec.

    Everything that could read/write the file system or reach the import
    machinery is dropped; ``import_module`` is offered instead so that
    read-only introspection stays possible.
    """
    safe = {k: v for k, v in vars(builtins).items() if k not in _DENIED_BUILTINS}
    safe["import_module"] = importlib.import_module
    return safe


def _run_with_deadline(fn, timeout_s: float):
    """Run ``fn`` under a wall-clock deadline.

    ``sys.settrace`` raises a 'line' event for every executed Python line,
    which is enough to interrupt a runaway loop.  It cannot interrupt a
    blocking C call (``time.sleep`` for instance) -- the deadline is then
    only checked once control returns to Python.
    """
    deadline = time.monotonic() + timeout_s

    def _tracer(frame, event, arg):  # noqa: ARG001 - trace signature
        if time.monotonic() > deadline:
            raise TimeoutError("evaluation exceeded %.1fs" % timeout_s)
        return _tracer

    old_trace = sys.gettrace()
    sys.settrace(_tracer)
    try:
        return fn()
    finally:
        sys.settrace(old_trace)


def _jpeg_bytes(image, quality: int = 62) -> bytes:
    """QPixmap/QImage → JPEG 字节（帧流用，比 PNG 小一个量级）。"""
    img = image.toImage() if isinstance(image, QPixmap) else image
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPEG", quality)
    data = bytes(buf.data())
    buf.close()
    return data


class _JpegEncoder:
    """帧编码线程。

    ``grab()`` 必须在 GUI 线程（它要读 widget），但**编码不必**——原先在
    主线程里做 JPEG，每帧要把几毫秒的编码时间砸在被测对象自己身上，
    帧率抖动直接反映成 UI 卡顿。

    编码放在独立线程，输入队列只留最新一帧（maxsize=1）：编码跟不上就
    丢旧帧，永远不阻塞 GUI 线程，也不会有延迟在队列里堆积。
    """

    def __init__(self, quality: int, out_queue: "queue.Queue"):
        self._quality = quality
        self._out = out_queue
        self._in: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="aclive-jpeg")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def submit(self, image: QImage) -> None:
        """交一帧进去；上一帧还没编完就丢掉它（只保最新）。"""
        try:
            self._in.get_nowait()
        except queue.Empty:
            pass
        try:
            self._in.put_nowait(image)
        except queue.Full:
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                img = self._in.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                data = _jpeg_bytes(img, self._quality)
            except Exception:  # noqa: BLE001 - 单帧失败不影响后续
                continue
            try:
                self._out.put_nowait(data)
            except queue.Full:
                try:                     # 丢旧帧，绝不阻塞
                    self._out.get_nowait()
                    self._out.put_nowait(data)
                except Exception:
                    pass


class _TypeState:
    """State of one scheduled typing run.

    Typing used to ``time.sleep`` in the GUI thread between characters,
    which froze the frame stream (and the launcher UI) for the whole
    duration.  Now the characters are pushed by a timer: the GUI thread
    handles exactly one character per tick, and the target widget is locked
    on the first tick so the text cannot land in a different widget
    halfway through.
    """

    def __init__(self, text: str, delay_ms: int, target: QWidget | None):
        self.text = text
        self.chars = list(text)
        self.delay_ms = max(0, int(delay_ms))
        self.target = target      # resolved on the first tick
        self.index = 0


# ── WebSocket 客户端 ────────────────────────────────────────────────────────
class _WSClient:
    """单个面板连接。

    写帧走**独立写线程 + 有界队列**：广播线程只负责入队，慢客户端不会
    把广播线程卡住（原先是直接 ``sendall``，一个卡住的客户端会把所有
    其他面板一起拖死）。队列满时丢最旧的一帧——实时流本来就不该排队。
    """

    _SEND_TIMEOUT = 5.0

    def __init__(self, sock):
        self.sock = sock
        self.alive = True
        self._out: queue.Queue = queue.Queue(maxsize=4)
        self._writer = threading.Thread(target=self._write_loop, daemon=True,
                                        name="aclive-ws")
        self._writer.start()

    def send_frame(self, payload: bytes, opcode: int = 0x2) -> None:
        if not self.alive:
            return
        try:
            self._out.put_nowait((payload, opcode))
        except queue.Full:
            try:
                self._out.get_nowait()          # 丢最旧的一帧
                self._out.put_nowait((payload, opcode))
            except Exception:  # noqa: BLE001
                pass

    def send_json(self, obj) -> None:
        try:
            self.send_frame(json.dumps(obj).encode("utf-8"), opcode=0x1)
        except Exception:  # noqa: BLE001
            self.alive = False

    def close(self) -> None:
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass

    # ── 写线程 ──
    def _write_loop(self) -> None:
        while self.alive:
            try:
                payload, opcode = self._out.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._send_raw(self._frame_bytes(payload, opcode))
            except Exception:  # noqa: BLE001 - 连接坏了就丢弃这个客户端
                self.alive = False
                break

    @staticmethod
    def _frame_bytes(payload: bytes, opcode: int) -> bytes:
        head = bytearray()
        head.append(0x80 | opcode)
        n = len(payload)
        if n < 126:
            head.append(n)
        elif n < 65536:
            head.append(126)
            head += struct.pack("!H", n)
        else:
            head.append(127)
            head += struct.pack("!Q", n)
        return bytes(head) + payload

    def _send_raw(self, data: bytes) -> None:
        """带超时的发送。

        socket 本身是阻塞的，``sendall`` 在对端不读的时候会一直卡住。
        用 select 先探一次可写性，并自己处理部分写——保证单个卡住的
        客户端最多占用一个写线程，而不是拖住整个服务。
        """
        view = memoryview(data)
        while view:
            _r, w, _x = select.select([], [self.sock], [], self._SEND_TIMEOUT)
            if not w:
                raise OSError("send timed out")
            sent = self.sock.send(view)
            if sent <= 0:
                raise OSError("send failed")
            view = view[sent:]


class _WSHub:
    """维护所有面板连接，负责广播。"""

    def __init__(self):
        self._clients: set[_WSClient] = set()
        self._lock = threading.Lock()

    def add(self, client: _WSClient) -> None:
        with self._lock:
            self._clients.add(client)

    def remove(self, client: _WSClient) -> None:
        with self._lock:
            self._clients.discard(client)

    def count(self) -> int:
        with self._lock:
            return len(self._clients)

    def snapshot(self) -> list[_WSClient]:
        with self._lock:
            return list(self._clients)

    def broadcast(self, payload: bytes, opcode: int = 0x2) -> None:
        for c in self.snapshot():
            c.send_frame(payload, opcode)


# ── HTTP / WebSocket 服务 ───────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    server_version = "aclive/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003 - 静默默认访问日志
        pass

    # ── GET：面板页 / WebSocket 升级 ──
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
        if (self.headers.get("Upgrade") or "").lower() == "websocket":
            self._handle_ws()
            return
        path = self.path.split("?")[0]
        if path in ("/", "/panel.html"):
            data = self.server.live.panel_html()
            if not data:
                self.send_error(404, "panel.html not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404, "aclive: use GET / or POST /ctl")

    # ── POST：控制口 ──
    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0] != "/ctl":
            self.send_error(404, "aclive: use GET / or POST /ctl")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception as e:  # noqa: BLE001
            body = {"__error__": str(e)}
        result = self.server.live.dispatch(body)
        out = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    # ── WebSocket 升级（劫持这条连接）──
    def _handle_ws(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_error(400, "missing Sec-WebSocket-Key")
            return
        accept = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
        try:
            self.wfile.write(
                ("HTTP/1.1 101 Switching Protocols\r\n"
                 "Upgrade: websocket\r\n"
                 "Connection: Upgrade\r\n"
                 "Sec-WebSocket-Accept: " + accept + "\r\n\r\n").encode())
        except OSError:
            return
        self.close_connection = True
        client = _WSClient(self.connection)
        hub = self.server.live.hub
        hub.add(client)
        try:
            self._ws_read_loop(client)
        finally:
            hub.remove(client)
            client.close()

    def _ws_read_loop(self, client: _WSClient) -> None:
        """读客户端帧：文本 = 控制消息，二进制 = 忽略（面板不发二进制）。"""
        rfile = self.rfile
        while client.alive:
            hdr = self._read_exact(rfile, 2)
            if hdr is None:
                return
            b0, b1 = hdr[0], hdr[1]
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F
            if length == 126:
                ext = self._read_exact(rfile, 2)
                if ext is None:
                    return
                length = struct.unpack("!H", ext)[0]
            elif length == 127:
                ext = self._read_exact(rfile, 8)
                if ext is None:
                    return
                length = struct.unpack("!Q", ext)[0]
            mask = None
            if masked:
                mask = self._read_exact(rfile, 4)
                if mask is None:
                    return
            payload = self._read_exact(rfile, length) if length else b""
            if payload is None:
                return
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:      # close
                return
            if opcode == 0x9:      # ping → pong
                client.send_frame(payload, opcode=0xA)
                continue
            if opcode in (0x1, 0x2):
                try:
                    msg = json.loads(payload.decode("utf-8"))
                except Exception:
                    continue
                self.server.live.on_panel_message(msg)

    @staticmethod
    def _read_exact(rfile, n: int):
        try:
            data = rfile.read(n)
        except OSError:
            return None
        if data is None or len(data) < n:
            return None
        return data


# ── live server 本体 ───────────────────────────────────────────────────────
class LiveServer:
    """帧流 + 控制口。所有 QWidget 操作都被路由到 Qt 主线程。"""

    def __init__(self, win: QWidget, port: int = 8788, fps: int = 8,
                 quality: int = 62, panel_path: str = ""):
        self.win = win
        self.port = int(port)
        self.fps = max(1, min(30, int(fps)))
        self.quality = quality
        self.panel_path = panel_path
        self.hub = _WSHub()
        self._cmd_q: queue.Queue = queue.Queue()
        self._frame_q: queue.Queue = queue.Queue(maxsize=2)
        self._encoder = _JpegEncoder(quality, self._frame_q)
        self._stop = threading.Event()
        self._last_target: QWidget | None = None
        self._last_size = (0, 0)
        self._httpd = None
        self._type_state: _TypeState | None = None
        self._type_timer: QTimer | None = None
        self._type_done = threading.Event()
        self._type_done.set()

    # ── 生命周期 ──
    def start(self) -> None:
        self._encoder.start()
        threading.Thread(target=self._sender_loop, daemon=True,
                         name="aclive-sender").start()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        self._httpd.live = self  # type: ignore[attr-defined]
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True,
                         name="aclive-http").start()
        # 帧抓取 + 命令泵都在 Qt 主线程
        self._grab_timer = QTimer(self.win)
        self._grab_timer.timeout.connect(self._tick_grab)
        self._grab_timer.start(max(50, int(1000 / self.fps)))
        self._pump_timer = QTimer(self.win)
        self._pump_timer.timeout.connect(self._tick_pump)
        self._pump_timer.start(20)

    def stop(self) -> None:
        self._stop.set()
        self._encoder.stop()
        try:
            self._grab_timer.stop()
            self._pump_timer.stop()
        except Exception:
            pass
        self._cancel_type()
        try:
            self._httpd.shutdown()
        except Exception:
            pass

    # ── 帧 ──
    def _current_window(self) -> QWidget:
        """当前该抓哪个窗口：弹出菜单 > 模态对话框 > 焦点顶层窗口 > 主窗口。"""
        app = QApplication.instance()
        if app is not None:
            for getter in ("activePopupWidget", "activeModalWidget"):
                try:
                    w = getattr(app, getter)()
                except Exception:
                    w = None
                if w is not None and w.isVisible():
                    return w
            try:
                fw = app.focusWidget()
            except Exception:
                fw = None
            if fw is not None:
                top = fw.window()
                if top is not None and top is not self.win and top.isVisible():
                    return top
        return self.win

    def _tick_grab(self) -> None:
        if self.hub.count() == 0:
            return          # 没有观众就不抓帧，省 CPU
        try:
            target = self._current_window()
            pm = target.grab()
        except Exception:
            return
        if pm.isNull():
            return
        w, h = pm.width(), pm.height()
        if (w, h) != self._last_size:
            self._last_size = (w, h)
            self.hub.broadcast(json.dumps(
                {"t": "size", "w": w, "h": h}).encode("utf-8"), opcode=0x1)
        try:
            # Deep copy: QPixmap and QImage share the same buffer, so the
            # image would dangle once the pixmap goes out of scope.  The
            # encoding itself happens on the encoder thread -- the GUI
            # thread must not spend milliseconds per frame on JPEG.
            self._encoder.submit(pm.toImage().copy())
        except Exception:
            return

    def _sender_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._frame_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.hub.broadcast(data, opcode=0x2)
            except Exception:
                pass

    # ── 命令泵（Qt 主线程）──
    def _tick_pump(self) -> None:
        while True:
            try:
                fn, body, box, ev = self._cmd_q.get_nowait()
            except queue.Empty:
                return
            try:
                box["r"] = fn(body) or {"ok": 1}
            except Exception as e:  # noqa: BLE001
                box["r"] = {"ok": 0, "err": "%s: %s" % (type(e).__name__, e)}
            ev.set()

    def _on_main(self, fn, body) -> dict:
        box: dict = {}
        ev = threading.Event()
        self._cmd_q.put((fn, body, box, ev))
        if not ev.wait(10.0):
            return {"ok": 0, "err": "main-thread timeout"}
        return box.get("r") or {"ok": 0, "err": "no result"}

    # ── 面板消息（WS 读线程）→ 丢进主线程队列 ──
    def on_panel_message(self, msg) -> None:
        t = msg.get("t")
        if t == "mouse":
            kind = msg.get("kind")
            x = int(msg.get("x", 0))
            y = int(msg.get("y", 0))
            if kind == "move":
                self._on_main(self._cmd_move, {"x": x, "y": y})
            elif kind == "down":
                self._on_main(self._cmd_click, {"x": x, "y": y, "phase": "down",
                                                "button": msg.get("button", "left")})
            elif kind == "up":
                self._on_main(self._cmd_click, {"x": x, "y": y, "phase": "up",
                                                "button": msg.get("button", "left")})
        elif t == "wheel":
            self._on_main(self._cmd_wheel, {"x": int(msg.get("x", 0)),
                                            "y": int(msg.get("y", 0)),
                                            "dx": int(msg.get("dx", 0)),
                                            "dy": int(msg.get("dy", 0))})
        elif t == "key":
            kind = msg.get("kind")
            self._on_main(self._cmd_key, {"key": msg.get("key", ""),
                                          "code": msg.get("code", ""),
                                          "text": msg.get("text", ""),
                                          "phase": kind})

    # ── HTTP 控制口分发 ──
    def dispatch(self, body: dict) -> dict:
        if not isinstance(body, dict):
            return {"ok": 0, "err": "body must be a JSON object"}
        if body.get("__error__"):
            return {"ok": 0, "err": "bad JSON: " + str(body["__error__"])}
        cmd = str(body.get("cmd", "")).strip()
        if not cmd:
            return {"ok": 0, "err": "missing cmd"}
        if cmd == "wait":
            try:
                time.sleep(min(float(body.get("ms", 500)), 15000) / 1000.0)
            except Exception:
                pass
            return {"ok": 1}
        fn = getattr(self, "_cmd_" + cmd.replace("-", "_"), None)
        if fn is None:
            return {"ok": 0, "err": "unknown cmd: " + cmd}
        result = self._on_main(fn, body)
        if cmd == "type" and result.get("ok") and body.get("wait_ms"):
            # Typing runs on the GUI thread; the wait happens here (HTTP
            # thread) so the launcher keeps painting while the caller waits.
            try:
                timeout = min(float(body["wait_ms"]), 60000.0) / 1000.0
            except Exception:  # noqa: BLE001
                timeout = 0.0
            if timeout > 0:
                self._type_done.wait(timeout)
            result = dict(result)
            result["waited"] = True
        return result

    def panel_html(self) -> bytes:
        if not self.panel_path or not os.path.isfile(self.panel_path):
            return b""
        try:
            with open(self.panel_path, "rb") as fh:
                return fh.read()
        except OSError:
            return b""

    # ── 命令实现（都在 Qt 主线程）──
    def _capture_target(self) -> QWidget:
        """The window the frames are captured from.

        Everything that reports a coordinate (click / move / wheel / find)
        must live in *this* coordinate space, otherwise the agent clicks
        where the picture does not show anything.  When a modal dialog is
        open the dialog is the frame, so the dialog is the reference.
        """
        return self._current_window()

    @staticmethod
    def _target_identity(w: QWidget) -> dict:
        try:
            title = str(w.windowTitle() or "")
        except Exception:
            title = ""
        return {"cls": w.__class__.__name__, "title": title[:60],
                "w": w.width(), "h": w.height()}

    @staticmethod
    def _dpr(target: QWidget) -> float:
        """Device pixel ratio of a widget (1.0 on unscaled screens).

        The frames are grabbed in *device* pixels (a 125% screen gives a
        1375x900 image for a 1100x720 window), so every coordinate the
        agent sees in the picture is a device pixel.  Widget geometry, on
        the other hand, is in logical pixels.  All coordinates crossing the
        control port are therefore kept in device pixels.
        """
        try:
            dpr = float(target.devicePixelRatioF())
        except Exception:  # noqa: BLE001
            dpr = 1.0
        return dpr if dpr > 0 else 1.0

    def _target_at(self, x: int, y: int):
        target = self._capture_target()
        dpr = self._dpr(target)
        pos = QPoint(int(round(x / dpr)), int(round(y / dpr)))
        w = None
        try:
            w = target.childAt(pos)
        except Exception:
            w = None
        if w is None:
            w = target
        try:
            gp = target.mapToGlobal(pos)
        except Exception:
            gp = QPoint(x, y)
        return w, gp

    def _cmd_shot(self, body) -> dict:
        path = body.get("path") or os.path.join(
            os.path.expanduser("~"), "aclive_shot_%d.png" % int(time.time()))
        target = self._capture_target()
        pm = target.grab()
        if pm.isNull():
            return {"ok": 0, "err": "grab failed"}
        ok = pm.save(str(path), "PNG")
        if not ok:
            return {"ok": 0, "err": "save failed: " + str(path)}
        return {"ok": 1, "path": str(path), "bytes": os.path.getsize(str(path)),
                "w": pm.width(), "h": pm.height()}

    def _cmd_click(self, body) -> dict:
        """Click at (x, y) -- delivered from the event loop.

        The delivery is deliberately *not* done inside this command: a
        button that opens a modal dialog would block this slot, and a
        blocked slot stops its own QTimer from firing again.  The pump
        timer would then go silent and the whole control port would die
        until the dialog was closed.  Handing the click to the event loop
        keeps the pump alive while a modal is open.
        """
        x = int(body.get("x", 0))
        y = int(body.get("y", 0))
        phase = body.get("phase", "full")
        button = {"left": Qt.LeftButton, "right": Qt.RightButton,
                  "middle": Qt.MiddleButton}.get(
                      body.get("button", "left"), Qt.LeftButton)
        w, gp = self._target_at(x, y)
        lp = QPointF(w.mapFromGlobal(gp))
        label = str(getattr(w, "text", lambda: "")() or "")[:60]

        def _deliver() -> None:
            self._last_target = w
            try:
                if phase in ("down", "full"):
                    ev = QMouseEvent(QEvent.MouseButtonPress, lp, QPointF(gp),
                                     button, button, Qt.NoModifier)
                    QApplication.sendEvent(w, ev)
                if phase in ("up", "full"):
                    ev = QMouseEvent(QEvent.MouseButtonRelease, lp, QPointF(gp),
                                     button, Qt.NoButton, Qt.NoModifier)
                    QApplication.sendEvent(w, ev)
                # A synthetic mouse event does not move the keyboard focus,
                # but a real click does -- without this the follow-up
                # "type" would land in the previously focused widget.
                if w.focusPolicy() != Qt.NoFocus:
                    w.setFocus()
            except Exception:  # noqa: BLE001 - the widget may be gone
                pass

        QTimer.singleShot(0, _deliver)
        return {"ok": 1, "widget": w.__class__.__name__, "text": label,
                "deferred": True}

    def _cmd_move(self, body) -> dict:
        x = int(body.get("x", 0))
        y = int(body.get("y", 0))
        w, gp = self._target_at(x, y)
        self._last_target = w
        lp = QPointF(w.mapFromGlobal(gp))
        ev = QMouseEvent(QEvent.MouseMove, lp, QPointF(gp), Qt.NoButton,
                         Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(w, ev)
        return {"ok": 1}

    def _cmd_wheel(self, body) -> dict:
        x = int(body.get("x", 0))
        y = int(body.get("y", 0))
        dx = int(body.get("dx", 0))
        dy = int(body.get("dy", 0))
        w, gp = self._target_at(x, y)
        lp = QPointF(w.mapFromGlobal(gp))
        ev = QWheelEvent(lp, QPointF(gp), QPoint(0, 0), QPoint(dx, dy),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(w, ev)
        return {"ok": 1}

    def _key_target(self):
        app = QApplication.instance()
        fw = None
        try:
            fw = app.focusWidget() if app is not None else None
        except Exception:
            fw = None
        if fw is not None and fw.isVisible():
            return fw
        if self._last_target is not None:
            return self._last_target
        return self.win

    def _cmd_key(self, body) -> dict:
        """Press a key -- delivered from the event loop (see _cmd_click).

        The target is resolved at delivery time, not at command time: a
        click that is still queued may move the focus in the meantime.
        """
        name = str(body.get("key", ""))
        text = body.get("text", "")
        phase = body.get("phase", "full")
        kv = _qt_key(name)
        if kv == 0:
            return {"ok": 0, "err": "unknown key: " + name}

        def _deliver() -> None:
            w = self._key_target()
            if phase in ("down", "full"):
                QApplication.sendEvent(
                    w, QKeyEvent(QEvent.KeyPress, kv, Qt.NoModifier, text))
            if phase in ("up", "full"):
                QApplication.sendEvent(
                    w, QKeyEvent(QEvent.KeyRelease, kv, Qt.NoModifier, text))

        QTimer.singleShot(0, _deliver)
        return {"ok": 1, "key": name, "deferred": True}

    def _cmd_type(self, body) -> dict:
        """Type text into the focused widget.

        The characters are pushed by a timer instead of ``time.sleep`` in the
        GUI thread: the old version froze the whole UI (and the frame
        stream) for the duration of the text.  The target widget is locked
        on the first tick, so the text cannot drift into another widget
        half-way.
        """
        text = str(body.get("text", ""))
        delay = max(0, int(body.get("ms", 15)))
        if not text:
            return {"ok": 1, "chars": 0, "async": 0}
        self._cancel_type()
        self._type_done.clear()
        self._type_state = _TypeState(text, delay, None)
        timer = QTimer(self.win)
        timer.setInterval(max(1, delay))
        timer.timeout.connect(self._type_tick)
        timer.start()
        self._type_timer = timer
        return {"ok": 1, "chars": len(text), "async": 1,
                "target": self._key_target().__class__.__name__}

    def _type_tick(self) -> None:
        """Timer callback: push one character, then give the GUI a breath."""
        st = self._type_state
        if st is None:
            self._cancel_type()
            return
        if st.index >= len(st.chars):
            self._cancel_type()
            return
        if st.target is None:
            # Resolve on the first tick: a click that was still queued may
            # have moved the focus since the command arrived.
            st.target = self._key_target()
        ch = st.chars[st.index]
        st.index += 1
        self._send_char(st.target, ch)

    def _cancel_type(self) -> None:
        """Stop a running typing job and release the waiter."""
        if self._type_timer is not None:
            try:
                self._type_timer.stop()
                self._type_timer.deleteLater()
            except Exception:
                pass
            self._type_timer = None
        self._type_state = None
        self._type_done.set()

    @staticmethod
    def _send_char(w: QWidget, ch: str) -> None:
        """Send one character to a widget."""
        kv = _qt_key(ch)
        if kv:
            QApplication.sendEvent(
                w, QKeyEvent(QEvent.KeyPress, kv, Qt.NoModifier, ch))
            QApplication.sendEvent(
                w, QKeyEvent(QEvent.KeyRelease, kv, Qt.NoModifier, ch))
            return
        # Not a keyboard key (CJK, emoji, ...): an input-method commit is
        # Qt's supported way of injecting arbitrary text.
        ev = QInputMethodEvent()
        ev.setCommitString(ch)
        QApplication.sendEvent(w, ev)

    def _cmd_keys(self, body) -> dict:
        seq = body.get("keys") or []
        for k in seq:
            if isinstance(k, str):
                k = {"key": k}
            self._cmd_key(k)
        return {"ok": 1, "count": len(seq)}

    def _cmd_nav(self, body) -> dict:
        """Switch page through the window's public API.

        The old implementation called the private ``_switch_stack`` and
        indexed ``STACK_INDEX`` itself, which broke as soon as the window
        changed its page model and bypassed the nav-row handling of the
        alternative layouts.
        """
        key = str(body.get("key", ""))
        if not key:
            return {"ok": 0, "err": "missing key"}
        show = getattr(self.win, "show_page", None)
        if not callable(show):
            return {"ok": 0, "err": "main window exposes no show_page()"}
        try:
            ok = bool(show(key))
        except Exception as e:  # noqa: BLE001
            return {"ok": 0, "err": "%s: %s" % (type(e).__name__, e)}
        if not ok:
            return {"ok": 0, "err": "unknown page: " + key,
                    "pages": sorted(self._page_keys())}
        return {"ok": 1, "page": key}

    @staticmethod
    def _page_keys() -> set:
        try:
            from .main_window import STACK_INDEX
            return set(STACK_INDEX.keys())
        except Exception:  # noqa: BLE001
            return set()

    @staticmethod
    def _eval_timeout(body) -> float:
        try:
            ms = float(body.get("timeout_ms", _EVAL_TIMEOUT_DEFAULT * 1000))
        except Exception:  # noqa: BLE001
            ms = _EVAL_TIMEOUT_DEFAULT * 1000
        return max(0.05, min(ms / 1000.0, _EVAL_TIMEOUT_MAX))

    def _cmd_eval(self, body) -> dict:
        expr = str(body.get("expr", ""))
        if not expr.strip():
            return {"ok": 0, "err": "empty expr"}
        timeout = self._eval_timeout(body)
        try:
            value = _run_with_deadline(
                lambda: eval(expr, self._eval_globals()), timeout)
        except TimeoutError as e:
            return {"ok": 0, "err": "timeout: %s" % e}
        except Exception as e:  # noqa: BLE001
            return {"ok": 0, "err": "%s: %s" % (type(e).__name__, e)}
        return {"ok": 1, "result": repr(value)}

    def _cmd_exec(self, body) -> dict:
        code = str(body.get("code", body.get("expr", "")))
        if not code.strip():
            return {"ok": 0, "err": "empty code"}
        timeout = self._eval_timeout(body)
        try:
            _run_with_deadline(lambda: exec(code, self._eval_globals()),
                               timeout)
        except TimeoutError as e:
            return {"ok": 0, "err": "timeout: %s" % e}
        except Exception as e:  # noqa: BLE001
            return {"ok": 0, "err": "%s: %s" % (type(e).__name__, e)}
        return {"ok": 1}

    def _cmd_find(self, body) -> dict:
        """Locate widgets in the window the frames are captured from.

        The answer carries the identity of that window, so the caller can
        tell whether a dialog took over the screen in the meantime.
        """
        target = self._capture_target()
        items = self._find_widgets(
            text=body.get("text"),
            cls=body.get("cls"),
            visible_only=bool(body.get("visible_only", True)),
        )
        return {"ok": 1, "target": self._target_identity(target),
                "dpr": self._dpr(target),
                "count": len(items), "items": items}

    def _cmd_info(self, body) -> dict:
        pages = sorted(self._page_keys())
        cur = None
        try:
            cur = self.win.stack.currentIndex()
        except Exception:
            pass
        typing = None
        st = self._type_state
        if st is not None:
            typing = {"sent": st.index, "total": len(st.chars),
                      "done": st.index >= len(st.chars)}
        target = self._capture_target()
        dpr = self._dpr(target)
        return {"ok": 1,
                "title": self.win.windowTitle(),
                "size": [self.win.width(), self.win.height()],
                "stack_index": cur,
                "pages": pages,
                "clients": self.hub.count(),
                "fps": self.fps,
                "target": self._target_identity(target),
                "dpr": dpr,
                "frame": [int(round(target.width() * dpr)),
                          int(round(target.height() * dpr))],
                "typing": typing}

    # ── eval 上下文 ──
    def _eval_globals(self) -> dict:
        from PySide6 import QtCore, QtGui, QtWidgets
        g = {
            "__builtins__": _sandbox_builtins(),
            "win": self.win,
            "app": QApplication.instance(),
            "Qt": Qt,
            "QtCore": QtCore,
            "QtGui": QtGui,
            "QtWidgets": QtWidgets,
            "import_module": importlib.import_module,
        }
        g["find"] = self._find_widgets
        g["click_text"] = self._click_text
        return g

    def _find_widgets(self, text=None, cls=None, visible_only=True):
        """按文本 / 类名找控件（给 Agent 定位按钮用）。

        坐标是**相对抓帧窗口**（弹窗优先）的位置，且与 ``click`` 用的坐标系
        完全一致 —— 都是**帧像素**（含屏幕缩放），拿到就能直接点，不会点
        到画面对不上的地方。
        """
        target = self._capture_target()
        dpr = self._dpr(target)
        out = []
        for w in target.findChildren(QWidget):
            if visible_only and not w.isVisible():
                continue
            if cls and cls.lower() not in w.__class__.__name__.lower():
                continue
            t = str(getattr(w, "text", lambda: "")() or "")
            if text and text.lower() not in t.lower():
                continue
            try:
                pos = w.mapTo(target, QPoint(0, 0))
                g = w.geometry()
                x, y = pos.x(), pos.y()
            except Exception:
                g = w.geometry()
                x, y = g.x(), g.y()
            out.append({"cls": w.__class__.__name__, "text": t[:60],
                        "obj": w.objectName(),
                        "x": int(round(x * dpr)), "y": int(round(y * dpr)),
                        "w": int(round(g.width() * dpr)),
                        "h": int(round(g.height() * dpr))})
        return out

    def _click_text(self, text):
        """按文本点击第一个匹配的按钮/标签（找不到返回 None）。

        点击同样交给事件循环投递：eval 是在泵槽里跑的，若被点击的按钮弹出
        模态框，泵定时器会被卡住，控制口随之失声。
        """
        target = self._capture_target()
        for w in target.findChildren(QWidget):
            if not w.isVisible():
                continue
            t = str(getattr(w, "text", lambda: "")() or "")
            if text.lower() not in t.lower():
                continue
            if hasattr(w, "click") and callable(getattr(w, "click")):
                QTimer.singleShot(0, w.click)
                return w.__class__.__name__ + ":" + t[:40]
        return None


def attach_live(win: QWidget) -> LiveServer:
    """把 live server 挂到主窗口上（main.py 在 AC_LIVE=1 时调用）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    panel = os.path.join(root, "tools", "aclive", "panel.html")
    port = int(os.environ.get("AC_LIVE_PORT", "8788") or 8788)
    fps = int(os.environ.get("AC_LIVE_FPS", "8") or 8)
    quality = int(os.environ.get("AC_LIVE_QUALITY", "62") or 62)
    srv = LiveServer(win, port=port, fps=fps, quality=quality,
                     panel_path=panel)
    srv.start()
    win._aclive = srv  # 防 GC
    print("[aclive] panel    → http://127.0.0.1:%d/" % port, flush=True)
    print("[aclive] control  → POST http://127.0.0.1:%d/ctl" % port, flush=True)
    print("[aclive] fps=%d quality=%d panel=%s" % (fps, quality, panel), flush=True)
    return srv
