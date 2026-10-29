"""Preserve dotenv syntax while moving secret values into current-user DPAPI.

Each secret assignment becomes a reference to a protected binding. Keeping the
assignment position preserves dotenv interpolation, even with duplicate keys.
"""

import argparse
import base64
import io
import os
import re
import secrets
from pathlib import Path

from dotenv.parser import parse_stream
from dotenv.variables import parse_variables

from persistence import atomic_write_bytes
from secure_storage import SecureStorageError, secure_read_json, secure_write_json

_REFERENCE_PREFIX = "__TTSLIVE_PROTECTED_"
_REFERENCE_RE = re.compile(r"\$\{__TTSLIVE_PROTECTED_([a-f0-9]{24})\}")
_SECRET_NAME_RE = re.compile(
    r"(?:^|_)(?:SECRET(?:_ACCESS_KEY|_KEY)?|PASSWORD|PRIVATE_KEY|API_KEY|TOKEN|ACCESS_KEY_ID)$"
)


class SecretConfigError(SecureStorageError):
    pass


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME_RE.search(name.upper()))


def _validate_store(data: object) -> dict:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise SecretConfigError("Formato das configuracoes protegidas invalido; recupere o backup protegido.")
    values, bindings = data.get("values"), data.get("bindings")
    if not isinstance(values, dict) or not isinstance(bindings, dict):
        raise SecretConfigError("Configuracoes protegidas incompletas; recupere o backup protegido.")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in values.items()):
        raise SecretConfigError("Valores de configuracao protegida invalidos.")
    for binding_id, entry in bindings.items():
        if (
            not isinstance(binding_id, str) or not re.fullmatch(r"[a-f0-9]{24}", binding_id)
            or not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
            or not isinstance(entry.get("value"), str)
        ):
            raise SecretConfigError("Referencia protegida invalida; recupere o backup protegido.")
    return data


def _interpolate(value: str, environment: dict) -> str:
    return "".join(atom.resolve(environment) for atom in parse_variables(value))


def _replace_secret_assignment(original: str, name: str, binding_id: str) -> str:
    key = re.escape(name)
    assignment = re.search(rf"(?m)^[ \t]*(?:export[ \t]+)?(?:'{key}'|{key})[ \t]*=[ \t]*", original)
    if assignment is None:
        raise SecretConfigError("Atribuicao secreta nao reconhecida; o .env original foi preservado.")
    ending = re.search(r"(\r\n|\n|\r)$", original)
    newline = ending.group() if ending else ""
    return original[:assignment.end()] + "${" + _REFERENCE_PREFIX + binding_id + "}" + newline


def load_secret_environment(env_path: Path, secret_path: Path, backup_path: Path) -> Path | None:
    """Load/migrate a dotenv file, without writing secret plaintext or backups.

    The encrypted backup contains the exact original bytes and the resulting
    protected configuration. Its recovery restores DPAPI state, not plaintext.
    """
    env_path, secret_path, backup_path = Path(env_path), Path(secret_path), Path(backup_path)
    empty = {"version": 1, "values": {}, "bindings": {}}
    stored = _validate_store(secure_read_json(secret_path, default=empty))
    values = dict(stored["values"])
    try:
        original_bytes = env_path.read_bytes()
    except FileNotFoundError:
        os.environ.update(values)
        return None
    try:
        text = original_bytes.decode("utf-8-sig")
    except UnicodeError as exc:
        raise SecretConfigError("O .env precisa estar em UTF-8; o arquivo original foi preservado.") from exc
    original_bindings = list(parse_stream(io.StringIO(text)))
    # dotenv opens files in text mode: actual CRLF inside quoted values becomes LF.
    # Keep original bindings for byte-preserving edits and parse normalized values
    # separately so escaped "\\r\\n" still retains its intended literal meaning.
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    semantic_bindings = list(parse_stream(io.StringIO(normalized_text)))
    if (
        len(original_bindings) != len(semantic_bindings)
        or any(binding.error for binding in original_bindings + semantic_bindings)
    ):
        raise SecretConfigError("Formato .env invalido; corrija a sintaxe antes de migrar os segredos.")

    environment = {**os.environ, **values}
    resolved = {}
    kept_bindings = {}
    replacements = []
    changed = False
    for binding, semantic_binding in zip(original_bindings, semantic_bindings):
        key, value = semantic_binding.key, semantic_binding.value
        original = binding.original.string
        if key is None or value is None:
            replacements.append(original)
            continue
        if not is_secret_name(key):
            resolved[key] = _interpolate(value, {**environment, **resolved})
            replacements.append(original)
            continue
        reference = _REFERENCE_RE.fullmatch(value)
        if reference:
            binding_id = reference.group(1)
            entry = stored["bindings"].get(binding_id)
            if entry is None or entry["name"] != key:
                raise SecretConfigError(
                    "O .env referencia um segredo indisponivel. Use o mesmo perfil Windows "
                    "e recupere data/env_original.bin; nenhum valor foi substituido por vazio."
                )
            effective_value = entry["value"]
            replacements.append(original)
        else:
            effective_value = _interpolate(value, {**environment, **resolved})
            binding_id = secrets.token_hex(12)
            replacements.append(_replace_secret_assignment(original, key, binding_id))
            changed = True
        kept_bindings[binding_id] = {"name": key, "value": effective_value}
        values[key] = effective_value
        resolved[key] = effective_value

    updated = {"version": 1, "values": values, "bindings": kept_bindings}
    if changed:
        backup = {
            "version": 1, "env_bytes_base64": base64.b64encode(original_bytes).decode("ascii"),
            "protected_config": updated,
        }
        # If interrupted, the original .env or complete protected configuration remains.
        secure_write_json(backup_path, backup)
        secure_write_json(secret_path, updated)
        redacted = "".join(replacements).encode("utf-8")
        if original_bytes.startswith(b"\xef\xbb\xbf"):
            redacted = b"\xef\xbb\xbf" + redacted
        atomic_write_bytes(env_path, redacted)
    elif updated != stored:
        secure_write_json(secret_path, updated)

    os.environ.update(values)
    os.environ.update({key: value for key, value in resolved.items() if value is not None})
    return env_path


def recover_environment_secrets(secret_path: Path, backup_path: Path) -> None:
    backup = secure_read_json(Path(backup_path), migrate_legacy=False)
    if not isinstance(backup, dict):
        raise SecretConfigError("Backup protegido do .env invalido.")
    restored = _validate_store(backup.get("protected_config"))
    secure_write_json(Path(secret_path), restored)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Recupera segredos do .env sem gravar valores em claro.")
    parser.add_argument("command", choices=["recover"])
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        recover_environment_secrets(
            args.data_dir / "platform_secrets.bin", args.data_dir / "env_original.bin"
        )
    except (OSError, ValueError, SecureStorageError) as exc:
        parser.exit(1, f"Recuperacao nao concluida: {exc}\n")
    print("Segredos do .env recuperados no armazenamento protegido.")


if __name__ == "__main__":
    _main()
