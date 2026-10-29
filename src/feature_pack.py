"""扩展组件（Chromium 运行时）按需下载与安装 —— round-139 B2。

组件包由 ``build.py --components`` 产出（见 docs/round139_component_download）::

    ac_webengine_runtime_<ver>.zip            # 根部含 component.manifest.json
    ac_webengine_runtime_<ver>.zip.sha256     # sha256sum 格式（最终 zip 的哈希）
    ac_webengine_runtime_<ver>.manifest.json  # 与 zip 内同内容（人读/发布校验）

状态机 :func:`state`::

    absent      未安装 / 版本绑定不匹配（state.reason 细分）/ 应有文件缺失
    downloading 本会话正在下载（进度见 :func:`progress`）
    installed   state.json 校验通过；或「手动合并」——无 state 记录但
                关键文件在位（开发环境 / 用户自己解压组件包进来）

安装流程 ``install()``：
解压到 ``<发行根>/_tmp_pack``（与目标同卷）→ 逐文件 sha256 校验（manifest
在 zip 内，读它不落地）→ 移动到 ``_internal/…`` → 写 state。任一步失败
回滚（删已移动文件 + 临时目录），**不留半套文件**（验收 B3）。

版本绑定（验收 B5）：state 里的 ``component_version``/``launcher_version`` 与
当前不一致 → 视为 absent（强制重装/重下），防启动器升级后组件错位。

下载源顺序（:func:`_sources`）：
``AC_PACK_SRC`` 环境变量（``|`` 分隔，本地路径或 URL）
→ ``launcher_config.json`` 的 ``component_src`` → :data:`DEFAULT_URLS`
→ 本地旁置 zip（exe 旁 / ``data/incoming/``）。

安装/卸载只动 manifest 清单内的文件，**绝不碰插件目录**，也不碰
``<data>/extensions/``（插件用户数据，验收 B4）。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import zipfile
from datetime import datetime

from .brand import APP_VERSION
from .i18n import t
from .paths import get_config_path, get_data_dir

COMPONENT = "webengine"
# 组件与启动器同版发布（build.py 的 manifest 同规则）：任一不匹配即需重装。
COMPONENT_VERSION = APP_VERSION
ZIP_NAME = f"ac_webengine_runtime_{APP_VERSION}.zip"
MANIFEST_MEMBER = "component.manifest.json"
_TMP_DIR = "_tmp_pack"

# release 时填组件 zip 的直链（GitHub release + gh-proxy 镜像多源，对齐
# core/easytier 的容灾写法）。为空时靠本地源/旁置 zip（见 _sources）。
DEFAULT_URLS: list[str] = []

# 下载进度（B3 UI 轮询）：active 期间 state() 返回 downloading。
_dl = {"active": False, "sofar": 0, "total": 0}


class ComponentError(Exception):
    """组件下载/安装失败（消息面向用户，可直接展示）。"""


# ---------------------------------------------------------------- 路径与状态

def _root() -> str:
    """发行根 = zip 内 ``_internal/…`` 相对的基准目录。

    frozen：exe 所在目录；dev：项目根（测试可 monkeypatch 本函数）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(".")


def _state_path() -> str:
    return os.path.join(get_data_dir(), "component_state.json")


def _read_state() -> dict | None:
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_state(st: dict) -> None:
    os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _markers_present() -> bool:
    """关键件在位判定（「手动合并」/ 开发环境无 state 记录时用）。"""
    ps = os.path.join(_root(), "_internal", "PySide6")
    return (os.path.isfile(os.path.join(ps, "Qt6WebEngineCore.dll"))
            and os.path.isfile(os.path.join(ps, "QtWebEngineProcess.exe")))


def state() -> dict:
    """当前组件状态 → ``{"status": "absent|downloading|installed", ...}``。

    ``downloading`` 只在本会话下载期间成立；``absent`` 带 ``reason``：
    ``version-mismatch``（B5 版本绑定）/ ``files-missing`` / ``no-state``。
    """
    if _dl["active"]:
        return {"status": "downloading", "sofar": _dl["sofar"],
                "total": _dl["total"]}
    st = _read_state()
    if st:
        if (st.get("component_version") != COMPONENT_VERSION
                or st.get("launcher_version") != APP_VERSION):
            return {"status": "absent", "reason": "version-mismatch",
                    "installed_version": st.get("component_version")}
        root = _root()
        missing = [f for f in st.get("files", [])
                   if not os.path.isfile(os.path.join(root, f))]
        if missing:
            return {"status": "absent", "reason": "files-missing",
                    "missing": missing[:5], "missing_total": len(missing)}
        return {"status": "installed",
                "version": st.get("component_version"),
                "installed_at": st.get("installed_at")}
    if _markers_present():  # 手动合并 / 开发环境：文件在位即算可用
        return {"status": "installed", "manual": True}
    return {"status": "absent", "reason": "no-state"}


def progress() -> tuple[int, int]:
    """下载进度 ``(sofar, total)``；total 未知时为 0。"""
    return _dl["sofar"], _dl["total"]


# ---------------------------------------------------------------- 下载

def _sources(root: str) -> list[str]:
    """按优先级返回下载源（URL 或本地路径）。"""
    srcs: list[str] = []
    env = os.environ.get("AC_PACK_SRC", "")
    srcs += [s.strip() for s in env.split("|") if s.strip()]
    try:
        with open(get_config_path("launcher_config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        cs = cfg.get("component_src") or []
        if isinstance(cs, str):
            cs = [cs]
        srcs += [str(s) for s in cs]
    except (OSError, ValueError, AttributeError):
        pass
    srcs += list(DEFAULT_URLS)
    # 本地旁置：用户手动下载好丢 exe 旁 / data/incoming（离线友好）
    for p in (os.path.join(root, ZIP_NAME),
              os.path.join(get_data_dir(), "incoming", ZIP_NAME)):
        if os.path.isfile(p) and p not in srcs:
            srcs.append(p)
    return srcs


def _zip_ok(zip_path: str) -> bool:
    """zip 存在且（有 sidecar 时）整体哈希过关。sidecar 缺失时信任传输，
    逐文件 sha256 校验在 install() 兜底。"""
    if not os.path.isfile(zip_path) or os.path.getsize(zip_path) == 0:
        return False
    side = zip_path + ".sha256"
    if os.path.isfile(side):
        try:
            with open(side, encoding="utf-8") as f:
                want = f.read().split()[0].lower()
        except (OSError, IndexError):
            return False
        return _sha256(zip_path) == want
    return True


def ensure_downloaded(root: str | None = None,
                      progress_cb=None, cancel=None) -> str:
    """确保组件 zip 在 ``data/component_pack/`` 就位，返回其路径。

    - 已有且哈希过关 → 直接返回（不重复下载）；
    - 逐源尝试：本地源复制，URL 走 ``net_api.download_file``（断点续传 +
      分片多线程 + 退避重试）；同时尝试取 ``.sha256`` sidecar 整体校验；
    - 全部源失败 → :class:`ComponentError`（含离线手动安装指引）。
    """
    root = root or _root()
    dl_dir = os.path.join(get_data_dir(), "component_pack")
    os.makedirs(dl_dir, exist_ok=True)
    dest = os.path.join(dl_dir, ZIP_NAME)

    if _zip_ok(dest):
        return dest

    sources = _sources(root)
    if not sources:
        raise ComponentError(t("pack.err.no_source", zip=ZIP_NAME))

    _dl.update(active=True, sofar=0, total=0)

    def _cb(sofar: int, total: int) -> None:
        _dl["sofar"], _dl["total"] = sofar, total
        if progress_cb:
            progress_cb(sofar, total)

    from . import net_api  # 懒加载：模块 import 较重，冷启动用不到

    errors: list[str] = []
    try:
        for src in sources:
            local = os.path.isfile(src) or src.startswith("file:")
            try:
                if local:
                    path = src[5:] if src.startswith("file:") else src
                    tmp = dest + ".part"
                    shutil.copyfile(path, tmp)
                    # 本地源同样吃 sidecar（有则校验）
                    side_src = path + ".sha256"
                    if os.path.isfile(side_src):
                        shutil.copyfile(side_src, dest + ".sha256")
                    if not _zip_ok(tmp):
                        os.remove(tmp)
                        raise ComponentError(t("pack.err.zip_hash", path=path))
                    os.replace(tmp, dest)
                    _cb(os.path.getsize(dest), os.path.getsize(dest))
                    return dest
                # URL：先取 sha256 sidecar（拿不到就靠 install 逐文件兜底）
                try:
                    net_api.download_file(src + ".sha256",
                                          dest + ".sha256",
                                          resume=False, timeout=30)
                except Exception:
                    if os.path.exists(dest + ".sha256"):
                        os.remove(dest + ".sha256")
                net_api.download_file(src, dest, resume=True,
                                      progress=_cb, cancel=cancel, timeout=60)
                if _zip_ok(dest):
                    return dest
                errors.append(f"{src}: 整体哈希校验失败")
                if os.path.exists(dest):
                    os.remove(dest)  # 坏包别留着下次续传
            except Exception as e:  # 单源失败 → 换下一源
                errors.append(f"{src}: {e}")
                if cancel and cancel():
                    break
    finally:
        _dl["active"] = False

    raise ComponentError(t("pack.err.download_fail", n=len(sources),
                           detail="；".join(errors[:3]) or "-", zip=ZIP_NAME))


# ---------------------------------------------------------------- 安装/卸载

def _load_manifest(zip_path: str) -> dict:
    """读 zip 内 manifest（旧包无内嵌成员时回退 sidecar）。"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(MANIFEST_MEMBER) as f:
                return json.load(f)
    except (KeyError, zipfile.BadZipFile, ValueError):
        pass
    side = os.path.splitext(zip_path)[0] + ".manifest.json"
    try:
        with open(side, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise ComponentError(t("pack.err.no_manifest"))


def install(zip_path: str | None = None, *, root: str | None = None) -> dict:
    """校验并落位组件；成功返回 state()，失败抛 :class:`ComponentError`。

    幂等：重复调用覆盖同名组件文件。安装完成后需**重启生效**（由调用方提示）。
    """
    root = root or _root()
    if zip_path is None:
        zip_path = ensure_downloaded(root)
    if not os.path.isfile(zip_path):
        raise ComponentError(f"组件包不存在：{zip_path}")

    man = _load_manifest(zip_path)
    if man.get("component_version") != COMPONENT_VERSION:
        raise ComponentError(t("pack.err.version_mismatch",
                               component=man.get("component_version"),
                               app=APP_VERSION))

    tmp = os.path.join(root, _TMP_DIR)
    shutil.rmtree(tmp, ignore_errors=True)
    moved: list[str] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            members = []
            for m in man.get("files", []):
                rel = m["path"]
                if os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
                    raise ComponentError(t("pack.err.illegal_path", path=rel))
                if rel not in names:
                    raise ComponentError(t("pack.err.missing_member", path=rel))
                members.append(rel)
            os.makedirs(tmp, exist_ok=True)
            zf.extractall(tmp, members=members)

        # 逐文件 sha256 校验（B3：不过 → 报错，删临时目录，不留半套）
        for m in man["files"]:
            p = os.path.join(tmp, *m["path"].split("/"))
            if not os.path.isfile(p) or _sha256(p) != m["sha256"]:
                raise ComponentError(t("pack.err.hash_fail", path=m["path"]))

        # 落位（同卷 os.replace 原子替换；目标按 diff 构造本不存在，覆盖无害）
        for m in man["files"]:
            rel = m["path"]
            dst = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(os.path.join(tmp, *rel.split("/")), dst)
            moved.append(rel)
    except BaseException as e:
        # 回滚：已移动的组件文件删掉（清单全是增量文件，不动主包既有件）
        for rel in moved:
            try:
                os.remove(os.path.join(root, *rel.split("/")))
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        if isinstance(e, ComponentError):
            raise
        raise ComponentError(t("pack.err.install_fail", err=e))

    shutil.rmtree(tmp, ignore_errors=True)
    _write_state({
        "component": COMPONENT,
        "component_version": man["component_version"],
        "launcher_version": APP_VERSION,
        "installed_at": datetime.now().isoformat(timespec="seconds"),
        "files": [m["path"] for m in man["files"]],
    })
    return state()


def uninstall(root: str | None = None) -> None:
    """按 state 记录删除组件文件并清 state。

    只删清单内文件；``<data>/extensions/``（插件用户数据）与插件目录不碰（B4）。
    「手动合并」（无 state 记录）无法整体卸载 → :class:`ComponentError`。
    """
    root = root or _root()
    st = _read_state()
    if not st:
        if _markers_present():
            raise ComponentError(t("pack.err.manual_uninstall"))
        return  # 本就未安装
    for rel in st.get("files", []):
        try:
            os.remove(os.path.join(root, *rel.split("/")))
        except OSError:
            pass
    try:
        os.remove(_state_path())
    except OSError:
        pass
