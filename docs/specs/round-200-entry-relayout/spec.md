# round-200 实例页入口重构 —— 规格（spec）

> 日期：2026-11-07　状态：待批准　范围：`mc_launcher` 桌面端实例页
> 关联：round-195/196/197 的「实例功能页内化」、round-199 的六维审计补漏

## 1. 背景与用户诉求

用户反馈原话：**「部分功能藏太深了，换入口」**，并在追问中勾选：

- 实例体检 / 崩溃分析
- 启动诊断
- **编辑实例（换版本 / 加载器 / 内存）**
- **模组启用 / 禁用、增删**
- **备份 / 还原 / 复制实例**
- 补充原话：**「对应版本的各种管理和功能分类等」**

### 1.1 现状（已核对代码）

| 功能 | 现有入口 | 深度 |
|---|---|---|
| 实例体检 | 详情「⋯ 更多」菜单第 3 项（`pages_instances.py:1848`） | 二级，菜单内 |
| 崩溃分析 | 详情「⋯ 更多」菜单最后一项（`:1855`） | 二级，菜单内 |
| 启动诊断 | 名称行主按钮，标签却是「体检 / 启动诊断」；点开是 **QDialog 弹窗**（`:1738` → `_launch` `:2275` → `open_launch_diagnostics` `launch_diagnostics_dialog.py:193`） | 一级按钮，但语义混装 + 窗口形态与同类功能不一致 |
| 编辑实例 | 详情「实例设置」按钮（`:1813`）+ 右键「编辑实例」；两处**同一功能两个名字** | 一级，但命名不统一 |
| 备份 / 还原 / 复制 | **只有**左侧列表右键菜单（`:1960-1958`） | 详情页完全看不到 |
| 补装缺失依赖 | 只有右键菜单（`:1968`） | 详情页看不到 |
| 模组 / 资源包 / 光影 / 存档 | 详情「内容分区」2×2 按钮（`:1872-1891`） | 一级，已可见，保留 |
| 打开存档 / 应用整合包 / 重构实例 / 导出整合包 | 「⋯ 更多」菜单 | 二级，属低频，**保留** |

结论：用户点名的功能里，除「内容分区」外都缺一级入口；启动诊断还存在
「窗口 vs 页内」两套呈现（round-195/197 已把体检、崩溃分析页内化）。

### 1.2 目标

1. 实例详情页把**所有按实例生效**的常用操作提到一级，并按用途分组。
2. 启动诊断改为**页内面板**，与体检 / 崩溃分析同一套页内栈。
3. 同一功能只保留一个名字、一套实现。

### 1.3 明确不做（避免过度设计）

- 不新增「启动游戏」按钮：启动链路只在首页（`main_window.py` 的 `home._play_instance`）；
  实例页再加一条启动路径会产生两套启动状态机。用户本轮也没要求。
- 不把 `ModsPage` 内嵌进实例详情：内容分区仍走既有 `section_requested` →
  `MainWindow._on_instance_section` 的导航模型。模组启停已在模组页里，入口不是瓶颈。
- 不改右键菜单：它是高级快捷入口，保留全部项。
- 不改启动诊断的报告内容 / 判据（`_command_report` / `_health_report` 原样复用）。
- 不新增图标资源：只用 `assets/icons/` 现有 43 个 SVG。

## 2. 目标布局（实例详情卡）

```
[实例名] [当前标签]                                [编辑实例]  ← accent，名称行
[版本 pill] [加载器] [格式] [加载器版本] [Java]

路径：<mc_dir>

来源 / 创建时间 / ID（QFormLayout 原样）

── 管理与诊断 ──                                  ← 新增分组标题
[实例体检] [崩溃分析] [启动诊断] [补装依赖]        ← 新增 4 列网格 第 1 行
[创建备份] [回滚备份…] [复制实例] [打开文件夹]     ← 新增 4 列网格 第 2 行

[设为当前] ......... [⋯ 更多] [删除]              ← 底部行；更多只剩 4 项低频

── 内容分区 ──                                   ← 原样保留
[模组] [资源包] [光影] [存档]
```

- 「⋯ 更多」菜单保留：打开存档 / 应用整合包 / 重构实例 / 导出整合包。
- 移除「⋯ 更多」里的：实例体检 / 崩溃分析（已升为一级）。
- 移除旧动作条里的：打开文件夹 / 实例设置（分别进网格 / 改为主按钮「编辑实例」）。

## 3. 逐文件改动

### 3.1 `src/pages_instances.py`

#### (a) 名称行主按钮（原 1735-1744）

替换为「编辑实例」：`instances.edit_instance`、`icon settings`、`on_accent("settings")`、
`cls=accent`、`minHeight=36`，点击 `self._edit_instance_settings(inst)`。

```python
        # round-200：主按钮从混装的「体检 / 启动诊断」改为「编辑实例」——
        # 它才是实例页最高频的修改入口（换版本 / 加载器 / 内存 / 模组）。
        edit_btn = QPushButton(t("instances.edit_instance"))
        edit_btn.setProperty("cls", "accent")
        edit_btn.setMinimumHeight(36)
        edit_btn.setIcon(on_accent("settings"))
        edit_btn.setIconSize(QSize(16, 16))
        edit_btn.clicked.connect(lambda: self._edit_instance_settings(inst))
        name_row.addWidget(edit_btn)
```

#### (b) 删除旧动作条，新增分组网格 + 精简底部行（原 1799-1870）

```python
        # ── 管理与诊断（round-200：全部改为一级入口）──
        lay.addWidget(ui_kit.group_label(t("instances.manage_group")))
        mgmt = [
            ("health.title", "tools", lambda: self._health_check(inst)),
            ("instances.crash_analyze", "crash", lambda: self._show_crash(inst)),
            ("instances.launch_diag", "console",
             lambda: self._show_launch_diag(inst)),
            ("instances.repair_deps_short", "download",
             lambda: self._repair_mod_deps(inst)),
            ("instances.backup", "export", lambda: self._backup(inst)),
            ("instances.restore", "refresh", lambda: self._restore(inst)),
            ("instances.duplicate", "add", lambda: self._duplicate(inst)),
            ("instances.open_folder", "folder",
             lambda: self._open_folder(inst)),
        ]
        mgmt_grid = QGridLayout()
        mgmt_grid.setSpacing(8)
        for i, (label_key, ico, slot) in enumerate(mgmt):
            b = QPushButton(t(label_key))
            b.setMinimumHeight(40)
            b.setIcon(icon(ico))
            b.setIconSize(QSize(15, 15))
            b.clicked.connect(lambda _c=False, f=slot: f())
            mgmt_grid.addWidget(b, i // 4, i % 4)
        lay.addLayout(mgmt_grid)

        # ── 底部行：设为当前 / 更多（低频） / 删除 ──
        actions = QHBoxLayout()
        actions.setSpacing(8)
        cur_btn = QPushButton(t("instances.set_current"))
        cur_btn.setMinimumHeight(34)
        cur_btn.setIcon(icon("check"))
        cur_btn.setIconSize(QSize(15, 15))
        cur_btn.setEnabled(inst.id != self.mgr.current_id)
        cur_btn.clicked.connect(lambda: self._set_current(inst.id))
        actions.addWidget(cur_btn)
        actions.addStretch(1)

        more_btn = QPushButton()
        more_btn.setToolTip(t("instances.more_actions"))
        more_btn.setFixedSize(34, 34)
        more_btn.setIcon(icon("more"))
        more_btn.setIconSize(QSize(18, 18))
        more_btn.setCursor(Qt.PointingHandCursor)
        more_btn.setProperty("cls", "surface")
        _more_menu = QMenu(more_btn)
        for key, ico, slot in [
            (t("instances.open_saves"), "folder",
             (lambda: self._open_saves(inst))),
            (t("instances.apply_pack"), "download",
             (lambda: self._apply_mrpack_to(inst))),
            (t("instances.rebuild"), "refresh",
             (lambda: self._rebuild_instance(inst))),
            (t("instances.export_pack"), "export",
             (lambda: self._export_pack(inst))),
        ]:
            a = _more_menu.addAction(icon(ico), key)
            a.triggered.connect(lambda _c=False, f=slot: f())
        more_btn.setMenu(_more_menu)
        actions.addWidget(more_btn)

        del_btn = QPushButton(t("instances.delete"))
        ...（原样：danger / delete 图标 / minHeight 34）
        lay.addLayout(actions)
```

保留原有的「⋯ 别用文字⋯」注释与 `surface` 类，避免字体豆腐块回归。

#### (c) 删除 `_launch`，新增 `_show_launch_diag`（原 2275-2292）

全仓只有 `pages_instances.py:1743` 引用 `_launch`（改动后无引用），直接删除；
新增方法放在 `_show_crash` 附近：

```python
    def _show_launch_diag(self, inst: Instance):
        """启动诊断：**页内**（round-200）。

        round-177 起它是 QDialog 弹窗，而体检（round-195）/ 崩溃分析
        （round-197）都已页内化——同一类实例功能不该有窗口 / 页面两套呈现。
        """
        from .launch_diagnostics_dialog import LaunchDiagnosticsPanel
        panel = LaunchDiagnosticsPanel(inst, mgr=self.mgr, parent=self)
        panel.closed.connect(self._close_feature)
        panel.open_health.connect(lambda _i=inst: self._health_check(_i))
        self._push_feature(panel)
```

### 3.2 `src/launch_diagnostics_dialog.py`

新增 `LaunchDiagnosticsPanel(QWidget)`，`LaunchDiagnosticsDialog` 退化为壳。

- 复用现有 `_command_report` / `_health_report` / `_text_view` / `_copy`，不改判据。
- 面板结构（与 `HealthPanel` 同风格，内容边距 20/14/20/16）：

```python
class LaunchDiagnosticsPanel(QWidget):
    closed = Signal()        # 页内：请求返回
    open_health = Signal()   # 页内：请求外层压入体检面板

    def __init__(self, inst, mgr=None, parent=None):
        ...
        title = QLabel(t("diag.launch_title", name=getattr(inst, "name", "")))
        title.setProperty("cls", "big")
        sub = QLabel(t("diag.subtitle")); sub.setProperty("cls", "sub")
        self._tabs = QTabWidget()
        self._cmd_view = self._text_view()
        self._cmd_view.setPlainText(_command_report(inst))
        self._tabs.addTab(self._cmd_view, t("diag.tab_command"))
        self._health_view = self._text_view()
        self._health_view.setPlainText(_health_report(inst))
        self._tabs.addTab(self._health_view, t("diag.tab_health"))
        row: [复制][打开完整体检][关闭]
```

- 按钮用 `ui_kit.make_button(..., min_h=34)`；「打开完整体检」→ `self.open_health.emit`；
  「关闭」→ `self.closed.emit`。
- `LaunchDiagnosticsDialog` 改为：`resize(900, 580)`、正文只放一个
  `LaunchDiagnosticsPanel`，`panel.closed → self.accept`，`panel.open_health → 旧行为`
  （`open_health_dialog(self, inst, mgr)`，供历史调用点使用）。
- `open_launch_diagnostics(parent, inst, mgr)` 保留不变（外部/测试仍可调用）。

### 3.3 `src/i18n.py`（zh-CN / en-US 各一处）

新增：

| key | zh-CN | en-US |
|---|---|---|
| `instances.manage_group` | 管理与诊断 | Manage & diagnose |
| `instances.launch_diag` | 启动诊断 | Launch diagnostics |
| `instances.repair_deps_short` | 补装依赖 | Fix dependencies |

删除（确认无其它引用后）：`instances.launch`（原值「体检 / 启动诊断」）。

要求：`zh-CN` 与 `en-US` 键集合完全对称（`regress.py` 内置 `run_i18n`）。

### 3.4 `tests/test_round200_entries.py`（新建）

静态断言（读源码字符串）：

1. `pages_instances.py` 含 `t("instances.manage_group")` 与 8 个网格 label key。
2. `_more_menu` 构造块内**不再**含 `health.title` / `instances.crash_analyze`。
3. `_show_launch_diag` 已定义；`pages_instances.py` 不再调用
   `open_launch_diagnostics`，也不再出现 `def _launch(`。
4. `launch_diagnostics_dialog.py` 含 `class LaunchDiagnosticsPanel`，且
   `closed = Signal()` / `open_health = Signal()` 各一处。
5. i18n：两字典都含新增 3 键；`instances.launch` 两边都已删除。

运行时断言（offscreen）：

6. 用 fake `_Inst`（`name/game_dir/mc_dir/version_id/game_version/java_path/
   loader/ram_mb/jvm_args`，目录用 `tempfile.mkdtemp()`）构造
   `LaunchDiagnosticsPanel`：不抛异常，`_tabs.count() == 2`，
   `hasattr(panel, "closed")` 与 `hasattr(panel, "open_health")`。
7. `_command_report(inst)` 返回非空字符串且包含实例名（拼不出命令时走
   `diag.cmd_failed` 分支也算通过——诊断必须如实写失败原因）。

### 3.5 `regress.py`

`SUITES` 末尾追加：

```python
("实例页入口重构（诊断一级可见）", "test_round200_entries.py", "script"),
```

套数 67 → 68。

### 3.6 文档与记忆

- `CHANGELOG.md` 顶部追加 `## round-200（2026-11-07）— 实例页入口重构（诊断一级可见）`，
  含改动清单 + 「### 🔍 验证」实测数字。
- `docs/quality_punchlist.md` 追加 `### ✅ round-200` 段落。
- 任务记忆：工作区根目录 `任务记忆_AC启动器_round163_实例完整性强制Java_2026-10-31.md`
  追加 `## 2026-11-07 round-200 — 实例页入口重构`。
- PII 红线：任何文档不写本机绝对路径 / 用户名 / 邮箱。

## 4. 验收标准

| # | 判据 | 验证方式 |
|---|---|---|
| 1 | 详情页首屏可见「实例体检 / 崩溃分析 / 启动诊断 / 补装依赖 / 创建备份 / 回滚备份 / 复制实例 / 打开文件夹」8 个按钮 | 静态断言 + offscreen 截图目视 |
| 2 | 「⋯ 更多」只剩 4 项低频 | 静态断言 |
| 3 | 点启动诊断 = 页内换页（无 QDialog 弹出） | 运行时构造 + 目视 |
| 4 | 启动诊断页内「打开完整体检」压入体检面板，关闭后回诊断面板 | 代码路径 + 目视 |
| 5 | 名称行主按钮 = 「编辑实例」，点击进编辑面板 | 目视 |
| 6 | i18n 中英对称，无缺失键 | `python regress.py` 的 `run_i18n` |
| 7 | 全量回归 68/68 | `python regress.py` |
| 8 | 打包可运行 | `python build.py` → 部署 → `AC_NO_TERMS=1 AC_LIVE=1` 10 秒冒烟 pid 存活 |

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 4 列网格在窄窗口被裁（详情滚动条横向关闭） | 每个按钮 `setMinimumHeight(40)`，标签用短键（`补装依赖` 而非 `补装缺失依赖`）；离屏 1280×800 / 1000×700 两档截图核对 |
| 删除 `instances.launch` 影响其它调用点 | 改动前全仓 grep `instances.launch`；仅 `pages_instances.py:1738` 一处 |
| 删除 `_launch` 影响测试 | 全仓 grep `_launch`；若有测试引用则同步改为 `_show_launch_diag` |
| 弹窗壳与页内面板行为分叉 | 弹窗壳只包一层 `LaunchDiagnosticsPanel`，不复制逻辑 |
| 备份 / 还原入口升为一级后误触 | 沿用 `_backup` / `_restore` 内已有的确认与进度逻辑，不新增行为 |
