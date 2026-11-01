# 2026-11 启动器横评：框架 / 体积 / 实现法对比

调研对象：HMCL（Java + JavaFX）、PCL2（VB.NET + WPF）、PrismLauncher（C++/Qt6）、
Modrinth App（Tauri/Rust）、XMCL（Electron/Tauri）、BakaXL 4.0（Tauri）。
本地对照：AC Launcher（Python 3.13 + PySide6 6.11.1，src 47,096 行 / 92 模块）。

---

## 一、PySide6 能不能「不破坏框架地缩小」

### 1.1 能做与不能做

| 做法 | 可行性 | 收益 | 代价 |
|---|---|---|---|
| 不打包未用模块 + 剪掉连带插件/DLL | ✅ 已在做（spec excludes + build.py 裁剪） | 19.4 MB（Quick/Qml/Pdf/虚拟键盘等） | 零，需冒烟验证 |
| 构建后删除 ffmpeg / opengl32sw | ✅ 可做 | 再省 38 MB | ogg/flac 音效、软件 GL 回退（详见 §二） |
| 换 PyQt6（同为 Qt 绑定） | ⚠️ 可行但无意义 | ±5 MB | 全量 API 迁移（Signal/enum 差异） |
| PySide6 自编译精简版（只留 Core/Gui/Widgets） | ❌ 不现实 | 理论 ~45 MB | 需 MSVC 编 Qt + PySide6，数小时/次，后续每次升级重建 |
| Qt 静态编译 | ❌ 不建议 | 理论 25–30 MB | 需自建 Qt/PySide6；LGPL 静态链接须提供可重链接目标文件；升级成本高 |
| 换 UI 技术栈（Tauri / C# / GPUI） | ⚠️ 理论可行 | 安装包 26 MB（Modrinth）/ 67 MB（LumilioCL） | 47k 行 UI 全重写，失去无边框/亚克力/自绘能力 |

**结论：能在「不换内核」的前提下裁到约 78 MB 安装 / 27 MB 下载；再往下就必须换 UI 运行时，属于重写而非瘦身。**

### 1.2 升级 / 降级有什么用

- **升级**：拿新控件、平台修复、图像/PDF 解码器的安全修复；代价是回归成本。当前已是 6.11.1（最新线），无升级需求。
- **降级到 Qt 6.5 LTS**：Windows 上默认多媒体后端是 WMF、不捆绑 ffmpeg，可省 18 MB。但会丢掉两年的音视频/RHI/HiDPI 修复，且需全量 UI 回归。**同样省 18 MB，直接裁 ffmpeg 更快更稳**。
- **降级到 Qt 5.15**：PySide6 不支持，需回 PySide2，等于重写绑定层。不做。

---

## 二、横评：关键实现法对照

| 维度 | HMCL | PCL2 | PrismLauncher | Modrinth / XMCL | AC 现状 |
|---|---|---|---|---|---|
| 下载并发 | 全局线程池 + Semaphore，按设置 | 每文件分块多线程；源不支持 Range 自动降单线程 | NetJob，并发 6（可调） | Tauri 分支：信号量 + 断点 JSON | mll + 48 并发；单文件 Range 探测 + 回退（领先） |
| 断点续传 | ✅ Range + If-Range | ❌ 官方明确不做 | ❌ 临时文件重下 | ✅ 每 1s 落盘断点，重启恢复 | 自有下载器 ✅；**mll 安装路径 ❌** |
| 镜像策略 | 国内默认「官方→镜像」，按区域 | 官方连通 <4s 才走官方 | 不挂 BMCLAPI | 美国为主，不挂 | 镜像优先 + 健康表/冷却/慢源让位（接近 PCL） |
| 重试 | 每候选 5 次 | 403 不重试 / 429 等 10s / 内容非 JSON 也算失败 | 默认 2 次；404 不重试；429 指数退避 + Retry-After | 组级重试 | 镜像 0 次、官方 1 次；**429 未单列** |
| 卡死判定 | 超时 10s | **低速超时**（按已收字节/耗时） | 传输空闲 15s | 组级超时 | 连接/读间隔超时；**无低速判据** |
| 元数据缓存 | 内存 + 磁盘 json | 内存 | HttpMetaCache（ETag/304，libraries eternal） | SQLite | net_api 24h TTL + 离线回退（够用） |
| 磁盘共享 | libraries/assets 全局一份 + 硬链接；cache 内容寻址 | 全局 `.minecraft` | libraries/assets/java 全局一份 | content_store 内容寻址 | **仅 libraries junction**；assets 每实例一份 |
| Java 来源 | Mojang runtime | Mojang runtime | Mojang runtime | 按版本选/下载 JRE | Adoptium Temurin（覆盖更广，不匹配 Mojang 版本表） |
| 自更新 | 完整包 + RSA 签名校验 | 整包替换单 exe | 独立 updater + 全量替换 | ASAR 增量（9 MB）/ 全量 | 完整 zip + sha256 + 回滚（优于 Prism） |
| 安装体积 | 单 jar + exe（~40 MB 级） | 单 exe 4.5–5 MB | 22.8 MB | 26 MB（Tauri，依赖系统 WebView2） | 135.6 MB（可裁到 ~78 MB） |

---

## 三、我们的问题清单

### P0 — 会直接影响玩家

**P0-1 assets 没有共享，每实例重复一套**
- 证据：AC 实例目录是 `data/instances/<id>/.minecraft`（`../src/instances.py#L109-L136`），
  只有 `libraries` 做 junction（`../src/core/shared_libs.py#L1-L22`），
  `assets` 未处理。
- 后果：现代版本一个实例 assets 约 300–600 MB，装 5 个版本就多 1–3 GB。
- 对照：Prism/HMCL 的 assets 都是启动器级全局一份（按 sha1 去重）。
- 建议：复用 `shared_libs` 的成熟机制，新增 `ensure_shared_assets()`：
  `data/shared/assets` 为池，实例 `assets` 做 junction；失败则降级为真实目录。

**P0-2 版本安装（mll 路径）没有断点续传**
- 证据：mll 的 `_helper.download_file` 直接 `open(path,'wb')` + `copyfileobj`，
  中断即整文件重下；我们自己的 `net_api.download_file` / `downloader.py` 有 Range 续传，
  但**安装走的是 mll 路径**，没吃到这层能力。
- 对照：HMCL 全路径 Range 续传；XMCL 每 1s 落盘断点。
- 建议：在 `MirrorSession` 的流式响应层接管写盘（`.part` + `Range` + 完成后原子替换），
  只对 `Content-Length > 8 MB` 的文件启用，避免小文件开销。

### P1 — 体验/健壮性差距

**P1-1 没有「低速判据」**
- 现状：只有连接 5/10s、读间隔 15/30s。一条 10 KB/s 的「活着的死链」永远不超时。
- 对照：PCL2 按「已收字节/耗时」判低速并断开重试。
- 建议：`SpeedMeter` 已有，加「已收 >64 KB 且连续 8s 平均 <10 KB/s → 换源」。

**P1-2 429 与 Retry-After 未单列**
- 现状：429 落入「≥400 换源」，还会被计为源失败、可能误触发 90s 冷却。
- 对照：Prism 指数退避 + 尊重 `Retry-After`；PCL 429 等 10s 再试。
- 建议：429 单独分支：按 `Retry-After` 睡（上限 60s），不计入健康表失败。

**P1-3 200 但内容不是文件（镜像错误页）**
- 现状：只有带 sha1 的文件会被 mll 的校验抓住；无 sha1 的目标（部分 loader 安装器）
  会把 HTML 错误页写进 jar。
- 对照：PCL2 把「返回内容不是 JSON」也当失败。
- 建议：GET 响应 `Content-Type: text/html` 且 `Content-Length` 异常 → 直接换源。

**P1-4 没有实例级互斥**
- 现状：同一实例重复点安装/启动可并发进入；无锁文件。
- 对照：XMCL `instance_locks`。
- 建议：安装/补全入口加 `data/instances/<id>/.ac_install.lock`（进程退出自动清理）。

**P1-5 全量更新包（135 MB）**
- 现状：sha256 + PowerShell 回滚已具备，但每次更新下发整包。
- 对照：XMCL 只下发 9 MB 的 asar.gz。
- 建议：清单含每文件 sha256 → 客户端只下「哈希不一致」的文件，拼增量 zip。

### P2 — 收益有限，先记着

- 无 ETag/304（net_api 的 24h TTL + mll 的 sha1 跳过已覆盖主要场景）。
- 无 jar ZIP 结构校验（HMCL 有；可防「下完是坏包」）。
- 无内容寻址的 mod 去重（同 mod 多实例各一份）。
- Java 只走 Adoptium，未优先 Mojang runtime（后者与版本表严格匹配、体积更小）。

---

## 四、我们做得对 / 领先的地方

- **单文件 Range 分片**：先 `bytes=0-0` 探测、200 即回退单流续传、分块失败整体回退
  （`../src/net_api.py#L380-L455`）——比 HMCL（不分片）和 Prism（无 Range）都强。
- **来源健康表 + 冷却**：比 HMCL 的固定区域顺序更自适应，接近 PCL 的「先测官方再选源」。
- **安装失败显式报错**：两源皆失败必须抛错，避免 mll 把 404 静默吞成「安装完成」。
- **更新校验 + 回滚**：sha256 + 断言 + `.upd_bak` 回滚，强于 Prism。
- **取消链路**：在途响应 socket 中断 + 安装器子进程 + 分片线程，PCL/Prism 都做不到这么细。

---

## 五、建议施工顺序

1. `assets` 共享池（P0-1，磁盘收益最大，机制可复用现成 junction 代码）
2. mll 安装路径断点续传（P0-2，弱网收益最大）
3. 低速判据 + 429 分支（P1-1/P1-2，同一处 `mirror.py` 改动，一起做完）
4. 内容不合法检测（P1-3）
5. 实例锁（P1-4）
6. 体积瘦身（安全档 19.4 MB + LZMA 分发，另立 round）
7. 增量更新（P1-5，工作量最大，最后做）
