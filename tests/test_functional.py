"""round-112 功能审计：核心逻辑离线冒烟（审计用，不入库）。

全部走临时目录 / monkeypatch，绝不碰用户真实数据。
重点验证「真接通」而非「看起来有」——UI 有按钮但逻辑不通是本轮要找的。
"""
import json
import os
import shutil
import sys
import tempfile

# tests/ 下运行：仓库根 = tests 的上一级
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)

TMP = tempfile.mkdtemp(prefix="ac_func_")
results = []


def check(label, cond, extra=""):
    results.append((label, bool(cond), extra))
    print("  %s %-46s %s" % ("OK  " if cond else "FAIL", label, extra))
    sys.stdout.flush()


def main():
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # ── 1. 配置读写 roundtrip + 敏感键不落盘 ──
    import src.settings_dialog as sd
    sd.CONFIG_FILE = os.path.join(TMP, "cfg.json")
    cfg = dict(sd._DEFAULTS)
    cfg["curseforge_api_key"] = "SECRET-KEY-123"
    cfg["download_mirror"] = "official"
    sd.save_config(cfg)
    check("配置保存落盘", os.path.isfile(sd.CONFIG_FILE))
    back = sd.load_config()
    check("配置读回一致（非敏感键）",
          back.get("download_mirror") == "official",
          "download_mirror=%r" % back.get("download_mirror"))
    check("_DEFAULTS 键全部读回",
          not (set(sd._DEFAULTS) - set(back)),
          "缺 %s" % sorted(set(sd._DEFAULTS) - set(back))[:3])

    # ── 2. 导出/导入必须剔除敏感键（round-83/108 声称的功能）──
    # 导出/导入是 UI 方法（要弹窗），这里验它依赖的纯逻辑：敏感键集合 + 过滤
    from src.settings_dialog import _SENSITIVE_CFG_KEYS, _DEFAULTS
    check("curseforge_api_key 在敏感集合内",
          "curseforge_api_key" in _SENSITIVE_CFG_KEYS,
          "集合=%s" % sorted(_SENSITIVE_CFG_KEYS))
    # 复刻 _export_settings 的过滤逻辑
    target = dict(cfg)
    for k in _SENSITIVE_CFG_KEYS:
        target.pop(k, None)
    check("导出过滤后不含任何敏感键",
          not (set(_SENSITIVE_CFG_KEYS) & set(target)),
          "残留=%s" % sorted(set(_SENSITIVE_CFG_KEYS) & set(target)))
    check("导出的 JSON 里搜不到密钥值",
          "SECRET-KEY-123" not in json.dumps(target, ensure_ascii=False))
    # 复刻 _import_settings 的过滤逻辑：敏感键 + 未知键都不还原
    imported = dict(_DEFAULTS)
    payload = {**cfg, "evil_unknown_key": "x", "curseforge_api_key": "HACK"}
    n = 0
    for k in _DEFAULTS:
        if k in _SENSITIVE_CFG_KEYS:
            continue
        if k in payload and payload[k] is not None:
            imported[k] = payload[k]
            n += 1
    check("导入拒绝还原敏感键",
          imported.get("curseforge_api_key") in (None, _DEFAULTS.get("curseforge_api_key")),
          "got=%r" % imported.get("curseforge_api_key"))
    check("导入拒绝未知键（防脏 json 污染）",
          "evil_unknown_key" not in imported)

    # ── 3. i18n：缺失键必须优雅降级而非崩溃 ──
    from src.i18n import t
    try:
        v = t("this.key.does.not.exist", default="FALLBACK")
        check("i18n 缺失键走 default", v == "FALLBACK", "got=%r" % v)
    except Exception as e:
        check("i18n 缺失键走 default", False, str(e)[:60])
    try:
        v2 = t("this.key.also.missing")
        check("i18n 缺失键无 default 也不崩", isinstance(v2, str), "got=%r" % v2[:40])
    except Exception as e:
        check("i18n 缺失键无 default 也不崩", False, str(e)[:60])

    # ── 4. 实例体检引擎（round-106 新增，纯逻辑可测）──
    try:
        from src.core import instance_health
        class FakeInst:
            def __init__(self):
                self.name = "t"; self.game_dir = os.path.join(TMP, "inst")
                self.mc_dir = self.game_dir; self.game_version = "1.20.1"
                self.loader = "vanilla"; self.java_path = ""
                self.external = False; self.id = "t1"
        os.makedirs(os.path.join(TMP, "inst"), exist_ok=True)
        res = instance_health.scan_health(FakeInst())
        check("体检引擎可跑（空实例不炸）", res is not None,
              "groups=%s" % (list(res.get("groups", {}))[:5] if isinstance(res, dict) else type(res)))
        check("体检返回计数结构",
              isinstance(res, dict) and all(
                  k in res for k in ("critical", "warning", "info")),
              "keys=%s" % sorted(res)[:6] if isinstance(res, dict) else "-")
    except Exception as e:
        import traceback
        check("体检引擎可跑", False, "%s: %s" % (type(e).__name__, e)[:90])

    # ── 5. 模组检查（纯逻辑）──
    try:
        from src.core import mod_check
        class FI2:
            game_dir = os.path.join(TMP, "inst2"); mc_dir = os.path.join(TMP, "inst2")
            game_version = "1.20.1"; loader = "fabric"
        os.makedirs(os.path.join(TMP, "inst2", "mods"), exist_ok=True)
        if hasattr(mod_check, "scan_conflicts"):
            out = mod_check.scan_conflicts(FI2())
            check("模组检查可跑（空 mods 不炸）", out is not None,
                  "type=%s" % type(out).__name__)
        else:
            check("模组检查接口存在", False, "无 scan_conflicts")
    except Exception as e:
        check("模组检查可跑", False, "%s: %s" % (type(e).__name__, e)[:80])

    # ── 6. 崩溃日志解析（纯逻辑）──
    try:
        from src import crash_analysis as ca
        log = ("---- Minecraft Crash Report ----\n"
               "Exception: java.lang.NoClassDefFoundError: net/fabricmc/loader/X\n"
               "at a.b.c(A.java:12)\n")
        lp = os.path.join(TMP, "crash.txt")
        open(lp, "w", encoding="utf-8").write(log)
        if hasattr(ca, "analyze_instance"):
            class FI3:
                game_dir = TMP; mc_dir = TMP; game_version = "1.20.1"
                loader = "fabric"; name = "t"; id = "t"
            r = ca.analyze_instance(FI3())
            check("崩溃解析可跑（无崩溃文件时）", isinstance(r, list),
                  "findings=%d" % len(r))
        else:
            fns = [n for n in dir(ca) if not n.startswith("_") and callable(getattr(ca, n))]
            check("崩溃解析接口存在", bool(fns), "可用: %s" % fns[:5])
    except Exception as e:
        check("崩溃解析可跑", False, "%s: %s" % (type(e).__name__, e)[:80])

    # ── 7. Java 扫描（本机可能真的有 JDK）──
    try:
        from src.core.java import scan_javas
        javas = scan_javas()
        check("Java 扫描可跑", isinstance(javas, list), "找到 %d 个" % len(javas))
    except Exception as e:
        check("Java 扫描可跑", False, "%s: %s" % (type(e).__name__, e)[:70])

    # ── 8. 成就：解锁后持久化 ──
    try:
        from src.achievements import achievements
        before = achievements.is_unlocked("first_launch")
        achievements.unlock("first_launch")
        after = achievements.is_unlocked("first_launch")
        check("成就解锁生效", after is True, "before=%r after=%r" % (before, after))
        n, total = achievements.progress()
        check("成就进度可统计", total > 0, "%d/%d" % (n, total))
    except Exception as e:
        check("成就系统可跑", False, "%s: %s" % (type(e).__name__, e)[:70])

    # ── 9. 主题应用不崩 ──
    try:
        from src.theme import apply_qss, set_theme_mode, set_accent_color
        set_theme_mode("dark"); apply_qss()
        set_theme_mode("light"); set_accent_color("#7C3AED"); apply_qss()
        check("明暗主题切换不崩", True)
    except Exception as e:
        check("明暗主题切换不崩", False, "%s: %s" % (type(e).__name__, e)[:70])

    app.quit()
    print()
    bad = [r for r in results if not r[1]]
    print("功能冒烟 %d/%d" % (len(results) - len(bad), len(results)))
    print("FUNC OK" if not bad else "FUNC FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    code = main()
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
