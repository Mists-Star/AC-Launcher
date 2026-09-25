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

from src.main_window import MainWindow, STACK_INDEX
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


def _force_foreground(win):
    """Steal foreground focus back to our main window (Windows).

    After the modal onboarding dialog (or the splash) closes, Windows often
    leaves focus on whatever external app was foreground *before* us — so the
    freshly shown launcher silently drops to the back. ``activateWindow()``
    alone is frequently denied by the foreground-lock when another process
    owns the foreground, so we also call ``SetForegroundWindow`` and use the
    ``AttachThreadInput`` trick to make that call survive the lock.
    """
    try:
        win.activateWindow()
    except Exception:
        pass
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = int(win.winId())
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        # Best-effort: attach to the current foreground thread so our
        # SetForegroundWindow is not blocked by the foreground-lock.
        try:
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
            ]
            fg = user32.GetForegroundWindow()
            if fg:
                my_tid = user32.GetWindowThreadProcessId(
                    hwnd, ctypes.byref(wintypes.DWORD(0)))
                fg_tid = user32.GetWindowThreadProcessId(
                    fg, ctypes.byref(wintypes.DWORD(0)))
                if my_tid and fg_tid and my_tid != fg_tid:
                    user32.AttachThreadInput(my_tid, fg_tid, True)
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
                    user32.AttachThreadInput(my_tid, fg_tid, False)
            else:
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        user32.BringWindowToTop(hwnd)
    except Exception:
        pass


def _raise_existing_instance(title: str) -> bool:
    """If another instance's window is actually on screen, bring it to front.

    Used by the single-instance guard: a second launch should raise the existing
    window (never silently "flash"/crash) when a real window exists; only when no
    window is found do we treat the lock as stale/orphaned and take over.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


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
    # Global crash log: windowed PyInstaller builds swallow stderr, so any
    # uncaught Python exception is written to <data_dir>/crash.log for post-mortem.
    from src.paths import get_data_dir
    _crash_path = os.path.join(get_data_dir(), "crash.log")
    _orig_excepthook = sys.excepthook

    def _crash_excepthook(exc_type, exc_value, exc_tb):
        try:
            import traceback as _tb
            import time as _time
            with open(_crash_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== {_time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                _tb.print_exception(exc_type, exc_value, exc_tb, file=f)
                f.flush()
        except Exception:
            pass
        _orig_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _crash_excepthook

    # DIAGNOSIS (opt-in): set AC_DIAG=1 to dump the main-thread stack if startup
    # blocks past 25s — useful for debugging a frozen-build hang. Off by default
    # so normal launches don't leave a spurious fault.log behind.
    if os.environ.get("AC_DIAG") == "1":
        try:
            import faulthandler as _fh
            _fault = open(os.path.join(get_data_dir(), "fault.log"), "w", encoding="utf-8")
            _fh.enable(_fault)
            _fh.dump_traceback_later(25, repeat=False, file=_fault)
        except Exception:
            pass

    # round-40 P2-16：exe 同目录可能是只读位置（便携部署到 Program Files 等），
    # 写失败降级到系统临时目录，不让启动崩溃也不丢日志。
    try:
        _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_startup.log"), "w", encoding="utf-8")
    except OSError:
        import tempfile as _tf
        _log = open(os.path.join(_tf.gettempdir(), "ac_startup.log"), "w", encoding="utf-8")
    _log.write("0 app start\n"); _log.flush()
    _setup_high_dpi()
    _log.write("1 high_dpi ok\n"); _log.flush()

    # 中文界面：QFileDialog / 标准对话框在 Windows 上默认用 Qt 自带翻译，
    # 但 PySide6 wheels 把 translations 目录放在 site-packages 里需要显式加载。
    # 用户反馈文件选择器是英文（"Look in:", "File name:", "Open", "Cancel"），
    # 说明 Qt 翻译没生效。强制 locale=zh_CN + 加载 qt_zh_CN.qm。
    from PySide6.QtCore import QLocale, QTranslator, QLibraryInfo
    QLocale.setDefault(QLocale("zh_CN"))
    qt_translator = QTranslator()
    qt_translations_dir = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    qt_zh = qt_translator.load("qt_zh_CN", qt_translations_dir)
    _log.write(f"1.5 locale=zh_CN, qt_zh_loaded={qt_zh} from {qt_translations_dir}\n")
    _log.flush()

    app = QApplication(sys.argv)
    if qt_zh:
        app.installTranslator(qt_translator)
    _log.write("2 QApplication ok\n"); _log.flush()
    app.setWindowIcon(_app_icon())  # taskbar + title bar icon
    _log.write("3 icon ok\n"); _log.flush()

    # ── Single-instance guard ─────────────────────────────────────────────
    # Double-clicking the exe (or a stuck process) used to spawn a second
    # window that visually overlapped the first ("双页"). QLockFile is a
    # stale-lock-safe cross-process mutex: the second process fails to
    # acquire and quits immediately.
    from src.paths import get_config_path
    from PySide6.QtCore import QLockFile
    from src.brand import APP_DISPLAY
    _lock = QLockFile(get_config_path("ac.lock"))
    _lock.setStaleLockTime(30_000)  # 30 s: released on clean exit; stale after crash
    if not _lock.tryLock(100):
        # A lock exists. If the other instance's window is still visible, just
        # raise it so a double-click never silently "flashes"/crashes. If no
        # window is found the lock is stale/orphaned — take over and start.
        # round-40 P3 修复：窗口标题用品牌名（APP_DISPLAY），不硬编码——
        # 改品牌后单实例"提升已有窗口"仍有效。
        if _raise_existing_instance(APP_DISPLAY):
            _log.write("3.5 another instance already running — raised it\n"); _log.flush()
            return
        _log.write("3.5 stale/orphaned lock — taking over\n"); _log.flush()
        try:
            _lock.remove()
        except Exception:
            pass
        _lock.tryLock(100)
    else:
        # round-96 修复「新手教程背后露出启动器页面」：清理数据（删除 ac.lock）
        # 或前一次异常退出时，旧实例的锁文件会丢失——新实例 tryLock 会误成功，
        # 形成双实例并存：旧启动器主窗口还留着，教程弹窗叠在上面。
        # 这里拿到锁后再按窗口标题扫一遍：此刻本进程尚未创建任何窗口，
        # FindWindow 命中的必然是在跑的旧实例 → 提升它并退出，绝不双开。
        if _raise_existing_instance(APP_DISPLAY):
            _log.write("3.5 window found for a free lock — raising existing instance\n")
            _log.flush()
            try:
                _lock.unlock()
            except Exception:
                pass
            return
    _log.write("3.5 single-instance lock acquired\n"); _log.flush()

    # Load config FIRST so theme mode can be applied before QSS generation
    cfg = load_config()
    _log.write("4 config ok\n"); _log.flush()
    # round-44 E1：先应用保存的语言（之前 _app_lang 默认 zh-CN，导致
    # 设置切英文后重启又回中文——Settings 写盘但 i18n 不知道）。
    try:
        from src.i18n import set_language
        set_language(cfg.get("language", "zh-CN"))
    except Exception:
        pass
    set_theme_mode(cfg.get("theme_mode", "light"))
    from src.theme import set_accent_color
    # round-49：先应用自定义 accent，主题包最后套用（包的 accent 优先）。
    if cfg.get("accent_color"):
        set_accent_color(cfg["accent_color"])
    from src.theme import find_theme_pack, apply_theme_pack
    pack = find_theme_pack(cfg.get("theme_pack", "")) if cfg.get("theme_pack") else None
    if pack:
        apply_theme_pack(pack)
    from src.theme import set_frosted
    set_frosted(cfg.get("frosted_theme", True))
    # round-51 透底效果：按配置把应用层背景切半透明（配合系统 Acrylic）。
    try:
        from src.theme import set_app_background_translucent
        set_app_background_translucent(cfg.get("transparent_window", True))
    except Exception:
        pass
    apply_qss()
    # round-46 结构性修复：QSlider 自绘（QSS 无法给 sub-page 圆角）
    try:
        from src.theme import AcSliderStyle
        app.setStyle(AcSliderStyle())
    except Exception:
        pass
    _log.write("5 qss ok\n"); _log.flush()

    splash = None
    if cfg.get("splash_enabled", True):
        _log.write("6 splash construct\n"); _log.flush()
        # round-63：接入 SplashWindow 完整品牌动画（AC 字母自绘 + 旋转光晕
        # + 标语打字 + 进度条）。AC 用 MC 像素字体渲染（用户指定 round-62），
        # 字体缺失回退矢量描边——logo 永不消失。
        from src.splash_window import SplashWindow
        splash = SplashWindow()
        _log.write("7 splash obj\n"); _log.flush()
        splash.show()
        _log.write("8 splash shown\n"); _log.flush()

    # Defer MainWindow construction to the event loop so the splash animation
    # can actually render while we build the (heavier) main window.
    holder = []

    def _on_welcome_done(error_msg: str = ""):
        from PySide6.QtCore import QTimer
        win = holder[0] if holder else None
        # 成就：第一次成功打开主窗口
        try:
            from src.achievements import achievements as _ach
            _ach.unlock("first_launch")
        except Exception:
            pass
        if error_msg:
            # Startup failed (construction exception or welcome watchdog timeout).
            QMessageBox.critical(
                None, "AC Launcher",
                error_msg or "启动失败：主窗口未能初始化。",
            )
            app.quit()
            return
        # 用户提前点"开始"——主窗口 boot() 还没跑完（holder 仍空）。同步构造
        # 一次，让流程不卡在"启动失败"分支。
        if win is None:
            try:
                win = MainWindow()
                holder.append(win)
                _log.write("10 MainWindow built (on-demand after welcome)\n"); _log.flush()
            except Exception as e:
                import traceback as _tb
                QMessageBox.critical(
                    None, "AC Launcher",
                    "启动失败：主窗口构造异常。\n" + _tb.format_exc(),
                )
                app.quit()
                return
        # 主题/强调色/主题包已在启动早期（apply_qss）应用，欢迎页本身也据此绘制，
        # 这里不再重复重算，直接进入主界面以提速。
        # round-60 修：PCL2 布局构建的是 self.pcl2_side（顶栏按钮），不存在 self.nav；
        # 直接访问必 AttributeError。AC 布局才需要选中左侧导航第一行。
        _nav = getattr(win, "nav", None)
        if _nav is not None:
            _nav.setCurrentRow(0)
        win.stack.setCurrentIndex(0)
        # ── dev: AC_JUMP=instances|mods|store|versions|settings|... ──
        # overrides the home page so screenshots can verify any page without
        # manual clicking. No-op in normal runs.
        _jump = os.environ.get("AC_JUMP", "").strip()
        if _jump and _jump in STACK_INDEX:
            QTimer.singleShot(0, lambda k=_jump: win._switch_stack(STACK_INDEX[k]))
        # Final sync (style/language). MUST run BEFORE show(): retranslate →
        # home.rebuild() tears down and rebuilds the page; doing it after the
        # window is visible leaves a brief transparent flash.
        win.retranslate_ui()
        win.home._refresh()

        def _show_main():
            """真正显示主窗口 + 预加载资源中心 + 强制前台。"""
            win.show()
            # round-95 修复：强制前台必须放在 win.show() 之后。此前这段在
            # 教程分支之前执行，_force_foreground 内部 ShowWindow(SW_RESTORE)
            # 会把「尚未显示」的主窗口直接拉成可见 → 教程弹窗背后露出启动器
            # 主页（round-30/46 只挪了 win.show()，没防住这条旁路）。
            try:
                win.repaint()
                win.raise_()
                _force_foreground(win)
            except Exception:
                pass
            # Pre-warm the resource center in the background: build StorePage
            # off-screen right after show so its search + icon downloads run
            # while the user is still on the home page.
            try:
                _store_idx = STACK_INDEX.get("store")
                if _store_idx is not None:
                    QTimer.singleShot(0, lambda: win._ensure_page(_store_idx))
            except Exception:
                pass
            # 微软 token 静默续期（round-34 P1-5）：启动后异步刷新，不阻塞 UI。
            try:
                from src.worker import Worker
                from src.accounts import manager as _acct_mgr
                _w = Worker(_acct_mgr().refresh_current_silently)
                win._token_refresh_worker = _w  # 挂到 win 防 GC（QThread 被回收=崩溃）
                _w.start()
            except Exception:
                pass
            # round-40 资源中心秒加载：后台预取各分类首页（search 结果 24h 磁盘
            # 缓存，冷启动后首次进资源中心也秒开，不用等网络）。
            try:
                def _prefetch_store():
                    from src import net_api
                    for _pt in ("mod", "shader", "resourcepack", "datapack", "modpack"):
                        try:
                            net_api.search_mods("", 0, 20, _pt)
                        except Exception:
                            pass
                _pw = Worker(_prefetch_store)
                win._store_prefetch_worker = _pw
                _pw.start()
            except Exception:
                pass
            # round-47 版本清单预取：后台拉取 Mojang version_manifest.json，
            # 让新建实例时的版本下拉列表秒开（否则第一次进设置页要等 1.5-4s）。
            try:
                def _prefetch_versions():
                    from src import net_api
                    try:
                        net_api.fetch_versions()
                    except Exception:
                        pass
                _v = Worker(_prefetch_versions)
                win._version_prefetch_worker = _v
                _v.start()
            except Exception:
                pass
            # round-95：强制首页首帧/前台逻辑已移入 _show_main()（win.show() 之后）。
            # 这里不再对「未显示」的主窗口做 repaint/raise/_force_foreground——
            # ShowWindow(SW_RESTORE) 会把还没到展示时机的主窗口拉出来，
            # 导致教程弹窗背后露出启动器主页。

        # 新手教程：首次启动（launch_count < 3）弹出。
        # round-30 用户反馈：教程前会闪现 ~1s 启动器主页——把 win.show() 挪到
        # 教程完成之后，教程期间主窗口根本不显示（不 show，就不会露馅）。
        try:
            from src.onboarding import should_show_onboarding, OnboardingDialog
            _need_onboard = (not os.environ.get("AC_NO_ONBOARDING")
                             and should_show_onboarding())
        except Exception:
            _need_onboard = False

        if _need_onboard:
            # round-46：用户反馈"教程和启动器一起出现"——回到原设计（教程期间主窗口
            # 不 show）。之前为治段错误改成"先 show 再弹"是错的方向，toast
            # double-delete 等根治后不需要主窗口先 show。
            # 延迟 1200ms：等 splash（3.5s）+ 淡出（1.6s）完全消失后弹教程
            def _run_onboarding():
                try:
                    OnboardingDialog(win).exec()
                finally:
                    _show_main()
            QTimer.singleShot(1200, _run_onboarding)
        else:
            _show_main()

    def boot():
        # Build the main window while the splash plays on top.
        # Pump events during construction so the splash animation stays smooth.
        app.processEvents()
        _log.write("9 boot: building MainWindow\n"); _log.flush()
        try:
            win = MainWindow()
            _log.write("10 MainWindow built\n"); _log.flush()
        except Exception as e:
            import traceback as _tb
            err = "主窗口构造时发生异常：\n" + "".join(
                _tb.format_exception_only(type(e), e)
            ).strip()
            # DIAGNOSIS: persist the full traceback so a frozen build that hangs
            # inside the QMessageBox modal loop still leaves a readable cause.
            try:
                with open(os.path.join(get_data_dir(), "boot_err.log"), "w", encoding="utf-8") as _bf:
                    _tb.print_exc(file=_bf)
            except Exception:
                pass
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
            if splash._finished_emitted:
                # round-62/63：慢机首次启动 MainWindow 构造可能 >3.5s，欢迎页早于
                # boot() 末尾 connect 就先自动关窗并 emit finished——信号发进
                # 虚空 → 主窗口永远不显示，最后窗口关闭触发 app.exec() 返回 →
                # 静默退出（"第一次启动无报错退出" + "小窗口一闪而过"）。
                # SplashWindow 由 mark_ready 驱动（不会提前自关），此分支仅
                # 在 15s 看门狗超时触发时出现；检测到已提前关闭则补回调，不再等信号。
                QTimer.singleShot(0, _on_welcome_done)
            else:
                splash.finished.connect(_on_welcome_done)
        else:
            _on_welcome_done()

    from PySide6.QtCore import QTimer
    QTimer.singleShot(40, boot)

    # Drain in-flight worker threads before the interpreter tears down so no
    # QThread is destroyed while still running (heap corruption 0xc0000374 on
    # close with a fetch in flight).
    try:
        from src.worker import drain_workers
        app.aboutToQuit.connect(lambda: drain_workers(4000))
    except Exception:
        pass
    # round-37 轴心2：关窗时关闭默认下载队列（终止消费线程）
    try:
        from src.downloader import _DEFAULT_QUEUE
        if _DEFAULT_QUEUE is not None:
            app.aboutToQuit.connect(lambda: _DEFAULT_QUEUE.shutdown(4000))
    except Exception:
        pass

    code = app.exec()
    # round-35：关闭启动日志句柄（之前全程不关，直到进程退出 OS 兜底）
    try:
        _log.close()
    except Exception:
        pass
    # PySide6 6.11 × Python 3.13 已知问题：解释器 shutdown 阶段析构复杂
    # QObject 对象图（SettingsPage 等）会触发 fail-fast（0xC0000409）闪退。
    # exec 返回后所有功能收尾已完成（aboutToQuit 已 drain 线程/队列、日志
    # 已关闭），用 os._exit 跳过该阶段，避免每次关闭启动器都闪退。
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


if __name__ == "__main__":
    main()
