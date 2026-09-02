# AC Launcher 更新日志

## v1.0.4-beta（2026-08-30）— 日志打码 · 非 ASCII 路径警告（round-70/71）

### 🛡 round-71 日志打码（借鉴 PCL-CE `McLogFilter.cs`）

* 新增 `src/log_mask.py`：`mask_launch_text()` 在**展示层**统一打码——启动参数段 `accessToken xxx`、当前登录 token、Windows 用户名，均保留**首尾各 5 位**中间 `*` 替换；磁盘日志原样保留，崩溃分析不受影响

* 控制台页 `set_game()` 接收登录 token，tail 日志时逐块打码后显示；崩溃分析证据 `detail` 构建时同样过打码，防分享截图/日志时泄漏凭证

* 修复 `_mask_access_token` 单段 token 尾部日志被重复拼接的缺陷（冒烟测试捕获）

### ⚠ round-71 非 ASCII 路径警告（借鉴 PCL-CE McLaunchPrecheck）

* 启动预检新增「游戏目录含非 ASCII 字符（如中文）→ 启动前给一次提示」：只警告不拦截，启动失败时把原因指向路径；设置 → 加载器 → 「非 ASCII 路径警告」开关可关闭（对齐 PCL-CE「不再提示」语义），配置 `warn_non_ascii_path`（默认开）

* 补齐 `settings.warn_non_ascii_path(_hint)` 中英键值，i18n 审计中英对称

### 📚 round-70 ModDownload.cs 下载引擎 · 崩溃分析模块深挖（PCL-CE 源码）

* 抓取 PCL-CE 关键源码至 `<workspace>\_PCLCE\`（`ModDownload.cs`、`FileDownloader.cs`、`LoaderDownload.cs`、`ModBase.cs`、`CrashAnalysis/` 29 文件）

* 下载引擎要点：多阶段 Loader 权重流水线 + 官方 URL `.Replace` 生成镜像源按序切换 + 临时文件后缀下载原子移动 + `FileChecker` 哈希按长度自动判型（MD5/SHA1/SHA256）+ 精确/最小 size + JSON 结构校验

* 崩溃分析要点：Collect→Prepare→Analyze→Output 四步管道、按文件名前缀分类日志、Fatal→Primary→Secondary 三阶段规则短路、46 种稳定 `CrashCause` 枚举映射本地化建议

* 详细对照见 `2026-08-30_PCL-CE下载引擎与崩溃分析深挖.md`

### 🔍 验证

* 冒烟测试：log\_mask 单/多段 token、用户名、无敏感文本全通过

* `_diag_all.py` 18 脚本 + i18n 审计（ZH\_NOT\_EN/EN\_NOT\_ZH 为空）全部 exit=0；全量编译 0 错误

## v1.0.4-beta（2026-08-30）— Quilt 加载器 · 设置简化 · 进程优先级（round-68/69）

### ✨ round-68 Quilt 加载器

* 新建实例页新增 **Quilt** 加载器卡片与版本获取（`minecraft_launcher_lib` 的 Quilt 分支，`stable_only=True` 只列稳定版）

* 设置 → 加载器 → **「显示 Quilt 加载器」开关**（对齐 PCL-CE 的隐藏加载器思路）：关闭后 `_compatible_loaders` 与新建实例卡片同时过滤，不残留入口

### 🎛 设置简化（round-68）

* 设置页由三分区（快速设置/Java/高级设置）合并为**两分区：设置 / Java 管理**；原「快速设置」+「高级设置」纵向合并进「设置」滚动页，Java 单独成区（对齐 PCL-CE「Java 归游戏分区」的分类）

### ⚡ round-69 进程优先级

* 新增「进程优先级」下拉：标准 / 高 / 实时，写入 `process_priority` 配置

* `launch._priority_bits()` 用 Windows 原生 `CREATE_HIGH_PRIORITY_CLASS`(0x80) / `CREATE_REALTIME_PRIORITY_CLASS`(0x100) 与 `CREATE_NO_WINDOW` 按位或，随 creationflags 一次性生效，**零新增依赖**（不引入 psutil）

### ✨ round-62\~67 汇总补录

* 资源中心详情页（全部版本列表 + 按 MC 版本过滤 + 谷歌翻译中文说明，24h 缓存）

* 设置页滚轮误调预防；版本列表 24h 缓存 + 主窗口构建时后台预取提速

* Logo 页精简（去背景/文字，保留 AC 字母动画）；音乐播放/暂停按钮图标随状态切换

* 联机大厅工具选择器（无联机插件时引导 Terracotta/EasyTier/MCTier）；MC 像素字体 Logo 与 Splash 动画

* 修复：崩溃分析对话框缺 QWidget 导入、设置页未改动误弹保存、导航布局被硬编码篡改、启动窗口闪现与首次启动假死、authlib 配置原子写、退出后命令未执行、版本页加载缓慢等

### 🔍 验证

* `_diag_priority.py`（位映射/下拉/脏检测/creationflags 4 项）+ `_diag_quilt_tmp.py`（两分区/开关/过滤/兼容列表/版本分支 5 项）新增并通过

* `_diag_all.py` 16 脚本 + i18n 审计（ZH\_NOT\_EN/EN\_NOT\_ZH 为空）全部 exit=0；全量编译 0 错误

## v1.0.3-beta（2026-08-30）— 性能优化（round-61）

### ⚡ 性能

* **流光卡视口裁剪**：`QScrollArea` 里滚出屏幕的卡片此前虽 `isVisible()=True`，仍每帧触发一次被裁剪掉的光栅化。现在按 `visibleRegion()` 判定，只有真正可见的卡片才推进动画（浏览页/实例列表滚动时 CPU 显著下降），滚回来自动续播

* **动态壁纸随可见性暂停**：GIF/视频壁纸在页面被切走、窗口最小化时暂停解码（`QMovie.setPaused` / `QMediaPlayer.pause`），回到页面/还原窗口自动恢复，避免后台白跑 CPU

* 修复进程退出时流光卡析构触发 `hideEvent → _stop_master()` 访问已销毁 QTimer 的 RuntimeError

### 🔍 验证

* 全量编译 0 错误；离屏功能验证（壁纸无媒体静默通过、滚动视口掩码正确）；`_diag_all.py` 全量回归 11 脚本 + i18n 审计全部 exit=0

## v1.0.2-beta（2026-08-30）— 启动高级设置（对齐 PCL2）+ 玻璃拟态 + 拖拽修复

### ✨ 新增：启动高级设置（round-55，对齐 PCL2「启动游戏 / 版本设置」）

* **游戏附加参数**：全局默认 + 实例级覆盖，追加到游戏启动参数末尾；支持 `--server <ip>` / `--port` 服务器直连（自动解析并交给 minecraft-launcher-lib 注入）

* **JVM 参数预设**：三档下拉（默认不注入 / Aikar GC 优化 / 自定义），替换原 Aikars 单勾选框；旧配置 `jvm_aikars=true` 自动映射到 `aikar`，不丢用户选择

* **版本隔离**：默认共享 / 版本隔离（`versions/<版本>/`）/ 自定义目录三选项，经 `gameDirectory` 下发，实例级可覆盖全局

* **启动后 / 退出后命令**：`run_hook_cmd` 异步 `Popen` 执行（失败静默），游戏退出时自动补跑退出钩子

### ✨ 体验

* **窗口拖拽修复**：无边框 + Acrylic 透底下 `startSystemMove` 失效，改为「原生优先 + 手动移动兜底」双机制（标题栏 + 主窗口统一）

* **玻璃拟态（毛玻璃）**：Acrylic 透底 + 半透明卡片 `bg_frost`，全局/实例设置界面统一升级

* **版本页图标**：MC 风格 3D 等距方块（按区块纹理合成）

* **authlib 自动更新**：后台线程检查 GitHub 最新版，原子替换 jar，失败静默回退

* **渲染器选择 + 实验性 GC 性能选项**：实例级 `auto/software/legacy` 渲染器 + G1GC 优化组/禁显式 GC

### 🔍 验证

* 编译 0 错误；i18n 审计中英对称、模板变量全匹配；`_diag_launch/_diag_settings/_diag_exit/_diag_backup/_diag_shared` 等回归脚本全部通过

* 功能单测：`--server` 解析（含 `=` 写法）、版本隔离三种目录解析、Aikar 参数注入均 PASS

## v1.0.1-beta（2026-08-03）— 导入体验修复

### 🛠️ 修复

* **复制导入进度条**：扫描导入选"复制到本启动器"时显示实时进度（文件级 + 当前文件名），可随时取消；取消则停止导入，不再静默回退为接管

* **导入后立即刷新**：主页 / 实例页扫描导入完成后，主页实例卡、实例列表、模组页实例选择器一次性全部刷新——之前只有当前页刷新，导入的实例要等切页才出现

* **主页"刷新列表"按钮修复**：之前点击必抛异常（HomePage 缺 inst\_mgr 引用），现在正常重读磁盘列表

* **主页"扫描接管"修复**：对话框关闭后的成就检查之前会抛 AttributeError 导致主页不刷新

* **新建实例顺序调整**：先选游戏版本 → 再选加载器 → Java（与主流启动器一致；加载器兼容性依赖版本）

* **一键导入全部**：支持中途取消（复制到一半点取消即中断，不再继续导后面的实例）

### 🔍 自检（不变）

* 10 项检查：依赖 / 数据目录 / 配置 / 账户 / 外置登录 / 资源文件 / Java / 游戏文件 / 网络连通性 / 界面状态（双页预警）

### ⚠️ 已知问题（Beta 1.1）

* 偶发"双页"视觉问题仍在排查（自检"界面状态"可检测是否实例重复）

* PCL2 实例目录结构与标准 MC 不同，启动可能触发多余下载（独立跟进中）

* 启动崩溃（窗口消失）个案在排查，可能与 PCL2 实例或新建实例连点有关

## v1.0.0-beta（2026-08-03）— 首个公开测试版

### ✨ 核心功能

* **跨启动器实例接管**：扫描并导入 MultiMC / Prism / HMCL / PCL2 / 官方启动器的游戏实例（复制或接管）

* **实例管理**：新建 / 导入 / 删除 / 设置当前实例，游戏版本 + 加载器（Fabric / Forge / Quilt / NeoForge 等 9 种）选择

* **版本安装**：浏览并安装 Minecraft 版本（官方 / BMCLAPI 镜像源）

* **模组管理**：按实例管理 .jar 模组（启用 / 禁用 / 删除 / 添加）

* **启动游戏**：微软账户登录（Azure OAuth）/ 离线模式，自动选 Java、注入 Authlib-Injector（外置登录）

* **统御面板**：已接管实例数 / 来源启动器数 / 待修复实例一目了然

### 🛠️ 修复（本轮 20+ 项）

* **单实例锁**：双击 exe 或进程残留不再开第二个实例（消灭"双页/双进程"）

* **切页动画移除**：不再出现页面半透明叠加的"重影双页"

* **实例页空状态**：重写为 toggle 可见性方案，不再堆叠双卡片

* **"新建实例"按钮**：修复 LOADERS 元组解包崩溃（之前点击无反应）

* **"新建实例"按钮文字**：去掉文案中多余的"+"（避免"++"）

* **首页重建优化**：语言未变时跳过全量重建，欢迎页加载提速

* **模组页快速交互**：同步删除 + 重入保护，不再崩溃

* **SSL 修复**：exe 旁加载 libssl/libcrypto，资源中心 HTTPS 正常

* **欢迎页（Onboarding）**：样式应用延迟，不阻塞响应

### 🔍 新增：内置自检（诊断）

* 10 项检查：依赖 / 数据目录 / 配置 / 账户 / 外置登录 / 资源文件 / Java / 游戏文件 / **网络连通性** / **界面状态（双页预警）**

* 入口：左侧"工具"区 → 诊断，或 设置 → 诊断

### ⚠️ 已知问题（Beta 1）

* 偶发"双页"视觉问题仍在排查（自检"界面状态"可检测是否实例重复）

* 欢迎页初次加载仍偏慢（已部分优化）

* 微软登录需在 Azure 配置回环重定向地址

### 🖥️ 环境

* Windows 10/11 x64

* 需要 Java 8+（自动检测，可用自带 Java 或系统 Java）

