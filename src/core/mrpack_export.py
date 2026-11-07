"""导出 Modrinth 整合包（``.mrpack``）。

为什么需要这个文件：AC 一直只能**导入**整合包，玩家把自己调好的实例发给朋友
只能「压缩整个 .minecraft 文件夹」，几十上百 MB 的 libraries/assets 全进去，
对方解压还要自己找版本。``.mrpack`` 只写「元数据 + 非 CDN 内容」，体积小、
对方启动器能直接装。

格式要点（Modrinth ``modrinth.index.json`` v1）::

    {
      "formatVersion": 1,
      "game": "minecraft",
      "versionId": "1.0.0",
      "name": "包名",
      "summary": "简介",
      "files": [ {path, hashes:{sha1,sha512}, env, downloads:[url]} ],
      "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.11"}
    }

**为什么 files 全空、内容都放 overrides/**：``files`` 里的每一项都必须带
``downloads``（可直链下载地址）与 sha1/sha512。我们是本地已有 jar，无从反查
它来自哪个 CDN —— 硬编一个假 URL 会让对方的导入直接失败。Modrinth 规范本身
允许把「无法从 CDN 获取的内容」整体塞进 ``overrides/``（等于「随包附带」），
所以这里走 overrides-only：保真优先，代价只是没有 CDN 去重。

``minecraft_launcher_lib.mrpack.install_mrpack`` 对 overrides 的处理是原样解压，
所以导出的包用 AC 自己再导入一遍能 1:1 还原（有测试卡这条往返）。
"""
from __future__ import annotations

import json
import os
import zipfile

#: 加载器 → mrpack ``dependencies`` 里的键名（原版不写）。
LOADER_DEP = {
    "fabric": "fabric-loader",
    "quilt": "quilt-loader",
    "forge": "forge",
    "neoforge": "neoforge",
}

#: 可勾选打包的内容块：key → (相对 game_dir 的路径, 是否目录, 默认勾选)。
#: 默认只带「改了才有意义」的三样；资源包/光影/存档默认不带 —— 前两者通常
#: 单个就上百 MB，存档带别人的世界容易造成误解。
PARTS = (
    ("mods", "mods", True, True),
    ("config", "config", True, True),
    ("options", "options.txt", False, True),
    ("resourcepacks", "resourcepacks", True, False),
    ("shaderpacks", "shaderpacks", True, False),
    ("saves", "saves", True, False),
)

DEFAULT_PARTS = tuple(k for k, _p, _d, on in PARTS if on)

#: 单个内容块的大小上限：超过就跳过并在结果里报出来，避免把 3 GB 存档打进
#: 临时 zip 把磁盘写满。
MAX_PART_BYTES = 512 * 1024 * 1024

_SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", "__MACOSX"}


def default_pack_name(inst) -> str:
    """``<实例名>-<版本>``，去掉文件名非法字符。"""
    name = (getattr(inst, "name", "") or "instance").strip()
    ver = (getattr(inst, "game_version", "") or "").strip()
    raw = f"{name}-{ver}" if ver else name
    safe = "".join("_" if c in '\\/:*?"<>|' else c for c in raw).strip()
    return safe or "instance"


def _walk(root: str):
    """Yield every regular file under *root* (no symlink loops)."""
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        # 目录名排序，输出稳定（同一实例两次导出字节级可比）
        dirnames[:] = sorted(d for d in dirnames
                             if d not in _SKIP_NAMES and d != "__pycache__")
        for n in sorted(filenames):
            if n in _SKIP_NAMES:
                continue
            p = os.path.join(dirpath, n)
            try:
                if os.path.islink(p) or not os.path.isfile(p):
                    continue
            except OSError:
                continue
            yield p


def collect(inst, parts=DEFAULT_PARTS) -> tuple[list, list]:
    """收集要打包的文件。

    返回 ``(files, skipped)``：``files`` 是 ``[(归档相对路径, 绝对路径), ...]``，
    相对路径已带 ``overrides/`` 前缀；``skipped`` 是超限/读不了的块说明。
    """
    try:
        base = inst.game_dir or inst.mc_dir
    except Exception:  # noqa: BLE001 - 目录推导失败时退回 mc_dir
        base = inst.mc_dir
    base = base or ""
    out: list[tuple[str, str]] = []
    skipped: list[str] = []
    wanted = {k for k in parts}

    for key, rel, is_dir, _default in PARTS:
        if key not in wanted:
            continue
        target = os.path.join(base, rel)
        if is_dir:
            if not os.path.isdir(target):
                continue
            batch = []
            total = 0
            over = False
            for p in _walk(target):
                try:
                    total += os.path.getsize(p)
                except OSError:
                    continue
                if total > MAX_PART_BYTES:
                    over = True
                    break
                arc = os.path.relpath(p, base).replace(os.sep, "/")
                batch.append(("overrides/" + arc, p))
            if over:
                skipped.append("%s (> %d MB)" % (rel, MAX_PART_BYTES >> 20))
                continue
            out.extend(batch)
        else:
            if not os.path.isfile(target):
                continue
            out.append(("overrides/" + rel.replace(os.sep, "/"), target))
    return out, skipped


def build_index(inst, *, name: str, version_id: str, summary: str = "",
                files: list | None = None) -> dict:
    """组装 ``modrinth.index.json``。"""
    gv = (getattr(inst, "game_version", "") or "").strip()
    loader = (getattr(inst, "loader", "") or "vanilla").strip().lower()
    ldver = (getattr(inst, "loader_version", "") or "").strip()
    deps = {}
    if gv:
        deps["minecraft"] = gv
    dep_key = LOADER_DEP.get(loader)
    if dep_key and ldver:
        deps[dep_key] = ldver
    return {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": (version_id or "1.0.0").strip() or "1.0.0",
        "name": (name or default_pack_name(inst)).strip(),
        "summary": (summary or "").strip(),
        # 见模块注释：本地 jar 无从反查 CDN 地址，全部走 overrides/。
        "files": list(files or []),
        "dependencies": deps,
    }


def export_mrpack(inst, out_path: str, *, name: str = "",
                  version_id: str = "1.0.0", summary: str = "",
                  parts=DEFAULT_PARTS, progress=None,
                  callback=None) -> dict:
    """把实例写成 ``.mrpack``。返回统计字典。

    ``progress``：``(文件名, 已完成, 总数) -> None``，给测试/直调用的回调。

    ``callback``：mll 风格的进度字典（``setStatus`` / ``setProgress`` /
    ``setMax``）。``ProgressWorker`` 会把这个关键字自动注进来，UI 因此不用
    另开一套信号。两个回调互不干扰。

    抛 ``ValueError`` 表示「这台实例根本导不出」（没游戏版本 / 什么都没勾）；
    其余异常（磁盘满、权限）原样上抛，由调用方提示。
    """
    gv = (getattr(inst, "game_version", "") or "").strip()
    if not gv:
        raise ValueError("instance has no game version")

    files, skipped = collect(inst, parts)
    if not files:
        raise ValueError("nothing to pack")

    index = build_index(inst, name=name, version_id=version_id,
                        summary=summary)

    out_path = os.path.abspath(out_path)
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    total = len(files)

    def _emit(fname: str, done: int) -> None:
        if callback:
            try:
                callback.get("setStatus")(fname)
                callback.get("setMax")(total)
                callback.get("setProgress")(done)
            except Exception:  # noqa: BLE001 - 进度回调不该影响导出
                pass
        if progress is not None:
            try:
                progress(fname, done, total)
            except Exception:  # noqa: BLE001
                pass

    written = 0
    total_bytes = 0
    # 先写 index.json —— 有些工具只读第一个条目，顺序不影响正确性，但这样
    # 出问题时压缩包里至少能看出这是什么包。
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        z.writestr("modrinth.index.json",
                   json.dumps(index, ensure_ascii=False, indent=2))
        for arc, src in files:
            try:
                z.write(src, arc)
            except OSError:
                # 单个文件读不了（被占用/权限）不该整包失败，跳过并记账
                skipped.append(os.path.basename(src))
                continue
            written += 1
            try:
                total_bytes += os.path.getsize(src)
            except OSError:
                pass
            _emit(os.path.basename(src), written)

    return {
        "path": out_path,
        "files": written,
        "bytes": total_bytes,
        "size": os.path.getsize(out_path) if os.path.isfile(out_path) else 0,
        "skipped": skipped,
        "name": index["name"],
        "version": index["versionId"],
        "dependencies": index["dependencies"],
    }
