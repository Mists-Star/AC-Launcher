# round-138 — .NET 轻量版启动器（立项 spec）

> 决策来源（2026-10-28，用户选定）：**双版本发 release（349MB 完整版 + 135MB
> lite 版）+ 立项 .NET 轻量版**。Rust/Tauri 路线已评估后放弃（无成熟 MC 启动
> 生态、复杂桌面 UI 表现力弱），对比见 `CHANGELOG.md` round-137。

## 1. 为什么立项

- Python/PySide6 栈的体积下限被 Qt 锁死：**不带 Chromium 也还有 ~80MB Qt 本体**，
  做不到 PCL2 那种 15MB 级原生档（本轮实测 lite = 135.4MB 即证）。
- PCL2（.NET/WPF，15.2MB）证明了 .NET 做到原生档是**已验证路径**。
- 关键架构优势：**HTML 扩展宿主可以保住**——.NET 侧用 **WebView2（Windows
  系统自带 runtime，零打包体积）** 替代打包版 Chromium（195MB），插件生态不作废。

## 2. 目标与非目标

**目标**
- G1 体积：完整功能 **< 60 MB**（发布单文件 zip；对标 PCL2 15 / Prism 23）。
- G2 功能与 Python 版对齐：登录、实例管理、版本下载/启动、Mod/整合包导入、
  设置、皮肤、音效、i18n（中/英）、品牌自定义（round-136）、扩展宿主（WebView2）。
- G3 视觉不回退：AC 主题、亚克力/圆角（现 `win_acrylic`/`win_rounded` 逻辑等价复刻）。
- G4 与 Python 版**并行存在**：Python 版继续作为主线发双版本 release，直到
  .NET 版通过验收才切换。

**非目标（本期明确不做）**
- 跨平台（macOS/Linux）——那是 Avalonia/Tauri 的理由，本项目暂不需要。
- 离线重写视觉特效框架（aclive 等）——先功能等价，视觉增强后置。
- Python 版停止维护。

## 3. 技术选型

| 项 | 选择 | 理由 |
| --- | --- | --- |
| 运行时 | **.NET 10 LTS**（若生态坑多则回落 .NET 8 LTS） | LTS、裁剪发布成熟 |
| UI 框架 | **WPF** | PCL2 验证过的原生档路径；纯 Windows 目标下无 Avalonia 必要 |
| MC 启动库 | **CmlLib.Core**（+ Installer.Forge 等） | 原版/Java 运行时/Fabric/Quilt/Forge/NeoForge/认证/启动全覆盖 |
| 扩展宿主 | **WebView2**（系统 runtime） | 零打包体积保住 HTML 插件生态，替代 195MB Chromium |
| 打包 | `dotnet publish -p:PublishSingleFile=true -r win-x64 --self-contained` + trimming | 单文件/小目录分发 |

**选型待验证（M0 必须给出结论，见 tasks.md）**
- mrpack（Modrinth 整合包）与 CurseForge 整合包 zip 导入 —— CmlLib 不含，需自实现
  （Python 版 `mrpack_import`/`modpack_import` 可作规格参照）。
- 本项目自有后端 `net_api.py`（皮肤/商店/联机等）协议移植 —— C# HttpClient 平移，
  需盘点全部端点。
- 离线登录 + 第三方认证（现有 authlib 路径）是否被 CmlLib 的 auth 覆盖。

## 4. 迁移盘子（实测）

- **76 个 Python 模块 / 38,776 行**；巨石 top4：`main_window.py` 194KB、
  `i18n.py` 194KB、`pages_instances.py` 126KB、`settings_dialog.py` 118KB。
- 分层映射：
  | 层 | Python 现状 | .NET 目标 |
  | --- | --- | --- |
  | 核心 | `core/*`（java/install/launch/mirror/auth…） | 类库 `Ac.Launcher.Core`，CmlLib 之上薄封装 |
  | 服务 | `net_api.py` / `aclive.py` | `Ac.Launcher.Services`（HttpClient + JSON） |
  | UI | `main_window` + `pages_*` + `settings_dialog` | WPF MVVM（ViewModel 逐页对应） |
  | 平台 | `win_acrylic`/`win_dpapi`/`win_rounded`/`frameless` | P/Invoke 等价迁移（Win32 代码可直接翻译） |
  | 扩展 | `plugin_host.py`（QWebEngine 注入桥） | WebView2 `postMessage` 桥（协议保持 `window.AC.*` 不变） |

## 5. 体积预算（.NET 版）

| 组件 | 预算 |
| --- | --- |
| WPF 运行时（self-contained + trim） | ~30-40 MB |
| CmlLib.Core + 依赖 | < 2 MB |
| WebView2（系统自带，不打包） | 0 |
| 资源/assets/翻译 | ~3 MB |
| **合计目标** | **< 60 MB**（G1） |

若 self-contained 仍超标，备选：framework-dependent 版（< 10MB，需用户装 .NET
Desktop Runtime，PCL2「需 .NET」同款取舍）——作为 release 的**第二档**，届时再定。

## 6. 风险

- R1 `net_api` 自有后端协议盘点不全 → M0 出端点清单，缺一个就阻塞一个里程碑。
- R2 CmlLib 覆盖不到的整合包格式 → 先保 mrpack，CF zip 次之（分批交付）。
- R3 WPF 视觉复刻工作量（亚克力/无边框/主题动画）→ 功能等价优先，动效后置。
- R4 双栈并行期的 bug 双修成本 → 缺陷清单仍以 `待办与Bug清单.md`（若涉及
  Environmental Box 则另说）/ CHANGELOG 为准，.NET 版缺陷单独记在本目录 tasks.md。

## 7. 与发版的关系（round-137 结论）

- release 立即可挂：**完整版 349.0 MB**（带扩展宿主）+ **lite 135.4 MB**
  （扩展区降级提示），release notes 必须写清两者差异。
- .NET 版验收（M4）通过前，不改变发版策略。
