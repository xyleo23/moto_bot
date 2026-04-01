"""MotoPair keyboards."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Не редактировать сообщение с контактом/лайком — открыть меню мотопары новым сообщением (см. cb_motopair_menu_preserve).
CALLBACK_MOTOPAIR_MENU_PRESERVE = "motopair_menu_preserve"


def get_filter_kb(role: str, current: dict) -> InlineKeyboardMarkup:
    """Filter setup keyboard. current = {gender, age_max, weight_max, height_max}."""
    prefix = f"motopair_fset_{role}"
    rows = []

    # Gender
    g = current.get("gender") or "any"
    rows.append(
        [
            InlineKeyboardButton(
                text="Пол: М" + (" ✓" if g == "male" else ""), callback_data=f"{prefix}_gender_male"
            ),
            InlineKeyboardButton(
                text="Ж" + (" ✓" if g == "female" else ""), callback_data=f"{prefix}_gender_female"
            ),
            InlineKeyboardButton(
                text="Любой" + (" ✓" if g == "any" else ""), callback_data=f"{prefix}_gender_any"
            ),
        ]
    )

    # Age max
    a = current.get("age_max") or 0
    age_btns = []
    for v in [25, 30, 35, 40, 50]:
        age_btns.append(
            InlineKeyboardButton(
                text=str(v) + (" ✓" if a == v else ""),
                callback_data=f"{prefix}_age_{v}",
            )
        )
    rows.append(age_btns)
    rows.append([InlineKeyboardButton(text="Возраст: сбросить", callback_data=f"{prefix}_age_0")])

    if role == "passenger":
        w = current.get("weight_max") or 0
        weight_btns = []
        for v in [60, 70, 80, 90]:
            weight_btns.append(
                InlineKeyboardButton(
                    text=str(v) + (" ✓" if w == v else ""),
                    callback_data=f"{prefix}_weight_{v}",
                )
            )
        rows.append(weight_btns)
        rows.append(
            [InlineKeyboardButton(text="Вес: сбросить", callback_data=f"{prefix}_weight_0")]
        )

        h = current.get("height_max") or 0
        height_btns = []
        for v in [160, 170, 180, 190]:
            height_btns.append(
                InlineKeyboardButton(
                    text=str(v) + (" ✓" if h == v else ""),
                    callback_data=f"{prefix}_height_{v}",
                )
            )
        rows.append(height_btns)
        rows.append(
            [InlineKeyboardButton(text="Рост: сбросить", callback_data=f"{prefix}_height_0")]
        )

    rows.append(
        [
            InlineKeyboardButton(text="Применить", callback_data=f"{prefix}_apply"),
            InlineKeyboardButton(text="Сбросить всё", callback_data=f"{prefix}_reset"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_profile_view_kb(
    profile_id: str, role: str, offset: int, has_more: bool
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="👍 Лайк", callback_data=f"like_{profile_id}_{role}"),
            InlineKeyboardButton(text="👎 Дизлайк", callback_data=f"dislike_{profile_id}_{role}"),
        ],
    ]
    if has_more:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Следующая ➡", callback_data=f"motopair_next_{role}_{offset + 1}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="« В меню", callback_data="menu_motopair")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_like_notification_kb(from_user_internal_id: str) -> InlineKeyboardMarkup:
    """Keyboard for the person who received a like — reply like or skip."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💚 Взаимно!", callback_data=f"reply_like_{from_user_internal_id}"
                ),
                InlineKeyboardButton(
                    text="👎 Пропустить", callback_data=f"reply_skip_{from_user_internal_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="« Мотопара",
                    callback_data=CALLBACK_MOTOPAIR_MENU_PRESERVE,
                ),
            ],
        ]
    )


def get_match_kb(telegram_username: str | None, telegram_id: int | None) -> InlineKeyboardMarkup:
    """После взаимного лайка / пары: ссылка на TG; без username — пробуем tg://user (может не сработать из‑за приватности)."""
    rows = []
    if telegram_username:
        rows.append(
            [InlineKeyboardButton(text="💬 Написать в Telegram", url=f"https://t.me/{telegram_username}")]
        )
    elif telegram_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💬 Написать в Telegram",
                    url=f"tg://user?id={telegram_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="« Мотопара",
                callback_data=CALLBACK_MOTOPAIR_MENU_PRESERVE,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
