import threading
import unittest
from unittest.mock import patch

from services.chat.message_dedupe import MessageDeduper


class MessageDeduperTests(unittest.TestCase):
    def test_duplicate_does_not_hide_an_expired_entry_behind_newer_entries(self):
        deduper = MessageDeduper(ttl_seconds=5)
        with patch("services.chat.message_dedupe.time.monotonic", side_effect=[0, 2, 3, 6]):
            self.assertFalse(deduper.seen_or_mark("old"))
            self.assertFalse(deduper.seen_or_mark("new"))
            self.assertTrue(deduper.seen_or_mark("old"))
            self.assertFalse(deduper.seen_or_mark("old"))

    def test_memory_is_bounded(self):
        deduper = MessageDeduper(max_items=100)
        for index in range(1000):
            deduper.seen_or_mark(str(index))
        self.assertEqual(len(deduper._items), 100)
        self.assertFalse(deduper.seen_or_mark("0"))

    def test_only_one_concurrent_caller_marks_the_same_message(self):
        deduper = MessageDeduper()
        barrier = threading.Barrier(12)
        results = []

        def mark():
            barrier.wait(timeout=2)
            results.append(deduper.seen_or_mark("same-message"))

        threads = [threading.Thread(target=mark) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(results.count(False), 1)
        self.assertEqual(results.count(True), 11)


if __name__ == "__main__":
    unittest.main()
