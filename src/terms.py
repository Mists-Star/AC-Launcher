"""用户条款 / 隐私协议 / 免责声明的唯一正文来源（round-162）。

版本化规则：
  * 改动正文 → ``TERMS_VERSION`` 加 1，并把 ``TERMS_UPDATED`` 改成当天；
  * 启动时 ``terms_accepted_version < TERMS_VERSION`` 即视为未同意 → 弹门禁；
  * 同意后把当前版本写入 ``launcher_config.json``，改版才再次征询。

法律正文以中文版为准；界面框架文案（标题/按钮）走 i18n。
"""

TERMS_VERSION = 2
TERMS_UPDATED = "2026-11-08"

PRIVACY_TEXT = (
    "AC Launcher 隐私协议\n\n"
    "1. AC Launcher 是一款本地运行的 Minecraft Java 版启动器，\n"
    "   所有游戏实例、配置与账户数据都存储在你的设备上。\n"
    "2. 我们不收集、上传或共享任何个人信息，不含第三方统计 / 广告 SDK，\n"
    "   也没有遥测埋点；账户令牌在本机加密后保存。\n"
    "3. 联网行为分两类：\n"
    "   ① 你主动触发：版本与模组下载、资源搜索、登录、皮肤管理、联机；\n"
    "   ② 自动触发：检查启动器更新、检查 authlib-injector 新版本、\n"
    "      开机拉取皮肤头像、翻译搜索词与模组简介。\n"
    "4. 因此除 Mojang / 微软、Modrinth / CurseForge 等游戏与资源服务外，\n"
    "   启动器还会联系第三方翻译服务、GitHub 更新接口与皮肤 CDN。\n"
    "   发给翻译服务的只有你输入的搜索词或简介片段，不含账户凭据；\n"
    "   具体域名与触发点以开源源码为准。\n"
    "5. 本启动器开源透明，你可以随时审查源码。\n\n"
    f"最后更新：{TERMS_UPDATED}"
)

TOS_TEXT = (
    "AC Launcher 用户守则\n\n"
    "1. 本启动器仅供合法使用 Minecraft 的用户。\n"
    "2. 你需要自行拥有 Minecraft 正版授权。\n"
    "3. 禁止利用本启动器进行任何违法活动。\n"
    "4. Mod / 资源包 / 光影的版权归属其原作者。\n"
    "5. 使用联机大厅功能时请遵守社区规范。\n\n"
    f"最后更新：{TERMS_UPDATED}"
)

DISCLAIMER_TEXT = (
    "AC Launcher 免责声明\n\n"
    "1. AC Launcher 由雾星（Mists Star）开发维护。\n"
    "2. 本软件按「现状」提供，不作任何明示或暗示的保证。\n"
    "3. 开发者不对因使用本软件造成的任何直接或间接损失负责。\n"
    "4. Minecraft 是 Mojang Studios 的商标，本启动器与其无关。\n"
    "5. 第三方 Mod / 资源 / 皮肤由其原作者负责，与本启动器无关。\n\n"
    f"最后更新：{TERMS_UPDATED}"
)

_TEXTS = {
    "privacy": PRIVACY_TEXT,
    "tos": TOS_TEXT,
    "disclaimer": DISCLAIMER_TEXT,
}


def legal_text(key: str) -> str:
    return _TEXTS.get(key, "")


def combined_text() -> str:
    sep = "\n\n" + ("─" * 40) + "\n\n"
    return sep.join((PRIVACY_TEXT, TOS_TEXT, DISCLAIMER_TEXT))


def accepted_version(cfg: dict) -> int:
    try:
        return int(cfg.get("terms_accepted_version", 0) or 0)
    except (TypeError, ValueError):
        return 0


def needs_acceptance(cfg: dict) -> bool:
    """True on first run or after the terms text was bumped."""
    return accepted_version(cfg) < TERMS_VERSION
