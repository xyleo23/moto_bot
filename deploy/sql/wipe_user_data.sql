-- Очистка пользовательских и связанных данных перед боевым запуском.
-- Сохраняются: cities, subscription_settings, bot_settings, global_texts (шаблоны).
-- Выполнять на сервере: см. комментарий внизу.

BEGIN;

TRUNCATE TABLE users CASCADE;

COMMIT;

-- Проверка: SELECT COUNT(*) FROM users;  → 0
--
-- Надёжно (без редиректа файла в stdin — на части хостов он не доходит до psql в контейнере):
--   ./deploy/wipe_user_data.sh
-- или одной строкой:
--   docker compose -f docker-compose.prod.yml stop bot
--   docker compose -f docker-compose.prod.yml exec -T postgres \
--     psql -v ON_ERROR_STOP=1 -U postgres -d moto_bot -c "TRUNCATE TABLE users CASCADE;"
--   docker compose -f docker-compose.prod.yml up -d bot
--
-- Локально (psql в PATH):
--   psql "$DATABASE_URL" -f deploy/sql/wipe_user_data.sql
--   (для asyncpg URL замени схему на postgresql://)
