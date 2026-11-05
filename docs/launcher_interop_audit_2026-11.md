# 2026-11 横向实现审计：AC Launcher vs 主流启动器

> 审计阶段为只读（未改实现）；2026-11-05 晚用户授权「动手」后，**三条 P0 已按本报告修复**，
> P1/P2 仍只登记未动。审查对象为当前工作区（含未提交的 round-175 批次与上一轮 P0 修复）。
> 与 `quality_punchlist.md` 第五章互补：那一轮查「AC 主路径 vs 外来实例分支」的内部一致性，
> 本轮查「AC vs 业界标准实现」。修复记录见文末「P0 修复落地」。

## 尺子与方法

| 类别 | 对照来源 |
|---|---|
| 启动器实现 | Mojang 官方 Launcher、Prism Launcher（C++/Qt, GPL）、HMCL（Java, GPL）、PCL2、MultiMC/Prism 实例格式 |
| 协议规范 | authlib-injector 官方 README「部署」节、Modrinth API 官方 User-Agent 条款、Microsoft device-code → XBL → XSTS → Minecraft profile 链路、Yggdrasil wiki.vg |
| 本地基准 | 仓库内 `minecraft-launcher-lib 8.0`（venv 与 `dist_beta` 内副本逐字节一致）——AC 把版本 json 解析与命令行构造**整体委托**给它，因此「库行为 + AC 传入的 options」二者合起来才是真实实现 |

方法：静态逐行核对 + 对 3 条 P0 做临时目录运行时复现（不写仓库文件）。

**运行时复现结果（2026-11-05）**
- 用真实 profile 结构 `{"id","name":"WuXing","access_token":"MCTOKEN","type":"microsoft"}` 调
  `build_options(account.get("username"), account.get("uuid"), account.get("token"))`
  → `username='Player' | uuid='' | token=''`。
- 构造 `neoforge-21.1.0` 版本 json 调 `find_installed_loader()` → `NameError: name 'json' is not defined`。
- 用 AC 的 LiteLoader 子 json 走 mll `inherit_json()` → 合并后
  `minecraftArguments='--tweakClass ...'`（父串被整体覆盖），且 `jar` 键不存在。

---

## P0 — 与业界标准直接冲突，功能不可用

| 位置 | 问题描述 | 影响范围 | 改进方向 |
|---|---|---|---|
| `src/launch.py:869-872`<br>`src/main_window.py:1808`<br>`src/accounts.py:106-116` | **账号字段错位**。业界/官方要求 `--username` 取 profile `name`、`--uuid` 取 `id`、`--accessToken` 取 `access_token`。AC 的 `AccountsManager.current()` 产出 `{id, name, access_token, type}`，启动却读 `username/uuid/token`；全仓只有 `main_window.py:146` 的 `OFFLINE_ACCOUNT` 常量恰好有这三个键。无任何归一化映射。 | **所有已登录账号**（微软正版 / 离线 / 外置）：游戏恒以 `Player` + 空 UUID + 空 token 启动；正版服、Realms、聊天签名、皮肤、白名单全失效，且不报错。未登录时走 `OFFLINE_ACCOUNT` 反而正常，掩盖了问题。 | `launch_instance` 入口归一化 `username = acc.get("name") or acc.get("username")`、`uuid = acc.get("id") or acc.get("uuid")`、`token = acc.get("access_token") or acc.get("token")`；统一账号存储键名；`main_window.py:5009` 的 `_game_token` 同步取真实 token。 |
| `src/core/install.py:274-275` | **模块缺 `import json`**。文件头只有 `os/shutil/minecraft_launcher_lib`，`json` 只在 432/453/512 行做函数内局部导入；`data = json.load(f)` 直接抛 NameError，`except (OSError, ValueError)` 抓不到。 | id 不含 MC 版本号的加载器实例（NeoForge 1.21+ `neoforge-21.1.0`、Cleanroom `Cleanroom-0.7.x`）：`launch.py:675` 裸调 → 启动直接失败；`instance_health.py:184` 同路径被 `_safe` 吞掉 → 体检静默漏检。 | 顶部补 `import json`（或复用本文件 430 行 `_safe_json`），异常白名单扩到 `NameError`；并给 `launch.py:675` 加兜底。 |
| `src/core/install.py:482-492` | **手写 LiteLoader 版本 json 破坏继承**。业界要求子 json 的 `minecraftArguments` = 父版本**完整**参数串 + `--tweakClass`，并写 `"jar": "<原版版本>"`。AC 只写 `"--tweakClass ..."`；mll `_helper.py:189-190` 对标量整体覆盖，且因无 `jar` 会去拼 `<id>.jar`（不存在）。 | 全部 LiteLoader 实例（MC ≤1.12.2）：`--username/--version/--gameDir/--assetsDir/--assetIndex/--uuid/--accessToken` 全丢，classpath 缺 client jar → 秒退。 | 生成前读父 `<mc>.json` 的 `minecraftArguments` 拼接后追加 tweakClass，补 `"jar": mc_version`；或改用 `arguments` 结构让数组继承后追加。 |

## P0 修复落地（2026-11-05，用户授权「动手」）

| 原问题 | 修法 | 行为判据 |
|---|---|---|
| 账号字段错位 | `src/accounts.py` 新增 `launch_identity(account)` 单一归一化入口，兼容 profile 三键与旧三键；`src/launch.py` 组装 options 前调用；`src/main_window.py` 的 `_game_token`（日志打码）与皮肤拉取的 uuid 同步改用归一化结果 | 真实微软 profile → `build_options` 收到 `WuXing / <真实UUID> / MCTOKEN`；`OFFLINE_ACCOUNT` 旧三键保持原样 |
| `install.py` 缺 `import json` | 模块顶部补 `import json`（`find_installed_loader` 的 `json.load` 与全文件 5 处 `json.dump` 共用） | 临时目录构造 `neoforge-21.1.0` + `inheritsFrom`，`find_installed_loader` 返回该 id，不再抛 NameError |
| LiteLoader 子 json 破坏继承 | 生成前读父 `<mc>.json` 的完整 `minecraftArguments`，追加 `--tweakClass`，并显式写 `"jar": mc_version`；父串读不到时抛 `RuntimeError` 而不是静默造一个必然秒退的 json（失败可见） | 真实调用 `install_liteloader` → mll `inherit_json` 合并后父参数全部保留，`get_libraries` 的 classpath 指向 `versions/1.12.2/1.12.2.jar` |

改动文件：`src/accounts.py`、`src/launch.py`、`src/main_window.py`、`src/core/install.py`；
新增 `tests/test_interop_p0_fixes.py`（23 项静态 + 行为判据）并登记进 `regress.py`。
验证：`python regress.py` → **38/38 exit 0**；全页面构造冒烟、共享 assets 去重、
mll 断点续传等原有套件均照常通过。

**刻意未动的相邻项**：离线账号当前拿到的是 12 位内部 id（非空但非规范 UUID），
合法 `OfflinePlayer:<name>` UUID v3 仍属 P1；本轮只解除「空凭证」这一 P0。

## P1 — 与主流实现不一致，功能缺失或可靠性风险

| 位置 | 问题描述 | 影响范围 | 改进方向 |
|---|---|---|---|
| `src/core/auth.py:273-290,316-346`<br>`src/accounts.py:141-163`<br>`src/skin_dialog.py:564` | 微软 token **无 `expires_at`、启动前无过期检查/刷新**：`expires_in` 只用于 device-code 轮询；静默刷新唯一调用点是皮肤上传返回 401。刷新还硬编码内置 `client_id`，玩家自建 Azure 应用时必然失败，且 `except Exception: return None` 全吞。HMCL/Prism 均保存过期时间并在启动前用 refresh_token 续期。 | 所有微软正版账号：token 过期后用失效凭据启动，正版服/皮肤/签名静默失效，无重新登录提示。 | profile 写 `expires_at`；`_handle_play` 启动前检查并刷新；`refresh_microsoft` 接收登录时的 `client_id`；失败区分「网络暂失败」与「需重新登录」并回报 UI。 |
| `src/login_dialog.py:617-622`<br>`src/accounts.py:106-116` | 离线账号 `"uuid": ""`。主流启动器一律用 `uuid3(NAMESPACE, "OfflinePlayer:"+name)` 生成稳定 UUID，且不伪造正版凭据。 | 离线多人服白名单/OP、存档归属、UUID 相关 Mod 异常，改名/重启身份漂移。 | 新增 `offline_uuid(name)`（UUID v3，按版本 json 要求转无横线格式），登录时写入 profile 并持久化。 |
| `src/launch.py:288-318` | **authlib-injector javaagent 参数形式错误**。官方 README 部署节明写 `-javaagent:{jar}={验证服务器 URL (API 地址)}`；HMCL/PCL2/Prism 都直接传 API 根 URL。AC 传的是本地 `authlib-injector-config.json` **文件路径**，且自造 `authServer/sessionServer/servicesServer` 三键不是官方 API metadata 结构。 | 全部外置登录：agent 无法解析参数，外置认证失效（叠加 P0 账号字段错位，实际完全不可用）。 | `=account["server"]`（API 根 URL）直接传；需要离线 metadata 时另走官方预取机制，不要自造配置。 |
| `src/core/authlib.py:69-95,174-176` | 注入 JVM 的 javaagent 二进制**校验不对称**：固定版有 `AUTHLIB_SHA256`，但自动更新只验「合法 zip + ≥60KB」；`ensure_authlib` 见到 `.version` 文件即跳过全部校验直接返回本地 jar。与本项目 `update_trust.py` 的 Ed25519 fail-closed 强度相差极大。 | 启用外置登录的所有用户：CDN 投毒 / 中间人替换 / 本地写入任意 zip 都会被当 javaagent 加载，等同任意代码执行。 | 更新包走发布方签名清单（复用 Ed25519 公钥体系）或按版本校验官方 checksum；删除 `.version` 旁路，每次校验已存 jar 的 hash。 |
| `src/launch.py:226-235`<br>mll `command.py:229-234` | `logging.client` 配置永不生效：mll 仅当 `enableLoggingConfig=True` 才注入 `-Dlog4j.configurationFile=`，AC 的 `build_options` 从不设置；而 mll 安装期已把 `assets/log_configs/<id>` 下载好，文件在却不用。官方/HMCL/Prism 对 1.12~1.18 一律注入。 | MC 1.12~1.18.x 全部实例：缺 log4j2 配置（含 log4shell 缓解与日志格式），崩溃堆栈缺失，连带削弱 `launch.py:1078` 的 `classify_exit`。 | `opts["enableLoggingConfig"] = True`；调用前校验 `assets/log_configs/<logging.client.file.id>` 存在，缺失按 `url/sha1` 补下；无 `logging` 字段的老版本跳过。 |
| `src/launch.py:1064` ↔ `:231,817` | 游戏进程 `cwd` 固定 `inst.mc_dir`，而注入 mll 的 `gameDirectory` 是 `resolve_game_dir()` 的结果；业界要求二者一致（`logs/`、`crash-reports/`、相对路径资源写入同一目录）。`post_launch_cmd` 的 cwd 同样未统一。 | 所有开启「版本隔离 / 自定义游戏目录」的实例：日志与崩溃报告写进共享根，玩家/崩溃分析找不到。 | 改 `launch_process(cmd, game_dir, ...)`；hook 命令 cwd 同步。 |
| `src/launch.py:944-971` | 启动前补库**绕开 `downloads.artifact`**：自己用相对路径拼 `https://libraries.minecraft.net/...`，无 sha1/size 校验，仅以「响应体 >1000 字节」判定有效，HTML 错误页会被当 jar 落盘；失败仍走 `:1002` 宽容启动。业界按 version json 的 `artifact.url/path/sha1/size` 与 `classifiers` 下载复核。 | 外来完整客户端（PCL2/HMCL 导入）classpath 缺库时：假 jar 污染 classpath、私有仓库库永远补不回、后续静默失败。 | 从合并后 json 取 artifact 元数据，校验 sha1+size 后 `os.replace` 原子落盘；无 artifact 时按 `url` 仓库 + maven 坐标构造；校验失败不写文件、不 `missing.remove`，明确报错。 |
| `src/net_api.py:321,875-894,1363-1422` | 自有下载器只比 `Content-Length`，**丢弃 Modrinth `hashes.sha1/sha512` 与 CurseForge `hashes`/`fileLength`**；`download_file` 接口连 `sha1=` 参数都不存在。（mll 路径与 mrpack 已正确验 sha1，问题只在资源中心链路。） | 资源中心全部 Mod / CF 整合包 mod：CDN 投毒、截断、缓存串味会静默装入损坏或恶意 jar。 | `download_file` 增 `sha1/sha512/expected_size`，边下边算并落盘前复核，不符删 `.part` 换源。 |
| `src/scan.py:462-497`<br>`src/core/instance_rebuild.py:176-220`<br>`src/modpack_import.py:340-351` | MultiMC/Prism 导入**丢弃 `patches/*.json` 与 `instance.cfg` 大部分字段**：只读 `mmc-pack.json` 的 `net.minecraft` + loader uid/version 和 cfg 的 `name/IntendedVersion`；`instance.cfg` 的 `JavaPath/JvmArgs/OverrideJava.../iconKey`、patches 的 `+tweakers/libraries/mavenFiles` 全不迁移。文件夹导入更只按 `mods/` 里第一个 jar 名猜加载器（`:369-381`）。 | 所有从 Prism/MultiMC/PCL-CE/HMCL 导入的实例：加载器版本、Java、JVM 参数、图标、tweaker 丢失；`needs_convert` 标记后按默认版本重装（与上一轮 P1「死字段」同源）。 | 新增 `parse_patches()` 合并 tweakers/libraries/mavenFiles；把 cfg 的 Java/JVM/图标字段映射到 `Instance`；`reconstruct` 按 components 精确安装 loader 版本。 |
| mll `command.py:60`<br>`src/launch.py:869-891` | `${user_type}` 被 mll 无条件替换成 `msa`，AC 不按账号类型覆盖；也不注入 1.19+ 所需的 `--xuid`/`--clientId`。主流启动器按 `msa/mojang/legacy` 映射并携带 XSTS xui 信息。 | 离线/外置账号身份类型错标；正版账号现代版本聊天签名/Realms 相关能力异常。 | 按 `account["type"]` 映射 userType；保存 XSTS 的 `xid` 并在 `get_command` 后做参数后置修补（补 `--xuid`、清理残留 `${...}`）。 |
| `src/accounts.py:86-103` | `accounts.json` 直写目标文件，无 tmp+`os.replace`、无锁、无 schema；而 `instances.py:679-684`、`settings_dialog.py:235-240` 已用原子写 + schema。UI 线程与 `skin_dialog.py:564` 的 Worker 线程会并发读写。 | 写盘中断/并发覆盖产生半截 JSON → 全部账号（含加密 token）丢失。 | 复用 instances 的原子写 + `schema`，加 `RLock` 保护读改写序列。 |

## P2 — 规范细节 / 可维护性

| 位置 | 问题描述 | 影响范围 | 改进方向 |
|---|---|---|---|
| `src/net_api.py:46` | `_HEADERS = {"User-Agent": "MC-Launcher/0.1 (local dev)"}`。Modrinth API 官方条款**强制**唯一可识别 UA（`github_username/project/version (contact)`），泛化 UA 会被提高封禁概率；CF 也要求标识来源。 | 全部 Modrinth/CF 搜索、版本、下载请求，随时可能被限流/403。 | 改 `AC-Launcher/{APP_VERSION} (+项目地址)`，两平台可分别配置。 |
| `src/core/java.py:220,258-266`<br>`src/launch.py:710-712` | Java 兼容只读 `javaVersion.majorVersion`，用硬编码 `JAVA_MAX_OK` 连续区间与版本 ID 正则推断；不沿 `inheritsFrom` 回溯父 json，不认加载器/整合包 patch 里的离散 `compatibleJavaMajors` 集合。HMCL 用 `JavaVersionConstraint` 分强制/建议约束，Prism 有 `OverrideJavaLocation` + 兼容开关。 | NeoForge/Fabric/整合包自定义 json、无 `javaVersion` 的加载器子 json、新快照：误拒兼容 Java 或放行不兼容高版本（`InaccessibleObjectException` 类崩溃）。 | 解析成允许集合判定；沿继承链找第一个含 javaVersion 的父 json；ID 推断只作最后兜底。（与上一轮 P1「Java 四套判据」合并处理。） |
| `src/launch.py:404-408`<br>`src/core/shared_libs.py:149-210` | `assets/virtual/legacy` 从不生成。mll `command.py:65` 把 `${game_assets}` 展开到该路径，安装期却只写 `assets/indexes/<id>.json` + `objects`；全仓无虚拟目录生成代码。 | version json 含 `${game_assets}` 的老版本（1.6.x~1.12.2，含大量 1.7.10 模组包）：声音/语言/材质静默缺失。 | 按 asset index 的 objects 虚路径生成 copy/硬链接到 `assets/virtual/legacy`；共享池模式下按版本生成映射。 |
| `requirements.txt:3`<br>`src/launch.py:404-408` | `minecraft-launcher-lib` **未锁版本**，却把 rules / 继承 / logging / processors / 模板展开全部委托给它。当前 venv 与打包副本都是 8.0，但重建环境会装最新版，`enableLoggingConfig`、`${quickPlay...}`、`${user_type}=msa` 等行为均版本相关。 | 全新安装、重建 venv、打包机：库升级可让启动行为静默漂移。 | 固定 `==8.0` 或明确区间；把 rules/继承/模板解析收进自有模块，mll 只负责下载。 |
| `src/launch.py:662-681`<br>`src/core/instance_health.py:144-208` | 完整性判定只查 `<id>.json` 是否存在即 `_skip=True`，不校验 client jar / 每库 sha1 / assetIndex+objects / log_configs / Forge processors 产物。业界（Prism `ComponentUpdateTask`、HMCL `checkGameCompletionAsync`）启动前逐项校验修复。 | json 在但依赖损坏时跳过修复，游戏内静默异常；体检给不出结论。（与上一轮 P1「补库失败仍标成功」同源。） | 以 mll 安装器的 sha1 清单或自有清单为 `_skip` 与体检基线。 |
| `src/core/auth.py:349-350,389-395` | Yggdrasil `clientToken` 每次随机生成且不落盘，profile 不返回它；全仓无 `refresh/validate/invalidate` 调用。wiki.vg 协议要求续期/登出复用同一 clientToken。 | 外置登录 token 失效只能重新输密码，无法静默续期与安全登出。 | 持久化 clientToken（纳入加密字段），实现启动前 `validate/refresh` 与登出 `invalidate`。 |

## 已核对：AC 做对 / 由 mll 正确覆盖（不列为问题）

- natives 的 `${arch}` 替换与 `extract.exclude` 排除（mll `natives.py:29,46-61`）。
- Forge ≥1.13 的 `processors/data/sides`（mll `_forge.py:61-113`，经 `install.py:216-223` 调用，未漏跑）。
- 两套参数体系 `minecraftArguments` 与 `arguments.game/jvm` 的主流模板变量（mll `command.py:45-73`）。
- 安装期 `downloads.artifact` 的 `url/path/sha1`、assetIndex/objects、mrpack sha1（mll `install.py:86-90,119-132`；`mrpack.py:130`）。
- 共享池去重、单文件 Range 分片、来源健康表、更新 Ed25519 信任链 + 回滚、取消真正在途响应与安装器子进程——这几项**强于** Prism/HMCL 的常见实现，见 `docs/launcher_comparison_2026-11.md` 第四节。

## 建议施工顺序

1. ~~**P0 三条**：账号字段归一化 → `install.py` 补 import → LiteLoader json 生成~~ → **已完成**（见「P0 修复落地」），返工从这里之后开始。
2. **认证链路一起修**：token 过期/刷新 + client_id、离线 UUID、authlib javaagent 参数与 jar 校验（这四条互相叠加，分开修验证不出来）。
3. **下载完整性**：net_api hash 复核 + UA；补库改走 artifact 元数据。
4. **渐进项**：实例导入 patches、logging/clientId/cwd、Java 集合判据、依赖锁版本。

## 审计边界与状态

- 审计阶段只读；随后按用户授权**只修了三条 P0**，P1/P2 一行未动。
- 工作区仍有上一轮（第五章）P0 修复 + TRAE 的 round-175 批次 + 本轮修复；**未 commit / 未 push**。
- 未跑真机启动；P0 结论来自临时目录运行时复现，P1/P2 为静态核对 + 官方规范条文比对。
- 修复后验证：`python regress.py` → 38/38 exit 0（含新增 23 项横向审计回归）。
- 仓库内没有第三方启动器源码，横向对照依据是公开实现文档/规范与 mll 8.0 实际行为，不是逐仓库源码 diff。
