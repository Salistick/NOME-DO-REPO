import threading
import time
from pathlib import Path
from typing import Optional

from services.tts.tts_manager import TTSManager

from .youtube_auth import YouTubeAuth
from .youtube_config_store import YouTubeConfigStore
from .youtube_live_resolver import YouTubeLiveResolver
from .youtube_message_store import YouTubeMessageStore
from .youtube_chat_monitor import YouTubeChatMonitor


class YouTubeBot:
    def __init__(
        self,
        tts_manager: TTSManager,
        token_cache_file: Path,
        config_file: Path,
        message_store_file: Path,
    ):
        self.tts = tts_manager

        self.config_store = YouTubeConfigStore(config_file)
        self.message_store = YouTubeMessageStore(message_store_file)
        self.live_resolver = YouTubeLiveResolver()
        self.auth = YouTubeAuth(
            token_cache_file=token_cache_file,
            config_store=self.config_store,
        )

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._status = "desconectado"
        self._lock = threading.Lock()

        self._manual_stop = False
        self._should_reconnect = False

        self._active_account_index = 0
        self._active_account: Optional[dict] = None
        self._active_channel: Optional[dict] = None
        self._active_live: Optional[dict] = None

        self._chat_monitor: Optional[YouTubeChatMonitor] = None

        self._live_recheck_interval_seconds = 60.0
        self._no_live_retry_seconds = 5.0

    # ==================================
    # Status helpers
    # ==================================

    def get_status(self) -> str:
        return self._status

    def is_running(self) -> bool:
        return self._running

    def has_saved_auth(self) -> bool:
        return bool(self.auth.list_cached_accounts())

    def get_active_channel(self) -> Optional[dict]:
        return self._active_channel

    def get_active_live(self) -> Optional[dict]:
        return self._active_live

    def get_active_account_index(self) -> int:
        return self._active_account_index

    # ==================================
    # Public API
    # ==================================

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            self._running = True
            self._manual_stop = False
            self._should_reconnect = True
            self._status = "conectando"

            # ao abrir o bot, sempre volta para a conta principal
            self._active_account_index = 0

            self._thread = threading.Thread(
                target=self._run_forever,
                name="YouTubeBotThread",
                daemon=True,
            )
            self._thread.start()

    def stop(self):
        with self._lock:
            self._running = False
            self._manual_stop = True
            self._should_reconnect = False
            self._status = "desconectando"

        self._stop_chat_monitor()
        try:
            self.message_store.flush()
        except Exception:
            pass

        try:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5.0)
        except Exception:
            pass

        self._thread = None
        self._active_account = None
        self._active_channel = None
        self._active_live = None
        self._status = "desconectado"

    def disconnect_and_forget(self):
        # No YouTube, desconectar só para o monitor atual.
        self.stop()

    def shutdown(self):
        try:
            self.stop()
        except Exception:
            pass
        try:
            self.message_store.flush()
        except Exception:
            pass

    # ==================================
    # Admin helpers
    # ==================================

    def switch_account_by_display_index(self, display_index: int) -> bool:
        if display_index <= 0:
            return False

        index = display_index - 1

        account = self.config_store.get_account_by_index(index)
        channel = self.config_store.get_channel_by_index(index)

        if not account or not channel:
            return False

        print(f"[YOUTUBE BOT] Alterando monitoramento para live{display_index}: {channel.get('title', '')}")

        self._active_account_index = index
        self._active_account = account
        self._active_channel = channel
        self._active_live = None

        self._stop_chat_monitor()

        # força busca imediata
        if self._running and self._should_reconnect and not self._manual_stop:
            try:
                self._reconcile_live_state()
            except Exception as exc:
                print(f"[YOUTUBE BOT] Erro ao trocar imediatamente para live{display_index}: {exc}")

        return True

    def remove_account_by_display_index(self, display_index: int) -> bool:
        if display_index <= 0:
            return False

        removed = self.auth.remove_account_by_display_index(display_index)
        if not removed:
            return False

        total = self.config_store.count_accounts()

        if total <= 0:
            self._active_account_index = 0
            self._active_account = None
            self._active_channel = None
            self._active_live = None
            self._stop_chat_monitor()
            self._status = "desconectado"
            return True

        current_display = self._active_account_index + 1
        if display_index <= current_display:
            self._active_account_index = 0

        self._active_account = self.config_store.get_account_by_index(self._active_account_index)
        self._active_channel = self.config_store.get_channel_by_index(self._active_account_index)
        self._active_live = None

        self._stop_chat_monitor()

        return True

    def list_accounts_summary_lines(self) -> list[str]:
        return self.config_store.build_accounts_summary_lines()

    # ==================================
    # OAuth / conta
    # ==================================

    def ensure_authenticated(self) -> dict:
        # clique manual sempre força novo OAuth
        return self.auth.run_browser_login()

    # ==================================
    # Internal lifecycle
    # ==================================

    def _run_forever(self):
        generic_retry_delay = 5.0

        while self._should_reconnect:
            try:
                self._run_main_loop()

                if self._manual_stop or not self._should_reconnect:
                    break

            except Exception as exc:
                if self._manual_stop or not self._should_reconnect:
                    break

                self._status = "reconectando"
                print(f"[YOUTUBE BOT] Falha: {exc}")
                print(f"[YOUTUBE BOT] Tentando recuperar em {generic_retry_delay}s...")
                self._sleep_with_cancel(generic_retry_delay)

        self._running = False

        if self._manual_stop or not self._should_reconnect:
            self._status = "desconectado"

    def _run_main_loop(self):
        last_recheck_at = 0.0

        while self._should_reconnect and not self._manual_stop:
            self._load_current_account_and_channel()

            if not self._active_account or not self._active_channel:
                self._active_live = None
                self._stop_chat_monitor()
                self._status = "desconectado"
                self._sleep_with_cancel(2.0)
                continue

            now = time.time()

            if now - last_recheck_at >= self._live_recheck_interval_seconds or last_recheck_at == 0.0:
                last_recheck_at = now
                self._reconcile_live_state()

                # se não encontrou live, tenta novamente em 5s
                if self._active_live is None:
                    self._sleep_with_cancel(self._no_live_retry_seconds)
                    last_recheck_at = 0.0
                    continue

            if self._chat_monitor is not None and not self._chat_monitor.is_running():
                print("[YOUTUBE BOT] Monitor do chat morreu. Reavaliando live ativa imediatamente...")
                self._stop_chat_monitor()
                self._active_live = None
                self._reconcile_live_state()
                last_recheck_at = time.time()

            time.sleep(1.0)

    def _load_current_account_and_channel(self):
        account = self.config_store.get_account_by_index(self._active_account_index)
        channel = self.config_store.get_channel_by_index(self._active_account_index)

        # fallback para principal
        if not account or not channel:
            self._active_account_index = 0
            account = self.config_store.get_account_by_index(0)
            channel = self.config_store.get_channel_by_index(0)

        self._active_account = account
        self._active_channel = channel

    def _reconcile_live_state(self):
        if not self._active_channel:
            self._status = "desconectado"
            return

        channel_id = (self._active_channel.get("channel_id") or "").strip()
        if not channel_id:
            self._status = "erro"
            raise RuntimeError("Canal YouTube ativo sem channel_id.")

        self._status = "conectando"
        access_token = self._get_active_account_access_token()

        live_data = self.live_resolver.resolve_active_live(
            channel_id=channel_id,
            access_token=access_token,
        )
        current_video_id = ((self._active_live or {}).get("video_id") or "").strip()
        new_video_id = ((live_data or {}).get("video_id") or "").strip()

        if not live_data or not new_video_id:
            if self._chat_monitor is not None:
                print("[YOUTUBE BOT] Nenhuma live ativa encontrada. Encerrando monitor atual.")
                self._stop_chat_monitor()

            self._active_live = None
            self._status = "aguardando live"
            print(f"[YOUTUBE BOT] Nenhuma live ativa no momento. Nova tentativa em {int(self._no_live_retry_seconds)}s.")
            return

        if self._chat_monitor is not None and current_video_id == new_video_id:
            self._status = "conectado"
            print(f"[YOUTUBE BOT] Live ativa confirmada e inalterada: {new_video_id}")
            return

        if self._chat_monitor is not None and current_video_id != new_video_id:
            print(f"[YOUTUBE BOT] Live mudou de {current_video_id} para {new_video_id}. Reiniciando monitor.")

        self._stop_chat_monitor()
        self._active_live = live_data

        print(
            f"[YOUTUBE BOT] Conta ativa: {self._active_account.get('email', '')} | "
            f"Canal ativo: {self._active_channel.get('title', '')}"
        )
        print(
            f"[YOUTUBE BOT] Live ativa encontrada: {live_data.get('title', '')} | "
            f"video_id={new_video_id}"
        )

        self._chat_monitor = YouTubeChatMonitor(
            video_id=new_video_id,
            on_message=self.handle_incoming_chat_message,
            restart_interval_seconds=300.0,
            idle_sleep_seconds=0.5,
            max_consecutive_failures=3,
        )

        self._chat_monitor.start()
        self._status = "conectado"

        print(f"[YOUTUBE BOT] Monitorando chat da live {new_video_id}")

    def _get_active_account_access_token(self) -> str:
        if self._active_account is None:
            return ""

        try:
            account = self.auth.get_valid_account_by_index(self._active_account_index)
        except Exception as exc:
            print(f"[YOUTUBE BOT] Nao foi possivel renovar token da conta ativa: {exc}")
            return (self._active_account.get("access_token") or "").strip()

        self._active_account = account
        return (account.get("access_token") or "").strip()

    def _stop_chat_monitor(self):
        monitor = self._chat_monitor
        self._chat_monitor = None

        if not monitor:
            return

        try:
            monitor.stop()
        except Exception:
            pass

    def _sleep_with_cancel(self, seconds: float):
        slept = 0.0
        while slept < seconds and self._should_reconnect and not self._manual_stop:
            time.sleep(0.2)
            slept += 0.2

    # ==================================
    # Message ingress
    # ==================================

    def handle_incoming_chat_message(self, message: dict):
        message_id = (message.get("message_id") or "").strip()
        message_text = (message.get("message_text") or "").strip()
        author_name = (message.get("author_name") or "").strip()

        if not message_id or not message_text:
            return

        if self.message_store.has_seen(message_id):
            return

        self.message_store.mark_seen(
            message_id=message_id,
            author_name=author_name,
            message_text=message_text,
        )

        payload = {
            "platform": "youtube",
            "channel": (self._active_channel or {}).get("title", ""),
            "username": author_name,
            "display_name": author_name,
            "message": message_text,
            "role": "viewer",
            "is_mod": False,
            "is_sub": False,
            "is_broadcaster": False,
            "send_chat": None,
        }

        if self.tts:
            self.tts.handle_message(payload)
