# round-108 记忆：CurseForge 对外发布合规准备

> 日期：2026-10-17。公共发布前的「第三方服务」接线批次。承接 round-105/106 的功能扩展方案。

## 背景

启动器准备公开发布。查证 CurseForge 官方口径后确认两条硬约束，本轮据此改变代码默认行为：

1. **CF 官方 API 不捆绑 key**：3rd Party API 需申请（表单 + 同意 ToS + Overwolf 审核），且 ToS 第 4 条要求申请人 **≥18 岁**且信息真实。作者未满 18 → **不能自己申请**，也不能捆绑 key。
2. **免 key 通道必须默认关**：`cfwidget + edge.forgecdn.net` 直链绕过作者在 CF 上的第三方分发授权，公开分发时与申请时的声明冲突。

结论：**公开发布版只挂 Modrinth（无年龄门槛/无需 key）**；CF 源改为「谁用谁填 key」；官方 key 待作者成年后再申请。

## 本轮改动（4 文件）

| 文件 | 改动 |
|---|---|
| `src/settings_dialog.py` | `_DEFAULTS` 加 `curseforge_api_key=""` / `curseforge_keyless=False`；`_SENSITIVE_CFG_KEYS` 加 `curseforge_api_key`（导出/导入备份永不携带）；`_page_network` 末尾新增「第三方服务」分组（key 输入框 + 免 key 通道勾选 + 两段 hint）；`_sync_ui_to_cfg` 回写这两个键 |
| `src/net_api.py` | 新增 `curseforge_keyless_enabled()`（读 `curseforge_keyless`，默认 False） |
| `src/pages_browse.py` | `_load_curseforge` / `_on_source_changed` 改成**三态**：有 key → 官方关键词搜索；无 key + 开关开 → slug/链接解析；都没有 → 提示去设置填 key（清列表 + 状态栏提示，不起 worker） |
| `src/i18n.py` | 新增 7 键 × zh/en：`settings.cf_group/cf_key_ph/cf_key_hint/cf_keyless/cf_keyless_hint` + `store.cf_hint_key/cf_no_key` |

### 顺带修掉一个潜在崩溃

`pages_browse._download` 在 CF 源下**无条件**调 `download_cfwidget_file(cf_file, ...)`，但官方 API 搜索命中的 hit **没有 `_cf_file`**（`search_curseforge` 只返回 `project_id`）→ `cf_file=None` 会在 worker 里炸。现改为：有 `_cf_file` 走 forgecdn 直链，否则走 `download_curseforge_mod(project_id, dest)`。**即：此前「配了 key 能搜到但一下载就崩」。**

## 验证

- `python -m compileall -q src main.py` → exit 0
- i18n parity：zh 1254 / en 1254，**零单边键**
- 离屏冒烟（venv，21 条断言，**全绿，FAILS: 0**）：默认值/敏感键、`curseforge_available`/`curseforge_keyless_enabled` 三态、设置页控件存在且勾选态正确、`_sync_ui_to_cfg` 回写、导出剔除 key / 导入拒绝还原 key、StorePage 三种状态各自走对的通道（无 worker / link_search / search_curseforge）
- 冒烟脚本通过 monkeypatch `settings_dialog.load_config` 走内存 cfg，**全程不碰真实 `launcher_config.json`**；脚本已删除（临时产物不入库）

## 待办 / 未做

- **真机目检一次**：设置 → 网络 → 「第三方服务」分组的排版（离屏无字体，文字为 tofu，只能验结构与配色）
- CF 3rd Party API 申请：**等作者成年**（或由 18+ 家长作为合同主体代签，需家长知情同意）
- 若要面向公众提供 CF 源，仍需在公开版**不内置 key**的前提下让用户自行填写（现已实现）
- `MS_CLIENT_ID` 保留决定维持不变（公共客户端 client_id 非密钥；微软登录走 device code flow，"未验证"是未经 Mojang 审核时的正常态）
