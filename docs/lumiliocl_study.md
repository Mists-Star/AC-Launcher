# LumilioCL 深读：一个原生 Rust 启动器能教 AC 什么

> 调研日期：2026-10-31 ｜ 对象：LumilioCL（https://launcher.lumilio.org/ ，源码
> `github.com/EdwinZhanCN/LumilioCL`，AGPL-3.0-only）
> 证据分级：**【实证】**= 官网/源码/文档原文；**【推断】**= 由事实推导，未见实现。
> 结论只用来指导 AC（PySide6/Qt6）的取舍，不代表要换技术栈。

---

## 0. 一句话结论

LumilioCL 真正值得学的不是「Rust + GPU UI」这个壳，而是三套**模型**：

1. **传输模型**：`SourceProvider → SourceChain → 每文件多连接/预算 → 失败按源记录**，
   而不是「全局开关 + monkey patch」。
2. **任务模型**：所有后台工作（下载/安装/更新/修复/导入）都是同一张 DAG 上的节点，
   统一状态机 + 事件流 + 可重试/可暂停 + 持久化历史（「动态」页）。
3. **「能不能玩」模型**：`diagnose()` 是一个纯函数，把 Java/账户/文件/模组/内存/上次崩溃
   变成带严重级的 `Problem` 列表；首页只回答两件事——**继续哪个、哪些挡住你**。

外加两个「工程习惯」：**动效 token 化**（90/160/280/700ms + 8px 位移）和
**可机读的门禁**（文案长度/文案禁用词/用户路径表都由测试或生成器盯着）。

---

## 1. 产品与功能矩阵【实证】

定位：原生、高性能、可扩展；「你的最后一个下一代 Minecraft 启动器」。
平台：macOS（Apple 芯片）、Windows 10/11 x64、Linux x64（要求可用 Vulkan 驱动）。
当前版本 0.2.3（2026-10-27 发布），官网/文档/路线图全部公开。

| 能力 | 具体内容 |
|---|---|
| 账户 | 微软登录、离线账户、第三方 Yggdrasil（源码导出 `LITTLE_SKIN_URL`、`LITTLE_SKIN_CSL`） |
| Java | 自动检测、推荐版本下载、GraalVM 构建、按规则选 Java、启动前冲突询问 |
| 实例 | 游戏库、合集（标签）、复制、导入其他启动器、整合包导入/导出、快照与完整备份 |
| 内容 | Modrinth + CurseForge 浏览/安装/更新；整合包缺文件按 SHA-1 跨源补齐；简介翻译 |
| 世界 | 世界地图（种子预测、结构图层）、Litematica 投影 3D 预览、材料清单 CSV |
| 外观 | 皮肤/披风/鞘翅预览、衣柜；主题（含自建主题、主题工作室网页预览） |
| 诊断 | 崩溃归因、日志分级、诊断包导出（带脱敏）、磁盘占用与共享文件回收 |
| 工程 | 更新器、内置插件（崩溃分析/投影/Modrinth/CurseForge/Discord/世界地图）、WASM 插件（计划中 0.3.0） |

路线图【实证】：0.2.0 发现页翻译（进行中）→ 0.3.0 WASM 插件与可审核目录（提议）→
0.4.0 陶瓦联机插件（提议）。注意：**WASM 插件当前不可安装**，文档明确「内置原生插件，
不要把原生插件 API 当作已发布的 WASM 契约」。

---

## 2. 技术栈与分层【实证】

### 2.1 栈

- Rust 2024（最低 1.95，开发工具链 1.98.1），`unsafe_code = "forbid"`；
  clippy 把 `dbg_macro` / `todo` / `unimplemented` 全部 deny。
- UI：GPUI（`gpui-pre =0.3.7`）+ `gpui-kit 0.7` + `gpui-component 0.7`（本地 fork）。
- 3D：WGPU（世界地图、投影预览）；Metal/DirectX/Vulkan 由 WGPU 后端选择。
- 异步：tokio（fs/io/net/process/time/sync）；UI 用 `cx.spawn`/channel 桥接。
- 存储：SQLite（`launcher.db`）+ `settings.json`（版本化 schema）。
- 更新器与网站：独立 crate；网站是 Astro + React + Cloudflare Worker，和桌面 UI 无关。

### 2.2 工作区（25 个 crate，依赖方向单向）

```
lumilio-app → lumilio-ui → lumilio-core
                 ↘ lumilio-transfer（下载/校验/发布，独立于领域）
core 还依赖：minecraft / nbt / anvil / schematic / schematic-render / skin-render /
             cubiomes / map-render / block-assets / plugin-api / 内置插件 crates
```

硬约束（`AGENTS.md` 不变量 1）：**core 不许依赖 gpui / gpui-kit / gpui-component**。
理由是「UI 框架换代时的保险」——领域逻辑可以独立测试、独立替换。

### 2.3 UI 内部：feature 实体 + shell

- 每个页面是一个 `features/<name>` 实体：自己持有状态、自己的后台任务
  （`runtime::Worker`）、自己的订阅；**只通过事件向 shell 汇报**，不跨 feature 直接
  改别人的视图。
- `shell` 负责组合、路由 `LiveIntent`、窗口/导航/历史/全局选择。
- 共享控件与主题（`key` / `controls` / `kit` / `theme`）留在 features 之外。
- 规则：**UI 线程绝不做阻塞 I/O**；页面文件超过 ~800 行非测试代码就拆目录模块；
  单元测试放代码旁边的 `tests.rs`，不写行内测试。

### 2.4 对 AC 的翻译

AC 是 `main_window.py` 巨类 + 各 page 文件 + `core/*`。不需要 Rust 的分层，
但可以借两点：

- `core/*` 已经是 Qt-free 的（`instance_health.py` 明确「static, Qt-free」），
  继续守住这条线：新逻辑先落 `core/`，UI 只做展示与触发。
- 页面状态别再往 `MainWindow` 上堆；每个页面一个「页面控制器」对象，
  由它持有自己的 worker/定时器/订阅，主窗口只负责路由。

---

## 3. 性能与内存：宣传数字怎么来的【实证 + 推断】

官网数字（2026-10-09，Apple M2 Pro / 16GB / macOS 27.2，各启动 3 次取中位数）：

| 指标 | LumilioCL | Modrinth App |
|---|---|---|
| 启动 30s 后物理内存 | 106 MB | 404 MB（约 74% 降幅） |
| 进程数（含 GPU/网络等辅助） | 1 | 5（含 WebKit 辅助进程） |
| 安装后体积（不含游戏文件） | 67 MB | 88 MB |

【实证】达成手段：

1. **没有浏览器内核**：界面由 GPU 每帧绘制，不是 Chromium/WebView。
2. **单进程**：无 WebKit 辅助进程族。
3. **发布构建优化**：GPUI 在 CPU 上做布局/排版/绘制，未优化会慢约 13 倍
   （实测 20 行发现页 76ms/帧 → 优化后 6ms/帧）；因此连 dev 构建也把
   **依赖包**编译成 opt-level 3，自己的 crate 保持快速重编。
4. **把内存让给游戏**：导航文档写明——游戏启动后，「游戏页和项目详情连同
   不在屏幕上的图片一起释放」。
5. **隐藏即停**：设计语言 §4 要求装饰性工作「在不可见时、游戏运行时停止」。

【推断】106MB 是「物理内存 footprint（与活动监视器一致）」，非虚拟内存；
其数值优势主要来自无 WebView + 单进程，而非某种魔法分配器。

### 对 AC 的启示（不换栈）

AC 的内存大头通常是：壁纸/全景纹理、角色立绘缓存、页面与对话框常驻、QtWebEngine
插件窗口。可做的：

- **启动游戏即降载**：释放首页大图/全景缓存、隐藏页面、暂停装饰动画
  （AC 已有 `EFFECTS_ENABLED` 与 `_in_viewport` 思路，可扩展到「游戏运行中」）。
- 插件窗口（QWebEngine）**用完即销毁**，不要静默常驻。
- 为「启动器空闲内存」立一个可重复的测量脚本（进程 Private Bytes + 工作集），
  作为回归指标（AC 已有 `docs/round107_memory.md` 等记忆，可复用口径）。

---

## 4. 传输子系统：最值得抄的一层【实证】

`crates/lumilio-transfer` 的模块划分：`attempt / budget / cancel / engine / files /
http / memory / parallel / partial / pieces / request / sources / transport`，
测试覆盖 `resume / pause / pieces / parallel / budget / memory`。
它**不依赖启动器领域**，更新器也复用它。

### 4.1 来源是「提供者链」，不是布尔开关

```rust
trait SourceProvider {
    fn candidates(&self, original: &str) -> Vec<String>;
    fn maximum_concurrency(&self) -> usize { 16 }
}
struct OfficialSource;                 // 原样返回
struct PrefixMirror { official_prefix, mirror_prefix, concurrency }
struct SourceChain { providers: Vec<Arc<dyn SourceProvider>> }
```

- `SourceChain::candidates()` 把所有提供者展开、去重、去空，**顺序即优先级**。
- `preferred_concurrency()` 取第一个提供者的上限。
- 设置里只有三档偏好：`OfficialOnly` / `OfficialFirst`（默认）/ `MirrorFirst`；
  镜像规则是数据（`MirrorRule { official_prefix, mirror_prefix }`），不是代码分支。
- 下载失败时逐源记录原因；「动态」页的技术详情会写「每个试过的来源和它的原因」。

对比 AC 现状：`src/core/mirror.py` 是**对第三方库打补丁**（改 session、重写 URL、
包 `download_file`、并行 `_try_parallel_mll`、`SpeedMeter` + round-151 的 30s
watchdog）。能用，但：

- 来源顺序、每源并发、失败原因散在补丁里，UI 拿不到「这个文件试过哪些源」。
- 加一个新镜像 = 改补丁逻辑；Lumilio 加镜像 = 加一条 `MirrorRule`。

### 4.2 下载任务的状态与暂停

动态页路径文档【实证】写明：

- **暂停**：放开连接、保留已下载部分，状态「已暂停」、进度条变灰；继续从断点接上。
- **取消**：停止，已下载部分保留给下次重试；启动时清理超过 7 天的残留。
- **重试**：用当时的输入重新发起，作为**新任务**出现，旧条目保留。
- **进度单调**：进度条只前进；剩余时间在**有两次读数后**才出现。
- **仪表**：总速度 + 每格一条连接的 LED + 进行中/已暂停计数，格数 = 设置里的并发数。

Lumilio 的实现细节【实证】：`ProgressSnapshot` 拒绝倒退（`completed < previous`
直接报错）、拒绝中途改变 `total`；`ActivityEvent::Retrying { id, source, attempt }`
把「换源重试」变成 UI 可显示的一等事件。

### 4.3 AC 可落地的改造（不改第三方库也能做）

在 `src/core/` 增加一层 `transfer.py`（名字可换）：

- `SourceProvider` 协议：`candidates(url) -> list[str]`、`max_concurrency`；
  内置 `OfficialProvider`、`BMCLAPIProvider`（把现有 `mirror.py` 的 URL 重写规则搬成数据）。
- `SourceChain`：按偏好生成候选列表（官方优先 / 镜像优先 / 仅官方）。
- 每文件下载循环：候选逐个尝试；失败记录 `(source, reason)`；切换时发事件；
  成功/失败都带上「试过的源」列表。
- 现有的 30s watchdog 变成链上的一个策略（「无字节进展 → 下一个候选」），
  而不是独立线程。
- UI：下载详情里显示「来源链 + 当前源 + 已试源失败原因」。

成本 M；风险低（先并存，验证后再撤补丁）。

---

## 5. 任务模型：DAG + 事件流 + 持久化【实证】

### 5.1 结构

```
ActivityGraph (BTreeMap<id, ActivityNode>)
  ActivityNode { id, label, stage?, prerequisites: BTreeSet<id>, action: Fn(ctx) -> Future }
  validate(): 空 id / 重复 id / 缺失前置 / 环
ActivityScheduler { concurrency, broadcast::Sender<ActivityEvent> }
  run(graph, cancellation) -> ActivityReport
```

- 状态机：`Queued → Running → Succeeded / Failed / Cancelled / Blocked`；
  前置失败会把后继标成 `Blocked`（不是失败，语义更准）。
- 取消：`tokio::select!` 监听取消令牌，`abort_all()` 后把所有未完成任务标 Cancelled。
- 事件：`Registered / Started / Progress / Retrying{source, attempt} / Finished{state, detail}`。
- 报告：`ActivityReport` 按 id 汇总每条记录的状态/进度/失败详情。
- 每个节点可以带 `stage`（阶段名），UI 用它在进度条上方显示「正在做什么」。

### 5.2 「动态」页（11 条用户路径）【实证】

- 分类标签：全部 / 下载 / 安装 / 更新 / 修复。
- 行内容：名字 + 状态 + 进度条 + 已下载/总量 + 剩余时间；失败行有「重试」、
  「打开」（跳到关联游戏页）、「技术详情」。
- 展开键：每文件一行——文件名、来源、几条连接（亮几格）、进度；
  某来源失败写在那个文件下面。
- L2「清除已完成」；导航角标显示运行中数量（>99 显示 99+）。

对比 AC：`src/downloader.py` 有 `DownloadQueue`（3 并发、取消、`.part` 续传），
`src/worker.py` 有 `ProgressWorker`（mll 回调 → 信号 + 停滞提示），状态栏有全局进度
（round-151 已能点回任务对话框）。**缺的是「统一」**：

- 安装 / 修复 / 导入 / 更新各有一套对话框与回调，没有共同的任务记录；
- 没有持久化历史，关掉对话框就消失；
- 没有任务级重试、暂停（只有取消）；
- 没有「打开结果」（任务完成 → 跳到对应页面）。

### 5.3 AC 落地建议（分两步，避免一次重写）

**第一步（低风险）**：先立一个 `TaskRecord` 数据模型 + `TaskCenter` 单例：

```python
TaskRecord: id, kind(download/install/repair/update/import), label, stage,
            state, progress(completed,total), sources[], detail, target_page, created_at
```

- 现有 `DownloadQueue` / `install_instance` / 导入流程在开始/进度/结束时**上报**到 TaskCenter；
- 状态栏进度条 + round-151 的召回逻辑改为读 TaskCenter；
- 完成后记录落 `launcher_config.json` 旁边的历史文件（只留最近 N 条）。

**第二步（可选）**：活动页 UI（列表 + 分类 + 重试/打开/详情），状态栏角标。
依赖图（DAG）暂时不必做——AC 的安装流程是线性的，先上「状态机 + 事件」，
等真有并行阶段（如「下载 Java」「下载库」「下载资源」可并发）再引入。

成本：第一步 S/M，第二步 M；风险低。

---

## 6. 「能不能玩」模型：诊断纯函数 + 首页两问【实证】

### 6.1 `diagnose()` 是纯函数

输入 `Facts{ instance, has_game_folder, launchable_loaders, runtimes, java_needs,
auto_install_java, host, has_account, damaged_files, mods, max_memory_mb, last_session }`，
输出 `Vec<Problem{ severity, kind }>`，按严重级排序、同级稳定。

`ProblemKind` 清单（原文枚举）：

| 类别 | 触发条件 | 级别 |
|---|---|---|
| `GameFolderMissing` | 游戏目录被移走/删掉 | Error |
| `LoaderUnsupported` | 启动器不支持该加载器 | Error |
| `NoAccount` | 没有可用账户 | Error |
| `NoJava{required}` | 没有可运行版本，且不会自动下载 | Error |
| `JavaWillDownload{major}` | 同上，但下次启动会自动下载 | Info |
| `JavaMismatch{chosen,needed}` | 用户选的 Java 破坏硬性规则 | Warning |
| `JavaAdvice{advised,chosen_by_user}` | 能跑，但不是推荐版本 | Info |
| `NotInstalled` | 尚未安装 | Info |
| `DamagedFiles{count}` | 扫描发现缺失/损坏文件 | Warning |
| `WrongLoaderMods{names}` | 启用模组属于别的加载器 | Warning |
| `DuplicateMods{ids}` | 同一 mod id 多个启用文件 | Warning |
| `LowMemory{max_mb}` | 堆上限 < 1024MB | Warning |
| `LastSessionFailed(outcome)` | 上次崩溃/启动失败/准备失败 | Warning |
| `Finding(plugin)` | 插件（崩溃分析器）给的发现 | 由插件定 |

注意 Java 的三种情况被拆成了 Error / Warning / Info 三档——**「会自动修」与「不会自动修」
必须视觉可区分**，这是 AC 体检目前没有表达的。

### 6.2 首页只回答两问

`HomeSummary { continue_with: Option<instance_id>, needs_attention: Vec<AttentionItem> }`：

- **继续** = 最近玩过、且没有 Error 级问题的实例；「启动不了的实例不提供继续」。
- **需要留意** = 有 Warning 及以上问题的实例；按「严重级 → 最近玩过 → id」排序；
  Info（如「还没安装」）不算。
- 每个实例只显示**最严重的一条标题** + 还有几条；按钮按动作命名
  （安装 / 修复 / 更换… / 去设置 / 去添加 / 查看日志），**先打开游戏页再执行**。
- 账户问题在汇总时才注入（`with_account`），换账户不需要重新扫盘。

另有「启动前确认」两条【实证】：Java 不匹配时问一次（本次改用 / 下载 / 仍然启动 / 取消，
**只影响这一次**）；游戏目录丢失时问（作为空游戏启动 / 查看游戏 / 取消，**不悄悄启动空目录**）。
启动失败后首页给「恢复并继续」「技术详情」（准备失败给原因；启动即退出给最后 ≤50 行日志；
崩溃/异常退出/无输出 → 打开诊断页）。

### 6.3 AC 现状与差距

AC 已有 `src/core/instance_health.py`（性能模组、JVM 参数、Java、启动参数检查 + 一键修复）
和 `src/diagnostics_dialog.py`、`src/crash_analysis.py`、`src/diagnostics.py`。
差距不在「有没有检查」，而在**聚合与呈现**：

1. 体检只能从诊断对话框进，**首页看不到**；用户不点就不知道。
2. 没有「严重级 → 首页标题 + 还有几条」的聚合；问题是完整列表。
3. 没有「继续哪个」的判定：首页永远启动「当前实例」，当前实例坏了也给大按钮。
4. 没有启动前确认（Java 不匹配/目录丢失）时，失败发生在启动之后，用户看到的是错误。
5. 结果不持久化：上次崩溃只活在本次会话。

落地（P0，成本 S/M）：

- 在 `core/` 加一个 `home_summary(instances, findings)` 纯函数（照 `attention.rs`），
  返回 `continue_with` + `needs_attention`；
- 首页 hero 下方用一行一条：`游戏名 · 最严重问题 · 另有 N 条 [动作]`，
  点击先切到实例页再执行（与 round-151 的召回逻辑同源）；
- `apply_fix` 的 `fix` 描述符已存在，可直接映射成动作按钮；
- 增补 Java 三档（Error/Warning/Info）与「本次启动改用 Java」确认框。
- 验收：构造 3 个实例（正常/缺 Java/缺目录），首页显示 1 条继续 + 2 条留意，
  点击动作能跳到实例页并执行；regress 加断言。

---

## 7. 设计语言：动效与「仪器感」【实证】

### 7.1 动效 token（`theme/motion.rs` 原文值）

| token | 值 | 用途 |
|---|---|---|
| `INSTANT` | 90 ms | hover / press / focus 反馈 |
| `QUICK` | 160 ms | 路由淡入、小状态切换 |
| `SETTLE` | 280 ms | 面板、按钮→进度条之类的形变 |
| `SCENE` | 700 ms | 英雄区文案入场、大叙事变化 |
| `WORLD_TICK` | 50 ms | 世界动画帧间隔（= 游戏 20 tick/s） |
| `LIFT` | 8 px | 入场位移距离 |

规则：先复用 token 再新增；动效只表达「状态变化 / 空间连续」；进度必须反映真实工作，
**动画不许发明进度或掩盖失败**；遵守「减少动效」，关闭动效后同一状态仍可理解。

对比 AC：`docs/style-gates.md` 已规定「转场 ≤200ms、不做弹跳/过冲」，但**没有 token 表**；
`effects.py` 里时长散落（170ms 等）。建议：把 90/160/280/700 + 8px 写成
`theme.py` 的常量（`MOTION_INSTANT/QUICK/SETTLE/SCENE`、`LIFT_PX`），新代码只许引用；
顺带补一个「减少动效」开关（跟随系统或设置项），并把装饰动画门控到它。

### 7.2 视觉语法

- 主题是语义 token：`ALUMINIUM / BIRCH / DEEPSLATE / GLASS / NIGHT / TINTED_GLASS`
  + 自建主题；配色、圆角、字体、界面缩放都可换。
- 代码里提供 `contrast()` / `legible()`，**对比度是算出来的**，不是拍脑袋；
  设计文档还诚实标注「白字配亮橙键 3.55:1 是已知取舍，不等于达标」。
- 控件语言：中性表面、实体按键（有键程 `KEY_TRAVEL`）、小 LED、等宽读数、克制的
  accent；「不要为了隐喻硬加显示屏/铭牌/螺丝/卡片」。
- 字体：界面 Space Grotesk + 系统 CJK 回退；数值 JetBrains Mono；显示数字 DSEG7；
  游戏消息 Monocraft。AC 现状是 1 正文 + 数字/像素点缀，方向一致，不必换。

### 7.3 文案与交互模式

`plain-language.md` 把消息分成 7 类（动作/标题/确认/设置帮助/失败/空状态/占位），
每类给「起点」而非模板；核心纪律：**先给结果或问题；不可逆操作先写后果；
按钮写实际动作；安慰话必须对所有情况成立；不要把必要说明藏进 tooltip**。

更硬的一条【实证】：i18n 测试 `hints_fit_one_line` 约束所有 `-help` / `-note` 键
**不超过 20 个加权汉字、一句话**（英文加权 40；汉字 1、拉丁/数字/空格 0.5、占位符 1），
例外清单 `long-hints.txt` 只许缩短。这是「文案门禁可机读」的样板。

`design-patterns.md` 是 10 张模式卡（版本选择 / 加载器选择 / 内容条目 / 版本切换 /
批量 / 添加文件 / 设置组 / 确认 / 加载空错 / 图标占位），每张写「起点 + 不要做什么」，
明确「模式不是每页必须实现的全部建议」。

对比 AC：`docs/style-gates.md` 已有文案禁用词/感叹号/em dash/中英同步等**人工清单**。
可升级为**自动检查**（P1，成本 S）：
- `t()` 里 `-help`/`-note`/`-hint` 结尾的键做单行长度上限（加权算法照抄）；
- 禁用词表（赋能/极致/一站式…）扫描 zh 与 en；
- 中英键集合一致性检查（AC 已有 1412/1412 的对齐脚本，扩展成 CI/regress 断言）。

---

## 8. 工程化：流程也是一等公民【实证】

| 机制 | 做法 | 价值 |
|---|---|---|
| `justfile` 单一真源 | `just check` = build → test → clippy → fmt → rustdoc 链接；`just test-pkg <crate> <test>` 只跑相关 | 「改完必须闭环」，禁止 commit-now-fix-later |
| CI 分 job | `rust` / `plans`（计划文档） / `web`；每个 job 有 `changes` 过滤，不相关路径跳过 | 文档与代码同样被验证 |
| 计划 JSON | `.agents/plans/<slug>.json` 是权威；`just plans` 生成只读 md 与网站路线图；`plans-check` 拒绝过期 | 决策/验收/教训都留在计划里，不写 ADR/归档目录 |
| 用户路径表 | 代码里一行 `// ia[page]: 操作 | 层/组件 | 结果与反馈 [| 备注]`，`just ia` 生成 `docs/ia/paths/`，**过期就 check 失败** | 文档不会说谎：「表里每一行都有实现，没有的就是没做」 |
| 技能 | `.agents/skills/`：gpui-kit、选检查、执行计划、写测试、IA 路径、i18n、动效设计 | 把「怎么做才对」写成可加载的操作手册 |
| 归属 | 改编自 Modrinth App / HMCL 的代码在文件注释写明来源与许可证；fork 的依赖进 `forks/`，vendor 进 `vendor/` | 许可证合规，也让「向谁学」可追溯 |
| 平台细节 | Windows 子进程统一走 `background_command`（`CREATE_NO_WINDOW`），保留 stdout 捕获 | 不弹黑框，日志仍完整 |

对比 AC：AGENTS.md 已有分工、CHANGELOG round、`_` 调试脚本、PII 红线、`regress.py`。
可借的两条（不引入 Rust 工具链）：

1. **用户路径表**（P1，成本 M）：AC 页面多、状态多，靠人写文档必过时。
   可以先做「机器可读的最小版」——每个页面类里维护 `PATHS = [(操作, 结果)]`，
   由 `tools/gen_paths.py` 汇总成 `docs/ia/paths.md`，`regress.py` 检查它与
   `i18n` 键/页面类是否存在。先覆盖首页/实例页/设置页。
2. **计划 JSON 的最小版**：AC 已有 `docs/LAUNCH_MODE_DESIGN.md` 这种施工图，
   可以给每个 round 加一个 `docs/plans/round-XXX.json`（目标/验收/决策/教训），
   CHANGELOG 仍保留。不要另建 ADR 目录。

---

## 9. 更新器、条款与发布【实证 + 推断】

- `lumilio-updater` 只做「发现版本 / 校验 / 平台安装」，`polling` 与状态归 app；
  导出 `CheckResult / Relaunch / UpdateClient / UpdateRelease / UpdateRestriction`。
- 导航左侧有「重启以更新」按钮；**游戏启动中或运行时禁用**。
- 首次打开：免责声明 + Minecraft EULA（`TERMS_VERSION` 版本化，改含义就重新征询）；
  更新后首次打开：更新内容弹窗（列出本次与跳过的版本），可「全部更新日志」外链。
- 签名：作者明说「没有购买开发者证书」，官网教用户放行；这是**信任成本**，
  不是最佳实践。AC 若做自动更新，必须校验哈希/签名，别学这条。

---

## 10. 不该照搬的（避免「学歪」）

1. **重写成 Rust/GPUI**：AC 的价值在功能与交互密度，不在渲染栈。PySide6 的
   原生控件 + QSS 已足够；重写会丢掉全部既有资产与验证。
2. **单进程原生插件（in-process）**：Lumilio 的插件是编译进二进制的 Rust trait，
   权限靠 `HostContext` 收口（读/写/网络/启动事件/Discord），写文件还做
   sha256 乐观锁 + 游戏运行时拒写。AC 的 QWebEngine 扩展虽有性能代价，
   但**隔离性更好**；应加强权限清单，而不是改成同进程。
3. **AGPL-3.0-only**：直接抄代码会把 AC 拖进 AGPL。只学模型与命名，不复制实现。
4. **无签名分发 / 只 3 平台**：AC 面向 Windows 为主，别为对齐而砍平台。
5. **把 WASM 插件当既成事实**：官方文档自己说「当前不可安装、API 未定」，别跟。

---

## 11. AC 落地清单（按优先级）

> 成本：S（单文件/单函数级）、M（跨 2~4 个模块）、L（新页面/新子系统）。
> 风险指回归面与用户可见变化。

| # | 事项 | AC 现状 | 差距 | 成本 | 风险 | 优先级 | 建议 round |
|---|---|---|---|---|---|---|---|
| 1 | 首页「继续 + 需要留意」聚合 | 首页 hero + 单行修复日志；体检只在对话框 | 无聚合/无严重级/无动作跳转 | S/M | 低 | **P0** | round-152 |
| 2 | Java 三档语义 + 启动前「本次改用 Java N」确认 | `core/java.py` 有兼容判断，失败发生在启动后 | 无「会自动修 vs 不会修」表达，无启动前询问 | S | 低 | **P0** | round-152 |
| 3 | 任务中心（TaskRecord + 状态机 + 事件上报） | `DownloadQueue`/`ProgressWorker`/各对话框各管各的 | 无统一记录、无持久历史、无重试/暂停、无「打开结果」 | M | 中 | **P0** | round-153 |
| 4 | 来源链（Provider → Chain → 逐源失败记录） | `mirror.py` 补丁 + `SpeedMeter` + 30s watchdog | 来源顺序/并发/失败原因散落，UI 不可见 | M | 中 | **P1** | round-154 |
| 5 | 动效 token 化 + 减少动效开关 | `effects.py` 时长散落；style-gates 只有上限 | 无 token 表、无 reduced-motion | S | 低 | **P1** | round-152 |
| 6 | 文案门禁自动化（单行上限/禁用词/中英一致） | `style-gates.md` 人工清单；i18n 已有对齐 | 规则不可机读，靠人记 | S | 低 | **P1** | round-153 |
| 7 | 启动即降载（释放大图缓存、暂停装饰、销毁插件窗） | 有 `EFFECTS_ENABLED`/视口判断/图片缓存 | 没有「游戏运行中」全局降载策略 | S/M | 低 | **P1** | round-154 |
| 8 | 用户路径表自动生成 + regress 校验 | 无 IA 路径表 | 文档靠人写，易过时 | M | 低 | **P2** | 待排 |
| 9 | 诊断包导出（脱敏 + 版本/日志/配置摘要） | 有 `log_mask.py`、诊断对话框 | 无「一键打包给作者」 | M | 低 | **P2** | 待排 |
| 10 | 更新器 + 更新后「更新内容」弹窗 + 条款版本化 | 未核实（需先查 `updater`/版本检查现状） | 无签名更新的信任链设计 | L | 中高 | **P2** | 待评估 |
| 11 | 实例级设置继承/覆盖（预设 vs 覆盖） | 有 preset（`_eff_preset`）与实例设置 | 继承/覆盖的可见性与冲突解决不完整 | M | 中 | **P2** | 待排 |
| 12 | 任务依赖图（DAG） | 安装流程线性 | 暂无并行阶段需求 | L | 中 | **暂缓** | 等真有并行 |

**明确不做**：换 Rust/GPUI、单进程原生插件、照抄 AGPL 代码、WASM 插件框架。

---

## 12. 每条怎么验收（照 AC 现有习惯）

- 新增纯函数（`home_summary`、`source_chain`、`motion` token）→ 单元测试放
  `tools/_probe_*.py` 或 `regress.py` 断言，必须能「故意改坏后失败」。
- 首页聚合 → 构造 3 实例场景（正常 / 缺 Java / 缺目录），截图对比 + 点击动作后
  落在实例页对应位置（复用 round-151 的 `_goto_page_key`）。
- 任务中心 → 杀进程重启后，历史仍在；取消/重试各一次；状态栏点击能召回。
- 来源链 → 用本地假 HTTP 服务模拟「官方 404 / 镜像超时 / 镜像成功」，断言
  事件序列与最终来源；再跑一次 round-151 的 watchdog 用例防回归。
- 文案门禁 → 故意塞一条 21 字 help，regress 必须红。
- 降载 → 启动游戏前后各采一次内存与可见页面列表，断言大图缓存已释放、
  装饰定时器已停（不能只看代码）。

---

## 13. 参考（原文位置）

- 官网：`https://launcher.lumilio.org/`（性能数字、功能三档、下载页）
- 文档：`https://launcher.lumilio.org/docs/`（安装/使用/路线图/更新日志/贡献/开发环境）
- 源码：`https://github.com/EdwinZhanCN/LumilioCL`
  - `AGENTS.md`（不变量、验证闭环、结构、UI 约定、计划与技能）
  - `Cargo.toml`（25 crate、edition 2024、lints、dev profile 优化）
  - `crates/lumilio-core/src/lib.rs`（领域模块地图）
  - `crates/lumilio-core/src/activity/{graph,log}.rs`、`docs/ia/paths/activity.md`
  - `crates/lumilio-core/src/transfer` + `crates/lumilio-transfer/src/sources.rs`
  - `crates/lumilio-core/src/diagnostics/{problems,attention}.rs`
  - `crates/lumilio-core/src/settings/{store,tuning}.rs`
  - `crates/lumilio-plugin-api/src/{lib,plugin}.rs`
  - `crates/lumilio-ui/src/theme/{mod,motion}.rs`
  - `docs/design-language.md`、`docs/design-patterns.md`、`docs/plain-language.md`
  - `docs/ia/paths/{README,home,library,navigation,activity}.md`
  - `crates/lumilio-app/src/main.rs`、`crates/lumilio-updater/src/lib.rs`
