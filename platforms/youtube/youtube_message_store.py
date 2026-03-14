import json
import threading
import time
from pathlib import Path


class YouTubeMessageStore:
    def __init__(self, filepath: Path, max_messages: int = 5000):
        self.filepath = Path(filepath)
        self.max_messages = max_messages

        self._lock = threading.Lock()
        self._loaded = False

        self._messages: list[dict] = []
        self._index_by_id: dict[str, int] = {}
        self._seen_ids: set[str] = set()

        self._dirty = False
        self._pending_writes = 0
        self._last_flush_at = 0.0
        self._flush_every_n_changes = 25
        self._flush_every_seconds = 3.0

    def _default_data(self) -> dict:
        return {
            "messages": []
        }

    def _load_from_disk(self) -> list[dict]:
        if not self.filepath.exists():
            return []

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        if not isinstance(data, dict):
            return []

        messages = data.get("messages", [])
        if not isinstance(messages, list):
            return []

        normalized = []
        for item in messages:
            if not isinstance(item, dict):
                continue

            message_id = str(item.get("message_id") or "").strip()
            if not message_id:
                continue

            normalized.append(
                {
                    "message_id": message_id,
                    "author_name": str(item.get("author_name") or "").strip(),
                    "message_text": str(item.get("message_text") or "").strip(),
                    "seen_at": float(item.get("seen_at") or time.time()),
                }
            )

        if len(normalized) > self.max_messages:
            normalized = normalized[-self.max_messages:]

        return normalized

    def _save_to_disk(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "messages": self._messages,
        }

        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _rebuild_indexes(self) -> None:
        self._index_by_id.clear()
        self._seen_ids.clear()

        for idx, item in enumerate(self._messages):
            message_id = item.get("message_id")
            if not message_id:
                continue
            self._index_by_id[message_id] = idx
            self._seen_ids.add(message_id)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        self._messages = self._load_from_disk()
        self._rebuild_indexes()

        self._loaded = True
        self._dirty = False
        self._pending_writes = 0
        self._last_flush_at = time.time()

    def _trim_to_limit(self) -> None:
        if len(self._messages) <= self.max_messages:
            return

        self._messages = self._messages[-self.max_messages:]
        self._rebuild_indexes()

    def _flush_if_needed_unlocked(self, force: bool = False) -> None:
        if not self._dirty:
            return

        now = time.time()
        should_flush = force

        if not should_flush and self._pending_writes >= self._flush_every_n_changes:
            should_flush = True

        if not should_flush and (now - self._last_flush_at) >= self._flush_every_seconds:
            should_flush = True

        if not should_flush:
            return

        self._save_to_disk()
        self._dirty = False
        self._pending_writes = 0
        self._last_flush_at = now

    def load(self) -> dict:
        with self._lock:
            self._ensure_loaded()
            return {
                "messages": list(self._messages),
            }

    def save(self, data: dict) -> None:
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            messages = []

        with self._lock:
            normalized = []
            for item in messages:
                if not isinstance(item, dict):
                    continue

                message_id = str(item.get("message_id") or "").strip()
                if not message_id:
                    continue

                normalized.append(
                    {
                        "message_id": message_id,
                        "author_name": str(item.get("author_name") or "").strip(),
                        "message_text": str(item.get("message_text") or "").strip(),
                        "seen_at": float(item.get("seen_at") or time.time()),
                    }
                )

            if len(normalized) > self.max_messages:
                normalized = normalized[-self.max_messages:]

            self._messages = normalized
            self._rebuild_indexes()
            self._loaded = True

            self._dirty = True
            self._pending_writes += 1
            self._flush_if_needed_unlocked(force=True)

    def clear(self) -> None:
        with self._lock:
            self._messages = []
            self._index_by_id.clear()
            self._seen_ids.clear()
            self._loaded = True

            self._dirty = False
            self._pending_writes = 0
            self._last_flush_at = time.time()

            try:
                if self.filepath.exists():
                    self.filepath.unlink()
            except Exception:
                pass

    # ==================================
    # Controle de mensagens processadas
    # ==================================

    def has_seen(self, message_id: str) -> bool:
        message_id = (message_id or "").strip()
        if not message_id:
            return False

        with self._lock:
            self._ensure_loaded()
            return message_id in self._seen_ids

    def mark_seen(self, message_id: str, author_name: str = "", message_text: str = "") -> None:
        message_id = (message_id or "").strip()
        if not message_id:
            return

        with self._lock:
            self._ensure_loaded()

            idx = self._index_by_id.get(message_id)

            if idx is not None:
                self._messages[idx]["seen_at"] = time.time()
                self._dirty = True
                self._pending_writes += 1
                self._flush_if_needed_unlocked()
                return

            self._messages.append(
                {
                    "message_id": message_id,
                    "author_name": (author_name or "").strip(),
                    "message_text": (message_text or "").strip(),
                    "seen_at": time.time(),
                }
            )

            self._index_by_id[message_id] = len(self._messages) - 1
            self._seen_ids.add(message_id)

            self._trim_to_limit()

            self._dirty = True
            self._pending_writes += 1
            self._flush_if_needed_unlocked()

    def filter_new_messages(self, messages: list[dict]) -> list[dict]:
        with self._lock:
            self._ensure_loaded()
            seen_ids = set(self._seen_ids)

        new_messages = []

        for message in messages:
            message_id = (message.get("message_id") or "").strip()
            if not message_id:
                continue

            if message_id in seen_ids:
                continue

            new_messages.append(message)

        return new_messages

    def mark_many_seen(self, messages: list[dict]) -> None:
        if not messages:
            return

        changed = False

        with self._lock:
            self._ensure_loaded()

            for message in messages:
                message_id = (message.get("message_id") or "").strip()
                if not message_id or message_id in self._seen_ids:
                    continue

                self._messages.append(
                    {
                        "message_id": message_id,
                        "author_name": (message.get("author_name") or "").strip(),
                        "message_text": (message.get("message_text") or "").strip(),
                        "seen_at": time.time(),
                    }
                )

                self._index_by_id[message_id] = len(self._messages) - 1
                self._seen_ids.add(message_id)
                changed = True

            if not changed:
                return

            self._trim_to_limit()

            self._dirty = True
            self._pending_writes += 1
            self._flush_if_needed_unlocked()

    def flush(self) -> None:
        with self._lock:
            self._ensure_loaded()
            self._flush_if_needed_unlocked(force=True)
