# Ревизия проекта moto_bot (текущая)
**Дата:** 17 марта 2026  
**Уровень:** Senior Developer  

---

## 1. Статус по ТЗ и предыдущим аудитам

### 1.1. Реализовано ✅

| Пункт | Комментарий |
|-------|-------------|
| Регистрация (Telegram + MAX) | Полный FSM, registration_service |
| SOS (Telegram + MAX) | MAX: sos:choose_type → sos:location → sos:comment → broadcast |
| Мотопара | Проверка подписки везде |
| Мероприятия | Подписка проверяется; создание с дифференцированной оплатой |
| Жалобы на мероприятия | Кнопка «Пожаловаться», уведомление админам, admin_evreport_accept/reject |
| Полезные контакты | OK |
| Профиль, подписка | OK |
| Логи активности | activity_logs, админка |
| Шаблоны уведомлений | global_texts, админка |
| event_motorcade_limit в админке | Редактируется (cb_admin_set_motorcade_limit) |
| Redis для max_registration_state | Инжектируется в main.py и run_max |
| max_reg_cancel при пустом fsm | Обработка вынесена в начало _handle_fsm_callback |
| Тексты преимуществ подписки | В profile.py: «Мотопробеги — 2 бесплатно в месяц», «Масштабные — платно» |

### 1.2. Частично / не реализовано ❌

| Пункт | Статус |
|-------|--------|
| CRUD городов | Только Екатеринбург, админы по городам |
| Платежи в MAX | Редирект на веб (YooKassa), webhook для активации подписки есть |

---

## 2. Обнаруженные проблемы

### 2.1. Ошибки и неточности

| # | Файл | Проблема | Критичность |
|---|------|----------|-------------|
| 1 | max_adapter.py:219, 244 | `except Exception: pass` — скрывает ошибки MAX API при answer_callback | Средняя |
| 2 | max_runner.py:1995 | `except Exception:` при get_profile_text — fallback есть, но нет логирования | Низкая |
| 3 | motopair.py:232 | `except Exception:` при answer_photo → edit_text — нет лога | Низкая |
| 4 | max_runner | uuid.UUID(profile_id_str), uuid.UUID(event_id) — при невалидной строке ValueError не ловится в handle_motopair_like, handle_event_detail, handle_event_register | Средняя |

### 2.2. Потенциальные улучшения

| Рекомендация | Приоритет |
|--------------|-----------|
| Добавить try/except для uuid.UUID в MAX callbacks (event_detail_, like_, event_register_) | Средний |
| Добавить logger.warning в пустые except (max_adapter, max_runner, motopair) | Средний |
| CRUD городов в админке | Низкий |
| Удалить неиспользуемый импорт get_location_button_row (если не используется) | Низкий |

---

## 3. Предлагаемые изменения (для согласования)

### Группа A: Логирование в except (низкий риск)

1. **max_adapter.py** — в двух блоках `except Exception: pass` добавить `logger.warning("MAX answer_callback/send_message failed: %s", e)`.
2. **max_runner.py:1995** — в `except Exception:` добавить `logger.warning("get_profile_text failed for MAX user %s: %s", user.id, e)`.
3. **motopair.py:232** — в `except Exception:` добавить `logger.warning("answer_photo failed, fallback to edit_text: %s", e)`.

### Группа B: Валидация uuid (средний риск)

4. **max_runner.py** — в `handle_motopair_like`, `handle_event_detail`, `handle_event_register` обернуть `uuid.UUID(...)` в try/except ValueError и при ошибке отправлять «Ошибка.» и возврат в меню.

### Группа C: Опционально (после согласования)

5. CRUD городов — отдельная задача.
6. Рефакторинг registration.py на использование registration_service для Telegram — отдельная задача.

---

## 4. Рекомендация

Выполнить **группы A и B** — это повысит отказоустойчивость и облегчит отладку. Группа C — по желанию, как отдельные задачи.
