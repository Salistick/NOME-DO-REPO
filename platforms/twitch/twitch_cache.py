import json
from pathlib import Path
from typing import Any, Optional


class TokenCache:
    def __init__(self, filepath: Path):
        self.filepath = filepath

    def exists(self) -> bool:
        return self.filepath.exists()

    def load(self) -> Optional[dict[str, Any]]:
        if not self.filepath.exists():
            return None

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save(self, data: dict[str, Any]) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def clear(self) -> None:
        if self.filepath.exists():
            self.filepath.unlink()