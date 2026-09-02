# AC Launcher 代码审查与整改报告（round-34，2026-08-13）

## 一、审查范围

- 全部 src/*.py（53 个模块）+ main.py 入口，thorough 级别逐文件阅读
- 基准：BlockHelm / PCL2 / HMCL 三个参考实现的特性矩阵（见 docs/frosted-glass-research.md 及各调研记录）

## 二、已修复（本轮 build27 包含）

| 编号 | 级别 | 问题 | 修复 |
|---|---|---|---|
| P1-1 | 功能错误 | **加载器实例二次启动降级为原版**：AC 创建 Fabric/Forge 实例 version_id 空，跳过检查只匹配基础版 json（装了 loader 必然存在）→ 二次启动用原版启动，加载器静默失效 | launch.py 按 loader 匹配 `<loader>-*-<mcver>` 的 version json（fabric-loader-0.15.11-1.20.1 / 1.20.1-forge-47.2.0）|
| P1-2 | 功能错误 | 标准布局导入实例 mc_dir 指向父目录（%APPDATA%\Roaming），游戏文件装错位置 | _base 语义统一为「游戏目录本身」：link 模式存 mc_dir（不再 dirname），mc_dir property 有 _base 直接返回 |
| P1-3 | 功能错误 | Cleanroom 安装必失败：pages_instances 读 `_build` 字段（恒空）→ loader_version 空 → install.py 缺 installer URL 抛 RuntimeError | 改读 `_installer_url` |
| P1-4 | 崩溃 | launcher_config.json 合法 JSON 但非 dict → TypeError 启动崩溃；accounts/instances 脏数据 KeyError | load_config 加 isinstance 校验；accounts/instances _load 跳过脏条目 |
| P0-1 | 崩溃 | onboarding 的 _JavaScanThread/_JavaInstallThread 绕过 _LIVE 注册，下载 Java 中关窗 → QThread destroyed → heap corruption 0xC0000374 | 两线程 run() 注册/注销 _LIVE（drain_workers 可 join）|
| P2-5 | 异常 | bgm_mode 非法值 → .index() ValueError | try/except 兜底 index=0 |
| P2-6 | 误报 | welcome 看门狗 6s 在慢机 MainWindow 构造 >6s 时误报"启动超时" | 放宽到 15s |

## 三、待整改（记录在案，按优先级）

### P1（功能错误，下轮优先）
- **P1-5 微软 token 无刷新**：access_token 过期后只能重新完整登录。需加 refresh_token 自动续期（core/auth.py 已有 refresh_token 存储，缺刷新逻辑）

### P2（隐患/健壮性）
- **P2-1** launch.py res 元组缺项传 None；ram_mb<1024 时 Xms>Xmx（UI 滑杆已挡，防御性修复）
- **P2-2** net_api.py legacyfabric/cleanroom 函数重复定义两份（646/746、698/798），合并
- **P2-3** net_api.py:204 `files[0]` 空列表 IndexError；fetch_versions `v["id"]` 缺键 KeyError
- **P2-4** settings_dialog 多处 `int(float(cfg[...]))` 对非法配置值抛异常（473/480/768/834/876）
- **线程安全** net_api 模块级 `_cache` 无锁，多 worker 并发读写 → RuntimeError
- **资源泄漏** main.py `_startup.log` 句柄全程不关
- **性能** main_window._refresh_stats 对每个实例 `f.read()` 整个 latest.log（可数百 MB）→ 应 seek 尾部
- **安全** accounts 明文存 token；java_install/easytier zipfile.extractall 未防 zip-slip；easytier 密钥上命令行
- **边界** launch.py jvm_args.split() 拆坏带引号参数

## 四、与参考实现的功能差距（需补齐/新增）

| 能力 | BlockHelm | PCL2 | HMCL | AC 现状 |
|---|---|---|---|---|
| 游戏进程生命周期管理（检测退出/强杀） | ✅ | ✅ | ✅ | ❌ 启动后丢 proc |
| 微软 refresh_token 静默续期 | ✅ | ✅ | ✅ | ❌ |
| Mod 依赖树解析（Modrinth 下载自动装依赖） | ✅ | ✅ | ✅ | ❌ 仅下载本体 |
| 整合包二次安装/升级 | ✅ | ✅ | ✅ | 仅导入 |
| 下载队列/断点续传/并发限制 | ✅ | ✅ | ✅ | ❌ 整文件重下 |
| 自动更新 | ✅ | ✅ | ✅ | ❌ |
| 联机（EasyTier）UI 主流程 | ✅ | ✅ | ✅ | 大厅占位，未接 UI |
| Java 自动下载差异校验 | ✅ | ✅ | ✅ | 有下载无校验 |
| 正版启动隔离/参数模板 | ✅ | ✅ | ✅ | ❌ |

## 五、整改依据

1. 用户 2026-08-13 指令：以 AC 为基准与三参考实现逐项对比，分类差距并实施整改；排查全部 Bug/报错/警告/隐患
2. P1-1/P1-2/P1-3 为用户可感知的功能错误（加载器失效、文件装错位、Cleanroom 必失败）→ 本轮修复
3. P0-1/P1-4 为崩溃级（关窗 heap corruption、脏配置启动崩溃）→ 本轮加固
4. P2 清单 + 功能差距矩阵 → 下一轮按优先级实施（先 token 刷新，再性能/安全）

---

# 更新记录（round-35 / round-36 / 当前）

## 已完成 ✅（build28 / build29）

| 原编号 | 级别 | 问题 | 修复（版本） |
|---|---|---|---|
| P1-5 | 功能 | 微软 token 无刷新 | ✅ build28：core/auth.refresh_microsoft（refresh_token→XBL→XSTS→MC 全链）+ accounts.refresh_current_silently + 启动后台 Worker 触发 |
| P2-2 | 维护 | net_api 重复定义 | ✅ build28：删除 642-735 死代码块 |
| P2-3 | 异常 | files[0] IndexError | ✅ build28：空 files 抛 NetError |
| 线程安全 | 并发 | _cache 无锁 | ✅ build28：_CACHE_LOCK |
| 性能 | 隐患 | _refresh_stats 读整个 log | ✅ build28：seek 尾部读 20KB |
| 边界 | 隐患 | jvm_args.split 拆坏引号 | ✅ build28：shlex.split + 降级 |
| 新增 | 功能 | 游戏进程生命周期 | ✅ build28：_track_game_process/_poll_game（2s 轮询退出提示）+ kill_game（taskkill /F /T） |
| 新增 | 性能 | net_api 磁盘缓存路径每次 mkdtemp 不一致 | ✅ build28：模块级缓存 _CACHE_DISK_PATH |
| 安全 | 隐患 | 账户 token 明文存储 | ✅ build29：DPAPI 加密（win_dpapi.py），dpapi: 前缀，旧数据自动迁移 |
| 安全 | 隐患 | zip-slip（java_install/easytier extractall） | ✅ build29：safe_extract_zip 越界条目拒绝 |
| 资源 | 隐患 | _startup.log 句柄不关 | ✅ build29：app.exec() 后 close |

## 剩余待办（round-37 起，轴心/边缘排序）

### 🎯 轴心（日常使用核心，优先做）
1. **Mod 依赖树解析**（Modrinth 下载自动拉依赖）——Mods 页核心体验，对齐 BlockHelm/PCL2/HMCL
2. **下载队列/断点续传/并发限制**——下载核心体验（当前整文件重下）
3. **游戏进程 kill UI 入口**——底层已就绪（kill_game），缺实例卡/诊断页按钮

### 🗂 中轴（提升体验）
4. 整合包二次安装/升级
5. 版本列表 fetch_versions `v["id"]` 缺键 KeyError 容错

### ⚪ 边缘（低频）
6. 自动更新机制
7. EasyTier 联机 UI 主流程
8. 正版启动隔离/参数模板管理

### 已知剩余 P2（小，随改随修）
- P2-1 launch.py res 元组缺项传 None / ram<1024 Xms>Xmx
- P2-4 settings_dialog int(float()) 非法值（473/480/768/834/876）
- P2-7 微信：easytier 密钥上命令行（进程列表可见）
