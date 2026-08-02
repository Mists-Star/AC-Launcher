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

_TYPE_LABEL = {"microsoft": "微软", "offline": "离线", "yggdrasil": "外置登录"}


def type_label(t: str) -> str:
    return _TYPE_LABEL.get(t, t)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class AccountsManager:
    def __init__(self):
        self._path = os.path.join(get_data_dir(), "accounts.json")
        self._accounts: dict[str, dict] = {}
        self._current: str | None = None
        self._load()

    # ---- persistence ----
    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        for raw in data.get("accounts", []):
            self._accounts[raw["id"]] = raw
        self._current = data.get("current")

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(
                {"current": self._current, "accounts": list(self._accounts.values())},
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


_manager = AccountsManager()


def manager() -> AccountsManager:
    return _manager
