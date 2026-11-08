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
| 点「编辑实例」 | 详情名称行主按钮 | 页内打开编辑面板（换版本/加载器/内存/模组） | `src/pages_instances.py` |
| 点「实例体检」 | 详情「管理与诊断」网格 | 页内体检面板（静态扫描 + 一键本地修复） | `src/pages_instances.py` |
| 点「崩溃分析」 | 详情「管理与诊断」网格 | 页内崩溃分析面板（崩溃原因 + 修复建议） | `src/pages_instances.py` |
| 点「启动诊断」 | 详情「管理与诊断」网格 | 页内面板：启动命令 / classpath / 体检摘要 | `src/pages_instances.py` |
| 点「补装依赖」 | 详情「管理与诊断」网格 | 扫描缺失前置并自动安装（后台 Worker） | `src/pages_instances.py` |
| 点「创建备份」 | 详情「管理与诊断」网格 | 后台打包实例快照到备份目录 | `src/pages_instances.py` |
| 点「回滚备份…」 | 详情「管理与诊断」网格 | 选历史快照，二次确认后恢复 mods / config / 存档 | `src/pages_instances.py` |
| 点「复制实例」 | 详情「管理与诊断」网格 | 输入新名后后台克隆实例目录 | `src/pages_instances.py` |
| 点「删除」 | 详情底部操作行 | 二次确认后移除实例并刷新列表 | `src/pages_instances.py` |
| 点「打开文件夹」 | 详情「管理与诊断」网格 | 用系统文件管理器打开实例目录 | `src/pages_instances.py` |
| 点「设为当前」 | 详情底部操作行 | 切换当前实例并刷新列表/首页 | `src/pages_instances.py` |

## 模组（`mods`）

| 操作 | 层/组件 | 结果与反馈 | 备注 |
| --- | --- | --- | --- |
| 切换当前实例 | 模组页实例选择 | 重新读取该实例 mods 目录并刷新列表 | `src/pages_instances.py` `src/main_window.py` |
| 点模组行启停按钮 | 模组页列表行 | 重命名 .disabled 后缀并即时刷新状态 | `src/mod_list.py` `src/main_window.py` |
| 批量勾选后删除/启用 | 模组页批量操作条 | 确认后批量落盘并给出结果反馈 | `src/pages_instances.py` `src/main_window.py` |

## 资源中心（`store`）

| 操作 | 层/组件 | 结果与反馈 | 备注 |
| --- | --- | --- | --- |
| 点分类胶囊 | 资源中心分类栏 | 切换资源类型并回到第 1 页重新搜索 | `src/pages_browse.py` |
| 改筛选侧栏（来源/排序/版本/加载器/分类/隐藏已装） | 筛选侧栏 | 350ms 防抖后按服务端参数重搜 | `src/pages_browse.py` |
| 点「显示/收起筛选」 | 资源中心页头 | 折叠或展开筛选侧栏，不重建结果 | `src/pages_browse.py` |
| 输入关键词并回车 | 资源中心搜索框 | 350ms 防抖后重搜，页码归零、旧结果不回灌 | `src/pages_browse.py` |
| 滚动结果列表 | 资源中心结果区 | 只加载进入视口的图标，占位图先上屏 | `src/pages_browse.py` |
| 点「上一页 / 下一页 / 回到首页」 | 资源中心页码器 | 按双源 offset/total 游标切片，结果已缓存则零请求 | `src/pages_browse.py` |
| 点资源卡片 | 资源中心结果卡片 | 页内栈切到详情（全部版本 / 前置 / 下载），不新开窗口 | `src/pages_browse.py` |
| 点「下载 / 安装」 | 资源中心卡片按钮 | 按目标实例下载，缺前置时先询问补齐 | `src/pages_browse.py` |

## 版本库（`versions`）

| 操作 | 层/组件 | 结果与反馈 | 备注 |
| --- | --- | --- | --- |
| 选择游戏版本 | 版本库页版本列表 | 展示该版本可用加载器与推荐构建 | `src/pages_browse.py` `src/main_window.py` |
| 点「安装此版本」 | 版本库页安装按钮 | 页内创建实例并跳到实例页 | `src/pages_browse.py` `src/main_window.py` |
| 点「资源中心」返回 | 版本库页页头 | 切回资源中心列表并保留搜索词 | `src/pages_browse.py` `src/main_window.py` |

## 联机大厅（`lobby`）

| 操作 | 层/组件 | 结果与反馈 | 备注 |
| --- | --- | --- | --- |
| 输入大厅编号并回车 | 联机大厅页编号输入框 | 加入指定大厅 | `src/lobby_dialog.py` `src/main_window.py` |
| 点「创建大厅」 | 联机大厅页主按钮 | 打开联机配置并生成大厅 | `src/lobby_dialog.py` `src/main_window.py` |
| 查看加入帮助 | 联机大厅页说明卡 | 展示编号获取与联机前置说明 | `src/lobby.py` `src/main_window.py` |

## 设置（`settings`）

| 操作 | 层/组件 | 结果与反馈 | 备注 |
| --- | --- | --- | --- |
| 点「从文件安装」 | 模块分区 | 选择 .zip 安装模块，成功/失败弹窗后刷新列表 | `src/modules_page.py` |
| 点左侧分区 | 设置左栏 | 首次进入时构建该分区，之后只切换（未保存草稿保留） | `src/settings_dialog.py` |
| 点「保存」 | 底部操作条 | 写配置并即时应用主题/音效/壁纸，然后回到首页 | `src/settings_dialog.py` |

## 工具箱（`toolbox`）

| 操作 | 层/组件 | 结果与反馈 | 备注 |
| --- | --- | --- | --- |
| 点工具箱快捷入口 | 工具箱页工具卡 | 页内打开对应工具或跳到目标页 | `src/main_window.py` `src/main_window.py` |
| 打开诊断工具 | 工具箱页工具卡 | 生成诊断报告并展示可修复项 | `src/diagnostics.py` `src/main_window.py` |
| 打开 Java 管理 | 工具箱页工具卡 | 跳到设置页并定位 Java 分区 | `src/settings_dialog.py` `src/main_window.py` |
