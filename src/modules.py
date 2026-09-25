"""模块化内容市场 — 把主题包 / JVM 预设 / 音效包 / 崩溃策略统一为「可安装模块」。

模块 = <data>/modules/<id>/ 目录 + manifest.json + 按类型命名的载荷文件：

    theme_pack  → theme-pack.json  与旧版主题包 .json 同构（见 theme.py）
    jvm_preset  → preset.json     {label, jvm_args}
    sfx_pack    → sfx.json        {files: {click/hover/success/error: 相对路径}, volume}
    crash_pol   → policy.json     {action, auto_analyze, ...}

安装来源：本地目录 / .zip 包 / 旧版主题包 .json（自动转成模块）/ 内置市场精选。
『应用』把模块载荷写入 launcher 配置（theme_pack / jvm_args / sfx_* / crash_policy）；
卸载时回滚主题等副作用。现有主题下拉（theme.py 的 data/themes/*.json）完全不受影响，
主题模块安装时会自动桥接一份 json 过去，保证旧入口可用、无回归。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Optional

from .paths import get_data_dir, get_resource_path

# ── 模块类型：键 → i18n 键（UI 用 t() 取显示名）───────────────────────────
MODULE_TYPES: dict[str, str] = {
    "theme_pack": "modules.type_theme_pack",
    "jvm_preset": "modules.type_jvm_preset",
    "sfx_pack":   "modules.type_sfx_pack",
    "crash_pol":  "modules.type_crash_pol",
}
TYPE_ORDER = ["theme_pack", "jvm_preset", "sfx_pack", "crash_pol"]
MANIFEST_FILE = "manifest.json"

_PAYLOAD_FILES = {
    "theme_pack": "theme-pack.json",
    "jvm_preset": "preset.json",
    "sfx_pack":   "sfx.json",
    "crash_pol":  "policy.json",
}

_RE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ModuleError(Exception):
    """模块清单无效 / 安装冲突等业务错误（UI 直接展示 str(e)）。"""


# ── 目录与注册表 ───────────────────────────────────────────────────────────
def get_modules_dir() -> str:
    d = os.path.join(get_data_dir(), "modules")
    os.makedirs(d, exist_ok=True)
    return d


def _registry_path() -> str:
    return os.path.join(get_modules_dir(), "registry.json")


def _load_registry() -> dict:
    try:
        with open(_registry_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("enabled", []), list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"enabled": []}


def _save_registry(reg: dict) -> None:
    tmp = _registry_path() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _registry_path())
    except OSError:
        pass


# ── 模块信息 ───────────────────────────────────────────────────────────────
@dataclass
class ModuleInfo:
    id: str
    folder: str            # <data>/modules/<id>
    manifest: dict         # 原始 manifest.json
    version: str = ""
    name: str = ""
    name_en: str = ""
    author: str = ""
    description: str = ""
    description_en: str = ""
    tags: list = None
    type: str = ""
    enabled: bool = True

    @property
    def source(self) -> str:
        return self.manifest.get("source", "local")


def _sanitize_id(raw_id) -> str:
    return "".join(c for c in str(raw_id) if c.isalnum() or c in "-._")


def validate_manifest(m: dict, folder_name: str = "") -> str:
    """校验清单，返回模块 id；不合法抛 ModuleError。"""
    if not isinstance(m, dict):
        raise ModuleError("模块清单格式无效（应为 JSON 对象）")
    mid = m.get("id")
    if not mid:
        raise ModuleError("模块清单缺少 id")
    mid = _sanitize_id(mid)
    if not _RE_ID.match(mid):
        raise ModuleError(f"模块 id 非法：{mid!r}")
    if folder_name and folder_name != mid:
        raise ModuleError(
            f"模块目录名（{folder_name}）与 manifest.id（{mid}）不一致")
    if not m.get("name"):
        raise ModuleError("模块清单缺少 name")
    if not str(m.get("version", "")).strip():
        raise ModuleError("模块清单缺少 version")
    mtype = m.get("type")
    if mtype not in MODULE_TYPES:
        raise ModuleError(f"未知模块类型：{mtype!r}（可选 {', '.join(TYPE_ORDER)}）")
    return mid


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ModuleError("模块载荷不是 JSON 对象")
    return data


def scan_modules() -> list[ModuleInfo]:
    """读取 <data>/modules/*/manifest.json，返回全部已安装模块（排序）。"""
    reg = _load_registry()
    enabled_set = set(reg.get("enabled", []))
    out: list[ModuleInfo] = []
    d = get_modules_dir()
    try:
        names = sorted(os.listdir(d))
    except OSError:
        names = []
    for name in names:
        folder = os.path.join(d, name)
        mpath = os.path.join(folder, MANIFEST_FILE)
        if not os.path.isfile(mpath):
            continue
        try:
            m = _read_json(mpath)
            mid = validate_manifest(m, folder_name=name)
        except Exception:
            continue   # 坏模块不拖垮整个加载，列表里自然消失
        out.append(ModuleInfo(
            id=mid, folder=folder, manifest=m,
            version=str(m.get("version", "")),
            name=str(m.get("name", mid)),
            name_en=str(m.get("name_en", "") or m.get("name", mid)),
            author=str(m.get("author", "")),
            description=str(m.get("description", "")),
            description_en=str(m.get("description_en", "") or m.get("description", "")),
            tags=list(m.get("tags", []) or []),
            type=str(m.get("type", "")),
            enabled=mid in enabled_set,
        ))
    out.sort(key=lambda mo: (TYPE_ORDER.index(mo.type) if mo.type in TYPE_ORDER else 99,
                             mo.name.lower()))
    return out


def find_module(mid: str) -> Optional[ModuleInfo]:
    for m in scan_modules():
        if m.id == mid:
            return m
    return None


def is_module_enabled(mid: str) -> bool:
    return mid in set(_load_registry().get("enabled", []))


def set_module_enabled(mid: str, on: bool) -> None:
    reg = _load_registry()
    enabled = set(reg["enabled"])
    if on:
        enabled.add(mid)
    else:
        enabled.discard(mid)
    reg["enabled"] = sorted(enabled)
    _save_registry(reg)


# ── 载荷 ───────────────────────────────────────────────────────────────────
def module_payload(mod: ModuleInfo) -> Optional[dict]:
    """读取类型载荷（theme-pack.json / preset.json / …），无载荷返回 None。"""
    name = _PAYLOAD_FILES.get(mod.type)
    if not name:
        return None
    p = os.path.join(mod.folder, name)
    if not os.path.isfile(p):
        return None
    try:
        return _read_json(p)
    except Exception:
        return None


# ── 安装 / 卸载 / 导出 ─────────────────────────────────────────────────────
def _install_from_folder(src: str, check_dir_name: bool = True) -> ModuleInfo:
    """把含 manifest.json 的目录复制为模块（存在则报冲突）。

    round-92 审查修复：`check_dir_name` 为 False 时跳过「目录名 == manifest.id」
    校验——用于 **zip 安装的包内 manifest 就在根** 的情况：那时解压容器临时目录名
    （`ac_mod_xxxx`）本身没有语义，却会被当成模块目录名去比对 id，**必然不一致**，
    导致 CHANGELOG 声称支持的「manifest 位于包根」形式实际装不上。
    本地目录安装与「zip 内唯一顶层目录」两种情况仍照常校验。
    """
    mpath = os.path.join(src, MANIFEST_FILE)
    if not os.path.isfile(mpath):
        raise ModuleError("目录里没有 manifest.json")
    m = _read_json(mpath)
    folder = os.path.basename(os.path.normpath(src)) if check_dir_name else ""
    mid = validate_manifest(m, folder_name=folder)
    dest = os.path.join(get_modules_dir(), mid)
    if os.path.exists(dest):
        raise ModuleError(f"已安装模块 id 冲突：{mid}（请先卸载或换个包）")
    os.makedirs(dest, exist_ok=True)
    try:
        _copy_tree(src, dest)
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)
        raise ModuleError("模块复制失败（文件被占用？）")
    set_module_enabled(mid, True)
    return find_module(mid)


def _copy_tree(src: str, dest: str) -> None:
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dest, item)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def install_module_dir(path: str) -> ModuleInfo:
    return _install_from_folder(os.path.abspath(path))


def _safe_extract_zip(zf: "zipfile.ZipFile", dest: str) -> None:
    """逐成员校验后解压，目标路径必须落在 dest 内。

    round-92 安全审查：**fail-closed 加固**（非紧急修补）。

    结论先说：Python 3.13 标准库 `zipfile.extractall()` **已内置路径净化**——
    `../../a.txt` 会被折叠为 `<dest>/a.txt`、绝对路径成员被去掉根目录，
    实测无法逃逸。所以这里原本**不是可利用的 Zip Slip 漏洞**。

    仍然改为逐成员 realpath 校验的理由：净化是**静默**的——恶意包里的遍历成员
    会被悄悄塞进模块目录并被后续安装逻辑使用，没有任何告警；改为显式拒绝
    （fail-closed）可在安装阶段就报错中止。同时防御将来依赖/解释器行为变化。

    注意：模块市场本就要安装第三方包，此处属于真实受攻击面，保持严格是对的。
    """
    dest_root = os.path.realpath(dest)
    for info in zf.infolist():
        target = os.path.realpath(os.path.join(dest, info.filename))
        if target != dest_root and not target.startswith(dest_root + os.sep):
            raise ModuleError(
                f"模块压缩包包含非法路径成员：{info.filename!r}——"
                "已阻止安装（疑似 Zip Slip 攻击）")
        zf.extract(info, dest)


def install_module_zip(zip_path: str) -> ModuleInfo:
    """解压 .zip 安装模块：manifest.json 在包根目录或唯一顶层目录均可。"""
    tmp = tempfile.mkdtemp(prefix="ac_mod_")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract_zip(zf, tmp)
        root = tmp
        _at_root = os.path.isfile(os.path.join(root, MANIFEST_FILE))
        if not _at_root:
            subs = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
            if len(subs) == 1:
                root = os.path.join(root, subs[0])
            else:
                raise ModuleError(
                    "压缩包内找不到 manifest.json（应位于包根或唯一顶层目录）")
        # manifest 在包根时跳过目录名校验（容器是随机临时目录名，无语义）
        mod = _install_from_folder(root, check_dir_name=not _at_root)
        _strip_secret_dirs(mod.folder)
        return mod
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _strip_secret_dirs(folder: str) -> None:
    """安装后清掉包内备份目录（__MACOSX / .git 等），避免脏文件进 data。"""
    for name in ("__MACOSX", ".git", ".svn", ".hg"):
        p = os.path.join(folder, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)


def install_legacy_theme_pack(json_path: str) -> ModuleInfo:
    """把旧版主题包 .json 转成一个 theme_pack 模块（不破坏旧主题下拉）。"""
    pack = _read_json(os.path.abspath(json_path))
    mid = _sanitize_id(pack.get("id", ""))
    if not mid:
        raise ModuleError("旧主题包缺少 id，无法转换")
    dest = os.path.join(get_modules_dir(), mid)
    if os.path.exists(dest):
        raise ModuleError(f"已存在同名模块：{mid}")
    os.makedirs(dest, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "id": mid,
        "name": pack.get("name", mid),
        "name_en": pack.get("name_en") or pack.get("name", mid),
        "version": str(pack.get("version", "1.0.0")),
        "type": "theme_pack",
        "author": pack.get("author", ""),
        "description": pack.get("description", ""),
        "source": "legacy",
    }
    with open(os.path.join(dest, MANIFEST_FILE), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(dest, "theme-pack.json"), "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=2)
    set_module_enabled(mid, True)
    return find_module(mid)


def _dump_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def uninstall_module(mid: str) -> None:
    """删除模块目录 + 注册表条目 + 主题桥接文件；主题当前选中则回滚。"""
    mod = find_module(mid)
    if not mod:
        return
    shutil.rmtree(mod.folder, ignore_errors=True)
    reg = _load_registry()
    enabled = set(reg["enabled"])
    enabled.discard(mid)
    reg["enabled"] = sorted(enabled)
    _save_registry(reg)
    # 主题模块：清掉桥接 file + 若正在使用则回滚到无主题
    if mod.type == "theme_pack":
        bridge = os.path.join(get_data_dir(), "themes", f"{mid}.json")
        if os.path.isfile(bridge):
            os.remove(bridge)
        _unset_theme_in_cfg(mid)
    # JVM 预设模块：卸载后清掉它填进去的 jvm_args（用户没再改过才清）
    if mod.type == "jvm_preset":
        _unset_jvm_in_cfg(mid)
    # 音效 / 崩溃策略模块：卸载后清掉它们写进 config 的键防残留
    if mod.type == "sfx_pack":
        _unset_sfx_in_cfg(mid)
    if mod.type == "crash_pol":
        _unset_crash_in_cfg(mid)


def export_module_zip(mod: ModuleInfo, dest_path: str) -> None:
    """把模块目录打包成 <id>.zip，方便分享。"""
    tmp = tempfile.mkdtemp(prefix="ac_exp_")
    try:
        stage = os.path.join(tmp, mod.id)
        shutil.copytree(mod.folder, stage)
        if os.path.isfile(os.path.join(stage, "registry.json")):
            os.remove(os.path.join(stage, "registry.json"))
        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(stage):
                for fn in files:
                    full = os.path.join(root, fn)
                    zf.write(full, os.path.relpath(full, tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── 应用副作用（写入 launcher 配置，_save 同款路径）────────────────────────
def _cfg() -> dict:
    from .settings_dialog import load_config
    return load_config()


def _save(cfg: dict) -> None:
    from .settings_dialog import save_config
    save_config(cfg)


def apply_theme_module(mod: ModuleInfo) -> bool:
    """应用主题模块：桥接 file 供旧下拉使用 + 立即整窗换肤。"""
    payload = module_payload(mod)
    if not payload:
        raise ModuleError("主题模块缺少 theme-pack.json")
    from . import theme
    pack = dict(payload)
    pack.setdefault("id", mod.id)
    bridge = os.path.join(get_data_dir(), "themes", f"{mod.id}.json")
    _dump_json(bridge, pack)
    theme.apply_theme_pack(pack)
    theme.apply_qss()
    c = _cfg()
    c["theme_pack"] = mod.id
    _save(c)
    return True


def apply_jvm_module(mod: ModuleInfo) -> bool:
    """应用 JVM 预设：jvm_preset→custom + jvm_args 填入。"""
    payload = module_payload(mod)
    if not payload:
        raise ModuleError("JVM 预设模块缺少 preset.json")
    args = str(payload.get("jvm_args", "")).strip()
    if not args:
        raise ModuleError("preset.json 里没有 jvm_args")
    c = _cfg()
    c["jvm_preset"] = "custom"
    c["jvm_args"] = args
    c["_jvm_module"] = mod.id
    _save(c)
    return True


def apply_sfx_module(mod: ModuleInfo) -> bool:
    """应用音效包：把包内音频绝对路径填进 sfx_* 并开启。"""
    payload = module_payload(mod)
    if not payload:
        raise ModuleError("音效包缺少 sfx.json")
    files = payload.get("files") or {}
    if not isinstance(files, dict) or not files:
        raise ModuleError("sfx.json 的 files 为空")
    c = _cfg()
    for key in ("click", "hover", "success", "error"):
        rel = files.get(key)
        if rel:
            c[f"sfx_{key}"] = os.path.join(mod.folder, rel)
        else:
            c[f"sfx_{key}"] = ""
    c["sfx_enabled"] = bool(payload.get("enabled", True))
    if "volume" in payload:
        try:
            c["sfx_vol"] = float(payload["volume"])
        except (TypeError, ValueError):
            pass
    c["_sfx_module"] = mod.id
    _save(c)
    return True


def apply_crash_module(mod: ModuleInfo) -> bool:
    """应用崩溃策略：把 policy.json 存进 config（崩溃流程按需消费）。"""
    payload = module_payload(mod)
    if not payload:
        raise ModuleError("崩溃策略模块缺少 policy.json")
    c = _cfg()
    c["crash_policy"] = dict(payload)
    c["_crash_module"] = mod.id
    _save(c)
    return True


def active_crash_policy() -> Optional[dict]:
    """取当前生效的崩溃策略（供崩溃流程读取，无则由调用方给默认）。"""
    return _cfg().get("crash_policy")


def _unset_theme_in_cfg(mid: str) -> None:
    c = _cfg()
    if c.get("theme_pack") == mid:
        c["theme_pack"] = ""
        _save(c)


def _unset_jvm_in_cfg(mid: str) -> None:
    c = _cfg()
    if c.get("_jvm_module") == mid:
        c["_jvm_module"] = ""
        c["jvm_preset"] = "default"
        c["jvm_args"] = ""
        _save(c)


def _unset_sfx_in_cfg(mid: str) -> None:
    """卸载 sfx_pack 模块：还在用它的话清掉 sfx_* 键（防残留覆盖用户后续设置）。"""
    c = _cfg()
    if c.get("_sfx_module") == mid:
        for key in ("click", "hover", "success", "error"):
            c.pop(f"sfx_{key}", None)
        c.pop("sfx_enabled", None)
        c.pop("sfx_vol", None)
        c["_sfx_module"] = ""
        _save(c)


def _unset_crash_in_cfg(mid: str) -> None:
    """卸载 crash_pol 模块：还在用它的话清掉崩溃策略（回到启动器默认行为）。"""
    c = _cfg()
    if c.get("_crash_module") == mid:
        c.pop("crash_policy", None)
        c["_crash_module"] = ""
        _save(c)


# ── 内置市场（bundled catalog + 模块包）───────────────────────────────────
CATALOG_FILE = "catalog.json"


def get_catalog_dir() -> str:
    return os.path.join(get_resource_path("assets/modules"))


def get_bundle_dir(bundle_id: str) -> str:
    return os.path.join(get_catalog_dir(), "bundle", bundle_id)


def load_catalog() -> list[dict]:
    """内置精选目录：[{id, name, name_en, type, version, author, description,
    description_en, bundle_dir}]。读取失败返回 []（市场空态，不阻塞启动）。"""
    path = os.path.join(get_catalog_dir(), CATALOG_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict) and e.get("id")]
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return []


def install_bundle(entry: dict) -> ModuleInfo:
    """从内置精选安装模块（复制 assets 下的 bundle 目录）。"""
    bid = entry.get("bundle_dir") or entry.get("id")
    src = get_bundle_dir(bid)
    if not os.path.isdir(src):
        raise ModuleError(f"内置模块包缺失：{bid}")
    return _install_from_folder(src)