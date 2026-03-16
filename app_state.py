import json
from pathlib import Path


def _default_state() -> dict:
    return {
        "platforms": {
            "twitch": {
                "enabled": False
            },
            "youtube": {
                "enabled": False
            }
        },
        "window": {
            "main_geometry": None
        }
    }


class AppStateStore:
    def __init__(self, filepath: Path):
        self.filepath = filepath

    def load(self) -> dict:
        if not self.filepath.exists():
            return _default_state()

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return _default_state()

        defaults = _default_state()
        data.setdefault("platforms", {})
        data["platforms"].setdefault("twitch", defaults["platforms"]["twitch"].copy())
        data["platforms"].setdefault("youtube", defaults["platforms"]["youtube"].copy())
        data.setdefault("window", {})
        data["window"].setdefault("main_geometry", None)
        return data

    def save(self, data: dict) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
