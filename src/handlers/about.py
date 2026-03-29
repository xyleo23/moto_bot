"""About us, support, donations — Stage 9."""

from loguru import logger
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.config import get_settings
from src.keyboards.menu import get_back_to_menu_kb
from src.services.admin_service import get_global_text
from src.services.payment import create_payment
from src.usecases.payment_metadata import donate_metadata
from src.utils.text_format import split_plain_text_chunks

router = Router()

DEFAULT_ABOUT = """ℹ️ О нас

Бот мото-сообщества Екатеринбурга.
Объединяем пилотов и двоек, помогаем в экстренных ситуациях."""

DONATE_AMOUNTS = [
    (10000, "100 ₽"),
    (30000, "300 ₽"),
    (50000, "500 ₽"),
    (100000, "1000 ₽"),
]


class FeedbackStates(StatesGroup):
    text = State()


class DonateCustomStates(StatesGroup):
    amount = State()


@router.callback_query(F.data == "menu_about")
async def cb_about(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    s = get_settings()
    text_db = await get_global_text("about_us")
    text = (text_db or DEFAULT_ABOUT).strip()
    text += f"\n\n📧 Поддержка: {s.support_email}"
    text += f"\n👤 Telegram: @{s.support_username}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Предложения и пожелания", callback_data="about_feedback"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✉️ Написать в поддержку", url=f"https://t.me/{s.support_username}"
                )
            ],
            [InlineKeyboardButton(text="❤️ Поддержать проект", callback_data="about_donate")],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ]
    )
    chunks = split_plain_text_chunks(text, max_len=3800)
    await callback.message.edit_text(chunks[0], reply_markup=kb)
    for extra in chunks[1:]:
        await callback.message.answer(extra)
    await callback.answer()


# ——— Feedback ———


@router.callback_query(F.data == "about_feedback")
async def cb_about_feedback_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(FeedbackStates.text)
    await callback.message.edit_text(
        "Напиши своё предложение или пожелание (до 1000 символов). Или нажми «Отмена».",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Отмена", callback_data="menu_about")],
            ]
        ),
    )
    await callback.answer()


@router.message(FeedbackStates.text, F.text)
async def about_feedback_text(message: Message, state: FSMContext, user=None):
    text = message.text.strip()[:1000]
    if not text:
        await message.answer("Введи текст.")
        return

    await state.clear()

    name = user.platform_first_name or "Пользователь"
    username = f"@{user.platform_username}" if user.platform_username else ""
    msg = f"📩 <b>Предложение/пожелание</b>\n\nОт: {name} {username} (id: {user.platform_user_id})\n\n{text}"

    from src.services.admin_multichannel_notify import notify_superadmins_plain
    from src.services.broadcast import get_max_adapter

    await notify_superadmins_plain(
        msg,
        telegram_bot=message.bot,
        max_adapter=get_max_adapter(),
    )

    await message.answer(
        "✅ Спасибо! Твоё сообщение отправлено администрации.",
        reply_markup=get_back_to_menu_kb(),
    )


# ——— Donate ———


@router.callback_query(F.data == "about_donate")
async def cb_about_donate(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"donate_{kop}")]
        for kop, label in DONATE_AMOUNTS
    ]
    rows.append([InlineKeyboardButton(text="Своя сумма", callback_data="donate_custom")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu_about")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text("Поддержать проект — выбери сумму:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "donate_custom")
async def cb_donate_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DonateCustomStates.amount)
    await callback.message.edit_text(
        "Введи сумму в рублях (например 250, минимум 10):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="about_donate")],
            ]
        ),
    )
    await callback.answer()


@router.message(DonateCustomStates.amount, F.text)
async def about_donate_custom_amount(message: Message, state: FSMContext, user=None):
    if not user:
        await state.clear()
        return
    try:
        rub = int(message.text.strip())
        if rub < 10 or rub > 100000:
            await message.answer("Сумма от 10 до 100 000 ₽.")
            return
        amount_kop = rub * 100
    except ValueError:
        await message.answer("Введи число.")
        return

    await state.clear()

    s = get_settings()
    payment = await create_payment(
        amount_kopecks=amount_kop,
        description="Донат — поддержка бота мото-сообщества",
        metadata=donate_metadata(user, platform="telegram"),
        return_url=s.telegram_return_url or "https://t.me",
    )

    if not payment or not payment.get("confirmation_url"):
        await message.answer(
            "Не удалось создать платёж. Попробуй позже.",
            reply_markup=get_back_to_menu_kb(),
        )
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_about")],
        ]
    )
    await message.answer("Спасибо за поддержку! Перейди по ссылке для оплаты:", reply_markup=kb)


@router.callback_query(F.data.startswith("donate_"))
async def cb_donate_amount(callback: CallbackQuery, state: FSMContext, user=None):
    if not user:
        await callback.answer("Ошибка.")
        return

    amount_str = callback.data.replace("donate_", "")
    if amount_str == "custom":
        await cb_donate_custom(callback, state)
        return

    try:
        amount_kop = int(amount_str)
        if amount_kop < 1000:
            raise ValueError("min 10 руб")
    except (ValueError, TypeError):
        await callback.answer("Ошибка суммы.")
        return

    s = get_settings()
    payment = await create_payment(
        amount_kopecks=amount_kop,
        description="Донат — поддержка бота мото-сообщества",
        metadata=donate_metadata(user, platform="telegram"),
        return_url=s.telegram_return_url or "https://t.me",
    )

    if not payment or not payment.get("confirmation_url"):
        await callback.message.edit_text(
            "Не удалось создать платёж. Попробуй позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад", callback_data="menu_about")],
                ]
            ),
        )
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_about")],
        ]
    )
    await callback.message.edit_text(
        "Спасибо за поддержку! Перейди по ссылке для оплаты:",
        reply_markup=kb,
    )
    await callback.answer()
