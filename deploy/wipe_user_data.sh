#!/usr/bin/env bash
# Очистка пользователей и всех связанных данных (TRUNCATE users CASCADE).
# Запускать на сервере из корня репозитория: ./deploy/wipe_user_data.sh
#
# Переменные окружения (опционально):
#   COMPOSE_FILE       — файл compose (по умолчанию docker-compose.prod.yml)
#   POSTGRES_SERVICE   — имя сервиса Postgres в compose (по умолчанию postgres)
#   POSTGRES_DB        — имя БД внутри контейнера (по умолчанию moto_bot)
#   POSTGRES_USER      — пользователь Postgres (по умолчанию postgres)
#   STOP_BOT_FIRST=1   — перед TRUNCATE остановить сервис bot (снимает блокировки)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-moto_bot}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
STOP_BOT_FIRST="${STOP_BOT_FIRST:-1}"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Файл не найден: $ROOT/$COMPOSE_FILE" >&2
  echo "Задай путь: COMPOSE_FILE=docker-compose.yml ./deploy/wipe_user_data.sh" >&2
  exit 1
fi

dc() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

psql_in_pg() {
  dc exec -T "$POSTGRES_SERVICE" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

echo "=== Проект: $ROOT, compose: $COMPOSE_FILE ==="
echo "=== Сервис Postgres: $POSTGRES_SERVICE, БД: $POSTGRES_DB ==="
dc ps

if ! dc exec -T "$POSTGRES_SERVICE" true 2>/dev/null; then
  echo "Ошибка: контейнер сервиса «$POSTGRES_SERVICE» недоступен. Проверь: docker compose -f $COMPOSE_FILE ps" >&2
  exit 1
fi

if [[ "${STOP_BOT_FIRST}" == "1" ]]; then
  echo "=== Останавливаю сервис bot (чтобы снять блокировки с users) ==="
  dc stop bot 2>/dev/null || true
fi

echo "=== Пользователей до: ==="
psql_in_pg -t -A -c "SELECT COUNT(*) FROM users;" || {
  echo "Не удалось выполнить SELECT. Есть ли таблица users? Команда проверки:" >&2
  echo "  docker compose -f $COMPOSE_FILE exec $POSTGRES_SERVICE psql -U $POSTGRES_USER -d $POSTGRES_DB -c '\\dt'" >&2
  exit 1
}

echo "=== TRUNCATE TABLE users CASCADE ==="
psql_in_pg -c "TRUNCATE TABLE users CASCADE;"

echo "=== Пользователей после: ==="
AFTER="$(psql_in_pg -t -A -c "SELECT COUNT(*) FROM users;")"
echo "$AFTER"
if [[ "${AFTER}" != "0" ]]; then
  echo "Внимание: ожидалось 0 пользователей. Возможно, это не та БД или TRUNCATE не отработал." >&2
  exit 1
fi

if [[ "${STOP_BOT_FIRST}" == "1" ]]; then
  echo "=== Запускаю bot снова ==="
  dc up -d bot
fi

echo "=== Готово. Рекомендуется: docker compose -f $COMPOSE_FILE exec redis redis-cli FLUSHDB ==="
