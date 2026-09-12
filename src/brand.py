"""Application brand: single source of truth for name / identity / definition.

Everything user-facing that names the launcher reads from here, so renaming
later is a one-file edit.

Name: AC Launcher / Absolute Controller
  - English full name : Absolute Controller
  - Short brand / abbreviation : AC   (like "AC" -> "AC Launcher")
  - Chinese full name : 绝对控制器
  - Window title / about : AC Launcher

定位：跨启动器的 Minecraft Java 版统一控制器。聚合、管理并修复本机所有
其它启动器的实例——一切尽在本地、私密、由你掌控。
"""

# Core identity
APP_NAME = "AC"                 # short ASCII brand (logs, Minecraft launcherName)
APP_NAME_EN = "Absolute Controller"
APP_NAME_ZH = "绝对控制器"
APP_DISPLAY = "AC Launcher"     # window title / about / titlebar logo text
APP_ABBR = "AC"

APP_TAGLINE = "掌控每一次启动"

# Microsoft identity platform — this launcher's own Azure AD app (public client).
# Registered by Mists-Star. The launcher uses the Authorization Code flow with a
# local loopback redirect (http://127.0.0.1:7890/), so the Azure app MUST list
# that exact URI under "公共客户端/本机" redirect URIs. Overridable at runtime via
# Settings -> 登录 -> 微软应用 ID (leave blank to fall back to the built-in default).
# NOTE: Xbox Live scope (XboxLive.signin) for this app requires Mojang review
# (https://aka.ms/mce-reviewappid) before real Minecraft login works end-to-end.
MS_CLIENT_ID = "ba522940-6118-4c81-82f1-7e5dd304d5e0"
APP_DESCRIPTION = (
    "现代、轻量的跨启动器 Minecraft Java 版启动器。"
    "统一管理本机与各主流启动器的实例，支持微软 / 离线 / 外置登录，"
    "并能自动检测、导入与修复其它启动器的实例，让你的每一次启动都尽在掌握。"
)

# Versioning
APP_VERSION = "1.0.0-beta"
APP_AUTHOR = "雾星 / Mists Star"

# Brand accent (mirrors theme.py accent so the logo + UI stay in sync)
BRAND_ACCENT = "#7C3AED"
