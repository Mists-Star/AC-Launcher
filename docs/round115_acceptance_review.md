# round-115 · AC 启动器验收报告（代码设计 + 实际作用）

> 验收标准：不是「能跑、不报错」，而是**代码设计上有没有实质缺陷**、**功能是不是真的在起作用**。
> 本轮不修改代码，只做取证与定性。所有结论都带文件行号或运行时实测证据。

---

## 0. 结论速览

| # | 级别 | 问题 | 位置 |
|---|------|------|------|
| 1 | **P0** | 低内存预检用错指标 → 15GB 机器上误报「内存不足」，且默认按钮是「取消」→ 启动被挡 | `main_window.py:2948-2962` |
| 2 | **P0** | 磁盘空间预检由「内存大小」推导磁盘需求，且默认按钮同样是「取消」 | `main_window.py:2963-2987` |
| 3 | **P1** | 56 个图标**全部写死颜色** → 暗色主题下 32 个图标对比度仅 1.89:1（实际不可见）；6 个用的是早已废弃的旧强调色 | `assets/icons/*.svg` |
| 4 | **P1** | 按钮图标尺寸被 Qt 样式默认值静默压成 16×16 → 44×44 的播放按钮里只画了一个 16×16 的小三角 | `icons.py` / `music_page.py:91-106` |
| 5 | **P1** | 中文侧栏出现**两个「联机」**（分组标题 + 条目名同名） | `main_window.py:72-81` + `i18n.py:86,1401` |
| 6 | **P1** | 联机页文案承诺的「大厅编号输入框」在页面层**不存在** | `i18n.py:1381` vs `main_window.py:2512-2542` |
| 7 | **P2** | 首页 hero 内「26.2」重复出现 3 次 | `main_window.py:507/517/521` |
| 8 | **P2** | `aclive.py` 6 项设计缺陷（主线程编码 / 主线程 sleep / eval 无沙箱 / 坐标系不一致 / 私有方法耦合 / WS 无背压） | `aclive.py` |
| 9 | ✅ | round-113 下载源并发改造**复核通过**，一处打折（单次 GET 不复用连接池） | `core/mirror.py` |

### 两条需要**撤回**的旧结论

- ❌「开始游戏会堵死 UI 线程」——**不准确**。`QMessageBox.exec()` 起的是**嵌套事件循环**，用户界面仍可交互；真正发生的是 live view 的 `/ctl` 通道 10s 超时。真因是**预检弹窗 + 误报**（见 #1），不是 `on_play` 路径上的同步网络调用。
- ❌「侧栏分组标题与条目视觉权重几乎相同」——**不准确**。`theme.py:742-748` 的 `nav-group` 是 小字号 + `text_sub` 灰 + 700 字重 + 1px 字距，与条目**有明确层级差**。这条只保留 #5 的「同名」问题。

---

## 1. P0-1 · 低内存预检用错指标，默认取消启动

### 证据

`_available_memory_mb()` 读的是 `GlobalMemoryStatusEx.ullAvailPhys` —— **当前可用物理内存**：

```python
# main_window.py:133-157
def _available_memory_mb() -> int | None:
    """当前可用物理内存（MB）。Windows 用 GlobalMemoryStatusEx 的 AvailPhys；
    其他平台/失败返回 None（调用方跳过警告——宁可漏报不误报）。"""
    ...
    return int(m.ullAvailPhys // (1024 * 1024))
```

但它被拿去和 JVM **堆上限**直接比：

```python
# main_window.py:2948-2962
ram = int(getattr(inst, "ram_mb", 0) or 0) or int(settings.get("ram_mb", 4096) or 0)
avail = _available_memory_mb()
if ram > 0 and avail is not None and ram > avail * 1.05:
    ...
    dont = box.addButton(t("launch.low_mem_continue"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(t("common.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(box.buttons()[-1])      # ← buttons() = [继续, 取消]，[-1] 是「取消」
    box.exec()                                    # ← GUI 线程同步模态
    if box.clickedButton() is not dont:
        return                                    # ← 取消 = 直接终止启动
```

**本机实测触发条件**：总内存 15.19GB / 可用物理 **0.82GB**（残留 `javaw.exe` PID 23964 占 1287MB）→ `4096 > 0.82×1024×1.05 ≈ 882` → 条件成立 → 弹窗。

### 实际作用层面的三个问题

1. **指标错位**。`-Xmx4096M` 是 JVM 堆的**预留上限**，不是「此刻必须空出 4096MB 物理内存」。别的程序占着 13GB 内存，就判「内存不足」。真正该问的是**还能提交多少**（commit headroom = `CommitLimit - CommitCharge`），`PERFORMANCE_INFORMATION` 直接给得到；退一步也该用 `ullTotalPhys` 折算，而不是 `ullAvailPhys`。
2. **默认按钮方向反了**。`setDefaultButton(buttons()[-1])` 把**「取消」**设成默认。于是「误报 → 用户按回车 → 启动被取消」成为默认路径。误报的默认值应该是「继续」。
3. **误报是硬闸门**。`box.exec()` + `return` 让一次误报直接挡死启动，用户必须意识到弹窗并点「继续」。

> 讽刺的是函数 docstring 自己写着「宁可漏报不误报」——**实现做的正好相反**。

### 修复方向

- 判据换成 commit headroom（`ctypes` 取 `PERFORMANCE_INFORMATION`），条件改为 `ram > headroom * 0.9` 才提示；
- 默认按钮改为「继续」；
- 提示降级为状态栏提示 + 可选弹窗，不阻断启动（对齐项目既有约定「UI error handling must not silently interrupt workflows」的镜像要求：**不要用错误提示打断正常流程**）。

---

## 2. P0-2 · 磁盘预检同类的概念错位与硬闸门

```python
# main_window.py:2963-2987
_need_mb = ram + 2048                       # ← 用「内存」推导「磁盘需求」
if _free_mb < _need_mb:
    ...
    _box.setDefaultButton(_box.buttons()[-1])  # 同样是「取消」
    _box.exec()
    if _box.clickedButton() is not _continue:
        return
```

- **概念错位**：磁盘占用由世界存档 / 资源 / 日志 / Mod 决定，与 JVM 堆大小没有因果关系；`ram + 2048` 是把两个无关量绑在一起。
- **默认按钮同样是「取消」**，同样硬闸门。
- `except Exception: pass`（:2986）把 `resolve_game_dir` 抛错一并吞掉——注释说「宁可漏报不误报」，但**吞掉的是取不到路径的真实错误**，用户看不到任何提示。

### 修复方向

- 磁盘需求按「资源包体积 + 世界预留 + 日志预留」估，或直接给一个可配置阈值；
- 默认按钮改「继续」；
- `resolve_game_dir` 失败要单独 `except` 并提示，而不是和「空间够」混在一个 except 里。

---

## 3. P1-3 · 图标颜色写死 → 暗色主题下 32 个图标实际不可见

### 实测数据

```
assets/icons/*.svg  共 56 个
  颜色写死 (fill="#..."/stroke="#...") : 55
  使用 currentColor                   :  0
  无颜色属性                           :  1
```

写死颜色的分布（前几项）：

| 颜色 | 数量 | 用途 |
|------|------|------|
| `#475569` | **32** | slate-700，**暗色**描边 |
| `#FFFFFF` | 11 | 反色（用于深底） |
| `#6366F1` | **6** | **旧强调色**（当前 accent 是 `#7C3AED` / 控制中枢 `#00E5FF`） |

### 对比度实算

| 背景 | `#475569` 对比度 | 结论 |
|------|------------------|------|
| 亮色 `#FFFFFF`（`bg_card`） | 7.58 : 1 | 正常 |
| 暗色 `#2A2A2E`（`THEME_DARK.bg_card`） | **1.89 : 1** | 远低于图形对象 3:1 门槛 → 基本不可见 |
| 控制中枢 `#141B28`（`bg_card`） | **2.28 : 1** | 同上 |

即：**切到暗色主题，56 个图标里有 32 个会糊进背景**。这正是截图里「按钮上是个小方块」的观感来源之一。

### 附带问题

`#6366F1` 与主题 accent（`#7C3AED`）是**两个肉眼可辨的不同紫色**，和全站强调色对不上。项目里已有同类先例（欢迎页 `#A78BFA` → `COLORS["text_accent"]`，round-107），**图标层没跟上**。

### 修复方向

- SVG 统一改 `stroke="currentColor"` / `fill="currentColor"`；
- `icons.py` 增加按上下文着色的入口（用 `QIcon` + `QPixmap` 手工 recolor，或 `QSvgRenderer` + `fill="#RRGGBB"` 覆写）；
- 最小改动方案：把 `#475569` 换成随主题的 `text_sub`（`#9CA3B0` 暗色 / `#6B7280` 亮色），把 `#6366F1` 换成 accent。

---

## 4. P1-4 · 按钮图标尺寸被静默压成 16×16

### 实测

```
folder     btnIconSize=16x16  renderedPixmap=16x16  pixmapNull=False
console    btnIconSize=16x16  renderedPixmap=16x16  pixmapNull=False
delete     btnIconSize=16x16  renderedPixmap=16x16  pixmapNull=False
play       btnIconSize=16x16  renderedPixmap=16x16  pixmapNull=False
```

- 56 个 SVG **全部存在、全部 `isNull=False`** → **不是缺资源**；
- 全项目**没有任何 QSS `icon-size` 规则**，也没有在 `QPushButton(icon(k), text)` 这类构造处设 `setIconSize` → Qt 样式默认 `PM_ButtonIconSize` = **16×16** 生效。

### 命中点

| 位置 | 控件 | 按钮尺寸 | 实际图标 |
|------|------|----------|----------|
| `main_window.py:2577-2586` | 工具箱 folder/console/delete | 高 42 | 16×16 |
| `music_page.py:91,98,105` | 音乐 prev / **play** / next | 40 / **44** / 40 | 16×16 |
| `main_window.py:2526,2530` | 联机 加入/创建 | 高 40 | 16×16 |

只有两处显式设了尺寸：`_make_play_btn()` → `setIconSize(QSize(24,24))`（`main_window.py:480`）、pcl2 布局 → `18/20/22px`。其余走 `icon()` 返回的裸 `QIcon` → 尺寸意图**全部丢失**。

> **修正**：截图里的「小方块 / 纯紫色方块」不是 SVG 渲染失败，是**尺寸被样式默认值吃掉**——44×44 的紫色播放按钮里只画了个 16×16 的小三角。

### 修复方向

- `icons.py` 增 `icon(name, size=None)` 或提供 `icon_button(name, size)`；
- 或在 `theme.py` 加 `QPushButton { icon-size: 18px; }` 统一兜底，再对大按钮单独覆盖；
- 把所有 `QPushButton(icon(k), text)` 改成显式 `setIconSize`。

---

## 5. P1-5 · 中文侧栏两个「联机」

```python
# main_window.py:72-81
NAV_GROUPS = [
    (None, [("nav.home", "home")]),
    ("nav.group.game",      [("nav.instances", "instances")]),
    ("nav.group.resource",  [("nav.store", "store")]),
    ("nav.group.multiplayer",[("lobby.nav_lobby", "lobby")]),   # ← 条目名也叫「联机」
    ("nav.group.system",    [("nav.account", "account"), ("nav.settings", "settings")]),
]
```

| key | 中文 | 英文 |
|-----|------|------|
| `nav.group.multiplayer` | **联机** | Multiplayer |
| `lobby.nav_lobby` | **联机** | Lobby |

中文下两个「联机」上下相邻；英文不重复 → **纯中文 i18n 缺陷**（`i18n.py:86` 与 `i18n.py:1401`）。

**修复方向**：条目名改「大厅」（en 已是 Lobby），或分组标题改「多人」。

---

## 6. P1-6 · 联机页文案承诺的输入框不存在

```python
# i18n.py:1381
"lobby.join_help": "在下方输入朋友发送给你的大厅编号，单击【加入】"
```

但页面层（`main_window.py:2512-2542`）只有：

```python
self._lobby_join   = QPushButton(icon("login"), t("lobby.join"))    # → _open_lobby()
self._lobby_create = QPushButton(icon("add"),   t("lobby.create"))  # → _open_lobby()
```

- **页面层没有编号输入框**（`QLineEdit` 只存在于 `lobby_dialog.py:159-195` 的弹窗里）；
- 「加入大厅」和「创建大厅」两个按钮**走同一个弹窗**（`_open_lobby`），页面层的语义分工是假的。

**实际作用**：用户被文案引导去做一个页面上不存在的操作，页面本身只是个跳转壳。

**修复方向**：要么页面直接放输入框并真正按编号加入，要么改文案指向弹窗。

---

## 7. P2-7 · 首页 hero 信息三重重复

```python
# main_window.py:507 / 517 / 521
name   = QLabel("—")                       # 实例名
detail = QLabel("")                        # "版本 26.2 · 加载器 vanilla"
self.inst_combo = QComboBox()             # 当前项又是 "26.2"
```

同一屏内「26.2」出现 3 次（标题区 / detail 行 / 下拉当前项），稀释 hero 的视觉重心。

**修复方向**：detail 行只留加载器与关键差异，版本号由 combo 独家承载；或 combo 不重复显示当前版本。

---

## 8. P2-8 · `aclive.py` 的 6 项设计缺陷

工具自身的问题，但它决定「live view 能不能作为验收依据」，所以要列。

| # | 位置 | 问题 | 实际后果 |
|---|------|------|----------|
| a | `aclive.py:341-370` `_tick_grab` | **GUI 主线程**做 JPEG 编码 | 帧率抖动直接砸在 UI 线程上，工具本身会污染被测对象 |
| b | `aclive.py:_cmd_type` | 主线程 `time.sleep(delay)` 逐字符 | 阻塞事件循环，帧流在打字期间停 |
| c | `aclive.py:598-616` | `eval`/`exec` **无超时、无沙箱** | 一个卡死的 eval 永久占住串行的 `_tick_pump`，后续命令全排队 |
| d | `aclive.py:653-677` vs `_current_window()` | `_find_widgets` 用 `mapTo(self.win,...)`（相对**主窗口**），但抓帧目标可能是**弹窗** | 对弹窗内控件给出的坐标，点击会错位 |
| e | `aclive.py:585-596` `_cmd_nav` | 直接调私有方法 `self.win._switch_stack(idx)` | 强耦合内部实现，主窗口重构即断 |
| f | `_WSHub.broadcast` | 无 per-client 队列 / 背压 | 慢客户端拖垮整条广播 |

补充：`_cmd_keys` 每个字符重查 `_key_target()`（`aclive.py:533-544`），焦点在打字过程中可能漂移。

---

## 9. ✅ round-113 下载源改造复核（结论：成立）

逐条核到 mll 源码，不是看注释：

| 核查项 | 结论 | 证据 |
|--------|------|------|
| 默认源 = official | ✅ | `settings_dialog.py:130` `"download_mirror": "official"` |
| 并发 48 注入生效 | ✅ | mll `install.py:91/133` 是 `ThreadPoolExecutor(max_workers=max_workers)`，模块级全局查找 → 属性替换能被 `do_version_install` 看到 |
| 连接池 64 生效 | ✅ | mll `install.py:27/114` 各自 `requests.session()` 建**一个** session 复用全部文件 → `MirrorSession` 的 `pool_maxsize=64` 在并发路径**确实生效** |
| `_forge` 单独替换必要 | ✅ | mll `_forge.py` 用 `from ..install import install_libraries` 直接引用；`mirror.py:721-731` 已单独处理 |
| 镜像路径规则 13 条 | ✅ | piston-meta / piston-data / libraries→/maven / 各 loader Maven 均覆盖，路径边界判断正确（`mirror.py:506-508`） |
| `BMCLAPI_OPTIFINE_LIST` 残留 | ❌ **不是缺陷** | 仍被 `fetch_optifine_versions` → `_install_optifine`（新建实例→加载器→OptiFine 入口）使用，与「OptiFine 仅保留在新建实例→加载器路径」的既定决策一致 |
| 连接池跨调用复用 | ⚠️ **打折** | `_RequestsShim.get()`（`mirror.py:480-482`）每次 `MirrorSession()` 新建 → 单次 GET 各有一套池。mll `_helper.download_file` 在**未传 session** 的分支（版本 json / logging config / client jar）走这条路；并发主路径传了 session，故整体影响有限 |

**另一处上游不一致（非我方代码，但影响失败可见性）**：mll `install.py:74-77` 第一个 `download_file` 被 `try/except Exception: pass` 吞掉（失败静默），而 `:85` 的 artifact 下载不吞（会冒泡）。同一函数里两种失败语义。

---

## 10. 建议的修复顺序

1. **先修 #1**（低内存判据 + 默认按钮）——这是唯一会让用户「游戏起不来」的项，改动量小、收益最大。
2. **再修 #3 + #4**（图标颜色 + 尺寸）——暗色主题下 1/3 的图标不可见，且影响每一个页面的观感；一次性改 SVG + `icons.py` 即可。
3. **#5 #6 #7**（文案与信息重复）——低风险纯文案/布局调整。
4. **#2**（磁盘判据）——与 #1 同批改。
5. **#8**（`aclive.py`）——只影响验收工具自身，可在被测对象稳定后再改。

---

## 附：取证方式

- 运行时：faulthandler `dump_traceback_later` 抓主线程堆栈（独立定时器线程，主线程被卡也照样触发）；
- 静态：`minecraft_launcher_lib` 安装源码逐行对照（`venv/Lib/site-packages/minecraft_launcher_lib/install.py`）；
- 视觉：离屏逐页截图目检 + 图标尺寸/对比度脚本实测（`QT_QPA_PLATFORM=offscreen`）。
