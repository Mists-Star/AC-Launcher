# AC Launcher 竞品参考与功能规划清单
> 生成于 2026-07-31 · 更新于 13:10（补 sudachi.top 全量列表）

## 一、GitHub 开源启动器技术栈全景表

| 启动器 | 技术栈 | 架构 | 体感 | 中国用户 | 你最该看的 | GitHub Stars |
|-------|--------|------|------|---------|-----------|-------------|
| **AC Launcher** 🎯 | Python + PySide6 | QSS主题·IO分离·brand单源 | 轻量/主题化/自定义 | ✅ 纯中文 | 就是你自己 | 1 |
| **PCL2** | VB.NET (部分开源) | 国内第一·超快下载·高度自定义UI | **简洁+高速+动画流畅** | ✅ 中文 | **UI动画/下载速度/设置分级** | 2.4k |
| **PCL2-CE** | VB.NET 社区版 | PCL2 分支·社区新增功能 | 主线没做的新功能先出 | ✅ 中文 | 社区功能方向 | — |
| **HMCL** | Java + JavaFX | 全平台·内置镜像 | 最大中文社区·功能大而全 | ✅ 中文开发者 | 中文MC生态深度 | 6.2k |
| **BakaXL** | C# + WPF | **打破层级概念**·视差效果·实况壁纸·BakaXL Network | 主题自定义王者 | ✅ 中文 | **UI/主题/壁纸系统·NeoForge/Quilt国内首个** | 2.3k |
| **Fluent Launcher** | C# + WinUI3 .NET | **专为 Win11** 设计 | **亚克力/圆角/Win11设计语言** | ✅ 中文 | **Win11 设计语言 = AC 大改方向** | 3k |
| **WonderLab** | C# + Avalonia | Blessing Studio·跨平台 | **外置登录生态深度**（Blessing Skin 同团队） | ✅ 中文 | **authlib-injector 生态** | 300 |
| **LauncherX** | C++ (闭源) | Corona Studio·下一代 | 界面优美·功能强大 | ✅ 中文 | UI 看截图/视频 | — |
| **MultiMC** | C++ + Qt5 | 经典单进程·实例隔离 | **~25MB内存**·稳如老狗 | ⚪ 英文 | 极简设计哲学 | 1.7k |
| **Prism Launcher** | C++ + Qt5/6 | MultiMC Fork + 资源市场 | 比MMC新·支持CurseForge/Modrinth | ⚪ 英文 | Qt轻量+社区运营 | 5.7k |
| **BlockHelm** | C# + WPF .NET 8 | 4层架构(DDD)·资源中心 | 最新(22天前)·功能面面俱到 | ✅ 中文 | **联机房间码+P2P** | ⭐ |
| **ObsMCLauncher** | C# + Avalonia .NET 8 | Core/Desktop分离·**插件系统** | **插件市场**·模组冲突检测·多质感UI | ✅ 中文 | **插件系统是你差异化方向** | 290 |
| **XMCL** | Electron + Vue + Rust | Monorepo·Client/Server架构 | 硬链接去重·双平台热更新 | ✅ 中文 | 资源库一体化 | 1.6k |
| **GDLauncher Carbon** | Electron + React + Rust | Java自动管理·云端实例分享 | 拖入即玩·Potato PC模式·**实例共享码** | ⚪ 英文 | Potato PC优化 | 2.2k |
| **DCML (大聪明)** | Python 单文件 | CMCL内核封装·极简 | 一键启动·自动版本更新 | ✅ 中文开发 | Onboarding极简 | 0 |
| **ATLauncher** | Java/JavaFX | 模块化·列表/矩阵UI | 老牌稳定·NeoForge支持 | ⚪ 英文 | UI组织方式 | 2k |
| **Lunar / Badlion** | 闭源 | PVP 客户端 | 高度定制化 | ⚪ | 不借鉴 | — |
| **SKlauncher** | JavaFX (闭源) | 商业免费·正版免费启动 | MC玩家跑反代服的方案 | ✅ 免正版登录 | (闭源不借鉴) | — |
| **PolyMC** (已死) | C++ Qt5 | MultiMC Fork 已归档 | 被Prism取代 | — | 看Prism就行 | — |

### 手机端（Pojav 系，PC 不直接适配但可学）
| 启动器 | 说明 | 可借鉴 |
|--------|------|--------|
| **PojavLauncher** | 手机跑 JE·全版本 | 启动器通用逻辑（不适用 UI） |
| **Fold Craft Launcher (FCL)** | HMCL核心+Pojav后端+Boat后端 | 多后端抽象（AC 可学"后端可换"思路） |
| **Zalith Launcher** | Pojav 重设计 UI | **重设计 UI 思路** |

> ⭐ = BlockHelm 新开 22 天，Stars 尚少但活跃，作者每天在推

## 二、关键架构取经

### 最轻量 → MultiMC / Prism
```
~25MB RAM · C++ Qt5 · 实例隔离干净
→ AC 可以学的：不加载无用的web引擎、启动时零额外网络请求
```

### UI 美化学习（sudachi.top 全量列表 + GitHub fetch 结论）

**Fluent Launcher（Win11 设计语言）** — 对 AC 大改最有参考价值：
```
· WinUI3/Mica/Acrylic → AC 对应：QSS 模拟亚克力半透明
· NavigationView 左侧导航 → AC 已有，需统一图标/间距
· 功能清单：多线程下载、自动找 Java、快捷方式启动、官方新闻、
  自定义外观(背景+主题色)、CurseForge/Modrinth 导入、BMCL 镜像、中文检索
```

**BakaXL（主题自定义王者，不开源但方向明确）**：
```
· 打破层级概念、视差效果、实况壁纸 → AC 已有 wallpaper 系统雏形，可加视差
· 国内首个 Quilt/NeoForge → AC 需要跟上加载器支持
· BakaXL Network 联机 → 对应 AC 的 lobby 计划
```

**PCL2（国内第一，简洁+动画流畅）**：
```
· 设置分级（新手/进阶）、快速下载、UI 动画 → AC 设置页应该分级
```

**WonderLab（Blessing Studio，外置登录生态）**：
```
· Blessing Skin 同团队 → AC 的 authlib-injector 外置登录方向正确
· Avalonia 跨平台 → 参考其 UI 布局（非 WinUI 依赖）
```

### 最现代 → BlockHelm / ObsMC
```
BlockHelm：资源中心(CF+MR)+联机P2P+实例导出为整合包
ObsMC：插件系统(开发中插件市场)+Velopack自更新+多质感主题
→ AC 应优先做：资源中心 + 联机；长远做：插件系统(差异化)
```

### 最大中文生态 → HMCL
```
Java/JFX · 内置BMCLAPI镜像 · CurseForge+Modrinth
→ AC 优势：Python比Java轻，不必全盘模仿
```

### 最独特 → GDLauncher 云分享
```
实例共享码 → 生成code发给朋友，对方粘贴自动重建完全一致的实例
→ AC 可参考：比BlockHelm房间码更进一步
```

## 三、所有启动器共有的核心功能（AC 缺的标 ❌）

| 功能 | MultiMC | Prism | HMCL | BlockHelm | ObsMC | XMCL | GDLauncher | AC |
|------|---------|-------|------|-----------|-------|------|------------|----|
| 实例管理 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Modrinth/CF资源库 | ✅ | ✅ | ✅ | ✅ | 🚧 | ✅ | ✅ | ❌ |
| 整合包导入 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| 游戏诊断报告 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❓ | ❌ |
| 跨平台 | ✅ | ✅ | ✅ | 🟡(仅Win) | ✅ | ✅ | 🟡 | ❌ |
| 深色主题 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| 自更新 | ✅ | ✅ | ✅ | ❓ | ✅ | ✅ | ✅ | ❌ |
| 联机(房间码/P2P) | ❌ | ❌ | ❌ | ✅ | ❌ | ❓ | ✅ | ❌ |
| 内建服务器管理(开服/关服/监控) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| 启动器插件系统 | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| 跨启动器实例导入* | 🟡手动 | 🟡手动 | 🟡手动 | 🟡手动 | 🟡手动 | 🟡手动 | 🟡手动 | **✅唯一** |

> *跨启动器实例自动探测+修复 = AC Launcher **唯一差异化优势**

## 四、AC Launcher 明天可以补的功能（按优先级）

### 🔥 P0 — 核心差异方向

| 功能 | 参考来源 | 实现思路 |
|------|---------|---------|
| **跨启动器实例修复** ☑️ **已有** | AC原创 | 完善导入向导、修复实例注册表 |
| **Java 管理器完善** ☑️ **已有** | AC原创 | 下载+切换+deep扫描已做，补"自动推荐最佳Java" |
| ✅ **资源中心(Modrinth/CF)** | BlockHelm / XMCL | 搜索模组+一键安装到实例——最值做的功能扩展 |
| ✅ **联机系统（P2P + 服务器管理）** | BlockHelm / GDLauncher | 三个子模块：① 自动发现局域网MC世界 ② P2P房间码联机(穿透) ③ **开服/关服/玩家管理/控制台/性能监控**——GDLauncher有Server Management模块可参考 |

### 🔥 P1 — 体验打磨

| 功能 | 参考来源 | 说明 |
|------|---------|------|
| ✅ **启动诊断报告** | BlockHelm / MultiMC | 启动失败时给可读的错误分析，AC目前是异常堆栈 |
| ✅ **深色/浅色/跟随系统主题** | 全部 | AC已有Light，补Dark+跟随系统 |
| ✅ **模组冲突检测** | ObsMCLauncher | 扫mods目录的jar，检测重复/冲突 |
| ✅ **启动器自更新** | ObsMC / XMCL / GDLauncher | Velopack或GitHub Release增量更新 |
| ✅ **整合包导入(CF/MR格式)** | BlockHelm / HMCL | .mrpack / zip 整合包导入 |
| 全局+实例独立设置 | HMCL / BlockHelm | 每个实例可单独配Java/内存/启动参数（AC目前只有全局） |
| 设置从弹窗改为导航页 | AC自改 | SettingsDialog → MainWindow.stack 页面，不再弹窗，导航栏加设置项 |

### 🔥 P2 — UI 设计取经

| 方向 | 参考来源 | 说明 |
|------|---------|------|
| **磨砂/亚克力质感** | ObsMCLauncher | 3套质感样式(Flat/Acrylic/Glass)，AC目前纯白背景 |
| **主页卡片布局** | ObsMC / BlockHelm | 信息卡片式排版，AC已有部分 |
| **设置项层级** | BlockHelm | 全局vs实例设置分明，AC需要理清 |
| **Potato PC 模式** | GDLauncher | 一键关闭全部视觉增强让老旧电脑也能跑——AC可借鉴 |

### 💎 长远差异化：插件系统

ObsMC的插件系统（市场/卡片/页面扩展/命令/钩子/通知）是未来方向。

**AC 连这个都不用做全，做到 ObsMC 的 30% 就够差异化**：只暴露"启动前钩子"+"主页卡片"两个扩展点，让用户能自己给 AC 加小功能。

## 五、B站视频对应参考点

| 视频 | 对应上面哪个启动器 | 关注点 |
|------|------------------|--------|
| **30+启动器盘点** | 全部 | 全景认知，看生态缺什么 |
| **Modrinth 美西螈(07-18最新)** | HMCL / XMCL | 中文社区适配最佳实践 |
| **LauncherX 功能一览** | BlockHelm | UI布局+设置项组织 |
| **DCML(一键启动)** | DCML | onboarding极简设计 |
| **PCL罢工吐槽** | —(闭源) | 用户痛点→设计避坑 |
| **BlockHelm(全新)** | BlockHelm | 联机/资源中心/实例导出 |
| **GDLauncher全功能** | GDLauncher | 云分享(实例码)+服务器管理模块 |

## 六、UI 大改实施方案（13:10 更新，sudachi.top 列表 + GitHub fetch 结论）

### 目标：实例页 + 设置页 + 登录 + 导航 全量美化

#### A. 实例卡片（最优先，用户明确吐槽"用不惯"）
```
现状：InstanceCard = 简单 QHBox（图标 + 名字 + 版本·加载器 + 按钮）
改法（参考 Fluent/PCL2/HMCL 卡片式）：
  ① 卡片：圆角+阴影+hover 高亮（QSS 已有 card 类，补 hover 态）
  ② 徽标：加载器小徽章（原版/Fabric/Forge 彩色标签）
  ③ 版本行：版本 + 加载器分开显示，加"游玩时长"（如果有）
  ④ 操作：启动/设为当前/删除 移到右侧，hover 才显示（或常显小图标）
  ⑤ 空态：无实例时显示引导（"点右上角新建实例"）
```

#### B. 新实例对话框（卡片式向导）
```
现状：3 行表单（名称/版本/加载器）+ 路径预览
改法（参考 Fluent/BlockHelm）：
  ① 分步：名称 → 版本+加载器 → Java → 确认
  ② 版本区：正式版为主 + "显示快照" 开关（已做过滤，补开关）
  ③ Java 选择：默认自动，可下拉指定（实例级）
  ④ 卡片式选项：加载器用卡片按钮而非下拉（原版/Fabric/Forge 图标卡片）
```

#### C. 设置页（补全功能，参考 PCL2 分级 + Fluent 清单）
```
① 分级：新手页（RAM预设/窗口/语言/主题）+ 进阶页（JVM/Java/镜像/诊断）
② 补：Java 版本管理入口（已有，改明显）、BMCL 镜像源开关
③ 深色主题：QSS token 已有 dark 色板，接 settings 开关（确认可用）
④ 设置项 hover 提示（tooltip 解释每个设置干什么）
```

#### D. 登录对话框（重构，顺手修 FramelessHelper 残留 bug）
```
① 去掉 FramelessHelper + TitleBar → 标准 QDialog（跟设置页迁移一致）
② 卡片式：离线卡 / 外置卡 / 微软按钮 三区视觉统一
③ 微软区已简化（上轮做了）
```

#### E. 导航栏
```
① 图标统一：补齐 lobby 图标（已 fallback server），检查所有 nav 图标
② 间距/选中态：仿 Fluent NavigationView（选中底色块+圆角）
```

#### F. 全局视觉
```
① 圆角统一：card 12 / btn 10 / 输入框 8（theme.py 已有 radii 常量）
② 阴影：卡片阴影已定义，确认全局生效
③ 主色调：accent 统一用 COLORS['accent']，减少硬编码
```

### 实施顺序
```
第1步：A 实例卡片美化（最快见效）
第2步：B 新实例对话框重做
第3步：C 设置页分级 + 补功能
第4步：D 登录重构（连带修 bug）
第5步：E/F 导航 + 全局视觉收尾
```

## 七、资源中心数据源方案（13:26）

### 现状
AC 的 store 页（StorePage）只接了 Modrinth 搜索。用户要求：加其他资源站（国外站做备选 + 警告下载慢）。

### 数据源清单（按优先级）

| 源 | 类型 | API 开放性 | 国内可用性 | 建议 |
|----|------|-----------|-----------|------|
| **Modrinth** | Mod/光影/资源包/整合包 | ✅ 完全开放（api.modrinth.com，无需 key） | 🟡 时好时坏 | **主源** |
| **CurseForge** | Mod/整合包/资源包 | ⚠️ 需要 API key + 使用条款严格（2023 收紧，第三方启动器受限） | 🔴 基本不可用 | 备选（需 key + 警告） |
| **BMCLAPI** | 游戏核心/依赖/镜像 | ✅ 开放（bmclapi2.bangbang93.com） | 🟢 国内快 | **核心下载主源** |
| **MC百科 (mcmod.cn)** | Mod 信息/中文描述 | ⚠️ 无正式下载 API，信息可爬 | 🟢 国内快 | **中文信息增强**（Modrinth 结果附中文名/简介） |
| **MCBBS** | 整合包 | ❌ 已关停（2023） | — | 忽略 |
| **FCL 整合包源** | 整合包 | 社区自建 | 🟡 | 可选 |

### 集成方案
```
主流程：Modrinth 搜索/浏览 → 一键安装到实例
增强：搜索结果用 MC百科 补中文名 + 简介（可选，异步）
下载加速：核心文件走 BMCLAPI 镜像；Modrinth 文件走官方（可加镜像开关）
备选：CurseForge（默认关闭，用户开启时警告"需网络工具/可能很慢"）
```

### CurseForge 现实
- CF API 2023 起要求 app key + 限制第三方（Prism/HMCL 用"手动访问网页"方式绕过）
- **不建议首版做 CF**，先 Modrinth + BMCLAPI + MC百科 中文增强，CF 留接口以后接

## 八、联机功能全景（13:26）

### 用户问题：P2P 之外还能加什么

| 方案 | 说明 | 成本 | 优先级 |
|------|------|------|--------|
| **局域网自动发现** | UDP 广播找本机/局域网已开的 MC 世界，一键加入 | 低（Python 自写） | 🥇 先做 |
| **自定义服务器列表** | 手动添加 IP:端口，右键"添加服务器"，一键进 | 低 | 🥇 先做 |
| **房间码 + STUN/TURN 穿透** | P2P 直连优先，打洞失败走 TURN 中继（BlockHelm 方案） | 中（需自建/租 TURN） | 🥈 核心 |
| **内置开服管理** | 一键装服务端 + 开服 + 玩家管理 + 控制台 + 性能监控（GDLauncher Server Management） | 中高 | 🥈 差异化 |
| **内网穿透（樱花frp/NatApp）** | 玩家自己配 frp，启动器只是提示引导 | 低（做引导 UI） | 🥉 可选 |
| **整合包一键部署服务端** | 把实例直接部署成独立服务端（BlockHelm 有） | 中 | 🥉 后续 |
| **Tailscale 式组网** | 把玩家拉进虚拟局域网，复杂 | 高 | ❌ 暂缓 |

### 建议路线
```
第 1 步（快速）：局域网发现 + 服务器列表（纯本地，无服务器成本）
第 2 步（核心）：房间码 + STUN/TURN（需要一台中继服务器或租 TURN）
第 3 步（差异化）：开服管理（GDLauncher 模式）
```

## 九、实例/Mod 管理信息架构（13:26，学 HMCL/PCL/Prism）

### 现状问题（用户反馈）
- 实例管理和 Mod/资源包是**独立的导航页**，玩家要在页面间跳转
- 主页只有启动按钮 + 实例下拉，没有"进入实例"的入口
- 用户希望"每个实例像文件夹一样"——选中实例后能看它的 Mods / 资源包 / 光影 / 存档

### 主流启动器怎么划分

| 启动器 | 模式 |
|--------|------|
| **HMCL** | 左侧版本列表（卡片）→ 选中版本 → 顶部 tab 切换（启动/设置/Mod/资源包/光影/存档）——**实例为中心** |
| **PCL2** | 主页大卡片 + 版本下拉；下载页分 Mod/整合包/光影/资源包 tab；设置分全局/版本两级 |
| **Prism** | 实例列表 → 双击进实例详情页 → 左侧菜单（Settings / Mods / Resource Packs / Shader Packs / Saves / Worlds）——**实例详情页模式** |

### AC 建议架构（Prism 模式最清晰）
```
导航保持：主页 / 实例 / Mods / 资源 / 联机 / 设置

实例页改造：
  左侧：实例列表（现在的卡片，可选）
  右侧：选中实例后显示"实例详情"——而不是直接平铺列表

实例详情页内容（参考 Prism 的 Edit Instance）：
  ├─ 概览：版本/加载器/路径/操作（启动/打开文件夹/备份/导出）
  ├─ Mods：列表 + 启用/禁用 + 添加（拖放/文件选择）
  ├─ 资源包 / 光影包 / 存档：分区列表
  └─ 设置：该实例的 Java / 内存 / 启动参数（独立于全局）

Mods 页改造：
  现在 ModsPage 是独立导航页（只显示当前实例 mods）
  建议：并入实例详情页，导航的"Mods"改为"打开当前实例详情"
```

### 好处
- 玩家习惯"实例 = 文件夹"的心智模型（Prism/HMCL 验证过）
- 每个实例的 mods/资源包/光影/存档都在一个地方，不用到处找
- 为后续"实例独立设置"铺路

## 十、主页自定义 + 新闻（13:26，学 PCL2）

### PCL2 有而我们没有的
1. **自定义主页**：背景图/布局自定义、版本列表位置与样式可调
2. **主页新闻**：官方新闻源（Mojang 博客 / Modrinth 公告）拉取展示
3. 自定义主题（PCL2 的强项）

### AC 建议
```
① 主页布局：现有 home_style 只有 4 种预设，改"预设 + 自定义"两级：
   - 预设：ac_default / pcl_card / hmcl_list / modrinth_modern（已有）
   - 自定义：背景图（已有 wallpaper）、卡片顺序（可拖？低优先）
② 主页新闻：加载 Mojang 官网新闻 RSS 或 Modrinth 公告 → 主页底部/侧边卡片
   - 离线可缓存上次内容
   - 失败静默（不挡启动）
③ 主题：深色主题已基本可用（theme.py 双 token），设置里接通
```

### HMCL 实际代码结构（13:30 agent 抓取 GitHub main 分支）

```
HMCLBoot  薄引导（JVM 检查、拉起主程序）
HMCL      JavaFX UI 层
  ├─ ui/main/       根导航（MainPage/RootPage）
  ├─ ui/instances/  GameListPage(左侧列表) + GameInstancePage(详情页)
  │                  + ModListPage / ResourcePackListPage / DataPackListPage
  │                  / WorldListPage / WorldManagePage / WorldBackupsPage / SchematicsPage
  ├─ ui/download/   VersionsPage / InstallersPage / ModpackPage（可选下载源）
  ├─ theme/         PersonalizationPage(个性化) + ThemePackManagementPage(主题包导入导出)
  └─ ui/main/       JavaManagementPage / JavaInstallPage / JavaDownloadDialog
HMCLCore  核心逻辑（纯 Java）
  ├─ game/          实例与版本模型（2026-07 重构：GameInstanceID/Manifest/Patch）
  ├─ download/      BMCLAPIDownloadProvider(镜像) + AutoDownloadProvider(自动选源)
  │                  + MCIM 回退源（PR#5798）
  ├─ auth/          authlib-injector 第三方登录
  ├─ addon/         **统一抽象：模组/数据包/资源包都是 Addon**
  ├─ modpack/       CurseForge / Modrinth 整合包导入导出
  └─ java/          运行时发现+缓存 / JavaVersionConstraint(版本约束)
```

**对 AC 的关键结论**：
1. **实例详情页模式实锤**：HMCL = 左侧列表 + 详情页 + 各资源分区页面（Mod/资源包/数据包/存档/投影各一页）——正是我第九节建议的模式
2. **addon 统一抽象**：模组/数据包/资源包统一成 Addon → AC 的 ModsPage 应该能复用到资源包/光影（做通用"资源列表"组件）
3. **主题包系统**：PersonalizationPage + 主题包导入/导出 → AC 可以学"主题包"（QSS 预设导出为 .actheme 文件）
4. **自动选源**：AutoDownloadProvider 自动在官方/BMCLAPI/MCIM 间选源 → AC 下载模块应内置"自动镜像"逻辑
5. HMCL **没有新闻模块** → 新闻是 AC 可做的差异化（PCL2 有）

### PCL2-CE 实际代码结构（20:45 GitHub 仓库抓取）

```
PCL2-CE（社区版）：
  Plain Craft Launcher 2/  主程序源码（自定义许可证！）
  PCL.Core/                核心逻辑库
  PCL.Core.Test/           单元测试
  PCL.Core.SourceGenerators/  Roslyn 源生成器
技术栈：C# / .NET 10 / WPF（社区版已从 VB.NET 迁移到 C#）
```

**对 AC 的关键结论**：
1. ⚠️ **许可证警告**：主程序目录是**自定义许可证**（非开源许可），只能"看思路"不能"抄代码"——UI/功能设计参考思路可以，逐字复制代码有法律风险
2. **核心与 UI 分离**：PCL.Core 独立于 UI 层 → AC 的 src/core 结构方向正确，继续保持
3. PCL2 的主页自定义/新闻/主题/下载都内嵌在主目录，**从公开仓库看不到实现细节**——只能通过实际使用观察
4. 社区版当前重心：.NET 10 迁移 + 安全补丁 + **卸载功能** → 启示：AC 应做**启动器自卸载/清理**（删除数据目录的引导流程）

## 十一、明天开工步骤