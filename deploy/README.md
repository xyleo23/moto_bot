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
