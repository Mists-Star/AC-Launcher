# AC Launcher 竞品横向对比（启动器地貌 + 差距分析）

> 日期：2026-08-11 ｜ 目的：找我们（AC Launcher，Python/PySide6）与新旧启动器的差距，决定明天「抄 / 超」哪些点。
> 关联：BlockHelm 专项见 `2026-08-11.md`；第 13 轮双页+图标缓存修复待打包复测。

---

## 0. 我们的现状基线（对照锚点）

- **栈**：Python 3.13 + PySide6（QSS 主题）+ PyInstaller / Nuitka 打包。
- **已实现**：Microsoft 登录（device-code）、实例管理、多加载器（Fabric/Forge/NeoForge/OptiFine/LiteLoader/Quilt）、mod 本地管理、资源中心 `StorePage`（Modrinth + CF widget）、BMCLAPI + 官方下载、单实例（跨进程 mutex，**已实现**）、崩溃分析 UI。
- **第 13 轮待打包**：双页根因修复（QDialog 窗口标志）、图标缓存 `.img`→`.png` 修复。
- **11 个短板（用户原话）**：动画 / 主页排版功能样式 / 玩家各类管理 / 启动器图标资源 / 流畅度 / 美观度 / 可自定义度 / 资源图标零等待 / 下载路线窄慢 / 欢迎页 / 单实例优化。

---

## 1. 启动器地貌（新 + 旧，含栈 / 协议 / 强项）

| 名称 | 年代 / 定位 | 技术栈 | 协议 | 最大强项 | 与 AC 差距相关度 |
|---|---|---|---|---|---|
| **Prism Launcher** | 现代标杆 | C++ / Qt | GPL | 实例管理天花板、轻量、可定制、内置 mod 管理 | 高（实例/mod） |
| **GDLauncher (Carbon)** | 现代 | Electron/React + Java | 开源 | 现代 UI、云实例分享、自动更新、CF+MR | 高（UI/流畅） |
| **Modrinth App** | 现代新秀 | Electron/React | 开源 | 快、无广告、MR 生态 | 高（UI/流畅/图标） |
| **HMCL** | 现代 / 中国最火 | Java（Gradle） | GPL | 多账户（MS/离线/第三方）+ 皮肤披风 3D 预览、UI 定制、主题、窗口透明、跨平台多架构 | **极高**（玩家管理/中国适配） |
| **FluentLauncher** | 现代 / Win11 | C# / .NET 9 + WinUI 3 | 开源 | 流畅视觉、自定义背景+主题色、多线程并发补全依赖、BMCLAPI 镜像、CF/MR、MS/Yggdrasil/离线 | **极高**（背景/下载并发/流畅） |
| **SkLauncher** | 现代 | C++ | MIT | 轻量极速、皮肤披风、fluent UI 主题、便携、RAM 滑条 | 高（流畅/玩家管理） |
| **AetherLauncher** | 现代 | Java / Swing | — | 7 内置主题+透明、账户+皮肤预览（Minotar）、Win Acrylic、动画、插件系统 | 高（主题/动画/玩家） |
| **Tempest-Launcher** | 现代（**我们同栈!**） | PyQt（→ Tauri 重构中） | Apache | 整合包创建、自动装 mod、5 用户名绑 MS、自定义皮肤披风、多贴图服务器 | **极高**（同栈参考） |
| **BlockHelm** | 现代（用户点名） | C# / .NET 8 | GPL v3 | 皮肤披风、图片+亚克力背景、多源+并发+限速、mod 依赖检测、LAN 房间、启动诊断 | **极高**（已专项） |
| **ShardLauncher** | 现代 / 移动 | Kotlin / Jetpack Compose | GPL 3 | Material3、动态取色、毛玻璃、发光动效、静态/视频背景、动画速度调节、侧栏位置自定义 | 高（动画/背景灵感） |
| **BedrockLauncher** | 现代 / Bedrock | C# / .NET + WPF | 开源 | 主题系统、80+ 方块图标版本标识、自定义背景、本地化 | 中（图标体系参考） |
| **MultiMC** | 经典鼻祖 | C++ / Qt | GPL | 多实例沙盒、极简功能派 | 中（实例范式） |
| **PolyMC** | 经典 fork | C++ / Qt | GPL | MultiMC fork + 下载 mod（曾有争议） | 低 |
| **Legacy Launcher** (TL Legacy) | 经典 | Java | 开源 | 经典体验延续 | 低 |
| **Technic Launcher** | 经典 | Java | 闭源 | 社区整合包发现 | 低 |
| **ATLauncher** | 经典长青 | Java | 开源 | 154 内置包、易用、轻量 | 中 |

---

## 2. 按我们 11 个短板逐条对比（谁做得好 + 我们能学什么）

### ① 动画（整体缺失）
- **标杆**：Shard（Compose 发光/模糊/动态取色）、GDLauncher/Modrinth（React motion）、Aether（Swing 动画 + Acrylic）、Fluent（WinUI 过渡）。
- **学**：Qt `PropertyAnimation` 做页面淡入 / 卡片浮入；**欢迎页 AC 字母动画**（用户已定）。

### ② 主页排版 / 功能 / 样式（要重做）
- **标杆**：GDLauncher（视觉卡片 + 分组 + 拖拽排序）、HMCL（现代化）、Prism（实用列表但朴素）。
- **学**：主页用「状态面板 + 实例卡片网格」而非纯列表。AC 当前 `ac_default` 统御状态面板方向已对，深化即可。

### ③ 玩家的各类管理（我们只有 Microsoft 登录）
- **标杆**：HMCL（多账户 MS/离线/第三方 Authlib-Injector + 皮肤披风 3D 预览）、Tempest（5 用户名绑 MS + 皮肤披风 + 多贴图服务器 Tempest/Elyby/SkinMe/Mojang/TLauncher）、SkLauncher（皮肤披风）、BlockHelm（皮肤披风 + 多账户）。
- **学**：加**离线账户**；加**皮肤/披风上传 + 预览**（接 CustomSkinLoader / LittleSkin / MinePI / Minotar API）；**多账户切换**。

### ④ 启动器图标资源（缺统一图标体系）
- **标杆**：BedrockLauncher（80+ 方块图标版本标识）、Shard、HMCL。
- **学**：建**统一图标集**（版本/加载器/mod 类型/资源包/光影），别全靠运行时生成 pixmap；图标走 **QRC 内嵌**。

### ⑤ 流畅度
- **标杆**：Prism / SkLauncher（C++ 极速）、GDLauncher / Modrinth（轻量）、Yumeri SDK（并发下载 + 完整性校验）。
- **学**：主线程**绝不阻塞**；下载/解压/校验放 `Worker`；图标异步 + 缓存（已修）；实例多时列表**虚拟化**。

### ⑥ 美观度
- **标杆**：GDLauncher / Modrinth / HMCL 现代；Aether（7 主题 + 亚克力）；BlockHelm（优雅精致，用户已赞）。
- **学**：上**主题系统**（深/浅/跟随 + 强调色）；QSS 精细化；圆角 / 阴影 / 毛玻璃（Win11）。

### ⑦ 可自定义度（尤其自定义背景）
- **标杆**：FluentLauncher（背景 + 主题色）、BlockHelm（图片 + 亚克力 + 强调色）、BedrockLauncher（主题 + 80 图标 + 背景图）、Shard（动态取色 + 静态/视频背景 + 动画速度 + 侧栏位置）、HMCL（UI 定制 + 窗口透明）。
- **学**：用户设想——**官方版本壁纸默认 + 玩家自定义图覆盖**（玩家设了用玩家的；没设按所选版本给官方壁纸）；强调色选择；主题（深/浅/跟随）。设置持久化到 json。

### ⑧ 资源图标零等待（我们还在等）
- **标杆**：他们普遍本地缓存/内嵌，读盘秒显。BlockHelm「mod 不要加载」推测：图标随包元数据本地/内嵌或激进缓存。
- **学**：我们已修 `.png` 缓存；再加——**占位图立即显示**（signal 先 `setPlaceholder` 再异步替换）、**热门 mod 图标随程序 QRC 内置**、避免每次重建卡片触发重新 `load`。

### ⑨ 下载 / 资源获取路线（我们太窄太慢）
- **标杆**：FluentLauncher（BMCLAPI + CF + Modrinth + MCIM 翻译，多线程并发补全）、PCL2（BMCLAPI + 64–128 并发 TCP 分片 + CRC 重传）、Yumeri SDK（Mojang+BMCLAPI，`maxConcurrentDownloads`，完整性校验）、GDLauncher/Prism/Modrinth（CF+MR）。
- **学**：加 **Modrinth 直连源**（我们目前只有 CF widget）；加**镜像源选择**（BMCLAPI/官方/MCMod/MCIM）；**下载并发**（多线程分片）；**限速选项**；进度精确。我们当前 BMCLAPI+官方+CF widget 偏窄。

### ⑩ 欢迎页（用户说不好看）
- **标杆**：Shard 启动动画；GDLauncher splash。
- **学**：用户已定——**AC 字母动画作启动动画再正常进入**；可加淡出。

### ⑪ 单实例（我们已实现，用户没测过）
- 我们：`main.py:94-103` stale-lock-safe 跨进程 mutex，第二实例**静默退出**（非置前）。多数竞品不强调。
- **学**：升级为「第二实例**置前现有窗口**」（Win: `FindWindow` + `SetForegroundWindow`；跨平台用本地 socket 或 `QLockFile` + 消息）。我们已领先，只需优化 UX。

---

## 3. 合规红线

- **GPL v3**：BlockHelm、HMCL、Prism、MultiMC、PolyMC、Shard → 抄代码须整体 GPL 兼容（我们 license 未定，**先不抄代码，学思路/架构**）。
- **MIT**：SkLauncher、Aether(?) → 较宽松但仍需署名。
- 我们 license **未定** → 决定抄前先拍板。
- 既有红线不变：不逆向 / 不复制专有资源。

---

## 4. 明天优先级（抄 / 超路线）

- **P0**：欢迎页 AC 字母动画 + 主页重做（状态面板 + 实例卡片）+ 自定义背景（官方版本壁纸默认 + 玩家覆盖）。
- **P1**：主题系统（深/浅/跟随 + 强调色）+ 图标体系内嵌（QRC）+ 资源图标零等待加固（占位立即 + 内置热门）。
- **P2**：玩家管理（离线账户 + 皮肤披风预览 + 多账户切换）+ 下载（Modrinth 源 + 并发 + 镜像选择 + 限速）。
- **P3**：单实例置前优化 + 流畅度（Worker / 虚拟化）。
- ⚠️ **前置**：第 13 轮双页 + 图标缓存修复先打包复测（卡在源码未 build）。

---

## 5. 重点参考仓库链接

- BlockHelm（用户点名）：https://github.com/zqq-699/BlockHelm-Launcher
- Tempest-Launcher（**PyQt 同栈**）：https://github.com/GoodDay360/Tempest-Launcher
- FluentLauncher：https://github.com/Xcube-Studio/Natsurainko.FluentLauncher
- HMCL：https://github.com/HMCL-dev/HMCL
- Prism Launcher：https://github.com/PrismLauncher/PrismLauncher
- GDLauncher：https://github.com/gorilla-devs/GDLauncher
- SkLauncher：https://github.com/Harshit-pruthi/sklauncher-minecraft
- AetherLauncher：https://github.com/twiks228/AetherLauncher
- ShardLauncher：https://github.com/LanRhyme/ShardLauncher
- MultiMC：https://github.com/MultiMC/MultiMC5
- ATLauncher：https://github.com/ATLauncher/ATLauncher
- BMCLAPI 文档：https://bmclapidoc.bangbang93.com/
- Yumeri-Craft-SDK（并发下载参考）：https://github.com/yumerijs/Yumeri-Craft-SDK
