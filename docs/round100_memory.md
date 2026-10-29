# round-100 记忆（2026-10-07）— 极简美学重构第二波

玩家指令「ac搁太久了，赶快做完」→ 执行 round-99 拍板的第二波清单（其余页面
清扫 / 欢迎页·AC 标志 / 成就入口 / 动画三件套 / OptiFine 入口移除 + 验证归档）。
第一波记忆见 `round99_memory.md`；施工计划 `.trae/documents/ac-minimal-ui-wave1.md`。

## 1. alpha 序盲区第二波清扫（系统性 ×10+ 处）

### 现象
第一波只修了资源详情/资源中心；其余页面仍有 `{color}1F` / `#22C55E1A` 式
**末尾拼 alpha** 的内联色（Qt 按 `#AARRGGBB` 解析 → 颜色完全错位）。

### 修复
一律改走 `theme.with_alpha(hex, alpha)`（alpha 在前）：
`ui_kit.badge`、`pages_instances`（`_badge_style`/「当前」标签/ModCard 启用态）、
`modules_page` 4 处、`scan_dialog` 2 处状态标、`achievements_page`、
`java_manager_dialog`、`settings_dialog` 主题色徽章、`main_window` 来源徽章。

### 实例页品牌徽章中性化（复用第一波模式）
`pages_instances` 新增 `_loader_vivid()`（读主题包 `loader_vivid` 声明）与
`_loader_badge()`：默认挂全局 `badge` 中性类，主题包声明才用品牌色。
`_fmt_badge`、`_LoaderCard`（删 color 参数，fallback 色块 → 中性 bg_hover）、
详情页 loader/java 徽章、`ModCard`（`bg=LOADER_BADGE... if _loader_vivid()`）
全部同一模式，与 `store_detail.py` 对齐。

## 2. 首页 / 登录 hero 重写

`main_window._build_home` 的 hero：accent→#28BCD8 大渐变底 + 白字 + 白 pill +
白底 combo 全套内联 → `RoundedCard(radius=16, accent_border=3)`（唯一强调 =
左侧 3px 竖条）+ `badge`/`sub` 类 + 全局实例选择器样式；主按钮直接沿用
`_make_play_btn()`（accent 实底）；kill → `cls="danger"`；hero 高 192→176。
`login_dialog._build_hero` 同款（紫→洋红渐变 + 白字 → 中性卡 + tile 图标 + 类）。

## 3. 成就弹窗默认关

`settings_dialog._DEFAULTS["achievement_toasts"] = False`；设置→效果加
`ach_toast_chk`（含 `_hint` 提示语，i18n 补键）；`main_window._show_achievement_toast`
首行 `if not cfg.get("achievement_toasts", False): return`。成就页入口不变
（左侧导航 `nav.achievements`），弹窗只是可选的即时反馈。

## 4. 欢迎页 token 化

`welcome_window` 暗色文字色从硬编码 `#A78BFA` → `COLORS["text_accent"]`
（自定义 accent 时自动 `_lighten(0.15)`，与全站联动）；亮色分支保持
`accent_text()`（round-91：防浅色 accent 在白底不可读）。AC 像素墨迹渲染、
透明画布、1100ms 浮现动画维持 round-93 方案，无结构改动。

## 5. 动画打磨（克制）

* `effects.fade_page_transition`：150→160ms；新页追加 **8px 上浮汇入**
  （180ms OutCubic）。防漂移关键：上浮前 `stack.layout().activate()` 强制
  同步布局拿真实落点，`rise.finished` 再 `move(end_pos)` 归位——连续切换/
  中途打断都不累积偏移（诊断脚本断言 pos 归位 + effect 必清）。
* 新增 `effects.fade_in_widget(w, duration=170)`：一次性
  QGraphicsOpacityEffect 淡入，结束必清 effect（同防重影策略），重复触发先
  清旧 effect。应用点：资源中心结果列表（仅 `reset` 整页重置，加载更多不闪
  整屏）、实例列表 `_refresh`（作用在 `scroll.viewport()`，滚动中无重影）。
* 按压反馈沿用既有 QSS（`QPushButton:pressed` / accent/secondary/chip 各有
  pressed 态），本轮未改。

## 6. OptiFine 资源中心入口移除（拍板）

`net_api.STORE_CATEGORIES` 去 `("optifine", ...)`；`pages_browse` 同步清理
import、`_cat_btns["optifine"].setToolTip` 行（不删会 KeyError）、`_load`
分支、`_load_optifine` 方法、`_download` 的 optifine 分支（签名简化为
`cf_file`）。OptiFine 仍可从「新建实例 → 加载器」独立入口使用。

## 7. 验证与证据

* `py_compile` 14 个改动文件全过（含 main.py 启动链）
* `_audit_i18n.py`：886 键，仅 3 个已知误报（`key`/`scan.note_`/`some.key`）
* `_diag_round100_tmp.py`（新增离屏回归，17 项全过）：动画零漂移/effect 清理、
  成就默认关、分类按钮=表长、`StorePage` 无 optifine 残留、实例页 8 位 hex
  全为「alpha 在前 + 体为已知 token」（抓 #RRGGBBAA 回归）、欢迎页 token 化
* `_diag_store_detail_tmp.py`（第一波回归）24 项全过
* 真机启动（`AC_DEV_TEMP=1` 隔离数据）：`_startup.log` 到 `MainWindow built`
  + 两次 `hero done`（初始 + retranslate 重建）无异常，log 无 traceback

### 环境教训
离屏（`QT_QPA_PLATFORM=offscreen`）下本机**所有文字渲染成 tofu 方框**（字体
缺失），离屏截图只能校验几何/配色/中性化，**文字排版必须真机目检**；诊断脚本
末尾用 `os._exit(code)` 绕过 PySide6 6.11×Py3.13 解释器 shutdown 的
fail-fast(0xC0000409)，否则退出码恒定 3221226505。

## 8. 玩家复核补充：查bug + 反花哨复审

玩家随后拍了一遍：「查bug，对了，不是极简吗，颜色不能给我搞的花里胡哨吧」。

### 硬编码色修复 4 处
* `pages_instances._style_filter_btn`：选中态白字 `#FFFFFF` → 
  `COLORS['text_on_accent']`（自定义浅 accent 时白字几乎不可读，bug）
* `pages_instances` splitter hover：硬编码紫 `rgba(124,58,237,0.3)`（旧默认
  accent）→ `with_alpha(COLORS['accent'], 0x3D)`，随自定义 accent 联动
* `settings_dialog` 自定义色圆点：`#33333A/#555555/#9CA3B0` → 
  `COLORS['bg_input']/COLORS['border']/COLORS['text_sub']`
* `login_dialog`：清理未使用的 `QColor/QLinearGradient` import

### modules_page 去花（类型徽章中性化）
旧版按模块类型给 4 种品牌色（`_TYPE_COLORS`，#8B5CF6/#3B82F6/#22C55E/
#F59E0B，两种列表 ×2 处）——与加载器徽章同一问题：多色同屏显花、硬编码色
不随主题/accent 联动。二进制化处理：类型徽章 → 中性 `cls="badge"`（类型名
文字已足够区分）；作者/描述灰字 `#9CA3AF`/`#6B7280` → `cls="sub"`（4 处）；
已应用/已安装绿标 `#22C55E` → `COLORS['success']` + `with_alpha` 底色（与
scan_dialog 状态标同一口径）；内置蓝标 `#3B82F6` → 中性 badge。`_TYPE_COLORS`
字典整块删除。

### 全页面计量审计（新增 `_audit_visual_tmp.py`）
离屏构建真实配置 MainWindow（light + #7C3AED），逐页 grab 后统计**高饱和
像素面积占比**（`getHsvF`：s>0.45 且 v>0.25，步长 ~1/180 采样）+ 全树扫
8 位 hex 内联（校验体是否为已知 token，抓 #RRGGBBAA 反序回归）：

```
home 1.86% / settings 1.20% / music 0.67% / lobby 0.51% / store 0.49% /
achievements 0.34% / mods 0.14% / instances 0.03% / versions 0.03% /
toolbox 0.00% / console 0.00%     ← 全部 ≤2%（阈值 6% 复核线）
8-hex 内联反序残留：无（修 modules_page 前抓出 1 处 #1F8B5CF6）
```

home 的 1.86% = hero 主按钮实底 + 3px 竖条 + 边框/图标点缀（允许面），其余
页面均为小面积状态标。截图复核 mods 页：绿/灰/紫块均为 token/类驱动
（success 12% 底 / badge / tile），ModsPage（pages_instances L2548+）零硬编码
色。结论：当前默认外观无「大面积高饱和」，符合极简口径。

## 9. 后续（未做）

* 非默认 home 模板（`_build_pcl_card` / `_build_modrinth` 等）的内联色未清扫
  ——默认 `home_style=ac_default`，模板切换功能 round-32 已删，低优先
* Nuitka 打包版 shiboken6 ImportError（历史遗留，未动）
  —— **round-133 已关闭**：改用 PyInstaller onedir，同版本组合构建/启动通过，
  详见 CHANGELOG round-133。