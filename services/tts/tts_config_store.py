import json
import threading
from pathlib import Path

from persistence import atomic_write_json


class TTSConfigStore:
    def __init__(self, filepath: Path):
        self.filepath = Path(filepath)
        self._lock = threading.Lock()

    def load(self) -> dict:
        if not self.filepath.exists():
            return {}

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}

    def save(self, data: dict) -> None:
        with self._lock:
            atomic_write_json(self.filepath, data)

    def clear(self) -> None:
        try:
            if self.filepath.exists():
                self.filepath.unlink()
        except OSError as exc:
            print(f"[TTS CONFIG] nao foi possivel limpar configuracao: {exc}")
