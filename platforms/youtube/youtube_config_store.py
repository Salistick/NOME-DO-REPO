import json
from pathlib import Path


class YouTubeConfigStore:
    def __init__(self, filepath: Path):
        self.filepath = Path(filepath)

    def _default_data(self) -> dict:
        return {
            "accounts": [],
        }

    def load(self) -> dict:
        if not self.filepath.exists():
            return self._default_data()

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return self._default_data()

        if not isinstance(data, dict):
            return self._default_data()

        accounts = data.get("accounts", [])
        if not isinstance(accounts, list):
            accounts = []

        return {
            "accounts": accounts,
        }

    def save(self, data: dict) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "accounts": data.get("accounts", []),
        }

        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def clear(self) -> None:
        try:
            if self.filepath.exists():
                self.filepath.unlink()
        except Exception:
            pass

    # ==================================
    # Helpers base
    # ==================================

    def list_accounts(self) -> list[dict]:
        return self.load()["accounts"]

    def list_all_channels(self) -> list[dict]:
        channels = []

        for idx, account in enumerate(self.load()["accounts"]):
            for channel in account.get("channels", []):
                channels.append(
                    {
                        "list_index": idx,
                        "display_index": idx + 1,
                        "account_id": account.get("account_id", ""),
                        "account_email": account.get("email", ""),
                        "account_name": account.get("name", ""),
                        "channel_id": channel.get("channel_id", ""),
                        "title": channel.get("title", ""),
                        "handle": channel.get("handle", ""),
                    }
                )

        return channels

    def get_account_by_index(self, index: int) -> dict | None:
        accounts = self.load()["accounts"]

        if index < 0 or index >= len(accounts):
            return None

        return accounts[index]

    def get_channel_by_index(self, index: int) -> dict | None:
        account = self.get_account_by_index(index)
        if not account:
            return None

        channels = account.get("channels", [])
        if not channels:
            return None

        return channels[0]

    def get_default_account(self) -> dict | None:
        return self.get_account_by_index(0)

    def get_default_channel(self) -> dict | None:
        return self.get_channel_by_index(0)

    # ==================================
    # Upsert / remove
    # ==================================

    def upsert_account(
        self,
        account_id: str,
        email: str,
        name: str,
        channels: list[dict],
    ) -> None:
        account_id = (account_id or "").strip()
        email = (email or "").strip()
        name = (name or "").strip()

        if not account_id:
            raise ValueError("account_id é obrigatório.")

        normalized_channels = []
        for channel in channels or []:
            channel_id = (channel.get("channel_id") or "").strip()
            if not channel_id:
                continue

            normalized_channels.append(
                {
                    "channel_id": channel_id,
                    "title": (channel.get("title") or "").strip(),
                    "handle": (channel.get("handle") or "").strip(),
                }
            )

        data = self.load()
        accounts = data["accounts"]

        found = False

        for account in accounts:
            if account.get("account_id") == account_id:
                account["email"] = email
                account["name"] = name
                account["channels"] = normalized_channels
                found = True
                break

        if not found:
            accounts.append(
                {
                    "account_id": account_id,
                    "email": email,
                    "name": name,
                    "channels": normalized_channels,
                }
            )

        self.save(data)

    def remove_account_by_index(self, index: int) -> bool:
        data = self.load()
        accounts = data["accounts"]

        if index < 0 or index >= len(accounts):
            return False

        accounts.pop(index)
        self.save(data)
        return True

    def remove_account_by_display_index(self, display_index: int) -> bool:
        if display_index <= 0:
            return False

        return self.remove_account_by_index(display_index - 1)

    # ==================================
    # Compat helpers para comandos
    # ==================================

    def count_accounts(self) -> int:
        return len(self.load()["accounts"])

    def build_accounts_summary_lines(self) -> list[str]:
        lines = []

        for idx, account in enumerate(self.load()["accounts"]):
            channels = account.get("channels", [])
            channel = channels[0] if channels else {}

            title = channel.get("title", "Canal sem nome")
            handle = channel.get("handle", "")

            suffix = ""
            if handle:
                suffix += f" ({handle})"

            lines.append(f"{idx + 1}: {title}{suffix}")

        return lines