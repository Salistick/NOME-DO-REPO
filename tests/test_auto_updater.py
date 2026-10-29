import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

import auto_updater as updater


class AutoUpdaterTests(unittest.TestCase):
    TAG = "v1.2.3"
    URL = "https://github.com/Salistick/NOME-DO-REPO/releases/download/v1.2.3/TTSLiveInstaller.exe"
    CONTENT = b"MZ-test-installer"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.digest = "sha256:" + hashlib.sha256(self.CONTENT).hexdigest()
        self.response = MagicMock()
        self.response.__enter__.return_value = self.response
        self.response.iter_content.return_value = [self.CONTENT[:5], b"", self.CONTENT[5:]]

    def download(self, **kwargs):
        values = dict(download_url=self.URL, tag_name=self.TAG,
                      expected_digest=self.digest, expected_size=len(self.CONTENT))
        values.update(kwargs)
        with patch("auto_updater.tempfile.gettempdir", return_value=str(self.root)):
            with patch("auto_updater.requests.get", return_value=self.response):
                return updater._download_installer(**values)

    def test_verified_download_is_complete_and_unique(self):
        first = self.download()
        second = self.download()
        self.assertEqual(first.read_bytes(), self.CONTENT)
        self.assertNotEqual(first.parent, second.parent)
        self.response.__exit__.assert_called()

    def test_corrupt_truncated_or_failed_download_leaves_no_executable(self):
        cases = [dict(expected_digest="sha256:" + "0" * 64),
                 dict(expected_size=len(self.CONTENT) + 1),
                 dict(expected_size=len(self.CONTENT) - 1)]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    self.download(**case)
                self.assertEqual(list(self.root.iterdir()), [])
        self.response.iter_content.side_effect = requests.ConnectionError("offline")
        with self.assertRaises(requests.ConnectionError):
            self.download()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_metadata_never_contacts_server(self):
        cases = [dict(download_url="https://example.com/installer.exe"),
                 dict(expected_digest=""), dict(expected_size=True),
                 dict(expected_size=updater.MAX_INSTALLER_BYTES + 1),
                 dict(tag_name="v1.2.3/../../evil"), dict(tag_name="v1.2.3&calc")]
        for case in cases:
            with self.subTest(case=case), patch("auto_updater.requests.get") as get:
                values = dict(download_url=self.URL, tag_name=self.TAG,
                              expected_digest=self.digest, expected_size=len(self.CONTENT))
                values.update(case)
                with self.assertRaises(ValueError):
                    updater._download_installer(**values)
                get.assert_not_called()

    def test_versions_compare_numerically_without_prereleases(self):
        self.assertEqual(updater._parse_version("v1.2"), updater._parse_version("1.2.0"))
        self.assertGreater(updater._parse_version("v1.10"), updater._parse_version("v1.9"))
        for tag in ("v1.2.3-beta1", "v1.2&calc", "dev", "1/2", None, "vv1.2"):
            with self.subTest(tag=tag):
                self.assertEqual(updater._parse_version(tag), ())

    def test_non_object_release_is_ignored(self):
        self.response.json.return_value = []
        with patch("auto_updater._is_supported_runtime", return_value=True), \
                patch("auto_updater.CURRENT_APP_VERSION", "v1.0"), \
                patch("auto_updater.cleanup_old_update_downloads"), \
                patch("auto_updater.requests.get", return_value=self.response):
            self.assertFalse(updater.try_start_auto_update())

    def test_batch_paths_reject_expansion(self):
        with self.assertRaises(ValueError):
            updater._write_update_script(self.root / "%USERPROFILE%.exe",
                                         self.root / "current.exe", self.root / "app.exe", 1234)


if __name__ == "__main__":
    unittest.main()
