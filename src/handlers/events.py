"""Events block."""
import uuid
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.keyboards.menu import get_back_to_menu_kb
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
    type = State()
    title = State()
    start_date = State()
    start_time = State()
    point_start = State()
    point_end = State()
    ride_type = State()
    avg_speed = State()
    description = State()


def _format_event_card(e) -> str:
    return (
        f"<b>{e.title or TYPE_LABELS.get(e.type.value, e.type.value)}</b>\n"
        f"Тип: {TYPE_LABELS.get(e.type.value, e.type.value)}\n"
        f"📅 {e.start_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 Старт: {e.point_start}\n"
        f"📍 Финиш: {e.point_end or '—'}\n"
        f"Формат: {RIDE_LABELS.get(e.ride_type.value if e.ride_type else '', '—')}\n"
        f"Скорость: {e.avg_speed or '—'} км/ч\n"
        f"Описание: {e.description or '—'}"
    )


@router.callback_query(F.data == "menu_events")
async def cb_events_menu(callback: CallbackQuery, user=None):
    await callback.message.edit_text("📅 Мероприятия", reply_markup=get_events_menu_kb())
    await callback.answer()


# ——— Create ———
@router.callback_query(F.data == "event_create")
async def cb_event_create_start(callback: CallbackQuery, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if not user or not user.city_id:
        await callback.message.edit_text("Сначала выбери город в /start.", reply_markup=get_back_to_menu_kb())
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Масштабное", callback_data="evcreate_type_large"),
            InlineKeyboardButton(text="Мотопробег", callback_data="evcreate_type_motorcade"),
            InlineKeyboardButton(text="Прохват", callback_data="evcreate_type_run"),
        ],
        [InlineKeyboardButton(text="« Отмена", callback_data="menu_events")],
    ])
    await state.set_state(EventCreateStates.type)
    await callback.message.edit_text("Тип мероприятия:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("evcreate_type_"), EventCreateStates.type)
async def cb_evcreate_type(callback: CallbackQuery, state: FSMContext):
    ev_type = callback.data.replace("evcreate_type_", "")
    await state.update_data(event_type=ev_type)
    await state.set_state(EventCreateStates.title)
    await callback.message.edit_text("Введи название мероприятия (или «Пропустить»):")
    await callback.answer()


@router.message(EventCreateStates.title, F.text)
async def evcreate_title(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-"):
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
        await message.answer("Точка старта (адрес или описание):")
    except ValueError:
        await message.answer("Формат: ЧЧ:ММ (например 10:00)")


@router.message(EventCreateStates.point_start, F.text)
async def evcreate_point_start(message: Message, state: FSMContext):
    await state.update_data(point_start=message.text.strip()[:500])
    await state.set_state(EventCreateStates.point_end)
    await message.answer("Точка финиша (или «Пропустить»):")


@router.message(EventCreateStates.point_end, F.text)
async def evcreate_point_end(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-"):
        text = None
    await state.update_data(point_end=text[:500] if text else None)
    await state.set_state(EventCreateStates.ride_type)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Колонна", callback_data="evcreate_ride_column"),
            InlineKeyboardButton(text="Свободная", callback_data="evcreate_ride_free"),
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data="evcreate_ride_skip")],
    ])
    await message.answer("Формат движения:", reply_markup=kb)


@router.callback_query(F.data.startswith("evcreate_ride_"), EventCreateStates.ride_type)
async def cb_evcreate_ride(callback: CallbackQuery, state: FSMContext):
    if "skip" in callback.data:
        await state.update_data(ride_type=None)
    else:
        rt = "column" if "column" in callback.data else "free"
        await state.update_data(ride_type=rt)
    await state.set_state(EventCreateStates.avg_speed)
    await callback.message.edit_text("Средняя скорость (км/ч), число или «Пропустить»:")
    await callback.answer()


@router.message(EventCreateStates.avg_speed, F.text)
async def evcreate_avg_speed(message: Message, state: FSMContext):
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
    await message.answer("Описание (или «Пропустить»):")


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
        creator_id=user.id,
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
    await callback.message.edit_text(
        "Фильтр по типу:",
        reply_markup=get_event_list_filter_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("event_list_"))
async def cb_event_list_filtered(callback: CallbackQuery, user=None):
    parts = callback.data.replace("event_list_", "")
    ev_type = parts if parts in ("large", "motorcade", "run") else None

    events = await get_events_list(user.city_id if user else None, ev_type)
    if not events:
        await callback.message.edit_text(
            "Мероприятий пока нет.",
            reply_markup=get_back_to_menu_kb(),
        )
    else:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        rows = []
        for e in events:
            rows.append([InlineKeyboardButton(
                text=f"{e['title']} — {e['date']} (П:{e['pilots']} Д:{e['passengers']})",
                callback_data=f"event_detail_{e['id']}",
            )])
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu_events")])
        await callback.message.edit_text(
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
        await callback.message.edit_text("Мероприятие не найдено.", reply_markup=get_back_to_menu_kb())
        await callback.answer()
        return

    reg = await get_user_registration(ev_uuid, user.id) if user else None
    user_role = reg.role if reg else None
    kb = get_event_card_kb(eid, bool(reg), user_role)
    await callback.message.edit_text(_format_event_card(ev), reply_markup=kb)
    await callback.answer()


# ——— Register ———
@router.callback_query(F.data.startswith("event_register_"))
async def cb_event_register(callback: CallbackQuery, user=None):
    parts = callback.data.replace("event_register_", "").split("_")
    if len(parts) < 2:
        await callback.answer()
        return
    eid, role = uuid.UUID(parts[0]), parts[1]
    ok, err = await register_for_event(eid, user.id, role)
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
    reg = await get_user_registration(eid, user.id)
    if not reg:
        await callback.answer()
        return
    await set_seeking_pair(eid, user.id, True)
    seekers = await get_seeking_users(eid, target_role, exclude_user_id=user.id)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if not seekers:
        await callback.message.edit_text(
            "Пока никого нет. Заявки появятся, когда кто-то запишется и тоже включит поиск.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« К мероприятию", callback_data=f"event_detail_{eid}")],
            ]),
        )
    else:
        rows = []
        for reg, u in seekers:
            name = await get_profile_display(u.id)
            rows.append([InlineKeyboardButton(
                text=name[:40],
                callback_data=f"event_pair_req_{eid}_{u.id}",
            )])
        rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"event_detail_{eid}")])
        await callback.message.edit_text(
            "Выбери, кому отправить заявку:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("event_seek_no_"))
async def cb_event_seek_no(callback: CallbackQuery, user=None):
    eid = callback.data.replace("event_seek_no_", "")
    await set_seeking_pair(uuid.UUID(eid), user.id, False)
    ev = await get_event_by_id(uuid.UUID(eid))
    await callback.message.edit_text(
        _format_event_card(ev),
        reply_markup=get_event_card_kb(eid, True, None),
    )
    await callback.answer()


# ——— Pair request ———
@router.callback_query(F.data.startswith("event_pair_req_"))
async def cb_event_pair_request(callback: CallbackQuery, user=None, bot=None):
    parts = callback.data.replace("event_pair_req_", "").split("_")
    eid, to_user_id = uuid.UUID(parts[0]), uuid.UUID(parts[1])
    ok, msg = await send_pair_request(eid, user.id, to_user_id)
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
        from_text = await get_profile_display(user.id)
        ev = await get_event_by_id(eid)
        try:
            await bot.send_message(
                to_platform_id,
                f"💌 Заявка на пару!\n\n{from_text} хочет поехать с тобой на мероприятие «{ev.title or 'Мероприятие'}».",
                reply_markup=get_pair_request_kb(str(eid), str(user.id)),
            )
        except Exception:
            pass
    await callback.answer("Заявка отправлена!")


@router.callback_query(F.data.startswith("event_pair_accept_"))
async def cb_event_pair_accept(callback: CallbackQuery, user=None, bot=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    parts = callback.data.replace("event_pair_accept_", "").split("_")
    eid, from_user_id = uuid.UUID(parts[0]), uuid.UUID(parts[1])
    ok = await accept_pair_request(eid, from_user_id, user.id)
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
        to_text = await get_profile_display(user.id)
        try:
            await bot.send_message(
                from_platform_id,
                f"✅ Заявка принята! {to_text} едет с тобой.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Написать", url=f"tg://user?id={callback.from_user.id}")],
                ]),
            )
        except Exception:
            pass
    await callback.message.edit_text("✅ Заявка принята!")
    await callback.answer()


@router.callback_query(F.data.startswith("event_pair_reject_"))
async def cb_event_pair_reject(callback: CallbackQuery, user=None):
    parts = callback.data.replace("event_pair_reject_", "").split("_")
    eid, from_user_id = uuid.UUID(parts[0]), uuid.UUID(parts[1])
    await reject_pair_request(eid, from_user_id, user.id)
    await callback.message.edit_text("Заявка отклонена.")
    await callback.answer()


# ——— My events ———
@router.callback_query(F.data == "event_my")
async def cb_event_my(callback: CallbackQuery, user=None):
    events = await get_creator_events(user.id)
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
    if not ev or ev.creator_id != user.id:
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
    ok, notify_ids = await cancel_event(ev_uuid, user.id)
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
                except Exception:
                    pass
    await callback.message.edit_text(
        "Мероприятие отменено. Участники уведомлены.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Мои мероприятия", callback_data="event_my")],
        ]),
    )
    await callback.answer()
