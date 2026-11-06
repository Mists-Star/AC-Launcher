# 加载器图标来源（round-180）

用户 2026-11-06 明确要求：**不生成 / 不手绘 SVG，全部复用对应项目官方发布的
原始资源**。本目录 `loader_*` 文件均为上游官方原文件（或官方原图的无损格式
转换），未做任何重绘。各 logo 归其各自项目所有，此处仅用于标识对应软件，
AC Launcher 与这些项目无从属 / 背书关系。

## 官方资源清单（2026-11-06 实测可直连）

| 文件 | 加载器 | 官方来源 | 许可 / 说明 |
|---|---|---|---|
| `loader_fabric.png` | Fabric | `https://fabricmc.net/assets/logo.png` | FabricMC 官方站 logo；仓库 `FabricMC/fabric` 亦以 Apache-2.0 发布同图 |
| `loader_forge.png` | Forge | `https://files.minecraftforge.net/static/images/apple-touch-icon.png` | Forge 官网 apple-touch-icon，Forge Development LLC |
| `loader_quilt.svg` | Quilt | `https://quiltmc.org/assets/img/logo.svg` | QuiltMC 官方站；`QuiltMC/art` 的 logo 标注 CC0 1.0 |
| `loader_neoforge.svg` | NeoForge | `neoforged/Documentation` 仓库 `static/img/logo.svg` | 代码 MIT；品牌图 CC BY 4.0，作者 @Ridanisaurus / NeoForged team |
| `loader_optifine.ico` | OptiFine | `https://optifine.net/favicon.ico` | OptiFine 官网 favicon，**官方只提供 16×16**，放大略糊但不重绘 |
| `loader_labymod.ico` | LabyMod | `https://www.labymod.net/favicon.ico` | LabyMod 官网 favicon，含 16~128 多尺寸 |
| `loader_legacyfabric.ico` | Legacy Fabric | `https://legacyfabric.net/favicon.ico` | Legacy Fabric 官网 favicon（32×32） |
| `loader_liteloader.ico` | LiteLoader | `https://www.liteloader.com/favicon.ico` | LiteLoader 官网 favicon（16/32） |
| `loader_vanilla.png` | 原版 | 本仓 `assets/mc_textures/block/grass_block_{side,top}.png` | **Minecraft 官方方块贴图**（随包资源），仅做 64×64 缩放拼接，未绘制新图形。Mojang/Microsoft 商标不用作 logo |

官方未发布可复用 logo 的：**Cleanroom**（`CleanroomMC/Cleanroom` 仓库与
`cleanroommc.com` 均无品牌图）→ 不硬造，UI 走文字占位。

### GitHub 资源获取方式

本机直连 `github.com` / `raw.githubusercontent.com` 不通，改用多条通路：
1. 内网 DevHub `gh_proxy_health` / `gh_proxy_fastest` 选节点；
2. `https://gh-proxy.org/`、`https://github.cnxiaobai.com/`、`https://gh.monlor.com/`
   代理 `raw.githubusercontent.com`（三者对 NeoForge logo 均 200 / 12434 B）；
3. 用联网抓取工具直接读 GitHub 仓库页 / API 确认**真实文件路径**
   （`static/img/logo.svg` 不在仓库根目录，猜路径会得到 404）。

## 主流启动器怎么做（2026-11-06 仓库实证）

| 启动器 | 图标方案 | 具体形态 |
|---|---|---|
| **Prism Launcher** | FreeDesktop 图标主题 | `launcher/resources/multimc/` 下 `index.theme` + `8x8 / 16x16 / 22x22 / 24x24 / 32x32 / 48x48 / 50x50 / 64x64 / 128x128 / 256x256 / scalable` 多尺寸目录 + `multimc.qrc`，按图标名从主题取，天然适配任意 DPI |
| **HMCL** | 固定分辨率位图 + `@2x` | `HMCL/src/main/resources/assets/img/` 下 `fabric.png`/`fabric@2x.png`、`forge.png`、`neoforge.png`、`quilt.png`、`optifine.png`、`cleanroom.png`、`legacyfabric.png`、`grass.png`，共 48 个 PNG；**没有 liteloader** |
| **PCL2** | WPF 内置 PNG 资源 | 图片随程序集打包，按加载器名引用 |

⚠ 这三家的图标是**各自维护的一套图标集**，并非逐个嵌入上游官方原图。
本仓按用户要求走的是「上游官方原文件」路线，因此格式不统一（SVG / PNG /
ICO 混用），由 `src/icons.py` 的 `_ICON_EXTS` 与 Qt 的 `qico` / `qsvg` 插件统一
承载；代价是尺寸不整齐（OptiFine 只有 16×16），收益是零自绘、来源可追溯。
若以后要改成 HMCL 那种统一 PNG@2x，需要先取得用户对「偏离官方原图」的确认。

## 与资源中心 / 版本卡片的关系

版本列表的等距方块图标（`async_image.make_version_pixmap`）本来就用
`assets/mc_textures/block/` 下的**官方 MC 贴图**渲染，与 HMCL / PCL2 同思路，
不属于「自绘 SVG」，本次未改动。
