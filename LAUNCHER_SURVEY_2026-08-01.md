# 启动器全生态调研报告 — 样式 × 代码

> 调研日期：2026-08-01 · 依据：《D:\调研.txt》启动器清单 · 用途：AC Launcher UI/架构 对标
> 覆盖：桌面 12 款 + 手机 11 款 + 生态仓 2 个 = 25 个条目，全部按「UI 样式 + 技术栈/代码结构」双维度调查

---

## 一、全景速览表

| 启动器 | 技术栈 | UI 形态 | 一句话定位 |
|---|---|---|---|
| **MultiMC** | C++11 + Qt5 | 原生极简 | 25MB 内存、实例隔离、"稳如老狗" |
| **Prism Launcher** | C++20 + Qt6 | 原生列表 | MMC 继任者，最活跃，主题三层分离 |
| **PolyMC** | C++ + Qt5/6 | 原生 | Prism 前身，已停维护 |
| **ElyPrism** | C++ + Qt | 原生 | Prism fork + Ely.by OAuth2 |
| **PrismLauncher-Cracked** | C++ + Qt | 原生 | Prism fork，仅改 3 文件做离线 |
| **FjordLauncher** | C++ + Qt6 | 原生 | Prism fork + 内置 FTB 下载 |
| **GDLauncher** | Electron+React+Rust | Web 卡片 | 拖拽实例、下载队列、Potato 模式 |
| **Technic Launcher** | Java + Swing | 老式 | 模组包生态 + Solder 增量更新 |
| **FTB App** | Electron+Kotlin | Web 左导航 | 官方整合包，但 Windows 强依赖 Overwolf ❌ |
| **PCL2** | C# + WPF | 顶栏分栏 | 国内第一，动画流畅，12+ 主题 |
| **PCL2-CE** | C#/.NET10 + WPF | 顶栏分栏 | PCL2 社区版，核心/UI 硬分离 |
| **HMCL** | Java + JavaFX | 左列表+右详情 | 最大中文生态，主题包 .thm 即时生效 |
| **HMCL-PE** | Java Android | 原生 | HMCL 核心 + Boat/Pojav 后端（停维护） |
| **BakaXL** | C# + WPF + MahApps | 打破层级 | 视差背景、动态壁纸、Spotlight 搜索 |
| **BakaXL-Deprecated-Core** | Rust | — | 曾试 Rust 写启动核心（废弃） |
| **PojavLauncher** | Java + Gradle | 原生 Material | 手机跑 JE 全版本的家族基座 |
| **PojavLauncher_iOS** | ObjC + UIKit | Navigation | iOS 端口（停维护） |
| **MojoLauncher** | Java + View | 原生 | Pojav fork，活跃 |
| **HyperLauncher** | Kotlin + M3 | Material3 | Mojo fork，动态取色（归档） |
| **Amethyst** | Java + View | 原生 | Pojav 继任者，想摆脱旧声誉 |
| **SolCraftLauncher** | Java + View | 原生 | Pojav/Amethyst fork（停维护） |
| **Pojav-Glow-Worm** | Java + View | 原生 | Pojav fork + 渲染器实验设置 |
| **ForkCringeLauncher** | Android | 原生 | DroidBridge fork，讽刺向、去登录 |
| **ZalithLauncher** | Java + View | **重设计 UI** | 深浅主题+自定义背景+TapTarget 引导 |
| **Fold Craft (FCL)** | Java | 原生 | HMCL-PE 继任，**多后端插件化** |
| **PCL2-Language** | — | — | PCL2 多语言组件仓 |
| **AC Launcher** 🎯 | Python + PySide6 | QSS 主题 | 轻量 + 跨启动器接管（本项目） |

---

## 二、桌面 Qt 系（MultiMC 家族 + Web 系）— 样式 × 代码

### 2.1 Prism Launcher（重点）
**UI 样式**
- 顶部工具栏（新建/启动/编辑/文件夹）+ 中央实例列表（图标+名称+描述）+ 底部状态栏（总游玩时长）
- **主题三层分离**：应用主题（QPalette 深浅色）× 图标主题（pe_colored/breeze_dark）× 背景包（CatPack），由 `ThemeManager` 统一管理，可整包替换
- 几乎无花哨动效，卖点 = "可预测、稳定"

**代码结构**：`launcher/`（ui / launch 启动管线 / minecraft/auth / net 下载缓存 / modplatform / meta）、`libraries/`（Java wrapper、javacheck、quazip）、`buildconfig/`、`tests/`

**对 AC 启示**：① 主题拆"配色/图标/背景"三独立层 → PySide6 用 QPalette + QSS + 图标资源包照搬；② 信息架构极简，AC 应克制 UI 复杂度，资源留给实例/下载逻辑。

### 2.2 MultiMC（架构蓝本）
- `Application(QApplication)` 单例调度、`InstanceList` 继承 `QAbstractListModel`、`NetJob` 异步任务状态机 + `HttpMetaCache` 缓存、`libraries/` 内置 14 个三方库
- **启示**：Qt 模型-视图由模型层直接驱动 → AC 实例管理可用 `QAbstractListModel` 统一

### 2.3 Prism 系 fork（PolyMC / ElyPrism / Fjord / Cracked）
- 代码同源，差异只在认证与平台接入
- **ElyPrism**：浏览器 OAuth2（凭据不进启动器）→ AC 微软登录可借鉴
- **Fjord**：内置多平台 modpack 下载 → AC 资源中心参考
- **Cracked**：最小侵入改上游（3 文件）→ 对 AC 维护 fork 的启示

### 2.4 GDLauncher（Web 化，重点）
**UI 样式**
- Electron + React + **Ant Design**，深色卡片式，实例可拖拽排序（react-beautiful-dnd）、虚拟滚动（react-virtualized）
- 登录入口左下角，Modal 承载流程；**下载队列（排队自动下载）**、**Potato PC 低配模式**、Java 自动匹配

**代码结构**：`public/electron.js`（主进程窗口 + 大量 IPC）、`src/common/reducers/actions.js`（全部业务逻辑集中）、React 组件层

**对 AC 启示**：① 业务逻辑集中成独立 actions 层 + IPC 桥 → PySide6 对应"Service 对象 + 信号槽解耦"；② 下载队列 + 自动 Java 是低成本高感知的体验点。

### 2.5 Technic / FTB
- **Technic**：Java/Swing，Solder 服务做**增量更新**（只下载变更）→ AC 资源/实例增量更新参考
- **FTB**：左导航 + 首页推荐；⚠️ Windows 版强依赖 Overwolf 运行时 → **反面教训：AC 坚持零外部依赖**

---

## 三、中文生态系（PCL2 / HMCL / BakaXL）— UI 视觉细节

### 3.1 PCL2 / PCL2-CE
**UI 样式**
- **顶栏图标 Tab + 分栏**；扁平图标、按钮反馈/页面切换流畅动效
- 深浅色 + 约 **12 套主题**；"个性化"含背景图上传 + 透明度/模糊滑块、字体与颜色方案
- 主题 = 背景图 + 强调色组合，即时预览；资源按 `Images/Themes`、`Images/Heads` 目录组织

**代码结构**：git submodule 挂 `MeloongCore` + `Plain Craft Launcher 2`(UI) + PCLCS + patches；CE 版 `PCL.Core` + `PCL.Core.SourceGenerators` + Test，**核心/UI 硬分离**
⚠️ 自定义许可证 → 看思路可，抄代码有法律风险

**对 AC**：① 核心/UI 分层（启动/下载引擎独立为可单测 Python 包）；② 主题 = 资源目录（背景图+强调色+动效开关）运行时换肤

### 3.2 HMCL（重点）
**UI 样式**
- **左侧版本/实例列表 + 右侧详情页**；设置左栏 12 类导航
- **主题包 `.thm` 导入即时生效无需重启**；12 种预设配色 + HEX 色盘（实时生效、含透明度）
- Material Symbols 统一图标体系；窗口开/关/最小化/还原均有动画；背景支持 WebP/16:9；半透明遮罩、长列表滚动优化

**代码结构**：`HMCLCore`（业务）/ `HMCL`（UI 壳）/ `HMCLBoot`（引导）三层；HMCLCore 含 game 实例模型、download（BMCLAPI 镜像 + AutoDownloadProvider 自动选源）、auth（authlib-injector）、addon（模组/数据包/资源包统一为 Addon）、modpack（CF/MR 导入导出）、java（运行时发现+版本约束）

**对 AC**：① 主题包即时生效 + 实时预览；② Addon 统一抽象 → AC 的 ModsPage 可复用为通用"资源列表"组件；③ 自动选源（官方/BMCLAPI/MCIM 自动切换）

### 3.3 BakaXL
**UI 样式**
- **打破层级**——卡片自由排布、视差背景 + 动态壁纸（支持 Wallpaper Engine）、非线性动效、Windows 动态磁贴风
- 主题包 + 自定义背景；设置走分步向导
- 4.0 改竖向极简布局 + **游戏抽屉 + Spotlight 全局搜索**（快捷键呼出），首页元素压到最少

**代码结构**：门户仓库非全开源；启动核心独立；Deprecated-Core 曾用 Rust 写启动核心（废弃）

**对 AC**：① 背景层/内容层分离做视差（AC 已有 wallpaper 系统雏形，可加视差）；② Spotlight 全局搜索是 BakaXL 4.0 的杀手级入口，AC 可做一个简版（搜索实例/版本/设置）

---

## 四、手机端系（Pojav 家族 + 生态）— 样式 × 代码

### 4.1 血统图
```
Boardwalk → PojavLauncher（基座）→ fork 群：Zalith / Mojo / Hyper / SolCraft / Glow-Worm
                             └→ 继任者 Amethyst
另一支：HMCL-PE → Fold Craft Launcher (FCL)
```

### 4.2 PojavLauncher（家族基座）
- **UI**：Android 原生 View+XML（非 Compose），Material 风格跟随系统深浅色；主页 = 版本列表 + 设置
- **代码**：`app_pojavlauncher`(UI) / `jre_lwjgl3glfw`(启动核心) / `forge_installer` / `arc_dns_injector`；自改 LWJGL3 + GL4ES/Mesa/virgl；OpenJDK 8/17/21 移动移植
- **借鉴**：单模块扁平化；版本列表长列表 + 内嵌下载进度

### 4.3 ZalithLauncher（重设计 UI，重点）
- **完全重写布局**；深浅主题 + 自定义背景图 + 虚拟鼠标图标
- **TapTargetView 新手引导**、AndroidViewAnimations 动效；吸收 HMCL 代码
- **借鉴**：onboarding 引导 overlay、启动器背景自定义、内置文件管理器降低权限门槛

### 4.4 Fold Craft Launcher（多后端抽象，重点）
- **代码**：`FCL`(UI) / `FCLCore`(核心) / `FCLLibrary`(公共) / `FCLauncher`(后端) / LWJGL-Pojav / NG-GL4ES / Terracotta / ZipFileSystem
- **抽象**：渲染器插件化（Krypton/VirGL/Zink/MG）、多 Java 自动选、加载器统一抽象、zip/7z/rar 统一解压、`version_map.json` 版本映射
- **借鉴**：UI/核心/底层三层隔离 = 桌面 AC 的目标架构

### 4.5 其余简表
| 项目 | 一句话 | 技术栈/UI |
|---|---|---|
| Pojav_iOS | ObjC+UIKit Storyboard，NavigationController 推入，停维护 | 无 TabBar |
| Mojo | Pojav fork，活跃，规划实例系统替代 profile | Java+View |
| Hyper | Mojo fork，M3+动态取色，归档 | Kotlin+M3 |
| Amethyst | Pojav 继任者，主张摆脱原家族声誉 | Java+View |
| SolCraft | Pojav/Amethyst fork，停维护 | 原生 View |
| Glow-Worm | Pojav fork，加渲染器与实验设置 | 原生 View |
| ForkCringe | DroidBridge fork，讽刺性、去登录 | Android app |
| HMCL-PE | HMCL 核心 + Boat/Pojav 后端，停维护 | 原生 View |

### 4.6 手机端对桌面 AC 的通用借鉴
1. **底部导航（3-5 Tab）优于侧滑抽屉**，拇指可达；桌面升级为顶部 Tab + 侧栏
2. **实例紧凑卡片**：小屏 2 列网格 + 状态徽标（版本/加载器/Java）；桌面响应式 4-6 列
3. **版本列表筛选 chips**（正式/快照/旧版/加载器）避免大海捞针 → AC 已做 filter，可加 chips 视觉
4. **下载→安装→启动流水线单页内联进度**，少弹窗
5. **多后端插件化抽象**（渲染器/Java/加载器），FCL 已验证
6. **空状态 + 新手引导 overlay**（Zalith TapTargetView 思路）降低上手门槛

---

## 五、AC 总启示（Top 行动项）

### UI 方向（三层）
1. **布局骨架**：Prism 式"顶部工具栏 + 实例列表 + 状态栏"极简骨架 + 深色主题（对齐 HMCL 左列表右详情）——AC 的实例页改造方向
2. **主题系统**：拆「配色 QPalette × QSS × 图标资源包」三层，主题包即时生效（学 HMCL .thm）+ 实时预览（学 PCL2）——AC 的 C 方向（自定义主题 JSON）落地形态
3. **动效清单**：HMCL 窗口过渡动画、统一图标库（Material Symbols）、半透明遮罩；BakaXL 背景/内容分离视差——AC 用 QPropertyAnimation 做页面过渡

### 架构方向（三层）
1. **核心/UI 硬分离**：PCL2-CE `PCL.Core` / HMCL `HMCLCore` / FCL `FCLCore` 三家验证 → AC 将启动/下载引擎独立为可单测 Python 包，UI 仅薄壳（AC 已有 src/core 雏形，需继续抽干净）
2. **Addon 统一抽象**：HMCL 模组/数据包/资源包统一为 Addon → AC 做通用"资源列表"组件，ModsPage 复用
3. **多后端插件化**：FCL 渲染器/Java/加载器插件化 → AC 加载器安装（已做 9 种）可继续抽象成"后端可换"

### 功能方向（小而感知强）
1. **下载队列**（GDLauncher）→ AC 资源中心排队下载
2. **自动 Java 匹配 + 增量更新**（GDLauncher/Technic）
3. **Spotlight 全局搜索**（BakaXL 4.0）→ AC 简版：搜实例/版本/设置
4. **新手引导 overlay**（Zalith TapTargetView）→ 对 AC 的 onboarding 升级
5. **离线账号生成 + 浏览器 OAuth**（Cracked/ElyPrism）→ AC 登录路径参考

### 反面教训
- FTB App Windows 强依赖 Overwolf → **AC 坚持零外部依赖**
- PCL2 自定义许可证 → 看思路不抄代码
- PolyMC 停维护 → fork 生态的教训：AC 自己的仓库保持 README-only 是保护策略

---

*调研方式：GitHub 仓库代码结构抓取 + 官方文档 + 社区截图/评测，由 3 个并行调研 agent 分头完成，覆盖《D:\调研.txt》全部 25 个条目。*

---

## 六、AC 下一步任务单（2026-08-01 定稿，按优先级）

> 前置条件：今天的 bug 修复全部已进 build.bat，重编后即为当前基线。

### 🥇 P0 — 实例页改造（对标 Prism 骨架 × HMCL 详情页）
- [ ] 实例页：左侧实例列表 + 右侧实例详情页（概览：版本/加载器/路径/启动/打开文件夹/导出）
- [ ] 详情页分区：Mods / 资源包 / 光影 / 存档（Prism Edit Instance 模式）
- [ ] 实例卡片紧凑化：状态徽标（版本/加载器/Java）+ hover 操作（LAUNCHER_REFERENCE 第六节 A 方案）
- [ ] 底部状态栏：显示选中实例描述 + 游玩时长（Prism）

### 🥈 P1 — 主题系统三层化（对标 HMCL .thm × PCL2 实时预览）
- [ ] 主题拆三层：QPalette（配色）× QSS（样式）× 图标资源包 —— 现在 COLORS 已做，补图标层
- [ ] 主题包导出/导入（`.actheme` JSON，学 HMCL .thm 即时生效不重启）
- [ ] 实时预览：设置页改主题即时生效（PCL2 个性化页模式，AC 设置页已能 apply_qss，补预览卡）
- [ ] 动效：页面过渡 QPropertyAnimation、半透明遮罩（HMCL 窗口动画清单）

### 🥉 P2 — 架构收敛（对标 PCL2-CE/HMCLCore/FCLCore）
- [ ] 核心/UI 硬分离：src/core 抽成可单测包（启动/下载/实例引擎独立，UI 薄壳）
- [ ] Addon 统一抽象：ModsPage 重构为通用"资源列表"组件（复用给资源包/光影）
- [ ] 多后端插件化：加载器安装抽象为"后端可换"（FCL 思路，AC 已有 9 种加载器，抽象成 Provider）

### 🔥 P3 — 功能金矿（小而感知强）
- [ ] 下载队列：资源中心排队下载 + 内联进度（GDLauncher）
- [ ] 自动 Java 匹配：按 MC 版本自动选最佳 Java（GDLauncher/HMCL 版本约束）
- [ ] Spotlight 全局搜索：Ctrl+K 搜实例/版本/设置（BakaXL 4.0）
- [ ] 新手引导 overlay：onboarding 加 TapTarget 式高亮引导（Zalith）
- [ ] 增量更新：资源/实例下载只拉变更（Technic Solder）

### ⛔ 反面教训（不做）
- FTB 式强依赖外部运行时（Overwolf）→ AC 零外部依赖
- PCL2 逐字抄代码（自定义许可证）→ 看思路不抄码
- PolyMC 式无维护 fork → AC 保持 README-only 保护策略

### 建议顺序
```
第1步：P0 实例详情页（最快见效，玩家"实例=文件夹"心智）
第2步：P1 主题三层 + 主题包（差异化 C 方向落地）
第3步：P3 下载队列 + Spotlight（感知强的甜点功能）
第4步：P2 架构收敛（重构期穿插，不影响用户）
```
