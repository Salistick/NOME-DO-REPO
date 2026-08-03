from __future__ import annotations

import os
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BUILD_ASSETS_DIR = ROOT_DIR / "build_assets"


def _normalize_display_version(raw_version: str) -> str:
    version = (raw_version or "").strip()
    return version or "dev"


def _parse_numeric_version(display_version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", display_version)[:4]]
    parts = [min(max(part, 0), 65535) for part in parts]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def _write_version_info(display_version: str) -> None:
    numeric_version = _parse_numeric_version(display_version)
    version_info = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric_version},
    prodvers={numeric_version},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Salistick'),
          StringStruct('FileDescription', 'TTS Live'),
          StringStruct('FileVersion', {display_version!r}),
          StringStruct('InternalName', 'TTSLive'),
          StringStruct('OriginalFilename', 'TTSLive.exe'),
          StringStruct('ProductName', 'TTS Live'),
          StringStruct('ProductVersion', {display_version!r}),
        ],
      ),
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""
    (BUILD_ASSETS_DIR / "version_info.txt").write_text(version_info, encoding="utf-8")


def main() -> None:
    display_version = _normalize_display_version(os.environ.get("TTSLIVE_VERSION", "dev"))
    BUILD_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_ASSETS_DIR / "version.txt").write_text(f"{display_version}\n", encoding="utf-8")
    _write_version_info(display_version)


if __name__ == "__main__":
    main()
