import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

import requests

from config import (
    TWITCH_AUTH_URL,
    TWITCH_CLIENT_ID,
    TWITCH_CLIENT_SECRET,
    TWITCH_REDIRECT_URI,
    TWITCH_SCOPES,
    TWITCH_TOKEN_URL,
    TWITCH_VALIDATE_URL,
)
from .twitch_cache import TokenCache


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
                    <h2>Autorização concluída.</h2>
                    <p>Você pode fechar esta aba.</p>
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

        start = time.time()

        while time.time() - start < timeout:

            if self.auth_code or self.error:
                return self.auth_code, self.error, self.state

            time.sleep(0.05)

        return None, "timeout", None


class TwitchAuth:

    def __init__(self, cache: TokenCache):
        self.cache = cache

    # ==================================
    # AUTH URL
    # ==================================

    def build_auth_url(self, state):

        params = {
            "client_id": TWITCH_CLIENT_ID,
            "redirect_uri": TWITCH_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(TWITCH_SCOPES),
            "state": state,
            "force_verify": "false",
        }

        return f"{TWITCH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    # ==================================
    # EXCHANGE TOKEN
    # ==================================

    def exchange_code_for_token(self, code):

        payload = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": TWITCH_REDIRECT_URI,
        }

        r = requests.post(
            TWITCH_TOKEN_URL,
            data=payload,
            timeout=(3, 5),
        )

        if r.status_code != 200:
            raise RuntimeError(
                f"Falha ao trocar code por token. {r.text}"
            )

        token_data = r.json()
        token_data["expires_at"] = int(time.time()) + int(
            token_data.get("expires_in", 0)
        )

        return token_data

    # ==================================
    # REFRESH TOKEN
    # ==================================

    def refresh_token(self, refresh_token):

        payload = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        r = requests.post(
            TWITCH_TOKEN_URL,
            data=payload,
            timeout=(3, 5),
        )

        if r.status_code != 200:
            raise RuntimeError(
                f"Falha ao renovar token. {r.text}"
            )

        token_data = r.json()
        token_data["expires_at"] = int(time.time()) + int(
            token_data.get("expires_in", 0)
        )

        return token_data

    # ==================================
    # VALIDATE TOKEN
    # ==================================

    def validate_token(self, access_token):

        headers = {"Authorization": f"OAuth {access_token}"}

        r = requests.get(
            TWITCH_VALIDATE_URL,
            headers=headers,
            timeout=(3, 5),
        )

        if r.status_code != 200:
            return None

        return r.json()

    # ==================================
    # ENRICH
    # ==================================

    def enrich_with_validation(self, token_data: dict) -> dict:

        validation = self.validate_token(token_data["access_token"])

        if not validation:
            raise RuntimeError("Token inválido ao validar no endpoint /validate.")

        token_data["login"] = (validation.get("login") or "").lower()
        token_data["user_id"] = validation.get("user_id")
        token_data["client_id"] = validation.get("client_id")
        token_data["scopes_validated"] = validation.get("scopes", [])

        return token_data

    # ==================================
    # LOGIN VIA BROWSER
    # ==================================

    def run_browser_login(self):

        parsed = urllib.parse.urlparse(TWITCH_REDIRECT_URI)

        host = parsed.hostname or "localhost"
        port = parsed.port or 80

        state = secrets.token_urlsafe(24)

        callback = OAuthCallbackServer(host, port)
        callback.start()

        try:

            auth_url = self.build_auth_url(state)

            print("Abrindo navegador para autorizar a conta Twitch...")

            threading.Thread(
                target=webbrowser.open,
                args=(auth_url, 2),
                daemon=True,
            ).start()

            code, error, returned_state = callback.wait_for_code()

            if error:
                raise RuntimeError(error)

            if not code:
                raise RuntimeError(
                    "Não foi possível obter o código OAuth da Twitch."
                )

            if returned_state != state:
                raise RuntimeError(
                    "State OAuth inválido. Possível resposta adulterada."
                )

            token_data = self.exchange_code_for_token(code)

            # salva imediatamente para não atrasar o fluxo
            self.cache.save(token_data)

            def validate_async():
                try:
                    enriched = self.enrich_with_validation(token_data)
                    self.cache.save(enriched)
                except Exception as e:
                    print("[TWITCH AUTH] validação posterior falhou:", e)

            threading.Thread(
                target=validate_async,
                daemon=True,
            ).start()

            # espera curta pelo login aparecer no cache
            for _ in range(20):
                cached = self.cache.load()
                if cached and cached.get("login"):
                    return cached
                time.sleep(0.1)

            return token_data

        finally:
            callback.stop()

    # ==================================
    # TOKEN PRINCIPAL
    # ==================================

    def get_valid_token(self):

        cached = self.cache.load()

        if cached and cached.get("access_token"):

            now = int(time.time())
            expires_at = int(cached.get("expires_at", 0))

            # usa direto se ainda estiver confortável
            if (
                expires_at > now + 60
                and cached.get("login")
            ):
                return cached

            refresh_token = cached.get("refresh_token")

            if refresh_token:
                try:
                    refreshed = self.refresh_token(refresh_token)

                    # preserva dados anteriores se refresh não trouxer tudo
                    refreshed["login"] = cached.get("login", "")
                    refreshed["user_id"] = cached.get("user_id")
                    refreshed["client_id"] = cached.get("client_id")
                    refreshed["scopes_validated"] = cached.get("scopes_validated", [])

                    self.cache.save(refreshed)

                    # se não tiver login, tenta enriquecer rapidamente
                    if not refreshed.get("login"):
                        try:
                            enriched = self.enrich_with_validation(refreshed)
                            self.cache.save(enriched)
                            return enriched
                        except Exception as exc:
                            print(f"[TWITCH AUTH] Falha ao enriquecer token renovado: {exc}")

                    return refreshed

                except Exception as exc:
                    print(f"[TWITCH AUTH] Falha ao renovar token salvo: {exc}")

        return self.run_browser_login()