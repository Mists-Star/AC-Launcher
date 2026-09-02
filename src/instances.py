"""Instance data model + manager.

An *instance* is a self-contained game configuration: one game version, one
mod loader (or vanilla), and an isolated .minecraft directory. This mirrors how
PCL2 / HMCL organise things and lets each profile keep its own mods & saves.

State is persisted to data/instances.json (portable, lives beside the exe).
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
    #   ("PCL2" | "HMCL" | "Prism" | "MultiMC" | "CurseForge" | "Modrinth" |
    #    "BakaXL" | "TLauncher" | "Other" | "AC" for AC-created).
    # Drives the source badge on home cards (direction A: 控制中枢叙事).
    launcher: str = "AC"
    # needs_convert: True when the imported game dir had no directly-launchable
    # version json (MultiMC/Prism/CurseForge/Modrinth). Conversion happens at
    # launch via install_instance.
    needs_convert: bool = False
    created_at: str = ""
    # java_path: per-instance Java executable. Empty ⇒ fall back to the global
    # launcher setting. Lets one instance force a specific JDK (e.g. older Forge
    # on Java 8, newer vanilla on Java 21) without changing the global default.
    java_path: str = ""
    # round-42 实例级覆盖（对齐 Prism/HMCL）：0/空 = 用全局设置
    ram_mb: int = 0       # 0 = 全局 ram_mb
    jvm_args: str = ""    # 空 = 全局 jvm_args
    # round-53 实例级渲染器（对齐 HMCL/PCL2 版本设置 → 渲染器）：
    #   "auto" = 不动（默认）；"software" = 软件 OpenGL 兜底（老显卡/虚拟机）；
    #   "legacy" = 旧 LWGJL 驱动兼容（关共享上下文，防旧驱动崩）。
    # 仅对 LWJGL2 老版本（≤1.12.2 系）有意义，1.13+ 注入无害（参数被忽略）。
    renderer: str = "auto"
    # round-53 实例级实验性 GC（对齐 PCL2「性能」高级设置）。默认开 G1GC。
    perf_g1gc: bool = True              # -XX:+UseG1GC 优化参数组
    perf_disable_explicit_gc: bool = False  # -XX:+DisableExplicitGC
    # round-55 启动高级设置（对齐 PCL2「启动游戏/版本设置」）：空值 = 跟随全局
    game_args: str = ""          # 游戏附加参数（追加到游戏启动参数末尾，--server <ip> 直连）
    jvm_preset: str = ""         # "" = 跟随全局；"default"/"aikar"/"custom" 覆盖全局预设
    isolation: str = ""          # "" = 跟随全局；"isolated" = 版本隔离；"custom" = 自定义游戏目录
    game_dir_override: str = ""  # isolation == "custom" 时的自定义游戏目录（绝对路径）
    post_launch_cmd: str = ""    # 游戏进程启动后执行的命令，空 = 跟随全局
    exit_cmd: str = ""           # 游戏进程退出后执行的命令，空 = 跟随全局
    # round-42 实例分组（对齐 Prism 分组/筛选）：空 = 未分组
    group: str = ""
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


class InstancesManager:
    def __init__(self):
        self._path = os.path.join(get_data_dir(), "instances.json")
        self._instances: dict[str, Instance] = {}
        self._current: Optional[str] = None
        self._load()

    # ---- persistence ----
    def refresh(self) -> None:
        """Reload the on-disk instance list. Useful when the user copies a
        new instance folder in from outside AC and wants the launcher to
        pick it up without restarting."""
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        for raw in data.get("instances", []):
            # round-34/40 加固：脏数据（缺 id/name/game_version/非 dict）跳过，
            # 避免启动期 KeyError 崩整个启动器
            if not (isinstance(raw, dict) and raw.get("id") and raw.get("name")
                    and raw.get("game_version")):
                continue
            inst = Instance(
                id=raw["id"],
                name=raw["name"],
                game_version=raw["game_version"],
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
                external=raw.get("external", False),
                _base=raw.get("_base", ""),
                launcher=raw.get("launcher", "AC"),
            )
            self._instances[inst.id] = inst
        self._current = data.get("current")

    def _save(self) -> None:
        data = {
            "current": self._current,
            "instances": [
                {**asdict(i), "_base": i._base} for i in self._instances.values()
            ],
        }
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ---- api ----
    def list(self) -> list[Instance]:
        return list(self._instances.values())

    def get(self, instance_id: str) -> Optional[Instance]:
        return self._instances.get(instance_id)

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
        self._save()
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
            self._save()

    def duplicate(self, inst_id: str, new_name: str = "") -> Instance | None:
        """克隆实例（round-42，对齐 Prism Ctrl+D）：复制游戏目录 + 元数据。

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
        self._save()
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
                external=False,
                launcher=launcher or "Other",
            )
            inst.ensure_dirs()  # creates data/instances/<id>/.minecraft
            try:
                if on_progress is not None:
                    _copied_with_progress(mc_dir, inst.mc_dir, on_progress)
                else:
                    shutil.copytree(mc_dir, inst.mc_dir, dirs_exist_ok=True,
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
        self._save()
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
        self._save()

    @property
    def current_id(self) -> Optional[str]:
        return self._current

    def current(self) -> Optional[Instance]:
        return self._instances.get(self._current) if self._current else None

    def set_current(self, instance_id: str) -> None:
        if instance_id in self._instances:
            self._current = instance_id
            self._save()


# module-level singleton (one manager per process)
_manager = InstancesManager()


def manager() -> InstancesManager:
    return _manager
