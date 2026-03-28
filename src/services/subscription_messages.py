"""Единые тексты «нужна подписка» с преимуществами из БД (лимит мотопробегов)."""

from __future__ import annotations

from typing import Literal

from src import texts
from src.services.admin_service import get_subscription_settings

SubscriptionRequiredKind = Literal[
    "motopair_menu",
    "motopair_cards",
    "events_menu",
    "events_register",
    "events_create",
]

_INTROS: dict[str, str] = {
    "motopair_menu": "Для доступа к поиску мотопары нужна активная подписка.\n\n",
    "motopair_cards": "Для просмотра анкет нужна активная подписка.\n\n",
    "events_menu": "Для доступа к мероприятиям нужна активная подписка.\n\n",
    "events_register": "Для записи на мероприятие нужна активная подписка.\n\n",
    "events_create": "Для создания мероприятий нужна активная подписка.\n\n",
}

_FOOTERS: dict[str, str] = {
    # Дублирует кнопку «Мой профиль», но помогает при только текстовом канале
    "events_register": "\n\nОформить подписку можно в разделе «Мой профиль».",
}


async def motorcade_limit_for_subscription_texts() -> int:
    """Лимит бесплатных мотопробегов/мес из subscription_settings."""
    settings_db = await get_subscription_settings()
    if settings_db and settings_db.event_motorcade_limit_per_month is not None:
        return settings_db.event_motorcade_limit_per_month
    return 2


async def max_profile_subscription_block() -> str:
    """Текст про подписку для экрана «Мой профиль» в MAX (без эмодзи-заголовка)."""
    lim = await motorcade_limit_for_subscription_texts()
    return (
        "Для доступа к функциям бота нужна подписка.\n\n"
        "Подписка даёт:\n" + texts.sub_benefits_full_text(lim)
    )


async def subscription_required_message(kind: SubscriptionRequiredKind) -> str:
    """
    Заголовок ситуации + «Подписка даёт:» + bullet-список (как в профиле).
    """
    intro = _INTROS[kind]
    footer = _FOOTERS.get(kind, "")
    lim = await motorcade_limit_for_subscription_texts()
    body = "Подписка даёт:\n" + texts.sub_benefits_full_text(lim)
    return intro + body + footer
