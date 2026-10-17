# round-104 页面排版审计（只读 · 待玩家确认）

> 目的：为「全页面排版简化 + 对标其他启动器」优化轮做前置审计。
> 方法：本轮**未改任何代码**，只通读 + 穷尽清点。
> 标签约定：`[重复]` 同信息/同功能多处以不同形式出现 · `[多余]` 无实际作用的控件/设置 ·
> `[繁杂]` 层级或按钮过密 · `[布局风险]` 可能溢出/裁字/挤压 · `[建议]` 优化方向。

---

## 1. 页面 / 对话框速览

### 主窗口导航页（8）
| 文件 | 页面 | 一句话职责 |
|---|---|---|
| main_window.py | HomePage | 首页：标题块 / Hero / 实例网格 / 修复日志 / 快捷操作 |
| pages_instances.py | InstancesPage | 实例管理：列表 + 新建 / 扫描导入 / 导入整合包 |
| pages_instances.py | ModsPage | 单实例模组：目标实例下拉 + 添加 mod + 检查更新 + mod 列表 |
| pages_browse.py | VersionsPage | 官方版本库：类型过滤 + 搜索 + 版本卡片 + 建实例 |
| pages_browse.py | StorePage | 资源中心（Modrinth）：源 + 分类 + 目标实例 + 搜索 + 卡片 |
| achievements_page.py | AchievementsPage | 成就：页头 + 进度条 + 成就滚动区 |
| modules_page.py | ModulesPage | 内容模块：已安装 / 市场 / 从文件导入 / 扩展（内嵌设置） |
| music_page.py | MusicPage | 背景音乐：控制行 + 模式下拉 + 播放列表 |
| pages_console.py | ConsolePage | 游戏日志：页头 4 钮 + 搜索行 + 过滤行 + 长文本面板 |
| settings_dialog.py | SettingsPage | 设置：左菜单三段（设置 / Java / 模块）+ 右侧滚动页 |

### 对话框（15）
| 文件 | 对话框 | 一句话职责 |
|---|---|---|
| onboarding.py | OnboardingDialog | 首启向导（欢迎/语言/主题色/内存/Java/完成） |
| login_dialog.py | LoginDialog | 登录：账号卡 + 微软/离线/第三方 |
| pages_instances.py | NewInstanceDialog | 新建实例向导 |
| scan_dialog.py | ScanPanel / ScanDialog | 扫描导入已有实例 |
| store_detail.py | StoreDetailDialog | 资源详情：信息头 + 最新版本 + 筛选 + 版本流 + 翻译 |
| java_manager_dialog.py | JavaManagerDialog | Java 检测 / 下载 / 选择 |
| launch_dialog.py | LaunchProgressDialog | 启动进度 |
| crash_dialog.py | CrashAnalyzerDialog | 崩溃分析 |
| diagnostics_dialog.py | DiagnosticsDialog | 诊断信息 |
| mod_check_dialog.py | ModCheckDialog | 模组兼容性检查结果 |
| skin_dialog.py | SkinDialog | 皮肤管理 |
| server_fav_dialog.py | ServerFavDialog | 收藏服务器 |
| lobby_dialog.py | LobbyDialog | 联机大厅 |
| splash/welcome | SplashWindow / WelcomeWindow | 启动页（round-103 已改手绘 monogram） |

---

## 2. ★ 设置页分栏审计（玩家点名）

**现状结构**：左菜单三段 `设置 / Java / 模块`（[settings_dialog.py](../src/settings_dialog.py#L428-L470)）。
其中「设置」段右侧 = **quick 布局 + adv 布局 两坨纵向堆叠**，两者**都**套了折叠管理器
`_FoldMgr`（[L192-L288](../src/settings_dialog.py#L192-L288)）：

- `_fold_mgr.apply(quick.layout(), default_collapsed=False)` → 快速组**默认展开**
- `_fold_mgr.apply(adv.layout(), default_collapsed=True)` → 高级组**默认收起**
- 折叠状态持久化到配置键 `collapsed_groups`

**折叠组穷尽清单（QGroupBox）**

| 归属 | 组 | 行 | 内容 |
|---|---|---|---|
| 配置备份 | `cfg_backup` | [L554](../src/settings_dialog.py#L554) | 导入/导出配置 |
| quick（默认展开） | `ram_preset` | [L592](../src/settings_dialog.py#L592) | 内存预设 |
| quick | `window_mode` | [L613](../src/settings_dialog.py#L613) | 窗口模式 |
| quick | `resolution_preset` | [L630](../src/settings_dialog.py#L630) | 分辨率预设（两列） |
| quick | `language` | [L663](../src/settings_dialog.py#L663) | 语言 |
| quick | `font_family` | [L683](../src/settings_dialog.py#L683) | 界面字体 |
| quick | `appearance` | [L707](../src/settings_dialog.py#L707) | 主题色/明暗/特效/透明度（两列） |
| quick | `theme_pack_section` | [L826](../src/settings_dialog.py#L826) | 主题包 |
| quick | `cache_section` | [L854](../src/settings_dialog.py#L854) | 缓存清理 |
| quick | `wallpaper_section` | [L868](../src/settings_dialog.py#L868) | 壁纸 |
| quick | `about` | [L952](../src/settings_dialog.py#L952) | 关于 |
| adv（默认收起） | `ram_preset (MB)` | [L1023](../src/settings_dialog.py#L1023) | 游戏内存（滑块） |
| adv | `launcher_ram` | [L1042](../src/settings_dialog.py#L1042) | **启动器内存（待移除，见 §4）** |
| adv | `jvm_opts` | [L1063](../src/settings_dialog.py#L1063) | JVM 参数 |
| adv | `game_args` | [L1087](../src/settings_dialog.py#L1087) | 游戏参数 |
| adv | `hook_cmd` | [L1124](../src/settings_dialog.py#L1124) | 启动/退出命令 |
| adv | `resolution_preset (px)` | [L1144](../src/settings_dialog.py#L1144) | 分辨率（像素） |
| adv | `mirror` | [L1161](../src/settings_dialog.py#L1161) | 下载镜像 |
| adv | `lobby_tool` | [L1194](../src/settings_dialog.py#L1194) | 大厅工具 |
| adv | `proxy` | [L1214](../src/settings_dialog.py#L1214) | 代理 |
| adv | `jvm` | [L1249](../src/settings_dialog.py#L1249) | JVM 选择 |
| adv | `sound` | [L1258](../src/settings_dialog.py#L1258) | 声音 |
| adv | `bgm` | [L1310](../src/settings_dialog.py#L1310) | 背景音乐 |
| adv | `sfx` | [L1380](../src/settings_dialog.py#L1380) | 音效 |
| adv | `boot` | [L1410](../src/settings_dialog.py#L1410) | 启动项 |
| adv | `登录` | [L1421](../src/settings_dialog.py#L1421) | 登录 |
| adv | `loader` | [L1439](../src/settings_dialog.py#L1439) | 加载器 |
| adv | `diag` | [L1454](../src/settings_dialog.py#L1454) | 诊断 |
| Java 段 | `settings.java` | [L1669](../src/settings_dialog.py#L1669) | Java 运行时选择 |
| Java 段 | `settings.java_quick_label` | [L1695](../src/settings_dialog.py#L1695) | 已知 Java 列表 |

**结论**：单单「设置」段就有 **约 27 个折叠组**（quick ~10 + adv ~17）。平铺后单页会非常长
（估计 2500px+ 滚动高度），所以**不能只是“去掉折叠”**。三个可选方向：
- **A. 左菜单再分区**（推荐）：把左菜单从 3 段扩到 ~6 段（基础 / 外观 / 启动与 Java / 网络 / 音效 / 高级 / 关于），
  每段内容扁平成列、不再折叠；
- **B. Tab 分区**：段内再按主题拆 tab；
- **C. 保折叠但精简**：仅保留必要折叠，删除重复/多余组（见 §3 的 [重复]/[多余] 项）。

---

## 3. 问题清单

### 3.1 设置页 [重复] / [多余]
- `[重复]` **内存设置出现两次**：`quick.ram_preset`（[L592](../src/settings_dialog.py#L592)）与 `adv.ram_preset (MB)`（[L1023](../src/settings_dialog.py#L1023)）——同一个「游戏内存」，一处预设按钮、一处滑块。
- `[重复]` **分辨率出现两次**：`quick.resolution_preset`（[L630](../src/settings_dialog.py#L630)）与 `adv.resolution_preset (px)`（[L1144](../src/settings_dialog.py#L1144)）。
- `[多余]` **启动器内存**：`launcher_ram`（[L1042](../src/settings_dialog.py#L1042)）无运行期消费者，hint 承诺不兑现（已定：移除）。
- `[多余]` `jvm_opts` / `jvm` 两组同页（[L1063](../src/settings_dialog.py#L1063) 与 [L1249](../src/settings_dialog.py#L1249)）疑似可合并。

### 3.2 首页 HomePage
- `[建议]` **四种模板** `ac_default / pcl_card / hmcl_list / modrinth`（[main_window.py L367-L399](../src/main_window.py#L367-L399)），默认 `ac_default`，其余三套为同类布局的重复实现、且自 round-32 起模板切换已移除（`apply_home_style` 无人 connect）→ 疑为**半成品/死代码**，建议确认后删或明确保留。
- `[多余]` ac_default 里「修复日志」区块（[L565-L731](../src/main_window.py#L565-L731)）在首页占位，是否必要待定。

### 3.3 版本页 / 新建实例向导 [重复]
- `[重复]` **「版本列表 + 类型筛选 + 搜索 + 卡片」两处实现几乎同构**：VersionsPage（[pages_browse.py L102-L293](../src/pages_browse.py#L102-L293)）与 NewInstanceDialog 版本步（[pages_instances.py L439-L690](../src/pages_instances.py#L439-L690)）→ 建议抽公共「版本浏览器」组件复用。
- `[重复]` 版本卡片同一信息多重展示：版本 id + 日期 + 类型标签 + 安装状态/按钮挤一行（[L203-L293](../src/pages_browse.py#L203-L293)）。

### 3.4 商店页 StorePage
- `[繁杂]` 顶部 4 类控件堆叠：源切换 combo + 分类 chip 行 + 目标实例 + 搜索框 + 搜索按钮（[L341-L416](../src/pages_browse.py#L341-L416)）→ 建议「搜索框吃掉搜索按钮」「目标实例移到页头」。
- `[繁杂]` 资源卡信息满（缩略图/标题/描述/meta/按钮 + 整卡可点）（[L583-L654](../src/pages_browse.py#L583-L654)）。

### 3.5 控制台 ConsolePage [重复]
- `[重复]` **两个文本输入**：搜索框（高亮，[L64-L79](../src/pages_console.py#L64-L79)）+ 另一个「过滤」输入框（[L82-L86](../src/pages_console.py#L82-L86)）→ 语义重叠，建议合并为一个（搜索即过滤）。
- `[繁杂]` 页头 4 个按钮 + 搜索行 1 个导出按钮 = 5 个同级操作（[L44-L79](../src/pages_console.py#L44-L79)）→ 建议收进「更多」菜单。

### 3.6 模块页 ModulesPage [繁杂]
- `[繁杂]` **已安装模块每行 9 个控件**：启用勾选 + 名称 + 作者 + 描述 + 类型徽章 + 已应用徽章 + 「应用」按钮 + 导出图标 + 卸载图标（[L149-L209](../src/modules_page.py#L149-L209)）→ 建议图标钮收进行尾「⋯」菜单。
- `[重复]` 市场行（[L255-L304](../src/modules_page.py#L255-L304)）与已安装行结构相似 → 可共用行组件。

### 3.7 资源详情 StoreDetailDialog
- `[繁杂]` 6 大区块：信息头 / 最新版本条 / 筛选栏 / 版本流 / 加载更多 / 翻译 + 文本 / 底部状态（[store_detail.py L240-L313](../src/store_detail.py#L240-L313)）→ 建议把「翻译」合并进信息头、版本条与筛选栏合并。

### 3.8 对话框横向 [重复]
- `[重复]` **多处都在“选实例”**：ModsPage 顶部下拉、StorePage 目标实例、StoreDetailDialog、NewInstanceDialog、LaunchProgressDialog → 建议统一成一个「实例选择器」组件。
- `[重复]` **多处都在“选 Java”**：设置页 Java 段、JavaManagerDialog、onboarding Java 步 → 已有 `java` 段可作单一入口。
- `[布局风险]` LoginDialog 固定尺寸 + 多登录入口（账号卡 / 切换 / 微软 / 离线 / 第三方）（[login_dialog.py L96-L199](../src/login_dialog.py#L96-L199)）→ 窗口高时易拥挤，建议改可滚动。
- `[建议]` ScanPanel / JavaManagerDialog 与其它「扫描 + 进度条 + 列表 + 关闭」对话框结构雷同 → 抽公共对话框骨架。

---

## 4. 顺带发现（非排版，来自 round-103 复核）

- `launcher_ram_mb`「启动器内存」设置无效 → **本轮移除**（已确认）。
- `enabled_modules` / `dev_mode_key` 两个配置默认键从未被读取（后者为已移除功能字段）。
- 其它三处已确认项（接 LiteLoader/旧版 Fabric、展示 WebEngine 失败原因）与本轮合并执行。

---

## 5. 下一步（待玩家确认后执行）

1. 先定「设置页分区方向」（A 左菜单细分 / B tab / C 保折叠精简）。
2. 再对标 PCL2 / HMCL / Prism Launcher 的设置页与版本页布局、功能分布（下一子步）。
3. 然后按本清单动手改，顺序：设置页 → 首页 → 版本/商店 → 控制台/模块 → 对话框重复抽组件。

---

## 6. 对标其他启动器（2026-10-17 调研）

| 启动器 | 顶层结构 | 设置页组织 | 可借鉴点 |
|---|---|---|---|
| **Prism Launcher** | 侧栏页面容器 `PageContainer`/`PageDialog`（可复用框架） | **左侧分类 + 类内 Tab**：Launcher（Features / User Interface / Console）、Minecraft（Window/Performance/Misc）、Java（Runtime / Management）、APIs、Custom Commands、Environment Variables、Proxy… | ①设置用「侧栏分类」而非折叠；②分类内可再分 Tab；③`PageContainer` 组件化复用 |
| **HMCL** | 左侧设置分类列表 | 分类点进去是**扁平分组**（如「全局游戏设置」放内存、「外观」放背景/配色、「版本隔离」独立），**不做折叠** | 内存等归入「全局游戏设置」单一处；外观独立分类 |
| **PCL2** | 顶部四板块：**启动 / 下载 / 联机 / 设置** | 设置含主题/皮肤/Java 管理；「可自由关闭不喜欢的功能」 | 顶部板块化导航；设置项可按需隐藏 |

**要点**：三家都走「**左侧分类导航（不折叠）**」，与玩家选的 A 方案一致；Prism 进一步在类内用 Tab 分摊长内容。

## 7. AC 设置页建议分区方案（A 方案落地稿，待玩家微调）

把现有左菜单 `设置 / Java / 模块` 三段，重构为**约 7 个扁平分类**（组内不再折叠）：

| 新分类 | 收纳的现有组 |
|---|---|
| **基础** | 语言、界面字体、窗口模式、分辨率、缓存 |
| **外观** | 主题色、明暗模式、特效、窗口透明度、主题包、壁纸 |
| **启动** | 游戏内存（合并 quick 预设 + adv 滑块）、JVM 参数/预设、加载器、版本隔离、进程优先级、启动/退出命令 |
| **网络** | 下载镜像、代理、联机大厅工具 |
| **音效** | 声音、背景音乐、音效包 |
| **账号** | 登录相关 |
| **高级** | 游戏参数、配置备份、诊断、关于 |

> Java 段与模块段维持独立（已是「选 Java」「装模块」的唯一入口）。
> 效果：设置页从「3 段 + 27 折叠组」→「7 扁平分类」，单类滚动高度可控、无折叠交互。

---

## 8. 执行状态（2026-10-17 · round-104 已落地）

> 落地细节见 `docs/round104_memory.md`，条目见 `CHANGELOG.md` round-104。

**已按本审计执行（玩家确认 A 方案）：**

- §2 设置页 → 采用 **A 方案**：左菜单细分 **9 类**（基础/外观/启动/网络/音效/
  账号/高级/Java 管理/模块与扩展），组内**不折叠**。已完成。
- §3.1 设置页 `[重复]/[多余]`：内存、分辨率、JVM **去重复**；`launcher_ram_mb`
  「启动器内存」**已移除**。已完成。
- §3.2 首页四种模板：**已删三套**（只留 `ac_default`）+ 全部死代码清理。
  「修复日志」区块**保留**（仍待玩家定夺）。
- §3.4 资源中心顶部 4 类控件：**已完成**（目标实例上移页头 + 搜索框吃掉搜索按钮）。
- §3.5 控制台两个输入 / 5 个同级按钮：**已完成**（搜索即过滤合一 + 「更多」菜单）。
- §3.6 模块页行控件：**已完成**（导出/卸载、重授权/卸载图标钮收进行尾「⋯」菜单）。
- §3.8 `LoginDialog` 布局风险：经查**已由 `_wrap_scroll` 缓解**（choice/code
  两视图均套滚动区），**无需改动**。
- §4 顺带发现：`launcher_ram_mb` 已在 §3.1 一并移除。

**未做（属内部重构 / 中高风险，待玩家定夺）：**

- §3.3 版本浏览器组件抽取（`VersionsPage` ↔ `NewInstanceDialog` 版本步近乎同构）。
- §3.7 `StoreDetailDialog` 区块合并（翻译并入信息头、版本条与筛选栏合并）。
- §3.8「实例选择器」统一、对话框公共骨架抽取。

> 说明：以上三项**无可视收益**（纯内部去重）或改动面较大，故本轮暂缓，避免
> 在无人可见的收益下引入回归风险。

