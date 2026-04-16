import os
import sys
from pathlib import Path


DEFAULT_APP_VERSION = "dev"
VERSION_FILE_NAME = "version.txt"


def _candidate_version_paths() -> list[Path]:
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / VERSION_FILE_NAME)
        candidates.append(Path(sys.executable).resolve().parent / VERSION_FILE_NAME)

    candidates.append(Path(__file__).resolve().parent / VERSION_FILE_NAME)
    return candidates


def get_app_version() -> str:
    for path in _candidate_version_paths():
        try:
            if path.exists():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except Exception:
            continue

    env_value = os.getenv("TTSLIVE_VERSION", "").strip()
    if env_value:
        return env_value

    return DEFAULT_APP_VERSION


CURRENT_APP_VERSION = get_app_version()

