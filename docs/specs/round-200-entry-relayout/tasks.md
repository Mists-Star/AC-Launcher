# round-200 任务清单（tasks）

> 规格：[spec.md](./spec.md)　批准后才执行
> 纪律：不跑 git；每批更新 `CHANGELOG.md`；诊断脚本 `_` 开头；PII 写占位符

## T1 实例详情操作区重构（`src/pages_instances.py`）

- [x] 名称行主按钮：`instances.launch` → `instances.edit_instance`，图标 `on_accent("settings")`，点击 `_edit_instance_settings(inst)`
- [x] 删除旧动作条（打开文件夹 / 实例设置 / 设为当前 / ⋯ / 删除）
- [x] 新增「管理与诊断」分组标题 + 2×4 网格（体检 / 崩溃分析 / 启动诊断 / 补装依赖 / 创建备份 / 回滚备份 / 复制实例 / 打开文件夹）
- [x] 底部行保留：设为当前 + ⋯ 更多 + 删除
- [x] 「⋯ 更多」精简为 4 项：打开存档 / 应用整合包 / 重构实例 / 导出整合包
- [x] 内容分区（模组 / 资源包 / 光影 / 存档）原样保留

验收：静态断言 + offscreen 1280×800 / 1000×700 截图（仅验布局与按钮可见性）

## T2 启动诊断页内化（`src/launch_diagnostics_dialog.py`）

- [x] 新增 `LaunchDiagnosticsPanel(QWidget)`：`closed` / `open_health` 两个信号
- [x] 复用 `_command_report` / `_health_report` / `_text_view` / `_copy`，不改判据
- [x] `LaunchDiagnosticsDialog` 退化为壳（只包一层 panel；`closed → accept`；`open_health →` 旧弹窗行为）
- [x] `open_launch_diagnostics()` 保留签名不变
- [x] `pages_instances._show_launch_diag()` 推入页内栈；`open_health` → 再压一层 `_health_check`
- [x] 删除 `pages_instances._launch`（先确认无其它引用）

验收：运行时构造面板 `_tabs.count()==2`；点「打开完整体检」后关闭回到诊断面板

## T3 i18n（`src/i18n.py`）

- [x] 新增 `instances.manage_group` / `instances.launch_diag` / `instances.repair_deps_short`（zh + en 各一处）
- [x] 删除 `instances.launch`（zh + en）
- [x] `python regress.py` 的 i18n 对称检查通过

## T4 回归测试（`tests/test_round200_entries.py` + `regress.py`）

- [x] 新建 7 条断言（5 静态 + 2 运行时），风格沿用 `test_round199_audit.py`
- [x] `regress.py` SUITES 追加，套数 67 → 68
- [x] `python regress.py` 全绿（68/68）

## T5 构建与冒烟

- [x] `python -m compileall -q src main.py`
- [x] `python build.py` → 产物落到 `dist_beta\AC_Launcher`（116.9 MB / 4100 文件，exe 6,672,265 B）
- [x] 重命名旧 exe/_internal 为 `.upd_bak` → `robocopy /E`（RC=3 视为成功）
- [x] `AC_NO_TERMS=1 AC_LIVE=1` 10 秒冒烟，确认 pid 存活（ALIVE pid=19068）
- [x] 杀进程、清理锁与 `.upd_bak`（procs=0 / bak=False）

## T6 文档与记忆

- [x] `CHANGELOG.md` 顶部 `## round-200（2026-11-07）— 实例页入口重构（诊断一级可见）` + 验证数据
- [x] `docs/quality_punchlist.md` 追加 `### ✅ round-200`
- [x] 工作区根目录任务记忆文件追加 round-200 段落
- [x] 全文核对无本机绝对路径 / 用户名 / 邮箱

## 待确认（批准前）

1. 名称行主按钮从「体检 / 启动诊断」改为「编辑实例」是否接受（诊断类全部进网格第一行）。
2. 「⋯ 更多」保留 4 项低频是否够——若还要更少，可把「应用整合包 / 导出整合包」也提到网格。
3. 模组启停仍走「内容分区 → 模组」（切到模组页），本轮不内嵌。
