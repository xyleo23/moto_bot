"""MotoPair block — find pilot/passenger."""
import uuid

from loguru import logger
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.keyboards.menu import get_back_to_menu_kb
from src.keyboards.motopair import (
    get_profile_view_kb,
    get_like_notification_kb,
    get_match_kb,
    get_filter_kb,
)
from src import texts

router = Router()


@router.callback_query(F.data == "menu_motopair")
async def cb_motopair_menu(callback: CallbackQuery, user=None):
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
    role = "pilot" if callback.data == "motopair_pilots" else "passenger"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Все анкеты", callback_data=f"motopair_list_{role}")],
        [InlineKeyboardButton(text="Фильтр", callback_data=f"motopair_filter_{role}")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_motopair")],
    ])
    label = "Пилотов" if role == "pilot" else "Двоек"
    await callback.message.edit_text(f"Анкеты {label}:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("motopair_filter_"))
async def cb_motopair_filter_open(callback: CallbackQuery, user=None):
    from src.services.filter_store import get_filter

    if not user:
        await callback.answer()
        return
    role = "pilot" if "pilot" in callback.data else "passenger"
    current = await get_filter(user.id, role)
    label = "Пилотов" if role == "pilot" else "Двоек"
    await callback.message.edit_text(
        f"Фильтр для анкет {label}:\n\nВыбери параметры:",
        reply_markup=get_filter_kb(role, current),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("motopair_fset_"))
async def cb_motopair_filter_set(callback: CallbackQuery, user=None):
    from src.services.filter_store import get_filter, set_filter, clear_filter

    if not user:
        await callback.answer()
        return

    parts = callback.data.replace("motopair_fset_", "").split("_")
    if len(parts) < 2:
        await callback.answer()
        return

    role = parts[0]
    param = parts[1]
    value = parts[2] if len(parts) > 2 else None

    current = await get_filter(user.id, role)
    label = "Пилотов" if role == "pilot" else "Двоек"

    if param == "apply":
        await callback.message.edit_text(
            f"Фильтр применён. Просматривай анкеты {label}.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Смотреть анкеты", callback_data=f"motopair_list_{role}")],
                [InlineKeyboardButton(
                    text="« Назад",
                    callback_data=f"motopair_{'pilots' if role == 'pilot' else 'passengers'}",
                )],
            ]),
        )
        await callback.answer()
        return

    if param == "reset":
        await clear_filter(user.id, role)
        await callback.message.edit_text(
            f"Фильтр сброшен. Анкеты {label}:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Все анкеты", callback_data=f"motopair_list_{role}")],
                [InlineKeyboardButton(text="Фильтр", callback_data=f"motopair_filter_{role}")],
                [InlineKeyboardButton(text="« Назад", callback_data="menu_motopair")],
            ]),
        )
        await callback.answer()
        return

    if param == "gender":
        current["gender"] = value if value != "any" else None
    elif param == "age":
        current["age_max"] = int(value) if value and value != "0" else None
    elif param == "weight":
        current["weight_max"] = int(value) if value and value != "0" else None
    elif param == "height":
        current["height_max"] = int(value) if value and value != "0" else None

    await set_filter(user.id, role, current)
    await callback.message.edit_text(
        f"Фильтр для анкет {label}:\n\nВыбери параметры:",
        reply_markup=get_filter_kb(role, current),
    )
    await callback.answer()


def _parse_motopair_cb(data: str) -> tuple[str, int]:
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
    from src.services.filter_store import get_filter

    if not user:
        await callback.answer("Ошибка: пользователь не определён.", show_alert=True)
        return

    role, offset = _parse_motopair_cb(callback.data)
    filters = await get_filter(user.id, role)
    profile, has_more = await get_next_profile(user.id, role, offset=offset, filters=filters)

    if not profile:
        # Improved empty state with "raise profile" CTA
        await callback.message.edit_text(
            texts.MOTOPAIR_NO_PROFILES,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=texts.MOTOPAIR_RAISE_BTN,
                    callback_data="profile_raise",
                )],
                [InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")],
            ]),
        )
    else:
        text = _format_profile(profile)
        kb = _profile_kb_with_report(str(profile.id), role, offset, has_more)
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


def _profile_kb_with_report(
    profile_id: str,
    role: str,
    offset: int,
    has_more: bool,
) -> InlineKeyboardMarkup:
    """Build profile view keyboard with like/dislike/next + report button."""
    rows = [
        [
            InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like_{profile_id}_{role}"),
            InlineKeyboardButton(text="👎 Пропустить", callback_data=f"dislike_{profile_id}_{role}"),
        ],
    ]
    if has_more:
        rows.append([
            InlineKeyboardButton(
                text="➡️ Следующая",
                callback_data=f"motopair_next_{role}_{offset + 1}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=texts.MOTOPAIR_REPORT_BTN,
            callback_data=f"motopair_report_{profile_id}_{role}",
        )
    ])
    rows.append([InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("motopair_report_"))
async def cb_motopair_report(callback: CallbackQuery, user=None):
    """User reports an offensive/spam profile. Notifies city admin."""
    from src.services.motopair_service import get_user_for_profile, get_profile_info_text
    from src.services.admin_service import get_city_admins
    from src.config import get_settings

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    parts = callback.data.replace("motopair_report_", "").split("_")
    if len(parts) < 2:
        await callback.answer()
        return

    profile_id_str = parts[0]
    role = parts[1]

    try:
        profile_uuid = uuid.UUID(profile_id_str)
    except ValueError:
        await callback.answer()
        return

    target_user = await get_user_for_profile(profile_uuid, role)
    if not target_user:
        await callback.answer("Анкета не найдена.", show_alert=True)
        return

    profile_text, _ = await get_profile_info_text(target_user.id)
    reporter_display = (
        f"@{user.platform_username}" if user.platform_username
        else str(user.platform_user_id)
    )
    reported_display = (
        f"@{target_user.platform_username}" if target_user.platform_username
        else str(target_user.platform_user_id)
    )

    admin_text = texts.MOTOPAIR_REPORT_ADMIN_TEXT.format(
        reporter=reporter_display,
        reported=reported_display,
        profile_text=profile_text,
    )
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=texts.MOTOPAIR_REPORT_BTN_ACCEPT,
            callback_data=f"admin_report_accept_{target_user.id}",
        )],
        [InlineKeyboardButton(
            text=texts.MOTOPAIR_REPORT_BTN_REJECT,
            callback_data=f"admin_report_reject_{target_user.id}",
        )],
    ])

    # Send to city admins + superadmins
    settings = get_settings()
    bot = callback.bot
    notified = False

    if user.city_id:
        admins = await get_city_admins(user.city_id)
        for _, admin_user in admins:
            try:
                await bot.send_message(
                    admin_user.platform_user_id, admin_text, reply_markup=admin_kb
                )
                notified = True
            except Exception as e:
                logger.warning("Cannot notify city admin %s: %s", admin_user.platform_user_id, e)

    for admin_id in settings.superadmin_ids:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_kb)
            notified = True
        except Exception as e:
            logger.warning("Cannot notify superadmin %s: %s", admin_id, e)

    await callback.message.edit_text(
        texts.MOTOPAIR_REPORT_SENT, reply_markup=get_back_to_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_report_accept_"))
async def cb_admin_report_accept(callback: CallbackQuery, user=None):
    """Admin accepts a report — hides the reported profile (soft-ban)."""
    from src.services.motopair_service import hide_profile
    from src.config import get_settings
    from src.services.admin_service import is_city_admin

    settings = get_settings()
    is_sa = callback.from_user.id in settings.superadmin_ids
    is_ca = False
    if not is_sa and user and user.city_id:
        is_ca = await is_city_admin(callback.from_user.id, user.city_id)

    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    uid_str = callback.data.replace("admin_report_accept_", "")
    try:
        uid = uuid.UUID(uid_str)
    except ValueError:
        await callback.answer("Ошибка.")
        return

    await hide_profile(uid)
    await callback.message.edit_text(texts.MOTOPAIR_REPORT_ACCEPTED)
    await callback.answer("Анкета скрыта.")


@router.callback_query(F.data.startswith("admin_report_reject_"))
async def cb_admin_report_reject(callback: CallbackQuery, user=None):
    """Admin rejects a report — profile remains visible."""
    from src.config import get_settings
    from src.services.admin_service import is_city_admin

    settings = get_settings()
    is_sa = callback.from_user.id in settings.superadmin_ids
    is_ca = False
    if not is_sa and user and user.city_id:
        is_ca = await is_city_admin(callback.from_user.id, user.city_id)

    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    await callback.message.edit_text(texts.MOTOPAIR_REPORT_REJECTED)
    await callback.answer("Жалоба отклонена.")


# ── Like / Dislike handlers ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("like_"))
async def cb_like(callback: CallbackQuery, user=None, bot=None):
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
        from_text, _ = await get_profile_info_text(target_user.id)
        to_text, _ = await get_profile_info_text(user.id)

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
                logger.warning(
                    "Cannot notify match user %s: %s", result["target_platform_user_id"], e
                )

        await callback.message.edit_text(
            f"🎉 <b>Взаимный лайк!</b>\n\n{from_text}",
            reply_markup=get_match_kb(
                target_user.platform_username,
                target_user.platform_user_id,
            ),
        )
    else:
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
                logger.warning(
                    "Cannot notify like user %s: %s", result["target_platform_user_id"], e
                )

        await callback.message.edit_text(
            "👍 Лайк отправлен! Если понравишься в ответ — сообщим о совпадении.",
            reply_markup=get_back_to_menu_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("dislike_"))
async def cb_dislike(callback: CallbackQuery, user=None):
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
    text = "👎 Анкета скрыта." if result["blacklisted"] else "👎 Пропущено."
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("reply_like_"))
async def cb_reply_like(callback: CallbackQuery, user=None, bot=None):
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

    from src.models.base import get_session_factory
    session_factory = get_session_factory()
    async with session_factory() as session:
        res = await session.execute(select(User).where(User.id == from_user_uuid))
        from_user = res.scalar_one_or_none()

    if not from_user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return

    result = await process_like(user.id, from_user_uuid, is_like=True)
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
            logger.warning(
                "Cannot notify match reply user %s: %s", from_user.platform_user_id, e
            )

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
    await callback.message.edit_text(
        "Хорошо, пропускаем.", reply_markup=get_back_to_menu_kb()
    )
    await callback.answer()
