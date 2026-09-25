# round-96/97 记忆（2026-09-23）

## round-96：单实例守卫加固
- 用户报「新手教程背后露出启动器页面」：根因 = 清理数据删了 ac.lock + 旧实例未退出，
  新实例 `tryLock` 误成功 → 双实例并存，教程叠在旧主窗口上。
- 修复 main.py：`tryLock` 成功后仍 `FindWindowW` 按 `APP_DISPLAY` 找窗口，找到则提拉旧实例并 `unlock` 退出；
  splash_window.py `__init__` 设 `setWindowTitle(APP_DISPLAY)`，让 splash 阶段也可被按标题识别。
- 实测：删运行中 ac.lock 再启动 → 日志 "another instance already running — raised it"，进程数不增。

## round-97：扫描/首页三处 bug
1. **PCL2 分组折叠完全失效**：组键是内部码（"PCL-CE"），组头文字是显示名（"PCL2"），
   旧 `_toggle_group` 靠 `launcher in w.text()` 反查按钮 → 永匹配不上 → 折叠无反应。
   修复：`_rebuild_instance_list` 增 `_group_headers[launcher] = hbtn` 直接持有按钮引用；
   `_toggle_group` 直查 + 只替换行首 ▾/▸（老实现 `text[2:]` 每次点击累积空格）。
2. **扫描结果界面横向溢出（右侧"15/导入文件"被裁）**：`_InstanceRow` sizeHint 宽度不受限
   （长实例名/长详情），QListWidget 随行撑宽 → 整列顶出视口。
   修复：`item.setSizeHint` 行宽封顶 `max(viewport-24, 320)`，行内布局自动压缩详情区。
3. **首页实例网格被压成小条（首次导入后）**：QScrollArea 的 minimumSizeHint 不自动跟随
   内容最小高度 → 网格卡被布局压到 ~150px，卡片底部裁切 + 出现滚动条。
   修复：`_refresh_inst_grid` 非空分支按 rows 计算需要高度并 `setMinimumHeight`（≤520，
   至多 3 行），空态分支还原 `setMinimumHeight(96)` 防 min>max。

## 验证
- py_compile 通过（scan_dialog.py / main_window.py）。GUI 复测：扫描并折叠 PCL2 组、
  检查右侧控件完整、导入 1 个实例看首页卡片完整显示。

## 备注
- Python 陷阱：QToolButton 的文本含 ▾/▸ 时按字面字符编辑，勿用索引截断。
- QListWidget 的 sizeHint/minimumSizeHint 会随 item 的 sizeHint 变化——行宽必须封顶。