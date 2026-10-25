"""JS 扩展宿主 — QWebEngine HTML/JS 插件，选装组件。

扩展 = <data>/extensions/<id>/ 目录 + manifest.json：

    {
      "id": "sample-clock",
      "name": "示例：时钟",
      "name_en": "Sample Clock",
      "version": "1.0.0",
      "author": "AC",
      "entry": "index.html",
      "permissions": ["read_only_instance"]
    }

能力声明式沙箱：manifest 声明 permissions，安装时弹窗逐项授权（enabled 项
写入 config ext_grants），运行时宿主侧对每次调用校验授权——页面拿到的
window.AC.* 只是转发层，真正执行与把关都在 Python 这端。

QtWebEngine 是选装组件：import 失败时 webengine_available() 返回 False，
设置页扩展区显示提示并禁用，主程序体积与启动不受拖累。

桥接实现（不依赖 qwebchannel.js，PySide6 未捆绑该文件）：
往页面注入客户端脚本，暴露 window.AC.invoke() → Promise；调用被推入页面
队列 __acQ；宿主用 QTimer 轮询（page.runJavaScript）取出请求，校验权限后
分发执行，再把结果经 __acDeliver(id, json) 投回页面。粒度虽在 300ms 级，
对插件 API 足够，且权限把关全部在宿主侧。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Optional

# ── QtWebEngine 选装检测（不 import 失败拖垮主程序）──────────────────────
_WEBENGINE_IMPORT_ERROR = ""
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    from PySide6.QtWebEngineCore import (
        QWebEngineScript,
        QWebEngineProfile,
    )
except Exception as e:  # noqa: BLE001
    QWebEngineView = None
    _WEBENGINE_IMPORT_ERROR = str(e)
    QWebEngineScript = QWebEngineProfile = None

from PySide6.QtCore import (
    QUrl, QTimer, QEventLoop, QProcess,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QMainWindow, QCheckBox, QDialog,
    QLabel, QPushButton,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

from .paths import get_data_dir, get_resource_path
from .i18n import t, get_language
from .icons import icon


def webengine_available() -> bool:
    return QWebEngineView is not None


def webengine_unavailable_reason() -> str:
    return _WEBENGINE_IMPORT_ERROR


# ── 权限清单（键 → i18n 键）──────────────────────────────────────────────
PERMISSIONS: dict[str, str] = {
    "read_only_instance": "ext.perm_read_only_instance",   # 读取实例信息（只读）
    "change_args":        "ext.perm_change_args",          # 修改启动参数
    "exec_command":       "ext.perm_exec_command",         # 执行外部命令
    "network":            "ext.perm_network",              # 发起网络请求
}


# ── 目录 / 扫描 ───────────────────────────────────────────────────────────
def get_extensions_dir() -> str:
    d = os.path.join(get_data_dir(), "extensions")
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class ExtensionInfo:
    id: str
    folder: str
    manifest: dict
    name: str = ""
    name_en: str = ""
    version: str = ""
    author: str = ""
    entry: str = "index.html"
    permissions: list = None


def _parse_manifest(m: dict, folder_name: str) -> ExtensionInfo:
    if not isinstance(m, dict):
        raise ValueError("扩展清单格式无效（应为 JSON 对象）")
    eid = str(m.get("id", "")).strip()
    if not eid or not eid.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"扩展 id 非法：{eid!r}")
    if folder_name and folder_name != eid:
        raise ValueError(f"目录名（{folder_name}）与 id（{eid}）不一致")
    if not m.get("name"):
        raise ValueError("扩展清单缺少 name")
    perms = list(m.get("permissions", []) or [])
    unknown = [p for p in perms if p not in PERMISSIONS]
    if unknown:
        raise ValueError(f"未声明的权限：{', '.join(map(str, unknown))}")
    return ExtensionInfo(
        id=eid, folder="", manifest=m,
        name=str(m.get("name", eid)),
        name_en=str(m.get("name_en", "") or m.get("name", eid)),
        version=str(m.get("version", "")),
        author=str(m.get("author", "")),
        entry=str(m.get("entry", "index.html")),
        permissions=perms,
    )


def scan_extensions() -> list[ExtensionInfo]:
    out: list[ExtensionInfo] = []
    d = get_extensions_dir()
    try:
        names = sorted(os.listdir(d))
    except OSError:
        names = []
    for name in names:
        folder = os.path.join(d, name)
        mpath = os.path.join(folder, "manifest.json")
        if not os.path.isfile(mpath):
            continue
        try:
            with open(mpath, "r", encoding="utf-8") as f:
                m = json.load(f)
            info = _parse_manifest(m, folder_name=name)
            info.folder = folder
            out.append(info)
        except Exception:
            continue
    return out


def bundled_extensions() -> list[ExtensionInfo]:
    """assets/extensions/ 下随包分发的示例扩展（仅展示，未安装）。"""
    out: list[ExtensionInfo] = []
    root = os.path.join(get_resource_path("assets/extensions"))
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        mpath = os.path.join(root, name, "manifest.json")
        if not os.path.isfile(mpath):
            continue
        try:
            with open(mpath, "r", encoding="utf-8") as f:
                m = json.load(f)
            info = _parse_manifest(m, folder_name=name)
            info.folder = os.path.join(root, name)
            out.append(info)
        except Exception:
            continue
    return out


# ── 安装 / 卸载 ───────────────────────────────────────────────────────────
def install_extension_folder(src: str) -> ExtensionInfo:
    src = os.path.abspath(src)
    with open(os.path.join(src, "manifest.json"), "r", encoding="utf-8") as f:
        m = json.load(f)
    info = _parse_manifest(m, folder_name=os.path.basename(src))
    dest = os.path.join(get_extensions_dir(), info.id)
    if os.path.exists(dest):
        raise ValueError(f"已安装扩展 id 冲突：{info.id}")
    os.makedirs(dest, exist_ok=True)
    try:
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dest, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError("扩展复制失败")
    return install_extension_by_id(info.id)


def install_extension_zip(zip_path: str) -> ExtensionInfo:
    tmp = tempfile.mkdtemp(prefix="ac_ext_")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)
        root = tmp
        if not os.path.isfile(os.path.join(root, "manifest.json")):
            subs = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
            if len(subs) == 1:
                root = os.path.join(root, subs[0])
            else:
                raise ValueError("压缩包内找不到 manifest.json")
        info = install_extension_folder(root)
        for name in ("__MACOSX", ".git", ".svn"):
            p = os.path.join(get_extensions_dir(), info.id, name)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
        return info
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install_extension_bundle(bundle: ExtensionInfo) -> ExtensionInfo:
    """安装随包分发的示例扩展（复制 assets/extensions/<id>）。"""
    info = install_extension_folder(bundle.folder)
    grant_defaults(info.id)
    return info


def install_extension_by_id(eid: str) -> ExtensionInfo:
    """扫描后按 id 找已安装扩展（含 folder/perms 就绪）。"""
    for e in scan_extensions():
        if e.id == eid:
            return e
    raise ValueError(f"未找到扩展：{eid}")


def clear_ext_arg_jobs(eid: str) -> None:
    """清掉某个扩展写入的全部 changeArgs 启动参数任务。

    round-92 安全审查修复：`ext_launch_arg_jobs` 是**全局配置**，卸载扩展时
    原先只删目录和授权，没清这里——导致扩展卸载后它注入的 JVM 参数
    **永久残留并持续影响每一次启动**，而玩家在 UI 里已找不到来源，无法撤销。
    """
    try:
        cfg = _cfg()
        jobs = list(cfg.get("ext_launch_arg_jobs") or [])
        kept = [j for j in jobs if str((j or {}).get("ext") or "") != eid]
        if len(kept) != len(jobs):
            cfg["ext_launch_arg_jobs"] = kept
            _save(cfg)
    except Exception:  # noqa: BLE001 - 清理失败不阻塞卸载主流程
        pass


def uninstall_extension(eid: str) -> None:
    for e in scan_extensions():
        if e.id == eid:
            shutil.rmtree(e.folder, ignore_errors=True)
            break
    _set_grants(eid, None)
    # round-92 修复：连同它注入的启动参数任务一起清理，避免残留副作用
    clear_ext_arg_jobs(eid)


def display_name(info: ExtensionInfo) -> str:
    return info.name_en if get_language().startswith("en") else info.name


# ── 授权（config ext_grants: {ext_id: {perm: bool}}）──────────────────────
def _cfg() -> dict:
    from .settings_dialog import load_config
    return load_config()


def _save(cfg: dict) -> None:
    from .settings_dialog import save_config
    save_config(cfg)


def grants_for(eid: str) -> dict:
    return dict((_cfg().get("ext_grants") or {}).get(eid) or {})


def is_granted(eid: str, perm: str) -> bool:
    return bool(grants_for(eid).get(perm))


def set_grant(eid: str, perm: str, on: bool) -> None:
    c = _cfg()
    gr = dict(c.get("ext_grants") or {})
    per = dict(gr.get(eid) or {})
    per[perm] = bool(on)
    gr[eid] = per
    c["ext_grants"] = gr
    _save(c)


def _set_grants(eid: str, grants: Optional[dict]) -> None:
    c = _cfg()
    gr = dict(c.get("ext_grants") or {})
    if grants is None:
        gr.pop(eid, None)
    else:
        gr[eid] = grants
    c["ext_grants"] = gr
    _save(c)


def grant_defaults(eid: str) -> dict:
    """未记录过授权的扩展：默认全拒（严格）；返回当前授权表。"""
    if not grants_for(eid):
        _set_grants(eid, {perm: False for perm in PERMISSIONS})
    return grants_for(eid)


# ── 逐项授权弹窗 ──────────────────────────────────────────────────────────
def grant_dialog(info: ExtensionInfo, parent=None) -> Optional[dict]:
    """安装/启用时逐项授权。返回 {perm: bool}；取消返回 None。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(t("ext.grant_dialog_title"))
    dlg.setMinimumWidth(460)
    dlg.setModal(True)
    root = QVBoxLayout(dlg)
    root.setContentsMargins(20, 18, 20, 18)
    root.setSpacing(10)

    title = QLabel(t("ext.grant_body", name=display_name(info)))
    title.setWordWrap(True)
    title.setStyleSheet("font-size: 14px; font-weight: 700;")
    root.addWidget(title)

    if not info.permissions:
        note = QLabel(t("ext.grant_none"))
        note.setStyleSheet("color: #6B7280; font-size: 12px;")
        root.addWidget(note)
    boxes: dict[str, QCheckBox] = {}
    for perm in info.permissions:
        cb = QCheckBox(t(PERMISSIONS.get(perm, perm)))
        cb.setChecked(True)   # 安装时默认勾选要用的；之后可在授权里手动关
        boxes[perm] = cb
        root.addWidget(cb)

    root.addStretch(1)
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton(t("common.cancel"))
    cancel.setMinimumHeight(32)
    ok = QPushButton(t("ext.grant_install"))
    ok.setProperty("cls", "accent")
    ok.setMinimumHeight(32)
    row.addWidget(cancel)
    row.addWidget(ok)
    root.addLayout(row)

    cancel.clicked.connect(dlg.reject)
    ok.clicked.connect(dlg.accept)
    if dlg.exec() != QDialog.Accepted:
        return None
    return {perm: cb.isChecked() for perm, cb in boxes.items()}


# ── 客户端注入脚本（页面端 window.AC 转发层）──────────────────────────────
_CLIENT_JS = r"""
(function () {
  if (window.__acHostReady) return;
  window.__acHostReady = true;
  var seq = 0, pend = {};
  window.__acQ = window.__acQ || [];
  window.__acDeliver = function (id, jsonStr) {
    var h = pend[id];
    if (!h) return;
    delete pend[id];
    var data = JSON.parse(jsonStr);
    if (data && data.__error) { h.reject(new Error(data.__error)); }
    else { h.resolve(data); }
  };
  function invoke(method) {
    var args = Array.prototype.slice.call(arguments, 1);
    var id = ++seq;
    var p = new Promise(function (resolve, reject) { pend[id] = { resolve: resolve, reject: reject }; });
    window.__acQ.push(JSON.stringify({ id: id, m: method, a: args }));
    return p;
  }
  window.AC = {
    version: "1.0.0",
    invoke: invoke,
    listInstances: function () { return invoke("listInstances"); },
    readInstanceFile: function (instId, rel) { return invoke("readInstanceFile", instId, rel); },
    execCommand: function (cmd) { return invoke("execCommand", cmd); },
    changeArgs: function (argsText) { return invoke("changeArgs", argsText); },
    httpGet: function (url) { return invoke("httpGet", url); }
  };
})();
"""

_injected = False


def _ensure_client_injected() -> None:
    """往默认 profile 注入宿主客户端脚本（DocumentCreation，先于扩展脚本）。"""
    global _injected
    if _injected or not webengine_available():
        return
    script = QWebEngineScript()
    script.setName("ac-host-client")
    script.setSourceCode(_CLIENT_JS)
    script.setInjectionPoint(QWebEngineScript.DocumentCreation)
    script.setWorldId(QWebEngineScript.MainWorld)
    script.setRunsOnSubFrames(False)
    coll = QWebEngineProfile.defaultProfile().scripts()
    for i in range(coll.count()):
        try:
            if coll.at(i).name() == "ac-host-client":
                _injected = True
                return
        except Exception:
            continue
    coll.insert(script)
    _injected = True


# ── 宿主侧桥（权限校验 + 分发）───────────────────────────────────────────
class BridgeCore:
    """每次调用都先查授权，再执行；结果一律 JSON 可序列化。

    越权/失败统一返回 {"__error": 说明}，页面 Promise reject。
    """

    PERM_FOR = {
        "listInstances":   "read_only_instance",
        "readInstanceFile": "read_only_instance",
        "execCommand":     "exec_command",
        "changeArgs":      "change_args",
        "httpGet":         "network",
    }

    def __init__(self, ext_id: str):
        self.ext_id = ext_id
        grants = grants_for(ext_id)
        self._granted = grants if grants else grant_defaults(ext_id) or {}

    def granted(self, perm: str) -> bool:
        return bool(self._granted.get(perm))

    def dispatch(self, method: str, args: list):
        perm = self.PERM_FOR.get(method)
        if not perm:
            return {"__error": f"未知方法：{method}"}
        if not self.granted(perm):
            return {"__error": f"权限未授权：{perm}"}
        try:
            return self._call(method, args or [])
        except Exception as e:  # noqa: BLE001
            return {"__error": f"{type(e).__name__}: {e}"}

    # ── 方法实现 ─────────────────────────────────────────────────────
    def _call(self, method: str, args: list):
        if method == "listInstances":
            return self._list_instances()
        if method == "readInstanceFile":
            return self._read_instance_file(args)
        if method == "execCommand":
            return self._exec_command(args)
        if method == "changeArgs":
            return self._change_args(args)
        if method == "httpGet":
            return self._http_get(args)
        return {"__error": f"未实现：{method}"}

    def _list_instances(self) -> list:
        try:
            from .instances import manager
        except Exception:
            return []
        out = []
        for inst in manager().list():
            out.append({
                "id": getattr(inst, "id", ""),
                "name": getattr(inst, "name", ""),
                "version": getattr(inst, "game_version", ""),
                "dir": getattr(inst, "game_dir", ""),
            })
        return out

    def _read_instance_file(self, args: list):
        if len(args) < 2:
            return {"__error": "参数不足：readInstanceFile(instanceId, relPath)"}
        id_, rel = str(args[0]), str(args[1])
        try:
            from .instances import manager
            inst = None
            for i in manager().list():
                if getattr(i, "id", "") == id_:
                    inst = i
                    break
            if inst is None:
                return {"__error": f"实例不存在：{id_}"}
            base = os.path.realpath(getattr(inst, "game_dir", ""))
            target = os.path.realpath(os.path.join(base, rel))
            if os.path.commonpath([base, target]) != base:
                return {"__error": "路径越界（只能在实例目录内读取）"}
            size = os.path.getsize(target)
            if size > 1024 * 1024:
                return {"__error": "文件超过 1MB，拒绝读取"}
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except FileNotFoundError:
            return {"__error": "文件不存在"}
        except OSError as e:
            return {"__error": f"读取失败：{e}"}

    def _exec_command(self, args: list):
        if not args or not str(args[0]).strip():
            return {"__error": "参数不足：execCommand(cmdLine)"}
        cmd = str(args[0])
        proc = QProcess()
        proc.start("cmd.exe", ["/C", cmd])
        if not proc.waitForStarted(5000):
            return {"__error": "命令启动失败"}
        proc.waitForFinished(15000)
        out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
        return {"code": proc.exitCode(), "stdout": out, "stderr": err}

    def _change_args(self, args: list):
        if not args or not str(args[0]).strip():
            return {"__error": "参数不足：changeArgs(argsText)"}
        c = _cfg()
        jobs = list(c.get("ext_launch_arg_jobs") or [])
        # round-92 修复：按 ext 归属**替换**而非盲目 append——原来每次调用都追加
        # 一条，同一扩展反复 changeArgs 会让 jobs 无限膨胀。
        jobs = [j for j in jobs if str((j or {}).get("ext") or "") != self.ext_id]
        jobs.append({"ext": self.ext_id, "args": str(args[0])})
        c["ext_launch_arg_jobs"] = jobs
        _save(c)
        return {"ok": True, "jobs": len(jobs)}

    def _http_get(self, args: list):
        if not args or not str(args[0]).strip():
            return {"__error": "参数不足：httpGet(url)"}
        url = str(args[0])
        if not url.startswith(("http://", "https://")):
            return {"__error": "仅允许 http/https"}
        mgr = QNetworkAccessManager()
        req = QNetworkRequest(QUrl(url))
        req.setTransferTimeout(12000)
        reply = mgr.get(req)
        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        QTimer.singleShot(15000, loop.quit)   # 超时兜底
        loop.exec()
        if reply.error() != reply.NetworkError.NoError:
            err = reply.errorString()
            reply.deleteLater()
            return {"__error": f"网络错误：{err}"}
        body = bytes(reply.readAll()).decode("utf-8", "replace")
        status = reply.attribute(reply.HttpStatusCodeAttribute)
        mime = reply.header(reply.ContentTypeHeader)
        reply.deleteLater()
        return {"status": int(status) if status else 0, "mime": str(mime), "body": body}


# ── 扩展窗口 ──────────────────────────────────────────────────────────────
class ExtensionWindow(QMainWindow):
    """承载一个扩展页面的独立圆角窗口（框架复用 TitleBar）。"""

    WINDOW_W, WINDOW_H = 760, 540

    def __init__(self, info: ExtensionInfo, parent=None):
        super().__init__(parent)
        self.info = info
        self._bridge = BridgeCore(info.id)
        self.setWindowTitle(display_name(info))
        self.resize(self.WINDOW_W, self.WINDOW_H)
        self.setMinimumSize(560, 420)

        from .frameless import FramelessHelper, TitleBar
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self, title=display_name(info), height=38)
        root.addWidget(self.titlebar)
        self._frameless = FramelessHelper(self)
        self._frameless.set_titlebar(self.titlebar)
        from .win_rounded import enable_win11_round_corners
        enable_win11_round_corners(self)

        head = QHBoxLayout()
        head.setContentsMargins(16, 10, 16, 6)
        name_lbl = QLabel(display_name(info))
        name_lbl.setStyleSheet("font-size: 14px; font-weight: 700;")
        head.addWidget(name_lbl)
        v_lbl = QLabel(f"v{info.version}")
        v_lbl.setStyleSheet("color: #6B7280; font-size: 11px;")
        head.addWidget(v_lbl)
        granted = [k for k in info.permissions if self._bridge.granted(k)]
        if granted:
            perm_lbl = QLabel(" · ".join(t(PERMISSIONS.get(p, p)) for p in granted))
        else:
            perm_lbl = QLabel(t("ext.grant_none"))
        perm_lbl.setStyleSheet("color: #6B7280; font-size: 11px;")
        head.addWidget(perm_lbl)
        head.addStretch(1)
        reload_btn = QPushButton(icon("refresh"), t("ext.reload"))
        reload_btn.setMinimumHeight(30)
        reload_btn.clicked.connect(self.reload)
        head.addWidget(reload_btn)
        root.addLayout(head)

        self.view = QWebEngineView()
        self.page = self.view.page()
        root.addWidget(self.view, stretch=1)

        _ensure_client_injected()
        entry = os.path.join(info.folder, info.entry)
        if not os.path.isfile(entry):
            entry = os.path.join(info.folder, "index.html")
        self.view.setUrl(QUrl.fromLocalFile(entry))

        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll_queue)
        self._timer.start()

    def reload(self):
        self.view.reload()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)

    def _poll_queue(self):
        if not self.page:
            return
        js = ("JSON.stringify("
              "window.__acQ && window.__acQ.length ? window.__acQ.shift() : null)")
        self.page.runJavaScript(js, self._on_request)

    def _on_request(self, raw):
        if not raw or raw == "null":
            return
        try:
            req = json.loads(raw)
            result = self._bridge.dispatch(str(req.get("m", "")), req.get("a") or [])
        except Exception as e:  # noqa: BLE001
            result = {"__error": f"宿主处理失败：{e}"}
        payload = json.dumps(result)
        code = f"window.__acDeliver({req['id']}, {json.dumps(payload)})"
        self.page.runJavaScript(code)