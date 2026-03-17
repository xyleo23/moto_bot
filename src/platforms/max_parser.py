"""Parse MAX platform-api updates into normalized events."""
from src.platforms.base import (
    IncomingMessage,
    IncomingCallback,
    IncomingContact,
    IncomingLocation,
    IncomingPhoto,
)


def _get_user_id(obj: dict) -> int | None:
    """Extract user id from various possible structures."""
    if not obj:
        return None
    # Common patterns: from.id, user_id, user.id
    from_obj = obj.get("from") or obj.get("user")
    if from_obj:
        uid = from_obj.get("id") or from_obj.get("user_id")
        if uid is not None:
            return int(uid) if isinstance(uid, str) and uid.isdigit() else uid
    uid = obj.get("user_id") or obj.get("from_id")
    if uid is not None:
        return int(uid) if isinstance(uid, str) and uid.isdigit() else uid
    return None


def _get_username(obj: dict) -> str | None:
    from_obj = obj.get("from") or obj.get("user") or {}
    return from_obj.get("username") or from_obj.get("nickname")


def _get_first_name(obj: dict) -> str | None:
    from_obj = obj.get("from") or obj.get("user") or {}
    return from_obj.get("first_name") or from_obj.get("name")


def _extract_photo_file_id(msg: dict) -> str | None:
    """Try to extract a photo file_id from a MAX message dict.

    MAX may deliver photos as:
    - ``message.photo`` (direct dict with ``token`` / ``file_id``)
    - ``message.attachments[].type == "image"`` with ``payload.token`` or ``payload.file_id``
    Returns the first found token/file_id string, or ``None``.
    """
    # Direct photo field
    photo = msg.get("photo")
    if isinstance(photo, dict):
        fid = photo.get("token") or photo.get("file_id") or photo.get("id")
        if fid:
            return str(fid)

    # Attachments list
    attachments = msg.get("attachments") or []
    if isinstance(attachments, list):
        for att in attachments:
            if not isinstance(att, dict):
                continue
            att_type = att.get("type", "")
            if att_type in ("image", "photo"):
                payload = att.get("payload") or {}
                fid = (
                    payload.get("token")
                    or payload.get("file_id")
                    or payload.get("id")
                    or att.get("token")
                    or att.get("file_id")
                )
                if fid:
                    return str(fid)
    return None


def parse_updates(response: dict) -> list[IncomingMessage | IncomingCallback | IncomingContact | IncomingLocation | IncomingPhoto]:
    """Parse MAX /updates response. Returns list of parsed events."""
    raw_updates = response.get("updates") or response.get("result") or []
    if isinstance(raw_updates, dict):
        raw_updates = [raw_updates]
    result = []
    for raw in raw_updates:
        if not isinstance(raw, dict):
            continue
        ev = parse_update(raw)
        if ev:
            result.append(ev)
    return result


def parse_update(raw: dict) -> IncomingMessage | IncomingCallback | IncomingContact | IncomingLocation | IncomingPhoto | None:
    """Parse single raw MAX update. Returns event or None."""
    # If update has nested message/callback_query
    cq = raw.get("callback_query") or raw.get("callback")
    if cq:
        user_id = _get_user_id(cq)
        if user_id is None:
            return None
        msg = cq.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id") or msg.get("chat_id") or user_id)
        msg_id = str(msg.get("message_id") or msg.get("id") or "")
        data = cq.get("data") or cq.get("payload") or ""
        return IncomingCallback(
            platform="max",
            chat_id=chat_id,
            user_id=user_id,
            message_id=msg_id,
            callback_data=data,
            raw=raw,
        )

    # Message
    msg = raw.get("message") or raw
    if not isinstance(msg, dict):
        return None

    user_id = _get_user_id(msg)
    if user_id is None:
        return None

    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or chat.get("chat_id") or user_id)

    # Contact
    contact = msg.get("contact")
    if contact:
        phone = contact.get("phone_number", "")
        if not phone and isinstance(contact, str):
            phone = contact
        return IncomingContact(
            platform="max",
            chat_id=chat_id,
            user_id=user_id,
            phone_number=str(phone),
            raw=raw,
        )

    # Location
    loc = msg.get("location") or msg.get("geo")
    if loc:
        lat = float(loc.get("latitude") or loc.get("lat") or 0)
        lon = float(loc.get("longitude") or loc.get("lon") or 0)
        return IncomingLocation(
            platform="max",
            chat_id=chat_id,
            user_id=user_id,
            latitude=lat,
            longitude=lon,
            raw=raw,
        )

    # Photo — MAX may deliver via attachments[].type == "image" or message.photo
    photo_file_id = _extract_photo_file_id(msg)
    if photo_file_id:
        caption = msg.get("text") or msg.get("caption") or None
        return IncomingPhoto(
            platform="max",
            chat_id=chat_id,
            user_id=user_id,
            file_id=photo_file_id,
            caption=str(caption) if caption else None,
            raw=raw,
        )

    # Text message
    text = msg.get("text") or msg.get("message") or ""
    return IncomingMessage(
        platform="max",
        chat_id=chat_id,
        user_id=user_id,
        username=_get_username(msg),
        first_name=_get_first_name(msg),
        text=str(text) if text else None,
        raw=raw,
    )
