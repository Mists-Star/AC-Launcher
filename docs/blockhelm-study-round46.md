# BlockHelm Launcher 源码学习报告（round-46，重构参考）

> 目标：为 AC Launcher 大规模重构提供"已学透一个启动器源码"的依据。
> 源码：`<workspace>\_launcher_research\BlockHelm-Launcher`（zqq-699/BlockHelm-Launcher，GPL-3.0，WPF/C#/.NET 8，977 个 C# 文件，五层架构）

---

## 一、总体架构

```
Launcher.App            WPF View/ViewModel/控件/样式/主题/窗口壳（412 文件）
Launcher.Application    业务接口/Use Case/业务编排/Repository 接口（147）
Launcher.Domain         纯领域模型/枚举/值对象，零依赖（56）
Launcher.Infrastructure 文件/JSON/网络/CmlLib/账户/第三方实现（277）
Launcher.Tests          单元/契约/回归测试（85）
```

- 严格依赖方向：App→Application→Domain；Infrastructure→Application/Domain；**Domain 纯净、Application 不碰 UI/文件/网络**。
- UI 范式：**主窗口 = 左侧图标导航栏（62px 可折叠）+ 内容区**；每页 = **左侧二级菜单（SecondaryMenuFrame）+ 右侧统一列表框架（ListPageFrame）**。
- 页面同屏实例化 + Visibility 切换（类 AC 的 QStackedWidget）。

---

## 二、UI/交互层要点（对照 AC 痛点）

### 1. 导航
- `NavigationItem { Page, Title, Icon, IconKey, Loader, IsSelected }` 轻量模型 + `NavigationCatalog` 静态目录工厂。
- 主导航 7 项：Account / Home / Multiplayer / Download / GameSettings / Resources / Settings。
- 选中态 = 两层 Border 透明度动画（0.16s），颜色用主题资源。

### 2. 首页
- **居中启动面板**（头像+账户名+大播放按钮+版本名+游戏设置入口；启动时切进度条+状态+取消+速度）+ **左下 224px 悬浮实例列表**（毛玻璃+渐进模糊）。
- 列表项 = 32px 版本图标 + 名称 + 副标题（`1.21.4 · Fabric 0.16.9`），克制不堆信息。

### 3. 下载/版本选择（⭐ AC 最痛点"加载器页乱"）
- **三步向导**：选 MC 版本 → 选加载器/命名实例 → 安装。
- 版本列表：左侧固定 5 分类（release/snapshot/april_fools/ancient/local_import），右侧虚拟化列表（版本号+类型标签+日期+图标），顶部搜索。
- **排序**：非 release 类按 ReleaseTime 降序；**release 保持服务端原始顺序**（单一来源，不混合排序）。
- **加载器选择**：固定顺序单选列表（Vanilla→Fabric→Forge→NeoForge→Quilt，硬编码），选中后**行内原地展开**版本下拉（含"稳定/预览"徽章）；Fabric/Quilt 再展开附加库（Fabric API/QSL）。

### 4. 实例设置
- 左侧 9 项固定顺序（id+本地化标题+图标）：general / launch / java / mod_management / saves / resource_packs / shaders / backup / export。
- `InstanceJavaSettingsView`：**启动设置模式 ComboBox（继承全局/独立覆盖）** + GroupBox「Java」（自动/手动 ComboBox + 刷新/导入按钮 + 运行时列表，两行显示 名称/版本/架构 + 路径截断）。

### 5. 全局设置 + Java 管理（⭐ AC"Java 藏设置里反人类"）
- 设置页左侧分区菜单（General/Download/Language/Memory/**Java**/Theme/Info），右侧按 ViewModel 类型映射子视图。
- `JavaSettingsView` 与实例 Java 设置**同构复用**（同一 Editor ViewModel）：自动/手动模式下拉 + 刷新/导入 + 运行时列表。Java 是设置页内的独立分区，不是深层入口。

### 6. 资源中心（⭐ AC"半英文半中文"）
- 左侧分区（模组/资源包/光影/世界/整合包），共享同一列表页。
- 搜索框 + 筛选按钮（来源/类型）+ **顶部内嵌版本/加载器 ComboBox 筛选**（加载器固定 Fabric/Forge/NeoForge/Quilt）。
- **中英文策略（关键）**：Modrinth/CF 标题**原文透传不翻译**；只有分类徽章、来源名、"未知加载器/版本"、下载量格式被本地化。务实、低维护。

### 7. 主题
- `Shared.xaml`（静态：尺寸/字体/圆角/8 种 accent）+ `Dark/Light/Accents/Backgrounds`（运行时动态增删字典层：theme→accent→image→blur）。
- `ThemeService`：跟随系统（注册表+事件监听）/手动/强调色/背景模糊，零重启换肤。
- 资源命名：`Brush.MenuButtonSelectedBackgroundBrush`、`Opacity.Page.Background`、`Is.ProgressiveBlur.Enabled`。

### 8. i18n
- resx 文化回退（zh-Hans 覆盖默认），key = **功能前缀 + PascalCase**：`Page_Home`、`Nav_JavaMemory`、`Status_LoadVersionsFailed`、`Dialog_CloseWithDownloadsTitle`。
- 语言切换后显示**红色重启提示**（不即时全量翻译）；"游戏内语言跟随启动器"开关。

---

## 三、核心逻辑要点

### 1. Java 检测与兼容（⭐ AC"exit 1/不兼容"）
- **发现**：JAVA_HOME/PATH/注册表（JavaSoft/Adoptium/Uninstall）/厂商目录递归，候选→`java -version` 实测（1.5s 超时），符号链接去重。
- **兼容规则** `GuessRequiredMajorVersion`：`>=26→25; >=1.20.5→21; >=1.18→17; >=1.17→16; 否则→8`；优先读 version.json `javaVersion.majorVersion`；叠加 Loader 上限（Forge 1.12≤9、36.2.26+<24 等）。
- **选 Java**：实例 PerInstance 用实例配置否则继承全局；按 兼容层级→距离→x64→版本 排序；**自动缺失才下载内置 JRE（CmlLib），手动路径错误直接报错不自动装**。

### 2. 启动链
- CmlLib.Core；顺序：解析设置→前置命令→文件检查修复→账户会话→语言同步→Java 选择→BuildAndStartProcess。
- **GameStartupReadinessWaiter 等待"启动就绪"**（防快速退出误判）。
- **失败诊断** `LaunchFailureAnalyzer`：正则分析 stdout/stderr/latest.log/crash，按序匹配 缺client.jar→缺GameProvider→**Java 版本不匹配**→**Mod 兼容性**→缺文件→OOM，产出 (Category, Details, Evidence, 修复建议)，可导出诊断包。

### 3. 微软登录（⭐ AC"登录回来等半天"）
- 交互登录在内存 session 认证（MSAL code flow，10min 超时）→ 校验游戏所有权 → 成功才提交持久化。
- **日常启动/列表刷新全部静默刷新 token**；只有 invalid_grant 等才映射 ReauthenticationRequired。
- **登录完成立即返回账户对象通知 UI，无轮询**。

### 4. 实例管理
- 实例目录 `<mc>/versions/<VersionName>/BlockHelm/instance-settings.json`，原子写 + 文件锁 + UpdatedAt 防覆盖。
- **versions 隔离在各实例、libraries/assets/resources 共享**（多实例不炸盘）。
- 创建 = 安装租约（同名串行）→ 事务（pending 目录→commit）→ 失败只清理本次。

### 5. 下载/版本安装（⭐ AC"下载不了实例"）
- 官方/BmclApi **按资源类别双源 fallback**（主+备请求），非整站切换。
- 并发 = CPU 核数 checker + 全局限速 + **断点续传 + SHA 校验**；启动前自动修复缺失/损坏文件。
- 加载器 Provider 字典；Forge/NeoForge 走独立 Installer 流程（安装器所需 Java 自动准备）。

### 6. 资源安装与依赖
- `IResourceProviderClient` 统一 Modrinth/CF 搜索/详情/版本。
- 版本筛选**同时约束 MC 版本 + Loader**，找不到兼容直接抛错，绝不装错 Loader 的文件。
- 递归解析依赖（visiting/visited 防环），状态 Installed/UpdateRequired/Missing；版本比较器提取数值。
- 本地 Mod 解析 jar 内 fabric.mod.json / mods.toml 识别 ModId/Version。

### 7. 错误处理
- 三层异常模型：Infrastructure 抛带 Reason 枚举的业务异常 → Application 映射 UI 异常 → UI 不依赖第三方异常文本。
- `LaunchDiagnosticRedactor` 正则+敏感值表双层脱敏（token/Authorization → `<redacted>`）。

### 8. 领域模型命名（AC 命名对齐参考）
- 枚举：`LoaderKind(Vanilla/Fabric/Forge/NeoForge/Quilt)`、`JavaSelectionMode(Auto/Manual)`、`LaunchSettingsMode(UseGlobal/PerInstance)`、`MemorySettingsMode(Manual/Auto)`、`DownloadSourcePreference(Official/BmclApi)`、`ResourceProjectSource(Modrinth/CurseForge)`。
- 命名规律：Domain 纯模型；Application `I{Service}` + `{X}Coordinator`（跨服务编排）+ `{X}Exception/FailureReason`；Infrastructure `{X}Provider/Resolver/Service/Session`。

---

## 四、AC 16 项反馈 → BlockHelm 做法 → 改法映射

| AC 问题 | BlockHelm 做法 | AC 重构改法 |
|---|---|---|
| A1 启动 exit 1 / Java 不兼容 | 版本区间判定 + 按推荐排序选 Java + 缺失才装 JRE | 加 JavaRuntimeCompatibility（GuessRequiredMajorVersion 移植）+ 启动前校验 + 错误归类 |
| A2 下载不了实例 | 双源 fallback + 断点续传 + 核数并发 + 启动前修复 | net_api 改造：分资源类双源 + 校验重试 |
| A3 版本列表压扁+滑块 | 分类筛选 + 虚拟化列表 + 单一排序 | 版本页重做：左分类右列表，去掉横向滑块 |
| A4 加载器排序混乱 | 固定顺序单选 + 行内展开版本下拉 | 加载器选择重做：Vanilla→Fabric→Forge→NeoForge→Quilt 固定序 |
| A5 Java 管理反人类 | 设置页独立分区 + 全局/实例复用 | Java 设置独立分区 + 顶栏入口，自动/手动模式 |
| A6 登录回来等半天 | 交互/静默分离，登录完即返回对象 | 登录后台任务 + 完成后一次性通知，启动只静默刷新 |
| A7 皮肤头像不显示 | Account 页头像 + 皮肤/披风管理 | 头像加载复用 skin 渲染 |
| A8 资源中心半英半中 | 标题原文 + 分类/元数据本地化 | 分类映射本地化（有 mod_names 基础），标题保留原文 |
| A9 历史版本下载 | manifest 全量 + 分类筛选 | 版本页已支持全版本（保序） |
| B1 教程有 min/max/close | 教程=独立对话框（无控制栏） | Onboarding 用 controls="close" 或无控制栏 |
| B2 3 栏居中难看 | 右上角（WPF 标题栏自绘） | frameless 控制按钮回右上角 |
| B3 最小化对齐 | 自绘按钮字形 | 换居中字形或矢量绘制 |
| B4 弹窗只有关闭 | 对话框用 DialogHost/独立窗口 | 各 Dialog 用 controls="close" |
| B5 左侧留白多 | 62px 可折叠图标栏 | 导航栏收窄 + 可折叠 |
| B6 设置底部滑动 | 左分区菜单 + 右侧内容 | 设置页改左分区右内容，去横滑 |
| B7 命名对齐 | Page_/Nav_/Settings_ 前缀 | i18n key 重构为功能前缀命名 |

---

## 五、重构路线建议（分批）

**批次 1（UI 骨架，最快见效）**：导航收窄可折叠 + 控制按钮回右上角（含弹窗 close-only）+ 设置页改左分区式 + 实例页 header/版本列表去横滑
**批次 2（下载/版本/加载器）**：版本页 = 左分类右列表 + 固定加载器顺序 + 行内版本下拉（移植 BlockHelm 三步向导）
**批次 3（Java）**：Java 兼容区间 + 自动选择 + 设置页独立 Java 分区 + 实例级模式（继承/独立）
**批次 4（启动链）**：启动就绪判定 + 崩溃日志 6 类正则 + 错误枚举化 + 日志脱敏
**批次 5（账户/资源）**：登录交互/静默分离 + 资源中心分类本地化 + 依赖检测

每批自检（编译+关键路径手测）→ 全部完成后一次打包验收。
