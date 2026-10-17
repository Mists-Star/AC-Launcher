# round-105 功能扩展实现方案（A2 / A1 / B6）

> 承接 `docs/launcher_feature_ideas_2026-10-17.md` 第 6 节的取舍结论，把三个方向展开成可评审的实现方案。
> **本轮只出方案，不写生产代码、不提交 git。** 方案通过评审后，与用户手工测试产生的 bug 清单合并进下一轮迭代。

## 0. 结论速览（含现状修正）

摸底源码后有一个重要修正：**三个方向的“引擎”完成度差异极大，A2/B6 的缺口主要在 UI 落地，A1 才是真正的功能空白。**

| 方向 | 引擎现状 | 真正缺口 |
|---|---|---|
| **A2 可解释诊断** | `core/mod_check.py` + `core/instance_health.py` 两个静态扫描引擎**已完成**；`health.*` / `modcheck.*` i18n **中英双语齐全**；`apply_fix` / `apply_all_safe` 一键修复**已实现** | ①`scan_health` 有 i18n 键但**全仓库无任何 UI 消费者**（死代码）；②`mod_check_dialog.py` 只展示 3 类模组冲突，未接富体检；③启动前预检只调 `mod_check`，未接 `instance_health` |
| **A1 零配置联机** | `lobby.py` + `lobby_dialog.py` + `core/easytier.py` 可建房/加入/起虚拟局域网 | `join_lobby()` **只查本地 `lobbies.json`**，无跨机发现机制 → 邀请码出门即失效，**闭环未打通**（唯一真空白） |
| **B6 Java 自动绑定** | `required_java_major` / `select_java` / `scan_javas` / `java_install` 齐备；`instance_health._check_java` 已能报 mismatch 并产修复；`Instance.java_path` 实例级字段已存在 | ①实例详情/设置无「将用哪个 Java」的可解释展示；②无一键补装 Java 入口接线；③新建实例未按版本预绑定 |

因此建议的实现量级：**A2 = 接线 + 增强（低风险）｜A1 = 补跨机闭环（中风险，核心）｜B6 = 接线 + 展示（低风险）。**

---

# A2 · 依赖与冲突「可解释」诊断（启动前静态检查 + 一键修复）

## A2.1 现有代码触点

**扫描引擎（纯逻辑、无 Qt、可无头测试）**
- [mod_check.py](../src/core/mod_check.py#L143-L212) — `scan_conflicts(inst)`：读 `mods/` 每个 jar 的 Fabric/Quilt `*.mod.json`、Forge/NeoForge `META-INF/mods.toml`，产出 `Finding`（`loader_mismatch` warn / `missing_dep` critical / `duplicate_id` warn）。`Finding` 定义在 [L46-L57](../src/core/mod_check.py#L46-L57)：字段 `kind/severity/title/reason/suggestion` 均为 **i18n key**，另带 `filenames/meta/fix`。
- [instance_health.py](../src/core/instance_health.py#L353-L391) — `scan_health(inst, settings)`：把 `mod_check.scan_conflicts` 与四层自有检查合成 `groups`（mods/perf/jvm/java/args）+ 计数 + `fixable`。
  - 层1 性能模组 [_check_perf_mods L126](../src/core/instance_health.py#L126-L181)（渲染模组重复 / OptiFine 冲突 / 缺常用性能模组）
  - 层2 JVM 与内存 [_check_jvm L187](../src/core/instance_health.py#L187-L254)
  - 层3 Java 运行时 [_check_java L270](../src/core/instance_health.py#L270-L313)（mismatch/missing）
  - 层4 启动参数 [_check_launch_args L319](../src/core/instance_health.py#L319-L347)（残留 `--server` / jvm_args 格式）
- 修复执行：`apply_fix(inst, fix)` [L394](../src/core/instance_health.py#L394-L460) 与 `apply_all_safe(inst, findings)` [L463](../src/core/instance_health.py#L463-L471)——**只改 `Instance` 字段，不碰游戏文件、不联网**，幂等（无变化返回 False）。

**已有 UI（只接了 mod_check）**
- [mod_check_dialog.py](../src/mod_check_dialog.py) — `open_check_dialog(parent, inst)`，仅渲染 `mod_check` 的 3 类结果。
- 实例右键菜单入口 [pages_instances.py `_show_row_menu` L1679-L1704](../src/pages_instances.py#L1679-L1704) → `_mod_check` [L1830](../src/pages_instances.py#L1830-L1833)。
- 崩溃分析对话框 [crash_dialog.py `_FindingCard` L34](../src/crash_dialog.py#L34-L105) 是**可复用的展示范式**（severity 圆点 + title + reason + suggestion + 动作按钮）。

**启动前（非阻塞）预检**
- [launch.py L901-L909](../src/launch.py#L901-L909) — 启动前调用 `mod_check.scan_conflicts`，critical 数经 `status.modcheck_crit` 打到状态栏，**不拦截启动**。

**崩溃后分析（事后）**
- [crash_analysis.py](../src/crash_analysis.py#L133-L196) — `analyze_instance(inst)` 读 `logs/latest.log` + `crash-reports/*`；`scan_mod_manifests` [L202](../src/crash_analysis.py#L202-L233) / `find_missing_dependencies` [L279](../src/crash_analysis.py#L279-L294) / `search_and_download_missing` [L297](../src/crash_analysis.py#L297-L332)（按 mod id 去 Modrinth 搜并下载首个命中）。

**i18n（已双语齐全，无需新增即可上线基础版）**
- `health.*` 中文 [i18n.py L759-L800](../src/i18n.py#L759-L800)，英文 [L2129-L2160 附近](../src/i18n.py#L2129)。键含 `health.title / dialog_title / ok_title / ok_desc / summary / groups.{mods,perf,jvm,java,args} / fix / fix_all / report_only / rescan / fixed_toast / fix_none / sev.{info,warning,critical}` + 每类 `health.kind.*/reason.*/fix.*/fixlabel.*`。
- `modcheck.*` 中文 [L742-L756](../src/i18n.py#L742-L756)，英文 [L2113-L2126](../src/i18n.py#L2113-L2126)。

## A2.2 缺口（逐条）

1. **富体检无 UI**：`scan_health` / `apply_all_safe` 是死代码，`health.*` 一半键（`dialog_title/ok_*/summary/fix/fix_all/rescan/...`）无消费者。
2. **解释力仍可增强**：现有检查不覆盖——模组**版本区间**不符（`mod_check` 解析出 `deps` 的 `versionRange` 但 [L182-L193](../src/core/mod_check.py#L182-L193) 只判“在不在”不判“版本对不对”）、**同 id 多版本并存**（两 jar 同 id，`duplicate_id` 只在两个都能解析出 id 时命中，且不区分版本）、**资源包/光影与渲染管线的顺序/冲突**。
3. **启动前未接富体检**：`launch.py` 只跑 `mod_check`，`instance_health` 里更有价值的 `java_mismatch`（critical、且可一键修）没进启动前提示。

## A2.3 设计与接口

### (1) 新增展示层：`src/instance_health_dialog.py`
沿用 `crash_dialog._FindingCard` 的视觉范式，不复刻另一个卡片实现——**抽公共卡片**或直接复用。

建议对外接口（与 `mod_check_dialog.open_check_dialog` 同构）：
```
open_health_dialog(parent, inst, settings=None) -> None
```
内部：
- Worker 线程跑 `instance_health.scan_health(inst, settings)`（读 jar 元数据可能上百 ms，避免卡 UI；注意 `_MAX_SCAN_JARS=60` 上限已内建）。
- 头部：`health.summary`（{n} 项可优化 · {f} 项可一键修复）；`health.fix_all`（**一键修复安全项**按钮，仅当 `fixable>0`）；`health.rescan`。
- 分区渲染 `groups[]`：每区标题用 `health.groups.<key>`，区内按 severity 排序，条目用 `_FindingCard`（title/reason/suggestion + `fix.label` 按钮）。
- 单条「修复」→ `instance_health.apply_fix(inst, f.fix)` → 成功则 `instances.manager().save(inst)` 持久化 + `health.fixed_toast`；再 `_rescan` 刷新。
- `fix_all` → `apply_all_safe(inst, findings)` → save → toast `health.fixed_toast`。
- 全部空 → `health.ok_title` + `health.ok_desc`。

**关键**：`apply_fix` 只写 `Instance` 字段（含 `java_path`），**必须** `mgr.save(inst)` 落盘，否则刷新/重启丢修复。

### (2) 入口接线（3 处）
| 入口 | 位置 | 动作 |
|---|---|---|
| 实例右键菜单 | [pages_instances.py L1692](../src/pages_instances.py#L1692-L1693) 当前为「启动前模组冲突预检」 | 改为「实例体检」（`health.title`）→ `open_health_dialog`；旧 `mod_check` 入口可并入体检的 mods 分区（或**保留双入口**：右键「冲突预检」+「实例体检」，由评审定） |
| 实例详情「⋯ 更多」 | [L1579 起](../src/pages_instances.py#L1579) | 增一项「实例体检」 |
| 崩溃分析对话框顶部 | [crash_dialog.py L107 起](../src/crash_dialog.py#L107) | 加「先做启动前体检」按钮，把“事后分析”与“前移诊断”串成一屏 |

### (3) 启动前预检升级
[launch.py L901-L909](../src/launch.py#L901-L909) 由 `mod_check.scan_conflicts` 升级为 `instance_health.scan_health(inst, settings)`：
- 取 `critical` 计数打状态栏（复用 `status.modcheck_crit`，或新增 `status.health_crit` 提到“含 Java 不匹配”）。
- **仍非阻塞**（守住现有策略：有些实例容忍缺前置照常进主菜单）。可加一个设置开关「启动前遇到严重问题弹体检」（默认关，对齐主流“不再提示”语义）。
- 边界：`scan_health` 依赖 `settings`，`launch.py` 内可 `load_config()`；失败必须 `except` 吞掉，绝不阻断启动（沿用现有写法）。

### (4) 增强检查（增量加在 `instance_health.py`，各自独立函数）
- `_check_mod_versions`：用 `mod_check._parse_jar` 已解析的 `deps` 版本区间，对**每个**依赖做区间判定，产出 `mod_version_mismatch`（critical）——把“有但版本不对”从“装了就崩但看不出为什么”变成“一目了然”。
- `_check_duplicate_jars`：同一 `mod_id` 多 jar（不同 version）并存 → 复用/细化 `duplicate_id`，在 `reason` 里带上各自版本，`fix` 给「保留较高版本」的**报告型**建议（删除文件属危险操作，默认只提示 `report_only`）。
- `_check_shader_packs`：`shaderpacks/` 存在 + 渲染管线冲突（Iris/OptiFine 并用）→ warning（低优先，可 P2 再做）。
- `_check_missing_dep_explain`：把 `missing_dep` 的 `fix` 升级为「到资源中心安装 {dep}」的**动作**（复用 `crash_analysis.search_and_download_missing`，但需用户显式点按钮才联网）。

## A2.4 需新增 i18n 键（中文示例，**en 必须同步**）
- 新增检查：`health.kind.mod_version_mismatch` / `health.reason.mod_version_mismatch`（{mod} 需要 {dep} {range}，当前 {have}）/ `health.fix.mod_version_mismatch`
- `health.kind.duplicate_jars` / `health.reason.duplicate_jars` / `health.fix.duplicate_jars`
- （可选 P2）`health.kind.shader_conflict` / `health.reason.shader_conflict` / `health.fix.shader_conflict`
- （可选）`status.health_crit`：`启动前体检发现 {n} 项严重问题——建议先到 实例 → 「实例体检」处理`
- 依赖安装动作：`health.fixlabel.install_dep` / `health.installing_dep` / `health.installed_dep`
> 硬约束：新键必须在 zh 与 en 两表中**同时**存在（仓库有 parity 校验需求）。

## A2.5 风险与边界
- **UI 卡顿**：jar 元数据读取属 IO；必须 Worker + 保持 60 jar 上限（`_MAX_SCAN_JARS`）。
- **误报**：`_check_java` 已刻意“路径不在扫描表就不判”（手填 JDK 不误报）——新增的版本区间检查要沿用“只对能确认的情况报”原则。
- **external 实例**：`apply_fix` 只改 AC 元数据不碰游戏文件，天然安全；但**不要**对 external 实例做“删 jar”类修复。
- **联网动作**：默认离线；只有用户点「安装 {dep}」才联网。
- **启动前拦截**：保持**非阻塞**为默认，拦截/弹窗作为可选开关。

## A2.6 验证方式
- `python -m compileall -q src main.py`。
- 无头单元：构造 fixture `mods/`（含缺前置的 fabric mod、同名不同版本 jar），断言 `scan_health` 产出对应 kind、`apply_all_safe` 返回条数、`apply_fix` 幂等（二次调用返回 False）。
- 离屏冒烟：`QT_QPA_PLATFORM=offscreen` 打开 `instance_health_dialog`，校验分区/计数渲染（文字为 tofu 方块，只验结构）。

## A2.7 阶段划分
- **P1（低风险，先做）**：接 `open_health_dialog` 到 3 处入口 + `launch.py` 升级为非阻塞体检提示。引擎/i18n 零改动。
- **P2**：增强检查（版本区间 / 重复 jar）+ 缺失前置一键安装动作 + 新增 i18n 键。
- **P3（可选）**：启动前“严重问题弹体检”开关 + 光影/资源包检查。

---

# A1 · 零配置联机闭环（一键建房 + 跨机邀请码）

## A1.1 现有代码触点

- [lobby.py](../src/lobby.py) — `Lobby` dataclass [L24](../src/lobby.py#L24-L34)（`code` / `secret` / `members` …）；`create_lobby` [L67](../src/lobby.py#L67-L86)、`join_lobby` [L89](../src/lobby.py#L89-L97)（**仅遍历本地 `data/lobbies.json`**）、`list_lobbies` [L100](../src/lobby.py#L100-L103)、`leave_lobby` [L106](../src/lobby.py#L106-L115)；`_generate_code`（`U/NNNN-AAAA-SSSS-EEEE`）[L51](../src/lobby.py#L51-L59)、`_generate_secret` [L62](../src/lobby.py#L62-L64)。
- [lobby_dialog.py](../src/lobby_dialog.py) — `LobbyDialog` [L128](../src/lobby_dialog.py#L128)；加入 `_do_join` [L269](../src/lobby_dialog.py#L269-L282)、建房 `_do_create` [L284](../src/lobby_dialog.py#L284-L296)、起虚拟网 `_start_easytier` [L299](../src/lobby_dialog.py#L299-L331)、`_show_lobby`/`_copy_code` [L403-L420](../src/lobby_dialog.py#L403-L420)；工具选择器 `_ToolPicker` [L34](../src/lobby_dialog.py#L34)。
- [easytier.py](../src/core/easytier.py) — `find_easytier` [L56](../src/core/easytier.py#L56)、`download_easytier` [L85](../src/core/easytier.py#L85)、`start_node(network_name, network_secret, hostname, peer)` [L135](../src/core/easytier.py#L135-L180)、`stop_node` [L183](../src/core/easytier.py#L183)、`_probe_ip` [L204](../src/core/easytier.py#L204-L238)；`DEFAULT_PEER = tcp://public.easytier.cn:11010` [L32](../src/core/easytier.py#L32)。
- 设置：`lobby_tool`（ask/easytier）[settings_dialog.py L124](../src/settings_dialog.py#L124) + 设置页 [L978](../src/settings_dialog.py#L978-L994)。
- i18n：`lobby.*` 已双语（`et_ready` 中文 [L1387](../src/i18n.py#L1387) / 英文 [L2751](../src/i18n.py#L2751)）。

**现有联机模型（理解闭环的关键）**：EasyTier 把两名玩家放进**同一个虚拟 LAN**（网络名=`code`、密码=`secret`、DHCP 分配 `10.126.126.x`）。主机在游戏里「对局域网开放」，客户端在同一虚拟 L2 网段里**能在多人游戏→局域网列表直接看到**主机。即：**只要双方 network_name + secret 一致，闭环即成立**。

## A1.2 缺口（核心）

`join_lobby(code)` 只在**本机** `lobbies.json` 里按 code 找——**跨机器完全失效**；而建房方生成的 `secret` 也**只存本地**，客户端即便知道 `code` 也**推不出 secret**，`_start_easytier` 里 `secret = lob.secret or lob.code` 只对本机成的 lobby 成立。
→ 结论：**“邀请码”必须是能自携带 `network_name(code) + secret` 的可分享字符串**，让客户端无需任何后端即可起网。这就是要补的唯一一块。

## A1.3 设计与接口

### (1) 邀请码编解码（无后端，纯离线）
在 `lobby.py` 增加：
```
encode_invite(lob: Lobby) -> str          # 生成可分享邀请码
decode_invite(text: str) -> dict | None   # -> {"code","secret","host","name"} 或 None
```
- 载荷：`{"v":1,"c":code,"s":secret,"h":host,"n":name}`；`json` → 紧凑字节 → **base32**（去换行、大写）→ 前缀 `AC1-`。
- 人类可读兜底：仍打印 `code`（主机可在设置里选“邀请码包含密钥”默认开）；邀请码整体可复制/粘贴。
- 安全提示：邀请码内含 secret ⇒ 拿到码即可入网；UI 明示「仅发给要一起玩的人」。（沿用 easytier 已有“secret 走环境变量、不暴露进程列表”[L147-L154](../src/core/easytier.py#L147-L154)，本项只影响分享面。）

### (2) 加入流程改造（`lobby_dialog._do_join`）
- 输入先试 `decode_invite`：
  - 命中 → 直接以 `{code, secret}` 起网（**不依赖本地 `lobbies.json`**），`_current_lobby` 用解码结果构造（可只存本地缓存用于展示）。
  - 未命中 → 回退旧 `join_lobby(code)`（同机/已在本机的 lobby）。
- `_start_easytier` 改为接受 `(network_name, secret)` 显式参数，而非从 `lob.secret` 取。

### (3) 一键建房闭环（`lobby_dialog._do_create` 增强）
1. 选实例 → `create_lobby`（已有）。
2. 自动 `start_node(code, secret)`（已有 `_start_easytier`）。
3. 面板新增：
   - **邀请码** 大号显示（`lobby.invite_label`）+ 「复制邀请码」按钮（`_copy_invite`）——取代/并列现有「复制 code」。
   - 虚拟 IP 展示（已有 `et_ready`）+ 「复制连接地址」（若探测到 IP）。
   - **对方操作指引**（`lobby.invite_howto`）：一段固定文案——“把你的邀请码发给他 → 他粘贴即加入 → 你在游戏里开启局域网 → 他在多人游戏里即可看到”。
   - （可选）导出邀请码为图片/文本，便于分享。
4. 主机仍需手动「游戏内对局域网开放」——这是 MC 机制，不改；但 UI 把它讲清楚（闭环的最后一米）。

### (4) 缓存/簿记策略
主机侧沿用本地 `lobbies.json`（成员展示）；客户端解码加入的 lobby **不写成员列表**（无服务器无法同步），面板只显示“已加入 {host} 的网络 · 你的虚拟 IP”。

## A1.4 需新增 i18n 键（zh + en 同步）
- `lobby.invite_label` / `lobby.copy_invite` / `lobby.invite_copied`
- `lobby.invite_join_ph`（输入框 placeholder：粘贴邀请码或 U/… 码）
- `lobby.invite_howto`（闭环指引）
- `lobby.invite_secret_warn`（含密钥的提示）
- `lobby.joined_net`（客户端加入成功文案，带 host）
- `lobby.invite_bad`（邀请码无法解析的报错）

## A1.5 风险与边界
- **无后端 = 主机必须在线**：主机退出/停网，客户端掉线。这是“零配置”的代价，需在指引文案里说清；真正稳定要 A3「一键开服」（单独立项）。
- **secret 分享面**：邀请码泄露=可入网。提供“不含密钥的纯 code 模式”作为可选（此时只能同机加入）——默认含密钥。
- **easytier 未安装**：沿用现有 `_choose_tool_prompt` / `lobby_tool` 偏好，不新增流程。
- **`_probe_ip` 不稳定**：已有 `et_ready_noip` 兜底，不阻塞。
- **跨机加入时 `members` 不产生**：UI 不要假装有成员列表（避免误导）。

## A1.6 验证方式
- 单元：`encode_invite`→`decode_invite` 往返一致；构造一个“非本机”邀请码，断言 `decode_invite` 能拿到 `secret`，且 `join` 分支走到直接起网。
- 单机可测：同机开两个 LobbyDialog（一个建房、一个粘贴邀请码加入），验证网络名/密码一致。
- 离屏冒烟：打开 `LobbyDialog`，校验邀请码面板渲染。
- 真机（用户）：两台机器，A 建房发码、B 粘贴加入、B 在局域网列表看到 A。

## A1.7 阶段划分
- **P1（核心）**：`encode_invite/decode_invite` + `_do_join` 双分支 + `_start_easytier(net, secret)` 签名调整。
- **P2**：建房面板闭环 UI（邀请码/复制/指引/复制地址）+ 新增 i18n。
- **P3（后续立项）**：A3 一键开服（服务端/客户端同版本 + 自动同步 mod），把“联机”升级为“开服+联机”一体。

---

# B6 · MC 版本 ↔ Java 自动绑定

## B6.1 现有代码触点
- [java.py](../src/core/java.py) — `required_java_major(game_version)` [L161](../src/core/java.py#L161-L190)（1.16 及以下=8，1.17=16，1.18–1.20.4=17，1.20.5+/1.21+=21）、`select_java(game_version, java_auto, user_path)` [L193](../src/core/java.py#L193-L224)（精确匹配→兼容区间→`None`**不 fallback**）、`scan_javas(deep)` [L82](../src/core/java.py#L82-L143)（带缓存）。
- [java_install.py](../src/core/java_install.py) — `install_java(major, progress)` [L103](../src/core/java_install.py#L103-L162)（Adoptium，便携解压）、`installed_majors` [L47](../src/core/java_install.py#L47-L66)、`recommended_majors` [L165](../src/core/java_install.py#L165-L168)、`JAVA_CHOICES` [L30](../src/core/java_install.py#L30-L37)。
- [java_manager_dialog.py](../src/java_manager_dialog.py) — `JavaManagerDialog` [L156](../src/java_manager_dialog.py#L156)，`selected_path` [L170](../src/java_manager_dialog.py#L170)/`select_java` [L420](../src/java_manager_dialog.py#L420-L428)，下载 `_download` [L371](../src/java_manager_dialog.py#L371)。
- 实例级字段：`Instance.java_path` [instances.py L66](../src/instances.py#L66)。全局：`java_auto`/`java_path` [settings_dialog.py L62-L63](../src/settings_dialog.py#L62-L63)。
- 启动解析优先级：[launch.py L566-L571](../src/launch.py#L566-L571)（`inst.java_path` > 全局 `java_path` > 自动 `select_java`）。
- 已有诊断：`instance_health._check_java` [L270](../src/core/instance_health.py#L270-L313) 产 `java_mismatch`（critical，fix=`set_java_path`→`select_java` 结果 / `clear_java_path`）与 `java_missing`（critical，无 fix，提示安装）。
- 新建实例向导：`NewInstanceDialog` 的 Java 区 [pages_instances.py L836-L856](../src/pages_instances.py#L836-L856)、`_choose_java` [L1060](../src/pages_instances.py#L1060-L1066)、创建信号 [L466](../src/pages_instances.py#L466)。
- 实例详情 Java 徽章 [L1524-L1527](../src/pages_instances.py#L1524-L1527)（**仅当 `java_path` 非空才显示**）。
- 实例设置对话框 [_edit_instance_settings L1866](../src/pages_instances.py#L1866)（**当前无 Java 项**）。

## B6.2 缺口
1. 详情页不显示“未指定 Java 时**自动将用哪个 Java**”（自动模式下用户看不到绑定结果）。
2. 实例设置无 Java 选择行（只能创建时选/全局设置）。
3. 新建实例向导未按版本提示/预绑定（Java 区只有“使用默认 / 自选”）。
4. 缺“**当前版本需要 Java N 但没装** → 一键下载”入口（`java_install.install_java` 已具备，仅差接线）。

## B6.3 设计与接口
- **自动绑定语义澄清**：真正“绑定”由 `select_java(inst.game_version)` 在启动时完成（已实现）。B6 的增量是**让它可解释、可落定、可补装**：
  1. **详情徽章**：`java_path` 为空时显示 `☕ 自动 · Java {required_java_major(gv)}`（新增 `instances.java_auto_badge`）；非空仍显示 basename（现状）。
  2. **实例设置新增「Java 运行环境」行**：
     - 下拉 [自动（Java {need}）(=空) / 指定…]，选“指定”弹 `JavaManagerDialog(current_path=inst.java_path)`，回填 `inst.java_path = dlg.selected_path`；“自动”则 `inst.java_path = ""`。
     - 保存走 `mgr.save(inst)`（该对话框已有保存逻辑）。
  3. **缺 Java 一键补装**：当 `required_java_major` 对应该 major 无任何已装 JRE（`scan_javas` 无匹配）时，行内/体检里提供「下载 Java {need}」→ `Worker(java_install.install_java, need)` → 完成后 `inst.java_path = path; mgr.save(inst)`（或留空走自动，见 A2.5 决策点）。
  4. **新建实例向导**：Java 区标题旁显示 `new_instance.java_recommend`（“本版本建议 Java {need}”），默认仍走“使用默认（自动）”。
- 复用而非新增：`required_java_major` / `select_java` / `scan_javas` / `install_java` / `JavaManagerDialog` 全部现成。

## B6.4 需新增 i18n 键（zh + en 同步）
- `instances.java_auto_badge`（`☕ 自动 · Java {need}`）
- `instances.setting_java_title` / `instances.setting_java_follow`（自动（Java {need}））/ `instances.setting_java_pick`
- `instances.java_download`（下载 Java {need}）/ `instances.java_downloading` / `instances.java_downloaded`
- `new_instance.java_recommend`（本版本建议 Java {need}）
> 与 A2 的 `health.kind.java_missing/java_mismatch`（已有双语）保持文案一致。

## B6.5 风险与边界
- **不擅自写 `java_path`**：默认留空=自动（状态更少、更随版本走）；仅当用户“指定”或自动找不到时才写值。若在自动模式下帮用户绑死，会在将来换 Java 时反而制造“版本错配”（违背 B6 初衷）——**这是需要评审确认的决策点**。
- **手填 JDK 不判版本**：沿用 `instance_health._check_java` 的“路径不在扫描表就不误报”原则。
- `select_java` 缺 Java 返回 `None` 且**不 fallback**（硬约束）→ 缺 Java 必须显式提示补装，绝不能回退到任意高版本。
- external 实例：Java 属 AC 元数据，可安全设置。

## B6.6 验证方式
- 单元：给定 `game_version` 断言 `required_java_major` 边界（1.16.5/1.17/1.20.4/1.20.5/1.21）。
- 离屏冒烟：打开实例设置，校验 Java 行渲染；打开新建向导校验建议文案。
- 真机（用户）：老版本实例（1.8.9）与新版（1.21）各起一次，确认用对 Java、详情徽章显示正确。

## B6.7 阶段划分
- **P1**：详情徽章 + 实例设置 Java 行（自动/指定）——纯 UI 接线。
- **P2**：缺 Java 一键下载接线 + 新建向导建议文案 + 新增 i18n。

---

# 附 · 落地顺序与并行建议

1. **A2-P1 + B6-P1 可并行、且均为低风险接线**（引擎/i18n 已备），建议作为下一轮的“稳收益”批。
2. **A1-P1 是唯一需要新逻辑的**（邀请码编解码 + join 双分支），单独一批，改动集中在 `lobby.py` / `lobby_dialog.py`，互不干扰。
3. **A2-P2 / A1-P2 / B6-P2** 属“增强”，可与用户手工测试反馈的 bug 一起排。
4. **A3 一键开服 / A4·A5 云同步与短码分享** 涉及后端/账号/隐私，按调研结论**单独立项**，不进本批。

**交付节奏**：每批（P1/P2）完成后建议执行——`python -m compileall -q src main.py` → 离屏冒烟（`QT_QPA_PLATFORM=offscreen`）→ i18n 中英键 parity 校验（无单边键）→ 交由用户真机验收。**本轮只评审本方案，不动代码。**
