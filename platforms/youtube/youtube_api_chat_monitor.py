import json
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import requests


YOUTUBE_LIVE_CHAT_STREAM_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages/stream"
YOUTUBE_LIVE_CHAT_LIST_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"


class YouTubeApiChatMonitor:
    def __init__(
        self,
        live_chat_id: str,
        access_token_provider: Callable[[], str],
        on_message: Callable[[dict], None],
        max_results: int = 500,
        reconnect_delay_seconds: float = 2.0,
        max_consecutive_failures: int = 3,
    ):
        self.live_chat_id = (live_chat_id or "").strip()
        self.access_token_provider = access_token_provider
        self.on_message = on_message

        self.max_results = max(200, min(2000, int(max_results or 500)))
        self.reconnect_delay_seconds = max(0.5, float(reconnect_delay_seconds))
        self.max_consecutive_failures = max(1, int(max_consecutive_failures))

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._page_token: str | None = None
        self._created_at = time.time()
        self._use_poll_fallback = False
        self._stream_buffer = ""

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            if not self.live_chat_id:
                raise ValueError("live_chat_id e obrigatorio para iniciar o monitor API do YouTube.")

            self._running = True
            self._stop_event = threading.Event()
            self._created_at = time.time()
            self._thread = threading.Thread(
                target=self._run,
                name="YouTubeApiChatMonitorThread",
                daemon=True,
            )
            self._thread.start()

    def stop(self):
        with self._lock:
            self._running = False
            self._stop_event.set()

        try:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3.0)
        except Exception:
            pass

        self._thread = None

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def _run(self):
        consecutive_failures = 0

        try:
            while self._running and not self._stop_event.is_set():
                try:
                    if self._use_poll_fallback:
                        self._poll_once()
                    else:
                        self._consume_stream()

                    if not self._running or self._stop_event.is_set():
                        break

                    consecutive_failures = 0
                    self._sleep_interruptible(self.reconnect_delay_seconds)

                except Exception as exc:
                    if not self._running or self._stop_event.is_set():
                        break

                    consecutive_failures += 1
                    print(f"[YOUTUBE API CHAT] Erro no monitor: {exc}")

                    if getattr(exc, "stream_fallback", False):
                        self._use_poll_fallback = True
                        consecutive_failures = 0
                        print("[YOUTUBE API CHAT] Stream indisponivel; usando listagem com intervalo oficial.")
                        continue

                    if consecutive_failures >= self.max_consecutive_failures:
                        print("[YOUTUBE API CHAT] Falhas repetidas. Encerrando monitor para forcar nova busca.")
                        self._running = False
                        break

                    self._sleep_interruptible(min(30.0, self.reconnect_delay_seconds * consecutive_failures))
        finally:
            self._running = False

    def _consume_stream(self):
        token = self._get_access_token()
        params = self._build_params(max_results=self.max_results)
        if self._page_token:
            params["pageToken"] = self._page_token

        response = requests.get(
            YOUTUBE_LIVE_CHAT_STREAM_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            stream=True,
            timeout=(5, 70),
        )

        if response.status_code in {400, 404, 405, 501}:
            error = RuntimeError(f"streamList indisponivel: status {response.status_code}")
            setattr(error, "stream_fallback", True)
            raise error

        if response.status_code != 200:
            raise RuntimeError(f"YouTube streamList retornou status {response.status_code}: {response.text[:300]}")

        self._stream_buffer = ""
        for chunk in response.iter_content(chunk_size=65536, decode_unicode=True):
            if not self._running or self._stop_event.is_set():
                break
            if not chunk:
                continue
            self._handle_stream_chunk(chunk)

    def _handle_stream_chunk(self, chunk: str):
        self._stream_buffer += chunk
        decoder = json.JSONDecoder()

        while self._stream_buffer:
            stripped = self._stream_buffer.lstrip()
            if not stripped:
                self._stream_buffer = ""
                return

            skipped = len(self._stream_buffer) - len(stripped)
            if skipped:
                self._stream_buffer = stripped

            try:
                payload, index = decoder.raw_decode(self._stream_buffer)
            except json.JSONDecodeError:
                if len(self._stream_buffer) > 1024 * 1024:
                    self._stream_buffer = self._stream_buffer[-8192:]
                return

            self._handle_payload(payload)
            self._stream_buffer = self._stream_buffer[index:]

    def _poll_once(self):
        token = self._get_access_token()
        params = self._build_params(max_results=min(self.max_results, 500))
        if self._page_token:
            params["pageToken"] = self._page_token

        response = requests.get(
            YOUTUBE_LIVE_CHAT_LIST_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=(5, 20),
        )

        if response.status_code != 200:
            raise RuntimeError(f"YouTube liveChatMessages.list retornou status {response.status_code}: {response.text[:300]}")

        payload = response.json()
        self._handle_payload(payload)

        interval_ms = int(payload.get("pollingIntervalMillis") or 4000)
        self._sleep_interruptible(max(1.0, interval_ms / 1000.0))

    def _handle_payload(self, payload: dict):
        if not isinstance(payload, dict):
            return

        self._page_token = payload.get("nextPageToken") or self._page_token

        if payload.get("offlineAt"):
            self._running = False
            return

        items = payload.get("items") or []
        if not isinstance(items, list):
            return

        for item in items:
            parsed = self._parse_item(item)
            if not parsed:
                continue
            if not self._is_recent_enough(parsed.get("published_at", "")):
                continue
            self.on_message(parsed)

    def _parse_item(self, item: dict) -> Optional[dict]:
        if not isinstance(item, dict):
            return None

        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        author = item.get("authorDetails") if isinstance(item.get("authorDetails"), dict) else {}

        message_text = (
            snippet.get("displayMessage")
            or (snippet.get("textMessageDetails") or {}).get("messageText")
            or (snippet.get("superChatDetails") or {}).get("userComment")
            or (snippet.get("fanFundingEventDetails") or {}).get("userComment")
            or (snippet.get("memberMilestoneChatDetails") or {}).get("userComment")
            or ""
        )
        message_text = str(message_text).strip()
        if not message_text:
            return None

        author_name = str(author.get("displayName") or "").strip()
        author_channel_id = str(author.get("channelId") or snippet.get("authorChannelId") or "").strip()
        role_data = self._detect_author_role(author)

        return {
            "message_id": str(item.get("id") or "").strip(),
            "author_name": author_name,
            "author_channel_id": author_channel_id,
            "message_text": message_text,
            "published_at": str(snippet.get("publishedAt") or "").strip(),
            "role": role_data["role"],
            "is_mod": role_data["is_mod"],
            "is_sub": role_data["is_sub"],
            "is_broadcaster": role_data["is_broadcaster"],
        }

    def _detect_author_role(self, author: dict) -> dict:
        is_broadcaster = bool(author.get("isChatOwner"))
        is_mod = bool(author.get("isChatModerator"))
        is_sub = bool(author.get("isChatSponsor"))

        role = "viewer"
        if is_broadcaster:
            role = "broadcaster"
        elif is_mod:
            role = "moderator"
        elif is_sub:
            role = "subscriber"

        return {
            "role": role,
            "is_mod": is_mod,
            "is_sub": is_sub,
            "is_broadcaster": is_broadcaster,
        }

    def _is_recent_enough(self, published_at: str) -> bool:
        if not published_at:
            return True

        try:
            normalized = published_at.replace("Z", "+00:00")
            timestamp = datetime.fromisoformat(normalized).astimezone(timezone.utc).timestamp()
        except Exception:
            return True

        return timestamp >= self._created_at - 10.0

    def _build_params(self, max_results: int) -> dict:
        return {
            "part": "snippet,authorDetails",
            "liveChatId": self.live_chat_id,
            "maxResults": str(max_results),
            "profileImageSize": "88",
        }

    def _get_access_token(self) -> str:
        token = ""
        if callable(self.access_token_provider):
            token = (self.access_token_provider() or "").strip()

        if not token:
            raise RuntimeError("Token OAuth do YouTube indisponivel para monitorar liveChatMessages.")

        return token

    def _sleep_interruptible(self, seconds: float):
        deadline = time.time() + max(0.1, seconds)
        while time.time() < deadline and self._running and not self._stop_event.is_set():
            time.sleep(min(0.25, deadline - time.time()))
