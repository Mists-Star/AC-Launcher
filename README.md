# AC Launcher (Absolute Controller / 绝对控制器)

[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D4.svg)](https://github.com/Mists-Star/AC-Launcher)

**如绝对求解器，掌控每一次启动。**

AC Launcher 是一款免费的 **Minecraft: Java 版** 启动器，用 Python (PySide6) 从零构建，
面向中文与英文玩家的完整功能面：实例管理、三大主流加载器、联机大厅、崩溃自修复分析、
资源中心、双语界面与隐私优先的凭据加密。

> AC Launcher is a free **Minecraft: Java Edition** launcher for Windows, built
> from scratch in Python (PySide6). It ships a complete feature set for both
> Chinese and English players: instance management, major loaders, an online
> lobby, crash analysis with self-repair, a resource center, bilingual UI and
> encrypted local credentials.

---

## ✨ Features / 核心功能

### 🕹 实例与启动 Instance & Launch

- **多实例管理**：创建 / 导入 / 删除 / 设置当前实例；实例级独立版本、加载器、Java、内存与启动参数
- **跨启动器实例接管**：一键扫描并导入 **MultiMC / Prism / HMCL / PCL2 / 官方启动器** 实例（复制或接管），自动修复损坏实例、补全缺失文件
- **启动高级设置**：游戏附加参数（含 `--server` 直连）、JVM 参数预设（默认 / Aikar / 自定义）、版本隔离（共享 / 隔离 / 自定义目录）、**进程优先级**（标准 / 高 / 实时）、启动后与退出后命令
- **非 ASCII 路径预检** + Java 版本自动匹配（按游戏版本约束）

### 🔌 加载器 Loaders

- **原版 / Fabric / Forge / Quilt / NeoForge / LiteLoader** 安装与切换，新建实例向导一键装好
- 设置页可隐藏 Quilt 等加载器入口

### 🌐 联机大厅 Online Lobby

- 内置联机工具分发：无联机插件时引导选择 **Terracotta / EasyTier / MCTier**，零额外配置开黑

### 🩺 崩溃自修复 Crash Self-Repair

- **崩溃分析**：读取 `latest.log` / 崩溃报告，规则库（缺依赖 / 加载器不匹配 / Java 版本 / 内存不足 / 显卡驱动 / Mixin 冲突等）给出**起因 + 修复建议**，可一键跳转修复
- **内置自检（诊断）**：依赖 / 配置 / 账户 / 外置登录 / Java / 游戏文件 / 网络连通性等 10 项

### 📥 资源中心 Resource Center

- **Modrinth / CurseForge** 模组、资源包、光影、整合包、游戏的搜索与下载；细节页含全部版本列表 + 按 MC 版本过滤 + 中文说明翻译（24h 缓存）
- **镜像源**：官方 / BMCLAPI 自动降级切换；断点续传 + 退避重试
- **整合包导入**：Modrinth (`.mrpack`) / CurseForge / Prism / MultiMC / 普通文件夹

### 🎨 界面与体验 UI & UX

- **玻璃拟态**（Acrylic 半透明）深色 UI，MC 风格 3D 等距版本图标
- **主题包**：内置主题即时切换；双语界面（简体中文 / English）
- 启动 Splash 动画、动态壁纸（窗口不可见时自动暂停解码）、背景音乐

---

## 🔐 Privacy / 隐私

- **凭据加密落盘**：`access_token` / `refresh_token` 经 Windows **DPAPI** 加密后才写入本地，内存明文、磁盘密文（对标明文 `auth.json` 方案更安全）
- **日志打码**：控制台 / 崩溃分析展示层对 `accessToken`、用户名自动打码（首尾各留 5 位），分享截图不泄漏凭证；磁盘日志原样保留
- **仅存本地**：所有令牌、配置、实例数据只保存在用户本机
- **零遥测**：无遥测、无分析、无任何数据上传
- **零外部依赖**：不依赖 Overwolf 等第三方运行时；仅请求用户级委托权限，绝不请求应用级管理权限

---

## 🧱 Tech Stack / 技术栈

| Layer | Technology |
|-------|------------|
| UI | Python 3.12+, **PySide6 6.11**（Acrylic 毛玻璃 + QSS 主题包 + 双语文案） |
| Core | `src/core/` — accounts / java / install / auth / mirror / sound / easytier |
| Launch | `minecraft-launcher-lib` |
| Auth | 微软 OAuth2 device-code + **Authlib-Injector（外置登录 / Yggdrasil）** + 离线 |
| Net | requests（Range 断点续传 · 原子落盘 · 退避重试 · 镜像降级） |
| Security | Windows DPAPI（凭据加密）· 展示层日志打码 |
| i18n | zh-CN / en 双语，键值表 + 中英对称审计 |

---

## 🚀 Quick Start / 快速开始

```bash
pip install -r requirements.txt
python main.py
```

### 构建独立可执行文件

```bash
python build_main.py
```

### 自检（回归）

```bash
python -B _diag_all.py
```

---

## 🗺 Roadmap / 路线图

当前按 [RELEASE_1.0.0_CHECKLIST.md](./RELEASE_1.0.0_CHECKLIST.md) 推进：
正式发布前使用 `round-NN` 内部迭代号；清单全部完工后一次性打上 `v1.0.0`。
已落地方向：下载引擎加固（退避重试 / 毒 `.part` 清理 / 完整性校验 / 断点续传）、
日志打码、非 ASCII 路径警告、Quilt 支持、进程优先级、版本页缓存加速、崩溃分析。

---

## ⚖️ License / 许可证

Released under the [GNU General Public License v3.0](LICENSE).
This is an independent hobby project and is **not affiliated with Mojang or Microsoft**.

**AC Launcher 是独立开发者的个人项目，仅供启动与管理 Minecraft 实例使用。**

---

*AC Launcher is a personal project by an independent developer,
designed solely for launching and managing Minecraft instances.*