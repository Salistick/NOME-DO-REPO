import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from platforms.youtube.youtube_auth import YouTubeAuth
from platforms.youtube.youtube_config_store import YouTubeConfigStore
from platforms.youtube.youtube_json import atomic_write_json
from platforms.youtube.youtube_message_store import YouTubeMessageStore


class YouTubeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)

    def test_failed_replace_preserves_cache_and_removes_temporary_file(self):
        target = self.path / "cache.json"
        atomic_write_json(target, {"old": True})
        with (
            patch("persistence.os.replace", side_effect=OSError("disk")),
            self.assertRaises(OSError),
        ):
            atomic_write_json(target, {"new": True})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"old": True})
        self.assertEqual(list(self.path.iterdir()), [target])

    def test_concurrent_config_upserts_keep_every_account(self):
        store = YouTubeConfigStore(self.path / "config.json")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: store.upsert_account(str(i), "", "", []), range(30)))
        self.assertEqual({item["account_id"] for item in store.list_accounts()}, {str(i) for i in range(30)})

    def test_concurrent_token_upserts_keep_every_account(self):
        auth = YouTubeAuth(self.path / "tokens.json", YouTubeConfigStore(self.path / "config.json"))
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: auth.update_account_token({"account_id": str(i)}), range(30)))
        self.assertEqual({item["account_id"] for item in auth.list_cached_accounts()}, {str(i) for i in range(30)})

    def test_message_eviction_keeps_indexes_without_rebuilding_on_each_message(self):
        store = YouTubeMessageStore(self.path / "messages.json", max_messages=3)
        store.load()
        with patch.object(store, "_rebuild_indexes", side_effect=AssertionError("linear rebuild")):
            for index in range(200):
                store.mark_seen(str(index), message_text=f"text {index}")
        self.assertEqual([item["message_id"] for item in store.load()["messages"]], ["197", "198", "199"])
        self.assertFalse(store.has_seen("196"))
        self.assertTrue(store.has_seen("198"))
        store.mark_seen("198")
        store.flush()
        restored = YouTubeMessageStore(store.filepath, max_messages=3)
        self.assertEqual(restored.load(), store.load())

    def test_filter_removes_duplicates_within_the_same_batch(self):
        store = YouTubeMessageStore(self.path / "messages.json")
        messages = [{"message_id": "a"}, {"message_id": "a"}, {"message_id": "b"}]
        self.assertEqual(store.filter_new_messages(messages), [messages[0], messages[2]])

    def test_loaded_message_snapshot_cannot_modify_internal_indexes(self):
        store = YouTubeMessageStore(self.path / "messages.json")
        store.mark_seen("original")
        store.load()["messages"][0]["message_id"] = "changed"
        self.assertEqual(store.load()["messages"][0]["message_id"], "original")
        self.assertTrue(store.has_seen("original"))

    def test_malformed_timestamp_does_not_break_loading(self):
        target = self.path / "messages.json"
        target.write_text(json.dumps({"messages": [{"message_id": "a", "seen_at": "invalid"}]}), encoding="utf-8")
        store = YouTubeMessageStore(target)
        self.assertTrue(store.has_seen("a"))
        self.assertIsInstance(store.load()["messages"][0]["seen_at"], float)


if __name__ == "__main__":
    unittest.main()
