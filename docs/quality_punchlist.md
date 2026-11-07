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

### round-178 收尾状态（2026-11-06 22:30，A/B/C/D 组按序落地）

| 组 | 已修（✅） | 明确未修 / 有意不动（⚠） |
|---|---|---|
| **A 依赖与版本** | `resolve_mod_dependencies` 跳过 `embedded`、递归传依赖声明的 `version_id`、顶层指定版本不存在时抛错；CF 官方卡片下载按实例 MC 版本 / 加载器过滤（资源中心三路 UI 全部传参），无匹配**拒绝下载而不是取最新**；cfwidget 文件版本校验 + 字符串 fileID 容错；整合包 `get_mod_download` / `download_modpack_to` 支持 `version_id`；keyless 指定 manifest fileID 找不到时不再静默退回最新 | ⚠ **CF `required` 依赖树递归仍未做**：keyless 通道（cfwidget / 镜像）能否稳定返回 `dependencies` 未核实，贸然递归会多出 N 次网络请求且可能装错；下一批先定 API 契约再动。⚠ `_seen` 仍按 `project_id` 去重（同项目多版本依赖只装一个），**刻意保留**——全放开会往 mods 目录塞同名 modid 的两个版本，直接 duplicate 崩溃 |
| **B 完整性** | `download_file` / `parallel_download_file` 统一 `expected_sha1`（在 `.part` 阶段校验，坏字节永不 `os.replace` 成正式文件；不符就丢 part 重下）；CF 三条下载路径 + keyless 通道接 `_cf_sha1`（兼容 CF `hashes[algo=1]` / cfwidget 字典 / 顶层字段，MD5 与 fingerprint 绝不冒充）；Modrinth 两条路径改走通用参数 | ⚠ `.part` 的取消策略**刻意不统一**：通用下载器保留 `.part` 供断点续传，Java 侧删半成品是用户明确要求，两者语义不同、不是 bug |
| **C 检测** | 新建 `src/core/mod_repair.py` 收敛「扫描 → 精确匹配 → 补装」；`scan_missing` 显式区分「没有缺失」与「jar > 60 深扫被跳过」（旧行为会误报「依赖齐全」）；失败按 `search` / `match` / `download` 三阶段带原因；`crash_analysis.search_and_download_missing` 改为兼容薄封装；匹配只接受规范化后完全相等（`fabric-api` 不再误命中 `fabric-api-base`，也不做 `startswith` 宽松匹配） | ⚠ 启动前预检**维持「只提示不拦截」**：缺前置要不要拦启动是产品语义，等用户定；`find_missing_dependencies` 仍只比 modid 字符串，不解析 Fabric `depends` 版本区间 / Forge 约束 |
| **D 入口** | 崩溃弹窗「一键修复」补汇总终态（不再只调 deps 却什么都不说）+ 结构化失败明细；实例右键新增「补装缺失依赖」，走同一 `mod_repair`；`crash_dialog` 与右键都显示「jar 过多已跳过」 | ⚠ 体检对话框 `scan_conflicts` 的 `missing_dep` finding 仍 `fix=None`（其「补装」按钮是重装游戏版本，不是补 mod）；`diagnostics.repair_all` **刻意不并入**模组域——它管配置 / 账户 / 游戏文件，与模组依赖不是一回事，硬合并反而让「一键修复」语义更乱 |

**登记纠错**：八章原写「右键菜单仍无『实例体检』」不准确 —— `pages_instances.py` 右键本来就有
`t("health.title")`（实例体检）与 `t("instances.crash_analyze")`（崩溃分析），本轮新增的是
「补装缺失依赖」这一项，不是补体检入口。

> ⚠ 双轨验收：本批全部是代码轨 + 构造判据，**未联网 / 未在真客户端复现**。
> 真机要验：① 资源中心 CF 卡片下载装到的是匹配当前实例版本的文件；② 下载损坏 hash 时会重下而不是落坏 jar；
> ③ 崩溃弹窗 / 右键「补装缺失依赖」的终态与失败明细；④ 模组 > 60 个时提示「已跳过」而不是「依赖齐全」。

### 修复分组建议（历史记录，实际执行见上一节）

- **A 组**：CF 依赖树 + 版本口径统一，一次改（分散修容易互相打脸）。
- **B 组**：把 sha1 / `.part` 策略做成 `download_file` 的通用能力，再让 CF 三条路径接入，别继续按渠道各写一份。
- **C 组**：崩溃分析的错误分类与启动前拦截，需先定义「缺前置时是拦还是提示」的产品语义。
- **D 组**：纯 UI 增量，风险最低，可随时插入。

> ⚠ 双轨验收：本节修复全部是代码轨 + 构造判据，**未在真客户端复现**。
> 按项目铁律，必须真机走一遍「搜模组 → 下载 → 启动 → 体检 / Java 下拉」
> 才算结案。特别是 #7 Java 25 下拉，要重开一次 Java 管理对话框目检。

---

## 九、启动格式与「AC 专属标识」（待设计，用户 22:06 提出，本轮不实现）

> 用户原话要点：① 「我们启动游戏不是有个特殊格式吗？但是好像没有合理区分，
> 自定义启动格式这个功能好像没有什么实际作用」；举例「一个目录实例层层叠进、
> 把游戏拆成一个个文件夹混着叠在一起」这种极端布局该怎么搞；② 「搞一个专属标识
> 只有我们能识别的，识别对应启动格式和实际格式对应，然后就可以直接自动选中
> 对应选项启动，就不用判断这么多东西了」。
> **排期**：用户明确「先干其他那一组的事情」→ 本节先登记，等第八章 A/B/C/D
> 组收尾后再回来做设计评审，不要顺手改代码。

### 现状（2026-11-06 逐行核实，勿凭印象改）

- `src/instances.py:100` `Instance.format`（`""` / `auto` / `ac` / `vanilla` /
  `iso` / `multimc` / `curseforge` / `modrinth` / `custom` 等 `INSTANCE_FORMATS`），
  `:106` `_base` = **游戏目录本身**（不是实例根）；`:124` `mc_dir`、
  `:139` `game_dir`、`:180` `mods_dir` 由它派生。
- `detect_format()` `:325` 优先级：`_is_ac_owned()`（`:356`，`_base` 空且非
  external ⇒ 结构性事实 `ac`）> 玩家手选（非空非 auto）> `_probe_format()`
  （`:366`，只读扫 `mmc-pack.json` / `<ver>.json` / `minecraftinstance.json` /
  `profile.json` …）> `kind` 兜底。`adapt_format()` `:409` 把 AC 自有布局上
  残留的外来标签纠正为 `ac`。
- `layout_of()` `:424` 是启动 / 补全 / 体检共用的**唯一口径**，返回
  `format` / `version` / `flat` / `install_dir` / `versions_root`。
  `src/launch.py:359`、`src/core/install.py:121`、`src/core/instance_rebuild.py:125`
  都走它。
- `src/pages_instances.py:2310/2454` 实例设置可手选格式；新建向导
  `result_data()`（`:500`）返回 7 元组带 `format` / `base`。
- i18n `instances.fmt_mismatch_hint` 只是「手选与实测不符」的**提示文字**，
  不自动纠正、不落盘任何标识。
- `src/scan.py:744` 已有「按 marker 文件猜别的启动器」的逻辑，但那是**扫描外部
  实例时猜归属**，与 AC 自有实例的启动格式是两回事，别混用。

### 为什么用户觉得「没实际作用」

`format` 现在只是**一个粗粒度枚举标签**，不是「目录结构描述」：只够区分
「AC 自有 / 官版共享 / 版本隔离 / 某启动器」，表达不了「游戏目录被拆成多层
子目录、版本 json / mods / saves / assets 分散在不同层」这类布局。每次启动
都靠 `_probe_format()` 按 marker 猜，目录一变就可能与手选不一致；而手选值
又会被 `adapt_format()` 在 AC 自有布局上强行改回 `ac`。所以「自定义格式」
既不能描述结构，也不能稳定生效。

### 用户提的方案（待评审）

在实例目录里放一个 **AC 专属标识文件**（只有 AC 识别），记录「声明的启动格式
+ 实际目录结构映射」，启动时直接读它自动选中对应选项，不再每次探测。

### 设计时必须回答的问题（一条都不能跳）

1. 文件名 / schema 版本 / 字段（是否含 `versions_root` `mods_dir` `saves_dir`
   `assets_dir` 的**逐项路径**，而非一个枚举）、编码与原子写。
2. 写入时机：新建 / 导入 / 复制 / 重建 / 手动改目录后；谁负责校验与更新。
3. 与 `_base` / `format` / `layout_of()` 的关系：标识是**真理源**还是缓存？
   冲突时以谁为准（建议：实际文件存在性优先，标识只作加速与声明）。
4. 外来实例无标识 → 降级到现有 `_probe_format()`，不能因此启动失败。
5. 存量实例迁移：一次性补全还是懒生成；老版本 AC 读到新文件会不会忽略。
6. 标识被其它启动器 / 清理工具删掉时的兜底；目录被整体移动后路径失效检测。
7. 极端嵌套布局是否需要「路径映射表」而不是扩展 `INSTANCE_FORMATS` 枚举
   —— 若需要，`layout_of()` 与所有调用点（启动 / 补全 / 体检 / 诊断 / 整合包
   导入目录口径）都要一起改，属于跨模块改动，必须单独一批 + 双轨验收。

### 用户方案 v2（22:41）与设计评审

> 用户明确方案：① 新建/下载版本时**本来就能选格式**（AC / 原版 / 其它启动器的
> 不同实例），给这些格式**加标识码**；② 标识码必须**不影响迁移到其它启动器、
> 不影响正常启动、不被其它启动器误识别，只对 AC 生效**；③ 顺序为
> **先找识别码 → 找到就按对应格式查漏补缺 → 没找到（或选了「不查验完整性」）
> 就跳过 → 若压根没识别码，则看一遍实例特征后补写识别码用于区分**；
> ④ **把启动默认的「AC 格式识别」改成自动查验**，防止其它实例被按 AC 规矩补全；
> 目标：省掉反复识别错误 → 乱补全 → 再查验完整性的繁琐流程。

**新增硬证据（本轮逐行查实）**

- `src/instances.py:779` `add()`：`format=(format or "").strip() if base else ""`
  —— **`base` 为空（AC 自有布局）时，向导里选的格式被直接丢弃**。「自定义启动格式
  没实际作用」是确凿 bug，不是体验问题，且**应该比标识更早修**。
- `src/instances.py:346` `detect_format()`：第一优先级 `_is_ac_owned()` 直接返回
  `ac`，跳过手选值与 `_probe_format()`；`adapt_format()`（`:409`）还会把 AC 自有
  实例上残留的外来标签强行改回 `ac`。`layout_of()`（`:424`）被
  `launch.py:359`（启动解析根）、`core/install.py:121`（补全写盘根）、
  `core/instance_rebuild.py:125`（重建根）共用 → 这里判错，三处一起错着补。
- 向导格式枚举：`pages_instances.py:123` `_fmt_keys` 共 8 个
  （auto / ac / vanilla / iso / multimc / curseforge / modrinth / custom）；
  新建向导 `current_layout()`（`:1299`）实际只给 ac / vanilla / iso / custom，
  即「AC 自有 / 玩家指定 .minecraft / 版本隔离 / 指定游戏目录」。
  **没有 PCL2 专属格式**——PCL2 实例在这里落到 `iso`（版本隔离）或 `custom`。

**设计评审：方案方向成立，三处建议改**

1. ☠ **标识文件放 AC 元数据侧，不要写进游戏目录**。
   建议 `data/instances/<id>/ac-layout.json`（与 `<id>.json` 同级），**不碰
   `.minecraft/`**。理由：写进用户外部实例的真实游戏目录是对外操作，PCL2/HMCL
   的「清理无效文件」或整合包覆盖可能删掉它，迁移时还会跟着走被别的启动器看见；
   放元数据侧则「只对我们生效」最彻底、零污染。代价是用户手动复制 `.minecraft`
   迁移后标识不跟随 → 降级到特征探测，这正是方案里的「没查到就看特征」分支。
2. ☠ **标识内容不能只是「格式 ID」，得是路径映射表**。
   一个 `ac|vanilla|iso` 枚举表达不了用户 22:06 举的「游戏拆成多个文件夹混着叠」
   的极端布局，光存 ID 之后还是靠猜。建议 schema：
   `{"schema":1,"fmt":"...","confidence":"high|low","paths":{"versions_root":"...",
   "install_dir":"...","mods_dir":"...","saves_dir":"...","assets_dir":"..."},
   "fingerprint":"...","created_at":...}`。「查漏补缺」= 按这张表逐项验证路径存在，
   缺哪个补哪个，不再每次重新探测。
3. ☠ **「没查到就自动补写标识」必须收窄**：只在探测置信度高时落盘；低置信度
   写 `confidence:low` 且不参与补全，或直接不写并提示。否则探测本身就不可靠时
   写死一张错表，之后会一直按错的补 —— 反而放大用户想消灭的「识别错误乱补全」。
   只读目录（Program Files / 别的启动器目录）写失败要静默降级，不能弹错。

**实施分两批（避免一次改动波及启动主链路）**

- 批次 1（零回归风险，纯增量）：新建 `core/instance_marker.py` 负责标识的
  读 / 校验 / 原子写 / 指纹 / 置信度 / 降级；补单测。**不接任何现有逻辑**，
  并且顺手修 `:779` 丢弃 format 的 bug。
- 批次 2（需确认后动）：把 `detect_format()` 的「AC 无条件优先」降级为
  「先查标识 → 命中按映射查验 → 未命中按现有 `_probe_format()` 探测 →
  高置信度才补写标识」；`layout_of()` 消费标识路径表；加「不查验完整性」开关。
  这批改 `layout_of` 会同时影响启动 / 补全 / 重建 / 体检，**必须真机双轨验收**。

**状态：已按用户拍板实现（round-179，22:41 之后）**

用户选择：① 标识**写进 `.minecraft`**（不是我推荐的元数据侧）；② **一次做到
自动查验**（批次 1+2 一起）。据此落地：

| 用户方案 | 实现 | 与评审建议的差异 |
|---|---|---|
| 给格式加标识码 | `<mc_dir>/.ac-layout.json`，点开头未知 JSON；内容是**逐项路径映射**而非格式 ID | 按用户选择写进游戏目录；用「点开头 + 其它启动器不读」满足「只对我们生效」。⚠ 代价：外部实例的 `.minecraft` 里会多一个文件，整合包覆盖/清理工具可能删掉它 → 删了就自动降级重探，不影响使用 |
| 先找识别码 → 命中按格式查漏补缺 | `_resolve_layout()` 先 `im.read()`，命中且指纹/身份有效则直接用记录路径；`im.verify()` 返回缺失目录清单（**只读不创建**，真补全仍归 `install_instance`） | 「查漏补缺」实现为可见的完整性报告，不擅自往外部实例建目录 |
| 没查到（或不查验）就跳过 | 设置 → 行为「查验启动格式完整性」开关，关闭后不读不写不查验 | 关闭开关仍保留 AC 自动查验（防错补核心） |
| 没识别码就看特征并补写 | 无标识 → 实时特征探测 → **仅高置信度**写标识；身份/指纹校验保证后续变化自动作废 | 低置信度（特征全 miss 兜底 vanilla）**不写**，避免把一次猜错固化成常驻错误 |
| 默认 AC 识别改自动查验 | `_is_ac_owned()` 不再直接返回 `ac`；目录里出现 mmc-pack.json / minecraftinstance.json / profile.json / instance.cfg 时降级探测 | 保留 round-164「AC 扁平 json 不切根」保护（回归真实抓到过破坏并修回） |

**同批修掉的两个真 bug**：`instances.py:779` `add()` 在 `base` 空时丢弃向导选的
format（「自定义格式没作用」根因）；`core/instance_rebuild.py:146` 把点开头的
`.ac-layout.json` 当版本文件（「无版本文件」误判）。

判据 `tests/test_round179_instance_marker.py`（27 条）已登记 `regress.py`。
**双轨验收仍欠**：真机目检标识生成、外来特征降级、开关关闭、以及把该
`.minecraft` 交给别的启动器仍能启动 —— 详见 CHANGELOG round-179。


---

## 十、加载器选择与版本展示（2026-11-06 23:01 用户提出，待实现）

> 用户原话要点：①「每次选择一个都会导致页面重构？还是什么情况，然后位置就有一些奇怪」；
> ②「下载加载器，看看其他启动器是怎么做的，我们的可以用，但是和其他启动器比差距很大，
> 比如说图标不是公共的那种对应加载器官方样式」；③「默认最高版本你不说版本玩家不知道的」；
> ④「加载器版本你没有区分测试版等」。

### 逐条核实（均已读到代码，非推测）

| # | 位置 | 现状 / 原因 |
|---|---|---|
| 1 | `src/pages_instances.py:1092` `_select_loader` | 每次点加载器卡片都会 `ldver_box.setVisible(show_ldver)`（布局高度突变）+ `_load_loader_versions()`（**无条件重新发 Worker 请求**，即使重复点同一个加载器）+ `_update_path()`；异步回来 `_on_loader_versions()` 再 `clear()` 重建整个 combo。三次布局变化叠加 = 用户说的「页面重构 / 位置奇怪」。另外 `card.set_selected(lid == loader_id and card.isVisible())` 依赖 `isVisible()`，刚 show 的卡片可能状态不对 |
| 2 | `assets/icons/loader_*.svg`（10 个）+ `src/icons.py:62` `_KEEP_COLOR` 白名单 | 图标是**自绘近似 SVG**（如 `loader_fabric.svg` 是手写 path 的绿色方块），不是各加载器官方 logo / 社区通用图标包。`_LoaderCard.__init__` 用 `_pix(f"loader_{lid}", 40)`，缺资源时回退中性色块。smoke 日志出现过 `Cannot open file :/icons/loader_labymod.svg`（QRC 注册与文件清单要一并核） |
| 3 | `src/pages_instances.py:873` `ldver_combo.addItem(t("new_instance.ldver_latest"))` | 第一项只有「最新版」文案、**不带 data**；`selected_loader_version()` 读 `currentData()` 得到空串 → 安装时取最新。玩家完全不知道会装哪个具体版本，也没法确认/复现 |
| 4 | `src/pages_instances.py:150` `_fetch_loader_versions` / `:1167` `_on_loader_versions` | 统一返回 `[{title, meta}]`，**没有 stable / beta / snapshot / preview 字段**，UI 也不分组。Forge 的 recommended vs latest、Fabric loader 稳定版、NeoForge beta、OptiFine preview 全混在一个平铺下拉里。`net_api.py:734` 的 `order={release,snapshot,...}` 只用于 **Minecraft 版本**，别误以为加载器版本已分类 |

### 主流启动器做法（待联网调研后补实证，不要凭印象写）

- PCL2 / HMCL / Prism / Modrinth App 的加载器选择页：官方 logo 资源来源、版本列表是否标注
  `稳定版 / 测试版 / 推荐`、默认项是否显示具体版本号、切换加载器时是否保留滚动位置。
- 需要确认各加载器上游 API 是否直接给稳定标记：Forge `promos` / `recommended`、
  Fabric `meta.fabricmc.net/v2/versions/loader`、NeoForge maven、Quilt、OptiFine preview。

### 建议分组（等用户确认后开干）

- **① 位置跳动**：切换时不再 `clear()` 整个 combo、同一加载器重复点直接复用缓存、
  `ldver_box` 用固定占位高度（隐藏时保留空间）避免布局跳；`_ldver_gen` 已有竞态守卫可复用。
- **② 图标**：换成官方 / 社区通用 logo 资源，核对 QRC 注册与 `labymod` 缺图告警；
  别继续手绘近似 path。
- **③④ 版本展示**：默认项显示解析出的具体版本号（如「最新稳定版 0.16.10」），
  数据源给每个版本加 `channel`，UI 分组或加角标，并允许玩家显式选择测试版。

**状态：✅ 已在 round-180 实现（2026-11-06 23:40）**

| 项 | 实现 |
|---|---|
| ① 页面重构 / 位置跳 | `_select_loader` 加重复点守卫 + 版本结果缓存 + `ldver_box` 高度占位；`selected_loader_version` 改显式标志；选中态去掉 `isVisible()` 依赖 |
| ② 官方图标 | 9 个 `loader_*` 全换上游官方原文件（PNG/SVG/ICO），`icons.py` 支持三种扩展名、QRC 重新生成；Cleanroom 官方无 logo → 删自绘占位；来源/许可见 `assets/icons/LOADER_LOGOS.md`。**主流启动器做法**（Prism 图标主题 / HMCL PNG@2x / PCL2 WPF PNG）已实证写入该文档 |
| ③ 默认最高版本不显示号 | 默认项改为「最新版本 {ver}（推荐）」，data 仍为空（安装取最新） |
| ④ 不区分测试版 | `version_channel()` 从标题识别 beta/preview/snapshot/recommended 并加角标；**纯版本号标 unknown 不加角标**，不假造稳定性 |

**同批额外修**：`async_image.ImageLoader` 重写（原图单缓存 / 去重 / HTTP
状态码检查 / 失败负缓存+退避 / 限并发 / 坏缓存删除 / bump 不吞图），解决
「资源中心有缓存却没图片」；列表描述单行省略、来源标签、下载量人读格式，
详情页封面 88px + `big` 标题类，全部走现有 token 与 `ui_kit` 组件。

判据 `tests/test_round180_ui.py` / `test_round180_icon_cache.py` 已登记
`regress.py`。⚠ 双轨验收仍欠真机目检（切换不跳、版本号、角标、滚动图标
补全率、详情页观感）。


---

## 十一、加载器复用 / PCL 式实例编辑 / 下载页格式选项（2026-11-07 用户提出）

> 用户原话要点：①「加载器你看看其他启动器是什么样的，基本上是一样的，
> 可以复用他们的，不要自己乱找」；②「像PCL一样的实例/版本修改功能呢？
> 就是可以随便加或去除加载器mod等更换」；③「为什么下载时只有选择隔离和
> 目录？为啥看不到启动方式里的各种格式在下载中选择？」

### ① 加载器复用 ✅ round-181 已实现

不再逐个溯源上游官方原图（round-180 的做法被用户纠正）。直接采用 HMCL
`assets/img/*@2x.png` 现成集，8 张 + 2 张官网 favicon；Cleanroom 补齐。
主流做法实证与许可见 `assets/icons/LOADER_LOGOS.md`。

### ② PCL 式实例 / 版本随意编辑 — 现状核实（未授权改动）

| 位置 | 现状 |
|---|---|
| `pages_instances.py:2284` 实例设置 | **已有**但分散：可改名称、游戏版本、加载器、加载器版本、内存、JVM 参数/预设、渲染器、游戏附加参数、版本隔离、自定义目录、分组、Java 强制、启动/退出命令、启动格式 |
| `:2539` 版本变更 | 只置 `version_id=""` + 后台 `_start_instance_download()` 补游戏文件（幂等、保留存档模组），**并没有真正安装/卸载加载器**；`install_loader` 仅存在于 `core/instance_health.py:638` 体检修复 |
| `:2339` `_editable` | 导入实例禁改版本 / 加载器 / 加载器版本三项 |
| `modules_page.py` | 模组禁用 / 删除在这里；实例详情的 Mods / 资源包 / 光影 / 存档四个按钮只是跳转页，不是「在同一面板里勾选加载器 + 加删 mod」 |
| `:1940-1960` 右键 | 有体检、补装依赖、崩溃分析，无「管理加载器」「添加模组」独立项 |

**结论：能力碎片化，且「换加载器」是改字段不是真换**，与 PCL 的整页式编辑差距在
交互聚合与加载器真实安装/卸载，不在字段数量。属功能增强，等用户拍板范围。

### ③ 下载 / 新建时看不到各种启动格式 — 真缺口（未授权改动）

| 位置 | 现状 |
|---|---|
| `pages_instances.py:1352` `current_layout()` | 新建向导的 `dir_combo` 只有 `ac / vanilla / iso / custom` **4 项**，语义是「游戏目录布局」，不是启动格式 |
| `instances.py:311` `INSTANCE_FORMATS` | 9 种：`ac / vanilla / iso / multimc / curseforge / modrinth / custom / auto …`，**只在已建实例的「实例设置」** `pages_instances.py:2394` `fmt_combo` 里出现 |
| `pages_instances.py:2466` | 「隔离 / 目录」是另一组控件（isolation + game_dir_override），与格式无关 |

所以用户在下载/新建阶段只看到隔离和目录，是**格式枚举从未接进新建向导**；
round-179 之前 `instances.py:779 add()` 还会把向导选的 format 直接丢掉（已修）。
另外枚举里**没有 `pcl` 这一项**，用户说的「PCL 等启动器的不同实例」目前只能
落到 `vanilla` / `iso` / `multimc` 近似表达。

**建议（等授权）**：新建向导增加「启动格式」下拉，复用 `INSTANCE_FORMATS` +
`_fmt_keys` 文案，选中结果随 `result_data()` 落到 `add()`；补 `pcl` 枚举与对应
`detect_format` 特征（PCL2 的版本隔离目录 / `.minecraft` 布局）；与 round-179 的
`.ac-layout.json` 标识联动，避免选了格式又被自动探测覆盖。

**状态：②③ 仅登记，未改代码。** 涉及新建向导与实例主链路，按项目约定先问再动。

> **2026-11-07 00:56 用户拍板**：采用**完整版**——新建整页编辑面板，左侧分组导航
> （基础 / 启动 / Java / 目录格式 / 模组 / 资源包 / 存档 / 高级），加载器**真装真卸**，
> 模组增删启停内嵌不跳页。下次开工直接照此实现，无需再确认范围。
> ③（新建向导补「启动格式」下拉 + `pcl` 枚举）同批做。

### ✅ round-183 已实现（2026-11-07 12:xx）

| 项 | 落地方式 |
|---|---|
| 整页编辑面板 | `src/instance_editor.py` · `InstanceEditorDialog`，7 页左侧导航 + `QStackedWidget`；右键「编辑实例」与详情齿轮共用 |
| 加载器真装真卸 | `src/core/loader_swap.py` · `swap_loader`（幂等装 + 清理旧版本目录 + 失败回滚字段）/ `uninstall_loader`（删 `versions/<id>` 退回原版） |
| 模组内嵌 | 面板「模组」页复用 `ModCard`，增 / 删 / 启停 / 打开目录都在面板内 |
| 资源包 / 光影 / 存档 | 面板「内容」页三个列表 + 打开目录 + 删除所选 |
| `pcl` 枚举 | `INSTANCE_FORMATS` 补 `pcl`；`_probe_format` 认 `<mc>/PCL/Setup.ini`；徽章 `#0EA5E9` |
| 新建向导格式 | 目录下拉补 `pcl`，另加一行「启动格式将标记为：…」显式展示结果 |

**未做（有意，非遗漏）**：新建向导不提供 `multimc / curseforge / modrinth` 选项。
这三种是「导入别人已建好的实例」才有的目录特征，新建一个空目录再标成 CurseForge
只会让补全走错分支。需要时走导入或建好后在编辑面板里手选格式。

### ✅ round-183 收尾：真机截图逐页目检后修的六处（2026-11-07 12:5x）

面板能开 ≠ 画得对。用部署目录的两个真实实例 offscreen 渲染七页截图
（`_probe_editor_shot.py` → `_shots_r183/page_0..6.png`）后查出：

| 现象（截图实测） | 根因 | 修法 |
|---|---|---|
| 紫色按钮上的图标只剩一团暗影（放大 4× 才看出是下载箭头） | `make_button` 一律用主题文字色 tint 图标 → 近黑压紫底 | `kind ∈ accent/play/danger` 改用 `on_accent()`（跟随 `text_on_accent`，浅色 accent 自动转深） |
| 「＋ ＋ 添加模组」两个加号 | 文案 `mods.add` 自带「+」，与 `icon_key="add"` 重复 | 新增 `inst.mods_add`（无「+」） |
| 模组空态标题写「暂无可用实例」 | 借用实例列表的空态键 | 新增 `inst.mods_empty_title`「还没有模组」 |
| 高级页游戏目录显示成「\Appdata\AC_Launcher\…」（盘符被吃掉） | 只读 `QLineEdit` 设值后光标停在末尾 → 视图滚到尾部 | `setCursorPosition(0)` |
| `QSpinBox` 右侧多出一根怪线 | 自定义 QSS 没定义 `::up-button`，原生箭头画到框外 | `setButtonSymbols(NoButtons)` + `ui_kit` 全局补 `QSpinBox.wheelEvent`（滚动区里滚轮不再静默改内存值） |
| 「当前状态」拉出半屏灰字墙 | 标签换行 + 值堆叠 | 改两列表格；路径单独段落，字号 11px |

> ☠ **探针陷阱（已踩）**：用 `QTest.qWait` 等后台 `Worker` 会**饿死工作线程** ——
> 等满 12s 后台函数一次都没跑，Java 页恒显「尚未判定」，极易误判成「功能没做」。
> 正确写法是 `time.sleep()` + `app.processEvents()` 循环；换成它之后 0.4s 就填出
> `需要：Java 25 / 将使用：Java 25 · …javaw.exe`。

### ✅ round-183 收尾二：大尺寸图标描边（用户实拍指出「四方圆角图标被遮挡」）

| 现象 | 根因 | 修法 |
|---|---|---|
| 空态 56px 的四宫格图标看起来四块粘成一块、「被遮挡」 | 24px 设计的字形（`stroke-width="2"`）放大 2.33× → 描边 4.7px，而方块间隙只有 4 个单位 → 只剩 4px（gap/stroke = 0.67） | 新增 `icons.pixmap_large()`：按目标**物理像素**反推 SVG 单位描边（只减不增），描边 = `size × 0.06` 夹 [2.6, 5.0]；`empty_state` 与登录页 56px 头像回退改走它 |

**判据**：`tests/test_round183_editor.py` ⑩ 量 56px 渲染的「中缝/描边」比值 ≥ 1.2，
并**先断言旧实现 < 1.0**（证明判据能抓到问题，而不是没数据就通过）。实测 0.67 → 1.50。

**边界**：`_KEEP_COLOR` 里的品牌/状态图（加载器 logo、绿勾、警告三角、太阳）
不参与收细 —— 它们自带配色，重着色会毁掉含义。

> ☠ 教训：检查「图标有没有问题」不能只看**有没有被裁切**，还要看**描边配重**。
> 同一张 SVG 在 18/24px 好看，放大到 48/56px 就会因为描边同比变粗而糊成团 ——
> 大尺寸必须单独渲染，不能把小尺寸位图拉大、也不能让矢量等比放大。

### ✅ round-189：修改页重做（2026-11-07 16:2x）

用户实拍：「我们整个修改太简陋了，而且内容和细节完善度不全面」。差距不在配色，
在**信息形态**：加载器是光秃秃的下拉（logo/说明全藏着）、游戏版本是自由文本框
（能打进不存在的版本）、危险区只有一句 hint。

- 加载器 → **带 logo 的卡片选择器**（新 `src/loader_picker.py`，logo 复用 HMCL
  已整理好的 `loader_*.png`）；过滤后重排，网格不留空洞。
- 游戏版本 → **可编辑下拉 + 「选版本」按钮**（后台拉官方版本列表，走缓存）。
- 加载器版本 → 第一条标「最新」。
- 危险区 → 红字「会删除…」+ 灰字「会保留…」，按钮改 danger 样式。
- 当前加载器卡 → 加 loader logo。

**顺带修的真 bug**：`LoaderPicker.current()` 曾返回「第一个可用的卡」而不是
「选中的卡」——点了 Quilt 程序按原版走。已由新判据钉死。

### ✅ round-197：崩溃页内 / Java 三合一 / 整合包来源（2026-11-07 19:1x）

round-196 登记 7 条未修，本轮做掉 3 条：
1. **崩溃分析页内化**（最后一个还在弹窗的实例功能）；
2. **Java 管理三入口合一**：设置页内嵌唯一管理 UI；新建向导改文件选择器；
   崩溃分析跳设置页 Java 分区；
3. **整合包 / 导入的模组来源记录**：「整合包」/「导入」标记（它们没有可靠
   project_id，但来源要标出来）。

**「壳包面板」两个结构性坑（已修）**：
- `__setattr__` 也要转发（只转发读取 → 状态行永远停在旧状态）；
- QDialog 自带 `done()` 会**遮蔽**面板同名方法 → 显式转发 + **递归守卫**
  （面板 done → closed → 壳 accept → 壳 done → 面板 done = 卡死）。

**仍未修（剩余 4 条）**：商店详情页无「已安装」提示；商店列表页无兼容徽章；
两个诊断对话框标题键相同；实例编辑面板「内容」页无「来源」标记。

### ✅ round-196：全面审计补漏（2026-11-07 18:5x）

把 round-189..195 逐条复查，修掉 6 处漏项（toast 根因、两源不判重、导出页内套
窗口、硬截断残留、「已安装」误报、加载器选择器两套）。

**仍未修（已登记）**：
1. 整合包安装 / 扫描导入的模组**没有来源记录**（列表不标「资源中心」、更新
   检测认不出）；
2. 商店**详情页**没有「已安装」提示；
3. 商店**列表页**没有兼容徽章；
4. **Java 管理三个入口**（实例页/设置页/崩溃分析）都还是弹窗；
5. **崩溃分析**应进实例页内栈（地图/投影图弹窗可接受）；
6. 两个诊断对话框**标题键相同**（`diag.title`）分不清；
7. 实例编辑面板「内容」页没有模组页那样的「来源」标记。

### ✅ round-195：功能统一 + 页面化（2026-11-07 18:2x）

用户三条：描述又被截断 / 同一功能两套页面 / 实用功能用窗口不用换页。

| 问题 | 修法 |
|---|---|
| 模组管理两套页面 | 侧栏模组页改用 `ModListPanel`（与编辑面板**同一个组件**）；删掉旧的 ModCard 列表与独立的「检查更新」按钮 |
| 描述被截断 | 原来按**字符数**砍到 78 → 改按**像素宽度**折两行、随宽度重排、tooltip 给全文 |
| 实用功能用弹窗 | 新增实例页内功能栈：编辑面板 / 体检 / 客户端增强都压到实例页上方，底部按钮改「返回」，页头动作自动收起 |

类改造：`InstanceEditorDialog→InstanceEditorPanel(QWidget)`、
`HealthDialog→HealthPanel(QWidget)`、`EnhanceDialog→EnhancePanel(QWidget)`；
窗口壳保留（内部就是页内面板，同一套实现）。

**仍未改**：导出整合包、崩溃分析、Java 管理、启动诊断、服务器收藏仍是弹窗 ——
下一轮照这套模式改；登录/皮肤库是全局功能，保留弹窗形态。

### ✅ round-194：一键修复安全项的反馈（2026-11-07 18:0x）

用户：「一键修复安全项点了没有用，修补一点提示都没有」。

☠ **真因不是"没做事"，是反馈弹错了地方**：`toast(self, ...)` 在体检对话框里
**回落成模态 `info()` 框**（`win_rounded.toast` 的兜底），而 frameless 对话框
后面弹出的模态框玩家看不见 → 「点了没反应」。而且对话框内本来就有反馈行
（round-163 为单条修复加的），批量修复却没用它。

修法：一键修复改写对话框内反馈行（不弹模态框）+ 逐条捕获异常 + 反馈写清
修了哪几项 + 反馈行做成看得见的条 + 无可修项时 tooltip 说明。

**通用教训**：☠ `toast()` 在**没有主窗口浮层**的对话框里会退化成模态框 ——
凡是自带对话框的场景，反馈一律写进对话框自己的 UI，不要调 toast。

### ✅ round-193：资源中心重做（版本随实例 / 前置 / 下载可见）（2026-11-07 17:4x）

用户四问全部落地：推荐版本随实例走、下载可见、前置可见、下载前询问 + 自动补。

| 问题 | 根因 | 修法 |
|---|---|---|
| 推荐版本不跟实例走 | 拉的是「全量最新 50 条」，兼容版本排在第 50+ 位（Mod Menu 上千版本） | **服务端按实例的 MC + 加载器过滤**；不兼容行压暗并标原因；加「只看兼容」开关 |
| 下载不可见 | 详情页没有进度条 | 详情页加 slim 进度条 + 速度；完成后列出装了哪些文件 |
| 看不到前置 | 依赖信息从没显示 | 详情页「前置模组」区（required 依赖 + 已装/未装） |
| 不询问/不自动补 | 从来没有这一步 | 下载前弹确认（默认装）；选「不装」只下本体（only_self）；装完再体检提示缺前置 |

**实测**：Mod Menu @ 1.20.1 fabric → 版本 50 → 5，推荐 22.0.0-alpha.3（26.4
快照）→ 7.2.2（1.20.1 兼容）。

**仍未做**：列表页卡片级的兼容筛选（要逐个查版本，太贵）；CF 源无依赖信息；
资源中心**版式**还没重做（仍是旧布局）。

### ✅ round-191：中文搜索 / 图标通路 / 模组来源（2026-11-07 17:1x）

| 用户反馈 | 根因 | 修法 |
|---|---|---|
| 模组搜索打中文没结果 | Modrinth 不认中文，本地名库只有约 150 条 | 名库优先 + **翻成英文再搜**合并；☠ 另外修了 MyMemory 把源语言写死 `en`（中译英变 `en|en` 直接报错）的死路 |
| 资源中心好多图标加载不出来 | API 走 requests（直连），图标走 QNAM（**吃系统代理**）→ 系统代理残留就「搜索正常、图标全白」 | 图标代理对齐 `download_proxy`（默认直连）+ 失败退回直连重试一次 |
| 要区分模组下载 | 所有 jar 一视同仁，更新检测靠文件名猜 slug | `core/mod_sources.py` 登记来源 → 列表标「资源中心」+ 更新检测用真 slug |

**仍未做**：翻译兜底依赖 MyMemory 匿名额度（约 1 万字符/天），额度用完时中文搜索
只能命中名库 —— 后续可加重试之外的第二个免费翻译源。

### ✅ round-190：实例图标 + 收藏夹（2026-11-07 16:3x）

PCL 概览「个性化」卡的两项：**图标**与**收藏夹**。

- `instance.favorite`：`sorted_instances()` 统一「收藏置顶 → 分组 → 名称」，
  实例列表与首页网格共用一套顺序；卡片带 ★；概览页切换即落盘。
- `instance.icon_path` + `src/instance_art.py`：图片**复制**进
  `data/instance_icons/<id>.<ext>`（不动原文件），换格式清旧缓存；
  4 MB / png·jpg·webp·bmp 限制，非图片或超限显式报错。
- 卡片（列表 44px / 首页 26px）与概览预览共用 `instance_art.icon_pixmap()`。

**踩到的坑**：dev 模式下 `get_data_dir()` 是 cwd 相对的，测试把实例写进了项目
自己的 `data/`（已清理，测试改为先 chdir 到临时目录）。

**仍未做**：窗口标题/自定义信息（要 launch.py 配合）、登录方式限制（要接登录链路）、
内存「自动配置」全局档。

### ✅ round-188：GC 模式 + 启动前内存优化（2026-11-07 16:0x）

用户补刀：「启动前内存优化呢」。PCL「内存分配」卡还差这一项，补上：

- **内存管理（GC）下拉**：ZGC / 分代 ZGC / 标准 G1GC / 调优 G1GC / 不指定；
  ☠ **显式选 GC 时必须跳过原来的 G1GC 参数组** —— ZGC 与 G1GC 互斥，同时下发
  JVM 起不来。面板上同步把「G1GC 优化参数」复选框置灰。
- **启动前内存优化**：实例 on/off/跟随全局 + 全局开关；启动前
  `EmptyWorkingSet` 裁工作集 + `gc.collect()`，释放 >32 MB 时提示。
  清 standby list 要管理员权限，**不做**（别假装能做全局的）。

### ✅ round-187：编辑面板 8 页重排 5 页 + 功能补齐（2026-11-07 15:3x）

用户：「实例修改页面很难受」「主要不是空，是功能和便捷性和完整性」。

**结构**：概览（名称/状态/ID/快捷方式/导出+补全）· 设置（隔离/格式/Java/内存/参数/
服务器/命令）· 修改 · 模组 · 内容。旧 basic/launch/java/dir/adv 五个页函数退役，
字段一个没丢（`_collect` 读同一批属性）。

**功能补齐**（对着 PCL 设置页逐项核）：
1. 内存可视化条（三段色块）+ 分配超 85% 红字护栏（ctypes 读内存，
   psutil 在本机 venv 是坏的）；
2. 自动进入服务器（`instance.auto_server` → 启动自动追加 --server/--port；
   收藏直连 > 实例字段 > 全局参数）；
3. 补全文件按钮（概览·高级管理，幂等校验 + 重下缺失）。

**仍未做（PCL 有、AC 暂缺，按价值排序）**：游戏窗口标题/自定义信息（要 launch.py
配合，单独一轮）、登录方式限制（仅正版/仅离线，要接登录链路）、实例图标与收藏
（要动首页排序）、GC 显式下拉（ZGC/分代 ZGC，现用 jvm_preset 覆盖）、
内存「自动配置」档（全局已是固定值，要先做全局自动档）。

### ✅ round-186：修改页按版本过滤 + Fabric API 随装（2026-11-07 15:xx）

用户：「下加载器不下配套 fabric api」「修改的选项中会出现不存在的加载器与版本，
而且功能不全，建议仿照 PCL」。

| 项 | 根因 | 修法 |
|---|---|---|
| 加载器下拉出现不存在的加载器 | 直接列 `LOADERS` 全表，从不按 MC 版本筛 | 新增 `core/loader_catalog.py` 可用性目录；修改页按当前 MC 版本重建下拉；**当前加载器永远保留**（否则自己的加载器会"消失"） |
| Fabric 版本列表混进全历史版本 | `mll.fabric.get_all_loader_versions()` 不带 MC | 改走官方 meta 的按版本接口 `net_api.fetch_loader_builds` |
| NeoForge 版本混进别的 MC 版本 | `mll.Neoforge.get_loader_versions()` 是全 MC 大表 | 按版本号前缀裁（20.1.x ↔ 1.20.1）+ 卡「NeoForge 无 19.x」下限 |
| 空列表被当成网络失败 | 只显示「拉取失败」 | 改说「{mc} 没有这个加载器的可用版本」并**禁用安装按钮** |
| 装完加载器没有 Fabric API | 从来没装过 | 修改页加「同时安装 Fabric API」勾选（默认勾，fabric/quilt 时才出现）；装完自动拉对应 MC 版本的 Fabric API 进 mods 目录 |

**边界**：Fabric API 装失败**不会**把「加载器已装好」说成失败 —— 两件事分开提示。

**未做（有意）**：新建向导的加载器卡片沿用它自己的 `_compatible_loaders`（已能按
版本过滤），没改成共用 catalog —— 两套规则目前只在 Quilt/NeoForge 的边界版本上
略有差异（向导略松），改动向导有回归风险，单独排一轮。

### ✅ round-185：模组页重做（2026-11-07 14:xx）

用户：「mod 功能太难用了，建议整个重做，学其他启动器的」。诊断结论：难在
**根本不知道装了什么** —— 名字取文件名、加载器徽章靠文件名子串猜、jar 里的
清单完全不读。

| 项 | 落地 |
|---|---|
| 真实元数据 | 新增 `core/modmeta.py`：fabric.mod.json / quilt.mod.json / META-INF/(neo)forge.mods.toml / mcmod.info → id·名称·版本·描述·作者·图标字节；读不出返回 None 不抛异常 |
| 列表 | 新增 `mod_list.py`：搜索 + 全部/已启用/已禁用/可更新四筛选 + 紧凑行 + 批量条（启用/禁用/更新/删除所选）+ 空态三条路 |
| 选中表达 | 勾选框外加**整行高亮 + 左侧紫条**；复选框本身改成白底 + 紫色对勾（全局 QSS） |

**仍未做**：模组页的「拖 .jar 进窗口即装」、依赖缺失的自动修复提示
（`core/mod_check` 有数据但没接到这个页面）、按 Modrinth 项目对本地 jar 做
「可更新」判定目前仍靠文件名猜 slug（`mod_updater.parse_mod_slug`）。

### ✅ round-184：「修改」页 + 导出 .mrpack（2026-11-07 13:xx）

用户两问：「这里为什么有一个下拉还有 3 个点的省略？」「去看看 PCL 的修改版本
到底是什么再来改」。第一问是缺陷，第二问查证后是**结构问题**。

| 项 | 查证 / 落地 |
|---|---|
| 「⋯⌄」双符号 | `QPushButton("⋯") + setMenu()` 会让 Qt 另画 `menu-indicator`；且 U+22EF 常缺字。改为 `more.svg` 图标 + 全局 `::menu-indicator { image:none; width:0 }` |
| PCL「修改」到底是什么 | 源码 `PageInstanceLeft.xaml`：左侧是 **概览/设置/修改/Mod管理/导出**；「修改」= `PageDownloadModify`，**装/换 Mod 加载器**，不是字段表单 |
| AC 面板 | 新增第 3 页「修改」，游戏版本 / 加载器 / 安装更新 / 退回原版全部搬过去；「启动」页只留内存·JVM·渲染器·性能 |
| 导出整合包 | 新增 `core/mrpack_export.py` + `export_pack_dialog.py`；入口：实例「⋯」菜单、编辑面板「高级」页 |

**格式取舍（重要，别当 bug 修）**：导出的 `.mrpack` 里 `files` 恒为空、内容全部
在 `overrides/`。因为 `files` 每项必须带可直链 `downloads` 与 sha1/sha512，而本地
jar 反查不到 CDN 地址；编假 URL 会让对方导入失败。代价是包体没有 CDN 去重。

**判据**：`tests/test_round184_export.py` 33 条，含**第三方往返**（用
`minecraft_launcher_lib.mrpack` 读回自己写的包，避免「自己读自己」掩盖格式错）。
regress **54/54**；i18n **1807 = 1807**。

**仍未做（有意）**：PCL 的「导出启动脚本 / 补全文件 / 删除版本」三个概览页按钮没搬
（AC 在别处已有等价入口：崩溃分析、重建实例、删除实例）；PCL「设置」页的服务器
填表（认证服务器 / 自动进服）AC 没有对应能力，不硬抄。

**未做（待确认）**：`libraries/` 清理。卸载加载器只删 `versions/<id>`，共享库
原样保留（PCL2 / HMCL 同样不删）——理由是多实例共用同一份库，删了会连带别的
实例；代价是磁盘不会立刻回收。要做成可选「深度清理」需先拿到用户授权。

---

## 十二、客户端增强包与 Java 25 识别（2026-11-07 round-182）

### ① 「不加 mod 直接在游戏里用鼠标手势」——查证结论

用户问的是 Mouse Tweaks（YaLTeR，BSD-3，Modrinth `mouse-tweaks`）。它 hook 容器
界面的 `mouseClicked / mouseDragged / mouseScrolled`，必须知道「光标下是哪个
slot、手里拿着什么、对面是什么容器」。启动器在进程外只有像素，按坐标盲点最坏
**会把物品丢到地上**。→ **启动器层面做不了，只能装 mod**。

已落地为一键装 / 卸（`src/core/enhance.py` + `src/enhance_dialog.py`，实例右键
→「客户端增强」）。清单 14 项分 5 组，Modrinth slug 全部逐个实测存在。

**仍未做（等授权）**：启动器级手势（GestureKeys 式：低级鼠标钩子采笔迹 →
`SendInput` 发按键/命令）。它只能触发按键与命令，不能直接操作 GUI，且要独占
一个触发键——收益与 Mouse Tweaks 不重叠，属另一条产品线。

### ② 为什么「识别不到启动器自己下的 Java 25」——根因已修

两套口径不一致：

| 入口 | 数据来源 | 能否看到自装 JRE |
|---|---|---|
| Java 管理页下拉（round-177 修过） | `java_install.installed_majors()` 读安装记录 | 能 |
| 自动选择 / 启动判定 / 体检 / Cleanroom 安装器 | `core.java.scan_javas()` | **不能**（扫描根里没有 `<data>/java`） |

所以表现为：管理页里看得见、手选能用，但 `java25_path()` 是 None、
`select_java(need=25)` 返回 None → 判「没有兼容 Java」；Cleanroom 安装器退回
「最高的现代 JVM」抓到系统 Java 26。

round-182 已把 `installed_majors()` 并进 `scan_javas()` 且排最前。探针复验：
`java25_path()` 命中、`cleanroom_installer_java()` = Java 25、
`select_java(need=25)` 命中。

**遗留（未修）**：`scan_javas` 有 deep/fast 两档缓存，`install_java()` 装完新
JRE 后**没有主动失效缓存**，最长要等 TTL 过期才出现在自动选择里（管理页下拉
走 installed_majors 所以是即时可见的）。属体验毛刺，登记待办。

### ③ 仍挂着的待办（本轮未动）

- 设置 → 基础的两项新开关（窗口模式 / Gamma）只在**启动前**写 `options.txt`，
  实例自定义 `game_dir` 与版本隔离目录的取值已核对一致，但「同一实例换目录后
  旧 options.txt 残留」未处理。
- `neoforge` 与 `forge` 的 mod 兼容判断只按加载器精确匹配，未处理同时发布两版
  的 mod（如部分 ModernFix 构建）在 neoforge 上找不到 forge-only 依赖的情况。
