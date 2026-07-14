import re
import time
from typing import Any

from .kick_chat_event import KickChatEvent


_KICK_EMOTE_RE = re.compile(r"\[emote:[^:\]\s]+:([^\]]+)\]")


def map_kick_pusher_chat_message_event(
    payload: dict[str, Any],
    channel_slug: str = "",
    broadcaster_user_id: str = "",
) -> KickChatEvent | None:
    if not isinstance(payload, dict):
        return None

    message = _first_dict(
        payload.get("message"),
        _nested(payload, "data", "message"),
        _nested(payload, "payload", "message"),
        payload,
    )
    if not message:
        return None

    sender = _first_dict(
        payload.get("sender"),
        payload.get("user"),
        message.get("sender"),
        message.get("user"),
        payload.get("profile"),
    )
    broadcaster = _first_dict(
        payload.get("broadcaster"),
        payload.get("channel"),
        message.get("broadcaster"),
    )

    content = _clean_kick_content(
        _extract_message_content(message) or _extract_message_content(payload)
    )
    if not content:
        return None

    username = _clean_text(
        _pick_first(
            sender.get("username"),
            sender.get("slug"),
            sender.get("channel_slug"),
            message.get("username"),
            payload.get("username"),
            payload.get("sender_username"),
            "usuario",
        )
    )
    display_name = _clean_text(
        _pick_first(
            sender.get("display_name"),
            sender.get("displayName"),
            sender.get("name"),
            username,
        )
    )
    channel = _clean_text(
        _pick_first(
            channel_slug,
            broadcaster.get("channel_slug"),
            broadcaster.get("slug"),
            broadcaster.get("username"),
            payload.get("channel_slug"),
            payload.get("channel"),
        )
    )
    message_id = _clean_text(
        _pick_first(
            message.get("id"),
            message.get("message_id"),
            payload.get("message_id"),
            payload.get("id"),
            "",
        )
    )

    badges = _collect_badges(sender, message, payload)
    badge_types = _badge_types(badges)
    sender_user_id = _clean_text(
        _pick_first(sender.get("user_id"), sender.get("id"), payload.get("user_id"))
    )
    resolved_broadcaster_user_id = _clean_text(
        _pick_first(
            broadcaster_user_id,
            broadcaster.get("user_id"),
            broadcaster.get("broadcaster_user_id"),
            payload.get("broadcaster_user_id"),
        )
    )

    is_broadcaster = bool(
        sender_user_id
        and resolved_broadcaster_user_id
        and sender_user_id == resolved_broadcaster_user_id
    )
    if not is_broadcaster and channel and username:
        is_broadcaster = username.strip().lower() == channel.strip().lower()

    is_mod = (
        _has_any_badge_type(badge_types, {"moderator", "mod"})
        or _has_truthy_field(sender, "is_moderator", "moderator", "isMod", "is_mod")
        or _has_truthy_field(message, "is_moderator", "moderator", "isMod", "is_mod")
        or _has_truthy_field(payload, "is_moderator", "moderator", "isMod", "is_mod")
    )
    is_sub = (
        _has_any_badge_type(badge_types, {"subscriber", "sub", "founder"})
        or _has_truthy_field(sender, "is_subscriber", "subscriber", "isSubscriber", "is_sub")
        or _has_truthy_field(message, "is_subscriber", "subscriber", "isSubscriber", "is_sub")
        or _has_truthy_field(payload, "is_subscriber", "subscriber", "isSubscriber", "is_sub")
        or _has_membership_data(sender)
        or _has_membership_data(message)
        or _has_membership_data(payload)
    )

    role = "viewer"
    if is_broadcaster:
        role = "broadcaster"
    elif is_mod:
        role = "moderator"
    elif is_sub:
        role = "subscriber"

    return KickChatEvent(
        channel=channel,
        username=username,
        display_name=display_name or username,
        message=content,
        message_id=message_id,
        role=role,
        is_mod=is_mod,
        is_sub=is_sub,
        is_broadcaster=is_broadcaster,
        raw=payload,
    )


def build_fallback_message_id(channel: str, username: str, content: str) -> str:
    return f"kick-ws:{channel}:{username}:{content}:{int(time.time() // 5)}"


def _extract_message_content(value: Any, depth: int = 0) -> str:
    if value is None or depth > 4:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_extract_message_content(item, depth + 1) for item in value)
    if not isinstance(value, dict):
        return ""

    for key in ("content", "text", "body", "raw", "raw_content", "comment"):
        current = value.get(key)
        if isinstance(current, str) and current.strip():
            return current
        if isinstance(current, list):
            text = _extract_message_content(current, depth + 1)
            if text.strip():
                return text

    for key in ("fragments", "parts", "messages"):
        text = _extract_message_content(value.get(key), depth + 1)
        if text.strip():
            return text

    message = value.get("message")
    if isinstance(message, str) and message.strip():
        return message
    if isinstance(message, (dict, list)):
        text = _extract_message_content(message, depth + 1)
        if text.strip():
            return text

    if value.get("type") == "emote" and isinstance(value.get("name"), str):
        return f":{value['name']}:"
    for key in ("name", "alt"):
        current = value.get(key)
        if isinstance(current, str) and current.strip():
            return current
    return ""


def _collect_badges(*sources: dict[str, Any]) -> list[Any]:
    badges: list[Any] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        identity = source.get("identity") if isinstance(source.get("identity"), dict) else {}
        profile = source.get("profile") if isinstance(source.get("profile"), dict) else {}
        membership = source.get("membership") if isinstance(source.get("membership"), dict) else {}
        subscription = source.get("subscription") if isinstance(source.get("subscription"), dict) else {}
        for current in (
            source.get("badges"),
            source.get("chatbadges"),
            source.get("badge_collection"),
            source.get("badgeCollection"),
            identity.get("badges"),
            identity.get("badge_info"),
            profile.get("badges"),
            membership.get("badges"),
            subscription.get("badges"),
            source.get("roles"),
        ):
            if isinstance(current, list):
                badges.extend(current)
            elif isinstance(current, (str, dict)):
                badges.append(current)
    return badges


def _badge_types(badges: list[Any]) -> set[str]:
    values: set[str] = set()
    for badge in badges:
        if isinstance(badge, str):
            cleaned = badge.strip().lower()
            if cleaned:
                values.add(cleaned)
            continue
        if not isinstance(badge, dict):
            continue
        for key in ("type", "text", "label", "name", "title", "slug", "id", "role"):
            value = badge.get(key)
            if isinstance(value, str) and value.strip():
                values.add(value.strip().lower())
        for key, value in badge.items():
            if _truthy(value):
                cleaned = str(key or "").strip().lower()
                if cleaned:
                    values.add(cleaned)
    return values


def _has_any_badge_type(badge_types: set[str], wanted: set[str]) -> bool:
    for item in badge_types:
        if item in wanted:
            return True
        if any(want in item for want in wanted):
            return True
    return False


def _has_truthy_field(source: dict[str, Any], *keys: str) -> bool:
    if not isinstance(source, dict):
        return False

    for key in keys:
        if _truthy(source.get(key)):
            return True

    identity = source.get("identity") if isinstance(source.get("identity"), dict) else {}
    badge_info = identity.get("badge_info") if isinstance(identity.get("badge_info"), dict) else {}
    for key in keys:
        if _truthy(badge_info.get(key)):
            return True

    roles = source.get("roles")
    if isinstance(roles, str):
        return any(key.lower() in roles.lower() for key in keys)
    if isinstance(roles, list):
        lowered = {str(role or "").strip().lower() for role in roles}
        return any(key.lower() in lowered for key in keys)

    return False


def _has_membership_data(source: dict[str, Any]) -> bool:
    if not isinstance(source, dict):
        return False

    for key in ("membership", "subscription", "subscriber", "subscriptions"):
        value = source.get(key)
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, list) and value:
            return True
        if isinstance(value, str) and value.strip().lower() not in {"0", "false", "no", "none", "null"}:
            return True
        if isinstance(value, bool) and value:
            return True

    return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "sim", "on", "moderator", "mod", "subscriber", "sub"}
    return bool(value)


def _nested(source: dict[str, Any], *keys: str) -> Any:
    current: Any = source
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _pick_first(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value
            continue
        return value
    return ""


def _clean_kick_content(value: Any) -> str:
    text = _clean_text(value)
    text = _KICK_EMOTE_RE.sub(lambda match: f" {match.group(1)} ", text)
    return " ".join(text.split())


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())
