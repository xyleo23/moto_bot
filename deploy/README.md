# Деплой на VPS

## Ручной деплой (Docker)

```bash
cd /opt/moto_bot
git pull origin main
docker compose -f docker-compose.prod.yml build bot --no-cache
docker compose -f docker-compose.prod.yml up -d
```

Или через скрипт:

```bash
./deploy/deploy.sh
```

Миграции выполняются автоматически при старте контейнера (`run.py`).

---

## Первоначальная настройка

1. Клонировать, создать `.env`:
   ```bash
   cd /opt
   git clone https://github.com/xyleo23/moto_bot.git
   cd moto_bot
   cp .env.example .env
   nano .env  # TELEGRAM_BOT_TOKEN, POSTGRES_PASSWORD, SUPERADMIN_IDS
   ```

2. Запустить:
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

---

## Бот не реагирует на /start

Частая причина: **установлен webhook** — тогда Telegram отправляет обновления на URL, а не в polling.

Проверка на VPS:
```bash
cd /opt/moto_bot
source .env 2>/dev/null || true
export TELEGRAM_BOT_TOKEN  # или подставь токен вручную
./deploy/check-telegram.sh
docker compose -f docker-compose.prod.yml restart bot
```

Или вручную:
```bash
# Проверить webhook
curl "https://api.telegram.org/bot<ТОКЕН>/getWebhookInfo"

# Снять webhook (если url непустой)
curl "https://api.telegram.org/bot<ТОКЕН>/deleteWebhook?drop_pending_updates=true"
```

---

## Автодеплой через GitHub Actions

Репозиторий → **Settings** → **Secrets** → добавить `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`.

Workflow при push в `main` выполняет `deploy.sh` (Docker).

---

## Боевой ЮKassa и чистая база перед запуском

1. **Секреты только на сервере** в `.env` (не в git): `YOOKASSA_SHOP_ID` и `YOOKASSA_SECRET_KEY` из **боевого** магазина ЮKassa; ключ обычно с префиксом `live_`. `shop_id` у боевого магазина часто **другой**, чем у тестового — проверь в кабинете.

2. **Webhook** в ЮKassa: URL вида `https://<твой-домен>/webhook/yookassa`, порт приложения (8080) проксируй через nginx. Если бот за reverse proxy — в `.env` задай `WEBHOOK_TRUST_PROXY=true`.

3. **Очистка тестовых пользователей и связанных данных** (города, `subscription_settings`, `bot_settings`, шаблоны в `global_texts` не трогаются).

   Надёжнее всего — скрипт (одна команда `TRUNCATE`, без редиректа файла в контейнер):
   ```bash
   cd /opt/moto_bot
   chmod +x deploy/wipe_user_data.sh
   ./deploy/wipe_user_data.sh
   ```

   Если скрипт недоступен, вручную:
   ```bash
   cd /opt/moto_bot
   docker compose -f docker-compose.prod.yml exec -T postgres \
     psql -v ON_ERROR_STOP=1 -U postgres -d moto_bot \
     -c "TRUNCATE TABLE users CASCADE;"
   ```

   Проверка: `SELECT COUNT(*) FROM users;` должно вернуть `0`. Если не очищается — часто запускали не тот compose/не ту БД (другой `POSTGRES_DB` или контейнер без этого volume).

   Старый вариант через файл (на части окружений `-f -` с `<` не подхватывается):
   `cat deploy/sql/wipe_user_data.sql | docker compose -f docker-compose.prod.yml exec -T postgres psql -U postgres -d moto_bot -f -`

   **Если «как будто не очистилось»:**
   - Запусти **`./deploy/wipe_user_data.sh`** (он по умолчанию делает `stop bot` → `TRUNCATE` → `up -d bot`). Пока бот держит пул соединений, `TRUNCATE` может **ждать** или ты мог прервать команду.
   - Убедись, что чистишь **ту же БД**, куда ходит бот: `docker compose -f docker-compose.prod.yml exec postgres psql -U postgres -d moto_bot -c "SELECT COUNT(*) FROM users;"` — число до и после.
   - Другой compose / имя сервиса: `POSTGRES_SERVICE=db POSTGRES_DB=mydb ./deploy/wipe_user_data.sh`
   - Бот **не** в Docker, Postgres в Docker — подключись к хосту/порту с тем же именем БД, что в `DATABASE_URL`, и выполни `TRUNCATE TABLE users CASCADE;` оттуда.

4. **Redis** (сброс FSM и кэшей после тестов):
   ```bash
   docker compose -f docker-compose.prod.yml exec redis redis-cli FLUSHDB
   ```

5. **Перезапуск**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
