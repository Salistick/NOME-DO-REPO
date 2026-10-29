import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from single_instance import AlreadyRunningError, SingleInstanceLock


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)

    def test_locks_same_directory_and_releases_on_exception(self):
        first, second = SingleInstanceLock(self.path), SingleInstanceLock(self.path / ".")
        with self.assertRaisesRegex(ValueError, "test"):
            with first:
                with self.assertRaises(AlreadyRunningError):
                    second.acquire()
                raise ValueError("test")
        with second:
            self.assertTrue(second.path.exists())

    def test_different_directories_are_independent(self):
        with SingleInstanceLock(self.path / "one"), SingleInstanceLock(self.path / "two"):
            pass

    def test_other_process_cannot_acquire_live_lock(self):
        code = (
            "import sys; from single_instance import SingleInstanceLock, AlreadyRunningError; "
            "from pathlib import Path\n"
            "try: SingleInstanceLock(Path(sys.argv[1])).acquire()\n"
            "except AlreadyRunningError: sys.exit(23)\n"
            "sys.exit(0)\n"
        )
        with SingleInstanceLock(self.path):
            result = subprocess.run(
                [sys.executable, "-c", code, str(self.path)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 23, result.stderr.decode(errors="replace"))

    def test_os_releases_lock_when_process_crashes(self):
        code = (
            "import os, sys; from single_instance import SingleInstanceLock; from pathlib import Path; "
            "held=SingleInstanceLock(Path(sys.argv[1])); held.acquire(); os._exit(17)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.path)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 17)
        with SingleInstanceLock(self.path):
            pass
