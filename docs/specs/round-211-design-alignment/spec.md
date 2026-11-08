# round-211 — 整体设计比对（8 域 × 上游源码）

> **决策来源**：主理人 2026-11-08「先 c/p，然后整体设计比对一下，一起干了」。
> **性质**：`56452d2` 之后、全启动器**设计层**对齐度盘点；不是再找一遍 bug，
> 不重复 `round-208-store-alignment/spec.md` §2 的 12 条资源中心细节。
> **证据口径**：上游 `repo:path:line` 相对 `_scratch/upstream/src/<repo>/`（57 文件快照，
> tree SHA 见 round-208 §0.1）；AC `file:line` 相对仓库根。**没读过的一律标「未核实」**，
> AC 自调研转述（`docs/launcher_comparison_2026-11.md`）**不算上游源码证据**。
> **判定**：已对齐 / 部分对齐 / 结构性偏离 / 故意的 1% / 未核实。

## 0. 证据边界（诚实登记）

本地快照 = **资源中心 / 下载 / 整合包单域**：`hmcl` 9、`prism` 25、`pclce` 23 文件，
全部落在 `modplatform/`、`ui/download/`、`ui/instances/`、`Pages/PageDownload/Comp/`、
`PCL.Launcher.Core/Comp/`、`PCL.Core/…/Cache/`。因此 **域 1–4 有上游硬证据；
域 5–8 上游侧整体「未核实」** —— 不是「上游没有」，是快照零覆盖。本轮不联网补写
行号（取当前 main/develop 与 §0.1 固定 tree SHA 行号不可复现，宁缺勿造）。
AC 侧 8 域均实读。补齐方向（推测路径，不构成证据）：
`prism:launcher/minecraft/launch/*`、`prism:launcher/accounts/*`、
`hmcl:HMCL/…/setting/*`、`pclce:PCL.Core/Minecraft/*`。

---

## 1. 八域对照矩阵

| 域 | 设计维度 | 上游（`repo:path:line` + 要点） | AC（`file:line`） | 判定 |
|---|---|---|---|---|
| 1 IA | 主页面 / 全局栈 | 未核实（快照无 MainWindow；仅见下载域 6 tab：`hmcl:…/ui/download/DownloadPage.java:119-126`） | `src/main_window.py:100-104` `STACK_INDEX` 8 固定页 + `FEATURE_BASE_INDEX=8`；`:1939-1997` 全局 `QStackedWidget`，`:4123` 惰性 `_ensure_page` | 未核实 |
| 1 IA | 页内子栈 | `hmcl:…/DownloadPage.java:71-72` tab 切换独立于 sidebar；`prism:…/ResourceDownloadDialog.cpp:319-336` 分页容器跨页同步 `searchTerm` | `src/pages_browse.py:563-565` 列表↔详情 `_stack`；`:1137-1164` `_open_detail/_close_detail` | 部分对齐（层级不同） |
| 1 IA | 侧栏 | `hmcl:…/DownloadPage.java:132-140` `startCategory("GAME"/"CONTENT")` 分组挂 tab | `src/main_window.py:82-93` `NAV_GROUPS` 分组侧栏 | **已对齐** |
| 1 IA | 详情形态 | `prism:…/ResourcePage.ui:29-62` QSplitter 三栏同屏；`pclce:…/PageDownloadCompDetail.xaml:8-9` 独立详情页 | `src/pages_browse.py:563-565,1137-1164` 整页切换不新开窗口 | **故意的 1%**（round-208 §4 拍板 B） |
| 1 IA | 返回语义 | `hmcl:…/DownloadPage.java:242-291` `DownloadNavigator implements Navigation`（`onPrev/onNext/canPrev`）；`prism:…/ResourceDownloadDialog.cpp:319-336` 换页灌上一页搜索词 | `src/main_window.py:4483` `_show_page` 直接 `setCurrent` 无历史栈；`src/pages_browse.py:1156` 手动切回 | **结构性偏离** |
| 2 实例 | 元数据 | `prism:…/ResourceDownloadDialog.cpp:57,66` 强类型 `MinecraftInstance*`；`:259-262` `getPackProfile()->getComponentVersion("net.minecraft")` | `src/instances.py:37` `Instance` + `:108-148` 四种目录布局 + `:453` `detect_format`；`src/core/instance_marker.py:43-180` 指纹 | 部分对齐（无组件版本对象） |
| 2 实例 | 版本隔离 | `hmcl:…/DownloadPage.java:335` `shouldIsolateNewInstance(modded)`；`:349-351` builder 显式 `enableIsolation()` | `src/instances.py:108-109` 靠目录形状推断；`src/launch.py:112` `resolve_game_dir` | 部分对齐 |
| 2 实例 | 共享池 | 未核实（快照零覆盖；旧横评文档 P0-1「assets 未共享」**已过时**） | `src/core/shared_libs.py:30-31` libraries + assets 双池；`:213` `should_use_shared_pool` | 未核实 |
| 2 实例 | 备份模型 | `hmcl:…/ui/instances/ModListPage.java:320-327` `rollback(from,to)`；`:884-894` `getOldFiles()` **mod 文件级**回滚 | `src/core/backup.py:1-13,32-86` **整实例快照** + manifest（round-210 起带事务） | **结构性偏离**（粒度不同） |
| 3 资源 | 平台接口抽象 | `prism:…/ResourceAPI.h:56-57,108-143` 纯虚接口 + 统一 `SearchArgs`；`hmcl:…/LocalizedRemoteAddonRepository.java:22,27` 装饰器叠中文层 | `src/store_search.py:221` `search_store_source(source,…)` 字符串分支；`src/net_api.py:703,761` 散函数 | **结构性偏离** |
| 3 资源 | 依赖解析模型 | `pclce:…/ModDependencyResolver.cs:52-57,81-151` 三态 + `MaxDepth=32` + visited + 兼容判定；`prism:…/ResourceDownloadDialog.cpp:356-369` 统一任务 | `src/net_api.py:1005-1022` 递归；另有 `src/core/mod_repair.py:118`、`src/crash_analysis.py:463` 第二套 | 部分对齐（无统一三态） |
| 3 资源 | 元数据缓存归属 | `pclce:…/FileCache.cs:12-28` **按 projectId** 缓存整份文件列表 | `src/net_api.py:134` `_cached` 通用 TTL；`src/store_search.py:134` `cache_lookup` 另一套 | **结构性偏离**（两套无收口） |
| 3 资源 | 中文搜索 / 默认源 | `hmcl:…/LocalizedRemoteAddonRepository.java:42-43,49-57` 名库反查 ≤3 英文名；`pclce:…/ProjectRequest.cs:10-14` CF 中文需替代词 | `src/net_api.py:1445-1449,1463` MCIM 公益镜像（无官方 CF key）；`src/store_search.py:151,170-172` | **故意的 1%** |
| 4 下载 | 队列 / 任务契约 | `hmcl:…/DownloadPage.java:172-184` `Task.composeAsync` + `Controllers.taskDialog`；`prism:…/ResourceAPI.h:70-75` `Callback<T>` `onSucceed/onFail/onAbort` | `src/downloader.py:41,78` `DownloadQueue`；`src/core/task_center.py:103`；`src/core/dl_gate.py:59-91` 实例级互斥 | 部分对齐 |
| 4 下载 | 分片 / 断点 / 校验 | 未核实（快照不含下载器；`pclce:…/HttpCacheHandler.cs:66-76` 只是 304 复用） | `src/net_api.py:350,406` `:285-302` `.part`+Range，`:334-345` `expected_sha1`（round-210 已加固 206 校验）；`src/batch_download.py:52-68` | 未核实 |
| 4 下载 | 失败回退 / 候选源 | `hmcl:…/DownloadPage.java:173` `getDownloadCandidates`；`pclce:…/ProjectQuery.cs:654-658` 单源失败不拖死另一源 | `src/core/transfer.py:63-72,87,114-130` `SourceChain`；`src/core/mirror.py:172,233-240` 健康表/冷却 | 部分对齐 |
| 4 下载 | HTTP 缓存层次 | `pclce:…/HttpCacheHandler.cs:14,23-99` `DelegatingHandler` 统一 ETag/304/TTL（`:101-115` 默认 5 分钟） | `src/net_api.py:134-159` 纯 TTL + `_stale`；`src/store_search.py:134` 另一套 | 部分对齐（缺条件请求） |
| 5 启动 | classpath / JVM / 进程 | 未核实 | `src/launch.py:5-6,505` 外包给 mll；`:532,540,562` 事后补检；`:630` `launch_process`；`src/core/last_session.py:53` | 未核实 |
| 6 认证 | 身份 / 凭据 / 刷新 | 未核实 | `src/accounts.py:33-51` `launch_identity`；`:109-119` 落盘；`src/core/auth.py` OAuth 链（round-210 修 client_id） | 未核实 |
| 7 设置 | 配置 / 主题 / 语言 | 未核实 | `src/settings_dialog.py:246,274`；`src/theme.py:266,1334`；`src/i18n.py:39,4339,4350` | 未核实 |
| 8 更新 | 签名 / 自替换 / 诊断 | 未核实 | `src/core/update_trust.py:11,337,425` Ed25519 + sha256；`src/core/update_install.py:193`（round-210 加验证）；`src/crash_analysis.py:260` | 未核实 |

---

## 2. A. 结构性差距 Top 5（不改分层补不上）

1. **资源平台无「每源一个实现」的接口层** — `prism:…/ResourceAPI.h:56-57,108-143` / `hmcl:…/LocalizedRemoteAddonRepository.java:22,27` 是接口 + 装饰器；AC `src/store_search.py:221` 按 `source` 字符串分支，加第三源只能继续加 `if`。
   *切口*：`src/store_search.py:221` 抽 `StoreSource` 协议（`search/versions/dependencies/categories`），cf/mr 拆成注册实现，`:302 search_store_page` 遍历注册表（不动 UI）。
2. **无统一导航 / 返回栈** — `hmcl:…/DownloadPage.java:242-291` `Navigation` 契约；AC `src/main_window.py:4483` 直接切、`src/pages_browse.py:1156` 手动切回，跨页状态各页自传。
   *切口*：`src/main_window.py:4483` 增 `_nav_history` + `back()`，`_close_detail` 改调 `back()`，惰性构建不变。
3. **HTTP / 元数据缓存两套、无管道收口** — `pclce:…/HttpCacheHandler.cs:14,23-99` 管道层；AC 两套缓存键口径不同。
   *切口*：`src/net_api.py:134` 收口为单一 `HttpCache`，`src/store_search.py:134` 委托并保留 `("stale", old)` 出参。
4. **实例是「目录约定 + 路径拼接」，不是拥有资源列表的对象** — `prism:…/ResourceDownloadDialog.cpp:259-286,380-389`；AC `src/instances.py:37`。
   *切口*：`Instance.resource_lists() -> dict[type,path]`，`src/pages_browse.py:601 _target()` 直接消费。
5. **依赖解析有实现、无统一结果模型** — `pclce:…/ModDependencyResolver.cs:52-57,81-151`；AC 下载时与崩溃修复时两套。
   *切口*：`src/net_api.py:1022` 返回三态 dataclass，`src/core/mod_repair.py:118` 消费同一结果。

> 域 5–8 上游侧未核实，不列入 Top 5（避免拿 AC 自调研转述冒充上游证据）。
> **这 5 条属架构改造，本轮不动**，只登记为技术债；本轮「一起干了」的范围见 §5。

## 3. B. 故意的 1%（勿「对齐」掉）

| # | 偏离 | 证据 | 理由 |
|---|---|---|---|
| B1 | 中文优先 + 中英对称门禁，不复制上游翻译串 | `src/i18n.py:3-9,39,4339,4350` | 上游各有翻译表，AC 需自有门禁保键对称 |
| B2 | PC 单平台（Windows-only） | `src/win_dpapi.py:11`；`src/core/shared_libs.py:77` `mklink /J`；`src/core/update_install.py:305` PowerShell | 不移植 Qt/C++/Java 跨平台层 |
| B3 | 离线可用 | `src/net_api.py:148-149,730-732`；`src/login_dialog.py:621`；`src/batch_download.py:9-10` | 无网 / 正版不可用时仍能启动 |
| B4 | 无外部遥测 | 全仓 Grep `telemetry/sentry/umeng/analytics` 无外部上报命中；`src/aclive.py:12` 仅 `AC_LIVE=1` 本地调试口 | 不为「像上游」引入埋点（Grep 未见，非全量行为审计） |
| B5 | 便携目录 | `src/paths.py:9,26-27,35-38`；`src/core/backup.py:3` | data/config/backups 与 exe 并列，不写注册表 |
| B6 | 公益镜像 + 默认双源 | `src/net_api.py:1445-1449,1463`；`src/store_search.py:151,170-172` | round-140 拍板，不悄悄换后端 |
| B7 | 详情整页切换 / 不静默收窄搜索 | `src/pages_browse.py:563-565,601` vs `prism:…/ModFilterWidget.cpp:259-262` 上游会预填实例版本 | round-208 拍板 B + round-209：静默收窄让 FTB 整批消失 |
| B8 | 沿用 `Worker`/`TrackedThread`/`ImageLoader` | `src/downloader.py:41` | 不移植上游线程模型 |

## 4. C. 上游自己也有坑（99% 参考 ≠ 照抄）

1. `prism:…/ResourceModel.h:137-139` — `// HACK: … leaks a tiny bit of memory per time the user has opened a resource dialog. How to make this better?` 配 `static QHash<ResourceModel*, bool>`：上游自认泄漏且自问无解。
2. `prism:…/flame/FlameAPI.cpp:405` — `// edge case: mod has installed for forge but the instance is fabric => fabric version will be prioritizated on update`：上游自认混合加载器更新会选错优先级。
3. `hmcl:…/LocalizedRemoteAddonRepository.java:56,89` — `:56` `if (count >= 3) break;` 硬编码只取 3 个中文反查；`:89` 用**英文反查结果**的 `totalPages` 冒充中文搜索总页数，中文分页天然不准。
4. `pclce:…/FileCache.cs:82` — `pageSize=10000` 一次拉完项目文件列表，无分页无上限保护。
5. `pclce:…/ProjectQuery.cs:691-755` — `_ScoreProjectResults` 本地重排 + `:750-752` 按来源硬编码权重（Mod CF=1 / MR=7），与 round-208 §2.3 采纳的「服务端排序下推」**正好相反**：上游三家自己就不一致，99% 对齐必须选一家口径。
6. `hmcl:…/ModListPage.java:564` — `// Do we need to search in the background thread?` 自留疑问，`:565-576` 主线程线性过滤全部 mod。

> **结论**：99% 参考 = 复刻可观测行为与架构决策（接口层、状态机、分页契约、失败回退），
> 不是把 HACK、硬编码常量、自认 edge case 与自相矛盾的排序口径一起搬过来。

---

## 5. 本轮「一起干了」的范围与不做的边界

按 `docs/quality_punchlist.md` §16.7 剩余第 3 / 5 / 6 批，只做**判据明确、不改产品语义、
不撞既有契约**的项；落地清单与逐条判据写进 `CHANGELOG.md` round-211 与 §十八。

| 批次 | 本轮做 | 本轮不做（原因） |
|---|---|---|
| 3 资源中心 | 未知总数空页收敛、缓存/请求 key 补语言与隐藏已装、迟到回调按 `(gen,key)` 丢弃并写回状态、SWR signet 不再让 fresh 恒真、假断言换行为判据、IA 护栏补到 8 页 | A 节 1/3/5 三条架构改造（接口层 / 缓存收口 / 三态依赖模型） |
| 5 隐私合规 | 加密失败拒绝明文 + 原子写、脱敏多形态、敏感键单一清单、条款/README 文案对齐实际域名 | 翻译服务 / authlib 后台更新 / 开机自动拉皮肤是否改「显式触发」= 产品决策 |
| 6 历史项 | classpath 基准、ProgressWorker 终态、CF 依赖树、弹窗收敛 3 处、教程 `reject()` 单点 | 缺库秒退是否记 `degraded`、启动前缺前置是否拦截、Java 四套判据一次性统一、`save_config` merge-on-write（4 份快照 + 5 套测试钉住，牵一发动全身） |

> 产品拍板项在 §十八单列，不替主理人决定。
