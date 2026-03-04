"""All bot message text constants."""

# ——— Start / Welcome ———
WELCOME_NEW = """Привет! 👋
Это бот мото‑сообщества Екатеринбурга.

Здесь ты можешь:
• 🚨 Отправить SOS в экстренной ситуации
• 🏍 Найти мотопару
• 📇 Узнать полезные контакты (сервисы, магазины, эвакуаторы)
• 📅 Создавать и посещать мероприятия

Для начала выбери город и свою роль."""

WELCOME_RETURNING = "С возвращением! 👋\nГлавное меню:"

# ——— FSM / Registration ———
FSM_CANCEL_TEXT = "❌ Действие отменено. Возвращаю в главное меню."
FSM_CANCEL_COMMAND = "/cancel"

REG_ASK_NAME = (
    "Введи своё имя или никнейм.\n"
    "Мы покажем его другим вместе с твоим Telegram-логином."
)
REG_ASK_PHONE = (
    "Теперь отправь свой номер телефона кнопкой ниже.\n"
    "Вводить номер вручную нельзя — только через Telegram."
)
REG_ASK_AGE = "Введи свой возраст (число лет):"
REG_ASK_GENDER = "Выбери пол:"
REG_ASK_BIKE_BRAND = "Введи марку мотоцикла:"
REG_ASK_BIKE_MODEL = "Введи модель мотоцикла:"
REG_ASK_ENGINE_CC = "Введи кубатуру (см³):"
REG_ASK_DRIVING_SINCE = "Введи дату получения прав или начала вождения (ДД.ММ.ГГГГ):"
REG_ASK_STYLE = "Выбери стиль вождения:"
REG_ASK_PHOTO = "Отправь своё фото (необязательно):"
REG_ASK_ABOUT = "Напиши о себе (необязательно):"

REG_ASK_WEIGHT = "Введи вес (кг):"
REG_ASK_HEIGHT = "Введи рост (см):"
REG_ASK_PREFERRED_STYLE = "Желаемый стиль вождения:"

REG_ERROR_AGE = "Возраст должен быть от 18 до 80 лет."
REG_ERROR_NOT_NUMBER = "Введи число."
REG_ERROR_DATE_FORMAT = "Формат: ДД.ММ.ГГГГ (например, 15.06.2020). Попробуй ещё раз:"
REG_ERROR_ENGINE_CC = "Укажи разумную кубатуру (50-3000)."
REG_ERROR_WEIGHT = "Укажи разумный вес (30-200)."
REG_ERROR_HEIGHT = "Укажи рост 120-220 см."
REG_ERROR_ABOUT_TOO_LONG = "Максимум {max_len} символов."
REG_ERROR_NOT_TEXT = "Напиши о себе текстом или нажми «Пропустить»."
REG_ERROR_SAVE = "Ошибка при сохранении. Попробуй /start и пройди регистрацию заново."
REG_ERROR_USER_NOT_FOUND = "Ошибка: пользователь не найден. Нажми /start"

REG_DONE = "✅ Анкета заполнена! 🏍"

# ——— Profile preview ———
PROFILE_PREVIEW_HEADER = "👀 Вот как тебя будут видеть другие:\n\n"
PROFILE_PREVIEW_CONFIRM = "Всё верно? Сохранить анкету?"
PROFILE_BTN_SAVE = "✅ Сохранить"
PROFILE_BTN_EDIT = "✏️ Редактировать заново"

# ——— SOS ———
SOS_CHOOSE_TYPE = "🚨 Выбери тип SOS:"
SOS_SEND_LOCATION = "Отправь свою геолокацию:"
SOS_ASK_COMMENT = "Введи комментарий (необязательно):"
SOS_SENT = (
    "✅ SOS отправлен!\n"
    "Следующий доступен через {cooldown} мин."
)
SOS_COOLDOWN = "⏳ Подожди {mins} мин. перед следующим SOS."
SOS_NO_CITY = "Ошибка: город не выбран. Нажми /start"
SOS_CHECK_READY = "🔄 Проверить готовность"
SOS_READY_NOW = "✅ SOS уже доступен!"
SOS_READY_WAIT = "⏳ Следующий SOS доступен через {mins} мин. {secs} сек."
SOS_ALL_CLEAR_BTN = "✅ Помощь получена — отбой"
SOS_ALL_CLEAR_BROADCAST = "✅ Отбой! {name} сообщает: помощь получена."
SOS_BROADCAST_TYPE = "🚨 SOS: {type_label}\n\n{profile}\n\n"
SOS_BROADCAST_COMMENT = "Комментарий: {comment}\n\n"
SOS_BROADCAST_MAP = "📍 https://yandex.ru/maps/?ll={lon},{lat}&z=16"
SOS_BTN_CALL = "📞 Позвонить"
SOS_BTN_TELEGRAM = "✈️ Написать в Telegram"

# ——— Мотопара ———
MOTOPAIR_NO_PROFILES = (
    "Новых анкет пока нет 🏍\n"
    "Загляни позже или подними свою анкету, чтобы тебя заметили!"
)
MOTOPAIR_RAISE_BTN = "⬆️ Поднять мою анкету"
MOTOPAIR_REPORT_BTN = "🚩 Пожаловаться"
MOTOPAIR_REPORT_SENT = "Жалоба отправлена администратору."
MOTOPAIR_REPORT_ADMIN_TEXT = (
    "🚩 <b>Жалоба на анкету</b>\n\n"
    "От: {reporter}\n"
    "На: {reported}\n"
    "Профиль: {profile_text}"
)
MOTOPAIR_REPORT_BTN_ACCEPT = "✅ Принять (скрыть анкету)"
MOTOPAIR_REPORT_BTN_BLOCK = "🔒 Заблокировать пользователя"
MOTOPAIR_REPORT_BTN_REJECT = "❌ Отклонить жалобу"
MOTOPAIR_REPORT_ACCEPTED = "Жалоба принята, анкета скрыта."
MOTOPAIR_REPORT_REJECTED = "Жалоба отклонена."

# ——— Блокировка администратором города ———
ADMIN_BLOCK_NOTIFY_SUPERADMIN = (
    "🔒 <b>Блокировка пользователя</b>\n\n"
    "Администратор: {admin}\n"
    "Заблокировал: {user}\n"
    "Причина: {reason}"
)
ADMIN_BLOCK_USER_NOTIFICATION = (
    "🔒 Ваш аккаунт заблокирован.\n\n"
    "Причина: {reason}\n\n"
    "Для обжалования обратитесь к администрации сообщества."
)
ADMIN_BLOCK_DONE = "✅ Пользователь заблокирован. Суперадмин уведомлён."

# ——— Мероприятия ———
EVENT_SHARE_TEXT = (
    "🏍 {type}: {title}\n"
    "📅 {date}\n"
    "📍 {point_start}\n"
    "{description}"
)
EVENT_SHARE_BTN = "📤 Поделиться"

# ——— Профиль / смена телефона ———
PHONE_CHANGE_REQUEST_SENT = (
    "📱 Заявка на смену телефона отправлена администратору.\n"
    "Ожидай подтверждения."
)
PHONE_CHANGE_ADMIN_TEXT = (
    "📱 <b>Запрос на смену телефона</b>\n\n"
    "Пользователь: {user}\n"
    "Текущий номер: {old_phone}\n\n"
    "Введи новый номер для подтверждения:"
)
PHONE_CHANGE_CONFIRMED = "✅ Номер телефона изменён на {new_phone}."
PHONE_CHANGE_BTN = "📱 Сменить телефон"
PHONE_CHANGE_BTN_CONFIRM = "✅ Подтвердить и ввести новый номер"
PHONE_CHANGE_BTN_REJECT = "❌ Отклонить"
PHONE_CHANGE_REJECTED = "Запрос на смену телефона отклонён."
PHONE_CHANGE_REJECTED_USER = "❌ Запрос на смену телефона отклонён администратором."

# ——— Подписка ———
SUB_EXPIRY_REMINDER = (
    "⚠️ Твоя подписка истекает через {days} {days_word}!\n"
    "Продли сейчас, чтобы не потерять доступ к поиску мотопары."
)
SUB_RENEW_BTN = "🔄 Продлить подписку"

# ——— Общие ———
BTN_BACK = "« Назад"
BTN_SKIP = "Пропустить ➡️"
BTN_CANCEL = "✖ Отмена"
BTN_MAIN_MENU = "« Назад в меню"

ERROR_GENERIC = "Произошла ошибка. Попробуй позже."
USER_BLOCKED = "Вы заблокированы. Обратитесь в поддержку."
