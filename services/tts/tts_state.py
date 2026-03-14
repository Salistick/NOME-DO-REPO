from dataclasses import dataclass, field
import time


@dataclass
class QueuedTTSMessage:
    platform: str
    channel: str
    username: str
    display_name: str
    role: str
    original_message: str
    sanitized_message: str
    tts_text: str
    priority: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass
class TTSState:
    # persistentes
    mode_sub_only: bool = False
    rate_seconds: float = 2.5
    user_cooldown_seconds: float = 5.0
    max_words: int = 20

    # voláteis
    paused: bool = False
    stopped: bool = False

    # controle em memória
    last_user_audio_time: dict[str, float] = field(default_factory=dict)
    queue: list[QueuedTTSMessage] = field(default_factory=list)

    def to_persisted_dict(self) -> dict:
        return {
            "mode_sub_only": self.mode_sub_only,
            "rate_seconds": self.rate_seconds,
            "user_cooldown_seconds": self.user_cooldown_seconds,
            "max_words": self.max_words,
        }

    @classmethod
    def from_persisted_dict(cls, data: dict | None) -> "TTSState":
        data = data or {}
        return cls(
            mode_sub_only=bool(data.get("mode_sub_only", False)),
            rate_seconds=float(data.get("rate_seconds", 2.5)),
            user_cooldown_seconds=float(data.get("user_cooldown_seconds", 5.0)),
            max_words=int(data.get("max_words", 20)),
            paused=False,
            stopped=False,
        )

    def reset_runtime_state(self) -> None:
        self.paused = False
        self.stopped = False
        self.last_user_audio_time.clear()
        self.queue.clear()

    def queue_length(self) -> int:
        return len(self.queue)

    def enqueue(self, item: QueuedTTSMessage) -> None:
        if item.priority:
            self.queue.insert(0, item)
        else:
            self.queue.append(item)

    def dequeue(self) -> QueuedTTSMessage | None:
        if not self.queue:
            return None
        return self.queue.pop(0)

    def clear_queue(self) -> None:
        self.queue.clear()

    def can_user_send_audio(self, username: str, now: float | None = None) -> tuple[bool, float]:
        now = now if now is not None else time.time()

        last_time = self.last_user_audio_time.get(username)
        if last_time is None:
            return True, 0.0

        elapsed = now - last_time
        if elapsed >= self.user_cooldown_seconds:
            return True, 0.0

        remaining = self.user_cooldown_seconds - elapsed
        return False, remaining

    def mark_user_audio_time(self, username: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.last_user_audio_time[username] = now