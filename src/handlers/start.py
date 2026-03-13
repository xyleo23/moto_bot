"""Start command, main menu, /cancel."""
from loguru import logger

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext

from src.keyboards.menu import get_main_menu_kb, get_city_select_kb, get_role_select_kb, get_persistent_kb
from src.services.user import has_profile, get_or_create_user
from src import texts

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user=None):
    try:
        await state.clear()
        if not user:
            user = await get_or_create_user(
                platform="telegram",
                platform_user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )

        if not user or not user.city_id:
            await message.answer(texts.WELCOME_NEW, reply_markup=get_city_select_kb())
            return

        has_prof = await has_profile(user)
        if not has_prof:
            await message.answer(texts.WELCOME_NEW, reply_markup=get_role_select_kb())
            return

        # Show persistent keyboard once on /start, then inline menu
        await message.answer("⌨️", reply_markup=get_persistent_kb())
        await message.answer(
            texts.WELCOME_RETURNING,
            reply_markup=get_main_menu_kb(platform_user_id=message.from_user.id),
        )
    except Exception as e:
        logger.exception("cmd_start error: %s", e)
        await message.answer(texts.ERROR_GENERIC + "\n\nПопробуй /start снова.")


@router.message(Command("myid"))
async def cmd_myid(message: Message):
    """Показать свой Telegram ID (для настройки SUPERADMIN_IDS)."""
    from src.config import get_settings

    uid = message.from_user.id
    is_sa = uid in get_settings().superadmin_ids
    status = "✅ Ты в списке суперадминов" if is_sa else "❌ Тебя нет в SUPERADMIN_IDS"
    await message.answer(
        f"Твой Telegram ID: <code>{uid}</code>\n"
        f"Статус: {status}\n\n"
        f"Добавь в .env: <code>SUPERADMIN_IDS={uid}</code>"
        + ("\n\nПосле изменения .env перезапусти: docker compose up -d" if not is_sa else ""),
    )


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel any active FSM flow and return to main menu."""
    current = await state.get_state()
    if current is not None:
        await state.clear()
    await message.answer(
        texts.FSM_CANCEL_TEXT,
        reply_markup=get_main_menu_kb(platform_user_id=message.from_user.id),
    )


@router.message(Command("sos"))
async def cmd_sos(message: Message, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.handlers.sos import SosStates
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ДТП", callback_data="sos_accident")],
        [InlineKeyboardButton(text="Сломался", callback_data="sos_broken")],
        [InlineKeyboardButton(text="Обсох", callback_data="sos_ran_out")],
        [InlineKeyboardButton(text="Другое", callback_data="sos_other")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await state.set_state(SosStates.choose_type)
    await message.answer("🚨 Выбери тип SOS:", reply_markup=kb)


@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.profile_service import get_profile_text
    from src.services.subscription import check_subscription_required
    if not user:
        await message.answer(texts.WELCOME_RETURNING, reply_markup=get_main_menu_kb(platform_user_id=message.from_user.id))
        return
    profile_text = await get_profile_text(user)
    sub_required = await check_subscription_required(user)
    kb_rows = [[InlineKeyboardButton(text="Редактировать анкету", callback_data="profile_edit")]]
    if sub_required:
        kb_rows.append([InlineKeyboardButton(text="Оформить подписку", callback_data="profile_subscribe")])
    kb_rows.extend([
        [InlineKeyboardButton(text="Поднять анкету", callback_data="profile_raise")],
        [InlineKeyboardButton(text="📱 Сменить телефон", callback_data="profile_phone_change")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await message.answer(profile_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.message(Command("motopair"))
async def cmd_motopair(message: Message, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.subscription import check_subscription_required
    if user and await check_subscription_required(user):
        await message.answer(
            "Для доступа к поиску мотопары нужна активная подписка.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оформить подписку", callback_data="profile_subscribe")],
                [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
            ]),
        )
        return
    await message.answer("🏍 Мотопара\n\nВыбери категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Анкеты Пилотов", callback_data="motopair_pilots")],
        [InlineKeyboardButton(text="Анкеты Двоек", callback_data="motopair_passengers")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ]))


@router.message(Command("events"))
async def cmd_events(message: Message, state: FSMContext, user=None):
    from src.services.subscription import check_subscription_required
    from src.config import get_settings
    from src.services.admin_service import is_city_admin
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    is_sa = message.from_user.id in get_settings().superadmin_ids
    is_ca = user and user.city_id and await is_city_admin(message.from_user.id, user.city_id)
    if not (is_sa or is_ca) and user and await check_subscription_required(user):
        await message.answer(
            "Для доступа к мероприятиям нужна активная подписка.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оформить подписку", callback_data="profile_subscribe")],
                [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
            ]),
        )
        return
    from src.keyboards.events import get_events_menu_kb
    await message.answer("📅 Мероприятия", reply_markup=get_events_menu_kb())


@router.message(Command("contacts"))
async def cmd_contacts(message: Message, state: FSMContext, user=None):
    from src.keyboards.contacts import get_contacts_menu_kb
    await message.answer("📇 Полезные контакты", reply_markup=get_contacts_menu_kb())


@router.message(Command("about"))
async def cmd_about(message: Message, state: FSMContext, user=None):
    from src.services.admin_service import get_global_text
    from src.handlers.about import DEFAULT_ABOUT
    from src.keyboards.menu import get_back_to_menu_kb
    from src.config import get_settings
    s = get_settings()
    text_db = await get_global_text("about_us")
    about_text = (text_db or DEFAULT_ABOUT).strip()
    about_text += f"\n\n📧 {s.support_email}"
    await message.answer(about_text, reply_markup=get_back_to_menu_kb())


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext, user=None):
    from src.config import get_settings
    if message.from_user.id not in get_settings().superadmin_ids:
        return
    from src.keyboards.admin import get_admin_main_kb
    await message.answer("⚙️ Панель администратора", reply_markup=get_admin_main_kb())


@router.callback_query(F.data == "menu_main")
async def cb_menu_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        texts.WELCOME_RETURNING,
        reply_markup=get_main_menu_kb(platform_user_id=callback.from_user.id),
    )
    await callback.answer()


@router.callback_query(F.data == "city_ekb")
async def cb_city_ekb(callback: CallbackQuery, state: FSMContext, user=None):
    from src.models.base import get_session_factory
    from sqlalchemy import select
    from src.models.city import City

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(City).where(City.name == "Екатеринбург"))
        city = result.scalar_one_or_none()
        if city:
            user = await get_or_create_user(
                platform="telegram",
                platform_user_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                city_id=city.id,
            )

    await callback.message.edit_text(
        "Отлично! Теперь выбери свою роль:",
        reply_markup=get_role_select_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.in_(["role_pilot", "role_passenger"]))
async def cb_role_select(callback: CallbackQuery, state: FSMContext, user=None):
    from src.models.base import get_session_factory
    from src.models.user import User, UserRole, Platform
    from sqlalchemy import select

    role = UserRole.PILOT if callback.data == "role_pilot" else UserRole.PASSENGER
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.platform_user_id == callback.from_user.id,
                User.platform == Platform.TELEGRAM,
            )
        )
        u = result.scalar_one_or_none()
        if u:
            u.role = role
            await session.commit()

    await state.update_data(registration_role=callback.data)
    text = (
        "Отлично! Ты выбрал роль Пилота.\n\nДавай заполним короткую анкету."
        if role == UserRole.PILOT
        else "Отлично! Ты выбрал роль Двойки.\n\nДавай заполним короткую анкету."
    )
    await callback.message.edit_text(text)
    await callback.answer()
    from src.handlers import registration
    await registration.start_registration(callback.message, state, role)


# ── Persistent keyboard button handlers ──────────────────────────────────────

@router.message(F.text == "🆘 SOS")
async def kb_sos(message: Message, state: FSMContext, user=None):
    """Handle SOS quick button from persistent keyboard."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ДТП", callback_data="sos_accident")],
        [InlineKeyboardButton(text="Сломался", callback_data="sos_broken")],
        [InlineKeyboardButton(text="Обсох", callback_data="sos_ran_out")],
        [InlineKeyboardButton(text="Другое", callback_data="sos_other")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    from src.handlers.sos import SosStates
    await state.set_state(SosStates.choose_type)
    await message.answer("🚨 Выбери тип SOS:", reply_markup=kb)


@router.message(F.text == "🏍 Мотопара")
async def kb_motopair(message: Message, state: FSMContext, user=None):
    """Handle MotoPair from persistent keyboard. Must check subscription same as menu_motopair."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.subscription import check_subscription_required

    if user and await check_subscription_required(user):
        await message.answer(
            "Для доступа к поиску мотопары нужна активная подписка.\n"
            "Подписка даёт доступ к анкетам и контактам.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оформить подписку", callback_data="profile_subscribe")],
                [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
            ]),
        )
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Анкеты Пилотов", callback_data="motopair_pilots")],
        [InlineKeyboardButton(text="Анкеты Двоек", callback_data="motopair_passengers")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await message.answer("🏍 Мотопара\n\nВыбери категорию:", reply_markup=kb)


@router.message(F.text == "📅 Мероприятия")
async def kb_events(message: Message, state: FSMContext, user=None):
    from src.config import get_settings
    from src.services.admin_service import is_city_admin, get_admin_events
    from src.services.event_service import TYPE_LABELS
    from src.services.subscription import check_subscription_required
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    is_sa = message.from_user.id in get_settings().superadmin_ids
    is_ca = user and user.city_id and await is_city_admin(message.from_user.id, user.city_id)

    # Subscription check for regular users (admins bypass)
    if not (is_sa or is_ca) and user and await check_subscription_required(user):
        await message.answer(
            "Для доступа к мероприятиям нужна активная подписка.\n"
            "Подписка даёт доступ к просмотру, записи и поиску мотопары на мероприятиях.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оформить подписку", callback_data="profile_subscribe")],
                [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
            ]),
        )
        return
    if is_sa or is_ca:
        events = await get_admin_events(superadmin=is_sa, city_id=user.city_id if user else None)
        rows = []
        for e in events[:20]:
            label = e.title or TYPE_LABELS.get(e.type.value, e.type.value)
            rows.append([InlineKeyboardButton(
                text=f"{e.start_at.strftime('%d.%m')} {label}",
                callback_data=f"admin_ev_{e.id}",
            )])
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
        text = (
            "Мероприятия (последние):\n\n"
            + "\n".join(
                f"• {(ev.title or TYPE_LABELS.get(ev.type.value, ''))} — {ev.start_at.strftime('%d.%m.%Y')}"
                for ev in events[:20]
            )
            if events
            else "Мероприятий нет."
        )
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return

    from src.keyboards.events import get_events_menu_kb
    await message.answer("📅 Мероприятия", reply_markup=get_events_menu_kb())


@router.message(F.text == "📞 Контакты")
async def kb_contacts(message: Message, state: FSMContext, user=None):
    from src.keyboards.contacts import get_contacts_menu_kb
    await message.answer("📇 Полезные контакты", reply_markup=get_contacts_menu_kb())


@router.message(F.text == "👤 Профиль")
async def kb_profile(message: Message, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.profile_service import get_profile_text
    from src.services.subscription import check_subscription_required

    if not user:
        await message.answer(
            texts.WELCOME_RETURNING,
            reply_markup=get_main_menu_kb(platform_user_id=message.from_user.id),
        )
        return

    profile_text = await get_profile_text(user)
    sub_required = await check_subscription_required(user)
    kb_rows = [
        [InlineKeyboardButton(text="Редактировать анкету", callback_data="profile_edit")],
    ]
    if sub_required:
        kb_rows.append([InlineKeyboardButton(text="Оформить подписку", callback_data="profile_subscribe")])
    kb_rows.extend([
        [InlineKeyboardButton(text="Поднять анкету", callback_data="profile_raise")],
        [InlineKeyboardButton(text="📱 Сменить телефон", callback_data="profile_phone_change")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await message.answer(profile_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.message(F.text == "ℹ️ О нас")
async def kb_about(message: Message, state: FSMContext, user=None):
    from src.services.admin_service import get_global_text
    from src.handlers.about import DEFAULT_ABOUT
    from src.keyboards.menu import get_back_to_menu_kb
    from src.config import get_settings

    s = get_settings()
    text_db = await get_global_text("about_us")
    about_text = (text_db or DEFAULT_ABOUT).strip()
    about_text += f"\n\n📧 {s.support_email}"
    await message.answer(about_text, reply_markup=get_back_to_menu_kb())
