"""round-161 回归：更新下载 + PowerShell 自替换助手（纯逻辑，无 Qt）。

不执行 PowerShell：只校验脚本内容 / 引号转义 / 待展示更新说明。
下载走 ``file://`` 并以 ``allow_insecure=True`` 放行（生产路径仅 https）。
"""
import hashlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src.core import update_install as ui, update_trust as ut  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "FAIL", label, extra))
    if not cond:
        fails.append(label)


def _raises(code, fn):
    try:
        fn()
        return False
    except ut.TrustError as exc:
        return exc.code == code


def _file_url(path):
    return "file:///" + path.replace("\\", "/").lstrip("/")


def _manifest(content, url, *, version="1.2.0", size=None, sha=None, notes=()):
    return ut.UpdateManifest(
        version=version,
        notes=tuple(notes),
        asset_name="AC_Launcher_%s.zip" % version,
        asset_url=url,
        sha256=sha or hashlib.sha256(content).hexdigest(),
        size=len(content) if size is None else size,
        key_id="test-key",
        terms_version=2,
    )


content = b"PK\x03\x04 fake launcher zip payload"
NOTES = ("新增更新器", "修复下载卡住")

with tempfile.TemporaryDirectory(prefix="ac_upd_") as td:
    data = os.path.join(td, "data")
    src = os.path.join(td, "AC_Launcher_1.2.0.zip")
    with open(src, "wb") as f:
        f.write(content)
    url = _file_url(src)
    m = _manifest(content, url, notes=NOTES)

    # 让默认目录 / 待展示说明都落在临时目录
    ui.get_data_dir = lambda: data

    # ── 1. 下载成功 ──
    progress = []
    final = ui.download_update(m, allow_insecure=True,
                               progress=lambda rcv, total: progress.append((rcv, total)))
    check("下载落盘", os.path.isfile(final), final)
    check("默认目录为 data/updates/<version>",
          os.path.dirname(final) == os.path.join(data, "updates", "1.2.0"))
    with open(final, "rb") as f:
        check("字节与源一致", f.read() == content)
    check("无 .part 残留", not os.path.exists(final + ".part"))
    check("进度回报到最后", progress and progress[-1] == (len(content), len(content)))
    check("进度单调递增", [p[0] for p in progress] == sorted(p[0] for p in progress))

    # ── 2. 已校验缓存直接复用 ──
    with open(src, "wb") as f:
        f.write(b"changed on server")
    seen = []
    again = ui.download_update(m, allow_insecure=True,
                               progress=lambda rcv, total: seen.append((rcv, total)))
    check("缓存命中返回同一路径", again == final)
    check("缓存命中不重新下载", seen == [(len(content), len(content))], str(seen))
    with open(again, "rb") as f:
        check("缓存内容未被源变更覆盖", f.read() == content)

    # ── 3. 本地缓存损坏 → 重新下载 ──
    with open(src, "wb") as f:
        f.write(content)
    with open(final, "wb") as f:
        f.write(b"corrupted")
    fixed = ui.download_update(m, allow_insecure=True)
    with open(fixed, "rb") as f:
        check("损坏缓存被重下替换", f.read() == content)

    # ── 4. 大小 / 哈希不符 → 清理且不留成品 ──
    bad_size_dir = os.path.join(td, "dl_size")
    mgr = _manifest(content, url, size=len(content) + 3)
    check("大小不符 → asset_size",
          _raises("asset_size", lambda: ui.download_update(
              mgr, dest_dir=bad_size_dir, allow_insecure=True)))
    check("失败不留下 zip / part",
          not os.path.exists(os.path.join(bad_size_dir, mgr.asset_name))
          and not os.path.exists(os.path.join(bad_size_dir, mgr.asset_name + ".part")))

    bad_hash_dir = os.path.join(td, "dl_hash")
    mgh = _manifest(content, url, sha="0" * 64)
    check("哈希不符 → asset_hash",
          _raises("asset_hash", lambda: ui.download_update(
              mgh, dest_dir=bad_hash_dir, allow_insecure=True)))
    check("哈希失败不留 part",
          not os.path.exists(os.path.join(bad_hash_dir, mgh.asset_name + ".part")))

    # ── 5. 非 https 默认拒绝 ──
    check("http/file 未放行 → manifest_https",
          _raises("manifest_https", lambda: ui.download_update(
              m, dest_dir=os.path.join(td, "dl_https"))))

    # ── 6. 取消 ──
    cancel_dir = os.path.join(td, "dl_cancel")
    try:
        ui.download_update(m, dest_dir=cancel_dir, allow_insecure=True,
                           cancel=lambda: True)
        cancelled = False
    except ui.UpdateCancelled:
        cancelled = True
    check("取消抛出 UpdateCancelled", cancelled)
    check("取消后无残留",
          not os.path.exists(os.path.join(cancel_dir, m.asset_name + ".part")))

    # ── 7. 自替换脚本 ──
    app = os.path.join(td, "App Dir's")
    os.makedirs(app)
    with open(os.path.join(app, "AC_Launcher.exe"), "wb") as f:
        f.write(b"old exe")

    # 下载到独立目录，避免使用上面的缓存路径
    asset = ui.download_update(m, dest_dir=os.path.join(td, "dl_script"),
                               allow_insecure=True)
    script = ui.write_upgrade_script(
        m, asset, app_dir=app, pid=4242, exe_name="AC_Launcher.exe", data_dir=data)
    check("脚本落盘", os.path.isfile(script), script)
    check("脚本命名含版本", os.path.basename(script).endswith("upgrade_1.2.0.ps1"),
          os.path.basename(script))
    with open(script, encoding="utf-8-sig") as f:
        body = f.read()
    check("带 BOM 可被 PowerShell 正确读中文", body.lstrip("\ufeff").startswith("$ErrorActionPreference"))
    check("单引号已双写转义", "App Dir''s" in body)
    check("等待主进程 PID", "$LauncherPid = 4242" in body)
    check("替换前改名备份", "Rename-Item" in body and ".upd_bak" in body)
    check("解压覆盖", "Expand-Archive" in body)
    check("成功后重启并指定工作目录",
          "Start-Process -FilePath $exePath -WorkingDirectory $AppDir" in body)
    check("失败回滚并重启旧版", "ROLLBACK FAILED" in body)
    check("回滚时清除待展示更新说明", "Remove-Item -Force $Notes" in body)
    # PowerShell 语法解析（不执行）：确认生成的脚本本身可被解析。
    if sys.platform == "win32":
        import shutil
        import subprocess
        ps = shutil.which("powershell.exe") or shutil.which("powershell")
        if ps:
            env = dict(os.environ, AC_PS1=script)
            code = ("$e=$null; [void][System.Management.Automation.Language.Parser]"
                    "::ParseFile($env:AC_PS1,[ref]$null,[ref]$e);"
                    "if($e.Count){ $e[0].Message | Write-Output; exit 1 }")
            p = subprocess.run(
                [ps, "-NoProfile", "-NonInteractive", "-Command", code],
                capture_output=True, text=True, timeout=30, env=env)
            check("PowerShell 语法解析通过", p.returncode == 0,
                  ((p.stdout or "") + (p.stderr or "")).strip()[:60])

    # ── 8. 待展示更新说明 ──
    notes = ui.read_pending_notes(data)
    check("pending notes 已写入", isinstance(notes, dict), str(notes))
    check("版本与备注正确",
          notes and notes.get("version") == "1.2.0"
          and notes.get("notes") == list(NOTES))
    check("terms_version 透传", notes and notes.get("terms_version") == 2)
    ui.clear_pending_notes(data)
    check("清理后读取为 None", ui.read_pending_notes(data) is None)

    # ── 9. 开发版 / 缺资产拒绝 ──
    if not getattr(sys, "frozen", False):
        check("非打包版拒绝自动替换 → upgrade_dev_build",
              _raises("upgrade_dev_build", lambda: ui.write_upgrade_script(m, asset)))
    check("资产缺失 → asset_missing",
          _raises("asset_missing", lambda: ui.write_upgrade_script(
              m, os.path.join(td, "missing.zip"), app_dir=app, data_dir=data)))

    # ── 10. PowerShell 字面量转义 ──
    check("_ps 双写单引号", ui._ps("a'b") == "'a''b'")

print()
if fails:
    print("FAILED: %d 项 → %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL CHECKS PASSED")
