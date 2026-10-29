"""Windows current-user DPAPI storage, with explicit migration and recovery.

This module intentionally has no application/configuration imports. Failures never
fall back to plaintext. The byte functions also read the original Polly DPAPI blobs.
"""

import argparse
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from persistence import atomic_write_bytes

SECURE_MAGIC = b"TTSLIVE-DPAPI-JSON-v1\x00"
_INNER_MAGIC = b"TTSLIVE-JSON-v1\x00"
_UI_FORBIDDEN = 0x01


class SecureStorageError(RuntimeError):
    """The original file is retained when protection/decryption cannot complete."""


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.c_void_p)]


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise SecureStorageError("A protecao local de segredos requer Windows; nenhum arquivo em claro foi gravado.")
    if not isinstance(data, bytes):
        raise TypeError("DPAPI espera bytes.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p if decrypt else ctypes.c_wchar_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.POINTER(_DATA_BLOB),
    ]
    function.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(data)
    source = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    destination = _DATA_BLOB()
    description = None if decrypt else "TTS Live local secrets"
    if not function(
        ctypes.byref(source), description, None, None, None, _UI_FORBIDDEN,
        ctypes.byref(destination),
    ):
        action = "abrir" if decrypt else "proteger"
        raise SecureStorageError(
            f"Windows nao conseguiu {action} os segredos (codigo {ctypes.get_last_error()}). "
            "Use o mesmo usuario/perfil Windows ou recupere um backup protegido."
        )
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        if decrypt and destination.pbData:
            ctypes.memset(destination.pbData, 0, destination.cbData)
        kernel32.LocalFree(destination.pbData)
        ctypes.memset(buffer, 0, len(buffer))


def protect_secret_bytes(data: bytes) -> bytes:
    return _dpapi(data, decrypt=False)


def unprotect_secret_bytes(data: bytes) -> bytes:
    return _dpapi(data, decrypt=True)


def migration_backup_path(path: Path) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".migration.bak")


def _encode_json(data: Any) -> bytes:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    payload = _INNER_MAGIC + hashlib.sha256(raw).digest() + raw
    return SECURE_MAGIC + protect_secret_bytes(payload)


def _decode_json(raw: bytes) -> Any:
    if not raw.startswith(SECURE_MAGIC):
        raise SecureStorageError("O arquivo nao possui o formato protegido esperado.")
    payload = unprotect_secret_bytes(raw[len(SECURE_MAGIC):])
    prefix_length = len(_INNER_MAGIC)
    if not payload.startswith(_INNER_MAGIC) or len(payload) < prefix_length + 32:
        raise SecureStorageError("Formato interno do arquivo protegido invalido.")
    expected = payload[prefix_length:prefix_length + 32]
    content = payload[prefix_length + 32:]
    if not hmac.compare_digest(expected, hashlib.sha256(content).digest()):
        raise SecureStorageError("A integridade do arquivo protegido falhou; recupere um backup protegido.")
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise SecureStorageError("Conteudo do arquivo protegido invalido.") from exc


def secure_write_json(path: Path, data: Any) -> None:
    """Encrypt completely before creating a temporary file on disk."""
    encrypted = _encode_json(data)
    atomic_write_bytes(Path(path), encrypted)


def secure_read_json(path: Path, default: Any = None, *, migrate_legacy: bool = True) -> Any:
    """Read protected JSON; migrate valid legacy JSON with an encrypted backup.

    A migration failure keeps the legacy original and propagates the error. An
    inaccessible protected file is never treated as an empty/new store.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return default
    if raw.startswith(SECURE_MAGIC):
        return _decode_json(raw)
    if not migrate_legacy:
        raise SecureStorageError("O arquivo precisa estar protegido pelo Windows.")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ValueError("Cache legado invalido; o arquivo original foi preservado.") from exc
    encrypted = _encode_json(data)
    # Verify readability before replacing the original, then retain only encrypted backups.
    _decode_json(encrypted)
    atomic_write_bytes(migration_backup_path(path), encrypted)
    atomic_write_bytes(path, encrypted)
    return data


def recover_secure_json(path: Path, backup_path: Path | None = None) -> None:
    """Explicit recovery only: never silently substitute stale OAuth tokens."""
    path = Path(path)
    backup = Path(backup_path) if backup_path is not None else migration_backup_path(path)
    raw = backup.read_bytes()
    _decode_json(raw)
    atomic_write_bytes(path, raw)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Recupera um cache de um backup DPAPI, sem exibir valores.")
    parser.add_argument("command", choices=["recover"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        recover_secure_json(args.path, args.backup)
    except (OSError, ValueError, SecureStorageError) as exc:
        parser.exit(1, f"Recuperacao nao concluida: {exc}\n")
    print("Cache recuperado a partir do backup protegido.")


if __name__ == "__main__":
    _main()
