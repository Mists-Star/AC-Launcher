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
from typing import Optional

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
    # external=True means this instance links to an existing .minecraft on
    # disk (imported from another launcher) — removing it must NOT delete the
    # user's real game files, only the AC metadata entry.
    external: bool = False
    # path is derived, not stored
    _base: str = field(default="", repr=False, compare=False)

    @property
    def root(self) -> str:
        """Instance root directory (contains .minecraft)."""
        if not self._base:
            self._base = os.path.join(get_data_dir(), "instances", self.id)
        return self._base

    @property
    def mc_dir(self) -> str:
        """The .minecraft directory minecraft-launcher-lib expects.

        For isolated instances (version dir IS the game dir), _base already
        points to it directly.  For standard layout, append /.minecraft.
        """
        if self._base and os.path.basename(self._base) != ".minecraft":
            return self.root  # isolated: _base is the game dir itself
        return os.path.join(self.root, ".minecraft")

    @property
    def mods_dir(self) -> str:
        return os.path.join(self.mc_dir, "mods")

    def ensure_dirs(self) -> None:
        os.makedirs(self.mc_dir, exist_ok=True)
        os.makedirs(self.mods_dir, exist_ok=True)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


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
                shutil.copytree(mc_dir, inst.mc_dir, dirs_exist_ok=True)
            except (OSError, shutil.Error) as e:  # fall back to in-place link
                shutil.rmtree(inst.root, ignore_errors=True)
                raise _CopyFailed(str(e)) from e
        else:  # link / in-place takeover
            # For isolated instances (version dir IS the game dir, e.g.
            # .minecraft/versions/1.21.1-OptiFine), store the dir directly
            # as _base so mc_dir returns it without appending /.minecraft.
            is_isolated = os.path.basename(mc_dir) != ".minecraft"
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
                _base=mc_dir if is_isolated else os.path.dirname(mc_dir),
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
