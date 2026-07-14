import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class KickChatEvent:
    channel: str
    username: str
    display_name: str
    message: str
    message_id: str
    role: str = "viewer"
    is_mod: bool = False
    is_sub: bool = False
    is_broadcaster: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        if self.message_id:
            return f"kick:id:{self.message_id}"
        return f"kick:fallback:{self.channel}:{self.username}:{self.message}:{int(time.time() // 5)}"

    def to_tts_payload(self, send_chat: Callable[[str], bool] | None = None) -> dict[str, Any]:
        return {
            "platform": "kick",
            "channel": self.channel,
            "username": self.username,
            "display_name": self.display_name,
            "message": self.message,
            "message_id": self.message_id,
            "role": self.role,
            "is_mod": self.is_mod,
            "is_sub": self.is_sub,
            "is_broadcaster": self.is_broadcaster,
            "send_chat": send_chat,
        }
