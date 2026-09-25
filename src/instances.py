"""Instance data model + manager.

An *instance* is a self-contained game configuration: one game version, one
mod loader (or vanilla), and an isolated .minecraft directory. Each profile
keeps its own mods & saves just like a separate game folder.

round-78 storage: per-instance full files under data/instances/<id>.json +
a summary index data/instances.index.json (portable, live beside the exe).
Legacy single-file data/instances.json is auto-migrated on first load.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

from .paths import get_data_dir

LOADERS = [
    "vanilla", "fabric", "forge", "quilt", "neoforge", "liteloader",
    "legacyfabric", "cleanroom", "optifine",
]


class _CopyFailed(Exception):
    """Raised by import_external('copy') when the file copy fails.

    The caller (scan dialog) catches this and transparently falls back to a
    link/in-place takeover so the import still succeeds.
    """


@dataclass
class Instance:
    id: str
    name: str
    game_version: str
    loader: str = "vanilla"
    loader_version: str = ""
    # version_id: the versions/<id> folder name. Empty for AC-created instances
    # (where game_version IS the folder id). For imported instances this may
    # differ from game_version (e.g. folder "1.20.1-forge-47.2.0" vs base
    # "1.20.1") and is what minecraft-launcher-lib resolves versions by.
    version_id: str = ""
    # kind: how the instance was stored on disk when imported
    #   ("standard" | "mmc" | "curseforge" | "modrinth"); "" for AC-created.
    kind: str = ""
    # launcher: the source launcher this instance was taken over from
    #   ("PCL-CE" | "HMCL" | "Prism" | "MultiMC" | "CurseForge" | "Modrinth" |
    #    "BakaXL" | "TLauncher" | "Other" | "AC" for AC-created).
    # Drives the source badge on home cards (direction A: 控制中枢叙事).
    # 品牌码内部保留（用于识别目录布局）；对外展示走 launcher_label()——
    # 导入实例显示来源名，AC 自建实例不显示来源。
    launcher: str = "AC"
    # needs_convert: True when the imported game dir had no directly-launchable
    # version json (Integrations/CurseForge/Modrinth). Conversion happens at
    # launch via install_instance.
    needs_convert: bool = False
    created_at: str = ""
    # java_path: per-instance Java executable. Empty ⇒ fall back to the global
    # launcher setting. Lets one instance force a specific JDK (e.g. older Forge
    # on Java 8, newer vanilla on Java 21) without changing the global default.
    java_path: str = ""
    # round-42 实例级覆盖（对齐主流做法）：0/空 = 用全局设置
    ram_mb: int = 0       # 0 = 全局 ram_mb
    jvm_args: str = ""    # 空 = 全局 jvm_args
    # round-53 实例级渲染器（对齐主流版本设置 → 渲染器）：
    #   "auto" = 不动（默认）；"software" = 软件 OpenGL 兜底（老显卡/虚拟机）；
    #   "legacy" = 旧 LWGJL 驱动兼容（关共享上下文，防旧驱动崩）。
    # 仅对 LWJGL2 老版本（≤1.12.2 系）有意义，1.13+ 注入无害（参数被忽略）。
    renderer: str = "auto"
    # round-53 实例级实验性 GC（对齐主流「性能」高级设置）。默认开 G1GC。
    perf_g1gc: bool = True              # -XX:+UseG1GC 优化参数组
    perf_disable_explicit_gc: bool = False  # -XX:+DisableExplicitGC
    # round-55 启动高级设置（对齐主流「启动游戏/版本设置」）：空值 = 跟随全局
    game_args: str = ""          # 游戏附加参数（追加到游戏启动参数末尾，--server <ip> 直连）
    jvm_preset: str = ""         # "" = 跟随全局；"default"/"aikar"/"custom" 覆盖全局预设
    isolation: str = ""          # "" = 跟随全局；"isolated" = 版本隔离；"custom" = 自定义游戏目录
    game_dir_override: str = ""  # isolation == "custom" 时的自定义游戏目录（绝对路径）
    post_launch_cmd: str = ""    # 游戏进程启动后执行的命令，空 = 跟随全局
    exit_cmd: str = ""           # 游戏进程退出后执行的命令，空 = 跟随全局
    # round-42 实例分组（对齐主流分组/筛选）：空 = 未分组
    group: str = ""
    # round-82 启动格式（磁盘布局，驱动版本 json / 游戏目录解析）：
    #   "" / "auto" = 自适应：启动/展示时实时检测（见 detect_format）；
    #   "vanilla" 原版共享 .minecraft；"iso" 外来版本隔离（导入）；
    #   "multimc" 整合布局；"curseforge" CurseForge；"modrinth" Modrinth；
    #   "custom" 玩家手动强制（仍按标准布局解析，改装目录靠特征兜底自适应）
    format: str = ""
    # external=True means this instance links to an existing .minecraft on
    # disk (imported from another launcher) — removing it must NOT delete the
    # user's real game files, only the AC metadata entry.
    external: bool = False
    # path is derived, not stored
    _base: str = field(default="", repr=False, compare=False)

    @property
    def root(self) -> str:
        """Instance root directory (contains .minecraft).

        round-49 修复：**不得**改写 ``_base``。旧实现把 ``data/instances/<id>``
        写回 ``_base``，会让 AC 原生实例（``_base`` 空）第一次访问 ``mc_dir``
        得到 ``<id>/.minecraft``、之后却变成 ``<id>``（丢了 .minecraft），导致
        模组/游戏文件路径前后不一致（N5 模组预检即由此误判）。``_base`` 的
        语义是「mc_dir 本身」，只允许由注册/导入路径显式赋值；此处只读取。
        """
        if self._base:
            # _base 即 mc_dir：其父目录才是「含 .minecraft（或版本目录）的根」
            return os.path.dirname(self._base)
        return os.path.join(get_data_dir(), "instances", self.id)

    @property
    def mc_dir(self) -> str:
        """The .minecraft directory minecraft-launcher-lib expects.

        round-34 修复：_base 语义统一为「游戏目录本身」（mc_dir）——
        - 导入/链接实例：_base 直接存 mc_dir（隔离版本目录 或 .minecraft 目录）
        - AC 自有实例：_base 空 → data/instances/<id>/.minecraft（标准布局）
        之前标准布局导入存的是 dirname(mc_dir)（父目录），mc_dir property
        又误判 basename≠".minecraft" 走"隔离"分支，导致 mc_dir 变成父目录
        （如 %APPDATA%\\Roaming），游戏文件装错位置。
        """
        if self._base:
            return self._base
        return os.path.join(self.root, ".minecraft")

    @property
    def game_dir(self) -> str:
        """当前生效的游戏数据目录（感知版本隔离，round-57 统一入口）。

        与 ``launch.resolve_game_dir`` 规则一一对应：实例级 ``isolation`` 为空
        回退全局 ``version_isolation``；isolated → ``versions/<版本>``；
        custom → 自定义目录（相对路径按 ``<mc_dir>/<值>`` 解析，保证确定性，
        避免相对路径被解释成启动器进程 CWD 下）。

        存档/模组/资源包/光影/商店下载等 UI 与游戏实际读写路径统一由本属性
        派生，杜绝「UI 操作目录 ≠ 游戏读取目录」的脱节（round-56 只修了 mods）。
        """
        iso = (self.isolation or "").strip()
        if not iso:
            try:
                from .settings_dialog import load_config
                iso = (load_config().get("version_isolation") or "default")
            except Exception:  # noqa: BLE001 - 配置读取失败仅回退默认
                iso = "default"
        if iso == "isolated":
            sub = self.version_id or self.game_version
            # round-78 其他启动器版本隔离（导入）：mc_dir 本身就是
            # versions/<id> 隔离目录，真实版本 json 躺在 mc_dir/<sub>.json。
            # 再套一层 versions/<sub> 会指向不存在的嵌套目录（存档/模组 UI 与
            # 游戏实际读写路径脱节，启动还会触发假补全）。此时隔离目录即游戏目录。
            try:
                if os.path.isfile(os.path.join(self.mc_dir, f"{sub}.json")):
                    return self.mc_dir
            except OSError:
                pass
            return os.path.join(self.mc_dir, "versions", sub)
        if iso == "custom":
            custom = (self.game_dir_override or "").strip()
            if custom:
                if not os.path.isabs(custom):
                    custom = os.path.normpath(os.path.join(self.mc_dir, custom))
                else:
                    custom = os.path.normpath(custom)
                return custom
        return self.mc_dir

    @property
    def mods_dir(self) -> str:
        """当前生效的模组目录（感知版本隔离，round-56 修）。

        对齐 ``launch.resolve_game_dir`` 的规则：实例级 ``isolation`` 为空时
        跟随全局 ``version_isolation``；isolated → ``versions/<版本>/mods``，
        custom → 自定义目录下的 ``mods``。否则默认 ``mc_dir/mods``。

        之前模组页/更新器/整合包导入固定写 ``mc_dir/mods``，而隔离模式下
        游戏实际读取 ``game_dir/mods`` —— 两边脱节，用户装的模组游戏里
        永远不生效。现在统一由 ``game_dir`` 属性给出「游戏真正会读的」目录。
        """
        return os.path.join(self.game_dir, "mods")

    def ensure_dirs(self) -> None:
        os.makedirs(self.mc_dir, exist_ok=True)
        os.makedirs(self.mods_dir, exist_ok=True)
        # round-48 共享 libraries 去重：AC 自有实例把 <mc_dir>/libraries 指到
        # 全局共享池（目录联接）。external（链接他人目录）实例绝不改用户真实文件。
        if not self.external:
            try:
                from .core.shared_libs import ensure_shared_libraries
                ensure_shared_libraries(self.mc_dir)
            except Exception:  # noqa: BLE001 - 去重失败只是退回独立目录，不阻塞
                pass

    @staticmethod
    def _strip_library_junction(mc_dir: str) -> None:
        """删除实例目录里的 libraries 联接 <链接>，避免误删共享池。删除实例前调用。"""
        try:
            from .core.shared_libs import _remove_junction
            _remove_junction(os.path.join(mc_dir, "libraries"))
        except Exception:  # noqa: BLE001
            pass


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# 来源启动器 → 中性展示名（品牌码内部保留，界面默认不出现第三方品牌，
# 作为 launcher_label(show_original=False) 的兜底）。
LAUNCHER_LABELS = {
    "PCL-CE": "导入",
    "HMCL": "导入",
    "Prism": "导入",
    "MultiMC": "导入",
    "PolyMC": "导入",
    "CurseForge": "导入",
    "Modrinth": "导入",
    "BakaXL": "导入",
    "TLauncher": "导入",
    "Official": "官方",
    "Other": "导入",
}

# 来源启动器 → 原始展示名（round-86：用户允许「从其他启动器导入的实例
# 显示来源」，launcher_label(show_original=True) 时使用）。
LAUNCHER_NAMES = {
    "PCL-CE": "PCL2",
    "HMCL": "HMCL",
    "Prism": "Prism Launcher",
    "MultiMC": "MultiMC",
    "PolyMC": "PolyMC",
    "CurseForge": "CurseForge",
    "Modrinth": "Modrinth App",
    "BakaXL": "BakaXL",
    "TLauncher": "TLauncher",
    "Official": "官方",
    "Other": "其他",
}


def launcher_label(launcher: str, show_original: bool = False) -> str:
    """把内部来源启动器品牌码映射为界面展示名。

    - show_original=True（导入实例）：已知来源返回其原始启动器名
      （如 import from PCL-CE → "PCL2"）；未知码照实显示；AC 返回 ""（无来源）。
    - show_original=False（默认，中性化兜底）：统一为「导入」/「官方」。
    """
    code = launcher or "AC"
    if show_original:
        return LAUNCHER_NAMES.get(code, "" if code == "AC" else code)
    return LAUNCHER_LABELS.get(code, "AC" if code == "AC" else "导入")


def _copied_with_progress(
    src: str, dst: str, on_progress: "Callable[[int, int, str], bool]"
) -> bool:
    """Copy ``src`` into ``dst`` (like ``shutil.copytree(..., dirs_exist_ok=True)``)
    but call ``on_progress(copied, total, current_file)`` after each file. The
    callback returns ``False`` to abort (raises OSError so the caller can
    surface the abort as a _CopyFailed fallback).

    Two-pass approach: walk first to count, then copy. Cheap for the sizes
    we're dealing with (a few GB at most) and keeps the API simple.
    """
    files: list[tuple[str, str]] = []
    src_len = len(src.rstrip(os.sep)) + 1
    for dirpath, _dirnames, filenames in os.walk(src):
        for fn in filenames:
            ap = os.path.join(dirpath, fn)
            files.append((ap, ap[src_len:]))
    total = len(files)
    on_progress(0, total, "")
    copied = 0
    for abs_src, rel in files:
        rel_dir = os.path.dirname(rel)
        out_dir = os.path.join(dst, rel_dir) if rel_dir else dst
        os.makedirs(out_dir, exist_ok=True)
        shutil.copy2(abs_src, os.path.join(out_dir, os.path.basename(rel)))
        copied += 1
        if on_progress(copied, total, rel) is False:
            raise OSError("Copy aborted by caller")
    on_progress(total, total, "")
    return True


# round-82 启动格式（磁盘布局分类）。
# "auto" = 自适应（启动/展示时实时探测，目录变化自动跟上）；
# 其余为玩家可手动指定的具体格式。UI 徽章颜色/label 见 pages_instances。
INSTANCE_FORMATS = (
    "auto", "vanilla", "iso", "multimc", "curseforge", "modrinth", "custom",
)


def detect_format(inst) -> str:
    """判定实例的启动格式（round-82）。

    优先级：
    1. 玩家已手动指定（format 非空且非 auto）→ 直接用；
    2. 自适应（auto / 空）→ ``_probe_format`` 按磁盘特征实时探测：
       MMC 布局（mmc-pack.json）> 外来版本隔离（导入，
       mc_dir 内直接躺 <version>.json）> CurseForge（minecraftinstance.json）
       > Modrinth（modrinth.json 等）> 兜底原版标准布局。

    返回始终是 INSTANCE_FORMATS 之一；特征全不符时视为原版标准布局——
    改装/奇怪目录由 versions_root 的 <id>.json 特征兜底自适应（round-78）。
    """
    fmt = (getattr(inst, "format", "") or "").strip() or "auto"
    if fmt != "auto":
        return fmt if fmt in INSTANCE_FORMATS else "auto"
    return _probe_format(inst)


def _probe_format(inst) -> str:
    """磁盘特征探测：不修改实例，纯只读判断。"""
    mc = getattr(inst, "mc_dir", "") or ""
    if not mc or not os.path.isdir(mc):
        return "vanilla"
    parent = os.path.dirname(os.path.normpath(mc))
    mine = os.path.join(mc, ".minecraft")
    # 1) MMC 布局：mmc-pack.json 实例根 / .minecraft / 上级实例目录
    for cand in (os.path.join(mc, "mmc-pack.json"),
                 os.path.join(mine, "mmc-pack.json"),
                 os.path.join(parent, "mmc-pack.json")):
        if os.path.isfile(cand):
            return "multimc"
    # 2) 外来版本隔离（其他启动器隔离导入）：mc_dir 就是 versions/<id> 目录
    #    本身，真实 json 扁平躺在 <mc>/<version>.json（而非 versions/<v>/<v>.json）
    version = (getattr(inst, "version_id", "") or getattr(inst, "game_version", ""))
    if version and os.path.isfile(os.path.join(mc, f"{version}.json")):
        return "iso"
    # 3) CurseForge：minecraftinstance.json（实例根 / .minecraft / 上级）
    for cand in (os.path.join(mc, "minecraftinstance.json"),
                 os.path.join(mine, "minecraftinstance.json"),
                 os.path.join(parent, "minecraftinstance.json")):
        if os.path.isfile(cand):
            return "curseforge"
    # 4) Modrinth App：modrinth.json / modrinth.index.json / instance.cfg
    for cand in ("modrinth.json", "modrinth.index.json", "instance.cfg"):
        if os.path.isfile(os.path.join(mc, cand)):
            return "modrinth"
    # 5) 原版标准布局兜底（shared .minecraft / versions 在根下）
    return "vanilla"


class InstancesManager:
    # round-78 存储升级：单文件 data/instances.json → 拆分
    #   data/instances/<id>.json     每实例全量（真理源，独占文件，原子写）
    #   data/instances.index.json    摘要索引（渲染字段，启动秒开；lazy 全量）
    # 旧版单文件首次启动一次性迁移后改名 .legacy.bak。
    def __init__(self):
        self._dir = os.path.join(get_data_dir(), "instances")
        self._index_path = os.path.join(get_data_dir(), "instances.index.json")
        self._legacy_path = os.path.join(get_data_dir(), "instances.json")
        self._instances: dict[str, Instance] = {}
        self._current: Optional[str] = None
        # 已从 <id>.json 补齐全量字段的实例（其余仅摘要字段在内存）
        self._full_ids: set[str] = set()
        self._load()

    # ---- persistence ----
    def refresh(self) -> None:
        """Reload the on-disk instance list. Useful when the user copies a
        new instance folder in from outside AC and wants the launcher to
        pick it up without restarting."""
        self._load()

    # ------------------------------------------------------------- 读取
    def _load(self) -> None:
        """实例化内存状态（round-78）。

        优先读摘要索引（快）；index 缺失/损坏 → glob 全量重建；
        旧单文件 → 迁移。索引与文件 diff 时以 <id>.json（真理源）为准：
        - 文件在、摘要缺 → 补全
        - 摘要条目文件已丢 → 剔出（避免"幽灵实例"）
        """
        self._instances = {}
        self._full_ids = set()
        self._current = None

        # 1) 旧格式迁移：新目录还没有任何文件 + 旧单文件存在
        if not self._has_new_files() and os.path.exists(self._legacy_path):
            self._migrate_legacy()
            return

        # 2) 摘要索引路径
        index = self._read_index()
        if index:
            for iid, raw in index.get("instances", {}).items():
                if not iid or self._instances.get(iid):
                    continue
                inst = self._from_dict(raw, iid=iid)
                if inst.id:
                    self._instances[inst.id] = inst
            self._current = index.get("current")
            if os.path.isdir(self._dir):
                for fn in sorted(os.listdir(self._dir)):
                    if not fn.endswith(".json"):
                        continue
                    iid = fn[:-5]
                    if iid in self._instances:
                        # 文件在但摘要缺全量字段：保持摘要（渲染够用）
                        continue
                    full = self._read_full(iid)
                    if full is not None:
                        self._instances[iid] = full
                        self._full_ids.add(iid)
                # 反噬：摘要条目文件已丢 → 剔除
                for iid in list(self._instances):
                    if iid not in self._full_ids and not os.path.exists(
                            os.path.join(self._dir, f"{iid}.json")):
                        del self._instances[iid]
            if self._current and self._current not in self._instances:
                self._current = next(iter(self._instances), None)
            return

        # 3) 全量重建（index 缺失/损坏）：glob 目录
        if os.path.isdir(self._dir):
            for fn in sorted(os.listdir(self._dir)):
                if not fn.endswith(".json"):
                    continue
                iid = fn[:-5]
                full = self._read_full(iid)
                if full is not None:
                    self._instances[iid] = full
                    self._full_ids.add(iid)
        self._write_index()

    def _has_new_files(self) -> bool:
        if not os.path.isdir(self._dir):
            return False
        try:
            return any(fn.endswith(".json") for fn in os.listdir(self._dir))
        except OSError:
            return False

    def _migrate_legacy(self) -> None:
        """旧版单文件 → 每实例 <id>.json；完成后改名备份。"""
        try:
            with open(self._legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return
        os.makedirs(self._dir, exist_ok=True)
        for raw in data.get("instances", []):
            if not (isinstance(raw, dict) and raw.get("id") and raw.get("name")
                    and raw.get("game_version")):
                continue
            try:
                self._write_inst_file(raw)  # raw 即全量 dict（含 _base）
            except OSError:
                continue
        self._current = data.get("current")
        self._load()
        try:
            os.replace(self._legacy_path, self._legacy_path + ".legacy.bak")
        except OSError:
            pass

    def _read_index(self) -> dict | None:
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("instances"), dict):
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
        return None

    def _read_full(self, iid: str) -> Instance | None:
        p = os.path.join(self._dir, f"{iid}.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return None
        if not (isinstance(raw, dict) and raw.get("id") and raw.get("name")
                and raw.get("game_version")):
            return None
        return self._from_dict(raw, iid=iid)

    def _ensure_full(self, iid: str) -> Optional[Instance]:
        """按需读 <id>.json 补齐全量字段并缓存（round-78 lazy 读取）。

        摘要对象的高级字段默认"跟随全局"，此方法在有真实需求（启动/
        备份/设置）前触发，费用为一次小文件读。全量文件丢失时退回摘要。
        """
        inst = self._instances.get(iid)
        if inst is None or iid in self._full_ids:
            return inst
        full = self._read_full(iid)
        if full is not None:
            self._instances[iid] = full
            self._full_ids.add(iid)
            return full
        return inst

    @staticmethod
    def _from_dict(raw: dict, iid: str = "") -> Instance:
        """dict → Instance（round-34/40 加固保留：脏数据缺 id/name/
        game_version 一律跳过；未知键忽略）。

        摘要文件缺的字段落在默认值上（=「跟随全局」语义），由
        _ensure_full 补齐为真值。
        """
        return Instance(
            id=raw.get("id") or iid,
            name=raw.get("name", ""),
            game_version=raw.get("game_version", ""),
            loader=raw.get("loader", "vanilla"),
            loader_version=raw.get("loader_version", ""),
            version_id=raw.get("version_id", ""),
            kind=raw.get("kind", ""),
            needs_convert=raw.get("needs_convert", False),
            created_at=raw.get("created_at", ""),
            java_path=raw.get("java_path", ""),
            ram_mb=raw.get("ram_mb", 0) or 0,
            jvm_args=raw.get("jvm_args", "") or "",
            renderer=raw.get("renderer", "auto") or "auto",
            perf_g1gc=bool(raw.get("perf_g1gc", True)),
            perf_disable_explicit_gc=bool(raw.get("perf_disable_explicit_gc", False)),
            game_args=raw.get("game_args", "") or "",
            jvm_preset=raw.get("jvm_preset", "") or "",
            isolation=raw.get("isolation", "") or "",
            game_dir_override=raw.get("game_dir_override", "") or "",
            post_launch_cmd=raw.get("post_launch_cmd", "") or "",
            exit_cmd=raw.get("exit_cmd", "") or "",
            group=raw.get("group", "") or "",
            # round-82 启动格式：空 / auto = 自适应（实时探测），见 detect_format
            format=raw.get("format", "") or "",
            external=raw.get("external", False),
            _base=raw.get("_base", ""),
            launcher=raw.get("launcher", "AC"),
        )

    @staticmethod
    def _to_dict(inst: Instance) -> dict:
        """Instance → 持久化 dict（含 _base）。"""
        return {**asdict(inst), "_base": inst._base}

    # 摘要索引只存「UI 渲染 + 路径派生」字段，启动/右键/详情用 get() 触发
    # _ensure_full 读全量——索引保持小体积，列表秒开。
    _SUMMARY_KEYS = (
        "id", "name", "game_version", "loader", "loader_version",
        "version_id", "kind", "launcher", "needs_convert", "group",
        "format",  # round-82 启动格式：摘要即存，懒加载实例也能渲染徽章
        "external", "created_at", "_base",
    )

    def _summary(self, inst: Instance) -> dict:
        d = self._to_dict(inst)
        return {k: d[k] for k in self._SUMMARY_KEYS if k in d}

    # ------------------------------------------------------------- 写入
    def _write_inst_file(self, raw: dict) -> None:
        """原子写单个实例文件（独占文件：一个实例写坏不影响其他实例）。"""
        os.makedirs(self._dir, exist_ok=True)
        tmp = os.path.join(self._dir, f".{raw.get('id')}.json.tmp")
        final = os.path.join(self._dir, f"{raw.get('id')}.json")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
            os.replace(tmp, final)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise

    def _write_index(self) -> None:
        """原子写摘要索引（小：只含渲染字段）。"""
        os.makedirs(self._dir, exist_ok=True)
        data = {
            "schema": 2,
            "current": self._current,
            "instances": {
                iid: self._summary(inst)
                for iid, inst in self._instances.items()
            },
        }
        tmp = self._index_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._index_path)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise

    def _persist(self, inst: Instance | None = None, *, dropped: str = "") -> None:
        """统一持久化入口：写（inst）或删（dropped）单实例文件 + 重写索引。"""
        if inst is not None:
            self._write_inst_file(self._to_dict(inst))
        elif dropped:
            p = os.path.join(self._dir, f"{dropped}.json")
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        self._write_index()

    def _save(self, inst: Instance | None = None) -> None:
        """兼容旧调用点（mgr._save()）：无参时按内存状态全量落盘。

        round-78 拆分存储后旧 `_save()` 语义「整库全量写」仍被部分外部调用
        （modpack_import、pages_instances 等）依赖，它们改完字段不传实例。
        这里无参 = 把所有实例全量文件重写一遍 + 重建索引，等价旧行为；
        传了实例则走单文件原子写，两者都保证磁盘全量文件与内存一致。
        """
        if inst is not None:
            if inst.id in self._instances:
                self._instances[inst.id] = inst
            self._persist(inst)
            return
        for iid, one in self._instances.items():
            self._write_inst_file(self._to_dict(one))
        self._write_index()

    # ---- api ----
    def list(self) -> list[Instance]:
        return list(self._instances.values())

    def get(self, instance_id: str) -> Optional[Instance]:
        return self._ensure_full(instance_id)

    def add(
        self,
        name: str,
        game_version: str,
        loader: str = "vanilla",
        loader_version: str = "",
        java_path: str = "",
    ) -> Instance:
        inst = Instance(
            id=_new_id(),
            name=name,
            game_version=game_version,
            loader=loader if loader in LOADERS else "vanilla",
            loader_version=loader_version,
            java_path=java_path or "",
        )
        inst.ensure_dirs()
        self._instances[inst.id] = inst
        if self._current is None:
            self._current = inst.id
        self._persist(inst)
        return inst

    @staticmethod
    def _copy_name(src_name: str) -> str:
        """克隆默认名：走 i18n（英文界面显示 "(Copy)"）。round-45。"""
        try:
            from .i18n import t as _t
            return _t("instances.copy_suffix", default="（副本）") \
                if False else _t("instances.copy_name",
                                 default="{name}（副本）").format(name=src_name)
        except Exception:
            return f"{src_name} (Copy)"

    def save(self, inst: Instance) -> None:
        """Persist an existing instance after in-place modification
        (e.g. apply_mrpack_to_instance 更新了 version_id/loader)。round-38。"""
        if inst.id in self._instances:
            self._instances[inst.id] = inst
            self._persist(inst)

    def duplicate(self, inst_id: str, new_name: str = "") -> Instance | None:
        """克隆实例（round-42，对齐主流 Ctrl+D）：复制游戏目录 + 元数据。

        - 目录复制用 copytree（大实例较慢，调用方放 Worker 或提示）
        - 新实例：新 id、名称默认 "原名称 (副本)"、继承 java/ram/jvm/group
        - 源实例是 external（链接到他人目录）时只复制元数据不复制目录？
          不行——克隆必须有独立目录，仍复制（防止误改原目录）。
        Returns 新实例；失败抛异常（调用方提示）。
        """
        src = self._instances.get(inst_id)
        if src is None:
            return None
        import shutil
        new_id = _new_id()
        new_root = os.path.join(get_data_dir(), "instances", new_id)
        # 复制游戏目录（mc_dir → 新实例的 mc_dir）；round-48 跳过 libraries
        #（它要么是去重池联接、要么会被 ensure_dirs 重建成联接，复制反而把池盖一遍）
        dst_mc = os.path.join(new_root, ".minecraft")
        shutil.copytree(src.mc_dir, dst_mc, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("libraries"))
        inst = Instance(
            id=new_id,
            name=(new_name.strip() or self._copy_name(src.name)),
            game_version=src.game_version,
            loader=src.loader,
            loader_version=src.loader_version,
            version_id=src.version_id,
            kind=src.kind,
            needs_convert=src.needs_convert,
            created_at=src.created_at,
            java_path=src.java_path,
            ram_mb=src.ram_mb,
            jvm_args=src.jvm_args,
            renderer=src.renderer,
            perf_g1gc=src.perf_g1gc,
            perf_disable_explicit_gc=src.perf_disable_explicit_gc,
            game_args=src.game_args,
            jvm_preset=src.jvm_preset,
            # round-56 修重：复制实例必须得到独立数据目录。若沿用源的
            # isolation/game_dir_override，副本与源共享同一版本的存
            # 档/模组/自定义目录，两个实例共写一份数据（复制意图落空）。
            # 副本回退全局隔离（一般用户=共享、数据本来就一笔），明确隔离
            # 需求的用户在副本设置里重开——与「复制」的独立性语义一致。
            isolation="",
            game_dir_override="",
            post_launch_cmd=src.post_launch_cmd,
            exit_cmd=src.exit_cmd,
            group=src.group,
            external=False,
            launcher="AC",
        )
        inst.ensure_dirs()
        self._instances[inst.id] = inst
        self._persist(inst)
        return inst

    def import_external(
        self,
        *,
        mc_dir: str,
        name: str,
        game_version: str,
        loader: str = "vanilla",
        loader_version: str = "",
        version_id: str = "",
        kind: str = "standard",
        needs_convert: bool = False,
        mode: str = "link",
        java_path: str = "",
        launcher: str = "",
        on_progress: "Callable[[int, int, str], bool] | None" = None,
    ) -> Instance:
        """Import an instance discovered inside another launcher.

        ``mode`` chooses how the game files are handled:
          · "link" — point AC at the original game folder *in place*. No copy is
            made and the instance is marked ``external=True`` (so removing it
            later only drops AC's metadata, never the user's real files). If the
            instance ``needs_convert``, the first launch will write version files
            into the *other* launcher's directory — exactly the "直接操控启动器
            资源" choice the user explicitly opted into.
          · "copy" — duplicate the whole game folder into AC's data dir so the
            two launchers are fully independent (``external=False``). Conversion
            (if needed) is handled at launch time by ``install_instance``, which
            downloads the base version + mod loader into the copy. On any copy
            error we raise ``_CopyFailed`` so the caller can fall back to "link".

        ``on_progress`` (copy mode only) receives ``(copied, total, current_file)``
        after each file copy. Return ``False`` from the callback to abort.

        ``kind`` / ``needs_convert`` are stored on the instance for diagnostics
        and future batch-repair; they do not change launch behaviour here.
        """
        mc_dir = os.path.normpath(mc_dir)
        loader = loader if loader in LOADERS else "vanilla"

        if mode == "copy":
            # round-98：复制「版本隔离」实例必须保留 versions/<id>/ 层级。
            # 扫描出的隔离实例（PCL2 等开启版本隔离）其 mc_dir 就是
            # versions/<id> 目录本身，目录内既有 <id>.json（启动所需）又有
            # saves/mods（游戏数据）。旧实现把它拍平到 <new>/.minecraft/*，
            # 产物既不是标准 .minecraft 也不是版本目录：_probe_format 因
            # <mc>/<id>.json 存在判为 "iso" → versions_root 指到实例目录的
            # 上级 → mll 按 <root>/versions/<id>/<id>.json 解析必然
            # VersionNotFound（玩家看到「版本不存在 / 文件不见了」，而磁盘上
            # 文件其实都在）。保留层级后 mll 直接食用玩家真实 json，且标记
            # 版本隔离让存档/模组仍落在该版本目录。
            isolated_src = bool(version_id) and os.path.isfile(
                os.path.join(mc_dir, f"{version_id}.json"))
            inst = Instance(
                id=_new_id(),
                name=name,
                game_version=game_version,
                loader=loader,
                loader_version=loader_version,
                version_id=version_id,
                kind=kind,
                needs_convert=needs_convert,
                java_path=java_path or "",
                isolation="isolated" if isolated_src else "",
                external=False,
                launcher=launcher or "Other",
            )
            inst.ensure_dirs()  # creates data/instances/<id>/.minecraft
            dst_mc = (os.path.join(inst.mc_dir, "versions", version_id)
                      if isolated_src else inst.mc_dir)
            os.makedirs(dst_mc, exist_ok=True)
            try:
                if on_progress is not None:
                    _copied_with_progress(mc_dir, dst_mc, on_progress)
                else:
                    shutil.copytree(mc_dir, dst_mc, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("libraries"))
            except (OSError, shutil.Error) as e:  # fall back to in-place link
                shutil.rmtree(inst.root, ignore_errors=True)
                raise _CopyFailed(str(e)) from e
        else:  # link / in-place takeover
            # round-34 修复：_base 统一存「游戏目录本身」（mc_dir）——
            # 隔离实例（版本目录即游戏目录）存 mc_dir；标准布局存 .minecraft
            # 目录本身。之前标准布局存 dirname(mc_dir)（父目录）导致
            # mc_dir property 误判为隔离目录返回父目录（P1-2）。
            inst = Instance(
                id=_new_id(),
                name=name,
                game_version=game_version,
                loader=loader,
                loader_version=loader_version,
                version_id=version_id,
                kind=kind,
                needs_convert=needs_convert,
                java_path=java_path or "",
                external=True,
                _base=mc_dir,
                launcher=launcher or "Other",
            )
            inst.ensure_dirs()  # no-op if the dirs already exist

        self._instances[inst.id] = inst
        if self._current is None:
            self._current = inst.id
        self._persist(inst)
        return inst

    def remove(self, instance_id: str) -> None:
        inst = self._instances.pop(instance_id, None)
        if inst is not None:
            # Never delete a user's real game folder for a linked (imported)
            # instance — only drop the AC metadata entry.
            if not inst.external:
                import shutil

                # round-48 先摘掉 libraries 联接（链接是跟共享池耦合的，直接 rmtree
                # 可能顺着 reparse point 误删整个共享池）。去重池本身单独管理。
                inst._strip_library_junction(inst.mc_dir)
                shutil.rmtree(inst.root, ignore_errors=True)
        if self._current == instance_id:
            self._current = next(iter(self._instances), None)
        self._persist(dropped=instance_id)

    @property
    def current_id(self) -> Optional[str]:
        return self._current

    def current(self) -> Optional[Instance]:
        return self._instances.get(self._current) if self._current else None

    def set_current(self, instance_id: str) -> None:
        if instance_id in self._instances:
            self._current = instance_id
            self._persist()  # 只重写索引（current 变）


# module-level singleton (one manager per process)
_manager = InstancesManager()


def manager() -> InstancesManager:
    return _manager
