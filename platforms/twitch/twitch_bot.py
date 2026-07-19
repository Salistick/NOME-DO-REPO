import random
import threading
import time
from typing import Callable, Optional

from config import TWITCH_CHANNEL, TOKEN_CACHE_FILE, has_twitch_bot_sender_config
from .twitch_auth import TwitchAuth
from .twitch_cache import TokenCache
from .twitch_irc import TwitchIRCClient
from .twitch_sender import TwitchChatSender


class TwitchBot:

    def __init__(self, tts_manager):

        self.cache = TokenCache(TOKEN_CACHE_FILE)
        self.auth = TwitchAuth(self.cache)

        self.client: Optional[TwitchIRCClient] = None
        self.sender = TwitchChatSender()

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._status = "desconectado"
        self._lock = threading.Lock()

        self._token_data: Optional[dict] = None
        self._message_callback: Optional[Callable[[dict], None]] = None
        self._public_channel = ""
        self._public_mode = False

        self._manual_stop = False
        self._should_reconnect = False

        self.tts = tts_manager

    # ==================================
    # Status helpers
    # ==================================

    def get_status(self) -> str:
        return self._status

    def is_running(self) -> bool:
        return self._running

    def is_public_mode(self) -> bool:
        return self._public_mode

    def has_saved_auth(self) -> bool:
        return self.cache.exists()

    # ==================================
    # Public API
    # ==================================

    def start(self, token_data: dict, message_callback: Optional[Callable[[dict], None]] = None):

        with self._lock:

            if self._thread and self._thread.is_alive():
                return

            self._running = True
            self._manual_stop = False
            self._should_reconnect = True
            self._status = "conectando"

            self._token_data = token_data
            self._message_callback = message_callback
            self._public_channel = ""
            self._public_mode = False

            self._thread = threading.Thread(
                target=self._run_forever,
                name="TwitchBotThread",
                daemon=False,
            )

            self._thread.start()

    def start_public_channel(self, channel_name: str, message_callback: Optional[Callable[[dict], None]] = None):
        channel = (channel_name or "").strip().lower().lstrip("@#")
        if not channel:
            raise ValueError("Informe o nome do canal Twitch.")

        with self._lock:

            if self._thread and self._thread.is_alive():
                return

            self._running = True
            self._manual_stop = False
            self._should_reconnect = True
            self._status = "conectando Twitch sem login"

            self._token_data = {
                "login": f"justinfan{random.randint(10000, 999999)}",
                "access_token": "",
            }
            self._message_callback = message_callback
            self._public_channel = channel
            self._public_mode = True

            self._thread = threading.Thread(
                target=self._run_forever,
                name="TwitchPublicBotThread",
                daemon=False,
            )

            self._thread.start()

    def stop(self):

        with self._lock:
            self._running = False
            self._manual_stop = True
            self._should_reconnect = False
            self._status = "desconectando"

        try:
            if self.client:
                self.client.stop()
        except Exception:
            pass

        try:
            self.sender.disconnect()
        except Exception:
            pass

        try:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5.0)
        except Exception:
            pass

        self.client = None
        self._token_data = None
        self._message_callback = None
        self._public_channel = ""
        self._public_mode = False
        self._thread = None
        self._status = "desconectado"

    def disconnect_and_forget(self):

        self.stop()

        try:
            self.cache.clear()
        except Exception:
            pass

    # ==================================
    # Chat interaction
    # ==================================

    def send_chat_message(self, text: str) -> bool:

        if not text:
            return False

        try:
            clean = " ".join(text.split()).strip()
            if not clean:
                return False

            clean = clean[:450]
            channel = self._get_monitored_channel()

            if not channel:
                print("[TWITCH BOT] Canal monitorado indisponivel. Mensagem nao enviada.")
                return False

            if not has_twitch_bot_sender_config():
                print("[TWITCH BOT] Conta bot da Twitch nao configurada no .env.")
                return False

            self.sender.send_message(channel, clean)
            return True

        except Exception as exc:
            print(f"[TWITCH BOT] Falha ao enviar mensagem: {exc}")
            return False

    # ==================================
    # Connection lifecycle
    # ==================================

    def _run_forever(self):

        retry_delay = 2
        consecutive_failures = 0
        max_consecutive_failures = 3

        while self._should_reconnect:

            try:
                # em reconnects, sempre revalida/renova token antes de usar
                if not self._public_mode and (consecutive_failures > 0 or not self._token_data):
                    self._status = "reconectando"
                    self._token_data = self.auth.get_valid_token()

                started_at = time.time()

                self._run_once()

                # se saiu normalmente sem querer reconnectar, encerra
                if self._manual_stop or not self._should_reconnect:
                    break

                # se caiu depois de rodar, considera falha recuperável
                alive_seconds = time.time() - started_at

                if alive_seconds >= 10:
                    consecutive_failures = 0
                    retry_delay = 2
                else:
                    consecutive_failures += 1

                if consecutive_failures >= max_consecutive_failures:
                    self._status = "erro"
                    print("[TWITCH BOT] Falhas consecutivas demais ao conectar no IRC. Reconnect interrompido.")
                    self._should_reconnect = False
                    break

                self._status = "reconectando"
                print(f"[TWITCH BOT] Conexão perdida. Tentando reconectar em {retry_delay}s...")

            except Exception as exc:
                if self._manual_stop or not self._should_reconnect:
                    break

                consecutive_failures += 1

                if consecutive_failures >= max_consecutive_failures:
                    self._status = "erro"
                    print(f"[TWITCH BOT] Falha de conexão: {exc}")
                    print("[TWITCH BOT] Falhas consecutivas demais. Reconnect interrompido.")
                    self._should_reconnect = False
                    break

                self._status = "reconectando"
                print(f"[TWITCH BOT] Falha de conexão: {exc}")
                print(f"[TWITCH BOT] Tentando reconectar em {retry_delay}s...")

            slept = 0.0
            while slept < retry_delay and self._should_reconnect:
                step = min(0.5, retry_delay - slept)
                time.sleep(step)
                slept += step

            if not self._should_reconnect:
                break

            try:
                if self.client:
                    self.client.stop()
            except Exception:
                pass

            try:
                self.sender.disconnect()
            except Exception:
                pass

            self.client = None
            retry_delay = min(retry_delay + 2, 15)

        self._running = False

        if self._manual_stop:
            self._status = "desconectado"
        elif not self._should_reconnect and self._status != "erro":
            self._status = "desconectado"

    def _run_once(self):

        token_data = self._token_data or {}

        login = token_data.get("login")
        access_token = token_data.get("access_token")

        if self._public_mode:
            channel = self._public_channel
            if not login or not channel:
                raise RuntimeError("Canal Twitch publico indisponivel.")

            print(f"[TWITCH BOT] Monitoramento sem login: #{channel}")

            self.client = TwitchIRCClient(
                oauth_token="",
                login_name=login,
                channel_name=channel,
                anonymous=True,
            )

            self.client.connect()

            self._status = f"monitorando #{channel} sem login"
            print(f"Conectado ao chat da Twitch sem login. Monitorando #{channel}...")
            self.client.listen_forever(self._on_message)

            if not self._manual_stop and self._should_reconnect:
                raise RuntimeError("Conexao IRC anonima encerrada.")

            return

        if not login or not access_token:
            raise RuntimeError("Token sem login/access_token suficiente para conectar ao chat.")

        channel = TWITCH_CHANNEL or login

        print(f"[TWITCH BOT] Conta autenticada: {login}")
        print(f"[TWITCH BOT] Canal monitorado: {channel}")

        self.client = TwitchIRCClient(
            oauth_token=access_token,
            login_name=login,
            channel_name=channel,
        )

        self.client.connect()

        self._status = f"monitorando #{channel}"

        print(f"Conectado ao chat da Twitch. Monitorando #{channel}...")
        self._announce_chat_connection(channel)

        self.client.listen_forever(self._on_message)

        # se saiu do loop sem stop manual, trata como queda
        if not self._manual_stop and self._should_reconnect:
            raise RuntimeError("Conexão IRC encerrada.")

    # ==================================
    # Message handler
    # ==================================

    def _on_message(self, message: dict):

        try:

            role = message.get("role", "viewer")

            payload = {
                "platform": "twitch",
                "channel": message.get("channel", ""),
                "username": message.get("username", ""),
                "display_name": message.get("display_name", ""),
                "message": message.get("message", ""),
                "role": role,
                "is_mod": role == "moderator",
                "is_sub": role == "subscriber",
                "is_broadcaster": role == "broadcaster",
                "send_chat": self.send_chat_message,
            }

            if self.tts:
                self.tts.handle_message(payload)

            if self._message_callback:
                self._message_callback(message)

        except Exception as exc:
            print(f"[TWITCH BOT] Erro no callback de mensagem: {exc}")

    def _announce_chat_connection(self, channel: str):
        message = "Mensagem de voz conectado ao chat"

        for attempt in range(2):
            try:
                if attempt:
                    time.sleep(1.0)
                self.send_chat_message(message)
                print(f"[TWITCH BOT] Mensagem de conexao enviada em #{channel}.")
                return
            except Exception as exc:
                print(f"[TWITCH BOT] Falha ao enviar mensagem de conexao (tentativa {attempt + 1}/2): {exc}")

    # ==================================
    # Shutdown completo
    # ==================================

    def shutdown(self):

        try:
            self.stop()
        except Exception:
            pass

    def _get_monitored_channel(self) -> str:
        if self.client and getattr(self.client, "channel_name", ""):
            return self.client.channel_name

        if self._public_channel:
            return self._public_channel

        token_data = self._token_data or {}
        login = (token_data.get("login") or "").strip().lower()

        return (TWITCH_CHANNEL or login).strip().lower().lstrip("#")
