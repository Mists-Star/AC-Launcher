"""全页面/对话框离屏构造冒烟（审计用，不入库）。

离线能做的最高价值运行时检查：真构造每个页面与关键对话框，
捕获「只在运行时才炸」的问题（QSS 应用、布局、信号接线、缺属性）。
配置走内存 monkeypatch，全程不碰真实 launcher_config.json。
"""
import os
import sys
import traceback

# tests/ 下运行：仓库根 = tests 的上一级
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

# ── 配置走内存，绝不碰真实文件 ──
import src.settings_dialog as sd  # noqa: E402

_CFG = dict(sd._DEFAULTS) if hasattr(sd, "_DEFAULTS") else {}
sd.load_config = lambda *a, **k: dict(_CFG)
sd.save_config = lambda *a, **k: None

results = []


def attempt(label, fn):
    try:
        w = fn()
        app.processEvents()
        results.append((label, True, ""))
        return w
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc().strip().splitlines()
        results.append((label, False, "%s: %s | %s" % (
            type(e).__name__, e, tb[-3].strip() if len(tb) >= 3 else "")))
        return None


def main():
    from src.instances import manager
    _mgr = manager()

    # ── 主窗口 + 全页面导航 ──
    def build_main():
        from src.main_window import MainWindow
        w = MainWindow()
        w.resize(1280, 800)
        w.show()
        return w

    win = attempt("MainWindow", build_main)
    if win is not None:
        # 逐个导航到所有页面（禁过渡动画，避免截图/构造撞动画中段）
        try:
            win._cfg_cache = getattr(win, "_cfg_cache", {})
            if hasattr(win, "_switch_stack"):
                pass
        except Exception:
            pass
        nav = getattr(win, "_nav_row", None)
        keys = []
        if nav:
            # 从导航模型反推 key
            for attr in ("_nav_keys", "_NAV_KEYS", "nav_items"):
                v = getattr(win, attr, None)
                if v:
                    keys = [k for _lbl, k in v] if isinstance(v, (list, tuple)) else list(v)
                    break
        if not keys:
            keys = ["home", "instances", "browse", "console", "settings",
                    "music", "achievements", "account"]
        # "account" 不是页面而是**弹模态登录框**（main_window._open_account →
        # LoginDialog.exec()），阻塞是预期行为，跳过以免冒烟挂死。
        keys = [k for k in keys if k != "account"]
        for k in keys:
            def go(k=k):
                row = win._nav_row(k)
                win._on_nav(row)
                app.processEvents()
                return True
            attempt("nav -> %s" % k, go)

    # ── 关键对话框 ──
    attempt("SettingsPage", lambda: __import__(
        "src.settings_dialog", fromlist=["SettingsPage"]).SettingsPage())
    attempt("NewInstanceDialog", lambda: __import__(
        "src.pages_instances", fromlist=["NewInstanceDialog"]).NewInstanceDialog())
    attempt("StoreDetailPanel", lambda: __import__(
        "src.store_detail", fromlist=["StoreDetailPanel"]).StoreDetailPanel(
            None, {"project_id": "x", "slug": "x", "title": "x"}, "mod",
            None, "mods"))
    attempt("DiagnosticsDialog", lambda: __import__(
        "src.diagnostics_dialog", fromlist=["DiagnosticsDialog"]).DiagnosticsDialog())
    attempt("JavaManagerDialog", lambda: __import__(
        "src.java_manager_dialog", fromlist=["JavaManagerDialog"]).JavaManagerDialog())
    attempt("LoginDialog", lambda: __import__(
        "src.login_dialog", fromlist=["LoginDialog"]).LoginDialog())
    attempt("ServerFavDialog", lambda: __import__(
        "src.server_fav_dialog", fromlist=["ServerFavDialog"]).ServerFavDialog())
    attempt("CrashAnalyzerDialog", lambda: __import__(
        "src.crash_dialog",
        fromlist=["CrashAnalyzerDialog"]).CrashAnalyzerDialog())

    # ── round-132 防回归：内嵌「新建实例」面板关闭后不得残留第二页 ──
    # 对应 round-126 的「退出后双页」报告：关闭时 deleteLater 要等下一轮事件
    # 循环，期间面板还在绘制 → 先 hide() 再延迟删除，且 body_stack 必须回到
    # 两个常驻页（空态 / 列表）之一。
    if win is not None:
        try:
            win._show_page("instances")
            app.processEvents()
        except Exception:
            pass
    if win is not None and getattr(win, "instances_page", None) is not None:
        def double_page_check():
            page = win.instances_page
            page._new()                     # 打开内嵌新建向导
            app.processEvents()
            opened = page._new_panel is not None
            page._close_new_panel()         # 立即关闭（旧 bug 的双页场景）
            app.processEvents()
            app.processEvents()             # 让 QTimer.singleShot(0) 收尾跑完
            count = page._body_stack.count()
            cur = page._body_stack.currentWidget()
            assert opened, "内嵌向导没有打开"
            assert page._new_panel is None, "面板引用未清空"
            assert count == 2, "残留多余页：count=%d" % count
            assert cur is page._empty_page or cur is page._split_view, \
                "当前页异常：%s" % type(cur).__name__
            return True

        attempt("内嵌新建面板无双页", double_page_check)

    # ── 汇总 ──
    print()
    ok = [r for r in results if r[1]]
    bad = [r for r in results if not r[1]]
    print("构造成功 %d / %d" % (len(ok), len(results)))
    for label, _, err in bad:
        print("  FAIL %-28s %s" % (label, err[:170]))
    print()
    # 退出前收掉后台线程（真机由 main.py 的 aboutToQuit 负责）：
    # 否则解释器析构仍在运行的 QThread → 0xC0000409。离屏 harness 不走真实
    # 退出，且 C++ 静态析构与 atexit 之间存在竞态，偶发原生崩溃会让 regress
    # 把「构造全过」误判成 FAIL。这里显式排空已知的两类后台资源（全景加载器
    # + TrackedThread），再绕过脆弱的 C++ 静态析构，拿确定性退出码。
    try:
        from src.panorama import wait_for_loaders
        wait_for_loaders(5000)
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.worker import drain_workers
        drain_workers(4000)
    except Exception:  # noqa: BLE001
        pass
    print("SMOKE OK" if not bad else "SMOKE FAILED (%d)" % len(bad))
    # os._exit 不跑 atexit / 不刷缓冲：上面已手动排空，这里先 flush，再拿退出码
    # 直接终止，绕过会偶发崩的 C++ 全局/静态析构（所有构造断言早已跑完）。
    sys.stdout.flush()
    os._exit(1 if bad else 0)


if __name__ == "__main__":
    main()
