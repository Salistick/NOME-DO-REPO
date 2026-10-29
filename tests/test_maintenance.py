import json
import tempfile
import unittest
from pathlib import Path

from maintenance import run_maintenance
from secure_storage import migration_backup_path, secure_read_json, secure_write_json
from single_instance import SingleInstanceLock


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.output = self.path / "result.json"

    def arguments(self):
        return ["--recover-token", "twitch", "--data-dir", str(self.path),
                "--maintenance-output", str(self.output)]

    def test_recovers_without_loading_application_config_or_exposing_values(self):
        token = self.path / "twitch_token.json"
        fixture = {"access_token": "fictional-token-not-a-real-account"}
        secure_write_json(migration_backup_path(token), fixture)
        token.write_bytes(b"corrupted")
        self.assertEqual(run_maintenance(self.arguments()), 0)
        self.assertEqual(secure_read_json(token), fixture)
        self.assertNotIn(fixture["access_token"], self.output.read_text())
        self.assertTrue(json.loads(self.output.read_text())["ok"])

    def test_recovery_refuses_to_overwrite_a_running_instance(self):
        token = self.path / "twitch_token.json"
        token.write_bytes(b"original")
        with SingleInstanceLock(self.path):
            self.assertEqual(run_maintenance(self.arguments()), 1)
        self.assertEqual(token.read_bytes(), b"original")
        self.assertEqual(json.loads(self.output.read_text())["error_type"], "AlreadyRunningError")
