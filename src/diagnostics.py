"""Launcher self-diagnostics & repair — the built-in health check.

Each check returns a :class:`CheckResult`. Repairable checks expose a repair
path that the UI invokes. Checks cover three areas:

  * Launcher integrity — core deps, writable data dir, config & account JSON
    validity, bundled assets, the external-login (authlib-injector) component.
  * System environment — a usable Java runtime for launching the game.
  * Game files — integrity of the *current* instance's ``.minecraft`` (missing
    or corrupt versions are healed via ``install.repair_minecraft_dir``).

Everything here is pure logic with no Qt dependency, so it can run on a worker
thread and be unit-tested head-less.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .paths import get_data_dir, get_resource_path, get_config_path
from .i18n import t

# ---- status constants ----
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_ERROR = "error"
STATUS_SKIP = "skip"


@dataclass
class CheckResult:
    id: str
    title_key: str
    category_key: str
    status: str
    detail: str
    repairable: bool


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _config_path() -> str:
    return get_config_path("launcher_config.json")


def _accounts_path() -> str:
    return os.path.join(get_data_dir(), "accounts.json")


def _uses_external_login() -> bool:
    try:
        from .accounts import manager as am

        return any(a.get("type") == "yggdrasil" for a in am().list())
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# individual checks
# --------------------------------------------------------------------------- #
def _check_deps() -> CheckResult:
    missing = []
    for mod in ("PySide6", "minecraft_launcher_lib", "requests"):
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001
            missing.append(mod)
    if missing:
        return CheckResult(
            "deps", "diag.check.deps", "diag.cat.launcher", STATUS_ERROR,
            t("diag.d.deps.err", missing=", ".join(missing)), repairable=False,
        )
    return CheckResult(
        "deps", "diag.check.deps", "diag.cat.launcher", STATUS_OK,
        t("diag.d.deps.ok"), repairable=False,
    )


def _check_java() -> CheckResult:
    from .core import java as java_mod

    javas = java_mod.scan_javas()
    if not javas:
        return CheckResult(
            "java", "diag.check.java", "diag.cat.system", STATUS_WARN,
            t("diag.d.java.none"), repairable=False,
        )
    best = sorted(javas, key=lambda x: -x["major"])[0]
    return CheckResult(
        "java", "diag.check.java", "diag.cat.system", STATUS_OK,
        t("diag.d.java.ok", ver=best["version"], major=best["major"]),
        repairable=False,
    )


def _check_datadir() -> CheckResult:
    d = get_data_dir()
    try:
        probe = os.path.join(d, ".writetest")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return CheckResult(
            "datadir", "diag.check.datadir", "diag.cat.launcher", STATUS_OK,
            t("diag.d.datadir.ok", path=d), repairable=False,
        )
    except Exception:  # noqa: BLE001
        return CheckResult(
            "datadir", "diag.check.datadir", "diag.cat.launcher", STATUS_ERROR,
            t("diag.d.datadir.err", path=d), repairable=False,
        )


def _check_config() -> CheckResult:
    p = _config_path()
    if not os.path.exists(p):
        # Absent config simply falls back to defaults — that's fine.
        return CheckResult(
            "config", "diag.check.config", "diag.cat.launcher", STATUS_OK,
            t("diag.d.config.ok"), repairable=False,
        )
    try:
        with open(p, "r", encoding="utf-8") as f:
            json.load(f)
        return CheckResult(
            "config", "diag.check.config", "diag.cat.launcher", STATUS_OK,
            t("diag.d.config.ok"), repairable=False,
        )
    except (json.JSONDecodeError, OSError):
        return CheckResult(
            "config", "diag.check.config", "diag.cat.launcher", STATUS_ERROR,
            t("diag.d.config.err"), repairable=True,
        )


def _check_accounts() -> CheckResult:
    p = _accounts_path()
    if not os.path.exists(p):
        return CheckResult(
            "accounts", "diag.check.accounts", "diag.cat.launcher", STATUS_OK,
            t("diag.d.accounts.ok", n=0), repairable=False,
        )
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        n = len(data.get("accounts", [])) if isinstance(data, dict) else 0
        return CheckResult(
            "accounts", "diag.check.accounts", "diag.cat.launcher", STATUS_OK,
            t("diag.d.accounts.ok", n=n), repairable=False,
        )
    except (json.JSONDecodeError, OSError):
        return CheckResult(
            "accounts", "diag.check.accounts", "diag.cat.launcher", STATUS_ERROR,
            t("diag.d.accounts.err"), repairable=True,
        )


def _check_authlib() -> CheckResult:
    from .core import authlib as authlib_mod

    if not _uses_external_login():
        return CheckResult(
            "authlib", "diag.check.authlib", "diag.cat.launcher", STATUS_SKIP,
            t("diag.d.authlib.skip"), repairable=False,
        )
    from .settings_dialog import load_config

    cfg = load_config()
    jar = cfg.get("authlib_path") or os.path.join(get_data_dir(), "authlib-injector.jar")
    if not os.path.exists(jar):
        return CheckResult(
            "authlib", "diag.check.authlib", "diag.cat.launcher", STATUS_WARN,
            t("diag.d.authlib.missing"), repairable=True,
        )
    if authlib_mod._sha256_of(jar) == authlib_mod.AUTHLIB_SHA256:
        return CheckResult(
            "authlib", "diag.check.authlib", "diag.cat.launcher", STATUS_OK,
            t("diag.d.authlib.ok"), repairable=False,
        )
    return CheckResult(
        "authlib", "diag.check.authlib", "diag.cat.launcher", STATUS_WARN,
        t("diag.d.authlib.bad"), repairable=True,
    )


def _check_gamefiles() -> CheckResult:
    from .core import install as install_mod
    from .instances import manager as im

    inst = im().current()
    if inst is None:
        return CheckResult(
            "gamefiles", "diag.check.gamefiles", "diag.cat.game", STATUS_SKIP,
            t("diag.d.gamefiles.skip"), repairable=False,
        )
    versions = install_mod.list_installed_versions(inst.mc_dir)
    if not versions:
        return CheckResult(
            "gamefiles", "diag.check.gamefiles", "diag.cat.game", STATUS_WARN,
            t("diag.d.gamefiles.warn"), repairable=True,
        )
    bad = []
    for v in versions:
        vdir = os.path.join(inst.mc_dir, "versions", v)
        if not os.path.isfile(os.path.join(vdir, f"{v}.jar")):
            bad.append(v)
    if bad:
        return CheckResult(
            "gamefiles", "diag.check.gamefiles", "diag.cat.game", STATUS_WARN,
            t("diag.d.gamefiles.warn"), repairable=True,
        )
    return CheckResult(
        "gamefiles", "diag.check.gamefiles", "diag.cat.game", STATUS_OK,
        t("diag.d.gamefiles.ok", n=len(versions)), repairable=False,
    )


def _check_assets() -> CheckResult:
    missing = []
    for rel in ("assets/icons/logo.svg", "assets/icons/repair.svg", "assets/icons/refresh.svg"):
        if not os.path.exists(get_resource_path(rel)):
            missing.append(rel)
    if missing:
        return CheckResult(
            "assets", "diag.check.assets", "diag.cat.launcher", STATUS_ERROR,
            t("diag.d.assets.err", missing=", ".join(missing)), repairable=False,
        )
    return CheckResult(
        "assets", "diag.check.assets", "diag.cat.launcher", STATUS_OK,
        t("diag.d.assets.ok"), repairable=False,
    )


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def _check_network() -> CheckResult:
    """Reachability of the core download endpoints (mojang / bmclapi / modrinth).

    Pure TCP connect test — no HTTPS handshake, no downloads. A failing
    endpoint explains "无法连接" style errors in versions / mods pages.
    """
    import socket
    targets = [
        ("launchermeta.mojang.com", 443, "diag.d.net.mojang"),
        ("bmclapi2.bangbang93.com", 443, "diag.d.net.bmclapi"),
        ("api.modrinth.com", 443, "diag.d.net.modrinth"),
    ]
    bad = []
    for host, port, label_key in targets:
        try:
            s = socket.create_connection((host, port), timeout=5)
            s.close()
        except Exception as e:
            bad.append(f"{t(label_key)} ({type(e).__name__})")
    if bad:
        return CheckResult(
            "network", "diag.check.network", "diag.cat.launcher", STATUS_WARN,
            t("diag.d.net.err", bad="、".join(bad)), repairable=False,
        )
    return CheckResult(
        "network", "diag.check.network", "diag.cat.launcher", STATUS_OK,
        t("diag.d.net.ok"), repairable=False,
    )


def _check_ui_state() -> CheckResult:
    """Sanity-check the live UI for the "double page" symptom and other
    visual glitches.

    Called from the main thread (needs the running MainWindow). Unlike the
    old check that only counted duplicate HomePage objects in the stack, this
    version looks at the *currently visible* page for the actual visual
    symptoms players report as "double page":

    * a stray QGraphicsOpacityEffect making the page translucent
    * duplicate content layers inside the current page
    * the embedded scan panel and normal content both visible at once
    """
    try:
        from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget
        wins = QApplication.topLevelWidgets()
        main = None
        for w in wins:
            cls = type(w).__name__
            if cls == "MainWindow" and hasattr(w, "stack"):
                main = w
                break
        if main is None:
            return CheckResult(
                "ui", "diag.check.ui", "diag.cat.launcher", STATUS_SKIP,
                t("diag.d.ui.skip"), repairable=False,
            )

        n = main.stack.count()
        page = main.stack.currentWidget()
        if page is None:
            return CheckResult(
                "ui", "diag.check.ui", "diag.cat.launcher", STATUS_OK,
                t("diag.d.ui.ok", n=n), repairable=False,
            )

        findings: list[str] = []

        # 1) leftover opacity effect (historical root cause of the ghost overlay)
        fx = page.graphicsEffect()
        if isinstance(fx, QGraphicsOpacityEffect):
            op = fx.opacity()
            if op < 0.99:
                findings.append(t("diag.d.ui.opacity", op=f"{op:.2f}"))

        # 2) duplicated content layers inside the visible page
        from .main_window import HomePage
        from .pages_instances import InstancesPage

        if isinstance(page, HomePage):
            # HomePage should have exactly one visible content layer plus an
            # optional scan panel. If both content and scan_panel are visible,
            # that's the embedded-mode equivalent of a double page.
            content = getattr(page, "content", None)
            scan = getattr(page, "_scan_panel", None)
            if content is not None and scan is not None:
                if content.isVisible() and scan.isVisible():
                    findings.append(t("diag.d.ui.home_both_layers"))
            # Also look for multiple direct children that look like content
            if content is not None:
                vis_contents = [
                    c for c in page.children()
                    if isinstance(c, QWidget)
                    and c is not page.backdrop
                    and c is not content
                    and c.isVisible()
                    and c.parent() is page
                ]
                if len(vis_contents) > 1:  # at most the scan panel should be visible
                    findings.append(t("diag.d.ui.home_extra_children", n=len(vis_contents)))

        elif isinstance(page, InstancesPage):
            detail = getattr(page, "detail_scroll", None)
            scan = getattr(page, "_scan_panel", None)
            if detail is not None and scan is not None:
                if detail.isVisible() and scan.isVisible():
                    findings.append(t("diag.d.ui.instances_both_layers"))

        # 3) duplicate HomePage objects in the stack (old indicator)
        dup = sum(1 for i in range(n) if isinstance(main.stack.widget(i), HomePage))
        if dup > 1:
            findings.append(t("diag.d.ui.dup_home", n=dup))

        if findings:
            return CheckResult(
                "ui", "diag.check.ui", "diag.cat.launcher", STATUS_WARN,
                "; ".join(findings), repairable=False,
            )
        return CheckResult(
            "ui", "diag.check.ui", "diag.cat.launcher", STATUS_OK,
            t("diag.d.ui.ok", n=n), repairable=False,
        )
    except Exception as e:  # noqa: BLE001 - diagnostics must never crash
        return CheckResult(
            "ui", "diag.check.ui", "diag.cat.launcher", STATUS_SKIP,
            f"{type(e).__name__}: {e}", repairable=False,
        )


def run_diagnostics() -> list[CheckResult]:
    """Run every check and return the results (fast, no downloads).

    NOTE: intentionally excludes the UI-state check — it touches live Qt
    widgets and must run on the GUI thread. Call :func:`check_ui_state_now`
    separately from the main thread.
    """
    return [
        _check_deps(),
        _check_datadir(),
        _check_config(),
        _check_accounts(),
        _check_authlib(),
        _check_assets(),
        _check_java(),
        _check_gamefiles(),
        _check_network(),
    ]


def check_ui_state_now() -> CheckResult:
    """UI-state check; must run on the main (GUI) thread.

    Detects the "double page" symptom: two HomePage instances in the stack.
    """
    return _check_ui_state()


def repair(check_id: str) -> str:
    """Repair a single check by id. Returns a human-readable result message."""
    if check_id == "config":
        p = _config_path()
        if os.path.exists(p):
            try:
                os.replace(p, p + ".bak")
            except OSError:
                pass
        from .settings_dialog import _DEFAULTS, save_config

        save_config(dict(_DEFAULTS))
        return t("diag.repair.config_reset")

    if check_id == "accounts":
        p = _accounts_path()
        if os.path.exists(p):
            try:
                os.replace(p, p + ".bak")
            except OSError:
                pass
        try:
            os.remove(p)
        except OSError:
            pass
        return t("diag.repair.accounts_reset")

    if check_id == "authlib":
        from .core import authlib as authlib_mod
        from .settings_dialog import load_config

        cfg = load_config()
        jar = cfg.get("authlib_path") or None
        path = authlib_mod.ensure_authlib(jar)
        return t("diag.repair.authlib_dl") if path else t("diag.repair.fail", e="download")

    if check_id == "gamefiles":
        from .core import install as install_mod
        from .instances import manager as im

        inst = im().current()
        if inst is None:
            return t("diag.repair.fail", e="no instance")
        # Never touch a linked (imported "原地接管") instance — its mc_dir IS
        # the user's real game folder from another launcher, so repairing it
        # would clobber that launcher's files. Mirrors instances.remove().
        if getattr(inst, "external", False):
            return t("diag.repair.external_skip")
        repaired = install_mod.repair_minecraft_dir(inst.mc_dir)
        return t("diag.repair.gamefiles", n=len(repaired))

    return t("diag.repair.fail", e=check_id)


def repair_all() -> list[str]:
    """Repair every repairable, non-OK check. Returns a list of result messages."""
    out: list[str] = []
    for r in run_diagnostics():
        if r.repairable and r.status != STATUS_OK:
            out.append(repair(r.id))
    return out
