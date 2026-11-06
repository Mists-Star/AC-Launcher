# 质量开放项清单（punch list）

> round-112 建立。目的：让「哪些地方没做好」的判断**有据可依、可跨会话追**，
> 而不是每次靠临场感觉。
>
> 配套入口：[`regress.py`](../regress.py) —— 一条命令跑完所有自检。

## 一、判定框架：什么算「没做好」

按可证伪性从强到弱排——**越靠前越该先修**：

| 级别 | 判定信号 | 典型例子 |
|---|---|---|
| **P0 功能错** | 真跑一遍结果与声称不符；崩溃 / 数据错 / 逻辑反了 | 成就页幽灵卡片叠画；设置页 `is_dirty()` 恒真 |
| **P1 布局/可见** | 截图能看出重叠、裁切、对比度不足、节奏不一致 | 分组标题被卡片压住（本轮已修） |
| **P2 声称未接通** | 文档/CHANGELOG 说有，实测没有或返回空 | `_diag_all.py` 从未入库却写在发布清单里 |
| **P3 一致性** | 同类控件/文案/行为不统一，但不影响可用 | 网格单卡占半宽、双卡占满宽 |
| **P4 卫生** | 死代码、未使用导入、命名 | 30 个文件未使用导入、11 个死函数 |

**反过来说，以下几种不算「没做好」，别误判：**

- 真死路做了**诚实降级**（如离线无联机层 → 明确提示，不假装能用）
- 命中通用清单但属**本项目全站惯例**（design-review skill 铁律 1：惯例 > 清单）
- 程序化导航导致的表象（如离屏截图里侧栏高亮不跟随——用户点击时正常）
- 解释器 teardown 退出码非 0（round-107 记录的既存问题，测试内容其实全过）

## 二、返工循环

```
改代码
  └─> python regress.py            # 11 项自检，exit 0 才继续
        ├─ 编译 / i18n 对称 / PII 门禁
        ├─ 功能冒烟（配置、体检、模组、崩溃、Java、成就、主题）
        ├─ 构造冒烟（MainWindow + 11 页 + 8 对话框）
        └─ 各批次回归（脏检测 / mll 分片 / 进度桥接 / 默认值审计）
  └─> python regress.py --shots    # 视觉：截图到 _shots_r112/ 后自己看图审
  └─> 把新发现按上表分级写进本文件（级别 / 位置 / 问题 / 修法 / 状态）
  └─> 修完再跑一遍，直到 exit 0
```

**跨会话记忆靠本文件**，不靠聊天上下文——每次开工先读它。

被测脚本在 **`tests/`**（受版本控制），`regress.py` 是唯一入口。
新增回归脚本请放进 `tests/` 并登记到 `regress.py` 的 `SUITES`——
**别再写成 `_` 开头**（`.gitignore` 的 `_*` 规则会把它挡在仓库外）。

⚠️ **例外：PII 门禁（`_pii_gate.py`）故意留在仓库根、受 `.gitignore` 忽略。**
因为它内部必须写出真实 PII 字面量（如**本机用户目录** / **仓库根路径** /
**个人邮箱** …）才能检测它们——一旦入库就等于把 PII 又写回
公开仓库。所以它是**本机专属工具**，不随仓库分发；`regress.py` 找不到它会
跳过（显示为 SKIP）而不是判失败。新机器上若要做脱敏门禁，需按
`notes/ac-launcher/` 下的规则文件本地重建一份。

## 三、当前开放项

| 级别 | 位置 | 问题 | 修法 | 状态 |
|---|---|---|---|---|
| ~~P2~~ | ~~`RELEASE_1.0.0_CHECKLIST.md`~~ | ~~发布阻塞项写着「`_diag_all.py` 全部 exit=0」，但该脚本**从未入库**（`git log --all -- _diag_all.py` 为空）——回归套件此前不存在~~ | **已解决**（round-112）：清单引用已改为 `regress.py`（原句保留为历史说明）；回归入口 11 项全绿 | ✅ 完成 |
| ~~P2~~ | ~~`.gitignore` `_*` 规则~~ | ~~回归测试脚本全被忽略，换机/重 clone 就没了~~ | **已解决**（round-112）：脚本迁到受控的 `tests/`，`.gitignore` 加注说明别再写 `_` 开头 | ✅ 完成 |
| ~~P3~~ | ~~`achievements_page.py` 网格~~ | ~~单卡分区的卡片只占左半宽，双卡分区占满宽——同一网格两种节奏~~ | **已解决**（round-120）：单数分区最后一张卡跨两列 | ✅ 完成 |
| ~~P3~~ | ~~`pages_instances.py` 实例「路径」行~~ | ~~文字对比度偏低（截图中 `D:` 后几乎看不清）~~ | **已解决**（round-120）：路径改 `text_main`，live 真机截图可读 | ✅ 完成 |
| ~~P1~~ | ~~`settings_dialog.py` 设置页裁切~~ | ~~round-102 遗留：设置页在小窗口 / 125% DPI 下底部内容可能被裁~~ | **已复核**（2026-10-24 round-119）：设置 → 网络 / 第三方服务真机截图无裁切；**2026-10-26 补验设置 → 外观页**：离屏 1280×800 / 1000×700 / 900×640 三档均无控件超出 GroupBox 底边，3 个复选框与「主页背景」组完整可见 | ✅ 完成 |
| ~~P1~~ | ~~`main_window._show_page`~~ | ~~从版本库（无导航行的子页面）返回时，侧栏仍高亮首页 → `setCurrentRow` 同一行不发信号，「首页」点了没反应~~ | **已解决**（round-120）：行已选中时直接 `_switch_stack` | ✅ 完成 |
| ~~P1~~ | ~~`wallpaper._Veil`~~ | ~~媒体壁纸薄纱固定 alpha 118：亮灰壁纸上「找到 N 个结果」等裸标签对比度不足~~ | **已解决**（round-120）：图片 / GIF 按平均亮度自适应薄纱，视频与全景保持原策略 | ✅ 完成 |
| ~~P4~~ | ~~30 个文件~~ | ~~未使用导入（`QColor` / `QSize` / `QFrame` 等）~~ | **已解决**（round-120）：`pyflakes src main.py` 零告警 | ✅ 完成 |
| ~~P4~~ | ~~11 个死函数~~ | ~~`play_sfx` / `stop_bgm` / `read_json` / `write_json` / `ensure_dir` / `login_with_microsoft` 等~~ | **已解决**（round-120）：全仓引用扫描后删除，死函数扫描 0 | ✅ 完成 |

**待用户（真机，AI 做不了）**：`RELEASE_1.0.0_CHECKLIST.md` A 组剩余两项——
① 新建 Fabric+Forge 实例真实拉取/启动到主菜单一次通过（含镜像可用性）；
② `build.bat`/PyInstaller 打包成品 + 安装后首次运行冒烟。
离屏环境只能验逻辑与布局，真机启动链路（JVM 参数/内存/Acrylic 降级）必须人跑。

## 四、已知既存问题（非本轮引入，别当 bug 修）

- **离屏 Qt 在解释器 teardown 阶段崩 `0xC0000409 (-1073740791)`**：测试内容其实
  全部通过并打印成功标记，但进程退出码非 0。已在 HEAD `a9ffef4` 的 worktree 复现，
  属既存问题。`regress.py` 已识别成功标记，不会误判。
- **导航 `account` 会阻塞**：它不是页面而是弹模态 `LoginDialog`（`dlg.exec()`），
  预期行为。离屏冒烟需跳过。
- **离屏无字体（tofu）**：真因是 offscreen 平台插件不加载系统字体
  （`QFontDatabase` 字体数 0）。`QT_QPA_FONTDIR=C:\Windows\Fonts` 即修复，
  `regress.py` 已默认设置。

## 五、2026-11-05 全链路代码审查（AC 主路径 vs 外来实例兼容路径）

**审查范围**：仓库内没有第三方启动器源码，这里的「其他启动器」指 AC 兼容外来
实例的链路——`src/scan.py` → `src/instances.py::import_external` →
`src/core/instance_rebuild.py` / `src/modpack_import.py` → `src/launch.py`
的 round-78 / round-92 分流，对比 AC 自建实例主路径与 `main.py` 应用初始化。
静态审查，未跑真机启动验证。

### P0 — 已修（本次落地；判据 `tests/test_p0_review_fixes.py`，已登记 regress.py）

| 位置 | 问题 | 修法 |
|---|---|---|
| `src/main_window.py` 手选 Java 兜底 | 旧实现写到 `get_data_dir()/launcher_config.json`，而统一入口读 `get_config_path()` → 手选 Java 永远不生效；裸写非原子、读失败 `cfg={}` 清空回写 | 改 `load_config()` → 改键 → `save_config(cfg)`（原子写），同步 `self.cfg`；写盘失败弹框不重试 |
| `main.py` 条款门禁 | 整段 try/except 外层只写日志 → 对话框/判据抛异常即「未同意条款直接进启动器」；`save_config` 失败被吞 | 改 fail-closed：判据/对话框异常 `QMessageBox.critical` + `return`；写盘失败明确警告，下次重新询问 |
| `src/core/shared_libs.py` 合并 | `getsize` 相等即删源、单文件失败 `pass`、末了无条件 `rmtree`；junction 已建后 `is_junction()` 短路 → 失败文件永久丢失 | 改 sha1 判重；同坐标内容不同两边都留；返回失败数，调用方仅在 0 时删 pending；`is_junction` 分支与开头改为重试残留 |
| `src/launch.py` + `src/instances.py` 共享池适用范围 | round-175 只按 `not external` 判定，「复制导入」(`external=False`) 的外来完整客户端也被套池，与 round-92「绝不改布局」冲突，补库写 jar 穿透联接污染全局池；`copytree` 未忽略新增 assets | 新增 `should_use_shared_pool(inst)`（`external` / `version_id` / `kind` / `launcher` 四判据），两处统一调用；外来导入改全量复制，`duplicate()` 只对 AC 自有实例忽略 `libraries`+`assets` |

⚠ **存量迁移风险**：round-175 期间已被改成联接的外来实例，本次**不自动回滚**
（池是共享的，无法还原单实例原始内容）。真机需检查这类实例的 `libraries` /
`assets` 是否为联接；若缺文件，重新「复制导入」一次即可。

### P1 — 待修（未动，避免与 TRAE round-175 批次撞车）

| 位置 | 问题 / 影响 | 改进方向 |
|---|---|---|
| `src/launch.py:702/705-714` ↔ `src/core/java.py:395` ↔ `src/core/install.py:132-134` ↔ `src/launch.py:896` | 同一「Java 要求」四套判据：UI/体检显示 A、实启 B；安装期 `need_override=0` + `java = java or "java"` 会选错 JVM 或回退裸 java | 抽 `java_plan(inst, settings)` 为唯一来源，启动/安装/体检/`-noverify` 全复用 |
| `src/launch.py:938/950-952` ↔ `:699`、`src/instances.py:423-455` | classpath 基于 `vroot`（iso 布局上移两级），补库却以 `mc_dir/libraries` 做 relpath → `..` 开头的缺失库被整批跳过 | `_libs_root` 改 `vroot/libraries`，或按 maven 坐标拼 URL |
| `src/launch.py:964-969/994-998` → `src/main_window.py:5092-5118` | 补库失败吞掉后继续 spawn，`_on_launch_done` 无条件 `mark_launched()` + `last_session.record(...,"ok")` → 缺库秒退记成成功 | `launch_instance` 返回 `degraded_reason`；主库失败中止，宽容启动标注缺库数 |
| `src/scan.py:482` → `src/i18n.py:1360` → `src/pages_instances.py:2153` | `needs_convert` 是死字段：UI 承诺「首次启动自动重建」，启动/安装链路零消费；`reconstruct` 仅手动按钮调，`instance_rebuild.py:216` 还无条件清标志 → MMC/Prism 组件包导入后按空壳重装，mods/patches 失效 | 启动前按标志走 `reconstruct`，仅转换成功才清标志 |
| `src/launch.py:909` ↔ `:461/:484` | `_prepare_natives` 未传 `on_repair`，注释里的「补全后重试」永不执行；失败静默返回 None 仍启动 → 老客户端 `NativeLibraryNotFound` 秒退 | 传入回调；二次失败显式报错 |
| `src/worker.py:365-379` | `ProgressWorker` 在「异常 + 已取消」时 `error/cancelled/finished` 一个都不发 → 任务中心/进度框永久运行中；`_cancel_requested` 裸 bool 无同步 | `finally` 发统一终态信号；`error` 带类型+traceback；改 `threading.Event` |
| `src/settings_dialog.py:234-247` + 4 份 cfg 快照（`main.py:258`、`main_window.py:1833/4602`、`settings_dialog.py:385`、`onboarding.py:155`）；`onboarding.py:724-725/774-777` | `save_config` 整文件覆盖 + 多份长生命周期快照 → 旧快照回写回滚后续改动；教程 `reject()` 不提交却 `mark_done`，写盘失败被吞 → 语言/主题/RAM 全丢且向导永不再弹 | 单一配置仓储 + merge-on-write；`closeEvent` 只写窗口几何；写盘成功才标完成 |
| `src/modpack_import.py:181-186/291-294`、`src/instances.py:657-659` | 整合包导入安装失败只 `print`，错误挂动态属性不进 `asdict` → 落盘丢失，UI 仍显示导入成功 | 正式 dataclass 字段 + `install_ok` 返回标志，错误上报任务中心 |

### P2 / P3 — 待修（一致性与可维护性）

| 位置 | 问题 / 影响 | 改进方向 |
|---|---|---|
| `src/settings_dialog.py:143/726/2765`、`src/main_window.py:3576` | `tray_minimize` `_DEFAULTS=False`，消费端三处 `.get(..., True)`；`jvm_aikars` 同类漂移。局部 cfg 快照缺键时「关闭即退出」变藏托盘常驻 | 去掉字面量默认值，扩展 `tests/audit_defaults.py` 全键扫描 |
| 全仓 37 处 `load_config()`、4 处直读配置文件（`brand_custom.py:29`、`diagnostics.py:45`、`core/support_bundle.py:75`、`main_window.py` 旧实现已修）、`main.py:209` 在 `load_config()`(258) 前读配置、`settings_dialog.py:223` 异常白名单漏 `PermissionError` | schema 改键无法扩散；只读/杀软占用场景启动直接崩；三份行为各异的 `_read_json`（`modules.py:147` / `features.py:238` / `instance_rebuild.py:31`） | 抽 `config.py` 单一入口（缓存/校验/原子写），`except` 改 `OSError`，`_read_json` 合并到 `core/utils.py` |
| `settings_dialog.py` 2945 行 / `main_window.py` 5739 行、根目录 36 个 `_probe_*.py`、全仓 310 处 `except Exception` 紧跟 `pass` | 启动期 i18n/主题/更新说明/退出 drain 全静默降级，排障只能翻 `_startup.log`；改动难回归 | 区分「可选装饰」（记诊断面板）与「关键状态」（回报 UI）；抽 `launch_options.py` 统一组装 Java/mirror/proxy/RAM；大文件按 mixin 拆，探针归档 |

### 六维度一致性结论

| 维度 | 结论 |
|---|---|
| 初始化顺序 | `main.py` 主线正确（单实例锁 → 配置 → i18n/主题），破口在「配置加载前读配置」与门禁 fail-open（已修后者） |
| 配置读取 | 最不一致：统一入口 / 直读文件 / 写错路径三套并存，4 份长生命周期快照配整文件覆盖写 |
| 依赖处理 | AC 路径全量安装 vs 外来路径「精确补库 + 宽容启动」；补库基准、Java 判据、natives 修复未对齐 |
| 状态管理 | `needs_convert` 死字段、任务终态信号缺失、`last_session` 不认降级 = 状态与事实不同步 |
| 异常处理路径 | 默认「吞掉后继续」，在门禁、跨实例文件合并、补库失败三处升级为合规/数据安全风险 |
| 代码组织 | 配置 / Java / 镜像各有 3–4 个组装点 + 两个超大文件 + 310 处静默 except，是多数问题的共同根因 |

---

## 六、横向实现审计（2026-11-05）：AC vs 主流启动器

完整报告 → `docs/launcher_interop_audit_2026-11.md`。审计阶段只读；
**2026-11-05 晚经用户授权「动手」，三条 P0 已修**，P1/P2 仍待修。
尺子：官方 Launcher / Prism / HMCL / PCL2 的公开实现 + authlib-injector 与 Modrinth
官方规范 + 仓库内 `minecraft-launcher-lib 8.0` 实际行为（AC 把版本解析与命令行构造
整体委托给它）。与第五章互补：第五章查 AC 内部路径分叉，本章查与业界标准相违背处。

| 级别 | 位置 | 问题 | 状态 |
|---|---|---|---|
| **P0** | `src/launch.py:869-872` | 账号 profile 键 `name/id/access_token` 与启动读取的 `username/uuid/token` 不匹配 → 所有已登录账号以 `Player` + 空 UUID + 空 token 启动（运行时复现确认） | ✅ 已修：`src/accounts.py` 新增 `launch_identity()`，启动 / `_game_token` / 皮肤 uuid 统一走归一化 |
| **P0** | `src/core/install.py:274-275` | 模块缺 `import json` → `find_installed_loader` 抛 NameError，NeoForge 1.21+ / Cleanroom 启动失败（运行时复现确认） | ✅ 已修：模块顶部补 `import json` |
| **P0** | `src/core/install.py:482-492` | 手写 LiteLoader 子 json 覆盖父 `minecraftArguments` 且缺 `jar` → 1.12.2 实例秒退（mll `inherit_json` 复现确认） | ✅ 已修：读父完整参数串后追加 tweakClass + 写 `"jar": mc_version`；父串缺失显式报错 |
| P1 | `src/core/auth.py`, `src/login_dialog.py:617`, `src/launch.py:288-318`, `src/core/authlib.py:174` | 认证链路四项：微软 token 无过期/刷新、离线 UUID 为空、authlib javaagent 传本地文件路径而非 API URL、javaagent jar `.version` 旁路免校验 | 待修（建议一起修，互相叠加） |
| P1 | `src/launch.py:226-235,1064,944-971`, `src/net_api.py:321,1363` | 启动链路四项：logging 配置不注入、cwd 与 gameDir 不一致、补库裸拼 URL 且只按 1000 字节判有效、资源中心下载丢弃 sha1 | 待修 |
| P1 | `src/scan.py:462-497`, `src/modpack_import.py:340-351`, `src/accounts.py:86-103` | 导入/持久化三项：MMC patches 与 instance.cfg 字段丢弃、文件夹导入按 jar 名猜 loader、accounts.json 非原子写 | 待修 |
| P2 | `src/net_api.py:46`, `src/core/java.py:220`, `requirements.txt:3`, `src/launch.py:662` | UA 不可识别、Java 兼容区间硬编码、mll 未锁版本、完整性只看 json 存在 | 待修 |

**P0 修复验证**：新增 `tests/test_interop_p0_fixes.py`（23 项静态 + 行为判据，
含真实调用 `install_liteloader` 后让 mll 继承并核对 classpath 主 jar），登记 `regress.py`
→ **38/38 exit 0**。刻意未动：离线账号目前拿到 12 位内部 id（非空但非规范 UUID），
合法 `OfflinePlayer:<name>` UUID v3 仍列在 P1。

**返工顺序**：~~P0 三条~~（已完成）→ 认证链路四条 → 下载完整性 → 渐进项。
报告里另列了「AC 已做对/领先」的 5 类能力（Forge processors、natives exclude、
安装期 sha1、共享池、取消链路），修的时候别误伤。

---

## 七、2026-11-06 真机验收（部署版 exe）发现

场景：按 `docs/round163_instance_java_reliability/tasks.md` 重打部署后，用户在真机上
新建 1.21.10 实例，连点「创建」十几次毫无反应（不弹框、不关向导、无网络等待）。
证据：`<安装目录>/data/crash.log` 20:27:17–20:30:45 共 **15 条**同一异常。

| 级别 | 位置 | 问题 | 状态 |
|---|---|---|---|
| **P0** | `src/pages_instances.py:500` / `:1346` | `created` 信号定义为 5 参，但 `result_data()` 自 `4811b8f` 起返回 7 元组（新增 `format` / `base`）。`emit(*7)` 抛 `TypeError: created(...) only accepts 5 argument(s), 7 given!`；Qt 槽内异常只被 `main.py:149` 的 excepthook 写进 crash.log，**界面静默失败**。版本页弹窗路径（`pages_browse.py:354`）已按 7 元解包，故只炸实例页嵌入式向导 | ✅ 已修：信号扩为 7 参；新增 `tests/test_new_instance_signal.py`（Qt 元对象运行时验签 + 返回值/信号/槽三方一致 + 全仓 63 处 Signal/emit 超参扫描），登记 `regress.py` → **39/39 exit 0** |
| **P1** | `src/core/java_install.py` | Java 下载裸 GET `api.adoptium.net` → 307 跳 GitHub Releases（55.9 MB，本机 ≈10 KB/s ≈95 min），未接入项目已有的 Range 分片 / 来源健康 / 断点续传 | 待用户授权修（建议「USTC/TUNA 镜像优先 + 官方兜底 + 断点续传」；实测 USTC 同文件 22.8 MB/s、Content-Length 与官方一致、支持 Range） |
| **P1** | `src/core/java_install.py:175-183` | 取消 / 失败分支 `shutil.rmtree(target)` 删的是**已装好的** `jre-25/` 整个目录，不只是半成品 zip；点「取消」会连带删掉可用运行时 | 待用户授权修（应与上条一起改，同一处代码） |

**结构性教训**：Qt 信号是「定义处 arity 硬约束」，任何 `emit(*tuple)` 的返回值扩字段
必须同步改 Signal 声明；而 Qt 槽内异常不弹框、不中断进程，只落 crash.log →
「点了没反应」优先查 `data/crash.log`，不要先怀疑网络。新加的全仓 arity 扫描
就是为防止同类分叉再次静默溜过回归。

**同场已完成**：重打并部署含修复的 exe（保留 `launcher_config.json` / `data/`），
`AC_NO_TERMS=1` 10 秒冒烟通过；JRE 25 已由国内镜像补装进 `data/java/jre-25`。

### 七·续 真机连报三现象（20:49–20:53，同一条因果链）

用户口述：① 下载资源文件时「左下角那个进度一直在闪，第一个数字正确、后面都是 9，又弹回正常值，反复跳，像是昨天的状态」；②「下载进度不会关」，于是以为没点上、又启动了一次；③ 再启动直接报「少了 classpath」。用户自己怀疑是「启动了两次」。随后再重启一次，补全跑完，游戏正常启动。

**现场证据**（`<本机部署目录>/data/`）：
- `Get-CimInstance Win32_Process` 只有 **1 个** `AC_Launcher.exe`（20:46:03 起），`ac.lock` 存在 → 单实例锁有效，**不是两个 exe 进程**；`_handle_play` / `_start_download` 的 `isRunning()` 护栏也确实挡住了并行双 worker。
- `task_history.json`：**20:46 `cancelled launch 38/113`（正在下载依赖库 38/113）→ 20:47 `done launch 3058/5146`（资源下载完成）**，两次任务、前一次被取消，与用户「又启动一次」吻合。
- `data/<id>.log`（游戏日志，GBK）：`错误: 找不到或无法加载主类 net.minecraft.client.main.Main / ClassNotFoundException`。但 `versions/26.3/26.3.jar` 41,483,720 B 完整、`net/minecraft/client/main/Main.class` 在包内、`26.3.json` mainClass 正确 / 114 libraries → **不是主 jar 坏，是 38/113 被取消后 classpath 没拼齐**；启动器崩溃分析把这条日志归类为 `exit.classpath`（「缺少游戏运行库(classpath)」）才显示成「少了 classpath」。再启动补全跑完即自愈，用户已确认。
- `crash.log` 无新增（仍 15 条旧信号异常）→ 全程无 Python 崩溃。

| 级别 | 位置 | 问题 | 状态 |
|---|---|---|---|
| **P1** | `src/main_window.py:2714,2720,2721`（下载）/ `:5049,5054,5055`（启动） | `w.status.connect(self.statusBar().showMessage)`、`w.speed.connect(self._set_speed)`、`w.progress.connect(self._set_progress)` 三路信号**直连全局状态栏且无 worker 归属检查**。取消/失败后 `self._dl_workers.pop()` 但**没有 disconnect**，`ProgressWorker` 的 `_speed_loop` 轮询与 `_on_stall` Timer 仍持续发信号；`_set_progress` 还会 `setVisible(True)` 重新点亮进度条。只有 `_on_download_progress` 有 `inst_id not in self._dl_workers` guard，注释声称「残留 status/progress 信号因 worker 已移出表而被丢弃」**是错的** → 旧任务数值（用户看到的 9…）与新任务正确值交替刷 = 闪 | 待授权修 |
| **P1** | `src/main_window.py:2853-2858` `_on_download_error` | 明确写着「round-170：失败不再自动关框——保留对话框并提供重试下载」，**是设计**；但失败态视觉不够醒目，用户误判为「还在下载」→ 重复点启动，是整条链的触发点 | 待授权修（加醒目失败态 + 「重试」按钮语义） |
| P2 | `src/worker.py:293-301,319-340` | `abort()` 后 `_speed_loop` / stall Timer 未立即停，是残留信号的上游；即使 UI 加了 guard，也该在 abort 时 `disarm_stall()` + 置 `_speed_stop` | 待授权修 |

**修复方向**：给状态栏三路信号统一走「当前活跃 worker」归属槽（连接时带 worker 引用，槽首判 `self._active_status_worker is worker`），并在完成/失败/取消时清空 + `disconnect`；失败对话框加醒目终态。完成后必须**真机复现「点两次 → 状态栏不再闪」**才算结案（纯静态判据不足以证明运行时闪烁消失）。

⚠ 本条登记时用户游戏正在运行，未改代码、未重打部署，避免打断。

### 七·续 2 启动后行为 + 实例页「启动」按钮 + 模组侧完整性（20:57–21:00）

| 级别 | 位置 | 问题 | 状态 |
|---|---|---|---|
| **P1** | `src/main_window.py:5322-5356`（原实现） | `close_after_launch` 默认 `True`（`settings_dialog.py:138`，真机 `launcher_config.json` 亦为 `true`）→ 游戏起来 5s 后 `_tray_auto_quit=True` + `close()` → `QApplication.quit()` **真退出**，强制绕过托盘。随主窗口销毁的还有 `_game_poll_timer`（`QTimer(self)`），导致 `explain_exit()` 退出码分类、崩溃弹窗、`last_session` 崩溃记录、退出后命令、控制台结束标记、托盘「结束全部游戏」全部失效。用户诉求「退出游戏后 AC 还在 + 崩溃检测能看到」 | ✅ 已修：改为 hide 到系统托盘（无托盘时 `showMinimized`），游戏退出时自动恢复窗口；同步中英文案，判据 `tests/test_post_launch_behavior.py` |
| **P1** | `src/pages_instances.py:1667` / `:2052` | 实例详情卡的「启动」按钮名不副实：`_launch()` 只 `set_current()` + `_refresh()` + `current_changed.emit()`，**不启动游戏也不跳首页**（注释声称 `jumps home & selects`）。用户点着「毫无反应」，实际只是把实例悄悄设为当前 | 待用户选方案（推荐换成「体检 / 启动诊断」，复用 `mod_check_dialog.open_health_dialog` + 补一页启动命令/classpath/缺库视图；或按用户原话直接删掉） |
| **P1** | `src/crash_analysis.py:328` | 崩溃自动补前置调 `download_mod_to(project_id, inst.mods_dir)` **未传 `mc_version` / `loader`** → `resolve_mod_dependencies` 取项目最新版本，可能装进与当前实例不兼容的 mod | 待授权修（应传 `inst.game_version` / `inst.loader`） |
| **P1** | `src/store_detail.py:775-785`（CurseForge 分支） | CF 渠道走 `download_curseforge_file` / `download_cfwidget_file` 单文件直下，**无依赖树解析、无版本自适应**；「另存为文件夹」分支也把 `mc_version, loader` 置空 | 待授权修 |
| P2 | 入口可发现性 | 冲突检测（`core/mod_check.py` + `core/instance_health.py`）、一键修复（体检 `apply_fix` / 崩溃弹窗 `_repair_all` / `diagnostics.repair_all`）三套能力都在，但分散在右键二级菜单与不同弹窗，无统一「模组完整性」入口 | 待授权（建议整合进「体检 / 启动诊断」） |
| P2 | `src/settings_dialog.py:726` vs `:143` | `tray_minimize` UI 缺省值写 `True`、`_DEFAULTS` 是 `False`；配置缺键时勾选态与实际行为不一致 | ✅ 已修：UI 缺省对齐为 `False`；`_sync_behavior_hints` 的行为说明不再依赖 `tray_chk`（自动隐藏与托盘开关解耦），测试判据已覆盖 |

**已有能力，勿重复造轮子**：Modrinth `required` 依赖递归（`net_api.py:805`，深度 5 / 去重 / 跳过 optional+incompatible）、按 MC 版本+加载器过滤（`net_api.py:707`、`store_detail.py:586`）、重复 modid 与缺前置扫描（`core/mod_check.py`）、OptiFine/Sodium 冲突（`core/instance_health.py:230-247`）、`install.repair_minecraft_dir` 版本文件自愈。


---

## 八、模组 / 资源链路复查（2026-11-06 round-177）

> 用户指出「前面那三个缺口只是举例，去找找还有没有别的」。因此对
> 「版本过滤 → 依赖解析 → 下载落盘 → 崩溃补前置 → Java 选择」重做了一遍
> 逐行复查。**以下每一条都带实际读到的 file:line；没查实的明确标「待核实」，
> 不把推测写成结论。**
>
> ⚠ 过程说明：先派了一个后台只读审计任务，其结论未通过工具通道稳定返回，
> 因此本节每条 `file:line` 均由主 agent 逐行复查源码确认，未直接采信转述；
> 没读透的部分单列「待核实」，不写成结论。

### 本轮已修（✅ 均为真 bug，非功能增强）

| # | 位置 | 问题 / 影响 | 判据 |
|---|---|---|---|
| 1 | `src/crash_analysis.py:328` | 崩溃自动补前置 `download_mod_to(target["project_id"], inst.mods_dir)` 不带 MC 版本 / 加载器 → `_modrinth_versions` 不过滤，拉到不兼容最新版，修完照样崩 | `test_round177_mod_diag.py` |
| 2 | `src/crash_analysis.py:322` | 模糊匹配失败时 `target = hits[0]` 兜底 → 装进一个无关模组，比「没修好」更糟（多一个冲突源） | 同上 |
| 3 | `src/net_api.py` `parallel_download_file` 预建 `.part` 前 `os.remove(dest)` | 分片失败 + 单流兜底也失败时，**已装 mod / 核心 jar 已被删掉**（数据损坏）。本来就是 `os.replace` 原子收尾，根本不需要预删 | 同上 |
| 4 | `src/net_api.py:805-855` `resolve_mod_dependencies` | 本体网络错误 / 无匹配版本时静默 `return out` → `download_mod_to` 抛「没有可下载的文件」之前 UI 无差别，且子依赖被吞后显示成功却缺前置 | 同上 |
| 5 | `src/net_api.py` 6 处 `os.path.join(dest_dir, filename)` | 服务端返回的文件名未 `os.path.basename` 清洗，带 `../` 可写穿目标目录 | 同上（`_safe_filename`） |
| 6 | `src/net_api.py` Modrinth 两条下载路径 | 全链路无 sha1 校验；Modrinth version 的 `files[].hashes.sha1` 现成就没用 | 同上（`_verify_sha1`） |
| 7 | `src/core/java_install.py` + `src/java_manager_dialog.py:319` | **Java 下拉候选不含本机已装 major**：`JAVA_CHOICES` 最大 24、`available_majors()` 离线回退静态表、`installed_majors()` 只用于渲染「已安装」卡片 → 玩家装好的 Java 25 路径能选、能启动，但列表里永远看不见 | `test_java_mirror_resume.py` |
| 8 | `src/core/java_install.py` 整体 | Java 下载裸单流 GET `api.adoptium.net` → 307 到 GitHub（实测 ~10 KB/s，55.9 MB 约 95 分钟），无镜像 / 无 Range 续传；取消时 `shutil.rmtree(target)` 会把已装运行时一起删 | `test_java_mirror_resume.py` |
| 9 | `src/main_window.py` 状态栏三路信号 | 见七·续：取消/失败只 pop worker、从不 disconnect，旧 worker 残留信号与新任务交替刷 → 左下角闪烁 | `test_status_signal_ownership.py` |
| 10 | `src/pages_instances.py:1667` / `:2052` | 详情页「启动」按钮名不副实（只 `set_current` + refresh，不启动不跳首页）→ 改成「体检 / 启动诊断」，新增 `src/launch_diagnostics_dialog.py`（启动命令 / classpath / 缺库 / 体检两页，token 恒占位符） | `test_round177_mod_diag.py` |

### 仍未修 — 真缺口（P1，按耦合分组）

| 组 | 位置 | 问题 |
|---|---|---|
| A 依赖与版本 | `src/pages_browse.py:879-895` | CurseForge 下载分支（`download_cfwidget_file` / `download_cfwidget_slug` / `download_curseforge_mod`）**完全不解析 required 依赖树**，也不带实例版本/加载器；只有 Modrinth 分支传了。CF 靠 fileID 选版本，但依赖得单独查 |
| A | `src/net_api.py:805` | `resolve_mod_dependencies` 递归时把 `version_id` 传空、`_seen` 按 `project_id` 去重 → 同一项目多版本依赖会被吞（当前设计取舍，改动前需定语义） |
| A | `src/net_api.py:2188` `download_modpack_to` | 走 `get_mod_download(project_id)` 无版本参数，只能拿最新整合包版本；详情页「指定版本」走的是另一条路径，两条口径未统一（待核实是否会装错） |
| B 完整性 | `src/net_api.py:1363/1681/1783` | CurseForge 三条下载路径**仍无 hash 校验**（本轮只补了 Modrinth 两条）；CF 文件侧是否有 hash 字段待核实 |
| B | `src/net_api.py:328` `download_file` | 只有 Content-Length 长度校验，无期望 hash 参数；建议做成统一可选参数，别每个调用点各写一份 |
| B | `src/net_api.py` mod 下载 | 失败时 `.part` 保留策略与 Java 侧不一致（Java 本轮做了「取消删、失败留」） |
| C 检测 | `src/crash_analysis.py:279` | `find_missing_dependencies` 只比 modid 字符串，不解析 Fabric `depends` 版本区间 / Forge 依赖约束 |
| C | `src/crash_analysis.py:297` | `except Exception: failed.append(dep)` 把网络错、解析错、写盘失败全折叠成一个字符串，UI 无法区分「没搜到」和「装失败」 |
| C | `src/launch.py:1024` 注释 | 启动前只做轻量预检，缺前置不拦截（PCL2 / HMCL 会显式提示） |
| D 入口 | 三处 | 「一键修复」分散在右键实例体检 / 崩溃弹窗 / 设置→诊断与修复，语义不一、无统一「模组完整性」入口 |
| D | `src/pages_instances.py` | 右键菜单仍无「实例体检」「模组完整性」，能力藏在详情页二级 |

### 待核实（本轮没读透，不写成结论）

- `src/core/install.py` 对 `.mrpack` 的 `overrides/` 解压与覆盖策略；
- `src/core/mod_check.py:_parse_jar` 对 Forge `META-INF/mods.toml` 的覆盖程度
  （`crash_analysis.py:274` 有 `_toml_attr`，两条链路口径可能不一致）；
- 资源包 / 光影 / 数据包是否与 mod 共用 `loaders` 过滤而被误筛；
- CurseForge 缓存键是否包含版本 / 加载器（Modrinth 侧 `_modrinth_versions` 的 key 已含，确认过）；
- `download_cfwidget_file` 目录口径与整合包 UI 读取路径是否一致。

### 修复分组建议

- **A 组**：CF 依赖树 + 版本口径统一，一次改（分散修容易互相打脸）。
- **B 组**：把 sha1 / `.part` 策略做成 `download_file` 的通用能力，再让 CF 三条路径接入，别继续按渠道各写一份。
- **C 组**：崩溃分析的错误分类与启动前拦截，需先定义「缺前置时是拦还是提示」的产品语义。
- **D 组**：纯 UI 增量，风险最低，可随时插入。

> ⚠ 双轨验收：本节修复全部是代码轨 + 构造判据，**未在真客户端复现**。
> 按项目铁律，必须真机走一遍「搜模组 → 下载 → 启动 → 体检 / Java 下拉」
> 才算结案。特别是 #7 Java 25 下拉，要重开一次 Java 管理对话框目检。
