# Промпт: MAX — полная регистрация FSM (пилот + пассажир)

**Задача:** Реализовать полный FSM регистрации для платформы MAX, аналогичный Telegram-версии в `src/handlers/registration.py`. Сейчас в MAX после выбора роли пользователь сразу видит главное меню без анкеты — нужно добавить пошаговую регистрацию с сохранением в БД.

---

## Контекст проекта

- **Репозиторий:** moto_bot (Telegram + MAX бот мото-сообщества)
- **MAX:** мессенджер с API platform-api.max.ru. Обработка в `src/max_runner.py`, адаптер `src/platforms/max_adapter.py`
- **События:** `parse_updates` в `src/platforms/max_parser.py` возвращает:
  - `IncomingMessage` (text, username, first_name)
  - `IncomingCallback` (callback_data, chat_id, user_id, message_id)
  - `IncomingContact` (phone_number)
  - `IncomingLocation` (latitude, longitude)
- **IncomingPhoto** объявлен в `src/platforms/base.py`, но **не парсится** в max_parser — если MAX присылает фото в `message.photo` или `message.attachments`, нужно добавить парсинг; иначе шаг «фото» сделать только «Пропустить»

---

## Референс: Telegram-регистрация

Полностью изучить `src/handlers/registration.py` (~900 строк).

**Пилот (11 шагов):**
1. Имя (текст)
2. Телефон (кнопка «Отправить мой номер» / `IncomingContact`)
3. Возраст (18–80)
4. Пол (callback: `gender_male`, `gender_female`, `gender_other`)
5. Марка мотоцикла (текст)
6. Модель (текст)
7. Кубатура (50–3000)
8. Стаж (год или месяц.год, например 2020 или 06.2020)
9. Стиль вождения (callback: `calm`, `aggressive`, `mixed`)
10. Фото (опционально; кнопка «Пропустить»)
11. О себе (опционально; кнопка «Пропустить»)
12. Превью → «Сохранить» / «Редактировать»

**Пассажир (9 шагов):**
1. Имя
2. Телефон
3. Возраст
4. Пол (callback: `pax_gender_male`, `pax_gender_female`, `pax_gender_other`)
5. Вес (30–200)
6. Рост (120–220)
7. Желаемый стиль (callback: `pax_style_calm`, `pax_style_dynamic`, `pax_style_mixed`)
8. Фото (опционально)
9. О себе (опционально)
10. Превью → «Сохранить» / «Редактировать»

Тексты — из `src/texts.py`:
- `REG_ASK_NAME`, `REG_ASK_PHONE`, `REG_ASK_AGE`, `REG_ASK_GENDER`, `REG_ASK_BIKE_BRAND`, `REG_ASK_BIKE_MODEL`, `REG_ASK_ENGINE_CC`, `REG_ASK_DRIVING_SINCE`, `REG_ASK_STYLE`, `REG_ASK_PHOTO`, `REG_ASK_ABOUT`
- `REG_ASK_WEIGHT`, `REG_ASK_HEIGHT`, `REG_ASK_PREFERRED_STYLE`
- `REG_ERROR_*`, `REG_ERROR_SAVE`, `REG_ERROR_USER_NOT_FOUND`
- `BTN_SKIP`, `PROFILE_PREVIEW_HEADER`, `PROFILE_PREVIEW_CONFIRM`, `PROFILE_BTN_SAVE`, `PROFILE_BTN_EDIT`, `REG_DONE`, `FSM_CANCEL_TEXT`

Прогресс-бар: `src/utils/progress.py` — `progress_prefix(step, total)`.

---

## Хранение состояния FSM

Telegram использует aiogram FSM + Redis (`RedisStorage`). Для MAX нужен отдельный state store.

**Вариант 1 (предпочтительный):** Redis
- Ключ: `max_reg:{platform_user_id}` (user_id — число)
- Значение: JSON `{ "state": "pilot:phone", "data": { "name": "...", ... } }`
- TTL: 3600 секунд (1 час)
- Состояния: `pilot:name`, `pilot:phone`, `pilot:age`, … `pilot:preview`; `passenger:name`, … `passenger:preview`
- Redis уже есть: `get_settings().redis_url`, в `main.py` подключается Redis для FSM

**Вариант 2:** In-memory dict (fallback при недоступном Redis, с предупреждением в лог)

Создать модуль `src/services/max_registration_state.py`:
- `async def get_state(platform_user_id: int) -> dict | None`
- `async def set_state(platform_user_id: int, state: str, data: dict) -> None`
- `async def clear_state(platform_user_id: int) -> None`

---

## Интеграция в max_runner.py

### 1. Обработка callbacks

В `handle_callback` после выбора роли (`role_pilot`, `role_passenger`):
- Вместо показа главного меню — вызвать старт регистрации
- Сохранить состояние `pilot:name` или `passenger:name` с `data={}`
- Отправить первый вопрос: `progress_prefix(1, 11) + texts.REG_ASK_NAME` (или 9 для пассажира)
- Использовать `get_main_menu_rows()` только после завершения регистрации

### 2. Обработка сообщений

В `handle_message`:
- Если пользователь в состоянии FSM (`get_state(ev.user_id)` не None):
  - Маршрутизировать по `state` на соответствующий step handler
  - Передавать `ev.text` в логику валидации (аналогично registration.py)
  - При ошибке валидации — отправить текст ошибки и оставить состояние
  - При успехе — обновить `data`, перейти к следующему шагу, отправить следующий вопрос
- Иначе — текущее поведение (echo / «Используй меню или /start»)

### 3. Обработка контакта

В `handle_contact`:
- Проверить `get_state(ev.user_id)`
- Если `state == "pilot:phone"` или `state == "passenger:phone"` — взять `ev.phone_number`, сохранить, перейти к age, отправить следующий вопрос
- Иначе — игнорировать или отправить «Сейчас ожидается другой ввод»

### 4. Отмена

- Текст `/cancel` или «отмена» (регистронезависимо) — `clear_state`, отправить `texts.FSM_CANCEL_TEXT` и главное меню
- Опционально: кнопка «Отменить» на каждом шаге с payload `max_reg_cancel`

### 5. Callbacks внутри FSM

Префиксы, чтобы не пересекаться с меню:
- Пилот: `max_reg_gender_`, `max_reg_style_`, `max_reg_skip_photo`, `max_reg_skip_about`, `max_reg_preview_save`, `max_reg_preview_edit`
- Пассажир: `max_reg_pax_gender_`, `max_reg_pax_style_`, `max_reg_pax_skip_photo`, `max_reg_pax_skip_about`, `max_reg_pax_preview_save`, `max_reg_pax_preview_edit`

Обрабатывать в `handle_callback` **до** основных меню, если `get_state(ev.user_id)` не None.

---

## Завершение регистрации

В `_finish_pilot_registration` и `_finish_passenger_registration` в `registration.py` сейчас жёстко:

```python
User.platform == Platform.TELEGRAM
```

Для MAX нужно сохранять профиль для `Platform.MAX`. Рекомендации:

1. **Вынести логику в сервис** `src/services/registration_service.py`:
   - `async def finish_pilot_registration(platform: Platform, platform_user_id: int, data: dict) -> str | None`
   - `async def finish_passenger_registration(platform: Platform, platform_user_id: int, data: dict) -> str | None`
   - Возвращают `None` при успехе или строку с текстом ошибки
   - Внутри: `User.platform == platform`, `User.platform_user_id == platform_user_id`
2. Или вызывать те же функции с параметром `platform="max"` и `platform_user_id=ev.user_id`

Создавать/обновлять `ProfilePilot` / `ProfilePassenger` по `user_id` из `User`, найденного по `platform=MAX` и `platform_user_id`.

---

## Клавиатуры

Использовать `src/keyboards/shared.py`:
- `get_contact_button_row()` — кнопка «Отправить мой номер»
- `Button("Муж", payload="max_reg_gender_male")` и т.п.
- Для превью: `Button(texts.PROFILE_BTN_SAVE, payload="max_reg_preview_save")`, `Button(texts.PROFILE_BTN_EDIT, payload="max_reg_preview_edit")`
- Кнопка «Пропустить»: `Button(texts.BTN_SKIP, payload="max_reg_skip_photo")`

В `shared.py` можно добавить функции для registration-клавиатур, если нужна общая структура.

---

## Фото

- Если MAX API присылает фото (проверить структуру `message` в сыром update): добавить парсинг `IncomingPhoto` в `max_parser.py` и обработку в `process_max_update` → `handle_photo`.
- Если фото нет или формат неизвестен: шаг «фото» показывать только с кнопкой «Пропустить», при нажатии переходить к «о себе»; `photo_file_id` оставлять `None`.

---

## Порядок реализации

1. Модуль `src/services/max_registration_state.py` (Redis + fallback)
2. Модуль `src/services/registration_service.py` с `finish_pilot_registration` и `finish_passenger_registration` (platform-agnostic)
3. В `max_runner.py`:
   - Импорт state и registration_service
   - Диспетчеризация в `handle_callback`: роль → старт регистрации; FSM callbacks
   - Диспетчеризация в `handle_message`: FSM steps по `state`
   - Диспетчеризация в `handle_contact`: phone step
   - Обработка `/cancel`
4. Обновить `handle_start`: при `has_profile(user) == False` и `user.role in (PILOT, PASSENGER)` — проверять `get_state(user.platform_user_id)`. Если состояние есть — продолжить FSM; если нет — стартовать регистрацию (показать первый вопрос).
5. Опционально: парсинг `IncomingPhoto` и `handle_photo` для шага фото

---

## Валидация (как в registration.py)

- Возраст: 18–80
- Телефон: минимум 5 символов, нормализовать с `+`
- Кубатура: 50–3000
- Вес: 30–200
- Рост: 120–220
- Стаж: `_parse_russian_date` или парсинг `YYYY` / `MM.YYYY` (см. registration.py)
- About: `get_settings().about_text_max_length`

---

## Тесты

Добавить в `tests/`:
- `test_max_registration_state.py`: get/set/clear state (с mock Redis или реальным)
- `test_registration_service.py`: `finish_pilot_registration`, `finish_passenger_registration` для `Platform.MAX` (с тестовой БД)

---

## Важно

- Не менять поведение Telegram-регистрации
- `User` для MAX ищется по `platform=Platform.MAX` и `platform_user_id`
- После успешного сохранения профиля — `clear_state`, отправить `texts.REG_DONE` и главное меню
- Логировать `logger.info("MAX reg: user_id=%s state=%s", user_id, state)` при смене шагов
- Обрабатывать исключения: при ошибке БД отправлять `texts.REG_ERROR_SAVE` и не сбрасывать state (пользователь может повторить)
