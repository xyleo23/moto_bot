"""Сообщение об ошибке: текст + опционально фото → суперадмины на той же платформе (TG/MAX)."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src import texts
from src.keyboards.menu import get_back_to_menu_kb
from src.services.bug_report_service import send_bug_report_to_superadmins
from src.services.broadcast import get_max_adapter
from src.ui_copy import BTN_BUG_REPORT

router = Router()


class BugReportStates(StatesGroup):
    text = State()
    photo = State()


def _bug_report_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="menu_main")],
        ]
    )


def _bug_report_photo_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Без скриншота", callback_data="bug_report_skip_photo")],
            [InlineKeyboardButton(text="« Отмена", callback_data="menu_main")],
        ]
    )


async def _start_bug_report_telegram(message: Message, state: FSMContext) -> None:
    await state.set_state(BugReportStates.text)
    await message.answer(
        texts.BUG_REPORT_ASK_TEXT,
        reply_markup=_bug_report_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(Command("bug"))
async def cmd_bug(message: Message, state: FSMContext):
    """Команда /bug — то же, что кнопка «Сообщить об ошибке»."""
    cur = await state.get_state()
    if cur is not None:
        await message.answer(texts.BUG_REPORT_BUSY)
        return
    await _start_bug_report_telegram(message, state)


@router.callback_query(F.data == "menu_bug_report")
async def cb_bug_report_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    cur = await state.get_state()
    if cur is not None:
        await callback.message.answer(texts.BUG_REPORT_BUSY)
        return
    await _start_bug_report_telegram(callback.message, state)


@router.message(F.text == BTN_BUG_REPORT)
async def kb_bug_report_start(message: Message, state: FSMContext):
    cur = await state.get_state()
    if cur is not None:
        await message.answer(texts.BUG_REPORT_BUSY)
        return
    await _start_bug_report_telegram(message, state)


@router.message(BugReportStates.text, F.text)
async def bug_report_text(message: Message, state: FSMContext, user=None):
    if not user:
        await state.clear()
        return
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await message.answer("Опиши ошибку обычным текстом или нажми «Отмена».")
        return
    if len(raw) > 4000:
        raw = raw[:4000]
    if not raw:
        await message.answer(texts.BUG_REPORT_EMPTY)
        return
    await state.update_data(bug_text=raw)
    await state.set_state(BugReportStates.photo)
    await message.answer(
        texts.BUG_REPORT_ASK_PHOTO,
        reply_markup=_bug_report_photo_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "bug_report_skip_photo", BugReportStates.photo)
async def bug_report_skip_photo(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    if not user:
        await state.clear()
        return
    data = await state.get_data()
    text = data.get("bug_text") or ""
    await state.clear()
    await send_bug_report_to_superadmins(
        user,
        text,
        photo_file_id=None,
        telegram_bot=callback.message.bot,
        max_adapter=get_max_adapter(),
    )
    await callback.message.answer(
        texts.BUG_REPORT_THANKS,
        reply_markup=get_back_to_menu_kb(),
    )


@router.message(BugReportStates.photo, F.photo)
async def bug_report_photo(message: Message, state: FSMContext, user=None):
    if not user:
        await state.clear()
        return
    data = await state.get_data()
    text = data.get("bug_text") or ""
    file_id = message.photo[-1].file_id
    await state.clear()
    await send_bug_report_to_superadmins(
        user,
        text,
        photo_file_id=file_id,
        telegram_bot=message.bot,
        max_adapter=get_max_adapter(),
    )
    await message.answer(
        texts.BUG_REPORT_THANKS,
        reply_markup=get_back_to_menu_kb(),
    )


@router.message(BugReportStates.photo, F.text)
async def bug_report_photo_step_text(message: Message, state: FSMContext):
    """Подсказка, если вместо фото прислали текст."""
    await message.answer(
        "Пришли фото или нажми «Без скриншота».",
        reply_markup=_bug_report_photo_kb(),
        parse_mode="HTML",
    )
