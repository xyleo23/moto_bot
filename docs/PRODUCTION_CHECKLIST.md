# Чеклист перед продакшеном (moto_bot)

Сверка с ТЗ: `ТЗ_СТРУКТУРИРОВАННОЕ.md`, ревизии: `REVISION_2026_03_CURRENT.md`, `АНАЛИЗ_НЕРЕАЛИЗОВАННОЕ_ТЗ.md`.

---

## Обязательно

| Пункт | Действие |
|--------|----------|
| **Секреты** | `TELEGRAM_BOT_TOKEN`, `MAX_BOT_TOKEN`, `YOOKASSA_SECRET_KEY` только в `.env` на сервере; не коммитить. При утечке — перевыпустить в BotFather / MAX / ЮKassa. |
| **ЮKassa** | Боевые `YOOKASSA_SHOP_ID` и секрет **без** префикса `test_`. Webhook URL в личном кабинете ЮKassa совпадает с HTTPS. |
| **Webhook за nginx** | В `.env`: `WEBHOOK_TRUST_PROXY=true`, в nginx — `X-Real-IP` / `X-Forwarded-For` (см. `ИНСТРУКЦИЯ_WEBHOOK_ЮKASSA.md`). Порт webhook **не** открывать наружу без прокси. |
| **Возврат после оплаты** | `TELEGRAM_BOT_USERNAME`, `MAX_BOT_USERNAME` заданы → корректный `return_url` в ЮKassa. |
| **БД и миграции** | Актуальная схема, `subscription_settings` с нужными ценами и `event_motorcade_limit_per_month`. |
| **Health** | `GET /health` для мониторинга (200 / 503 при падении БД). |
| **Тесты** | `pytest tests/` — все зелёные перед выкладкой. |

---

## Рекомендуется

- Резервное копирование PostgreSQL.
- Логи контейнера / systemd с ротацией.
- Ограничить доступ к Redis и Postgres только с хоста приложения.

---

## Известные ограничения ТЗ

- **CRUD городов** в админке — по сути один город через `ensure_cities`; расширение — отдельная задача.
- **Платежи MAX** — редирект на ЮKassa (веб), не нативный платёж MAX.

---

## UI / UX

- **Единый текст «нужна подписка»** — реализовано: `src/services/subscription_messages.py` (`subscription_required_message`, `max_profile_subscription_block`). Используется в Telegram (`motopair`, `start`, `events`, `profile`) и MAX (`handle_motopair_*`, `handle_events_*`, оплата/создание мероприятий). Лимит мотопробегов везде из БД.
- В MAX для списка анкет добавлена проверка подписки (паритет с Telegram).
- **Админка** — при `limit=0` тексты показывают «без бесплатных в месяц».

---

## Последние правки (аудит кода)

- `max_return_url`: формат `https://max.ru/{username}` (как в официальной ссылке на бота).
- Лимит мотопробегов в текстах подписки (Telegram профиль, MAX) берётся из `subscription_settings`.
- `WEBHOOK_TRUST_PROXY` + `X-Real-IP` для проверки IP ЮKassa за reverse-proxy.
