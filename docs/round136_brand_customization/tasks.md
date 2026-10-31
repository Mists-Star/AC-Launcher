# round-136 任务清单：品牌自定义（左上角标志 / 左上角文本 / 启动页）

状态：**已完成**（2026-10-28）
规格：`spec.md`（同目录）
日期：2026-10-28

---

## T1 · 新增统一入口 `src/brand_custom.py`

- [x] 新建 `src\brand_custom.py`
- [x] 常量：`CUSTOM_LOGO_KEY` / `CUSTOM_TITLE_KEY` / `SPLASH_BG_KEY` / `SUPPORTED_EXTS`
- [x] `load_brand_cfg()` —— 读 `launcher_config.json` 里 3 个键，异常 → `{}`
- [x] `normalize_path(raw)` —— 空/非 str → `""`；否则 `abspath+expanduser+normpath`
- [x] `valid_image_path(raw)` —— 存在 + 是文件 + 后缀受支持 → 绝对路径，否则 `""`
- [x] `custom_logo_path(cfg=None)` / `custom_title_text(cfg=None)` / `splash_bg_path(cfg=None)`
- [x] `load_pixmap(path, size)` —— `QPixmap(path)` → 等比缩小 → 按 `(path, mtime, size)` 缓存；失败 → `None`
- [x] **约束**：不 import `settings_dialog`（避免循环）；不抛异常

**验证**：`python -c "import src.brand_custom"` 通过 ✅

---

## T2 · `src/settings_dialog.py` —— 配置键

- [x] `_DEFAULTS` 新增（`# ---- round-136 品牌自定义 ----` 注释块）：
  - `"custom_logo_path": ""`
  - `"custom_title_text": ""`
  - `"splash_bg_image": ""`
- [x] **铁律**：3 个键都同时被 `_sync_ui_to_cfg` 写入

**验证**：`python tests/audit_defaults.py` → 缺失 **0 个** ✅

---

## T3 · `src/settings_dialog.py` —— 外观页「品牌自定义」组

- [x] `_page_appearance()` 现有 4 组之后新增 `QGroupBox(t("settings.brand"))`
- [x] 控件：`brand_logo_path`（只读 QLineEdit）/ `brand_logo_pick` / `brand_logo_clear` / `brand_logo_preview`（40×40）/ `brand_title_text`
- [x] 选择按钮 → `pick_files(...)`，过滤 `*.png *.jpg *.jpeg *.bmp *.webp *.svg *.ico`
- [x] 选中图片后立即刷新预览（`brand_custom.load_pixmap(path, 40)`）
- [x] 提示文案 `t("settings.brand_logo_hint")` / `t("settings.brand_title_text_hint")`
- [x] import `from . import brand_custom` + `from .brand import APP_DISPLAY`

---

## T4 · `src/settings_dialog.py` —— 启动页背景图控件

- [x] `_page_launch()` 的 `boot_grp` 内、`splash_on` 与 hint 之后新增：
  - `splash_bg_edit`（只读 QLineEdit）/ `splash_bg_pick` / `splash_bg_clear`
- [x] 文案：`t("settings.splash_bg")` / `t("settings.splash_bg_hint")`

---

## T5 · `src/settings_dialog.py` —— `_sync_ui_to_cfg`

- [x] 追加 3 行（`self._safe(fn, target.get(key, ""))` 兜底未构建分区）：
  - `target["custom_logo_path"]`
  - `target["custom_title_text"]`
  - `target["splash_bg_image"]`
- [x] **未改** `_SENSITIVE_CFG_KEYS`

**验证**：改后 `is_dirty=True`、还原后 `is_dirty=False` ✅（设置页 UI 验证 14 项全过）

---

## T6 · `src/i18n.py` —— 中英对称文案

- [x] zh-CN 新增 **9** 个 key（含规格外的 `settings.brand_logo_pick` / `settings.brand_logo_clear`）
- [x] en-US 新增同名 9 个 key
- [x] 修正已脱节的 `settings.splash_hint`（中英各一）

**验证**：i18n 差异 == 0（1369 → **1378**）✅

---

## T7 · `src/main_window.py` —— 标题栏标志 + 左上角文本

- [x] import `from . import brand_custom`
- [x] `_build_titlebar()`：logo pixmap 走 `_titlebar_logo_pixmap()`；保存 `self._tb_logo` / `self._tb_name`
- [x] name 标签文本 = `brand_custom.custom_title_text(self.cfg)`
- [x] 新增 `_titlebar_logo_pixmap()` / `_refresh_titlebar_brand()`
- [x] **未动** `setWindowTitle(APP_DISPLAY)`

---

## T8 · `src/main_window.py` —— 窗口图标 + 设置保存刷新

- [x] `__init__` 的 setWindowIcon 逻辑 → 抽成 `_apply_window_icon()`（在 `self.cfg = load_config()` 之后调用）
- [x] `_on_settings_saved()` 追加 `_refresh_titlebar_brand()` + `_apply_window_icon()`
- [x] 托盘图标 `icon("ac_launcher_icon")` **未动**

---

## T9 · `main.py` —— 任务栏图标

- [x] `_app_icon()`：优先 `brand_custom.custom_logo_path()`（**局部 import**），失败回落 assets 查找
- [x] **未动** `main()` 里的语句顺序

---

## T10 · `src/splash_window.py` —— 背景图 + 自定义标志

- [x] `__init__`：读 `self._logo_pm`（512 上限）/ `self._bg_pm`（960 上限）
- [x] `paintEvent`：
  - 背景图 → cover 铺满（`_cover_rect()`）+ 半透明暗色蒙版 `#00000078`
  - 自定义标志 → **替代**矢量 AC 字母：居中 `cx=w//2, cy=int(h*0.40)`，高度 112，`_smooth((phase-0.05)/0.40)` 驱动淡入 + 0.86→1.0 放大
  - 两者都无 → 现有矢量路径**一行未改**
  - **进度条完全保留**（位置/样式/100% 收敛逻辑未动）

---

## T11 · 新增 `tests/test_brand_custom.py`

- [x] 离屏（`QT_QPA_PLATFORM=offscreen`）
- [x] **35 项断言全 PASS**
- [x] **测试隔离**：`sd.CONFIG_FILE` + `bc.get_config_path` 指向临时目录
      （MainWindow 关闭时会 `save_config()`，不隔离会污染用户真实配置）
- [x] 覆盖：配置键存在性 / 文本三种回落 / 路径校验 / `load_pixmap` /
      标题栏刷新 / 窗口图标 / 启动页默认与自定义分支 `grab()`

---

## T12 · `regress.py` 接入

- [x] SUITES 追加 `("品牌自定义回归", "test_brand_custom.py", "script")`（「设置页脏检测回归」之后）

---

## T13 · 全量验证

- [x] `python -m compileall -q src main.py` → exit 0 ✅
- [x] `python regress.py` → **12/12 通过**（i18n 1378/1378 差异=0、默认值审计缺失 0、设置页脏检测）✅
- [x] `python tests/test_brand_custom.py` → 35 项全过 ✅
- [x] 端到端实效验证（临时脚本，已删）→ 11 项全过 ✅
- [x] 设置页 UI 验证（临时脚本，已删）→ 14 项全过 ✅
- [x] 用户真实 `launcher_config.json` 已还原并二次核验 ✅

---

## T14 · 文档与记忆

- [x] `CHANGELOG.md` 追加 round-136（2026-10-28）条目
- [x] 新建 `<本地工作区>\2026-10-28_AC启动器_round136_品牌自定义.md`（含 5 个踩坑记录）
- [x] **未写** Environmental Box 的待办清单（本项目与它无关）

---

## 施工顺序速览（实际执行）

```
T1 (新模块) → T2/T3/T4/T5 (设置页) → T6 (i18n) → T7/T8 (主窗口) → T9 (任务栏图标)
                                                                     → T10 (启动页)
                                                                     → T11/T12 (测试接入) → T13 (全量验证) → T14 (文档)
```
