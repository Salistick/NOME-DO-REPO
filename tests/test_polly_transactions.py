import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from secure_storage import SecureStorageError
from services.tts.polly_credentials import (
    PollyCredentialConfig,
    PollyCredentialsError,
    PollyCredentialStore,
)

PREFIX = b"mock-protected:"


def protect(raw):
    return PREFIX + raw


def unprotect(raw):
    if not raw.startswith(PREFIX):
        raise PollyCredentialsError("Wrong Windows identity or invalid ciphertext")
    return raw[len(PREFIX):]


class PollyTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.store = PollyCredentialStore(self.directory / "config.json", self.directory / "secret.bin")
        self.protect_patch = patch("services.tts.polly_credentials._protect_secret_bytes", side_effect=protect)
        self.unprotect_patch = patch("services.tts.polly_credentials._unprotect_secret_bytes", side_effect=unprotect)
        self.protect_patch.start()
        self.unprotect_patch.start()
        self.addCleanup(self.protect_patch.stop)
        self.addCleanup(self.unprotect_patch.stop)

    def save(self, name="old"):
        self.store.save_access_key("us-east-1", f"{name}-id", f"{name}-secret")

    def snapshot(self):
        return json.loads(unprotect(self.store.bundle_file.read_bytes()))

    def legacy(self):
        config = PollyCredentialConfig(source="access_key", region="us-east-1", access_key_id="legacy-id")
        self.store.config_file.write_text(json.dumps(config.to_dict()), encoding="utf-8")
        self.store.secret_file.write_bytes(protect(json.dumps({"secret_access_key": "legacy-secret"}).encode()))
        return self.store.config_file.read_bytes(), self.store.secret_file.read_bytes()

    def test_metadata_and_secret_are_one_protected_generation(self):
        self.save()
        raw = self.store.bundle_file.read_bytes()
        self.assertTrue(raw.startswith(PREFIX))
        snapshot = self.snapshot()
        self.assertEqual(snapshot["config"]["access_key_id"], "old-id")
        self.assertEqual(snapshot["secret"]["secret_access_key"], "old-secret")
        self.assertTrue(snapshot["revision"])
        self.assertEqual(list(self.directory.iterdir()), [self.store.bundle_file])

    def test_legacy_migration_preserves_original_pair_for_explicit_recovery(self):
        original_config, original_secret = self.legacy()
        self.assertEqual(self.store.load_config().access_key_id, "legacy-id")
        self.assertEqual(self.snapshot()["secret"]["secret_access_key"], "legacy-secret")
        self.assertEqual(self.store.config_file.read_bytes(), original_config)
        self.assertEqual(self.store.secret_file.read_bytes(), original_secret)
        with patch("services.tts.polly_credentials.boto3.client") as client:
            self.store.create_client()
        self.assertEqual(client.call_args.kwargs["aws_access_key_id"], "legacy-id")
        self.assertEqual(client.call_args.kwargs["aws_secret_access_key"], "legacy-secret")

    def test_migration_write_failure_keeps_the_legacy_pair(self):
        originals = self.legacy()
        with patch("services.tts.polly_credentials.atomic_write_bytes", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.store.load_config()
        self.assertFalse(self.store.bundle_file.exists())
        self.assertEqual((self.store.config_file.read_bytes(), self.store.secret_file.read_bytes()), originals)

    def test_failed_replace_keeps_both_old_values_and_cleans_temporary(self):
        self.save()
        before = self.store.bundle_file.read_bytes()
        with patch("persistence.os.replace", side_effect=OSError("locked")), self.assertRaises(OSError):
            self.save("new")
        self.assertEqual(self.store.bundle_file.read_bytes(), before)
        self.assertEqual(self.store.load_config().access_key_id, "old-id")
        self.assertEqual(self.snapshot()["secret"]["secret_access_key"], "old-secret")
        self.assertEqual(list(self.directory.iterdir()), [self.store.bundle_file])

    def test_dpapi_failure_does_not_replace_current_generation(self):
        self.save()
        before = self.store.bundle_file.read_bytes()
        with patch("services.tts.polly_credentials._protect_secret_bytes", side_effect=SecureStorageError("Windows denied")), self.assertRaises(PollyCredentialsError):
            self.save("new")
        self.assertEqual(self.store.bundle_file.read_bytes(), before)

    def test_present_inaccessible_bundle_never_uses_stale_legacy_credentials(self):
        originals = self.legacy()
        self.store.bundle_file.write_bytes(b"inaccessible ciphertext")
        with self.assertRaisesRegex(PollyCredentialsError, "bundle protegido"):
            self.store.load_config()
        self.assertEqual((self.store.config_file.read_bytes(), self.store.secret_file.read_bytes()), originals)
        self.assertEqual(self.store.bundle_file.read_bytes(), b"inaccessible ciphertext")

    def test_explicit_recovery_restores_legacy_and_preserves_replaced_ciphertext(self):
        self.legacy()
        self.store.bundle_file.write_bytes(b"protected by another Windows identity")
        self.store.recover_legacy_configuration()
        self.assertEqual(self.store.load_config().access_key_id, "legacy-id")
        backup = self.store.bundle_file.with_name(self.store.bundle_file.name + ".recovery.bak")
        self.assertEqual(backup.read_bytes(), b"protected by another Windows identity")
        self.store.clear()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_process_restart_after_replace_reads_complete_new_generation(self):
        self.save()
        self.save("new")
        restarted = PollyCredentialStore(self.store.config_file, self.store.secret_file)
        self.assertEqual(restarted.load_config().access_key_id, "new-id")
        with patch("services.tts.polly_credentials.boto3.client") as client:
            restarted.create_client()
        self.assertEqual(client.call_args.kwargs["aws_secret_access_key"], "new-secret")

    def test_client_uses_matching_metadata_and_secret_during_reconfiguration(self):
        self.save()

        def create(_service, **kwargs):
            self.save("new")
            self.assertEqual(kwargs["aws_access_key_id"], "old-id")
            self.assertEqual(kwargs["aws_secret_access_key"], "old-secret")
            return Mock()

        with patch("services.tts.polly_credentials.boto3.client", side_effect=create):
            self.store.create_client()
        self.assertEqual(self.store.load_config().access_key_id, "new-id")

    def test_late_sso_refresh_cannot_overwrite_a_new_configuration(self):
        self.store._pending_sso_secret = {
            "sso_access_token": "old-token", "sso_refresh_token": "refresh",
            "sso_client_id": "client", "sso_client_secret": "secret",
        }
        self.store.save_sso("us-east-1", "https://example.invalid", "us-east-1", "123", "Account", "Role")
        initial = self.snapshot()
        config = self.store.load_config()
        oidc = Mock()

        def refresh(**_kwargs):
            another_store = PollyCredentialStore(self.store.config_file, self.store.secret_file)
            another_store.save_access_key("us-east-1", "new-id", "new-secret")
            return {"accessToken": "refreshed-token", "expiresIn": 100}

        oidc.create_token.side_effect = refresh
        with patch("services.tts.polly_credentials.boto3.client", return_value=oidc):
            self.store._refresh_sso_access_token(config, initial["secret"], expected_revision=initial["revision"])
        self.assertEqual(self.store.load_config().access_key_id, "new-id")
        self.assertEqual(self.snapshot()["secret"]["secret_access_key"], "new-secret")

    def test_profile_commit_has_no_live_secret_and_clear_removes_legacy_and_bundle(self):
        self.legacy()
        self.store.load_config()
        self.store.save_profile("us-east-1", "profile")
        self.assertEqual(self.snapshot()["secret"], {})
        self.assertTrue(self.store.has_saved_configuration())
        self.store.clear()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_incomplete_legacy_pair_requires_setup_without_losing_config(self):
        self.store.config_file.write_text('{"source":"access_key","region":"us-east-1"}', encoding="utf-8")
        self.assertFalse(self.store.has_saved_configuration())
        self.assertTrue(self.store.config_file.exists())


if __name__ == "__main__":
    unittest.main()
