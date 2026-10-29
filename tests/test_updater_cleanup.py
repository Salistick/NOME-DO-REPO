import json
import tempfile
import unittest
from pathlib import Path

import auto_updater as updater


class UpdaterCleanupTests(unittest.TestCase):
    NOW = 2_000_000_000

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def create_attempt(self, name="owned", age=8 * 24 * 60 * 60):
        path = self.root / f"{updater.UPDATE_DIR_NAME}-{name}"
        path.mkdir()
        (path / updater.UPDATE_MARKER_NAME).write_text(json.dumps({
            "format": updater.UPDATE_MARKER_FORMAT, "created_at": self.NOW - age,
        }), encoding="utf-8")
        (path / updater.INSTALLER_ASSET_NAME).write_bytes(b"fixture")
        return path

    def test_only_old_owned_attempt_is_removed(self):
        old = self.create_attempt()
        recent = self.create_attempt("recent", age=10)
        unmarked = self.create_attempt("unmarked")
        (unmarked / updater.UPDATE_MARKER_NAME).unlink()
        unknown = self.create_attempt("unknown")
        (unknown / "personal-note.txt").write_text("keep", encoding="utf-8")
        self.assertEqual(updater.cleanup_old_update_downloads(self.root, self.NOW), 1)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(unmarked.exists())
        self.assertEqual((unknown / "personal-note.txt").read_text(), "keep")

    def test_future_invalid_and_nested_content_are_preserved(self):
        for name, created_at in (("future", self.NOW + 10), ("nan", float("nan")),
                                 ("invalid", "yesterday")):
            attempt = self.create_attempt(name)
            (attempt / updater.UPDATE_MARKER_NAME).write_text(json.dumps({
                "format": updater.UPDATE_MARKER_FORMAT, "created_at": created_at,
            }), encoding="utf-8")
        nested = self.create_attempt("nested")
        (nested / "documents").mkdir()
        self.assertEqual(updater.cleanup_old_update_downloads(self.root, self.NOW), 0)
        self.assertEqual(len(list(self.root.iterdir())), 4)
