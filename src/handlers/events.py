"""Events block."""
import uuid
from datetime import datetime

from loguru import logger
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.keyboards.menu import get_back_to_menu_kb
from src.models.user import effective_user_id
from src.utils.callback_short import get_pair_callback
from src.keyboards.events import (
    get_events_menu_kb,
    get_event_list_filter_kb,
    get_event_card_kb,
    get_seeking_confirm_kb,
    get_seeking_list_kb,
    get_pair_request_kb,
    get_my_events_kb,
    get_my_event_detail_kb,
)
from src.services.event_service import (
    get_events_list,
    get_event_by_id,
    create_event,
    update_event,
    register_for_event,
    set_seeking_pair,
    get_seeking_users,
    get_user_registration,
    send_pair_request,
    accept_pair_request,
    reject_pair_request,
    get_creator_events,
    cancel_event,
    get_profile_display,
    TYPE_LABELS,
    RIDE_LABELS,
)


router = Router()


class EventCreateStates(StatesGroup):
    awaiting_payment = State()  # Waiting for event creation payment confirmation
    type = State()
    title = State()
    start_date = State()
    start_time = State()
    point_start = State()
    point_end = State()
    ride_type = State()
    avg_speed = State()
    description = State()


class EventEditStates(StatesGroup):
    """FSM for editing an existing event's fields."""
    field = State()      # Choosing which field to edit
    title = State()
    start_date = State()
    start_time = State()
    point_start = State()
    point_end = State()
    description = State()


def _format_location(value: str | None) -> str:
    """Return a Maps link if value looks like coordinates, otherwise return as-is."""
    if not value:
        return "—"
    import re

    from src.utils.yandex_maps import yandex_maps_href_for_html

    if re.match(r"^-?\d+\.\d+,-?\d+\.\d+$", value.strip()):
        lat, lon = value.strip().split(",")
        href = yandex_maps_href_for_html(float(lat), float(lon))
        return f'<a href="{href}">📍 Открыть на карте</a>'
    return value


def _format_event_card(e) -> str:
    return (
        f"<b>{e.title or TYPE_LABELS.get(e.type.value, e.type.value)}</b>\n"
        f"Тип: {TYPE_LABELS.get(e.type.value, e.type.value)}\n"
        f"📅 {e.start_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 Старт: {_format_location(e.point_start)}\n"
        f"📍 Финиш: {_format_location(e.point_end)}\n"
        f"Формат: {RIDE_LABELS.get(e.ride_type.value if e.ride_type else '', '—')}\n"
        f"Скорость: {e.avg_speed or '—'} км/ч\n"
        f"Описание: {e.description or '—'}"
    )


def _format_event_share_text(e) -> str:
    """Generate shareable plain text for an event (no HTML tags)."""
    type_label = TYPE_LABELS.get(e.type.value, e.type.value)
    title = e.title or type_label
    lines = [
        f"🏍 {type_label}: {title}",
        f"📅 {e.start_at.strftime('%d.%m.%Y в %H:%M')}",
    ]
    if e.point_start:
        lines.append(f"📍 Старт: {e.point_start}")
    if e.point_end:
        lines.append(f"🏁 Финиш: {e.point_end}")
    if e.description:
        lines.append(f"\n{e.description}")
    return "\n".join(lines)


@router.callback_query(F.data == "menu_events")
async def cb_events_menu(callback: CallbackQuery, user=None):
    from src.services.subscription import check_subscription_required
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if user and await check_subscription_required(user):
        from src.services.subscription_messages import subscription_required_message

        text = await subscription_required_message("events_menu")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оформить подписку", callback_data="profile_subscribe")],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ])
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as e:
            logger.debug("cb_events_menu: edit_text failed ({}), falling back to answer", e)
            await callback.message.answer(text, reply_markup=kb)
        await callback.answer()
        return

    try:
        await callback.message.edit_text("📅 Мероприятия", reply_markup=get_events_menu_kb())
    except TelegramBadRequest as e:
        logger.debug("cb_events_menu: edit_text failed ({}), falling back to answer", e)
        await callback.message.answer("📅 Мероприятия", reply_markup=get_events_menu_kb())
    await callback.answer()


# ——— Create ———
def _evcreate_type_kb() -> "InlineKeyboardMarkup":
    """Keyboard for selecting event type."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Масштабное", callback_data="evcreate_type_large"),
            InlineKeyboardButton(text="Мотопробег", callback_data="evcreate_type_motorcade"),
            InlineKeyboardButton(text="Прохват", callback_data="evcreate_type_run"),
        ],
        [InlineKeyboardButton(text="« Отмена", callback_data="menu_events")],
    ])


@router.callback_query(F.data == "event_create")
async def cb_event_create_start(callback: CallbackQuery, state: FSMContext, user=None):
    if not user or not user.city_id:
        await callback.message.edit_text("Сначала выбери город в /start.", reply_markup=get_back_to_menu_kb())
        await callback.answer()
        return

    await state.set_state(EventCreateStates.type)
    await callback.message.edit_text("Тип мероприятия:", reply_markup=_evcreate_type_kb())
    await callback.answer()


@router.callback_query(F.data == "evcreate_checkpay", EventCreateStates.awaiting_payment)
async def cb_evcreate_check_payment(callback: CallbackQuery, state: FSMContext, user=None):
    """User clicked 'I paid — check'. Verify payment status via YooKassa."""
    from src.services.payment import check_payment_status

    data = await state.get_data()
    payment_id = data.get("event_payment_id")
    if not payment_id:
        await callback.answer("Ошибка: платёж не найден.", show_alert=True)
        return

    status = await check_payment_status(payment_id)
    if status == "succeeded":
        await state.set_state(EventCreateStates.title)
        await callback.message.edit_text("✅ Оплата прошла! Введи название мероприятия (или «Пропустить»):")
    elif status == "canceled":
        await state.clear()
        await callback.message.edit_text("❌ Платёж отменён.", reply_markup=get_back_to_menu_kb())
    else:
        await callback.answer(
            "Платёж ещё не обработан. Подожди несколько секунд и попробуй ещё раз.",
            show_alert=True,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("evcreate_type_"), EventCreateStates.type)
async def cb_evcreate_type(callback: CallbackQuery, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.admin_service import get_subscription_settings
    from src.services.payment import create_payment
    from src.services.event_service import event_creation_payment_required

    ev_type = callback.data.replace("evcreate_type_", "")
    if ev_type not in ("large", "motorcade", "run"):
        await callback.answer("Неизвестный тип.", show_alert=True)
        return

    await state.update_data(event_type=ev_type)

    settings_db = await get_subscription_settings()
    eff_id = effective_user_id(user)
    needs_payment, price = await event_creation_payment_required(
        eff_id, user.platform_user_id, user.city_id, ev_type, settings_db
    )

    if needs_payment and price and price > 0:
        from src.config import get_settings
        s = get_settings()
        payment = await create_payment(
            amount_kopecks=price,
            description="Создание мероприятия",
            metadata={"type": "event_creation", "user_id": str(eff_id), "event_type": ev_type},
            return_url=s.telegram_return_url or "https://t.me",
        )
        if payment and payment.get("confirmation_url"):
            await state.set_state(EventCreateStates.awaiting_payment)
            await state.update_data(event_payment_id=payment["id"])
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
                [InlineKeyboardButton(text="✅ Я оплатил — проверить", callback_data="evcreate_checkpay")],
                [InlineKeyboardButton(text="« Отмена", callback_data="menu_events")],
            ])
            price_rub = price // 100
            await callback.message.edit_text(
                f"💳 Создание мероприятия платное: <b>{price_rub} ₽</b>\n\n"
                f"Оплати и нажми «Я оплатил — проверить».",
                reply_markup=kb,
            )
            await callback.answer()
            return
        await callback.answer("Платёжный сервис недоступен.", show_alert=True)
        return

    await state.set_state(EventCreateStates.title)
    await callback.message.edit_text("Введи название мероприятия (или «Пропустить»):")
    await callback.answer()


@router.message(EventCreateStates.title, F.text)
async def evcreate_title(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    event_type = data.get("event_type", "")

    if text.lower() in ("пропустить", "skip", "-"):
        # Для «Масштабных» название обязательно
        if event_type == "large":
            await message.answer(
                "Для масштабного мероприятия название обязательно. Введи название:"
            )
            return
        text = None

    await state.update_data(title=text or None)
    await state.set_state(EventCreateStates.start_date)
    await message.answer("Дата начала (ДД.ММ.ГГГГ):")


def _parse_datetime(date_str: str, time_str: str) -> datetime | None:
    from datetime import datetime as dt_cls
    try:
        d = dt_cls.strptime(date_str.strip(), "%d.%m.%Y").date()
        t = dt_cls.strptime(time_str.strip(), "%H:%M").time()
        return dt_cls.combine(d, t)
    except ValueError:
        return None


@router.message(EventCreateStates.start_date, F.text)
async def evcreate_date(message: Message, state: FSMContext):
    try:
        from datetime import datetime as dt_cls
        d = dt_cls.strptime(message.text.strip(), "%d.%m.%Y").date()
        await state.update_data(start_date=message.text.strip())
        await state.set_state(EventCreateStates.start_time)
        await message.answer("Время начала (ЧЧ:ММ):")
    except ValueError:
        await message.answer("Формат: ДД.ММ.ГГГГ (например 15.06.2025)")


@router.message(EventCreateStates.start_time, F.text)
async def evcreate_time(message: Message, state: FSMContext):
    try:
        from datetime import datetime as dt_cls
        dt_cls.strptime(message.text.strip(), "%H:%M")
        await state.update_data(start_time=message.text.strip())
        await state.set_state(EventCreateStates.point_start)
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        await message.answer(
            "Точка старта — отправь геолокацию кнопкой или введи адрес текстом:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
    except ValueError:
        await message.answer("Формат: ЧЧ:ММ (например 10:00)")


@router.message(EventCreateStates.point_start, F.text)
async def evcreate_point_start(message: Message, state: FSMContext):
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
    await state.update_data(point_start=message.text.strip()[:500])
    await state.set_state(EventCreateStates.point_end)
    kb_inline = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="evcreate_point_end_skip")],
    ])
    await message.answer(
        "Точка финиша — отправь геолокацию кнопкой, введи адрес текстом или нажми «Пропустить»:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Отправить геолокацию", request_location=True)],
                [KeyboardButton(text="Пропустить")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
        ),
    )
    await message.answer("Или нажми:", reply_markup=kb_inline)


@router.message(EventCreateStates.point_start, F.location)
async def evcreate_point_start_location(message: Message, state: FSMContext):
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
    lat = message.location.latitude
    lon = message.location.longitude
    point_str = f"{lat},{lon}"
    await state.update_data(point_start=point_str)
    await state.set_state(EventCreateStates.point_end)
    kb_inline = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="evcreate_point_end_skip")],
    ])
    await message.answer(
        "Точка финиша — отправь геолокацию кнопкой, введи адрес текстом или нажми «Пропустить»:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Отправить геолокацию", request_location=True)],
                [KeyboardButton(text="Пропустить")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
        ),
    )
    await message.answer("Или нажми:", reply_markup=kb_inline)


@router.callback_query(F.data == "evcreate_point_end_skip", EventCreateStates.point_end)
async def cb_evcreate_point_end_skip(callback: CallbackQuery, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

    await state.update_data(point_end=None)
    await state.set_state(EventCreateStates.ride_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Колонна", callback_data="evcreate_ride_column"),
            InlineKeyboardButton(text="Свободная", callback_data="evcreate_ride_free"),
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data="evcreate_ride_skip")],
    ])
    await callback.message.edit_text(
        "Точка финиша — пропущено.\n\nФормат движения:",
        reply_markup=kb,
    )
    try:
        await callback.message.answer("Выберите формат движения:", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logger.warning("evcreate_point_end_skip: answer with ReplyKeyboardRemove failed: %s", e)
    await callback.answer()


@router.message(EventCreateStates.point_end, F.text)
async def evcreate_point_end(message: Message, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-"):
        text = None
    await state.update_data(point_end=text[:500] if text else None)
    await state.set_state(EventCreateStates.ride_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Колонна", callback_data="evcreate_ride_column"),
            InlineKeyboardButton(text="Свободная", callback_data="evcreate_ride_free"),
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data="evcreate_ride_skip")],
    ])
    await message.answer("Формат движения:", reply_markup=ReplyKeyboardRemove())
    await message.answer("Выберите формат движения:", reply_markup=kb)


@router.message(EventCreateStates.point_end, F.location)
async def evcreate_point_end_location(message: Message, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
    lat = message.location.latitude
    lon = message.location.longitude
    await state.update_data(point_end=f"{lat},{lon}")
    await state.set_state(EventCreateStates.ride_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Колонна", callback_data="evcreate_ride_column"),
            InlineKeyboardButton(text="Свободная", callback_data="evcreate_ride_free"),
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data="evcreate_ride_skip")],
    ])
    await message.answer("Формат движения:", reply_markup=ReplyKeyboardRemove())
    await message.answer("Выберите формат движения:", reply_markup=kb)


@router.callback_query(F.data.startswith("evcreate_ride_"), EventCreateStates.ride_type)
async def cb_evcreate_ride(callback: CallbackQuery, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if "skip" in callback.data:
        await state.update_data(ride_type=None)
    else:
        rt = "column" if "column" in callback.data else "free"
        await state.update_data(ride_type=rt)
    await state.set_state(EventCreateStates.avg_speed)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="60 км/ч", callback_data="evcreate_speed_60"),
            InlineKeyboardButton(text="80 км/ч", callback_data="evcreate_speed_80"),
            InlineKeyboardButton(text="100 км/ч", callback_data="evcreate_speed_100"),
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data="evcreate_speed_skip")],
    ])
    await callback.message.edit_text("Средняя скорость:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("evcreate_speed_"), EventCreateStates.avg_speed)
async def cb_evcreate_speed(callback: CallbackQuery, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    val = callback.data.replace("evcreate_speed_", "")
    if val == "skip":
        await state.update_data(avg_speed=None)
    else:
        await state.update_data(avg_speed=int(val))
    await state.set_state(EventCreateStates.description)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="evcreate_desc_skip")],
    ])
    await callback.message.edit_text(
        "Описание (или нажми «Пропустить»):",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(EventCreateStates.avg_speed, F.text)
async def evcreate_avg_speed(message: Message, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    text = message.text.strip().lower()
    if text in ("пропустить", "skip", "-"):
        await state.update_data(avg_speed=None)
    else:
        try:
            v = int(text)
            if 0 < v <= 200:
                await state.update_data(avg_speed=v)
            else:
                await message.answer("Укажи число от 1 до 200.")
                return
        except ValueError:
            await message.answer("Введи число.")
            return
    await state.set_state(EventCreateStates.description)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить ➡️", callback_data="evcreate_desc_skip")],
    ])
    await message.answer(
        "Описание (или нажми «Пропустить»):",
        reply_markup=kb,
    )


@router.callback_query(F.data == "evcreate_desc_skip", EventCreateStates.description)
async def cb_evcreate_desc_skip(callback: CallbackQuery, state: FSMContext, user=None):
    if not user or not user.city_id:
        await callback.answer("Ошибка. Начни заново.", show_alert=True)
        return
    await state.update_data(description=None)
    data = await state.get_data()
    await state.clear()

    start_at = _parse_datetime(data["start_date"], data["start_time"])
    if not start_at:
        await callback.message.answer("Ошибка даты. Создание отменено.", reply_markup=get_back_to_menu_kb())
        await callback.answer()
        return

    ev = await create_event(
        city_id=user.city_id,
        creator_id=effective_user_id(user),
        event_type=data["event_type"],
        title=data.get("title"),
        start_at=start_at,
        point_start=data["point_start"],
        point_end=data.get("point_end"),
        ride_type=data.get("ride_type"),
        avg_speed=data.get("avg_speed"),
        description=None,
    )
    if ev:
        try:
            await callback.message.edit_text(
                f"✅ Мероприятие создано!\n\n{_format_event_card(ev)}",
                reply_markup=get_back_to_menu_kb(),
            )
        except TelegramBadRequest:
            await callback.message.answer(
                f"✅ Мероприятие создано!\n\n{_format_event_card(ev)}",
                reply_markup=get_back_to_menu_kb(),
            )
    else:
        await callback.message.answer("Ошибка при создании.", reply_markup=get_back_to_menu_kb())
    await callback.answer()


@router.message(EventCreateStates.description, F.text)
async def evcreate_description(message: Message, state: FSMContext, user=None):
    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-"):
        text = None
    await state.update_data(description=text[:1000] if text else None)
    data = await state.get_data()
    await state.clear()

    start_at = _parse_datetime(data["start_date"], data["start_time"])
    if not start_at:
        await message.answer("Ошибка даты. Создание отменено.", reply_markup=get_back_to_menu_kb())
        return

    ev = await create_event(
        city_id=user.city_id,
        creator_id=effective_user_id(user),
        event_type=data["event_type"],
        title=data.get("title"),
        start_at=start_at,
        point_start=data["point_start"],
        point_end=data.get("point_end"),
        ride_type=data.get("ride_type"),
        avg_speed=data.get("avg_speed"),
        description=data.get("description"),
    )
    if ev:
        await message.answer(
            f"✅ Мероприятие создано!\n\n{_format_event_card(ev)}",
            reply_markup=get_back_to_menu_kb(),
        )
    else:
        await message.answer("Ошибка при создании.", reply_markup=get_back_to_menu_kb())


# ——— List ———
@router.callback_query(F.data == "event_list")
async def cb_event_list(callback: CallbackQuery, user=None):
    try:
        await callback.message.edit_text(
            "Фильтр по типу:",
            reply_markup=get_event_list_filter_kb(),
        )
    except TelegramBadRequest as e:
        logger.debug("cb_event_list: edit_text failed ({}), falling back to answer", e)
        await callback.message.answer("Фильтр по типу:", reply_markup=get_event_list_filter_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("event_list_"))
async def cb_event_list_filtered(callback: CallbackQuery, user=None):
    parts = callback.data.replace("event_list_", "")
    ev_type = parts if parts in ("large", "motorcade", "run") else None

    events = await get_events_list(user.city_id if user else None, ev_type)
    if not events:
        try:
            await callback.message.edit_text(
                "Мероприятий пока нет.",
                reply_markup=get_back_to_menu_kb(),
            )
        except TelegramBadRequest as e:
            logger.debug("cb_event_list_filtered: edit_text failed ({}), falling back to answer", e)
            await callback.message.answer("Мероприятий пока нет.", reply_markup=get_back_to_menu_kb())
    else:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        rows = []
        for e in events:
            rows.append([InlineKeyboardButton(
                text=f"{e['title']} — {e['date']} (П:{e['pilots']} Д:{e['passengers']})",
                callback_data=f"event_detail_{e['id']}",
            )])
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu_events")])
        try:
            await callback.message.edit_text(
                "Мероприятия:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
        except TelegramBadRequest as e:
            logger.debug("cb_event_list_filtered: edit_text failed ({}), falling back to answer", e)
            await callback.message.answer(
                "Мероприятия:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
    await callback.answer()


# ——— Detail ———
@router.callback_query(F.data.startswith("event_detail_"))
async def cb_event_detail(callback: CallbackQuery, user=None):
    eid = callback.data.replace("event_detail_", "")
    try:
        ev_uuid = uuid.UUID(eid)
    except ValueError:
        await callback.answer("Ошибка.")
        return

    ev = await get_event_by_id(ev_uuid)
    if not ev:
        try:
            await callback.message.edit_text("Мероприятие не найдено.", reply_markup=get_back_to_menu_kb())
        except TelegramBadRequest as e:
            logger.debug("cb_event_detail: edit_text failed ({}), falling back to answer", e)
            await callback.message.answer("Мероприятие не найдено.", reply_markup=get_back_to_menu_kb())
        await callback.answer()
        return

    eff_uid = effective_user_id(user) if user else None
    reg = await get_user_registration(ev_uuid, eff_uid) if eff_uid else None
    user_role = reg.role if reg else None
    can_report = bool(user) and ev.creator_id != eff_uid
    kb = get_event_card_kb(eid, bool(reg), user_role, can_report)
    try:
        await callback.message.edit_text(_format_event_card(ev), reply_markup=kb)
    except TelegramBadRequest as e:
        logger.debug("cb_event_detail: edit_text failed ({}), falling back to answer", e)
        await callback.message.answer(_format_event_card(ev), reply_markup=kb)
    await callback.answer()


# ——— Share ———
@router.callback_query(F.data.startswith("event_share_"))
async def cb_event_share(callback: CallbackQuery, user=None):
    """Send a shareable event card that user can forward to other chats."""
    eid = callback.data.replace("event_share_", "")
    try:
        ev_uuid = uuid.UUID(eid)
    except ValueError:
        await callback.answer("Ошибка.")
        return

    ev = await get_event_by_id(ev_uuid)
    if not ev:
        await callback.answer("Мероприятие не найдено.")
        return

    share_text = _format_event_share_text(ev)
    # Send as a separate message without extra buttons so user can forward it directly
    await callback.message.answer(
        f"👇 Перешли это сообщение в нужный чат:\n\n{share_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« К мероприятию", callback_data=f"event_detail_{eid}")],
        ]),
    )
    await callback.answer()


# ——— Report ———
@router.callback_query(F.data.startswith("event_report_"))
async def cb_event_report(callback: CallbackQuery, user=None):
    """User reports an event. Notifies city admins and superadmins."""
    from src import texts
    from src.services.admin_service import get_city_admins
    from src.config import get_settings

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    eid = callback.data.replace("event_report_", "")
    try:
        ev_uuid = uuid.UUID(eid)
    except ValueError:
        await callback.answer()
        return

    ev = await get_event_by_id(ev_uuid)
    if not ev:
        await callback.answer("Мероприятие не найдено.", show_alert=True)
        return

    if ev.creator_id == effective_user_id(user):
        await callback.answer("Нельзя пожаловаться на своё мероприятие.", show_alert=True)
        return

    ev_title = ev.title or TYPE_LABELS.get(ev.type.value, ev.type.value)
    reporter = f"@{user.platform_username}" if user.platform_username else str(user.platform_user_id)
    admin_text = texts.EVENT_REPORT_ADMIN_TEXT.format(
        reporter=reporter,
        event_title=ev_title,
        event_date=ev.start_at.strftime("%d.%m.%Y %H:%M"),
        event_type=TYPE_LABELS.get(ev.type.value, ev.type.value),
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=texts.EVENT_REPORT_BTN_ACCEPT,
            callback_data=f"admin_evreport_accept_{eid}",
        )],
        [InlineKeyboardButton(
            text=texts.EVENT_REPORT_BTN_REJECT,
            callback_data=f"admin_evreport_reject_{eid}",
        )],
    ])

    settings = get_settings()
    bot = callback.bot
    notified = False

    if ev.city_id:
        admins = await get_city_admins(ev.city_id)
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

    await callback.answer(texts.EVENT_REPORT_SENT, show_alert=False)


# ——— Register ———
@router.callback_query(F.data.startswith("event_register_"))
async def cb_event_register(callback: CallbackQuery, user=None):
    from src.services.subscription import check_subscription_required
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if user and await check_subscription_required(user):
        from src.services.subscription_messages import subscription_required_message

        await callback.message.edit_text(
            await subscription_required_message("events_register"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Оформить подписку", callback_data="profile_subscribe"),
                InlineKeyboardButton(text="◀️ Назад", callback_data="menu_events"),
            ]]),
        )
        await callback.answer()
        return

    parts = callback.data.replace("event_register_", "").split("_")
    if len(parts) < 2:
        await callback.answer()
        return
    eid, role = uuid.UUID(parts[0]), parts[1]
    ok, err = await register_for_event(eid, effective_user_id(user), role)
    if ok:
        await callback.message.edit_text(
            "Записал! Хочешь искать пару (двойку/пилота)?",
            reply_markup=get_seeking_confirm_kb(str(eid)),
        )
    else:
        await callback.answer(err, show_alert=True)
        return
    await callback.answer()


# ——— Seeking ———
@router.callback_query(F.data.startswith("event_seeking_"))
async def cb_event_seeking(callback: CallbackQuery, user=None):
    eid = callback.data.replace("event_seeking_", "")
    await callback.message.edit_text(
        "Кого ищешь?",
        reply_markup=get_seeking_confirm_kb(eid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("event_seek_yes_"))
async def cb_event_seek_yes(callback: CallbackQuery, user=None):
    parts = callback.data.replace("event_seek_yes_", "").split("_")
    eid, target_role = uuid.UUID(parts[0]), parts[1]
    eff_uid = effective_user_id(user)
    reg = await get_user_registration(eid, eff_uid)
    if not reg:
        await callback.answer()
        return
    await set_seeking_pair(eid, eff_uid, True)
    seekers = await get_seeking_users(eid, target_role, exclude_user_id=eff_uid)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if not seekers:
        await callback.message.edit_text(
            "Пока никого нет. Заявки появятся, когда кто-то запишется и тоже включит поиск.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« К мероприятию", callback_data=f"event_detail_{eid}")],
            ]),
        )
    else:
        from src.utils.callback_short import put_pair_callback

        rows = []
        for reg, u in seekers:
            name = await get_profile_display(u.id)
            code = put_pair_callback(eid, u.id)
            rows.append([InlineKeyboardButton(text=name[:40], callback_data=f"epr_{code}")])
        rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"event_detail_{eid}")])
        await callback.message.edit_text(
            "Выбери, кому отправить заявку:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("event_seek_no_"))
async def cb_event_seek_no(callback: CallbackQuery, user=None):
    eid = callback.data.replace("event_seek_no_", "")
    await set_seeking_pair(uuid.UUID(eid), effective_user_id(user), False)
    ev = await get_event_by_id(uuid.UUID(eid))
    await callback.message.edit_text(
        _format_event_card(ev),
        reply_markup=get_event_card_kb(eid, True, None),
    )
    await callback.answer()


# ——— Pair request ———
@router.callback_query(F.data.startswith("epr_"))
async def cb_event_pair_request(callback: CallbackQuery, user=None, bot=None):
    code = callback.data[4:]  # after "epr_"
    pair = get_pair_callback(code)
    if not pair:
        await callback.answer("Заявка устарела.", show_alert=True)
        return
    eid, to_user_id = pair
    ok, msg = await send_pair_request(eid, effective_user_id(user), to_user_id)
    if not ok:
        await callback.answer(msg, show_alert=True)
        return
    to_platform_id = None
    from sqlalchemy import select
    from src.models.user import User
    from src.models.base import get_session_factory
    async with get_session_factory() as session:
        r = await session.execute(select(User).where(User.id == to_user_id))
        u = r.scalar_one_or_none()
        if u:
            to_platform_id = u.platform_user_id
    if bot and to_platform_id:
        from_text = await get_profile_display(effective_user_id(user))
        ev = await get_event_by_id(eid)
        try:
            await bot.send_message(
                to_platform_id,
                f"💌 Заявка на пару!\n\n{from_text} хочет поехать с тобой на мероприятие «{ev.title or 'Мероприятие'}».",
                reply_markup=get_pair_request_kb(str(eid), str(effective_user_id(user))),
            )
        except Exception as e:
            logger.warning(f"Cannot send pair request notification to {to_platform_id}: {e}")
    await callback.answer("Заявка отправлена!")


@router.callback_query(F.data.startswith("epa"))
async def cb_event_pair_accept(callback: CallbackQuery, user=None, bot=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    code = callback.data[3:]  # after "epa"
    pair = get_pair_callback(code)
    if not pair:
        await callback.answer("Заявка устарела.", show_alert=True)
        return
    eid, from_user_id = pair
    ok = await accept_pair_request(eid, from_user_id, effective_user_id(user))
    if not ok:
        await callback.answer()
        return
    ev = await get_event_by_id(eid)
    from_platform_id = None
    from sqlalchemy import select
    from src.models.user import User
    from src.models.base import get_session_factory
    async with get_session_factory() as session:
        r = await session.execute(select(User).where(User.id == from_user_id))
        u = r.scalar_one_or_none()
        if u:
            from_platform_id = u.platform_user_id
    if bot and from_platform_id:
        to_text = await get_profile_display(effective_user_id(user))
        try:
            await bot.send_message(
                from_platform_id,
                f"✅ Заявка принята! {to_text} едет с тобой.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Написать", url=f"tg://user?id={callback.from_user.id}")],
                ]),
            )
        except Exception as e:
            logger.warning(f"Cannot notify user {from_platform_id} about pair accept: {e}")
    await callback.message.edit_text("✅ Заявка принята!")
    await callback.answer()


@router.callback_query(F.data.startswith("epj"))
async def cb_event_pair_reject(callback: CallbackQuery, user=None):
    code = callback.data[3:]  # after "epj"
    pair = get_pair_callback(code)
    if not pair:
        await callback.answer()
        return
    eid, from_user_id = pair
    await reject_pair_request(eid, from_user_id, effective_user_id(user))
    await callback.message.edit_text("Заявка отклонена.")
    await callback.answer()


# ——— My events ———
@router.callback_query(F.data == "event_my")
async def cb_event_my(callback: CallbackQuery, user=None):
    events = await get_creator_events(effective_user_id(user))
    if not events:
        await callback.message.edit_text(
            "Ты ещё не создавал мероприятий.",
            reply_markup=get_back_to_menu_kb(),
        )
    else:
        await callback.message.edit_text(
            "Мои мероприятия:",
            reply_markup=get_my_events_kb(events),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("event_my_detail_"))
async def cb_event_my_detail(callback: CallbackQuery, user=None):
    eid = callback.data.replace("event_my_detail_", "")
    ev = await get_event_by_id(uuid.UUID(eid))
    if not ev or ev.creator_id != effective_user_id(user):
        await callback.answer("Не найдено.", show_alert=True)
        return
    await callback.message.edit_text(
        _format_event_card(ev),
        reply_markup=get_my_event_detail_kb(eid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("event_cancel_"))
async def cb_event_cancel(callback: CallbackQuery, user=None, bot=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    eid = callback.data.replace("event_cancel_", "")
    ev_uuid = uuid.UUID(eid)
    ok, notify_ids = await cancel_event(ev_uuid, effective_user_id(user))
    if not ok:
        await callback.answer("Ошибка.", show_alert=True)
        return
    ev = await get_event_by_id(ev_uuid)
    if bot and ev:
        for pid in notify_ids:
            if pid != callback.from_user.id:
                try:
                    await bot.send_message(
                        pid,
                        f"❌ Мероприятие «{ev.title or 'Мероприятие'}» отменено организатором.",
                    )
                except Exception as e:
                    logger.warning(f"Cannot notify participant {pid} about event cancel: {e}")
    await callback.message.edit_text(
        "Мероприятие отменено. Участники уведомлены.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Мои мероприятия", callback_data="event_my")],
        ]),
    )
    await callback.answer()


# ——— Edit event ———

def _event_edit_field_kb(event_id: str) -> "InlineKeyboardMarkup":
    """Keyboard to choose which event field to edit."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"evedit_f_title_{event_id}")],
        [InlineKeyboardButton(text="📅 Дата", callback_data=f"evedit_f_date_{event_id}")],
        [InlineKeyboardButton(text="⏰ Время", callback_data=f"evedit_f_time_{event_id}")],
        [InlineKeyboardButton(text="📍 Старт", callback_data=f"evedit_f_start_{event_id}")],
        [InlineKeyboardButton(text="🏁 Финиш", callback_data=f"evedit_f_end_{event_id}")],
        [InlineKeyboardButton(text="📝 Описание", callback_data=f"evedit_f_desc_{event_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"event_my_detail_{event_id}")],
    ])


@router.callback_query(F.data.startswith("event_edit_"))
async def cb_event_edit_start(callback: CallbackQuery, state: FSMContext, user=None):
    """Show edit field selection for the event."""
    eid = callback.data.replace("event_edit_", "")
    try:
        ev = await get_event_by_id(uuid.UUID(eid))
    except ValueError:
        await callback.answer("Ошибка.")
        return
    if not ev or ev.creator_id != effective_user_id(user):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await state.set_state(EventEditStates.field)
    await state.update_data(edit_event_id=eid)
    await callback.message.edit_text(
        f"Редактирование: <b>{ev.title or TYPE_LABELS.get(ev.type.value, 'Мероприятие')}</b>\n\n"
        f"Выбери что изменить:",
        reply_markup=_event_edit_field_kb(eid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("evedit_f_"), EventEditStates.field)
async def cb_evedit_choose_field(callback: CallbackQuery, state: FSMContext, user=None):
    """User selected a field to edit."""
    parts = callback.data.replace("evedit_f_", "").split("_", 1)
    field = parts[0]
    eid = parts[1] if len(parts) > 1 else ""

    field_prompts = {
        "title": "Введи новое название (или «-» чтобы убрать):",
        "date": "Введи новую дату (ДД.ММ.ГГГГ):",
        "time": "Введи новое время начала (ЧЧ:ММ):",
        "start": "Введи новую точку старта:",
        "end": "Введи новую точку финиша (или «-» чтобы убрать):",
        "desc": "Введи новое описание (или «-» чтобы убрать):",
    }
    state_map = {
        "title": EventEditStates.title,
        "date": EventEditStates.start_date,
        "time": EventEditStates.start_time,
        "start": EventEditStates.point_start,
        "end": EventEditStates.point_end,
        "desc": EventEditStates.description,
    }
    if field not in field_prompts:
        await callback.answer()
        return

    await state.update_data(edit_event_id=eid, edit_field=field)
    await state.set_state(state_map[field])
    await callback.message.edit_text(field_prompts[field])
    await callback.answer()


async def _apply_event_edit(message: Message, state: FSMContext, user, **kwargs) -> None:
    """Apply a single field edit and show updated event card."""
    from src.services.event_service import update_event

    data = await state.get_data()
    eid_str = data.get("edit_event_id", "")
    await state.clear()

    try:
        eid = uuid.UUID(eid_str)
    except ValueError:
        await message.answer("Ошибка ID мероприятия.", reply_markup=get_back_to_menu_kb())
        return

    ok = await update_event(eid, effective_user_id(user), **kwargs)
    if not ok:
        await message.answer("Ошибка сохранения.", reply_markup=get_back_to_menu_kb())
        return

    ev = await get_event_by_id(eid)
    if ev:
        await message.answer(
            f"✅ Изменено!\n\n{_format_event_card(ev)}",
            reply_markup=get_my_event_detail_kb(eid_str),
        )
    else:
        await message.answer("Сохранено.", reply_markup=get_back_to_menu_kb())


@router.message(EventEditStates.title, F.text)
async def evedit_title(message: Message, state: FSMContext, user=None):
    val = message.text.strip()
    await _apply_event_edit(message, state, user, title=(None if val == "-" else val))


@router.message(EventEditStates.start_date, F.text)
async def evedit_date(message: Message, state: FSMContext, user=None):
    data = await state.get_data()
    ev = await get_event_by_id(uuid.UUID(data.get("edit_event_id", "")))
    try:
        from datetime import datetime as dt_cls
        d = dt_cls.strptime(message.text.strip(), "%d.%m.%Y").date()
        # Keep existing time
        existing_time = ev.start_at.time() if ev else dt_cls.now().time()
        new_dt = dt_cls.combine(d, existing_time)
        await _apply_event_edit(message, state, user, start_at=new_dt)
    except (ValueError, AttributeError):
        await message.answer("Формат: ДД.ММ.ГГГГ (например 15.06.2025)")


@router.message(EventEditStates.start_time, F.text)
async def evedit_time(message: Message, state: FSMContext, user=None):
    data = await state.get_data()
    ev = await get_event_by_id(uuid.UUID(data.get("edit_event_id", "")))
    try:
        from datetime import datetime as dt_cls
        t = dt_cls.strptime(message.text.strip(), "%H:%M").time()
        existing_date = ev.start_at.date() if ev else dt_cls.now().date()
        new_dt = dt_cls.combine(existing_date, t)
        await _apply_event_edit(message, state, user, start_at=new_dt)
    except (ValueError, AttributeError):
        await message.answer("Формат: ЧЧ:ММ (например 14:00)")


@router.message(EventEditStates.point_start, F.text)
async def evedit_point_start(message: Message, state: FSMContext, user=None):
    await _apply_event_edit(message, state, user, point_start=message.text.strip())


@router.message(EventEditStates.point_end, F.text)
async def evedit_point_end(message: Message, state: FSMContext, user=None):
    val = message.text.strip()
    await _apply_event_edit(message, state, user, point_end=(None if val == "-" else val))


@router.message(EventEditStates.description, F.text)
async def evedit_description(message: Message, state: FSMContext, user=None):
    val = message.text.strip()
    await _apply_event_edit(message, state, user, description=(None if val == "-" else val))
