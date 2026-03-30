"""MAX bot runner — dispatches updates to handlers (with full registration FSM)."""

import re
import uuid
from datetime import datetime
from html import escape

from loguru import logger

from src.config import get_settings
from src.platforms.max_adapter import MaxAdapter
from src.platforms.max_parser import parse_updates
from src.platforms.base import (
    Button,
    ButtonType,
    IncomingMessage,
    IncomingCallback,
    IncomingContact,
    IncomingLocation,
    IncomingPhoto,
    KeyboardRow,
)
from src.services.user import (
    get_or_create_user,
    has_profile,
    delete_user_data,
    sync_city_across_linked_identities,
)
from src.services import max_registration_state as reg_state
from src.services.registration_service import (
    finish_pilot_registration,
    finish_passenger_registration,
    MaxCrossLinkKind,
    apply_max_early_account_link,
    check_max_registration_cross_link,
    mask_registration_phone_hint,
    user_role_display_ru,
)
from src.models.user import User, UserRole, Platform, effective_user_id
from src.models.base import get_session_factory
from sqlalchemy import select
from src.utils.yandex_maps import (
    format_sos_broadcast_map_html,
    is_plausible_gps_coordinate,
    yandex_maps_point_url,
)
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
    get_max_my_event_detail_rows,
    get_max_event_edit_menu_rows,
    get_welcome_city_rows_for_cities,
    get_welcome_role_rows,
    get_max_documents_menu_rows,
    get_max_delete_confirm_rows,
    get_match_max_rows,
    get_like_notification_max_rows,
    get_main_menu_shortcut_row,
    get_max_seeking_confirm_rows,
)
from src.utils.progress import progress_prefix
from src import texts
from src.usecases.payment_metadata import donate_metadata, subscription_metadata
from src.utils.text_format import split_plain_text_chunks

# Module-level Telegram bot reference for cross-platform SOS broadcasts.
# Injected at startup via set_tg_bot() when platform=both or platform=telegram.
_tg_bot = None


def set_tg_bot(bot) -> None:
    """Inject the Telegram bot instance for cross-platform SOS broadcasts."""
    global _tg_bot
    _tg_bot = bot


def _get_tg_bot():
    return _tg_bot


# ── Step counts ───────────────────────────────────────────────────────────────
PILOT_TOTAL_STEPS = 11
PASSENGER_TOTAL_STEPS = 9

# ── Registration date parser (same logic as registration.py) ──────────────────
RUSSIAN_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

# MAX message-type inline buttons: label is sent as chat text — map to command keys
MAX_MENU_MESSAGE_TO_CMD: dict[str, str] = {
    "🚨 SOS": "sos",
    "🏍 Мотопара": "motopair",
    "📇 Полезные контакты": "contacts",
    "📅 Мероприятия": "events",
    "👤 Мой профиль": "profile",
    "ℹ️ О нас": "about",
    "📄 Документы": "documents",
}


async def _main_menu_rows_for(user) -> list:
    """Главное меню MAX с кнопкой админки для суперадмина и админа города."""
    from src.services.admin_service import max_user_should_see_admin_menu

    show_admin = await max_user_should_see_admin_menu(user)
    return get_main_menu_rows(show_admin=show_admin)


async def _max_send_legal_chunks(adapter: MaxAdapter, chat_id: str, content: str) -> None:
    """Отправить длинный юридический текст частями (как в Telegram)."""
    from src.handlers.legal import _chunk_text

    for chunk in _chunk_text(content):
        await adapter.send_message(chat_id, chunk, None)


def _parse_russian_date(text: str):
    text = (text or "").strip()
    m = re.search(r"(\d{1,2})\s+(\S+)\s+(\d{4})", text, re.IGNORECASE)
    if not m:
        return None
    day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    month_num = RUSSIAN_MONTHS.get(month_name)
    if not month_num:
        return None
    try:
        return datetime(year, month_num, day).date()
    except ValueError:
        return None


def _parse_date(text: str):
    text = (text or "").strip()
    m_year = re.match(r"^(\d{4})$", text)
    if m_year:
        y = int(m_year.group(1))
        if 1970 <= y <= 2030:
            return datetime(y, 1, 1).date()
    m_my = re.match(r"^(\d{1,2})[./](\d{4})$", text)
    if m_my:
        month, year = int(m_my.group(1)), int(m_my.group(2))
        if 1 <= month <= 12 and 1970 <= year <= 2030:
            try:
                return datetime(year, month, 1).date()
            except ValueError:
                pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(f"{text[:2]}.{text[2:4]}.{text[4:]}", "%d.%m.%Y").date()
        except ValueError:
            pass
    return _parse_russian_date(text)


# ── Keyboard builders for registration ───────────────────────────────────────


def _pilot_gender_kb() -> list[KeyboardRow]:
    return [
        [
            Button("Муж", payload="max_reg_gender_male"),
            Button("Жен", payload="max_reg_gender_female"),
        ]
    ]


def _pilot_style_kb() -> list[KeyboardRow]:
    return [
        [Button("Спокойный", payload="max_reg_style_calm")],
        [Button("Динамичный", payload="max_reg_style_aggressive")],
        [Button("Смешанный", payload="max_reg_style_mixed")],
    ]


def _pilot_photo_kb() -> list[KeyboardRow]:
    return [[Button(texts.BTN_SKIP, payload="max_reg_skip_photo")]]


def _pilot_about_kb() -> list[KeyboardRow]:
    return [[Button(texts.BTN_SKIP, payload="max_reg_skip_about")]]


def _pilot_preview_kb() -> list[KeyboardRow]:
    return [
        [Button(texts.PROFILE_BTN_SAVE, payload="max_reg_preview_save")],
        [Button(texts.PROFILE_BTN_EDIT, payload="max_reg_preview_edit")],
    ]


def _pax_gender_kb() -> list[KeyboardRow]:
    return [
        [
            Button("Муж", payload="max_reg_pax_gender_male"),
            Button("Жен", payload="max_reg_pax_gender_female"),
        ]
    ]


def _pax_style_kb() -> list[KeyboardRow]:
    return [
        [Button("Спокойный", payload="max_reg_pax_style_calm")],
        [Button("Динамичный", payload="max_reg_pax_style_dynamic")],
        [Button("Смешанный", payload="max_reg_pax_style_mixed")],
    ]


def _pax_photo_kb() -> list[KeyboardRow]:
    return [[Button(texts.BTN_SKIP, payload="max_reg_pax_skip_photo")]]


def _pax_about_kb() -> list[KeyboardRow]:
    return [[Button(texts.BTN_SKIP, payload="max_reg_pax_skip_about")]]


def _pax_preview_kb() -> list[KeyboardRow]:
    return [
        [Button(texts.PROFILE_BTN_SAVE, payload="max_reg_pax_preview_save")],
        [Button(texts.PROFILE_BTN_EDIT, payload="max_reg_pax_preview_edit")],
    ]


def _cancel_kb() -> list[KeyboardRow]:
    return [[Button("❌ Отменить", payload="max_reg_cancel")]]


def _cross_link_confirm_kb() -> list[KeyboardRow]:
    return [
        [Button("✅ Да, это я", payload="max_reg_cross_link_yes")],
        [Button("❌ Нет, другой номер", payload="max_reg_cross_link_no")],
    ]


def _max_registration_text_to_callback(state: str, text: str) -> str | None:
    """MAX иногда шлёт текст кнопки (message_created) вместо message_callback — эмулируем payload."""
    if not text or not isinstance(state, str):
        return None
    t = text.strip()
    if not t:
        return None

    if t == "❌ Отменить" and not state.startswith("admin:"):
        return "max_reg_cancel"

    if state == "pilot:gender":
        if t == "Муж":
            return "max_reg_gender_male"
        if t == "Жен":
            return "max_reg_gender_female"
        return None

    if state == "pilot:driving_style":
        if t == "Спокойный":
            return "max_reg_style_calm"
        if t == "Динамичный":
            return "max_reg_style_aggressive"
        if t == "Смешанный":
            return "max_reg_style_mixed"
        return None

    if state == "passenger:gender":
        if t == "Муж":
            return "max_reg_pax_gender_male"
        if t == "Жен":
            return "max_reg_pax_gender_female"
        return None

    if state == "passenger:preferred_style":
        if t == "Спокойный":
            return "max_reg_pax_style_calm"
        if t == "Динамичный":
            return "max_reg_pax_style_dynamic"
        if t == "Смешанный":
            return "max_reg_pax_style_mixed"
        return None

    if state == "pilot:photo" and t == texts.BTN_SKIP:
        return "max_reg_skip_photo"
    if state == "pilot:about" and t == texts.BTN_SKIP:
        return "max_reg_skip_about"
    if state == "pilot:preview":
        if t == texts.PROFILE_BTN_SAVE:
            return "max_reg_preview_save"
        if t == texts.PROFILE_BTN_EDIT:
            return "max_reg_preview_edit"
        return None

    if state == "passenger:photo" and t == texts.BTN_SKIP:
        return "max_reg_pax_skip_photo"
    if state == "passenger:about" and t == texts.BTN_SKIP:
        return "max_reg_pax_skip_about"
    if state == "passenger:preview":
        if t == texts.PROFILE_BTN_SAVE:
            return "max_reg_pax_preview_save"
        if t == texts.PROFILE_BTN_EDIT:
            return "max_reg_pax_preview_edit"
        return None

    if state in ("pilot:cross_link_confirm", "passenger:cross_link_confirm"):
        if t == "✅ Да, это я":
            return "max_reg_cross_link_yes"
        if t == "❌ Нет, другой номер":
            return "max_reg_cross_link_no"
        return None

    if state == "sos:comment" and t == texts.BTN_SKIP:
        return "sos_skip_comment"

    if state == "event_create:preview":
        if t == texts.PROFILE_BTN_SAVE:
            return "max_evcreate_preview_save"
        if t == texts.PROFILE_BTN_EDIT:
            return "max_evcreate_preview_edit"
        if t == texts.EVENT_CREATE_BTN_CANCEL:
            return "max_evcreate_preview_cancel"
        return None

    return None


def _strip_cross_link_keys(data: dict) -> dict:
    return {k: v for k, v in data.items() if not str(k).startswith("cross_link_")}


async def _advance_max_reg_past_phone(
    adapter: MaxAdapter, chat_id: str, user_id: int, data: dict, *, is_pilot: bool
) -> None:
    if is_pilot:
        await reg_state.set_state(user_id, "pilot:age", data)
        logger.info("MAX reg: user_id=%s state=pilot:age", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(3, PILOT_TOTAL_STEPS) + texts.REG_ASK_AGE,
            _cancel_kb(),
        )
    else:
        await reg_state.set_state(user_id, "passenger:age", data)
        logger.info("MAX reg: user_id=%s state=passenger:age", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(3, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_AGE,
            _cancel_kb(),
        )


async def _process_max_reg_phone_captured(
    adapter: MaxAdapter, chat_id: str, user_id: int, data: dict, *, is_pilot: bool
) -> None:
    role = UserRole.PILOT if is_pilot else UserRole.PASSENGER
    chk = await check_max_registration_cross_link(
        data.get("phone", ""),
        max_platform_user_id=user_id,
        registering_as=role,
    )
    if chk.kind == MaxCrossLinkKind.NONE:
        await _advance_max_reg_past_phone(adapter, chat_id, user_id, data, is_pilot=is_pilot)
        return
    if chk.kind == MaxCrossLinkKind.ROLE_MISMATCH:
        clean = _strip_cross_link_keys(dict(data))
        clean.pop("phone", None)
        st = "pilot:phone" if is_pilot else "passenger:phone"
        await reg_state.set_state(user_id, st, clean)
        await adapter.send_message(
            chat_id,
            texts.REG_CROSS_LINK_ROLE_MISMATCH.format(
                platform=chk.platform_label,
                existing_role=user_role_display_ru(chk.existing_role),
                registering_role=user_role_display_ru(role),
            ),
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return
    assert chk.canonical_user_id is not None
    data = dict(data)
    data["cross_link_canonical_id"] = str(chk.canonical_user_id)
    data["cross_link_display_name"] = chk.display_name
    data["cross_link_platform_label"] = chk.platform_label
    confirm_state = "pilot:cross_link_confirm" if is_pilot else "passenger:cross_link_confirm"
    await reg_state.set_state(user_id, confirm_state, data)
    phone_masked = mask_registration_phone_hint(str(data.get("phone", "")))
    await adapter.send_message(
        chat_id,
        texts.REG_CROSS_LINK_ASK.format(
            phone_masked=phone_masked,
            platform=chk.platform_label,
            name=chk.display_name,
            role_label=user_role_display_ru(chk.existing_role),
        ),
        _cross_link_confirm_kb(),
    )


# ── Preview text builders ─────────────────────────────────────────────────────


def _build_pilot_preview(data: dict) -> str:
    style_labels = {"calm": "Спокойный", "aggressive": "Динамичный", "mixed": "Смешанный"}
    gender_labels = {"male": "Муж", "female": "Жен", "other": "Другое"}
    return (
        texts.PROFILE_PREVIEW_HEADER
        + f"🏍 <b>{data.get('name')}</b>\n"
        + f"Возраст: {data.get('age')} лет\n"
        + f"Пол: {gender_labels.get(str(data.get('gender', '')), '—')}\n"
        + f"Мотоцикл: {data.get('bike_brand')} {data.get('bike_model')}, {data.get('engine_cc')} см³\n"
        + f"Стаж с: {data.get('driving_since') or '—'}\n"
        + f"Стиль: {style_labels.get(str(data.get('driving_style', '')), '—')}\n"
        + f"О себе: {data.get('about') or '—'}\n\n"
        + texts.PROFILE_PREVIEW_CONFIRM
    )


def _build_passenger_preview(data: dict) -> str:
    style_labels = {"calm": "Спокойный", "dynamic": "Динамичный", "mixed": "Смешанный"}
    gender_labels = {"male": "Муж", "female": "Жен", "other": "Другое"}
    return (
        texts.PROFILE_PREVIEW_HEADER
        + f"👤 <b>{data.get('name')}</b>\n"
        + f"Возраст: {data.get('age')} лет\n"
        + f"Пол: {gender_labels.get(str(data.get('gender', '')), '—')}\n"
        + f"Вес: {data.get('weight')} кг, Рост: {data.get('height')} см\n"
        + f"Стиль: {style_labels.get(str(data.get('preferred_style', '')), '—')}\n"
        + f"О себе: {data.get('about') or '—'}\n\n"
        + texts.PROFILE_PREVIEW_CONFIRM
    )


# ── Profile formatter ─────────────────────────────────────────────────────────


def _format_profile_max(profile) -> str:
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


async def _max_send_photo_caption_keyboard(
    adapter: MaxAdapter,
    chat_id: str,
    stored_photo_id: str | None,
    caption: str,
    keyboard,
    *,
    log_ctx: str = "max_photo",
) -> None:
    """Отправить фото в MAX: id может быть MAX token (регистрация в MAX) или Telegram file_id."""
    if not stored_photo_id or not str(stored_photo_id).strip():
        logger.info(
            "{}: skip (no photo id) chat_id={} caption_len={}",
            log_ctx,
            chat_id,
            len(caption or ""),
        )
        await adapter.send_message(chat_id, caption, keyboard)
        return
    pid = str(stored_photo_id).strip()
    ref_hint = f"{pid[:16]}…(len={len(pid)})" if len(pid) > 16 else pid
    logger.info(
        "{}: try_direct chat_id={} ref_hint={} tg_bot_registered={}",
        log_ctx,
        chat_id,
        ref_hint,
        _get_tg_bot() is not None,
    )
    try:
        await adapter.send_photo(chat_id, pid, caption=caption, keyboard=keyboard)
        logger.info("{}: direct_send_ok chat_id={}", log_ctx, chat_id)
        return
    except Exception as e:
        logger.warning(
            "{}: direct_send_fail chat_id={} err={}",
            log_ctx,
            chat_id,
            str(e)[:400],
        )
    tg_bot = _get_tg_bot()
    if tg_bot:
        try:
            max_token = await adapter.import_photo_from_telegram(tg_bot, pid)
            if max_token:
                await adapter.send_photo(chat_id, max_token, caption=caption, keyboard=keyboard)
                logger.info("{}: tg_bridge_ok chat_id={}", log_ctx, chat_id)
                return
            logger.warning("{}: tg_bridge_no_token chat_id={}", log_ctx, chat_id)
        except Exception as e:
            logger.warning("{}: tg_bridge_exception chat_id={} err={}", log_ctx, chat_id, e)
    else:
        logger.warning("{}: no_tg_bot_for_bridge chat_id={}", log_ctx, chat_id)
    logger.warning("{}: fallback_text_only chat_id={}", log_ctx, chat_id)
    await adapter.send_message(chat_id, caption, keyboard)


# ── Registration FSM — step handlers ─────────────────────────────────────────


async def _start_pilot_registration(adapter: MaxAdapter, chat_id: str, user_id: int) -> None:
    """Begin pilot registration — ask for name (step 1)."""
    await reg_state.set_state(user_id, "pilot:name", {})
    logger.info("MAX reg: user_id=%s state=pilot:name", user_id)
    await adapter.send_message(
        chat_id,
        progress_prefix(1, PILOT_TOTAL_STEPS) + texts.REG_ASK_NAME,
        _cancel_kb(),
    )


async def _start_passenger_registration(adapter: MaxAdapter, chat_id: str, user_id: int) -> None:
    """Begin passenger registration — ask for name (step 1)."""
    await reg_state.set_state(user_id, "passenger:name", {})
    logger.info("MAX reg: user_id=%s state=passenger:name", user_id)
    await adapter.send_message(
        chat_id,
        progress_prefix(1, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_NAME,
        _cancel_kb(),
    )


async def _max_profile_phone_change_text(
    adapter: MaxAdapter, chat_id: str, user_id: int, text: str
) -> None:
    """Ввод нового телефона в MAX — заявка суперадмину (как в Telegram)."""
    from sqlalchemy import select
    from src.models.base import get_session_factory
    from src.models.phone_change_request import PhoneChangeRequest, PhoneChangeStatus
    from src.models.profile_pilot import ProfilePilot
    from src.models.profile_passenger import ProfilePassenger
    from src.models.user import effective_user_id
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    new_phone = (text or "").strip()
    if not new_phone.startswith("+") or len(new_phone) < 10:
        await adapter.send_message(
            chat_id,
            "Введи номер в формате +79991234567.",
            [[Button("« Отмена", payload="menu_profile")], get_main_menu_shortcut_row()],
        )
        return

    user = await get_or_create_user(platform="max", platform_user_id=user_id)
    if not user:
        await reg_state.clear_state(user_id)
        await adapter.send_message(chat_id, "Ошибка. Нажми /start.", get_back_to_menu_rows())
        return

    canon = effective_user_id(user)
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await session.execute(
            select(PhoneChangeRequest).where(
                PhoneChangeRequest.user_id == canon,
                PhoneChangeRequest.status == PhoneChangeStatus.PENDING,
            )
        )
        if existing.scalar_one_or_none():
            await reg_state.clear_state(user_id)
            await adapter.send_message(
                chat_id,
                "У тебя уже есть активная заявка на смену телефона.",
                [[Button("👤 Мой профиль", payload="menu_profile")], get_main_menu_shortcut_row()],
            )
            return

        pilot = await session.execute(select(ProfilePilot).where(ProfilePilot.user_id == canon))
        p = pilot.scalar_one_or_none()
        old_phone = p.phone if p else None
        if not old_phone:
            pax = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == canon)
            )
            pp = pax.scalar_one_or_none()
            old_phone = pp.phone if pp else "—"

        req = PhoneChangeRequest(user_id=canon, new_phone=new_phone[:20])
        session.add(req)
        await session.commit()
        req_id = str(req.id)

    await reg_state.clear_state(user_id)
    tg_bot = _get_tg_bot()
    user_display = (
        f"@{user.platform_username}" if user.platform_username else str(user.platform_user_id)
    )
    admin_text = (
        f"📱 <b>Запрос на смену телефона</b> (MAX)\n\n"
        f"Пользователь: {user_display}\n"
        f"Текущий номер: {old_phone}\n"
        f"Новый номер: <b>{new_phone}</b>\n\n"
        f"Подтвердить смену?"
    )
    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.PHONE_CHANGE_BTN_CONFIRM,
                    callback_data=f"admin_phone_approve_{req_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=texts.PHONE_CHANGE_BTN_REJECT, callback_data=f"admin_phone_reject_{req_id}"
                )
            ],
        ]
    )
    from src.services.admin_multichannel_notify import notify_superadmins_multichannel
    from src.services.broadcast import get_max_adapter

    await notify_superadmins_multichannel(
        admin_text,
        telegram_markup=admin_kb,
        telegram_bot=tg_bot,
        max_adapter=get_max_adapter() or adapter,
    )

    await adapter.send_message(
        chat_id,
        texts.PHONE_CHANGE_REQUEST_SENT,
        [[Button("👤 Мой профиль", payload="menu_profile")], get_main_menu_shortcut_row()],
    )


async def _handle_fsm_message(
    adapter: MaxAdapter, chat_id: str, user_id: int, text: str, fsm: dict
) -> None:
    """Route incoming text to the correct FSM step handler."""
    state = fsm["state"]
    data = fsm["data"]

    if isinstance(state, str) and state.startswith("admin:contact"):
        from src.max_admin_contacts import handle_max_contact_fsm_text

        await handle_max_contact_fsm_text(adapter, chat_id, user_id, text, fsm)
        return

    if isinstance(state, str) and state.startswith("admin:"):
        from src.max_admin_panel import handle_max_admin_fsm_text

        await handle_max_admin_fsm_text(adapter, chat_id, user_id, text, fsm)
        return

    if state == "profile:phone_change":
        await _max_profile_phone_change_text(adapter, chat_id, user_id, text)
        return

    synth_cb = _max_registration_text_to_callback(state, text)
    if synth_cb and await _handle_fsm_callback(adapter, chat_id, user_id, synth_cb, fsm):
        return

    if state == "event_create:preview":
        await adapter.send_message(
            chat_id,
            "Нажми кнопку под карточкой: «Сохранить», «Редактировать заново» или «Отменить создание».",
        )
        return

    # ── SOS location step: accept text address if pin didn't work ────────────
    if state == "sos:location":
        loc_text = text.strip() if text else ""
        if len(loc_text) >= 3:
            # Accept text as location description (fallback when GPS pin fails)
            data["location_text"] = loc_text[:200]
            await reg_state.set_state(user_id, "sos:comment", data)
            skip_kb = [
                [Button(texts.BTN_SKIP, payload="sos_skip_comment")],
                [Button("❌ Отменить", payload="max_reg_cancel")],
            ]
            await adapter.send_message(
                chat_id,
                "📍 Адрес записан!\n\nДобавь комментарий или нажми «Пропустить»:",
                skip_kb,
            )
        else:
            _loc_kb = [
                [get_location_button_row()[0]],
                [Button("❌ Отменить", payload="max_reg_cancel")],
            ]
            await adapter.send_message(
                chat_id,
                "Нажми кнопку для отправки геопозиции или напиши адрес текстом:",
                _loc_kb,
            )
        return

    # ── SOS comment step ──────────────────────────────────────────────────────
    if state == "sos:comment":
        if text and text.strip().lower() in ("пропустить", "skip", "-", ""):
            comment = None
        else:
            comment = text.strip() if text else None
        user = await get_or_create_user(platform="max", platform_user_id=user_id)
        if user:
            try:
                await _handle_sos_send(adapter, chat_id, user, comment=comment)
            except Exception as e:
                logger.exception("MAX SOS send error: %s", e)
                await adapter.send_message(
                    chat_id,
                    "Ошибка при отправке SOS. Попробуй заново или напиши в поддержку.",
                    get_back_to_menu_rows(),
                )
        else:
            await adapter.send_message(
                chat_id, "Ошибка. Нажми /start и пройди регистрацию.", get_back_to_menu_rows()
            )
        return

    # ── PILOT steps ──────────────────────────────────────────────────────────
    if state == "pilot:name":
        if not text:
            await adapter.send_message(chat_id, "Введи имя текстом.", _cancel_kb())
            return
        data["name"] = text.strip()
        await reg_state.set_state(user_id, "pilot:phone", data)
        logger.info("MAX reg: user_id=%s state=pilot:phone", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(2, PILOT_TOTAL_STEPS) + texts.REG_ASK_PHONE_MAX,
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

    if state == "pilot:phone":
        # Accept manual phone number as fallback text input
        if text and len(text.strip()) >= 5:
            phone = text.strip()
            if not phone.startswith("+"):
                phone = "+" + phone
            data["phone"] = phone
            logger.info("MAX reg: user_id=%s pilot phone captured (manual)", user_id)
            await _process_max_reg_phone_captured(adapter, chat_id, user_id, data, is_pilot=True)
        else:
            await adapter.send_message(
                chat_id,
                "Нажми кнопку «Отправить мой номер» или введи номер вручную (например: +79001234567):",
                [get_contact_button_row(), _cancel_kb()[0]],
            )
        return

    if state == "pilot:age":
        try:
            age = int(text.strip())
            if 18 <= age <= 80:
                data["age"] = age
                await reg_state.set_state(user_id, "pilot:gender", data)
                logger.info("MAX reg: user_id=%s state=pilot:gender", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(4, PILOT_TOTAL_STEPS) + texts.REG_ASK_GENDER,
                    _pilot_gender_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_AGE, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "pilot:bike_brand":
        if not text:
            await adapter.send_message(chat_id, "Введи марку мотоцикла текстом.", _cancel_kb())
            return
        data["bike_brand"] = text.strip()
        await reg_state.set_state(user_id, "pilot:bike_model", data)
        logger.info("MAX reg: user_id=%s state=pilot:bike_model", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(6, PILOT_TOTAL_STEPS) + texts.REG_ASK_BIKE_MODEL,
            _cancel_kb(),
        )
        return

    if state == "pilot:bike_model":
        if not text:
            await adapter.send_message(chat_id, "Введи модель мотоцикла текстом.", _cancel_kb())
            return
        data["bike_model"] = text.strip()
        await reg_state.set_state(user_id, "pilot:engine_cc", data)
        logger.info("MAX reg: user_id=%s state=pilot:engine_cc", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(7, PILOT_TOTAL_STEPS) + texts.REG_ASK_ENGINE_CC,
            _cancel_kb(),
        )
        return

    if state == "pilot:engine_cc":
        try:
            cc = int(text.strip())
            if 50 <= cc <= 3000:
                data["engine_cc"] = cc
                await reg_state.set_state(user_id, "pilot:driving_since", data)
                logger.info("MAX reg: user_id=%s state=pilot:driving_since", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(8, PILOT_TOTAL_STEPS) + texts.REG_ASK_DRIVING_SINCE,
                    _cancel_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_ENGINE_CC, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "pilot:driving_since":
        dt = _parse_date(text)
        if dt:
            data["driving_since"] = dt.isoformat()
            await reg_state.set_state(user_id, "pilot:driving_style", data)
            logger.info("MAX reg: user_id=%s state=pilot:driving_style", user_id)
            await adapter.send_message(
                chat_id,
                progress_prefix(9, PILOT_TOTAL_STEPS) + texts.REG_ASK_STYLE,
                _pilot_style_kb(),
            )
        else:
            await adapter.send_message(chat_id, texts.REG_ERROR_DATE_FORMAT, _cancel_kb())
        return

    if state == "pilot:photo":
        # Text in photo step — remind to send photo or skip
        await adapter.send_message(
            chat_id,
            "Отправь фото или нажми «Пропустить».",
            _pilot_photo_kb(),
        )
        return

    if state == "pilot:about":
        about = text.strip() if text else None
        if about and about.lower() in ("пропустить", "skip"):
            about = None
        if about:
            max_len = get_settings().about_text_max_length
            if len(about) > max_len:
                await adapter.send_message(
                    chat_id,
                    texts.REG_ERROR_ABOUT_TOO_LONG.format(max_len=max_len),
                    _pilot_about_kb(),
                )
                return
        data["about"] = about
        await reg_state.set_state(user_id, "pilot:preview", data)
        logger.info("MAX reg: user_id=%s state=pilot:preview", user_id)
        preview_text = _build_pilot_preview(data)
        photo_tok = data.get("photo_file_id")
        if photo_tok:
            await adapter.send_photo(chat_id, photo_tok, preview_text, _pilot_preview_kb())
        else:
            await adapter.send_message(chat_id, preview_text, _pilot_preview_kb())
        return

    if state == "pilot:preview":
        await adapter.send_message(
            chat_id,
            "Нажми «Сохранить» или «Редактировать».",
            _pilot_preview_kb(),
        )
        return

    # ── PASSENGER steps ──────────────────────────────────────────────────────
    if state == "passenger:name":
        if not text:
            await adapter.send_message(chat_id, "Введи имя текстом.", _cancel_kb())
            return
        data["name"] = text.strip()
        await reg_state.set_state(user_id, "passenger:phone", data)
        logger.info("MAX reg: user_id=%s state=passenger:phone", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(2, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PHONE_MAX,
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

    if state == "passenger:phone":
        if text and len(text.strip()) >= 5:
            phone = text.strip()
            if not phone.startswith("+"):
                phone = "+" + phone
            data["phone"] = phone
            logger.info("MAX reg: user_id=%s passenger phone captured (manual)", user_id)
            await _process_max_reg_phone_captured(adapter, chat_id, user_id, data, is_pilot=False)
        else:
            await adapter.send_message(
                chat_id,
                "Нажми кнопку «Отправить мой номер» или введи номер вручную (например: +79001234567):",
                [get_contact_button_row(), _cancel_kb()[0]],
            )
        return

    if state == "passenger:age":
        try:
            age = int(text.strip())
            if 18 <= age <= 80:
                data["age"] = age
                await reg_state.set_state(user_id, "passenger:gender", data)
                logger.info("MAX reg: user_id=%s state=passenger:gender", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(4, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_GENDER,
                    _pax_gender_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_AGE, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "passenger:weight":
        try:
            w = int(text.strip())
            if 30 <= w <= 200:
                data["weight"] = w
                await reg_state.set_state(user_id, "passenger:height", data)
                logger.info("MAX reg: user_id=%s state=passenger:height", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(6, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_HEIGHT,
                    _cancel_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_WEIGHT, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "passenger:height":
        try:
            h = int(text.strip())
            if 120 <= h <= 220:
                data["height"] = h
                await reg_state.set_state(user_id, "passenger:preferred_style", data)
                logger.info("MAX reg: user_id=%s state=passenger:preferred_style", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(7, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PREFERRED_STYLE,
                    _pax_style_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_HEIGHT, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "passenger:photo":
        await adapter.send_message(
            chat_id,
            "Отправь фото или нажми «Пропустить».",
            _pax_photo_kb(),
        )
        return

    if state == "passenger:about":
        about = text.strip() if text else None
        if about and about.lower() in ("пропустить", "skip"):
            about = None
        if about:
            max_len = get_settings().about_text_max_length
            if len(about) > max_len:
                await adapter.send_message(
                    chat_id,
                    texts.REG_ERROR_ABOUT_TOO_LONG.format(max_len=max_len),
                    _pax_about_kb(),
                )
                return
        data["about"] = about
        await reg_state.set_state(user_id, "passenger:preview", data)
        logger.info("MAX reg: user_id=%s state=passenger:preview", user_id)
        preview_text = _build_passenger_preview(data)
        photo_tok = data.get("photo_file_id")
        if photo_tok:
            await adapter.send_photo(chat_id, photo_tok, preview_text, _pax_preview_kb())
        else:
            await adapter.send_message(chat_id, preview_text, _pax_preview_kb())
        return

    if state == "passenger:preview":
        await adapter.send_message(
            chat_id,
            "Нажми «Сохранить» или «Редактировать».",
            _pax_preview_kb(),
        )
        return

    # ── Event edit FSM (пошаговое редактирование в MAX) ───────────────────────
    if state.startswith("event_edit:"):
        from datetime import datetime as dt_cls
        from src.services.event_service import get_event_by_id, update_event

        user = await get_or_create_user(platform="max", platform_user_id=user_id)
        if not user:
            await adapter.send_message(chat_id, "Ошибка профиля.", get_back_to_menu_rows())
            await reg_state.clear_state(user_id)
            return
        eid_str = str(data.get("event_id") or "")
        try:
            eid = uuid.UUID(eid_str)
        except ValueError:
            await adapter.send_message(chat_id, "Ошибка ID мероприятия.", get_back_to_menu_rows())
            await reg_state.clear_state(user_id)
            return
        ev = await get_event_by_id(eid)
        if not ev or ev.creator_id != effective_user_id(user):
            await adapter.send_message(chat_id, "Нет доступа.", get_back_to_menu_rows())
            await reg_state.clear_state(user_id)
            return

        sub = state.split(":", 1)[1]
        canon = effective_user_id(user)

        if sub == "title":
            val = (text or "").strip()
            ok = await update_event(eid, canon, title=(None if val == "-" else val))
            if not ok:
                await adapter.send_message(chat_id, "Ошибка сохранения.", _cancel_kb())
                return
            await reg_state.clear_state(user_id)
            await _max_show_event_edit_menu(adapter, chat_id, eid_str, intro="✅ Изменено!")
            return

        if sub == "date":
            try:
                d = dt_cls.strptime((text or "").strip(), "%d.%m.%Y").date()
                existing_time = ev.start_at.time() if ev else dt_cls.now().time()
                new_dt = dt_cls.combine(d, existing_time)
                ok = await update_event(eid, canon, start_at=new_dt)
            except (ValueError, AttributeError):
                await adapter.send_message(
                    chat_id,
                    "Формат: ДД.ММ.ГГГГ (например 15.06.2025)",
                    _cancel_kb(),
                )
                return
            if not ok:
                await adapter.send_message(chat_id, "Ошибка сохранения.", _cancel_kb())
                return
            await reg_state.clear_state(user_id)
            await _max_show_event_edit_menu(adapter, chat_id, eid_str, intro="✅ Изменено!")
            return

        if sub == "time":
            try:
                t = dt_cls.strptime((text or "").strip(), "%H:%M").time()
                existing_date = ev.start_at.date() if ev else dt_cls.now().date()
                new_dt = dt_cls.combine(existing_date, t)
                ok = await update_event(eid, canon, start_at=new_dt)
            except (ValueError, AttributeError):
                await adapter.send_message(
                    chat_id,
                    "Формат: ЧЧ:ММ (например 14:00)",
                    _cancel_kb(),
                )
                return
            if not ok:
                await adapter.send_message(chat_id, "Ошибка сохранения.", _cancel_kb())
                return
            await reg_state.clear_state(user_id)
            await _max_show_event_edit_menu(adapter, chat_id, eid_str, intro="✅ Изменено!")
            return

        if sub == "point_start":
            ps = (text or "").strip()[:500]
            if not ps:
                await adapter.send_message(chat_id, "Введи адрес старта:", _cancel_kb())
                return
            ok = await update_event(eid, canon, point_start=ps)
            if not ok:
                await adapter.send_message(chat_id, "Ошибка сохранения.", _cancel_kb())
                return
            await reg_state.clear_state(user_id)
            await _max_show_event_edit_menu(adapter, chat_id, eid_str, intro="✅ Изменено!")
            return

        if sub == "point_end":
            val = (text or "").strip()
            if val.lower() in ("пропустить", "skip", "-", ""):
                pe = None
            else:
                pe = val[:500]
            ok = await update_event(eid, canon, point_end=pe)
            if not ok:
                await adapter.send_message(chat_id, "Ошибка сохранения.", _cancel_kb())
                return
            await reg_state.clear_state(user_id)
            await _max_show_event_edit_menu(adapter, chat_id, eid_str, intro="✅ Изменено!")
            return

        if sub == "description":
            val = (text or "").strip()
            if val.lower() in ("пропустить", "skip", "-", ""):
                desc = None
            else:
                desc = val
            ok = await update_event(eid, canon, description=desc)
            if not ok:
                await adapter.send_message(chat_id, "Ошибка сохранения.", _cancel_kb())
                return
            await reg_state.clear_state(user_id)
            await _max_show_event_edit_menu(adapter, chat_id, eid_str, intro="✅ Изменено!")
            return

        await reg_state.clear_state(user_id)
        await adapter.send_message(
            chat_id, "Неизвестный шаг редактирования.", get_back_to_menu_rows()
        )
        return

    # ── Event create FSM steps ────────────────────────────────────────────────
    if state == "event_create:title":
        title = text.strip() if text else None
        if title and title.lower() in ("пропустить", "skip", "-"):
            ev_type = data.get("event_type", "")
            if ev_type == "large":
                await adapter.send_message(
                    chat_id,
                    "Для масштабного мероприятия название обязательно. Введи название:",
                    _cancel_kb(),
                )
                return
            title = None
        data["title"] = title
        await reg_state.set_state(user_id, "event_create:date", data)
        await adapter.send_message(chat_id, "Дата начала (ДД.ММ.ГГГГ):", _cancel_kb())
        return

    if state == "event_create:date":
        dt = _parse_date(text)
        if not dt:
            await adapter.send_message(
                chat_id, "Формат: ДД.ММ.ГГГГ (например 15.06.2025)", _cancel_kb()
            )
            return
        data["start_date"] = dt.strftime("%d.%m.%Y")
        await reg_state.set_state(user_id, "event_create:time", data)
        await adapter.send_message(chat_id, "Время начала (ЧЧ:ММ):", _cancel_kb())
        return

    if state == "event_create:time":
        import re as _re

        if not _re.match(r"^\d{1,2}:\d{2}$", text.strip()):
            await adapter.send_message(chat_id, "Формат: ЧЧ:ММ (например 10:00)", _cancel_kb())
            return
        data["start_time"] = text.strip()
        await reg_state.set_state(user_id, "event_create:point_start", data)
        await adapter.send_message(chat_id, "Точка старта — введи адрес:", _cancel_kb())
        return

    if state == "event_create:point_start":
        if not text:
            await adapter.send_message(chat_id, "Введи адрес старта:", _cancel_kb())
            return
        data["point_start"] = text.strip()[:500]
        await reg_state.set_state(user_id, "event_create:point_end", data)
        await adapter.send_message(
            chat_id,
            "Точка финиша — введи адрес или «Пропустить»:",
            [[Button("Пропустить", payload="max_evcreate_skip_end")], _cancel_kb()[0]],
        )
        return

    if state == "event_create:point_end":
        val = text.strip() if text else None
        if val and val.lower() in ("пропустить", "skip", "-"):
            val = None
        data["point_end"] = val[:500] if val else None
        await reg_state.set_state(user_id, "event_create:description", data)
        await adapter.send_message(
            chat_id,
            "Описание мероприятия (или «Пропустить»):",
            [[Button("Пропустить", payload="max_evcreate_skip_desc")], _cancel_kb()[0]],
        )
        return

    if state == "event_create:description":
        val = text.strip() if text else None
        if val and val.lower() in ("пропустить", "skip", "-"):
            val = None
        data["description"] = val[:1000] if val else None
        await _max_show_event_create_preview(adapter, chat_id, user_id, data)
        return

    # Unknown state — clear and show menu
    logger.warning(f"MAX reg: unknown state={state} for user_id={user_id} — clearing")
    await reg_state.clear_state(user_id)
    u_unk = await get_or_create_user(platform="max", platform_user_id=user_id)
    menu_rows = await _main_menu_rows_for(u_unk) if u_unk else get_main_menu_rows()
    await adapter.send_message(chat_id, "Что-то пошло не так. Начни заново.", menu_rows)


async def _handle_fsm_contact(
    adapter: MaxAdapter, chat_id: str, user_id: int, phone_number: str, fsm: dict
) -> None:
    """Handle contact during phone step of pilot or passenger registration."""
    state = fsm["state"]
    data = fsm["data"]

    if state not in ("pilot:phone", "passenger:phone"):
        u_ct = await get_or_create_user(platform="max", platform_user_id=user_id)
        menu_rows = await _main_menu_rows_for(u_ct) if u_ct else get_main_menu_rows()
        await adapter.send_message(
            chat_id,
            "Сейчас ожидается другой ввод.",
            menu_rows,
        )
        return

    phone = phone_number.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    if len(phone) < 5:
        # Phone couldn't be extracted automatically — ask for manual entry
        logger.warning("MAX reg: user_id=%s empty/invalid phone from contact attachment", user_id)
        await adapter.send_message(
            chat_id,
            "Не удалось получить номер телефона автоматически. "
            "Введи номер вручную (например: +79001234567):",
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

    data["phone"] = phone
    is_pilot = state.startswith("pilot")
    await _process_max_reg_phone_captured(adapter, chat_id, user_id, data, is_pilot=is_pilot)


async def _handle_fsm_photo(
    adapter: MaxAdapter, chat_id: str, user_id: int, file_id: str, fsm: dict
) -> None:
    """Handle photo upload during photo step."""
    state = fsm["state"]
    data = fsm["data"]

    if state == "pilot:photo":
        data["photo_file_id"] = file_id
        await reg_state.set_state(user_id, "pilot:about", data)
        logger.info("MAX reg: user_id=%s state=pilot:about (photo saved)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(11, PILOT_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
            _pilot_about_kb(),
        )
    elif state == "passenger:photo":
        data["photo_file_id"] = file_id
        await reg_state.set_state(user_id, "passenger:about", data)
        logger.info("MAX reg: user_id=%s state=passenger:about (photo saved)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(9, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
            _pax_about_kb(),
        )
    else:
        # Photo received outside photo step — ignore
        pass


async def _handle_fsm_callback(
    adapter: MaxAdapter, chat_id: str, user_id: int, cb_data: str, fsm: dict
) -> bool:
    """Handle FSM callback. Returns True if callback was consumed."""
    # Cancel — handle first, fsm may be empty if state expired
    if cb_data == "max_reg_cancel":
        await reg_state.clear_state(user_id)
        logger.info("MAX reg: user_id=%s cancelled", user_id)
        u_can = await get_or_create_user(platform="max", platform_user_id=user_id)
        await adapter.send_message(
            chat_id,
            texts.FSM_CANCEL_TEXT,
            await _main_menu_rows_for(u_can) if u_can else get_main_menu_rows(),
        )
        return True

    state = fsm.get("state")
    data = fsm.get("data", {})
    if not state:
        return False

    if isinstance(state, str) and state.startswith("admin:"):
        from src.max_admin_panel import handle_max_admin_fsm_callback

        if await handle_max_admin_fsm_callback(adapter, chat_id, user_id, cb_data, fsm):
            return True

    # ── Cross-platform link (same phone as Telegram) ──────────────────────────
    if cb_data == "max_reg_cross_link_yes" and state in (
        "pilot:cross_link_confirm",
        "passenger:cross_link_confirm",
    ):
        raw = data.get("cross_link_canonical_id")
        try:
            canon = uuid.UUID(str(raw))
        except (ValueError, TypeError):
            await adapter.send_message(chat_id, texts.REG_ERROR_SAVE, get_back_to_menu_rows())
            await reg_state.clear_state(user_id)
            return True
        err = await apply_max_early_account_link(user_id, canon)
        if err:
            logger.warning("MAX cross_link_yes: apply failed uid=%s err=%s", user_id, err)
            await adapter.send_message(chat_id, texts.REG_ERROR_SAVE, get_back_to_menu_rows())
        else:
            await reg_state.clear_state(user_id)
            u_x = await get_or_create_user(platform="max", platform_user_id=user_id)
            await adapter.send_message(
                chat_id,
                texts.REG_CROSS_LINK_SUCCESS,
                await _main_menu_rows_for(u_x) if u_x else get_main_menu_rows(),
            )
        return True

    if cb_data == "max_reg_cross_link_no" and state in (
        "pilot:cross_link_confirm",
        "passenger:cross_link_confirm",
    ):
        is_pilot = state.startswith("pilot")
        data = _strip_cross_link_keys(dict(data))
        await _advance_max_reg_past_phone(adapter, chat_id, user_id, data, is_pilot=is_pilot)
        return True

    # ── SOS skip comment ─────────────────────────────────────────────────────
    if cb_data == "sos_skip_comment" and state == "sos:comment":
        user = await get_or_create_user(platform="max", platform_user_id=user_id)
        if user:
            try:
                await _handle_sos_send(adapter, chat_id, user, comment=None)
            except Exception as e:
                logger.exception("MAX SOS send error (skip): %s", e)
                await adapter.send_message(
                    chat_id,
                    "Ошибка при отправке SOS. Попробуй заново.",
                    get_back_to_menu_rows(),
                )
        return True

    # ── Pilot gender ─────────────────────────────────────────────────────────
    if cb_data.startswith("max_reg_gender_") and state == "pilot:gender":
        gender = cb_data.replace("max_reg_gender_", "")
        data["gender"] = gender
        await reg_state.set_state(user_id, "pilot:bike_brand", data)
        logger.info("MAX reg: user_id=%s state=pilot:bike_brand", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(5, PILOT_TOTAL_STEPS) + texts.REG_ASK_BIKE_BRAND,
            _cancel_kb(),
        )
        return True

    # ── Pilot style ───────────────────────────────────────────────────────────
    if cb_data.startswith("max_reg_style_") and state == "pilot:driving_style":
        style = cb_data.replace("max_reg_style_", "")
        data["driving_style"] = style
        await reg_state.set_state(user_id, "pilot:photo", data)
        logger.info("MAX reg: user_id=%s state=pilot:photo", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(10, PILOT_TOTAL_STEPS) + texts.REG_ASK_PHOTO,
            _pilot_photo_kb(),
        )
        return True

    # ── Pilot skip photo ──────────────────────────────────────────────────────
    if cb_data == "max_reg_skip_photo" and state == "pilot:photo":
        data["photo_file_id"] = None
        await reg_state.set_state(user_id, "pilot:about", data)
        logger.info("MAX reg: user_id=%s state=pilot:about (skip photo)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(11, PILOT_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
            _pilot_about_kb(),
        )
        return True

    # ── Pilot skip about ──────────────────────────────────────────────────────
    if cb_data == "max_reg_skip_about" and state == "pilot:about":
        data["about"] = None
        await reg_state.set_state(user_id, "pilot:preview", data)
        logger.info("MAX reg: user_id=%s state=pilot:preview", user_id)
        await adapter.send_message(
            chat_id,
            _build_pilot_preview(data),
            _pilot_preview_kb(),
        )
        return True

    # ── Pilot preview save ────────────────────────────────────────────────────
    if cb_data == "max_reg_preview_save" and state == "pilot:preview":
        await _do_finish_pilot(adapter, chat_id, user_id, data)
        return True

    # ── Pilot preview edit ────────────────────────────────────────────────────
    if cb_data == "max_reg_preview_edit" and state == "pilot:preview":
        await reg_state.set_state(user_id, "pilot:name", {})
        logger.info("MAX reg: user_id=%s restarted (edit)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(1, PILOT_TOTAL_STEPS) + texts.REG_ASK_NAME,
            _cancel_kb(),
        )
        return True

    # ── Passenger gender ──────────────────────────────────────────────────────
    if cb_data.startswith("max_reg_pax_gender_") and state == "passenger:gender":
        gender = cb_data.replace("max_reg_pax_gender_", "")
        data["gender"] = gender
        await reg_state.set_state(user_id, "passenger:weight", data)
        logger.info("MAX reg: user_id=%s state=passenger:weight", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(5, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_WEIGHT,
            _cancel_kb(),
        )
        return True

    # ── Passenger style ───────────────────────────────────────────────────────
    if cb_data.startswith("max_reg_pax_style_") and state == "passenger:preferred_style":
        style = cb_data.replace("max_reg_pax_style_", "")
        data["preferred_style"] = style
        await reg_state.set_state(user_id, "passenger:photo", data)
        logger.info("MAX reg: user_id=%s state=passenger:photo", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(8, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PHOTO,
            _pax_photo_kb(),
        )
        return True

    # ── Passenger skip photo ──────────────────────────────────────────────────
    if cb_data == "max_reg_pax_skip_photo" and state == "passenger:photo":
        data["photo_file_id"] = None
        await reg_state.set_state(user_id, "passenger:about", data)
        logger.info("MAX reg: user_id=%s state=passenger:about (skip photo)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(9, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
            _pax_about_kb(),
        )
        return True

    # ── Passenger skip about ──────────────────────────────────────────────────
    if cb_data == "max_reg_pax_skip_about" and state == "passenger:about":
        data["about"] = None
        await reg_state.set_state(user_id, "passenger:preview", data)
        logger.info("MAX reg: user_id=%s state=passenger:preview", user_id)
        await adapter.send_message(
            chat_id,
            _build_passenger_preview(data),
            _pax_preview_kb(),
        )
        return True

    # ── Passenger preview save ────────────────────────────────────────────────
    if cb_data == "max_reg_pax_preview_save" and state == "passenger:preview":
        await _do_finish_passenger(adapter, chat_id, user_id, data)
        return True

    # ── Passenger preview edit ────────────────────────────────────────────────
    if cb_data == "max_reg_pax_preview_edit" and state == "passenger:preview":
        await reg_state.set_state(user_id, "passenger:name", {})
        logger.info("MAX reg: user_id=%s passenger restarted (edit)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(1, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_NAME,
            _cancel_kb(),
        )
        return True

    # ── Event create skip buttons ─────────────────────────────────────────────
    if cb_data == "max_evcreate_skip_end" and state == "event_create:point_end":
        data["point_end"] = None
        await reg_state.set_state(user_id, "event_create:description", data)
        await adapter.send_message(
            chat_id,
            "Описание мероприятия (или «Пропустить»):",
            [[Button("Пропустить", payload="max_evcreate_skip_desc")], _cancel_kb()[0]],
        )
        return True

    if cb_data == "max_evcreate_skip_desc" and state == "event_create:description":
        data["description"] = None
        await _max_show_event_create_preview(adapter, chat_id, user_id, data)
        return True

    if cb_data == "max_evcreate_preview_save" and state == "event_create:preview":
        await _do_create_event(adapter, chat_id, user_id, data)
        return True

    if cb_data == "max_evcreate_preview_edit" and state == "event_create:preview":
        await reg_state.set_state(user_id, "event_create:title", data)
        await adapter.send_message(
            chat_id,
            "✏️ Редактирование. Введи название мероприятия заново (или «Пропустить»):",
            _cancel_kb(),
        )
        return True

    if cb_data == "max_evcreate_preview_cancel" and state == "event_create:preview":
        await reg_state.clear_state(user_id)
        u_pv = await get_or_create_user(platform="max", platform_user_id=user_id)
        await adapter.send_message(
            chat_id,
            texts.EVENT_CREATE_CANCELLED,
            await _main_menu_rows_for(u_pv) if u_pv else get_main_menu_rows(),
        )
        return True

    # ── Event edit: пропуск финиша / описания (внутри FSM) ───────────────────
    if cb_data.startswith("max_evedit_skpend_") and state == "event_edit:point_end":
        eid = cb_data.replace("max_evedit_skpend_", "", 1)
        u = await get_or_create_user(platform="max", platform_user_id=user_id)
        if u:
            await _max_event_edit_skip_end(adapter, chat_id, u, eid)
        return True

    if cb_data.startswith("max_evedit_skdesc_") and state == "event_edit:description":
        eid = cb_data.replace("max_evedit_skdesc_", "", 1)
        u = await get_or_create_user(platform="max", platform_user_id=user_id)
        if u:
            await _max_event_edit_skip_desc(adapter, chat_id, u, eid)
        return True

    return False


async def _max_show_event_create_preview(
    adapter: MaxAdapter, chat_id: str, user_id: int, data: dict
) -> None:
    """Карточка-предпросмотр перед сохранением (как в Telegram, texts.EVENT_CREATE_PREVIEW_*)."""
    from datetime import datetime as _dt

    from src.handlers.events import _format_event_card_from_evcreate_data

    try:
        start_at = _dt.strptime(f"{data['start_date']} {data['start_time']}", "%d.%m.%Y %H:%M")
    except (KeyError, ValueError):
        await reg_state.clear_state(user_id)
        await adapter.send_message(
            chat_id, "Ошибка даты. Создание отменено.", get_back_to_menu_rows()
        )
        return
    if not data.get("point_start"):
        await reg_state.clear_state(user_id)
        await adapter.send_message(
            chat_id,
            "Ошибка: не указана точка старта. Начни создание заново.",
            get_back_to_menu_rows(),
        )
        return
    card = _format_event_card_from_evcreate_data(data, start_at)
    full = (
        texts.EVENT_CREATE_PREVIEW_HEADER
        + card
        + "\n\n"
        + texts.EVENT_CREATE_PREVIEW_CONFIRM
    )
    await reg_state.set_state(user_id, "event_create:preview", data)
    preview_kb: list = [
        [Button(texts.PROFILE_BTN_SAVE, payload="max_evcreate_preview_save")],
        [Button(texts.PROFILE_BTN_EDIT, payload="max_evcreate_preview_edit")],
        [Button(texts.EVENT_CREATE_BTN_CANCEL, payload="max_evcreate_preview_cancel")],
    ]
    preview_kb.append(_cancel_kb()[0])
    await adapter.send_message(chat_id, full, preview_kb)


async def _do_create_event(adapter: MaxAdapter, chat_id: str, user_id: int, data: dict) -> None:
    """Commit event to DB after all FSM steps collected."""
    from src.services.event_service import create_event
    from src.models.base import get_session_factory
    from src.models.user import User, Platform
    from sqlalchemy import select

    await reg_state.clear_state(user_id)

    # Resolve city_id for this user
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(User).where(User.platform_user_id == user_id, User.platform == Platform.MAX)
        )
        u = r.scalar_one_or_none()

    if not u or not u.city_id:
        await adapter.send_message(
            chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows()
        )
        return

    # Parse datetime
    try:
        from datetime import datetime as _dt

        start_at = _dt.strptime(f"{data['start_date']} {data['start_time']}", "%d.%m.%Y %H:%M")
    except (KeyError, ValueError):
        await adapter.send_message(
            chat_id, "Ошибка даты/времени. Создание отменено.", get_back_to_menu_rows()
        )
        return

    ev = await create_event(
        city_id=u.city_id,
        creator_id=effective_user_id(u),
        event_type=data.get("event_type", "run"),
        title=data.get("title"),
        start_at=start_at,
        point_start=data.get("point_start", ""),
        point_end=data.get("point_end"),
        ride_type=None,
        avg_speed=None,
        description=data.get("description"),
    )
    if ev:
        from src.services.event_creation_credit import consume_event_creation_credit
        from src.services.event_service import TYPE_LABELS

        await consume_event_creation_credit(effective_user_id(u), data.get("event_type", "run"))
        title = ev.title or TYPE_LABELS.get(ev.type.value, ev.type.value)
        await adapter.send_message(
            chat_id,
            f"✅ Мероприятие создано!\n\n<b>{title}</b>\n📅 {ev.start_at.strftime('%d.%m.%Y %H:%M')}\n📍 {ev.point_start or '—'}",
            get_back_to_menu_rows(),
        )
    else:
        await adapter.send_message(
            chat_id, "Ошибка при создании мероприятия.", get_back_to_menu_rows()
        )


async def _do_finish_pilot(adapter: MaxAdapter, chat_id: str, user_id: int, data: dict) -> None:
    """Commit pilot profile to DB and send confirmation."""
    err = await finish_pilot_registration(Platform.MAX, user_id, data)
    if err == "user_not_found":
        u_nf = await get_or_create_user(platform="max", platform_user_id=user_id)
        await adapter.send_message(
            chat_id,
            texts.REG_ERROR_USER_NOT_FOUND,
            await _main_menu_rows_for(u_nf) if u_nf else get_main_menu_rows(),
        )
        return
    if err:
        logger.warning(f"MAX reg: pilot finish error={err} user_id={user_id}")
        await adapter.send_message(
            chat_id,
            texts.REG_ERROR_SAVE,
            get_back_to_menu_rows(),
        )
        return
    await reg_state.clear_state(user_id)
    logger.info("MAX reg: user_id=%s pilot registration done", user_id)
    u_done = await get_or_create_user(platform="max", platform_user_id=user_id)
    await adapter.send_message(
        chat_id,
        texts.REG_DONE,
        await _main_menu_rows_for(u_done) if u_done else get_main_menu_rows(),
    )


async def _do_finish_passenger(adapter: MaxAdapter, chat_id: str, user_id: int, data: dict) -> None:
    """Commit passenger profile to DB and send confirmation."""
    err = await finish_passenger_registration(Platform.MAX, user_id, data)
    if err == "user_not_found":
        u_nf2 = await get_or_create_user(platform="max", platform_user_id=user_id)
        await adapter.send_message(
            chat_id,
            texts.REG_ERROR_USER_NOT_FOUND,
            await _main_menu_rows_for(u_nf2) if u_nf2 else get_main_menu_rows(),
        )
        return
    if err:
        logger.warning(f"MAX reg: passenger finish error={err} user_id={user_id}")
        await adapter.send_message(
            chat_id,
            texts.REG_ERROR_SAVE,
            get_back_to_menu_rows(),
        )
        return
    await reg_state.clear_state(user_id)
    logger.info("MAX reg: user_id=%s passenger registration done", user_id)
    u_done2 = await get_or_create_user(platform="max", platform_user_id=user_id)
    await adapter.send_message(
        chat_id,
        texts.REG_DONE,
        await _main_menu_rows_for(u_done2) if u_done2 else get_main_menu_rows(),
    )


# ── Top-level event handlers ──────────────────────────────────────────────────


def _max_use_chat_id(ev) -> bool:
    """True when event target is recipient.chat_id (use chat_id param for POST /messages)."""
    return bool(getattr(ev, "raw", None) and ev.raw.get("_max_use_chat_id"))


async def process_max_update(adapter: MaxAdapter, raw: dict) -> None:
    """Process one MAX update."""
    from src.platforms.max_adapter import set_max_use_chat_id

    events = parse_updates({"updates": [raw]})
    for ev in events:
        try:
            set_max_use_chat_id(_max_use_chat_id(ev))
            if isinstance(
                ev,
                (
                    IncomingMessage,
                    IncomingCallback,
                    IncomingContact,
                    IncomingLocation,
                    IncomingPhoto,
                ),
            ):
                from src.services import max_peer_chat

                await max_peer_chat.remember(ev.user_id, ev.chat_id)
            if isinstance(ev, IncomingCallback):
                await handle_callback(adapter, ev)
            elif isinstance(ev, IncomingMessage):
                await handle_message(adapter, ev)
            elif isinstance(ev, IncomingContact):
                await handle_contact(adapter, ev)
            elif isinstance(ev, IncomingPhoto):
                await handle_photo(adapter, ev)
            elif isinstance(ev, IncomingLocation):
                await handle_location(adapter, ev)
        except Exception as e:
            logger.exception("MAX handle error: %s", e)


async def _max_route_menu_text_press(
    adapter: MaxAdapter, ev: IncomingMessage, user, text: str
) -> bool:
    """
    Некоторые клиенты MAX показывают inline-кнопки, но при нажатии шлют message_created
    с текстом кнопки вместо message_callback — дублируем логику callback здесь.
    """
    from src.services.event_service import get_events_list
    from src.services.max_last_event_context import clear_last_event_id, get_last_event_id
    from src.ui_copy import (
        EVENT_REGISTER_PASSENGER,
        EVENT_REGISTER_PILOT,
        EVENT_SEEK_PAIR,
        SEEK_CONFIRM_PASSENGER,
        SEEK_CONFIRM_PILOT,
        SEEK_DECLINE,
    )
    from src.utils.text_format import event_button_label

    t = (text or "").strip()
    if not t:
        return False

    if t.startswith("📅 ") and user.city_id:
        events = await get_events_list(user.city_id, None)
        for e in events:
            label = event_button_label(str(e.get("title") or "")).strip()
            if label == t:
                await handle_event_detail(adapter, ev.chat_id, user, str(e["id"]))
                return True
        return False

    low = t.lower()
    filter_routes = {
        "все": (None, 0),
        "масштабное": ("large", 0),
        "мотопробег": ("motorcade", 0),
        "прохват": ("run", 0),
    }
    if low in filter_routes:
        et, off = filter_routes[low]
        await handle_events_list(adapter, ev.chat_id, user, et, offset=off)
        return True
    if low.startswith("масшт"):
        await handle_events_list(adapter, ev.chat_id, user, "large", offset=0)
        return True
    if low.startswith("мотопр"):
        await handle_events_list(adapter, ev.chat_id, user, "motorcade", offset=0)
        return True

    if t == "« Мероприятия":
        await handle_events_menu(adapter, ev.chat_id, user)
        return True
    if t == "« К списку":
        await handle_events_list_filter(adapter, ev.chat_id, user)
        return True
    if t == "« Мотопара":
        await handle_motopair_menu(adapter, ev.chat_id, user)
        return True

    leid = await get_last_event_id(ev.user_id)

    if t == "« К мероприятию" and leid:
        await handle_event_detail(adapter, ev.chat_id, user, leid)
        return True

    if t == "🚩 Пожаловаться" and leid:
        await handle_event_report(adapter, ev.chat_id, user, leid)
        return True

    if t in (EVENT_REGISTER_PILOT, EVENT_REGISTER_PASSENGER) and leid:
        role = "pilot" if t == EVENT_REGISTER_PILOT else "passenger"
        await handle_event_register(adapter, ev.chat_id, user, leid, role)
        return True

    if t == EVENT_SEEK_PAIR and leid:
        await _max_event_seeking_open(adapter, ev.chat_id, user, leid)
        return True

    if leid:
        try:
            euuid = uuid.UUID(leid)
        except ValueError:
            euuid = None
        if euuid is not None:
            h = euuid.hex
            if t == SEEK_CONFIRM_PASSENGER:
                await _max_event_seek_yes(adapter, ev.chat_id, user, f"seeky_{h}_pax")
                return True
            if t == SEEK_CONFIRM_PILOT:
                await _max_event_seek_yes(adapter, ev.chat_id, user, f"seeky_{h}_plt")
                return True
            if t == SEEK_DECLINE:
                await _max_event_seek_no(adapter, ev.chat_id, user, f"seekn_{h}")
                return True

    if t == "🏠 Главное меню":
        await clear_last_event_id(ev.user_id)
        await reg_state.clear_state(ev.user_id)
        try:
            await _pay_clear(ev.user_id)
        except Exception:
            pass
        await adapter.send_message(
            ev.chat_id,
            "С возвращением! 👋\nГлавное меню:",
            await _main_menu_rows_for(user),
        )
        return True

    return False


async def _handle_max_myid(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Показать MAX platform_user_id — для SUPERADMIN_IDS и добавления админом города."""
    from src.config import get_settings
    from src.services.admin_service import is_effective_superadmin_user

    pid = int(user.platform_user_id)
    s = get_settings()
    in_env = pid in s.superadmin_ids
    eff_sa = await is_effective_superadmin_user(user)
    body = (
        f"Твой <b>MAX user ID</b>: <code>{pid}</code>\n\n"
        f"В SUPERADMIN_IDS (указан этот MAX ID): {'✅' if in_env else '❌'}\n"
        f"Суперадмин (связка TG+MAX / список): {'✅' if eff_sa else '❌'}\n\n"
        "<b>Суперадмин в MAX:</b> добавь это число в <code>SUPERADMIN_IDS</code> в .env на сервере "
        "(через запятую с Telegram ID) и перезапусти бота.\n"
        "<b>Админ города:</b> суперадмин в Telegram или MAX: "
        "«Города → Админы городов → город → Добавить» — вставь это число. "
        "Пользователь должен хотя раз написать боту в MAX."
    )
    await adapter.send_message(chat_id, body, await _main_menu_rows_for(user))


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

    # /cancel or «отмена»
    if text.lower() in ("/cancel", "отмена"):
        fsm = await reg_state.get_state(ev.user_id)
        if fsm:
            await reg_state.clear_state(ev.user_id)
        menu_rows = await _main_menu_rows_for(user)
        await adapter.send_message(ev.chat_id, texts.FSM_CANCEL_TEXT, menu_rows)
        return

    if text.startswith("/start") or text.lower() == "start":
        await handle_start(adapter, ev.chat_id, user)
        return

    _t_myid = text.lower()
    if _t_myid == "/myid" or _t_myid.startswith("/myid "):
        await _handle_max_myid(adapter, ev.chat_id, user)
        return

    # Выбор роли текстом (MAX иногда шлёт label кнопки вместо callback)
    from src.ui_copy import ROLE_PASSENGER_BTN, ROLE_PILOT_BTN

    if (
        user.city_id
        and not await has_profile(user)
        and text in (ROLE_PILOT_BTN, ROLE_PASSENGER_BTN)
    ):
        role = UserRole.PILOT if text == ROLE_PILOT_BTN else UserRole.PASSENGER
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
        if role == UserRole.PILOT:
            await _start_pilot_registration(adapter, ev.chat_id, ev.user_id)
        else:
            await _start_passenger_registration(adapter, ev.chat_id, ev.user_id)
        return

    # Menu labels (message-type buttons) and known slash commands bypass FSM so
    # users can always navigate. Exception: event_create:* is "sticky" — the user
    # explicitly paid, so we remind them to finish or cancel instead of losing state.
    _nav_cmd: str | None = MAX_MENU_MESSAGE_TO_CMD.get(text)
    if _nav_cmd is None and text.startswith("/"):
        _slash = text.lower().lstrip("/").split()[0]
        if _slash in {
            "events", "motopair", "contacts", "profile",
            "about", "sos", "documents", "admin", "myid",
        }:
            _nav_cmd = _slash

    if _nav_cmd is not None:
        _active_fsm = await reg_state.get_state(ev.user_id)
        if _active_fsm and _active_fsm.get("state", "").startswith("event_create:"):
            await adapter.send_message(
                ev.chat_id,
                "⚠️ Создание мероприятия в процессе. Ответь на вопрос выше или нажми «Отмена».",
                _cancel_kb(),
            )
            return
        if _active_fsm:
            await reg_state.clear_state(ev.user_id)
        # Fall through to CMD routing below
    else:
        # Regular text — route through FSM if active
        fsm = await reg_state.get_state(ev.user_id)
        if fsm:
            await _handle_fsm_message(adapter, ev.chat_id, ev.user_id, text, fsm)
            return

    # Slash commands + same labels from MAX message-type menu buttons
    cmd = _nav_cmd or MAX_MENU_MESSAGE_TO_CMD.get(text, text.lower().lstrip("/"))
    if cmd == "sos":
        await _handle_sos_menu(adapter, ev.chat_id, user)
        return
    if cmd == "motopair":
        await handle_motopair_menu(adapter, ev.chat_id, user)
        return
    if cmd == "contacts":
        await handle_contacts_menu(adapter, ev.chat_id, user)
        return
    if cmd == "events":
        await handle_events_menu(adapter, ev.chat_id, user)
        return
    if cmd == "profile":
        await handle_profile(adapter, ev.chat_id, user)
        return
    if cmd == "about":
        await handle_about(adapter, ev.chat_id)
        return
    if cmd == "documents":
        await adapter.send_message(
            ev.chat_id, texts.LEGAL_DOCS_INTRO, get_max_documents_menu_rows()
        )
        return
    if cmd == "admin":
        from src.max_admin_panel import show_max_admin_root

        await show_max_admin_root(adapter, ev.chat_id, user)
        return

    low = text.lower()
    if low.startswith("/privacy") or low == "privacy":
        from src.handlers.legal import _chunk_text, format_legal_template

        legal = await format_legal_template(texts.PRIVACY_TEXT)
        for chunk in _chunk_text(legal):
            await adapter.send_message(ev.chat_id, chunk, None)
        return
    if low.startswith("/consent") or low == "consent":
        from src.handlers.legal import _chunk_text, format_legal_template

        legal = await format_legal_template(texts.CONSENT_TEXT)
        for chunk in _chunk_text(legal):
            await adapter.send_message(ev.chat_id, chunk, None)
        return
    if low.startswith("/delete_data") or low.startswith("/deletedata"):
        await adapter.send_message(
            ev.chat_id,
            texts.LEGAL_DELETE_CONFIRM,
            get_max_delete_confirm_rows(),
        )
        return
    if low.startswith("/support"):
        from src.services.admin_service import get_effective_support_email, get_effective_support_username

        try:
            st = texts.LEGAL_SUPPORT_TEXT.format(
                email=await get_effective_support_email(),
                username=await get_effective_support_username(),
            )
        except KeyError:
            st = texts.LEGAL_SUPPORT_TEXT
        await adapter.send_message(ev.chat_id, st, None)
        return

    if await _max_route_menu_text_press(adapter, ev, user, text):
        return

    # Default
    await adapter.send_message(
        ev.chat_id, "Используй меню или /start", await _main_menu_rows_for(user)
    )


async def handle_photo(adapter: MaxAdapter, ev: IncomingPhoto) -> None:
    """Handle photo message (registration photo step)."""
    user = await get_or_create_user(platform="max", platform_user_id=ev.user_id)
    if not user or user.is_blocked:
        return

    fsm = await reg_state.get_state(ev.user_id)
    if fsm and fsm["state"] in ("pilot:photo", "passenger:photo"):
        await _handle_fsm_photo(adapter, ev.chat_id, ev.user_id, ev.file_id, fsm)
    else:
        await adapter.send_message(
            ev.chat_id,
            "Используй меню или /start",
            await _main_menu_rows_for(user),
        )


async def handle_start(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Handle /start flow — including resuming active FSM."""
    if not user.city_id:
        from src.services.admin_service import get_cities

        cities = await get_cities()
        intro = f"{texts.WELCOME_NEW}\n\n{texts.WELCOME_LEGAL_DISCLAIMER}\n\n{texts.WELCOME_CITY_PROMPT}"
        if cities:
            await adapter.send_message(chat_id, intro, get_welcome_city_rows_for_cities(cities))
        else:
            await adapter.send_message(chat_id, intro, get_city_select_rows())
        return

    if not await has_profile(user):
        if user.role in (UserRole.PILOT, UserRole.PASSENGER):
            # Check for active FSM — resume or start fresh
            fsm = await reg_state.get_state(user.platform_user_id)
            if fsm:
                state = fsm["state"]
                data = fsm["data"]
                await adapter.send_message(
                    chat_id,
                    "Продолжаем регистрацию...",
                )
                # Re-send the current step prompt
                await _resend_current_step(adapter, chat_id, user.platform_user_id, state, data)
            else:
                # Start registration
                if user.role == UserRole.PILOT:
                    await _start_pilot_registration(adapter, chat_id, user.platform_user_id)
                else:
                    await _start_passenger_registration(adapter, chat_id, user.platform_user_id)
            return
        role_intro = f"{texts.WELCOME_NEW}\n\n{texts.WELCOME_LEGAL_DISCLAIMER}\n\n{texts.WELCOME_ROLE_PROMPT}"
        await adapter.send_message(chat_id, role_intro, get_welcome_role_rows())
        return

    await adapter.send_message(
        chat_id,
        "С возвращением! 👋\nГлавное меню:",
        await _main_menu_rows_for(user),
    )


async def _resend_current_step(
    adapter: MaxAdapter, chat_id: str, user_id: int, state: str, data: dict
) -> None:
    """Re-send the prompt for the current FSM step (used when /start is called mid-flow)."""
    if state in ("pilot:cross_link_confirm", "passenger:cross_link_confirm"):
        phone_masked = mask_registration_phone_hint(str(data.get("phone", "")))
        role = UserRole.PILOT if state.startswith("pilot") else UserRole.PASSENGER
        ask = texts.REG_CROSS_LINK_ASK.format(
            phone_masked=phone_masked,
            platform=data.get("cross_link_platform_label", "Telegram"),
            name=data.get("cross_link_display_name", "—"),
            role_label=user_role_display_ru(role),
        )
        await adapter.send_message(chat_id, ask, _cross_link_confirm_kb())
        return

    step_map = {
        "pilot:name": (1, PILOT_TOTAL_STEPS, texts.REG_ASK_NAME, _cancel_kb()),
        "pilot:phone": (
            2,
            PILOT_TOTAL_STEPS,
            texts.REG_ASK_PHONE_MAX,
            [get_contact_button_row(), _cancel_kb()[0]],
        ),
        "pilot:age": (3, PILOT_TOTAL_STEPS, texts.REG_ASK_AGE, _cancel_kb()),
        "pilot:gender": (4, PILOT_TOTAL_STEPS, texts.REG_ASK_GENDER, _pilot_gender_kb()),
        "pilot:bike_brand": (5, PILOT_TOTAL_STEPS, texts.REG_ASK_BIKE_BRAND, _cancel_kb()),
        "pilot:bike_model": (6, PILOT_TOTAL_STEPS, texts.REG_ASK_BIKE_MODEL, _cancel_kb()),
        "pilot:engine_cc": (7, PILOT_TOTAL_STEPS, texts.REG_ASK_ENGINE_CC, _cancel_kb()),
        "pilot:driving_since": (8, PILOT_TOTAL_STEPS, texts.REG_ASK_DRIVING_SINCE, _cancel_kb()),
        "pilot:driving_style": (9, PILOT_TOTAL_STEPS, texts.REG_ASK_STYLE, _pilot_style_kb()),
        "pilot:photo": (10, PILOT_TOTAL_STEPS, texts.REG_ASK_PHOTO, _pilot_photo_kb()),
        "pilot:about": (11, PILOT_TOTAL_STEPS, texts.REG_ASK_ABOUT, _pilot_about_kb()),
        "passenger:name": (1, PASSENGER_TOTAL_STEPS, texts.REG_ASK_NAME, _cancel_kb()),
        "passenger:phone": (
            2,
            PASSENGER_TOTAL_STEPS,
            texts.REG_ASK_PHONE_MAX,
            [get_contact_button_row(), _cancel_kb()[0]],
        ),
        "passenger:age": (3, PASSENGER_TOTAL_STEPS, texts.REG_ASK_AGE, _cancel_kb()),
        "passenger:gender": (4, PASSENGER_TOTAL_STEPS, texts.REG_ASK_GENDER, _pax_gender_kb()),
        "passenger:weight": (5, PASSENGER_TOTAL_STEPS, texts.REG_ASK_WEIGHT, _cancel_kb()),
        "passenger:height": (6, PASSENGER_TOTAL_STEPS, texts.REG_ASK_HEIGHT, _cancel_kb()),
        "passenger:preferred_style": (
            7,
            PASSENGER_TOTAL_STEPS,
            texts.REG_ASK_PREFERRED_STYLE,
            _pax_style_kb(),
        ),
        "passenger:photo": (8, PASSENGER_TOTAL_STEPS, texts.REG_ASK_PHOTO, _pax_photo_kb()),
        "passenger:about": (9, PASSENGER_TOTAL_STEPS, texts.REG_ASK_ABOUT, _pax_about_kb()),
    }

    if state in ("pilot:preview", "passenger:preview"):
        is_pilot = state.startswith("pilot")
        preview_text = _build_pilot_preview(data) if is_pilot else _build_passenger_preview(data)
        kb = _pilot_preview_kb() if is_pilot else _pax_preview_kb()
        photo_tok = data.get("photo_file_id")
        if photo_tok:
            await adapter.send_photo(chat_id, photo_tok, preview_text, kb)
        else:
            await adapter.send_message(chat_id, preview_text, kb)
        return

    if state in step_map:
        step, total, ask_text, kb = step_map[state]
        await adapter.send_message(chat_id, progress_prefix(step, total) + ask_text, kb)
    else:
        u_rs = await get_or_create_user(platform="max", platform_user_id=user_id)
        await adapter.send_message(
            chat_id,
            "Начнём сначала.",
            await _main_menu_rows_for(u_rs) if u_rs else get_main_menu_rows(),
        )


async def handle_callback(adapter: MaxAdapter, ev: IncomingCallback) -> None:
    """Handle callback button press."""
    # Acknowledge the button press immediately (removes loading state in MAX UI)
    from src.platforms.max_parser import normalize_max_callback_id

    cb = ev.raw.get("callback") or {}
    raw = ev.raw if isinstance(ev.raw, dict) else {}
    cb_id = normalize_max_callback_id(cb, raw)
    if cb_id:
        await adapter.answer_callback(cb_id)

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
    if not data:
        logger.warning(
            "MAX message_callback empty payload user_id=%s callback_keys=%s raw_callback=%s",
            ev.user_id,
            list((ev.raw.get("callback") or {}).keys()) if isinstance(ev.raw, dict) else None,
            ev.raw.get("callback") if isinstance(ev.raw, dict) else None,
        )

    # ── FSM callbacks (highest priority) ─────────────────────────────────────
    fsm = await reg_state.get_state(ev.user_id)
    if fsm or data == "max_reg_cancel":
        if fsm is None:
            fsm = {}
        consumed = await _handle_fsm_callback(adapter, chat_id, ev.user_id, data, fsm)
        if consumed:
            return

    from src.max_admin_panel import max_admin_dispatch

    if await max_admin_dispatch(adapter, chat_id, user, data):
        return

    # ── City selection ────────────────────────────────────────────────────────
    if data == "city_ekb" or (data.startswith("city_") and len(data) > 5):
        from src.models.city import City

        cb_user = (ev.raw.get("callback") or {}).get("user") or {}
        city = None
        if data == "city_ekb":
            session_factory = get_session_factory()
            async with session_factory() as session:
                r = await session.execute(select(City).where(City.name == "Екатеринбург"))
                city = r.scalar_one_or_none()
        else:
            cid_str = data.replace("city_", "").strip()
            try:
                c_uuid = uuid.UUID(cid_str)
            except (ValueError, TypeError):
                c_uuid = None
            if c_uuid:
                session_factory = get_session_factory()
                async with session_factory() as session:
                    r = await session.execute(select(City).where(City.id == c_uuid))
                    city = r.scalar_one_or_none()
        if not city:
            await adapter.send_message(
                chat_id,
                "Город не найден. Нажми /start и выбери город из списка.",
                get_back_to_menu_rows(),
            )
            return
        u_city = await get_or_create_user(
            platform="max",
            platform_user_id=ev.user_id,
            username=cb_user.get("username"),
            first_name=cb_user.get("first_name") or cb_user.get("name"),
            city_id=city.id,
        )
        fsm_city = await reg_state.get_state(ev.user_id)
        if fsm_city and fsm_city.get("state") == "profile:city_pick":
            await reg_state.clear_state(ev.user_id)
            if u_city:
                await sync_city_across_linked_identities(effective_user_id(u_city), city.id)
            await adapter.send_message(
                chat_id,
                f"✅ Город изменён на «{city.name}».",
                [[Button("👤 Мой профиль", payload="menu_profile")], get_main_menu_shortcut_row()],
            )
            return
        await adapter.send_message(
            chat_id,
            "Отлично! Теперь выбери свою роль:",
            get_role_select_rows(),
        )
        return

    # ── Юридические документы (как в Telegram) ───────────────────────────────
    if data == "menu_documents":
        await adapter.send_message(chat_id, texts.LEGAL_DOCS_INTRO, get_max_documents_menu_rows())
        return
    if data == "doc_privacy":
        from src.handlers.legal import format_legal_template

        await _max_send_legal_chunks(
            adapter, chat_id, await format_legal_template(texts.PRIVACY_TEXT)
        )
        await adapter.send_message(chat_id, "Документы:", get_max_documents_menu_rows())
        return
    if data == "doc_agreement":
        t = texts.AGREEMENT_TEXT
        if "{support_email}" in t:
            from src.handlers.legal import format_legal_template

            t = await format_legal_template(t)
        await _max_send_legal_chunks(adapter, chat_id, t)
        await adapter.send_message(chat_id, "Документы:", get_max_documents_menu_rows())
        return
    if data == "doc_consent":
        from src.handlers.legal import format_legal_template

        await _max_send_legal_chunks(
            adapter, chat_id, await format_legal_template(texts.CONSENT_TEXT)
        )
        await adapter.send_message(chat_id, "Документы:", get_max_documents_menu_rows())
        return
    if data == "doc_delete":
        await adapter.send_message(
            chat_id,
            texts.LEGAL_DELETE_CONFIRM,
            get_max_delete_confirm_rows(),
        )
        return
    if data == "doc_support":
        from src.services.admin_service import get_effective_support_email, get_effective_support_username

        try:
            st = texts.LEGAL_SUPPORT_TEXT.format(
                email=await get_effective_support_email(),
                username=await get_effective_support_username(),
            )
        except KeyError:
            st = texts.LEGAL_SUPPORT_TEXT
        await adapter.send_message(chat_id, st, None)
        await adapter.send_message(chat_id, "Документы:", get_max_documents_menu_rows())
        return
    if data == "confirm_delete_data":
        if user:
            await delete_user_data(user)
        await adapter.send_message(chat_id, texts.LEGAL_DELETE_DONE, get_main_menu_rows())
        await adapter.send_message(
            chat_id,
            "Чтобы зарегистрироваться снова, нажми /start или кнопку меню.",
            get_main_menu_rows(),
        )
        return

    # ── Role selection → start registration ───────────────────────────────────
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

        if role == UserRole.PILOT:
            await _start_pilot_registration(adapter, chat_id, ev.user_id)
        else:
            await _start_passenger_registration(adapter, chat_id, ev.user_id)
        return

    # ── Main menu ─────────────────────────────────────────────────────────────
    if data == "menu_main":
        from src.services.max_last_event_context import clear_last_event_id

        await clear_last_event_id(ev.user_id)
        await reg_state.clear_state(ev.user_id)
        try:
            await _pay_clear(ev.user_id)
        except Exception:
            pass
        await adapter.send_message(
            chat_id,
            "С возвращением! 👋\nГлавное меню:",
            await _main_menu_rows_for(user),
        )
        return

    if data == "menu_sos":
        await _handle_sos_menu(adapter, chat_id, user)
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
    if data == "menu_admin":
        from src.max_admin_panel import show_max_admin_root

        await show_max_admin_root(adapter, chat_id, user)
        return
    if data == "max_profile_phone":
        await reg_state.set_state(user.platform_user_id, "profile:phone_change", {})
        await adapter.send_message(
            chat_id,
            "📱 Введи новый номер в формате +79991234567.\n"
            "Заявка уйдёт администратору на подтверждение.",
            [[Button("« Отмена", payload="menu_profile")], get_main_menu_shortcut_row()],
        )
        return
    if data == "max_profile_city":
        from src.services.admin_service import get_cities

        await reg_state.set_state(user.platform_user_id, "profile:city_pick", {})
        cities = await get_cities()
        intro = "Выбери новый город:"
        if cities:
            await adapter.send_message(chat_id, intro, get_welcome_city_rows_for_cities(cities))
        else:
            await adapter.send_message(chat_id, intro, get_city_select_rows())
        return

    # ── SOS callbacks ─────────────────────────────────────────────────────────
    if data in ("sos_accident", "sos_broken", "sos_ran_out", "sos_other"):
        await _handle_sos_type_selected(adapter, chat_id, ev.user_id, data)
        return
    if data == "sos_skip_comment":
        await _handle_sos_send(adapter, chat_id, user, comment=None)
        return
    if data == "sos_check_ready":
        await _handle_sos_check_ready(adapter, chat_id, ev.user_id)
        return
    if data == "sos_all_clear":
        await _handle_sos_all_clear(adapter, chat_id, user)
        return

    # ── MotoPair callbacks ────────────────────────────────────────────────────
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
    if data.startswith("motopair_report_"):
        await handle_motopair_report_max(adapter, chat_id, user, data)
        return

    if data.startswith("like_") or data.startswith("dislike_"):
        from src.services.motopair_service import parse_motopair_like_callback

        parsed = parse_motopair_like_callback(data)
        if parsed:
            pid, role, off, is_like = parsed
            await handle_motopair_like(
                adapter,
                ev,
                user,
                str(pid),
                role,
                is_like,
                list_offset=off,
            )
        return

    if data.startswith("reply_like_"):
        await _handle_max_reply_like(adapter, chat_id, user, data)
        return
    if data.startswith("reply_skip_"):
        await adapter.send_message(chat_id, "Хорошо, пропускаем.", get_back_to_menu_rows())
        return

    # ── Contacts callbacks ────────────────────────────────────────────────────
    if data.startswith("contacts_"):
        if data.startswith("contacts_page_"):
            p = data.replace("contacts_page_", "").split("_")
            if len(p) >= 2:
                await handle_contacts_list(adapter, chat_id, user, p[0], int(p[1]))
        else:
            cat = data.replace("contacts_", "")
            await handle_contacts_list(adapter, chat_id, user, cat, 0)
        return

    # ── Events callbacks ──────────────────────────────────────────────────────
    if data.startswith("max_evt_seek_"):
        eid = data.replace("max_evt_seek_", "", 1)
        await _max_event_seeking_open(adapter, chat_id, user, eid)
        return
    if data.startswith("seeky_"):
        await _max_event_seek_yes(adapter, chat_id, user, data)
        return
    if data.startswith("seekn_"):
        await _max_event_seek_no(adapter, chat_id, user, data)
        return
    if data.startswith("epr_"):
        await _max_event_pair_request(adapter, chat_id, user, data)
        return
    if data.startswith("epa") and len(data) > 3:
        await _max_event_pair_accept(adapter, chat_id, user, data)
        return
    if data.startswith("epj") and len(data) > 3:
        await _max_event_pair_reject(adapter, chat_id, user, data)
        return

    parsed_ev = None
    if data.startswith("evtlp_") or data.startswith("event_list_"):
        from src.usecases.event_list_ui import parse_event_list_callback

        parsed_ev = parse_event_list_callback(data)
    if parsed_ev is not None:
        ev_type, offset = parsed_ev
        await handle_events_list(adapter, chat_id, user, ev_type, offset=offset)
        return
    if data == "event_list":
        await handle_events_list_filter(adapter, chat_id, user)
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

    if data == "event_my":
        await handle_event_my_max(adapter, chat_id, user)
        return
    if data.startswith("event_my_detail_"):
        eid = data.replace("event_my_detail_", "", 1)
        await handle_event_my_detail_max(adapter, chat_id, user, eid)
        return
    if data.startswith("event_cancel_"):
        eid = data.replace("event_cancel_", "", 1)
        await handle_event_cancel_max(adapter, chat_id, user, eid)
        return

    if data.startswith("max_evedit_menu_"):
        eid = data.replace("max_evedit_menu_", "", 1)
        await handle_max_evedit_menu(adapter, chat_id, user, eid)
        return
    if data.startswith("max_evedit_skpend_"):
        eid = data.replace("max_evedit_skpend_", "", 1)
        await _max_event_edit_skip_end(adapter, chat_id, user, eid)
        return
    if data.startswith("max_evedit_skdesc_"):
        eid = data.replace("max_evedit_skdesc_", "", 1)
        await _max_event_edit_skip_desc(adapter, chat_id, user, eid)
        return
    ev_field = _parse_max_evedit_field_payload(data)
    if ev_field:
        fk, eid = ev_field
        await handle_max_evedit_field_open(adapter, chat_id, user, fk, eid)
        return

    if data.startswith("max_event_report_"):
        eid = data.replace("max_event_report_", "")
        await handle_event_report(adapter, chat_id, user, eid)
        return

    # ── Payment callbacks ─────────────────────────────────────────────────────
    if (
        data.startswith("max_pay_")
        or data.startswith("max_profile_")
        or data.startswith("max_donate")
        or data.startswith("max_evcreate_")
        or data == "max_event_create"
    ):
        consumed = await _handle_payment_callback(adapter, chat_id, user, data)
        if consumed:
            return

    await adapter.send_message(
        chat_id,
        "Неизвестная команда.",
        await _main_menu_rows_for(user),
    )


async def handle_contact(adapter: MaxAdapter, ev: IncomingContact) -> None:
    """Handle contact shared — used during registration phone step."""
    user = await get_or_create_user(platform="max", platform_user_id=ev.user_id)
    if not user or user.is_blocked:
        return

    fsm = await reg_state.get_state(ev.user_id)
    if fsm and fsm["state"] in ("pilot:phone", "passenger:phone"):
        await _handle_fsm_contact(adapter, ev.chat_id, ev.user_id, ev.phone_number, fsm)
    else:
        await adapter.send_message(
            ev.chat_id,
            f"Номер получен: {ev.phone_number}.",
            await _main_menu_rows_for(user),
        )


async def handle_location(adapter: MaxAdapter, ev: IncomingLocation) -> None:
    """Handle location — used for SOS flow."""
    user = await get_or_create_user(platform="max", platform_user_id=ev.user_id)
    if not user or user.is_blocked:
        return

    fsm = await reg_state.get_state(ev.user_id)
    if fsm and fsm.get("state") == "sos:location":
        if not is_plausible_gps_coordinate(ev.latitude, ev.longitude):
            logger.warning(
                "MAX SOS: reject implausible location uid=%s lat=%s lon=%s",
                ev.user_id,
                ev.latitude,
                ev.longitude,
            )
            kb = [[get_location_button_row()[0]], [Button("❌ Отменить", payload="max_reg_cancel")]]
            await adapter.send_message(ev.chat_id, texts.SOS_GEO_INVALID, kb)
            return
        # Save location data and transition to comment step
        data = fsm.get("data", {})
        data["lat"] = ev.latitude
        data["lon"] = ev.longitude
        await reg_state.set_state(ev.user_id, "sos:comment", data)
        skip_kb = [
            [Button(texts.BTN_SKIP, payload="sos_skip_comment")],
            [Button("❌ Отменить", payload="max_reg_cancel")],
        ]
        await adapter.send_message(
            ev.chat_id,
            "📍 Локация получена!\n\nДобавь комментарий или нажми «Пропустить»:",
            skip_kb,
        )
    else:
        await adapter.send_message(
            ev.chat_id,
            f"Геолокация получена ({ev.latitude:.5f}, {ev.longitude:.5f}).",
            get_back_to_menu_rows(),
        )


# ── SOS handlers for MAX ─────────────────────────────────────────────────────


def _sos_type_kb() -> list[KeyboardRow]:
    return [
        [Button("ДТП", payload="sos_accident"), Button("Сломался", payload="sos_broken")],
        [Button("Обсох", payload="sos_ran_out"), Button("Другое", payload="sos_other")],
        get_main_menu_shortcut_row(),
    ]


async def _handle_sos_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Show SOS type selection and set FSM state."""
    if not user.city_id:
        await adapter.send_message(
            chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows()
        )
        return

    from src.services.sos_service import check_sos_cooldown

    remaining = await check_sos_cooldown(effective_user_id(user))
    if remaining > 0:
        mins, secs = remaining // 60, remaining % 60
        kb = [
            [Button(texts.SOS_CHECK_READY, payload="sos_check_ready")],
            [Button(texts.SOS_ALL_CLEAR_BTN, payload="sos_all_clear")],
            get_main_menu_shortcut_row(),
        ]
        await adapter.send_message(
            chat_id,
            texts.SOS_READY_WAIT.format(mins=mins, secs=secs),
            kb,
        )
        return

    await reg_state.set_state(user.platform_user_id, "sos:choose_type", {})
    await adapter.send_message(chat_id, texts.SOS_CHOOSE_TYPE, _sos_type_kb())


async def _handle_sos_type_selected(
    adapter: MaxAdapter, chat_id: str, user_id: int, sos_type: str
) -> None:
    """User selected SOS type — ask for location."""
    fsm = await reg_state.get_state(user_id)
    data = fsm.get("data", {}) if fsm else {}
    data["sos_type"] = sos_type
    await reg_state.set_state(user_id, "sos:location", data)
    kb = [[get_location_button_row()[0]], [Button("❌ Отменить", payload="max_reg_cancel")]]
    await adapter.send_message(
        chat_id,
        "📍 Укажи место на карте — нажми кнопку ниже, перетащи метку и отправь.\n"
        "Или напиши адрес текстом, если кнопка карты не работает:",
        kb,
    )


async def _handle_sos_send(adapter: MaxAdapter, chat_id: str, user, comment: str | None) -> None:
    """Create and broadcast SOS alert from MAX."""
    from src.services.sos_service import (
        create_sos_alert,
        get_city_telegram_user_ids,
        get_city_max_user_ids,
    )
    from src.services.broadcast import broadcast_max_background
    from src.services.user import get_all_platform_identities, get_user_profile_display
    from src.config import get_settings

    fsm = await reg_state.get_state(user.platform_user_id)
    data = dict(fsm.get("data", {}) if fsm else {})

    has_gps = "lat" in data and "lon" in data
    has_text_loc = bool(data.get("location_text"))

    if not data.get("sos_type") or (not has_gps and not has_text_loc):
        await adapter.send_message(
            chat_id,
            "Данные SOS устарели. Начни заново — нажми кнопку 🚨 SOS.",
            get_back_to_menu_rows(),
        )
        return

    if has_gps and not is_plausible_gps_coordinate(float(data["lat"]), float(data["lon"])):
        kb = [[get_location_button_row()[0]], [Button("❌ Отменить", payload="max_reg_cancel")]]
        await adapter.send_message(chat_id, texts.SOS_GEO_INVALID, kb)
        await reg_state.set_state(
            user.platform_user_id,
            "sos:location",
            {"sos_type": data["sos_type"]},
        )
        return

    await reg_state.clear_state(user.platform_user_id)

    if not user.city_id:
        await adapter.send_message(chat_id, texts.SOS_NO_CITY, get_back_to_menu_rows())
        return

    eff_uid = effective_user_id(user)

    lat_val = float(data["lat"]) if has_gps else 0.0
    lon_val = float(data["lon"]) if has_gps else 0.0

    ok, remaining = await create_sos_alert(
        user_id=eff_uid,
        city_id=user.city_id,
        sos_type=data["sos_type"],
        lat=lat_val,
        lon=lon_val,
        comment=comment,
    )
    if not ok:
        mins, secs = remaining // 60, remaining % 60
        kb = [
            [Button(texts.SOS_CHECK_READY, payload="sos_check_ready")],
            [Button(texts.SOS_ALL_CLEAR_BTN, payload="sos_all_clear")],
            get_main_menu_shortcut_row(),
        ]
        await adapter.send_message(chat_id, texts.SOS_READY_WAIT.format(mins=mins, secs=secs), kb)
        return

    type_labels = {
        "sos_accident": "ДТП",
        "sos_broken": "Сломался",
        "sos_ran_out": "Обсох",
        "sos_other": "Другое",
    }
    settings = get_settings()
    profile = await get_user_profile_display(user)

    broadcast_text = texts.SOS_BROADCAST_TYPE.format(
        type_label=type_labels.get(data["sos_type"], "Другое"),
        profile=escape(profile),
    )
    if comment:
        broadcast_text += texts.SOS_BROADCAST_COMMENT.format(comment=escape(comment))

    if has_gps:
        broadcast_text += format_sos_broadcast_map_html(data["lat"], data["lon"])
    elif has_text_loc:
        broadcast_text += f"\n📍 Местоположение: {escape(data['location_text'])}"

    # No tel: in inline buttons — Telegram/MAX reject it; phone is in message text (profile).

    map_kb_row: list[KeyboardRow] = []
    if has_gps:
        map_kb_row = [
            [
                Button(
                    text=texts.SOS_BROADCAST_MAP_LINK_LABEL,
                    type=ButtonType.URL,
                    url=yandex_maps_point_url(data["lat"], data["lon"]),
                )
            ],
        ]

    # Broadcast to MAX users in the city
    max_user_ids = await get_city_max_user_ids(user.city_id)
    if max_user_ids:
        excl_max: set[int] = set()
        for ident in await get_all_platform_identities(eff_uid):
            if ident.platform == Platform.MAX:
                excl_max.add(int(ident.platform_user_id))
        broadcast_max_background(
            adapter,
            max_user_ids,
            broadcast_text,
            exclude_ids=excl_max,
            kb_rows=map_kb_row,
        )

    # Cross-platform: also broadcast to Telegram users in the city
    from src.services.broadcast import broadcast_background
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    tg_user_ids = await get_city_telegram_user_ids(user.city_id)
    if tg_user_ids:
        tg_kb = None
        if has_gps:
            map_url = yandex_maps_point_url(data["lat"], data["lon"])
            tg_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=texts.SOS_BROADCAST_MAP_LINK_LABEL, url=map_url)],
                ]
            )
        tg_bot_instance = _get_tg_bot()
        if tg_bot_instance:
            broadcast_background(
                tg_bot_instance,
                tg_user_ids,
                broadcast_text,
                reply_markup=tg_kb,
            )

    cooldown_mins = settings.sos_cooldown_minutes
    kb = [
        [Button(texts.SOS_CHECK_READY, payload="sos_check_ready")],
        [Button(texts.SOS_ALL_CLEAR_BTN, payload="sos_all_clear")],
        get_main_menu_shortcut_row(),
    ]
    await adapter.send_message(chat_id, texts.SOS_SENT.format(cooldown=cooldown_mins), kb)


async def _handle_sos_check_ready(adapter: MaxAdapter, chat_id: str, user_id: int) -> None:
    """Show current cooldown status."""
    from src.services.sos_service import check_sos_cooldown

    user = await get_or_create_user(platform="max", platform_user_id=user_id)
    if not user:
        return
    remaining = await check_sos_cooldown(effective_user_id(user))
    if remaining <= 0:
        kb = [[Button("🚨 Отправить SOS", payload="menu_sos")], get_main_menu_shortcut_row()]
        await adapter.send_message(chat_id, texts.SOS_READY_NOW, kb)
    else:
        mins, secs = remaining // 60, remaining % 60
        kb = [
            [Button(texts.SOS_CHECK_READY, payload="sos_check_ready")],
            [Button(texts.SOS_ALL_CLEAR_BTN, payload="sos_all_clear")],
            get_main_menu_shortcut_row(),
        ]
        await adapter.send_message(chat_id, texts.SOS_READY_WAIT.format(mins=mins, secs=secs), kb)


async def _handle_sos_all_clear(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Broadcast 'all clear' from MAX user."""
    from src.services.sos_service import get_city_telegram_user_ids, get_city_max_user_ids
    from src.services.broadcast import broadcast_max_background, broadcast_background
    from src.services.user import get_all_platform_identities

    if not user or not user.city_id:
        await adapter.send_message(chat_id, texts.SOS_NO_CITY, get_back_to_menu_rows())
        return

    from src.services.user import get_user_sos_broadcast_name

    name = await get_user_sos_broadcast_name(user)
    clear_text = texts.SOS_ALL_CLEAR_BROADCAST.format(name=escape(name))

    # Broadcast to MAX users
    max_user_ids = await get_city_max_user_ids(user.city_id)
    if max_user_ids:
        excl_clear: set[int] = set()
        for ident in await get_all_platform_identities(effective_user_id(user)):
            if ident.platform == Platform.MAX:
                excl_clear.add(int(ident.platform_user_id))
        broadcast_max_background(
            adapter, max_user_ids, clear_text, exclude_ids=excl_clear
        )

    # Cross-platform: broadcast to Telegram users (исключаем привязанный TG, чтобы не дублировать)
    tg_user_ids = await get_city_telegram_user_ids(user.city_id)
    if tg_user_ids:
        tg_bot_instance = _get_tg_bot()
        if tg_bot_instance:
            tg_exclude = None
            for ident in await get_all_platform_identities(effective_user_id(user)):
                if ident.platform == Platform.TELEGRAM:
                    tg_exclude = int(ident.platform_user_id)
                    break
            broadcast_background(tg_bot_instance, tg_user_ids, clear_text, exclude_id=tg_exclude)

    await adapter.send_message(
        chat_id, "✅ Рады, что всё хорошо! Отбой разослан.", get_back_to_menu_rows()
    )


# ── Feature handlers (unchanged from original) ────────────────────────────────


async def handle_motopair_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    from src.services.subscription import check_subscription_required
    from src.services.subscription_messages import subscription_required_message

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            await subscription_required_message("motopair_menu"),
            [[Button("👤 Мой профиль", payload="menu_profile")], get_main_menu_shortcut_row()],
        )
        return
    kb = [
        [Button("Анкеты пилотов", payload="motopair_pilots")],
        [Button("Анкеты двоек", payload="motopair_passengers")],
        get_main_menu_shortcut_row(),
    ]
    await adapter.send_message(chat_id, "🏍 Мотопара\n\nВыбери категорию:", kb)


async def _handle_max_reply_like(adapter: MaxAdapter, chat_id: str, user, data: str) -> None:
    """Взаимный лайк из уведомления (MAX)."""
    from sqlalchemy import select
    from src.models.user import User
    from src.services.motopair_service import (
        process_like,
        get_profile_info_text,
        contact_footer_html_for_max_notifications,
    )
    from src.services.notification_templates import get_template
    from src.services.cross_platform_notify import (
        send_text_to_all_identities,
        max_send_message_with_optional_profile_photo,
    )
    from src.services.broadcast import get_max_adapter
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rest = data.replace("reply_like_", "")
    try:
        from_uid = uuid.UUID(rest)
    except ValueError:
        return
    session_factory = get_session_factory()
    async with session_factory() as session:
        res = await session.execute(select(User).where(User.id == from_uid))
        from_user = res.scalar_one_or_none()
    if not from_user:
        await adapter.send_message(chat_id, "Пользователь не найден.", get_back_to_menu_rows())
        return
    from src.services.motopair_service import get_contact_footer_html as _get_contact_footer

    from_canon = effective_user_id(from_user)
    replier_eff = effective_user_id(user)
    like_res = await process_like(replier_eff, from_canon, is_like=True)
    if not like_res.get("matched"):
        await adapter.send_message(
            chat_id,
            "Сначала нужен взаимный лайк в ленте мотопары.",
            get_back_to_menu_rows(),
        )
        return
    from_text, original_liker_photo = await get_profile_info_text(from_canon)
    to_text, replier_photo = await get_profile_info_text(replier_eff)

    msg_self_base = await get_template("template_mutual_like_self", profile=from_text)
    from_contact = await _get_contact_footer(from_canon)
    msg_self = msg_self_base + from_contact
    await max_send_message_with_optional_profile_photo(
        adapter,
        chat_id,
        msg_self,
        get_match_max_rows(from_user.platform_username),
        original_liker_photo,
        _get_tg_bot(),
    )

    msg_target_base = await get_template("template_mutual_like_reply", profile=to_text)
    replier_contact = await _get_contact_footer(replier_eff)
    msg_target_tg = msg_target_base + replier_contact
    tg_mk = []
    if user.platform_username:
        tg_mk.append(
            [
                InlineKeyboardButton(
                    text="💬 Написать",
                    url=f"https://t.me/{user.platform_username}",
                )
            ]
        )
    elif user.platform_user_id:
        tg_mk.append(
            [
                InlineKeyboardButton(
                    text="💬 Написать",
                    url=f"tg://user?id={user.platform_user_id}",
                )
            ]
        )
    max_suffix = await contact_footer_html_for_max_notifications(replier_eff)
    await send_text_to_all_identities(
        from_canon,
        msg_target_tg,
        telegram_bot=_get_tg_bot(),
        max_adapter=get_max_adapter(),
        tg_reply_markup=InlineKeyboardMarkup(inline_keyboard=tg_mk) if tg_mk else None,
        max_kb_rows=get_match_max_rows(user.platform_username),
        max_extra_html=max_suffix,
        photo_file_id=replier_photo,
    )


async def handle_motopair_list(
    adapter: MaxAdapter, chat_id: str, user, role: str, offset: int = 0
) -> None:
    from src.services.motopair_service import get_next_profile
    from src.services.subscription import check_subscription_required
    from src.services.subscription_messages import subscription_required_message

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            await subscription_required_message("motopair_cards"),
            [
                [Button("👤 Мой профиль", payload="menu_profile")],
                [Button("« Мотопара", payload="menu_motopair")],
                get_main_menu_shortcut_row(),
            ],
        )
        return

    city_id = getattr(user, "city_id", None)
    profile, has_more = await get_next_profile(
        effective_user_id(user), role, offset=offset, viewer_city_id=city_id
    )
    if not profile:
        await adapter.send_message(
            chat_id,
            texts.MOTOPAIR_NO_PROFILES,
            [
                [Button("« Мотопара", payload="menu_motopair")],
                get_main_menu_shortcut_row(),
            ],
        )
        return
    text = _format_profile_max(profile)
    kb = get_motopair_profile_rows(str(profile.id), role, offset, has_more)
    await _max_send_photo_caption_keyboard(
        adapter,
        chat_id,
        getattr(profile, "photo_file_id", None),
        text,
        kb,
        log_ctx="motopair_photo",
    )


async def handle_motopair_like(
    adapter: MaxAdapter,
    ev: IncomingCallback,
    user,
    profile_id_str: str,
    role: str,
    is_like: bool,
    *,
    list_offset: int = 0,
) -> None:
    from src.services.motopair_service import (
        get_user_for_profile,
        process_like,
        contact_footer_html_for_max_notifications,
        get_contact_footer_html,
    )

    try:
        to_user_id = await get_user_for_profile(uuid.UUID(profile_id_str), role)
    except (ValueError, TypeError):
        await adapter.send_message(ev.chat_id, "Ошибка.", get_back_to_menu_rows())
        return
    if not to_user_id:
        await adapter.send_message(ev.chat_id, "Профиль не найден.", get_back_to_menu_rows())
        return
    eff_from = effective_user_id(user)
    target_user = to_user_id  # variable renamed for clarity below
    result = await process_like(eff_from, target_user.id, is_like)

    canon_target_user = effective_user_id(target_user)

    if is_like and result.get("matched"):
        from src.services.motopair_service import get_profile_info_text
        from src.services.notification_templates import get_template
        from src.services.activity_log_service import log_event
        from src.models.activity_log import ActivityEventType
        from src.services.cross_platform_notify import (
            send_text_to_all_identities,
            max_send_message_with_optional_profile_photo,
        )
        from src.services.broadcast import get_max_adapter
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        await log_event(
            ActivityEventType.MUTUAL_LIKE,
            user_id=eff_from,
            data={"target_user_id": str(target_user.id), "from_user_id": str(eff_from)},
        )

        from src.services.motopair_service import get_contact_footer_html

        from_text, match_photo = await get_profile_info_text(canon_target_user)
        msg_self_base = await get_template("template_mutual_like_self", profile=from_text)
        matched_contact = await get_contact_footer_html(canon_target_user)
        msg_self = msg_self_base + matched_contact
        self_rows = get_match_max_rows(target_user.platform_username)
        await max_send_message_with_optional_profile_photo(
            adapter,
            ev.chat_id,
            msg_self,
            self_rows,
            match_photo,
            _get_tg_bot(),
        )

        to_text, liker_photo = await get_profile_info_text(eff_from)
        msg_target_base = await get_template("template_mutual_like_target", profile=to_text)
        liker_contact = await get_contact_footer_html(eff_from)
        msg_target_tg = msg_target_base + liker_contact
        tg_mk = []
        if user.platform_username:
            tg_mk.append(
                [
                    InlineKeyboardButton(
                        text="💬 Написать",
                        url=f"https://t.me/{user.platform_username}",
                    )
                ]
            )
        elif user.platform_user_id:
            tg_mk.append(
                [
                    InlineKeyboardButton(
                        text="💬 Написать",
                        url=f"tg://user?id={user.platform_user_id}",
                    )
                ]
            )
        max_suffix_match = await contact_footer_html_for_max_notifications(eff_from)
        await send_text_to_all_identities(
            canon_target_user,
            msg_target_tg,
            telegram_bot=_get_tg_bot(),
            max_adapter=get_max_adapter(),
            tg_reply_markup=InlineKeyboardMarkup(inline_keyboard=tg_mk) if tg_mk else None,
            max_kb_rows=get_match_max_rows(user.platform_username),
            max_extra_html=max_suffix_match,
            photo_file_id=liker_photo,
        )

    elif is_like:
        from src.services.motopair_service import get_profile_info_text
        from src.services.notification_templates import get_template
        from src.services.cross_platform_notify import notify_like_received_cross_platform
        from src.services.broadcast import get_max_adapter
        from src.keyboards.motopair import get_like_notification_kb

        from_text, from_photo = await get_profile_info_text(eff_from)
        notify_text = await get_template("template_like_received", profile=from_text)
        kb_tg = get_like_notification_kb(str(eff_from))
        max_rows = get_like_notification_max_rows(str(eff_from))
        max_suffix_like = await contact_footer_html_for_max_notifications(eff_from)
        await notify_like_received_cross_platform(
            canon_target_user,
            notify_text,
            from_photo,
            telegram_bot=_get_tg_bot(),
            max_adapter=get_max_adapter(),
            tg_reply_markup=kb_tg,
            max_kb_rows=max_rows,
            max_extra_html=max_suffix_like,
        )

        await handle_motopair_list(adapter, ev.chat_id, user, role, list_offset)
    else:
        next_off = list_offset if result.get("blacklisted") else list_offset + 1
        await handle_motopair_list(adapter, ev.chat_id, user, role, next_off)


async def handle_contacts_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    await adapter.send_message(
        chat_id, "📇 Полезные контакты\n\nВыбери категорию:", get_contacts_menu_rows()
    )


async def handle_contacts_list(
    adapter: MaxAdapter, chat_id: str, user, category: str, offset: int = 0
) -> None:
    from src.services.useful_contacts_service import (
        get_contacts_by_category,
        CAT_LABELS,
        format_useful_contact_html,
    )

    if not user.city_id:
        await adapter.send_message(
            chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows()
        )
        return
    contacts, total, has_more = await get_contacts_by_category(
        user.city_id, category, offset=offset
    )
    label = CAT_LABELS.get(category, category)
    if not contacts:
        text = f"<b>{label}</b>\n\nКонтактов пока нет."
    else:
        blocks = [format_useful_contact_html(c) for c in contacts]
        text = f"<b>{label}</b>\n\n" + "\n\n".join(blocks)
    if len(text) > 4000:
        text = text[:3997] + "…"
    kb = get_contacts_page_rows(category, offset, has_more)
    await adapter.send_message(chat_id, text, kb)


def _parse_max_evedit_field_payload(data: str) -> tuple[str, str] | None:
    pfx = "max_evedit_f_"
    if not data.startswith(pfx):
        return None
    rest = data[len(pfx) :]
    for fk in ("title", "date", "time", "pstart", "pend", "desc"):
        head = fk + "_"
        if rest.startswith(head):
            eid = rest[len(head) :]
            try:
                uuid.UUID(eid)
            except ValueError:
                return None
            return fk, eid
    return None


async def _max_show_event_edit_menu(
    adapter: MaxAdapter, chat_id: str, event_id: str, intro: str | None = None
) -> None:
    from src.handlers.events import _format_event_card
    from src.services.event_service import get_event_by_id

    ev = await get_event_by_id(uuid.UUID(event_id))
    if not ev:
        await adapter.send_message(chat_id, "Мероприятие не найдено.", get_back_to_menu_rows())
        return
    body = _format_event_card(ev)
    lead = (intro + "\n\n") if intro else ""
    await adapter.send_message(
        chat_id,
        f"{lead}{body}\n\nВыбери поле для изменения:",
        get_max_event_edit_menu_rows(event_id),
    )


async def handle_max_evedit_menu(adapter: MaxAdapter, chat_id: str, user, event_id: str) -> None:
    from src.services.event_service import get_event_by_id

    try:
        eid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(chat_id, "Ошибка ID.", get_back_to_menu_rows())
        return
    ev = await get_event_by_id(eid)
    if not ev or ev.creator_id != effective_user_id(user):
        await adapter.send_message(chat_id, "Нет доступа.", get_back_to_menu_rows())
        return
    await _max_show_event_edit_menu(adapter, chat_id, event_id)


async def _max_event_edit_skip_end(adapter: MaxAdapter, chat_id: str, user, event_id: str) -> None:
    from src.services.event_service import get_event_by_id, update_event

    try:
        eid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(chat_id, "Ошибка ID.", get_back_to_menu_rows())
        return
    ev = await get_event_by_id(eid)
    if not ev or ev.creator_id != effective_user_id(user):
        await adapter.send_message(chat_id, "Нет доступа.", get_back_to_menu_rows())
        return
    await update_event(eid, effective_user_id(user), point_end=None)
    cur = await reg_state.get_state(user.platform_user_id)
    if cur and str(cur.get("state", "")).startswith("event_edit"):
        await reg_state.clear_state(user.platform_user_id)
    await _max_show_event_edit_menu(adapter, chat_id, event_id, intro="✅ Финиш убран.")


async def _max_event_edit_skip_desc(adapter: MaxAdapter, chat_id: str, user, event_id: str) -> None:
    from src.services.event_service import get_event_by_id, update_event

    try:
        eid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(chat_id, "Ошибка ID.", get_back_to_menu_rows())
        return
    ev = await get_event_by_id(eid)
    if not ev or ev.creator_id != effective_user_id(user):
        await adapter.send_message(chat_id, "Нет доступа.", get_back_to_menu_rows())
        return
    await update_event(eid, effective_user_id(user), description=None)
    cur = await reg_state.get_state(user.platform_user_id)
    if cur and str(cur.get("state", "")).startswith("event_edit"):
        await reg_state.clear_state(user.platform_user_id)
    await _max_show_event_edit_menu(adapter, chat_id, event_id, intro="✅ Описание убрано.")


async def handle_max_evedit_field_open(
    adapter: MaxAdapter, chat_id: str, user, field_key: str, event_id: str
) -> None:
    from src.services.event_service import get_event_by_id

    try:
        eid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(chat_id, "Ошибка ID.", get_back_to_menu_rows())
        return
    ev = await get_event_by_id(eid)
    if not ev or ev.creator_id != effective_user_id(user):
        await adapter.send_message(chat_id, "Нет доступа.", get_back_to_menu_rows())
        return

    uid = user.platform_user_id
    prompts = {
        "title": ("event_edit:title", "Введи новое название (или «-» чтобы убрать):"),
        "date": ("event_edit:date", "Введи новую дату начала (ДД.ММ.ГГГГ):"),
        "time": ("event_edit:time", "Введи новое время начала (ЧЧ:ММ):"),
        "pstart": ("event_edit:point_start", "Введи новый адрес старта:"),
        "pend": ("event_edit:point_end", "Введи адрес финиша или нажми «Пропустить»:"),
        "desc": ("event_edit:description", "Введи новое описание или нажми «Пропустить»:"),
    }
    st, prompt = prompts.get(field_key, (None, None))
    if not st:
        await adapter.send_message(chat_id, "Неизвестное поле.", get_back_to_menu_rows())
        return
    await reg_state.set_state(uid, st, {"event_id": event_id})
    if field_key == "pend":
        kb = [
            [Button("Пропустить (убрать финиш)", payload=f"max_evedit_skpend_{event_id}")],
            _cancel_kb()[0],
        ]
    elif field_key == "desc":
        kb = [
            [Button("Пропустить (убрать описание)", payload=f"max_evedit_skdesc_{event_id}")],
            _cancel_kb()[0],
        ]
    else:
        kb = _cancel_kb()
    await adapter.send_message(chat_id, prompt, kb)


async def handle_event_my_max(adapter: MaxAdapter, chat_id: str, user) -> None:
    from src.services.event_service import get_creator_events, TYPE_LABELS
    from src.services.subscription import check_subscription_required
    from src.services.subscription_messages import subscription_required_message
    from src.utils.text_format import truncate_smart, event_button_label

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            await subscription_required_message("events_menu"),
            [
                [Button("👤 Мой профиль", payload="menu_profile")],
                get_main_menu_shortcut_row(),
            ],
        )
        return
    events = await get_creator_events(effective_user_id(user))
    if not events:
        await adapter.send_message(
            chat_id,
            "Ты ещё не создавал мероприятий.",
            [
                [Button("« Мероприятия", payload="menu_events")],
                get_main_menu_shortcut_row(),
            ],
        )
        return
    lines = ["<b>Мои мероприятия</b>\n"]
    kb: list = []
    for e in events[:10]:
        title = e.title or TYPE_LABELS.get(e.type.value, e.type.value)
        lines.append(
            f"• {truncate_smart(str(title), 55)} — {e.start_at.strftime('%d.%m.%Y %H:%M')}"
        )
        kb.append([Button(event_button_label(str(title)), payload=f"event_my_detail_{e.id}")])
    kb.append([Button("« Мероприятия", payload="menu_events")])
    kb.append(get_main_menu_shortcut_row())
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3997] + "…"
    await adapter.send_message(chat_id, text, kb)


async def handle_event_my_detail_max(
    adapter: MaxAdapter, chat_id: str, user, event_id: str
) -> None:
    from src.handlers.events import _format_event_card
    from src.services.event_service import get_event_by_id

    try:
        ev_uuid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(chat_id, "Ошибка ID.", get_back_to_menu_rows())
        return
    ev = await get_event_by_id(ev_uuid)
    if not ev or ev.creator_id != effective_user_id(user):
        await adapter.send_message(chat_id, "Мероприятие не найдено.", get_back_to_menu_rows())
        return
    text = _format_event_card(ev)
    kb = get_max_my_event_detail_rows(event_id)
    await adapter.send_message(chat_id, text, kb)


async def handle_event_cancel_max(adapter: MaxAdapter, chat_id: str, user, event_id: str) -> None:
    from src.services.event_service import cancel_event, get_event_by_id
    from src.services.event_participant_notify import notify_event_participants_cancelled
    from src.services.broadcast import get_max_adapter

    try:
        ev_uuid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(chat_id, "Ошибка ID.", get_back_to_menu_rows())
        return
    ok, participant_ids = await cancel_event(ev_uuid, effective_user_id(user))
    if not ok:
        await adapter.send_message(chat_id, "Не удалось отменить.", get_back_to_menu_rows())
        return
    ev = await get_event_by_id(ev_uuid)
    if ev:
        msg = f"❌ Мероприятие «{ev.title or 'Мероприятие'}» отменено организатором."
        await notify_event_participants_cancelled(
            participant_ids,
            msg,
            telegram_bot=_get_tg_bot(),
            max_adapter=get_max_adapter() or adapter,
        )
    await adapter.send_message(
        chat_id,
        "Мероприятие отменено. Участники уведомлены (Telegram и MAX, где есть аккаунт).",
        [
            [Button("« Мои мероприятия", payload="event_my")],
            get_main_menu_shortcut_row(),
        ],
    )


async def handle_motopair_report_max(adapter: MaxAdapter, chat_id: str, user, data: str) -> None:
    from src.services.motopair_service import get_user_for_profile, get_profile_info_text
    from src import texts
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rest = data.replace("motopair_report_", "", 1)
    if "_" not in rest:
        await adapter.send_message(chat_id, "Ошибка.", get_back_to_menu_rows())
        return
    profile_id_str, role = rest.rsplit("_", 1)
    try:
        profile_uuid = uuid.UUID(profile_id_str)
    except ValueError:
        await adapter.send_message(chat_id, "Ошибка.", get_back_to_menu_rows())
        return
    target_user = await get_user_for_profile(profile_uuid, role)
    if not target_user:
        await adapter.send_message(chat_id, "Анкета не найдена.", get_back_to_menu_rows())
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
    tg_bot = _get_tg_bot()
    from src.services.admin_multichannel_notify import (
        notify_city_admins_multichannel,
        notify_superadmins_multichannel,
    )
    from src.services.broadcast import get_max_adapter

    _max_a = get_max_adapter() or adapter
    if user.city_id:
        await notify_city_admins_multichannel(
            user.city_id,
            admin_text,
            telegram_markup=admin_kb,
            telegram_bot=tg_bot,
            max_adapter=_max_a,
        )
    await notify_superadmins_multichannel(
        admin_text,
        telegram_markup=admin_kb,
        telegram_bot=tg_bot,
        max_adapter=_max_a,
    )
    await adapter.send_message(chat_id, texts.MOTOPAIR_REPORT_SENT, get_back_to_menu_rows())


async def _max_event_seeking_open(adapter: MaxAdapter, chat_id: str, user, eid_str: str) -> None:
    try:
        eid = uuid.UUID(eid_str)
    except ValueError:
        await adapter.send_message(chat_id, "Некорректное мероприятие.", get_back_to_menu_rows())
        return
    from src.services.event_service import get_user_registration

    reg = await get_user_registration(eid, effective_user_id(user))
    if not reg:
        await adapter.send_message(
            chat_id, "Сначала запишись на мероприятие.", get_back_to_menu_rows()
        )
        return
    from src.services.max_last_event_context import set_last_event_id

    await set_last_event_id(user.platform_user_id, str(eid))
    await adapter.send_message(
        chat_id, texts.EVENT_PAIR_SEEK_INTRO, get_max_seeking_confirm_rows(str(eid))
    )


async def _max_event_seek_yes(adapter: MaxAdapter, chat_id: str, user, data: str) -> None:
    # payload = "seeky_" + 32-hex uuid + "_pax|_plt" (6 chars prefix, not 5)
    if not data.startswith("seeky_"):
        return
    rest = data[6:]
    idx = rest.rfind("_")
    if idx < 32:
        return
    h, role_s = rest[:idx], rest[idx + 1 :]
    try:
        eid = uuid.UUID(hex=h)
    except ValueError:
        return
    target = "passenger" if role_s == "pax" else "pilot"
    from src.services.event_service import (
        set_seeking_pair,
        get_seeking_users,
        get_user_registration,
    )

    eff = effective_user_id(user)
    reg = await get_user_registration(eid, eff)
    if not reg:
        await adapter.send_message(chat_id, "Ошибка регистрации.", get_back_to_menu_rows())
        return
    await set_seeking_pair(eid, eff, True)
    seekers = await get_seeking_users(eid, target, exclude_user_id=eff)
    if not seekers:
        await adapter.send_message(
            chat_id,
            "Пока никого нет. Заявки появятся, когда кто-то запишется и тоже включит поиск.",
            [
                [Button("« К мероприятию", payload=f"event_detail_{eid}")],
                get_main_menu_shortcut_row(),
            ],
        )
    else:
        from src.usecases.event_pair import build_max_seeking_list_rows

        kb_rows = await build_max_seeking_list_rows(str(eid), seekers)
        await adapter.send_message(
            chat_id,
            "Выбери, кому отправить заявку:",
            kb_rows,
        )


async def _max_event_seek_no(adapter: MaxAdapter, chat_id: str, user, data: str) -> None:
    if not data.startswith("seekn_"):
        return
    h = data[6:]
    try:
        eid = uuid.UUID(hex=h)
    except ValueError:
        return
    from src.services.event_service import (
        set_seeking_pair,
        get_event_by_id,
        get_user_registration,
        TYPE_LABELS,
    )

    await set_seeking_pair(eid, effective_user_id(user), False)
    ev = await get_event_by_id(eid)
    if not ev:
        return
    reg = await get_user_registration(eid, effective_user_id(user))
    role = reg.role if reg else None
    title = ev.title or TYPE_LABELS.get(ev.type.value, ev.type.value)
    text = (
        f"<b>{escape(title)}</b>\n📅 {ev.start_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {escape(str(ev.point_start or '—'))}"
    )
    can_report = ev.creator_id != effective_user_id(user)
    kb = get_event_detail_rows(str(eid), True, can_report=can_report, user_role=role)
    await adapter.send_message(chat_id, text, kb)


async def _max_event_pair_request(adapter: MaxAdapter, chat_id: str, user, data: str) -> None:
    from src.utils.callback_short import get_pair_callback
    from src.services.event_service import send_pair_request, get_profile_display, get_event_by_id
    from src.services.broadcast import get_max_adapter
    from src.usecases.event_pair import notify_pair_request_cross_platform

    code = data[4:]
    pair = get_pair_callback(code)
    if not pair:
        await adapter.send_message(chat_id, "Заявка устарела.", get_back_to_menu_rows())
        return
    eid, to_user_id = pair
    ok, msg = await send_pair_request(eid, effective_user_id(user), to_user_id)
    if not ok:
        await adapter.send_message(chat_id, msg, get_back_to_menu_rows())
        return
    from_text = await get_profile_display(effective_user_id(user))
    ev = await get_event_by_id(eid)
    tg = _get_tg_bot()
    if tg:
        await notify_pair_request_cross_platform(
            bot=tg,
            max_adapter=get_max_adapter(),
            event_id=eid,
            from_user_canonical_id=effective_user_id(user),
            to_user_internal_id=to_user_id,
            from_profile_text=from_text,
            event_title=ev.title if ev else None,
        )
    await adapter.send_message(
        chat_id,
        "Заявка отправлена!",
        [[Button("« Мероприятия", payload="menu_events")], get_main_menu_shortcut_row()],
    )


async def _max_event_pair_accept(adapter: MaxAdapter, chat_id: str, user, data: str) -> None:
    from src.utils.callback_short import get_pair_callback
    from src.services.event_service import accept_pair_request
    from src.services.broadcast import get_max_adapter
    from src.usecases.event_pair import notify_pair_accepted_cross_platform

    code = data[3:]
    pair = get_pair_callback(code)
    if not pair:
        await adapter.send_message(chat_id, "Заявка устарела.", get_back_to_menu_rows())
        return
    eid, from_user_id = pair
    ok = await accept_pair_request(eid, from_user_id, effective_user_id(user))
    if not ok:
        return
    tg = _get_tg_bot()
    await notify_pair_accepted_cross_platform(
        bot=tg,
        max_adapter=get_max_adapter(),
        initiator_user_id=from_user_id,
        accepter_user_id=effective_user_id(user),
    )
    await adapter.send_message(chat_id, "✅ Заявка принята!", get_back_to_menu_rows())


async def _max_event_pair_reject(adapter: MaxAdapter, chat_id: str, user, data: str) -> None:
    from src.utils.callback_short import get_pair_callback
    from src.services.event_service import reject_pair_request

    code = data[3:]
    pair = get_pair_callback(code)
    if not pair:
        return
    eid, from_user_id = pair
    await reject_pair_request(eid, from_user_id, effective_user_id(user))
    await adapter.send_message(chat_id, "Заявка отклонена.", get_back_to_menu_rows())


async def handle_events_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    from src.services.subscription import check_subscription_required
    from src.services.subscription_messages import subscription_required_message

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            await subscription_required_message("events_menu"),
            [
                [Button("👤 Мой профиль", payload="menu_profile")],
                get_main_menu_shortcut_row(),
            ],
        )
        return
    # Build events menu with create button
    kb = list(get_events_menu_rows())
    # Insert "Create event" before the last "Back" row
    create_row = [Button("➕ Создать мероприятие", payload="max_event_create")]
    if kb and kb[-1]:
        kb.insert(-1, create_row)
    else:
        kb.append(create_row)
    hint = await _max_events_menu_pricing_hint()
    body = "📅 Мероприятия" + (f"\n\n{hint}" if hint else "")
    await adapter.send_message(chat_id, body, kb)


async def handle_events_list_filter(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Показать только фильтр по типу (как «event_list» в Telegram — без отдельной проверки подписки)."""
    if not user.city_id:
        await adapter.send_message(
            chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows()
        )
        return
    await adapter.send_message(chat_id, "Фильтр по типу:", get_event_list_rows())


async def _max_events_menu_pricing_hint() -> str:
    """Кратко о платности создания (как логика TG), без хардкода «всё платно»."""
    from src.services.admin_service import get_subscription_settings

    s = await get_subscription_settings()
    if not s:
        return ""
    parts = [
        "ℹ️ <b>Прохваты</b> — создание всегда бесплатно.",
        "<b>Мотопробег / масштабное</b> — по настройкам подписки и лимитам "
        "(см. раздел подписки в боте).",
    ]
    if s.event_creation_enabled and (s.event_creation_price_kopecks or 0) > 0:
        rub = (s.event_creation_price_kopecks or 0) // 100
        parts.append(f"Платное создание (после лимитов): <b>{rub} ₽</b>.")
    return "\n".join(parts)


async def handle_events_list(
    adapter: MaxAdapter,
    chat_id: str,
    user,
    event_type: str | None = None,
    *,
    offset: int = 0,
) -> None:
    from src.services.event_service import get_events_list
    from src.usecases.event_list_ui import (
        PAGE_SIZE,
        build_max_event_detail_rows,
        format_event_list_header_plain,
    )
    from src.utils.text_format import truncate_smart, event_button_label

    if not user.city_id:
        await adapter.send_message(
            chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows()
        )
        return
    events = await get_events_list(user.city_id, event_type)
    if not events:
        await adapter.send_message(chat_id, "Мероприятий пока нет.", get_event_list_rows())
        return
    if offset >= len(events):
        offset = 0
    slice_e = events[offset : offset + PAGE_SIZE]
    hdr = escape(format_event_list_header_plain(event_type, offset))
    lines = [f"<b>{hdr}</b>\n"]
    for e in slice_e:
        title_line = truncate_smart(str(e.get("title") or ""), 80)
        lines.append(
            f"• {title_line} — {e['date']}\n  Пилотов: {e['pilots']}, двоек: {e['passengers']}"
        )
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3997] + "…"
    base_rows = get_event_list_rows()
    filter_row, *tail = base_rows
    detail_rows = build_max_event_detail_rows(
        events,
        event_type,
        offset,
        event_button_label_fn=event_button_label,
    )
    kb = [filter_row, *detail_rows, *tail]
    await adapter.send_message(chat_id, text, kb)


async def handle_event_detail(adapter: MaxAdapter, chat_id: str, user, event_id: str) -> None:
    from src.services.event_service import get_event_by_id, TYPE_LABELS
    from src.models.event import EventRegistration

    try:
        ev_uuid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(
            chat_id, "Ошибка: некорректный ID мероприятия.", get_back_to_menu_rows()
        )
        return
    ev = await get_event_by_id(ev_uuid)
    if not ev:
        await adapter.send_message(chat_id, "Мероприятие не найдено.", get_back_to_menu_rows())
        return
    from html import escape
    from src.utils.text_format import truncate_smart

    title = ev.title or TYPE_LABELS.get(ev.type.value, ev.type.value)
    title_esc = escape(str(title))
    point_esc = escape(str(ev.point_start or "—"))
    dt_s = ev.start_at.strftime("%d.%m.%Y %H:%M")
    header = f"<b>{title_esc}</b>\n📅 {dt_s}\n📍 {point_esc}\n"
    desc_raw = (ev.description or "").strip()
    max_body = 3500
    if desc_raw:
        desc_esc = escape(desc_raw)
        room = max_body - len(header)
        if room < 1:
            text = header[:max_body]
        elif len(desc_esc) > room:
            text = header + truncate_smart(desc_esc, room)
        else:
            text = header + desc_esc
    else:
        text = header.rstrip()
    if len(text) > max_body:
        text = text[: max_body - 1] + "…"
    session_factory = get_session_factory()
    is_reg = False
    user_role: str | None = None
    async with session_factory() as session:
        r = await session.execute(
            select(EventRegistration).where(
                EventRegistration.event_id == ev.id,
                EventRegistration.user_id == effective_user_id(user),
            )
        )
        reg_row = r.scalar_one_or_none()
        if reg_row:
            is_reg = True
            user_role = reg_row.role
    can_report = ev.creator_id != effective_user_id(user)
    kb = get_event_detail_rows(
        event_id, is_reg, can_report=can_report, user_role=user_role if is_reg else None
    )
    from src.services.max_last_event_context import set_last_event_id

    await set_last_event_id(user.platform_user_id, str(ev.id))
    await adapter.send_message(chat_id, text, kb)


async def handle_event_register(
    adapter: MaxAdapter, chat_id: str, user, event_id: str, role: str
) -> None:
    from src.services.subscription import check_subscription_required
    from src.services.subscription_messages import subscription_required_message
    from src.services.event_service import register_for_event

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            await subscription_required_message("events_register"),
            [
                [Button("👤 Мой профиль", payload="menu_profile")],
                [Button("« Мероприятия", payload="menu_events")],
                get_main_menu_shortcut_row(),
            ],
        )
        return
    try:
        ev_uuid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(
            chat_id, "Ошибка: некорректный ID мероприятия.", get_back_to_menu_rows()
        )
        return
    ok, _ = await register_for_event(ev_uuid, effective_user_id(user), role)
    if ok:
        await adapter.send_message(
            chat_id,
            texts.EVENT_REGISTER_SEEK_PROMPT,
            get_max_seeking_confirm_rows(str(ev_uuid)),
        )
    else:
        await adapter.send_message(chat_id, "Ошибка регистрации.", get_back_to_menu_rows())


async def handle_event_report(adapter: MaxAdapter, chat_id: str, user, event_id: str) -> None:
    """Report an event from MAX. Уведомляет админов города и суперадминов (TG + MAX)."""
    from src.services.event_service import get_event_by_id, format_event_report_admin_html
    from src import texts

    try:
        ev_uuid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(chat_id, "Ошибка.", get_back_to_menu_rows())
        return

    ev = await get_event_by_id(ev_uuid)
    if not ev:
        await adapter.send_message(chat_id, "Мероприятие не найдено.", get_back_to_menu_rows())
        return

    if ev.creator_id == effective_user_id(user):
        await adapter.send_message(
            chat_id, "Нельзя пожаловаться на своё мероприятие.", get_back_to_menu_rows()
        )
        return

    reporter = (
        f"@{user.platform_username}" if user.platform_username else str(user.platform_user_id)
    )
    admin_text = await format_event_report_admin_html(ev, reporter)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.EVENT_REPORT_BTN_ACCEPT,
                    callback_data=f"admin_evreport_accept_{event_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=texts.EVENT_REPORT_BTN_REJECT,
                    callback_data=f"admin_evreport_reject_{event_id}",
                )
            ],
        ]
    )

    tg_bot = _get_tg_bot()
    from src.services.admin_multichannel_notify import (
        notify_city_admins_multichannel,
        notify_superadmins_multichannel,
    )
    from src.services.broadcast import get_max_adapter

    _max_a = get_max_adapter() or adapter
    if ev.city_id:
        await notify_city_admins_multichannel(
            ev.city_id,
            admin_text,
            telegram_markup=admin_kb,
            telegram_bot=tg_bot,
            max_adapter=_max_a,
        )
    await notify_superadmins_multichannel(
        admin_text,
        telegram_markup=admin_kb,
        telegram_bot=tg_bot,
        max_adapter=_max_a,
    )

    await adapter.send_message(chat_id, texts.EVENT_REPORT_SENT, get_back_to_menu_rows())


async def handle_profile(adapter: MaxAdapter, chat_id: str, user) -> None:
    from src.services.subscription import check_subscription_required
    from src.services.admin_service import get_subscription_settings
    from src.services.payment import create_payment

    sub_settings = await get_subscription_settings()
    monthly_price = (
        sub_settings.monthly_price_kopecks
        if sub_settings and sub_settings.monthly_price_kopecks
        else 29900
    )
    season_price = (
        sub_settings.season_price_kopecks
        if sub_settings and sub_settings.season_price_kopecks
        else 79900
    )

    sub_required = await check_subscription_required(user)
    logger.info(
        "handle_profile: max_uid={} canon={} sub_required={}",
        user.platform_user_id,
        effective_user_id(user),
        sub_required,
    )
    if sub_required:
        # Offer both monthly and season subscription options
        monthly_payment = await create_payment(
            amount_kopecks=monthly_price,
            description="Подписка на 1 месяц — мото-бот",
            metadata=subscription_metadata(user, "monthly", platform="max"),
            return_url=get_settings().max_return_url,
        )
        season_payment = await create_payment(
            amount_kopecks=season_price,
            description="Подписка на год (365 дней) — мото-бот",
            metadata=subscription_metadata(user, "season", platform="max"),
            return_url=get_settings().max_return_url,
        )

        from src.services.subscription_messages import max_profile_subscription_block

        paywall = await max_profile_subscription_block()
        text = (
            "👤 Мой профиль\n\n" + paywall + "\n\n"
            f"• 1 месяц — {monthly_price // 100} ₽\n"
            f"• Год (365 дн.) — {season_price // 100} ₽\n\n"
            "Выбери тариф и оплати по ссылке. После оплаты нажми «Я оплатил — проверить»."
        )
        kb = []
        # Store both payment IDs so "Я оплатил" can check whichever was paid
        fsm_data: dict = {}
        if monthly_payment and monthly_payment.get("confirmation_url"):
            kb.append(
                [
                    Button(
                        f"💳 1 месяц — {monthly_price // 100} ₽",
                        type=ButtonType.URL,
                        url=monthly_payment["confirmation_url"],
                    )
                ]
            )
            fsm_data["monthly_payment_id"] = monthly_payment["id"]
        if season_payment and season_payment.get("confirmation_url"):
            kb.append(
                [
                    Button(
                        f"💳 Год (365 дн.) — {season_price // 100} ₽",
                        type=ButtonType.URL,
                        url=season_payment["confirmation_url"],
                    )
                ]
            )
            fsm_data["season_payment_id"] = season_payment["id"]
        if fsm_data:
            await reg_state.set_state(user.platform_user_id, "pay:subscription", fsm_data)
        if kb:
            kb.append([Button("✅ Я оплатил — проверить", payload="max_pay_sub_check")])
        _tg_pay = get_settings().telegram_return_url
        if _tg_pay:
            kb.append(
                [Button("✏️ Редактировать анкету (Telegram)", type=ButtonType.URL, url=_tg_pay)]
            )
        kb.append(get_main_menu_shortcut_row())
        logger.info(
            "profile_photo: paywall branch (фото не отправляем — только текст оплаты) max_uid={}",
            user.platform_user_id,
        )
        await adapter.send_message(chat_id, text, kb)
    else:
        # Subscription active — show profile menu (с фото как в мотопаре)
        from src.services.profile_service import get_profile_display
        from src.services.admin_service import get_subscription_settings as _get_sub_settings

        try:
            profile_text, photo_ref = await get_profile_display(user)
        except Exception as e:
            logger.warning(
                "handle_profile: get_profile_display failed for user_id={}: {}",
                effective_user_id(user),
                e,
            )
            profile_text = "👤 Мой профиль\n\nПодписка активна."
            photo_ref = None

        pr = photo_ref or ""
        logger.info(
            "profile_photo: after_display max_uid={} has_photo_ref={} ref_len={} ref_prefix={!r}",
            user.platform_user_id,
            bool(photo_ref),
            len(pr),
            pr[:20] if pr else "",
        )

        sub_settings2 = await _get_sub_settings()
        raise_enabled = (
            sub_settings2 and sub_settings2.raise_profile_enabled if sub_settings2 else False
        )
        raise_price = (
            sub_settings2.raise_profile_price_kopecks
            if sub_settings2 and sub_settings2.raise_profile_price_kopecks
            else 0
        )

        kb = [[Button("🔄 Продлить подписку", payload="max_profile_renew_sub")]]
        kb.append([Button(texts.PHONE_CHANGE_BTN, payload="max_profile_phone")])
        kb.append([Button("🏙️ Сменить город", payload="max_profile_city")])
        tg_url = get_settings().telegram_return_url
        if tg_url:
            kb.append(
                [Button("✏️ Редактировать анкету", type=ButtonType.URL, url=tg_url)],
            )
        if raise_enabled:
            label = (
                f"⬆️ Поднять анкету — {raise_price // 100} ₽"
                if raise_price > 0
                else "⬆️ Поднять анкету (бесплатно)"
            )
            kb.append([Button(label, payload="max_profile_raise")])
        kb.append(get_main_menu_shortcut_row())

        await _max_send_photo_caption_keyboard(
            adapter, chat_id, photo_ref, profile_text, kb, log_ctx="profile_photo"
        )


async def handle_about(adapter: MaxAdapter, chat_id: str) -> None:
    from src.handlers.about import get_about_display_full_text

    text = await get_about_display_full_text()
    kb = [
        [Button("❤️ Поддержать проект", payload="max_donate")],
        get_main_menu_shortcut_row(),
    ]
    chunks = split_plain_text_chunks(text, max_len=3500)
    for part in chunks:
        await adapter.send_message(chat_id, part, kb)


# ── MAX payment FSM helpers ────────────────────────────────────────────────────

_PAY_KEY_PREFIX = "max_pay:"
_PAY_TTL = 86_400  # 24 hours — user may pay and return later


async def _pay_set(user_id: int, data: dict) -> None:
    """Store payment pending state for MAX user (reuses reg_state Redis/memory)."""
    key = f"{_PAY_KEY_PREFIX}{user_id}"
    import json

    payload = json.dumps(data, ensure_ascii=False)
    from src.services import max_registration_state as _rs

    if _rs._redis_client is not None:
        try:
            await _rs._redis_client.set(key, payload, ex=_PAY_TTL)
            return
        except Exception as exc:
            logger.warning("max_pay set Redis error: %s", exc)
    _rs._memory_store[f"pay_{user_id}"] = data


async def _pay_get(user_id: int) -> dict | None:
    """Get payment pending state for MAX user."""
    import json
    from src.services import max_registration_state as _rs

    key = f"{_PAY_KEY_PREFIX}{user_id}"
    if _rs._redis_client is not None:
        try:
            val = await _rs._redis_client.get(key)
            if val:
                return json.loads(val)
            return None
        except Exception as exc:
            logger.warning("max_pay get Redis error: %s", exc)
    return _rs._memory_store.get(f"pay_{user_id}")


async def _pay_clear(user_id: int) -> None:
    """Clear payment pending state for MAX user."""
    from src.services import max_registration_state as _rs

    key = f"{_PAY_KEY_PREFIX}{user_id}"
    if _rs._redis_client is not None:
        try:
            await _rs._redis_client.delete(key)
            return
        except Exception as exc:
            logger.warning("max_pay clear Redis error: %s", exc)
    _rs._memory_store.pop(f"pay_{user_id}", None)


# ── MAX payment callback handlers ─────────────────────────────────────────────


async def _handle_payment_callback(adapter: MaxAdapter, chat_id: str, user, data: str) -> bool:
    """Handle all max_pay_* callbacks. Returns True if consumed."""

    # ── Subscription check ────────────────────────────────────────────────────
    if data == "max_pay_sub_check":
        pay_data = await _pay_get(user.platform_user_id)
        if not pay_data:
            # Try to check via FSM state (set in handle_profile / renew)
            fsm = await reg_state.get_state(user.platform_user_id)
            if fsm and fsm.get("state") == "pay:subscription":
                pay_data = fsm.get("data", {})
            else:
                await adapter.send_message(
                    chat_id,
                    "Платёж не найден. Вернись в профиль и начни оплату заново.",
                    get_back_to_menu_rows(),
                )
                return True

        from src.services.payment import check_payment_status

        # Check both season and monthly payments — user may have paid either one.
        # Season takes priority: if both somehow succeeded, activate season.
        season_pid = pay_data.get("season_payment_id")
        monthly_pid = pay_data.get("monthly_payment_id")
        # Legacy FSM had a single "payment_id" field
        legacy_pid = pay_data.get("payment_id")
        legacy_period = pay_data.get("period", "monthly")

        matched_pid: str | None = None
        matched_period: str = "monthly"

        if season_pid:
            s = await check_payment_status(season_pid)
            if s == "succeeded":
                matched_pid = season_pid
                matched_period = "season"
        if matched_pid is None and monthly_pid:
            s = await check_payment_status(monthly_pid)
            if s == "succeeded":
                matched_pid = monthly_pid
                matched_period = "monthly"
        if matched_pid is None and legacy_pid:
            s = await check_payment_status(legacy_pid)
            if s == "succeeded":
                matched_pid = legacy_pid
                matched_period = legacy_period

        if matched_pid:
            from src.services.subscription import activate_subscription

            ok = await activate_subscription(effective_user_id(user), matched_period, matched_pid)
            await reg_state.clear_state(user.platform_user_id)
            await _pay_clear(user.platform_user_id)
            if ok:
                period_label = "1 месяц" if matched_period == "monthly" else "год (365 дней)"
                await adapter.send_message(
                    chat_id,
                    f"✅ Подписка активирована на {period_label}! Добро пожаловать.",
                    await _main_menu_rows_for(user),
                )
            else:
                await adapter.send_message(
                    chat_id,
                    "Оплата прошла, но подписка не активировалась. Обратись в поддержку.",
                    get_back_to_menu_rows(),
                )
        else:
            # Check for explicit cancellation
            all_canceled = True
            for pid in filter(None, [season_pid, monthly_pid, legacy_pid]):
                st = await check_payment_status(pid)
                if st != "canceled":
                    all_canceled = False
                    break
            if all_canceled and any([season_pid, monthly_pid, legacy_pid]):
                await reg_state.clear_state(user.platform_user_id)
                await _pay_clear(user.platform_user_id)
                await adapter.send_message(chat_id, "❌ Платёж отменён.", get_back_to_menu_rows())
            else:
                await adapter.send_message(
                    chat_id,
                    "Платёж ещё не обработан. Подожди несколько секунд и нажми «Я оплатил — проверить» снова.",
                    [
                        [Button("✅ Я оплатил — проверить", payload="max_pay_sub_check")],
                        get_main_menu_shortcut_row(),
                    ],
                )
        return True

    # ── Renew subscription ────────────────────────────────────────────────────
    if data == "max_profile_renew_sub":
        from src.services.admin_service import get_subscription_settings
        from src.services.payment import create_payment

        sub_settings = await get_subscription_settings()
        monthly_price = (
            sub_settings.monthly_price_kopecks
            if sub_settings and sub_settings.monthly_price_kopecks
            else 29900
        )
        season_price = (
            sub_settings.season_price_kopecks
            if sub_settings and sub_settings.season_price_kopecks
            else 79900
        )

        monthly_payment = await create_payment(
            amount_kopecks=monthly_price,
            description="Продление подписки на 1 месяц — мото-бот",
            metadata=subscription_metadata(user, "monthly", platform="max"),
            return_url=get_settings().max_return_url,
        )
        season_payment = await create_payment(
            amount_kopecks=season_price,
            description="Продление подписки на год (365 дней) — мото-бот",
            metadata=subscription_metadata(user, "season", platform="max"),
            return_url=get_settings().max_return_url,
        )

        text = (
            "Продление подписки:\n\n"
            f"• 1 месяц — {monthly_price // 100} ₽\n"
            f"• Год (365 дн.) — {season_price // 100} ₽\n\n"
            "Оплати по ссылке и нажми «Я оплатил — проверить»."
        )
        # Store both payment IDs so "Я оплатил" can check whichever was paid
        kb = []
        renew_fsm: dict = {}
        if monthly_payment and monthly_payment.get("confirmation_url"):
            kb.append(
                [
                    Button(
                        f"💳 1 месяц — {monthly_price // 100} ₽",
                        type=ButtonType.URL,
                        url=monthly_payment["confirmation_url"],
                    )
                ]
            )
            renew_fsm["monthly_payment_id"] = monthly_payment["id"]
        if season_payment and season_payment.get("confirmation_url"):
            kb.append(
                [
                    Button(
                        f"💳 Год (365 дн.) — {season_price // 100} ₽",
                        type=ButtonType.URL,
                        url=season_payment["confirmation_url"],
                    )
                ]
            )
            renew_fsm["season_payment_id"] = season_payment["id"]
        if renew_fsm:
            await reg_state.set_state(user.platform_user_id, "pay:subscription", renew_fsm)
        if kb:
            kb.append([Button("✅ Я оплатил — проверить", payload="max_pay_sub_check")])
        kb.append([Button("« Профиль", payload="menu_profile")])
        kb.append(get_main_menu_shortcut_row())
        await adapter.send_message(chat_id, text, kb)
        return True

    # ── Profile raise ─────────────────────────────────────────────────────────
    if data == "max_profile_raise":
        from src.services.admin_service import get_subscription_settings
        from src.services.payment import create_payment
        from src.models.user import UserRole

        sub_settings = await get_subscription_settings()
        if not sub_settings or not sub_settings.raise_profile_enabled:
            await adapter.send_message(
                chat_id, "Поднятие анкеты сейчас недоступно.", get_back_to_menu_rows()
            )
            return True

        price = sub_settings.raise_profile_price_kopecks or 0
        role = "pilot" if user.role == UserRole.PILOT else "passenger"

        if price <= 0:
            from src.services.motopair_service import raise_profile

            ok = await raise_profile(effective_user_id(user), role)
            if ok:
                await adapter.send_message(
                    chat_id,
                    "✅ Анкета поднята! Тебя будут видеть выше в поиске.",
                    get_back_to_menu_rows(),
                )
            else:
                await adapter.send_message(
                    chat_id, "Ошибка при поднятии анкеты.", get_back_to_menu_rows()
                )
            return True

        payment = await create_payment(
            amount_kopecks=price,
            description="Поднятие анкеты — мото-бот",
            metadata={
                "type": "raise_profile",
                "user_id": str(effective_user_id(user)),
                "role": role,
                "platform": "max",
            },
            return_url=get_settings().max_return_url,
        )
        if not payment or not payment.get("confirmation_url"):
            await adapter.send_message(
                chat_id,
                "Платёжный сервис временно недоступен. Попробуй позже.",
                get_back_to_menu_rows(),
            )
            return True

        await _pay_set(
            user.platform_user_id,
            {
                "type": "raise_profile",
                "payment_id": payment["id"],
                "role": role,
            },
        )
        kb = [
            [
                Button(
                    f"💳 Оплатить — {price // 100} ₽",
                    type=ButtonType.URL,
                    url=payment["confirmation_url"],
                )
            ],
            [Button("✅ Я оплатил — проверить", payload="max_pay_raise_check")],
            [Button("« Профиль", payload="menu_profile")],
            get_main_menu_shortcut_row(),
        ]
        await adapter.send_message(
            chat_id,
            f"⬆️ Поднятие анкеты — <b>{price // 100} ₽</b>\n\nОплати и нажми «Я оплатил — проверить».",
            kb,
        )
        return True

    # ── Profile raise check ───────────────────────────────────────────────────
    if data == "max_pay_raise_check":
        pay_data = await _pay_get(user.platform_user_id)
        if not pay_data or pay_data.get("type") != "raise_profile":
            await adapter.send_message(
                chat_id, "Платёж не найден. Начни поднятие анкеты заново.", get_back_to_menu_rows()
            )
            return True

        from src.services.payment import check_payment_status
        from src.services.motopair_service import raise_profile

        payment_id = pay_data.get("payment_id")
        role = pay_data.get("role", "pilot")
        status = await check_payment_status(payment_id)

        if status == "succeeded":
            await _pay_clear(user.platform_user_id)
            ok = await raise_profile(effective_user_id(user), role)
            if ok:
                await adapter.send_message(
                    chat_id,
                    "✅ Оплата прошла! Анкета поднята — тебя увидят первым.",
                    get_back_to_menu_rows(),
                )
            else:
                await adapter.send_message(
                    chat_id,
                    "Оплата прошла, но поднять анкету не удалось. Обратись в поддержку.",
                    get_back_to_menu_rows(),
                )
        elif status == "canceled":
            await _pay_clear(user.platform_user_id)
            await adapter.send_message(chat_id, "❌ Платёж отменён.", get_back_to_menu_rows())
        else:
            await adapter.send_message(
                chat_id,
                "Платёж ещё не обработан. Подожди и попробуй снова.",
                [
                    [Button("✅ Я оплатил — проверить", payload="max_pay_raise_check")],
                    [Button("« Профиль", payload="menu_profile")],
                    get_main_menu_shortcut_row(),
                ],
            )
        return True

    # ── Donate ────────────────────────────────────────────────────────────────
    if data == "max_donate":
        DONATE_AMOUNTS = [(10000, "100 ₽"), (30000, "300 ₽"), (50000, "500 ₽"), (100000, "1000 ₽")]
        kb = [[Button(label, payload=f"max_donate_amount_{kop}")] for kop, label in DONATE_AMOUNTS]
        kb.append([Button("« О нас", payload="menu_about")])
        kb.append(get_main_menu_shortcut_row())
        await adapter.send_message(chat_id, "❤️ Поддержать проект — выбери сумму:", kb)
        return True

    if data.startswith("max_donate_amount_"):
        amount_str = data.replace("max_donate_amount_", "")
        try:
            amount_kop = int(amount_str)
        except ValueError:
            await adapter.send_message(chat_id, "Ошибка суммы.", get_back_to_menu_rows())
            return True

        from src.services.payment import create_payment

        payment = await create_payment(
            amount_kopecks=amount_kop,
            description="Донат — поддержка бота мото-сообщества",
            metadata=donate_metadata(user, platform="max"),
            return_url=get_settings().max_return_url,
        )
        if not payment or not payment.get("confirmation_url"):
            await adapter.send_message(
                chat_id, "Не удалось создать платёж. Попробуй позже.", get_back_to_menu_rows()
            )
            return True

        kb = [
            [
                Button(
                    f"💳 Оплатить — {amount_kop // 100} ₽",
                    type=ButtonType.URL,
                    url=payment["confirmation_url"],
                )
            ],
            [Button("« О нас", payload="menu_about")],
            get_main_menu_shortcut_row(),
        ]
        await adapter.send_message(
            chat_id, "Спасибо за поддержку! Перейди по ссылке для оплаты:", kb
        )
        return True

    # ── Event create (MAX) ────────────────────────────────────────────────────
    if data == "max_event_create":
        from src.services.subscription import check_subscription_required
        from src.services.subscription_messages import subscription_required_message

        if await check_subscription_required(user):
            await adapter.send_message(
                chat_id,
                await subscription_required_message("events_create"),
                [
                    [Button("👤 Мой профиль", payload="menu_profile")],
                    [Button("« Мероприятия", payload="menu_events")],
                    get_main_menu_shortcut_row(),
                ],
            )
            return True
        if not user.city_id:
            await adapter.send_message(
                chat_id, "Сначала выбери город в /start.", get_back_to_menu_rows()
            )
            return True
        kb = [
            [Button("Масштабное", payload="max_evcreate_type_large")],
            [Button("Мотопробег", payload="max_evcreate_type_motorcade")],
            [Button("Прохват", payload="max_evcreate_type_run")],
            [Button("« Мероприятия", payload="menu_events")],
            get_main_menu_shortcut_row(),
        ]
        await adapter.send_message(chat_id, "Тип мероприятия:", kb)
        return True

    if data.startswith("max_evcreate_type_"):
        ev_type = data.replace("max_evcreate_type_", "")
        if ev_type not in ("large", "motorcade", "run"):
            return True

        from src.services.admin_service import get_subscription_settings
        from src.services.payment import create_payment
        from src.services.event_service import event_creation_payment_required

        sub_settings = await get_subscription_settings()
        eff_uid = effective_user_id(user)
        needs_payment, price = await event_creation_payment_required(
            eff_uid,
            user.platform_user_id,
            user.city_id,
            ev_type,
            sub_settings,
            apply_subscription_benefits=True,
        )

        if needs_payment and price and price > 0:
            from src.services.event_creation_credit import has_event_creation_credit

            if await has_event_creation_credit(eff_uid, ev_type):
                from src.services.max_registration_state import _TTL_EVENT_CREATE

                await reg_state.set_state(
                    user.platform_user_id,
                    "event_create:title",
                    {"event_type": ev_type},
                    ttl=_TTL_EVENT_CREATE,
                )
                await adapter.send_message(
                    chat_id,
                    "✅ Оплата за этот тип мероприятия уже засчитана. "
                    "Введи название мероприятия (или «Пропустить»):",
                    _cancel_kb(),
                )
                return True

            payment = await create_payment(
                amount_kopecks=price,
                description="Создание мероприятия — мото-бот",
                metadata={
                    "type": "event_creation",
                    "user_id": str(eff_uid),
                    "event_type": ev_type,
                    "platform": "max",
                },
                return_url=get_settings().max_return_url,
            )
            if not payment or not payment.get("confirmation_url"):
                await adapter.send_message(
                    chat_id, "Платёжный сервис временно недоступен.", get_back_to_menu_rows()
                )
                return True

            await _pay_set(
                user.platform_user_id,
                {
                    "type": "event_creation",
                    "payment_id": payment["id"],
                    "event_type": ev_type,
                },
            )
            kb = [
                [
                    Button(
                        f"💳 Оплатить — {price // 100} ₽",
                        type=ButtonType.URL,
                        url=payment["confirmation_url"],
                    )
                ],
                [Button("✅ Я оплатил — проверить", payload="max_pay_event_check")],
                [Button("« Мероприятия", payload="menu_events")],
                get_main_menu_shortcut_row(),
            ]
            await adapter.send_message(
                chat_id,
                f"💳 Создание мероприятия платное: <b>{price // 100} ₽</b>\n\nОплати и нажми «Я оплатил — проверить».",
                kb,
            )
            return True

        # No payment needed — start FSM for event creation
        await reg_state.set_state(
            user.platform_user_id, "event_create:title", {"event_type": ev_type}
        )
        await adapter.send_message(
            chat_id, "Введи название мероприятия (или «Пропустить»):", _cancel_kb()
        )
        return True

    if data == "max_pay_event_check":
        pay_data = await _pay_get(user.platform_user_id)
        if not pay_data or pay_data.get("type") != "event_creation":
            await adapter.send_message(
                chat_id,
                "Платёж не найден. Начни создание мероприятия заново.",
                get_back_to_menu_rows(),
            )
            return True

        from src.services.payment import check_payment_status

        payment_id = pay_data.get("payment_id")
        ev_type = pay_data.get("event_type", "run")
        status = await check_payment_status(payment_id)

        if status == "succeeded":
            await _pay_clear(user.platform_user_id)
            from src.services.event_creation_credit import grant_event_creation_credit
            from src.services.max_registration_state import _TTL_EVENT_CREATE

            await grant_event_creation_credit(effective_user_id(user), ev_type)
            await reg_state.set_state(
                user.platform_user_id, "event_create:title", {"event_type": ev_type},
                ttl=_TTL_EVENT_CREATE,
            )
            await adapter.send_message(
                chat_id,
                "✅ Оплата прошла! Введи название мероприятия (или «Пропустить»):",
                _cancel_kb(),
            )
        elif status == "canceled":
            await _pay_clear(user.platform_user_id)
            await adapter.send_message(chat_id, "❌ Платёж отменён.", get_back_to_menu_rows())
        else:
            await adapter.send_message(
                chat_id,
                "Платёж ещё не обработан. Подожди и попробуй снова.",
                [
                    [Button("✅ Я оплатил — проверить", payload="max_pay_event_check")],
                    [Button("« Мероприятия", payload="menu_events")],
                    get_main_menu_shortcut_row(),
                ],
            )
        return True

    return False
