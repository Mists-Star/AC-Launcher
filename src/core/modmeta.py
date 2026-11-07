"""读 jar 里的**真实模组元数据**（round-185）。

为什么必须读 jar：现在模组列表拿文件名当名字（``fabric-api-0.92.2+1.20.1``
就显示成「fabric api 0.92.2+1.20.1」），加载器徽章靠文件名里有没有 "fabric"
子串去猜。玩家装了 40 个模组时根本认不出谁是谁 —— 这是「模组页难用」的根因。

支持四种清单（按优先级探测，命中即止）：

===== ================================== ==========================
格式  路径                                 适用
===== ================================== ==========================
fabric ``fabric.mod.json``                  Fabric / Quilt 兼容层
quilt  ``quilt.mod.json``                   Quilt 原生
forge  ``META-INF/mods.toml``               Forge 1.13+ / NeoForge
legacy ``mcmod.info``                       Forge 1.12 及更早
===== ================================== ==========================

NeoForge 从 1.20.5 起改用 ``META-INF/neoforge.mods.toml``，格式与 mods.toml
一致，一并识别。

设计约束：

* **不依赖 Qt** —— 本模块只回原始字节（图标给 ``bytes``），转 QPixmap 是 UI 的事；
* **读不出来不算失败** —— 一个 jar 可能只是资源包/坏包，返回 ``None`` 让调用方
  退回文件名显示，绝不抛异常打断整个列表；
* **按 (路径, mtime, 大小) 缓存** —— 打开面板要列几十个 jar，重复解析同一文件
  是纯浪费；文件被替换（更新/启停改名）时 mtime 变化自然失效。
"""
from __future__ import annotations

import json
import os
import zipfile

try:  # Python 3.11+
    import tomllib
except Exception:  # noqa: BLE001 - 3.10 及以下没有，退化到不解析 TOML
    tomllib = None

#: 列表最大读取体积：超过 64 MB 的 jar 只读清单不读图标（防止内存爆掉）
_ICON_MAX_BYTES = 512 * 1024

_CACHE: dict[tuple, dict | None] = {}
_CACHE_MAX = 600


def _norm_authors(raw) -> list[str]:
    """作者字段四种写法统一成 ``["name", ...]``。"""
    out: list[str] = []
    if not raw:
        return out
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    if isinstance(raw, dict):
        # quilt: {"Name": {"contact": {...}}}
        return [str(k) for k in raw.keys()]
    if isinstance(raw, (list, tuple)):
        for a in raw:
            if isinstance(a, str):
                out.append(a)
            elif isinstance(a, dict):
                nm = a.get("name") or a.get("Name") or ""
                if nm:
                    out.append(str(nm))
    return out


def _pick_icon(zf: zipfile.ZipFile, path: str) -> tuple[bytes, str]:
    """从 jar 里取出图标字节；返回 ``(bytes, ext)``，取不到返回 ``(b"", "")``。"""
    if not path:
        return b"", ""
    cand = path.lstrip("/")
    try:
        info = zf.getinfo(cand)
    except KeyError:
        # 有些包写成 ./icon.png 或大小写不一致
        low = cand.lower()
        match = next((n for n in zf.namelist()
                      if n.lstrip("./").lower() == low), "")
        if not match:
            return b"", ""
        info = zf.getinfo(match)
    if info.file_size > _ICON_MAX_BYTES:
        return b"", ""
    try:
        return zf.read(info), os.path.splitext(info.filename)[1].lower()
    except OSError:
        return b"", ""


def _base(loader: str) -> dict:
    return {"id": "", "name": "", "version": "", "description": "",
            "authors": [], "loader": loader, "icon": b"", "icon_ext": "",
            "env": "", "mc": "", "source": ""}


def _from_fabric(zf: zipfile.ZipFile) -> dict:
    raw = json.loads(zf.read("fabric.mod.json").decode("utf-8", "replace"))
    d = _base("fabric")
    d["id"] = str(raw.get("id") or "")
    d["name"] = str(raw.get("name") or raw.get("id") or "")
    d["version"] = str(raw.get("version") or "")
    d["description"] = str(raw.get("description") or "")
    d["authors"] = _norm_authors(raw.get("authors") or raw.get("contributors"))
    d["env"] = str(raw.get("environment") or "")
    if isinstance(raw.get("icon"), dict):
        icons = raw["icon"]
        # 取分辨率最高的一档
        key = sorted(icons.keys(), key=lambda k: int(k) if str(k).isdigit() else 0)[-1]
        icon_path = icons[key]
    else:
        icon_path = raw.get("icon") or ""
    d["icon"], d["icon_ext"] = _pick_icon(zf, str(icon_path))
    depends = raw.get("depends") or {}
    if isinstance(depends, dict):
        d["mc"] = str(depends.get("minecraft") or "")
    d["source"] = "fabric.mod.json"
    return d


def _from_quilt(zf: zipfile.ZipFile) -> dict:
    raw = json.loads(zf.read("quilt.mod.json").decode("utf-8", "replace"))
    ql = raw.get("quilt_loader") or {}
    meta = ql.get("metadata") or {}
    d = _base("quilt")
    d["id"] = str(ql.get("id") or "")
    d["version"] = str(ql.get("version") or "")
    d["name"] = str(meta.get("name") or d["id"])
    d["description"] = str(meta.get("description") or "")
    d["authors"] = _norm_authors(meta.get("contributors"))
    icon_path = meta.get("icon") or ""
    d["icon"], d["icon_ext"] = _pick_icon(zf, str(icon_path))
    d["source"] = "quilt.mod.json"
    return d


def _from_toml(zf: zipfile.ZipFile, name: str) -> dict:
    if tomllib is None:
        return {}
    raw = tomllib.loads(zf.read(name).decode("utf-8", "replace"))
    mods = raw.get("mods") or []
    if not mods:
        return {}
    m0 = mods[0]
    d = _base("neoforge" if "neoforge" in name else "forge")
    d["id"] = str(m0.get("modId") or "")
    d["name"] = str(m0.get("displayName") or m0.get("modId") or "")
    d["version"] = str(m0.get("version") or "")
    d["description"] = str(m0.get("description") or "")
    d["authors"] = _norm_authors(m0.get("authors"))
    icon_path = m0.get("logoFile") or ""
    d["icon"], d["icon_ext"] = _pick_icon(zf, str(icon_path))
    d["source"] = name
    return d


def _from_mcmod(zf: zipfile.ZipFile) -> dict:
    raw = json.loads(zf.read("mcmod.info").decode("utf-8", "replace"))
    if isinstance(raw, dict):
        raw = raw.get("modList") or [raw]
    if not isinstance(raw, list) or not raw:
        return {}
    m0 = raw[0]
    d = _base("forge")
    d["id"] = str(m0.get("modid") or "")
    d["name"] = str(m0.get("name") or m0.get("modid") or "")
    d["version"] = str(m0.get("version") or "")
    d["description"] = str(m0.get("description") or "")
    d["authors"] = _norm_authors(m0.get("authorList") or m0.get("authors"))
    d["icon"], d["icon_ext"] = _pick_icon(zf, str(m0.get("logoFile") or ""))
    d["mc"] = str(m0.get("mcversion") or "")
    d["source"] = "mcmod.info"
    return d


#: 探测顺序：越靠前越权威（fabric 包也可能带 mcmod.info，别被它抢）
_READERS = (
    ("fabric.mod.json", _from_fabric),
    ("quilt.mod.json", _from_quilt),
    ("META-INF/neoforge.mods.toml", lambda z: _from_toml(z, "META-INF/neoforge.mods.toml")),
    ("META-INF/mods.toml", lambda z: _from_toml(z, "META-INF/mods.toml")),
    ("mcmod.info", _from_mcmod),
)


def read_meta(path: str, *, use_cache: bool = True) -> dict | None:
    """读一个 jar 的元数据；不是模组 / 读不出来返回 ``None``。

    返回键：``id / name / version / description / authors(list) / loader /
    icon(bytes) / icon_ext / env / mc / source``。
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (os.path.normcase(os.path.abspath(path)), int(st.st_mtime), st.st_size)
    if use_cache and key in _CACHE:
        return _CACHE[key]

    meta = None
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            for name, reader in _READERS:
                if name not in names:
                    continue
                try:
                    got = reader(zf)
                except Exception:  # noqa: BLE001 - 单个清单坏了不影响别的格式
                    got = {}
                if got and (got.get("id") or got.get("name")):
                    meta = got
                    break
    except (zipfile.BadZipFile, OSError, KeyError):
        meta = None

    if meta is not None:
        meta["name"] = (meta.get("name") or "").strip()
        meta["description"] = " ".join((meta.get("description") or "").split())
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = meta
    return meta


def clear_cache() -> None:
    """测试用：强制下次重新读盘。"""
    _CACHE.clear()


def display_name(path: str, meta: dict | None = None) -> str:
    """展示名：优先 jar 里的 name，读不到退回文件名（去后缀、下划线转空格）。"""
    m = meta if meta is not None else read_meta(path)
    if m and m.get("name"):
        return m["name"]
    base = os.path.basename(path)
    if base.endswith(".disabled"):
        base = base[: -len(".disabled")]
    if base.lower().endswith(".jar"):
        base = base[: -len(".jar")]
    return base.replace("_", " ").replace("-", " ").strip() or os.path.basename(path)


def search_blob(path: str, meta: dict | None = None) -> str:
    """搜索用的全部可搜文本（小写）：名称 / id / 文件名 / 描述 / 作者。"""
    m = meta if meta is not None else read_meta(path)
    parts = [os.path.basename(path)]
    if m:
        parts += [m.get("name", ""), m.get("id", ""), m.get("description", "")]
        parts += list(m.get("authors") or [])
    return " ".join(p for p in parts if p).lower()
