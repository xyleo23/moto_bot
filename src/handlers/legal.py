"""Юридические документы: политика конфиденциальности, обработка ПД, удаление данных."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from src import texts
from src.config import get_settings
from src.keyboards.menu import get_main_menu_kb, get_back_to_menu_kb
from src.services.user import get_or_create_user, delete_user_data

router = Router()

MSG_LIMIT = 4096


def _chunk_text(text: str, limit: int = MSG_LIMIT) -> list[str]:
    """Разбить текст на части по limit символов."""
    if len(text) <= limit:
        return [text]
    chunks = []
    for i in range(0, len(text), limit):
        chunks.append(text[i : i + limit])
    return chunks


def get_documents_menu_kb() -> InlineKeyboardMarkup:
    """Клавиатура меню документов."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", callback_data="doc_privacy")],
        [InlineKeyboardButton(text="✅ Согласие на обработку ПД", callback_data="doc_consent")],
        [InlineKeyboardButton(text="🗑 Удалить мои данные", callback_data="doc_delete")],
        [InlineKeyboardButton(text="📞 Поддержка", callback_data="doc_support")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])


# ---- Команды ----

@router.message(Command("privacy"))
async def cmd_privacy(message: Message, user=None):
    """Политика конфиденциальности."""
    for chunk in _chunk_text(texts.PRIVACY_TEXT):
        await message.answer(chunk)


@router.message(Command("consent"))
async def cmd_consent(message: Message, user=None):
    """Согласие на обработку ПД."""
    for chunk in _chunk_text(texts.CONSENT_TEXT):
        await message.answer(chunk)


@router.message(Command("delete_data"))
async def cmd_delete_data(message: Message, user=None):
    """Запрос на удаление персональных данных."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete_data")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="doc_cancel_delete")],
    ])
    await message.answer(texts.LEGAL_DELETE_CONFIRM, reply_markup=kb)


@router.message(Command("support"))
async def cmd_support(message: Message):
    """Контакты поддержки."""
    try:
        s = get_settings()
        text = texts.LEGAL_SUPPORT_TEXT.format(
            email=s.support_email,
            username=s.support_username or "support",
        )
    except KeyError:
        text = texts.LEGAL_SUPPORT_TEXT
    await message.answer(text)


# ---- Callbacks: меню документов ----

@router.callback_query(F.data == "menu_documents")
async def cb_menu_documents(callback: CallbackQuery):
    """Открыть меню документов."""
    await callback.message.edit_text(
        texts.LEGAL_DOCS_INTRO,
        reply_markup=get_documents_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "doc_privacy")
async def cb_doc_privacy(callback: CallbackQuery):
    """Показать политику конфиденциальности."""
    await callback.answer()
    for chunk in _chunk_text(texts.PRIVACY_TEXT):
        await callback.message.answer(chunk)
    await callback.message.answer("Документы:", reply_markup=get_documents_menu_kb())


@router.callback_query(F.data == "doc_consent")
async def cb_doc_consent(callback: CallbackQuery):
    """Показать согласие на обработку ПД."""
    await callback.answer()
    for chunk in _chunk_text(texts.CONSENT_TEXT):
        await callback.message.answer(chunk)
    await callback.message.answer("Документы:", reply_markup=get_documents_menu_kb())


@router.callback_query(F.data == "doc_delete")
async def cb_doc_delete(callback: CallbackQuery):
    """Подтверждение удаления данных."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete_data")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_documents")],
    ])
    await callback.message.edit_text(texts.LEGAL_DELETE_CONFIRM, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "doc_cancel_delete")
async def cb_doc_cancel_delete(callback: CallbackQuery):
    """Отмена удаления."""
    await callback.message.edit_text(texts.LEGAL_DELETE_CANCELLED, reply_markup=get_documents_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "doc_support")
async def cb_doc_support(callback: CallbackQuery):
    """Контакты поддержки."""
    try:
        s = get_settings()
        text = texts.LEGAL_SUPPORT_TEXT.format(
            email=s.support_email,
            username=s.support_username or "support",
        )
    except KeyError:
        text = texts.LEGAL_SUPPORT_TEXT
    await callback.message.edit_text(text)
    await callback.message.answer("Документы:", reply_markup=get_documents_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "confirm_delete_data")
async def cb_confirm_delete_data(callback: CallbackQuery, user=None):
    """Выполнить удаление персональных данных."""
    if not user:
        user = await get_or_create_user(
            platform="telegram",
            platform_user_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
    if user:
        await delete_user_data(user)
    await callback.message.edit_text(texts.LEGAL_DELETE_DONE)
    await callback.message.answer(
        "Для нового доступа нажмите /start",
        reply_markup=get_main_menu_kb(platform_user_id=callback.from_user.id),
    )
    await callback.answer()
