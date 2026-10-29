# RELEASE\_1.0.0\_CHECKLIST — v1.0.0 完工清单

> 版本策略（2026-09-02）：正式发布前 CHANGELOG 用 `round-NN` 内部迭代号；
> 本篇全部完成并通过验收后，才一次性打上 `v1.0.0` 并发布首个 release。
> 来源：2026-09-02 Python 启动器对标报告（<workspace>）、8-30 PCL-CE 学习报告、
> 8-01 生态调研任务单（LAUNCHER\_SURVEY\_2026-08-01.md）、本轮代码盘点。

## A. Release-Blocker（不过不发布）

- [x] **README 重写**（round-73 2026-09-02）：功能矩阵（版本/实例/加载器/
  联机大厅/崩溃自修复/资源中心/双语/主题包/启动高级设置）、技术栈、
  **隐私承诺（DPAPI 加密、日志打码、零遥测、零外部依赖）**、自检命令、
  路线图指向本清单。此前停留在"轻量浅色主题"初版。

- [x] **批量下载队列**（round-73 2026-09-02）：新增 `src/batch_download.py`
      `BatchDownloader`——4~8 worker 线程池 + 任务队列 + 失败记录继续 +
      线程安全进度/取消 + 存在即跳过 & sha1 复核（`make_download_task`）；
      已接入 CurseForge 整合包文件下载（原本逐个顺序 + 失败中断整批）；
      `_diag_batch_tmp.py` 6 用例（并发/失败继续/cancel/跳过/sha1/边界）全过。

- [x] **版本号体系回归**（round-73 2026-09-02）：新增 `_diag_version_parse_tmp.py`
      覆盖 `26.1/26.2` 新版本号 + `26w08a` 快照 + `24w14potato/1.RV-Pre1` 愚人节
      + `c0.0.13a` classic + 缺日期条目——认证方式为「type + 日期」排序天然免疫
      语义化版本号（无需修解析器），5 项断言全过，不变式已固化防回归。

- [ ] **全量回归绿 + 真实启动冒烟**：`python regress.py` exit=0（round-112 前
  此处写的是 `_diag_all.py`——**该脚本从未入库**，`git log --all -- _diag_all.py`
  为空，等于回归套件一直不存在）。回归入口现已建好，覆盖 11 项：编译 / i18n
  对称 / PII 门禁 / 默认值审计 / 功能冒烟 / 全页面构造冒烟 / 各批次回归；
  `--shots` 额外出视觉截图。开放项见 `docs/quality_punchlist.md`。
  现状 2026-10-24（round-120）：`regress.py` 11/11 通过（无 git 的机器上 PII
  门禁自动 SKIP 而非误判失败），`pyflakes src main.py` 零告警。剩余：新建
  Fabric+Forge 实例真实拉取/启动到主菜单一次通过（含镜像可用性）——需要真机
  联网执行。

- [ ] **打包成品**：`build.bat`/PyInstaller 出可分发单包，安装后首次运行
  冒烟（Acrylic 关闭时的降级路径）。
  现状 2026-10-26（round-133）：打包已切换为 PyInstaller onedir，
  `build.bat` → `build.py` → `dist_beta\AC_Launcher\AC_Launcher.exe`；
  spec 补齐 32 个模块与 mll 动态导入，完整构建 exit=0，成品离屏启动到
  MainWindow 且无 crash/boot/fault 日志。**剩余：真机（非离屏）首启目检
  与 Program Files 只读路径验证。**

## B. 高感知（建议在 1.0.0 前，按性价比）

- [x] **日志终端 搜索高亮 + 导出到文件**（round-77 2026-09-03）：console 页新增搜索框——
  大小写不敏感高亮全部匹配 + 实时计数 + Enter 跳下一个；新增「导出…」把当前（过滤后）
  视图存 `.txt`（空日志拦截）；`_diag_console_search_tmp.py` 11 断言全过。

- [x] **窗口置顶**（PCL-CE 三行级小特性）。
      现状核实 2026-10-24：设置 → 启动 / 外观已有「窗口置顶（总在最前）」
      复选项（`settings.always_on_top`，`setWindowFlag(WindowStaysOnTopHint)`）。

- [x] **多实例并行启动**（PCL-CE ⭐⭐⭐，开小号/多开刚需，工程量中等——需线程
      安全审计 launch 流程）。
      现状核实 2026-10-24：round-81 已落地——`_game_procs` 按实例登记进程，
      同一实例重复启动会提示，不同实例可并行运行。

- [x] **低内存警告**（PCL-CE ⭐⭐⭐：128 内存玩家崩溃前提前拦截）。
      现状核实 2026-10-24：启动前预检用 commit headroom
      （CommitLimit − CommitCharge）而非「当前可用物理内存」比较 `-Xmx`，
      默认按钮落在「继续」，误报可按回车继续。

- [x] **导出/导入设置**（配置备份，零风险，PCL-CE ⭐）。
      现状核实 2026-10-24：`_export_settings` / `_import_settings` 已实现，
      敏感键（CurseForge Key 等）导出剔除、导入拒绝还原。

- [x] **下载源测速**（镜像切换已有，补各源 ping/测速展示；PCL-CE ⭐⭐）。
      现状核实 2026-10-24：设置 → 网络「测速选优」已可实测各镜像并选最快源。

- [x] **系统托盘**（PCL2/HMCL 惯例；实查无 QSystemTrayIcon）：最小化/关闭到托盘 +
      托盘菜单（快速启动/显隐窗口/退出），游戏后台运行期间挂托盘不占任务栏。
      现状核实 2026-10-24：`QSystemTrayIcon` + 托盘菜单已实现；默认关闭窗口即
      退出，用户可在设置里开启「最小化到系统托盘」。

- [x] **实例级参数覆盖**（HMCL 实例设置 ⭐）：全局默认 + 单实例覆写内存/Java/额外
      JVM 参数（现为全局 ram/java_auto 一套，多实例需求不同需手动改全局再改回）。
      现状核实 2026-10-24：`Instance.ram_mb`（0 = 跟随全局）与 `Instance.java_path`
      已接入 launch，实例详情页可单独覆盖内存 / Java。

## C. 可后置（1.1+ / 视反馈）

- [ ] Spotlight 全局搜索（BakaXL 4.0 思路：Ctrl+K 搜实例/版本/设置）。

- [ ] 服务器列表管理（`--server` 直连已有，列表 UI 后置）。

- [ ] Ely.by / 第三方皮肤站认证（Zaphyrous 三认证；国内场景小众）。

- [ ] 欢迎语录引擎（300+ 语录彩蛋，品牌感知，低优可选）。

- [ ] 增量更新（Technic Solder；资源/实例只拉变更）。

- [ ] 架构打磨：Addon 统一抽象（ModsPage → 通用资源列表）、加载器 Provider 化
  （FCL 后端可换思路）、核心/UI 更硬分离（src/core 继续抽净）。

- [x] 页面过渡动效（HMCL 窗口动画清单；QPropertyAnimation 页面切换）。
      现状核实 2026-10-24：round-107 全域 160ms 淡入 + 8px 上浮汇入，连续切页零漂移。

- [ ] 模组一键禁用/启用全部（PCL2 模组页批量开关——排查冲突一秒全关）。

- [x] 游戏完整性检查（补「校验已装核心完整性」入口；下载层 .part/大小/Content-Length 校验已有）。
      现状核实 2026-10-24：实例右键 / 详情「⋯」→「实例体检」按分区分区检查并
      支持单条修复 / 一键修复安全项（幂等，只改 Instance 字段）。

- [ ] 可折叠「调试选项」卡（PCL-CE 收纳高级项；诊断入口已独立成按钮，设置页再膨胀时优先采用）。

- [ ] 禁用硬件加速开关（PCL-CE 疑难杂症项——渲染异常/黑屏兜底）。

- [ ] 游玩时长统计（Prism 底部状态栏「总游玩时长」；现状态栏已有进度/版本/消息，补时长持久化）。

- [ ] TapTarget 式新手引导 overlay（Zalith；现有 onboarding 向导已覆盖首启，补局部高亮指引）。

- [ ] 顶栏「动词导航 + 胶囊反白」备选皮肤（PCL-CE 实验形态，dev_mode 门控，不动现有侧栏主方案）。

***

检查清单维护：完成一项 → `[x]` + round 号 + 日期；列表外新增项随时追加。
