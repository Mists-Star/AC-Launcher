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

**新开放项（2026-11-07 22:3x，round-206 更新）**：全项目「难受点」只读诊断见
**§十三**。P0 两条假死与占位页漏英文裸键**已修**（round-206，配 29 项回归断言）；
剩余：P1 弹窗收敛 / IA 路径表覆盖率、P2 反馈与模态毛刺 —— 未修、不在回归覆盖内。

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

### ✅ round-198：加载器版本不再继承不存在的旧值（2026-11-07 19:3x）

用户：「加载器版本会随着第一个所选的版本而切换，而且就算根本不存在也会继承，
而且看不到版本」。

- **继承**：旧值不在新列表时被 `insertItem(0, keep, keep)` 硬插回去 → 改成
  选最新 + 说明「原版本 X 不适用于 Y，已切到 Z」；
- **看不到**：空列表时下拉写「（该 MC 版本没有可用版本）」+ 禁用 + 提示不是网络问题；
- **隐藏放大器**：空列表时保存会把实例的 loader_version **清空** → 现在保留原值；
- 新建向导同样修（空列表时它会假装有「最新稳定版」）。

☠ 断言表达的是**旧行为** —— 改行为就要改断言（round-189 那条"实例当前版本仍在
下拉里"已按新行为重写）。

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

**仍未修（剩余 4 条）**：~~商店详情页无「已安装」提示；商店列表页无兼容徽章；
两个诊断对话框标题键相同；实例编辑面板「内容」页无「来源」标记。~~
→ **round-199 已全部清零**，见下。

### ✅ round-199：六维审计补漏（2026-11-07）

承接 WorkBuddy 接力项，全项目六维复查后把上面 4 条旧账清零，并修掉同类新发现。

| 问题 | 级别 | 修法 | 测试 |
|---|---|---|---|
| 商店详情页无「已安装」 | P1 | 头部徽章 + 跟随「下载到」实例切换刷新；判定收进 `mod_sources.is_installed` | `test_round199_audit.py` |
| 商店列表无兼容徽章 | P1 | Modrinth 搜索自带 `versions`/`categories`，零额外请求画「兼容 / 不兼容」 | 同上 |
| 两个诊断标题同键 | P2 | 启动诊断改 `diag.launch_title`，全局诊断保留 `diag.title` | 同上 |
| 内容页无来源标记 | P2 | 资源包/光影后标「资源中心 / 整合包 / 导入」，文件名存 `UserRole` | 同上 |
| `_dep_installed` 标题前 8 字符包含匹配 | P1 | 统一 `is_installed`；前缀后必须是版本号/加载器（`sodium-extra` 不再冒充 `sodium`） | 运行时反例 |
| 详情简介 240 字硬切、原文 1200 字硬切 | P2 | 像素省略两行 + tooltip 全文；原文完整显示 | 静态断言 |
| 详情来源记录落到旧 `_inst` | P1 | 记到本次真正写入的实例（`_dl_inst`） | 静态断言 |
| 崩溃分析菜单仍开弹窗 | P0 | `_analyze_crash` → 页内 `_show_crash`，全项目只剩一种呈现 | 静态断言 |

**仍未改（需产品或用户决策）**：Java 管理三个入口仍是弹窗；导出整合包、
启动诊断、服务器收藏仍为窗口形态（地图/投影图弹窗可接受）。

### ✅ round-200：实例页入口重构（2026-11-07）

用户反馈「部分功能藏太深了，换入口」。把实例详情页里按实例生效的功能全部提到
一级并按用途分组；启动诊断从 QDialog 改页内面板，与体检 / 崩溃分析同一套栈。

| 问题 | 级别 | 修法 | 测试 |
|---|---|---|---|
| 体检 / 崩溃分析埋在「⋯ 更多」 | P2 | 新增「管理与诊断」2×4 一级网格 | `test_round200_entries.py` |
| 备份 / 还原 / 复制只有右键菜单 | P2 | 同上一级网格第二行 | 同上 |
| 启动诊断仍是 QDialog（同类已页内） | P3 | 新增 `LaunchDiagnosticsPanel`；弹窗壳只包一层，报告判据不复制 | 同上 |
| 名称行主按钮「体检 / 启动诊断」语义混装 | P2 | 改为「编辑实例」，诊断全部进网格 | 同上 |
| 「实例设置」与「编辑实例」两个名字同一功能 | P3 | 统一为「编辑实例」 | 同上 |

**仍未改（本轮明确不做）**：模组启停仍走「内容分区 → 模组」切到模组页；
实例页不新增「启动游戏」按钮（避免第二条启动链路）。

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

## 十三、全项目「难受点」只读诊断（2026-11-07 22:3x，round-205 之后）

> 背景：TRAE round-199..205 停手、工作树尚未提交时，对其**最新代码**做的一次只读
> 全项目扫描。本节**只登记，未改任何源码**；下表每条都已对照 round-205 代码逐项
> 复核，全部仍成立。当时 `regress.py` 为 **73/73 全绿** —— 也就是说这些点
> **完全不在现有回归覆盖范围内**，回归绿不等于体验没问题。
>
> 与前文的关系：§五/§七/§八/§十二 已登记的旧账不重复（见文末）。
>
> **round-206（22:4x）已修**：P0 两条 + 占位页漏英文裸键（本节标 ✅）。
> 新增 `tests/test_round206_no_freeze.py`（29 项断言，已注册 `regress.py`），
> 回归 **74/74**。P1 弹窗收敛 / IA 覆盖率、P2 毛刺**仍未修**。

### P0 — 会表现为「点了没反应 / 假死」  ✅ round-206 已修

> 两条均已落地，详见 `CHANGELOG.md` round-206；下表保留作问题档案与修法依据。

| # | 位置 | 现象 | 根因 / 修法方向 |
|---|---|---|---|
| 1 | `src/main_window.py:5798-5817` (`kill_game`) 与 `:5342-5364` | 点「结束游戏」后界面可能冻住 | UI 主线程里**逐个** `subprocess.run(["taskkill"...], timeout=10)` 串行执行，多开 N 个最坏阻塞 10N 秒；整段 `except Exception: pass` 把失败全吞，玩家看不到「没杀掉」。§七·续只登记了「状态栏闪烁」，没这条。→ 批量 PID / 后台 worker，UI 立刻给「正在结束…」，失败逐项提示 |
| 2 | `src/net_api.py:1717-1734`（round-205 新写） | 搜索快了，但**关启动器可能卡住** | `wait(futs, timeout=8.0)` 后 `shutdown(wait=False, cancel_futures=True)` 不 join；慢 CF 线程最坏跑满 30s 请求超时，解释器退出时被 join 拖住 —— 与 round-203「下载解耦」目标相冲。另外慢网下 CF 结果**静默丢弃**，无「部分结果 / 某源超时」提示，玩家会误判「CF 源没这个 mod」。→ 请求 timeout ≤ 预算、线程 daemon 或复用 executor，返回结构带 `partial` 标记并在 UI 提示 |

### P1 — 页面化没收尾（用户最早吐槽的「启动器分歧感」）

round-195/197/200 统一了一批，但 30+ 处 `.exec()` 仍在，尤其**窗口里再弹窗口**：

- `src/main_window.py:5743-5744`：崩溃 `auto_analyze` 仍 new `CrashAnalyzerDialog` **窗口壳**；手动入口是 `src/pages_instances.py:2181` 的页内 `_show_crash` → round-197 声称「全项目只剩一种呈现」漏了自动路径。
- `src/pages_browse.py:351`：版本页「安装」弹 `NewInstanceDialog` 窗口；实例页新建走页内栈 → 同一「新建实例」两套形态。
- `src/settings_dialog.py:2623`：设置页（页内）里又 `DiagnosticsDialog.exec()`；同一窗口在 `src/main_window.py:4870` 有第二入口。
- `src/login_dialog.py:382` 登录 → 皮肤库窗口；`src/lobby_dialog.py:360`、`src/server_fav_dialog.py:64/193` 同类嵌套。
- `src/crash_dialog.py:373`：`_fix_java` 拿不到主窗口时回退 `JavaManagerDialog.exec()`（round-197 三合一没兜住）。

§四 已写明「导航 `account` 弹模态 `LoginDialog` 是预期」，与以上不冲突：问题是
**同一功能两种形态**，不是「模态本身有罪」。

### P1 — 占位页会漏英文裸键（红线）  ✅ round-206 已修

`src/main_window.py:4020-4027` 把 launch/download 映射到 `pcl2.ph_launch_title` /
`pcl2.ph_download_title`，但 `src/i18n.py:106-110`（英文 `:2162-2166`）**根本没有
这两个键**（只有 online / more / default）；`t()` 缺键回退 `default=key` → 界面直接
显示 `launch` / `download` 这类**英文裸键**（`default` 传的是函数参数 `key`，
不是 i18n 键名 —— 此处修正 22:3x 版登记里「显示完整源码名」的表述）。
body 也误用了 title 键；未映射的 `feature:xxx` 会把内部 key 原样 `setText`。
文案「联机大厅排班中——**主线程**写完就会自己开台」把开发术语写进玩家 UI。
→ 已补齐中英键、body 用独立键、未映射走通用占位文案、去掉开发术语。

### P1 — IA 路径表是「假护栏」

`tools/gen_paths.py` 生成的标记只覆盖 **3 页 / 21 条**（4 个文件；资源中心、版本页、
模组页、登录、诊断全裸）。`tests/check_paths.py` 只查「文档是否过期」，**不查覆盖率、
也不查条目真伪**。已经错了一条：`ia[home]: 点「登录」…打开账户页`，实际
`src/main_window.py:4544` 是弹模态 `LoginDialog`（§四 自己写明了）。回归全绿，表是错的。
→ 检查器加覆盖率下限 + 抽样断言导航行为。

### P2 — 毛刺

- `src/export_pack_dialog.py:231-234`：`toast()` 外面套 `except Exception: pass`，
  窗口壳模式下浮层宿主断链就是**彻底没反馈** —— 与 round-194「一键修复点了没反应」
  同款病，教训没推广到 `src/schematic_dialog.py:203/210`。
- `src/scan_dialog.py:414`：`QProgressDialog` 用 `WindowModal`，复制/扫描期间整个窗口
  锁死，啥也干不了。
- `src/login_dialog.py:456-467`：设备码登录 `webbrowser.open` 失败静默，玩家盯着
  「等待你在浏览器完成授权…」发呆；`:477-489` `_cancel_ms` 只 `wait(6000)` 而
  worker 最长 15min，注释自己承认有 `QThread: Destroyed while running` 风险。

### 已登记旧账（不重复）

310 处静默 `except`、配置快照回滚、Java 25 缓存失效（`install_java()` 装完未主动
失效 `scan_javas` 缓存）、状态栏信号闪烁、CF 依赖树、§三「待用户真机验收」两项 ——
均已在 §五 / §七 / §八 / §十二 登记。

⚠ **排序提醒**：那批里「缺库秒退记成成功」「补库失败吞掉继续 spawn」
「Java 下载 95 分钟」才是真正让人难受的，不宜长期排在 UI 毛刺后面。

### 剩余处理顺序（round-206 之后）

~~P0 两条~~ ✅ / ~~占位页文案~~ ✅ → **弹窗收敛剩余清单** → **IA 覆盖率** → P2 毛刺。
**每一项都要配一条回归断言** —— round-206 已验证这条管用：新增 29 项断言后
`regress.py` 从 73/73 变 **74/74**，这三条修复从此有回归护栏，不会再被
「全绿」盖回去。

---

## 十四、照主流启动器系统对齐（round-208 阶段二已完成，2026-11-07 主理人要求）

> 触发：主理人问「其他启动器为啥可以」，结论是**差别不在网速，在「谁排序」
> 和「要不要等齐」**。round-207 已把搜索链路对齐（服务端排序 + 按源渐进渲染），
> 以下为**剩下的整套做法**，按「能不能自己做完」分三层。
>
> ✅ **阶段一已完成（2026-11-07）**：代码级对照规格
> `docs/specs/round-208-store-alignment/spec.md` —— 实读 Prism / HMCL / PCL-CE 共 57 个源码文件，
> 12 条做法逐条标注 `repo:path:line` + 片段 + AC 落地点 + 断言点；
> 含现状差距清单与 16 条回归断言。**3 个 IA 分歧已拍板（2026-11-07）：
> 真页码器 / 详情保留整页切换 / 默认「全部」双源不变 → 两栏骨架，阶段二照此实施。**

> ✅ **阶段二已完成（2026-11-08）**：见 `CHANGELOG.md` round-208 阶段二与
> `docs/specs/round-208-store-alignment/spec.md`。P0-1 / 3 / 4 / 6、P1 的两栏 IA
> 与 IA 护栏已落地；P0-2 的「默认单源」按主理人拍板**不执行**（保持全部双源），
> 只把来源提升为筛选侧栏一级控件；P0-5 徽章复用既有判定，未另写一套。
>
> | §十四 项 | 状态 | 证据 |
> |---|---|---|
> | P0-1 服务端过滤 | ✅ | `store_search._cf_page_ex` / `_mr_facets`，37 + 54 项断言 |
> | P0-2 默认单源 | ⛔ 拍板否决 | 保留 `all`，来源进侧栏；规格 §4 表 C |
> | P0-3 真分页 | ✅ | `PageSize=40` + 双源游标 + 页码器；删除 `_more` / `_has_more` |
> | P0-4 占位图 / 懒加载 | ✅ | `thumb.setPixmap(fallback)` + `_pump_icons()` 视口泵 |
> | P0-5 徽章 | ✅ | 列表复用 `_is_installed` / `_compat_of_card`，不另写判定 |
> | P0-6 SWR | ✅ | `cache_lookup` 三态 + `store.swr_refreshing` / `swr_keep_old` |
> | P1 两栏 IA / IA 护栏 | ✅ | `QSplitter.count()==2`；IA 4 页 29 条 + 覆盖率真校验 |
> | P1 详情预取 / 共用缓存 | ⏸ 有意不做 | 「共用缓存」已存在：`get_project_info` 与 `cfv:`/`mr-ver:` 版本列表都在 `net_api._cached`（含语言键 + 磁盘缓存），重复打开同一项目本就秒开；详情头用的是列表行数据，首屏不等网络。剩下只有「列表里悬停就预取版本」这一层，**故意不加**：① Modrinth/CF 都有速率限制，翻一页悬停几次就是 6~10 个请求，容易把正常搜索挤成 429；② 收益只在「首次点开」那 200~400ms；③ 要验证它不坏事必须真机联网 A/B，本轮做不到。 |
> | P2 外部授权 | ⏳ 未动 | 不擅自换后端 |

### P0 — 纯本地可做，无需外部账号（推荐先做）

| # | 主流做法 | 我们现状 | 落地动作 |
|---|---|---|---|
| 1 | 版本 / 加载器过滤**下推到服务端**（Modrinth `facets`、CF `gameVersion` / `modLoaderType`） | 详情页拉回全部版本再本地过滤（`net_api.py` 版本请求已带过滤，列表页筛选仍是客户端） | 资源中心按目标实例 MC 版本 / 加载器构造 facets，一次请求只取兼容结果 |
| 2 | 默认**单源** + 显式来源切换，排序 / 分类 / 版本做成侧栏 | 默认「全部」双源合并，卡片流无限滚动 | 来源切换做成一级控件；排序（相关度 / 下载量 / 更新时间）服务端参数化 |
| 3 | **真分页**（上一页 / 下一页 / 页码） | 无限滚动 `_more()` + `_has_more` 闸门 | 翻页控件 + 每页条数，保留缓存键 `(query, offset, limit, ...)` |
| 4 | 图标**占位图先行** + 懒加载 + 图片代理；首屏不等图 | 20 张卡逐个拉 CDN、6 并发、512KB 熔断，字先出图后冒 | 骨架占位 → 视口内才 `load()`；失败负缓存已有，补「优先缓存命中」 |
| 5 | 已安装 / 不兼容**徽章**在列表页直接可读 | 兼容徽章 round-199 已加，已装标记只在详情页 | 列表页统一徽章口径，与实例目标版本联动 |
| 6 | 缓存 `stale-while-revalidate`：先画旧数据，后台刷新 | `_cached` 30min / 磁盘 24h，过期就等网络 | 过期值先返回并标「正在更新」，刷新完增量替换 |

### P1 — 需要版式决策（主理人拍板）

- **资源中心整页重做**：筛选侧栏 / 结果区 / 详情抽屉三栏，参考 PCL2、Prism 的 IA；
  `docs/ia/paths.md` 目前只覆盖 3 页 21 条，重做时必须同步补覆盖率断言。
- **详情页预取**：版本列表 / 前置依赖 / 中文简介在点开前按可见卡片预取，
  现在全是点开后串行请求。
- **下载与搜索共用一份项目缓存**：现在搜索命中、详情、版本各存各的 key。

### P2 — 需要外部账号 / 授权，AI 不能替主理人做

- **CurseForge 官方 API key**：PCL2 / HMCL / XMCL 都向 CurseForge 申请 key 后直连
  `api.curseforge.com`；我们无 key 默认走 `mod.mcimirror.top` 公益镜像（实测
  3.4–7.4s 波动）。需主理人申请后填「设置 → 第三方服务」，再测速决定是否切默认源。
- **国内聚合 API**（如麦块开放 API：自带中文标题 / 简介翻译、`/img` 图片代理、
  ES 相关度排序、精确名优先）：能一次请求同时解决中文、图标、排序三件事，
  但属第三方服务，**商用授权 / 稳定性 / 频率限制需先确认**，不能默认接入。

- **阶段二登记的 3 个未落地筛选项**：发布渠道（release/beta/alpha）、运行环境
  （client/server）、仅开源。上游依据 `prism:ModFilterWidget.ui:226-296`，但
  MR `/v2/search` 命中里没有 channel / open_source 字段，CF 镜像同样不返回 ——
  做成控件就是「点了没反应」的摆设，故**不渲染**。若后续拿到官方 CF key 或
  聚合 API 的对应字段，再补齐并各配一条回归断言。

### 纪律

- 每项配一条回归断言（round-206 / 207 / 208 已验证有效：73 → 74 → 75 → 77 全绿）。
- 改动前先复核「已知结论是否过期」—— round-141「sortField 不起作用」就是
  靠对照实验推翻的，别把历史判断当事实。
- P2 未定前，默认源与镜像行为保持不变，不要为了「像别人」悄悄换后端。

## 十五、round-209 真机反馈两项回归（2026-11-08，已修）

### P0 —「一部分 mod 搜不到，比如 FTB 系列」✅

- **不是网络**：所有请求 HTTP 200。联网 A/B（同一镜像、每次只改一个参数）：
  CF `FTB` 无过滤 409 → 加 `gameVersion=1.20.1+modLoaderType=4` 后 58（-86%）；
  `FTB Quests` 140 → 27 且 `can_next=False`；MR `FTB` 96 → 29。
- 根因：`_collect_filters()` 在玩家什么都没选时把目标实例版本 / 加载器隐式
  下推服务端；`set_target()` 还用 `setCurrentText(v)` 把「提示」变成真实筛选。
  上游 `prism:ModFilterWidget.ui:198-224` / `pclce:PageComp.xaml:33-106` 全是
  **玩家显式选**，规格 §2.3 初版属于误读，已加纠错框并同步断言。
- 修：默认只取侧栏显式值；`set_target()` 改 `setPlaceholderText()`；
  版本 / 加载器仍用于详情页推荐版本与兼容性徽章。
- 复验：默认 `FTB` CF **58 → 409**、MR 29 → 96，官方本体
  `FTB Library / Teams / Quests (NeoForge)` 全回来；`FTB Quests` 27 → 140、
  `can_next` 恢复 True。
- **刻意不改**：Modrinth 排在 CurseForge 前面是
  `pclce:ProjectQuery.cs:604` 的 `.OrderBy(x => x.FromCurseForge)` 同款；
  FTB 整合包在 `classId=6` 下没有本体，属分类边界（切「整合包」即可），
  都不是 bug，不为了「像别人」擅自改已定决策。

### P0 —「一键修复没用 / 修补无反馈」（二次反馈）✅

- 三条入口离屏复现（拦截全部模态框、用 `isHidden()` 而非 `isVisible()`
  校正探针）：崩溃分析只有会被异步覆盖的小灰字且**点击瞬间谎报成功**；
  实例右键**页内零反馈**、只有 frameless 下可能跑到窗口后面的模态框；
  体检反馈条虽在但另写一套样式/逻辑（违反「相同功能同一实现」）。
- 修：新增 `src/fix_feedback.py` 共享 `FeedbackBar` / `report()` /
  `summarize()`；三条入口统一；点击即时可见反馈 + 结构化汇总终态
  （成功 / 失败 / 需手动），失败附逐条阶段明细；占位符不漏进 UI。
- 断言：`tests/test_round209_fix_feedback.py` 24 项，含失败 / 全零 /
  无缺失依赖分支；round-178 / 194 的 3 条旧静态断言按新链路等价化。

### 纪律追加

- ☠ **探针先自证**：`isVisible()` 对未 `show()` 的顶层窗口的所有子控件恒为
  False，直接拿它当「反馈不可见」的判据会得到假阳性；用 `isHidden()`。
- ☠ **异步动作不得在启动瞬间写「已…」文案**：点击到完成之间必须显示
  「正在…」，终态由回调写，否则玩家看到的成功是假的。
- 一键修复只需修「能自动修的」，**剩下的必须明确列出**，不能静默跳过。

---

## 十六、全量审查（2026-11-08 11:1x，round-209 之后 · 只读审查）

> 触发：主理人「审查一遍整个启动器」。**未改任何源码**；本节只登记。
> 基线：HEAD `a8335bb`、工作树干净、`origin/main` 同步；部署版 exe
> `sha256 5C0019EC…` 与 `dist_beta/AC_Launcher` 逐字节一致，`_internal`
> 4184 : 4183（唯一差是运行期 `_startup.log`）。
> 三轨结论：`regress.py` **79/79**（i18n 2000=2000、PII zero residual、IA 4 页 29 条）；
> 部署版离屏冒烟 8s 存活、`crash.log` 无新增；**但真机日志与运行期探针仍抓到
> 回归覆盖不到的活问题** —— 又是一次「全绿 ≠ 没问题」。

> ⚠ **范围更正（主理人 11:41 指出）**：本节初版把资源中心写成了主角，
> 编排偏了。**本次审查对象是整个启动器**：按 8 个域分工逐文件扫过
> （① 资源中心 ② 启动/安装/下载 ③ 账号/认证/隐私 ④ 设置/主题/更新
> ⑤ 导航/页栈/IA ⑥ 实例/备份/导入 ⑦ 模组/内容 ⑧ 构建/文档/门禁），
> 覆盖矩阵见 **§16.6**；资源中心只占其中 1 个域。
> **§16.1 是资源中心域，§16.5 起才是其余 7 个域** —— 后者的 P0 更严重
> （点一下就崩 / 更新起不来 / 回滚丢档），返工顺序以 **§16.7** 为准。

### 16.1 资源中心域发现（按级别，均带判据）

| 级别 | 位置 | 问题 / 证据 | 可测量判据 / 修法方向 |
|---|---|---|---|
| **P0** | `src/mod_list.py:217,252` ↔ `src/store_detail.py:841,1392-1416` | **异步回调无 Qt 对象生命周期守卫**。部署版 `data/crash.log` 共 733 条，其中 **705 条** `RuntimeError: libshiboken: QLabel already deleted`：`store_detail.py:1122`(410) / `:849`(269) 属 11-07 旧 exe，`mod_list.py:252`(26) **最后一次 2026-11-08 10:35:38，当前版仍在复现**。本地离屏强制派发 `DeferredDelete` 后调 `ModRow._relayout_desc()` 已 100% 复现同一异常。`QTimer.singleShot(0, self._relayout_desc)` 无守卫；`_track/shutdown()` 只 `requestInterruption()` 不 disconnect，回调仍可触碰已删 `versions_lbl` | 项目内已有正解：`src/pages_browse.py:759` 用 `except RuntimeError: continue  # 卡片已被 deleteLater`。给 `_relayout_desc` / 所有 worker 回调加 `isValid()` 或 RuntimeError 守卫；`shutdown()` 断开信号。修完必须真机切页 10 次后确认 crash.log 零新增 |
| **P0** | `src/pages_browse.py:965-985` ↔ `:884-891,945-947` | **迟到源补卡只加 UI，不写回规范状态**。`_append_source_rows()` 只改 `_mods` / `_vbox` / status，不写 `_store_results`、`_store_cursors`、`_can_next`、页码器、`_store_swr`，也不重应用 `hide_installed`。后果：① 翻页时迟到行从累积集消失；② SWR 缓存的是「不含迟到行」快照，之后 fresh 命中永久丢数据；③ 勾「隐藏已装」后迟到回调把已装 mod 加回来（点了没反应）；④ 状态栏停在 `store.partial_loading` 不再回终态。触发器是 §16.1 第三条超时回调 | 离屏桩 `_is_installed` 恒 True + `_append_source_rows([m])`，断言 `m in _mods`（成立=缺陷）、`m not in _store_results`；再 `_goto_page(1)` 断言 m 消失。修法：迟到行走与 `_on_loaded` 同一套状态写回 / 或统一走「完整结果重渲染」 |
| **P1** | `src/store_search.py:249,256,277,390` ↔ `pages_browse.py:820` | **`total == -1` 让页码器无限翻空页**。中文搜索两条名库回退路径都返回 `total=-1`，`store_can_continue()` 把它当「还有」，`can_next` 恒 True。实测 `page1 hits=0 can_next=True`、`page5 hits=0 can_next=True` | 区分「本轮继续尝试」与「还有下一页」：`can_next` 用 `len(results) > target` 或已知 total 判定；**别直接改 `store_can_continue`**，`tests/test_round208_store_search.py:249-251` 已把 -1 允许继续钉成契约（单轮语义正确） |
| **P1** | `src/pages_browse.py:670-694,849-852,890-891` ↔ `store_search.py:87-99,228-232` | **SWR fresh 自我续期 + 键不一致**。fresh 分支 `_on_loaded(snap, reset)` 默认 `swr=False` → 又调 `_store_swr(data)` 刷新 `time.time()`，同一 key 30min 内反复命中即「永远 fresh」，revalidate 永不触发；freshness 是盘上 `{"n":N}` marker、数据本体只在内存 `_swr_cache`，两者分裂。且 `_swr_key`/`filters_key` 缺 `language` / `hide_installed` / 目标实例 → 切语言、勾隐藏已装、换目标实例都命中旧快照**不发 HTTP**（`_request_key` 含 hide_installed 反而放行去重，短路发生在它之后） | `p0=p._swr_key(); p._filters['hide_installed']=True; assert p._swr_key()==p0`（成立=缺陷）；桩 `search_store_page` 计数验证第二次 `_load` 不请求。`r208:` 单源缓存键同样缺语言 |
| **P1** | `src/store_search.py:338,348-355,363-386` | **8s 预算后 daemon 线程仍在写共享对象**。实测 `_SEARCH_BUDGET=0.01`、源 `sleep(0.06)`：函数已返回 `hits=0 / partial=True`，60ms 后 `on_source` 仍回调 `['Modrinth','CurseForge']` → 页面可能已切走/销毁，或往已渲染页补卡（即上一条 P0）。另 `box.items()`(`377`) 与线程 `box[k]=...` 并发，理论上可抛 `RuntimeError: dictionary changed size during iteration`（**静态分析，未离屏复现，不写成已证实**）；`net_api.search_all:1652` 预置两键只读下标，没有这个 race | 超时后给线程结果一个「不再回灌」标记，或把 `box` 换成每线程独立 return + 队列；`on_source` 回调带 gen 且页面销毁即丢弃 |
| **P1** | 历史开放项（§五/§六/§八 复核后**仍成立**） | ① `launch.py:1094-1128` 补库失败吞掉继续 spawn，`main_window.py:5242` 无条件 `last_session.record(...,"ok")` → 缺库秒退记成成功；② `launch.py:1068-1082` classpath 用 vroot、补库基准用 `mc_dir/libraries`，`..` 开头缺失库整批跳过；③ `launch.py:816-909` / `core/install.py:143-145` Java 判据仍四套（`java_plan()` 只被 `instance_editor.py:916` 消费）；④ `worker.py:365-379` 异常+取消时三个终态信号一个都不发、`_cancel_requested` 仍是裸 bool；⑤ 配置仍是 4 份长生命周期快照 + 整文件覆盖；⑥ `store_detail.py:1187-1193` CF 直下无依赖树；⑦ `launch.py:1144-1157` 缺前置只提示不拦截 | §十三 的排序提醒仍然有效：这几条才是真正让人难受的，**不宜长期排在 UI 毛刺后面**。逐条配行为断言（不能只查源码字符串） |
| **P1** | `pages_browse.py:358`、`settings_dialog.py:2623` + `main_window.py:4873`、`crash_dialog.py:389`、`main_window.py:5744-5748` | **弹窗收敛没收尾**（用户最早吐槽的「启动器分歧感」）。全仓 35 处 QDialog `.exec()`；同一功能两套形态仍存：版本页「安装」弹 `NewInstanceDialog`（实例页走页内栈）、诊断对话框页内+主窗口双入口、`_fix_java` 回退弹 `JavaManagerDialog`、崩溃 auto_analyze 仍是窗口壳（虽已改 NonModal `show()`） | 登录 / 皮肤库 / 地图 / 投影图是约定保留的全局模态，**不是缺陷**；只收敛上面 4 处 |
| **P2** | `src/fix_feedback.py:28-58` ↔ `crash_dialog.py:208`、`mod_check_dialog.py:120-122`、`pages_instances.py:2040-2066` | 主题切换后 `FeedbackBar` 颜色不更新（无 `on_theme_change`，`_TONE_COLOR['info']` 是 import 时冻结合照，ok/warn/busy 硬编码 hex）；三条修复入口只有两条 attach 真 FeedbackBar，第三条走 4.5s 浮层 toast、宿主断链时仍可兜到模态 —— 与「统一实现」宣称有偏差 | `bar.show_message('x','info'); theme.set_theme_mode('dark'); assert bar.styleSheet()==old`（成立=缺陷） |
| **P2** | `tests/test_round208_store_alignment.py:135-153`、`test_round208_store_search.py:48-54`、`test_round209_store_regression.py:145-147` | **回归里有假断言 / 覆盖盲区**。`:140` 只查源码里有没有 `"key == self._last_request_key"`，删掉去重逻辑仍通过；`search.py:53` 断言的是 docstring 一句注释；`regression.py` 把 `na._cached/_stale` 全 mock 成 None，导致 SWR fresh 短路路径**从不进入**（正是 §16.1 第四条逃逸原因） | 这是「79/79 全绿但仍有 P0」的直接解释。修 bug 前先把对应断言换成行为判据，否则新行为会被旧断言挡住 |
| **P3** | `AGENTS.md:38-66`、`RELEASE_1.0.0_CHECKLIST.md`、`CHANGELOG.md` | 文档过期：AGENTS 仍写「当前开发主线 2026-09-25 / round 99-103 待做 / 编号从 99 起」，实际已 round-209；发布清单 A 组两项仍未打勾（真机新建实例启动到主菜单、真机首启目检，AI 做不了）；CHANGELOG 375 KB 单文件。另 `main_window.py` 5940 行 / `i18n.py` 4377 行 / `net_api.py` 2901 行，192 处 `except...: pass`（旧文写 310 处，口径不同） | 协作者 TRAE 会照 AGENTS 排期，优先同步；发布清单两项标注「待主理人真机」而非空白 |

### 16.2 复核：这些**不是** bug，别再当开放项修

| 旧账 | 复核结论 |
|---|---|
| 状态栏三路信号交替刷（§七·续） | ✅ round-177 已加 `_bind_status_worker` / `_unbind_status_worker`（`main_window.py:3139-3176`） |
| Java 下载 95 分钟 / 取消删掉已装 jre-25 | ✅ round-177 已接 USTC 镜像 + Range 续传（`core/java_install.py:126,226`）+ 删前判 `java.exe` 存在（`:310-313`） |
| 微软 token 无刷新 / 离线 UUID 为空 | ✅ 已有 `refresh_microsoft()`（`core/auth.py:316`）；离线 UUID 现为 12 位内部 id（`accounts.py:29-30`）。⚠ 但「无 `expires_at` 判据、无条件刷新」与「非规范 `OfflinePlayer:<name>` UUID v3」仍缺，属残留 |
| `find_missing_dependencies` 只比 modid 字符串 | ✅ round-201 已加 `canonical_id()` + `provides`（`crash_analysis.py:463-493`）；**版本区间 / Forge 约束仍不解析**，这半条仍成立 |
| 切来源后复用旧快照 | ✅ round-209 已把 `source` 纳入 `filters_key`，且 `test_round209_store_regression.py:267-270` 有断言 |
| `_prepare_natives` 缺 on_repair / `needs_convert` 死字段 | 仍成立，但 §五 里 `i18n.py:1360` / `pages_instances.py:2153` 两处 UI 引用已不存在，行号过期 |
| 陈旧 `ac.lock`（PID 27608 无对应进程） | ✅ 不是 bug：`main.py:223-239` 的 `QLockFile.setStaleLockTime(30_000)` + 窗口探测接管。实测第二次冒烟锁 PID `27608 → 7120`、7s 存活、crash.log 零新增 |

### 16.3 本次附带处理（非源码改动）

- 主理人要求「备份删掉（有 bug 的版本不要）」→ 已删 5 份旧版备份共约 **5.2 GB**：
  部署目录同级 3 份 `AC_Launcher_prev_20261107_230232` / `_20261108_003832` /
  `_20261108_110908`，仓库 `dist_beta/` 2 份 `AC_Launcher_prev_20261108_003642` /
  `_110742`；前 3 份里后两份含 `data/` 旧副本，已按「直接删除」确认执行。
  删前校验当前版 exe 与构建产物 sha256 一致；当前 `AC_Launcher/`、`data/`、
  `dist_beta/AC_Launcher` 及无关的 XAMPP 备份全部保留。
- `AC_LIVE=1` 时启动器会起 `127.0.0.1:8788` 的本地控制面板（`src/aclive.py:489,1098`，
  `/ctl` 为 POST 控制口，无 token）。绑定 loopback 且**只在显式开 AC_LIVE 时启用**，
  默认不监听；若将来常态化开启需补鉴权。

### 16.4 建议返工顺序（等主理人拍板，本轮不动手）

1. **Qt 生命周期守卫**（真机还在刷 crash.log）+ **迟到回调状态写回**（会丢数据）；
2. **分页无限空页 + SWR 键/续期**（资源中心，且需先把 `test_round208_store_search.py:249`
   的契约断言改成区分两种语义）；
3. **把假断言换成行为判据**，否则 1/2 的修复会被旧断言挡住；
4. 历史 P0/P1：缺库秒退记成功 → classpath 基准 → Java 判据统一 → ProgressWorker 终态；
5. 弹窗收敛 4 处 + AGENTS / 发布清单同步。

> ☠ 双轨验收欠账未变：以上全是代码轨 + 离屏/日志轨，**没有联网真机跑「搜模组 →
> 下载 → 启动到主菜单」**。发布清单 A 组两项仍待主理人真机执行。

---

### 16.5 其余 7 个域的发现（**全启动器的主战场**）

> 三条轨道：源码逐域扫描 + 可复现探针（用 venv 直接调函数）+ 代码确证。
> 标 **【实测】** 的是我本地跑过并拿到结果的；标 **【静态】** 的是读码确证但未运行时复现。
> 与 §16.1 不重复，也不复述 §五/§六/§八 已登记旧账。

#### 16.5.1 P0 — 点一下就崩 / 直接丢数据

| # | 域 | 位置 | 问题 | 证据 |
|---|---|---|---|---|
| 1 | 设置 | `src/settings_dialog.py:2429,2449` | **「导出设置 / 导入设置」两个按钮必然崩**：`from . import _SENSITIVE_CFG_KEYS`，`src/__init__.py` 是空文件、包内无此属性也无同名模块。导出处 import 在 `try` 内被吞 → `:2434` 变 `UnboundLocalError`；导入处 import 在 `try` 之前 → 直接冒泡。设置备份/迁移功能完全不可用 | **【实测】** `ImportError: cannot import name '_SENSITIVE_CFG_KEYS' from 'src'`。修法：把键集合提到模块级常量或独立的 `src/core/cfg_keys.py` |
| 2 | 启动 | `src/launch.py:245-256,281-295` ↔ `src/settings_dialog.py:62,85` | **`jvm_preset=aikar` 与 `gc_mode=zgc/zgc_gen` 同时下发 `-XX:+UseG1GC` 和 `-XX:+UseZGC`**，JVM 直接拒绝启动、秒退。注释 `:279-280` 自己写明互斥，但 `_gc_explicit` 只保护 `perf_g1gc` 组（`:301-315`），**漏了预设组**；两个下拉在设置页可独立同时选 | **【实测】** `build_options(..., jvm_preset="aikar", gc_mode="zgc")["jvmArguments"]` 同时含 `UseG1GC` / `UseZGC`。修法：预设组也纳入 `_gc_explicit` 跳过，或 UI 互斥置灰 |
| 3 | 实例/备份 | `src/core/backup.py:135-163` ↔ `pages_instances.py:2123-2129` | **「还原备份」不是事务**：先摘共享池联接 → `os.listdir(mc)` 全量删（含 mods/config/saves）→ 再 `shutil.copytree`。中间任何失败（磁盘满 / 只读 / 文件被游戏占用）**既不回滚也不重建联接**，`error` 回调只 `warn()`。另外语义是「清空+覆盖」，快照之后新建的存档/新装 mod/新配置全部静默删除，确认框（`restore_confirm + restore_warn`）**没写这一句** | **【静态·代码确证】** 全函数无 `try/except`，`ensure_dirs()` 在 `:163` 才执行。判据：桩 `copytree` 抛 `OSError`，断言 `saves/W/level.dat` 已消失且 `libraries` 不再是联接。属**不可逆数据丢失**，优先级高于本表其它条目 |
| 4 | 下载完整性 | `src/net_api.py:511-529,567-580` | **分片下载把「服务端忽略 Range 返回的 200」当该分片成功**：`:513` 允许 `(206,200)`，`:516-529` 从偏移 `s` 写入整个 body、只按写入字节数判完成，各段互相覆盖；无 `expected_sha1` 的路径直接 `os.replace` 成正式文件。probe 阶段 `:448-452` 有 200 回退单流，**`_worker` 内部漏了同一判断**。5 个调用点未传 hash（`core/install.py:499,711,721,833`、`net_api.py:2388`）→ 客户端 jar / 整合包静默损坏，且下次 `isfile` 判「已装」跳过修复 | **【静态·代码确证】** 与 `core/java_install.py:236-237` 的正确处理形成对照。判据：让某分片返回 200 + 完整 body，落盘文件 sha1 ≠ 远端 |
| 5 | 更新 | `src/core/update_install.py:245-255` | **升级脚本在「确认新 exe 真能运行」之前就删掉备份**：`Expand-Archive` → `Test-Path $exePath`（只查存在）→ `:251-252` 删 `.upd_bak` → `:253` 才 `Start-Process`。`catch` 回滚（`:256-269`）只在解压/改名抛异常时触发；「exe 存在但启动即崩」不抛异常，**备份已没了** → 一次坏更新让启动器永久起不来，只能手工重装 | **【静态·代码确证】** 修法：先 `Start-Process` + 短时存活探测，成功后再删备份 |

#### 16.5.2 P1 — 功能错 / 隐私与合规

| 域 | 位置 | 结论 |
|---|---|---|
| 认证 | `src/core/auth.py:331,341` ↔ `:46-73`、`src/brand.py:30` | 微软静默刷新把 `client_id` 硬编码成 `MICROSOFT_CLIENT_ID=00000000402b12d1`，而登录走 `get_active_client_id()`（默认 `ba522940-6118-4c81-82f1-7e5dd304d5e0` 或玩家自填 Azure ID）→ **凡用内置/自定义 client_id 登录的账号，refresh_token 换不到新 token**，静默续期与皮肤上传 401 重试必然失败。**【实测】** 两值不同；`refresh_current_silently` 全项目唯一调用点是 `skin_dialog.py:564`，启动链路根本不调 |
| 启动 | `main_window.py:5817-5822` ↔ `:5496-5568` | 点「结束游戏」后 `kill_game` 直接 `_game_poll_timer.stop()` + `_game_procs.clear()`，**跳过 `_poll_game` 的全部退出回收**：窗口不弹回、退出命令不执行、控制台无结束标记、`last_session` 永远停在 `ok` |
| 启动 | `launch.py:779-780` ↔ `core/dl_gate.py:71-77`、`main_window.py:2697-2762` | 下载闸门两处断链：`wait_free` 超时**无条件 release 别人的锁**（全局 `discard` 不认持有者）；`claim` 成功后到 `w.start()` 之间无 `try/finally`，中途抛异常则闸门永久占用，该实例此后所有启动被 `download_busy` 拒绝 |
| 启动 | `core/loader_swap.py:138,145-162` | 换加载器失败只回滚 3 个内存字段：`version_id` 被清空、`old_vid` 取了却从未用，磁盘半成品 `versions/<id>/` 不清理 → 下次 `isfile` 判「已安装」跳过重装 |
| 安装 | `core/install.py:420-457` | `.mrpack` 覆盖安装做了 mods/config/options.txt 备份却**从不还原**（备份失败还静默 `pass`），中途失败则 mods 已被部分覆盖且无人认领备份 |
| 安装 | `core/mirror.py:1205-1248,1309-1317` | `_resume_mll_download` 在 `sha1=None` 时零完整性校验：`.part` 无来源标记、416 分支直接 `os.replace` 残件、无 hash 时不比 `start+got` 与 `total` → 版本 json / assetIndex 可能被截断后成正式文件 |
| 下载 | `net_api.py:2376-2382` | **`download_optifine_to` 是全仓唯一没走 `_safe_filename` 的网络文件名落盘点**（其余 8 处都走了）→ 页面被污染返回 `../` 可写穿目标目录 |
| 启动 | `launch.py:238,257-264` | 玩家在 `jvm_args` 写 `-Xmx2G` 会覆盖预设堆参数，但 `-Xms` 仍按 `ram_mb//2` 算 → `8192M` 时得到 `-Xms4096M -Xmx2G`，JVM 拒绝启动且 UI 无提示 |
| 账号/隐私 | `accounts.py:116-119` ↔ `win_dpapi.py:48-67`、`README.md:59` | DPAPI 是「尽力而为」：`enc is None` 时 token **原样明文**写进 `data/accounts.json`，无提示。README 宣称「磁盘密文」不成立 |
| 隐私 | `log_mask.py:24-44` ↔ `core/support_bundle.py:51-53,95-141`、`crash_analysis.py:363` | 脱敏只识别 `accessToken `（关键字+空格）一种形态，`token=` 参数默认空且两个导出通道都没传。`"accessToken":"…"` / `refresh_token=…` / `Authorization: Bearer …` 全部原样进可对外分享的诊断包 |
| 隐私 | `settings_dialog.py:40-45` ↔ `core/support_bundle.py:38-41` | 敏感配置键两处各写一份且**已漂移**；`redact_config` 对非敏感字符串只做 `mask_launch_text` → `download_proxy`（可含 `user:pass@`）、`ms_client_id`、`update_manifest_url`、一批自定义绝对路径都会随 `config.json` 外带 |
| 隐私/合规 | `README.md:62-63`、`terms.py:18,21` ↔ `net_api.py:1241-1341`、`launch.py:974-975`、`skins.py:188-229` | **「零数据上传 / 仅与 Mojang 官方 API 或你指定的服务器通信」被证伪**：翻译把最长 5000 字玩家文本发 `translate.googleapis.com` / `api.mymemory.translated.net`；外置登录启动时后台自动打 `api.github.com` 查 authlib 更新；登录成功后自动拉皮肤到 `crafatar.com` / `mc-heads.net` 等。全库 58 个 host 里**未见遥测/统计域名**，「零遥测」本身无反证，但「无任何数据上传」不成立 |
| 构建 | `build.py:118`、`.gitignore:9`、`README.md:91` | `AC_PiTest_noupx.spec` **本机存在（10012 B）但 `git ls-files` 为 0**（被 `*.spec` 忽略）→ 换机 / 新 clone 跑 `python build.py` 直接失败；README 写的 `python build_main.py` 文件不存在。构建不可复现，spec 的 `datas=` 也因此无法审计 |
| 导航 | `main_window.py:4759-4763` | pcl2 布局切语言时 `_pcl2_select_top()` 已切到正确子页，紧接 `stack.setCurrentIndex(STACK_INDEX.get(_pcl2_active_top,0))` 又覆盖；顶栏 key（`launch/download/...`）与 `STACK_INDEX` 键（`home/instances/...`）不同名，除 settings 外全回退 0 → 顶栏高亮「下载」、侧栏高亮「资源中心」、内容却是首页 |
| 导航 | `main_window.py:1951` ↔ `pages_instances.py:2950-2953` | 首页切当前实例直调 `inst_mgr.set_current()` **不发信号**，其它页面仍显示旧实例；实例页走 `current_changed.emit()`。两个页面同时指向不同实例，后续操作可能落在错误实例 |
| 实例 | `pages_instances.py:2005,2300-2308` ↔ `:1885,2955-2974` | 「删除实例」两套入口：右键确认框**不显示将删路径 / 无警告**、删后不清 `_selected_id`、不发 `current_changed`；详情按钮三项都做。IA 标记只挂前者 |
| 实例 | `core/backup.py` 同上、`instances.py:1116-1130` | 删除实例 `rmtree(..., ignore_errors=True)` 吞失败，元数据仍无条件移除 → 列表里没了、磁盘上留着含存档的目录 |
| 模组 | `modpack_import.py:147-177,326-329` | `_record_pack_sources` 声明并接收 `project_ids`，函数体却硬写 `"project_id":"" / "slug":""` → **CF 整合包所有 jar 的 slug 恒空**，`slug_map()` 返回空字典，round-197 的「精确来源」承诺落空 |
| 模组 | `mod_updater.py:61-70,124` / `:154-168` / `mod_list.py:575-597` | 更新检测「第一个返回 id 的候选即采纳」可能命中同名不同项目；仅比文件名判可更新；批量更新备份失败就 `os.remove(old)`，新旧两份 jar 并存导致 duplicate；启停用 `os.replace` **覆盖已存在的 `.jar.disabled`**，批量还静默吞 `OSError` |
| 性能 | `mod_list.py:443-482` ↔ `core/modmeta.py:186-223` | 40+ jar 时 `reload()` 在 **UI 主线程**逐个 `zipfile` 解清单，且每次销毁重建全部行 → 首次打开 / 批量变更后界面卡住 |
| 导入 | `modpack_import.py:242-322`、`scan_dialog.py:457-482` | CF 整合包**先落盘注册实例再下载**，失败留半成品且元数据已入库（Mrpack 弹窗反而会清理）；复制模式导入失败**静默改成就地 link**，把玩家原目录变成 external 实例，无二次确认 |
| IA 护栏 | `tools/gen_paths.py:38-39,76-82` ↔ `main_window.py:100-103` | `REQUIRED_PAGES` 只有 4 页、`MIN_PATHS_PER_PAGE=3`，而 `STACK_INDEX` 有 **8 个主页面**；`mods / versions / lobby / toolbox` 零标记，`--check` 仍 exit 0 → round-208 补的「覆盖率护栏」实际只覆盖 50% 主页面 |

#### 16.5.3 P2（摘）

- 更新 manifest 无 `expires` / 单调版本链 → 旧签名清单可无限重放（`core/update_trust.py:82-93,145-146`）；`_check_url` 只验 scheme 不验域名（`:176-189`）。**Ed25519 验签链本身完整、私钥不入库**，别误伤。
- `lobby.py:45-48` 非原子写 + `_load()` 遇损坏静默返回空 → 断电全量丢大厅；`:89-97` 加入不校验人数 / 不去重，`max_players=8` 从未被读。
- `apply_wrapper` 用 `list2cmdline` 拼进 `cmd /c`，未转义 `& | ^ < >`（`launch.py:125-129`）；authlib 配置是**全局共享文件**，多开不同外置登录服务器会互相覆盖（`:321-346`）。
- `download_optifine_to` 之外：`batch_download.make_download_task` / `download_modpack_to` 都不传 `expected_sha1`；**全仓无 sha512 校验**，只有 sha512 的 Modrinth 文件零校验；两条路径是坏文件已 `os.replace` 后才复核 hash。
- `Java` 下载全程无 hash（只用 `zipfile.is_zipfile`），同一 major 无并发锁；`install_java()` 装完仍未失效 `scan_javas` 缓存（§十二 旧账，仍成立）。
- `DownloadQueue.shutdown` / `BatchDownloader.cancel` 中断不了**在途** `download_file`（只遍历队列里的），关窗 4s drain 后 `os._exit` 强杀 → `.part` 残留、任务中心无终态。
- `last_session` 在「取消启动」后永久停在 `starting`（枚举里根本没有 cancelled/ended）；空 `inst.id` 的多开进程统一归到 `_unknown` 且第二个直接 return，成为无人监控孤儿。
- `login_dialog.py:456-467` 设备码 `webbrowser.open` 失败静默（§十三 已登记）；`skins.py:40-45,148-160` 对玩家粘贴 URL 无 scheme/host 限制（可请求本机内网）。
- `i18n.t()` 缺键最终回退 **key 原文**（`i18n.py:4357-4367`）；静态键全命中（zh/en 各 2000、1299 个静态字面键零缺失），但 `onboarding.py:519` 等处动态拼键无护栏。
- `server_favorites.py:91-99` 编辑时留空端口会清空已存端口；`instance_editor.py:1067-1084` 删内容回退用显示文本拼路径（注释自己警告过不能这么做）。
- `pcl2` 占位页下 `_current_page_key()` 回退 `instances`、任务召回可能落错页；`_pcl2_goto` 对 `account` 无 else 分支静默返回（**静态，未真机复现**）。

#### 16.5.4 已核对**无问题**的路径（证明是全量扫，不是只挑毛病）

更新信任链 Ed25519 验签 / key_id 白名单 / 严格 JSON / size+sha256 三重校验（`core/update_trust.py:152-190,238-369`）；条款门禁 fail-closed（`main.py:300-338`）；支持包不夹带 `accounts.json` / `skins.json` 且 zip 原子写；`launcher_config.json` 原子写、语言/主题切换即时生效**不需重启**；`win_dpapi` 实现本身正确（失败才返回 None）；i18n 双语键对称、静态键零缺失；`core/utils.py:41-59` 与 `modpack_import.py:254-273` 的 zip-slip 双重防护；`loader_swap._inside()` 的 commonpath 越界与 external / 原版目录保护；`mrpack_export` 跳过软链 + 体积上限；`async_image.py:164-199` 用 `shiboken6.isValid()` 包住所有 QLabel 写入（**正是 §16.1 该抄的正解**）；`shared_libs` sha1 判重 + junction 回滚；`core/mirror.py:412-432` 把 mirror/proxy 收进 InstallContext，并行安装不再互相污染；`main_window.py:3139-3176` 状态栏信号归属（旧账已修）；`main.py:591-630` 退出清理与 `os._exit`；`main_window.py:5039-5061` 同实例多开护栏。
⚠ 第三方 `minecraft_launcher_lib` 内部（Forge processors / natives exclude / `mrpack.install_mrpack` 的 overrides 解压）**未读源码，标未核实**。

---

### 16.6 覆盖矩阵（8 域 × 结论）

| 域 | 主文件 | 新发现 | 状态 |
|---|---|---|---|
| ① 资源中心 | `pages_browse` / `store_search` / `store_filter` / `store_detail` / `net_api` 搜索段 | §16.1：P0×2、P1×5、P2×2、P3×1 | 已审 |
| ② 启动·安装·下载 | `launch` / `core/install` / `core/java*` / `core/mirror` / `downloader` / `batch_download` / `worker` / `main_window` 启动段 | §16.5：P0×2、P1×8、P2×6 | 已审 |
| ③ 账号·认证·隐私 | `accounts` / `core/auth` / `core/authlib` / `win_dpapi` / `log_mask` / `skins` / `login_dialog` | §16.5：P1×5、P2×2（含实测 client_id 不一致） | 已审 |
| ④ 设置·主题·更新 | `settings_dialog` / `theme` / `onboarding` / `core/update_*` / `terms` | §16.5：P0×2、P1×1、P2×2 | 已审 |
| ⑤ 导航·页栈·IA | `main_window` 导航段 / `frameless` / `win_rounded` / `ui_kit` / `effects` / `docs/ia` + `tools/gen_paths` | §16.5：P1×2、P2×2 | 已审 |
| ⑥ 实例·备份·导入 | `pages_instances` / `instance_editor` / `instances` / `core/backup` / `scan*` / `modpack_import` / `mrpack_export` | §16.5：P0×1、P1×5、P2×2 | 已审 |
| ⑦ 模组·内容 | `mod_list` / `modules_page` / `core/modmeta` / `mod_check` / `mod_sources` / `mod_repair` / `mod_updater` | §16.1 P0（ModRow 生命周期，与①共享）+ §16.5：P1×4 | 已审 |
| ⑧ 构建·文档·门禁 | `build.py` / `AC_PiTest_noupx.spec` / `regress.py` / `tests/` / `AGENTS.md` / `RELEASE_*` / `.gitignore` | §16.1 P2（假断言）、§16.5 P1（spec 未入库 / 隐私宣称） | 已审 |

**全仓规模**：369 个受控文件、源码约 70.5k 行（`icons_rc.py` 7.2k / `main_window.py` 5.9k / `i18n.py` 4.4k / `pages_instances.py` 3.4k / `settings_dialog.py` 3.1k / `net_api.py` 2.9k）；35 处 QDialog `.exec()`、192 处 `except...: pass`、TODO/FIXME 0。`regress.py` 79 项全绿，但 **79 项里含源码字符串存在性断言**（§16.1 P2），且 8 个域的新 P0 **一项都没被覆盖**。

---

### 16.7 返工顺序（**取代 §16.4，以本节为准**）

1. **数据安全 P0**：备份回滚事务化 + 确认框写明「将删除快照后新增文件」→ 分片下载 200 分支 → 更新脚本先验证再删备份。这三条会造成**不可逆丢档 / 装坏包 / 启动器报废**。
2. **点一下就崩 P0**：设置导出/导入的 import → aikar+zgc 互斥 → 微软刷新 client_id → 异步回调生命周期守卫（§16.1 P0，真机还在刷日志）→ 迟到回调状态写回。
3. **资源中心**：分页无限空页 + SWR 键/续期（修前先把 `test_round208_store_search.py:249` 的契约断言改成区分两种语义）。
4. **把假断言换成行为判据**（`test_round208_store_alignment.py:140`、`test_round208_store_search.py:53`），否则 1–3 的修复会被旧断言挡住；并给 IA 护栏补到 8 页。
5. **隐私/合规**：DPAPI 失败不静默明文、`log_mask` 覆盖全部凭据形态、敏感键清单合并、README/条款文案对齐实际域名。
6. 历史 P0/P1（缺库秒退记成功 → classpath 基准 → Java 判据统一 → ProgressWorker 终态）→ 弹窗收敛 4 处 → AGENTS / 发布清单同步。

> §16.7 提出时**只登记、未改源码**；§16.1 的 16.4 顺序作废。
> 2026-11-08 12:xx 主理人「行」→ 已执行第 1、2 批（七条 P0）+ 第 4 批的行为断言，
> 明细见 **§十七**；第 3、5、6 批仍为开放项。

---

### 16.8 主理人问答：`ac.lock` 有什么用

| 项 | 结论 |
|---|---|
| 它是什么 | `main.py:212-255` 的**单实例互斥锁**，Qt `QLockFile` 写的 67 字节小文件，内容 = PID / 应用名 / 主机名 / UUID（本机当前是 `27608 / AC_Launcher / MISTS-STAR / 9ad20f1d…`）。**不是存档、不含账号或配置**，删了不丢玩家数据 |
| 为什么要有 | 防止双击 exe / 卡住的进程再开第二个窗口（历史「双页」bug）。第二个进程 `tryLock` 失败 → `_raise_existing_instance()` 按品牌名找窗口并 `SetForegroundWindow` 提升已有窗口后退出；**连拿到锁的情况也会再扫一遍窗口**（round-96 修「教程背后露出页面」） |
| 放哪 | `get_config_path("ac.lock")` = **exe 同级目录**（`src/paths.py:42-44`），所以部署目录里能看到它；配置本体是 `launcher_config.json`，玩家数据在 `data/` |
| `ac.live.lock` | `AC_LIVE=1` 时用独立锁文件，让调试/live 实例与玩家正常启动器**并存**（`main.py:222-223`）。这解释了第一次冒烟没碰 `ac.lock` |
| 残留怎么办 | 正常退出会 release；强杀 / 崩溃会残留。`setStaleLockTime(30_000)` + 窗口探测 → 30s 后自动 `remove()` 接管（`:224,234-239`）。**实测**：陈旧 PID 27608 无对应进程，第二次冒烟锁 PID 变 7120、7s 存活、`crash.log` 零新增 → 设计内正常，不需要手工删 |
| 能删吗 | 启动器**没在跑**时删没有副作用，下次启动会重建；**运行中别删**（会让第二个实例乘虚而入，造成双开写同一份数据） |

---

## 十七、round-210：§16.7 第 1、2、4 批返工（2026-11-08 12:xx，已改源码）

> 主理人「行」= 按 §16.7 顺序开工。**本轮范围**：数据安全三条 P0、
> 点一下就崩四条 P0、以及「先补行为断言再改代码」。
> **未动**：资源中心分页/SWR 与迟到回调（第 3 批）、隐私/合规文案（第 5 批）、
> 历史 P0/P1 与弹窗收敛（第 6 批）。**未打包、未部署、未提交**。

### 17.1 七条 P0 的处置

| # | §十六 条目 | 现状 | 落点 |
|---|---|---|---|
| 1 | 备份还原先 rmtree 后 copytree、无事务 | ✅ 已修 | `src/core/backup.py:122` 两阶段事务 + `_clear_contents` / `_move_contents`；确认框 `i18n.py:920,3069` 补「新增文件也会被删除」 |
| 2 | 分片把 200 当成功、坏 jar 落盘 | ✅ 已修 | `src/net_api.py:511` 严格 206 + Content-Range 起点 + 段长**相等**判定 |
| 3 | 升级先删 `.upd_bak` 再 Start-Process | ✅ 已修 | `src/core/update_install.py:247` `-PassThru` + 3s `HasExited` 验证通过才删备份 |
| 4 | 设置导出/导入 `from . import _SENSITIVE_CFG_KEYS` | ✅ 已修 | `src/settings_dialog.py:2422,2445` 改用本模块 `:40` 常量 |
| 5 | aikar+zgc 同时下发 G1GC/ZGC | ✅ 已修 | `src/launch.py:44` `normalize_gc_flags()`，在 `build_options` 返回前统一清理 |
| 6 | 微软静默刷新 client_id 硬编码不一致 | ✅ 已修 | `src/core/auth.py:273,316` 记录签发 ID + 优先复用 + 保住 refresh_token |
| 7 | ModRow QLabel 生命周期崩溃（真机 705 条） | ✅ 已修 | `src/mod_list.py:217,244` `_relayout_desc_safe` + `RuntimeError` 守卫 |

### 17.2 行为断言（不再只看源码字符串）

`tests/test_round210_p0_regression.py`，46 项，已登记 `regress.py`：

- **故障重放**：`copytree` 注入 `OSError` → 逐文件比对旧内容原样搬回、暂存区不留；
  假服务端首请求 206、后续 200 → 断言回退 `_allow_parallel=False` 且无 `.part`/dest；
  正常 206 → 断言不回退且拼出的字节与源完全一致（**反向对照**，防止把好路径改哑）。
- **真实对象**：离屏 `SettingsPage()` 真调 `_export_settings` / `_import_settings`
  （patch 掉文件对话框、模态与 `save_config`），断言导出 JSON 无敏感键、
  导入不合还原密钥、不吞未知键。
- **产物级判据**：真生成 PS1 比 `-PassThru` / `HasExited` / `verified` / `Remove-Item $Bak`
  的先后顺序，catch 回滚分支仍在。
- **矩阵与边界**：`aikar|auto × zgc|zgc_gen|g1_tuned|""`，默认 Aikar 组完整；
  mock `requests.post` 校验 client_id 与 refresh_token；强制 `DeferredDelete` 后调
  异步重排不抛、销毁前重排仍真改写文本。

### 17.3 仍然开放的边界（诚实登记，别当已修）

- `gc_mode="none"`：语义是「不指定 GC」，但 `aikar` 预设仍会带 `UseG1GC`；
  若玩家同时手填 `UseZGC` 仍可能冲突。`normalize_gc_flags` 对 `none` 目前恒等
  （保守不动），需要产品先定义「none 是否覆盖预设」再改。
- `refresh_microsoft` 的 `_TOKEN_REFRESH_URL` 仍是 `/consumers/` 租户，与设备码登录
  端点一致；玩家自建的多租户 Azure app 是否要换 `/common/` 未验证，本轮不动。
- 备份事务的暂存区在 `mc_dir` **同级目录**；若该盘在同一时刻写满，
  「搬回」也可能失败 → 此时暂存区会保留供人工恢复，但不会自动找回。
- 自更新 3s 存活判据是保守近似：新 exe 若因单实例锁/用户主动关闭在 3s 内退出，
  会被判失败并回滚到旧版（可再更新），不会造成启动器报废。

### 17.4 门禁结果

`regress.py` **80/80**（新增 1 套）；i18n 中英 **2000=2000**；PII `zero residual`；
文案门禁禁用词 0 / allowlist 38 条无过期；IA `4 页 / 29 条 / 0 错误`；
8 个改动模块 `py_compile` 全过。

**运行轨（源码级）**：`AC_NO_TERMS=1 QT_QPA_PLATFORM=offscreen python main.py`
离屏跑 8 秒存活（`timeout` 124 = 被外部杀，非崩溃）；`_startup.log` 记录
`MainWindow built` → `nav ok` → `tray ok`，证明 8 个改动模块没把主窗口带崩；
部署版 `data/crash.log` 零新增（157025 字节不变），源码侧未生成新 crash.log。

> ⚠ 这次运行轨用的是**源码**，不是部署产物：`D:\Appdata\AC_Launcher` 仍是
> round-209 的 `a8335bb` 打包版，本轮修复**尚未进 exe**。

> ☠ 双轨验收欠账**未变**：以上都是代码轨 + 离屏/日志轨，
> 没有联网真机跑「搜模组 → 下载 → 启动到主菜单」；也没有重新打包部署。
> 发布清单 A 组两项仍待主理人真机执行。

---

## 十八、round-211：整体设计比对 + 第 3/5/6 批（2026-11-08 13:xx）

> 主理人：「先 c/p，然后整体设计比对一下，一起干了」。
> 设计比对产物 = `docs/specs/round-211-design-alignment/spec.md`
> （8 域 × 上游源码，含证据边界：域 5–8 上游快照零覆盖，明确标「未核实」）。

### 18.1 已修（对照 §16.7 第 3/5/6 批）

| 批次 | 条目 | 落点 | 判据 |
|---|---|---|---|
| 3 | 中文搜索未知总数导致无限空页 | `store_search.py:273` 两态 `store_can_continue` | 空页/超时 `can_next=False`，有结果仍 True |
| 3 | 缓存键漏语言 / 隐藏已装 | `store_search.py:87` `filters_key` | 切语言 / 勾选后 key 与 HTTP 请求都变 |
| 3 | 8s 超时后迟到回调写共享容器 | `store_search.py:335` `abandoned` 冻结（仍 emit 保渐进渲染） | 返回后 `cursors/results` 不被写；慢源仍 emit |
| 3 | 迟到回调未写回分页状态 | `pages_browse.py:1015` 写回 `_store_results`；`(gen,key)` 联合判据 | 错 key 不污染；补卡进 results |
| 3 | SWR fresh 恒真 | `pages_browse.py:849` fresh 命中不重写 signet | 命中后 `_store` 调用 0 次 |
| 3 | IA 护栏只覆盖 4/8 页 | `tools/gen_paths.py:38` + 12 条新标记 | 8 页 / 41 条 / 0 错误；`STACK_INDEX` 口径一致 |
| 3 | 4 条假断言 | 3 个测试文件 | 换成运行时判据（连发去重 / 错 key 丢弃 / 补卡入 results） |
| 5 | DPAPI 失败静默明文 | `accounts.py:108` 不明文 + 原子写 + `LAST_SAVE_DEGRADED` | 桩加密失败 → 磁盘无明文；`os.replace` 失败旧文件不变 |
| 5 | 脱敏只认 1 种形态 | `log_mask.py:74` 5 种形态 | 5 种原值全不出现，首尾 5 位保留，普通文本不误伤 |
| 5 | 敏感键两份且漂移 | `support_bundle.py:38` 唯一口径 + 别名 | 两处集合相等；代理/Azure/私有源全 redact |
| 5 | 条款与 README 宣称被证伪 | `terms.py:11` v2 + `README.md` | 正文含翻译/GitHub/皮肤 CDN，删「仅 Mojang」 |
| 6 | 补库基准错位 | `launch.py:1099` 改 `vroot/libraries` | AST：赋值基准含 vroot、不含 `inst.mc_dir` |
| 6 | Worker 异常+取消无终态 | `worker.py:365` 补 `cancelled` | 取消丢异常：cancelled=1、error=0、finished=0 |
| 6 | 教程 reject 不提交却 mark_done | `onboarding.py:774` 先落盘再标记 | 顺序契约 + 异常分支不标记 |

### 18.2 明确未做（等拍板 / 风险过高）

- **结构性差距 Top5**：资源平台接口层、统一返回栈、缓存收口、实例资源对象、
  依赖三态模型 —— 见规格 §2，属架构改造。
- **产品语义**：缺库秒退记 `degraded`、启动前缺前置是否拦截、Java 四套判据统一、
  `save_config` merge-on-write。
- **CF 依赖树**（`store_detail.py:1180`）：改下载契约，会撞 `test_round178/201`。
- **弹窗收敛 4 处**：QDialog 壳被 `smoke_all.py` + 4 套测试钉住，需单独一轮页内栈改造。
- `refresh_microsoft` 仍用 `/consumers/` 租户（与设备码登录一致），多租户 Azure app 未验证。

### 18.3 门禁 / 打包 / 部署

- `regress.py` **81/81**（新增 round-211 一套 37 项）。
- i18n 中英对称、PII zero residual、文案禁用词 0、IA 8 页 41 条 0 错误。
- 打包：`BUILD_RC=0`，**118.3 MB / 4185 文件**（trim 有 85 个翻译文件被沙箱
  批量删除保护拦住，只瘦了 31 个 / 5.3 MB，产物可用）。
- 部署：`D:\Appdata\AC_Launcher` exe sha256 `51931bf5…` 与产物一致，
  `_internal` 4184 文件，`data/` 与 `launcher_config.json` 保留。
  ⚠ 部署时 `Start-Process robocopy` 在 PS 5.1 报「字典关键字冲突」导致首次
  未复制（旧目录已改名）→ 改 `& robocopy` 直接调用后补齐；**部署脚本以后
  一律直接调用 robocopy，不要过 Start-Process**。
- 冒烟：部署版离屏 9s 存活（timeout 124 = 外部杀），`crash.log` 零新增，
  `_startup.log` 走到 `nav ok` / `transparent ok` / `tray ok`。
- 旧版保留在 `AC_Launcher.exe.prev_r210` + `_internal_prev_r210` +
  `dist_beta/AC_Launcher_prev_r210_20261108`（未删，等主理人确认）。

---

## 十九、round-212：补审「从未被测试/审查碰过」的 40 个文件（2026-11-08 14:xx）

> 主理人质疑「确定整个启动器全部东西审查完了？」→ 机器核算：114 个 .py / 70,609 行里
> 28 个 / 8,137 行从未进过审查记录，23 个模块从未被任何测试引用。
> 本轮分 5 组只读审查（账号皮肤联机 / 扫描模块安装 / 地图投影 / 视觉窗口 / 调试通道与下载），
> 关键结论逐条亲自复现后才登记。

### 19.1 P0（正常使用即可触发）

| # | 结论 | 证据 | 状态 |
|---|---|---|---|
| 1 | **EasyTier 可执行文件从 5 个源（含 4 个第三方反代）下载后零校验解压并 `Popen`** —— 任一镜像被投毒即等于任意代码执行；同仓库 authlib 有固定 sha、更新包有 Ed25519，唯独这条没有信任根 | `core/easytier.py:38-44,92-127,164-170`（grep 无 `sha256/hashlib/signature`） | ✅ 已修（round-213：`EASYTIER_ZIP_SIZE/SHA256` 取自 GitHub Releases API 的 asset digest，先校验再解压，`.verified` 标记才可信） |
| 2 | **视频壁纸每次 `apply()` 泄漏一套 QMediaPlayer + QAudioOutput + QVideoSink**（以 `self` 为父，永不释放），旧视频句柄不关 | `wallpaper.py:870-873,820-837`；探针：apply 5 次 → `findChildren` 各 5 个，`_teardown_dynamic` 后仍 5 | ✅ 已修（round-213：stop→setSource(QUrl())→输出置 None→deleteLater+断信号；现 1 套 / teardown 后 0） |
| 3 | **启动画面在 MainWindow 构建期 100% 空白**：`QElapsedTimer` 只创建不 `start()`，`elapsed()` 实测 `-9.2e12` → `_phase` 恒 0，字母/进度全不画 | `splash_window.py:72`；探针 `isValid=False, elapsed=-9223359610726` | ✅ 已修（构造时 `start()`） |

### 19.2 P1（有前置条件但可达 / 后果重）

| # | 结论 | 证据 | 状态 |
|---|---|---|---|
| 1 | **authlib `.version` 让固定 sha256 永久失效**：只要 `.version` 文件存在就直接信任，而每次启动都会用「zip 能打开」的新 jar 覆盖固定版 | `core/authlib.py:171-176`、`launch.py:1006` | ✅ 已修（round-213：删掉 `_version_of/latest_authlib/_fetch_to` 整条旁路，固定版 + 固定 sha 是唯一信任源） |
| 2 | **`skins.json` 一条坏记录让启动器完全打不开**：`raw.get` / `raw["id"]` 不在外层 except 覆盖内，而 `main_window` 在 import 期构造单例 | `skins.py:72-86`、`main_window.py:43`；探针 `null→AttributeError`、缺 id→`KeyError` | ✅ 已修（逐条 isinstance/必填键校验） |
| 3 | **NBT 的 List 嵌套无深度上限**：2000 层 `TAG_LIST` 抛 `RecursionError`（非 `NbtError`），调用方 `except NbtError` 接不住 | `core/nbt.py:172,193`；探针复现 `RecursionError` | ✅ 已修（`payload` 加 `MAX_DEPTH` 检查，现抛 `NbtError`） |
| 4 | **条款对话框勾选后按 Enter = 直接退出启动器**：两个按钮都是 autoDefault，Enter 命中第一个（quit） | `terms_dialog.py:57-66`；探针 `quit auto=True / continue auto=True` | ✅ 已修（`quit.setAutoDefault(False)` + `continue.setDefault(True)`） |
| 5 | **`aclive` 无鉴权且 loopback 不是浏览器边界**：不校验 Origin/Content-Type，任意网页可用 `text/plain` 简单请求跨源 POST `/ctl`（含 `exec`），WS 也不校验 Origin → 可读屏 + 注入键鼠 | `aclive.py:362-378,381-404,489,1020-1034`；实测 `import_module('os')` 可穿透黑名单 | ✅ 已修（round-215：token + Origin 校验，跨源 403 / 缺错 token 401，控制端与面板同步带 token） |
| 6 | **地图解析失败被吞成「全透明 PNG」并写进缓存**：玩家看到一张看似正常、实际空白的地图，且被 mtime/size 键固化 | `core/world_map.py:148-151,415-423` | ✅ 已修（round-214：`chunks==0 and failed>0` 返回 None；`.meta` 升 3 值，旧格式判无效重渲染） |
| 7 | **`map_dialog` 包围盒只取最近 16 个 region 的极值**：两张相距 8000 方块的 region 就能申请 2.7 GB QImage → 无提示全白画布 | `map_dialog.py:50-57` | ✅ 已修（round-214：只铺锚点周围连续 4×4 窗口 + 256 MB 硬上限） |
| 8 | **BGM「顺序/随机播放」实际是单曲无限循环**：`setLoops(Infinite)` 在 `__init__` 设死后从未随 mode 变化 | `core/sound.py:84,121-129` | ✅ 已修（round-216：`set_mode()` 同步 `setLoops`，loop=Infinite / 其余=Once） |
| 9 | **扫描面板关闭后 Worker 不取消不等待**，回调落到已 `deleteLater` 的面板上；扫描体全程无中断点 | `scan_dialog.py:232-239`、`scan.py:553-646` | ✅ 已修（round-216：`should_stop` 轮询 + `ScanPanel.shutdown()`，关窗 0.01s 停线程且不再回调） |
| 10 | **「一键导入全部+复制」对同一个共享 `.minecraft` 的每个版本各整份复制一次**（无去重、无 ignore） | `scan_dialog.py:511-545`、`instances.py:1047-1088` | ✅ 已修（round-216：按目录去重 + 只有成功才标记已导入；顺带修了「失败也标已导入、行内按钮禁用无法重试」） |
| 11 | **旧版主题包转换绕过 id 校验**：`"id":".."` 会把两个 json 写进启动器 `data/` 根目录 | `modules.py:323-326`（对照 `:240` 走 `validate_manifest`） | ✅ 已修（round-216：`_safe_module_dir()` + legacy 包补 `_RE_ID` 校验；卸载前也校验目录归属） |
| 12 | **联机网络密钥明文落盘，且无 secret 时回退成邀请码**（邀请码本来是发人的） | `lobby.py:31,45-48,80`、`lobby_dialog.py:320` | ✅ 已修（round-215：DPAPI 加密落盘 + 原子写 + secrets，禁止回退邀请码） |
| 13 | **EasyTier 节点生命周期绑在对话框可见性上**：关窗即拆网卡，而模态期间无法启动游戏；强杀启动器则节点成孤儿 | `lobby_dialog.py:440-443`、`main_window.py:4880` | ✅ 已修（round-216：改非模态单窗口 `show()`，可边联机边启动游戏；关闭时给「保持联机 / 断开并关闭」确认） |
| 14 | **下载进度回调在 Worker 线程直接改 `QProgressBar`** | `lobby_dialog.py:391-394`（lambda 由 `easytier.py:105` 在工作线程调用） | ✅ 已修（round-215：类级 `Signal(int)`，Worker 只 emit） |

### 19.3 P2（择要，完整清单在各组的审查记录里）

- 单流续传只看 `206` 不看 `Content-Range` 起点（`net_api.py:302-305`，与 §17.1 分片修复是两条路径）；
  `416` 分支把「比远端还大」的 `.part` 当成品（`:295-300`）；批下载 sha1 失败不删坏文件，下次被「大小相同」判成功（`batch_download.py:61-68`）。
- `downloader.py` 全仓无生产调用方；`_DEFAULT_QUEUE` 在 `main.py:607` 取导入期值恒 `None` → 关窗钩子从未接上。
- `proc_kill` 部分成功被报成整体失败（`failed` 恒等于全部 PID）。
- `skins` 下载无大小上限、两条路径不校验 PNG 魔数；`file` 字段可 `..` 越界删（`skins.py:104-106,166`）。
- ~~`map_cache` 只增不删~~ ✅ round-216（同块留最新 + 每维度 128 块 + 整树 256 MB）；`repair_log.json` 非原子写；`achievements._save` 无异常保护且非原子。
- `win_rounded` 每次确认框在父窗口留一只隐藏 QDialog；`launch_dialog` 关闭后不销毁、部分槽无 `RuntimeError` 保护。
- `icons.screen_dpr()` 取主屏 DPR → 副屏 150% 下头像/状态图标发虚。
- 条款对话框没走深色标题栏；`win_acrylic` 的 import 保护是假的（非 Windows 直接 ImportError）。
- `memopt` 的「已释放 XX MB」恒为 0（返回值被丢弃）；`sfx_*` 音效是未接线功能。

### 19.4 本轮已修 4 条（均带复现判据）

`splash_window.py:72`（时钟 start）、`terms_dialog.py:57-66`（Enter 目标）、
`skins.py:72-86`（坏记录跳过）、`core/nbt.py:172`（List 深度上限）。
复验：`clock_valid=True / elapsed=0`、三种坏 JSON 均 `OK skins=0`、
深 List 抛 `NbtError: 递归深度超过上限：64`、`quit auto=False / continue default=True`。

> ☠ 双轨验收欠账不变：本轮是静态 + 离屏探针，没有联网真机跑完整链路。

---

## 二十、round-213：§十九 里 3 条安全/资源 P0·P1 的修复（2026-11-08 14:xx）

| 级别 | 条目 | 修法 | 复验 |
|---|---|---|---|
| **P0** | EasyTier 从 5 个源（含 4 个第三方反代）下载 exe 零校验直接 `Popen` | `easytier.py:46` 加 `EASYTIER_ZIP_SIZE` + `EASYTIER_ZIP_SHA256`（值取自 **GitHub Releases API asset digest**，非镜像自算）；下载后**先校验再解压**；校验通过写 `.verified`，`find_easytier` 只信任带标记的副本 | 假 zip 正确 size/sha → 通过；错 sha → `发布包 sha256 校验失败`；错 size → `大小不符`；旧未校验 exe 自动判不可信 |
| **P0** | 视频壁纸每次 `apply()` 泄漏 QMediaPlayer/QAudioOutput/QVideoSink | `wallpaper.py:820` `_teardown_dynamic` 改 `stop → setSource(QUrl()) → setVideoOutput(None) → setAudioOutput(None) → deleteLater()` + 断信号 | 改前 apply 5 次 = 5/5/5、teardown 后仍 5；改后 **5 次只剩 1 套、teardown 后 0** |
| **P1** | authlib `.version` 旁路让固定 sha256 失效，且每次启动用「zip 能打开」覆盖 | `core/authlib.py` 删 `_version_of` / `latest_authlib` / `_fetch_to`；`ensure_authlib` 只认固定版 + 固定 sha；`update_authlib` 改为「确保固定版存在且校验通过」 | 坏 jar + `.version` + 离线 → `None`（旧实现返回该 jar）；sha 匹配 → 返回路径；三个死函数已不存在 |

**本轮未修**：`aclive` 无鉴权 / 不校验 Origin（要同时改 `tools/aclive/live.py`
控制端加 token，否则调试流断；默认不启用）。

---

## 二十一、round-214：地图链三条 P1（2026-11-08 14:xx）

| # | §19.2 条目 | 修法 | 复验 |
|---|---|---|---|
| 1 | 解析失败被吞成「全透明 PNG」并写缓存 | `world_map.render_region` 返回 4 元组（多一个 `failed` 槽位）；`chunks==0 and failed>0` → 返回 `None`；`load_region_image` 的 `.meta` 升级为 3 值，旧 2 值 / broken 缓存判无效重渲染 | 造「slot 指向坏数据」的 region → 渲染与取图都 `None`，不写缓存 |
| 2 | 包围盒只取最近 16 个 region 的极值，可申请 2.7 GB QImage | `map_dialog.build_tiles` 改为锚点周围**连续 4×4 窗口**；无 region 时只画最近一个；`_MAX_CANVAS_BYTES=256MB` 硬上限 | `r.0.0` + `r.50.50` → 画布 `1024×1024`（旧实现会是 26112²） |
| 3 | 切世界/维度后旧 worker 结果覆盖画布 | `_load_gen` 递增 + 闭包带 gen，`_on_tiles/_on_error` 丢弃旧 gen | 投递旧 gen → 画布保持空；当前 gen 正常上屏 |

`tests/test_schematic_tools.py` **76 项全过**（新增 4 条）。

**§19.2 剩余项**：BGM 顺序播放、扫描面板 Worker、一键导入复制 N 份、模块 `id=".."`、
EasyTier 节点生命周期、`map_cache` 只增不删、区块级解压上限 —— 全部由 round-216
结清（见 §二十三）。

---

## 二十二、round-215：`aclive` 鉴权 + 联机密钥（2026-11-08 14:xx）

| # | §19.2 条目 | 修法 | 复验 |
|---|---|---|---|
| 1 | `aclive` 无鉴权、不校验 Origin：任意网页可 `text/plain` 跨源 POST `/ctl exec`；WS 不受同源限制 | 每次启动生成 `token_urlsafe(24)` 写 `<data>/aclive.token`；GET/POST/WS 统一 `_reject()`：跨源 **403**、缺/错 token **401**，`hmac.compare_digest` 比较；控制端 `--token` / `AC_LIVE_TOKEN` / 读文件；面板从 URL 取 token 并带 header / `?token=` | 真起 server：坏 Origin+对 token→403、无 token→401、对 token 同源→200、面板无 token→401 |
| 2 | 联机 `secret` 明文落盘 + 无 secret 时回退邀请码 + 非原子写 + `random.choices` | DPAPI 加密（失败不写）、`tmp+os.replace`、`secrets.choice`、`_lobby_from` 过滤未知字段、`join_lobby` 去重、路径函数内取 | 磁盘无明文且带 `dpapi:`；解密回读一致；重复加入成员仍 1；`[]` / 未知字段不崩 |
| 3 | 下载进度在 Worker 线程改 `QProgressBar` | 类级 `Signal(int)`，Worker 只 emit | 类信号存在且连接 `et_progress.setValue` |
| 4 | 成员列表硬编码中文 | `lobby.member_you` / `lobby.member_host` | 中英键对称 |

**§19.2 剩余项**：EasyTier 节点生命周期、BGM 顺序播放、扫描 Worker、一键导入复制
N 份、模块 `id=".."` 越界、`map_cache` 只增不删、区块级解压上限 —— 见 §二十三。

> ☠ 双轨欠账仍在：以上是代码轨 + 离屏轨；没有联网真机跑完整链路。

---

## 二十三、round-216：最后 8 条 P1 结清（2026-11-08 14:3x）

> 主理人「随便你，做完所有的」。这 8 条的共同点不是崩溃，而是**静默做错事**。

| # | §19.2 条目 | 修法 | 复验 |
|---|---|---|---|
| 1 | 旧主题包 `id=".."` 越界写 | `modules._safe_module_dir()`（realpath 后必须是 modules 直接子目录）+ legacy 包补 `_RE_ID`；`uninstall_module` 也校验目录归属 | `id=".."` → `ModuleError`，`<data>/manifest.json` 未生成；正常 id 装/卸照旧 |
| 2 | 一键导入全部复制 N 份 + 失败也标已导入 | 按 `normcase(abspath)` 去重；只有成功才写 `_imported` 并 `mark_imported()` | 3 条结果（同目录 2 + 另目录 1）→ 只调 2 次；失败目录不在 `_imported`；汇总「成功 1 失败 1」 |
| 3 | BGM 顺序/随机实际单曲循环 | `MusicPlayer.set_mode()` 每次同步 `setLoops`：loop→Infinite，其余→Once；`play()` 前再同步 | loop→Infinite / sequential→Once；投递 `EndOfMedia` 后 `_idx` 0→1；未知模式回退 loop |
| 4 | 区块级解压无上限（2MB→2GB） | `nbt.inflate/load_bytes` 增 `max_bytes`；`world_map._CHUNK_MAX_BYTES = 24 MB` | 6 MB 全零 gzip + 1 MB 上限 → `NbtError`；伪 region 膨胀区块 → `_chunk_nbt` 返回 `None` |
| 5 | `map_cache` 只增不删 | `_prune_tile_versions()` 同块留最新；`_prune_dir_budget()` 每维度 ≤128 块；`prune_cache_budget()` 整树 ≤256 MB（进程内一次） | 两次渲染 → 1 png + 1 meta；3 MB junk + 1 MB 预算 → 清到预算内；预算内不误删 |
| 6 | 扫描面板关闭后 Worker 不停 | `discover_instances(should_stop=)` + `_sweep` 轮询；`ScanPanel.shutdown()`；`ScanDialog.closeEvent/done` 调它 | 3000 步模拟扫描 → shutdown 0.01s 停线程、体内收到停止、`_on_done` 未触发 |
| 7 | EasyTier 节点生命周期绑模态对话框 | `_open_lobby` 改非模态单窗口（`show()` + `WA_DeleteOnClose` + 已有窗口前置）；关闭时给「保持联机 / 断开并关闭」确认 | 「保持联机」→ 窗口仍可见、未拆节点；「断开并关闭」→ 关窗且拆节点；未联机直接关不弹框 |
| 8 | 装完 Java 不失效 `scan_javas` 缓存 | `core/java.invalidate_scan_cache()`；`install_java` 返回前调用 | 两档缓存槽清空；顺序断言「失效在 `return path` 之前」 |

`tests/test_round216_regression.py` **40 项**（含反向对照），已登记 `regress.py`。

**至此 §19.2 全清**。剩下的是：`§14` 的「详情预取 / 下载与搜索共用项目缓存」（性能
增强，不是缺陷）、§19.3 的 P2 长尾、以及发布清单 A 组的联网真机全链路。

