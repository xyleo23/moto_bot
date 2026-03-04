"""MotoPair block - find pilot/passenger."""
import uuid

from loguru import logger
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from src.keyboards.menu import get_back_to_menu_kb
from src.keyboards.motopair import (
    get_profile_view_kb,
    get_like_notification_kb,
    get_match_kb,
)

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

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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


def _format_profile(profile) -> str:
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


@router.callback_query(F.data.startswith("motopair_list_") | F.data.startswith("motopair_next_"))
async def cb_motopair_list(callback: CallbackQuery, user=None):
    from src.services.motopair_service import get_next_profile

    if not user:
        await callback.answer("Ошибка: пользователь не определён.", show_alert=True)
        return

    role, offset = _parse_motopair_cb(callback.data)
    profile, has_more = await get_next_profile(user.id, role, offset=offset)

    if not profile:
        await callback.message.edit_text(
            "Анкеты закончились. Загляни позже! 🔄",
            reply_markup=get_back_to_menu_kb(),
        )
    else:
        text = _format_profile(profile)
        kb = get_profile_view_kb(str(profile.id), role, offset, has_more)
        if profile.photo_file_id:
            try:
                await callback.message.delete()
                await callback.message.answer_photo(
                    photo=profile.photo_file_id,
                    caption=text,
                    reply_markup=kb,
                )
            except Exception:
                await callback.message.edit_text(text, reply_markup=kb)
        else:
            await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("like_"))
async def cb_like(callback: CallbackQuery, user=None, bot=None):
    """User liked a profile."""
    from src.services.motopair_service import (
        process_like, get_user_for_profile, get_profile_info_text
    )

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    parts = callback.data.split("_")
    if len(parts) < 3:
        await callback.answer()
        return

    profile_id_str = parts[1]
    role = parts[2]

    try:
        profile_uuid = uuid.UUID(profile_id_str)
    except ValueError:
        await callback.answer()
        return

    target_user = await get_user_for_profile(profile_uuid, role)
    if not target_user:
        await callback.answer("Анкета не найдена.", show_alert=True)
        return

    result = await process_like(user.id, target_user.id, is_like=True)

    if result["matched"]:
        # Mutual like — show contacts to both
        from_text, _ = await get_profile_info_text(target_user.id)
        to_text, _ = await get_profile_info_text(user.id)

        # Notify the other user about match
        if bot and result["target_platform_user_id"]:
            try:
                await bot.send_message(
                    chat_id=result["target_platform_user_id"],
                    text=(
                        "🎉 <b>Взаимный лайк!</b>\n\n"
                        f"{to_text}\n\n"
                        "Вы понравились друг другу — напишите первым!"
                    ),
                    reply_markup=get_match_kb(
                        callback.from_user.username,
                        callback.from_user.id,
                    ),
                )
            except Exception as e:
                logger.warning("Cannot notify match user %s: %s", result["target_platform_user_id"], e)

        await callback.message.edit_text(
            f"🎉 <b>Взаимный лайк!</b>\n\n{from_text}",
            reply_markup=get_match_kb(
                target_user.platform_username,
                target_user.platform_user_id,
            ),
        )
    else:
        # One-way like — notify target
        if bot and result["target_platform_user_id"]:
            from_text, from_photo = await get_profile_info_text(user.id)
            try:
                notify_text = (
                    "💌 <b>Кто-то лайкнул твою анкету!</b>\n\n"
                    f"{from_text}"
                )
                kb = get_like_notification_kb(str(user.id))
                if from_photo:
                    await bot.send_photo(
                        chat_id=result["target_platform_user_id"],
                        photo=from_photo,
                        caption=notify_text,
                        reply_markup=kb,
                    )
                else:
                    await bot.send_message(
                        chat_id=result["target_platform_user_id"],
                        text=notify_text,
                        reply_markup=kb,
                    )
            except Exception as e:
                logger.warning("Cannot notify like user %s: %s", result["target_platform_user_id"], e)

        await callback.message.edit_text(
            "👍 Лайк отправлен! Если понравишься в ответ — сообщим о совпадении.",
            reply_markup=get_back_to_menu_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("dislike_"))
async def cb_dislike(callback: CallbackQuery, user=None):
    """User disliked a profile."""
    from src.services.motopair_service import process_like, get_user_for_profile

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    parts = callback.data.split("_")
    if len(parts) < 3:
        await callback.answer()
        return

    profile_id_str = parts[1]
    role = parts[2]

    try:
        profile_uuid = uuid.UUID(profile_id_str)
    except ValueError:
        await callback.answer()
        return

    target_user = await get_user_for_profile(profile_uuid, role)
    if not target_user:
        await callback.answer("Анкета не найдена.", show_alert=True)
        return

    result = await process_like(user.id, target_user.id, is_like=False)

    if result["blacklisted"]:
        text = "👎 Анкета скрыта."
    else:
        text = "👎 Пропущено."

    await callback.message.edit_text(text, reply_markup=get_back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("reply_like_"))
async def cb_reply_like(callback: CallbackQuery, user=None, bot=None):
    """Target user replies with a like to the notification."""
    from src.services.motopair_service import process_like, get_profile_info_text
    from src.models.user import User
    from sqlalchemy import select

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    from_user_id_str = callback.data.replace("reply_like_", "")
    try:
        from_user_uuid = uuid.UUID(from_user_id_str)
    except ValueError:
        await callback.answer()
        return

    # Get the from_user's platform_user_id
    session_factory = __import__("src.models.base", fromlist=["get_session_factory"]).get_session_factory()
    async with session_factory() as session:
        res = await session.execute(select(User).where(User.id == from_user_uuid))
        from_user = res.scalar_one_or_none()

    if not from_user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return

    result = await process_like(user.id, from_user_uuid, is_like=True)

    # This always results in a match (they liked us, we like them back)
    from_text, _ = await get_profile_info_text(from_user_uuid)

    if bot and from_user.platform_user_id:
        to_text, _ = await get_profile_info_text(user.id)
        try:
            await bot.send_message(
                chat_id=from_user.platform_user_id,
                text=(
                    "🎉 <b>Взаимный лайк!</b>\n\n"
                    f"{to_text}\n\n"
                    "Они ответили на твой лайк — напиши первым!"
                ),
                reply_markup=get_match_kb(
                    callback.from_user.username,
                    callback.from_user.id,
                ),
            )
        except Exception as e:
            logger.warning("Cannot notify match reply user %s: %s", from_user.platform_user_id, e)

    await callback.message.edit_text(
        f"🎉 <b>Взаимный лайк!</b>\n\n{from_text}",
        reply_markup=get_match_kb(
            from_user.platform_username,
            from_user.platform_user_id,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reply_skip_"))
async def cb_reply_skip(callback: CallbackQuery, user=None):
    """Target user skips the like notification."""
    await callback.message.edit_text(
        "Хорошо, пропускаем.",
        reply_markup=get_back_to_menu_kb(),
    )
    await callback.answer()
