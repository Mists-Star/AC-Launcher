"""Account store: persist multiple login identities (Microsoft / offline /
third-party Yggdrasil) and remember the currently-selected one.

Accounts are kept in data/accounts.json beside the exe (portable). Each account
is a dict produced by core.auth: {id, name, access_token, type, ...}. Offline
accounts need no token; third-party accounts carry a ``server`` field used by
the launcher to inject the authlib-injector javaagent.
"""
from __future__ import annotations

import json
import os
import uuid

from .paths import get_data_dir
from .win_dpapi import dpapi_encrypt, dpapi_decrypt

_TYPE_KEYS = {"microsoft": "account.type_microsoft",
              "offline": "account.type_offline",
              "yggdrasil": "account.type_yggdrasil"}


def type_label(t: str) -> str:
    """round-44：账户类型显示走 i18n（之前硬编码中文，英文界面仍中文）。"""
    from .i18n import t as _t
    return _t(_TYPE_KEYS.get(t, "account.type_" + t), default=t)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class AccountsManager:
    def __init__(self):
        self._path = os.path.join(get_data_dir(), "accounts.json")
        self._accounts: dict[str, dict] = {}
        self._current: str | None = None
        self._load()

    # ---- persistence ----
    # round-35 加固：token 加密字段（DPAPI）。_TOKEN_KEYS 是敏感字段集合：
    # 微软 access_token / refresh_token / ms_access_token（明文不落盘）。
    _TOKEN_KEYS = ("access_token", "refresh_token", "ms_access_token")

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        _migrated = False
        for raw in data.get("accounts", []):
            # round-34 加固：缺 id / 非 dict 的脏数据跳过，避免 KeyError 崩溃
            if isinstance(raw, dict) and raw.get("id"):
                # round-35：解密 token；旧明文数据（dpapi_decrypt 失败且值
                # 是普通 token 字符串）兼容读取，并顺手迁移为密文
                if self._decrypt_tokens(raw):
                    _migrated = True
                self._accounts[raw["id"]] = raw
        self._current = data.get("current")
        if _migrated:
            self._save()

    @staticmethod
    def _decrypt_tokens(acct: dict) -> bool:
        """Decrypt in-place the DPAPI-encrypted token fields of *acct*.

        返回 True 表示检测到旧明文数据（已标记迁移——_save 写盘时加密重写）。
        内存始终保留明文（launcher 各处直接读 access_token）；磁盘加密。
        """
        changed = False
        for key in AccountsManager._TOKEN_KEYS:
            val = acct.get(key)
            if not isinstance(val, str) or not val:
                continue
            if val.startswith("dpapi:"):
                plain = dpapi_decrypt(val[len("dpapi:"):])
                acct[key] = plain if plain is not None else ""
            else:
                # 旧明文：内存保留明文，只标记 changed → _save 加密写盘
                changed = True
        return changed

    def _save(self) -> None:
        # round-35：落盘前加密敏感 token 字段（内存保持明文，写盘加密）
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        snap = []
        for acct in self._accounts.values():
            copy = dict(acct)
            for key in self._TOKEN_KEYS:
                val = copy.get(key)
                if isinstance(val, str) and val and not val.startswith("dpapi:"):
                    enc = dpapi_encrypt(val)
                    if enc:
                        copy[key] = "dpapi:" + enc
            snap.append(copy)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(
                {"current": self._current, "accounts": snap},
                f, ensure_ascii=False, indent=2,
            )

    # ---- api ----
    def add(self, profile: dict) -> dict:
        """Store a profile (from core.auth) as a saved account. Returns it."""
        acct = dict(profile)
        acct.setdefault("id", _new_id())
        if not acct.get("type"):
            acct["type"] = "offline" if not acct.get("access_token") else "microsoft"
        self._accounts[acct["id"]] = acct
        if self._current is None:
            self._current = acct["id"]
        self._save()
        return acct

    def list(self) -> list[dict]:
        return list(self._accounts.values())

    def get(self, account_id: str) -> dict | None:
        return self._accounts.get(account_id)

    def current(self) -> dict | None:
        if self._current is None:
            return None
        return self._accounts.get(self._current)

    def set_current(self, account_id: str) -> None:
        if account_id in self._accounts:
            self._current = account_id
            self._save()

    def remove(self, account_id: str) -> None:
        self._accounts.pop(account_id, None)
        if self._current == account_id:
            self._current = next(iter(self._accounts), None)
        self._save()

    # ---- silent refresh (round-34, P1-5) ----
    def refresh_current_silently(self) -> bool:
        """Try to silently refresh the current Microsoft account.

        在 Worker 线程调用（网络请求 + 重走 XBL 链路耗时 ~1s）。成功时更新
        存储并返回 True；无需刷新（离线/外置/无 refresh_token）或失败返回
        False——调用方不提示用户，下一次完整登录自然兜底。
        """
        acct = self.current()
        if not acct or acct.get("type") != "microsoft":
            return False
        if not (acct.get("refresh_token") or "").strip():
            return False
        try:
            from .core.auth import refresh_microsoft
            refreshed = refresh_microsoft(acct)
            if not refreshed:
                return False
            refreshed["type"] = "microsoft"
            self._accounts[acct["id"]] = refreshed
            self._save()
            return True
        except Exception:  # noqa: BLE001 - 静默刷新失败绝不能崩
            return False


_manager = AccountsManager()


def manager() -> AccountsManager:
    return _manager
