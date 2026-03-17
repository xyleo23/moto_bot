"""Parse MAX platform-api updates into normalized events.

Real MAX API payload structure (reverse-engineered, Feb 2026):
- update_type: "message_created" | "message_callback" | "user_added"
- Text: update['message']['body']['text']
- Sender: update['message']['sender']['user_id']  (NOT 'from')
- chat_id: update['message']['recipient']['chat_id'] or ['recipient']['user_id']
- Callback user: update['callback']['user']['user_id']
- Callback data: update['callback']['payload']
"""
from src.platforms.base import (
    IncomingMessage,
    IncomingCallback,
    IncomingContact,
    IncomingLocation,
    IncomingPhoto,
)


def _extract_photo_file_id(body: dict) -> str | None:
    """Extract photo token from message body attachments."""
    attachments = body.get("attachments") or []
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


def parse_updates(response: dict) -> list:
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


def parse_update(raw: dict):
    """Parse single raw MAX update. Returns event or None.

    Real MAX update structure:
    {
        "update_type": "message_created" | "message_callback" | "user_added",
        "timestamp": <ms>,
        "user_locale": "ru",
        "message": { "sender": {...}, "recipient": {...}, "body": {"text": ..., "attachments": [...]} },
        "callback": { "user": {...}, "payload": "...", "callback_id": "..." }  # only for message_callback
    }
    """
    update_type = raw.get("update_type", "")

    # ── Callback (button press) ────────────────────────────────────────────────
    if update_type == "message_callback" or raw.get("callback"):
        cb = raw.get("callback") or {}
        cb_user = cb.get("user") or {}
        user_id = cb_user.get("user_id")
        if user_id is None:
            return None
        user_id = int(user_id)

        msg = raw.get("message") or {}
        recipient = msg.get("recipient") or {}
        # Use recipient.chat_id for dialogs (same as message_created).
        chat_type = recipient.get("chat_type", "dialog")
        if chat_type == "dialog" and recipient.get("chat_id") is not None:
            chat_id = str(recipient["chat_id"])
            raw["_max_use_chat_id"] = True
        else:
            chat_id = str(recipient.get("chat_id") or user_id)

        body = msg.get("body") or {}
        msg_id = str(body.get("mid") or "")
        data = str(cb.get("payload") or "")

        return IncomingCallback(
            platform="max",
            chat_id=chat_id,
            user_id=user_id,
            message_id=msg_id,
            callback_data=data,
            raw=raw,
        )

    # ── user_added (user opens chat / unblocks bot) ────────────────────────────
    if update_type == "user_added":
        user_obj = raw.get("user") or {}
        user_id = user_obj.get("user_id")
        if user_id is None:
            return None
        user_id = int(user_id)
        chat_id = str(user_id)  # reply to the user who opened the chat
        first_name = user_obj.get("first_name") or user_obj.get("name")
        return IncomingMessage(
            platform="max",
            chat_id=chat_id,
            user_id=user_id,
            username=user_obj.get("username"),
            first_name=first_name,
            text="/start",
            raw=raw,
        )

    # ── message_created (text / media message) ────────────────────────────────
    msg = raw.get("message")
    if not isinstance(msg, dict):
        return None

    sender = msg.get("sender") or {}
    user_id = sender.get("user_id")
    if user_id is None:
        return None
    user_id = int(user_id)

    # Skip messages sent by the bot itself
    if sender.get("is_bot"):
        return None

    # Reply target: use recipient.chat_id (dialog id) for POST /messages?chat_id=...
    # API returns "Invalid chatId: 0" when using user_id for dialogs.
    recipient = msg.get("recipient") or {}
    chat_id = str(recipient.get("chat_id") or user_id)
    if recipient.get("chat_id") is not None:
        raw["_max_use_chat_id"] = True

    body = msg.get("body") or {}

    # Contact attachment
    attachments = body.get("attachments") or []
    for att in (attachments if isinstance(attachments, list) else []):
        if not isinstance(att, dict):
            continue
        if att.get("type") == "contact":
            payload = att.get("payload") or {}
            # Try multiple locations: nested payload, top-level attachment, VCF
            phone = (
                payload.get("phone_number")
                or payload.get("phone")
                or att.get("phone_number")
                or att.get("phone")
                or ""
            )
            if not phone:
                import re as _re
                vcf = payload.get("vcf") or att.get("vcf") or ""
                if vcf:
                    m = _re.search(r"TEL[^:]*:([+\d\s\-().]+)", str(vcf))
                    if m:
                        phone = _re.sub(r"[\s\-().]", "", m.group(1))
            return IncomingContact(
                platform="max",
                chat_id=chat_id,
                user_id=user_id,
                phone_number=str(phone).strip(),
                raw=raw,
            )
        if att.get("type") in ("location", "geo"):
            payload = att.get("payload") or {}
            lat = float(payload.get("latitude") or payload.get("lat") or 0)
            lon = float(payload.get("longitude") or payload.get("lon") or 0)
            return IncomingLocation(
                platform="max",
                chat_id=chat_id,
                user_id=user_id,
                latitude=lat,
                longitude=lon,
                raw=raw,
            )

    # Photo
    photo_file_id = _extract_photo_file_id(body)
    if photo_file_id:
        caption = body.get("text") or None
        return IncomingPhoto(
            platform="max",
            chat_id=chat_id,
            user_id=user_id,
            file_id=photo_file_id,
            caption=str(caption) if caption else None,
            raw=raw,
        )

    # Text message — text is at message.body.text (NOT message.text)
    text = body.get("text") or ""
    username = sender.get("username")
    first_name = sender.get("first_name") or sender.get("name")

    return IncomingMessage(
        platform="max",
        chat_id=chat_id,
        user_id=user_id,
        username=username,
        first_name=first_name,
        text=str(text) if text else None,
        raw=raw,
    )
