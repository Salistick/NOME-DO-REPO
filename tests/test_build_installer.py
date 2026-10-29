import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPILER = (os.environ.get("INNO_COMPILER") or shutil.which("ISCC.exe") or
            str(ROOT / "build_validation/tools/inno-6.7.4/ISCC.exe"))


def preprocess_installer(directory, *, validation, include_directory=True):
    output = directory / ("validation.iss" if validation else "production.iss")
    wrapper = directory / ("validation-wrapper.iss" if validation else "production-wrapper.iss")
    lines = [f'#define TTSLiveExePath "{sys.executable}"']
    if validation:
        lines.append("#define TTSLiveValidationBuild 1")
        if include_directory:
            lines.append(f'#define TTSLiveValidationDirectory "{directory / "installed"}"')
    lines.extend(["[Setup]", f"SourceDir={ROOT}", f'#include "{ROOT / "installer.iss"}"',
                  f'#expr SaveToFile("{output}")'])
    wrapper.write_text("\n".join(lines), encoding="utf-8")
    process = subprocess.run([COMPILER, "/Q", "/O-", str(wrapper)],
                             capture_output=True, text=True, timeout=30)
    if process.returncode:
        raise RuntimeError(process.stdout + process.stderr)
    return output.read_text(encoding="utf-8-sig")


def section(text, name):
    lines = []
    active = False
    for line in text.splitlines():
        if line.startswith("["):
            active = line == f"[{name}]"
        elif active:
            lines.append(line)
    return "\n".join(lines).strip()


@unittest.skipUnless(sys.platform == "win32" and Path(COMPILER).is_file(), "Inno compiler required")
class InstallerIsolationTests(unittest.TestCase):
    def test_preprocessed_validation_mode_cannot_register_launch_or_create_shortcuts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            validation = preprocess_installer(path, validation=True)
            production = preprocess_installer(path, validation=False)
        setup = section(validation, "Setup")
        self.assertIn("CreateUninstallRegKey=no", setup)
        self.assertIn("Uninstallable=yes", setup)
        self.assertIn("CloseApplications=no", setup)
        self.assertIn("RestartApplications=no", setup)
        self.assertIn("TTS Live - Isolated Validation", setup)
        self.assertNotIn("2E3AF7D8-A9F3-4D0C-B91F-5600A6F58C11", setup)
        for forbidden in ("Icons", "Run", "Registry", "UninstallRun"):
            self.assertNotIn(f"[{forbidden}]", validation)
        for shared in ("Files", "UninstallDelete"):
            self.assertEqual(section(validation, shared), section(production, shared))
        self.assertIn("[Icons]", production)
        self.assertIn("[Run]", production)

    def test_validation_build_refuses_an_implicit_install_directory(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
            RuntimeError, "Validation builds require an explicit TTSLiveValidationDirectory"
        ):
            preprocess_installer(Path(temporary), validation=True, include_directory=False)


if __name__ == "__main__":
    unittest.main()
