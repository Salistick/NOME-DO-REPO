import threading
import time
from collections import OrderedDict


class MessageDeduper:
    def __init__(self, max_items: int = 5000, ttl_seconds: float = 600.0):
        self.max_items = max(100, int(max_items))
        self.ttl_seconds = max(5.0, float(ttl_seconds))
        self._items: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def seen_or_mark(self, key: str) -> bool:
        if not key:
            return False

        with self._lock:
            now = time.monotonic()
            self._prune(now)

            if key in self._items:
                return True

            self._items[key] = now

            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

        return False

    def _prune(self, now: float) -> None:
        expired_before = now - self.ttl_seconds
        while self._items:
            _, timestamp = next(iter(self._items.items()))
            if timestamp > expired_before:
                break
            self._items.popitem(last=False)
