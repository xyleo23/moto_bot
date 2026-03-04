"""MAX bot runner — dispatches updates to handlers."""
import uuid
import asyncio
from typing import Any

from loguru import logger

from src.config import get_settings
from src.platforms.max_adapter import MaxAdapter
from src.platforms.max_parser import parse_updates
from src.platforms.base import (
    IncomingMessage,
    IncomingCallback,
    IncomingContact,
    IncomingLocation,
    KeyboardRow,
)
from src.services.user import get_or_create_user, has_profile
from src.models.user import User, UserRole, Platform
from src.models.base import get_session_factory
from sqlalchemy import select
from src.keyboards.shared import (
    get_main_menu_rows,
    get_city_select_rows,
    get_role_select_rows,
    get_back_to_menu_rows,
    get_contact_button_row,
    get_location_button_row,
)


async def process_max_update(adapter: MaxAdapter, raw: dict) -> None:
    """Process one MAX update."""
    events = parse_updates({"updates": [raw]})
    for ev in events:
        try:
            if isinstance(ev, IncomingCallback):
                await handle_callback(adapter, ev)
            elif isinstance(ev, IncomingMessage):
                await handle_message(adapter, ev)
            elif isinstance(ev, IncomingContact):
                await handle_contact(adapter, ev)
            elif isinstance(ev, IncomingLocation):
                await handle_location(adapter, ev)
        except Exception as e:
            logger.exception("MAX handle error: %s", e)


async def handle_message(adapter: MaxAdapter, ev: IncomingMessage) -> None:
    """Handle text message or /start."""
    user = await get_or_create_user(
        platform="max",
        platform_user_id=ev.user_id,
        username=ev.username,
        first_name=ev.first_name,
    )
    if not user:
        return
    if user.is_blocked:
        await adapter.send_message(ev.chat_id, "Вы заблокированы. Обратитесь в поддержку.")
        return

    text = (ev.text or "").strip()
    if text.startswith("/start") or text.lower() == "start":
        await handle_start(adapter, ev.chat_id, user)
    else:
        # Echo or "unknown command" for now
        await adapter.send_message(ev.chat_id, "Используй меню или /start", get_main_menu_rows())


async def handle_start(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Handle /start flow."""
    WELCOME = """Привет! 👋
Это бот мото‑сообщества Екатеринбурга.

Здесь ты можешь:
• 🚨 Отправить SOS в экстренной ситуации
• 🏍 Найти мотопару
• 📇 Узнать полезные контакты
• 📅 Создавать и посещать мероприятия

Для начала выбери город и свою роль."""

    if not user.city_id:
        await adapter.send_message(chat_id, WELCOME, get_city_select_rows())
        return

    # Show role select until profile done. MAX: no full registration flow, show menu after role
    if not await has_profile(user):
        if user.role in (UserRole.PILOT, UserRole.PASSENGER):
            # MAX: have role, show menu (full profile in Telegram)
            pass
        else:
            await adapter.send_message(chat_id, WELCOME, get_role_select_rows())
            return

    await adapter.send_message(
        chat_id,
        "С возвращением! 👋\nГлавное меню:",
        get_main_menu_rows(),
    )


async def handle_callback(adapter: MaxAdapter, ev: IncomingCallback) -> None:
    """Handle callback button press."""
    user = await get_or_create_user(
        platform="max",
        platform_user_id=ev.user_id,
    )
    if not user:
        return
    if user.is_blocked:
        await adapter.send_message(ev.chat_id, "Вы заблокированы.")
        return

    data = ev.callback_data
    chat_id = ev.chat_id

    # City selection
    if data == "city_ekb":
        from src.models.city import City
        cq = ev.raw.get("callback_query") or ev.raw.get("callback") or ev.raw
        from_obj = cq.get("from") or cq.get("user") or {}
        session_factory = get_session_factory()
        async with session_factory() as session:
            r = await session.execute(select(City).where(City.name == "Екатеринбург"))
            city = r.scalar_one_or_none()
            if city:
                user = await get_or_create_user(
                    platform="max",
                    platform_user_id=ev.user_id,
                    username=from_obj.get("username"),
                    first_name=from_obj.get("first_name"),
                    city_id=city.id,
                )
        await adapter.send_message(
            chat_id,
            "Отлично! Теперь выбери свою роль:",
            get_role_select_rows(),
        )
        return

    # Role selection
    if data in ("role_pilot", "role_passenger"):
        role = UserRole.PILOT if data == "role_pilot" else UserRole.PASSENGER
        session_factory = get_session_factory()
        async with session_factory() as session:
            r = await session.execute(
                select(User).where(
                    User.platform_user_id == ev.user_id,
                    User.platform == Platform.MAX,
                )
            )
            u = r.scalar_one_or_none()
            if u:
                u.role = role
                await session.commit()
        await adapter.send_message(
            chat_id,
            "Роль сохранена! Полная анкета (фото, марка мото и т.д.) доступна в Telegram-версии бота. "
            "Здесь пока базовый доступ. Нажми /start для меню.",
            get_main_menu_rows(),
        )
        return

    # Main menu
    if data == "menu_main":
        await adapter.send_message(
            chat_id,
            "С возвращением! 👋\nГлавное меню:",
            get_main_menu_rows(),
        )
        return

    # Other menu items - placeholder responses
    if data == "menu_sos":
        await adapter.request_location(
            chat_id,
            "Отправь свою геолокацию для SOS или напиши комментарий.",
        )
        return
    if data == "menu_motopair":
        await adapter.send_message(
            chat_id,
            "Мотопара — в MAX пока в разработке. Используй Telegram-версию бота для полного функционала.",
            get_back_to_menu_rows(),
        )
        return
    if data == "menu_contacts":
        await adapter.send_message(
            chat_id,
            "Полезные контакты — в MAX пока в разработке.",
            get_back_to_menu_rows(),
        )
        return
    if data == "menu_events":
        await adapter.send_message(
            chat_id,
            "Мероприятия — в MAX пока в разработке.",
            get_back_to_menu_rows(),
        )
        return
    if data == "menu_profile":
        await handle_profile(adapter, chat_id, user)
        return
    if data == "menu_about":
        await handle_about(adapter, chat_id)
        return

    await adapter.send_message(chat_id, "Неизвестная команда.", get_main_menu_rows())


async def handle_profile(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Profile and subscription."""
    from src.services.subscription import check_subscription_required
    from src.services.admin_service import get_subscription_settings
    from src.services.payment import create_payment

    sub_required = await check_subscription_required(user)
    if sub_required:
        settings = await get_subscription_settings()
        text = (
            "Подписка нужна для доступа. Оформи через ссылку:\n"
            "Стоимость: месяц — {} ₽, сезон — {} ₽\n\n"
            "После оплаты нажми /start."
        ).format(
            (settings.monthly_price_kopecks or 29900) / 100,
            (settings.season_price_kopecks or 79900) / 100,
        )
        # Create payment link for MAX user
        payment = await create_payment(
            amount_kopecks=settings.monthly_price_kopecks or 29900,
            description="Подписка на 1 месяц — мото-бот",
            metadata={"type": "subscription", "user_id": str(user.id), "period": "monthly"},
            return_url="https://max.ru/",
        )
        if payment and payment.get("confirmation_url"):
            text += f"\n\n💳 Оплатить: {payment['confirmation_url']}"
        await adapter.send_message(chat_id, text, get_back_to_menu_rows())
    else:
        await adapter.send_message(
            chat_id,
            "Мой профиль. Подписка активна.",
            get_back_to_menu_rows(),
        )


async def handle_about(adapter: MaxAdapter, chat_id: str) -> None:
    """About us."""
    from src.services.admin_service import get_global_text
    from src.config import get_settings

    text_db = await get_global_text("about_us")
    default = "Бот мото-сообщества Екатеринбурга."
    text = (text_db or default).strip()
    s = get_settings()
    text += f"\n\n📧 {s.support_email}\n👤 @{s.support_username}"

    await adapter.send_message(chat_id, text, get_back_to_menu_rows())


async def handle_contact(adapter: MaxAdapter, ev: IncomingContact) -> None:
    """Handle contact shared (e.g. during registration)."""
    # For now just ack - full registration would continue FSM
    await adapter.send_message(
        ev.chat_id,
        f"Номер получен: {ev.phone_number}. Регистрация в MAX — используй Telegram для полной анкеты.",
        get_main_menu_rows(),
    )


async def handle_location(adapter: MaxAdapter, ev: IncomingLocation) -> None:
    """Handle location (e.g. SOS)."""
    await adapter.send_message(
        ev.chat_id,
        f"Геолокация получена: {ev.latitude:.5f}, {ev.longitude:.5f}. SOS в MAX — в разработке.",
        get_back_to_menu_rows(),
    )
