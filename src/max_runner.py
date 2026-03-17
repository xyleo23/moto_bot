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
    get_contacts_menu_rows,
    get_contacts_page_rows,
    get_motopair_profile_rows,
    get_events_menu_rows,
    get_event_list_rows,
    get_event_detail_rows,
)


def _format_profile_max(profile) -> str:
    """Format profile card for MAX (no Telegram links)."""
    if hasattr(profile, "bike_brand"):
        return (
            f"🏍 <b>{profile.name}</b>\n"
            f"Возраст: {profile.age}\n"
            f"Мотоцикл: {profile.bike_brand} {profile.bike_model}, {profile.engine_cc} см³\n"
            f"О себе: {profile.about or '—'}"
        )
    return (
        f"👤 <b>{profile.name}</b>\n"
        f"Возраст: {profile.age}, Рост: {profile.height} см, Вес: {profile.weight} кг\n"
        f"О себе: {profile.about or '—'}"
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
        await handle_motopair_menu(adapter, chat_id, user)
        return
    if data == "menu_contacts":
        await handle_contacts_menu(adapter, chat_id, user)
        return
    if data == "menu_events":
        await handle_events_menu(adapter, chat_id, user)
        return
    if data == "menu_profile":
        await handle_profile(adapter, chat_id, user)
        return
    if data == "menu_about":
        await handle_about(adapter, chat_id)
        return

    # MotoPair callbacks
    if data in ("motopair_pilots", "motopair_passengers"):
        role = "pilot" if data == "motopair_pilots" else "passenger"
        await handle_motopair_list(adapter, chat_id, user, role, offset=0)
        return
    if data.startswith("motopair_next_"):
        parts = data.replace("motopair_next_", "").split("_")
        role = parts[0] if parts else "pilot"
        offset = int(parts[1]) if len(parts) > 1 else 0
        await handle_motopair_list(adapter, chat_id, user, role, offset)
        return
    if data.startswith("like_"):
        parts = data.replace("like_", "").rsplit("_", 1)
        if len(parts) == 2:
            await handle_motopair_like(adapter, ev, user, parts[0], parts[1], is_like=True)
        return
    if data.startswith("dislike_"):
        parts = data.replace("dislike_", "").rsplit("_", 1)
        if len(parts) == 2:
            await handle_motopair_like(adapter, ev, user, parts[0], parts[1], is_like=False)
        return

    # Contacts callbacks
    if data.startswith("contacts_"):
        if data.startswith("contacts_page_"):
            p = data.replace("contacts_page_", "").split("_")
            if len(p) >= 2:
                await handle_contacts_list(adapter, chat_id, user, p[0], int(p[1]))
        else:
            cat = data.replace("contacts_", "")
            await handle_contacts_list(adapter, chat_id, user, cat, 0)
        return

    # Events callbacks
    if data == "event_list" or data.startswith("event_list_"):
        ev_type = data.replace("event_list_", "") if "_" in data else None
        await handle_events_list(adapter, chat_id, user, ev_type)
        return
    if data.startswith("event_detail_"):
        eid = data.replace("event_detail_", "")
        await handle_event_detail(adapter, chat_id, user, eid)
        return
    if data.startswith("event_register_"):
        p = data.replace("event_register_", "").split("_")
        if len(p) >= 2:
            await handle_event_register(adapter, chat_id, user, p[0], p[1])
        return

    await adapter.send_message(chat_id, "Неизвестная команда.", get_main_menu_rows())


async def handle_motopair_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Motopair: pilots or passengers choice."""
    from src.services.subscription import check_subscription_required
    from src.platforms.base import Button, KeyboardRow

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            "Для доступа к мотопаре нужна подписка. Оформи в «Мой профиль».",
            [[Button("👤 Мой профиль", payload="menu_profile")], [Button("« Назад", payload="menu_main")]],
        )
        return
    kb = [
        [Button("Анкеты пилотов", payload="motopair_pilots")],
        [Button("Анкеты двоек", payload="motopair_passengers")],
        [Button("« Назад", payload="menu_main")],
    ]
    await adapter.send_message(chat_id, "🏍 Мотопара\n\nВыбери категорию:", kb)


async def handle_motopair_list(adapter: MaxAdapter, chat_id: str, user, role: str, offset: int = 0) -> None:
    """Show next profile or empty state."""
    from src.services.motopair_service import get_next_profile, get_user_for_profile
    from src import texts

    profile, has_more = await get_next_profile(user.id, role, offset=offset)
    if not profile:
        await adapter.send_message(
            chat_id, texts.MOTOPAIR_NO_PROFILES,
            [[Button("« В меню", payload="menu_motopair")]],
        )
        return
    text = _format_profile_max(profile)
    kb = get_motopair_profile_rows(str(profile.id), role, offset, has_more)
    await adapter.send_message(chat_id, text, kb)


async def handle_motopair_like(
    adapter: MaxAdapter, ev: IncomingCallback, user, profile_id_str: str, role: str, is_like: bool
) -> None:
    """Process like/dislike."""
    from src.services.motopair_service import get_user_for_profile, process_like
    from src import texts

    try:
        to_user_id = await get_user_for_profile(uuid.UUID(profile_id_str), role)
    except (ValueError, TypeError):
        await adapter.send_message(ev.chat_id, "Ошибка.", get_back_to_menu_rows())
        return
    if not to_user_id:
        await adapter.send_message(ev.chat_id, "Профиль не найден.", get_back_to_menu_rows())
        return
    result = await process_like(user.id, to_user_id.id, is_like)
    if is_like and result.get("matched"):
        await adapter.send_message(
            ev.chat_id,
            "💚 Взаимный лайк! Контакты в Telegram-версии бота.",
            get_back_to_menu_rows(),
        )
    elif is_like:
        await adapter.send_message(ev.chat_id, "👍 Лайк отправлен!", get_back_to_menu_rows())
    else:
        await adapter.send_message(ev.chat_id, "👎 Дизлайк учтён.", get_back_to_menu_rows())
    # Show next profile
    await handle_motopair_list(adapter, ev.chat_id, user, role, 0)


async def handle_contacts_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Contacts: category menu."""
    await adapter.send_message(chat_id, "📇 Полезные контакты\n\nВыбери категорию:", get_contacts_menu_rows())


async def handle_contacts_list(
    adapter: MaxAdapter, chat_id: str, user, category: str, offset: int = 0
) -> None:
    """Contacts list by category."""
    from src.services.useful_contacts_service import get_contacts_by_category, CAT_LABELS

    if not user.city_id:
        await adapter.send_message(chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows())
        return
    contacts, total, has_more = await get_contacts_by_category(user.city_id, category, offset=offset)
    label = CAT_LABELS.get(category, category)
    if not contacts:
        text = f"{label}\n\nКонтактов пока нет."
    else:
        lines = [f"<b>{label}</b>\n"]
        for c in contacts:
            line = f"• {c['name']}"
            if c.get("phone"):
                line += f" — {c['phone']}"
            if c.get("link"):
                line += f"\n  {c['link']}"
            lines.append(line)
        text = "\n".join(lines)
    kb = get_contacts_page_rows(category, offset, has_more)
    await adapter.send_message(chat_id, text, kb)


async def handle_events_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Events menu."""
    await adapter.send_message(chat_id, "📅 Мероприятия", get_events_menu_rows())


async def handle_events_list(
    adapter: MaxAdapter, chat_id: str, user, event_type: str | None = None
) -> None:
    """Events list."""
    from src.services.event_service import get_events_list
    from src.platforms.base import Button

    if not user.city_id:
        await adapter.send_message(chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows())
        return
    events = await get_events_list(user.city_id, event_type)
    if not events:
        await adapter.send_message(
            chat_id, "Мероприятий пока нет.",
            get_event_list_rows(),
        )
        return
    lines = ["<b>Список мероприятий</b>\n"]
    for e in events[:15]:
        lines.append(
            f"• {e['title']} — {e['date']}\n"
            f"  Пилотов: {e['pilots']}, двоек: {e['passengers']}\n"
            f"  <i>Нажми для деталей: event_detail_{e['id']}</i>"
        )
    text = "\n".join(lines)
    kb = get_event_list_rows()
    # Add event detail buttons
    for e in events[:5]:
        kb.insert(-1, [Button(f"📅 {e['title'][:20]}", payload=f"event_detail_{e['id']}")])
    await adapter.send_message(chat_id, text[:4000], kb)


async def handle_event_detail(adapter: MaxAdapter, chat_id: str, user, event_id: str) -> None:
    """Event detail and registration."""
    from src.services.event_service import get_event_by_id
    from src.services.event_service import TYPE_LABELS

    ev = await get_event_by_id(uuid.UUID(event_id))
    if not ev:
        await adapter.send_message(chat_id, "Мероприятие не найдено.", get_back_to_menu_rows())
        return
    title = ev.title or TYPE_LABELS.get(ev.type.value, ev.type.value)
    text = (
        f"<b>{title}</b>\n"
        f"📅 {ev.start_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {ev.point_start or '—'}\n"
        f"{ev.description or ''}"
    )
    # Check if user already registered
    from src.models.event import EventRegistration
    session_factory = get_session_factory()
    is_reg = False
    async with session_factory() as session:
        from sqlalchemy import select
        r = await session.execute(
            select(EventRegistration).where(
                EventRegistration.event_id == ev.id,
                EventRegistration.user_id == user.id,
            )
        )
        is_reg = r.scalar_one_or_none() is not None
    kb = get_event_detail_rows(event_id, is_reg)
    await adapter.send_message(chat_id, text, kb)


async def handle_event_register(
    adapter: MaxAdapter, chat_id: str, user, event_id: str, role: str
) -> None:
    """Register for event."""
    from src.services.event_service import register_for_event

    ok, _ = await register_for_event(uuid.UUID(event_id), user.id, role)
    if ok:
        await adapter.send_message(
            chat_id, "✅ Ты зарегистрирован!",
            get_back_to_menu_rows(),
        )
    else:
        await adapter.send_message(
            chat_id, "Ошибка регистрации.",
            get_back_to_menu_rows(),
        )


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
