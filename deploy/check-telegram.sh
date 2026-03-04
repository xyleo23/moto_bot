#!/bin/bash
# Диагностика Telegram бота на VPS
# Запускать из корня проекта: ./deploy/check-telegram.sh
# Или: TELEGRAM_BOT_TOKEN=xxx ./deploy/check-telegram.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && [ -f .env ]; then
  TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2- | tr -d '"' | tr -d "'")
  export TELEGRAM_BOT_TOKEN
fi
TOKEN="${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN or add to .env}"

echo "=== getWebhookInfo ==="
curl -s "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python3 -m json.tool

echo ""
echo "=== deleteWebhook (для переключения на polling) ==="
curl -s "https://api.telegram.org/bot${TOKEN}/deleteWebhook?drop_pending_updates=true" | python3 -m json.tool

echo ""
echo "Готово. Если url был непустой — webhook снят. Перезапусти бота:"
echo "  docker compose -f docker-compose.prod.yml restart bot"
