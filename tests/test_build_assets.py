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
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from build_scripts import prepare_windows_build_assets as assets

ROOT = Path(__file__).resolve().parents[1]


def read_lock_requirements(name):
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
        requirements[canonicalize_name(requirement.name)] = requirement
    return requirements


def read_lock(name):
    return {name: str(requirement.specifier)
            for name, requirement in read_lock_requirements(name).items()}


def windows_dependency_gaps(requirements, python_version):
    """Validate locked metadata for the target, including transitive extras."""
    environment = {
        **default_environment(), "os_name": "nt", "sys_platform": "win32",
        "platform_system": "Windows", "platform_machine": "AMD64",
        "implementation_name": "cpython", "platform_python_implementation": "CPython",
        "python_version": python_version, "python_full_version": python_version + ".0",
        "implementation_version": python_version + ".0",
    }
    requirements = {
        name: requirement for name, requirement in requirements.items()
        if requirement.marker is None or requirement.marker.evaluate({**environment, "extra": ""})
    }
    pending = [(name, "") for name in requirements]
    pending.extend((name, extra) for name, requirement in requirements.items()
                   for extra in requirement.extras)
    processed = set()
    gaps = set()
    while pending:
        name, extra = pending.pop()
        if (name, extra) in processed:
            continue
        processed.add((name, extra))
        for value in importlib.metadata.requires(name) or []:
            dependency = Requirement(value)
            if dependency.marker and not dependency.marker.evaluate({**environment, "extra": extra}):
                continue
            dependency_name = canonicalize_name(dependency.name)
            locked = requirements.get(dependency_name)
            if locked is None:
                gaps.add(f"{name} requires missing {dependency_name}")
                continue
            version = next(iter(locked.specifier)).version
            if not dependency.specifier.contains(version, prereleases=True):
                gaps.add(f"{name} requires {dependency}, locked {locked}")
            pending.extend((dependency_name, child_extra) for child_extra in dependency.extras)
    return sorted(gaps)


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

    def test_windows_dependencies_are_unconditional_direct_inputs(self):
        for filename, expected in (("requirements-build.in", ("pefile", "pywin32-ctypes")),
                                   ("requirements-dev.in", ("colorama",))):
            direct = {}
            for line in (ROOT / filename).read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith(("#", "-")):
                    requirement = Requirement(line)
                    direct[canonicalize_name(requirement.name)] = requirement
            for name in expected:
                with self.subTest(filename=filename, dependency=name):
                    self.assertIn(name, direct)
                    self.assertIsNone(direct[name].marker)
                    self.assertEqual(len(direct[name].specifier), 1)
                    self.assertEqual(next(iter(direct[name].specifier)).operator, "==")

    def test_locks_close_all_windows_dependencies_for_supported_python_versions(self):
        for filename in ("requirements.txt", "requirements-build.txt", "requirements-dev.txt"):
            requirements = read_lock_requirements(filename)
            for version in ("3.12", "3.13"):
                with self.subTest(lock=filename, python=version):
                    self.assertEqual(windows_dependency_gaps(requirements, version), [])

    def test_windows_closure_detects_the_packages_dropped_by_linux_regeneration(self):
        requirements = read_lock_requirements("requirements-dev.txt")
        for name in ("pefile", "pywin32-ctypes", "colorama"):
            with self.subTest(removed=name):
                incomplete = {key: value for key, value in requirements.items() if key != name}
                gaps = windows_dependency_gaps(incomplete, "3.12")
                self.assertTrue(any("requires missing " + name in gap for gap in gaps), gaps)

    def test_linux_only_pins_do_not_count_as_windows_dependencies(self):
        requirements = read_lock_requirements("requirements-dev.txt")
        for name in ("pefile", "pywin32-ctypes", "colorama"):
            with self.subTest(linux_only=name):
                incompatible = dict(requirements)
                incompatible[name] = Requirement(f"{name}{requirements[name].specifier}; sys_platform == 'linux'")
                gaps = windows_dependency_gaps(incompatible, "3.13")
                self.assertTrue(any("requires missing " + name in gap for gap in gaps), gaps)

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
