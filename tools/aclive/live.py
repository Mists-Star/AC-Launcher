"""round-114: live view 启动器 + 控制口 CLI。

用法::

    python tools/aclive/live.py start                # 离屏起一个 live 实例
    python tools/aclive/live.py start --headful      # 弹真窗口（你能直接看/点）
    python tools/aclive/live.py start --page store   # 启动后直接跳到某页
    python tools/aclive/live.py ctl '{"cmd":"info"}' # 直接发控制命令
    python tools/aclive/live.py shot D:/tmp/x.png    # 截当前画面存 PNG

start 之后浏览器打开 http://127.0.0.1:8788/ 就是实时面板；
Agent 侧主要用 ctl（shot / nav / click / eval）做「看→改→再看」的闭环。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # tools/aclive → tools → 仓库根
DEFAULT_PORT = 8788
PID_FILE = os.path.join(tempfile.gettempdir(), "ac_aclive.pid")


def _python() -> str:
    """优先用仓库自带的 venv，避免系统 Python 缺 PySide6。"""
    p = os.path.join(ROOT, "venv", "Scripts", "python.exe")
    return p if os.path.isfile(p) else sys.executable


def _ctl(body: dict, port: int, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(
        "http://127.0.0.1:%d/ctl" % port,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_start(args) -> int:
    env = os.environ.copy()
    env["AC_LIVE"] = "1"
    env["AC_NO_ONBOARDING"] = "1"   # 教程弹窗会挡住画面
    env["AC_NO_SPLASH"] = "1"       # 第一帧就该是主窗口
    env["AC_LIVE_PORT"] = str(args.port)
    env["AC_LIVE_FPS"] = str(args.fps)
    if args.page:
        env["AC_JUMP"] = args.page
    if args.headful:
        env.pop("QT_QPA_PLATFORM", None)
    else:
        env["QT_QPA_PLATFORM"] = "offscreen"
    # 离屏渲染时字体回退会变成方框，指到系统字体目录
    env.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    print("[aclive] 面板 → http://127.0.0.1:%d/" % args.port, flush=True)
    proc = subprocess.Popen([_python(), os.path.join(ROOT, "main.py")],
                            env=env, cwd=ROOT)
    try:
        with open(PID_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(proc.pid))
    except OSError:
        pass
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


def cmd_stop(args) -> int:
    pid = _read_pid()
    if not pid:
        print("no live instance running")
        return 0
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True)
        print("stopped pid %d" % pid)
    except Exception as e:  # noqa: BLE001
        print("stop failed: %s" % e, file=sys.stderr)
        return 1
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    return 0


def cmd_restart(args) -> int:
    """杀掉旧实例再起新的——改了源码之后的「热重启」入口。"""
    cmd_stop(args)
    time.sleep(0.6)
    return cmd_start(args)


def _read_pid() -> int:
    try:
        with open(PID_FILE, "r", encoding="utf-8") as fh:
            return int((fh.read() or "0").strip() or 0)
    except (OSError, ValueError):
        return 0


def _body_from_args(args) -> dict:
    """把命令行参数拼成 /ctl 的 JSON body。

    优先用 --cmd/--key/--x… 这种不需要引号的写法（Windows 下把 JSON 塞进
    argv 很容易被引号解析吃掉）；位置参数 JSON 仍保留作为兜底。
    """
    if args.json:
        raw = " ".join(args.json)
        return json.loads(raw)
    body: dict = {"cmd": args.cmd}
    for name in ("key", "text", "expr", "path", "code", "button", "phase",
                 "cls"):
        val = getattr(args, name, None)
        if val not in (None, ""):
            body[name] = val
    for name in ("x", "y", "dx", "dy", "ms", "wait_ms", "timeout_ms"):
        val = getattr(args, name, None)
        if val is not None:
            body[name] = int(val)
    return body


def cmd_ctl(args) -> int:
    try:
        body = _body_from_args(args)
    except Exception as e:  # noqa: BLE001
        print("bad request: %s" % e, file=sys.stderr)
        return 2
    try:
        result = _ctl(body, args.port)
    except Exception as e:  # noqa: BLE001
        print("ctl failed: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_shot(args) -> int:
    try:
        result = _ctl({"cmd": "shot", "path": args.path}, args.port)
    except Exception as e:  # noqa: BLE001
        print("shot failed: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="AC live view")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = ap.add_subparsers(dest="cmd")

    sp = sub.add_parser("start", help="起一个 live 实例")
    sp.add_argument("--headful", action="store_true", help="弹真窗口")
    sp.add_argument("--fps", type=int, default=8)
    sp.add_argument("--page", default="", help="启动后跳到的页面 key")
    sp.set_defaults(func=cmd_start)

    rp = sub.add_parser("restart", help="杀掉旧实例再起新的（改完源码用）")
    rp.add_argument("--headful", action="store_true", help="弹真窗口")
    rp.add_argument("--fps", type=int, default=8)
    rp.add_argument("--page", default="", help="启动后跳到的页面 key")
    rp.set_defaults(func=cmd_restart)

    stp = sub.add_parser("stop", help="停掉 live 实例")
    stp.set_defaults(func=cmd_stop)

    cp = sub.add_parser("ctl", help="发一条控制命令")
    cp.add_argument("json", nargs="*", help="整条命令的 JSON（可选）")
    cp.add_argument("--cmd", default="info", help="命令名")
    cp.add_argument("--key", default="")
    cp.add_argument("--text", default="")
    cp.add_argument("--expr", default="")
    cp.add_argument("--code", default="")
    cp.add_argument("--path", default="")
    cp.add_argument("--button", default="")
    cp.add_argument("--phase", default="")
    cp.add_argument("--x", type=int)
    cp.add_argument("--y", type=int)
    cp.add_argument("--dx", type=int)
    cp.add_argument("--dy", type=int)
    cp.add_argument("--ms", type=int)
    cp.add_argument("--wait-ms", dest="wait_ms", type=int,
                    help="type 命令：等打完再返回")
    cp.add_argument("--timeout-ms", dest="timeout_ms", type=int,
                    help="eval/exec 命令：执行时限")
    cp.add_argument("--cls", default="", help="find 命令：按类名过滤")
    cp.set_defaults(func=cmd_ctl)

    sh = sub.add_parser("shot", help="截图存 PNG")
    sh.add_argument("path")
    sh.set_defaults(func=cmd_shot)

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
