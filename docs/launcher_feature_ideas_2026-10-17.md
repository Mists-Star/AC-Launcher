# AC Launcher 功能缺口与候选新功能（2026-10-17）

> 目的：在「实例隔离 + 下载器 + 崩溃分析」已成行业标配的背景下，找出真正的差异化空位，给 AC 的下一轮迭代提供候选方向。
> 方法：网络调研国内外主流启动器（PCL2 / HMCL / XMCL / BakaXL / Prism / MultiMC / Modrinth App / CurseForge / GDLauncher / ATLauncher / FTB App）近 1–2 年（2024–2026）的版本迭代与用户反馈，再对照 AC 现有能力做缺口分析。
> 说明：结论来自公开资料与社区讨论，部分条目需进一步核实；本文件只做方向研判，不含实现。

---

## 0. 一句话结论

**「实例隔离 + 下载 + 崩溃分析」已是标配，堆这些不再有差异化。**
真正的空位集中在三件事：**换机器要重来（无云同步）**、**分享整合包要导出文件（无短码/点对点）**、**联机/开服门槛高且出错难查（无可解释诊断）**。用户的抱怨也高度集中在这三处。

AC 的天然优势恰好压在这三件事上：**便携式 `data/` 目录**、**已内建的 EasyTier 联机大厅**、**已有的崩溃分析管线**。所以下一轮最优解不是「补标配」，而是**把这三块从「能用」推到「闭环」**。

---

## 1. 主流启动器近两年都加了什么

| 启动器 | 近 1–2 年新增亮点 |
|---|---|
| **PCL2 / 社区版 PCL2-CE** | 分享 Mod 给他人、多账号快速切换、启动器内下载资源包/光影、资源收藏夹、Win ARM64 支持、投影原理图(schematic)与子文件夹管理 |
| **HMCL 3.7.x** | 集成 **Terracotta 陶瓦 P2P 联机**（「多人联机」入口）、导出 Modrinth 整合包、世界列表显示图标、迁 Java 11 |
| **XMCL** | 0.51+ 全新 UI、**每实例独立主题**、自定义分辨率、整合包导出区分 server/client、OptiFine/LabyMod 按 mod 安装 |
| **Prism Launcher 9.x** | **自动 Java 管理 + 组件版本自动解析**、导出 `.mrpack`、性能与主题打磨 |
| **Modrinth App** | 皮肤页(beta)、**Friends 系统雏形**、Quick Instances、实例显示游玩时长、Home 世界直达；平台侧转向 Modrinth Hosting |
| **CurseForge** | 数据包支持、**Quick Play（一键回上次世界/服务器）**、**整合包克隆到不同 MC 版本并自动搬兼容 mod** |
| **GDLauncher (Carbon)** | 新 Java Manager、**一键「云实例分享」（短码、CF+MR 混装）**、内置服务器管理、Potato PC Mode |
| **FTB App** | **Cloud instances**、实例系统重写、可覆盖 ModLoader、自定义图标/分类 |
| **BakaXL** | Octo 联机测试、周更节奏 |
| **MultiMC** | 已停更归档，社区转向 Prism |

**规律**：新增功能几乎不约而同地指向「**降低搬运成本**（云/分享/克隆）」「**降低出错成本**（自动 Java、自动解析）」「**降低联机门槛**（P2P 联机、开服）」——而不是再加下载源。

---

## 2. 品类的系统性局限

1. **跨平台割裂**：国内主力（PCL2/WPF、BakaXL）基本 Windows-only；跨平台强者仍只有 Prism/MultiMC 系。Electron 栈体积大。
2. **实例「隔离」成熟、「传递」落后**：跨机器/跨人共享仍靠导出 zip/mrpack；Cloud 分享仅 GDLauncher / FTB / Modrinth 少数具备。
3. **联机与服务器**：Java 版无内置联机，官方 Realms 付费 → 催生 EasyTier/Terracotta/各类「联机大厅」；同时「一键开服」生态分散、门槛高。
4. **云同步/多设备**：国内几乎空白，国外也才起步（Modrinth / FTB Cloud）。
5. **分发依赖单一平台**：CF 授权争议后 Modrinth 崛起 → 启动器必须同时对接 CF + MR。
6. **自动更新/依赖解析**：仅 Prism 做到了组件自动解析，多数仍是手动选版本。
7. **账号体系**：正版 MSA 已普及，但离线/多账号切换体验参差。
8. **诊断能力弱**：出错后只能看日志；模组冲突、前置缺失、资源包/光影顺序问题基本靠人肉排查。

---

## 3. AC 现状基线 → 缺口对照

**AC 已有**：实例管理与隔离、加载器安装（原版/Fabric/Forge/Quilt/NeoForge/LiteLoader/Legacy Fabric/Cleanroom/OptiFine）、资源中心（Modrinth）、模块化内容系统、JS 扩展宿主（WebEngine 沙箱）、**联机大厅（EasyTier）**、成就系统、Java 扫描与下载、BMCLAPI 镜像与代理、**崩溃分析与自动修复**、跨启动器实例导入与修复、便携 exe + `data/`。

| 能力维度 | AC 现状 | 缺口 |
|---|---|---|
| 实例隔离 | ✅ 完整 | — |
| 下载/安装 | ✅ 覆盖广 | 缺 CurseForge 源 |
| 联机 | 🟡 有 EasyTier 大厅 | 缺「一键建房 + 邀请码」与「一键开服」闭环 |
| 分享/传递 | ❌ 无 | 无短码分享、无云同步 |
| 诊断 | 🟡 崩溃后分析 | 缺**启动前**静态依赖/冲突检查 |
| Java | 🟡 扫描+下载 | 缺「MC 版本—实例」自动绑定与提示 |
| 主题 | 🟡 全局主题 + 模块 | 缺**每实例独立主题/资源包/光影** |
| 世界/存档 | ❌ 弱 | 缺存档级备份、Quick Play、世界图标 |
| 整合包 | 🟡 可安装 mrpack | 缺「克隆升级到新 MC 版本」 |

结论：AC 在**联机**和**诊断**两处是「有底子但没闭环」，在**分享/同步**处是完全空白——正好对应第 0 节的三条空位。

---

## 4. 用户真实痛点（高价值信号）

- **Java 版本错配**：不同 MC 版本对应 Java 8/16/17/21，频繁踩坑（Prism 9.0、GDLauncher 都在用「自动 Java」回应它）。
- **安装/启动失败**：杀软拦截、access violation、卡在启动——「不知道哪错了」是最贵的体验成本。
- **模组/资源包/光影加载顺序冲突**难排查。
- **官方启动器被高赞吐槽**：设置不保存、世界数据丢失、换账号繁琐、强制更新。
- **高频诉求**：联机门槛高、一键开服、多设备同步、整合包点对点分享。

---

## 5. 给 AC 的候选新功能（分级 + 落地路径）

### A 级 · 贴 AC 现有架构、差异化最强
1. **零配置联机闭环**：在现有 EasyTier 大厅上加「一键建房 + 邀请码」，建房即生成可分享的加入码；对手是 HMCL 陶瓦联机、BakaXL Octo。**复用已有基建，成本最低、差异最大。**
2. **依赖与冲突「可解释」诊断**：把现有崩溃分析**前移**为「启动前静态检查」——重复模组、前置缺失、版本不匹配、资源包/光影顺序，输出中文结论 + 一键修复。整个品类都弱，AC 有管线底子，容易做出「别人没有的解释力」。
3. **整合包一键开服**：服务端/客户端同版本、自动同步 mod，把「联机」和「开服」串成闭环。参考开源开服包生态，但由 AC 一体化完成。

### B 级 · 高价值但成本更高
4. **实例一键云同步**：复用便携 `data/`，先支持 WebDAV / 自建 / Gist 后端（参考 FTB Cloud、GDLauncher）。**注意隐私与凭据安全**。
5. **短码实例分享**：生成分享码自动拉取 CF + MR 混合依赖（参考 GDLauncher Cloud Instance Sharing）。差异化很强。
6. **自动 Java 匹配与绑定**：按 MC 版本绑定 8/17/21 并随实例记忆（参考 Prism 9.0 / GDLauncher），补齐现有扫描/下载之后的「最后一公里」。
7. **整合包克隆升级**：克隆到新 MC 版本并自动搬运兼容 mod（参考 CurseForge 1.295）。高价值、较高成本。

### C 级 · 体验补强，随迭代顺手做
8. **每实例独立主题/资源包/光影**：参考 XMCL 每实例主题、PCL-CE 启动器内下载。
9. **存档级云备份 + 回家页**：Quick Play 一键回上次世界、世界图标、自动备份（参考 Modrinth Home / CurseForge Quick Play / HMCL 世界图标）。
10. **整合包分发页 + 一键导入**：CF + MR + 自定义链接一体搜索（参考 ATLauncher / PCL），补上单一 Modrinth 源的短板。

---

## 6. 建议取舍：先做哪三个

如果只做三个，建议 **A2 → A1 → B6**：

1. **A2 可解释诊断**：改动集中在已有诊断/崩溃管线，风险低、口碑收益高，且直接回应「出错难查」这一最大抱怨。
2. **A1 联机闭环**：复用 EasyTier 大厅，把「有功能」变「好用」，是最省力的差异化。
3. **B6 自动 Java 绑定**：行业都在补，且 AC 已有扫描/下载，只差绑定逻辑。

云端分享（A4/A5）价值最高但涉及后端、账号与隐私，建议**单独立项**评估，不要混进体验迭代。

---

## 附：主要来源

- PCL2 社区版 https://pcl-community.github.io/PCL2-CE-Web/ ；PCL2 v2.11.9 更新 https://soft.ali213.net/down/30863.html
- HMCL 3.7.1 https://www.bilibili.com/opus/1124733750249259010 ；HMCL 3.6.14 https://www.bilibili.com/opus/1088221679199453185
- XMCL Changelog https://xmcl.app/zh/changelogs/0.51.x
- Prism 9.0 https://prismlauncher.org/news/release-9.0/ ；Prism 9.3 https://prismlauncher.org/news/release-9.3/
- 启动器横向对比 https://mick235711.github.io/2024/11/26/minecraft-launcher-comparison/
- Modrinth Changelog https://modrinth.org/news/changelog ；Modrinth Skins https://modrinth.com/news/article/skins-now-in-modrinth-app
- CurseForge 1.295 发行说明 https://blog.curseforge.com/app-release-notes-1-295/
- GDLauncher Carbon https://gdlauncher.com/docs/gdlauncher-vs-gdlauncher-carbon/ ；云实例分享 https://gdlauncher.com/ja/vs/tlauncher/
- ATLauncher https://atlauncher.com/downloads/ ；FTB App 变更 https://www.feed-the-beast.com/ftb-app/changes
- Java 版本对照 https://minecraftmodwiki.com/en/guides/modpack-installation-troubleshooting/
- CurseForge 支持 https://support.curseforge.com/en/support/solutions/articles/9000196081-curseforge-minecraft-troubleshooting
- Mojira MCL-20342 https://bugs.mojang.com/browse/MCL/issues/MCL-20342 ；官方启动器反馈 https://feedback.minecraft.net/hc/en-us/community/posts/4413503544717-Remove-or-Improve-The-New-Minecraft-Launcher
- 加载顺序冲突案例 https://www.toxigon.com/actions-and-stuff-java-port ；一键开服案例 https://blog.csdn.net/2301_76197567/article/details/147710117
