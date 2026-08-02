"""MC Launcher — Phase 1 entry point.

Run:  venv/Scripts/python.exe main.py
"""
import os
import sys

# ── silence Qt's FFmpeg multimedia backend ──────────────────────────────────
# On every playback the FFmpeg backend calls av_log() and dumps
#   Input #0, wav, from '...launch_default.wav': Duration: ... Stream #0:0: ...
# to stderr at Info level. The file plays fine — it just reads like an error.
# Disable only Info-level qt.multimedia logging (the probe dump) and keep real
# warnings/errors. NOTE: the wildcard "*" does NOT cross dots in this Qt build,
# and an exact "qt.multimedia.ffmpeg=false" leaf rule is ignored at Info level,
# so the working form is the starred Info rule below. Set BEFORE importing
# PySide6 — the rule is read when the logging framework initialises.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia*.info=false")

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6 import __version__ as _pyside_version

from src.main_window import MainWindow
from src.theme import set_theme_mode, apply_qss
from src.settings_dialog import load_config
from src import paths  # noqa: F401  ensure packaging path helpers are importable


def _app_icon() -> QIcon:
    """Load the AC Launcher icon from assets."""
    base = os.path.dirname(os.path.abspath(__file__))
    for ext in ("png", "ico", "svg"):
        p = os.path.join(base, "assets", "icons", f"logo.{ext}")
        if os.path.isfile(p):
            return QIcon(p)
    return QIcon()  # fallback: OS default


# ── DEV FLAG ────────────────────────────────────────────────────────────────
# When True: launch counter is NOT incremented and the onboarding wizard is
# forced to show every launch (handy while iterating on the welcome flow).
# Set to False before a real release so the wizard only appears on the first
# 3 launches (or after "重置新手教程" in Settings).
DEV_FORCE_ONBOARDING = False
# ────────────────────────────────────────────────────────────────────────────


def _setup_high_dpi():
    """Enable crisp rendering on HiDPI (2K/4K) screens.

    NOTE: the packaging guide's PyQt5 snippet (AA_EnableHighDpiScaling /
    AA_UseHighDpiPixmaps) is for Qt5. In Qt6 those are deprecated no-ops — high
    DPI scaling is automatic — so we only apply them on PySide5 to avoid warnings.
    """
    if _pyside_version.startswith("5."):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def main():
    _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_startup.log"), "w", encoding="utf-8")
    _log.write("0 app start\n"); _log.flush()
    _setup_high_dpi()
    _log.write("1 high_dpi ok\n"); _log.flush()
    app = QApplication(sys.argv)
    _log.write("2 QApplication ok\n"); _log.flush()
    app.setWindowIcon(_app_icon())  # taskbar + title bar icon
    _log.write("3 icon ok\n"); _log.flush()

    # Load config FIRST so theme mode can be applied before QSS generation
    cfg = load_config()
    _log.write("4 config ok\n"); _log.flush()
    set_theme_mode(cfg.get("theme_mode", "light"))
    from src.theme import find_theme_pack, apply_theme_pack
    pack = find_theme_pack(cfg.get("theme_pack", "")) if cfg.get("theme_pack") else None
    if pack:
        apply_theme_pack(pack)
    from src.theme import set_accent_color
    if cfg.get("accent_color"):
        set_accent_color(cfg["accent_color"])
    apply_qss()
    _log.write("5 qss ok\n"); _log.flush()

    splash = None
    if cfg.get("splash_enabled", True):
        _log.write("6 splash construct\n"); _log.flush()
        from src.splash_window import SplashWindow
        splash = SplashWindow()
        _log.write("7 splash obj\n"); _log.flush()
        splash.show()
        _log.write("8 splash shown\n"); _log.flush()

    # Defer MainWindow construction to the event loop so the splash animation
    # can actually render while we build the (heavier) main window.
    holder = []

    def _reveal_after_splash(error_msg: str = ""):
        win = holder[0] if holder else None
        # 成就：第一次成功打开主窗口
        try:
            from src.achievements import achievements as _ach
            _ach.unlock("first_launch")
        except Exception:
            pass
        if error_msg or win is None:
            # Startup failed (construction exception or splash watchdog timeout).
            # Show the error instead of silently freezing on the boot screen.
            QMessageBox.critical(
                None, "AC Launcher",
                error_msg or "启动失败：主窗口未能初始化。",
            )
            app.quit()
            return
        # Runs AFTER splash intro finished.
        # Show onboarding FIRST; only reveal the main window after the wizard
        # completes (or the user skips it).
        from src.onboarding import (
            increment_launch_count,
            should_show_onboarding, OnboardingDialog,
        )

        # Decide whether onboarding is needed.
        if DEV_FORCE_ONBOARDING:
            show_onboarding = True
        else:
            increment_launch_count()
            show_onboarding = should_show_onboarding()

        if show_onboarding:
            try:
                from PySide6.QtCore import QTimer
                ob = OnboardingDialog()
                ob.style_changed.connect(lambda s: win.apply_home_style(s))
                # Safety net: if the wizard window is swallowed (e.g. blocked
                # by a security app) or the user walks away, never let it hang
                # the launcher forever — auto-continue after 30 s.
                _onboard_timer = QTimer(ob)
                _onboard_timer.setSingleShot(True)
                _onboard_timer.timeout.connect(ob.reject)
                _onboard_timer.start(30_000)
                ob.exec()  # modal — blocks until user finishes or skips
                _onboard_timer.stop()
            except Exception as e:
                import traceback
                err = "新手教程初始化失败：\n" + "".join(
                    traceback.format_exception_only(type(e), e)
                ).strip()
                QMessageBox.warning(
                    None, "AC Launcher",
                    err + "\n（已跳过新手教程，直接进入启动器）",
                )

        # Re-read config from disk after onboarding.  The wizard may have
        # written settings (or the user skipped, leaving defaults on disk).
        # This prevents a race where in-memory cfg diverges from what was
        # saved — especially when the user clicks through quickly.
        final_cfg = load_config()
        set_theme_mode(final_cfg.get("theme_mode", "light"))
        from src.theme import find_theme_pack, apply_theme_pack, set_accent_color
        _pack = find_theme_pack(final_cfg.get("theme_pack", "")) if final_cfg.get("theme_pack") else None
        if _pack:
            apply_theme_pack(_pack)
        if final_cfg.get("accent_color"):
            set_accent_color(final_cfg["accent_color"])
        apply_qss()
        win.cfg = final_cfg

        # NOW show the main window — after onboarding is done.
        win.nav.setCurrentRow(0)
        win.stack.setCurrentIndex(0)
        # Final sync (style/language may have changed during onboarding).
        # MUST run BEFORE show(): retranslate → home.rebuild() tears down every
        # widget and rebuilds it. Doing that after the window is visible leaves
        # the page briefly empty (transparent flash) before content re-appears.
        win.retranslate_ui()
        win.home._refresh()
        win.show()
        # Force a synchronous first paint so the window never flashes a
        # transparent / empty frame before its content is actually drawn.
        app.processEvents()
        win.repaint()
        win.raise_()

    def boot():
        # Build the main window while the splash plays on top.
        # Pump events during construction so the splash animation stays smooth.
        app.processEvents()
        _log.write("9 boot: building MainWindow\n"); _log.flush()
        try:
            win = MainWindow()
            _log.write("10 MainWindow built\n"); _log.flush()
        except Exception as e:
            import traceback
            err = "主窗口构造时发生异常：\n" + "".join(
                traceback.format_exception_only(type(e), e)
            ).strip()
            if splash is not None and not splash._finished_emitted:
                splash._finish_close(err)
            else:
                QMessageBox.critical(None, "AC Launcher", err)
                app.quit()
            return
        app.processEvents()
        holder.append(win)
        if splash is not None:
            splash.mark_ready()
            splash.finished.connect(_reveal_after_splash)
        else:
            _reveal_after_splash()

    from PySide6.QtCore import QTimer
    QTimer.singleShot(40, boot)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
