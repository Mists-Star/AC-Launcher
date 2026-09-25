# round-95 记忆（2026-09-22/23）

## 本轮完成
- **实例页折叠 bug**：`_toggle_panel` 收拢时对整个 `_left_panel` `setVisible(False)`，折叠按钮随之消失无法再展开。
  修复：新增常驻 40px 展开条（`_strip` + `reopen_btn`），收起后留在最左侧提供反向箭头（pages_instances.py，round-92 注释）。
- **侧边栏「其他」分组**：new `nav.group.other`（zh「其他」/en「Other」）；音乐/成就从「娱乐」移入；
  i18n 删除 `nav.group.fun`（无残留引用）。
- **数据全清**：删除 `data/*`（instances 513MB / shared 68MB / cache 等）+ 根目录 `launcher_config.json`、`ac.lock`、`_startup.log` + 全项目 `__pycache__`，供用户从头测试；保留 `_design_spec.json`。
- **版本库图标扁平化**：`make_version_pixmap` 重写为 HMCL/PCL2 式纯色圆角方块 + 居中版本号；
  无渐变/3D 方块/装饰 chips/更新名；文本色按底色亮度自适应（亮底深字）；调用点 pages_browse.py:246(56) / pages_instances.py:660(48) 无改动。
- **新手教程背后露出主窗口 bug**：根因 = `_force_foreground` 内 `user32.ShowWindow(hwnd, SW_RESTORE)` 把"未显示"的窗口直接拉成可见；
  它原在教程分支之前运行（round-30/46 只挪了 `win.show()`，没防住这条旁路）。
  修复：repaint/raise_/_force_foreground 整体移入 `_show_main()`、紧跟 `win.show()` 之后（main.py round-95 注释）。
- **扫描弹窗 NameError**：`scan_dialog.py` `_rebuild_instance_list` 用 `launcher_label` 但仅有他函数局部 import →
  模块级补 import（scan_dialog.py:26）。这可能就是之前「扫描实例扫不出来」的元凶之一（scan dialog 渲染时崩溃）。

## 用户已确认方向（大改进行中）
1. **AC 默认 = 极致暴力简洁美学**：默认配色/表现去花哨（可划分界限），动画例外——动画要搞好（感官重点）。
2. **完全重构欢迎页面** + **AC 标志改简洁美观**。
3. **花哨美化功能保留但改玩家自选**（theme packs / 主题色 / 管理器模块化不变）。
4. **成就弹窗默认关闭**，可从设置/新手教程里自由打开。
5. 动画三件套：页面切换滑入 + 按钮/卡片按压反馈 + 列表项淡入（现有 effects.py 体系上做，克制）。

## 待办（未做）
- 欢迎页重构、AC logo 简洁化、默认主题极简配色、成就弹窗默认关闭入口、动画三件套、
  OptiFine 资源中心入口移除（用户已确认砍）、导航/折叠的后续回归验证。
- 注意：扫描功能 NameError 修复后需重新验证「扫描实例」能正常出列表（用户原报扫不出）。

## 环境备注
- 启动器进程匹配 Stop-Process 时过滤条件会命中当前 PowerShell 自身 → 必须 `$_.ProcessId -ne $PID`。
- crash.log 位于 `data/crash.log`；`_startup.log` 在根目录。