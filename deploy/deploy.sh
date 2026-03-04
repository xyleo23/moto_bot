#!/bin/bash
# Деплой на VPS (Docker)
set -e

PROJECT_DIR="${1:-/opt/moto_bot}"
cd "$PROJECT_DIR"

echo "Pulling from GitHub..."
git pull origin main

echo "Clearing Telegram webhook (polling required)..."
./deploy/check-telegram.sh 2>/dev/null || true

echo "Building and starting..."
docker compose -f docker-compose.prod.yml build bot --no-cache
docker compose -f docker-compose.prod.yml up -d

echo "Done."
