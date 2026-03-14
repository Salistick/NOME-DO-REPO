import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import requests

from config import (
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REDIRECT_URI,
)
from .youtube_config_store import YouTubeConfigStore


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

YOUTUBE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/youtube.readonly",
]


class OAuthCallbackServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.auth_code: Optional[str] = None
        self.error: Optional[str] = None
        self.state: Optional[str] = None
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)

                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Not found")
                    return

                params = urllib.parse.parse_qs(parsed.query)

                outer.auth_code = params.get("code", [None])[0]
                outer.error = params.get("error", [None])[0]
                outer.state = params.get("state", [None])[0]

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()

                html = """
                <html>
                  <body style="font-family: Arial;">
                    <h2>Autorização do YouTube concluída.</h2>
                    <p>Você pode fechar esta aba e voltar ao bot.</p>
                  </body>
                </html>
                """

                self.wfile.write(html.encode("utf-8"))

            def log_message(self, format, *args):
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass

            try:
                self._server.server_close()
            except Exception:
                pass

    def wait_for_code(self, timeout=180):
        started = time.time()

        while time.time() - started < timeout:
            if self.auth_code or self.error:
                return self.auth_code, self.error, self.state

            time.sleep(0.05)

        return None, "timeout", None


class YouTubeAuth:
    def __init__(self, token_cache_file: Path, config_store: YouTubeConfigStore):
        self.token_cache_file = Path(token_cache_file)
        self.config_store = config_store

    # ==================================
    # token cache
    # ==================================

    def _load_token_cache(self) -> dict:
        if not self.token_cache_file.exists():
            return {"accounts": []}

        try:
            with open(self.token_cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {"accounts": []}

        if not isinstance(data, dict):
            return {"accounts": []}

        accounts = data.get("accounts", [])
        if not isinstance(accounts, list):
            accounts = []

        return {"accounts": accounts}

    def _save_token_cache(self, data: dict) -> None:
        self.token_cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _upsert_account_token(self, account_data: dict) -> None:
        cache = self._load_token_cache()
        accounts = cache["accounts"]

        account_id = account_data.get("account_id")
        if not account_id:
            raise ValueError("account_id ausente ao salvar token do YouTube.")

        found = False
        for item in accounts:
            if item.get("account_id") == account_id:
                item.update(account_data)
                found = True
                break

        if not found:
            accounts.append(account_data)

        self._save_token_cache(cache)

    def _remove_account_token_by_account_id(self, account_id: str) -> bool:
        account_id = (account_id or "").strip()
        if not account_id:
            return False

        cache = self._load_token_cache()
        accounts = cache["accounts"]

        new_accounts = [
            item for item in accounts
            if item.get("account_id") != account_id
        ]

        if len(new_accounts) == len(accounts):
            return False

        cache["accounts"] = new_accounts
        self._save_token_cache(cache)
        return True

    def list_cached_accounts(self) -> list[dict]:
        return self._load_token_cache()["accounts"]

    # ==================================
    # OAuth helpers
    # ==================================

    def build_auth_url(self, state: str) -> str:
        params = {
            "client_id": YOUTUBE_CLIENT_ID,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(YOUTUBE_SCOPES),
            "access_type": "offline",
            "prompt": "select_account consent",
            "state": state,
        }

        return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_token(self, code: str) -> dict:
        payload = {
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": YOUTUBE_REDIRECT_URI,
        }

        response = requests.post(
            GOOGLE_TOKEN_URL,
            data=payload,
            timeout=(3, 5),
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Falha ao trocar code por token do YouTube. "
                f"Status={response.status_code} Body={response.text}"
            )

        token_data = response.json()
        token_data["expires_at"] = int(time.time()) + int(token_data.get("expires_in", 0))
        return token_data

    def refresh_token(self, refresh_token: str) -> dict:
        payload = {
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        response = requests.post(
            GOOGLE_TOKEN_URL,
            data=payload,
            timeout=(3, 5),
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Falha ao renovar token do YouTube. "
                f"Status={response.status_code} Body={response.text}"
            )

        token_data = response.json()
        token_data["expires_at"] = int(time.time()) + int(token_data.get("expires_in", 0))
        return token_data

    # ==================================
    # Google / YouTube profile
    # ==================================

    def fetch_google_userinfo(self, access_token: str) -> dict:
        response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(3, 5),
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Falha ao buscar userinfo Google. "
                f"Status={response.status_code} Body={response.text}"
            )

        return response.json()

    def fetch_my_channels(self, access_token: str) -> list[dict]:
        response = requests.get(
            YOUTUBE_CHANNELS_URL,
            params={
                "part": "id,snippet",
                "mine": "true",
            },
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(3, 5),
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Falha ao listar canais do YouTube. "
                f"Status={response.status_code} Body={response.text}"
            )

        data = response.json()
        items = data.get("items", [])

        channels = []

        for item in items:
            snippet = item.get("snippet", {}) or {}

            channels.append(
                {
                    "channel_id": item.get("id", ""),
                    "title": snippet.get("title", ""),
                    "handle": snippet.get("customUrl", ""),
                }
            )

        return channels

    # ==================================
    # Browser login
    # ==================================

    def run_browser_login(self) -> dict:
        parsed = urllib.parse.urlparse(YOUTUBE_REDIRECT_URI)

        host = parsed.hostname or "localhost"
        port = parsed.port or 80

        state = secrets.token_urlsafe(24)

        callback = OAuthCallbackServer(host, port)
        callback.start()

        try:
            auth_url = self.build_auth_url(state)

            print("Abrindo navegador para autorizar a conta YouTube...")

            threading.Thread(
                target=webbrowser.open,
                args=(auth_url, 2),
                daemon=True,
            ).start()

            code, error, returned_state = callback.wait_for_code()

            if error:
                raise RuntimeError(f"Falha na autorização YouTube: {error}")

            if not code:
                raise RuntimeError("Não foi possível obter o código OAuth do YouTube.")

            if returned_state != state:
                raise RuntimeError("State OAuth inválido no YouTube.")

            token_data = self.exchange_code_for_token(code)

            userinfo = self.fetch_google_userinfo(token_data["access_token"])
            channels = self.fetch_my_channels(token_data["access_token"])

            account_id = str(userinfo.get("id", "")).strip()
            email = str(userinfo.get("email", "")).strip()
            name = str(userinfo.get("name", "")).strip()

            if not account_id:
                raise RuntimeError("OAuth do YouTube retornou conta sem account_id.")

            account_payload = {
                "account_id": account_id,
                "email": email,
                "name": name,
                "access_token": token_data.get("access_token", ""),
                "refresh_token": token_data.get("refresh_token", ""),
                "expires_at": token_data.get("expires_at", 0),
                "channels": channels,
            }

            # salva/atualiza no cache de tokens
            self._upsert_account_token(account_payload)

            # salva/atualiza no config
            self.config_store.upsert_account(
                account_id=account_id,
                email=email,
                name=name,
                channels=channels,
            )

            return account_payload

        finally:
            callback.stop()

    # ==================================
    # Main token flow
    # ==================================

    def get_valid_account(self) -> dict:
        """
        Retorna sempre a conta principal (índice 0), se ela existir.
        Se estiver expirada, tenta refresh.
        Se não houver nenhuma, faz OAuth.
        """
        accounts = self.list_cached_accounts()

        if not accounts:
            return self.run_browser_login()

        account = accounts[0]

        expires_at = int(account.get("expires_at", 0))
        refresh_token = account.get("refresh_token", "")
        access_token = account.get("access_token", "")

        now = int(time.time())

        if access_token and expires_at > now + 60:
            return account

        if refresh_token:
            try:
                refreshed = self.refresh_token(refresh_token)

                account["access_token"] = refreshed.get("access_token", "")
                account["expires_at"] = refreshed.get("expires_at", 0)

                if refreshed.get("refresh_token"):
                    account["refresh_token"] = refreshed.get("refresh_token", "")

                self._upsert_account_token(account)
                return account

            except Exception as exc:
                print(f"[YOUTUBE AUTH] Falha ao renovar token salvo: {exc}")

        return self.run_browser_login()

    # ==================================
    # Multi-account helpers
    # ==================================

    def get_account_by_display_index(self, display_index: int) -> dict | None:
        if display_index <= 0:
            return None

        index = display_index - 1
        accounts = self.list_cached_accounts()

        if index < 0 or index >= len(accounts):
            return None

        return accounts[index]

    def remove_account_by_display_index(self, display_index: int) -> bool:
        if display_index <= 0:
            return False

        account = self.get_account_by_display_index(display_index)
        if not account:
            return False

        account_id = (account.get("account_id") or "").strip()
        if not account_id:
            return False

        removed_token = self._remove_account_token_by_account_id(account_id)
        removed_config = self.config_store.remove_account_by_display_index(display_index)

        return removed_token or removed_config