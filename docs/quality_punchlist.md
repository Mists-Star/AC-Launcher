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
