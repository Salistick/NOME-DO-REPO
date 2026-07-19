import threading

from config import KICK_TOKEN_CACHE_FILE, KICK_WEBSOCKET_RECONNECT_SECONDS
from services.tts.tts_manager import TTSManager

from .kick_auth import KickAuth
from .kick_chat_sender import KickChatSender
from .kick_pusher_client import KickPusherClient


class KickBot:
    def __init__(self, tts_manager: TTSManager):
        self.tts = tts_manager
        self.auth = KickAuth(KICK_TOKEN_CACHE_FILE)
        self.sender = KickChatSender(
            token_provider=self._get_valid_auth_token,
            broadcaster_user_id_provider=self._get_broadcaster_user_id,
        )
        self.pusher_client = KickPusherClient(
            tts_manager=tts_manager,
            reconnect_seconds=KICK_WEBSOCKET_RECONNECT_SECONDS,
            send_chat_callback=self.send_chat_message,
        )

        self._thread: threading.Thread | None = None
        self._running = False
        self._status = "desconectado"
        self._lock = threading.Lock()
        self._auth_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._token_data: dict | None = None
        self._channel_override = ""
        self._public_mode = False
        self._sender_authenticated = False

    def get_status(self) -> str:
        if self.pusher_client.is_running():
            pusher_status = self.pusher_client.get_status()
            if pusher_status and pusher_status != "desconectado":
                if self._public_mode and "sem login" not in pusher_status:
                    return f"{pusher_status} sem login"
                return pusher_status
        return self._status

    def is_running(self) -> bool:
        return self._running or self.pusher_client.is_running()

    def has_saved_auth(self) -> bool:
        return self.auth.has_saved_auth()

    def start(self, force_auth: bool = True, channel_slug: str | None = None):
        channel = self._normalize_channel_slug(channel_slug)
        with self._lock:
            if self._running or (self._thread and self._thread.is_alive()):
                return

            self._running = True
            self._cancel_event = threading.Event()
            self._status = "iniciando Kick"
            self._channel_override = channel
            self._public_mode = bool(channel and not force_auth)
            self._sender_authenticated = False
            self._thread = threading.Thread(
                target=self._run,
                args=(self._cancel_event, force_auth),
                daemon=True,
                name="KickBotThread",
            )
            self._thread.start()

    def start_public_channel(self, channel_slug: str):
        channel = self._normalize_channel_slug(channel_slug)
        if not channel:
            raise ValueError("Informe o nome do canal Kick.")

        self.start(force_auth=False, channel_slug=channel)

    def stop(self):
        with self._lock:
            self._cancel_event.set()
            self._running = False
            self._status = "desconectando"

        try:
            self.pusher_client.stop()
        except Exception:
            pass

        thread = self._thread
        if thread and thread.is_alive():
            try:
                thread.join(timeout=5.0)
            except Exception:
                pass

        self._thread = None
        self._channel_override = ""
        self._public_mode = False
        self._sender_authenticated = False
        self._status = "desconectado"

    def disconnect_and_forget(self):
        self.stop()
        self.auth.clear_token_cache()
        self._token_data = None

    def shutdown(self):
        try:
            self.stop()
        except Exception:
            pass

    def _run(self, cancel_event: threading.Event, force_auth: bool):
        try:
            channel_slug = self._channel_override
            if self._public_mode:
                if not channel_slug:
                    self._status = "defina canal Kick"
                    print("[KICK BOT] Informe um canal Kick para monitorar sem login.")
                    return

                print("[KICK BOT] Monitoramento sem login; respostas no chat ficam desativadas.")
            else:
                self._status = "aguardando OAuth Kick"
                self._sender_authenticated = self._prepare_authenticated_sender(
                    force_auth=force_auth,
                    cancel_event=cancel_event,
                )
                if not self._sender_authenticated:
                    self._status = "OAuth Kick necessario"
                    print("[KICK BOT] Login Kick nao iniciado porque OAuth nao esta pronto.")
                    return

                channel_slug = self._normalize_channel_slug(
                    channel_slug or self._get_authenticated_channel_slug()
                )
                if not channel_slug:
                    self._status = "defina canal Kick"
                    print(
                        "[KICK BOT] OAuth concluido, mas nao foi possivel determinar o canal. "
                        "Use monitoramento por nome do canal."
                    )
                    return

            self._status = "conectando WebSocket Kick"
            self.pusher_client.send_chat_callback = (
                self.send_chat_message if self._sender_authenticated else None
            )
            self.pusher_client.start(channel_slug)
            if cancel_event.is_set():
                return

            if self.pusher_client.wait_until_connected(timeout=10.0):
                self._status = f"monitorando @{channel_slug}"
            else:
                self._status = self.pusher_client.get_status() or "conectando WebSocket Kick"

            suffix = " sem login" if self._public_mode else ""
            print(f"[KICK BOT] monitorando @{channel_slug}{suffix}")
        except Exception as exc:
            self._status = "erro WebSocket Kick"
            print(f"[KICK BOT] Falha no WebSocket Kick: {exc}")
            try:
                self.pusher_client.stop()
            except Exception:
                pass
        finally:
            if not self.pusher_client.is_running():
                self._running = False

    def send_chat_message(self, text: str) -> bool:
        if self._public_mode:
            print("[KICK BOT] Monitoramento sem login nao envia mensagens no chat.")
            return False

        if not self._sender_authenticated:
            print("[KICK BOT] Sessao Kick sem OAuth valido para enviar mensagens.")
            return False

        return self.sender.send_message(text)

    def _prepare_authenticated_sender(self, force_auth: bool, cancel_event: threading.Event | None = None) -> bool:
        if not self.auth.is_configured():
            print("[KICK BOT] OAuth Kick nao configurado; respostas no chat ficam desativadas.")
            return False

        if not force_auth and not self.auth.has_saved_auth():
            return False

        try:
            if force_auth:
                self._token_data = self.auth.run_browser_login(cancel_event=cancel_event)
            else:
                self._token_data = self.auth.get_valid_cached_token()
                if not (self._token_data or {}).get("access_token") and self.auth.has_saved_auth():
                    print("[KICK AUTH] Token salvo invalido. Abrindo OAuth Kick novamente.")
                    self._token_data = self.auth.run_browser_login(cancel_event=cancel_event)

            if not (self._token_data or {}).get("access_token"):
                print("[KICK BOT] Sessao Kick ausente; respostas no chat ficam desativadas.")
                return False

            print("[KICK BOT] Sessao Kick autenticada para envio de mensagens.")
            return True
        except Exception as exc:
            print(f"[KICK BOT] Nao foi possivel autenticar envio Kick: {exc}")
            return False

    def _get_valid_auth_token(self) -> dict:
        if not self.auth.is_configured():
            return {}

        if not self._sender_authenticated:
            return {}

        with self._auth_lock:
            try:
                self._token_data = self.auth.get_valid_cached_token()
            except Exception as exc:
                print(f"[KICK BOT] Token Kick indisponivel para envio: {exc}")
                self._sender_authenticated = False
                return {}

            if not (self._token_data or {}).get("access_token"):
                self._sender_authenticated = False
                return {}

            return self._token_data or {}

    def _get_broadcaster_user_id(self) -> str:
        if self.pusher_client.broadcaster_user_id:
            return self.pusher_client.broadcaster_user_id

        channel_slug = (
            self.pusher_client.channel_slug
            or self._channel_override
            or self._get_authenticated_channel_slug()
        )
        if channel_slug:
            try:
                channel = self.pusher_client.resolve_channel(channel_slug)
                broadcaster_user_id = str(channel.get("broadcaster_user_id") or "").strip()
                if broadcaster_user_id:
                    self.pusher_client.broadcaster_user_id = broadcaster_user_id
                return broadcaster_user_id
            except Exception as exc:
                print(f"[KICK BOT] Falha ao resolver broadcaster_user_id para envio: {exc}")

        return ""

    def _get_authenticated_channel_slug(self) -> str:
        token_data = self._token_data if isinstance(self._token_data, dict) else {}
        profile = token_data.get("profile") if isinstance(token_data.get("profile"), dict) else {}

        for value in (
            token_data.get("username"),
            token_data.get("slug"),
            token_data.get("channel_slug"),
            profile.get("username"),
            profile.get("slug"),
            profile.get("channel_slug"),
            profile.get("name"),
        ):
            channel_slug = self._normalize_channel_slug(value)
            if channel_slug:
                return channel_slug

        return ""

    @staticmethod
    def _normalize_channel_slug(value) -> str:
        return str(value or "").strip().replace("@", "").lower()
