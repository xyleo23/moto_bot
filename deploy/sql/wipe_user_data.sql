-- Очистка пользовательских и связанных данных перед боевым запуском.
-- Сохраняются: cities, subscription_settings, bot_settings, global_texts (шаблоны).
-- Выполнять на сервере: см. комментарий внизу.

BEGIN;

TRUNCATE TABLE users CASCADE;

COMMIT;

-- Проверка: SELECT COUNT(*) FROM users;  → 0
--
-- Docker (prod compose из корня репозитория):
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -U postgres -d moto_bot -f - < deploy/sql/wipe_user_data.sql
--
-- Локально (psql в PATH):
--   psql "$DATABASE_URL" -f deploy/sql/wipe_user_data.sql
--   (для asyncpg URL замени схему на postgresql://)
