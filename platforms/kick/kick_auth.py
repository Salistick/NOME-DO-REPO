import base64
import hashlib
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
    KICK_CLIENT_ID,
    KICK_CLIENT_SECRET,
    KICK_REDIRECT_URI,
    KICK_SCOPES,
)


KICK_AUTH_URL = "https://id.kick.com/oauth/authorize"
KICK_TOKEN_URL = "https://id.kick.com/oauth/token"
KICK_USERS_URL = "https://api.kick.com/public/v1/users"


class OAuthCallbackServer:
    def __init__(self, redirect_uri: str):
        parsed = urllib.parse.urlparse(redirect_uri)
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or 80
        self.path = parsed.path or "/callback"
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

                if parsed.path != outer.path:
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
                self.wfile.write(
                    b"<html><body style='font-family: Arial;'>"
                    b"<h2>Autorizacao da Kick concluida.</h2>"
                    b"<p>Voce pode fechar esta aba e voltar ao bot.</p>"
                    b"</body></html>"
                )

            def log_message(self, format, *args):
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="KickOAuthCallbackThread",
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

    def wait_for_code(self, timeout=180, cancel_event: threading.Event | None = None):
        started = time.time()

        while time.time() - started < timeout:
            if cancel_event is not None and cancel_event.is_set():
                return None, "cancelled", None
            if self.auth_code or self.error:
                return self.auth_code, self.error, self.state
            time.sleep(0.05)

        return None, "timeout", None


class KickAuth:
    def __init__(self, token_cache_file: Path):
        self.token_cache_file = Path(token_cache_file)

    def is_configured(self) -> bool:
        return bool(KICK_CLIENT_ID and KICK_CLIENT_SECRET and KICK_REDIRECT_URI)

    def has_saved_auth(self) -> bool:
        cached = self.load_token_cache()
        return bool(cached.get("access_token") or cached.get("refresh_token"))

    def load_token_cache(self) -> dict:
        if not self.token_cache_file.exists():
            return {}

        try:
            with open(self.token_cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}

        return data if isinstance(data, dict) else {}

    def save_token_cache(self, token_data: dict) -> None:
        self.token_cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_cache_file, "w", encoding="utf-8") as f:
            json.dump(token_data, f, ensure_ascii=False, indent=2)

    def clear_token_cache(self) -> None:
        try:
            self.token_cache_file.unlink(missing_ok=True)
        except Exception:
            pass

    def run_browser_login(self, cancel_event: threading.Event | None = None) -> dict:
        if not self.is_configured():
            raise RuntimeError("Defina KICK_CLIENT_ID, KICK_CLIENT_SECRET e KICK_REDIRECT_URI no .env.")

        code_verifier = self._generate_code_verifier()
        code_challenge = self._build_code_challenge(code_verifier)
        state = secrets.token_urlsafe(24)

        callback = OAuthCallbackServer(KICK_REDIRECT_URI)
        callback.start()

        try:
            auth_url = self.build_auth_url(
                state=state,
                code_challenge=code_challenge,
            )

            print("Abrindo navegador para autorizar a conta Kick...")
            threading.Thread(
                target=webbrowser.open,
                args=(auth_url, 2),
                daemon=True,
                name="KickOAuthBrowserThread",
            ).start()

            code, error, returned_state = callback.wait_for_code(cancel_event=cancel_event)

            if error:
                if error == "cancelled":
                    raise RuntimeError("Autenticacao da Kick cancelada.")
                raise RuntimeError(f"Falha na autorizacao Kick: {error}")

            if not code:
                raise RuntimeError("Nao foi possivel obter o codigo OAuth da Kick.")

            if returned_state != state:
                raise RuntimeError("State OAuth invalido na Kick.")

            token_data = self.exchange_code_for_token(code, code_verifier)
            token_data = self._attach_profile(token_data)
            self.save_token_cache(token_data)
            return token_data
        finally:
            callback.stop()

    def build_auth_url(self, state: str, code_challenge: str) -> str:
        params = {
            "response_type": "code",
            "client_id": KICK_CLIENT_ID,
            "redirect_uri": KICK_REDIRECT_URI,
            "scope": " ".join(KICK_SCOPES),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        return f"{KICK_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_token(self, code: str, code_verifier: str) -> dict:
        token_data = self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": KICK_CLIENT_ID,
                "client_secret": KICK_CLIENT_SECRET,
                "redirect_uri": KICK_REDIRECT_URI,
                "code_verifier": code_verifier,
                "code": code,
            }
        )
        return self._normalize_token_data(token_data)

    def refresh_token(self, refresh_token: str) -> dict:
        token_data = self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": KICK_CLIENT_ID,
                "client_secret": KICK_CLIENT_SECRET,
                "refresh_token": refresh_token,
            }
        )
        return self._normalize_token_data(token_data)

    def get_valid_token(self, cancel_event: threading.Event | None = None) -> dict:
        token_data = self.load_token_cache()
        now = int(time.time())

        if token_data.get("access_token") and int(token_data.get("expires_at", 0) or 0) > now + 60:
            return token_data

        refresh_token = (token_data.get("refresh_token") or "").strip()
        if refresh_token:
            try:
                refreshed = self.refresh_token(refresh_token)
                if not refreshed.get("refresh_token"):
                    refreshed["refresh_token"] = refresh_token
                merged = {**token_data, **refreshed}
                merged = self._attach_profile(merged)
                self.save_token_cache(merged)
                return merged
            except Exception as exc:
                print(f"[KICK AUTH] Falha ao renovar token salvo: {exc}")

        return self.run_browser_login(cancel_event=cancel_event)

    def get_valid_cached_token(self) -> dict:
        token_data = self.load_token_cache()
        now = int(time.time())

        if token_data.get("access_token") and int(token_data.get("expires_at", 0) or 0) > now + 60:
            return token_data

        refresh_token = (token_data.get("refresh_token") or "").strip()
        if not refresh_token:
            return {}

        try:
            refreshed = self.refresh_token(refresh_token)
            if not refreshed.get("refresh_token"):
                refreshed["refresh_token"] = refresh_token
            merged = {**token_data, **refreshed}
            merged = self._attach_profile(merged)
            self.save_token_cache(merged)
            return merged
        except Exception as exc:
            print(f"[KICK AUTH] Falha ao renovar token salvo: {exc}")
            return {}

    def _token_request(self, payload: dict) -> dict:
        response = requests.post(
            KICK_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=(5, 15),
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Falha no token OAuth da Kick. Status={response.status_code} Body={response.text[:300]}"
            )

        data = response.json()
        if not isinstance(data, dict) or not data.get("access_token"):
            raise RuntimeError("Kick nao retornou access_token.")
        return data

    def _normalize_token_data(self, token_data: dict) -> dict:
        normalized = dict(token_data)
        normalized["expires_at"] = int(time.time()) + int(normalized.get("expires_in", 0) or 0)
        normalized["scopes"] = self._parse_scope_value(normalized.get("scope", ""))
        return normalized

    def _attach_profile(self, token_data: dict) -> dict:
        access_token = (token_data.get("access_token") or "").strip()
        if not access_token:
            return token_data

        try:
            response = requests.get(
                KICK_USERS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                timeout=(5, 10),
            )
        except Exception:
            return token_data

        if response.status_code != 200:
            return token_data

        try:
            data = response.json()
        except Exception:
            return token_data

        profile = data.get("data")
        if isinstance(profile, list) and profile:
            profile = profile[0]
        if isinstance(profile, dict):
            token_data = dict(token_data)
            token_data["profile"] = profile
            username = (
                profile.get("username")
                or profile.get("slug")
                or profile.get("channel_slug")
                or profile.get("name")
            )
            user_id = profile.get("user_id") or profile.get("id")
            profile_picture = profile.get("profile_picture") or profile.get("profilePicture")

            if username and not token_data.get("username"):
                token_data["username"] = str(username).strip()
            if user_id and not token_data.get("user_id"):
                token_data["user_id"] = str(user_id).strip()
            if profile_picture and not token_data.get("profile_picture"):
                token_data["profile_picture"] = str(profile_picture).strip()
        return token_data

    def _parse_scope_value(self, value: str) -> list[str]:
        if not value:
            return []
        return [item.strip() for item in str(value).split() if item.strip()]

    def _generate_code_verifier(self) -> str:
        return secrets.token_urlsafe(64)

    def _build_code_challenge(self, verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
