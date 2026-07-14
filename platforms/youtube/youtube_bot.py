import threading
import time
from pathlib import Path
from typing import Optional

from services.tts.tts_manager import TTSManager

from .youtube_auth import YouTubeAuth
from .youtube_config_store import YouTubeConfigStore
from .youtube_live_resolver import YouTubeLiveResolver
from .youtube_message_store import YouTubeMessageStore
from .youtube_api_chat_monitor import YouTubeApiChatMonitor
from .youtube_chat_sender import YouTubeChatSender
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
        self.sender = YouTubeChatSender(self._get_active_account_access_token)

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._status = "desconectado"
        self._lock = threading.Lock()
        self._state_lock = threading.RLock()

        self._manual_stop = False
        self._should_reconnect = False

        self._active_account_index = 0
        self._active_account: Optional[dict] = None
        self._active_channel: Optional[dict] = None
        self._active_live: Optional[dict] = None
        self._public_mode = False
        self._public_channel_identifier = ""

        self._chat_monitor: Optional[object] = None

        self._live_recheck_interval_seconds = 60.0
        self._no_live_retry_seconds = 60.0
        self._main_loop_sleep_seconds = 2.0
        self._monitor_restart_delay_seconds = 5.0
        self._chat_restart_attempts = 0
        self._max_chat_restart_attempts = 3
        self._current_no_live_retry_seconds = self._no_live_retry_seconds
        self._monitoring_disabled = False
        self.refresh_idle_status()

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
        return bool(self.auth.list_cached_accounts())

    def refresh_idle_status(self):
        if self._running:
            return

        if self._monitoring_disabled:
            self._status = "monitoramento desligado"
            return

        if self.has_saved_auth():
            self._status = "aguardando selecao de live"
            return

        self._status = "desconectado"

    def get_active_channel(self) -> Optional[dict]:
        return self._active_channel

    def get_active_live(self) -> Optional[dict]:
        return self._active_live

    def get_active_account_index(self) -> int:
        return self._active_account_index

    # ==================================
    # Public API
    # ==================================

    def start(self, preferred_account_index: int | None = None):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            self._running = True
            self._manual_stop = False
            self._should_reconnect = True
            self._monitoring_disabled = False
            self._status = "conectando"
            self._public_mode = False
            self._public_channel_identifier = ""

            if preferred_account_index is not None and preferred_account_index >= 0:
                self._active_account_index = preferred_account_index
            else:
                self._active_account_index = 0

            self._thread = threading.Thread(
                target=self._run_forever,
                name="YouTubeBotThread",
                daemon=True,
            )
            self._thread.start()

    def start_public_channel(self, channel_identifier: str):
        channel = (channel_identifier or "").strip()
        if not channel:
            raise ValueError("Informe o nome, @handle ou URL do canal YouTube.")

        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            self._running = True
            self._manual_stop = False
            self._should_reconnect = True
            self._monitoring_disabled = False
            self._status = "conectando YouTube sem login"
            self._public_mode = True
            self._public_channel_identifier = channel
            self._active_account = None
            self._active_channel = {
                "title": channel,
                "channel_id": channel,
                "public": True,
            }
            self._active_live = None
            self._chat_restart_attempts = 0
            self._current_no_live_retry_seconds = self._no_live_retry_seconds

            self._thread = threading.Thread(
                target=self._run_forever,
                name="YouTubePublicBotThread",
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
        self._public_mode = False
        self._public_channel_identifier = ""
        self._chat_restart_attempts = 0
        self._current_no_live_retry_seconds = self._no_live_retry_seconds
        self.refresh_idle_status()

    def disable_monitoring(self):
        self.stop()
        self._monitoring_disabled = True
        self.refresh_idle_status()

    def set_monitoring_disabled(self, disabled: bool):
        self._monitoring_disabled = bool(disabled)
        if not self._running:
            self.refresh_idle_status()

    def is_monitoring_disabled(self) -> bool:
        return self._monitoring_disabled

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

        with self._state_lock:
            index = display_index - 1

            account = self.config_store.get_account_by_index(index)
            channel = self.config_store.get_channel_by_index(index)

            if not account or not channel:
                print(f"[YOUTUBE BOT] live{display_index} nao encontrada na configuracao.")
                return False

            account_id = (account.get("account_id") or "").strip()
            print(
                f"[YOUTUBE BOT] Comando !live{display_index}: "
                f"account_id={account_id or 'sem account_id'} | "
                f"canal={channel.get('title', '')} | running={self._running}"
            )

            self._active_account_index = index
            self._active_account = account
            self._active_channel = channel
            self._active_live = None
            self._public_mode = False
            self._public_channel_identifier = ""
            self._chat_restart_attempts = 0
            self._current_no_live_retry_seconds = self._no_live_retry_seconds
            self._monitoring_disabled = False

            self._stop_chat_monitor()

            # Forca busca imediata para o comando do chat nao depender do proximo ciclo.
            if self._running and self._should_reconnect and not self._manual_stop:
                try:
                    self._reconcile_live_state()
                except Exception as exc:
                    print(f"[YOUTUBE BOT] Erro ao trocar imediatamente para live{display_index}: {exc}")

            return True

    def remove_account_by_display_index(self, display_index: int) -> bool:
        if display_index <= 0:
            return False

        account = self.config_store.get_account_by_index(display_index - 1)
        account_id = ((account or {}).get("account_id") or "").strip()

        if account_id:
            removed_token = self.auth.remove_account_by_account_id(account_id)
            removed_config = self.config_store.remove_account_by_display_index(display_index)
            removed = removed_token or removed_config
        else:
            removed = self.auth.remove_account_by_display_index(display_index)

        if not removed:
            return False

        total = self.config_store.count_accounts()

        if total <= 0:
            self.stop()
            self._monitoring_disabled = False
            self.refresh_idle_status()
            return True

        current_display = self._active_account_index + 1
        if display_index <= current_display:
            self._active_account_index = 0

        self._active_account = self.config_store.get_account_by_index(self._active_account_index)
        self._active_channel = self.config_store.get_channel_by_index(self._active_account_index)
        self._active_live = None
        self._public_mode = False
        self._public_channel_identifier = ""
        self._chat_restart_attempts = 0
        self._current_no_live_retry_seconds = self._no_live_retry_seconds

        self._stop_chat_monitor()

        return True

    def list_accounts_summary_lines(self) -> list[str]:
        return self.config_store.build_accounts_summary_lines()

    def list_account_choices(self) -> list[dict]:
        choices = []

        for idx, line in enumerate(self.config_store.build_accounts_summary_lines(), start=1):
            choices.append(
                {
                    "display_index": idx,
                    "label": line,
                    "active": self._running and self._active_account_index == (idx - 1),
                }
            )

        return choices

    def activate_account_by_display_index(self, display_index: int) -> bool:
        if display_index <= 0:
            return False

        with self._state_lock:
            index = display_index - 1
            account = self.config_store.get_account_by_index(index)
            channel = self.config_store.get_channel_by_index(index)

            if not account or not channel:
                print(f"[YOUTUBE BOT] live{display_index} nao encontrada para ativacao.")
                return False

            self._monitoring_disabled = False

            if not self._running:
                print(
                    f"[YOUTUBE BOT] Comando !live{display_index}: iniciando monitoramento "
                    f"para canal={channel.get('title', '')}"
                )
                self._active_account_index = index
                self._active_account = account
                self._active_channel = channel
                self._active_live = None
                self._public_mode = False
                self._public_channel_identifier = ""
                self._chat_restart_attempts = 0
                self._current_no_live_retry_seconds = self._no_live_retry_seconds
                self.start(preferred_account_index=index)
                return True

            return self.switch_account_by_display_index(display_index)

    def activate_account_by_account_id(self, account_id: str) -> bool:
        index = self.config_store.find_account_index_by_account_id(account_id)
        if index is None:
            return False

        account = self.config_store.get_account_by_index(index)
        channel = self.config_store.get_channel_by_index(index)

        if not account or not channel:
            return False

        self._active_account_index = index
        self._active_account = account
        self._active_channel = channel
        self._active_live = None
        self._public_mode = False
        self._public_channel_identifier = ""
        self._chat_restart_attempts = 0
        self._current_no_live_retry_seconds = self._no_live_retry_seconds
        self._monitoring_disabled = False

        self._stop_chat_monitor()
        self.refresh_idle_status()

        return True

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
            self.refresh_idle_status()

    def _run_main_loop(self):
        last_recheck_at = 0.0

        while self._should_reconnect and not self._manual_stop:
            if self._monitoring_disabled:
                self._status = "monitoramento desligado"
                self._sleep_with_cancel(1.0)
                continue

            if self._public_mode:
                self._load_public_channel()
            else:
                self._load_current_account_and_channel()

            if (not self._public_mode and not self._active_account) or not self._active_channel:
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
                    self._sleep_with_cancel(self._current_no_live_retry_seconds)
                    last_recheck_at = 0.0
                    continue

            if self._chat_monitor is not None and not self._chat_monitor.is_running():
                self._status = "reconectando chat"
                print("[YOUTUBE BOT] Monitor do chat caiu. Tentando reconectar no mesmo video_id...")
                restarted = self._restart_chat_monitor_for_current_live()
                last_recheck_at = time.time()

                if not restarted:
                    print("[YOUTUBE BOT] Reconexao local falhou. Fazendo nova descoberta da live.")
                    self._active_live = None
                    self._reconcile_live_state()
                    last_recheck_at = time.time()

            self._sleep_with_cancel(self._main_loop_sleep_seconds)

    def _load_current_account_and_channel(self):
        with self._state_lock:
            account = self.config_store.get_account_by_index(self._active_account_index)
            channel = self.config_store.get_channel_by_index(self._active_account_index)

            # fallback para principal
            if not account or not channel:
                self._active_account_index = 0
                account = self.config_store.get_account_by_index(0)
                channel = self.config_store.get_channel_by_index(0)

            self._active_account = account
            self._active_channel = channel

    def _load_public_channel(self):
        if not self._public_channel_identifier:
            self._active_channel = None
            return

        self._active_account = None
        self._active_channel = {
            "title": self._public_channel_identifier,
            "channel_id": self._public_channel_identifier,
            "public": True,
        }

    def _reconcile_live_state(self):
        with self._state_lock:
            return self._reconcile_live_state_unlocked()

    def _reconcile_live_state_unlocked(self):
        if not self._active_channel:
            self._status = "desconectado"
            return

        channel_id = (self._active_channel.get("channel_id") or "").strip()
        if not channel_id:
            self._status = "erro"
            raise RuntimeError("Canal YouTube ativo sem channel_id.")

        self._status = "procurando live"
        current_video_id = ((self._active_live or {}).get("video_id") or "").strip()
        live_data = None

        if current_video_id:
            if self._public_mode:
                live_data = self.live_resolver.resolve_public_active_live(channel_id)
            else:
                live_data = self.live_resolver.resolve_active_live(channel_id=channel_id)
            if not live_data:
                print("[YOUTUBE BOT] Live atual nao foi confirmada. Buscando nova live.")

        if live_data is None:
            if self._public_mode:
                live_data = self.live_resolver.resolve_public_active_live(channel_id)
            else:
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
            self._chat_restart_attempts = 0
            self._status = "aguardando live"
            retry_seconds = int(self._current_no_live_retry_seconds)
            print(f"[YOUTUBE BOT] Nenhuma live ativa no momento. Nova tentativa em {retry_seconds}s.")
            self._current_no_live_retry_seconds = min(self._current_no_live_retry_seconds * 2, 300.0)
            return

        if self._chat_monitor is not None and current_video_id == new_video_id:
            self._chat_restart_attempts = 0
            self._current_no_live_retry_seconds = self._no_live_retry_seconds
            self._status = self._build_monitoring_status()
            print(f"[YOUTUBE BOT] Live ativa confirmada e inalterada: {new_video_id}")
            return

        if self._chat_monitor is not None and current_video_id != new_video_id:
            print(f"[YOUTUBE BOT] Live mudou de {current_video_id} para {new_video_id}. Reiniciando monitor.")

        self._stop_chat_monitor()
        self._active_live = live_data
        self._chat_restart_attempts = 0
        self._current_no_live_retry_seconds = self._no_live_retry_seconds

        if self._public_mode:
            print(
                f"[YOUTUBE BOT] Modo sem login | Canal: {self._active_channel.get('title', '')} | "
                "respostas no chat desativadas"
            )
        else:
            print(
                f"[YOUTUBE BOT] Modo autenticado | Conta: {(self._active_account or {}).get('email', '')} | "
                f"Canal: {self._active_channel.get('title', '')}"
            )
        print(
            f"[YOUTUBE BOT] Live ativa selecionada: {live_data.get('title', '')} | "
            f"video_id={new_video_id}"
        )

        self._chat_monitor = self._create_chat_monitor_for_live(live_data)

        self._chat_monitor.start()
        self._status = self._build_monitoring_status()

        print(f"[YOUTUBE BOT] Chat do YouTube em monitoramento | video_id={new_video_id}")

    def _restart_chat_monitor_for_current_live(self) -> bool:
        live_data = self._active_live or {}
        video_id = (live_data.get("video_id") or "").strip()

        if not video_id:
            return False

        self._stop_chat_monitor()
        self._chat_restart_attempts += 1

        if self._chat_restart_attempts > self._max_chat_restart_attempts:
            print("[YOUTUBE BOT] Limite de reconexoes locais atingido para o chat atual.")
            self._chat_restart_attempts = 0
            return False

        self._sleep_with_cancel(self._monitor_restart_delay_seconds)

        if self._manual_stop or not self._should_reconnect:
            return False

        try:
            self._chat_monitor = self._create_chat_monitor_for_live(live_data)
            self._chat_monitor.start()
            self._status = self._build_monitoring_status()
            print(
                f"[YOUTUBE BOT] Chat reconectado no mesmo video_id={video_id} "
                f"(tentativa {self._chat_restart_attempts}/{self._max_chat_restart_attempts})."
            )
            return True
        except Exception as exc:
            print(f"[YOUTUBE BOT] Falha ao reconectar chat localmente: {exc}")
            return False

    def _get_active_account_access_token(self) -> str:
        if self._active_account is None:
            return ""

        account_id = (self._active_account.get("account_id") or "").strip()

        try:
            if account_id:
                account = self.auth.get_valid_account_by_account_id(account_id)
            else:
                account = self.auth.get_valid_account_by_index(self._active_account_index)
        except Exception as exc:
            print(f"[YOUTUBE BOT] Nao foi possivel renovar token da conta ativa: {exc}")
            return (self._active_account.get("access_token") or "").strip()

        self._active_account = account
        return (account.get("access_token") or "").strip()

    def _create_chat_monitor_for_live(self, live_data: dict):
        live_chat_id = (live_data.get("live_chat_id") or "").strip()
        video_id = (live_data.get("video_id") or "").strip()

        if live_chat_id:
            access_token = self._get_active_account_access_token()
            if access_token and not self._public_mode:
                print("[YOUTUBE BOT] Leitura do chat: API oficial do YouTube com OAuth.")
                return YouTubeApiChatMonitor(
                    live_chat_id=live_chat_id,
                    access_token_provider=self._get_active_account_access_token,
                    on_message=self.handle_incoming_chat_message,
                    max_results=500,
                    reconnect_delay_seconds=2.0,
                    max_consecutive_failures=3,
                )

            print("[YOUTUBE BOT] Leitura do chat: live_chat_id encontrado, mas sem OAuth valido; usando monitor publico.")

        print("[YOUTUBE BOT] Leitura do chat: monitor publico do YouTube. Nao consome cota da API oficial.")
        return YouTubeChatMonitor(
            video_id=video_id,
            on_message=self.handle_incoming_chat_message,
            restart_interval_seconds=300.0,
            idle_sleep_seconds=0.5,
            max_consecutive_failures=3,
        )

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
            step = min(0.5, seconds - slept)
            time.sleep(step)
            slept += step

    def _build_monitoring_status(self) -> str:
        if self._public_mode:
            channel = self._public_channel_identifier or "canal"
            return f"monitorando {channel} sem login"

        display_index = self._active_account_index + 1
        return f"monitorando live {display_index}"

    # ==================================
    # Message ingress
    # ==================================

    def handle_incoming_chat_message(self, message: dict):
        message_id = (message.get("message_id") or "").strip()
        message_text = (message.get("message_text") or "").strip()
        author_name = (message.get("author_name") or "").strip()
        author_channel_id = (message.get("author_channel_id") or "").strip()
        role = self._normalize_chat_role(message)

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
            "username": author_channel_id or author_name,
            "display_name": author_name,
            "message": message_text,
            "role": role,
            "is_mod": role == "moderator",
            "is_sub": role == "subscriber",
            "is_broadcaster": role == "broadcaster",
            "send_chat": None if self._public_mode else self.send_chat_message,
        }

        if self.tts:
            self.tts.handle_message(payload)

    def send_chat_message(self, text: str) -> bool:
        clean = " ".join((text or "").split()).strip()
        if not clean:
            return False

        if self._public_mode:
            print("[YOUTUBE SENDER] Monitoramento sem login nao envia mensagens no chat.")
            return False

        live_data = self._active_live or {}
        live_chat_id = (live_data.get("live_chat_id") or "").strip()

        if not live_chat_id and self._active_channel:
            access_token = self._get_active_account_access_token()
            channel_id = (self._active_channel.get("channel_id") or "").strip()
            if channel_id and access_token:
                enriched = self.live_resolver.resolve_active_live(
                    channel_id=channel_id,
                    access_token=access_token,
                )
                if enriched:
                    self._active_live = enriched
                    live_chat_id = (enriched.get("live_chat_id") or "").strip()

        if not live_chat_id:
            print("[YOUTUBE SENDER] live_chat_id indisponivel. Mensagem nao enviada.")
            return False

        if not self.auth.account_has_chat_send_scope(self._active_account):
            print("[YOUTUBE SENDER] Conta YouTube sem permissao de envio. Reconecte a conta pelo bot.")

        return self.sender.send_message(live_chat_id, clean)

    def _normalize_chat_role(self, message: dict) -> str:
        role = str(message.get("role") or "viewer").strip().lower()

        if role in {"owner", "streamer"}:
            return "broadcaster"
        if role in {"mod"}:
            return "moderator"
        if role in {"member", "sponsor", "sub"}:
            return "subscriber"

        is_broadcaster = self._message_bool(message, "is_broadcaster")
        is_mod = self._message_bool(message, "is_mod")
        is_sub = self._message_bool(message, "is_sub")

        if is_broadcaster:
            return "broadcaster"
        if is_mod:
            return "moderator"
        if is_sub:
            return "subscriber"

        if role in {"broadcaster", "moderator", "subscriber", "vip"}:
            return role

        return "viewer"

    def _message_bool(self, message: dict, key: str) -> bool:
        value = message.get(key)

        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "sim", "on"}

        return bool(value)
