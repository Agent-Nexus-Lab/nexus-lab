"""Account list management — CRUD for target WeChat public accounts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ACCOUNT_LIST_PATH = Path(__file__).parent / "account_list.json"


@dataclass
class AccountConfig:
    """A single target WeChat public account."""

    id: str
    name: str
    keyword: str
    enabled: bool = True
    notes: str = ""


def load_account_list(path: Path | None = None) -> list[AccountConfig]:
    """Load the account list from JSON, returning only enabled accounts."""
    path = path or ACCOUNT_LIST_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    accounts = data.get("accounts", [])
    return [
        AccountConfig(
            id=a["id"],
            name=a["name"],
            keyword=a.get("keyword", a["name"]),
            enabled=a.get("enabled", True),
            notes=a.get("notes", ""),
        )
        for a in accounts
        if a.get("enabled", True)
    ]


def load_all_accounts(path: Path | None = None) -> list[AccountConfig]:
    """Load ALL accounts (including disabled) from the list."""
    path = path or ACCOUNT_LIST_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        AccountConfig(
            id=a["id"],
            name=a["name"],
            keyword=a.get("keyword", a["name"]),
            enabled=a.get("enabled", True),
            notes=a.get("notes", ""),
        )
        for a in data.get("accounts", [])
    ]


def get_config(path: Path | None = None) -> dict:
    """Get the full configuration (max_articles, cooldown, ttl, etc)."""
    path = path or ACCOUNT_LIST_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def add_account(config: AccountConfig, path: Path | None = None) -> None:
    """Add or update an account in the list."""
    path = path or ACCOUNT_LIST_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    existing = {a["id"]: a for a in data["accounts"]}
    existing[config.id] = {
        "id": config.id,
        "name": config.name,
        "keyword": config.keyword,
        "enabled": config.enabled,
        "notes": config.notes,
    }
    data["accounts"] = list(existing.values())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_account(account_id: str, path: Path | None = None) -> bool:
    """Remove an account by ID. Returns True if found and removed."""
    path = path or ACCOUNT_LIST_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    original_len = len(data["accounts"])
    data["accounts"] = [a for a in data["accounts"] if a["id"] != account_id]
    if len(data["accounts"]) < original_len:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True
    return False
