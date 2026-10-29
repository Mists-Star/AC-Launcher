# round-140 tasks

- [x] A1. GitHub 调研：HMCL/PCL2/PCL2-CE/Prism 的 CF 搜索实现（agent）
      → 无人逆向网页端点；MCIM 镜像是唯一免 key 可行路
- [x] A2. 密钥泄露扫描（7 类模式全仓）→ 真实密钥 0 命中
      （唯一命中是 Prism 公开 key 的调研临时文件，已删整个 cf_research/）
- [x] B1. `net_api.py`：`_CF_MIRROR` 常量 + `search_curseforge` 无 key 走镜像
      + `curseforge_keyless_enabled` 默认 True + `download_cfwidget_slug`
- [x] B2. `pages_browse.py`：三态提示 / keyless 分支改镜像搜索（链接仍走解析）
      / 下载补 slug 直链分支 / placeholder 恢复关键词
- [x] B3. `settings_dialog.py`：`_DEFAULTS` 及两处 fallback → True
- [x] B4. `i18n.py`：新增 `store.cf_hint_mirror`（zh/en）；改写
      `settings.cf_keyless` / `cf_keyless_hint`（zh/en）
- [x] C1. 实测：jei 20 命中 / the shooting star 10 命中 / 中文名库反查 /
      sodium 直链下载 1.9MB 落盘
- [x] C2. `regress.py` 12/12（i18n 对称 1403=1403、全页面冒烟）
- [x] C3. 落档：spec + tasks + CHANGELOG + <本地工作区> 记忆；删 `_keyscan.py`
- [ ] 遗留：git 历史密钥审计（git 不在 PATH，等可用后 `git log -p` 扫）
