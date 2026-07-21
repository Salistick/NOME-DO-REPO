from dataclasses import dataclass, field
import time


SUPPORTED_TTS_PLATFORMS = ("twitch", "youtube", "kick")


@dataclass
class PlatformTTSConfig:
    mode_sub_only: bool = False
    user_cooldown_seconds: float = 5.0
    max_words: int = 20

    def to_dict(self) -> dict:
        return {
            "mode_sub_only": self.mode_sub_only,
            "user_cooldown_seconds": self.user_cooldown_seconds,
            "max_words": self.max_words,
        }

    @classmethod
    def from_dict(cls, data: dict | None, fallback: "PlatformTTSConfig | None" = None) -> "PlatformTTSConfig":
        data = data or {}
        fallback = fallback or cls()
        return cls(
            mode_sub_only=bool(data.get("mode_sub_only", fallback.mode_sub_only)),
            user_cooldown_seconds=float(data.get("user_cooldown_seconds", fallback.user_cooldown_seconds)),
            max_words=int(data.get("max_words", fallback.max_words)),
        )


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
    rate_seconds: float = 2.5
    platform_configs: dict[str, PlatformTTSConfig] = field(default_factory=dict)
    audio_output_device: str = ""

    # voláteis
    paused: bool = False
    stopped: bool = False

    # controle em memória
    last_user_audio_time: dict[str, float] = field(default_factory=dict)
    queue: list[QueuedTTSMessage] = field(default_factory=list)

    def to_persisted_dict(self) -> dict:
        return {
            "audio_output_device": self.audio_output_device,
            "rate_seconds": self.rate_seconds,
            "platforms": {
                platform: self.get_platform_config(platform).to_dict()
                for platform in SUPPORTED_TTS_PLATFORMS
            },
        }

    @classmethod
    def from_persisted_dict(cls, data: dict | None) -> "TTSState":
        data = data or {}
        fallback_config = PlatformTTSConfig.from_dict(data)
        raw_platforms = data.get("platforms") if isinstance(data.get("platforms"), dict) else {}
        platform_configs = {}

        for platform in SUPPORTED_TTS_PLATFORMS:
            raw_config = raw_platforms.get(platform) if isinstance(raw_platforms, dict) else {}
            platform_configs[platform] = PlatformTTSConfig.from_dict(raw_config, fallback_config)

        return cls(
            rate_seconds=float(data.get("rate_seconds", 2.5)),
            platform_configs=platform_configs,
            audio_output_device=str(data.get("audio_output_device", "") or "").strip(),
            paused=False,
            stopped=False,
        )

    def get_platform_config(self, platform: str) -> PlatformTTSConfig:
        platform_key = normalize_tts_platform(platform)
        if platform_key not in self.platform_configs:
            self.platform_configs[platform_key] = PlatformTTSConfig()
        return self.platform_configs[platform_key]

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

    def can_user_send_audio(
        self,
        username: str,
        platform: str = "",
        now: float | None = None,
    ) -> tuple[bool, float]:
        now = now if now is not None else time.time()
        platform_config = self.get_platform_config(platform)
        key = self._user_cooldown_key(username, platform)

        last_time = self.last_user_audio_time.get(key)
        if last_time is None:
            return True, 0.0

        elapsed = now - last_time
        if elapsed >= platform_config.user_cooldown_seconds:
            return True, 0.0

        remaining = platform_config.user_cooldown_seconds - elapsed
        return False, remaining

    def mark_user_audio_time(self, username: str, platform: str = "", now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.last_user_audio_time[self._user_cooldown_key(username, platform)] = now

    @staticmethod
    def _user_cooldown_key(username: str, platform: str) -> str:
        user_key = str(username or "").strip().lower() or "usuario"
        return f"{normalize_tts_platform(platform)}:{user_key}"


def normalize_tts_platform(platform: str) -> str:
    platform_key = str(platform or "").strip().lower()
    if not platform_key:
        return "unknown"
    return platform_key
