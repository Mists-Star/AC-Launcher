# 启动方式（LaunchMode）深化设计

> round-93 起。目标：**不加新功能模块，把"启动"这一件事做深**——
> 从「所有实例走同一条启动链路」升级为「区分启动方式 + 自动选对方式」。
>
> 本文件是施工图，TRAE 按 round 顺序实现，WorkBuddy 按 round 收推送。

---

## 一、现状盘点（已有地基）

启动链路主入口：`src/launch.py:512 launch_instance()`
调用点：`src/main_window.py:3259`，完成回调 `:3276 _on_launch_done`

| 已有能力 | 位置 | 说明 |
|---|---|---|
| JVM 预设四档 | `launch.py:134 build_options()` | `default / auto / aikar / custom`；`auto` 按内存分档（≥8G 给完整 Aikar，否则轻量 G1GC 组） |
| 内存自适应 | `build_options()` | `Xms = clamp(ram/2, 512, ram)`，ram 非法兜底 2048 |
| 实例级渲染器 | `instances.py:74` | `auto / software / legacy` |
| Java 兼容自动选 | `core/java.py select_java()` | 按 MC 版本限 major 范围 |
| 共享库去重 | `launch.py:537` 调 `shared_libs.ensure_shared_libraries()` | 启动前合并到全局池 |
| **启动格式自适应** ⭐ | `instances.py:297 detect_format()` + `pages_instances.py:1832` | **已有成功先例**：`auto` 自动探测磁盘布局，可手动强制覆盖 —— 启动方式的 UI/交互直接照搬这个模式 |
| 版本完整性跳过 | `launch.py:552+` | 已装则跳过 install/repair，零下载启动 |
| 模组冲突预检 | `pages_instances.py:1728` | 启动前静态扫描 |
| 崩溃归因 | `launch.py:803 classify_exit()` / `:864 explain_exit()` | **仅用于展示状态栏，未持久化** |
| 服务器直连 | `launch.py:512 server_override/port_override` | round-83 收藏一键直连 |
| 进程优先级 | `launch.py:448 _priority_bits()` | Windows 原生 creationflags |
| 离线账户 | `accounts.py:111` | `type == "offline"` |
| 网络延迟探测 | `net_api.py:401 mirror_latencies()` | 可复用作网络可达性输入 |

---

## 二、三个必须补的地基（缺口）

### 缺口 1：没有实例级启动历史 → 自适应没有输入 ⚠️ 最关键

`classify_exit()` 的结果只在 `main_window.py:3432/3461/3508` 展示一次就丢了。
启动器重启后**不知道这个实例上次是不是崩的** → 任何"根据上次结果自适应"的逻辑都无法成立。

`Instance`（`instances.py:37`）目前**没有任何运行历史字段**。
（全局的 `launch_count.txt` 是启动器打开次数，给 onboarding 用，不是实例级。）

### 缺口 2：没有"启动方式"一等概念

`launch_instance()` 里所有分支都是"参数差异"，没有"路径差异"。
玩家的真实场景是有区别的：断网想进单人、装了 mod 崩了想排查、熟了不想每次等检查——
现在这几种情况走的是同一条路。

### 缺口 3：safe（安全）模式无实现

MC 无内建安全模式。主流做法是**临时移走 `mods/`**，但这属于**高风险文件操作**，
必须做原子性保证和崩溃自愈，否则玩家模组永久消失。

---

## 三、设计

### 3.1 五种启动方式

| mode | 语义 | 相比 normal 跳过 | 典型触发 |
|---|---|---|---|
| `normal` | 常规：完整链路 | — | 默认兜底 |
| `quick` | 极速：版本已装且无变更 → 跳网络校验 | 版本完整性网络校验、模组预检（本地存在性检查**不跳**） | 自适应：版本完整 + 上次正常退出 |
| `offline` | 离线：断网可玩 | 鉴权刷新、版本下载、模组更新检查 | 自适应：无网络 / offline 账户 |
| `safe` | 安全：临时禁用全部模组 | 不改链路，仅启动前移走 `mods/`，退出还原 | 自适应：连续崩溃 ≥1 次 → **建议**（弹一次） |
| `direct` | 直连：收藏服务器一键进 | 同 quick + 注入 `--server/--port` | 收藏服务器启动（round-83 能力升格） |

### 3.2 自适应决策器

新增 `resolve_launch_mode(inst, settings, account) -> (mode, reason_key, reason_kwargs)`

**优先级链**（先硬约束，后软优化）：

1. 实例目录不存在 → 直接报错（已有 `err.launch_missing_dir`）
2. **无网络** 或 账户为 `offline` → `offline`
3. `consecutive_crashes >= 1` → `safe`（**弹一次建议**，记住"已建议过"，不静默改玩家环境）
4. 版本完整 + 上次正常退出 + mods 无变更 → `quick`
5. 否则 → `normal`

**可解释性（硬要求）**：进度对话框首行/状态栏必须显示选择了哪种方式及原因，例如
「已自动选择：极速启动（版本完整 · 上次正常退出）」+ 一个「改用其他方式 ▾」入口。
自适应**永远可覆盖**，玩家在实例设置里可强制指定某一种。

### 3.3 需要持久化的实例字段

```python
# Instance 新增（instances.py:37，asdict(:541) 会自动带，save(:669) 无需改）
last_launch_at: str = ""      # 上次启动 ISO 时间
last_exit_code: int = 0       # 上次退出码
last_launch_mode: str = ""    # 上次实际用的启动方式
consecutive_crashes: int = 0  # 连续崩溃次数（正常退出清零）
last_crash_at: str = ""       # 上次崩溃时间
safe_suggested: bool = False  # 安全模式是否已建议过（防反复弹）
```

---

## 四、分 round 落地

### round-93 — 实例级启动历史持久化（地基，先做这个）
- `Instance` 新增上述 6 个字段
- 在游戏进程退出回调写回（`main_window.py` 进程跟踪处 + `:3276 _on_launch_done` 附近）：
  正常退出 → `consecutive_crashes = 0`；非 0 退出码 → `+1` 并记录 `last_crash_at`
- **验收**：启动 → 进游戏 → 退出 → 重启启动器，实例详情能看到上次启动时间与结果

### round-94 — LaunchMode 一等概念 + 决策器
- 新增 `src/core/launch_mode.py`：`LaunchMode` 枚举 + `resolve_launch_mode()` + 各 mode 的 skip 集合
- `launch_instance()` 接受 `mode` 参数，按 skip 集合跳过对应步骤
- 网络可达性：复用 `net_api.mirror_latencies()` 的超时判定，包一层 `has_network()` 并**缓存**
  （避免每次启动都多花几百 ms 探测）
- **验收**：断网 + offline 账户能正常进游戏；自适应结果文案正确显示

### round-95 — 启动方式 UI
- 首页启动大按钮：`右键 / 长按` → 启动方式菜单（常规 / 极速 / 离线 / 安全）
- 实例设置：新增「启动方式」下拉（自动 / 常规 / 极速 / 离线 / 安全）
  → **UI 与交互照搬 round-82 的启动格式自适应**（`pages_instances.py:1832`）：
  `auto` 时下方灰字实时显示「检测到：xxx」，手动强制时显示「已强制：xxx」
- i18n 中英双语补齐
- **验收**：中英切换无缺字；强制指定后自适应不再覆盖

### round-96 — safe 模式实现 ⚠️ 高风险，务必谨慎
- 启动前 `mods/` → `.ac_mods_disabled/`（rename，同分区原子操作）
- 游戏退出后**必须还原**：`finally` 保证 + **启动器每次启动时扫残留自愈**
  （否则启动器崩溃 → 玩家模组永久消失 = P0 数据丢失）
- UI 明确提示「安全模式：本次启动不加载任何模组」
- **验收**：safe 进游戏再退出，`mods/` 完好；**强制杀启动器进程后重启，mods 能自动还原**

### round-97 — 启动实例优化（实测提速）
- quick 模式实测：二次启动从点击到进程 spawn 的耗时
- 目标：热启动 < 1.5s；冷/热启动对比数据写进 CHANGELOG
- **注意**：本地文件存在性检查**不跳**（只跳重复的网络校验），否则文件被删了检测不到

---

## 五、风险红线

| 风险 | 级别 | 防范 |
|---|---|---|
| safe 模式移走 mods 后未还原 | **P0 数据丢失** | `finally` + 启动器启动自愈扫描 + 明确 UI 提示 |
| quick 跳过完整性校验 → 文件缺失启动失败 | P1 | 只跳**网络**校验，本地存在性检查保留 |
| offline 模式微软账户无 token 无法启动 | P1 | 仅对 `offline` 账户或已缓存 token 生效，否则回落 normal 并提示 |
| 自适应静默改变玩家预期 | P1 | 必须显示原因文案 + 始终可手动覆盖 |
| `has_network()` 每次启动探测拖慢启动 | P2 | 结果缓存（建议 60s TTL） |

---

## 六、与既有纪律的关系

- 遵循 `AGENTS.md`：TRAE 只写代码不碰 git；每 round 更新 `CHANGELOG.md`（`## round-NN（日期）— 主题`）
- 诊断脚本 `_` 开头（已 gitignore）
- 版本号 `v1.0.0` 仍待 `RELEASE_1.0.0_CHECKLIST.md` 全完工，本批次**不 bump**
