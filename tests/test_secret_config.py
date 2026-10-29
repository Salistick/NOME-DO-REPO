import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

from persistence import atomic_write_bytes
from secret_config import (
    SecretConfigError,
    is_secret_name,
    load_secret_environment,
    recover_environment_secrets,
)
from secure_storage import SECURE_MAGIC, SecureStorageError, secure_read_json


class SecretNameTests(unittest.TestCase):
    def test_every_platform_and_aws_secret_name_is_classified(self):
        names = [
            "TWITCH_CLIENT_SECRET", "TWITCH_BOT_CLIENT_SECRET", "TWITCH_BOT_ACCESS_TOKEN",
            "TWITCH_BOT_REFRESH_TOKEN", "YOUTUBE_CLIENT_SECRET", "KICK_CLIENT_SECRET",
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        ]
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(is_secret_name(name))
        for name in ("TWITCH_CLIENT_ID", "TWITCH_CHANNEL", "KICK_REDIRECT_URI", "POLLY_VOICE_ID", "AWS_REGION"):
            self.assertFalse(is_secret_name(name))


@unittest.skipUnless(os.name == "nt", "DPAPI requires Windows")
class SecretConfigWindowsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.env = self.folder / ".env"
        self.store = self.folder / "platform_secrets.bin"
        self.backup = self.folder / "env_original.bin"
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def load(self):
        return load_secret_environment(self.env, self.store, self.backup)

    def test_migration_preserves_nonsecret_bytes_and_exact_protected_original(self):
        original = (
            b"\xef\xbb\xbf# comment\r\nTWITCH_CLIENT_ID = 'literal id' # keep\r\n"
            b"export TWITCH_CLIENT_SECRET = 'fake-value' # remove secret comment\r\n"
            b"\r\nTWITCH_CHANNEL= some_channel  # exact spacing\r\n"
        )
        self.env.write_bytes(original)
        self.load()
        redacted = self.env.read_bytes()
        self.assertTrue(redacted.startswith(b"\xef\xbb\xbf# comment\r\n"))
        self.assertIn(b"TWITCH_CLIENT_ID = 'literal id' # keep\r\n", redacted)
        self.assertIn(b"\r\nTWITCH_CHANNEL= some_channel  # exact spacing\r\n", redacted)
        self.assertNotIn(b"fake-value", redacted)
        self.assertEqual(os.environ["TWITCH_CLIENT_SECRET"], "fake-value")
        for path in (self.store, self.backup):
            self.assertTrue(path.read_bytes().startswith(SECURE_MAGIC))
            self.assertNotIn(b"fake-value", path.read_bytes())
        backup = secure_read_json(self.backup)
        self.assertEqual(base64.b64decode(backup["env_bytes_base64"]), original)

    def test_duplicate_assignments_preserve_interpolation_order_on_every_launch(self):
        original = (
            "TWITCH_CLIENT_SECRET=first-fake\nURL=${TWITCH_CLIENT_SECRET}\n"
            "TWITCH_CLIENT_SECRET=second-fake\nAFTER=${TWITCH_CLIENT_SECRET}\n"
        )
        expected = dotenv_values(stream=io.StringIO(original))
        self.env.write_bytes(original.encode("utf-8"))
        self.load()
        first_bytes, protected_bytes = self.env.read_bytes(), self.store.read_bytes()
        self.assertIn(b"URL=${TWITCH_CLIENT_SECRET}\n", first_bytes)
        for key, value in expected.items():
            self.assertEqual(os.environ[key], value)
        os.environ.clear()
        self.load()
        for key, value in expected.items():
            self.assertEqual(os.environ[key], value)
        self.assertEqual(self.env.read_bytes(), first_bytes)
        self.assertEqual(self.store.read_bytes(), protected_bytes)

    def test_multiline_escapes_defaults_and_empty_values_keep_dotenv_semantics(self):
        original = (
            'TWITCH_CLIENT_SECRET="line1\\nline2 ${ABSENT:-default}"\n'
            "KICK_CLIENT_SECRET='multi\nline'\nYOUTUBE_CLIENT_SECRET=\nIGNORED_SECRET\n"
        )
        expected = dotenv_values(stream=io.StringIO(original))
        self.env.write_text(original, encoding="utf-8")
        self.load()
        os.environ.clear()
        self.load()
        for key, value in expected.items():
            if value is not None:
                self.assertEqual(os.environ[key], value)
        self.assertNotIn("IGNORED_SECRET", os.environ)

    def test_failure_to_encrypt_preserves_source_and_environment(self):
        original = b"TWITCH_CLIENT_SECRET=fake-value\nTWITCH_CLIENT_ID=some-id\n"
        self.env.write_bytes(original)
        with patch("secure_storage.protect_secret_bytes", side_effect=SecureStorageError("unavailable")):
            with self.assertRaises(SecureStorageError):
                self.load()
        self.assertEqual(self.env.read_bytes(), original)
        self.assertNotIn("TWITCH_CLIENT_SECRET", os.environ)
        self.assertEqual(list(self.folder.iterdir()), [self.env])

    def test_failure_replacing_env_is_recoverable_without_losing_original_values(self):
        original = b"TWITCH_CLIENT_SECRET=fake-value\nTWITCH_CLIENT_ID=some-id\n"
        self.env.write_bytes(original)

        def write(path, payload):
            if path == self.env:
                raise OSError("disk")
            atomic_write_bytes(path, payload)

        with patch("secret_config.atomic_write_bytes", side_effect=write), self.assertRaises(OSError):
            self.load()
        self.assertEqual(self.env.read_bytes(), original)
        self.assertTrue(self.backup.exists())
        self.load()
        self.assertNotIn(b"fake-value", self.env.read_bytes())
        self.assertEqual(os.environ["TWITCH_CLIENT_SECRET"], "fake-value")

    def test_recovery_restores_secret_state_without_writing_plaintext_env(self):
        self.env.write_text("AWS_SECRET_ACCESS_KEY=fake-aws\n", encoding="utf-8")
        self.load()
        redacted = self.env.read_bytes()
        self.store.write_bytes(SECURE_MAGIC + b"broken")
        os.environ.clear()
        with self.assertRaises(SecureStorageError):
            self.load()
        recover_environment_secrets(self.store, self.backup)
        self.load()
        self.assertEqual(os.environ["AWS_SECRET_ACCESS_KEY"], "fake-aws")
        self.assertEqual(self.env.read_bytes(), redacted)

    def test_missing_store_cannot_silently_replace_references_with_empty_strings(self):
        self.env.write_text("KICK_CLIENT_SECRET=fake-kick\n", encoding="utf-8")
        self.load()
        self.store.unlink()
        os.environ.clear()
        with self.assertRaises(SecretConfigError):
            self.load()
        self.assertNotIn("KICK_CLIENT_SECRET", os.environ)

    def test_missing_env_still_loads_protected_values(self):
        self.env.write_text("TWITCH_CLIENT_SECRET=fake-value\n", encoding="utf-8")
        self.load()
        self.env.unlink()
        os.environ.clear()
        self.assertIsNone(self.load())
        self.assertEqual(os.environ["TWITCH_CLIENT_SECRET"], "fake-value")

    def test_nonsecret_only_file_is_not_rewritten(self):
        original = b"# exact\r\nTWITCH_CLIENT_ID = 'value' # keep\r\n"
        self.env.write_bytes(original)
        self.load()
        self.assertEqual(self.env.read_bytes(), original)
        self.assertFalse(self.store.exists())
        self.assertFalse(self.backup.exists())


if __name__ == "__main__":
    unittest.main()
