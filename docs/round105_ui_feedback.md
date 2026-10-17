# round-105 UI/UX 反馈清单与修复计划（来自用户手工测试）

> 来源：用户在测试包 `<workspace>\AC_Launcher_test_run\AC_Launcher\AC_Launcher.exe` 上反馈（3 张截图 + 文字）。
> 本文件是 round-105 的执行清单；与 `round105_plan_feature_expansion.md`（A2/A1/B6 方案）并存，后者留到后续批次。

## 0. 用户已确认的决策
1. **分辨率预设 → 完全删除**（启动器不再给游戏传分辨率，由玩家在游戏内自由拖动窗口缩放）。
2. **版本下载时机 → 改为「点安装/选版本即下载」**（不再等启动时才补版本）。
3. **首页 → 先做极简版**（只留「当前实例 + 开始游戏」+ 一行修复提示；3D 皮肤小人后续单独立项）。

## 1. 已完成（round-105 第一批，已 compile 通过）
- **T1 主题色未同步**：首页「开始游戏」大按钮改主题色后仍是旧紫色。
  根因：`_make_play_btn` 用**内联 setStyleSheet 烘焙**了构造时的 `COLORS['accent']`；切 accent 时全局 QSS 会重生（侧边栏跟着变），但内联样式被冻结不更新。
  修法：在 [theme.py](../src/theme.py#L589-L601) 新增 QSS 类 `QPushButton[cls="play"]`（用 `$accent` 变量）；[main_window.py `_make_play_btn`](../src/main_window.py#L464-L483) 改为 `cls="play"`，删除内联样式。
- **T2 重复的「当前」**：新建实例向导「选择游戏版本」页，被选中版本行同时出现绿色「✓ 当前」徽章 + 黄色「当前」按钮。
  修法：[pages_instances.py `_make_version_card`](../src/pages_instances.py#L740-L750) 删除多余绿色徽章块，只保留按钮侧状态。

## 2. 待办清单（含代码触点）

### T3 分辨率预设 → 完全删除
- UI 组：[settings_dialog.py L517-L565](../src/settings_dialog.py#L517-L565)（`res_grp`：8 档预设 + `rw`/`rh` spinbox）
- 联动方法：`_apply_res_preset` [L1325](../src/settings_dialog.py#L1325-L1328)、`_sync_res_preset` [L1330](../src/settings_dialog.py#L1330-L1341)
- 默认值/保存：`_DEFAULTS` `res_w/res_h` [L47-L48](../src/settings_dialog.py#L47-L48)、`_collect` [L2161-L2163](../src/settings_dialog.py#L2161-L2163)
- 启动消费：[launch.py L264-L265](../src/launch.py#L264-L265)（`resolutionWidth/Height`）、[L773](../src/launch.py#L773)（`res=...`）
- 处理：删 UI 组与两个联动方法、删 `_DEFAULTS` 两项与保存赋值；`launch.py` 侧让 `res=None`（不再强制分辨率）。注意旧配置里已存的 `res_w` 会被 `L773` 读到 → 需一并忽略/清除，才能真正“不设分辨率”。
- i18n（删或留）：`settings.resolution_preset` / `res_hd/900p/fhd/16x10_fhd/2k/16x10_2k/ultrawide/4k` / `width` / `height`（zh [L1225 起](../src/i18n.py#L1225)，en [L2594 起](../src/i18n.py#L2594)）。如删需 zh+en 双边一起删。

### T8 版本下载时机前移
- 现状：版本库「安装」→ [pages_browse.py `_create` L295-L309](../src/pages_browse.py#L295-L309) 只开新建实例向导、**不下载**；新建实例 → [pages_instances.py](../src/pages_instances.py)（`NewInstanceDialog`，创建信号 [L466](../src/pages_instances.py#L466)）；下载真正发生在**首次启动**时 [launch.py L535-L616](../src/launch.py#L535-L616) 调 [core/install.py `install_instance` L21-L60](../src/core/install.py#L21-L60)。
- 目标：实例创建后立即在后台下载（复用 `install_instance` + 现有进度回调/`launch_dialog` 的进度条范式），状态可显示「下载中 → 就绪」。启动时若已就绪则跳过。
- 需评估：进度回调链、UI 等待、失败重试、并发实例。

### T9 首页极简（先做版）
- 实现类：[main_window.py `HomePage` L270-L313](../src/main_window.py#L270-L313)；主体 [`_build_ac_default` L513-L678](../src/main_window.py#L513-L678)（统计条 / Hero 卡 / 启动按钮 / 实例网格 / 修复日志 / 快捷操作行）。
- 目标：仅留「当前实例 + 开始游戏」（`_make_play_btn`）+ 一行修复/异常提示；删除统计条、实例网格、多余快捷行。（3D 小人后续立项。）

### T4 实例设置对话框排版（底部横向滚动 = 禁止）
- 位置：[pages_instances.py `_edit_instance_settings` L1866](../src/pages_instances.py#L1866)。
- 参照已验证范式：[settings_dialog.py L350-L369](../src/settings_dialog.py#L350-L369)（每个 page 包 `QScrollArea` + `setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)` + `page.setMinimumWidth(0)`）。实例设置要同样禁止横向滚动、避免被挤成两列。

### T5 实例页「收起」键
- 位置：实例页折叠相关（`QSplitter` 样式 [pages_instances.py L1272](../src/pages_instances.py#L1272) 附近；折叠按钮/`_list_panel_visible`/`fold`）。用户反馈：设计奇怪、位置会偏移。需重做为一个位置稳定、语义清晰的收起/展开控件。

### T6 左侧栏收起成纯图标（像 Blockhelm）
- 位置：[main_window.py `NAV_KEYS`/`NAV_GROUPS` L54-L80](../src/main_window.py#L54-L80)、[`_build_ac_nav` L2094-L2136](../src/main_window.py#L2094-L2136)、`_populate_ac_nav`、导航 `QListWidget`。
- 目标：可收起为只剩图标（悬停/点击展开），宽度动画平滑。

### T7 精简重复/繁杂的分页
- 位置：`NAV_GROUPS` [L54-L80](../src/main_window.py#L54-L80)。
- 需与用户确认**具体哪些页面重复/多余**，再做合并/删除（不要凭猜测删功能）。

## 3. 验证要求（每批）
`python -m compileall -q src main.py` → `QT_QPA_PLATFORM=offscreen` 离屏冒烟（文字渲染为方块，仅验结构/逻辑）→ i18n zh/en 键 parity（无单边键）→ 交用户真机验收。

## 4. round-107 新反馈批次（用户第二轮手工测试）

### 已完成（compile + 离屏冒烟 + i18n parity 最终 1271/1271）
- **T3 分辨率预设 → 完全删除**：删 UI 组 / `_apply_res_preset` / `_sync_res_preset` / `_DEFAULTS` 的 res_w·res_h；`_collect` 改为 `pop` 清除旧配置残留；[launch.py](../src/launch.py) 显式 `res=None`；i18n 相关 13 键 zh+en 双边删除。
- **N3 版本图标 → MC 3D 等距方块**：`async_image.make_version_pixmap` 回归 3D 方块，用随包真实贴图渲染（正式版草方块 / 快照命令方块 / 愚人节蛋糕 / 旧版铁砧·圆石），贴图缺失回退纯色向量块；不再用「纯色块 + 版本号文字」（长版本号被截断的痛点消失）。
- **N4 进度条重做**：theme 新增 QSS 类 `QProgressBar[cls="slim"]`（柔和轨道 + 圆角 accent 填充，高度 6px）；launch_dialog 去内联「黑框+方块」样式，百分比改旁侧标签；状态栏进度条同用 slim。
- **N1 启动/下载对话框可召回**：底部状态栏进度条可点击 → 重新召回被收起的启动对话框（`_reopen_launch_task` + `eventFilter`），tooltip 提示「点击返回当前任务」。
- **N2 自动持续加载 + 卡片淡入**：
  - 新建实例向导版本页：移除手动「显示全部」按钮，改为**滚到底自动展开下一组**（`_on_ver_scroll`）；新出现卡片淡入（旧卡片不复播）。
  - 资源中心：移除被隐藏的「加载更多」按钮（冗余 UI），加载更多时新卡片逐条淡入。
  - 版本浏览页：卡片加入淡入动画。
  - **顺带修真实 bug**：「全部」过滤下「最新版本」块用 `continue` 跳过了完整正式版列表 → 大量正式版被隐藏。已删除该特例，改为按分组完整渲染（无重复、无隐藏）。
- **T8 版本下载前移**（选择即下载，而非首次启动补下载）：
  - `main_window.py` 新增 `_start_instance_download` / `_on_download_progress` / `_on_download_done` / `_on_download_error`：实例创建后立即用 `ProgressWorker(install_instance)` 后台下载；状态栏进度 + 可召回下载对话框；`_reopen_launch_task` 改为「下载任务优先」。
  - `launch_dialog.py` 新增 `mode="download"`（只显示「安装 / 补齐」两步，标题/提示换成下载语义；`mark_done()` 泛化，`mark_launched()` 保留兼容）。
  - `pages_instances.py`：新增 `instance_created` 信号（页面内新建也上报）、`set_instance_task()` + `_InstRow` 任务徽标（下载中 {pct}% / 就绪）。
  - 启动侧天然跳过：`install_instance` 幂等（只补缺失文件），文件齐备后启动走 `launch.py` 的 `_skip` 直通；同时在 `_handle_play` 加护栏——该实例下载未完成时不并发启动（防止双写同一目录）。
  - 仅对 AC 自建（非 `external`）实例触发，绝不向其他启动器的真实目录写入。

### 已完成（本批其余项）
- **N5 效果开关 → 改为可选模块（插件）**：用户决策「这些功能不是可以加成插件吗」。把「玻璃拟态 / 透底 / 流光 / 页面动画 / 成就弹窗」等外观效果从设置页移出，做成 `data/modules/<id>/manifest.json` 形式的可选模块（装入后生效），设置页保持极简、效果默认不装。改动：`modules.py`（`type="effect"`、`EFFECT_CONFIG_KEYS`、`apply_effect_module`/`_reapply_appearance`）、`modules_page.py`（应用/卸载接线）、`assets/modules/catalog.json` + 5 个 effect bundle、`i18n.py`（`modules.type_effect`）、`settings_dialog.py`（移除 5 个效果勾选）。
- **T7 导航精简（用户已确认方向）**：移除导航入口 **版本库(versions)**、**模组(mods)**、以及「其他」分组里的 **音乐 / 成就 / 控制台**；功能保留，改由实例页 / 资源中心 / 设置页内的入口承接（`settings_dialog` 新增 `open_page` 信号；`StorePage.open_versions_requested`）。首页各栏目一并精简（T9）。
- **T6 左侧导航收起成纯图标**（像 Blockhelm）：标题栏常驻汉堡按钮 `nav_toggle_btn`、`_toggle_nav_collapsed` 宽度动画、`_populate_ac_nav(icons_only)`；`theme.py` 新增 `#ac-nav` 紧凑 QSS。
- **T4 实例设置对话框排版**：`_edit_instance_settings` 改为 `QScrollArea` + `ScrollBarAlwaysOff`（禁止横向滚动、不再被挤两列）。
- **T5 实例页「收起」键重做**：原「展开条 + 折叠按钮」双按钮方案整体移除，改为页头常驻图标按钮 `panel_btn`（位置永不偏移，图标方向 + tooltip 表语义）。

### 待办
- **真机目检一次**：离屏截图受环境字体限制（文字为方块），需在真机确认下载对话框（下载中/就绪）、实例行任务徽标、导航图标模式的排版与落位。

### 已完成补充
- **T9 首页极简**：删除统御统计条 / 实例卡片网格 / 修复日志卡 / 快捷操作行，只留「hero 当前实例卡 + 开始游戏 + 结束游戏 + 一行修复提示」。清理 `_stat_cell` / `_quick_chip` / `_refresh_stats` 统计逻辑与相关 i18n 键（双语删除后 parity 1247/1247）。
