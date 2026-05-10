"""Отправка challenge-кода владельцу канонического аккаунта на его платформу.

Используется в флоу подтверждения cross-platform линка: код отправляется
на ту платформу (Telegram или MAX), где зарегистрирован канонический
аккаунт. Заявитель должен ввести этот код у себя, чтобы линк применился.
"""

from __future__ import annotations

from html import escape
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.user import User, Platform


def _format_tg_message(code: str, requestor_platform: str, requestor_display: str) -> str:
    """HTML-форматирование для Telegram."""
    src = "MAX" if requestor_platform == "max" else "Telegram"
    return (
        "🔐 <b>Запрос на связывание аккаунтов</b>\n\n"
        f"Кто-то регистрируется в <b>{escape(src)}</b> с вашим номером телефона "
        f"и просит связать с этим аккаунтом MotoHub.\n\n"
        f"Код подтверждения: <code>{escape(code)}</code>\n"
        f"<i>Действует 10 минут.</i>\n\n"
        "Передайте код только если это вы сами регистрируетесь на второй "
        "платформе. Если вы не делали запрос — <b>проигнорируйте это сообщение</b>, "
        "ваш аккаунт в безопасности."
    )


def _format_max_message(code: str, requestor_platform: str, requestor_display: str) -> str:
    """Текстовый вариант для MAX (поддерживает HTML, но проще оставить чистый текст)."""
    src = "Telegram" if requestor_platform == "telegram" else "MAX"
    return (
        "🔐 Запрос на связывание аккаунтов\n\n"
        f"Кто-то регистрируется в {src} с вашим номером телефона "
        "и просит связать с этим аккаунтом MotoHub.\n\n"
        f"Код подтверждения: {code}\n"
        "Действует 10 минут.\n\n"
        "Передайте код только если это вы сами регистрируетесь на второй "
        "платформе. Если вы не делали запрос — проигнорируйте это сообщение, "
        "ваш аккаунт в безопасности."
    )


async def send_link_challenge_to_owner(
    canonical_user_id: UUID,
    code: str,
    requestor_platform: str,
    requestor_display: str = "",
) -> bool:
    """Найти владельца канонического аккаунта и отправить ему код на его платформу.

    requestor_platform: "telegram" | "max" — платформа заявителя; в сообщении
    владельцу указываем, ОТКУДА пришёл запрос.

    Возвращает True если сообщение реально отправлено, False иначе.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(User).where(User.id == canonical_user_id))
        owner = r.scalar_one_or_none()

    if not owner or not owner.platform_user_id:
        logger.warning(
            "account_link_notify: canonical user {} not found or has no platform_user_id",
            canonical_user_id,
        )
        return False

    chat_id = str(owner.platform_user_id)

    if owner.platform == Platform.TELEGRAM:
        from src.max_runner import _get_tg_bot

        tg_bot = _get_tg_bot()
        if tg_bot is None:
            logger.error(
                "account_link_notify: Telegram bot is not registered — cannot send code"
            )
            return False
        try:
            await tg_bot.send_message(
                chat_id=int(chat_id),
                text=_format_tg_message(code, requestor_platform, requestor_display),
                parse_mode="HTML",
            )
            return True
        except Exception as e:
            logger.warning(
                "account_link_notify: failed to send TG code to {}: {}", chat_id, e
            )
            return False

    if owner.platform == Platform.MAX:
        from src.services.broadcast import get_max_adapter

        adapter = get_max_adapter()
        if adapter is None:
            logger.error(
                "account_link_notify: MAX adapter is not registered — cannot send code"
            )
            return False
        try:
            await adapter.send_message(
                chat_id,
                _format_max_message(code, requestor_platform, requestor_display),
                parse_mode=None,
            )
            return True
        except Exception as e:
            logger.warning(
                "account_link_notify: failed to send MAX code to {}: {}", chat_id, e
            )
            return False

    logger.error(
        "account_link_notify: unknown platform for canonical user {}", canonical_user_id
    )
    return False
