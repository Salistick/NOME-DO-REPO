import json
from pathlib import Path


class TTSConfigStore:
    def __init__(self, filepath: Path):
        self.filepath = Path(filepath)

    def load(self) -> dict:
        if not self.filepath.exists():
            return {}

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}

    def save(self, data: dict) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def clear(self) -> None:
        try:
            if self.filepath.exists():
                self.filepath.unlink()
        except OSError as exc:
            print(f"[TTS CONFIG] nao foi possivel limpar configuracao: {exc}")
