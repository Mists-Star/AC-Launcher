# round-104 记忆（2026-10-17）— 全页面排版简化 · 对标其他启动器

玩家要求（原文）：「设置里放那么多折叠的分栏干啥？直接开在那一列列多好……
查排版，重复多余，繁杂等各种页面全部查一遍，简化，修改，不清楚问我，
先总体审计，再去看其他启动器的排版/功能分布和布局，我们进行一轮优化更新。」

流程：先只读审计（`docs/round104_audit.md`）→ 对标 Prism / HMCL / PCL2 →
玩家确认 A 方案（设置页左菜单细分）+ 删首页三模板 + 移除「启动器内存」→ 执行。

## 1. 设置页：3 段 / 27 折叠组 → 9 扁平分类

- **旧**：左菜单 3 段（设置 / Java / 模块），「设置」段内是 quick + adv 两坨纵向
  堆叠，**都套折叠管理器 `_FoldMgr`**（quick 默认展开 10 组、adv 默认收起 17 组），
  折叠状态持久化到 `collapsed_groups`。合计约 27 个 `QGroupBox`。
- **新**：左菜单 9 项扁平分类，组内**不再折叠**：
  `基础 / 外观 / 启动 / 网络 / 音效 / 账号 / 高级 / Java 管理 / 模块与扩展`。
  （对标：Prism 左栏分类、HMCL 左栏不折叠、PCL2 顶部板块化。）
- **删除**：`class _FoldMgr(_QObject)` 整类；`_build_settings / _build_quick /
  _build_about / _build_advanced` 四个方法；`QTabWidget` 与 `QObject as _QObject`
  导入；`_DEFAULTS` 里 `collapsed_groups`。
- **新增**：`_page_wrap()`（静态，统一边距 24,20,24,24 / 间距 14）+
  `_page_basic/_page_appearance/_page_launch/_page_network/_page_sound/
  _page_account/_page_advanced` 七个分类页（Java 段与模块段沿用原构建器）。
- **去重复**（同一信息多处出现）：
  - 游戏内存原「quick 预设按钮 + adv 滑块」两处 → 合并为**预设网格 + 滑块**，
    **滑块为唯一数据源**（`target["ram_mb"] = self.ram.value()`）；
  - 分辨率原「quick 预设网格 + adv 像素框」两处 → 合并为**预设网格 + 像素
    spinbox**，**像素框为唯一数据源**，两者双向联动（`_apply_res_preset` /
    `_sync_res_preset`）；
  - JVM 原「jvm_opts 文本框 + jvm 选择组」→ 合并进「启动」页（预设下拉 +
    QTextEdit）。
- **移除「启动器内存」**：`launcher_ram_mb` 无运行期消费者，hint 承诺不兑现 →
  从 `_DEFAULTS` 与 `_sync_ui_to_cfg` 去掉；`_save` 增加历史键清理
  （`for _stale in ("launcher_ram_mb", "collapsed_groups"): self.cfg.pop(_stale, None)`）。

## 2. 首页：删三套多余模板（只留 ac_default）

- 原首页有 4 套布局模板 `ac_default / pcl_card / hmcl_list / modrinth_modern`，
  自 round-32 起模板切换入口已移除（`apply_home_style` 无人 connect）→ 三套为
  死代码。玩家拍板删除。
- **删除**：`_build_pcl_card / _build_hmcl_list / _build_modrinth`、
  `_instance_card / _list_row / _label`、`_refresh_pcl_avatar`、`apply_home_style`，
  以及 `_refresh()` 内「主页模板专属字段填充」块与相关调用。`HomePage._build`
  改为固定 `ac_default`。因删除量达数百行、Edit 无法可靠精确匹配，改用**内容
  锚点 Python 脚本**做机械删除（脚本用后即删）。
- **onboarding 死代码联动清理**：`OnboardingDialog.style_changed = Signal(str)`
  （无消费者）、`style` 步骤构建块、`_on_style_picked`、`_update_style_preview`、
  `ONBOARDING_DEFAULTS["home_style"]`、`_save_step` 的 `style` 分支全部删除。
- **i18n 清理**：删 `settings.home_style` / `settings.home_style_hint` /
  `style.ac_default` / `style.pcl_card` / `style.hmcl_list` /
  `style.modrinth_modern` / `style.preview_*` / `onboard.step_style`。
  文案更新：`onboard.mode_hint`（去掉"四种主页样式"）、`onboard.theme_hint`
  （「设置 → 快速设置 → 主题」→「设置 → 外观 → 主题」）、
  `onboard.java_mgr_hint`（「设置 → Java → 管理」→「设置 → Java 管理」）、
  `settings.dev_hint`（去掉"主页布局"）。
- 保留说明：`settings_dialog` 里仍保留 `home_style` / `nav_layout` 两个配置键
  （注释明示：固定值、避免 is_dirty 误判），非本轮清理对象。

## 3. 控制台页：合并输入 + 收敛按钮

- **[重复] 两个输入框合一**：原「搜索框（高亮全部匹配）」+「过滤框（子串过滤
  行）」语义重叠 → 合并为单个输入框，**搜索即过滤**（`_render` 用
  `self._search.text()` 同时做过滤 + 高亮 + 计数）。
- **[繁杂] 5 个同级按钮 → 2 个**：页头原「自动滚动 / 复制 / 打开目录 / 清空」+
  搜索行「导出」共 5 个 → 收敛为「自动滚动」开关 + 「更多」菜单
  （复制 / 打开日志目录 / 导出 / 清空），沿用 `pages_instances` 既有的
  `QPushButton("⋯") + setMenu` 模式。
- **i18n**：删 `console.filter_placeholder`；加 `console.more`；
  `console.search_placeholder` 改为"搜索 / 过滤…（Enter 跳下一个匹配）"。

## 4. 模块页：行尾图标钮收进「⋯」菜单

- **[繁杂] 已安装模块行 9 个控件**（启用勾选 + 名称 + 作者 + 描述 + 类型徽章 +
  已应用徽章 + 应用按钮 + 导出图标 + 卸载图标）→ 导出 / 卸载两个图标钮收进
  行尾「⋯」菜单，行内只剩高频操作。
- 扩展行（打开 + 重新授权图标 + 卸载图标）同样处理：保留「打开」主按钮，
  重授权 / 卸载进「⋯」。
- 新增模块级 helper `_more_btn(entries)`（`entries = [(label, icon_key, cb)]`），
  两处共用。**i18n**：加 `common.more`。

## 5. 资源中心：目标实例上移页头 + 搜索框吃掉搜索按钮

- **[繁杂] 顶部 4 类控件堆叠** → 重构：
  - 页头 = 标题 + **目标实例**（label + combo，与「源切换」同排右对齐）；
  - 分类 chip 行不变；
  - 搜索行只剩**搜索框**（删掉独立「搜索」按钮），输入即**防抖搜索**
    （`textChanged → _search_timer.start()`）+ Enter 立即搜索。
- **i18n**：删 `store.search`。

## 6. 顺延项（本轮并入）

- **补全 LiteLoader 版本选择**：`new_instance` 的 `_fetch_loader_versions` 原**没有
  liteloader 分支** → 选 LiteLoader 时版本下拉恒空、只能走默认构建。新增分支，
  映射 `net_api.fetch_liteloader_builds(mc_version)`，`meta` 用 `_version`
  （maven 版本串，供 `install_liteloader` 的 `build_version` 使用）。
- **旧版 Fabric 支持列表接入**：`_compatible_loaders` 原用启发式 `minor <= 13`
  判断 Legacy Fabric 是否可选。新增 `net_api.legacy_fabric_games_cached()`
  （只读缓存 peek，**不联网**）；`NewInstanceDialog.__init__` 起一个后台
  `Worker(fetch_legacy_fabric_games)` 预热缓存，完成后 `_on_lf_games` →
  `_update_compatible_loaders()`。缓存就绪即用 `meta.legacyfabric.net` 的
  **真实支持游戏版本列表**判定；未就绪回退启发式（保证首屏不阻塞）。
- **展示 WebEngine 不可用原因**：`ModulesPage._fill_extensions` 在
  `webengine_available()` 为假时，除原「未检测到 QtWebEngine…」外，另附
  `plugin_host.webengine_unavailable_reason()` 的具体原因（新 i18n 键
  `ext.unavailable_reason`），文本可选可复制，便于排查（缺 DLL / 导入报错等）。

## 7. 验证

- `python -m compileall -q src main.py` → 通过。
- **i18n 键 parity**：zh-CN 与 en-US 均 **1202 / 1202**，无单边键
  （净 +1：删 `console.filter_placeholder` / `store.search`，加
  `console.more` / `common.more` / `ext.unavailable_reason`）。
- **离屏冒烟**（PySide6 6.11 × Py3.13，`QT_QPA_PLATFORM=offscreen`，
  临时脚本 `_` 前缀、`os._exit` 收尾、用后即删）：
  - `ConsolePage` 搜索即过滤（`ERROR foo` 命中、`line one` 被过滤）✓、更多菜单存在 ✓；
  - `ModulesPage` 构建 ✓；
  - `StorePage` 无 `search_btn`、搜索框存在 ✓；
  - `SettingsPage` 左菜单 9 项
    `['基础','外观','启动','网络','音效','账号','高级','Java 管理','模块与扩展']`，
    9 个分类页全部构建 ✓；
  - `HomePage` 构建 + `_refresh()` ✓；
  - `OnboardingDialog` 非 java 步骤构建 ✓，无 `style_grp/style_preview` ✓。
  - `NewInstanceDialog(preset_version="1.12.2")`：`_lf_worker` 已建 ✓；
    `_compatible_loaders("1.12.2")` 含 `legacyfabric` + `liteloader` ✓，
    `_compatible_loaders("1.20.1")` 不含 `legacyfabric` ✓；
    `legacy_fabric_games_cached()` 冷缓存返回 `None` ✓（回退启发式不阻塞）。
  - 注：离屏冒烟需先 `set_accent_color` + `apply_qss`，否则 `COLORS['text_on_accent']`
    缺失（属既有冷启动兜底路径，非本轮问题）。

## 8. 本轮未做（待玩家定夺）

以下为审计点名、但属**内部重构（无可见收益）/ 中高风险**的项，暂缓：
- **版本浏览器组件抽取**：`VersionsPage` 与 `NewInstanceDialog` 版本步近乎同构
  （列表 + 类型筛选 + 搜索 + 卡片），可抽公共组件复用。
- **统一「实例选择器」**：ModsPage 下拉 / StorePage 目标实例 / StoreDetailDialog /
  NewInstanceDialog / LaunchProgressDialog 各自实现"选实例"。
- **StoreDetailDialog 区块合并**：6 大区块（信息头 / 最新版本条 / 筛选栏 /
  版本流 / 加载更多 / 翻译 + 文本 / 底部状态）→ 翻译并入信息头、版本条与筛选栏合并。
- **对话框公共骨架**：ScanPanel / JavaManagerDialog 与其它"扫描 + 进度条 +
  列表 + 关闭"对话框结构雷同。
- 说明：`LoginDialog` 的布局风险（固定尺寸 + 多入口）**实际已由 `_wrap_scroll`
  缓解**（choice/code 两视图均套滚动区），无需改动。
