# round-106 记忆（2026-10-17）— 实例体检（N5 冲突预检 → 多分区体检 + 一键本地修复）

玩家起点（原文）是一段关于 MC 渲染栈的长分析（GLSL / SPIR-V / ShaderConductor /
SPIRV-Cross / Vulkan / VulkanMod / Slang / ShaderLab / Cg / Bindless / GPU-Driven /
Indirect Draw / Mesh Shader / JNI-Panama / ZGC / SoA / Palette / LOD / bgfx / Dawn /
FidelityFX / WebGPU / 优先级路线图），结尾追问：**「那么有这些我们能干什么？或者说
如果你有想法你觉得能干什么？」**

收敛结论：**换着色器语言（HLSL/Slang/Cg）不改变性能；唯一可落地的大头收益在
「编排层」——正确的模组栈 + 正确的 JVM 参数 + 正确的 Java 版本。** 由此定下本轮方向。

玩家经 AskUserQuestion 拍板三件事：
- 方向 = **启动器性能体检 + 一键优化**
- 载体 = **升级现有「冲突预检」为完整「实例体检」**
- 修复范围 = **仅本地安全修复**（不联网、不动用户游戏文件）

本项即 `docs/round105_plan_feature_expansion.md` 的 **A2-P1**：该方案已点名
「扫描引擎已完成、缺口在 UI 接线（`scan_health` 有 i18n 键但全仓库无 UI 消费者）」，
本轮补上的就是这条接线（外加把引擎/i18n 落进工作区，见下）。

---

## 1. 新增扫描引擎 `src/core/instance_health.py`（无 Qt，可无头回归）

对外只有两个公开函数：`scan_health(inst, settings=None)` 与
`apply_fix(inst, fix)` / `apply_all_safe(inst, findings)`。

- **`scan_health`**：把 `core.mod_check.scan_conflicts` 与四层自有检查合成
  `groups`（**mods / perf / jvm / java / args**）+ 计数（critical/warning/info）+
  `scanned` + `fixable`。每层用 `_safe()` 包住——**单项检查抛异常绝不影响整体体检**。
- **五层检查**：
  - 层 0 `mods`：复用 `mod_check.scan_conflicts`（loader_mismatch / missing_dep /
    duplicate_id）。
  - 层 1 `perf` [_check_perf_mods]：渲染模组重复（sodium+embeddium 同装）、
    OptiFine 与 Sodium/Iris/Oculus 并存、推荐集缺失。**均 report-only**（不产出 fix）。
  - 层 2 `jvm` [_check_jvm]：`aikar_off` / `pretouch_missing` / `g1gc_off` /
    `disable_explicit_gc_off` / `ram_small` / `ram_large`。
  - 层 3 `java` [_check_java]：`java_mismatch`（critical，可一键改路径）、
    `java_missing`（critical，无法自动修，只提示装 Java）。
  - 层 4 `args` [_check_launch_args]：`residual_server_arg`（残留 `--server`，
    可一键剥离且**保留其他参数**）、`malformed_jvm_args`（shlex 解析失败）。
- **共 13 个 kind**（见 §4 i18n 清单）；其中 **6 个带安全 fix**：
  `aikar_off` `g1gc_off` `disable_explicit_gc_off` `ram_small` `ram_large`
  `residual_server_arg`，外加条件触发的 `pretouch_missing` / `java_mismatch`。

### 设计取舍（防噪）
- **性能模组推荐集只收公认五项**：fabric = `sodium|embeddium` / `lithium` /
  `ferritecore` / `modernfix` / `entityculling`；forge = `embeddium|rubidium` /
  `ferritecore` / `modernfix` / `entityculling`。**刻意不含 iris / indium / c2me /
  moreculling**（场景化/实验性，推荐会成噪音；这些仍参与冲突检测）。
- **`aikar_off` 与 `pretouch_missing` 互斥**：内存充裕且预设为 default 时整组建议切
  Aikar（一次覆盖 GC/Pretouch/DisableExplicitGC），不再单发重复卡片；只有 `custom`
  预设才逐项检查 `-XX:+AlwaysPreTouch`。
- **不误报**：`_check_java` 只对「路径能在 `scan_javas()` 里确认版本、且确实不兼容」
  的情况报；玩家手填的 JDK 不在扫描表 → 不判（不运行无从得知版本）。
- **零模组 / 原版实例不刷提示**：`_check_perf_mods` 对 vanilla、空 mods 目录、
  元数据全解析失败的情况一律返回空。
- **jar 上限 `_MAX_SCAN_JARS=60`**：与 `crash_analysis.scan_mod_manifests` 一致，
  避免上百个 jar 的元数据读取拖死 UI 线程。

### 修复执行（`apply_fix` / `apply_all_safe`）
- 修复描述符 schema：`{"action", "params", "safety", "label", "label_kwargs"}`；
  `safety` 本模块恒为 `"safe"`。
- **只改 `Instance` 字段**（含 `java_path`），无 I/O、无网络、不碰游戏目录；
  **幂等——无变化返回 `False`**。
- 已实现 10 个 action 处理器：`enable_g1gc` `enable_degc` `set_preset_aikar`
  `set_preset_auto` `set_ram` `append_pretouch` `set_renderer` `clear_game_args`
  `set_java_path` `clear_java_path`。
  > 说明：`set_renderer` 与 `set_preset_auto` 目前**无生产者**（尚无 check 产出），
  > 属预留处理器，供后续增强检查（如光影/渲染管线）复用。
- `apply_all_safe` 只应用 `safety == "safe"` 的条目，返回实际生效条数。

## 2. `core/mod_check.py` 扩展（纯增量、向后兼容）

- 新增 `SEV_INFO = "info"`（提示级，供 `instance_health` 复用本 dataclass）。
- `Finding` 新增 `fix: dict | None = None` 字段——`scan_conflicts` 恒为 `None`，
  既有消费方语义不变；`instance_health` 用它挂一键修复描述符。

## 3. i18n（`src/i18n.py`，zh + en **各 68 键**，无单边键）

- 新增 **68 个 `health.*` 键**：`health.title / dialog_title / ok_title / ok_desc /
  summary / groups.{mods,perf,jvm,java,args} / fix / fix_all / report_only / rescan /
  fixed_toast / fix_none / sev.{info,warning,critical}` + 13×`kind.* / reason.* /
  fix.*` + 10×`fixlabel.*`。
- 文案更新：`status.modcheck_crit` 由「冲突预检」改为指向**实例体检**
  （zh：「…建议先到 实例 → 右键 →「实例体检」处理后再启动。」/ en 同步）。

## 4. UI 升级：`src/mod_check_dialog.py` 原地重写为 `HealthDialog`

- 沿用 crash_dialog `_FindingCard` 的视觉范式（严重度色标 + title + reason +
  涉及 .jar 名 + 「→ 建议」），**不新增另一套卡片实现**。
- 结构：AC 无边框窗口（`TitleBar` + `FramelessHelper` + `enable_win11_round_corners`）
  → `page_header`（`health.summary` 随结果刷新）→ `QScrollArea` 按 `groups` 分区
  渲染（分区标题走 `QLabel[cls="group"]`）→ 底部「重新体检 / 一键修复安全项 / 关闭」。
- 条目有 `fix` 时生成「修复」按钮：`apply_fix` → `mgr.save(inst)` → `_rescan()`；
  `_fix_all` → `apply_all_safe` → save → rescan → toast。
- 卡片容器用 `setProperty("cls", "card")` 走主题 QSS，**不内联硬编码色**（随明暗主题切换）。
- 全空 → `health.ok_title` / `health.ok_desc`；`fixall_btn` 在 `fixable==0` 时禁用。
- **兼容别名保留**：`ModCheckDialog = HealthDialog`、`open_check_dialog`（转调，`mgr=None`），
  新入口 `open_health_dialog(parent, inst, mgr=None)`。
- **关键**：`apply_fix` 只写 `Instance` 字段，**必须** `mgr.save(inst)` 落盘，
  否则刷新/重启丢修复——已在对话框内落实。

## 5. 入口接线（`src/pages_instances.py`，3 处，**不新增按钮**）

- 实例右键菜单 [L1694]：原「启动前模组冲突预检」→ 改为 `t("health.title")` →
  `self._health_check(inst)`（旧 `_mod_check` 保留为转调别名，保持调用点兼容）。
- 实例详情「⋯ 更多」菜单 [L1593]：追加一项 `(t("health.title"), "tools", …)`
  ——守 round-84「行内不堆按钮」的精简原则。
- `_health_check` 方法：`from .mod_check_dialog import open_health_dialog` →
  `open_health_dialog(self, inst, self.mgr)`。

## 6. 验证（全绿）

- `python -m compileall -q src main.py` → **通过**。
- **i18n 键 parity**：zh-CN / en-US 均 **1270 / 1270**，`only_zh`/`only_en` 均为空
  （无单边键）；`health.*` 去重后每语言 **68** 键、`health.kind.*` **13** 个。
- **无头冒烟**（项目 venv：PySide6 × Py3.13，`QT_QPA_PLATFORM=offscreen`，
  临时脚本 `_` 前缀、`os._exit` 收尾、用后即删）→ **FAILS: 0**，覆盖：
  - 健康实例仅命中 `disable_explicit_gc_off`(info)，无 java_* 误报 ✓
  - 病态实例命中 `residual_server_arg / g1gc_off / ram_small / perf_mod_missing /
    disable_explicit_gc_off`，`fixable=4` ✓
  - `apply_all_safe` 应用 4 项；`game_args` 被正确剥离为 `--width 1280`（保留非 server 参数）✓
  - 修复后 `perf_g1gc=True`、`ram_mb=4096` ✓；重扫后三项消失 ✓
  - `apply_fix` **幂等**（`enable_g1gc` / `set_ram` 二次调用返回 `False`）✓
  - `HealthDialog` 离屏构造成功、含 rescan/fixall 按钮、`_rescan()` 重建 groups ✓
- **中途踩坑记录**：首次冒烟用系统 Python → 缺 `minecraft_launcher_lib` / `PySide6`，
  `from ..launch import parse_game_args` 导入失败被 `_safe` 吞掉导致漏检；改用
  **项目 venv Python** 后全绿。`TitleBar` 实际签名无 `controls` 参数（参考
  crash_dialog），误写信参数已修正。

## 7. 本轮未做（已批计划明确 Out of scope / 待评审）

- **A2-P2 增强检查**：模组**版本区间**校验（`mod_check` 已解析 `deps` 的
  `versionRange` 但只判「在不在」不判「版本对不对」）、同 id 多版本并存、
  缺失前置「一键到资源中心安装」（需联网，须用户显式点按钮）、光影/资源包冲突。
- **启动前预检升级**：`launch.py` 仍只调 `mod_check.scan_conflicts`（非阻塞状态栏提示），
  未接 `instance_health`（含更有价值的 `java_mismatch`）。计划约定**不改**。
- **crash_dialog 顶部入口**：未加「先做启动前体检」按钮。
- `round105_plan` 的 **A1 零配置联机闭环**（跨机邀请码，唯一真空白）与
  **B6 Java 自动绑定展示/接线**：本轮未动。

## 8. 待办

- **真机目检一次**：离屏截图受环境字体限制，文字渲染成方框，只能校验配色/几何；
  对话框文案排版与按钮落位需真机开一次确认（`实例 → 右键 → 实例体检`）。
- 待玩家手工测试反馈 bug 后，与 `round105_plan` 的 A2-P2 增强项统一排期。
