import time
from collections import OrderedDict


class MessageDeduper:
    def __init__(self, max_items: int = 5000, ttl_seconds: float = 600.0):
        self.max_items = max(100, int(max_items))
        self.ttl_seconds = max(5.0, float(ttl_seconds))
        self._items: OrderedDict[str, float] = OrderedDict()

    def seen_or_mark(self, key: str) -> bool:
        if not key:
            return False

        now = time.time()
        self._prune(now)

        if key in self._items:
            self._items.move_to_end(key)
            return True

        self._items[key] = now

        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

        return False

    def _prune(self, now: float) -> None:
        expired_before = now - self.ttl_seconds
        expired = []

        for key, timestamp in self._items.items():
            if timestamp >= expired_before:
                break
            expired.append(key)

        for key in expired:
            self._items.pop(key, None)
