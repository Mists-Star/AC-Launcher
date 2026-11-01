# 世界地图 / 投影预览 / 材料清单 —— 调研与规格

> 状态：调研稿（round-170），**本轮不实现代码**。
> 目标：评估 LumilioCL 一类启动器的新颖功能（存档世界地图、Litematica 投影预览、
> 材料清单导出）在 AC Launcher 里的可行性、成本与分阶段落地路径。

---

## 0. 结论速览

| 功能 | 价值 | 成本 | 风险 | 建议 |
| --- | --- | --- | --- | --- |
| 材料清单 CSV（`.litematic` → 方块统计） | 中高：建筑/生电玩家刚需 | 低（1–2 天量级） | 低 | **先做**（阶段 1） |
| 存档世界地图（顶视图 PNG / 可缩放浏览） | 高：直观、有展示性 | 中（Anvil 解析 + 渲染 + 缓存） | 中（版本/模组方块配色） | 阶段 2 |
| Litematica 3D 预览 | 高（差异化），但非刚需 | 高（体素网格 + OpenGL/相机） | 高（内存/兼容/显卡） | 阶段 3（先 2D 等距降级） |

三者共享同一套底层：**NBT 解析 + 调色板方块表 + 方块配色表**。
先把这层做成独立模块，三个功能才不会被重复实现拖垮。

---

## 1. 现状与差距

AC 目前已有：

- 实例管理、存档目录定位（`instances.open_saves` / `resolve_game_dir`）；
- 崩溃分析、控制台日志、诊断包；
- 下载/安装/修复的统一任务记录（`core/task_center.py`）。

AC 目前没有：

- 任何读取世界存档（`.mca`）的能力；
- 任何读取结构文件（`.litematic` / `.schematic`）的能力；
- 方块 ID → 颜色的映射表；
- 3D/体素渲染基础设施（当前全是 QPainter 2D UI）。

> 注意版权红线：`assets/mc_textures/` 属 Mojang 资源，不入库。地图配色必须
> 使用**自建颜色表**（人工取色的近似色），不能打包原版纹理。

---

## 2. 共享底层设计

### 2.1 模块划分（建议新增）

```
src/core/nbt.py          # 最小 NBT 读取（gzip / zlib / 未压缩；只读）
src/core/block_palette.py# 方块 id → 近似颜色（JSON 资源 + 缺省灰）
src/core/world_map.py    # .mca → 顶视图像素（numpy）
src/core/schematic.py    # .litematic / .schematic → 方块统计 + 分层切片
src/pages_map.py         # 世界地图页面（缩放/平移/维度切换）
src/pages_schematic.py   # 投影预览页面（材料清单 + 分层预览）
assets/block_colors.json # 自建配色表（不入库原版纹理）
```

### 2.2 NBT 读取器

- 只需要**读**，不需要写：标签类型 0–12（End/Byte/Short/Int/Long/Float/Double/
  ByteArray/String/List/Compound/IntArray/LongArray）。
- 输入：gzip（`.mca` 内 chunk 是 zlib；`.litematic` 整体 gzip；`.schematic` gzip）。
- 安全红线：限制递归深度（≤ 64）、数组长度上限（防止恶意/损坏文件吃满内存）、
  单文件解压上限（建议 512 MB）、解析全部放后台线程。
- 纯 Python 实现即可（不引入 `nbtlib` 依赖）；性能瓶颈在方块数组解码，
  用 numpy 处理。

### 2.3 方块配色表

- 键：`namespace:block_id`（如 `minecraft:stone`）或 `block_id[properties]` 前缀匹配；
- 值：`{ "color": "#RRGGBB", "shade": 0.0–1.0 }`（shade 用于方向/高度微调）；
- 未命中：按 hash 生成稳定的灰阶色（同方块始终同色，避免花屏）；
- 模组方块：命中不了就用灰阶 + 图例里标注「未知方块 N 种」。

---

## 3. 存档世界地图

### 3.1 数据格式要点（Anvil / `.mca`）

- `<world>/region/r.<x>.<z>.mca`：每个文件覆盖 32×32 区块（512×512 方块）；
- 文件头 8 KiB：4096 个 4 字节位置项（3 字节扇区偏移 + 1 字节扇区数），
  后接 4096 个 4 字节时间戳；
- 每个区块数据 = 5 字节头（4 字节长度 + 1 字节压缩类型）+ zlib 数据；
- 区块 NBT 关键字段：
  - `DataVersion`（版本判定，决定 BlockStates 打包方式）；
  - `sections[]`：每段 `Y`、`block_states.palette`、`block_states.data`（1.18+）
    或旧版 `Palette` / `BlockStates`；
  - `Heightmaps`：`WORLD_SURFACE` / `MOTION_BLOCKING`（9 位/值，长数组打包）；
  - `biomes`（可选，用于底色/群系着色）。
- 打包规则差异是本功能最大的坑：
  - 1.16+ **不跨 long 边界**（每 long 能放 `64 // bits` 个值，余位补零）；
  - 更早版本**跨 long 连续**；
  - 1.18 起字段名/结构改为 `block_states`。
  → 必须按 `DataVersion` 分派解码器，并用「已知版本样本」做回归。

### 3.2 渲染方案（推荐：顶视图 + 分层缓存）

1. 只解**表层**：用 `Heightmaps.WORLD_SURFACE` 得到每列最高非空气 Y，
   再定位该 Y 所在 section，查 palette 得到方块 id（不遍历整列体素）。
2. 每区块输出 16×16 RGBA（numpy `uint8`），512×512 区块拼成一个 region 图像。
3. 着色：方块基色 × 高度明暗（Y 越高越亮，固定系数曲线）+ 可选群系 tint。
   不做光照/AO——顶视图不需要，做了反而慢。
4. 缓存：`<data>/map_cache/<world_hash>/<dim>/r.<x>.<z>.png`，
   以 mca 的 mtime + size 作为失效键；首次打开按可视区域后台加载。
5. 交互：滚轮缩放（1×/2×/4×/8×，最近邻采样保持像素感）、拖拽平移、
   维度切换（overworld / nether / end）、玩家位置与出生点标记
   （`level.dat` 的 `Data.Player.Pos` / `SpawnX/Y/Z`）。

### 3.3 性能预算

- 单个 region 512×512 方块：解码 + 渲染目标 **≤ 250 ms**（后台线程）；
- 可视区按需加载，同时最多 4 个 region 任务；LRU 内存缓存 ≤ 64 张 region；
- 全图表（数百 region）不做一次性生成，滚动时渐进填充。

### 3.4 风险与对策

| 风险 | 对策 |
| --- | --- |
| DataVersion 分叉导致解码错位 | 版本分派 + 多版本样本回归（见 5.2） |
| 模组方块无颜色 | hash 灰阶 + 「未知方块」统计，不阻断渲染 |
| 巨型存档 IO 卡顿 | 后台线程 + 可视区按需 + mtime 缓存 |
| 存档被游戏占用（写入中） | 只读打开；失败重试一次后提示「请先在游戏内保存退出」 |
| 版权（原版纹理） | 只用自建近似色表，不打包纹理 |

---

## 4. Litematica 投影预览 + 材料清单

### 4.1 `.litematic` 结构

- gzip 压缩的 NBT，根标签 `Schematic`：
  - `Version`、`MinecraftDataVersion`、`Metadata`（Name/Author/Description/
    EnclosingSize/TotalBlocks/TotalVolume/RegionCount）；
  - `Regions`：`<name>` → `{ Position, Size, Palette, BlockStates, TileEntities }`；
  - `Palette`：`"minecraft:air"` → 序号；`BlockStates`：按 `Size` 顺序打包的 long 数组；
  - 负尺寸表示该轴方向为负（用于镜像）。
- 兼容 `.schematic`（MCEdit，根 `Schematic`，`Blocks`/`Data` 字节数组，
  旧格式无 palette）可作为附加支持，优先级低。

### 4.2 材料清单（阶段 1，最先落地）

- 输入：选中的 `.litematic` 文件；
- 输出：CSV（UTF-8 BOM，Excel 友好）：`block_id,count,percentage`；
- 忽略 `minecraft:air` / `cave_air` / `void_air`（可开关）；
- 可选：按 `Metadata.TotalBlocks` 校验总数，不一致时提示文件损坏；
- 失败路径：非 gzip / 非 NBT / 缺 `Regions` → 明确错误文案，不弹栈；
- 入口建议：实例页右键「打开存档」旁新增「导出材料清单」，或独立「工具」页。

### 4.3 2D 预览（阶段 2，降级方案）

- 按 Y 层切片：每层生成 64×64 或自适应缩略图，QPainter 绘制调色板色块；
- 层选择滑杆 + 鼠标悬停显示方块名；
- 成本低，足以支撑「看看结构长什么样」的核心诉求。

### 4.4 3D 预览（阶段 3，可选）

技术选型对比：

| 方案 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- |
| `QOpenGLWidget` + 体素面剔除 | 可控、无额外依赖 | 自写相机/拾取/光照，工作量最大 | 若做，选它 |
| `Qt3D` | 现成相机/材质 | PySide6 里维护弱、包体变大 | 不推荐 |
| `pyqtgraph.opengl` | 上手快 | 依赖 + 大模型性能差 | 只做原型 |

- 体素网格：只生成**暴露面**（六邻接检查），按方块色写入顶点色；
- 分块 VBO（16×16×16），Frustum culling；
- 预算：≤ 2M 方块的结构在集显上 ≥ 30 FPS；超限时自动降级到 2D 切片；
- 交互：轨道相机、层高裁剪、坐标轴指示；
- 明确不做：实体渲染、方块纹理贴图、光影。

### 4.5 风险

| 风险 | 对策 |
| --- | --- |
| 超大投影（数十万方块）内存爆炸 | 解码前按 `TotalVolume` 上限（如 8M）拒绝并提供 2D/清单模式 |
| `BlockStates` 打包差异 | 与地图共用同一套「按 DataVersion 解码」工具 |
| 模组方块无颜色 | 同 3.4：hash 灰阶 + 未知统计 |
| 3D 在低配机掉帧 | 自动降级 2D；设置项「投影预览模式：自动/2D/3D」 |

---

## 5. 验收标准

### 5.1 功能验收

- 材料清单：给定样例 `.litematic`，CSV 行数 = 非空气方块种类数，
  总数与 `Metadata.TotalBlocks` 一致（误差 0）；空/损坏文件有明确错误文案。
- 世界地图：打开存档后 5 秒内出现可视区顶视图；缩放/平移不卡顿；
  切维度正确；缓存命中时二次打开 ≤ 1 秒。
- 投影 2D：分层切换无闪烁；色块与材料清单统计一致。
- 投影 3D（若做）：2M 方块样例 ≥ 30 FPS；超限自动降级且有提示。

### 5.2 回归样本（需要准备，注意不入库）

- 存档：1.12 / 1.16.5 / 1.18.2 / 1.20.1 各一个小世界（各含 1 个 region）；
- 投影：小木屋（< 1 万方块）、中型建筑（~50 万）、超大结构（> 2M，仅测试降级）；
- 样本放本机测试目录，**不进仓库**；测试脚本用路径参数/环境变量定位。

### 5.3 性能与稳定性

- 所有解析在后台线程，主线程单帧阻塞 ≤ 16 ms；
- 恶意/损坏文件：不得崩溃、不得无界内存增长（解析上限生效）；
- 关闭页面后后台任务可取消，不留孤儿线程。

---

## 6. 分阶段计划

| 阶段 | 内容 | 依赖 | 交付物 |
| --- | --- | --- | --- |
| P1 | `nbt.py` + `block_palette.py` + 材料清单 CSV | 无 | 工具入口 + CSV + 测试 |
| P2 | `world_map.py` 顶视图 + region 缓存 + 地图页 | P1 的 NBT/配色 | 可缩放地图页 |
| P3 | 投影 2D 分层预览 | P1 | 投影页（2D） |
| P4（可选） | 投影 3D（QOpenGLWidget） | P3 + 渲染基础设施 | 3D 预览 + 自动降级 |

每阶段独立可交付、可回滚；P4 失败不影响 P1–P3 的价值。

---

## 7. 与现有代码的接入点（只列位置，不改动）

- 存档目录：`src/launch.py` 的 `resolve_game_dir()`（版本隔离感知）；
- 实例操作入口：`src/pages_instances.py` 的实例右键菜单；
- 任务与进度：`src/core/task_center.py` + `src/worker.py`（后台解析复用现有
  `ProgressWorker` 范式）；
- 设置项：`src/settings_dialog.py`（新增「工具 / 地图」分区的懒加载页）；
- i18n：`src/i18n.py` 中英成对新增键，过 `tests/check_copy.py` 文案门禁。

---

## 8. 明确不做（本轮及近期）

- 不写存档（不提供地图编辑/区块删除）；
- 不解析实体/箱子内容（隐私 + 成本）；
- 不做原版纹理贴图渲染（版权）；
- 不做联机服务器地图（需要服务端配合）。
