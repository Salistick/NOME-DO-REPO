import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from persistence import atomic_write_bytes
from secure_storage import (
    SECURE_MAGIC,
    SecureStorageError,
    migration_backup_path,
    protect_secret_bytes,
    recover_secure_json,
    secure_read_json,
    secure_write_json,
    unprotect_secret_bytes,
)


class SecureStorageFailureTests(unittest.TestCase):
    def test_non_windows_does_not_fall_back_to_plaintext(self):
        with patch("secure_storage.os.name", "posix"), self.assertRaises(SecureStorageError):
            protect_secret_bytes(b"fake-secret")

    def test_encryption_failure_never_creates_plaintext_or_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "token.json"
            with patch("secure_storage.protect_secret_bytes", side_effect=SecureStorageError("unavailable")):
                with self.assertRaises(SecureStorageError):
                    secure_write_json(target, {"access_token": "fake-secret"})
            self.assertEqual(list(Path(folder).iterdir()), [])


@unittest.skipUnless(os.name == "nt", "DPAPI requires Windows")
class SecureStorageWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.path = self.folder / "token.json"

    def test_raw_bytes_roundtrip_is_compatible_with_dpapi_blobs(self):
        protected = protect_secret_bytes(b"fake-secret")
        self.assertNotIn(b"fake-secret", protected)
        self.assertEqual(unprotect_secret_bytes(protected), b"fake-secret")

    def test_legacy_json_migrates_with_only_protected_backup(self):
        payload = {"access_token": "fake-secret", "profile": {"name": "ação"}}
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(secure_read_json(self.path), payload)
        for path in (self.path, migration_backup_path(self.path)):
            data = path.read_bytes()
            self.assertTrue(data.startswith(SECURE_MAGIC))
            self.assertNotIn(b"fake-secret", data)
            self.assertEqual(secure_read_json(path, migrate_legacy=False), payload)

    def test_migration_failure_preserves_legacy_source_and_protected_backup(self):
        original = b'{"access_token":"fake-secret"}'
        self.path.write_bytes(original)

        def write(path, data):
            if path == self.path:
                raise OSError("disk")
            atomic_write_bytes(path, data)

        with patch("secure_storage.atomic_write_bytes", side_effect=write), self.assertRaises(OSError):
            secure_read_json(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(secure_read_json(migration_backup_path(self.path)), {"access_token": "fake-secret"})

    def test_unreadable_ciphertext_is_not_treated_as_empty_or_migrated(self):
        broken = SECURE_MAGIC + b"damaged ciphertext"
        self.path.write_bytes(broken)
        with self.assertRaises(SecureStorageError):
            secure_read_json(self.path)
        self.assertEqual(self.path.read_bytes(), broken)
        self.assertFalse(migration_backup_path(self.path).exists())

    def test_explicit_recovery_copies_protected_backup_without_plaintext(self):
        self.path.write_text('{"access_token":"fake-secret"}', encoding="utf-8")
        secure_read_json(self.path)
        self.path.write_bytes(SECURE_MAGIC + b"broken")
        recover_secure_json(self.path)
        self.assertEqual(secure_read_json(self.path), {"access_token": "fake-secret"})
        self.assertTrue(self.path.read_bytes().startswith(SECURE_MAGIC))

    def test_plaintext_backup_is_rejected_by_recovery(self):
        backup = self.folder / "backup"
        backup.write_text('{"access_token":"fake-secret"}', encoding="utf-8")
        with self.assertRaises(SecureStorageError):
            recover_secure_json(self.path, backup)
        self.assertFalse(self.path.exists())

    def test_atomic_write_failure_keeps_previous_protected_file(self):
        secure_write_json(self.path, {"access_token": "old-fake"})
        before = self.path.read_bytes()
        with patch("persistence.os.replace", side_effect=OSError("disk")), self.assertRaises(OSError):
            secure_write_json(self.path, {"access_token": "new-fake"})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.folder.iterdir()), [self.path])

    def test_platform_stores_migrate_and_forget_recovery_tokens(self):
        from platforms.kick.kick_auth import KickAuth
        from platforms.twitch.twitch_cache import TokenCache
        from platforms.youtube.youtube_auth import YouTubeAuth
        from platforms.youtube.youtube_config_store import YouTubeConfigStore

        twitch = TokenCache(self.folder / "twitch.json")
        twitch.filepath.write_text('{"access_token":"fake-twitch"}', encoding="utf-8")
        self.assertEqual(twitch.load()["access_token"], "fake-twitch")
        twitch.clear()
        self.assertFalse(twitch.filepath.exists())
        self.assertFalse(migration_backup_path(twitch.filepath).exists())

        kick = KickAuth(self.folder / "kick.json")
        kick.token_cache_file.write_text('{"access_token":"fake-kick"}', encoding="utf-8")
        self.assertEqual(kick.load_token_cache()["access_token"], "fake-kick")
        kick.clear_token_cache()
        self.assertFalse(migration_backup_path(kick.token_cache_file).exists())

        youtube = YouTubeAuth(self.folder / "youtube.json", YouTubeConfigStore(self.folder / "config.json"))
        payload = {"accounts": [{"account_id": "a", "access_token": "fake-youtube"}, {"account_id": "b"}]}
        youtube.token_cache_file.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(len(youtube.list_cached_accounts()), 2)
        youtube.remove_account_by_account_id("a")
        self.assertEqual(youtube.list_cached_accounts(), [{"account_id": "b"}])
        self.assertEqual(
            secure_read_json(migration_backup_path(youtube.token_cache_file)), {"accounts": [{"account_id": "b"}]}
        )


if __name__ == "__main__":
    unittest.main()
