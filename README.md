# AC Launcher (Absolute Controller / 绝对控制器)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D4.svg)](https://github.com/Mists-Star/AC-Launcher)

**如绝对求解器，掌控每一次启动。**

AC Launcher is a free, open-source **Minecraft: Java Edition launcher** for Windows,
built with Python and PySide6. It helps players manage multiple game instances,
switch Java versions, and launch the game with their Microsoft account.

> AC Launcher 是一款免费的、开源的 Minecraft：Java 版启动器，使用 Python + PySide6 开发，
> 用于管理多个游戏实例、切换 Java 版本，并通过微软账号启动游戏。

---

## ✨ Features / 核心功能

- **Microsoft Account Login** — sign in with your Microsoft account via the
  OAuth2 device-code flow, with local token storage.
  （微软账号登录：通过 OAuth2 device-code 流程，令牌仅存本地。）
- **Multi-instance Management** — create, import and organize Minecraft instances.
  （多实例管理：创建、导入与整理游戏实例。）
- **Cross-Launcher Instance Detection** — automatically detect and import instances
  from other popular launchers (MultiMC, Prism, HMCL, PCL2, official launcher),
  and repair broken instances.
  （跨启动器实例识别：自动探测并导入其他主流启动器的实例，修复损坏实例。）
- **Java Version Manager** — download and manage multiple Adoptium Java versions,
  assign the right one per instance.
  （Java 版本管理：下载并管理多个 Adoptium Java 版本，按实例分配。）
- **Game Settings** — configure game window mode (fullscreen / borderless / windowed),
  resolution, RAM allocation and custom JVM arguments.
  （游戏设置：窗口模式、分辨率、内存分配、自定义 JVM 参数。）
- **Lightweight & Themeable UI** — clean QSS-based light theme, no bloat.
  （轻量可换肤界面：基于 QSS 的浅色主题。）

---

## 🔐 Privacy / 隐私

- All authentication tokens are stored **locally** on the user's device.
  （所有登录令牌仅保存在用户本机。）
- The application requests **delegated (user) permissions only**, never app-level
  admin permissions.
  （仅请求用户级委托权限，绝不请求应用级管理权限。）
- No telemetry, no analytics, no data uploaded to any server.
  （无遥测、无分析、不上传任何数据。）

---

## 🧱 Tech Stack / 技术栈

| Layer | Technology |
|-------|------------|
| UI    | Python 3.12+, PySide6 (QSS theme) |
| Core  | `src/core/` — accounts, java, install, auth |
| Launch | `minecraft-launcher-lib` |
| Auth  | Microsoft identity platform (OAuth2 device-code) |

---

## 📦 Build / 构建

```bash
pip install -r requirements.txt
python main.py
```

To build a standalone executable:

```bash
python build_main.py
```

---

## ⚖️ License / 许可证

Released under the [MIT License](LICENSE).
This is an independent hobby project and is **not affiliated with Mojang or Microsoft**.

---

## 📮 Contact / 联系

- Author: Mists Star (雾星)
- Issues & discussions: GitHub Issues

---

*AC Launcher is a personal project by an independent developer.
No commercial use. Designed solely for launching and managing Minecraft instances.*
