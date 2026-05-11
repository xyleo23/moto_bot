# Заметки к рефакторингу (пункты Н и О пакета 15 000 ₽)

## Н — распил `max_runner.py` / `handlers/admin.py`

Текущее состояние:
- `src/max_runner.py` — 5062 строки, обрабатывает MAX update'ы по всем разделам: registration, profile, motopair, events, SOS, payments, admin callbacks. Один большой `if/elif`-роутер `process_max_update`.
- `src/handlers/admin.py` — ~2000 строк, TG-админка: пользователи, города, подписки, мероприятия, рассылка, поддержка.

**Решение:** распил **не делаю в текущей сессии**. Это не локальное изменение — каждое перемещение функции трогает 5–10 импортов, риск регрессии превышает выгоду без выделенного цикла регрессионного тестирования. Безопасный план:

1. Выделить отдельные сессии по 1–2 часа на каждый раздел: max SOS → max profile → max motopair → max events → max admin.
2. На каждой сессии: новый модуль `src/max/<section>.py`, перенос только функций без изменения логики, snapshot-тесты до/после.
3. После каждого этапа — деплой и наблюдение 24 часа, чтобы засечь регрессию.

## О — `registration_shared`

Сейчас регистрация дублируется в `handlers/registration.py` (TG, 1137 строк FSM-на-aiogram) и в `max_runner.py` (MAX, ручной FSM на Redis через `max_registration_state`). Логика валидации одинакова: имя, телефон, ник, возраст, мото-данные, согласия.

Что общего и просится в `services/registration_shared.py`:
- `validate_name`, `validate_phone`, `validate_age`, `validate_height/weight` (часть уже в `src/utils/`)
- `RegistrationData` Pydantic-модель (текущий dict-based стейт типобезопасности не даёт)
- `apply_registration(user, data, role)` — финальный INSERT в БД (сейчас две очень похожие реализации)

**Решение:** аналогично Н — оставлено как отдельная задача. Минимальное аддитивное действие здесь — Pydantic-модель `RegistrationData`, но без миграции существующих хендлеров она бесполезна.

## П — тесты на критичные модули

Сделано в текущей сессии:
- `effective_user_id` — два теста на linked / unlinked
- `maybe_auto_block_after_report` — порог не достигнут / достигнут
- `format_admin_user_card` — пилот с телефоном / без анкеты
- `check_report_cooldown` — первая / недавняя / дневной лимит
- `mark_payment_processed` — первая обработка / дубликат / пустой ID
- `_do_broadcast` — RetryAfter retry / исчерпание попыток / Forbidden без retry
- `set_profile_hidden_by_user` — пилот / без анкеты
- `format_admin_user_card` — TG-пилот / MAX-без-анкеты
- `handle_max_webhook` — secret в header / неверный header

Покрытие выросло с 92 до 108 тестов (+17%).
