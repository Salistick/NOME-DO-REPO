import json
import threading
from pathlib import Path

from persistence import atomic_write_json


def _default_state() -> dict:
    return {
        "platforms": {
            "twitch": {
                "enabled": False,
                "channel_name": ""
            },
            "youtube": {
                "enabled": False,
                "channel_name": ""
            },
            "kick": {
                "enabled": False,
                "channel_name": ""
            }
        },
        "window": {
            "main_geometry": None
        }
    }


class AppStateStore:
    def __init__(self, filepath: Path):
        self.filepath = Path(filepath)
        self._lock = threading.Lock()

    def load(self) -> dict:
        with self._lock:
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                return _default_state()

        if not isinstance(data, dict):
            return _default_state()

        defaults = _default_state()
        if not isinstance(data.get("platforms"), dict):
            data["platforms"] = {}
        for platform, default in defaults["platforms"].items():
            state = data["platforms"].get(platform)
            if not isinstance(state, dict):
                state = default.copy()
                data["platforms"][platform] = state
            for key, value in default.items():
                if type(state.get(key)) is not type(value):
                    state[key] = value
            if "disabled" in state and not isinstance(state["disabled"], bool):
                state["disabled"] = False
        if not isinstance(data.get("window"), dict):
            data["window"] = {}
        if not isinstance(data["window"].get("main_geometry"), str):
            data["window"]["main_geometry"] = None
        return data

    def save(self, data: dict) -> None:
        with self._lock:
            atomic_write_json(self.filepath, data)
