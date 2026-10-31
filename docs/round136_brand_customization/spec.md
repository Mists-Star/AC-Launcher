# round-136 规格：品牌自定义（左上角标志 / 左上角文本 / 启动页）

状态：**待批准**（批准后按 `tasks.md` 顺序施工）
日期：2026-10-28
归属项目：`mc_launcher 仓库根`（AC Launcher）

---

## 1. 需求原文

> 添加左上角AC标志可自定义替换和启动页面自定义以及左上角AC文本可自定义

用户已确认的范围（AskUserQuestion）：

| 维度 | 用户选择 | 含义 |
|---|---|---|
| 启动页范围 | **背景图 + 标志（推荐）** | 启动页可设自己的背景图；自定义标志时，手绘矢量 AC 字母改为显示用户图片；**保留进度条** |
| 标志应用范围 | **标题栏 + 窗口图标 + 启动页（推荐）** | 左上角小图标、任务栏/标题栏窗口图标、启动页标志全部换成用户的图 |

### 本规格锁定的两个实现口径（不再另行询问）

1. **「左上角 AC 文本」= 标题栏 logo 右侧的 `QLabel`**（当前显示 `APP_DISPLAY` = "AC Launcher"），
   **不改** `setWindowTitle(APP_DISPLAY)`。
   理由：`main.py:110` `user32.FindWindowW(None, title)` 与 `main.py:238` `_raise_existing_instance(APP_DISPLAY)`
   依赖窗口标题字面量 `APP_DISPLAY` 实现「双击启动器提拉已有实例」。改标题 = 双击变双开，是回归。
2. **自定义标志是同一个文件**，同时用于标题栏 / 窗口图标 / 启动页（不另设启动页专属标志）。
   理由：用户已选定「同一范围」，单一来源最不容易出错。

---

## 2. 现状事实（已核实，附出处）

### 2.1 「左上角 AC 标志」有两套互不相干的实现

| 位置 | 实现 | 出处 |
|---|---|---|
| 标题栏左上角小图标 | `icon("logo").pixmap(30, 30)` → `assets/icons/logo.svg`（24×24，A 三角 + C 圆弧，`#6366F1`）。在 `icons.py` 的 `_KEEP_COLOR` 集合内 → **不参与主题染色** | `src/main_window.py:2461-2465` |
| 启动页 AC 字标 | `brand.py` 的**手绘矢量路径**（填充笔锋多边形，零字体依赖），逐笔显现 | `src/splash_window.py:148-210` + `src/brand.py` |

→ 用户换自定义图后，**启动页必须单独写「用图片替代矢量笔画」的分支**，只改 SVG 路径无效。

### 2.2 窗口/任务栏图标有 3 个来源

| # | 位置 | 现状 |
|---|---|---|
| 1 | `main.py::_app_icon()` → `app.setWindowIcon(...)` | 找 `assets/icons/logo.{png,ico,svg}`；**在 `cfg = load_config()` 之前调用**（`main.py:200` vs `main.py:249`）→ 想读用户自定义路径必须处理这个顺序 |
| 2 | `main_window.py:1569-1580` `setWindowIcon(...)` | 只找 `logo.png` / `logo.ico`，**找不到就不设** |
| 3 | `main_window.py:2679` 托盘 `icon("ac_launcher_icon")` | **独立的白色托盘资产**（与 logo 无关）；本轮**不改**（白色剪影是系统托盘的可读性要求，用户也未要求） |

→ 「窗口图标生效」= 必须同时改 #1 与 #2。

### 2.3 配置系统约束（两条铁律）

- **`_sync_ui_to_cfg` 写入的每个键必须存在于 `_DEFAULTS`**。
  否则 `is_dirty()` 恒为真 → 每次进设置页再离开都弹「有未保存的更改」（round-111 的真 bug）。
  审计脚本：`tests/audit_defaults.py`。
- **i18n 中英必须对称**。
  `_STRINGS = {"zh-CN": {...}, "en-US": {...}}`；`regress.py::run_i18n()` 正则比对两块 key 集合，差异必须为 0（当前 1369/1369）。

### 2.4 其它既有约定

- 设置页分区懒加载：`_sec_builders` 9 个分区按需构建；未构建分区的控件用 `self._safe(fn, default)` 回落 cfg。
- 文件选择器：`src/win_rounded.py::pick_files(parent, title, start_dir, filt)` → 返回 **str**（不是 list），走暗色 QSS。
- 现成「用户自定义图片」范式：`src/wallpaper.py` 的 `IMAGE_EXTS` / `IMAGE_FILTER`，配置键 `wallpaper_image` **直接存用户原路径**（不拷贝进 data/）。
- 离屏测试：`QT_QPA_PLATFORM=offscreen`。

---

## 3. 设计决策

### 3.1 新增配置键（3 个，全部加进 `_DEFAULTS`）

```python
    # ---- round-136 品牌自定义 ----
    "custom_logo_path": "",     # 用户自定义标志图（标题栏 + 窗口/任务栏图标 + 启动页共用）
    "custom_title_text": "",    # 标题栏左上角文本；空 = 用 APP_DISPLAY
    "splash_bg_image": "",      # 启动页背景图；空 = 保持现有透明背景
```

**存储策略**：直接存用户原路径，与 `wallpaper_image` 一致。
- 理由：与既有范式统一，实现简单，行为可预期（用户能看出「我选的是哪个文件」）。
- 文件被删/移动 → 读取时校验失败 → **静默回落默认**，并在设置页提示（不抛异常、不阻断启动）。

**「左上角文本」允许空串回落**：`custom_title_text` 为空 或 仅空白 → 显示 `APP_DISPLAY`。
（用户若想真的不要文字，需要另一个开关 —— 本轮**不做**，避免加无用配置项。）

### 3.2 支持的格式

`png / jpg / jpeg / bmp / webp / svg / ico`

- 加载统一走 `QIcon(path)` / `QPixmap(path)`（QtSvg 已被 `icons.py` 依赖，SVG 可用）。
- 加载失败（文件不存在 / 格式不支持 / 损坏）→ 回落默认，**不抛异常**。

### 3.3 新模块 `src/brand_custom.py`（统一入口）

供 `main_window.py` / `main.py` / `splash_window.py` 共用，避免三处各写一份路径解析。

```python
"""round-136 品牌自定义：用户自定义标志 / 标题栏文本 / 启动页背景的统一解析入口。

设计约束：
  * 任何读取都必须容错 —— 文件被删/移动/损坏时静默回落默认，绝不让启动器崩。
  * 统一在这里做「路径归一化 + 有效性校验 + 解码缓存」，三处调用方只管用。
  * 本模块不依赖 settings_dialog（避免循环 import），直接读同���个配置文件。
"""
from __future__ import annotations

import os

from .brand import APP_DISPLAY
from .paths import get_config_path

CUSTOM_LOGO_KEY = "custom_logo_path"
CUSTOM_TITLE_KEY = "custom_title_text"
SPLASH_BG_KEY = "splash_bg_image"

SUPPORTED_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".svg", ".ico")

# 进程内解码缓存： key = (绝对路径, 文件 mtime, 目标边长)
_pixmap_cache: dict = {}


def load_brand_cfg() -> dict:
    """读配置文件里与品牌自定义有关的 3 个键（读失败 → 空 dict）。"""
    try:
        import json
        with open(get_config_path("launcher_config.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {k: data.get(k, "") for k in (CUSTOM_LOGO_KEY, CUSTOM_TITLE_KEY, SPLASH_BG_KEY)}
    except Exception:
        return {}


def normalize_path(raw) -> str:
    """归一化用户给的路径；无效/空 → ""。"""
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if not s:
        return ""
    p = os.path.normpath(os.path.abspath(os.path.expanduser(s)))
    return p


def valid_image_path(raw) -> str:
    """归一化 + 校验（存在 / 是文件 / 后缀受支持）→ 合法返回绝对路径，否则 ""。"""
    p = normalize_path(raw)
    if not p:
        return ""
    if not os.path.isfile(p):
        return ""
    if not p.lower().endswith(SUPPORTED_EXTS):
        return ""
    return p


def custom_logo_path(cfg: dict | None = None) -> str:
    """自定义标志的合法绝对路径；没有则 ""。"""
    cfg = cfg if cfg is not None else load_brand_cfg()
    return valid_image_path(cfg.get(CUSTOM_LOGO_KEY, ""))


def custom_title_text(cfg: dict | None = None) -> str:
    """标题栏左上角文本；空/仅空白 → APP_DISPLAY。"""
    cfg = cfg if cfg is not None else load_brand_cfg()
    raw = cfg.get(CUSTOM_TITLE_KEY, "")
    if not isinstance(raw, str):
        return APP_DISPLAY
    s = raw.strip()
    return s or APP_DISPLAY


def splash_bg_path(cfg: dict | None = None) -> str:
    """启动页背景图的合法绝对路径；没有则 ""。"""
    cfg = cfg if cfg is not None else load_brand_cfg()
    return valid_image_path(cfg.get(SPLASH_BG_KEY, ""))


def load_pixmap(path: str, size: int):
    """按目标边长解码图片并缓存；失败返回 None。"""
    if not path or size <= 0:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (path, mtime, int(size))
    hit = _pixmap_cache.get(key)
    if hit is not None:
        return hit
    from PySide6.QtGui import QPixmap
    pm = QPixmap(path)
    if pm.isNull():
        return None
    # 等比缩放到目标边长（不放大，避免糊）
    if not pm.isNull() and max(pm.width(), pm.height()) > 0:
        pm = pm.scaled(size, size, Qt_KeepAspectRatio(), Qt_SmoothTransformation())
    _pixmap_cache[key] = pm
    return pm
```

> 实现时 `Qt_KeepAspectRatio` / `Qt_SmoothTransformation` 用真实导入：
> `from PySide6.QtCore import Qt` → `Qt.KeepAspectRatio` / `Qt.SmoothTransformation`。
> `load_pixmap` 必须返回 `QPixmap | None`，调用方判空。

**缓存清理**：`valid_image_path` 每次都会 stat，mtime 变化 → 缓存 key 变化 → 自动失效（用户换图即刷新）。
缓存无限增长的风险可控（键数 = 用户换过的图数）。

### 3.4 `main_window.py` 改动

**(a) 标题栏**（`_build_titlebar`，约 2452-2470）：

```python
        logo = QLabel()
        logo.setPixmap(self._titlebar_logo_pixmap())
        logo.setFixedSize(32, 32)
        logo.setStyleSheet("padding-left: 2px;")
        lay.addWidget(logo)
        self._tb_logo = logo
        name = QLabel(brand_custom.custom_title_text(self.cfg))
        name.setProperty("cls", "big")
        name.setStyleSheet(f"color: {COLORS['accent']}; font-weight: 600; font-size: 15px;")
        lay.addWidget(name)
        self._tb_name = name
```

**重要**：`self.titlebar = self._build_titlebar()` 只在 `__init__` 跑一次（`main_window.py:1650`），
`retranslate_ui()` 只刷 `_refresh_win_icons()` → **保存设置后必须主动刷新标题栏**。

**(b) 新增方法**：

```python
    def _titlebar_logo_pixmap(self):
        """标题栏标志：优先用户自定义图，回落内置 logo.svg。"""
        pm = brand_custom.load_pixmap(brand_custom.custom_logo_path(self.cfg), 30)
        if pm is not None and not pm.isNull():
            return pm
        return icon("logo").pixmap(30, 30)

    def _refresh_titlebar_brand(self):
        """设置保存后刷新标题栏标志与左上角文本。"""
        lb = getattr(self, "_tb_logo", None)
        if lb is not None:
            lb.setPixmap(self._titlebar_logo_pixmap())
        nm = getattr(self, "_tb_name", None)
        if nm is not None:
            nm.setText(brand_custom.custom_title_text(self.cfg))

    def _apply_window_icon(self):
        """窗口/任务栏图标：优先用户自定义图，回落内置 logo。"""
        path = brand_custom.custom_logo_path(self.cfg)
        if path:
            ico = QIcon(path)
            for _sz in (16, 24, 32, 48, 64, 128, 256):
                ico.addPixmap(ico.pixmap(_sz, _sz))
            self.setWindowIcon(ico)
            return
        # 回落：现有 assets/icons/logo.{png,ico}
        ...
```

**(c) 接线点**：
- `__init__` 里现有的 `setWindowIcon(...)`（1567-1583 行）→ 换成调用 `self._apply_window_icon()`。
- `_on_settings_saved()`（约 3555 行）→ 在 `self.cfg = load_config(); self.retranslate_ui(); self.home._refresh()` 之后追加：
  `self._refresh_titlebar_brand()` + `self._apply_window_icon()`。

**(d) import**：加 `from . import brand_custom`。

### 3.5 `main.py` 改动（任务栏图标）

`_app_icon()` 目前在 `cfg = load_config()` 之前调用。
处理方式：**把用户自定义路径的读取放进 `_app_icon()` 内部**（函数内局部 import + 读一次配置），
不动 `main()` 里的语句顺序 —— 顺序调整风险大于收益。

```python
def _app_icon() -> QIcon:
    """Load the AC Launcher icon: user custom logo wins over the built-in asset."""
    try:
        from src.brand_custom import custom_logo_path
        p = custom_logo_path()
        if p:
            return QIcon(p)
    except Exception:
        pass
    base = os.path.dirname(os.path.abspath(__file__))
    for ext in ("png", "ico", "svg"):
        p = os.path.join(base, "assets", "icons", f"logo.{ext}")
        if os.path.isfile(p):
            return QIcon(p)
    return QIcon()  # fallback: OS default
```

注意：`main.py` 在仓库根、`src` 是包 → import 形式是 `from src.brand_custom import ...`（与 `main.py` 现有的 `from src.splash_window import SplashWindow` 一致）。
`src/brand_custom.py` 内部的相对 import（`from .brand import ...`）在包内可用。

### 3.6 `splash_window.py` 改动

**(a) `__init__` 读配置**（`SplashWindow()` 目前无参，`main.py:293` 调用）：

```python
        from . import brand_custom
        self._logo_pm = brand_custom.load_pixmap(brand_custom.custom_logo_path(), 160)
        self._bg_pm = brand_custom.load_pixmap(brand_custom.splash_bg_path(), 960)
```

（用局部 import 避免 `splash_window` ← → `brand_custom` 的循环；`brand_custom` 不 import `splash_window`，其实安全，但保持局部 import 与本文件既有风格一致。）

**(b) `paintEvent` 改动**：

1. **背景图**（仅当 `self._bg_pm` 非空）：
   - 绘制到整个 widget：`p.drawPixmap(target_rect, pm)`，target_rect 用 **cover** 铺满（保持比例、居中裁切）。
   - 覆盖一层半透明暗色蒙版（`QColor(0,0,0,120)` 左右）→ 保证前景标志/进度条在任何背景下都可读。
   - 背景为空 → 保持现状（透明背景，无面板）。
2. **标志**（仅当 `self._logo_pm` 非空）：
   - **替代**矢量 AC 字母（不再画笔锋路径）。
   - 位置：与原字母同一视觉中心 `cx = w//2, cy = int(h*0.40)`。
   - 尺寸：等比缩放到**高度 112**（与原 `target_h = 112.0` 对齐）。
   - 动画：用现有 `self._phase` 做 **淡入 + 轻微放大**（`_smooth((self._phase - 0.05) / 0.40)` 与字母 A 的显现曲线一致）：
     `scale = 0.86 + 0.14 * l`，`alpha = l`。
     - 绘制时用 `p.setOpacity(alpha)`，画完 `p.setOpacity(1.0)`。
   - 进度条**完全保留**（位置、样式、100% 收敛逻辑不动）。
3. 标志为空 → 现有矢量路径**一行不改**（保证默认体验零变化）。

**(c) 保留**：`_TOTAL = 1.6`、进度条 `prog = _smooth((self._phase - 0.12) / 0.88)` 逻辑不动。

### 3.7 `settings_dialog.py` 改动

**(a) `_DEFAULTS`**：加 3 个键（见 §3.1），放在 `# ---- round-136 品牌自定义 ----` 注释块下。

**(b) UI —— 外观页新增「品牌自定义」组**（`_page_appearance()` 内，紧跟现有 4 组之后）：

```
品牌自定义
  [标志图片]  (<路径只读显示>)  [选择...] [清除]
  提示：自定义图片会同时用于左上角标志、窗口/任务栏图标和启动页标志。
  [预览缩略图 40x40]

  [左上角文本]  [QLineEdit，占位符 "AC Launcher"]
  提示：留空显示默认「AC Launcher」。不影响窗口标题（窗口标题用于单实例提拉）。
```

- 控件成员名：`self.brand_logo_path`（QLineEdit, 只读）、`self.brand_logo_pick`（QPushButton）、`self.brand_logo_clear`（QPushButton）、`self.brand_logo_preview`（QLabel）、`self.brand_title_text`（QLineEdit）。
- 选择按钮 → `pick_files(self, t("settings.brand_logo_pick_title"), "", IMAGE_FILTER)`；`pick_files` 返回 **str**。
- 选中后立即刷新预览缩略图。
- 清除按钮 → 清空路径 + 预览。

**(c) UI —— 启动动画组新增背景图**（`_page_launch()` 的 `boot_grp` 内，紧跟现有 `splash_on` 与 hint）：

```
  [启动页背景图]  (<路径只读显示>)  [选择...] [清除]
  提示：留空则启动页保持透明背景。
```
控件成员名：`self.splash_bg_path`（QLineEdit, 只读）、`self.splash_bg_pick`、`self.splash_bg_clear`。
注意命名冲突：`self.splash_bg_path` 与模块函数名同名会遮蔽 —— 函数 `brand_custom.splash_bg_path()` 是**模块属性**，不受影响；但为清晰起见 UI 成员用 `self.splash_bg_edit`。

**(d) `_sync_ui_to_cfg`**（必须写进 target，且键已在 `_DEFAULTS`）：

```python
        target["custom_logo_path"] = self._safe(
            lambda: self.brand_logo_path.text().strip(), target["custom_logo_path"])
        target["custom_title_text"] = self._safe(
            lambda: self.brand_title_text.text().strip(), target["custom_title_text"])
        target["splash_bg_image"] = self._safe(
            lambda: self.splash_bg_edit.text().strip(), target["splash_bg_image"])
```

> `_safe(fn, default)` 是既有的「分区未构建时回落 cfg」封装，签名照抄现有用法。

**(e) 懒加载注意**：外观页与启动页是**两个不同分区** → 两处控件可能一个已构建一个没构建。
`_sync_ui_to_cfg` 用 `self._safe` 逐项回落 → 未构建的一侧回落 cfg 原值 → 不会误清空。

**(f) import**：`from . import brand_custom`（用于校验/预览）。

### 3.8 `i18n.py` 改动（中英严格对称，+7 对）

| key | zh-CN | en-US |
|---|---|---|
| `settings.brand` | 品牌自定义 | Brand customization |
| `settings.brand_logo` | 左上角标志 | Titlebar logo |
| `settings.brand_logo_hint` | 自定义图片将同时用于左上角标志、窗口/任务栏图标和启动页标志。支持 PNG / JPG / BMP / WEBP / SVG / ICO。 | Your image is used for the titlebar logo, the window/taskbar icon and the splash logo. PNG / JPG / BMP / WEBP / SVG / ICO supported. |
| `settings.brand_title_text` | 左上角文本 | Titlebar text |
| `settings.brand_title_text_hint` | 留空则显示默认「AC Launcher」。不影响窗口标题（窗口标题用于单实例提拉）。 | Leave blank to show the default "AC Launcher". The window title is unaffected (it drives single-instance focus). |
| `settings.splash_bg` | 启动页背景图 | Splash background |
| `settings.splash_bg_hint` | 留空则启动页保持透明背景。 | Leave blank to keep the splash screen transparent. |

**顺带修正已脱节的文案**（round-65 已删掉旋转光环与逐字标语，`settings.splash_hint` 仍在描述它们）：

- zh：`"开场动画：AC 字标缩放淡入 + 底部进度条。可在下方自定义启动页背景图与标志。"`
- en：`"Intro: the AC wordmark scales and fades in over a bottom progress bar. Customize the background and logo below."`

**i18n 计数**：1369 → 1376（两块同时 +7）。

### 3.9 测试

**新增 `tests/test_brand_custom.py`**（离屏，`QT_QPA_PLATFORM=offscreen`）：

1. `_DEFAULTS` 含 `custom_logo_path` / `custom_title_text` / `splash_bg_image`，且默认值分别是 `""` / `""` / `""`。
2. `brand_custom.custom_title_text({})` == `APP_DISPLAY`；`{"custom_title_text": "  "}` == `APP_DISPLAY`；`{"custom_title_text": "My Launcher"}` == `"My Launcher"`。
3. `brand_custom.custom_logo_path({"custom_logo_path": "<不存在的路径>"})` == `""`（无效回落）。
4. `custom_logo_path` 指向**真实临时图片**（用 `QPixmap` 现画一张 32×32 存 png）时返回该绝对路径；`load_pixmap(path, 30)` 返回非空 pixmap 且宽/高 ≤ 30。
5. 后缀不支持（如 `.txt`）→ `custom_logo_path` 返回 `""`。
6. `splash_bg_path` 同理（存在合法图 → 路径；不存在 → `""`）。
7. **标题栏生效**：构造 `MainWindow`（离屏）→ 设置 `cfg["custom_title_text"] = "XX"` 后调用 `_refresh_titlebar_brand()` → 断言 `self._tb_name.text() == "XX"`。
   （若 MainWindow 构造在离屏下过重，退化为：断言 `_refresh_titlebar_brand` 后 `_tb_name` 文本变化；用 `smoke_all.py` 已验证 MainWindow 可离屏构造 → 直接构造即可。）
8. **启动页不崩**：构造 `SplashWindow()`（离屏）→ `grab()` 不抛异常；且 `_logo_pm` 为 None 时默认路径分支正常。

**`regress.py`**：SUITES 追加一行：

```python
    ("品牌自定义回归", "test_brand_custom.py", "script"),
```

（插在「设置页脏检测回归」之后、「核心功能冒烟」之前。）

### 3.10 文档与记忆

- `CHANGELOG.md` 追加 round-136（2026-10-28）条目。
- `<本地工作区>\2026-10-28_AC启动器_round136_品牌自定义.md` 落盘任务记忆（用户规则：每日较长任务记忆放 <本地工作区>）。
- **不写** `D:\Environmental Box_Unity\...\待办与Bug清单.md`（本任务是 AC Launcher，与 Environmental Box 无关）。

---

## 4. 不在本轮范围（明确排除）

| 项 | 原因 |
|---|---|
| 改窗口标题 `setWindowTitle(APP_DISPLAY)` | 会破坏单实例「提拉已有实例」 |
| 托盘图标换成自定义图 | `ac_launcher_icon` 是白色剪影（系统托盘可读性要求），与 logo 无关，用户也未要求 |
| 启动页「整页一张图」模式 | 用户选的是「背景图 + 标志」 |
| 独立「不要左上角文字」开关 | 空串回落 `APP_DISPLAY` 已够用，避免加无用配置项 |
| 欢迎页 `welcome_window.py` | round-98 已标注死代码 |
| 把自定义图**拷贝**进 `data/` | 与既有 `wallpaper_image` 范式（存原路径）保持一致 |
| `settings_dialog` 导出/导入备份的敏感键处理 | 品牌自定义不是敏感信息，随备份走即可（`_SENSITIVE_CFG_KEYS` 不动） |

---

## 5. 验收标准

| # | 标准 | 验证方式 |
|---|---|---|
| A1 | 自定义标志图出现在标题栏左上角 | 离屏：`MainWindow` → `_tb_logo.pixmap()` 非空且非默认 logo |
| A2 | 同一张图出现在窗口/任务栏图标 | 离屏：`MainWindow.windowIcon().isNull()` == False 且 pixmap 非空 |
| A3 | 同一张图出现在启动页 | 离屏：`SplashWindow` → `_logo_pm` 非空；`grab()` 不抛异常 |
| A4 | 启动页背景图生效且前景可读 | 离屏：自定义背景 → `grab()` 不抛异常；有蒙版 |
| A5 | 启动页进度条保留 | 离屏：`paintEvent` 后进度条逻辑不变（代码审查 + 冒烟） |
| A6 | 左上角文本可改 | 离屏：改 cfg → `_refresh_titlebar_brand()` → `_tb_name.text()` == 新值 |
| A7 | 空值/坏路径不崩、回落默认 | `test_brand_custom.py` 断言 3/5/6 |
| A8 | 设置页保存后立即生效 | `_on_settings_saved()` 触发刷新（代码审查 + 冒烟） |
| A9 | 设置页不误报「未保存的更改」 | `tests/audit_defaults.py` 差异 == 0；`tests/test_settings_dirty.py` 通过 |
| A10 | i18n 中英对称 | `regress.py` 的 i18n 检查差异 == 0（1376/1376） |
| A11 | 全量回归绿 | `python regress.py` 全项 PASS |
| A12 | 编译通过 | `python -m compileall src main.py` |

---

## 6. 风险与预案

| 风险 | 影响 | 预案 |
|---|---|---|
| `_sync_ui_to_cfg` 写了 `_DEFAULTS` 没有的键 | 设置页每次都弹「未保存的更改」 | 新键同步加进 `_DEFAULTS`；跑 `audit_defaults.py` 兜底 |
| i18n 只加了一边 | regress i18n 检查 FAIL | 两边同时写；跑 regress 兜底 |
| 自定义图路径含中文/空格 | 加载失败 | `os.path.abspath` + `normpath`；`pick_files` 返回绝对路径 |
| `main.py` 顶部 import 循环 | 启动崩溃 | `brand_custom` 只依赖 `brand` + `paths`；`main.py` 用**局部 import** |
| `QIcon(path)` 对 jpg/webp 支持不确定 | 图不显示 | `load_pixmap` 走 `QPixmap(path)`（走 Qt 图像插件，支持范围与 Pillow 无关），失败静默回落 |
| 启动页背景图过大导致卡顿 | 启动慢 | 背景图按 960px 解码缓存，不加载原尺寸大图 |
| 标题栏不随 `retranslate_ui()` 重建 | 保存后不刷新 | 已在 `_on_settings_saved()` 显式接 `_refresh_titlebar_brand()` |
| 离屏构造 `MainWindow` 过重/失败 | 测试跑不起来 | 断言拆到最小单元；必要时只测 `brand_custom` 纯函数 + `SplashWindow` |

---

## 7. 预计改动文件清单

| 文件 | 改动性质 |
|---|---|
| `src\brand_custom.py` | **新增**（统一解析入口） |
| `src\main_window.py` | 改：标题栏 logo/文本、窗口图标、设置保存刷新 |
| `src\main.py` | 改：`_app_icon()` 优先自定义图 |
| `src\splash_window.py` | 改：背景图 + 自定义标志分支，保留进度条 |
| `src\settings_dialog.py` | 改：3 个配置键 + 外观页「品牌自定义」组 + 启动页背景控件 + `_sync_ui_to_cfg` |
| `src\i18n.py` | 改：+7 对中英文案 + 修正 `settings.splash_hint` |
| `tests\test_brand_custom.py` | **新增** |
| `regress.py` | 改：SUITES +1 |
| `CHANGELOG.md` | 改：round-136 条目 |
| `<本地工作区>\2026-10-28_AC启动器_round136_品牌自定义.md` | **新增**（任务记忆） |

---

## 8. 批准

本规格需用户确认后施工。请重点核对：

1. 「左上角 AC 文本」= 标题栏 logo 右侧的文本（**窗口标题不动**）——是否合你意？
2. 自定义标志**一个文件三处共用**（标题栏 / 窗口图标 / 启动页）——是否合你意？
3. 启动页背景图默认**保持透明**（只有你设了图才铺背景）——是否合你意？
4. 换自定义图后**即时生效**（保存设置即刷新标题栏与图标；启动页下次启动生效）——是否合你意？
