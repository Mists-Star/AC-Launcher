# round-98 记忆（2026-09-25）

本轮修两个玩家实测 bug。

## 1. PCL 导入的 1.17 实例启动报「版本不存在 / 文件不见了」

### 现象
- 用户在 PCL2 导入 `1.17.1-OptiFine_H1`（来源 `D:\Appdata\<PCL2数据目录>\.minecraft\versions\1.17.1-OptiFine_H1`），
  启动报版本找不到；玩家看磁盘「目录还在、扫描也还能识别」。

### 根因（已实测复现）
链路：`scan._Collector.add_standard` → `import_external(mode="copy")` → `detect_format` → `versions_root` → mll。

1. PCL2 开了**版本隔离**，版本目录 `versions/<id>/` 里既有 `<id>.json`（启动所需）又有
   `saves/ mods/ options.txt`（游戏数据）。扫描据此把 `mc_dir` 定成**版本目录本身**（正确）。
2. 复制导入时**把版本目录拍平**到 `<instance>/.minecraft/*`（旧实现直接 `copytree(src.mc_dir, inst.mc_dir)`），
   产物既不是标准 `.minecraft` 也不是版本目录。
3. `_probe_format` 看到 `<mc>/<id>.json` 存在 → 判为 `"iso"` → `versions_root` 返回
   **实例目录的上级**（`data/instances`）。
4. mll 固定按 `<root>/versions/<id>/<id>.json` 解析 → `data/instances/versions/<id>/<id>.json`
   **必然不存在** → `minecraft_launcher_lib.exceptions.VersionNotFound`
   （`Version <id> was not found`，玩家口中的「不存在这个版本/文件不见了」）。

实测证据（修复前）：
```
mll reads = <repo>\data\instances\versions\1.17.1-OptiFine_H1\1.17.1-OptiFine_H1.json
EXISTS    = False
```

### 修复（`src/instances.py` `import_external` copy 分支）
- 复制前判 `isolated_src = bool(version_id) and isfile(mc_dir/<version_id>.json)`
  （= 源就是版本隔离目录）。
- 是 → 目标目录取 `<new>/.minecraft/versions/<version_id>/`，并给实例标 `isolation="isolated"`
  （存档/模组仍落在该版本目录）；否 → 保持原行为（复制到 `<new>/.minecraft`）。

### 验证（新建临时数据目录跑真实代码路径）
```
isolation     = isolated
mc_dir        = ...\data\instances\<id>\.minecraft
game_dir      = ...\instances\<id>\.minecraft\versions\1.17.1-OptiFine_H1
detect_format = vanilla
versions_root = ...\instances\<id>\.minecraft
JSON EXISTS   = True     ← mll 能读到
saves kept    = True
mods_dir ok   = True
```

### 存量脏实例
`data/instances/e3243f0207ae.json` 仍是拍平布局（本轮不做数据迁移）。
处理：删除该实例 → 重新扫描导入（复制）即可，新复制会带上 `versions/<id>/` 层级。
源目录 `D:\Appdata\<PCL2数据目录>` 不受影响。

## 2. 欢迎页（启动 splash）AC 两个标识偏移

### 现象
玩家报「AC 两个标识偏移了」，要求并入 AC logo 简洁化重构一起做。
实际在跑的启动页是 `SplashWindow`（`main.py:281`）；`WelcomeWindow` 已是死代码（仅诊断脚本引用）。

### 根因（实测数据）
MC 像素字（family = `Minecraft AE`）是**位图字体**，`QFontMetrics` 与字形脱节。
96px 下实测：`advance=72 / ascent=84 / descent=12`，而每字墨迹只占
**origin +0..59px、基线上 84..1px（60×84）**。

旧实现 `_draw_text_letter` 按 `-horizontalAdvance/2` 居中 + 硬编码 `cx-62` / `cx+2` 排布：

| 字母 | 实际墨迹 X（相对 cx） | Y |
|---|---|---|
| A | −98 … −39 | −48 … 35 |
| C | −34 … +25 | −48 … 35 |

整组墨迹中心 = (−36.5, −6.5) → **整体偏左 ~36px、偏下 ~6px**，而 `_glow` 光晕画在 (cx, cy)
上，错位被放大得很明显。

### 修复（`src/splash_window.py`）
- 新增 `_ink_bbox()` + `_render_ac_glyphs()`：逐字渲染到离屏图 → 量**真实墨迹包围盒**后裁边
  （和 `welcome_window.py` round-93 同思路），`__init__` 预渲染一次。
- 新增 `_draw_glyph()`：以 (cx, cy) 为**墨迹中心**画预渲染图；交错动画语义不变
  （缩放 0.6→1.0 + 渐显 + 上浮 14px），光晕按墨迹尺寸给半径。
- 删除 `_draw_text_letter`（不再依赖失真 metrics）；矢量兜底字母同步居中（`cx-63` / `cx+53`）。

### 验证（offscreen 实测墨迹中心）
```
glyphs = [(60, 84), (60, 84)]
intended center = (240, 128)
logo ink center = (239.5, 127.0)   →  offset dx −0.5px, dy −1.0px（原先 −36.5 / −6.5）
```
另渲染 PNG 目视确认：AC 居中、两字同基线、间距均匀。

## 备注
- 坑：`_render_ac_glyphs` 里曾把循环变量写成 `ch`，遮蔽了 `cell_w, cell_h = _GLYPH_CELL` 的高度
  → `QPixmap(320, "A")`，被 `try/except` 静默吞掉退化回矢量字母。**离屏渲染失败一定要打日志或断言**。
- `QRect` 在 `QtCore`，不在 `QtGui`。
- 排查入口：`versions_root()`（`launch.py:300`）是「mll 该去哪读版本 json」的唯一出口，
  任何「版本不存在」类报错先看它算出来的 root + `versions/<id>/<id>.json` 是否真存在。