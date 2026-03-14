import signal
import threading
import time
from typing import Callable, Optional

import pytchat


class YouTubeChatMonitor:
    def __init__(
        self,
        video_id: str,
        on_message: Callable[[dict], None],
        restart_interval_seconds: float = 300.0,
        idle_sleep_seconds: float = 0.5,
        max_consecutive_failures: int = 3,
    ):
        self.video_id = (video_id or "").strip()
        self.on_message = on_message

        self.restart_interval_seconds = max(30.0, float(restart_interval_seconds))
        self.idle_sleep_seconds = max(0.1, float(idle_sleep_seconds))
        self.max_consecutive_failures = max(1, int(max_consecutive_failures))

        self._chat = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    # ==================================
    # Public API
    # ==================================

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            if not self.video_id:
                raise ValueError("video_id é obrigatório para iniciar o monitor do YouTube.")

            self._running = True
            self._thread = threading.Thread(
                target=self._run,
                name="YouTubeChatMonitorThread",
                daemon=True,
            )
            self._thread.start()

    def stop(self):
        with self._lock:
            self._running = False

        self._close_chat()

        try:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3.0)
        except Exception:
            pass

        self._thread = None

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ==================================
    # Internal lifecycle
    # ==================================

    def _run(self):
        session_started_at = time.time()
        consecutive_failures = 0

        try:
            while self._running:
                try:
                    if self._chat is None:
                        self._chat = self._create_chat_safe()

                    if not self._chat.is_alive():
                        raise RuntimeError("Monitor do chat do YouTube não está mais ativo.")

                    data = self._chat.get()
                    items = data.sync_items()

                    had_messages = False

                    for item in items:
                        had_messages = True
                        parsed = self._parse_item(item)
                        if parsed:
                            self.on_message(parsed)

                    # sessão longa: reinicia uma vez de forma controlada
                    if time.time() - session_started_at >= self.restart_interval_seconds:
                        self._restart_chat()
                        session_started_at = time.time()
                        consecutive_failures = 0
                        continue

                    if not had_messages:
                        time.sleep(self.idle_sleep_seconds)

                    # se voltou ao normal, zera contador
                    consecutive_failures = 0

                except Exception as exc:
                    if not self._running:
                        break

                    consecutive_failures += 1
                    print(f"[YOUTUBE CHAT] Erro no monitor: {exc}")

                    # Se o monitor falhar repetidamente, para de insistir no mesmo video_id.
                    # A responsabilidade sobe para o YouTubeBot procurar nova live ativa.
                    if consecutive_failures >= self.max_consecutive_failures:
                        print("[YOUTUBE CHAT] Chat indisponível repetidamente. Encerrando monitor para forçar nova busca de live.")
                        self._running = False
                        break

                    try:
                        self._restart_chat()
                    except Exception as restart_exc:
                        print(f"[YOUTUBE CHAT] Erro ao reiniciar monitor: {restart_exc}")

                    session_started_at = time.time()
                    time.sleep(1.0)

        finally:
            self._running = False
            self._close_chat()

    def _create_chat_safe(self):
        original_signal = signal.signal

        def _dummy_signal(*args, **kwargs):
            return None

        try:
            signal.signal = _dummy_signal
            return pytchat.create(video_id=self.video_id)
        finally:
            signal.signal = original_signal

    def _restart_chat(self):
        self._close_chat()

        if self._running:
            self._chat = self._create_chat_safe()

    def _close_chat(self):
        chat = self._chat
        self._chat = None

        if not chat:
            return

        try:
            chat.terminate()
        except Exception:
            pass

    # ==================================
    # Parsing
    # ==================================

    def _parse_item(self, item) -> Optional[dict]:
        try:
            author = getattr(item, "author", None)

            author_name = ""
            author_channel_id = ""

            if author is not None:
                author_name = getattr(author, "name", "") or ""
                author_channel_id = getattr(author, "channelId", "") or ""

            message_text = getattr(item, "message", "") or ""

            message_id = (
                getattr(item, "id", None)
                or getattr(item, "messageId", None)
                or getattr(item, "msgId", None)
                or ""
            )

            message_id = str(message_id).strip()
            author_name = str(author_name).strip()
            author_channel_id = str(author_channel_id).strip()
            message_text = str(message_text).strip()

            if not message_text:
                return None

            if not message_id:
                message_id = self._build_fallback_message_id(
                    author_name=author_name,
                    message_text=message_text,
                    item=item,
                )

            return {
                "message_id": message_id,
                "author_name": author_name,
                "author_channel_id": author_channel_id,
                "message_text": message_text,
            }

        except Exception as exc:
            print(f"[YOUTUBE CHAT] Falha ao parsear item: {exc}")
            return None

    def _build_fallback_message_id(self, author_name: str, message_text: str, item) -> str:
        timestamp = (
            getattr(item, "timestamp", None)
            or getattr(item, "timestampUsec", None)
            or getattr(item, "elapsedTime", None)
            or time.time()
        )

        return f"{author_name}|{message_text}|{timestamp}"