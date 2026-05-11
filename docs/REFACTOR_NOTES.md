# Заметки к рефакторингу (пункты Н и О пакета 15 000 ₽)

## Н — распил `max_runner.py` / `handlers/admin.py` (частично сделано)

В пакете обещано: «выделю основу для распиливания и вынесу 2-3 наиболее автономных куска… полный распил — отдельная работа на следующий заход».

**Сделано:**
1. `handlers/admin_broadcast.py` — вся FSM рассылки (выбор сегмента → ввод текста → подтверждение → отправка) вынесена в отдельный модуль с собственным router'ом. `handlers/admin.py` стал ~130 строк короче.
2. `services/registration_shared.py` — парсеры дат регистрации, ранее продублированные в `handlers/registration.py` и `max_runner.py`, теперь один источник правды (см. пункт О ниже).

**Отложено (отдельные сессии):**
- Полный распил `max_runner.py` (5062 строки). План по разделам:
  1. `src/max/registration.py` — MAX-флоу регистрации (≈800 строк, FSM на Redis)
  2. `src/max/sos.py` — SOS-обработчики (≈300 строк, уже есть `_send_max_sos_alert`)
  3. `src/max/motopair.py` — фид мотопары, лайки, жалобы (≈600 строк)
  4. `src/max/events.py` — мероприятия (≈900 строк)
  5. `src/max/profile.py` — профиль и редактирование (≈400 строк)
  6. `src/max/admin_callbacks.py` — админ-меню MAX
  7. В `max_runner.py` остаётся `process_max_update` как тонкий диспетчер.
- `handlers/admin.py` (1860 строк после выноса broadcast). Кандидаты: cities-CRUD, subscriptions, support-handlers.

**Безопасный принцип:** один модуль = один деплой = 24 часа наблюдения. Иначе риск регрессии превышает выгоду.

## О — `registration_shared` (сделано)

В пакете обещано: «Будет вынесено в общий сервис `registration_shared`, оба адаптера будут пользоваться одной реализацией».

**Сделано:**
- `services/registration_shared.py`: `parse_russian_date`, `parse_registration_date`, `RUSSIAN_MONTHS`.
- Старые дубли в `handlers/registration.py` (lines 513-582) и `max_runner.py` (lines 103-186) удалены, оба импортируют из общего модуля.
- Тесты на 4 формата ввода (год / месяц.год / полная дата / DD месяц YYYY).
- DB-commit логика уже была общей в `registration_service.py` (`finish_pilot_registration`, `finish_passenger_registration` использовались обеими платформами ещё до пакета).

**Что осталось общего ещё дублируется** (не критично, для будущих заходов):
- Тексты вопросов в FSM (`REG_ASK_*`) — частично используются обеими, частично свои.
- Шаги FSM (state-машина) — у TG aiogram-FSM, у MAX свой ручной on-Redis. Объединить их — это большая архитектурная задача.

## П — тесты на критичные модули (сделано)

Покрытие выросло с 92 → 112 тестов (+22%). Добавленные тесты:
- `parse_registration_date` × 3, `parse_russian_date`
- `effective_user_id` linked/unlinked
- `maybe_auto_block_after_report` ниже / на пороге
- `format_admin_user_card` TG-pilot / MAX-без-анкеты
- `check_report_cooldown` × 3
- `mark_payment_processed` × 3
- `_do_broadcast` × 3 (RetryAfter, исчерпание попыток, Forbidden)
- `set_profile_hidden_by_user` × 2
- `handle_max_webhook` header-секрет × 2
