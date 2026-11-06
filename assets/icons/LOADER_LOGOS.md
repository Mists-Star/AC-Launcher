# 加载器图标来源与许可

> round-181（2026-11-07）：按主理人要求，加载器图标**统一复用主流启动器
> 已经整理好的现成资源**，不再逐个溯源上游官网原图、不自绘、不生成。

## 采用的资源

| 图标 | 来源 | 文件 |
|---|---|---|
| Fabric / Forge / NeoForge / Quilt / OptiFine / Cleanroom / LegacyFabric / 原版(草方块) | **HMCL** `HMCL/src/main/resources/assets/img/*@2x.png` | `loader_*.png` |
| LabyMod / LiteLoader | 各自官网 favicon（HMCL 未收录这两个） | `loader_labymod.ico` / `loader_liteloader.ico` |

HMCL 仓库：<https://github.com/HMCL-dev/HMCL>，GPL-3.0-or-later。
本图标集按 GPL-3.0 兼容条款复用，保留原项目署名。这些图标本身是各加载器
社区通用标识，HMCL 只是统一整理成 PNG/@2x 尺寸。

## 主流启动器做法（实证，2026-11-06 翻仓库确认）

| 启动器 | 方案 |
|---|---|
| HMCL | `assets/img/` 固定 PNG + `@2x`，约 48 个；含 `cleanroom.png`、`grass.png`，不含 liteloader |
| Prism Launcher | FreeDesktop 图标主题：`launcher/resources/multimc/` 下 `index.theme` + 8×8…256×256 共 11 个尺寸目录 + `scalable` + `multimc.qrc` |
| PCL2 | WPF 程序集内置 PNG，按名引用 |

三家都是**自维护一整套图标集**，而不是在客户端里逐个去上游拉原图。
本项目采用 HMCL 那套（格式统一、体积小、免网络），由 `src/icons.py` 的
`_ICON_EXTS` + Qt 的 `qico/qsvg` 插件承载 PNG/ICO/SVG。

## 与 round-180 的差异

round-180 曾按「全部复用官方原文件」逐个下载上游 SVG/PNG/ICO，格式混杂、
部分官网国内不可达、还为一个仓库路径反复试镜像。按主理人 round-181 的
纠正改为复用 HMCL 现成集，同时补上了官方未单发 logo 的 Cleanroom。
