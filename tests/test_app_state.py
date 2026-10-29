import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_state import AppStateStore


class AppStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.store = AppStateStore(self.path)

    def test_invalid_shapes_are_repaired(self):
        for value in ([], None, 42, {"platforms": None, "window": []},
                      {"platforms": {"twitch": [], "youtube": {"enabled": "false"}}}):
            with self.subTest(value=value):
                self.path.write_text(json.dumps(value), encoding="utf-8")
                state = self.store.load()
                self.assertIs(state["platforms"]["twitch"]["enabled"], False)
                self.assertIs(state["platforms"]["youtube"]["enabled"], False)
                self.assertIsNone(state["window"]["main_geometry"])

    def test_valid_and_unknown_settings_survive(self):
        state = {"platforms": {"kick": {"enabled": True, "channel_name": "ação"}},
                 "window": {"main_geometry": "440x625+10+20"}, "custom": [1, 2]}
        self.store.save(state)
        loaded = self.store.load()
        self.assertEqual(loaded["platforms"]["kick"], state["platforms"]["kick"])
        self.assertEqual(loaded["window"], state["window"])
        self.assertEqual(loaded["custom"], [1, 2])

    def test_replace_failure_preserves_previous_bytes_and_cleans_temp(self):
        self.store.save({"custom": "previous"})
        original = self.path.read_bytes()
        with patch("persistence.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.store.save({"custom": "new"})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_serialization_failure_preserves_previous_state(self):
        self.store.save({"custom": "previous"})
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.save({"custom": float("nan")})
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
