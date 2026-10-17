# AC Launcher 更新日志

> **版本策略（2026-09-02 起）**：正式发布前不再使用 `v1.x` 前缀，改为纯
> `round-NN` 内部迭代号。对外版本号只有在按《RELEASE\_1.0.0\_CHECKLIST.md》
> 全部完工、完成首个 release 时才一次性打上 `v1.0.0`。

> **补记说明（2026-09-16）**：下列 round-78 ~ round-91 为 09-03 ~ 09-12 期间
> TRAE 迭代完成、但当时未同步 CHANGELOG 的批次（代码随 `57825e6` 一并入库）。
> 内容依据代码中的 `round-NN` 标记与改动反推整理；**日期为按文件改动时间推断**，
> 非逐条精确记录。

## round-108（2026-10-17）— CurseForge 对外发布合规准备

> 依据 `docs/round108_memory.md`（TRAE 实测记录）整理。

* **公开发布只挂 Modrinth**：查证 CurseForge 官方口径后确认，`cfwidget +
  edge.forgecdn.net` 直链绕过作者在 CF 上的第三方分发授权，公开分发与申请声明冲突。
  故免 key 通道**默认关闭**（`curseforge_keyless=False`），CF 源改为「谁用谁填 key」；
  官方 API key 待作者成年后再申请（或由 18+ 家长作为合同主体代签）
* `settings_dialog.py`：`_DEFAULTS` 加 `curseforge_api_key=""` / `curseforge_keyless=False`；
  `_SENSITIVE_CFG_KEYS` 加入 `curseforge_api_key`——**导出/导入配置备份永不携带该 key**；
  网络页新增「第三方服务」分组（key 输入框 + 免 key 勾选 + 两段 hint）
* `net_api.py`：新增 `curseforge_keyless_enabled()`；`pages_browse.py` 的 CF 源改
  **三态**：有 key → 官方关键词搜索；无 key + 开关开 → slug/链接解析；都没有 →
  提示去设置填 key（清列表 + 状态栏提示，不起 worker）
* **顺带修一个潜在崩溃**：`pages_browse._download` 在 CF 源下无条件调
  `download_cfwidget_file(cf_file, ...)`，但官方 API 搜索命中的 hit 没有 `_cf_file`
  （`search_curseforge` 只返回 `project_id`）→ `cf_file=None` 会在 worker 里炸。
  即「**配了 key 能搜到、但一下载就崩**」。现改为有 `_cf_file` 走 forgecdn 直链，
  否则走 `download_curseforge_mod(project_id, dest)`
* i18n +7 键 × zh/en：`settings.cf_group/cf_key_ph/cf_key_hint/cf_keyless/cf_keyless_hint`
  + `store.cf_hint_key/cf_no_key`

## round-107（2026-10-17）— 全启动器 UI/UX 反馈批次（用户手工测试第二轮）

> 依据 `docs/round107_memory.md`（TRAE 实测记录）整理。承接
> `docs/round105_ui_feedback.md` 执行清单。

* **T3 分辨率预设完全删除**：启动器不再给游戏传分辨率，由玩家在游戏内自由拖动窗口
  缩放。删 UI 组 + 两个联动方法 + `_DEFAULTS` 两项 + 保存赋值；`launch.py` 侧
  `res=None`，旧配置里已存的 `res_w` 也一并忽略
* **T4** 实例设置对话框改 `QScrollArea` + `ScrollBarAlwaysOff`（禁止横向滚动/挤两列）
* **T5** 实例页「收起」键重做：删「展开条 + 折叠按钮」双按钮，改页头常驻 `panel_btn`
  （位置永不偏移）
* **T6 左侧导航可收起为纯图标**（像 Blockhelm）：标题栏汉堡 `nav_toggle_btn` + 宽度动画
  + `icons_only` 重排 + `#ac-nav` 紧凑 QSS
* **T7 导航精简**：移除 模组 / 版本库 / 音乐 / 成就 / 控制台 五个入口，功能改由页面内
  入口承接（设置页新增 `open_page` 信号、资源中心新增 `open_versions_requested`）；
  `_switch_stack` 默认关页面动画
* **T8 版本下载前移**：点安装/选版本即下载（不再等首次启动才补版本）。实例创建后立即
  后台下载，状态栏进度 + 可召回下载对话框 + 实例行「下载中 {pct}% → 就绪」徽标；
  `_handle_play` 加护栏——下载未完成不并发启动；**仅 AC 自建实例触发**，绝不向其他
  启动器真实目录写入
* **T9 首页极简**：只留 hero 当前实例卡 + 开始/结束游戏 + 一行修复提示
* **N1** 启动/下载对话框可召回（状态栏进度条可点击 → 重开被收起的对话框）
* **N2** 自动持续加载 + 卡片淡入；顺带修「全部」过滤下正式版被 `continue` 隐藏的真 bug
* **N3** 版本图标回归 MC 3D 等距方块（草方块/命令方块/蛋糕/铁砧·圆石）
* **N4** 进度条重做：`QProgressBar[cls="slim"]`（6px 圆角 accent 填充），去「黑框+方块」
* **N5 效果开关 → 可选模块**：`type="effect"` + `EFFECT_CONFIG_KEYS` + 5 个 effect
  bundle（成就弹窗 / 亚克力窗 / 磨砂 / 流光 / 页面动画），玻璃拟态/透底/流光/页面动画/
  成就弹窗从设置页移出，默认不装
* 验证：compileall exit 0；i18n zh 1271 / en 1271 零单边；离屏冒烟 21 条断言全绿
* **待真机目检**：下载对话框、实例行任务徽标、导航图标模式、第三方服务分组排版
  （离屏无字体，只能验结构/配色/几何）

## round-106（2026-10-17）— 实例体检：N5 冲突预检 → 多分区体检 + 一键本地修复

> 依据 `docs/round106_memory.md`（TRAE 实测记录）整理。

* 新增扫描引擎 `src/core/instance_health.py`（471 行，**无 Qt，可无头回归**），
  对外仅 `scan_health(inst, settings)` / `apply_fix(inst, fix)` /
  `apply_all_safe(inst, findings)`
* 把 `core.mod_check.scan_conflicts` 与四层自有检查合成 `groups`
  （**mods / perf / jvm / java / args**）+ 计数（critical/warning/info）+
  `scanned` + `fixable`；每层用 `_safe()` 包住——**单项检查抛异常绝不影响整体体检**
* 五层检查、共 **13 个 kind**，其中 6 个带安全 fix（`aikar_off` / `g1gc_off` /
  `disable_explicit_gc_off` / `ram_small` / `ram_large` / `residual_server_arg`），
  外加条件触发的 `pretouch_missing` / `java_mismatch`
* 层 1 `perf` 渲染模组冲突（sodium+embeddium 同装、OptiFine 与 Sodium/Iris/Oculus
  并存）与推荐集缺失——**均 report-only 不产出 fix**
* 防噪设计：性能模组推荐集只收公认五项（刻意不含 iris/indium/c2me/moreculling）；
  `aikar_off` 与 `pretouch_missing` 互斥；不误报手填 JDK；零模组/原版实例不刷提示；
  jar 上限 `_MAX_SCAN_JARS=60`（避免上百 jar 元数据读取拖死 UI 线程）
* 修复范围**仅本地安全修复**：不联网、不动用户游戏文件
* 用户经 AskUserQuestion 拍板：方向 = 启动器性能体检 + 一键优化；载体 = 升级现有
  「冲突预检」为完整「实例体检」

## round-105（2026-10-17）— UI 反馈修复（第一批）+ 功能扩展方案

> 依据 `docs/round105_ui_feedback.md` 与 `docs/round105_plan_feature_expansion.md` 整理。

* **T1 主题色未同步**：首页「开始游戏」大按钮改主题色后仍是旧紫色。根因是
  `_make_play_btn` 用**内联 setStyleSheet 烘焙**了构造时的 `COLORS['accent']`，
  切 accent 时全局 QSS 会重生但内联样式被冻结。修法：theme.py 新增 QSS 类
  `QPushButton[cls="play"]`（用 `$accent` 变量），`_make_play_btn` 改 `cls="play"`
  并删除内联样式
* **T2 重复的「当前」**：新建实例向导「选择游戏版本」页，被选中版本行同时出现绿色
  「✓ 当前」徽章 + 黄色「当前」按钮。删多余绿色徽章，只保留按钮侧状态
* `docs/launcher_feature_ideas_2026-10-17.md`：功能扩展点子池 + 取舍结论；
  `docs/round105_plan_feature_expansion.md`：A2/A1/B6 三方向实现方案
  （**本轮只出方案不写生产代码**；摸底后修正——A2/B6 缺口在 UI 落地，A1 才是真空白）

## round-104（2026-10-17）— 全页面排版简化 · 对标其他启动器

> 玩家要求：设置页别用折叠分栏、直接平铺；把「重复 / 多余 / 繁杂」的页面全部
> 审一遍再简化；先总体审计、再对标其他启动器的排版与功能分布，做一轮优化。

* **先只读审计**（`docs/round104_audit.md`）：通读 10 个导航页 + 15 个对话框，
  穷尽清点设置页 **约 27 个折叠组**，并分页列出 `[重复] / [多余] / [繁杂] /
  [布局风险]` 问题；对标 **Prism Launcher（左栏分类 + 类内 Tab）、HMCL（左栏
  不折叠扁平分组）、PCL2（顶部四板块）**——三家一致走「左侧分类导航」。
* **设置页：3 段 / 27 折叠组 → 9 扁平分类**。左菜单改为
  `基础 / 外观 / 启动 / 网络 / 音效 / 账号 / 高级 / Java 管理 / 模块与扩展`，
  **组内不再折叠**。删除折叠管理器 `_FoldMgr` 整类与四个旧构建方法；
  去重复：**游戏内存**（预设 + 滑块合并，滑块为唯一数据源）、**分辨率**
  （预设 + 像素框合并，双向联动）、**JVM**（两组并入「启动」页）。
  移除无运行期消费者的「启动器内存」`launcher_ram_mb`，并在保存时清理
  历史键 `launcher_ram_mb` / `collapsed_groups`。
* **首页删三套多余模板**：`pcl_card / hmcl_list / modrinth_modern` 自 round-32
  起切换入口已移除、属死代码 → 只留 `ac_default`。连带清理
  `apply_home_style / _refresh_pcl_avatar / _instance_card / _list_row` 及
  onboarding 的 `style_changed / style 单选 / _update_style_preview` 与
  对应 i18n 键（`style.* / settings.home_style* / onboard.step_style`）。
* **控制台页**：两个语义重叠的输入框（搜索 / 过滤）**合一**（搜索即过滤 +
  高亮 + 计数）；页头 5 个同级按钮收敛为「自动滚动」开关 + 「更多」菜单。
* **模块页**：已安装模块行的导出 / 卸载图标钮、扩展行的重授权 / 卸载图标钮
  收进行尾「⋯」菜单（新增 `_more_btn` helper）。
* **资源中心**：目标实例上移页头（与源切换同排）；删掉独立「搜索」按钮，
  搜索框输入即防抖搜索。
* **顺延项并入本轮**：①补全 `new_instance` 的 **LiteLoader** 版本分支（原缺失
  → 版本下拉恒空，接入 `fetch_liteloader_builds`）；②**旧版 Fabric** 支持列表
  接入——后台预热 `fetch_legacy_fabric_games` 缓存，`_compatible_loaders` 由
  启发式改为「有缓存用真实列表、无缓存回退」；③**模块页**展示 QtWebEngine
  不可用的**具体原因**（`webengine_unavailable_reason`，文本可选可复制）。
* **验证**：`compileall` 通过；i18n zh/en 键 **1202/1202** 无单边键；离屏冒烟
  覆盖 SettingsPage 九分类、HomePage 构建 + refresh、ConsolePage 搜索即过滤、
  StorePage / ModulesPage 构建、OnboardingDialog 无 style 残留、
  NewInstanceDialog 加载器兼容表（含 legacyfabric/liteloader），全部 OK。

## round-103（2026-10-16）— 手绘矢量 logo · 死代码清扫 · 设置裁字修复

> 玩家四点要求：①启动 logo 别再用手写的 MC 像素字体；②代码里无用/多余/
> 100% 走 fallback 的收掉；③排查「设置项存了但实际不生效」类隐患；
> ④（顺延）修设置→外观底部文字裁切。

* **启动 logo 换手绘矢量 monogram**（`brand.py` 新增几何 + `welcome_window.py`
  / `splash_window.py` 重写）。起因：MC 像素字体属「字体不随包」（玩家
  2026-09-25 决定），发布环境三级查找**每一级都失败**，两个启动页实际永远在
  渲染系统 fallback 字体——既是死路径也是每次启动的无谓开销。新方案为
  **填充式锥形笔锋路径**（中轴粗、两端尖），零字体/零外部资源，任何 DPI 都清晰。
  出现动画由「缩放+淡入」改为**手写显现**（笔画按手绘顺序逐段画出，A 先 C 后）。
  离屏渲染预览已目检：A 圆角顶、C 开月牙开口向右，形态正常。
* **删除 `src/fonts.py`**（整模块 100% fallback 死代码）；同时清掉
  `welcome_window.mark_ready`（空实现、全仓无调用）、`_on_stroke_done`、
  `brand.APP_TAGLINE`（无引用）。
* **修复真隐患：页面切换动画被流光开关牵连**（`effects.py`）。
  `fade_page_transition` 在 `EFFECTS_ENABLED`（流光装饰总开关，默认关）关闭时
  直接瞬时跳转 → 设置里「页面切换动画」开关（默认开）**形同虚设**，默认配置下
  动画从不播放。改为只由调用方按 `page_transition` 配置决定，与流光解耦。
* **修复设置→外观/分辨率预设文字被横向裁断**（`settings_dialog.py`）。
  实测根因：外观组 8 个复选框、分辨率组 8 个单选各挤在一行，`QScrollArea`
  强制页宽贴合视口 → 每项被压到 83–188px，长标签（最长需 228px）被截断；
  离屏量测 `need>got` 逐条命中。两处均改**两列网格**，并在 760–1024px
  四档宽度复测：**裁切 0 项**。
* **删除设置页重复的 `lay.addWidget(app_grp)`**（`L816`/`L932` 加同一控件，
  Qt 会把「外观」组移到最后）——保留一次，恢复编号注释的预期顺序。
* **死代码全量清扫（脚本化校验）**：判据为「符号名在整项目出现次数 == 1（仅
  定义行）」，即无任何调用/引用点（也排除 getattr 字符串引用）。据此删除
  **33 个函数 + 2 个常量**：`main_window` 的 round-100 遗留模板构造器
  （`nav_items`/`_yield`/`_make_scan_btn`/`_make_settings_btn`/`_action_card`/
  `_quick_btn`/`_open_mods`）、`settings_dialog` 的 dev_mode 桩、
  `async_image` 的扁平化前装饰绘制（含 `_circle`/`_hex`/`_MOTIF` 等）、
  以及 `achievements`/`downloader`/`i18n`/`lobby`/`modules`/`onboarding`/`scan`/
  `theme` 的无用访问器。`python -m compileall src main.py` 通过。
* **修复「重置新手教程」点了无反应**（`settings_dialog._reset_tutorial`）。
  教程开关自 round-45 起改为显式 flag 文件 `onboarding_done.flag`，旧实现却
  仍在删已废弃的 `launch_count.txt`，且该文件不存在时连提示都不弹 → 按钮
  100% 空操作。改为调用 `onboarding.reset_onboarding()`（函数内导入避免与
  onboarding 循环依赖）。**此缺陷为收尾复核时新发现，非上轮清单项。**
* **保留并上报 4 个「疑似未接线」符号**（疑为功能隐患而非纯死代码，未删）：
  `main_window.apply_home_style` 及 `onboarding` 的 style 步骤分支 /
  `style_changed` 信号——均为已移除的「主页模板切换」**刻意保留的恢复入口**
  （注释注明 re-add 方式），非误留；`net_api.fetch_liteloader_builds` /
  `fetch_legacy_fabric_games`（疑似应接入版本选择，LiteLoader / 旧版 Fabric
  目前不可选）、`plugin_host.webengine_unavailable_reason`（WebEngine 不可用
  时未向用户展示具体原因）。（`onboarding.reset_onboarding` 本轮已接入。）
* **配置键复核修正**（上轮「5 个从未读取」经二次核对后收窄）：`jvm_aikars`
  （`settings_dialog L1072` 旧配置迁移时读取）、`collapsed_groups`（折叠组
  读取/写回）实为**在用**；`launcher_ram_mb` 仅在设置页回填滑块，**无任何
  运行期消费者 → 承诺的「AC 自身加速（模组加载/资源解压）」不生效**（疑死
  设置，待定：接线 or 移除）；真正从未读取的只有 `enabled_modules` 与
  `dev_mode_key`（后者为已移除功能字段、注释标明「字段保留」）。
  （`sfx_click/hover/success/error` 经核为**动态键** `cfg.get(f"sfx_{key}")`，
  非死。）
* **核实并排除误报**：探索代理误判 `page_transition` / `achievement_toasts` /
  `close_after_launch` 三项「设置不生效」；实查三者均在 `_collect` 采集
  （`settings_dialog` L2377+）且在运行期被读取（`main_window` L2912 / L1794 /
  L3366），功能正常。

## round-102（2026-10-16）— 风格门禁：外部 skill 移植 + 首次全量扫描

> 玩家在 WB 国际版装了 `humanizer`（文案去AI味）与 `hallmark`（设计反 slop
> 58 门禁）两个 skill，要求评估 AC 是否需要并抄用。结论：AC 已基本达标，
> 转为**固化门禁**防回归。

* **全量扫描结果**：i18n 1194 条中文 AI 高频词 0 命中；2944 条英文仅 1 处
  （`ld_fabric` 的 "vibrant"，本轮修复）；感叹号仅 7 处且全为功能性 toast。
  对比度 9/9 配对全过（亮/暗；最低暗色 `text_accent` 3.38:1，判定为
  ≥18px 粗体限定）；饱和面积 ≤2%（门禁线 5%）。
* **新增 [docs/style-gates.md](docs/style-gates.md)**：两 skill 的 Qt 适配版
  —— 文案 10 条 + 视觉 12 条 + 发版抽查流程；含已知豁免（frameless 关闭红、
  splash 光晕、占位 em dash）。今后改文案/样式/发版前照单过一遍。
* `i18n.py`：`new_instance.ld_fabric` 英文 "Lightweight, vibrant mod
  ecosystem" → "Lightweight loader, active mod ecosystem"（对齐中文语气，
  消 vibrabt 类促销词）。
* 待办顺延（玩家验收时确认）：设置→外观页底部复选框行被卡片底边裁切；
  内存进一步下探的取舍。

## round-101（2026-10-13）— 验收修复：导航全失效 · 清数据首启闪退 · 教程无任务栏图标

> 玩家真机验收 round-100 时连续暴露 3 个阻断性问题，均在本轮修复并回归验证。

* **致命：关闭流光特效后全部导航点击无响应**（`effects.py`）
  `fade_page_transition` 开头 `if not EFFECTS_ENABLED: return`，而
  `EFFECTS_ENABLED` 由装饰性配置 `effect_light_trail`（默认关）驱动；
  `_switch_stack` 又把该函数当作**唯一**切页口——玩家一旦关闭流光（默认即关），
  点击任何左侧菜单都不切页、且无异常。改为关特效时执行瞬时 `setCurrentIndex`
  （切换是功能不是装饰），开特效时维持淡入+上浮。新增导航点击离屏回归
  （9 个功能页 + 分组标题/弹窗行分流，特效开/关两条路径均断言切页）。
* **致命：清空 data/ 或全新首启时静默闪退**（`main.py` + `main_window.py`）
  首启流程为 splash 关闭 → 延迟 1.2s 弹新手教程 → 教程结束才 show 主窗口；
  Qt 默认 `quitOnLastWindowClosed=True` 在 splash（最后一个可见窗口）关闭瞬间
  直接退出 app，表现为「窗口一闪而过、日志停在构建完成、无任何报错」。
  改为 `app.setQuitOnLastWindowClosed(False)` 手动管理生命周期，主窗口
  `closeEvent` 实关闭分支显式 `QApplication.quit()`（托盘最小化 hide 不误退）。
* **新手教程窗口在任务栏无图标**（`onboarding.py`）
  教程对话框的 owner 是尚未 show 的主窗口，Windows 不给这种 owned window
  发任务栏按钮。`showEvent` 首次显示时加 `WS_EX_APPWINDOW` 扩展样式，强制
  任务栏条目（图标继承 app windowIcon）；失败静默不阻断教程。
* **发布前清理**：删除历史测试实例（含扁平化坏布局，版本 json 散落在
  `.minecraft` 根导致版本解析 notfound）、图标/网络缓存、成就、配置、
  `_diag*/_audit*` 等全部诊断脚本与截图、`dist/`（749MB 打包产物）、
  `__pycache__`、试验性 `*.spec`；`.gitignore` 补 `*.spec`。

## round-100（2026-10-07）— 极简美学重构第二波：其余页面清扫 · 欢迎页 token · 动画打磨

> round-99 第二波（清单见第一波段落：其余页面 + 欢迎页/AC 标志 + 成就入口 +
> 动画三件套）。玩家指令「ac搁太久了，赶快做完」。

* **alpha 序盲区第二波清扫**：`ui_kit.badge`、`pages_instances`（行徽章底/
  「当前」标签/ModCard 启用态/`_badge_style`）、`modules_page` 4 处、
  `scan_dialog` 2 处状态标、`achievements_page`、`java_manager_dialog`、
  `settings_dialog` 主题色徽章、`main_window` 来源徽章，全部从
  `{color}1F`/#RRGGBBAA 式手拼 → `with_alpha()`；`pages_instances` 新增
  `_loader_vivid()`/`_loader_badge()`（与资源详情同一套「主题包声明
  `loader_vivid` 才品牌色、默认中性」模式）
* **首页 hero 重写（`main_window.py`）**：accent→#28BCD8 大渐变底 + 白字 +
  白 pill + 白底 combo 全套内联 → `RoundedCard(radius=16, accent_border=3)`
  中性卡 + `badge`/`sub` 类 + 全局实例选择器样式；主按钮沿用全局 accent
  按钮；hero 高 192→176。`login_dialog` hero 同款重写（紫→洋红渐变 → 中性卡）
* **成就解锁弹窗默认关**：`achievement_toasts: False`（设置→效果可开，
  带提示语；成就页始终可从左侧导航进入），`_show_achievement_toast` 首行守卫
* **欢迎页（`welcome_window.py`）**：暗色文字色硬编码 `#A78BFA` →
  `COLORS["text_accent"]`（随自定义 accent 联动提亮），亮色保持
  `accent_text()`；AC 像素墨迹渲染/透明画布/浮现动画维持 round-93 方案
* **动画打磨（克制）**：`fade_page_transition` 150→160ms，新页追加
  **8px 上浮汇入**（上浮前强制同步布局取真实落点、结束归位 → 连续切换零
  漂移）；新增 `effects.fade_in_widget()` 一次性淡入（结束必清 effect），
  应用于资源中心结果列表（仅整页重置，加载更多不闪整屏）与实例列表刷新
* **移除资源中心 OptiFine 分类入口（拍板）**：`STORE_CATEGORIES` 去
  optifine；`pages_browse` 清理 `_load_optifine`/下载分支/预取调用；
  OptiFine 仍可从「新建实例 → 加载器」作为独立安装入口使用
* **验证**：py_compile 14 文件；`_audit_i18n` 886 键（仅 3 个已知误报）；
  离屏冒烟 `_diag_round100_tmp.py` 17 项全过（含动画零漂移/effect 清理、
  分类按钮=表长、实例页 8 位 hex 全 alpha 在前）；第一波回归
  `_diag_store_detail_tmp.py` 24 项全过；真机启动 `_startup.log` 到
  `MainWindow built` + `hero done` 无异常
* **补充（玩家复核「查bug + 颜色不能花里胡哨」）**：
  - 硬编码色修复 4 处：`pages_instances._style_filter_btn` 选中态白字
    `#FFFFFF` → `COLORS['text_on_accent']`（浅 accent 下白字不可读 bug）；
    实例页 splitter hover 硬编码紫 `rgba(124,58,237,0.3)` →
    `with_alpha(COLORS['accent'], 0x3D)`；`settings_dialog` 自定义色点
    三色 `#33333A/#555/#9CA3B0` → 主题 token；`login_dialog` 清理
    未使用的 `QColor/QLinearGradient` import
  - `modules_page` 去花：模块类型徽章删除 `_TYPE_COLORS` 4 色 → 中性
    `cls="badge"`（与加载器徽章同一理由：多色同屏显花）；作者/描述灰字
    `#9CA3AF`/`#6B7280` → `cls="sub"`；已应用/已安装绿标 → `success`
    token（`with_alpha` 底色）；内置蓝标 → 中性 badge
  - 新增离屏计量审计 `_audit_visual_tmp.py`：11 页面高饱和像素面积占比
    （`s>0.45 且 v>0.25`）全部 ≤2%（home 1.86% 最高，为 hero 主按钮 +
    3px 竖条 + 边框点缀），8-hex 反序内联残留 = 0；ModsPage 截图复核
    绿/灰/紫块均为 token/类驱动（success 12% 底 / badge / tile）

## round-99（2026-09-27）— 极简美学重构第一波：全局中性基座 · 资源详情/资源中心去花哨

> 玩家反馈「很多页面配色不清晰、颜色丑、色块压住文字」，拍板提前上极简美学重构
> （分两波推进）。本波 = 全局基座 + 资源详情页/资源中心 + 漏键 + 花哨默认翻转；
> 第二波 = 其余页面清扫 + 欢迎页/AC 标志 + 成就入口 + 动画打磨。

* **Qt 颜色解析 bug（截图「半绿半紫」的真根因）**：Qt 的 8 位 hex 是
  **`#AARRGGBB`（alpha 在前）**，旧代码 `f"{accent}22"`（= `#RRGGBBAA`）会被
  解析成完全无关的颜色——紫 `#7C3AED` + `"22"` → `(58,237,20)` **荧光绿**。
  页面里所有「淡色 accent」（横幅渐变的 `accent18`、推荐条 `accent14/40`、
  chip `accent26`、加载器徽章底 `colr1F`、版本行 hover `accent66`）全是怪绿。
  修复：`theme.py` 新增公开助手 `with_alpha()`；`_apply_accent` 的 `accent_soft`
  改正确序（`#22RRGGBB`，实测 `#14B8A6` → `(20,184,166)` 而非怪色）
* **全局基座（`theme.py`，不改 token 名 → 主题包兼容）**：新增中性 QSS 类
  `hero / latest / vrow / badge / bare`（实色底 + 1px 描边，无渐变、无 accent
  底纹）；`chip:checked` 从整块实色改为「accent 描边 + 淡底」点缀；写入
  **强调色使用规约**：accent 只允许出现在主按钮、选中态、focus 描边、进度条与
  ≤16px 小图标点缀上，禁止作文字背景或大面积底色
* **资源详情页（`store_detail.py`）全面清扫**：横幅紫渐变 → `hero` 中性卡；
  「推荐」条去 accent 底纹 → `latest`（唯一强调 = 左侧 3px accent 竖条 + 星标）；
  加载器 13 色品牌徽章默认关（主题包声明 `"loader_vivid": true` 才恢复，兑现
  「花哨保留但自选」）；分类/加载器徽章 → `badge` 中性；loader 筛选 chip 删除
  整段内联样式 → 全局 `chip`；版本号不再按最新态染 accent；`_fill_latest`
  加载器名改中性纯文本；「在线页面/加载更多/获取中文翻译」统一 `cls="secondary"`
  （旧 `surface` 是卡片容器类，按钮上会显示成裸文字"链接"）
* **资源中心（`pages_browse.py`）**：`_letter_fallback` 首字母图标从
  `hash(title)%360` 随机饱和色块 → 中性灰底 + 次级文字色；`TYPE_COLOR` 模块级
  颜色快照改 `_type_color()` 按需读 COLORS（切主题实时刷新），去掉 `#DB2777`
  硬编码（并入中性）
* **漏翻译 4 键**（中英都缺、界面直接显示 key 原文）：`store.detail_shown` /
  `store.detail_load_more` / `store.detail_more_n` / `store.detail_all_loaded`
* **花哨默认翻转**：`frosted_theme / transparent_window / effect_light_trail`
  默认改 False（`settings_dialog` DEFAULTS + `main.py` / `main_window.py` 读取点
  全部同步）；`page_transition` 保持 True（动画是感官重点，后续专门打磨）；
  本地 `launcher_config.json` 仅关这 3 个花哨项，Java/内存/实例等配置全保留
* **暗色「深色补丁压字」修复**：plain `QWidget` 包装层会被全局 `QWidget` 规则
  画上 `bg_app` 底色——亮色主题下不可见（贴卡片色），暗色主题下在行卡片上成为
  一块深色补丁压住版本号文字。新增 `bare` 裸容器类，版本号包装层挂上后像素级
  验证透明（`alpha=0`）

🔍 **验证**（TRAE 离屏实测）：
* `_audit_i18n.py`：4 键补齐，MISSING 仅剩 3 个已知误报（`scan.note_` 为动态
  拼接、`key`/`some.key` 为文档字符串）
* `_diag_store_detail_tmp.py` 离屏冒烟 23 项全 PASS：全局类挂载、行内样式零
  8 位 hex、分页文案本地化（「加载更多（共 53 个）」）、切 accent 后 `accent_soft`
  正确解析、`_type_color` 实时取值、`bare` 容器像素透明
* `py_compile` 全绿；截图目检 `_shots/store_detail_minimal_{light,dark}.png`：
  无渐变、无彩块压字，亮/暗两套均「中性底 + 单一 accent 点缀」

## round-98（2026-09-25）— PCL 版本隔离导入启动失败修复 · 外来客户端宽容启动

> 依据 `docs/round98_memory.md`（TRAE 实测记录）整理。

* **PCL2 版本隔离实例导入后启动报「版本不存在」**（P0，玩家实测）：
  根因是三层错位——①PCL2 版本隔离下 `versions/<id>/` 里既有 `<id>.json` 又有
  `saves/ mods/`，扫描正确地把它判为版本目录；②**复制导入时把版本目录拍平**
  到 `<instance>/.minecraft/*`；③`_probe_format` 见到 `<mc>/<id>.json` 判为 `iso` →
  `versions_root` 返回**实例目录的上级** → mll 去
  `data/instances/versions/<id>/<id>.json` 找，**必然不存在**
  （修复前实测 `EXISTS = False`）

* 修复（`instances.py::import_external` copy 分支）：复制前判
  `isolated_src = version_id 且 mc_dir/<version_id>.json 存在` —— 是则目标目录取
  `<new>/.minecraft/versions/<version_id>/` 并标 `isolation="isolated"`，
  否保持原行为。修复后实测 `isolation=isolated`、`game_dir` 落在版本目录内

* **外来完整客户端宽容启动**：PCL2/HMCL 等导入客户端（version_id 非空）启动时若
  classpath 缺库——旧逻辑会触发 `install_minecraft_version` 下载官方原版库
  （「在补 PCL 特殊格式的 MC」）。现在按其原库布局直接启动，缺失条目由 JVM 静默
  忽略 + 进度提示，**绝不污染玩家客户端**（`launch.py`）

* **关闭行为默认改「直接退出」**：`tray_minimize` 默认 False——点关闭按钮即退出
  （主流直觉）；设置里勾选「最小化到系统托盘」可恢复藏盘常驻

## round-97（2026-09-23）— 扫描 / 首页三处 bug

* **PCL2 分组折叠完全失效**：组键是内部码（`"PCL-CE"`）而组头文字是显示名
  （`"PCL2"`），旧 `_toggle_group` 靠 `launcher in w.text()` 反查按钮 → **永远匹配不上**。
  修复：`_rebuild_instance_list` 用 `_group_headers[launcher]` 直接持有按钮引用；
  `_toggle_group` 直查，并只替换行首 ▾/▸（老实现 `text[2:]` 每次点击累积空格）

## round-96（2026-09-23）— 单实例守卫加固

* 用户报「新手教程背后露出启动器页面」：根因是清理数据删掉 `ac.lock` 后旧实例未退出，
  新实例 `tryLock` **误成功** → 双实例并存，教程叠在旧主窗口上
* 修复：`tryLock` 成功后仍用 `FindWindowW` 按 `APP_DISPLAY` 标题找窗口，找到则提拉旧实例
  并 `unlock` 退出；`splash_window.__init__` 设 `setWindowTitle(APP_DISPLAY)`，
  让 **splash 阶段**也可被识别。实测：删运行中锁再启动 → 进程数不增

## round-95（2026-09-22/23）— 实例页折叠 / 教程叠窗 / 版本图标扁平化

* **实例页折叠后再也展开不了**：`_toggle_panel` 收拢时对整个 `_left_panel`
  `setVisible(False)`，折叠按钮随之消失。修复：新增常驻 40px 展开条
  （`_strip` + `reopen_btn`），收起后留在最左侧提供反向箭头
* **新手教程背后露出主窗口**：根因 = `_force_foreground` 里的
  `user32.ShowWindow(hwnd, SW_RESTORE)` 把"未显示"的窗口直接拉成可见，
  而它原先在教程分支之前运行（round-30/46 只挪了 `win.show()`，没防住这条旁路）。
  修复：repaint / raise_ / `_force_foreground` 整体移入 `_show_main()`、紧跟 `win.show()`
* **扫描弹窗 NameError**：`scan_dialog.py::_rebuild_instance_list` 用 `launcher_label`
  但仅在他函数局部 import → 模块级补 import。这可能是之前「扫描实例扫不出来」的元凶
* **版本库图标扁平化**：`make_version_pixmap` 重写为 HMCL/PCL2 式纯色圆角方块 + 居中
  版本号；无渐变 / 3D 方块 / 装饰 chips；文本色按底色亮度自适应（亮底深字）
* **侧边栏「其他」分组**：新增 `nav.group.other`，音乐 / 成就从「娱乐」移入

## round-94（2026-09-22）— 字体查找共享化（移除写死本机路径）

* **字体不随包**（用户 09-25 决定）：后续 AC 走「暴力极简」美学重写，MC 像素字体
  只是排障期可选外观，不再作为发布产物（另：随包字体 16MB 且属 Mojang 字形版权灰色地带）。
  已移除 `assets/fonts/minecraft_pixel.ttf`；`fonts.py` 三级查找保留——
  玩家想要像素字效果，把 .ttf 放进 `data/fonts/` 即可（优先级最高），不放则回退系统矢量字体
* **启动页回退链防 tofu**：无 MC 字体时 `_font_family` 可能为空串
  （极端环境下 `QFont().defaultFamily()` 返回 ""），`QFont("")` 渲染成缺字形方框；
  两处字体构造加防线——空串改用 `QFont()` 默认构造

* 新增 `src/fonts.py`：MC 像素字体三级查找——
  ①`data/fonts/`（用户放置即覆盖默认）②`assets/fonts/`（随包只读）
  ③系统已安装字体中 family 含 `minecraft` 的。全部缺失返回 None，调用方回退，启动动画永不崩
* 移除原先写死的 `<本地字体目录>\[苦力怕论坛]Minecraft(...).ttf`
  （换机 / 目录移动后静默失效），改为随包 `assets/fonts/minecraft_pixel.ttf`

## round-92（2026-09-21）— 模块化内容市场 · JS 扩展宿主（选装桥接）

* **模块化内容市场**（`src/modules.py` + `settings_dialog.py`「模块与扩展」分区）：
  主题包 / JVM 预设 / 音效包 / 崩溃策略统一为「可安装模块」
  （`data/modules/<id>/manifest.json` + 按类型载荷），支持本地 zip / 目录 /
  旧主题 .json 导入、应用副作用（写主题桥接 / jvm_preset / sfx 卷 / crash_policy）、
  导出、卸载回滚；内置精选目录 `assets/modules/catalog.json`（Aikar G1GC 预设、
  午夜主题、崩溃后自动重启）

* **JS 扩展宿主**（`src/plugin_host.py`，QWebEngine 选装）：扩展 =
  `data/extensions/<id>/manifest.json` + HTML 入口，manifest 声明权限
  （read_only_instance / change_args / exec_command / network），默认全拒 +
  逐项授权弹窗；无 QWebChannel 下用「注入客户端脚本 + 页面队列 + QTimer 轮询
  runJavaScript 回投」的沙箱桥接，越权调用一律返回 `__error`；随包示例 `sample-clock`
  演示 `window.AC.listInstances()`

* **崩溃策略接线**：`crash_pol` 模块接入崩溃流程——`active_crash_policy()` 读
  action=restart 时崩溃弹窗追加「重启游戏」按钮并设为默认（复用完整启动流程，
  含内存/磁盘预检）；auto_analyze=true 时弹窗关闭后非模态打开日志分析器
  （`main_window.py:_show_crash_dialog`）

* **扩展启动参数接线**：host `changeArgs` 写入的 `ext_launch_arg_jobs` 在
  `build_options` 消费——追加到 JVM 参数末尾并按 token 与预设/玩家参数去重
  （`launch.py`）

### 🔍 验证

1. `venv\Scripts\python.exe -m py_compile src/modules.py src/plugin_host.py src/modules_page.py src/settings_dialog.py src/i18n.py src/launch.py src/main_window.py`
2. `pythonw main.py` 冒烟：设置 → 模块与扩展三分区正常；无 QWebEngine 时扩展区给出选装提示
3. 市场流程：安装「Aikar G1GC 预设」应用、安装「午夜」主题应用、安装「崩溃后自动重启」应用
4. 扩展流程：安装示例时钟 → 授权弹窗逐项选择 → 打开扩展窗口显示实例数 + 走秒
5. 崩溃接线：应用 crash-policy-restart 后，人为制造非零退出（如启动不存在的版本），
   崩溃弹窗应出现「重启游戏」默认按钮，关闭后自动打开日志分析器

### 🐛 仓库侧审查修复（2026-09-21 入库前）

1. **zip 安装的「manifest 位于包根」形式实际装不上**（P1，功能失效）：
   `_install_from_folder()` 固定拿解压容器目录名去和 `manifest.id` 比对，
   而 zip 安装时容器是随机临时目录（`ac_mod_xxxx`），**必然不一致**并抛错——
   导致文档声称支持的包根布局全部安装失败。新增 `check_dir_name` 开关，
   仅 zip 包根场景跳过该校验；本地目录安装与「包内唯一顶层目录」仍照常校验

2. **扩展卸载后 `changeArgs` 注入的 JVM 参数永久残留**（P1，静默副作用）：
   `uninstall_extension()` 原先只删目录与授权，没清理全局配置里的
   `ext_launch_arg_jobs`——扩展卸载后它注入的启动参数**持续影响每次启动**，
   而玩家在 UI 里已找不到来源、无法撤销。新增 `clear_ext_arg_jobs()` 并在卸载时调用

3. **`changeArgs` 反复调用导致配置无限膨胀**（P2）：原实现每次追加一条 job，
   同一扩展重复调用会不停堆叠；改为按 `ext` 归属先剔除同名再写入（替换语义）

4. **zip 解压改为 fail-closed**（安全加固）：原先直接用 `zf.extractall()`。
   实测确认 Python 3.13 标准库**已内置路径净化**（`../../a.txt` 折叠为
   `<dest>/a.txt`，绝对路径去根），**并非可利用的 Zip Slip**；但净化是静默的，
   恶意成员会被悄悄塞进模块目录。改为逐成员 `realpath` 校验后显式拒绝，
   以便在安装阶段就报错中止，同时防御将来解释器行为变化

### 🔭 扩大范围审查（2026-09-21 第二轮：视觉 / 体感 / 文案）

offscreen 渲染 8 个页面逐一截图审查（`_shots_audit.py`，诊断脚本不入库）：

### 🐛 启动页 logo 字母粘连修复（用户报障「logo 加载偏移」）

1. **根因**：Minecraft AE 是位图字体，`setPixelSize(96)` 后 QFontMetrics 与
   实际渲染**严重脱节**——实测 metrics 报 `horizontalAdvance("AC") == 18`，
   实际墨迹约 134px（**失真 7 倍**）。`drawText` 按 advance 逐字符排布 →
   A、C 完全重叠粘连成一团歪字形；按 metrics 宽度居中 → 整体错位。
   round-78 加的 -14 负字距在失真度量上雪上加霜，纯调数字无解
2. **修法**：`_render_ac_pixmap()` 预渲染——A、C 各自画到离屏图 →
   逐像素测**实际墨迹**包围盒 → 按墨迹宽 + 14px 间距手动排布拼接；
   `paintEvent` 改为按墨迹图实际尺寸居中绘制（透明度/缩放动画不变，
   主题色经 `CompositionMode_SourceIn` 染色）。彻底绕开失真的字体度量
3. 回退链保留：预渲染异常时兜底纯文本 `AlignCenter` 绘制

offscreen 渲染 8 个页面逐一截图审查（`_shots_audit.py`，诊断脚本不入库）：

1. **联机大厅卡片不居中**（布局 bug）：卡片 `setMaximumWidth(560)` 后
   `QVBoxLayout.addWidget` 默认**靠左**，右侧空出约 600px，整个页面重心歪向左边。
   加 `AlignHCenter` 水平居中（垂直方向上下 stretch 本来就对）
2. **空状态文案敷衍**（AI 味）：`"市场为空。"`（4 字，与相邻 `"还没有安装内容模块。`
   `去下方市场挑一个…"` 的详细引导形成鲜明反差）、`"还没有安装扩展。"`（无动作引导）。
   中英 4 条全部重写为「现状 + 下一步动作」结构
3. 审查中确认**健康**的部分：文案整体克制（感叹号全库 14 处、空话词仅 2 处且为
   合理技术描述）、弹窗收敛已落实（`QMessageBox` 构造仅 6 处）、主题令牌体系完整
   （radii 4/6/10/12/16）、`setStyleSheet` 硬编码颜色仅 14 处且均为中性灰
4. **遗留观察项**（待真机确认，未动）：设置页「外观」分组 4 列 radio 文字疑似
   横向挤压（offscreen 字体下溢出截断，真实字体待验证）；versions 页列表空时
   滚动区为整块灰底（status 小字存在但视觉存在感弱，建议加居中空态图标）

> 补记：本次为 09-21 完成、随日期批次补记；启动主线施工图见
> `docs/LAUNCH_MODE_DESIGN.md`（⚠️ 编号冲突：round-92 已被本次占用）。

## round-91（2026-09-12）— 自绘符号收尾 · 自定义强调色贯通

* **全局消灭文本 emoji / 符号**：Windows 下 `✓` `●` `▶` 会被 Segoe UI Emoji 渲染成
  彩色字形、风格突兀——对勾、圆点、折叠箭头全部改为自绘
  （`pages_instances.py:380/1214`、`java_manager_dialog.py:93`、`crash_dialog.py:64`），
  并删除已迁移到 `state_pix` 的残留文本符号表 `_GLYPH`（`launch_dialog.py:46`）

* **强调色贯通自定义 accent**：主窗口光晕、按钮起色、强调边框均跟随玩家自定义强调色
  （`main_window.py:265/520/656`），内置紫主题下仍与品牌 `#7C3AED` 一致

* **字体下拉改为自动检测**：不再枚举候选列表，扫描系统全部已安装字体，
  列表项各用自身字形预览，按钮文字跟随当前选中项（`settings_dialog.py:304`）

## round-90（2026-09-12）— 横溢出治理：不出现底部横条

* 确立 UI 原则：**页面不允许出现底部横向滚动条**。横向溢出一律改由内容自身收缩解决，
  而非放任出现滚动条

## round-89（2026-09-12）— 折叠箭头自绘

* 版本卡折叠箭头改为自绘（不再用文本 `▶`/`◀`），继续 round-91 前的 emoji/符号清理

## round-88（2026-09-12）— 加载器官方风格图标

* 版本卡片左侧显示加载器官方风格图标，新增 10 个 `assets/icons/loader_*.svg`：
  forge / fabric / quilt / neoforge / cleanroom / liteloader / legacyfabric /
  labymod / optifine / vanilla（`pages_instances.py:342`）

* 隐藏不兼容卡片后，剩余可见卡重新按 3 列排布，不留空位（`pages_instances.py:907`）

## round-87（2026-09-12）— 全局自定义字体 · 徽章文字色跟主题

* **玩家可改全局字体**：先于 `apply_qss` 生效，让 `build_qss` 用新字体重建；
  设置页放弃修改时字体同步还原

* **来源徽章文字色跟主题 `text_main`**：避免主题色为浅色（如琥珀黄）时徽章文字看不清
  （`main_window.py:213`）

## round-86（2026-09-12）— 来源徽章显示真实来源名 · 关于/守则置底

* **导入实例允许显示来源启动器名**（PCL2 / HMCL / Prism 等），此前一律不显示
  （`instances.py:227`、`main_window.py:212/1146`）

* 设置页「关于 / 守则」独立成组并**置于最底部**——无论快速/高级分组怎么折叠都在最后

## round-85（2026-09-12）— 资源中心详情页重构 · 版本列表分页

* `store_detail` 重构为**行卡片流**，对齐主流启动器信息密度

* `net_api` 新增 `limit` / `offset` 分页（`net_api.py:558`）——
  Fabric API 上千版本，分页后秒开

## round-84（2026-09-12）— 主题切换按钮修复 · 实例卡操作行简洁化

* 修复「**主题切换按钮只有空框**」：图标/文字只在 `on_theme_change` 时更新导致丢失；
  改为不再依赖 SVG 文件

* 实例卡操作行简洁化：一行只放高频操作（打开文件夹 / 实例设置 / 设为当前 / 删除）

## round-83（2026-09-12）— 服务器收藏一键直连 · 系统托盘常驻

* **服务器收藏一键直连**：新增 `server_favorites.py` + `server_fav_dialog.py`。
  收藏服务器 → 用当前实例直接启动并连入，覆盖 `game_args` / 全局里的
  `--server`/`--port`（收藏直连优先于附加参数）

* **系统托盘**：关闭窗口后藏到托盘常驻，游戏与下载不中断

## round-82（2026-09-11）— 启动格式（磁盘布局）自适应识别

* 新增 `detect_format()`（`instances.py:297`）：`auto` 自动识别磁盘布局
  （`vanilla` / `iso` / `multimc` / `curseforge` / `modrinth` / `custom`），
  实例设置可手动强制覆盖；`auto` 时下方灰字实时显示「检测到：xxx」，
  强制时显示「已强制：xxx」

* 识别结果驱动版本 json 定位与游戏目录解析
  （**后续「启动方式自适应」UI 直接复用本 round 的交互模式**）

## round-81（2026-09-11）— 多实例并行

* 同一实例已在运行 → 提示而非重复启动

* 多实例进程跟踪：`poll()` 非 None 即已退出，逐条清理

* 崩溃诊断弹窗支持多实例：`log_path` / `base_dir` 取退出实例自己的值

## round-80（2026-09-11）— 崩溃诊断弹窗 · 磁盘预检 · JVM 智能推荐

* **崩溃诊断弹窗**：内容 = `latest.log` 尾部 + `crash-reports` 最新文件摘要；
  三个动作——打开日志目录（优先 crash-reports）/ 复制诊断信息（方便贴给整合包作者）/ 好。
  数据不足时按 reason 兜底，绝不阻塞 UI

* **磁盘空间预检**：游戏盘剩余 < （堆内存 + 2GB 余量）时弹警告

* **JVM 预设新增 `auto`**：按分配内存自动选组——≥8G 给完整 Aikar，
  否则给轻量 G1GC 组（避免 `AlwaysPreTouch` 预占内存挤压堆）

## round-79（2026-09-10）— 英文支持（实验性）· 大厅 · 工具箱

* **英文支持**：尚未全覆盖（主页等仍有中文残留），先标注「实验性」

* **79b**：大厅从「敬请期待」占位升级为真实页面；工具箱升级为真实快捷工具
  （打开目录 / 清理缓存）；新增窗口置顶开关

* **79e**：低内存警告——实例覆盖内存优先，超过可用物理内存时警告

## round-78（2026-09-10）— 实例存储拆分升级 · 跨启动器版本隔离导入

* **存储升级**：单文件 `data/instances.json` 拆分为
  `data/instances/<id>.json`（每实例全量、真理源、原子写）+
  `data/instances.index.json`（摘要索引，启动秒开、懒加载全量）。
  旧版单文件首次启动一次性迁移后改名 `.legacy.bak`

* **其他启动器版本隔离实例导入**：这类实例 `mc_dir` 本身就是 `versions/<id>` 目录，
  按此布局正确解析

## round-77（2026-09-03）— 日志终端：搜索高亮 · 导出到文件

> 落地《RELEASE\_1.0.0\_CHECKLIST》B 段第 1 项（对齐 Zaphyrous 日志面板——9-02 对标报告点名的真实差距：无关键词搜索高亮与导出文件）。

* **搜索并高亮全部匹配**：console 页新增搜索行（header 下方）。输入即高亮所有匹配片段
  （`accent_soft` 主题底色、大小写不敏感），右侧实时显示「n 处匹配」；**Enter 跳下一个
  匹配**（到底自动从头再来一轮），搜索框带清除按钮

* **过滤 / 搜索职责分离**：过滤行 = 只展示匹配行（保持原有语义）；搜索行 = 全量保留 +
  高亮 + 跳转。两行独立，互不影响

* **渲染防抖**：`_render` 内容未变化时不再重建 QPlainTextEdit 文本——避免 1s poll 每次
  重置选区、打断搜索选中（此前每次 tail 都会 `setPlainText` 全量重建）

* **导出到文件**：「导出…」按钮把当前视图（过滤后的展示结果）存为 `.txt`，默认文件名
  `<实例名>_<yyyyMMdd-HHmmss>.txt`；日志为空时 toast 拦截不落盘；成功 toast（复用
  round-76 弹窗收敛）、磁盘/编码失败保留模态 warn

* **i18n**：新增 `console.search_placeholder / search_count / export / export_title /
  export_done_title / export_done / export_fail / export_empty` 8 键（中英对称）

### 🔍 验证

* compileall 0 错误；`_diag_console_search_tmp.py` 11 项断言全过（计数/高亮片段数/
  清空复位/Enter 跳转选中/过滤联动/导出落盘内容一致/toast 触发/空日志拦截）

* `_diag_all.py` 全量回归绿（新脚本自动纳入 glob 集）；`_audit_i18n.py` ZH\_NOT\_EN /
  EN\_NOT\_ZH 均为空

## round-76（2026-09-03）— 弹窗收敛：通用 toast 浮窗 · 模态 info 大批收敛

* **通用轻提示浮窗** **`show_toast`**（main\_window）：右下角滑入 → 停留 → 淡出，
  中性主题色（accent 左侧竖条 + 玻璃底 + 随主题 text\_main/text\_sub，无硬编码色），
  与成就 toast（MC 棕金风）并存互不干扰；复用 `_active_toasts` 防 GC

* **`win_rounded.toast`** **辅助**：主窗口上下文 → 浮窗；窗口外/对话框内自动回退模态 info

* **收敛 10 处模态 info → toast**：

  * 实例备份完成 / 无快照提示 / 恢复完成 / 克隆提示

  * 实例应用整合包完成

  * 整合包导入完成（modpack.done）

  * 模组：未选实例提示 / 已是最新 / 批量更新完成 / 添加模组提示

  * 资源中心：创建实例成功 / 未选实例下载提示（×2）

* **保留模态的 info**（决策/错误/引导性质，3 处 + 对话框上下文）：
  新实例向导提示、选错包格式错误、坏包提示

* **顺带修 bug**：`_copy_mod_name` 里 `from .toast import toast` 引用不存在的模块
  （round-74 并行编辑覆盖时残留——右键"复制文件名"触发即崩溃），改为 `win_rounded.toast`

### 🔍 验证

* compileall 0 错误；offscreen 冒烟通过（show\_toast 存在、QSS 无遗留 token、模块导入全通）；
  残留检索确认无 `from .toast import`、剩余 info 仅 3 处合理保留

## round-75（2026-09-03）— 交互反馈：整合包导入进度 · 按压反馈补齐

* **整合包导入进度感**：`_import_pack_path`（按钮/拖拽共用入口）导入期间在主窗口状态条
  挂上转圈进度条 + 「正在导入，请稍候…」文案，成功或报错都恢复就绪——解决大包导入
  几十秒内"点了没反应"的错觉；复用已有 `modpack.importing` i18n 键（无重复新增）

* **按压反馈补齐**：`icon-btn` / `chip` / `pcl2-pill` 补 `:pressed` 状态
  （icon-btn → `$border_light`；chip/pcl2-pill → `$accent_soft` + accent 字），
  与基础/accent/danger/secondary/seg 的既有按压体系对齐

### 🔍 验证

* compileall 0 错误；offscreen 冒烟通过；build\_qss 无遗留 `$token`；i18n 键中英对称

## round-74（2026-09-02）— 主题一致性 QSS 层 · 模组右键菜单

* **模组右键菜单**：模组管理页 `ModCard` 新增右键（对齐 Prism/CurseForge 鼠标流）——「打开所在文件夹」（explorer `/select` 直接定位文件，排查冲突更快）/「复制文件名」（写进剪贴板 + 状态条轻提示，查 Modrinth 时即贴即搜）；新增 `mods.open_folder` / `mods.copy_name` / `mods.copy_name_done` 中英键

* **字号层级扩展**：`FONTS` 新增 `xs`(11) 档，`F_XS/F_XL` 五个档位常量；QSS 模板内散落的 `11px`（pill/导航分组）/`13px`（chip/pcl2-pill）全部改走 `$f_xs/$f_md` token——改字号档位或主题包覆盖 `fonts` 时全 UI 联动

* **圆角 token 化**：`RADII` 新增 `icon`(8) 档；`[cls=surface/row/tile/pill/loader-card/icon-btn]` 的硬编码 `8/9/10/12px` 圆角统一走 `$r_card/$r_btn/$r_small/$r_icon`

* **颜色 token 化**：seg/chip checked、secondary pressed 的 `#FFFFFF` 改 `$text_on_accent`（accent 亮度自适应文字色，不再固定白字）；radio 未选圆心 `#FFFFFF` 改 `$bg_frost`（dark 下随主题深色）；slider 白心新增 `slider_knob` token（浅/深主题同为白，主题包可覆盖，QSS 与 `AcSliderStyle` 自绘共用）；danger 按钮 hover 底的 `rgba(239,68,68,0.08)` 改为 `$danger_hover`（由 danger token 派生，自定义主题包改 danger 时联动）

* **build\_qss 兜底**：`text_on_accent` 冷启动缺失时默认白字，杜绝 QSS 出现字面 `$text_on_accent`

* **main\_window 主题切换按钮**：`_style_theme_toggle` 的 dark 三元色值改为读 `COLORS` token（`bg_btn/border/text_main/bg_hover`）、字号走 `F_MD`——"控制中枢"等任意主题包自适应，不再锁死 light/dark 两套灰

### 🔍 验证

* `build_qss()` 冒烟：QSS 生成无遗留 `$token`；`F_XS/R_ICON/F_MD` 常量正确；全量 `compileall` 0 错误

## round-73（2026-09-02）— README 重写 · 版本号回归 · 批量下载队列

* **README 重写**：以 round-72 现实为准（功能矩阵 / 技术栈 / DPAPI 隐私承诺 / 零遥测 / 自检命令 / 路线图），告别"轻量浅色主题"初版旧文案

* **版本号体系回归**：新增 `_diag_version_parse_tmp.py`——验证 26.1/26.2 新版本号、26w 快照、愚人节分流、classic legacy、缺日期条目全部正常；结论：type+日期排序天然免疫语义化版本号，不变式固化防回归

* **批量下载队列**：新增 `src/batch_download.py`（`BatchDownloader`）：4\~8 worker 线程池 + 任务队列 + **失败记录继续** + 线程安全进度/取消 + 存在即跳过 & sha1 复核；接入 CurseForge 整合包文件下载（原逐个顺序下载、失败中断整批 → 并发批下载、失败汇总）；新增 `modpack.curse_batch_fail` 中英键

* 修复 `_diag_all.py` 审计发现的 i18n 中英不对称（`modpack.curse_batch_fail` 英文表先落、中文表补回）

### 🔍 验证

* `_diag_batch_tmp.py` 6 用例 + `_diag_version_parse_tmp.py` 5 用例新增并通过；`_diag_all.py` **21 脚本 + i18n 审计全绿**；全量编译 0 错误

## round-72（2026-09-02）— 下载器加固：退避重试 · 毒 .part 清理 · 完整性校验

### ⬇ 下载引擎加固（借鉴 PCL-CE `LoaderDownload.cs` / `FileDownloader.cs`）

* `download_file` 重构为「单次尝试 + 有限退避重试」两层：网络类失败（连接/超时/5xx/内容不完整）最多重试 3 次，抖动退避 0.8s/1.6s ± 0.3s（对齐 PCL retry<4 + Sleep 300\~500+retry\*300），重试期间 `.part` 断点续传；**4xx 确定性失败立即抛错、不重试，并删除可能被污染的** **`.part`**（防毒化后续续传）

* 新增下载完整性校验：`Content-Length` 已知但实际写不满 → 判定内容不完整按瞬时错误重试（PCL `FileChecker` actualSize 的简化版）

* `.part` 临时后缀 + `os.replace` 原子收尾此前已有（round-37/48），本轮补上缺失的「重试 + 失败清理」两环；所有下载入口（mod/modpack/cf/optifine/java）统一收益

### 🔍 验证

* 新增 `_diag_retry_tmp.py` 5 用例（假传输 monkeypatch）：瞬时失败重试至成功（恰 3 次请求）/ 404 立即失败 + 毒 .part 清理 / 内容不完整重试 / 416 直接原子收尾 / 架构常数约定——全过

* 真实网络下载（version\_manifest 274KB）端到端通过；`_diag_all.py` 19 脚本 + i18n 审计全部 exit=0；全量编译 0 错误

## round-70/71（2026-08-30）— 日志打码 · 非 ASCII 路径警告

### 🛡 round-71 日志打码（借鉴 PCL-CE `McLogFilter.cs`）

* 新增 `src/log_mask.py`：`mask_launch_text()` 在**展示层**统一打码——启动参数段 `accessToken xxx`、当前登录 token、Windows 用户名，均保留**首尾各 5 位**中间 `*` 替换；磁盘日志原样保留，崩溃分析不受影响

* 控制台页 `set_game()` 接收登录 token，tail 日志时逐块打码后显示；崩溃分析证据 `detail` 构建时同样过打码，防分享截图/日志时泄漏凭证

* 修复 `_mask_access_token` 单段 token 尾部日志被重复拼接的缺陷（冒烟测试捕获）

### ⚠ round-71 非 ASCII 路径警告（借鉴 PCL-CE McLaunchPrecheck）

* 启动预检新增「游戏目录含非 ASCII 字符（如中文）→ 启动前给一次提示」：只警告不拦截，启动失败时把原因指向路径；设置 → 加载器 → 「非 ASCII 路径警告」开关可关闭（对齐 PCL-CE「不再提示」语义），配置 `warn_non_ascii_path`（默认开）

* 补齐 `settings.warn_non_ascii_path(_hint)` 中英键值，i18n 审计中英对称

### 📚 round-70 ModDownload.cs 下载引擎 · 崩溃分析模块深挖（PCL-CE 源码）

* 抓取 PCL-CE 关键源码至 `<workspace>\_PCLCE\`（`ModDownload.cs`、`FileDownloader.cs`、`LoaderDownload.cs`、`ModBase.cs`、`CrashAnalysis/` 29 文件）

* 下载引擎要点：多阶段 Loader 权重流水线 + 官方 URL `.Replace` 生成镜像源按序切换 + 临时文件后缀下载原子移动 + `FileChecker` 哈希按长度自动判型（MD5/SHA1/SHA256）+ 精确/最小 size + JSON 结构校验

* 崩溃分析要点：Collect→Prepare→Analyze→Output 四步管道、按文件名前缀分类日志、Fatal→Primary→Secondary 三阶段规则短路、46 种稳定 `CrashCause` 枚举映射本地化建议

* 详细对照见 `2026-08-30_PCL-CE下载引擎与崩溃分析深挖.md`

### 🔍 验证

* 冒烟测试：log\_mask 单/多段 token、用户名、无敏感文本全通过

* `_diag_all.py` 18 脚本 + i18n 审计（ZH\_NOT\_EN/EN\_NOT\_ZH 为空）全部 exit=0；全量编译 0 错误

## round-68/69（2026-08-30）— Quilt 加载器 · 设置简化 · 进程优先级

### ✨ round-68 Quilt 加载器

* 新建实例页新增 **Quilt** 加载器卡片与版本获取（`minecraft_launcher_lib` 的 Quilt 分支，`stable_only=True` 只列稳定版）

* 设置 → 加载器 → **「显示 Quilt 加载器」开关**（对齐 PCL-CE 的隐藏加载器思路）：关闭后 `_compatible_loaders` 与新建实例卡片同时过滤，不残留入口

### 🎛 设置简化（round-68）

* 设置页由三分区（快速设置/Java/高级设置）合并为**两分区：设置 / Java 管理**；原「快速设置」+「高级设置」纵向合并进「设置」滚动页，Java 单独成区（对齐 PCL-CE「Java 归游戏分区」的分类）

### ⚡ round-69 进程优先级

* 新增「进程优先级」下拉：标准 / 高 / 实时，写入 `process_priority` 配置

* `launch._priority_bits()` 用 Windows 原生 `CREATE_HIGH_PRIORITY_CLASS`(0x80) / `CREATE_REALTIME_PRIORITY_CLASS`(0x100) 与 `CREATE_NO_WINDOW` 按位或，随 creationflags 一次性生效，**零新增依赖**（不引入 psutil）

### ✨ round-62\~67 汇总补录

* 资源中心详情页（全部版本列表 + 按 MC 版本过滤 + 谷歌翻译中文说明，24h 缓存）

* 设置页滚轮误调预防；版本列表 24h 缓存 + 主窗口构建时后台预取提速

* Logo 页精简（去背景/文字，保留 AC 字母动画）；音乐播放/暂停按钮图标随状态切换

* 联机大厅工具选择器（无联机插件时引导 Terracotta/EasyTier/MCTier）；MC 像素字体 Logo 与 Splash 动画

* 修复：崩溃分析对话框缺 QWidget 导入、设置页未改动误弹保存、导航布局被硬编码篡改、启动窗口闪现与首次启动假死、authlib 配置原子写、退出后命令未执行、版本页加载缓慢等

### 🔍 验证

* `_diag_priority.py`（位映射/下拉/脏检测/creationflags 4 项）+ `_diag_quilt_tmp.py`（两分区/开关/过滤/兼容列表/版本分支 5 项）新增并通过

* `_diag_all.py` 16 脚本 + i18n 审计（ZH\_NOT\_EN/EN\_NOT\_ZH 为空）全部 exit=0；全量编译 0 错误

## round-61（2026-08-30）— 性能优化

### ⚡ 性能

* **流光卡视口裁剪**：`QScrollArea` 里滚出屏幕的卡片此前虽 `isVisible()=True`，仍每帧触发一次被裁剪掉的光栅化。现在按 `visibleRegion()` 判定，只有真正可见的卡片才推进动画（浏览页/实例列表滚动时 CPU 显著下降），滚回来自动续播

* **动态壁纸随可见性暂停**：GIF/视频壁纸在页面被切走、窗口最小化时暂停解码（`QMovie.setPaused` / `QMediaPlayer.pause`），回到页面/还原窗口自动恢复，避免后台白跑 CPU

* 修复进程退出时流光卡析构触发 `hideEvent → _stop_master()` 访问已销毁 QTimer 的 RuntimeError

### 🔍 验证

* 全量编译 0 错误；离屏功能验证（壁纸无媒体静默通过、滚动视口掩码正确）；`_diag_all.py` 全量回归 11 脚本 + i18n 审计全部 exit=0

## 2026-08-30 — 启动高级设置（对齐 PCL2）+ 玻璃拟态 + 拖拽修复

### ✨ 新增：启动高级设置（round-55，对齐 PCL2「启动游戏 / 版本设置」）

* **游戏附加参数**：全局默认 + 实例级覆盖，追加到游戏启动参数末尾；支持 `--server <ip>` / `--port` 服务器直连（自动解析并交给 minecraft-launcher-lib 注入）

* **JVM 参数预设**：三档下拉（默认不注入 / Aikar GC 优化 / 自定义），替换原 Aikars 单勾选框；旧配置 `jvm_aikars=true` 自动映射到 `aikar`，不丢用户选择

* **版本隔离**：默认共享 / 版本隔离（`versions/<版本>/`）/ 自定义目录三选项，经 `gameDirectory` 下发，实例级可覆盖全局

* **启动后 / 退出后命令**：`run_hook_cmd` 异步 `Popen` 执行（失败静默），游戏退出时自动补跑退出钩子

### ✨ 体验

* **窗口拖拽修复**：无边框 + Acrylic 透底下 `startSystemMove` 失效，改为「原生优先 + 手动移动兜底」双机制（标题栏 + 主窗口统一）

* **玻璃拟态（毛玻璃）**：Acrylic 透底 + 半透明卡片 `bg_frost`，全局/实例设置界面统一升级

* **版本页图标**：MC 风格 3D 等距方块（按区块纹理合成）

* **authlib 自动更新**：后台线程检查 GitHub 最新版，原子替换 jar，失败静默回退

* **渲染器选择 + 实验性 GC 性能选项**：实例级 `auto/software/legacy` 渲染器 + G1GC 优化组/禁显式 GC

### 🔍 验证

* 编译 0 错误；i18n 审计中英对称、模板变量全匹配；`_diag_launch/_diag_settings/_diag_exit/_diag_backup/_diag_shared` 等回归脚本全部通过

* 功能单测：`--server` 解析（含 `=` 写法）、版本隔离三种目录解析、Aikar 参数注入均 PASS

## 2026-08-03 — 导入体验修复

### 🛠️ 修复

* **复制导入进度条**：扫描导入选"复制到本启动器"时显示实时进度（文件级 + 当前文件名），可随时取消；取消则停止导入，不再静默回退为接管

* **导入后立即刷新**：主页 / 实例页扫描导入完成后，主页实例卡、实例列表、模组页实例选择器一次性全部刷新——之前只有当前页刷新，导入的实例要等切页才出现

* **主页"刷新列表"按钮修复**：之前点击必抛异常（HomePage 缺 inst\_mgr 引用），现在正常重读磁盘列表

* **主页"扫描接管"修复**：对话框关闭后的成就检查之前会抛 AttributeError 导致主页不刷新

* **新建实例顺序调整**：先选游戏版本 → 再选加载器 → Java（与主流启动器一致；加载器兼容性依赖版本）

* **一键导入全部**：支持中途取消（复制到一半点取消即中断，不再继续导后面的实例）

### 🔍 自检（不变）

* 10 项检查：依赖 / 数据目录 / 配置 / 账户 / 外置登录 / 资源文件 / Java / 游戏文件 / 网络连通性 / 界面状态（双页预警）

### ⚠️ 已知问题（Beta 1.1）

* 偶发"双页"视觉问题仍在排查（自检"界面状态"可检测是否实例重复）

* PCL2 实例目录结构与标准 MC 不同，启动可能触发多余下载（独立跟进中）

* 启动崩溃（窗口消失）个案在排查，可能与 PCL2 实例或新建实例连点有关

## 2026-08-03 — 首个公开测试版

### ✨ 核心功能

* **跨启动器实例接管**：扫描并导入 MultiMC / Prism / HMCL / PCL2 / 官方启动器的游戏实例（复制或接管）

* **实例管理**：新建 / 导入 / 删除 / 设置当前实例，游戏版本 + 加载器（Fabric / Forge / Quilt / NeoForge 等 9 种）选择

* **版本安装**：浏览并安装 Minecraft 版本（官方 / BMCLAPI 镜像源）

* **模组管理**：按实例管理 .jar 模组（启用 / 禁用 / 删除 / 添加）

* **启动游戏**：微软账户登录（Azure OAuth）/ 离线模式，自动选 Java、注入 Authlib-Injector（外置登录）

* **统御面板**：已接管实例数 / 来源启动器数 / 待修复实例一目了然

### 🛠️ 修复（本轮 20+ 项）

* **单实例锁**：双击 exe 或进程残留不再开第二个实例（消灭"双页/双进程"）

* **切页动画移除**：不再出现页面半透明叠加的"重影双页"

* **实例页空状态**：重写为 toggle 可见性方案，不再堆叠双卡片

* **"新建实例"按钮**：修复 LOADERS 元组解包崩溃（之前点击无反应）

* **"新建实例"按钮文字**：去掉文案中多余的"+"（避免"++"）

* **首页重建优化**：语言未变时跳过全量重建，欢迎页加载提速

* **模组页快速交互**：同步删除 + 重入保护，不再崩溃

* **SSL 修复**：exe 旁加载 libssl/libcrypto，资源中心 HTTPS 正常

* **欢迎页（Onboarding）**：样式应用延迟，不阻塞响应

### 🔍 新增：内置自检（诊断）

* 10 项检查：依赖 / 数据目录 / 配置 / 账户 / 外置登录 / 资源文件 / Java / 游戏文件 / **网络连通性** / **界面状态（双页预警）**

* 入口：左侧"工具"区 → 诊断，或 设置 → 诊断

### ⚠️ 已知问题（Beta 1）

* 偶发"双页"视觉问题仍在排查（自检"界面状态"可检测是否实例重复）

* 欢迎页初次加载仍偏慢（已部分优化）

* 微软登录需在 Azure 配置回环重定向地址

### 🖥️ 环境

* Windows 10/11 x64

* 需要 Java 8+（自动检测，可用自带 Java 或系统 Java）

