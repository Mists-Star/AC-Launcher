import io

# CHANGELOG round-187
p = "CHANGELOG.md"
s = io.open(p, encoding="utf-8").read()
anchor = "## round-186（2026-11-07）— 修改页按版本过滤 + 装加载器顺手装 Fabric API"
new = """## round-187（2026-11-07）— 编辑面板 8 页重排 5 页 + 功能补齐（对齐 PCL）

用户：「实例修改页面很难受，看看其他启动器怎么做的」「主要不是空，是功能和
便捷性和完整性」。

### 结构：8 页 → 5 页（对齐 PCL 的 概览/设置/修改/Mod 管理/导出）

| 新页 | 收编了什么 |
|---|---|
| **概览** | 原基础页（名称/分组 + 状态卡）+ 原高级页的 实例 ID/来源、导出整合包，新增 **快捷方式**（游戏目录 / mods / 存档三个直达按钮，PCL 概览同名卡片） |
| **设置** | 原 启动 / Java / 目录与格式 三页合并：启动格式、版本隔离与自定义目录、实例标识、Java、内存与性能、JVM 与游戏参数、**服务器（自动进入）**、启动前后命令 |
| 修改 / 模组 / 内容 | 原样保留 |

旧 5 个页函数（basic/launch/java/dir/adv）退役，字段一个没丢 —— `_collect`
读的还是同一批属性。

### 功能补齐（对着 PCL 的设置页一项项核）

1. **内存可视化条**（PCL 同款三段色块：其他程序已用 / 本实例分配 / 剩余）+
   一行说明「系统内存 X GB · 可用 Y GB · 本实例分配 Z GB」。分配超过系统内存
   85% 时红字提醒（PCL 同款护栏）。读内存用 ctypes
   `GlobalMemoryStatusEx` —— psutil 在本机 venv 是坏的（缺
   `_psutil_windows`），不要引。
2. **自动进入服务器**（PCL「自动进入服务器」同款）：实例字段
   `auto_server`（IP:端口），启动时自动追加 `--server/--port`。优先级：
   收藏服务器直连（round-83 一次性覆盖）> 实例字段 > 全局参数里的 --server。
   `launch.py` 的 `parse_game_args` 本来就会解析这两段，这里只是把入口从
   「手改游戏参数」升级成独立字段。
3. **补全文件**（PCL 概览「高级管理」同款）：概览页新增按钮，手动触发
   `install_instance` 的幂等校验 + 重下缺失文件 —— 不用等启动失败才知道文件缺了。

### 验证

* `regress.py` **56/56**；i18n **1849 = 1849**；文案门禁 0 命中；PII 351 文件 zero。
* 实拍：概览页（信息+快捷方式+高级管理）、设置页（内存条渲染正确、8192 MB
  时紫段约占一半）、内存说明行文案正确。
* 端到端断言：`auto_server` 写回实例、`_collect` 全字段保留。

""" + anchor
assert s.count(anchor) == 1
s = s.replace(anchor, new)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("changelog ok")

# punchlist
p2 = "docs/quality_punchlist.md"
t = io.open(p2, encoding="utf-8").read()
anchor2 = "### ✅ round-186：修改页按版本过滤 + Fabric API 随装（2026-11-07 15:xx）"
new2 = """### ✅ round-187：编辑面板 8 页重排 5 页 + 功能补齐（2026-11-07 15:3x）

用户：「实例修改页面很难受」「主要不是空，是功能和便捷性和完整性」。

**结构**：概览（名称/状态/ID/快捷方式/导出+补全）· 设置（隔离/格式/Java/内存/参数/
服务器/命令）· 修改 · 模组 · 内容。旧 basic/launch/java/dir/adv 五个页函数退役，
字段一个没丢（`_collect` 读同一批属性）。

**功能补齐**（对着 PCL 设置页逐项核）：
1. 内存可视化条（三段色块）+ 分配超 85% 红字护栏（ctypes 读内存，
   psutil 在本机 venv 是坏的）；
2. 自动进入服务器（`instance.auto_server` → 启动自动追加 --server/--port；
   收藏直连 > 实例字段 > 全局参数）；
3. 补全文件按钮（概览·高级管理，幂等校验 + 重下缺失）。

**仍未做（PCL 有、AC 暂缺，按价值排序）**：游戏窗口标题/自定义信息（要 launch.py
配合，单独一轮）、登录方式限制（仅正版/仅离线，要接登录链路）、实例图标与收藏
（要动首页排序）、GC 显式下拉（ZGC/分代 ZGC，现用 jvm_preset 覆盖）、
内存「自动配置」档（全局已是固定值，要先做全局自动档）。

""" + anchor2
assert t.count(anchor2) == 1
t = t.replace(anchor2, new2)
io.open(p2, "w", encoding="utf-8", newline="").write(t)
print("punchlist ok")
