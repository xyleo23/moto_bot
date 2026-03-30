"""MotoPair block — find pilot/passenger."""

import uuid

from loguru import logger
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.keyboards.menu import get_back_to_menu_kb
from src.keyboards.motopair import (
    get_like_notification_kb,
    get_match_kb,
    get_filter_kb,
)
from src.models.user import effective_user_id
from src import texts
from src import ui_copy as uc

router = Router()


class CityAdminBlockStates(StatesGroup):
    """FSM for city admin entering a block reason."""

    reason = State()


@router.callback_query(F.data == "menu_motopair")
async def cb_motopair_menu(callback: CallbackQuery, user=None):
    from src.services.subscription import check_subscription_required

    if user and await check_subscription_required(user):
        from src.services.subscription_messages import subscription_required_message

        await callback.message.edit_text(
            await subscription_required_message("motopair_menu"),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Оформить подписку", callback_data="profile_subscribe"
                        )
                    ],
                    [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
                ]
            ),
        )
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=uc.MOTOPAIR_PILOTS, callback_data="motopair_pilots")],
            [
                InlineKeyboardButton(
                    text=uc.MOTOPAIR_PASSENGERS, callback_data="motopair_passengers"
                )
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ]
    )
    await callback.message.edit_text("🏍 Мотопара\n\nВыбери категорию:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.in_(["motopair_pilots", "motopair_passengers"]))
async def cb_motopair_category(callback: CallbackQuery, user=None):
    role = "pilot" if callback.data == "motopair_pilots" else "passenger"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=uc.MOTOPAIR_ALL_CARDS, callback_data=f"motopair_list_{role}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=uc.MOTOPAIR_FILTER, callback_data=f"motopair_filter_{role}"
                )
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_motopair")],
        ]
    )
    cat_title = uc.MOTOPAIR_PILOTS if role == "pilot" else uc.MOTOPAIR_PASSENGERS
    await callback.message.edit_text(f"{cat_title}:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("motopair_filter_"))
async def cb_motopair_filter_open(callback: CallbackQuery, user=None):
    from src.services.filter_store import get_filter

    if not user:
        await callback.answer()
        return
    role = "pilot" if "pilot" in callback.data else "passenger"
    current = await get_filter(effective_user_id(user), role)
    label = "пилотов" if role == "pilot" else "двоек"
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

    eff_uid = effective_user_id(user)
    current = await get_filter(eff_uid, role)
    label = "пилотов" if role == "pilot" else "двоек"

    if param == "apply":
        try:
            await callback.message.edit_text(
                f"Фильтр применён. Просматривай анкеты {label}.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=uc.MOTOPAIR_VIEW_CARDS, callback_data=f"motopair_list_{role}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="« Назад",
                                callback_data=f"motopair_{'pilots' if role == 'pilot' else 'passengers'}",
                            )
                        ],
                    ]
                ),
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                raise
        await callback.answer()
        return

    if param == "reset":
        await clear_filter(eff_uid, role)
        try:
            await callback.message.edit_text(
                f"Фильтр сброшен. Анкеты {label}:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=uc.MOTOPAIR_ALL_CARDS, callback_data=f"motopair_list_{role}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=uc.MOTOPAIR_FILTER, callback_data=f"motopair_filter_{role}"
                            )
                        ],
                        [InlineKeyboardButton(text="« Назад", callback_data="menu_motopair")],
                    ]
                ),
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                raise
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

    await set_filter(eff_uid, role, current)
    try:
        await callback.message.edit_text(
            f"Фильтр для анкет {label}:\n\nВыбери параметры:",
            reply_markup=get_filter_kb(role, current),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
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
    """Текст анкеты в ленте мотопары. Без @username и t.me — контакт только после взаимного лайка."""
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


async def _show_motopair_card_at(message: Message, user, role: str, offset: int) -> None:
    """Показать анкету с индексом offset (после лайка/скипа — та же логика, что у списка)."""
    from src.services.motopair_service import get_next_profile
    from src.services.filter_store import get_filter

    eff_id = effective_user_id(user)
    filters = await get_filter(eff_id, role)
    city_id = getattr(user, "city_id", None)
    profile, has_more = await get_next_profile(
        eff_id, role, offset=offset, filters=filters, viewer_city_id=city_id
    )

    empty_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.MOTOPAIR_RAISE_BTN,
                    callback_data="profile_raise",
                )
            ],
            [InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")],
        ]
    )

    if not profile:
        try:
            await message.edit_text(texts.MOTOPAIR_NO_PROFILES, reply_markup=empty_kb)
        except Exception:
            try:
                await message.delete()
            except Exception:
                pass
            await message.answer(texts.MOTOPAIR_NO_PROFILES, reply_markup=empty_kb)
        return

    text = _format_profile(profile)
    kb = _profile_kb_with_report(str(profile.id), role, offset, has_more)
    if profile.photo_file_id:
        try:
            await message.delete()
            await message.answer_photo(
                photo=profile.photo_file_id,
                caption=text,
                reply_markup=kb,
            )
        except Exception as e:
            logger.warning("_show_motopair_card_at: answer_photo failed, fallback: %s", e)
            try:
                await message.edit_text(text, reply_markup=kb)
            except Exception:
                try:
                    await message.delete()
                except Exception:
                    pass
                await message.answer(text, reply_markup=kb)
    else:
        try:
            await message.edit_text(text, reply_markup=kb)
        except Exception:
            try:
                await message.delete()
            except Exception:
                pass
            await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("motopair_list_") | F.data.startswith("motopair_next_"))
async def cb_motopair_list(callback: CallbackQuery, user=None):
    from src.services.subscription import check_subscription_required

    if not user:
        await callback.answer("Ошибка: пользователь не определён.", show_alert=True)
        return

    if await check_subscription_required(user):
        from src.services.subscription_messages import subscription_required_message

        await callback.message.edit_text(
            await subscription_required_message("motopair_cards"),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Оформить подписку", callback_data="profile_subscribe"
                        ),
                        InlineKeyboardButton(text="◀️ Назад", callback_data="menu_motopair"),
                    ]
                ]
            ),
        )
        await callback.answer()
        return

    role, offset = _parse_motopair_cb(callback.data)
    await _show_motopair_card_at(callback.message, user, role, offset)
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
            InlineKeyboardButton(
                text="❤️ Лайк",
                callback_data=f"like_{profile_id}_{role}_{offset}",
            ),
            InlineKeyboardButton(
                text="👎 Пропустить",
                callback_data=f"dislike_{profile_id}_{role}_{offset}",
            ),
        ],
    ]
    if has_more:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➡️ Следующая",
                    callback_data=f"motopair_next_{role}_{offset + 1}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=texts.MOTOPAIR_REPORT_BTN,
                callback_data=f"motopair_report_{profile_id}_{role}",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("motopair_report_"))
async def cb_motopair_report(callback: CallbackQuery, user=None):
    """User reports an offensive/spam profile. Notifies city admin."""
    from src.services.motopair_service import get_user_for_profile, get_profile_info_text

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    rest = callback.data.replace("motopair_report_", "", 1)
    if "_" not in rest:
        await callback.answer()
        return
    profile_id_str, role = rest.rsplit("_", 1)

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
        f"@{user.platform_username}" if user.platform_username else str(user.platform_user_id)
    )
    reported_display = (
        f"@{target_user.platform_username}"
        if target_user.platform_username
        else str(target_user.platform_user_id)
    )

    admin_text = texts.MOTOPAIR_REPORT_ADMIN_TEXT.format(
        reporter=reporter_display,
        reported=reported_display,
        profile_text=profile_text,
    )
    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.MOTOPAIR_REPORT_BTN_ACCEPT,
                    callback_data=f"admin_report_accept_{target_user.id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=texts.MOTOPAIR_REPORT_BTN_BLOCK,
                    callback_data=f"admin_report_block_{target_user.id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=texts.MOTOPAIR_REPORT_BTN_REJECT,
                    callback_data=f"admin_report_reject_{target_user.id}",
                )
            ],
        ]
    )

    # Send to city admins + superadmins
    bot = callback.bot

    from src.services.admin_multichannel_notify import (
        notify_city_admins_multichannel,
        notify_superadmins_multichannel,
    )
    from src.services.broadcast import get_max_adapter

    _max_a = get_max_adapter()
    if user.city_id:
        await notify_city_admins_multichannel(
            user.city_id,
            admin_text,
            telegram_markup=admin_kb,
            telegram_bot=bot,
            max_adapter=_max_a,
        )
    await notify_superadmins_multichannel(
        admin_text,
        telegram_markup=admin_kb,
        telegram_bot=bot,
        max_adapter=_max_a,
    )

    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=texts.MOTOPAIR_REPORT_SENT,
                reply_markup=get_back_to_menu_kb(),
            )
        else:
            await callback.message.edit_text(
                texts.MOTOPAIR_REPORT_SENT, reply_markup=get_back_to_menu_kb()
            )
    except Exception as e:
        logger.warning("motopair_report: edit failed: %s", e)
        await callback.message.answer(
            texts.MOTOPAIR_REPORT_SENT, reply_markup=get_back_to_menu_kb()
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_report_accept_"))
async def cb_admin_report_accept(callback: CallbackQuery, user=None):
    """Admin accepts a report — hides the reported profile (soft-ban)."""
    from src.services.motopair_service import hide_profile
    from src.config import get_settings
    from src.services.admin_service import is_city_admin, get_user_by_id

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

    if is_ca and user and user.city_id:
        target = await get_user_by_id(uid)
        if not target or target.city_id != user.city_id:
            await callback.answer("Доступ запрещён.", show_alert=True)
            return

    await hide_profile(uid)
    await callback.message.edit_text(texts.MOTOPAIR_REPORT_ACCEPTED)
    await callback.answer("Анкета скрыта.")


@router.callback_query(F.data.startswith("admin_report_reject_"))
async def cb_admin_report_reject(callback: CallbackQuery, user=None):
    """Admin rejects a report — profile remains visible."""
    from src.config import get_settings
    from src.services.admin_service import is_city_admin, get_user_by_id

    settings = get_settings()
    is_sa = callback.from_user.id in settings.superadmin_ids
    is_ca = False
    if not is_sa and user and user.city_id:
        is_ca = await is_city_admin(callback.from_user.id, user.city_id)

    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    uid_str = callback.data.replace("admin_report_reject_", "")
    try:
        uid = uuid.UUID(uid_str)
    except ValueError:
        await callback.answer("Ошибка.")
        return
    if is_ca and user and user.city_id:
        target = await get_user_by_id(uid)
        if not target or target.city_id != user.city_id:
            await callback.answer("Доступ запрещён.", show_alert=True)
            return

    await callback.message.edit_text(texts.MOTOPAIR_REPORT_REJECTED)
    await callback.answer("Жалоба отклонена.")


@router.callback_query(F.data.startswith("admin_report_block_"))
async def cb_admin_report_block(callback: CallbackQuery, state: FSMContext, user=None):
    """Admin initiates full account block for the reported user."""
    from src.config import get_settings
    from src.services.admin_service import is_city_admin, get_user_by_id

    settings = get_settings()
    is_sa = callback.from_user.id in settings.superadmin_ids
    is_ca = False
    if not is_sa and user and user.city_id:
        is_ca = await is_city_admin(callback.from_user.id, user.city_id)

    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    uid_str = callback.data.replace("admin_report_block_", "")
    try:
        uid = uuid.UUID(uid_str)
    except ValueError:
        await callback.answer("Ошибка.")
        return

    if is_ca and user and user.city_id:
        target = await get_user_by_id(uid)
        if not target or target.city_id != user.city_id:
            await callback.answer("Доступ запрещён.", show_alert=True)
            return

    await state.set_state(CityAdminBlockStates.reason)
    await state.update_data(block_target_user_id=str(uid))
    await callback.message.edit_text(
        "Введи причину блокировки пользователя (будет видна в уведомлении):"
    )
    await callback.answer()


@router.message(CityAdminBlockStates.reason, F.text)
async def city_admin_block_reason(message: Message, state: FSMContext, user=None):
    """Admin entered block reason — block the user and notify superadmin."""
    from src.config import get_settings
    from src.services.admin_service import is_city_admin, block_user, get_user_by_id
    from src.models.base import get_session_factory
    from src.models.user import User
    from sqlalchemy import select

    settings = get_settings()
    is_sa = message.from_user.id in settings.superadmin_ids
    is_ca = False
    if not is_sa and user and user.city_id:
        is_ca = await is_city_admin(message.from_user.id, user.city_id)

    if not is_sa and not is_ca:
        await state.clear()
        return

    data = await state.get_data()
    target_id_str = data.get("block_target_user_id")
    await state.clear()

    if not target_id_str:
        await message.answer("Ошибка: пользователь не найден.")
        return

    try:
        target_uuid = uuid.UUID(target_id_str)
    except ValueError:
        await message.answer("Ошибка ID пользователя.")
        return

    if is_ca and user and user.city_id:
        target_user = await get_user_by_id(target_uuid)
        if not target_user or target_user.city_id != user.city_id:
            await message.answer("Доступ запрещён.")
            return

    reason = message.text.strip()[:500]

    # Block the user account
    await block_user(target_uuid, reason=reason)

    # Get target user info for notifications
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(User).where(User.id == target_uuid))
        target = r.scalar_one_or_none()

    if target:
        admin_display = (
            f"@{user.platform_username}"
            if user and user.platform_username
            else str(message.from_user.id)
        )
        target_display = (
            f"@{target.platform_username}"
            if target.platform_username
            else str(target.platform_user_id)
        )

        nmsg = texts.ADMIN_BLOCK_NOTIFY_SUPERADMIN.format(
            admin=admin_display,
            user=target_display,
            reason=reason,
        )
        from src.services.admin_multichannel_notify import notify_superadmins_plain
        from src.services.broadcast import get_max_adapter
        from src.services.cross_platform_notify import send_text_to_all_identities

        await notify_superadmins_plain(
            nmsg,
            telegram_bot=message.bot,
            max_adapter=get_max_adapter(),
        )

        await send_text_to_all_identities(
            target_uuid,
            texts.ADMIN_BLOCK_USER_NOTIFICATION.format(reason=reason),
            telegram_bot=message.bot,
            max_adapter=get_max_adapter(),
            parse_mode="HTML",
        )

    await message.answer(
        texts.ADMIN_BLOCK_DONE,
        reply_markup=get_back_to_menu_kb(),
    )


# ── Like / Dislike handlers ───────────────────────────────────────────────────


@router.callback_query(F.data.startswith("like_"))
async def cb_like(callback: CallbackQuery, user=None, bot=None):
    from src.services.motopair_service import (
        process_like,
        get_user_for_profile,
        get_profile_info_text,
        parse_motopair_like_callback,
    )

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    parsed = parse_motopair_like_callback(callback.data)
    if not parsed:
        await callback.answer()
        return
    profile_uuid, role, list_offset, _is_like = parsed

    target_user = await get_user_for_profile(profile_uuid, role)
    if not target_user:
        await callback.answer("Анкета не найдена.", show_alert=True)
        return

    eff_from = effective_user_id(user)
    result = await process_like(eff_from, target_user.id, is_like=True)

    if result["matched"]:
        from src.services.activity_log_service import log_event
        from src.models.activity_log import ActivityEventType

        await log_event(
            ActivityEventType.MUTUAL_LIKE,
            user_id=eff_from,
            data={"target_user_id": str(target_user.id), "from_user_id": str(eff_from)},
        )
        from_text, _ = await get_profile_info_text(target_user.id)
        to_text, liker_photo = await get_profile_info_text(eff_from)
        from src.services.motopair_service import get_contact_footer_html

        if bot:
            from src.services.notification_templates import get_template
            from src.services.cross_platform_notify import send_text_to_all_identities
            from src.services.broadcast import get_max_adapter
            from src.keyboards.shared import get_match_max_rows
            from src.services.motopair_service import contact_footer_html_for_max_notifications

            msg_target_base = await get_template("template_mutual_like_target", profile=to_text)
            # Include contact info for TG (phone + username as HTML footer in message)
            liker_contact = await get_contact_footer_html(eff_from)
            msg_target_tg = msg_target_base + liker_contact
            tg_mk = get_match_kb(callback.from_user.username, callback.from_user.id)
            max_suffix = await contact_footer_html_for_max_notifications(eff_from)
            canon_target = effective_user_id(target_user)
            await send_text_to_all_identities(
                canon_target,
                msg_target_tg,
                telegram_bot=bot,
                max_adapter=get_max_adapter(),
                tg_reply_markup=tg_mk,
                max_kb_rows=get_match_max_rows(callback.from_user.username),
                max_extra_html=max_suffix,
                photo_file_id=liker_photo,
            )

        from src.services.notification_templates import get_template

        msg_self_base = await get_template("template_mutual_like_self", profile=from_text)
        # Include contact info for the liker (phone + link to matched user)
        matched_contact = await get_contact_footer_html(target_user.id)
        msg_self = msg_self_base + matched_contact
        mk = get_match_kb(
            target_user.platform_username,
            target_user.platform_user_id,
        )
        try:
            if callback.message.photo:
                await callback.message.edit_caption(
                    caption=msg_self,
                    reply_markup=mk,
                    parse_mode="HTML",
                )
            else:
                await callback.message.edit_text(msg_self, reply_markup=mk, parse_mode="HTML")
        except Exception as e:
            logger.warning("cb_like mutual: edit failed: %s", e)
            await callback.message.answer(msg_self, reply_markup=mk, parse_mode="HTML")
    else:
        if bot:
            from_text, from_photo = await get_profile_info_text(eff_from)
            from src.services.notification_templates import get_template
            from src.services.cross_platform_notify import notify_like_received_cross_platform
            from src.services.broadcast import get_max_adapter
            from src.keyboards.shared import get_like_notification_max_rows
            from src.services.motopair_service import contact_footer_html_for_max_notifications

            notify_text = await get_template("template_like_received", profile=from_text)
            kb = get_like_notification_kb(str(eff_from))
            max_suffix = await contact_footer_html_for_max_notifications(eff_from)
            await notify_like_received_cross_platform(
                effective_user_id(target_user),
                notify_text,
                from_photo,
                telegram_bot=bot,
                max_adapter=get_max_adapter(),
                tg_reply_markup=kb,
                max_kb_rows=get_like_notification_max_rows(str(eff_from)),
                max_extra_html=max_suffix,
            )

        await _show_motopair_card_at(callback.message, user, role, list_offset)
    await callback.answer()


@router.callback_query(F.data.startswith("dislike_"))
async def cb_dislike(callback: CallbackQuery, user=None):
    from src.services.motopair_service import (
        process_like,
        get_user_for_profile,
        parse_motopair_like_callback,
    )

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    parsed = parse_motopair_like_callback(callback.data)
    if not parsed:
        await callback.answer()
        return
    profile_uuid, role, list_offset, _ = parsed

    target_user = await get_user_for_profile(profile_uuid, role)
    if not target_user:
        await callback.answer("Анкета не найдена.", show_alert=True)
        return

    result = await process_like(effective_user_id(user), target_user.id, is_like=False)
    next_offset = list_offset if result["blacklisted"] else list_offset + 1
    await _show_motopair_card_at(callback.message, user, role, next_offset)
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

    from_canon = effective_user_id(from_user)
    res = await process_like(effective_user_id(user), from_canon, is_like=True)
    if not res.get("matched"):
        await callback.answer("Нужно дождаться взаимного лайка.", show_alert=True)
        return
    from_text, _ = await get_profile_info_text(from_canon)
    from src.services.motopair_service import get_contact_footer_html

    match_kb_target = get_match_kb(user.platform_username, user.platform_user_id)
    match_kb_self = get_match_kb(from_user.platform_username, from_user.platform_user_id)

    replier_eff = effective_user_id(user)
    if bot:
        to_text, replier_photo = await get_profile_info_text(replier_eff)
        from src.services.notification_templates import get_template
        from src.services.cross_platform_notify import send_text_to_all_identities
        from src.services.broadcast import get_max_adapter
        from src.keyboards.shared import get_match_max_rows
        from src.services.motopair_service import contact_footer_html_for_max_notifications

        msg_base = await get_template("template_mutual_like_reply", profile=to_text)
        replier_contact = await get_contact_footer_html(replier_eff)
        msg = msg_base + replier_contact
        max_suffix = await contact_footer_html_for_max_notifications(replier_eff)
        await send_text_to_all_identities(
            from_canon,
            msg,
            telegram_bot=bot,
            max_adapter=get_max_adapter(),
            tg_reply_markup=match_kb_target,
            max_kb_rows=get_match_max_rows(user.platform_username),
            max_extra_html=max_suffix,
            photo_file_id=replier_photo,
        )

    from src.services.notification_templates import get_template

    text_self_base = await get_template("template_mutual_like_self", profile=from_text)
    from_contact = await get_contact_footer_html(from_canon)
    text_self = text_self_base + from_contact
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=text_self,
                reply_markup=match_kb_self,
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                text_self,
                reply_markup=match_kb_self,
                parse_mode="HTML",
            )
    except Exception as e:
        logger.warning("cb_reply_like: edit failed, sending new message: %s", e)
        try:
            await callback.message.answer(text_self, reply_markup=match_kb_self, parse_mode="HTML")
        except TelegramBadRequest as e2:
            desc = (e2.message or "") if hasattr(e2, "message") else str(e2)
            if "BUTTON_USER_PRIVACY_RESTRICTED" in desc:
                await callback.message.answer(text_self, parse_mode="HTML")
            else:
                raise
    await callback.answer()


@router.callback_query(F.data.startswith("reply_skip_"))
async def cb_reply_skip(callback: CallbackQuery, user=None):
    text = "Хорошо, пропускаем."
    kb = get_back_to_menu_kb()
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=kb)
        else:
            await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logger.warning("cb_reply_skip: edit failed: %s", e)
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()
