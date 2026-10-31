# AC 用户路径表（自动生成）

> 由 `tools/gen_paths.py` 从源码里的 `# ia[page]: 操作 | 层/组件 | 结果与反馈 [| 备注]` 标记生成。
> **不要手改本文件**：改代码后重跑生成器；`regress.py` 会检查是否过期。

## 首页（`home`）

| 操作 | 层/组件 | 结果与反馈 | 备注 |
| --- | --- | --- | --- |
| 点「继续玩」 | 首页留意行 | 切到实例页并启动该实例 | `src/main_window.py` |
| 点「登录」 | 首页留意行 | 打开账户页（登录 / 切换账户） | `src/main_window.py` |
| 点「更换 Java」 | 首页留意行 | 打开设置页并定位 Java 分区 | `src/main_window.py` |
| 点「修复」 | 首页留意行 | 切到实例页并应用该修复 | `src/main_window.py` |
| 点「启动」 | hero 主按钮 | 启动当前实例（缺 Java/账户时先拦截提示） | `src/main_window.py` |
| 点「结束游戏」 | hero 主按钮（运行中） | 强杀游戏进程并恢复待机状态 | `src/main_window.py` |

## 实例（`instances`）

| 操作 | 层/组件 | 结果与反馈 | 备注 |
| --- | --- | --- | --- |
| 点左侧实例行 | 实例列表 | 右侧详情切换到该实例 | `src/pages_instances.py` |
| 「⋯ → 体检」 | 详情更多菜单 | 打开实例体检对话框（静态扫描 + 本地修复） | `src/pages_instances.py` |
| 点「删除」 | 详情操作条 | 二次确认后移除实例并刷新列表 | `src/pages_instances.py` |
| 点「启动」 | 详情主操作 | 设为当前实例并通知主窗口刷新（首页随即可启动） | `src/pages_instances.py` |
| 点「打开文件夹」 | 详情操作条 | 用系统文件管理器打开实例目录 | `src/pages_instances.py` |
| 点「设为当前」 | 详情操作条 | 切换当前实例并刷新列表/首页 | `src/pages_instances.py` |

## 设置（`settings`）

| 操作 | 层/组件 | 结果与反馈 | 备注 |
| --- | --- | --- | --- |
| 点「从文件安装」 | 模块分区 | 选择 .zip 安装模块，成功/失败弹窗后刷新列表 | `src/modules_page.py` |
| 点左侧分区 | 设置左栏 | 首次进入时构建该分区，之后只切换（未保存草稿保留） | `src/settings_dialog.py` |
| 点「保存」 | 底部操作条 | 写配置并即时应用主题/音效/壁纸，然后回到首页 | `src/settings_dialog.py` |
