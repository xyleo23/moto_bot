"""Редактирование анкеты в MAX (без перехода в Telegram)."""

from __future__ import annotations

from src import texts
from src.models.user import User, UserRole, effective_user_id
from src.platforms.base import Button, ButtonType
from src.platforms.max_adapter import MaxAdapter
from src.services import max_registration_state as reg_state
from src.services.profile_edit_service import (
    commit_passenger_profile_edit,
    commit_pilot_profile_edit,
    load_passenger_edit_fields,
    load_pilot_edit_fields,
)
from src.utils.validators import validate_profile_field


def _cancel_kb() -> list:
    return [[Button("❌ Отменить", payload="max_reg_cancel")]]


async def _menu_rows(user: User) -> list:
    from src.keyboards.shared import get_main_menu_rows
    from src.services.admin_service import max_user_should_see_admin_menu

    return get_main_menu_rows(show_admin=await max_user_should_see_admin_menu(user))


def _skip_row() -> list:
    return [[Button(texts.BTN_SKIP, payload="max_profedit_skip")]]


def _parse_state(state: str) -> tuple[str, str] | None:
    if not state.startswith("profile_edit:"):
        return None
    rest = state[len("profile_edit:") :]
    role, _, field = rest.partition(":")
    if role not in ("pilot", "passenger") or not field:
        return None
    return role, field


PILOT_STEPS = ("name", "age", "bike_brand", "bike_model", "engine_cc", "driving_style", "photo", "about")
PAX_STEPS = ("name", "age", "weight", "height", "preferred_style", "photo", "about")


async def max_profile_edit_start(adapter: MaxAdapter, chat_id: str, user: User) -> None:
    """Старт редактирования — как в Telegram: подписка не блокирует вход в мастер."""
    uid = effective_user_id(user)
    if user.role == UserRole.PILOT:
        fields = await load_pilot_edit_fields(uid)
        if not fields:
            await adapter.send_message(chat_id, "Анкета не найдена. Пройди регистрацию.", await _menu_rows(user))
            return
        await reg_state.set_state(user.platform_user_id, "profile_edit:pilot:name", fields)
        await adapter.send_message(
            chat_id,
            f"✏️ <b>Редактирование анкеты</b>\n\nТекущее имя: <b>{fields['name']}</b>\nВведи новое или нажми «Пропустить»:",
            _skip_row() + _cancel_kb(),
        )
    else:
        fields = await load_passenger_edit_fields(uid)
        if not fields:
            await adapter.send_message(chat_id, "Анкета не найдена. Пройди регистрацию.", await _menu_rows(user))
            return
        await reg_state.set_state(user.platform_user_id, "profile_edit:passenger:name", fields)
        await adapter.send_message(
            chat_id,
            f"✏️ <b>Редактирование анкеты</b>\n\nТекущее имя: <b>{fields['name']}</b>\nВведи новое или нажми «Пропустить»:",
            _skip_row() + _cancel_kb(),
        )


def _pilot_style_kb() -> list:
    return [
        [
            Button("Спокойный", payload="max_profedit_plt_style_calm"),
            Button("Динамичный", payload="max_profedit_plt_style_aggressive"),
            Button("Смешанный", payload="max_profedit_plt_style_mixed"),
        ],
        [Button(texts.BTN_SKIP, payload="max_profedit_skip")],
    ] + _cancel_kb()


def _pax_style_kb() -> list:
    return [
        [
            Button("Спокойный", payload="max_profedit_pax_style_calm"),
            Button("Динамичный", payload="max_profedit_pax_style_dynamic"),
            Button("Смешанный", payload="max_profedit_pax_style_mixed"),
        ],
        [Button(texts.BTN_SKIP, payload="max_profedit_skip")],
    ] + _cancel_kb()


async def _send_step_prompt(
    adapter: MaxAdapter, chat_id: str, role: str, field: str, data: dict
) -> None:
    if role == "pilot":
        if field == "name":
            await adapter.send_message(
                chat_id,
                f"Текущее имя: <b>{data.get('name')}</b>\nВведи новое или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
        elif field == "age":
            await adapter.send_message(
                chat_id,
                f"Текущий возраст: <b>{data.get('age')}</b>\nВведи новый или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
        elif field == "bike_brand":
            await adapter.send_message(
                chat_id,
                f"Текущая марка: <b>{data.get('bike_brand')}</b>\nВведи новую или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
        elif field == "bike_model":
            await adapter.send_message(
                chat_id,
                f"Текущая модель: <b>{data.get('bike_model')}</b>\nВведи новую или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
        elif field == "engine_cc":
            await adapter.send_message(
                chat_id,
                f"Текущий объём: <b>{data.get('engine_cc')} см³</b>\nВведи новый или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
        elif field == "driving_style":
            sl = {"calm": "Спокойный", "aggressive": "Динамичный", "mixed": "Смешанный"}
            cur = sl.get(str(data.get("driving_style", "")), "—")
            await adapter.send_message(
                chat_id,
                f"Текущий стиль: <b>{cur}</b>\nВыбери новый или «Пропустить»:",
                _pilot_style_kb(),
            )
        elif field == "photo":
            await adapter.send_message(
                chat_id,
                "Отправь новое фото или «Пропустить» (останется текущее):",
                _skip_row() + _cancel_kb(),
            )
        elif field == "about":
            cur = data.get("about") or "—"
            await adapter.send_message(
                chat_id,
                f"Текущее «О себе»: {cur}\n\nВведи новый текст или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
    else:
        if field == "name":
            await adapter.send_message(
                chat_id,
                f"Текущее имя: <b>{data.get('name')}</b>\nВведи новое или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
        elif field == "age":
            await adapter.send_message(
                chat_id,
                f"Текущий возраст: <b>{data.get('age')}</b>\nВведи новый или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
        elif field == "weight":
            await adapter.send_message(
                chat_id,
                f"Текущий вес: <b>{data.get('weight')} кг</b>\nВведи новый или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
        elif field == "height":
            await adapter.send_message(
                chat_id,
                f"Текущий рост: <b>{data.get('height')} см</b>\nВведи новый или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )
        elif field == "preferred_style":
            sl = {"calm": "Спокойный", "dynamic": "Динамичный", "mixed": "Смешанный"}
            cur = sl.get(str(data.get("preferred_style", "")), "—")
            await adapter.send_message(
                chat_id,
                f"Текущий желаемый стиль: <b>{cur}</b>\nВыбери новый или «Пропустить»:",
                _pax_style_kb(),
            )
        elif field == "photo":
            await adapter.send_message(
                chat_id,
                "Отправь новое фото или «Пропустить» (останется текущее):",
                _skip_row() + _cancel_kb(),
            )
        elif field == "about":
            cur = data.get("about") or "—"
            await adapter.send_message(
                chat_id,
                f"Текущее «О себе»: {cur}\n\nВведи новый текст или «Пропустить»:",
                _skip_row() + _cancel_kb(),
            )


async def _advance(
    adapter: MaxAdapter,
    chat_id: str,
    user_id: int,
    user: User,
    role: str,
    data: dict,
    current_field: str,
    patch: dict | None,
) -> None:
    if patch:
        data.update(patch)
    steps = PILOT_STEPS if role == "pilot" else PAX_STEPS
    try:
        i = steps.index(current_field)
    except ValueError:
        await reg_state.clear_state(user_id)
        await adapter.send_message(chat_id, "Ошибка шага.", await _menu_rows(user))
        return
    if i + 1 >= len(steps):
        uid = effective_user_id(user)
        if role == "pilot":
            ok = await commit_pilot_profile_edit(uid, data)
        else:
            ok = await commit_passenger_profile_edit(uid, data)
        await reg_state.clear_state(user_id)
        if ok:
            await adapter.send_message(chat_id, "✅ Анкета обновлена!", await _menu_rows(user))
        else:
            await adapter.send_message(chat_id, texts.REG_ERROR_SAVE, await _menu_rows(user))
        return
    nxt = steps[i + 1]
    await reg_state.set_state(user_id, f"profile_edit:{role}:{nxt}", data)
    await _send_step_prompt(adapter, chat_id, role, nxt, data)


async def max_profile_edit_handle_message(
    adapter: MaxAdapter, chat_id: str, user_id: int, text: str, user: User, fsm: dict
) -> None:
    state = fsm.get("state") or ""
    parsed = _parse_state(state)
    if not parsed:
        return
    role, field = parsed
    data = dict(fsm.get("data") or {})

    if field == "photo":
        await adapter.send_message(
            chat_id,
            "Отправь фото или нажми «Пропустить».",
            _skip_row() + _cancel_kb(),
        )
        return

    t = (text or "").strip()
    if field == "name":
        ok, err = validate_profile_field("name", text or "")
        if not ok:
            await adapter.send_message(chat_id, err, _skip_row() + _cancel_kb())
            return
        await _advance(adapter, chat_id, user_id, user, role, data, "name", {"name": t})
    elif field == "age":
        ok, err = validate_profile_field("age", text or "")
        if not ok:
            await adapter.send_message(chat_id, err, _cancel_kb())
            return
        age = int(t)
        await _advance(adapter, chat_id, user_id, user, role, data, "age", {"age": age})
    elif field == "bike_brand":
        ok, err = validate_profile_field("moto_brand", text or "")
        if not ok:
            await adapter.send_message(chat_id, err, _skip_row() + _cancel_kb())
            return
        await _advance(adapter, chat_id, user_id, user, role, data, "bike_brand", {"bike_brand": t})
    elif field == "bike_model":
        ok, err = validate_profile_field("moto_model", text or "")
        if not ok:
            await adapter.send_message(chat_id, err, _skip_row() + _cancel_kb())
            return
        await _advance(adapter, chat_id, user_id, user, role, data, "bike_model", {"bike_model": t})
    elif field == "engine_cc":
        try:
            cc = int(t)
            if 50 <= cc <= 3000:
                await _advance(adapter, chat_id, user_id, user, role, data, "engine_cc", {"engine_cc": cc})
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_ENGINE_CC, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
    elif field == "weight":
        try:
            w = int(t)
            if 30 <= w <= 200:
                await _advance(adapter, chat_id, user_id, user, role, data, "weight", {"weight": w})
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_WEIGHT, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
    elif field == "height":
        try:
            h = int(t)
            if 120 <= h <= 220:
                await _advance(adapter, chat_id, user_id, user, role, data, "height", {"height": h})
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_HEIGHT, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
    elif field == "about":
        ok, err = validate_profile_field("about", text or "")
        if not ok:
            await adapter.send_message(chat_id, err, _cancel_kb())
            return
        await _advance(adapter, chat_id, user_id, user, role, data, "about", {"about": t})


async def max_profile_edit_handle_photo(
    adapter: MaxAdapter, chat_id: str, user_id: int, file_id: str, user: User, fsm: dict
) -> None:
    state = fsm.get("state") or ""
    parsed = _parse_state(state)
    if not parsed:
        return
    role, field = parsed
    if field != "photo":
        return
    data = dict(fsm.get("data") or {})
    await _advance(adapter, chat_id, user_id, user, role, data, "photo", {"photo_file_id": file_id})


async def max_profile_edit_handle_callback(
    adapter: MaxAdapter, chat_id: str, user_id: int, cb_data: str, user: User, fsm: dict
) -> bool:
    state = fsm.get("state") or ""
    parsed = _parse_state(state)
    if not parsed:
        return False
    role, field = parsed
    data = dict(fsm.get("data") or {})

    if cb_data == "max_profedit_skip":
        await _advance(adapter, chat_id, user_id, user, role, data, field, None)
        return True

    if field == "driving_style" and cb_data.startswith("max_profedit_plt_style_"):
        st = cb_data.replace("max_profedit_plt_style_", "")
        if st in ("calm", "aggressive", "mixed"):
            await _advance(adapter, chat_id, user_id, user, role, data, "driving_style", {"driving_style": st})
        return True

    if field == "preferred_style" and cb_data.startswith("max_profedit_pax_style_"):
        st = cb_data.replace("max_profedit_pax_style_", "")
        if st == "aggressive":
            st = "dynamic"
        if st in ("calm", "dynamic", "mixed"):
            await _advance(
                adapter, chat_id, user_id, user, role, data, "preferred_style", {"preferred_style": st}
            )
        return True

    return False
