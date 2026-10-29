"""Small atomic file replacements shared by settings and protected stores."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    atomic_write_bytes(path, raw)
