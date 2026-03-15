# Источник цен: БД vs env

**Политика:** БД (`subscription_settings`) — основной источник. Переменные окружения (`.env`) — fallback при пустых значениях в БД.

| Параметр | БД | env | Использование |
|----------|-----|-----|---------------|
| Цена подписки (месяц) | `monthly_price_kopecks` | `SUBSCRIPTION_MONTHLY_PRICE` | `cb_subscribe`, `cb_profile_subscribe` |
| Цена подписки (сезон) | `season_price_kopecks` | `SUBSCRIPTION_SEASON_PRICE` | `cb_subscribe`, `cb_profile_subscribe` |
| Цена создания мероприятия | `event_creation_price_kopecks` | `EVENT_CREATION_PRICE` | `event_creation_payment_required` |
| Цена поднятия анкеты | `raise_profile_price_kopecks` | `RAISE_PROFILE_PRICE` | `cb_profile_raise` |

**Реализация:** В коде при получении цены проверяется `settings_db.field`; если задано — используется, иначе — `get_settings().field`.
