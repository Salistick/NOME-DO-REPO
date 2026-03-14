import threading
import time

import requests

from config import (
    TWITCH_BOT_ACCESS_TOKEN,
    TWITCH_BOT_CLIENT_ID,
    TWITCH_BOT_CLIENT_SECRET,
    TWITCH_BOT_LOGIN,
    TWITCH_BOT_REFRESH_TOKEN,
    TWITCH_TOKEN_URL,
    TWITCH_VALIDATE_URL,
)
from .twitch_irc import TwitchIRCClient


class TwitchChatSender:
    def __init__(self):
        self._lock = threading.Lock()
        self._client = None
        self._connected_channel = ""
        self._token_data = {
            "login": TWITCH_BOT_LOGIN,
            "access_token": TWITCH_BOT_ACCESS_TOKEN,
            "refresh_token": TWITCH_BOT_REFRESH_TOKEN,
            "client_id": TWITCH_BOT_CLIENT_ID,
            "client_secret": TWITCH_BOT_CLIENT_SECRET,
            "expires_at": 0,
        }

    def is_configured(self) -> bool:
        return bool(
            self._token_data.get("login")
            and self._token_data.get("access_token")
            and self._token_data.get("client_id")
            and self._token_data.get("client_secret")
        )

    def disconnect(self):
        with self._lock:
            self._disconnect_unlocked()

    def send_message(self, channel_name: str, text: str) -> bool:
        channel_name = (channel_name or "").strip().lower().lstrip("#")
        text = " ".join((text or "").split()).strip()

        if not channel_name or not text:
            return False

        if not self.is_configured():
            print("[TWITCH SENDER] Conta bot nao configurada no .env. Mensagem nao enviada.")
            return False

        with self._lock:
            try:
                self._ensure_connected_unlocked(channel_name)
                self._client.send_chat_message(text[:450])
                return True
            except Exception:
                # Se a primeira tentativa falhar, derruba a conexao do sender
                # e refaz uma vez para evitar falhas no primeiro PRIVMSG apos JOIN.
                self._disconnect_unlocked()
                self._ensure_connected_unlocked(channel_name)
                self._client.send_chat_message(text[:450])
                return True

    def _disconnect_unlocked(self):
        if not self._client:
            self._connected_channel = ""
            return

        try:
            self._client.stop()
        except Exception:
            pass

        self._client = None
        self._connected_channel = ""

    def _ensure_connected_unlocked(self, channel_name: str):
        if self._client and self._connected_channel == channel_name:
            return

        self._disconnect_unlocked()

        token_data = self._get_valid_token_unlocked()
        login = (token_data.get("login") or "").strip().lower()
        access_token = (token_data.get("access_token") or "").strip()

        if not login or not access_token:
            raise RuntimeError("Conta bot sem login/access_token valido para enviar no chat.")

        self._client = TwitchIRCClient(
            oauth_token=access_token,
            login_name=login,
            channel_name=channel_name,
        )
        self._client.connect()
        time.sleep(1.0)
        self._connected_channel = channel_name

    def _get_valid_token_unlocked(self) -> dict:
        now = int(time.time())
        access_token = (self._token_data.get("access_token") or "").strip()
        expires_at = int(self._token_data.get("expires_at", 0) or 0)

        if access_token and expires_at > now + 60:
            return self._token_data

        if access_token:
            validation = self._validate_token(access_token)
            if validation:
                self._token_data["login"] = (validation.get("login") or self._token_data.get("login") or "").lower()
                self._token_data["expires_at"] = now + int(validation.get("expires_in", 0) or 0)
                return self._token_data

        refresh_token = (self._token_data.get("refresh_token") or "").strip()
        if not refresh_token:
            raise RuntimeError("Conta bot sem refresh token para renovar o access token.")

        refreshed = self._refresh_token(refresh_token)
        refreshed["login"] = self._token_data.get("login", "")
        self._token_data.update(refreshed)

        validation = self._validate_token(self._token_data["access_token"])
        if validation:
            self._token_data["login"] = (validation.get("login") or self._token_data.get("login") or "").lower()
            self._token_data["expires_at"] = now + int(validation.get("expires_in", 0) or 0)

        return self._token_data

    def _validate_token(self, access_token: str) -> dict | None:
        response = requests.get(
            TWITCH_VALIDATE_URL,
            headers={"Authorization": f"OAuth {access_token}"},
            timeout=(3, 5),
        )

        if response.status_code != 200:
            return None

        return response.json()

    def _refresh_token(self, refresh_token: str) -> dict:
        response = requests.post(
            TWITCH_TOKEN_URL,
            data={
                "client_id": self._token_data["client_id"],
                "client_secret": self._token_data["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=(3, 5),
        )

        if response.status_code != 200:
            raise RuntimeError(f"Falha ao renovar token da conta bot. {response.text}")

        token_data = response.json()
        token_data["expires_at"] = int(time.time()) + int(token_data.get("expires_in", 0) or 0)

        if not token_data.get("refresh_token"):
            token_data["refresh_token"] = refresh_token

        return token_data
