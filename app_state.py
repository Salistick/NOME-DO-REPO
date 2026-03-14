import json
from pathlib import Path


class AppStateStore:
    def __init__(self, filepath: Path):
        self.filepath = filepath

    def load(self) -> dict:
        if not self.filepath.exists():
            return {
                "platforms": {
                    "twitch": {
                        "enabled": False
                    },
                    "youtube": {
                        "enabled": False
                    }
                }
            }

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "platforms": {
                    "twitch": {
                        "enabled": False
                    },
                    "youtube": {
                        "enabled": False
                    }
                }
            }

    def save(self, data: dict) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)