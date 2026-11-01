"""round-167 功能扩展包 — 可物理删除的页面插件。

与 `modules.py` 的「内容模块」（主题/JVM/音效/崩溃策略）不同，本模块管理
**功能页面本身**：音乐、成就、控制台等页面被移到 `<data>/features/<id>/`
下，删掉目录即彻底移除，启动器核心不受影响。

目录结构::

    <data>/features/<id>/manifest.json
    <data>/features/<id>/entry.py        # 必须暴露 create_page(ctx)
    assets/features/<id>/...             # 随安装包发布的内置原始包

`registry.json` 只记录「曾经装过的内置包」：玩家主动删掉的包不会被下一次
启动自动装回；只有设置页点「安装」或 `restore_builtin()` 才恢复。

动态导入用 `src._feature_<id>` 作为模块名，`__package__` 为 `src`，因此包内
页面代码可以直接沿用 `.theme` / `.i18n` / `.ui_kit` 等相对导入。
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field

from .paths import get_data_dir, get_resource_path

MANIFEST_FILE = "manifest.json"
ENTRY_DEFAULT = "entry.py"
REGISTRY_FILE = "registry.json"

_RE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_NAV_GROUPS = ("game", "resource", "multiplayer", "other", "system", "extensions")
_MAX_DOWNLOAD = 32 * 1024 * 1024   # 扩展包下载上限 32 MB

# ── 保护阈值：扩展是「以启动器权限运行的代码」，安装前先做静态判断 ──
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_ENTRY_BYTES = 2 * 1024 * 1024
_MAX_PACK_BYTES = 128 * 1024 * 1024
_MAX_PACK_FILES = 2000
_MAX_NAME = 64
_MAX_DESC = 200
_MAX_VERSION = 32
_MAX_ICON = 32
_MAX_ORDER = 9999
_RE_ICON = re.compile(r"^[A-Za-z0-9_-]+$")
# 与核心页面/顶部导航重名的 id 一律拒绝，避免扩展冒充内置入口。
CORE_PAGE_IDS = frozenset({
    "home", "instances", "mods", "store", "versions", "lobby", "settings",
    "toolbox", "account", "launch", "download", "online", "more",
})
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class FeatureError(Exception):
    """扩展包清单/安装错误（UI 直接展示 str(e)）。"""


# ── 路径与注册表 ──────────────────────────────────────────────────────────
_ROOT_CACHE: str | None = None


def feature_root() -> str:
    # AC_DEV_TEMP=1 时 get_data_dir() 每次调用都返回新临时目录；扩展目录
    # 必须在同一进程内稳定，否则扫描/安装/卸载会落在不同目录。缓存一次。
    global _ROOT_CACHE
    if _ROOT_CACHE and os.path.isdir(_ROOT_CACHE):
        return _ROOT_CACHE
    d = os.path.join(get_data_dir(), "features")
    os.makedirs(d, exist_ok=True)
    _ROOT_CACHE = d
    return d


def bundled_root() -> str:
    return get_resource_path(os.path.join("assets", "features"))


def _root(root: str | None) -> str:
    return root if root else feature_root()


def _registry_path(root: str) -> str:
    return os.path.join(root, REGISTRY_FILE)


def _load_registry(root: str) -> dict:
    try:
        with open(_registry_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("known"), list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"known": []}


def _save_registry(root: str, reg: dict) -> None:
    tmp = _registry_path(root) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _registry_path(root))
    except OSError:
        pass


# ── 清单与扫描 ────────────────────────────────────────────────────────────
def _sanitize_id(raw) -> str:
    return "".join(c for c in str(raw) if c.isalnum() or c in "-._")


def _entry_name(raw) -> str:
    """entry 只允许单个 .py 文件名，拒绝路径分隔符与目录穿越。"""
    name = str(raw or "").strip()
    if (not name or "/" in name or "\\" in name
            or os.path.dirname(name) or name in (".py",)):
        raise FeatureError("entry 必须是单个 .py 文件名（不允许路径）")
    if not name.lower().endswith(".py"):
        raise FeatureError("entry 必须是 .py 文件名")
    return name


def _str_field(m: dict, key: str, default: str = "", *,
               required: bool = False, limit: int = 0) -> str:
    """取字符串字段并校验类型/长度；None 视为缺省，类型不对直接拒绝。"""
    value = m.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise FeatureError(f"清单字段 {key} 必须是字符串")
    value = value.strip()
    if required and not value:
        raise FeatureError(f"扩展清单缺少 {key}")
    if limit and len(value) > limit:
        raise FeatureError(f"清单字段 {key} 过长（最多 {limit} 字符）")
    return value


def _order_of(m: dict) -> int:
    """order 必须是整数并夹在 ±9999；错类型拒绝，避免排序时崩溃。"""
    raw = m.get("order", 50)
    if raw is None:
        return 50
    if isinstance(raw, bool):
        raise FeatureError("order 必须是整数")
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return 50
        try:
            raw = int(raw)
        except ValueError:
            raise FeatureError("order 必须是整数")
    if not isinstance(raw, int):
        raise FeatureError("order 必须是整数")
    return max(-_MAX_ORDER, min(_MAX_ORDER, raw))


def _check_entry_size(folder: str, entry: str) -> None:
    """入口文件必须存在、非空、不超过 2 MB。"""
    path = os.path.join(folder, entry)
    try:
        size = os.path.getsize(path)
    except OSError:
        raise FeatureError("扩展缺少入口文件")
    if size <= 0:
        raise FeatureError("扩展入口文件为空")
    if size > _MAX_ENTRY_BYTES:
        raise FeatureError("扩展入口文件过大（上限 2 MB）")


def validate_manifest(m: dict, folder_name: str = "") -> str:
    """校验清单，返回扩展 id；不合法抛 FeatureError。"""
    if not isinstance(m, dict):
        raise FeatureError("扩展清单格式无效（应为 JSON 对象）")
    raw_id = m.get("id", "")
    if not isinstance(raw_id, str):
        raise FeatureError("扩展 id 必须是字符串")
    raw_id = raw_id.strip()
    mid = _sanitize_id(raw_id)
    # 不做静默清洗：清单里的 id 必须是干净可用的字符串
    if not mid or mid != raw_id or not _RE_ID.match(mid):
        raise FeatureError("扩展 id 非法")
    if mid in CORE_PAGE_IDS:
        raise FeatureError(f"扩展 id 与核心页面冲突：{mid}")
    if folder_name and folder_name != mid:
        raise FeatureError(
            f"扩展目录名（{folder_name}）与 manifest.id（{mid}）不一致")
    _str_field(m, "name", required=True, limit=_MAX_NAME)
    _str_field(m, "name_en", limit=_MAX_NAME)
    _str_field(m, "version", required=True, limit=_MAX_VERSION)
    _entry_name(m.get("entry", ENTRY_DEFAULT))
    icon = _str_field(m, "icon", limit=_MAX_ICON)
    if icon and not _RE_ICON.match(icon):
        raise FeatureError("icon 只能包含字母、数字、下划线或连字符")
    group = _str_field(m, "nav_group", default="extensions", limit=16) \
        or "extensions"
    if group not in _NAV_GROUPS:
        raise FeatureError(f"未知 nav_group：{group}")
    _str_field(m, "description", limit=_MAX_DESC)
    _str_field(m, "description_en", limit=_MAX_DESC)
    _order_of(m)
    return mid


@dataclass
class FeaturePack:
    id: str
    folder: str
    manifest: dict
    name: str = ""
    name_en: str = ""
    version: str = ""
    entry: str = ENTRY_DEFAULT
    icon: str = "tools"
    nav_group: str = "extensions"
    order: int = 50
    source: str = "manual"
    description: str = ""
    description_en: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = self.id
        if not self.name_en:
            self.name_en = self.name


def _read_json(path: str) -> dict:
    """读取清单前先限制体积，避免超大 JSON 卡住启动。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        raise FeatureError("无法读取扩展清单")
    if size > _MAX_MANIFEST_BYTES:
        raise FeatureError("manifest.json 过大（上限 256 KB）")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise FeatureError(f"扩展清单无法解析：{e}")
    if not isinstance(data, dict):
        raise FeatureError("清单不是 JSON 对象")
    return data


def _pack_from(folder: str, m: dict, mid: str, source: str = "") -> FeaturePack:
    return FeaturePack(
        id=mid,
        folder=folder,
        manifest=m,
        name=str(m.get("name", mid)),
        name_en=str(m.get("name_en", "") or m.get("name", mid)),
        version=str(m.get("version", "")) or "1.0.0",
        entry=_entry_name(m.get("entry", ENTRY_DEFAULT)),
        icon=str(m.get("icon", "") or "tools"),
        nav_group=str(m.get("nav_group", "extensions") or "extensions"),
        order=_order_of(m),
        source=str(m.get("source", "") or source or "manual"),
        description=str(m.get("description", "")),
        description_en=str(m.get("description_en", "") or m.get("description", "")),
    )


def scan_installed(root: str | None = None) -> list[FeaturePack]:
    """扫描已安装扩展；坏包/缺 entry 一律跳过，绝不抛异常。"""
    out: list[FeaturePack] = []
    base = _root(root)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        folder = os.path.join(base, name)
        mpath = os.path.join(folder, MANIFEST_FILE)
        if not os.path.isfile(mpath):
            continue
        try:
            m = _read_json(mpath)
            mid = validate_manifest(m, folder_name=name)
            _check_entry_size(folder, _entry_name(m.get("entry", ENTRY_DEFAULT)))
        except Exception:  # noqa: BLE001 - 坏扩展不拖垮启动
            continue
        out.append(_pack_from(folder, m, mid))
    out.sort(key=lambda p: (p.order, p.name.lower()))
    return out


# ── 内置包：首次安装 / 删除后不自动重装 ──────────────────────────────────
def _copy_tree(src: str, dest: str) -> None:
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dest, item)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def _check_tree_limits(base: str) -> None:
    """安装前检查目录体积/文件数，防止误装超大扩展包。"""
    count = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            count += 1
            total += size
            if count > _MAX_PACK_FILES:
                raise FeatureError(f"扩展文件过多（上限 {_MAX_PACK_FILES} 个）")
            if total > _MAX_PACK_BYTES:
                raise FeatureError("扩展包过大（上限 128 MB）")


def _bundled_packs(broot: str) -> list[tuple[str, str, dict]]:
    """返回 [(id, folder, manifest)]，坏包跳过。"""
    out = []
    try:
        names = sorted(os.listdir(broot))
    except OSError:
        return out
    for name in names:
        folder = os.path.join(broot, name)
        mpath = os.path.join(folder, MANIFEST_FILE)
        if not os.path.isfile(mpath):
            continue
        try:
            m = _read_json(mpath)
            mid = validate_manifest(m, folder_name=name)
        except Exception:  # noqa: BLE001
            continue
        out.append((mid, folder, m))
    return out


def ensure_builtins(dest_root: str | None = None,
                    bundled: str | None = None) -> list[str]:
    """首次把内置扩展复制到 data；玩家删掉的包不会自动恢复。"""
    root = _root(dest_root)
    broot = bundled if bundled else bundled_root()
    reg = _load_registry(root)
    known = [str(x) for x in reg.get("known", []) if isinstance(x, str)]
    known_set = set(known)
    installed: list[str] = []
    for mid, src, m in _bundled_packs(broot):
        dest = os.path.join(root, mid)
        if os.path.isdir(dest):
            # 已在磁盘上：可能是内置复制、手工放置或玩家保留的旧版
            known_set.add(mid)
            installed.append(mid)
            continue
        if mid in known_set:
            continue           # 曾装过、现在被玩家删了 → 不自动重装
        try:
            os.makedirs(dest, exist_ok=True)
            _copy_tree(src, dest)
        except OSError:
            shutil.rmtree(dest, ignore_errors=True)
            continue
        known_set.add(mid)
        installed.append(mid)
    _save_registry(root, {"known": sorted(known_set)})
    return installed


def bundled_ids(bundled: str | None = None) -> set[str]:
    """所有随包发布的内置扩展 id（用于来源徽章，不检查安装状态）。"""
    broot = bundled if bundled else bundled_root()
    return {mid for mid, _folder, _m in _bundled_packs(broot)}


def list_builtins(dest_root: str | None = None,
                  bundled: str | None = None) -> list[dict]:
    """列出尚未安装的内置扩展（供设置页「安装」按钮）。"""
    root = _root(dest_root)
    broot = bundled if bundled else bundled_root()
    out = []
    for mid, folder, m in _bundled_packs(broot):
        if os.path.isdir(os.path.join(root, mid)):
            continue
        out.append({
            "id": mid,
            "name": str(m.get("name", mid)),
            "name_en": str(m.get("name_en", "") or m.get("name", mid)),
            "version": str(m.get("version", "")),
            "description": str(m.get("description", "")),
            "description_en": str(m.get("description_en", "") or m.get("description", "")),
        })
    return out


def restore_builtin(feature_id: str, dest_root: str | None = None,
                    bundled: str | None = None) -> FeaturePack:
    """把被删除的内置扩展从 assets 装回 data。"""
    mid = _sanitize_id(feature_id)
    if not mid or not _RE_ID.match(mid):
        raise FeatureError("扩展 id 非法")
    root = _root(dest_root)
    broot = bundled if bundled else bundled_root()
    for bid, src, m in _bundled_packs(broot):
        if bid != mid:
            continue
        dest = os.path.join(root, mid)
        if not os.path.isdir(dest):
            os.makedirs(dest, exist_ok=True)
            try:
                _copy_tree(src, dest)
            except OSError:
                shutil.rmtree(dest, ignore_errors=True)
                raise FeatureError("内置扩展复制失败（文件被占用？）")
        return _pack_from(dest, m, mid, source="builtin")
    raise FeatureError(f"找不到内置扩展：{mid}")


# ── 安装 / 卸载 ───────────────────────────────────────────────────────────
def install_from_folder(src: str, root: str | None = None,
                        check_dir_name: bool = True) -> FeaturePack:
    """把含 manifest.json 的目录复制为扩展（同 id 已存在则报冲突）。"""
    src = os.path.abspath(src)
    mpath = os.path.join(src, MANIFEST_FILE)
    if not os.path.isfile(mpath):
        raise FeatureError("目录里没有 manifest.json")
    m = _read_json(mpath)
    folder_name = os.path.basename(os.path.normpath(src)) if check_dir_name else ""
    mid = validate_manifest(m, folder_name=folder_name)
    entry = _entry_name(m.get("entry", ENTRY_DEFAULT))
    _check_tree_limits(src)
    dest = os.path.join(_root(root), mid)
    if os.path.exists(dest):
        raise FeatureError(f"已安装同 id 扩展：{mid}（请先删除或换个 id）")
    os.makedirs(dest, exist_ok=True)
    try:
        _copy_tree(src, dest)
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)
        raise FeatureError("扩展复制失败（文件被占用？）")
    try:
        _check_entry_size(dest, entry)
    except FeatureError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return _pack_from(dest, m, mid)


def _safe_extract(zf: zipfile.ZipFile, dest: str) -> None:
    """逐成员校验后解压，拒绝目录穿越（fail-closed）。"""
    dest_root = os.path.realpath(dest)
    for info in zf.infolist():
        target = os.path.realpath(os.path.join(dest, info.filename))
        if target != dest_root and not target.startswith(dest_root + os.sep):
            raise FeatureError(f"压缩包包含非法路径成员：{info.filename!r}")
        zf.extract(info, dest)


def _check_zip_limits(zf: zipfile.ZipFile) -> None:
    """按清单里的 file_size 预估解压体积，防 zip bomb 撑爆磁盘/内存。"""
    infos = zf.infolist()
    if len(infos) > _MAX_PACK_FILES:
        raise FeatureError(f"压缩包文件过多（上限 {_MAX_PACK_FILES} 个）")
    total = 0
    for info in infos:
        if info.file_size > _MAX_PACK_BYTES:
            raise FeatureError("压缩包内单个文件过大")
        total += info.file_size
        if total > _MAX_PACK_BYTES:
            raise FeatureError("压缩包解压后过大（上限 128 MB）")


def install_from_zip(path: str, root: str | None = None) -> FeaturePack:
    """解压 zip 安装扩展：manifest 在包根或唯一顶层目录均可。"""
    tmp = tempfile.mkdtemp(prefix="ac_feat_")
    try:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                _check_zip_limits(zf)
                _safe_extract(zf, tmp)
        except zipfile.BadZipFile:
            raise FeatureError("不是有效的 zip 扩展包")
        root_dir = tmp
        at_root = os.path.isfile(os.path.join(root_dir, MANIFEST_FILE))
        if not at_root:
            subs = [n for n in os.listdir(root_dir)
                    if os.path.isdir(os.path.join(root_dir, n))]
            if len(subs) != 1:
                raise FeatureError("zip 内找不到 manifest.json（应在包根或唯一顶层目录）")
            root_dir = os.path.join(root_dir, subs[0])
        return install_from_folder(root_dir, root=root, check_dir_name=not at_root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _check_script_source(path: str) -> None:
    """安装前静态判断：UTF-8、语法正确、存在 create_page 入口。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        raise FeatureError("脚本读取失败")
    if size <= 0:
        raise FeatureError("脚本为空")
    if size > _MAX_ENTRY_BYTES:
        raise FeatureError("脚本过大（上限 2 MB）")
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except (OSError, UnicodeDecodeError):
        raise FeatureError("脚本读取失败（必须是 UTF-8 文本）")
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        raise FeatureError(f"脚本语法错误：第 {e.lineno or '?'} 行 {e.msg}")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "create_page"
               for n in ast.walk(tree)):
        raise FeatureError("脚本缺少 create_page(ctx) 入口函数")


def install_from_script(path: str, root: str | None = None) -> FeaturePack:
    """单个 .py 脚本安装成扩展：自动生成 manifest，入口即该脚本。"""
    path = os.path.abspath(path)
    if not os.path.isfile(path) or not path.endswith(".py"):
        raise FeatureError("请选择一个 .py 脚本")
    _check_script_source(path)
    raw_id = os.path.splitext(os.path.basename(path))[0]
    mid = _sanitize_id(raw_id)
    if not mid or not _RE_ID.match(mid):
        raise FeatureError(f"脚本文件名无法作为扩展 id：{raw_id!r}")
    if mid in CORE_PAGE_IDS:
        raise FeatureError(f"脚本文件名与核心页面冲突：{mid}")
    dest = os.path.join(_root(root), mid)
    if os.path.exists(dest):
        raise FeatureError(f"已安装同 id 扩展：{mid}（请先删除或改文件名）")
    os.makedirs(dest, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "id": mid,
        "name": raw_id,
        "name_en": raw_id,
        "version": "1.0.0",
        "entry": "entry.py",
        "icon": "tools",
        "nav_group": "extensions",
        "description": "",
        "description_en": "",
        "source": "script",
    }
    try:
        shutil.copy2(path, os.path.join(dest, "entry.py"))
        with open(os.path.join(dest, MANIFEST_FILE), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)
        raise FeatureError("脚本复制失败（文件被占用？）")
    return _pack_from(dest, manifest, mid)


def _check_url(url: str) -> str:
    """只允许 https；http 仅放行本机调试地址（防明文降级）。"""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        raise FeatureError("链接格式无效")
    if parts.scheme not in ("https", "http"):
        raise FeatureError("只支持 https 链接")
    if parts.scheme == "http" and (parts.hostname or "").lower() not in _LOCAL_HOSTS:
        raise FeatureError("出于安全考虑只允许 https 链接（http 仅限本机调试）")
    if not parts.hostname:
        raise FeatureError("链接缺少主机名")
    return url


def install_from_url(url: str, root: str | None = None) -> FeaturePack:
    """从 https 链接安装（GitHub Release / raw zip 或 .py）。"""
    url = _check_url(str(url or "").strip())
    tmp = tempfile.mkdtemp(prefix="ac_feat_dl_")
    try:
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                # 重定向后必须是同一安全策略，防止 https → http 降级
                _check_url(resp.geturl())
                data = resp.read(_MAX_DOWNLOAD + 1)
        except FeatureError:
            raise
        except Exception as e:  # noqa: BLE001 - 网络错误统一转业务错误
            raise FeatureError(f"下载失败：{e}")
        if len(data) > _MAX_DOWNLOAD:
            raise FeatureError("扩展包超过 32 MB，已拒绝")
        name = os.path.basename(url.split("?", 1)[0]) or "download.zip"
        path = os.path.join(tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        if name.endswith(".py"):
            return install_from_script(path, root=root)
        return install_from_zip(path, root=root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def uninstall(feature_id: str, root: str | None = None) -> None:
    """物理删除扩展目录（registry.known 保留，防止下次自动装回）。"""
    mid = _sanitize_id(feature_id)
    if not mid or not _RE_ID.match(mid):
        raise FeatureError("扩展 id 非法")
    folder = os.path.join(_root(root), mid)
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)


# ── 动态加载 ──────────────────────────────────────────────────────────────
_LAST_ERROR = ""


def last_error() -> str:
    return _LAST_ERROR


def _module_name(fid: str) -> str:
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in fid)
    return f"src._feature_{safe}"


def load_page(pack: FeaturePack, ctx=None):
    """导入扩展入口并调用 create_page(ctx)。

    返回 `create_page` 的返回值；任何异常都被吞掉并记录到 `last_error()`，
    调用方据此显示占位提示，绝不因扩展坏了而崩掉启动器。
    """
    global _LAST_ERROR
    _LAST_ERROR = ""
    entry = os.path.join(pack.folder, pack.entry)
    try:
        _check_entry_size(pack.folder, pack.entry)
    except FeatureError as e:
        _LAST_ERROR = str(e)
        return None
    modname = _module_name(pack.id)
    sys.modules.pop(modname, None)
    try:
        spec = importlib.util.spec_from_file_location(modname, entry)
        if spec is None or spec.loader is None:
            raise ImportError("无法创建模块规格")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        create = getattr(mod, "create_page", None)
        if not callable(create):
            raise AttributeError("entry.py 缺少 create_page(ctx)")
        return create(ctx)
    except Exception as e:  # noqa: BLE001 - 扩展失败不能影响主体
        sys.modules.pop(modname, None)
        _LAST_ERROR = f"{type(e).__name__}: {e}"
        return None


class FeatureContext:
    """传给扩展的只读上下文（扩展需要更多能力时在此扩展）。"""

    def __init__(self, launcher=None, cfg: dict | None = None):
        self.launcher = launcher
        self.cfg = cfg or {}

    @staticmethod
    def t(key: str, default: str | None = None) -> str:
        from .i18n import t
        return t(key, default=default)

    @staticmethod
    def icon(name: str):
        from .icons import icon
        return icon(name)

    @staticmethod
    def data_dir() -> str:
        return get_data_dir()
