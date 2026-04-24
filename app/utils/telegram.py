from __future__ import annotations

from collections.abc import Iterable


def is_command_message(text: str | None) -> bool:
    text = (text or "").strip()
    return text.startswith("/")


def is_digest_trigger(text: str | None, bot_username: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith("/digest"):
        return True
    bot_username = (bot_username or "").strip().lstrip("@").lower()
    return bool(bot_username and f"@{bot_username}" in lowered and "digest" in lowered)


def message_type_from_payload(payload: object | None) -> str:
    if payload is None:
        return "text"
    payload_type = type(payload).__name__
    if payload_type == "Voice":
        return "voice"
    if payload_type == "Audio":
        return "audio"
    if payload_type == "VideoNote":
        return "video_note"
    return payload_type.lower()


def message_to_dict(message: object) -> dict:
    return {
        "telegram_message_id": getattr(message, "message_id", None),
        "date": getattr(message, "date", None).isoformat() if getattr(message, "date", None) else None,
        "text": getattr(message, "text", None) or getattr(message, "caption", None),
        "message_type": "text",
    }


def has_media(message: object) -> bool:
    return any(getattr(message, attr, None) for attr in ("voice", "audio", "video_note"))


def get_message_text(message: object) -> str | None:
    return getattr(message, "text", None) or getattr(message, "caption", None)


def iter_entities_text(text: str, entities: Iterable[object]) -> list[str]:
    values: list[str] = []
    for entity in entities:
        if getattr(entity, "type", None) == "mention":
            offset = getattr(entity, "offset", 0)
            length = getattr(entity, "length", 0)
            values.append(text[offset : offset + length])
    return values
