ADMIN_EXACT_COMMANDS = {
    "!lives",
    "!ytoff",
    "!mm",
    "!rate",
    "!time",
    "!pause",
    "!stop",
    "!resume",
    "!len",
    "!modosub",
    "!config",
}


def resolve_command_type(command: str) -> str | None:
    command = (command or "").strip().lower()

    if command == "!ms":
        return "public_tts"

    if command in ADMIN_EXACT_COMMANDS:
        return "admin"

    if command.startswith("!live") and command != "!lives":
        return "admin"

    if command.startswith("!clive"):
        return "admin"

    return None


def normalized_role(payload: dict) -> str:
    role = str((payload or {}).get("role") or "viewer").strip().lower()

    if role in {"owner", "streamer"}:
        return "broadcaster"
    if role in {"mod"}:
        return "moderator"
    if role in {"member", "sponsor", "sub"}:
        return "subscriber"
    if role in {"broadcaster", "moderator", "subscriber", "vip"}:
        return role
    return "viewer"


def payload_bool(payload: dict, key: str) -> bool:
    value = (payload or {}).get(key)

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "sim", "on"}

    return bool(value)


def is_admin(payload: dict) -> bool:
    role = normalized_role(payload)

    return (
        role in {"moderator", "broadcaster"}
        or payload_bool(payload, "is_mod")
        or payload_bool(payload, "is_broadcaster")
    )


def can_use_sub_only(payload: dict) -> bool:
    role = normalized_role(payload)

    return (
        role in {"subscriber", "moderator", "broadcaster"}
        or payload_bool(payload, "is_sub")
        or payload_bool(payload, "is_mod")
        or payload_bool(payload, "is_broadcaster")
    )
