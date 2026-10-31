"""用户条款 / 隐私协议 / 免责声明的唯一正文来源（round-162）。

版本化规则：
  * 改动正文 → ``TERMS_VERSION`` 加 1，并把 ``TERMS_UPDATED`` 改成当天；
  * 启动时 ``terms_accepted_version < TERMS_VERSION`` 即视为未同意 → 弹门禁；
  * 同意后把当前版本写入 ``launcher_config.json``，改版才再次征询。

法律正文以中文版为准；界面框架文案（标题/按钮）走 i18n。
"""

TERMS_VERSION = 1
TERMS_UPDATED = "2026-10-31"

PRIVACY_TEXT = (
    "AC Launcher 隐私协议\n\n"
    "1. AC Launcher 是一款本地运行的 Minecraft Java 版启动器，\n"
    "   所有数据存储在你的设备上。\n"
    "2. 我们不收集、上传或共享任何个人信息。\n"
    "3. 你的游戏实例、账户凭据、皮肤文件均保留在本地。\n"
    "4. 联网功能（版本下载、皮肤获取）仅在你主动操作时触发，\n"
    "   且仅与 Mojang 官方 API 或你指定的服务器通信。\n"
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
