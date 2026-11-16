import secrets
import threading
import time
import urllib.parse
import webbrowser

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
from platforms.oauth_callback import OAuthCallbackServer

from .twitch_cache import TokenCache

TWITCH_AUTH_RECOVERABLE_ERRORS = (
    RuntimeError,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    requests.RequestException,
)


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
            allow_redirects=False,
        )

        if r.status_code != 200:
            raise RuntimeError(f"Falha ao trocar code por token da Twitch (HTTP {r.status_code}).")

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
            allow_redirects=False,
        )

        if r.status_code != 200:
            raise RuntimeError(f"Falha ao renovar token da Twitch (HTTP {r.status_code}).")

        token_data = r.json()
        token_data["expires_at"] = int(time.time()) + int(
            token_data.get("expires_in", 0)
        )

        if not token_data.get("refresh_token"):
            token_data["refresh_token"] = refresh_token

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
            raise RuntimeError("Token invalido ao validar no endpoint /validate.")

        token_data["login"] = (validation.get("login") or "").lower()
        token_data["user_id"] = validation.get("user_id")
        token_data["client_id"] = validation.get("client_id")
        token_data["scopes_validated"] = validation.get("scopes", [])

        return token_data

    # ==================================
    # LOGIN VIA BROWSER
    # ==================================

    def run_browser_login(self, cancel_event: threading.Event | None = None):
        state = secrets.token_urlsafe(24)

        callback = OAuthCallbackServer(TWITCH_REDIRECT_URI, state)
        callback.start()

        try:
            auth_url = self.build_auth_url(state)

            print("Abrindo navegador para autorizar a conta Twitch...")

            threading.Thread(
                target=webbrowser.open,
                args=(auth_url, 2),
                daemon=True,
            ).start()

            code, error = callback.wait_for_code(
                cancel_event=cancel_event
            )

            if error:
                if error == "cancelled":
                    raise RuntimeError("Autenticacao da Twitch cancelada.")
                raise RuntimeError(error)

            if not code:
                raise RuntimeError(
                    "Nao foi possivel obter o codigo OAuth da Twitch."
                )


            token_data = self.exchange_code_for_token(code)
            self.cache.save(token_data)

            def validate_async():
                try:
                    enriched = self.enrich_with_validation(token_data)
                    self.cache.save_if_current(token_data["access_token"], enriched)
                except TWITCH_AUTH_RECOVERABLE_ERRORS as e:
                    print(f"[TWITCH AUTH] Validacao posterior falhou: {type(e).__name__}")

            threading.Thread(
                target=validate_async,
                daemon=True,
            ).start()

            for _ in range(20):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Autenticacao da Twitch cancelada.")

                cached = self.cache.load()
                if cached and cached.get("login"):
                    return cached
                time.sleep(0.1)

            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Autenticacao da Twitch cancelada.")

            return token_data

        finally:
            callback.stop()

    # ==================================
    # TOKEN PRINCIPAL
    # ==================================

    def get_valid_token(self, cancel_event: threading.Event | None = None):
        cached = self.cache.load()

        if cached and cached.get("access_token"):
            now = int(time.time())
            try:
                expires_at = int(cached.get("expires_at", 0) or 0)
            except (TypeError, ValueError):
                expires_at = 0

            if expires_at > now + 60 and cached.get("login"):
                return cached

            refresh_token = cached.get("refresh_token")

            if refresh_token:
                try:
                    refreshed = self.refresh_token(refresh_token)

                    refreshed["login"] = cached.get("login", "")
                    refreshed["user_id"] = cached.get("user_id")
                    refreshed["client_id"] = cached.get("client_id")
                    refreshed["scopes_validated"] = cached.get("scopes_validated", [])

                    self.cache.save(refreshed)

                    if not refreshed.get("login"):
                        try:
                            enriched = self.enrich_with_validation(refreshed)
                            self.cache.save(enriched)
                            return enriched
                        except TWITCH_AUTH_RECOVERABLE_ERRORS as exc:
                            print(f"[TWITCH AUTH] Falha ao validar token renovado: {type(exc).__name__}")

                    return refreshed

                except TWITCH_AUTH_RECOVERABLE_ERRORS as exc:
                    print(f"[TWITCH AUTH] Falha ao renovar token salvo: {type(exc).__name__}")

        return self.run_browser_login(cancel_event=cancel_event)
