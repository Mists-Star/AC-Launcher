# Spec — round-144「仅留文字与背景，白色文字底不要」

AC Launcher（`mc_launcher 仓库根`）壁纸模式下去掉文字背后的白色底：
只保留 **文字 + 壁纸背景**，交互控件（按钮/输入框/下拉/弹层）仍走实色。

## 用户需求轨迹（事实 spec）

1. 「背景和白色背景影响视觉」
2. 「完整保留壁纸和后方显示，白框去掉（默认背景就是白的）」
3. **「仅留文字与背景，白色文字底不要」**（最终方向，本轮执行依据）

截图证据：首页 hero 整块白卡浮在壁纸上；实例页白色左列表 + 白色详情面板 + 页头灰条。

## 已查明的白底来源（全部实读确认）

| # | 来源 | 位置 |
|---|------|------|
| 1 | `QWidget { background: $bg_app_frost }`，壁纸模式 = `#FFFFFF` alpha185，亮壁纸上≈纯白 | theme.py:492-497、1180-1187 |
| 2 | `$glassy` = 实色 `bg_card`（`_frosted=False`）→ `[cls=card]`/`QFrame[cls=card]`/`QGroupBox`/`[cls=surface]`/`[cls=row]`/`[cls=loader-card]`/`QFrame[cls=latest]`/`QFrame[cls=vrow]` | theme.py:1198；模板 516/521/525/530/929/1010/1022/1054/1120/1142 |
| 3 | `RoundedCard` 默认 fill=None → paintEvent 实色 `bg_card`（首页 hero `main_window.py:705` 等） | theme.py:1287-1296 |
| 4 | `LightTrailCard` 走 `_card_fill()` 实色（实例详情卡 `pages_instances.py:1546`、`_InstRow:322`、首页实例网格） | effects.py:125-129、208-215 |
| 5 | 页头/页脚/标题栏/状态栏硬条：`$bg_panel` / `$bg_card` | theme.py:991-1007、973-978 |

**可读性保障（已有机制，无需新做）**：`_Veil`（wallpaper.py:254-286）用 `bg_app` 色覆盖壁纸，
light 主题目标 luma 0.86（白纱 alpha 0.46~0.92）——文字直接落壁纸时正文对比度已有保证；
页面标题/日志行现在就直接落在 veil 上（截图可读）。

**弹层/控件安全面**：QComboBox 下拉用 `$bg_card`、QListWidget/QToolTip/QMenu 用 `$bg_panel`、
输入框用 `$bg_input`、按钮用 `$bg_btn` —— 均不在本次替换之列，保持实色。

## 修改方案（4 个文件）

### 1. `src/theme.py` — build_qss() token 分支

`_wallpaper_surface` 判断**置顶**（先于 `_app_bg_translucent`）：

```python
if _wallpaper_surface:
    subst["bg_app_frost"] = "transparent"   # 页面底 → 透出壁纸
    subst["glassy"] = "transparent"         # 卡片/分组框/行 → 透出壁纸
    subst["band"] = "transparent"           # 标题栏/页头/状态栏
    subst["band_card"] = "transparent"      # 页脚
    subst["win_bg"] = COLORS["bg_app"]      # 主窗本体实色垫底（见下）
```

其余两个分支（`_app_bg_translucent` / 默认）里补：`band=bg_panel`、
`band_card=bg_card`、`win_bg=bg_app_frost` —— **非壁纸模式外观零变化**。

QSS 模板 4 处替换：
- `QMainWindow { background: $bg_app_frost; }` → `$win_bg`
- `[cls="titlebar"]`、`[cls="page-header"]`、`QStatusBar`：`$bg_panel` → `$band`
- `[cls="page-footer"]`：`$bg_card` → `$band_card`

`$win_bg` 的作用：① 壁纸子控件尚未盖满（加载间隙）时主窗不透出桌面；
② `ExtensionWindow(QMainWindow)`（plugin_host.py，无自绘）自动获得实色底，无需单独改。

### 2. `src/theme.py` — 卡片默认填充按窗归属判定

新增：

```python
def _on_wallpaper_window(widget) -> bool:
    """该 widget 所属顶层窗是否是铺壁纸的主窗（对话框/独立顶层返回 False）。"""
    # window().property("wallpaper_backdrop") == "1" 且 _wallpaper_surface

def default_card_fill(widget=None) -> QColor:
    """卡片默认填充：壁纸主窗上 → 全透明；对话框/独立顶层 → 现行实色。"""
```

- `RoundedCard.paintEvent`：`fill is None` 分支的 brush 改用 `default_card_fill(self)`；
  **`self._fill` 保持 None，边框/圆角逻辑（:1308）不动**。
- 对话框（`window().property` 缺失）继续实色 → 新建实例向导、登录、设置等
  白卡外观不变（对话框本来就没有壁纸）。

### 3. `src/effects.py` — LightTrailCard 同步

- `_card_fill()` → `_card_fill(widget=None)`，内部转调 `theme.default_card_fill(widget)`；
- paintEvent 调用点改为 `_card_fill(self)`（effects.py:210）。
- 流光/反射动画照旧（透明底上是轻微光泽，保留）。

### 4. `src/main_window.py` — 主窗标记

`MainWindow.__init__` 加一行 `self.setProperty("wallpaper_backdrop", "1")`（纯 Python 读取，
无需 repolish）。

## 明确不改

- 按钮 / 输入框 / 下拉 / QTextEdit / QListWidget / tooltip / menu 的实色 token；
- 对话框体系（`QDialog` → `$bg_app_solid`，卡片因无 property 保持实色）；
- SplashWindow / WelcomeWindow（自绘 paintEvent，不走 QSS 底）；
- 壁纸 `_Veil` / `_LoopFade`（自绘，无 WA_StyledBackground，QSS 不介入）。

## 边界与风险

1. **壁纸配置为 none**：`_wallpaper_surface=False` → 全部走旧分支，外观与现状完全一致。
2. **壁纸加载间隙**：`$win_bg` 实色兜底，不透桌面。
3. **dark 主题**：对称成立（veil 目标 luma 0.18，浅色文字落暗纱上）。
4. **透明后卡片边框**：`$border`（#E5E7EB）在亮壁纸上偏淡 —— 保留边框作为结构线，
   若用户嫌淡属后续迭代，不在本轮扩大范围。

## 验收步骤（未目视不判验收）

1. `python -m compileall -q src` 通过；
2. `python regress.py` 12/12；
3. WMI `Invoke-CimMethod Win32_Process Create` 拉起启动器 → 用户目视：
   - 首页：hero 无白卡，标题/实例下拉/开始游戏按钮直接在壁纸上；
   - 实例页：左右白面板、页头灰条消失，文字落壁纸；选中行/按钮仍有描边或底色；
   - 新建实例对话框仍为白卡（无壁纸窗不透）；
   - 无任何「透出桌面」穿帮。
4. 回收上轮 round-143 两项验收结论（加载器不重叠、'dict' not callable）。
5. 收尾：CHANGELOG round-144 条目 + <本地工作区> 记忆更新。
