import json
import threading
import time
from typing import Any

import requests
import websocket

from services.chat.message_dedupe import MessageDeduper

from .kick_pusher_event_mapper import (
    build_fallback_message_id,
    map_kick_pusher_chat_message_event,
)


PUSHER_KEY = "32cbd69e4b950bf97679"
PUSHER_WS_BASE = "wss://ws-us2.pusher.com"
PUSHER_CLIENT_VERSION = "8.4.0"
KICK_CHANNEL_API = "https://kick.com/api/v2/channels/{slug}"
PUSHER_CONNECT_TIMEOUT_SECONDS = 30.0
PUSHER_MAX_PING_INTERVAL_SECONDS = 45.0
PUSHER_RESUBSCRIBE_INTERVAL_SECONDS = 30.0 * 60.0
PUSHER_STALE_MIN_SECONDS = 180.0


class KickPusherClient:
    def __init__(
        self,
        tts_manager,
        reconnect_seconds: int = 5,
        send_chat_callback=None,
    ):
        self.tts_manager = tts_manager
        self.reconnect_seconds = max(2, int(reconnect_seconds or 5))
        self.send_chat_callback = send_chat_callback

        self.channel_slug = ""
        self.chatroom_id = ""
        self.channel_id = ""
        self.broadcaster_user_id = ""

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        self._ws = None
        self._dedupe = MessageDeduper()
        self._lock = threading.Lock()
        self._status = "desconectado"
        self._last_error = ""
        self._last_message_at = 0.0
        self._last_frame_at = 0.0
        self._activity_timeout_seconds = 60.0

    def start(self, channel_slug: str) -> None:
        channel = self.resolve_channel(channel_slug)
        chatroom_id = str(channel.get("chatroom_id") or "").strip()
        if not chatroom_id:
            raise RuntimeError(f"Nao foi possivel resolver o chatroom da Kick para @{channel_slug}.")

        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            self.channel_slug = str(channel.get("slug") or channel_slug).strip().replace("@", "").lower()
            self.chatroom_id = chatroom_id
            self.channel_id = str(channel.get("channel_id") or "").strip()
            self.broadcaster_user_id = str(channel.get("broadcaster_user_id") or "").strip()
            self._stop_event = threading.Event()
            self._connected_event = threading.Event()
            self._status = "conectando WebSocket Kick"
            self._last_error = ""
            self._last_frame_at = 0.0
            self._activity_timeout_seconds = 60.0
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="KickPusherThread",
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._connected_event.clear()

        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

        thread = self._thread
        if thread and thread.is_alive():
            try:
                thread.join(timeout=3.0)
            except Exception:
                pass

        self._thread = None
        self._status = "desconectado"

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def wait_until_connected(self, timeout: float = 10.0) -> bool:
        return self._connected_event.wait(timeout=max(0.1, float(timeout)))

    def get_status(self) -> str:
        return self._status

    def get_last_error(self) -> str:
        return self._last_error

    def get_last_message_at(self) -> float:
        return self._last_message_at

    def resolve_channel(self, channel_slug: str) -> dict[str, Any]:
        slug = self._normalize_slug(channel_slug)
        if not slug:
            raise RuntimeError("Defina KICK_CHANNEL no arquivo .env para usar WebSocket.")

        last_error = None
        for candidate in self._slug_candidates(slug):
            try:
                data = self._fetch_channel(candidate)
            except Exception as exc:
                last_error = exc
                continue

            chatroom = data.get("chatroom") if isinstance(data.get("chatroom"), dict) else {}
            chatroom_id = (
                data.get("chatroom_id")
                or data.get("chatroomId")
                or chatroom.get("id")
            )
            if not chatroom_id:
                last_error = RuntimeError(f"Canal Kick sem chatroom_id: @{candidate}")
                continue

            resolved_slug = self._normalize_slug(
                data.get("slug")
                or data.get("channel_slug")
                or data.get("username")
                or candidate
            )
            return {
                "slug": resolved_slug or candidate,
                "chatroom_id": chatroom_id,
                "channel_id": data.get("id") or data.get("channel_id") or chatroom.get("channel_id"),
                "broadcaster_user_id": (
                    data.get("user_id")
                    or data.get("broadcaster_user_id")
                    or data.get("broadcasterUserId")
                ),
                "raw": data,
            }

        if last_error:
            raise RuntimeError(f"Nao foi possivel resolver o canal Kick @{slug}: {last_error}") from last_error
        raise RuntimeError(f"Nao foi possivel resolver o canal Kick @{slug}.")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._connect_once()
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                self._last_error = str(exc)
                self._status = "WebSocket Kick reconectando"
                print(f"[KICK WS] {exc}")
                self._connected_event.clear()
                self._sleep_interruptible(self.reconnect_seconds)

        self._connected_event.clear()
        if self._status != "desconectado":
            self._status = "desconectado"

    def _connect_once(self) -> None:
        url = (
            f"{PUSHER_WS_BASE}/app/{PUSHER_KEY}"
            f"?protocol=7&client=js&version={PUSHER_CLIENT_VERSION}&flash=false"
        )
        self._status = "conectando WebSocket Kick"
        self._connected_event.clear()
        ws = websocket.create_connection(
            url,
            timeout=10,
            origin="https://kick.com",
            header=[
                "User-Agent: BotLiveKickWebSocket/1.0",
            ],
        )
        self._ws = ws
        ws.settimeout(1.0)
        now = time.time()
        connected_deadline = now + PUSHER_CONNECT_TIMEOUT_SECONDS
        next_ping_at = now + self._current_ping_interval_seconds()
        next_resubscribe_at = now + PUSHER_RESUBSCRIBE_INTERVAL_SECONDS
        self._last_frame_at = now

        try:
            while not self._stop_event.is_set():
                now = time.time()

                if not self._connected_event.is_set() and now >= connected_deadline:
                    raise RuntimeError("Timeout aguardando handshake Pusher da Kick.")

                if self._connected_event.is_set() and now >= next_ping_at:
                    self._send_frame("pusher:ping", {})
                    next_ping_at = now + self._current_ping_interval_seconds()

                if self._connected_event.is_set() and now >= next_resubscribe_at:
                    self._subscribe_channels()
                    next_resubscribe_at = now + PUSHER_RESUBSCRIBE_INTERVAL_SECONDS

                if self._connected_event.is_set() and self._last_frame_at:
                    stale_after = max(
                        PUSHER_STALE_MIN_SECONDS,
                        self._activity_timeout_seconds * 3.0,
                    )
                    if now - self._last_frame_at > stale_after:
                        raise RuntimeError("WebSocket Kick sem atividade; reconectando.")

                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue

                if not raw:
                    raise RuntimeError("WebSocket Kick fechou sem dados.")
                self._handle_frame(raw)
        finally:
            if self._ws is ws:
                self._ws = None
            try:
                ws.close()
            except Exception:
                pass

    def _handle_frame(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except Exception:
            return

        event_name = str(payload.get("event") or "").strip()
        if not event_name:
            return
        self._last_frame_at = time.time()

        if event_name == "pusher:connection_established":
            connection_data = self._decode_data(payload.get("data"))
            if isinstance(connection_data, dict):
                activity_timeout = connection_data.get("activity_timeout")
                try:
                    self._activity_timeout_seconds = max(10.0, float(activity_timeout))
                except Exception:
                    self._activity_timeout_seconds = 60.0

            self._status = "WebSocket Kick conectado"
            self._connected_event.set()
            self._subscribe_channels()
            return

        if event_name == "pusher_internal:subscription_succeeded":
            self._status = "monitorando Kick via WebSocket"
            print(f"[KICK WS] Assinado: {payload.get('channel')}")
            return

        if event_name == "pusher:ping":
            self._send_frame("pusher:pong", {})
            return

        if event_name == "pusher:pong":
            return

        if event_name == "pusher:error":
            error_data = self._decode_data(payload.get("data"))
            message = error_data.get("message") if isinstance(error_data, dict) else str(error_data)
            raise RuntimeError(f"Erro Pusher Kick: {message or 'desconhecido'}")

        data = self._decode_data(payload.get("data"))
        if event_name == "App\\Events\\ChatMessageEvent" and isinstance(data, dict):
            self._handle_chat_message(data)

    def _handle_chat_message(self, data: dict[str, Any]) -> None:
        message = map_kick_pusher_chat_message_event(
            data,
            channel_slug=self.channel_slug,
            broadcaster_user_id=self.broadcaster_user_id,
        )
        if message is None:
            return

        dedupe_key = message.dedupe_key
        if not message.message_id:
            dedupe_key = build_fallback_message_id(message.channel, message.username, message.message)

        if self._dedupe.seen_or_mark(dedupe_key):
            return

        if self.tts_manager:
            self.tts_manager.handle_message(message.to_tts_payload(self.send_chat_callback))
        self._last_message_at = time.time()

    def _subscribe_channels(self) -> None:
        channels = [f"chatrooms.{self.chatroom_id}.v2"]
        if self.channel_id:
            channels.append(f"channel.{self.channel_id}")

        for channel in channels:
            self._send_frame("pusher:subscribe", {"auth": "", "channel": channel})
        print(f"[KICK WS] Assinando canais: {', '.join(channels)}")

    def _send_frame(self, event: str, data: Any) -> None:
        ws = self._ws
        if ws is None:
            return
        ws.send(json.dumps({"event": event, "data": data}, ensure_ascii=False))

    def _current_ping_interval_seconds(self) -> float:
        return max(
            10.0,
            min(PUSHER_MAX_PING_INTERVAL_SECONDS, self._activity_timeout_seconds - 5.0),
        )

    def _fetch_channel(self, slug: str) -> dict[str, Any]:
        response = requests.get(
            KICK_CHANNEL_API.format(slug=slug),
            headers={
                "Accept": "application/json",
                "User-Agent": "BotLiveKickWebSocket/1.0",
            },
            timeout=(5, 10),
        )
        if response.status_code != 200:
            raise RuntimeError(f"Kick retornou status {response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Resposta invalida da Kick.")
        return data

    def _decode_data(self, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def _sleep_interruptible(self, seconds: float) -> None:
        deadline = time.time() + max(0.1, seconds)
        while time.time() < deadline and not self._stop_event.is_set():
            time.sleep(0.1)

    @staticmethod
    def _slug_candidates(slug: str) -> list[str]:
        candidates = [slug]
        if "_" in slug:
            candidates.append(slug.replace("_", "-"))
        if "-" in slug:
            candidates.append(slug.replace("-", "_"))
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _normalize_slug(value: Any) -> str:
        return str(value or "").strip().replace("@", "").lower()
