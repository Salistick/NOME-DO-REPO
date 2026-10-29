import importlib.metadata
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from build_scripts import prepare_windows_build_assets as assets

ROOT = Path(__file__).resolve().parents[1]


def read_lock(name):
    content = (ROOT / name).read_text(encoding="utf-8-sig")
    logical_lines = content.replace("\\\n", " ").splitlines()
    requirements = {}
    for line in logical_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement_text, *hashes = line.split(" --hash=sha256:")
        requirement = Requirement(requirement_text.strip())
        if len(requirement.specifier) != 1 or next(iter(requirement.specifier)).operator != "==":
            raise AssertionError(f"Unpinned dependency in {name}: {line}")
        if not hashes or any(not re.fullmatch(r"[a-f0-9]{64}", value.strip()) for value in hashes):
            raise AssertionError(f"Missing or malformed SHA-256 in {name}: {line}")
        requirements[canonicalize_name(requirement.name)] = str(requirement.specifier)
    return requirements


class BuildAssetsTests(unittest.TestCase):
    def test_all_locks_pin_packages_and_match_runtime_build_dev_versions(self):
        runtime = read_lock("requirements.txt")
        build = read_lock("requirements-build.txt")
        development = read_lock("requirements-dev.txt")
        self.assertGreater(len(runtime), 7)  # Transitive dependencies are locked too.
        self.assertEqual(runtime, {name: build[name] for name in runtime})
        self.assertEqual(build, {name: development[name] for name in build})
        for name, specifier in development.items():
            with self.subTest(package=name):
                self.assertEqual("==" + importlib.metadata.version(name), specifier)

    def test_generated_version_resource_is_readable_by_pyinstaller(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch.object(assets, "BUILD_ASSETS_DIR", target), patch.dict(os.environ, {"TTSLIVE_VERSION": "v1.2.3"}):
                assets.main()
            info = load_version_info_from_text_file(target / "version_info.txt")
            self.assertEqual(info.ffi.fileVersionMS, (1 << 16) | 2)
            self.assertEqual(info.ffi.fileVersionLS, 3 << 16)
            self.assertEqual((target / "version.txt").read_text(encoding="utf-8"), "v1.2.3\n")

    @unittest.skipUnless(sys.platform == "win32", "Windows build helper")
    def test_build_refuses_existing_artifact_directory_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            sentinel = target / "keep.txt"
            sentinel.write_text("previous build", encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 str(ROOT / "build_scripts" / "build_windows.ps1"),
                 "-PythonPath", sys.executable, "-ArtifactRoot", str(target),
                 "-SkipDependencyInstall", "-SkipTests"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Artifact directory already exists", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "previous build")


if __name__ == "__main__":
    unittest.main()
