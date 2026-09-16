# AC Launcher 仓库协作约定

## 分工（2026-09-12 起）

| 角色 | 职责 |
| --- | --- |
| **TRAE** | 功能开发 / UI 实现 —— 写代码、改文件、跑测试 |
| **WorkBuddy（小爪）** | 仓库管理 —— 提交、推送、历史整理、`.gitignore` 卫生、冲突处理 |

## TRAE 纪律（务必遵守）

1. **不要执行任何 git 命令**（`add` / `commit` / `push` / `rebase` / `merge` / `checkout` 分支等）。
   提交与推送由 WorkBuddy 统一执行，避免历史分叉、半成品入库、以及 GFW 下的推送失败。
   需要看状态可以只读地跑 `git status` / `git diff`。

2. **每完成一批功能：更新 `CHANGELOG.md`**
   顶部追加条目，格式：`## round-NN（YYYY-MM-DD）— 一句话主题`
   round 号自增，写完附「### 🔍 验证」说明怎么验证的。

3. **调试/诊断脚本一律 `_` 开头命名**（`_diag_xxx.py`、`_probe_xxx.py` 等）——
   已进 `.gitignore`，不会误入库。`_shots/` 截图、`ac.lock` 运行锁同理。

4. **敏感与合规红线（永不入库）**
   - `launcher_config.json`、任何 token / 凭据 / 用户数据
   - `assets/mc_textures/`（MC 原版纹理，版权属 Mojang，本地资源不入库）
   - 第三方专有资源、未经授权的品牌素材

5. **文件归位**：源码 `src/`、资源 `assets/`、研究/调研文档 `docs/`、打包脚本根目录。

6. **版本号策略**：正式发布前 CHANGELOG 只用 `round-NN` 内部迭代号；
   `v1.0.0` 要等 `RELEASE_1.0.0_CHECKLIST.md` 全部完工并通过验收后才一次性打上。
   不要擅自 bump 版本号。

## 当前开发主线（2026-09-16 起）

**方向：加深，不加宽。** 不再新增功能模块，集中把「启动」这一件事做透。
施工图见 **`docs/LAUNCH_MODE_DESIGN.md`**，按 round 顺序实现：

| round | 主题 | 状态 |
|---|---|---|
| 84 | 实例级启动历史持久化（地基，必须最先做） | 待做 |
| 85 | LaunchMode 一等概念 + 自适应决策器 | 待做 |
| 86 | 启动方式 UI（照搬 round-82 启动格式自适应的交互） | 待做 |
| 87 | safe 安全模式 ⚠️ 高风险 | 待做 |
| 88 | 启动实例优化实测提速 | 待做 |

⚠️ round-87 safe 模式涉及**移走玩家 `mods/` 目录**，属 P0 风险
（`finally` 还原 + 启动器启动自愈扫描 + 明确 UI 提示），实现前先读设计文档「风险红线」一节。

## 提交规范（WorkBuddy 执行）

conventional commits 格式：

```
feat: ...     新功能
fix: ...      缺陷修复
refactor: ... 重构（无功能变化）
chore: ...    构建/工具/清理
docs: ...     文档
```

摘要用中文，正文按 P0/P1/P2 或模块分组列要点。
推送走 SSH remote：`git@github.com:Mists-Star/AC-Launcher.git`（https 在 GFW 下不通）。
