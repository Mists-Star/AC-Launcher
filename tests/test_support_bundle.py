"""round-158 回归测试：诊断包导出（脱敏 / 内容 / 截断 / 原子写）。

纯逻辑，无 Qt。用临时数据目录构造配置与日志，导出 zip 后检查：
1. 敏感配置键被替换为 <redacted>，用户名与 accessToken 不出现在归档里；
2. 归档包含 summary/config/diagnostics + 两类日志（data/*.log 与 data/logs/*.log）；
3. 超过 256KB 的日志只保留尾部；
4. 缺失数据目录 / 空结果仍能导出；失败不留 .tmp。
"""
import json
import os
import re
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import support_bundle as sb  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def _username() -> str:
    try:
        u = os.path.basename(os.path.normpath(os.path.expanduser("~")))
    except Exception:  # noqa: BLE001
        return ""
    return u if len(u) >= 2 else ""


class _Result:
    def __init__(self, rid, status, detail=""):
        self.id = rid
        self.status = status
        self.detail = detail


TOKEN = "abcdefghijklmnopqrstuvwxyz012345"   # 32 chars, shape of a real token
USER = _username()

# ── 1. redact_config ──
cfg = {
    "ram_mb": 4096,
    "dev_mode_key": "super-secret-dev-key",
    "curseforge_api_key": "cf-secret-key",
    "java_path": f"C:\\Users\\{USER}\\java\\bin\\javaw.exe" if USER else "",
    "bgm_files": [f"C:\\Users\\{USER}\\music\\a.mp3"] if USER else [],
    "nested": {"dev_mode_key": "nested-secret"},
}
red = sb.redact_config(cfg)
check("dev_mode_key 打码", red["dev_mode_key"] == sb._REDACTED, str(red["dev_mode_key"]))
check("curseforge_api_key 打码", red["curseforge_api_key"] == sb._REDACTED)
check("嵌套敏感键同样打码", red["nested"]["dev_mode_key"] == sb._REDACTED)
check("普通值保持", red["ram_mb"] == 4096)
check("列表内字符串也被处理", isinstance(red["bgm_files"], list))
if USER:
    check("配置内用户名被打码",
          USER not in json.dumps(red, ensure_ascii=False))

# ── 2. 归档内容 + 脱敏 ──
with tempfile.TemporaryDirectory(prefix="ac_sb_") as td:
    data = os.path.join(td, "data")
    os.makedirs(os.path.join(data, "logs"))
    with open(os.path.join(data, "logs", "download.log"), "w", encoding="utf-8") as f:
        f.write("GET https://example.invalid/x accessToken " + TOKEN + "\n")
        if USER:
            f.write("user dir C:\\Users\\" + USER + "\\work\n")
    game_log = os.path.join(data, "1-20-1.log")
    with open(game_log, "w", encoding="utf-8") as f:
        f.write("game log accessToken " + TOKEN + "\n")
    # 非日志文件不应进入归档
    with open(os.path.join(data, "accounts.json"), "w", encoding="utf-8") as f:
        f.write('{"accessToken": "' + TOKEN + '"}')

    dest = os.path.join(td, "AC_support_test.zip")
    results = [
        _Result("deps", "ok", "all imports fine"),
        _Result("datadir", "error", "not writable"),
        _Result("java", "skip", ""),
        _Result("inst", "warn", "missing libraries"),
    ]
    saved = sb.build_support_bundle(dest, results, config=cfg, data_dir=data)
    check("返回目标路径", saved == dest)
    check("目标存在", os.path.isfile(dest))
    check("无 .tmp 残留", not os.path.exists(dest + ".tmp"))

    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        check("含 summary.txt", "summary.txt" in names)
        check("含 config.json", "config.json" in names)
        check("含 diagnostics.txt", "diagnostics.txt" in names)
        check("含 data/logs 日志", "logs/logs/download.log" in names)
        check("含 data 根日志", "logs/1-20-1.log" in names)
        check("非 .log 文件不打包", "logs/accounts.json" not in names)

        blob = "\n".join(zf.read(n).decode("utf-8", errors="replace") for n in names)
        check("敏感 dev key 未泄漏", "super-secret-dev-key" not in blob)
        check("敏感 CF key 未泄漏", "cf-secret-key" not in blob)
        check("原始 token 未泄漏", TOKEN not in blob)
        check("token 已按首尾 5 位打码",
              TOKEN[:5] in blob and TOKEN[-5:] in blob and "*" in blob)
        if USER:
            check("归档内无用户名", USER not in blob)

        summary = zf.read("summary.txt").decode("utf-8")
        check("summary 计数正确", "1 ok / 1 warn / 1 error / 1 skip" in summary,
              summary.splitlines()[-5] if summary else "")
        diag_txt = zf.read("diagnostics.txt").decode("utf-8")
        check("诊断逐条列出", "[error] datadir" in diag_txt)

# ── 3. 大日志截断 ──
with tempfile.TemporaryDirectory(prefix="ac_sb_") as td:
    data = os.path.join(td, "data")
    os.makedirs(os.path.join(data, "logs"))
    big = os.path.join(data, "logs", "big.log")
    with open(big, "w", encoding="utf-8") as f:
        f.write("HEAD\n" + ("x" * (600 * 1024)) + "\nTAIL")
    dest = os.path.join(td, "b.zip")
    sb.build_support_bundle(dest, [], config={}, data_dir=data)
    with zipfile.ZipFile(dest) as zf:
        body = zf.read("logs/logs/big.log").decode("utf-8")
        check("截断标记存在", "truncated" in body.lower())
        check("只保留尾部（<300KB）", len(body.encode("utf-8")) < 300 * 1024,
              str(len(body.encode('utf-8'))))
        check("尾部内容保留", body.rstrip().endswith("TAIL"))
        check("头部内容被丢弃", "HEAD" not in body)

# ── 4. 缺目录 / 空结果 ──
with tempfile.TemporaryDirectory(prefix="ac_sb_") as td:
    dest = os.path.join(td, "sub", "empty.zip")
    sb.build_support_bundle(dest, None, config={},
                            data_dir=os.path.join(td, "does-not-exist"))
    check("缺失数据目录仍可导出", os.path.isfile(dest))
    with zipfile.ZipFile(dest) as zf:
        check("空结果有占位文案",
              "no diagnostics" in zf.read("diagnostics.txt").decode("utf-8"))

# ── 5. 默认文件名 ──
name = sb.default_bundle_name()
check("默认文件名格式", bool(re.match(r"^AC_support_\d{8}_\d{6}\.zip$", name)), name)

print()
if fails:
    print("FAILED: %d 项 → %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL CHECKS PASSED")
