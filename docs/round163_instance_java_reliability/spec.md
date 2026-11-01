# round-163 规格：实例完整性 / 启动格式 / 启动窗口 / 强制 Java

> 状态：待用户批准 · 实施前不改任何源码
> 关联：round-82（启动格式）、round-146/153（Java 选择与启动前确认）、round-151（启动对话框文本高度）

## 1. 背景与已确认证据

用户报告（真机 `<install-dir>` 下 `data/instances.index.json` 可复现）：

| 现象 | 已确认的磁盘事实 | 根因判断 |
| --- | --- | --- |
| 启动游戏后窗口无限向下延伸 | 启动进度对话框在 `resizeEvent` 内反复 `setMinimumHeight` | `launch_dialog._fit_text_heights()` 的布局正反馈 |
| 修复实例无反馈、无效果 | 体检层只有 mods/perf/jvm/java/args | 缺「安装完整性」层；`apply_fix` 返回 False 时无任何提示 |
| 两个本地实例「识别不到完整性」 | 两个实例的 `versions/` 只有原版 json，无 Forge / Cleanroom 版本目录 | 启动时被判「未安装」→ 静默重装；体检完全看不出 |
| 无法正确识别启动格式 | 一个实例 `format="curseforge"` 但目录是 AC 自有 `.minecraft` | `detect_format` 让显式 format 无条件压过磁盘结构 |
| Cleanroom 1.12.2「没有有效 Java」 | `loader=cleanroom` 强制 need=25；本机扫描到 8/17/21/24/26，无 25 | `select_java` 返回 None → 安装/启动直接报错，从未尝试 `--provision-java` |

补充事实：
- `core/install.py::_install_cleanroom` 本就把 `--java <j25>` 与 `--provision-java` 设计成「有 25 用它跑，没有就让安装器自己拉一个 25」；但入口在 `select_java(need=25)` 返回 None 时就断了，永远到不了这一步。
- `launch_instance(java_override=...)` 目前**不能**绕过兼容性检查：`java_override` 只是跳过选择，后面的 `is_java_compatible` 分支仍会拦截（[launch.py](../../src/launch.py) L681-L724）。
- `scan_javas(deep=False)` 在本机只返回 Oracle javapath（major=0），`deep=True` 才识别出 8/17/21/24/26；多处判断混用 fast/deep 会得到不一致结论。

## 2. 决策（实施口径）

**D1 启动对话框：只在文本变化时设高度，按对话框宽度算，且硬上限。**
不再在 `resizeEvent` 里改 minimumHeight；永远不用 `lbl.width()`（布局未稳定时会被反复压缩）。

**D2 体检新增第一层 `install`（完整性）。**
判据与启动一致：`version_id` 存在 → 查 `versions/<id>/<id>.json` 或 `<mc>/<id>.json`；加载器实例 → 查 `versions/*<loader>*`（`inheritsFrom` 辅助）；原版 → 查 `versions/<game_version>/<game_version>.json`。缺失即 CRITICAL，并可一键后台补装。

**D3 补装复用现有安装器与进度对话框，不在体检对话框里重写下载逻辑。**
`HealthDialog` 收到 `fix.mode=="install"` 时启动 `Worker(install_instance, ...)` + `LaunchProgressDialog(mode="download")`，完成后 `mgr.save` + 重扫。

**D4 启动格式：AC 自有布局是结构性事实，优先于遗留的显式 format。**
`_is_ac_owned(inst)` 为真 → 直接 `ac`；其余实例仍尊重用户手动的非 auto 值。

**D5 Cleanroom：安装器 JVM 与目标 JVM 分离。**
运行安装器 jar 用「有 25 用 25，否则最高且 ≥17 的已装 Java」，目标 Java 25 交给安装器 `--provision-java` 自行落盘到 `~/.cleanroom/java`，安装后 `reset_scan_cache()`。安装失败才提示用户安装 Java 25。

**D6 强制不兼容 Java：双层开关 + 每次启动确认。**
- 全局：`java_force_incompatible`（设置 → Java 页，默认 False）。
- 实例：`Instance.java_force`（实例设置页，默认 False）。
- 只要任一层为真，且玩家手动 Java 不兼容 → 跳过确认直接强启，并在启动对话框/状态栏明示「已强制使用 Java N（不兼容）」。
- 未开强制时：不兼容且存在替代 → 确认框给三个选择「改用 Java X / 仍然使用 Java Y / 取消」；不存在替代 → 不再静默放行去报错，而是给「强制使用 Java Y / 取消」。
- 强制必须显式：绝不默认强制，绝不静默 fallback。

**D7 自动扫描按需求选 Java，统一口径。**
新增 `core/java.py::java_plan(inst, settings)`，启动、体检、实例设置提示、启动前确认四处都读它；deep 扫描只在需要时用，结果缓存沿用 `scan_javas` 双缓存。

## 3. 详细改动

### 3.1 [launch_dialog.py](../../src/launch_dialog.py)（P0 窗口无限增高）

1. `__init__` 末尾新增 `_apply_static_heights()`：对 `title_lbl / sub_lbl / hint_lbl / speed_lbl / 每个步骤名` 各设一次 `minimumHeight = max(lineSpacing, height) + 6`；`status_lbl / sources_lbl` 设 `minimumHeight = 2 行 + 4`、`maximumHeight = 5 行 + 4`。
2. 重写 `_fit_text_heights()`：
   - 宽度恒定用 `avail = max(240, self.width() - 42)`（body 左右 margin 20 + 2）；
   - `need = lbl.heightForWidth(avail)`，`clamp(2 行, need, 5 行)`；
   - 只有 `h != lbl.minimumHeight()` 时才 `setMinimumHeight(h)`（幂等，断开反馈）；
   - 保留 `_fitting` 重入保护。
3. **删除 `resizeEvent` 覆写**；`showEvent` 改为 `QTimer.singleShot(0, self._fit_text_heights)`（等首次布局宽确定）。
4. `set_status_text` / `set_sources` 仍调用 `_fit_text_heights`（文本变化才需要）。

验收：无 `resizeEvent` → 无「增高→resize→再增高」回路；5 行硬上限保证最坏情况也有限。

### 3.2 [core/install.py](../../src/core/install.py)（P0 完整性 + Cleanroom）

1. 把 [launch.py](../../src/launch.py) L515-L547 `_find_installed_loader` 的逻辑上移为公开函数 `find_installed_loader(mc_dir, loader, game_version) -> str | None`；`launch._find_installed_loader` 改为一行转发（保留旧名，避免外部引用断裂）。
2. 新增 `cleanroom_installer_java() -> str | None`：
   - `java25_path()` 命中 → 直接返回；
   - 否则扫描（`scan_javas(deep=True)`）取 `major >= 17` 中最高者（21/24/26 优先；同 major 优先 64 位）；
   - 再否则取任意 `major > 0`；
   - 全无 → `RuntimeError(t("err.cleanroom_installer_java"))`。
3. `install_instance` 的 Cleanroom 分支改用 `cleanroom_installer_java()`（不再用 `select_java(need=25)` 的 None 直接失败）；`_install_cleanroom` 内已有逻辑保持：无 25 → `--provision-java`，结束后 `reset_scan_cache()`。
4. 安装成功后把 callback 状态追加一条 `launch.cleanroom_provision`（「Cleanroom 安装器将自动下载 Java 25…」），让玩家知道为什么慢。
5. 其余加载器分支不变。

### 3.3 [core/instance_health.py](../../src/core/instance_health.py)（P0 完整性层 + 强制 Java 体检）

1. 新增 `_check_install(inst)`：
   - `version_id` 非空 → `versions/<id>/<id>.json` 或 `<mc>/<id>.json` 任一存在即通过；
   - `loader` 非 vanilla/空 → `find_installed_loader(...)` 返回 None → `Finding(kind="loader_missing", severity=CRITICAL, title="health.kind.loader_missing", reason="health.reason.loader_missing", suggestion="health.fix.loader_missing", fix={"action":"install_loader","mode":"install"})`；
   - vanilla/空 → `versions/<game_version>/<game_version>.json` 缺失 → `kind="client_missing"` 同构 finding；
   - 版本 json 有 `inheritsFrom` 但父版本 json 缺失 → WARNING `kind="base_missing"`，同一 install fix。
   - 任何 JSON 读取失败都按「缺失」处理（单层失败不影响其它层）。
2. `scan_health` 的 `sections` 在 `mods` 之前插入 `("install", _safe(_check_install, inst))`。
3. `quick_check` 同样纳入 `_check_install`（首页「留意」能显示未安装）。
4. `_check_java`：
   - 读 `java_force = bool(getattr(inst,"java_force",False)) or bool(settings.get("java_force_incompatible",False))`；
   - 不兼容但 `java_force` → INFO `kind="java_forced"`（`health.kind.java_forced`），无 fix；
   - 不兼容且未强制 → 保留现有 WARNING/CRITICAL，但 `fix` 追加第二个候选 `{"action":"set_java_force","params":{"path":<当前 java>},"label_key":"health.fix.set_java_force"}`（同一 finding 支持 `fixes` 列表时用列表；当前结构是单 `fix`，改为 `f.extra_fixes=[...]`，对话框逐条渲染按钮）。
5. `apply_fix` 新增动作：
   - `install_loader` → 返回 False（网络动作由 UI 层处理，`mode=="install"`）；
   - `set_java_force` → `inst.java_force=True`（并写入 `java_path` if params.path）；
   - `clear_java_force` → `inst.java_force=False`。
   - 返回值语义保持：是否真的改了实例字段。

### 3.4 [instances.py](../../src/instances.py)（P0 格式 + P1 字段）

1. `detect_format` 顺序改为：
   ```
   if _is_ac_owned(inst): return "ac"          # 结构事实优先
   fmt = 显式值；非 auto 且合法 → 返回
   return _probe_format(inst)
   ```
   更新 docstring，说明「显式 format 只对外来实例生效」。
2. `Instance` 新增字段 `java_force: bool = False`（紧跟 `java_path`）。
3. `_from_dict` 读取 `java_force=bool(raw.get("java_force", False))`；`_to_dict` 走 `asdict` 自动包含；**不加入** `_SUMMARY_KEYS`（摘要无需渲染，全量加载时补齐）。
4. `duplicate()` 复制 `java_force`。

### 3.5 [core/java.py](../../src/core/java.py)（P1 统一计划）

1. 新增 `java_major_or_zero(path) -> int`：先精确匹配 `scan_javas(deep=False)`，再 `java_major(basename)`，再对完整路径做 `(jdk|jre|java)[-_ ]?(\d{1,2})` 正则（`1 → 8`）。
2. 新增 `java_plan(inst, settings: dict | None = None) -> dict`：
   ```
   need = required_java_major_for(inst.game_version, inst.loader, version_json=find_version_json(...))
   auto = bool(settings["java_auto"]) and not inst.java_path
   user = inst.java_path or settings["java_path"]
   若 auto：path = select_java(...)；major = java_major_or_zero(path)
   否则：path = user；major = java_major_or_zero(user)
   compatible = bool(path) and is_java_compatible(need, major or 1)
   forced = not compatible and (inst.java_force or settings.java_force_incompatible)
   return {need, path, major, compatible, forced, auto, detected:[{path,major}...]}
   ```
   `path` 为空且 need>0 时返回 `detected` 前 5 条，供报错文案列出。
3. `select_java` 签名与行为不变（保持纯选择，不感知强制）。

### 3.6 [launch.py](../../src/launch.py)（P1 强制开关）

1. `launch_instance(..., force_java: bool = False)`。
2. 兼容性拦截块（L681-L724）加条件：`if _jmajor and not _java_ok(...) and not force_java:` 才进入「自动切换/报错」；`force_java=True` 时跳过整块，并通过 callback `setStatus` 输出 `launch.java_forced`（`{major}`, `{need}`）。
3. `java_override` 与 `force_java` 组合：override 路径原样使用；`force_java` 为真时不再被兼容检查推翻。
4. 无 Java 报错（L656-L664）改用 `err.java_compat_missing_list`：列出 `need` 与 `detected`（最多 5 条 major/path 的 basename），并提示两条出路「安装 Java N」或「在实例设置/全局设置开启强制」。
5. javaw 归一化保留（强制也不影响 javaw 切换）。

### 3.7 [main_window.py](../../src/main_window.py)（P1 启动前确认）

1. `_confirm_java_before_launch(inst, settings) -> tuple[bool, str, bool]`（proceed, override_path, force）。
2. 若 `inst.java_force or settings["java_force_incompatible"]`：不弹框，直接返回 `(True, user_path, True)`。
3. 需要确认时：
   - 有替代：按钮「本次改用 Java X」/「仍然使用 Java Y（不兼容）」/「取消」；默认 = 改用。
   - 无替代：按钮「仍然使用 Java Y（不兼容）」/「取消」；默认 = 取消。
   - 返回对应 `(True, alt, False)` / `(True, user_path, True)` / `(False, "", False)`。
4. 调用点（L4264-L4318）：解包三值，`ProgressWorker(..., java_override=override, force_java=force)`；强制时在启动前把状态文字设为 `launch.java_forced`。

### 3.8 [settings_dialog.py](../../src/settings_dialog.py)（P1 全局开关）

1. `_DEFAULTS` 增加 `"java_force_incompatible": False`（L67-L68 附近，紧跟 `java_path`）。
2. Java 卡片（L1923-L1940）增加 `self.java_force = QCheckBox(t("settings.java_force"))` + 说明标签 `settings.java_force_hint`（sub 样式、wordWrap）。
3. 配置收集（`_sync_ui_to_cfg`，L2538 附近）加入 `target["java_force_incompatible"] = self._safe(lambda: self.java_force.isChecked(), bool(target[...]))`。
4. 保存/脏检测沿用现有机制，不新增保存路径。

### 3.9 [pages_instances.py](../../src/pages_instances.py)（P1 实例设置联动）

1. `_edit_instance_settings`（L1981 起）新增一段 Java 卡片：
   - 只读提示：`instances.java_need`（`需要 Java {need}`）+ `instances.java_will_use`（`将使用 Java {major} · {path}`）或 `instances.java_none`（`未找到兼容 Java`）；
   - 复选框 `instances.java_force_label`「强制使用所选 Java（即使不兼容）」，初值 `inst.java_force`；
   - 保存时写 `inst.java_force`，沿用 `mgr.save(inst)`。
   - 数据来自 `core.java.java_plan(inst, load_config())`（后台无需 Worker：deep 扫描有缓存；首次冷启动可显示「检测中…」并跳过，避免卡设置页）。
2. `_update_fmt_hint`（实例设置里的格式提示）：追加一行「实际识别：{detected}」，当显式 format 与 `detect_format` 结果不一致时显示 `instances.fmt_mismatch_hint`（建议改回自适应）。
3. `_health_check` 不改入口；修复后的刷新依赖 HealthDialog 自身重扫，关闭时实例卡随 `mgr.save` 更新。

### 3.10 [mod_check_dialog.py](../../src/mod_check_dialog.py)（P0 反馈 + 补装）

1. `__init__` 底部新增 `self.note_lbl`（sub 样式、wordWrap，默认隐藏）。
2. `_apply(ff)`：
   - `changed = apply_fix(...)`；`changed` 为真才 `self.mgr.save(self.inst)`；
   - `note_lbl` 显示 `health.applied`（含 label）或 `health.no_change`；
   - 继续 `_rescan()`；若 finding 消失，列表即时变化，形成可感知反馈。
3. 支持多修复：finding 有 `extra_fixes` 时每个都渲染按钮（同一卡片内并排）。
4. 新增 `_run_install()`：
   - 防重入 `self._installing`；
   - `LaunchProgressDialog(self.inst, self, mode="download")` 非模态显示；
   - `Worker(install_instance, self.inst, java_auto=..., java_path=..., mirror=..., proxy=..., callback=...)`；`progress/status/step` 信号接到对话框；
   - `finished`：关闭进度框 → `mgr.save(self.inst)` → `_rescan()` → `note_lbl` = `health.install_done`；
   - `failed`：关闭进度框 → `QMessageBox.critical` 显示异常文本（不吞错）。
5. `_apply` 判断 `fix.get("mode") == "install"` 时改走 `_run_install()`，不调用 `apply_fix`。

### 3.11 i18n 新增键（zh-CN 与 en-US 必须同数同键）

| key | zh-CN 文案（要点） |
| --- | --- |
| `health.kind.loader_missing` | 未安装加载器 |
| `health.reason.loader_missing` | 实例缺少 {loader} 的版本文件，当前无法启动 |
| `health.fix.loader_missing` | 一键补装加载器 |
| `health.kind.client_missing` | 游戏本体缺失 |
| `health.reason.client_missing` | 未找到 {version} 的版本 json |
| `health.fix.client_missing` | 一键补装游戏文件 |
| `health.kind.base_missing` | 依赖版本缺失 |
| `health.reason.base_missing` | 父版本 {base} 未安装 |
| `health.kind.java_forced` | 已强制使用不兼容 Java |
| `health.fix.set_java_force` | 仍然使用并强制 |
| `health.fix.clear_java_force` | 取消强制 |
| `health.applied` | 已应用：{label} |
| `health.no_change` | 该项已是目标状态，无需修改 |
| `health.install_done` | 补装完成 |
| `settings.java_force` | 允许强制使用不兼容的 Java |
| `settings.java_force_hint` | 开启后，手动选择的 Java 即使不满足版本要求也不再询问，直接启动。可能崩溃，仅建议高级用户。 |
| `launch.java_force_btn` | 仍然使用 Java {major}（不兼容） |
| `launch.java_forced` | 已按你的要求强制使用 Java {major}（该版本建议 Java {need}） |
| `launch.java_confirm_msg2` | 此版本需要 Java {need}，当前选择 Java {major}。可改用 Java {alt}，或强制使用当前 Java。 |
| `err.java_compat_missing_list` | 此版本需要 Java {need}，未找到兼容运行时。已检测到：{detected}。请安装 Java {need}，或在设置中开启强制。 |
| `err.cleanroom_installer_java` | 运行 Cleanroom 安装器至少需要 Java 17，未检测到可用 Java。 |
| `launch.cleanroom_provision` | Cleanroom 安装器未找到 Java 25，将自动下载（首次较慢）… |
| `instances.java_need` | 需要 Java {need} |
| `instances.java_will_use` | 将使用 Java {major}：{path} |
| `instances.java_none` | 未找到兼容的 Java |
| `instances.java_force_label` | 强制使用所选 Java（即使不兼容） |
| `instances.fmt_mismatch_hint` | 当前手动格式为「{selected}」，但磁盘实际是「{detected}」；建议改回「自适应」。 |

## 4. 验证方案

### 4.1 自动

1. 新增 [tests/test_instance_java_plan.py](../../tests/test_instance_java_plan.py)：
   - AC 自有实例 `format="curseforge"` → `detect_format == "ac"`；
   - 外来隔离（`_base` 指向 `versions/<id>`，扁平 json）→ `"iso"`；显式 `multimc` + `mmc-pack.json` → `"multimc"`；
   - `find_installed_loader`：cleanroom 目录（id 不含 MC 版本，`inheritsFrom=1.12.2`）命中；forge 不误吞 neoforge；
   - `required_java_major_for("1.12.2","cleanroom") == 25`；`("1.20.1","forge") == 17`；
   - `java_plan`：monkeypatch `scan_javas` 返回 8/17/21/24/26，断言 1.20.1 forge → 17；1.12.2 cleanroom 无 25 → compatible=False；`java_force=True` → forced=True；
   - `apply_fix` 的 `set_java_force/clear_java_force` 返回值语义。
2. 新增 [tests/test_launch_dialog_layout.py](../../tests/test_launch_dialog_layout.py)（`QT_QPA_PLATFORM=offscreen`）：
   - 构造 `LaunchProgressDialog`，`show()` + `processEvents`；
   - 连续 20 次超长 `set_status_text`/`set_sources` + `processEvents`；
   - 断言 `height()` 在 3 次事件后稳定（相邻差值 ≤ 1px），且总增高 ≤ 60px。
3. 回归入口追加这两个套件到 `regress.py::SUITES`，运行：
   ```
   venv\Scripts\python.exe regress.py
   ```
   期望：全部通过（原 22 项 + 新 2 项 = 24 项），i18n 中英键数相等。
4. 真机只读诊断脚本 `_diag_instances_java.py`（`_` 前缀，不入库）：
   - cwd 指向 `<install-dir>`，读真实 data；
   - 输出每个实例：`detect_format`、`find_installed_loader`、`_check_install` findings、`java_plan`；
   - 期望：格式从 `curseforge` 变为 `ac`；cleanroom 得到 `loader_missing`；cleanroom 安装器 JVM 选中 21/24/26。

### 4.2 手动验收（真机）

1. 启动任一实例：进度对话框高度稳定，状态行从单行变多行时只增高一次，不再无限下坠。
2. 体检对话框：点「修复」→ 出现「已应用：…」；重复点同一项 → 出现「已是目标状态」。
3. Forge 实例：体检显示「未安装加载器」→ 点补装 → 进度框跑完后列表该 finding 消失 → 启动成功。
4. Cleanroom 实例：补装日志出现「自动下载 Java 25」；成功后 `~/.cleanroom/java` 出现 25，启动不再报无有效 Java。
5. 强制 Java：设置里手动选 Java 26 跑 1.12.2 → 启动前弹「仍然使用 Java 26（不兼容）」；选它后启动器不再拦截（游戏能否跑由游戏本身决定）；勾选全局强制后不再弹框。
6. 实例设置：格式提示显示「实际识别：AC 自有布局」与不一致提示；Java 行显示需求与将使用的 Java；勾选实例强制后，启动直接强启。

## 5. 交付与回滚

- 更新 `CHANGELOG.md`：新增 `## round-163（2026-10-31）— 实例完整性/启动格式/启动窗口/强制 Java`，附「### 🔍 验证」实测结果。
- 完成后按用户要求重新 `build.py` 打包并部署到 `<install-dir>`（保留 `launcher_config.json` 与 `data/`，部署前备份 exe 与 `_internal`，冒烟后清理 `ac.lock` / `.upd_bak`）。
- 回滚：本轮不涉及数据格式迁移；`java_force` 为新可选字段，旧代码读取时忽略，旧配置缺 `java_force_incompatible` 自动落默认 False。源码回滚按文件粒度即可。

## 6. 风险与红线

- **不静默强制**：所有强制都必须由用户勾选或点击确认；禁止默认 True。
- **不动用户真实文件**：`external=True` 实例的修复/补装仍写其自身 `mc_dir`；不删除、不移动任何玩家目录。
- **补装是网络动作**：必须在后台 Worker 中执行，UI 线程零阻塞；失败必须显示原始错误，不吞。
- **Cleanroom 自动下载 Java 25** 会写 `~/.cleanroom/java`（安装器自身行为），需在 UI 明示。
- **PII**：本文档与代码注释不写本机绝对路径/用户名；部署目标用 `<install-dir>` 占位。
