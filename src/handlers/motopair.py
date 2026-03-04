"""MotoPair block - find pilot/passenger."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from src.keyboards.menu import get_back_to_menu_kb

router = Router()


@router.callback_query(F.data == "menu_motopair")
async def cb_motopair_menu(callback: CallbackQuery, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.subscription import check_subscription_required

    if user and await check_subscription_required(user):
        await callback.message.edit_text(
            "Для доступа к поиску мотопары нужна активная подписка.\n"
            "Подписка даёт доступ к анкетам и контактам.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Оформить подписку", callback_data="menu_profile")],
                [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
            ]),
        )
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Анкеты Пилотов", callback_data="motopair_pilots")],
        [InlineKeyboardButton(text="Анкеты Двоек", callback_data="motopair_passengers")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await callback.message.edit_text("🏍 Мотопара\n\nВыбери категорию:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.in_(["motopair_pilots", "motopair_passengers"]))
async def cb_motopair_category(callback: CallbackQuery, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    role = "pilot" if callback.data == "motopair_pilots" else "passenger"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Все анкеты", callback_data=f"motopair_list_{role}")],
        [InlineKeyboardButton(text="Фильтр", callback_data=f"motopair_filter_{role}")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_motopair")],
    ])
    label = "Пилотов" if role == "pilot" else "Двоек"
    await callback.message.edit_text(f"Анкеты {label}:", reply_markup=kb)
    await callback.answer()


def _parse_motopair_cb(data: str) -> tuple[str, int]:
    """Parse motopair_next_role_offset or motopair_list_role -> (role, offset)."""
    if data.startswith("motopair_list_"):
        role = data.replace("motopair_list_", "")
        return role, 0
    if data.startswith("motopair_next_"):
        parts = data.replace("motopair_next_", "").split("_")
        return parts[0], int(parts[1]) if len(parts) > 1 else 0
    return "pilot", 0


@router.callback_query(F.data.startswith("motopair_list_") | F.data.startswith("motopair_next_"))
async def cb_motopair_list(callback: CallbackQuery, user=None):
    from src.services.motopair_service import get_next_profile
    from src.keyboards.motopair import get_profile_view_kb

    role, offset = _parse_motopair_cb(callback.data)
    profile, has_more = await get_next_profile(user.id, role, offset=offset)
    if not profile:
        await callback.message.edit_text("Анкет пока нет.", reply_markup=get_back_to_menu_kb())
    else:
        text = _format_profile(profile)
        await callback.message.edit_text(text, reply_markup=get_profile_view_kb(str(profile.id), role, offset, has_more))
    await callback.answer()


def _format_profile(profile) -> str:
    if hasattr(profile, "bike_brand"):
        return f"🏍 {profile.name}\nВозраст: {profile.age}\n{profile.bike_brand} {profile.bike_model}, {profile.engine_cc} см³\nО себе: {profile.about or '-'}"
    return f"👤 {profile.name}\nВозраст: {profile.age}, Рост: {profile.height} см, Вес: {profile.weight} кг\nО себе: {profile.about or '-'}"
