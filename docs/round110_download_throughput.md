# round-110 记忆：下载测速 + 大文件分片并行（+下载诊断日志）

> 日期：2026-10-18。提交：`652a51c`。承接用户实测反馈「下载怎么这么慢，而且看不到速度」，
> 以及随后的追问「为什么我 PCL-CE 的路线快到 10MB 左右（整合包）」。

## 背景：用户实测的两句话

用户在真机跑 round-109 包之后给出两个具体的感受：

1. **「下载怎么这么慢」** —— 同一个整合包，PCL-CE 能跑到 ~10MB/s，AC 只有零点几 MB/s；
2. **「而且看不到速度」** —— 对话框只有按「文件个数」走的进度条，既没有 KB/s，也没有已下载字节数，
   所以「慢」和「卡住」在 UI 上无法区分，用户也没有任何可自证的依据。

第二句是这一轮真正的入口：**没有速度显示，就等于无法证伪任何猜测**。所以本轮先补可观测量，再补吞吐。

## 诊断证据（本轮实测，均在该用户机器/网络上）

| 观测 | 结果 |
|---|---|
| `bmclapi2.bangbang93.com/libraries/...` | **403 Cloudflare 拦截页**（2 跳，~1.5s） |
| `bmclapi2.bangbang93.com/maven/...` | 同样 403 |
| `bmclapi2.bangbang93.com/assets/<hash>` | 200（1 跳，8140 B） |
| `bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json` | 200（2 跳） |
| Mojang `lwjgl-3.3.1.jar` | 724243 B / 2.75s = **0.26 MB/s** |
| BMCLAPI client jar | 3 MB / 8.56s = **0.37 MB/s** |
| `Mojang → mirror` 链路 | 3.03s = BMCLAPI 403 白试 + 回退 Mojang → **每个库都白试一次** |

关键前提：`download_mirror` 默认值是 **`"bmclapi"`**（`settings_dialog.py:123`），零状态包因此**默认走镜像**，
而镜像对 `libraries` 路径当前完全失效 —— 于是「每个库文件先白试一次镜像再回退官方源」，时间直接翻倍。

但这也解释了用户的第一句为什么主要不是镜像问题：**整合包**下载的是 CDN 上的 mod 文件，不走 Mojang 主机，
所以「慢」的主因不在镜像，而在下载引擎本身。

## 根因：单连接 vs 多线程分片

这是我们和 PCL 的结构性差异。

单条 TCP 连接的实际吞吐 ≈ 窗口 / RTT，跨境 / 跨运营商链路上常常只有 0.3~1 MB/s —— 上面的实测
（0.26 / 0.37 MB/s）正好落在这个区间。而整合包恰好是「**少数超大文件**」的组合（主包本身、客户端 jar、若干大 mod），
单文件单连接就会直接顶死在这个上限上。

| | AC（本轮之前） | PCL-CE |
|---|---|---|
| 单个大文件 | 1 条连接 | 切成 N 段、N 条连接并行（HTTP Range） |
| 文件间并发 | 4（上限 8） | 更高 |
| 整合包主文件 | 单连接 | 分片多线程 |
| 峰值 ≈ | 并发数 × 单连接速度 | 链路带宽上限 |

代码层面的对应事实：

* `net_api.download_file` 用 `session.get(url, stream=True)` 单流；
* `BatchDownloader`（整合包导入 / 资源队列）`workers=4`（上限 8），且**每个文件内部仍是单连接**；
* mll 的 `_helper.download_file` 同样是单连接，并发只发生在**文件与文件之间**（`install.py` 的 `ThreadPoolExecutor`）；
* **我们其实已经有** `net_api.parallel_download_file`（HTTP Range 分片、默认 `min(ncpu, 8)` 线程），
  但它此前只服务于 OptiFine / LiteLoader / Cleanroom 的安装器 jar —— **整合包主文件与包内 mod 完全没走它**。

## 本轮改动（10 文件）

| 文件 | 改动 |
|---|---|
| `src/net_api.py` | D 主体：`download_file` 先探测远端大小，**≥8MB 自动改走 `parallel_download_file`**；三条护栏（防递归 / 续传优先 / 拿不到长度即单流）；`_active_meter()` 让分片线程也能喂速度计量 |
| `src/batch_download.py` | 并发上限 `8 → 16` |
| `src/modpack_import.py` | 整合包导入 `workers=4 → 8` |
| `src/core/mirror.py` | A 计量：`SpeedMeter` + `_CountingRaw` 响应包裹 + `active_meter()` / `note_bytes()`；B 镜像按主机失效闩锁；C `set_diag` + `_diag_log` |
| `src/worker.py` | A 显示：`ProgressWorker.speed` 信号 + `_speed_loop()` 轮询 + `_speed_text()` / `_fmt_bytes()` |
| `src/launch_dialog.py` | 进度对话框新增速度行 `speed_lbl` + `set_speed()` |
| `src/main_window.py` | 状态栏新增速度标签 `_speed_lbl` + `_set_speed()`，并接上两处 `ProgressWorker` |
| `src/core/install.py` | `_diag_enabled()`；`install_instance` / `install_mrpack` / `repair_minecraft_dir` 三处均 `set_diag(...)` |
| `src/settings_dialog.py` | 默认值新增 `download_diag_log: False`；网络页新增「记录下载诊断日志」开关与回写 |
| `src/i18n.py` | 新增 4 键 × zh/en（`dl.speed` / `dl.speed_idle` / `settings.dl_diag` / `settings.dl_diag_hint`） |

### A 速度可见（先解决「看不到」）

mll 的回调**只有文件计数**（`setMax` / `setProgress`），拿不到字节数 —— 所以速度只能在**传输层**按响应字节记账。

* `_CountingRaw` 包住响应的 `raw`：mll 的 `_helper.download_file` 用 `shutil.copyfileobj(r.raw, f)` 落盘，
  全程只调 `raw.read`，包一层即可拿到真实吞吐而不改动任何下载逻辑；其余属性（`decode_content` 等）原样透传。
* `SpeedMeter` 按滑动时间窗（默认 5s）估算 B/s，窗口外样本丢弃 —— 一次挂死（长时间无新字节）会让速度**自然归零**，
  不靠假时间戳假装在动。
* 自建下载（`download_file` / `parallel_download_file`）在 chunk 落盘处喂同一口径，所以「mll 下载」与「自建下载」
  共用一套速度定义。

**踩到并修掉的一个真坑**：`install_scope()` 的 `_SCOPE` 是 `threading.local()`，而 `parallel_download_file` 的
`_tick` 跑在 `ThreadPoolExecutor` 的工作线程里 —— 那些线程没有安装上下文，`active_context()` 返回 `None`，
计量器收到的字节数是 **0**（离线测试第一轮直接暴露了这一点）。修法是：**在调用线程先取到计量器再传进去**
（`active_meter()` → 闭包捕获 → `_tick` 直接用），因为线程池工作线程拿不到 thread-local。

`bytes_per_second` 在样本跨度 < 0.75s 或窗口内无样本时返回 `0.0` —— 宁可不显示速度，也不显示一个虚高的数字。

### B 镜像按主机失效（此处**偏离了原计划做法**）

原计划是「安装开始时探测一次镜像，不可用则本次安装整体关闭主机重写」。**实际实现改成了请求级、按主机的失效闩锁**：

* 某主机在镜像上返回 **401 / 403 / 406** → 把该主机记进本次安装的 `ctx.mirror_dead`，后续该主机请求**直连官方源**；
* `_rewrite()` 在每个请求里跳过已失效主机。

改法的理由：

1. **不必硬编码一条可能过期的探测 URL**（探测需要一条「健康时必然 200」的库路径，这种路径是脆的）；
2. **不多发任何请求**；
3. **404 不闩锁整台主机** —— `libraries` 的 404 可能只是个别文件未同步，逐文件回退即可，不足以判定整台主机失效；
4. **能保住 `assets` 继续走镜像** —— 实测 `/assets` 是 200（1 跳、比官方快），开局「整体关闭」做不到这个区分；
   按主机闩锁可以「`libraries` 走官方、`assets` 继续走镜像」；
5. 代价只有**第一个库文件上那一次 403**（~1.5s），而不是每个文件都白试一次。

### C 下载诊断日志（可开关，默认关）

`set_diag(True)` 后，每次请求写一行到 `data/logs/download.log`：
`时间 status 耗时 声明字节 mirror|direct 原始URL`。用于回答「慢 / 卡住到底卡在哪一跳」。
设置页网络分类下新增「记录下载诊断日志」开关（默认关闭），并有 hint 说明。
`install_instance` / `install_mrpack` / `repair_minecraft_dir` 三处入口都从配置读取并 `set_diag(...)`。

### D 大文件自动分片（提速的主体）

`download_file` 流程改为：先 `_remote_size()` 探一次远端总长（`Range: bytes=0-0`，顺带确认服务器支持 206 分段），
**≥ `_PARALLEL_MIN_BYTES`（8MB）** 就交给 `parallel_download_file`，否则原样单流。

三条护栏，缺一不可：

1. **防递归**：`parallel_download_file` 内部的单流回退路径一律传 `_allow_parallel=False`（4 处），
   否则会出现「单流 → 分片 → 单流 → 分片」的递归；
2. **续传优先**：若 `dest + ".part"` 已存在，**不分片**，直接走单流以保住断点续传（分片路径会重建 `.part`，
   不继承已有进度）；这条能避免「为了加速而丢掉用户已有的下载进度」；
3. **拿不到长度就单流**：探测失败 / 服务器不支持分段（非 206）时返回 `False`，走原来的单流。

## 验证

* `python -m compileall -q src main.py` → **exit 0**
* i18n parity：**zh 1287 / en 1287，零单边键**（round-109 为 1283，本轮 +4）
* **离线引擎测试 16 项全 PASS**（`%TEMP%` 临时脚本，不入库）：本地起一个支持 Range 的 HTTP 服务器，
  - 20MB 文件确实走了 **4 次分片请求**（1 次探测 + 分片），落盘 MD5 与源一致，计量器总数字节正确；
  - 512KB 小文件**只发一次探测**、不分片，计量器总数正确；
  - `_allow_parallel=False` 时 20MB 文件**纯单流**、零 Range 请求（防递归护栏生效）；
  - 已有 1MB `.part` 时**只发 1 次 Range 请求**且最终 MD5 正确（续传优先生效）；
  - `SpeedMeter` 单测：累计值正确、有数据时 bps > 0、**停滞后自动归零**。
* **离线镜像/日志测试 15 项全 PASS**：`libraries` → 镜像、`assets` → 镜像、非 Mojang 透传、镜像关闭即官方；
  403 闩锁该主机、**404 不闩锁**、无 status 不闩锁、无安装上下文时仍能重写；
  `_CountingRaw` 逐次 read 上报、透传读返回空；日志开关门控与追加。
* **离屏冒烟 11 项全 PASS**：主窗速度标签存在且默认隐藏、`_set_speed` 显示/收起；设置页能构建出
  「记录下载诊断日志」复选框；进度对话框速度行隐藏/显示；`ProgressWorker` 用真实计量器驱动，
  产出 `10.8 MB/s · 已下载 11.0 MB` 这样的速度行并正确 `finished`。
* 离屏 teardown 退出码 `0xC0000409 (-1073740791)` 为**既存问题**（HEAD 亦可复现），与本轮无关，判定以 stdout 为准。

## 设计取舍

* **每次 `download_file` 多一次极小的探测请求**：小文件一发（探到 <8MB 就单流），大文件两发
  （自己的探测 + 分片内部再探一次）。这是「先知道大小再决定要不要分片」的代价 ——
  换来的是小文件不付分片开销、大文件必然并行。分片路径 16MB 一块，实际请求数很少。
* **阈值 8MB**：低于它的文件交给文件级并发（`BatchDownloader` 8~16 路）处理，高于它的少数大文件交给分片。
  这个分工正好对应「整合包 = 少数超大文件」的形状。
* **嵌套并发**：8 个批次 worker × 每文件最多 8 分片 → 瞬时峰值可能到 ~64 条连接。
  对下载管理器属正常量级且是瞬态的；若真机实测发现过猛，调低 `_PARALLEL_MIN_BYTES` 或分片线程数即可。
* **`_PARALLEL_MIN_BYTES` 与 `_RETRIES` 均为模块常量**：便于真机数据出来后一次性调整。

## 待办 / 未做

* **真机目检**：进度对话框速度行、状态栏速度标签、设置页「记录下载诊断日志」开关的排版 ——
  离屏无字体，文字渲染为 tofu，只能验结构与配色。
* **真机实测一次整合包**：确认「慢」确实被改善、速度行数值合理（不与系统下载器差一个量级）；
  同时观察嵌套连接数是否过猛。
* **mll 自持的游戏文件路径仍是单连接**：客户端 jar / 运行时等由 mll 下载的大文件本轮**未接入分片**
  （要在 `_helper.download_file` 层包裹，需同时兼顾 sha1 校验与 mll 的 callback 协议，风险显著高于本轮范围）。
  若真机显示客户端 jar 仍是瓶颈，再单开一轮处理。
* `src/pages_browse.py` 的资源中心 store 整合包下载走的是裸 `Worker`（无进度、无速度），
  本轮只让它拿到了「大文件自动分片」的提速，**没有给它加进度/速度 UI**；如需再补一轮。
