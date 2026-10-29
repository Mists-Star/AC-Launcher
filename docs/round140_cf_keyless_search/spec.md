# round-140 — CurseForge 免 Key 关键词搜索（MCIM 镜像）spec

> 决策来源（2026-10-28，用户拍板）：
> 1. **调研先行**：委托 GitHub 调研 HMCL / PCL2(Meloong) / PCL2-CE / Prism
>    的 CF 搜索实现 —— 结论见 `<本地工作区>\调研记忆_CurseForge免key搜索_2026-10-28.md`；
> 2. **「搜索+下载全默认开」** —— MCIM 镜像搜索默认启用 + 无 Key 直链下载
>    默认放行（round-140 显式偏离 round-108 的「keyless 默认关」纪律）；
> 3. 用户没成年申请不了官方 key，且官方 key 通道之外「输入 the shooting
>    star 搜不到」是真实痛点。

## 1. 背景与调研结论

- 用户诉求：「CF 源不是说直接搜索也能搜到吗不需要 key？为什么我输入
  the shooting star 搜不出来？」
- 现状（round-108）：无 key 时 `curseforge_link_search` **只认 slug/链接
  精确解析**（cfwidget 无搜索端点）→ 关键词必然搜不到。
- 调研（agent 800a0e98，2026-10-28）：
  - **无人逆向 CF 网页端点**：HMCL / PCL2 / PCL2-CE / Prism 全部走官方
    `api.curseforge.com` + key（构建期注入 / env / 官方签发）；
  - 自探 `www.curseforge.com/api/v1/mods/search` 全套浏览器头仍
    **403「Just a moment...」**（Cloudflare JS 挑战）→ 逆向路线放弃；
  - **MCIM 公益镜像** `https://mod.mcimirror.top/curseforge/v1` 与官方 API
    同契约、**免 x-api-key**（实测 200，total=450），HMCL 与 PCL2-CE 在用。

## 2. 设计

### 2.1 三态（有 key / 无 key+通道开 / 都无）

| 状态 | 搜索 | 下载 |
| --- | --- | --- |
| 有 key | 官方 `api.curseforge.com` + x-api-key | 官方 download-url 端点 |
| **无 key + 免 key 通道开（默认）** | **MCIM 镜像（新）** | cfwidget → forgecdn 直链 |
| 无 key + 通道关 | 提示去设置填 key | 同左 |

### 2.2 代码改动

- `net_api.py`
  - 新增 `_CF_MIRROR = "https://mod.mcimirror.top/curseforge/v1"`；
  - `search_curseforge`：无 key 且通道开 → 同路径换域名、去 x-api-key，
    中文名库反查 / 分页 / 缓存语义与官方路径完全一致；通道关才 raise；
  - `curseforge_keyless_enabled`：默认 **True**（round-140 拍板）；
  - 新增 `download_cfwidget_slug(slug, dest, callback)`：
    slug → `curseforge_link_search`（cfwidget 最新文件）→ `download_cfwidget_file`；
  - 缓存键 `cf:{query}:{offset}:{limit}` 两路共用（命中形状相同）。
- `pages_browse.py`
  - `_load_curseforge` keyless 分支：关键词 → `search_curseforge`（镜像），
    输入含 `/` 的完整链接 → 仍走 `curseforge_link_search`；
  - `_download` 无 key 无 `cf_file` → `download_cfwidget_slug`（镜像命中
    只有 slug，没有官方下载端点）；
  - 状态栏三态：key→`cf_hint_key` / 通道开→`cf_hint_mirror`（新）/
    都无→`cf_no_key`；placeholder 通道开时恢复关键词提示。
- `settings_dialog.py`：`_DEFAULTS["curseforge_keyless"] = True`
  （+ checkbox 初始化 / 保存两处 fallback 同步）。
- `i18n.py`：新增 `store.cf_hint_mirror`（zh/en）；改写
  `settings.cf_keyless` / `settings.cf_keyless_hint`（zh/en）。

### 2.3 不改的地方

- `store_detail.py`：版本列表 / 下载本就按 `curseforge_available()` 分流，
  无 key 走 `_curseforge_versions_keyless` + `download_cfwidget_file`，已完备。
- 有 key 路径逐字不动。

## 3. 验证（2026-10-28 实测）

- `search_curseforge('jei')` 免 key → **20 命中**（走 MCIM）；
- `search_curseforge('the shooting star')` → **10 命中**
  （`shooting-stars` 等，原始痛点解决）；
- 中文 `search_curseforge('小地图')` → 名库反查 `xaeros-minimap` → 镜像返回
  Xaero's Minimap；
- `download_cfwidget_slug('sodium')` → forgecdn 直链落盘
  `sodium-fabric-0.9.3-beta.1+mc26.3.jar`（1,912,496 B）；
- `regress.py` **12/12**（i18n 中英对称 1403=1403、全页面构造冒烟 OK）。

## 4. 决策记录

- 偏离 round-108：keyless 默认由 False → **True**，用户原话拍板
  「搜索+下载全默认开」；关闭开关仍可回到「仅官方 key」保守模式。
- 旧配置 `launcher_config.json` 中持久化的 `curseforge_keyless: false`
  （round-108 时代默认值写入）已同步改为 `true`。
