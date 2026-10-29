import threading
from pathlib import Path
from typing import Any

from secure_storage import migration_backup_path, secure_read_json, secure_write_json


class TokenCache:
    def __init__(self, filepath: Path):
        self.filepath = Path(filepath)
        self._lock = threading.RLock()

    def exists(self) -> bool:
        return self.filepath.exists()

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            try:
                data = secure_read_json(self.filepath)
                return data if isinstance(data, dict) else None
            except (OSError, TypeError, ValueError):
                return None

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            secure_write_json(self.filepath, data)

    def save_if_current(self, access_token: str, data: dict[str, Any]) -> bool:
        """Do not let delayed validation resurrect a forgotten/replaced login."""
        with self._lock:
            current = self.load()
            if not current or current.get("access_token") != access_token:
                return False
            self.save(data)
            return True

    def clear(self) -> None:
        with self._lock:
            self.filepath.unlink(missing_ok=True)
            migration_backup_path(self.filepath).unlink(missing_ok=True)
