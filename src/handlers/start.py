"""Start command and main menu."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from src.keyboards.menu import get_main_menu_kb, get_city_select_kb, get_role_select_kb
from src.services.user import has_profile, get_or_create_user

router = Router()


WELCOME_NEW = """Привет! 👋
Это бот мото‑сообщества Екатеринбурга.

Здесь ты можешь:
• 🚨 Отправить SOS в экстренной ситуации
• 🏍 Найти мотопару
• 📇 Узнать полезные контакты (сервисы, магазины, эвакуаторы)
• 📅 Создавать и посещать мероприятия

Для начала выбери город и свою роль."""

WELCOME_RETURNING = """С возвращением! 👋
Главное меню:"""


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user=None):
    await state.clear()
    if not user:
        user = await get_or_create_user(
            platform="telegram",
            platform_user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )

    if not user.city_id:
        await message.answer(WELCOME_NEW, reply_markup=get_city_select_kb())
        return

    has_prof = await has_profile(user)
    if not has_prof:
        await message.answer(WELCOME_NEW, reply_markup=get_role_select_kb())
        return

    await message.answer(WELCOME_RETURNING, reply_markup=get_main_menu_kb())


@router.callback_query(F.data == "menu_main")
async def cb_menu_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(WELCOME_RETURNING, reply_markup=get_main_menu_kb())
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
    text = "Отлично! Ты выбрал роль Пилота.\n\nДавай заполним короткую анкету." if role == UserRole.PILOT else "Отлично! Ты выбрал роль Двойки.\n\nДавай заполним короткую анкету."
    await callback.message.edit_text(text)
    await callback.answer()
    from src.handlers import registration
    await registration.start_registration(callback.message, state, role)
