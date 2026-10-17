# round-107 记忆：全启动器 UI/UX 反馈批次（用户手工测试第二轮）

> 日期：2026-10-17。承接 `round105_ui_feedback.md`（执行清单）与 `round105_plan_feature_expansion.md`（功能扩展方案）。
> 本文件记录 round-107 批次的最终落地与验证；清单本身在同目录 `round105_ui_feedback.md` §4。

## 背景（用户反馈 → 决策）

用户在测试包上跑了第二轮手工测试，反馈集中在四类：**排版/交互冗杂**、**效果看不见**、**列表加载生硬**、**下载时机**。已锁定的决策：

- 左侧导航「最简」：移除 模组 / 版本库 / 音乐 / 成就 / 控制台 五个入口，功能改由页面内入口承接。
- 外观效果（玻璃拟态 / 透底 / 流光 / 页面动画 / 成就弹窗）**从设置页移出，改为可选模块**（默认不装），不再追加改动透明度/可见性。
- 版本下载时机**前移**：点安装/选版本即下载，而非首次启动才补版本。
- 分辨率预设**完全删除**（改为鼠标角标缩放）。

## 本轮改动一览

| 项 | 内容 | 主要文件 |
|---|---|---|
| T3 | 分辨率预设完全删除（UI 组 + 联动方法 + `_DEFAULTS` + i18n 13 键双边） | `settings_dialog.py` / `launch.py` / `i18n.py` |
| T4 | 实例设置对话框改 `QScrollArea` + `ScrollBarAlwaysOff`（禁止横向滚动/挤两列） | `pages_instances.py` |
| T5 | 实例页「收起」键重做：删「展开条+折叠按钮」双按钮，改页头常驻 `panel_btn`（位置永不偏移） | `pages_instances.py` |
| T6 | 左侧导航可收起为纯图标（像 Blockhelm）：标题栏汉堡 `nav_toggle_btn` + 宽度动画 + `icons_only` 重排 + `#ac-nav` 紧凑 QSS | `main_window.py` / `theme.py` |
| T7 | 导航精简（移除 5 入口）；设置页新增 `open_page` 信号、资源中心新增 `open_versions_requested` 承接入口；`_show_page` 重写、`_switch_stack` 默认关页面动画 | `main_window.py` / `settings_dialog.py` / `pages_browse.py` |
| T8 | **版本下载前移**：实例创建后立即后台下载；状态栏进度 + 可召回下载对话框；实例行「下载中 {pct}% → 就绪」徽标 | `main_window.py` / `launch_dialog.py` / `pages_instances.py` |
| T9 | 首页极简：只留 hero 当前实例卡 + 开始游戏/结束游戏 + 一行修复提示 | `main_window.py` |
| N1 | 启动/下载对话框可召回：状态栏进度条可点击 → 重开被收起的对话框 | `main_window.py` |
| N2 | 自动持续加载 + 卡片淡入（版本页滚到底续载、资源中心逐条淡入、版本浏览卡淡入）；顺带修「全部」过滤下正式版被 `continue` 隐藏的真 bug | `pages_instances.py` / `pages_browse.py` |
| N3 | 版本图标回归 MC 3D 等距方块（草方块/命令方块/蛋糕/铁砧·圆石），不再用文字块 | `async_image.py` |
| N4 | 进度条重做：`QProgressBar[cls="slim"]`（6px 圆角 accent 填充），去「黑框+方块」内联样式，百分比改旁侧标签 | `theme.py` / `launch_dialog.py` |
| N5 | 效果开关 → 可选模块：`type="effect"` + `EFFECT_CONFIG_KEYS` + 5 个 effect bundle + 应用/卸载接线 | `modules.py` / `modules_page.py` / `assets/modules/` / `settings_dialog.py` / `i18n.py` |

### T8 细节（本轮新增，其余见清单）

- `main_window.py`：`_start_instance_download(inst_id)` 用 `ProgressWorker(install_instance, ...)` 后台下载；`_on_download_progress/_done/_error` 驱动状态栏 + 对话框 + 实例行徽标；`_reopen_launch_task` 改为**下载任务优先**。
- `launch_dialog.py`：`LaunchProgressDialog(mode="download")`，只显示「安装 / 补齐」两步，标题/副标题/底部提示换下载语义；`mark_done()` 泛化，`mark_launched()` 保留兼容别名。
- `pages_instances.py`：新增 `instance_created` 信号（页面内新建也上报 MainWindow）；`set_instance_task()` + `_InstRow.set_task_state()`（内存态 `_task_states`，不写 `Instance` 字段）。
- **启动侧天然跳过**：`install_instance` 幂等（只补缺失文件），文件齐备后启动走 `launch.py` 的 `_skip` 直通；`_handle_play` 加护栏——该实例下载未完成时不并发启动（防双写同一目录）。
- **仅 AC 自建（非 `external`）实例**触发，绝不向其他启动器真实目录写入。

## 验证

- `python -m compileall -q src main.py` → **EXIT 0**
- i18n parity：**zh 1271 / en 1271，零单边键**（本批新增 10 键：`launch.download_*` ×4、`status.download*` ×4、`instances.task_*` ×2）
- 离屏冒烟（venv，`QT_QPA_PLATFORM=offscreen`）：`DLG OK` / `ROW OK` / `MW OK` → **SMOKE OK，FAILS: 0**
  - 覆盖：下载模式对话框步骤数与启动模式互不串扰、`mark_done`/`mark_launched`、`_InstRow` 徽标文案（含 `{pct}%`）、MainWindow 的 `instance_created` 信号 / `set_instance_task` / `_dl_workers` / 无活动任务时 `_reopen_launch_task` 不崩。
  - 冒烟脚本为临时产物，验证后已删除（不入库）。

## 已知环境问题（非本轮引入）

- 离屏运行在解释器 teardown 阶段退出码 `0xC0000409 (-1073740791)`。**已在 HEAD `a9ffef4` 的 git worktree 复现 → 属既存问题**，与本轮改动无关，忽略。

## 待办 / 未做

- **真机目检一次**：离屏无字体（文字为 tofu），只能验结构/配色/几何。需在真机确认：下载对话框（下载中/就绪）、实例行任务徽标、左侧导航图标模式、设置页第三方服务分组的排版与落位。
- 资源中心版本浏览组件抽取、统一实例选择器等中高风险内部重构暂缓（见 round-105 计划）。
- 未做（已批计划明确 Out of scope）：A2-P2 增强检查、`launch.py` 启动前预检升级、crash_dialog 顶部入口、round105 方案的 A1 联机闭环 / B6 Java 绑定接线。
- 未 git commit（用户自行提交）。
